import logging
import re
from enum import IntEnum

import httpx
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.models import UserCreationPayload, UserCreationResult

logger = logging.getLogger(__name__)


class TicketStatus(IntEnum):
    """Status ITIL do chamado no GLPI."""
    PENDING = 4   # Pendente (erro na criacao)
    SOLVED  = 5   # Resolvido (sucesso)


# Compilado uma unica vez no carregamento do modulo
_FORM_PATTERN = re.compile(
    r"<b>\d+\)\s*([^<]+)</b>\s*:\s*([^<]+)",
    re.IGNORECASE,
)


class GLPIService:
    """Servico para comunicacao com a API REST do GLPI."""

    def __init__(self):
        settings = get_settings()
        self._base_url = f"{settings.glpi_url}/apirest.php"
        self._app_token = settings.glpi_app_token
        self._api_token = settings.glpi_api_token
        self._verify_ssl = settings.glpi_verify_ssl
        self._session_token: str | None = None

    def _headers(self, with_session: bool = True) -> dict[str, str]:
        """Monta headers base para requests a API do GLPI."""
        h = {
            "Content-Type": "application/json",
            "App-Token": self._app_token,
        }
        if with_session and self._session_token:
            h["Session-Token"] = self._session_token
        return h

    async def _init_session(self, client: httpx.AsyncClient) -> str:
        """Inicia uma sessao na API do GLPI e ativa o perfil de maior privilegio disponivel."""
        headers = {
            **self._headers(with_session=False),
            "Authorization": f"user_token {self._api_token}",
        }
        response = await client.get(f"{self._base_url}/initSession", headers=headers)
        response.raise_for_status()
        self._session_token = response.json()["session_token"]

        # Tenta ativar o perfil de maior privilegio (Super-Admin > Admin > outros)
        profiles_resp = await client.get(f"{self._base_url}/getMyProfiles", headers=self._headers())
        if profiles_resp.status_code == 200:
            profiles = profiles_resp.json().get("myprofiles", [])
            priority = {"super-admin": 0, "admin": 1}
            best = min(
                profiles,
                key=lambda p: priority.get(p.get("name", "").lower(), 99),
                default=None,
            )
            if best and best.get("id"):
                await client.post(
                    f"{self._base_url}/changeActiveProfile",
                    headers=self._headers(),
                    json={"profiles_id": best["id"]},
                )
                logger.debug("Perfil GLPI ativado: %s (id=%d)", best.get("name"), best["id"])

        logger.info("Sessao GLPI iniciada")
        return self._session_token

    async def _kill_session(self, client: httpx.AsyncClient) -> None:
        """Encerra a sessao na API do GLPI."""
        if not self._session_token:
            return
        try:
            await client.get(f"{self._base_url}/killSession", headers=self._headers())
            logger.info("Sessao GLPI encerrada")
        except httpx.HTTPError as e:
            logger.warning("Erro ao encerrar sessao GLPI: %s", e)
        finally:
            self._session_token = None

    @staticmethod
    def _build_followup_content(result: UserCreationResult) -> str:
        """Monta o conteudo HTML do followup a ser adicionado no chamado."""
        if result.success:
            lines = [
                "<b>Usuario criado com sucesso no Active Directory</b>",
                "",
                f"<b>Login (sAMAccountName):</b> {result.sam_account_name}",
                f"<b>UPN:</b> {result.user_principal_name}",
                f"<b>Nome de exibicao:</b> {result.display_name}",
                f"<b>Senha temporaria:</b> {result.temporary_password}",
                f"<b>DN:</b> {result.distinguished_name}",
                "",
                "<i>O usuario deve trocar a senha no primeiro login.</i>",
                "<i>A sincronizacao com Azure AD/Entra ocorre em ate 30 minutos.</i>",
            ]
            if result.groups_added:
                lines.append("")
                lines.append(f"<b>Grupos:</b> {', '.join(result.groups_added)}")
        else:
            lines = [
                "<b>ERRO na criacao do usuario no Active Directory</b>",
                "",
                f"<b>Mensagem:</b> {result.message}",
            ]
            if result.errors:
                lines.append("")
                lines.append("<b>Detalhes dos erros:</b>")
                lines.extend(f"- {err}" for err in result.errors)
            lines.append("")
            lines.append("<i>Favor verificar manualmente e reprocessar se necessario.</i>")

        return "<br>".join(lines)

    async def _add_followup(self, client: httpx.AsyncClient, result: UserCreationResult) -> None:
        """Adiciona followup ao chamado com o resultado da operacao."""
        followup_payload = {
            "input": {
                "itemtype": "Ticket",
                "items_id": result.ticket_id,
                "content": self._build_followup_content(result),
                "is_private": 0,
            }
        }
        response = await client.post(
            f"{self._base_url}/ITILFollowup",
            headers=self._headers(),
            json=followup_payload,
        )
        response.raise_for_status()
        logger.info("Followup adicionado ao chamado #%d", result.ticket_id)

    async def _update_ticket_status(self, client: httpx.AsyncClient, result: UserCreationResult) -> None:
        """Atualiza status do chamado: Resolvido (sucesso) ou Pendente (erro)."""
        status = TicketStatus.SOLVED if result.success else TicketStatus.PENDING
        response = await client.put(
            f"{self._base_url}/Ticket/{result.ticket_id}",
            headers=self._headers(),
            json={"input": {"status": int(status)}},
        )
        response.raise_for_status()
        logger.info(
            "Chamado #%d atualizado para status %s",
            result.ticket_id,
            "Resolvido" if result.success else "Pendente",
        )

    @staticmethod
    def parse_ticket_content(item: dict) -> UserCreationPayload | None:
        """Extrai dados do usuario a partir do conteudo HTML do ticket gerado pelo formulario GLPI.

        O formulario cria tickets com conteudo no formato:
            <b>1) Nome</b>: {valor}<br>
            <b>2) Sobrenome</b>: {valor}<br>
            ...

        Retorna None se o conteudo nao corresponde ao formulario de criacao de usuario.
        """
        ticket_id = item.get("id")
        content = item.get("content", "")
        if not content or not ticket_id:
            return None

        # Extrai pares "Rotulo: Valor" do HTML usando o pattern pre-compilado
        fields: dict[str, str] = {}
        for match in _FORM_PATTERN.finditer(content):
            label = match.group(1).strip().lower()
            value = match.group(2).strip()
            fields[label] = value

        logger.debug("Campos extraidos do conteudo do ticket #%d: %s", ticket_id, fields)

        # Verificar se os campos obrigatorios estao presentes
        required = {"nome", "sobrenome", "e-mail corporativo"}
        if not required.issubset(fields.keys()):
            logger.debug(
                "Ticket #%d nao tem campos do formulario de usuario AD (campos: %s)",
                ticket_id, list(fields.keys()),
            )
            return None

        grupo_raw = fields.get("grupo ad", "").strip()
        return UserCreationPayload(
            ticket_id=ticket_id,
            first_name=fields.get("nome", ""),
            last_name=fields.get("sobrenome", ""),
            email=fields.get("e-mail corporativo", ""),
            department=fields.get("departamento", ""),
            title=fields.get("cargo", ""),
            groups=[grupo_raw] if grupo_raw else [],
        )

    async def _do_update_ticket(self, result: UserCreationResult) -> None:
        """Executa followup + atualizacao de status numa sessao GLPI."""
        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=30.0) as client:
            try:
                await self._init_session(client)
                await self._add_followup(client, result)
                await self._update_ticket_status(client, result)
            finally:
                await self._kill_session(client)

    async def update_ticket(self, result: UserCreationResult) -> None:
        """Adiciona followup ao chamado e atualiza status conforme resultado.

        Realiza ate 3 tentativas com backoff exponencial em caso de falha HTTP.
        """
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10),
                retry=retry_if_exception_type(httpx.HTTPError),
                before_sleep=before_sleep_log(logger, logging.WARNING),
                reraise=True,
            ):
                with attempt:
                    await self._do_update_ticket(result)
        except httpx.HTTPError as e:
            logger.error(
                "Erro ao atualizar chamado #%d no GLPI apos 3 tentativas: %s",
                result.ticket_id, e,
            )
