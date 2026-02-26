import hashlib
import hmac
import json as _json
import logging

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.models import UserCreationPayload, UserCreationResult, WebhookResponse
from app.services.ad_service import ADService
from app.services.glpi_service import GLPIService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])


def _verify_webhook_signature(
    payload_body: bytes,
    signature: str | None,
    secret: str,
    timestamp: str | None = None,
) -> bool:
    """Valida a assinatura HMAC-SHA256 do webhook enviado pelo GLPI.

    O GLPI nativo assina com: hash_hmac('sha256', body . timestamp, secret)
    O endpoint legado /user-creation assina apenas com: hash_hmac('sha256', body, secret)
    """
    if not secret:
        logger.warning("WEBHOOK_SECRET nao configurado - assinatura nao validada")
        return True

    if not signature:
        return False

    # Tenta primeiro a assinatura com timestamp (formato GLPI nativo)
    if timestamp:
        data_with_ts = payload_body + timestamp.encode()
        expected_ts = hmac.new(secret.encode(), data_with_ts, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected_ts, signature):
            return True

    # Fallback: assinatura sem timestamp (endpoint legado)
    expected = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _execute_user_creation(payload: UserCreationPayload) -> UserCreationResult:
    """Orquestra criacao de usuario no AD e atualizacao do chamado no GLPI."""
    ad_service = ADService()
    result = ad_service.create_user(payload)
    glpi_service = GLPIService()
    await glpi_service.update_ticket(result)
    return result


@router.post("/glpi-native", response_model=WebhookResponse)
async def handle_glpi_native(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> WebhookResponse:
    """Endpoint que recebe o webhook nativo do GLPI (evento de criacao de ticket).

    Fluxo:
    1. Valida assinatura HMAC
    2. Extrai ticket_id do payload nativo do GLPI
    3. Parseia conteudo do ticket para extrair dados do formulario
    4. Cria o usuario no AD
    5. Atualiza o chamado no GLPI com o resultado
    """
    # 1. Validar assinatura (GLPI assina: hmac(body + timestamp, secret))
    body = await request.body()
    signature = request.headers.get("X-GLPI-signature")
    timestamp = request.headers.get("X-GLPI-timestamp")

    if not _verify_webhook_signature(body, signature, settings.webhook_secret, timestamp):
        logger.warning("Webhook nativo recebido com assinatura invalida")
        raise HTTPException(status_code=401, detail="Assinatura invalida")

    # 2. Extrair ticket_id do payload nativo {event, item: {id, ...}}
    try:
        json_data = _json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON invalido")

    event = json_data.get("event", "")
    item = json_data.get("item", {})
    ticket_id = item.get("id")

    if not ticket_id:
        raise HTTPException(status_code=422, detail="Campo 'item.id' ausente no payload")

    logger.info("Webhook nativo recebido: evento='%s' ticket_id=%s", event, ticket_id)

    # 3. Extrair dados do usuario do conteudo do ticket (gerado pelo formulario GLPI)
    # Nota: Glpi\Form\AnswersSet nao e acessivel via REST API (canView() == false).
    # O conteudo do ticket ja contem todos os campos formatados pelo template do formulario.
    payload = GLPIService.parse_ticket_content(item)

    if payload is None:
        logger.info(
            "Ticket #%d nao originou de formulario de criacao de usuario — ignorando",
            ticket_id,
        )
        return WebhookResponse(
            status="ignored",
            message=f"Ticket #{ticket_id} nao originou de formulario de criacao de usuario.",
            ticket_id=ticket_id,
        )

    logger.info(
        "Formulario mapeado: ticket #%d → %s %s (%s)",
        ticket_id, payload.first_name, payload.last_name, payload.email,
    )

    # 4. Criar usuario no AD e 5. Atualizar chamado no GLPI
    result = await _execute_user_creation(payload)

    return WebhookResponse(
        status="success" if result.success else "error",
        message=result.message,
        ticket_id=ticket_id,
    )


@router.post("/user-creation", response_model=WebhookResponse)
async def handle_user_creation(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> WebhookResponse:
    """Endpoint que recebe o webhook do GLPI para criacao de usuario no AD.

    Fluxo:
    1. Valida assinatura HMAC
    2. Parseia o payload
    3. Cria o usuario no AD
    4. Atualiza o chamado no GLPI com o resultado
    """
    # 1. Validar assinatura
    body = await request.body()
    signature = request.headers.get("X-GLPI-Signature")

    if not _verify_webhook_signature(body, signature, settings.webhook_secret):
        logger.warning("Webhook recebido com assinatura invalida")
        raise HTTPException(status_code=401, detail="Assinatura invalida")

    # 2. Parsear payload
    try:
        json_data = _json.loads(body)
        payload = UserCreationPayload(**json_data)
    except ValidationError as e:
        logger.error("Payload invalido recebido: %s", e)
        raise HTTPException(status_code=422, detail=f"Payload invalido: {e}")

    logger.info(
        "Webhook recebido: criacao de usuario para ticket #%d (%s %s)",
        payload.ticket_id,
        payload.first_name,
        payload.last_name,
    )

    # 3. Criar usuario no AD e 4. Atualizar chamado no GLPI
    result = await _execute_user_creation(payload)

    return WebhookResponse(
        status="success" if result.success else "error",
        message=result.message,
        ticket_id=payload.ticket_id,
    )
