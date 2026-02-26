from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # GLPI
    glpi_url: str = "https://glpi.empresa.local"
    glpi_api_token: str = ""
    glpi_app_token: str = ""
    glpi_verify_ssl: bool = True

    # Active Directory
    ad_server: str = "ldaps://dc01.empresa.local"
    ad_domain: str = "empresa.local"
    ad_base_dn: str = "DC=empresa,DC=local"
    ad_user_ou: str = "OU=Usuarios,DC=empresa,DC=local"
    ad_bind_user: str = "CN=svc-glpi-ad,OU=ServiceAccounts,DC=empresa,DC=local"
    ad_bind_password: str = ""
    ad_default_company: str = "Empresa"
    ad_verify_cert: bool = True  # False apenas para testes com certificado auto-assinado

    # Webhook
    webhook_secret: str = ""

    # Logging
    log_level: str = "INFO"

    @property
    def ad_domain_suffix(self) -> str:
        return f"@{self.ad_domain}"

    @property
    def ad_use_ssl(self) -> bool:
        return self.ad_server.startswith("ldaps://")


@lru_cache
def get_settings() -> Settings:
    """Retorna instancia cacheada das configuracoes.

    Usar @lru_cache garante uma unica instancia (singleton).
    Em testes, chame get_settings.cache_clear() para resetar.
    """
    return Settings()
