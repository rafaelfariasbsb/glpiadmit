# GLPIADmit

> Provisionamento automático de usuários no Active Directory a partir de chamados GLPI.

Quando um formulário de "Criação de Usuário" é submetido no **GLPI 11**, o GLPIADmit recebe o webhook nativo do GLPI, cria a conta no **Active Directory** via LDAPS, define uma senha temporária, adiciona o usuário aos grupos e atualiza o chamado com as credenciais. A conta sincroniza com **Azure AD / Entra ID** via Entra Connect em até 30 minutos.

---

## Como funciona

```
Solicitante preenche        GLPI dispara           Serviço FastAPI
formulário no              webhook nativo    ──►   valida e cria o
Catálogo de Serviços  ──►  (POST nativo)           usuário no AD
do GLPI 11                                               │
                                                         ▼
                                                   Atualiza chamado
                                                   GLPI com credenciais
                                                   (followup + Resolvido)
                                                         │
                                                         ▼
                                                   Entra Connect sincroniza
                                                   com Azure AD (~30 min)
```

**Fluxo completo:**

1. Solicitante preenche o formulário **"Solicitar Criação de Usuário AD"** no Catálogo de Serviços do GLPI
2. GLPI cria o ticket e dispara um **webhook nativo** (evento `new`) para o GLPIADmit
3. O serviço valida a assinatura HMAC, extrai os dados do conteúdo do ticket e **cria o usuário no AD** via LDAPS
4. O serviço **atualiza o chamado** no GLPI com credenciais (sucesso) ou detalhes do erro
5. O **Entra Connect** sincroniza o novo usuário com o Azure AD / Entra ID

## Funcionalidades

- **Criação automática** de usuários no Active Directory a partir de chamados GLPI
- **LDAPS obrigatório** (porta 636) — senhas nunca trafegam em texto plano
- **Detecção de duplicatas** — verifica `sAMAccountName` e `userPrincipalName` antes de criar
- **Senha temporária** — criptograficamente segura, troca obrigatória no primeiro login
- **Grupos AD** — adiciona automaticamente o usuário ao grupo especificado
- **Rollback** — se a criação falha parcialmente, o usuário é removido
- **Feedback no chamado** — ticket atualizado com credenciais ou detalhes do erro
- **Validação HMAC** — webhook autenticado com `hmac(body + timestamp, secret)` (formato nativo GLPI 11)
- **Proteção LDAP** — entradas sanitizadas conforme RFC 4514/4515

## Stack tecnológica

| Componente | Tecnologia |
|---|---|
| ITSM | GLPI 11 |
| Middleware | Python 3.11+ / FastAPI |
| Validação | Pydantic v2 + EmailStr |
| Comunicação AD | ldap3 (LDAPS) |
| Comunicação GLPI | httpx (REST API) |
| Configuração | pydantic-settings (variáveis de ambiente) |
| Deploy | Docker (recomendado) ou systemd |
| Diretório | Windows Server AD DS |
| Cloud sync | Azure AD / Entra ID (via Entra Connect) |

## Estrutura do projeto

