#!/usr/bin/env bash
# =============================================================================
# setup-test-env.sh — Sobe e configura o ambiente de teste completo do GLPIADmit
#
# Uso: bash tests/docker/setup-test-env.sh
# Pré-requisito: Docker e Docker Compose v2 instalados
#
# O que este script faz (totalmente automático):
#   1. Sobe MariaDB, GLPI e Samba AD DC
#   2. Aguarda o Samba DC provisionar o domínio
#   3. Cria OUs, conta de serviço e grupos no AD (via init-samba.sh)
#   4. Aguarda o MariaDB ficar pronto
#   5. Instala o banco de dados do GLPI via console (se ainda não instalado)
#   6. Configura a API REST do GLPI e gera os tokens automaticamente
#   7. Atualiza .env.test com os tokens gerados
#   8. Sobe o glpiadmit com as configurações completas
# =============================================================================
set -euo pipefail

COMPOSE="docker compose -f docker-compose.test.yml"
SAMBA_CONTAINER="test-samba-dc"
GLPI_CONTAINER="test-glpi"
MARIADB_CONTAINER="test-mariadb"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()   { echo -e "${GREEN}[ OK ]${NC}  $1"; }
warn() { echo -e "${YELLOW}[AVISO]${NC} $1"; }
err()  { echo -e "${RED}[ERRO]${NC}  $1"; }

# --- Verificações iniciais ---
if [[ ! -f "docker-compose.test.yml" ]]; then
    err "Execute este script a partir da raiz do projeto (onde está docker-compose.test.yml)."
    exit 1
fi

if [[ ! -f ".env.test" ]]; then
    err ".env.test não encontrado. O arquivo deve existir na raiz do projeto."
    exit 1
fi

echo ""
echo "============================================================"
log "Iniciando ambiente de teste GLPIADmit..."
echo "============================================================"
echo ""

# --- 1. Subir MariaDB, GLPI e Samba DC ---
log "Subindo MariaDB, GLPI e Samba DC..."
$COMPOSE up -d mariadb glpi samba-dc

# --- 2. Aguardar Samba DC ---
log "Aguardando Samba AD DC inicializar (pode levar 1-2 min para provisionar o domínio)..."
RETRIES=36  # 36 x 5s = 3 minutos
until docker exec "${SAMBA_CONTAINER}" bash -c 'echo > /dev/tcp/127.0.0.1/636' 2>/dev/null; do
    RETRIES=$((RETRIES - 1))
    if [[ ${RETRIES} -le 0 ]]; then
        echo ""
        err "Timeout aguardando Samba DC. Verifique os logs:"
        err "  $COMPOSE logs samba-dc"
        exit 1
    fi
    echo -n "."
    sleep 5
done
echo ""
ok "Samba DC respondendo (LDAPS porta 636)."

# Aguarda mais alguns segundos para o Samba terminar de inicializar
# (porta aberta != AD totalmente provisionado)
log "Aguardando provisionamento completo do domínio..."
sleep 15

# --- 3. Inicializar AD (OUs, conta de serviço, grupos) ---
log "Criando OUs, conta de serviço e grupos no AD..."
docker exec "${SAMBA_CONTAINER}" bash /opt/init-samba.sh
ok "AD de teste inicializado."

# --- 4. Aguardar MariaDB ficar pronto ---
log "Aguardando MariaDB ficar pronto..."
RETRIES=30  # 30 x 5s = 2.5 minutos
until docker exec "${MARIADB_CONTAINER}" \
    healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1; do
    RETRIES=$((RETRIES - 1))
    if [[ ${RETRIES} -le 0 ]]; then
        echo ""
        err "Timeout aguardando MariaDB. Verifique os logs:"
        err "  $COMPOSE logs mariadb"
        exit 1
    fi
    echo -n "."
    sleep 5
done
echo ""
ok "MariaDB pronto."

