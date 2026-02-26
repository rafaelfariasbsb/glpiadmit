from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.models import UserCreationPayload


def _get_test_settings() -> Settings:
    """Settings de teste com valores controlados."""
    return Settings(
        glpi_url="https://glpi.test.local",
        glpi_api_token="test-api-token",
        glpi_app_token="test-app-token",
        glpi_verify_ssl=False,
        ad_server="ldaps://dc01.test.local",
        ad_domain="test.local",
        ad_base_dn="DC=test,DC=local",
        ad_user_ou="OU=Usuarios,DC=test,DC=local",
        ad_bind_user="CN=svc-test,OU=ServiceAccounts,DC=test,DC=local",
        ad_bind_password="test-password",
        ad_default_company="TestCorp",
        webhook_secret="",
        log_level="DEBUG",
    )


@pytest.fixture
def test_settings():
    """Fornece settings de teste e faz override no FastAPI."""
    settings = _get_test_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client(test_settings):
    """TestClient do FastAPI com settings de teste."""
    return TestClient(app)


@pytest.fixture
def sample_payload() -> UserCreationPayload:
    """Payload de exemplo com todos os campos preenchidos."""
    return UserCreationPayload(
        ticket_id=123,
        first_name="Rafael",
        last_name="Silva",
        email="rafael.silva@empresa.com",
        department="TI",
        title="Analista de Sistemas",
        phone="(11) 99999-0000",
        manager="CN=Gestor,OU=Usuarios,DC=empresa,DC=local",
        groups=["CN=GRP-TI,OU=Grupos,DC=empresa,DC=local"],
    )


@pytest.fixture
def sample_payload_minimal() -> UserCreationPayload:
    """Payload minimo com apenas campos obrigatorios."""
    return UserCreationPayload(
        ticket_id=456,
        first_name="Maria",
        last_name="Santos",
        email="maria.santos@empresa.com",
        department="RH",
        title="Analista de RH",
    )


@pytest.fixture
def mock_ldap_connection():
    """Conexao ldap3 mockada com comportamento padrao de sucesso."""
    conn = MagicMock()
    conn.bound = True
    conn.entries = []
    conn.result = {"result": 0, "description": "success"}
    conn.extend.microsoft.add_members_to_groups = MagicMock()
    return conn
