#!/usr/bin/env bash
# =============================================================================
# init-samba.sh — Inicializa o AD de teste com OUs, conta de serviço e grupos
#
# Executado pelo setup-test-env.sh via:
#   docker exec test-samba-dc bash /opt/init-samba.sh
#
# Pré-requisito: samba-dc container já está rodando e respondendo (portas 389/636)
# =============================================================================
set -euo pipefail

DOMAIN_DN="DC=teste,DC=local"
SVC_PASS="SvcGlpi@Test123!"

echo "============================================================"
echo " Inicializando AD de teste — GLPIADmit"
echo "============================================================"

# --- 1. Criar OUs ---
echo ""
echo "[1/5] Criando OU=Usuarios..."
samba-tool ou create "OU=Usuarios,${DOMAIN_DN}" \
  2>/dev/null && echo "      -> OU criada." || echo "      -> OU ja existe, continuando."

echo "[2/5] Criando OU=ServiceAccounts..."
samba-tool ou create "OU=ServiceAccounts,${DOMAIN_DN}" \
  2>/dev/null && echo "      -> OU criada." || echo "      -> OU ja existe, continuando."

echo "[3/5] Criando OU=Grupos..."
samba-tool ou create "OU=Grupos,${DOMAIN_DN}" \
  2>/dev/null && echo "      -> OU criada." || echo "      -> OU ja existe, continuando."

# --- 2. Criar conta de serviço ---
echo "[4/5] Criando conta de servico svc-glpi-ad..."
# Sem --given-name/--surname para que CN fique como "svc-glpi-ad" (não "svc-glpi-ad Service")
samba-tool user create svc-glpi-ad "${SVC_PASS}" \
  --description="Conta de servico do GLPIADmit" \
  2>/dev/null && echo "      -> Conta criada." || echo "      -> Conta ja existe, continuando."

# Garantir senha correta (idempotente: redefine mesmo que a conta ja exista)
samba-tool user setpassword svc-glpi-ad --newpassword="${SVC_PASS}" \
  2>/dev/null && echo "      -> Senha confirmada." || true

# Mover para a OU correta
samba-tool user move svc-glpi-ad "OU=ServiceAccounts,${DOMAIN_DN}" \
  2>/dev/null && echo "      -> Movida para OU=ServiceAccounts." || echo "      -> Conta ja esta na OU correta."

# Adicionar ao Domain Admins (simplifica permissões no ambiente de teste)
# Em produção, use delegação de controle na OU específica
samba-tool group addmembers "Domain Admins" svc-glpi-ad \
  2>/dev/null && echo "      -> Adicionada ao Domain Admins." || echo "      -> Ja e membro do Domain Admins."

# --- 3. Criar grupo de teste ---
echo "[5/5] Criando grupo GRP-TI..."
samba-tool group add "GRP-TI" \
  --groupou="OU=Grupos" \
  --description="Grupo de teste - Tecnologia da Informacao" \
  2>/dev/null && echo "      -> Grupo criado." || echo "      -> Grupo ja existe, continuando."

# --- Resumo ---
echo ""
echo "============================================================"
echo " AD de teste pronto!"
echo "============================================================"
echo ""
echo " Dominio:         teste.local (TESTE)"
echo " Base DN:         ${DOMAIN_DN}"
echo ""
echo " Conta de servico (para .env.test):"
echo "   AD_BIND_USER=CN=svc-glpi-ad,OU=ServiceAccounts,${DOMAIN_DN}"
echo "   AD_BIND_PASSWORD=${SVC_PASS}"
echo ""
echo " OU de usuarios (para AD_USER_OU):"
echo "   OU=Usuarios,${DOMAIN_DN}"
echo ""
echo " Grupo de teste (para campo 'groups' no webhook):"
echo "   CN=GRP-TI,OU=Grupos,${DOMAIN_DN}"
echo ""
echo " Admin do dominio:"
echo "   Usuario: Administrator"
echo "   Senha:   Admin@Teste123"
echo "============================================================"