# --- 5. Aguardar GLPI ter seus arquivos prontos ---
log "Aguardando GLPI extrair arquivos (bin/console)..."
RETRIES=30  # 30 x 5s = 2.5 minutos
until docker exec "${GLPI_CONTAINER}" test -f /var/www/html/glpi/bin/console 2>/dev/null; do
    RETRIES=$((RETRIES - 1))
    if [[ ${RETRIES} -le 0 ]]; then
        echo ""
        err "Timeout: bin/console não encontrado no container GLPI. Verifique os logs:"
        err "  $COMPOSE logs glpi"
        exit 1
    fi
    echo -n "."
    sleep 5
done
echo ""
ok "GLPI pronto (bin/console encontrado)."

# --- 5b. Instalar banco de dados do GLPI via console ---
log "Instalando banco de dados do GLPI (via console)..."
INSTALL_OUTPUT=$(docker exec -w /var/www/html/glpi "${GLPI_CONTAINER}" \
    php bin/console database:install \
    --allow-superuser --no-interaction --no-telemetry \
    -H mariadb -d glpidb -u glpi -p glpipass 2>&1) || INSTALL_EXIT=$?

if [[ "${INSTALL_EXIT:-0}" -eq 0 ]]; then
    ok "Banco de dados do GLPI instalado com sucesso."
elif [[ "${INSTALL_EXIT:-0}" -eq 3 ]]; then
    ok "Banco de dados do GLPI já estava instalado."
else
    err "Falha ao instalar banco de dados do GLPI (exit ${INSTALL_EXIT:-?}):"
    echo "${INSTALL_OUTPUT}" >&2
    exit 1
fi

# --- 6. Configurar API REST do GLPI e gerar tokens ---
log "Configurando API REST do GLPI e gerando tokens..."
docker cp tests/docker/glpi-setup-api.php "${GLPI_CONTAINER}:/tmp/glpi-setup-api.php"
GLPI_TOKENS=$(docker exec -w /var/www/html/glpi "${GLPI_CONTAINER}" \
    php /tmp/glpi-setup-api.php 2>/dev/null | tail -1)

if [[ -z "${GLPI_TOKENS}" ]]; then
    err "Falha ao gerar tokens do GLPI. Diagnóstico:"
    docker exec -w /var/www/html/glpi "${GLPI_CONTAINER}" php /tmp/glpi-setup-api.php
    exit 1
fi

GLPI_API_TOKEN=$(echo "${GLPI_TOKENS}" | grep -oP 'API_TOKEN=\K\S+')
GLPI_APP_TOKEN=$(echo "${GLPI_TOKENS}" | grep -oP 'APP_TOKEN=\K\S+')

if [[ -z "${GLPI_API_TOKEN}" || -z "${GLPI_APP_TOKEN}" ]]; then
    err "Tokens gerados inválidos: ${GLPI_TOKENS}"
    exit 1
fi

# Atualizar .env.test com os tokens (substitui placeholders ou valores anteriores)
sed -i "s|^GLPI_API_TOKEN=.*|GLPI_API_TOKEN=${GLPI_API_TOKEN}|" .env.test
sed -i "s|^GLPI_APP_TOKEN=.*|GLPI_APP_TOKEN=${GLPI_APP_TOKEN}|" .env.test
ok "Tokens GLPI gerados e gravados em .env.test."

# --- 7. Criar formulário "Solicitar Criação de Usuário AD" no Catálogo de Serviços ---
log "Criando formulário de solicitação de usuário no GLPI (Catálogo de Serviços)..."
docker cp tests/docker/glpi-create-form.php "${GLPI_CONTAINER}:/tmp/glpi-create-form.php"
FORM_OUTPUT=$(docker exec -w /var/www/html/glpi "${GLPI_CONTAINER}" \
    php /tmp/glpi-create-form.php 2>/dev/null)
echo "${FORM_OUTPUT}" | grep -vE "^FORM_ID=" || true

FORM_ID=$(echo "${FORM_OUTPUT}" | grep -oP 'FORM_ID=\K\d+')
if [[ -z "${FORM_ID}" ]]; then
    # Formulário já existia — extrai ID da linha "Já existe (id=X)"
    FORM_ID=$(echo "${FORM_OUTPUT}" | grep -oP 'id=\K\d+' | head -1)
