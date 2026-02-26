import hashlib
import hmac
import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.models import UserCreationResult


@pytest.fixture
def valid_payload_dict():
    return {
        "ticket_id": 456,
        "first_name": "Maria",
        "last_name": "Santos",
        "email": "maria.santos@empresa.com",
        "department": "RH",
        "title": "Analista de RH",
        "phone": "(11) 98888-0000",
        "manager": "",
        "groups": [],
    }


def _generate_signature(payload: dict, secret: str) -> str:
    body = json.dumps(payload).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestWebhookEndpoint:
    @patch("app.routes.webhook.GLPIService")
    @patch("app.routes.webhook.ADService")
    def test_successful_creation(self, mock_ad_cls, mock_glpi_cls, client, valid_payload_dict):
        mock_ad = MagicMock()
        mock_ad.create_user.return_value = UserCreationResult(
            success=True,
            ticket_id=456,
            sam_account_name="msantos",
            user_principal_name="msantos@test.local",
            display_name="Maria Santos",
            temporary_password="TempPass123!",
            distinguished_name="CN=Maria Santos,OU=Usuarios,DC=test,DC=local",
            message="Usuario criado com sucesso",
        )
        mock_ad_cls.return_value = mock_ad

        mock_glpi = MagicMock()
        mock_glpi.update_ticket = AsyncMock()
        mock_glpi_cls.return_value = mock_glpi

        response = client.post("/webhook/user-creation", json=valid_payload_dict)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["ticket_id"] == 456

    @patch("app.routes.webhook.GLPIService")
    @patch("app.routes.webhook.ADService")
    def test_failed_creation_returns_error(self, mock_ad_cls, mock_glpi_cls, client, valid_payload_dict):
        mock_ad = MagicMock()
        mock_ad.create_user.return_value = UserCreationResult(
            success=False,
            ticket_id=456,
            message="Usuario ja existe no AD",
            errors=["Duplicata detectada"],
        )
        mock_ad_cls.return_value = mock_ad

        mock_glpi = MagicMock()
        mock_glpi.update_ticket = AsyncMock()
        mock_glpi_cls.return_value = mock_glpi

        response = client.post("/webhook/user-creation", json=valid_payload_dict)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"

    def test_invalid_payload_returns_422(self, client):
        response = client.post("/webhook/user-creation", json={"invalid": "data"})
        assert response.status_code == 422

    def test_missing_required_fields_returns_422(self, client):
        response = client.post(
            "/webhook/user-creation",
            json={"ticket_id": 1, "first_name": "Test"},
        )
        assert response.status_code == 422

    def test_invalid_signature_returns_401(self, client, test_settings, valid_payload_dict):
        test_settings.webhook_secret = "my-secret-key"

        response = client.post(
            "/webhook/user-creation",
            json=valid_payload_dict,
            headers={"X-GLPI-Signature": "invalid-signature"},
        )
        assert response.status_code == 401

    @patch("app.routes.webhook.GLPIService")
    @patch("app.routes.webhook.ADService")
    def test_glpi_service_called_after_ad(self, mock_ad_cls, mock_glpi_cls, client, valid_payload_dict):
        mock_ad = MagicMock()
        mock_ad.create_user.return_value = UserCreationResult(
            success=True,
            ticket_id=456,
            message="ok",
        )
        mock_ad_cls.return_value = mock_ad

        mock_glpi = MagicMock()
        mock_glpi.update_ticket = AsyncMock()
        mock_glpi_cls.return_value = mock_glpi

        client.post("/webhook/user-creation", json=valid_payload_dict)

        mock_glpi.update_ticket.assert_called_once()


def _make_glpi_native_body(ticket_id: int = 10) -> dict:
    return {
        "event": "new",
        "item": {
            "id": ticket_id,
            "name": "Solicitar Criacao de Usuario AD",
            "content": (
                f"<b>1) Nome</b>: Joao<br>"
                f"<b>2) Sobrenome</b>: Ferreira<br>"
                f"<b>3) E-mail corporativo</b>: joao.ferreira@empresa.com<br>"
                f"<b>4) Departamento</b>: TI<br>"
                f"<b>5) Cargo</b>: Analista<br>"
                f"<b>6) Grupo AD</b>: CN=GRP-TI,OU=Grupos,DC=empresa,DC=local<br>"
            ),
        },
    }


def _generate_glpi_native_signature(body: bytes, secret: str, timestamp: str) -> str:
    data = body + timestamp.encode()
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


class TestGlpiNativeEndpoint:
    @patch("app.routes.webhook.GLPIService")
    @patch("app.routes.webhook.ADService")
    def test_successful_creation(self, mock_ad_cls, mock_glpi_cls, client):
        mock_ad = MagicMock()
        mock_ad.create_user.return_value = UserCreationResult(
            success=True,
            ticket_id=10,
            sam_account_name="jferreira",
            message="Criado com sucesso",
        )
        mock_ad_cls.return_value = mock_ad
        mock_glpi = MagicMock()
        mock_glpi.update_ticket = AsyncMock()
        mock_glpi_cls.return_value = mock_glpi

        body_dict = _make_glpi_native_body(10)
        body_bytes = json.dumps(body_dict).encode()

        response = client.post(
            "/webhook/glpi-native",
            content=body_bytes,
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["ticket_id"] == 10

    def test_non_form_ticket_is_ignored(self, client):
        # Ticket com conteudo comum (nao originou de formulario de criacao de usuario)
        # Nao precisa de mock: parse_ticket_content retorna None e o endpoint retorna
        # "ignored" sem chamar ADService ou GLPIService.
        body_dict = {
            "event": "new",
            "item": {
                "id": 20,
                "content": "Preciso de suporte com impressora.",
            },
        }
        body_bytes = json.dumps(body_dict).encode()

        response = client.post(
            "/webhook/glpi-native",
            content=body_bytes,
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_missing_item_id_returns_422(self, client):
        body_dict = {"event": "new", "item": {}}
        response = client.post("/webhook/glpi-native", json=body_dict)
        assert response.status_code == 422

    def test_invalid_signature_returns_401(self, client, test_settings):
        test_settings.webhook_secret = "secret-key"
        body_dict = _make_glpi_native_body(30)

        response = client.post(
            "/webhook/glpi-native",
            json=body_dict,
            headers={
                "X-GLPI-signature": "assinatura-invalida",
                "X-GLPI-timestamp": "1700000000",
            },
        )
        assert response.status_code == 401

    def test_valid_glpi_signature_accepted(self, client, test_settings):
        test_settings.webhook_secret = "minha-chave-secreta"
        body_dict = _make_glpi_native_body(40)
        body_bytes = json.dumps(body_dict).encode()
        timestamp = "1700000000"
        sig = _generate_glpi_native_signature(body_bytes, "minha-chave-secreta", timestamp)

        with patch("app.routes.webhook.ADService") as mock_ad_cls, \
             patch("app.routes.webhook.GLPIService") as mock_glpi_cls:
            mock_ad = MagicMock()
            mock_ad.create_user.return_value = UserCreationResult(
                success=True, ticket_id=40, message="ok"
            )
            mock_ad_cls.return_value = mock_ad
            mock_glpi = MagicMock()
            mock_glpi.update_ticket = AsyncMock()
            mock_glpi_cls.return_value = mock_glpi

            response = client.post(
                "/webhook/glpi-native",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-GLPI-signature": sig,
                    "X-GLPI-timestamp": timestamp,
                },
            )

        assert response.status_code == 200

    def test_invalid_json_returns_400(self, client):
        response = client.post(
            "/webhook/glpi-native",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400


class TestHealthCheck:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "glpi-ad-integration"
