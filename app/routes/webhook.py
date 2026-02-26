import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.models import UserCreationPayload, WebhookResponse
from app.services.ad_service import ADService
from app.services.glpi_service import GLPIService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])


def _verify_webhook_signature(payload_body: bytes, signature: str | None, secret: str) -> bool:
    """Valida a assinatura HMAC-SHA256 do webhook enviado pelo GLPI."""
    if not secret:
        logger.warning("WEBHOOK_SECRET nao configurado - assinatura nao validada")
        return True

    if not signature:
        return False

    expected = hmac.new(
        secret.encode(),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


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
        json_data = await request.json()
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

    # 3. Criar usuario no AD
    ad_service = ADService()
    result = ad_service.create_user(payload)

    # 4. Atualizar chamado no GLPI
    glpi_service = GLPIService()
    await glpi_service.update_ticket(result)

    # 5. Responder ao GLPI
    return WebhookResponse(
        status="success" if result.success else "error",
        message=result.message,
        ticket_id=payload.ticket_id,
    )
