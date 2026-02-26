from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from app.models import UserCreationResult
from app.services.glpi_service import GLPIService, TicketStatus


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


class TestParseTicketContent:
    def test_valid_form_content_returns_payload(self):
        item = {
            "id": 42,
            "content": (
                "<b>1) Nome</b>: Rafael<br>"
                "<b>2) Sobrenome</b>: Silva<br>"
                "<b>3) E-mail corporativo</b>: rafael.silva@empresa.com<br>"
                "<b>4) Departamento</b>: TI<br>"
                "<b>5) Cargo</b>: Analista<br>"
                "<b>6) Grupo AD</b>: CN=GRP-TI,OU=Grupos,DC=empresa,DC=local<br>"
            ),
        }
        payload = GLPIService.parse_ticket_content(item)

        assert payload is not None
        assert payload.ticket_id == 42
        assert payload.first_name == "Rafael"
        assert payload.last_name == "Silva"
        assert payload.email == "rafael.silva@empresa.com"
        assert payload.department == "TI"
        assert payload.title == "Analista"
        assert payload.groups == ["CN=GRP-TI,OU=Grupos,DC=empresa,DC=local"]

    def test_form_without_group_returns_empty_groups(self):
        item = {
            "id": 43,
            "content": (
                "<b>1) Nome</b>: Maria<br>"
                "<b>2) Sobrenome</b>: Santos<br>"
                "<b>3) E-mail corporativo</b>: maria@empresa.com<br>"
                "<b>4) Departamento</b>: RH<br>"
                "<b>5) Cargo</b>: Analista<br>"
                "<b>6) Grupo AD</b>: <br>"
            ),
        }
        payload = GLPIService.parse_ticket_content(item)

        assert payload is not None
        assert payload.groups == []

    def test_non_form_ticket_returns_none(self):
        item = {
            "id": 99,
            "content": "Preciso de suporte tecnico com meu computador.",
        }
        assert GLPIService.parse_ticket_content(item) is None

    def test_missing_required_field_returns_none(self):
        # Sem "E-mail corporativo"
        item = {
            "id": 100,
            "content": (
                "<b>1) Nome</b>: Rafael<br>"
                "<b>2) Sobrenome</b>: Silva<br>"
            ),
        }
        assert GLPIService.parse_ticket_content(item) is None

    def test_empty_content_returns_none(self):
        assert GLPIService.parse_ticket_content({"id": 1, "content": ""}) is None

    def test_missing_ticket_id_returns_none(self):
        assert GLPIService.parse_ticket_content({"content": "<b>1) Nome</b>: X<br>"}) is None

    def test_case_insensitive_labels(self):
        item = {
            "id": 50,
            "content": (
                "<B>1) NOME</B>: Pedro<br>"
                "<B>2) SOBRENOME</B>: Costa<br>"
                "<B>3) E-MAIL CORPORATIVO</B>: pedro@empresa.com<br>"
                "<B>4) DEPARTAMENTO</B>: TI<br>"
                "<B>5) CARGO</B>: Dev<br>"
            ),
        }
        payload = GLPIService.parse_ticket_content(item)
        assert payload is not None
        assert payload.first_name == "Pedro"


class TestTicketStatus:
    def test_solved_equals_5(self):
        assert TicketStatus.SOLVED == 5

    def test_pending_equals_4(self):
        assert TicketStatus.PENDING == 4

    def test_is_int(self):
        assert isinstance(TicketStatus.SOLVED, int)
        assert isinstance(TicketStatus.PENDING, int)


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
