import logging
import ssl
from dataclasses import dataclass, field

from ldap3 import Connection, Server, SUBTREE, MODIFY_REPLACE, Tls
from ldap3.core.exceptions import LDAPException
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

from app.config import get_settings
from app.models import UserCreationPayload, UserCreationResult
from app.utils.password import generate_temporary_password
from app.utils.validators import (
    generate_sam_account_name,
    generate_upn,
    generate_display_name,
    generate_cn,
    sanitize_dn_component,
    sanitize_ldap_value,
)

logger = logging.getLogger(__name__)

# userAccountControl flags
UAC_NORMAL_ACCOUNT = 512
UAC_DISABLED_ACCOUNT = 514


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(LDAPException),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _build_connection() -> Connection:
    """Cria conexao LDAPS com o AD. Tenta ate 3 vezes com backoff exponencial."""
    settings = get_settings()
    tls_config = Tls(
        validate=ssl.CERT_REQUIRED if (settings.ad_use_ssl and settings.ad_verify_cert) else ssl.CERT_NONE,
    )
    server = Server(
        settings.ad_server,
        use_ssl=settings.ad_use_ssl,
        tls=tls_config,
        get_info="ALL",
    )
    return Connection(
        server,
        user=settings.ad_bind_user,
        password=settings.ad_bind_password,
        auto_bind=True,
        raise_exceptions=True,
    )


@dataclass
class _UserAttributes:
    """Atributos gerados para criacao do usuario no AD."""

    sam_account_name: str
    upn: str
    display_name: str
    cn: str
    dn: str
    temp_password: str


def _generate_attributes(payload: UserCreationPayload) -> _UserAttributes:
    """Gera todos os atributos derivados do payload."""
    settings = get_settings()
    sam = generate_sam_account_name(payload.first_name, payload.last_name)
    cn = generate_cn(payload.first_name, payload.last_name)
    safe_cn = sanitize_dn_component(cn)

    return _UserAttributes(
        sam_account_name=sam,
        upn=generate_upn(sam, settings.ad_domain),
        display_name=generate_display_name(payload.first_name, payload.last_name),
        cn=cn,
        dn=f"CN={safe_cn},{settings.ad_user_ou}",
        temp_password=generate_temporary_password(),
    )


