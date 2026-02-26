# Instalação e Configuração

## Pré-requisitos

- **Python 3.11+** instalado no servidor Linux
- **Acesso de rede** do servidor ao AD (porta 636/LDAPS)
- **Acesso de rede** do servidor ao GLPI (porta 443/HTTPS)
- **Acesso de rede** do GLPI ao servidor FastAPI (porta 8443)
- **Conta de serviço no AD** com permissão de criação de usuários no OU designado
- **API REST do GLPI** habilitada com tokens configurados

---

## 1. Clonar o projeto no servidor

```bash
cd /opt
git clone <repositorio> glpi-ad-integration
cd glpi-ad-integration
```

Ou copiar manualmente os arquivos para `/opt/glpi-ad-integration/`.

## 2. Criar ambiente virtual Python

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Instalar dependências de teste (opcional, para desenvolvimento)
pip install pytest pytest-asyncio pytest-cov
```

## 3. Configurar variáveis de ambiente

```bash
cp .env.example .env
chmod 600 .env    # IMPORTANTE: restringir permissões
nano .env
```

Preencha cada variável:

```ini
# --- GLPI ---
GLPI_URL=https://glpi.suaempresa.com.br
GLPI_API_TOKEN=abc123...          # User Token (Preferências do usuário no GLPI)
GLPI_APP_TOKEN=def456...          # App Token (Configuração > API no GLPI)
GLPI_VERIFY_SSL=true              # Verificar certificado SSL do GLPI (default: true)

# --- Active Directory ---
AD_SERVER=ldaps://dc01.suaempresa.local
AD_DOMAIN=suaempresa.local
AD_BASE_DN=DC=suaempresa,DC=local
AD_USER_OU=OU=Usuarios,DC=suaempresa,DC=local
AD_BIND_USER=CN=svc-glpi-ad,OU=ServiceAccounts,DC=suaempresa,DC=local
AD_BIND_PASSWORD=SenhaSeguraDaContaDeServico
AD_DEFAULT_COMPANY=Sua Empresa

# --- Webhook ---
WEBHOOK_SECRET=chave-secreta-configurada-no-glpi

# --- Logging ---
LOG_LEVEL=INFO
```

### Detalhes de cada variável

| Variável | Descrição |
|---|---|
| `GLPI_URL` | URL base do GLPI (sem barra no final) |
| `GLPI_API_TOKEN` | Token pessoal do usuário API no GLPI (Preferências > Token de API Remota) |
| `GLPI_APP_TOKEN` | Token da aplicação (Configuração > Geral > API > Clientes API) |
| `GLPI_VERIFY_SSL` | Verificar certificado SSL do GLPI (`true`/`false`, padrão: `true`) |
| `AD_SERVER` | Endereço do controlador de domínio. **Deve começar com `ldaps://`** |
| `AD_DOMAIN` | Domínio AD (ex: `empresa.local`) |
| `AD_BASE_DN` | Base DN para buscas (ex: `DC=empresa,DC=local`) |
| `AD_USER_OU` | OU onde os novos usuários serão criados |
| `AD_BIND_USER` | DN completo da conta de serviço |
| `AD_BIND_PASSWORD` | Senha da conta de serviço |
| `AD_DEFAULT_COMPANY` | Nome da empresa (atributo `company` no AD) |
| `WEBHOOK_SECRET` | Chave secreta para validar assinatura HMAC do webhook |
| `LOG_LEVEL` | Nível de log: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## 4. Testar execução manual

```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8443
```

Acesse `http://<ip-do-servidor>:8443/health` no navegador. Deve retornar:

```json
{"status": "ok", "service": "glpi-ad-integration"}
```

Acesse `http://<ip-do-servidor>:8443/docs` para ver a documentação OpenAPI interativa.

## 5. Instalar como serviço systemd

```bash
# Criar usuário de serviço (sem shell, sem home)
sudo useradd -r -s /usr/sbin/nologin glpi-ad-svc

# Ajustar permissões
sudo chown -R glpi-ad-svc:glpi-ad-svc /opt/glpi-ad-integration
sudo chmod 600 /opt/glpi-ad-integration/.env

# Copiar unit file
sudo cp systemd/glpi-ad-integration.service /etc/systemd/system/

# Habilitar e iniciar
sudo systemctl daemon-reload
sudo systemctl enable glpi-ad-integration
sudo systemctl start glpi-ad-integration

# Verificar status
sudo systemctl status glpi-ad-integration
```

## 6. Verificar logs

```bash
# Logs em tempo real
sudo journalctl -u glpi-ad-integration -f

# Últimas 100 linhas
sudo journalctl -u glpi-ad-integration -n 100
```
