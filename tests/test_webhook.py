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


class TestHealthCheck:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "glpi-ad-integration"