class ADService:
    """Servico para criacao de usuarios no Active Directory via LDAPS."""

    def __init__(self, connection_factory=_build_connection):
        self._connection_factory = connection_factory

    def _check_user_exists(self, conn: Connection, sam: str, upn: str) -> bool:
        """Verifica se ja existe usuario com mesmo sAMAccountName ou UPN."""
        safe_sam = sanitize_ldap_value(sam)
        safe_upn = sanitize_ldap_value(upn)

        conn.search(
            search_base=get_settings().ad_base_dn,
            search_filter=f"(|(sAMAccountName={safe_sam})(userPrincipalName={safe_upn}))",
            search_scope=SUBTREE,
            attributes=["sAMAccountName"],
        )
        return len(conn.entries) > 0

    def _set_password(self, conn: Connection, user_dn: str, password: str) -> None:
        """Define a senha do usuario via unicodePwd (requer LDAPS)."""
        encoded_password = f'"{password}"'.encode("utf-16-le")
        conn.modify(user_dn, {"unicodePwd": [(MODIFY_REPLACE, [encoded_password])]})

    def _configure_account(self, conn: Connection, user_dn: str, password: str) -> None:
        """Define senha, forca troca no proximo login e habilita a conta."""
        self._set_password(conn, user_dn, password)
        conn.modify(user_dn, {"pwdLastSet": [(MODIFY_REPLACE, [0])]})
        conn.modify(user_dn, {"userAccountControl": [(MODIFY_REPLACE, [UAC_NORMAL_ACCOUNT])]})

    def _add_to_groups(self, conn: Connection, user_dn: str, groups: list[str]) -> list[str]:
        """Adiciona o usuario aos grupos AD. Retorna lista dos grupos adicionados."""
        added: list[str] = []
        for group_dn in groups:
            try:
                conn.extend.microsoft.add_members_to_groups([user_dn], [group_dn])
                added.append(group_dn)
            except LDAPException as e:
                logger.warning("Falha ao adicionar ao grupo %s: %s", group_dn, e)
        return added

    def _rollback_user(self, conn: Connection, user_dn: str) -> None:
        """Rollback: tenta remover o usuario criado em caso de erro."""
        try:
            conn.delete(user_dn)
            logger.warning("Rollback: usuario %s removido do AD", user_dn)
        except LDAPException as e:
            logger.error("Falha no rollback do usuario %s: %s", user_dn, e)

    def _create_ad_object(
        self, conn: Connection, attrs: _UserAttributes, payload: UserCreationPayload
    ) -> None:
        """Cria o objeto usuario no AD com conta desabilitada."""
        settings = get_settings()
        ad_attributes = {
            "sAMAccountName": attrs.sam_account_name,
            "userPrincipalName": attrs.upn,
            "givenName": payload.first_name.strip(),
            "sn": payload.last_name.strip(),
            "displayName": attrs.display_name,
            "mail": payload.email,
            "department": payload.department.strip(),
            "title": payload.title.strip(),
            "company": settings.ad_default_company,
            "userAccountControl": UAC_DISABLED_ACCOUNT,
        }

        if payload.phone:
            ad_attributes["telephoneNumber"] = payload.phone
        if payload.manager:
            ad_attributes["manager"] = payload.manager

        conn.add(
            attrs.dn,
            object_class=["top", "person", "organizationalPerson", "user"],
            attributes=ad_attributes,
        )

    def create_user(self, payload: UserCreationPayload) -> UserCreationResult:
        """Cria um usuario no Active Directory a partir dos dados do chamado GLPI.

        Fluxo:
        1. Gerar atributos (sAMAccountName, UPN, CN, etc.)
        2. Verificar duplicidade
        3. Criar usuario desabilitado
        4. Definir senha + forcar troca + habilitar conta
        5. Adicionar a grupos
        """
        result = UserCreationResult(success=False, ticket_id=payload.ticket_id)

        # 1. Gerar atributos
        try:
            attrs = _generate_attributes(payload)
        except ValueError as e:
            result.message = f"Erro de validacao: {e}"
            result.errors.append(str(e))
            logger.error(result.message)
            return result

        result.sam_account_name = attrs.sam_account_name
        result.user_principal_name = attrs.upn
        result.display_name = attrs.display_name
        result.distinguished_name = attrs.dn
        result.temporary_password = attrs.temp_password

        # 2-5. Operacoes no AD
        try:
            conn = self._connection_factory()
        except LDAPException as e:
            result.message = f"Falha na conexao com AD: {e}"
            result.errors.append(str(e))
            logger.error(result.message)
            return result

        user_created = False
        try:
            logger.info(
                "Criando usuario: sAM=%s, UPN=%s, DN=%s (ticket #%d)",
                attrs.sam_account_name, attrs.upn, attrs.dn, payload.ticket_id,
            )

            # 2. Verificar duplicidade
            if self._check_user_exists(conn, attrs.sam_account_name, attrs.upn):
                result.message = f"Usuario ja existe no AD: {attrs.sam_account_name} ou {attrs.upn}"
                result.errors.append(result.message)
                logger.warning(result.message)
                return result

            # 3. Criar usuario (desabilitado)
            self._create_ad_object(conn, attrs, payload)
            user_created = True
            logger.info("Usuario criado (desabilitado): %s", attrs.dn)

            # 4. Configurar conta (senha + troca obrigatoria + habilitar)
            self._configure_account(conn, attrs.dn, attrs.temp_password)
            logger.info("Conta configurada e habilitada: %s", attrs.dn)

            # 5. Adicionar a grupos
            if payload.groups:
                result.groups_added = self._add_to_groups(conn, attrs.dn, payload.groups)

            result.success = True
            result.message = (
                f"Usuario {attrs.display_name} ({attrs.sam_account_name}) criado com sucesso no AD. "
                f"Senha temporaria gerada. Troca obrigatoria no primeiro login."
            )
            logger.info("Usuario criado com sucesso: %s (ticket #%d)", attrs.sam_account_name, payload.ticket_id)

        except LDAPException as e:
            result.message = f"Erro ao criar usuario no AD: {e}"
            result.errors.append(str(e))
            logger.error(result.message, exc_info=True)

            if user_created:
                self._rollback_user(conn, attrs.dn)

        finally:
            try:
                conn.unbind()
            except Exception:
                pass

        return result