```
├── app/
│   ├── main.py              # FastAPI app, lifespan, health check
│   ├── config.py            # Configurações via pydantic-settings (@lru_cache)
│   ├── models.py            # Modelos Pydantic (payload, resultado, resposta)
│   ├── services/
│   │   ├── ad_service.py    # Criação de usuário no AD (connection_factory DI)
│   │   └── glpi_service.py  # Cliente REST API do GLPI + parse de conteúdo do ticket
│   ├── utils/
│   │   ├── password.py      # Geração de senha temporária (secrets/CSPRNG)
│   │   └── validators.py    # Validação e sanitização de dados
│   └── routes/
│       └── webhook.py       # Endpoints do webhook (FastAPI Depends para settings)
├── tests/
│   ├── conftest.py          # Fixtures compartilhadas
│   ├── test_validators.py
│   ├── test_ad_service.py
│   ├── test_webhook.py
│   ├── test_password.py
│   └── test_glpi_service.py
├── tests/docker/            # Ambiente de teste completo (GLPI + Samba AD)
│   ├── setup-test-env.sh    # Script de setup automático do ambiente de teste
│   ├── glpi-create-form.php # Cria formulário no GLPI (Catálogo de Serviços)
│   ├── glpi-create-webhook.php # Configura webhook GLPI → GLPIADmit
│   ├── glpi-setup-api.php   # Habilita REST API e gera tokens
│   └── init-samba.sh        # Inicializa AD de teste (OUs, conta de serviço, grupos)
├── docs/                    # Documentação detalhada (Português)
├── docker-compose.test.yml  # Ambiente de teste: MariaDB + GLPI + Samba AD + GLPIADmit
├── systemd/                 # Unit file para deploy systemd
├── install.sh               # Script de instalação automatizada
├── .env.example             # Template de variáveis de ambiente
└── requirements.txt         # Dependências Python
```

## Ambiente de teste

O projeto inclui um ambiente de teste completo com GLPI 11, Samba AD DC e MariaDB:

```bash
# Subir e configurar o ambiente completo (automaticamente):
bash tests/docker/setup-test-env.sh
```

O script faz tudo automaticamente:
1. Sobe MariaDB, GLPI 11 e Samba AD DC
2. Instala banco de dados do GLPI
3. Configura API REST e gera tokens
4. Cria formulário no Catálogo de Serviços
5. Configura webhook GLPI → GLPIADmit
6. Sobe o GLPIADmit com a configuração completa

Após o setup:
- **GLPI**: `http://localhost:8080` (glpi / glpi)
- **GLPIADmit health**: `http://localhost:8443/health`
- **Catálogo de Serviços**: exibido no resumo do script

## Docker (produção)

```bash
# 1. Configurar o ambiente
cp .env.example .env
chmod 600 .env
# edite .env com seus valores reais

# 2. Build e start
docker compose up -d

# 3. Verificar
curl http://localhost:8443/health
# {"status": "ok", "service": "glpi-ad-integration"}
```

> **Importante**: O container deve escutar na **porta 80 internamente** para que o webhook do GLPI funcione. O GLPI 11 bloqueia URLs com porta explícita (`:8443`) por proteção SSRF. Mapeie `80:8443` ou `80:80` no docker-compose.

### Resolução de nomes (AD/GLPI em hosts locais)

```yaml
services:
  glpiadmit:
    extra_hosts:
      - "dc01.empresa.local:192.168.1.10"
      - "glpi.empresa.local:192.168.1.20"
```

## Configuração rápida

### Pré-requisitos

- Acesso de rede do servidor ao AD (porta 636/LDAPS)
- Acesso de rede do servidor ao GLPI (porta 443/HTTPS)
- Acesso de rede do GLPI ao servidor (porta 80 — sem porta explícita por restrição do GLPI)
- Conta de serviço no AD com permissão de criação de usuários no OU
- API REST do GLPI habilitada com tokens configurados

### Variáveis de ambiente

```ini
# --- GLPI ---
GLPI_URL=https://glpi.suaempresa.com.br
GLPI_API_TOKEN=seu_user_token          # Preferências do usuário API > Token de API Remota
GLPI_APP_TOKEN=seu_app_token           # Configuração > Geral > API > Clientes API
GLPI_VERIFY_SSL=true

# --- Active Directory ---
AD_SERVER=ldaps://dc01.suaempresa.local
AD_DOMAIN=suaempresa.local
AD_BASE_DN=DC=suaempresa,DC=local
AD_USER_OU=OU=Usuarios,DC=suaempresa,DC=local
AD_BIND_USER=CN=svc-glpi-ad,OU=ServiceAccounts,DC=suaempresa,DC=local
AD_BIND_PASSWORD=SenhaSegura!

# --- Webhook ---
WEBHOOK_SECRET=chave-secreta-forte     # Mesma configurada no webhook do GLPI

# --- Logging ---
LOG_LEVEL=INFO
```

