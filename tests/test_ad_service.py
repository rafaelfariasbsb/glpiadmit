from unittest.mock import patch, MagicMock

import pytest
from ldap3.core.exceptions import LDAPException

from app.models import UserCreationPayload
from app.services.ad_service import ADService, UAC_DISABLED_ACCOUNT


class TestADServiceCreateUser:
    def _make_service(self, mock_connection: MagicMock) -> ADService:
        """Cria ADService com factory de conexao mockada."""
        return ADService(connection_factory=lambda: mock_connection)

    def test_create_user_success(self, sample_payload, mock_ldap_connection):
        service = self._make_service(mock_ldap_connection)
        result = service.create_user(sample_payload)

        assert result.success is True
        assert result.sam_account_name == "rsilva"
        assert "rsilva@" in result.user_principal_name
        assert result.display_name == "Rafael Silva"
        assert result.ticket_id == 123
        assert result.temporary_password != ""

        # Verificar que o usuario foi criado
        mock_ldap_connection.add.assert_called_once()
        add_kwargs = mock_ldap_connection.add.call_args
        attrs = add_kwargs.kwargs.get("attributes") or add_kwargs[0][2] if len(add_kwargs[0]) > 2 else add_kwargs.kwargs["attributes"]
        assert attrs["sAMAccountName"] == "rsilva"
        assert attrs["userAccountControl"] == UAC_DISABLED_ACCOUNT

    def test_create_user_sets_password_and_enables(self, sample_payload, mock_ldap_connection):
        service = self._make_service(mock_ldap_connection)
        result = service.create_user(sample_payload)

        assert result.success is True
        # modify chamado 3x: senha, pwdLastSet, userAccountControl
        assert mock_ldap_connection.modify.call_count == 3

    def test_create_user_adds_to_groups(self, sample_payload, mock_ldap_connection):
        service = self._make_service(mock_ldap_connection)
        result = service.create_user(sample_payload)

        assert result.success is True
        mock_ldap_connection.extend.microsoft.add_members_to_groups.assert_called_once()

    def test_create_user_without_groups(self, sample_payload_minimal, mock_ldap_connection):
        service = self._make_service(mock_ldap_connection)
        result = service.create_user(sample_payload_minimal)

        assert result.success is True
        mock_ldap_connection.extend.microsoft.add_members_to_groups.assert_not_called()

    def test_create_user_duplicate(self, sample_payload, mock_ldap_connection):
        mock_ldap_connection.entries = [MagicMock()]  # Simula usuario existente

        service = self._make_service(mock_ldap_connection)
        result = service.create_user(sample_payload)

        assert result.success is False
        assert "ja existe" in result.message
        mock_ldap_connection.add.assert_not_called()

    def test_create_user_connection_failure(self, sample_payload):
        def failing_factory():
            raise LDAPException("Connection refused")

        service = ADService(connection_factory=failing_factory)
        result = service.create_user(sample_payload)

        assert result.success is False
        assert "conexao" in result.message.lower()

    def test_create_user_ldap_error_triggers_rollback(self, sample_payload, mock_ldap_connection):
        # Falha ao definir senha (apos criacao)
        call_count = 0

        def modify_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # Primeira chamada a modify (set_password)
                raise LDAPException("Password policy violation")

        mock_ldap_connection.modify.side_effect = modify_side_effect

        service = self._make_service(mock_ldap_connection)
        result = service.create_user(sample_payload)

        assert result.success is False
        # Rollback deve ter tentado deletar o usuario
        mock_ldap_connection.delete.assert_called_once()

    def test_create_user_unbinds_connection(self, sample_payload, mock_ldap_connection):
        service = self._make_service(mock_ldap_connection)
        service.create_user(sample_payload)

        mock_ldap_connection.unbind.assert_called_once()

    def test_create_user_unbinds_even_on_error(self, sample_payload, mock_ldap_connection):
        mock_ldap_connection.entries = [MagicMock()]  # Duplicata

        service = self._make_service(mock_ldap_connection)
        service.create_user(sample_payload)

        mock_ldap_connection.unbind.assert_called_once()

    def test_create_user_invalid_name_rejected_by_pydantic(self):
        """Pydantic rejeita first_name vazio (apenas espacos) na validacao do modelo."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="first_name"):
            UserCreationPayload(
                ticket_id=999,
                first_name="   ",
                last_name="Silva",
                email="x@empresa.com",
                department="TI",
                title="Dev",
            )