fi
ok "Formulário GLPI configurado (id=${FORM_ID:-?})."

# --- 8. Configurar webhook GLPI → GLPIADmit ---
log "Configurando webhook GLPI → GLPIADmit..."
docker cp tests/docker/glpi-create-webhook.php "${GLPI_CONTAINER}:/tmp/glpi-create-webhook.php"
WEBHOOK_SECRET_VAL=$(grep '^WEBHOOK_SECRET=' .env.test | cut -d= -f2)
docker exec -e "WEBHOOK_SECRET=${WEBHOOK_SECRET_VAL}" -w /var/www/html/glpi "${GLPI_CONTAINER}" \
    php /tmp/glpi-create-webhook.php 2>/dev/null
ok "Webhook GLPI configurado."

# Corrige permissões: todos os comandos PHP acima rodaram como root (docker exec),
# criando arquivos de cache/log com owner root. Apache roda como www-data — sem fix
# qualquer requisição HTTP falha com "Permission denied" ao tentar escrever no cache.
docker exec "${GLPI_CONTAINER}" chown -R www-data:www-data \
    /var/www/html/glpi/files \
    /var/lib/php/sessions \
    2>/dev/null || true
ok "Permissões GLPI corrigidas (www-data)."

# --- 9. Subir GLPIADmit (com tokens atualizados) ---
log "Construindo e subindo glpiadmit..."
$COMPOSE up -d --force-recreate glpiadmit

# --- 10. Aguardar GLPIADmit ---
log "Aguardando glpiadmit ficar pronto..."
RETRIES=20
until curl -sf http://localhost:8443/health >/dev/null 2>&1; do
    RETRIES=$((RETRIES - 1))
    if [[ ${RETRIES} -le 0 ]]; then
        err "Timeout aguardando glpiadmit. Verifique os logs:"
        err "  $COMPOSE logs glpiadmit"
        exit 1
    fi
    sleep 3
done
ok "GLPIADmit pronto."

# --- Resumo ---
echo ""
echo "============================================================"
ok "Ambiente de teste ativo e configurado!"
echo "============================================================"
echo ""
echo "  GLPI:"
echo "    URL:        http://localhost:8080"
echo "    Login:      glpi / glpi"
echo "    Catálogo:   http://localhost:8080/index.php?redirect=Glpi%5CForm%5CForm_${FORM_ID:-?}"
echo "    Admin form: http://localhost:8080/front/form/form.form.php?id=${FORM_ID:-?}"
echo ""
echo "  GLPIADmit:"
echo "    Health:   http://localhost:8443/health"
echo "    Docs:     http://localhost:8443/docs"
echo ""
echo "  Samba AD DC (teste.local):"
echo "    LDAP:     ldap://localhost:389"
echo "    LDAPS:    ldaps://localhost:636"
echo "    Admin:    Administrator / Admin@Teste123"
echo ""
echo "  Conta de serviço (já configurada em .env.test):"
echo "    DN:    CN=svc-glpi-ad,OU=ServiceAccounts,DC=teste,DC=local"
echo "    Senha: SvcGlpi@Test123!"
echo ""
echo "============================================================"
log "Teste rápido do webhook (substitua ticket_id por um ID existente no GLPI):"
echo ""
echo '  BODY='"'"'{"ticket_id":1,"first_name":"João","last_name":"Teste","email":"joao.teste@empresa.com","department":"TI","title":"Analista","groups":["CN=GRP-TI,OU=Grupos,DC=teste,DC=local"]}'"'"
echo '  SECRET="test-webhook-secret-2024"'
echo '  SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '"'"'{print $2}'"'"')'
echo '  curl -s -X POST http://localhost:8443/webhook/user-creation \'
echo '    -H "Content-Type: application/json" \'
echo '    -H "X-GLPI-Signature: $SIG" \'
echo '    -d "$BODY"'
echo "============================================================"