| Variável | Descrição | Obrigatório |
|---|---|---|
| `GLPI_URL` | URL base do GLPI (sem barra final) | Sim |
| `GLPI_API_TOKEN` | User Token do usuário API | Sim |
| `GLPI_APP_TOKEN` | App Token do cliente API | Sim |
| `GLPI_VERIFY_SSL` | Verificar SSL do GLPI (`true`/`false`) | Não (padrão: `true`) |
| `AD_SERVER` | Endereço do DC (**deve** começar com `ldaps://`) | Sim |
| `AD_DOMAIN` | Domínio AD (ex: `empresa.local`) | Sim |
| `AD_BASE_DN` | Base DN para buscas | Sim |
| `AD_USER_OU` | OU onde novos usuários serão criados | Sim |
| `AD_BIND_USER` | DN completo da conta de serviço | Sim |
| `AD_BIND_PASSWORD` | Senha da conta de serviço | Sim |
| `AD_DEFAULT_COMPANY` | Nome da empresa (atributo `company` no AD) | Não |
| `AD_VERIFY_CERT` | Verificar certificado LDAPS do AD (`true`/`false`) | Não (padrão: `true`) |
| `WEBHOOK_SECRET` | Chave secreta para validação HMAC do webhook | Sim* |
| `LOG_LEVEL` | Nível de log: `DEBUG`, `INFO`, `WARNING`, `ERROR` | Não |

*Se vazio, a validação é ignorada (apenas para desenvolvimento).

## API Reference

### `POST /webhook/glpi-native`

Endpoint principal. Recebe o **webhook nativo do GLPI 11** (evento `new` de Ticket).

**Headers enviados pelo GLPI:**
```
Content-Type: application/json
X-GLPI-signature: <hmac-sha256-hex>   (assinado com body + timestamp)
X-GLPI-timestamp: <unix-timestamp>
```

**Payload (gerado automaticamente pelo GLPI):**
```json
{
  "event": "new",
  "item": {
    "id": 9,
    "content": "<b>1) Nome</b>: Rafael<br><b>2) Sobrenome</b>: Silva<br>...",
    ...
  }
}
```

O serviço extrai os dados do campo `item.content` via `parse_ticket_content()`.

### `POST /webhook/user-creation`

Endpoint legado com payload JSON explícito (para integrações customizadas).

**Headers:**
```
Content-Type: application/json
X-GLPI-Signature: <hmac-sha256-hex>
```

**Body:**
```json
{
  "ticket_id": 123,
  "first_name": "Rafael",
  "last_name": "Silva",
  "email": "rafael.silva@empresa.com",
  "department": "TI",
  "title": "Analista",
  "groups": ["CN=GRP-TI,OU=Grupos,DC=empresa,DC=local"]
}
```

### `GET /health`

```json
{"status": "ok", "service": "glpi-ad-integration"}
```

**Códigos de resposta:**

| Código | Significado |
|---|---|
| `200` | Processado (verificar campo `status` para sucesso/erro/ignored) |
| `401` | Assinatura HMAC inválida |
| `422` | Payload JSON inválido |

## Convenção de nomenclatura

| Atributo | Regra | Exemplo |
|---|---|---|
| `sAMAccountName` | Primeira letra do nome + sobrenome, minúsculo, sem acentos (max 20) | `Rafael Silva` → `rsilva` |
| `userPrincipalName` | sAMAccountName + @domínio | `rsilva@empresa.local` |
| `displayName` | Nome + Sobrenome | `Rafael Silva` |

Acentos removidos automaticamente: `José Gonçalves` → `jgoncalves`, `André Müller` → `amuller`.

## Segurança

