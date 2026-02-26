from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from app.models import UserCreationResult
from app.services.glpi_service import GLPIService


@pytest.fixture
def success_result() -> UserCreationResult:
    return UserCreationResult(
        success=True,
        ticket_id=100,
        sam_account_name="rsilva",
        user_principal_name="rsilva@test.local",
        display_name="Rafael Silva",
        temporary_password="TempPass123!",
        distinguished_name="CN=Rafael Silva,OU=Usuarios,DC=test,DC=local",
        message="Usuario criado com sucesso",
        groups_added=["CN=GRP-TI,OU=Grupos,DC=test,DC=local"],
    )


@pytest.fixture
def error_result() -> UserCreationResult:
    return UserCreationResult(
        success=False,
        ticket_id=101,
        message="Falha na conexao com AD",
        errors=["Connection refused", "Timeout"],
    )


class TestBuildFollowupContent:
    def test_success_content_has_credentials(self, success_result):
        content = GLPIService._build_followup_content(success_result)

        assert "rsilva" in content
        assert "rsilva@test.local" in content
        assert "TempPass123!" in content
        assert "Rafael Silva" in content
        assert "GRP-TI" in content
        assert "sucesso" in content.lower()

    def test_error_content_has_details(self, error_result):
        content = GLPIService._build_followup_content(error_result)

        assert "ERRO" in content
        assert "Connection refused" in content
        assert "Timeout" in content
        assert "manualmente" in content.lower()

    def test_success_without_groups(self):
        result = UserCreationResult(
            success=True,
            ticket_id=1,
            sam_account_name="test",
            message="ok",
        )
        content = GLPIService._build_followup_content(result)
        assert "Grupos" not in content


class TestUpdateTicket:
    @pytest.mark.asyncio
    async def test_update_ticket_success_resolves(self, success_result):
        """Chamado deve ser resolvido (status 5) quando usuario criado com sucesso."""
        with patch("app.services.glpi_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                glpi_url="https://glpi.test",
                glpi_api_token="token",
                glpi_app_token="app-token",
                glpi_verify_ssl=False,
            )

            service = GLPIService()

            mock_response = MagicMock()
            mock_response.json.return_value = {"session_token": "sess-123"}
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.put = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                await service.update_ticket(success_result)

                # Verifica que PUT foi chamado com status 5 (Resolvido)
                put_call = mock_client.put.call_args
                assert put_call.kwargs["json"]["input"]["status"] == 5

    @pytest.mark.asyncio
    async def test_update_ticket_error_sets_pending(self, error_result):
        """Chamado deve ficar pendente (status 4) quando ha erro."""
        with patch("app.services.glpi_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                glpi_url="https://glpi.test",
                glpi_api_token="token",
                glpi_app_token="app-token",
                glpi_verify_ssl=False,
            )

            service = GLPIService()

            mock_response = MagicMock()
            mock_response.json.return_value = {"session_token": "sess-123"}
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.put = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                await service.update_ticket(error_result)

                put_call = mock_client.put.call_args
                assert put_call.kwargs["json"]["input"]["status"] == 4
