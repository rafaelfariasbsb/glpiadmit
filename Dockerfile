# =============================================================================
# Stage 1: builder — instala dependências em prefixo isolado
# =============================================================================
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# =============================================================================
# Stage 2: runtime — imagem final enxuta, usuário não-root
# =============================================================================
FROM python:3.11-slim

# Metadados
LABEL maintainer="glpiadmit" \
      description="GLPIADmit — Automated AD user provisioning from GLPI tickets" \
      version="1.0.0"

# Cria usuário sem privilégios (equivalente ao glpi-ad-svc do systemd)
RUN groupadd --system appgroup && \
    useradd --system --gid appgroup --no-create-home appuser

WORKDIR /app

# Copia dependências instaladas no stage builder
COPY --from=builder /install /usr/local

# Copia apenas o código da aplicação (não testes, docs, etc.)
COPY app/ ./app/

# Define dono dos arquivos
RUN chown -R appuser:appgroup /app

# Roda como não-root
USER appuser

# Porta da aplicação
EXPOSE 8443

# Variáveis de ambiente padrão (sobrescritas pelo .env / docker-compose)
ENV LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Health check interno
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8443/health')" || exit 1

# Comando de inicialização
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8443", "--workers", "2"]