| Camada | Implementação |
|---|---|
| Comunicação AD | LDAPS obrigatório (porta 636, SSL/TLS) |
| Autenticação webhook | HMAC-SHA256 com `hmac(body + timestamp, secret)` — formato nativo GLPI 11 |
| Proteção LDAP | Sanitização de inputs conforme RFC 4514/4515 |
| Geração de senha | `secrets` (CSPRNG), mínimo 16 chars, troca obrigatória no primeiro login |
| Credenciais | Variáveis de ambiente (`.env` com `chmod 600`), nunca em código |
| Verificação SSL GLPI | Configurável via `GLPI_VERIFY_SSL` (padrão: `true`) |
| Processo | Usuário dedicado, `NoNewPrivileges`, `ProtectSystem=strict` (systemd) |
| Rollback | Falha parcial na criação aciona remoção automática do usuário |

## Testes unitários

```bash
pip install pytest pytest-asyncio pytest-cov httpx
pytest tests/ -v
pytest tests/ --cov=app --cov-report=term-missing
```

**76 testes, ~92% de cobertura:**

| Módulo | Abordagem |
|---|---|
| `test_validators.py` | Testes puros (sem mock) |
| `test_password.py` | Testes puros (sem mock) |
| `test_ad_service.py` | Mock via `connection_factory` |
| `test_glpi_service.py` | Testes puros (followup HTML, status) |
| `test_webhook.py` | TestClient com serviços mockados |

## Configuração do GLPI

1. **Habilitar API REST** — Configuração > Geral > API
2. **Criar usuário API** — com permissão para ler/atualizar tickets e adicionar followups
3. **Criar formulário** — "Solicitar Criação de Usuário AD" com campos Nome, Sobrenome, E-mail corporativo, Departamento, Cargo, Grupo AD
4. **Publicar no Catálogo de Serviços** — ativar controle de acesso "Todos os usuários"
5. **Configurar webhook** — evento `new` do Ticket, URL sem porta explícita, secret criptografado com GLPIKey

> **Automação**: use `tests/docker/glpi-create-form.php` e `tests/docker/glpi-create-webhook.php` como referência para o setup em produção.

Ver [docs/03-configuracao-glpi.md](docs/03-configuracao-glpi.md) para passo a passo detalhado.

## Configuração do AD

1. Criar OU dedicada para novos usuários
2. Criar conta de serviço com permissão delegada na OU
3. Garantir que LDAPS (porta 636) está habilitado com certificado válido
4. Configurar Entra Connect para sincronizar a OU

Ver [docs/04-configuracao-ad.md](docs/04-configuracao-ad.md) para instruções detalhadas.

## Documentação

| Documento | Conteúdo |
|---|---|
| [01-visao-geral.md](docs/01-visao-geral.md) | Arquitetura e fluxo |
| [02-instalacao.md](docs/02-instalacao.md) | Instalação e deploy |
| [03-configuracao-glpi.md](docs/03-configuracao-glpi.md) | Configuração do GLPI (formulário, webhook, API) |
| [04-configuracao-ad.md](docs/04-configuracao-ad.md) | Configuração do Active Directory |
| [05-uso-operacao.md](docs/05-uso-operacao.md) | Uso e operação do sistema |
| [06-seguranca.md](docs/06-seguranca.md) | Detalhes de segurança |
| [07-troubleshooting.md](docs/07-troubleshooting.md) | Diagnóstico e solução de problemas |
| [08-guia-desenvolvimento.md](docs/08-guia-desenvolvimento.md) | Guia para desenvolvedores |

## Roadmap

- [x] Webhook nativo GLPI 11 (`/webhook/glpi-native`)
- [x] Ambiente de teste completo com Docker (GLPI + Samba AD)
- [x] Catálogo de Serviços no GLPI
- [ ] CI/CD — Pipeline GitHub Actions (lint, testes, build)
- [ ] Desativação de usuários — webhook para desabilitar contas AD
- [ ] Reset de senha — webhook para reset via chamado GLPI
- [ ] Notificações por e-mail ao gestor/usuário

## Licença

MIT
