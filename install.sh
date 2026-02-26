#!/usr/bin/env bash
# =============================================================================
# Script de Instalação — Integração GLPI + Active Directory
# Executa como root: sudo bash install.sh
# =============================================================================

set -euo pipefail

# --- Cores para output ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- Configurações ---
INSTALL_DIR="/opt/glpi-ad-integration"
SERVICE_USER="glpi-ad-svc"
SERVICE_NAME="glpi-ad-integration"
PYTHON_MIN_VERSION="3.11"
SERVICE_PORT=8443

# --- Funções auxiliares ---
log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[AVISO]${NC} $1"; }
log_error()   { echo -e "${RED}[ERRO]${NC} $1"; }

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "Este script deve ser executado como root (sudo bash install.sh)"
        exit 1
    fi
}

check_python() {
    log_info "Verificando Python..."

    if ! command -v python3 &>/dev/null; then
        log_error "Python 3 nao encontrado. Instale Python ${PYTHON_MIN_VERSION}+ antes de continuar."
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    REQUIRED_MAJOR=$(echo "$PYTHON_MIN_VERSION" | cut -d. -f1)
    REQUIRED_MINOR=$(echo "$PYTHON_MIN_VERSION" | cut -d. -f2)
    ACTUAL_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    ACTUAL_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

    if [[ "$ACTUAL_MAJOR" -lt "$REQUIRED_MAJOR" ]] || \
       [[ "$ACTUAL_MAJOR" -eq "$REQUIRED_MAJOR" && "$ACTUAL_MINOR" -lt "$REQUIRED_MINOR" ]]; then
        log_error "Python ${PYTHON_VERSION} encontrado, mas ${PYTHON_MIN_VERSION}+ e necessario."
        exit 1
    fi

    log_success "Python ${PYTHON_VERSION} encontrado"
}

check_port() {
    if ss -tlnp 2>/dev/null | grep -q ":${SERVICE_PORT} "; then
        log_warn "A porta ${SERVICE_PORT} ja esta em uso!"
        log_warn "Verifique com: ss -tlnp | grep ${SERVICE_PORT}"
        read -rp "Deseja continuar mesmo assim? [s/N]: " confirm
        if [[ "${confirm,,}" != "s" ]]; then
            log_info "Instalacao cancelada."
            exit 0
        fi
    fi
}

create_service_user() {
    log_info "Criando usuario de servico '${SERVICE_USER}'..."

    if id "$SERVICE_USER" &>/dev/null; then
        log_warn "Usuario '${SERVICE_USER}' ja existe, pulando criacao."
    else
        useradd -r -s /usr/sbin/nologin -d "$INSTALL_DIR" -c "GLPI-AD Integration Service" "$SERVICE_USER"
        log_success "Usuario '${SERVICE_USER}' criado"
    fi
}

install_files() {
    log_info "Copiando arquivos para ${INSTALL_DIR}..."

    # Criar diretorio de instalacao
    mkdir -p "$INSTALL_DIR"

    # Detectar diretorio do script (onde esta o codigo fonte)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # Copiar codigo da aplicacao
    cp -r "$SCRIPT_DIR/app" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

    # Copiar .env.example se .env nao existir
    if [[ ! -f "$INSTALL_DIR/.env" ]]; then
        cp "$SCRIPT_DIR/.env.example" "$INSTALL_DIR/.env"
        log_warn "Arquivo .env criado a partir do template. EDITE antes de iniciar o servico!"
    else
        log_warn "Arquivo .env ja existe, nao foi sobrescrito."
    fi

    log_success "Arquivos copiados para ${INSTALL_DIR}"
}

create_virtualenv() {
    log_info "Criando ambiente virtual Python..."

    if [[ -d "$INSTALL_DIR/venv" ]]; then
        log_warn "Ambiente virtual ja existe. Atualizando dependencias..."
    else
        python3 -m venv "$INSTALL_DIR/venv"
        log_success "Ambiente virtual criado"
    fi

    log_info "Instalando dependencias..."
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip --quiet
    "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --quiet
    log_success "Dependencias instaladas"
}

set_permissions() {
    log_info "Configurando permissoes..."

    chown -R "${SERVICE_USER}:${SERVICE_USER}" "$INSTALL_DIR"
    chmod 600 "$INSTALL_DIR/.env"
    chmod 755 "$INSTALL_DIR"

    log_success "Permissoes configuradas (.env com chmod 600)"
}

install_systemd_service() {
    log_info "Instalando servico systemd..."

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cp "$SCRIPT_DIR/systemd/glpi-ad-integration.service" "/etc/systemd/system/${SERVICE_NAME}.service"

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"

    log_success "Servico '${SERVICE_NAME}' instalado e habilitado no boot"
}

configure_firewall() {
    log_info "Verificando firewall..."

    if command -v ufw &>/dev/null; then
        log_warn "UFW detectado. Para permitir acesso ao servico, execute:"
        echo "    sudo ufw allow from <IP_DO_GLPI> to any port ${SERVICE_PORT}"
    elif command -v firewall-cmd &>/dev/null; then
        log_warn "firewalld detectado. Para permitir acesso ao servico, execute:"
        echo "    sudo firewall-cmd --permanent --add-port=${SERVICE_PORT}/tcp"
        echo "    sudo firewall-cmd --reload"
    else
        log_warn "Nenhum firewall detectado. Certifique-se de configurar regras de firewall para a porta ${SERVICE_PORT}."
    fi
}

print_summary() {
    echo ""
    echo "============================================================"
    echo -e "${GREEN} Instalacao concluida com sucesso!${NC}"
    echo "============================================================"
    echo ""
    echo "Diretorio de instalacao: ${INSTALL_DIR}"
    echo "Usuario de servico:      ${SERVICE_USER}"
    echo "Servico systemd:         ${SERVICE_NAME}"
    echo "Porta:                   ${SERVICE_PORT}"
    echo ""
    echo "--- Proximos passos ---"
    echo ""
    echo "1. Edite o arquivo de configuracao:"
    echo "   sudo nano ${INSTALL_DIR}/.env"
    echo ""
    echo "2. Preencha TODAS as variaveis obrigatorias:"
    echo "   - GLPI_URL, GLPI_API_TOKEN, GLPI_APP_TOKEN"
    echo "   - AD_SERVER, AD_DOMAIN, AD_BASE_DN, AD_USER_OU"
    echo "   - AD_BIND_USER, AD_BIND_PASSWORD"
    echo "   - WEBHOOK_SECRET"
    echo ""
    echo "3. Inicie o servico:"
    echo "   sudo systemctl start ${SERVICE_NAME}"
    echo ""
    echo "4. Verifique o status:"
    echo "   sudo systemctl status ${SERVICE_NAME}"
    echo ""
    echo "5. Teste o health check:"
    echo "   curl http://localhost:${SERVICE_PORT}/health"
    echo ""
    echo "6. Acompanhe os logs:"
    echo "   sudo journalctl -u ${SERVICE_NAME} -f"
    echo ""
    echo "7. Configure o firewall para aceitar conexoes do GLPI na porta ${SERVICE_PORT}"
    echo ""
    echo "Documentacao completa: ${INSTALL_DIR}/docs/ (se copiada)"
    echo "============================================================"
}

# --- Execucao principal ---
main() {
    echo ""
    echo "============================================================"
    echo "  Instalacao - Integracao GLPI + Active Directory"
    echo "============================================================"
    echo ""

    check_root
    check_python
    check_port
    create_service_user
    install_files
    create_virtualenv
    set_permissions
    install_systemd_service
    configure_firewall
    print_summary
}

main "$@"
