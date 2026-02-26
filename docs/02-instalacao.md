# Instalação e Configuração

## Escolha a topologia de deploy

Antes de instalar, escolha onde o GLPIADmit vai rodar:

| | Topologia A — Servidor dedicado | Topologia B — Mesmo servidor do GLPI |
|---|---|---|
| **Complexidade** | Servidor extra para gerenciar | Infraestrutura mais simples |
| **Acesso ao AD** | Servidor dedicado precisa ter acesso LDAPS ao AD | GLPI já costuma ter ou é fácil liberar |
| **Segurança** | Credenciais AD isoladas do servidor GLPI | `AD_BIND_PASSWORD` no mesmo servidor que o GLPI |
| **Disponibilidade** | Falha no GLPIADmit não afeta o GLPI | Manutenção do servidor derruba os dois |
| **Rede** | GLPI precisa alcançar o GLPIADmit na porta 80 | Comunicação local — sem firewall entre eles |
| **Indicado para** | GLPI em DMZ; ambientes com segmentação rígida | Ambientes on-premises simples; menos VMs |

> **Recomendação**: Se o GLPI está em DMZ e o AD está na rede interna com firewall entre eles, use a **Topologia A** (servidor dedicado na rede interna com acesso ao AD). Se tudo está na mesma rede interna e simplicidade operacional é prioridade, a **Topologia B** é uma escolha válida.

---

## Pré-requisitos (ambas as topologias)

- **Acesso de rede** do servidor GLPIADmit ao AD (porta 636/LDAPS)
- **Acesso de rede** do servidor GLPIADmit ao GLPI (porta 443/HTTPS)
- **Conta de serviço no AD** com permissão de criação de usuários no OU designado
- **API REST do GLPI** habilitada com tokens configurados

Requisitos adicionais dependem da forma de deploy:

| Deploy | Requisito adicional |
|---|---|
| **Docker** (recomendado) | Docker Engine 24+ e Docker Compose v2 |
| **systemd** | Python 3.11+ instalado no servidor Linux |

---

## 1. Clonar o projeto no servidor

```bash
cd /opt
git clone <repositorio> glpi-ad-integration
cd glpi-ad-integration
```

---

## 2. Configurar variáveis de ambiente

Independente da forma de deploy, o `.env` é necessário:

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

---

## 3. Topologia A — Servidor dedicado

GLPIADmit em servidor próprio, separado do GLPI.

### 3.1 Docker (recomendado)

```bash
# Verificar instalação
docker --version        # 24+
docker compose version  # v2

# Subir o serviço
docker compose up -d
```

#### Verificar

```bash
# Status do container
docker compose ps

# Health check
curl http://localhost:8443/health
# {"status": "ok", "service": "glpi-ad-integration"}

# Logs em tempo real
docker compose logs -f
```

#### Resolução de nomes (AD/GLPI em hosts locais)

Se o AD ou GLPI não são resolvíveis pelo DNS do container, adicione ao `docker-compose.yml`:

```yaml
services:
  glpiadmit:
    extra_hosts:
      - "dc01.suaempresa.local:192.168.1.10"
      - "glpi.suaempresa.local:192.168.1.20"
```

**URL do webhook no GLPI**: `http://<ip-do-servidor-glpiadmit>/webhook/glpi-native`

---

### 3.2 systemd (alternativa)

#### Criar ambiente virtual Python

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### Testar execução manual

```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8443
```

Acesse `http://<ip-do-servidor>:8443/health`. Deve retornar:

```json
{"status": "ok", "service": "glpi-ad-integration"}
```

#### Instalar como serviço systemd

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

#### Verificar logs (systemd)

```bash
# Logs em tempo real
sudo journalctl -u glpi-ad-integration -f

# Últimas 100 linhas
sudo journalctl -u glpi-ad-integration -n 100
```

> Para expor na porta 80 (sem porta explícita na URL do webhook), use um reverse proxy Nginx. Consulte [06-seguranca.md](06-seguranca.md) — seção "HTTPS (TLS) no GLPIADmit".

**URL do webhook no GLPI**: `http://<ip-do-servidor-glpiadmit>/webhook/glpi-native`

---

## 4. Topologia B — Mesmo servidor do GLPI

GLPIADmit instalado no mesmo host que o GLPI. O webhook é entregue localmente, sem atravessar a rede.

> **Atenção**: O arquivo `.env` com a `AD_BIND_PASSWORD` ficará no mesmo servidor que o GLPI. Avalie se isso é aceitável pela política de segurança da sua organização.

### 4.1 GLPI também em Docker (mesmo host)

Este é o cenário mais comum quando o GLPI foi instalado via Docker Compose.

**1. Descobrir a rede Docker do GLPI:**

```bash
# Ver redes do container GLPI (substitua pelo nome real do container)
docker inspect <nome-do-container-glpi> \
  --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'

# Listar todas as redes e identificar a do GLPI
docker network ls
```

O nome geralmente segue o padrão `<nome-do-projeto>_default` (ex: `glpi_default`, `meuglpi_default`).

**2. Ajustar o arquivo de override:**

Edite `docker-compose.same-host.yml` e substitua `glpi_default` pelo nome real da rede:

```yaml
networks:
  glpi_network:
    external: true
    name: glpi_default    # <- nome real da rede Docker do GLPI
```

**3. Subir com o override:**

```bash
docker compose -f docker-compose.yml -f docker-compose.same-host.yml up -d
```

**4. Verificar que o GLPI alcança o GLPIADmit:**

```bash
docker exec <container-glpi> curl -sf http://glpiadmit/health
# {"status": "ok", "service": "glpi-ad-integration"}
```

**5. URL do webhook no GLPI**: `http://glpiadmit/webhook/glpi-native`

> O GLPIADmit escuta na porta 80 nesta configuração (sem porta na URL — necessário para que o GLPI aceite a URL via `isUrlSafe()`). O health check local continua funcionando em `http://localhost:80/health`.

---

### 4.2 GLPI com Nginx no mesmo host (systemd)

Se o GLPI roda com Nginx (bare-metal ou em container com porta exposta), adicione um bloco `location` ao Nginx do GLPI para rotear `/webhook/` para o GLPIADmit local.

**1. Instalar o GLPIADmit** seguindo a seção 3.2 (systemd), rodando na porta 8443.

**2. Adicionar ao `server` block do Nginx do GLPI:**

```nginx
# Dentro do server block existente do GLPI (não criar novo vhost):
location /webhook/ {
    proxy_pass         http://127.0.0.1:8443;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-GLPI-signature  $http_x_glpi_signature;
    proxy_set_header   X-GLPI-timestamp  $http_x_glpi_timestamp;
}
```

**3. Aplicar a configuração:**

```bash
sudo nginx -t                        # testar sintaxe
sudo systemctl reload nginx
```

**4. Verificar:**

```bash
curl http://localhost/webhook/glpi-native
# Deve retornar 401 (assinatura ausente) — confirma que o proxy está funcionando
```

**5. URL do webhook no GLPI**: `https://glpi.suaempresa.com.br/webhook/glpi-native`

> A URL usa o mesmo domínio e porta do GLPI — sem porta extra, sem problema com `isUrlSafe()`. O tráfego do GLPI para o GLPIADmit passa pelo Nginx local, sem sair do servidor.
