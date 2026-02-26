import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.routes.webhook import router as webhook_router

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Configura logging com base nas settings."""
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia ciclo de vida da aplicacao (startup/shutdown)."""
    _setup_logging()
    logger.info("Servico de integracao GLPI-AD iniciado")
    yield
    logger.info("Servico de integracao GLPI-AD encerrado")


app = FastAPI(
    title="Integracao GLPI - Active Directory",
    description="Servico que recebe webhooks do GLPI e cria usuarios automaticamente no Active Directory.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(webhook_router)


@app.get("/health")
async def health_check():
    """Endpoint de health check para monitoramento."""
    return {"status": "ok", "service": "glpi-ad-integration"}
