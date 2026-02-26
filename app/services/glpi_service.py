import logging

import httpx

from app.config import get_settings
from app.models import UserCreationResult

logger = logging.getLogger(__name__)

# Status ITIL do GLPI
_STATUS_PENDING = 4
_STATUS_SOLVED = 5


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
        """Inicia uma sessao na API do GLPI."""
        headers = {
            **self._headers(with_session=False),
            "Authorization": f"user_token {self._api_token}",
        }
        response = await client.get(f"{self._base_url}/initSession", headers=headers)
        response.raise_for_status()
        self._session_token = response.json()["session_token"]
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
        status = _STATUS_SOLVED if result.success else _STATUS_PENDING
        response = await client.put(
            f"{self._base_url}/Ticket/{result.ticket_id}",
            headers=self._headers(),
            json={"input": {"status": status}},
        )
        response.raise_for_status()
        logger.info(
            "Chamado #%d atualizado para status %s",
            result.ticket_id,
            "Resolvido" if result.success else "Pendente",
        )

    async def update_ticket(self, result: UserCreationResult) -> None:
        """Adiciona followup ao chamado e atualiza status conforme resultado."""
        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=30.0) as client:
            try:
                await self._init_session(client)
                await self._add_followup(client, result)
                await self._update_ticket_status(client, result)
            except httpx.HTTPError as e:
                logger.error("Erro ao atualizar chamado #%d no GLPI: %s", result.ticket_id, e)
            finally:
                await self._kill_session(client)
