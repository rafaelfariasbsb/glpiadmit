# Guia de Desenvolvimento

Guia técnico para desenvolvedores que precisam entender, modificar ou estender o GLPIADmit.

---

## Sumário

1. [Ambiente de desenvolvimento](#1-ambiente-de-desenvolvimento)
2. [Arquitetura do código](#2-arquitetura-do-código)
3. [Fluxo de execução](#3-fluxo-de-execução)
4. [Detalhamento dos módulos](#4-detalhamento-dos-módulos)
5. [Padrões e convenções](#5-padrões-e-convenções)
6. [Testes](#6-testes)
7. [Como adicionar novas funcionalidades](#7-como-adicionar-novas-funcionalidades)
8. [Debug e desenvolvimento local](#8-debug-e-desenvolvimento-local)
9. [Ambiente de teste integrado](#9-ambiente-de-teste-integrado)
10. [Referência da API](#10-referência-da-api)

---

## 1. Ambiente de desenvolvimento

### Requisitos

- Python 3.11+ **ou** Docker Engine 24+
- Git

### Setup — ambiente virtual Python

```bash
git clone <repositorio> glpiadmit
cd glpiadmit

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov httpx

cp .env.example .env
```

### Executar em desenvolvimento

```bash
# Com hot-reload
uvicorn app.main:app --host 0.0.0.0 --port 8443 --reload

# Endpoints:
# Health:    http://localhost:8443/health
# Docs:      http://localhost:8443/docs
# ReDoc:     http://localhost:8443/redoc
```

### Ambiente de teste completo (recomendado)

Para testar o fluxo real com GLPI e AD:

```bash
bash tests/docker/setup-test-env.sh
```

Isso sobe GLPI 11, Samba AD DC e GLPIADmit automaticamente. Ver seção 9 para detalhes.

---

## 2. Arquitetura do código

### Diagrama de dependências

```
app/main.py
 └── app/routes/webhook.py              ← Entrada HTTP
      ├── app/services/ad_service.py    ← Lógica de criação no AD
      │    ├── app/utils/validators.py
      │    ├── app/utils/password.py
      │    └── app/config.py
      └── app/services/glpi_service.py  ← Feedback no chamado GLPI
           └── app/config.py
```

### Princípios de design

| Princípio | Aplicação |
|---|---|
| **Separação de responsabilidades** | Rota, serviço AD, serviço GLPI, validadores e config são módulos distintos |
| **Injeção de dependência** | `ADService` recebe `connection_factory` no construtor; webhook usa `Depends(get_settings)` |
| **Configuração centralizada** | Todas as variáveis em `config.py` via `pydantic-settings` + `@lru_cache` |
| **Validação na borda** | Pydantic valida o payload na entrada; lógica interna confia nos dados |
| **Fail-safe com rollback** | Criação parcialmente falha → `ADService._rollback_user()` remove o objeto |

---

## 3. Fluxo de execução

### Endpoint `/webhook/glpi-native` (principal)

```
POST /webhook/glpi-native
│
├── 1. Lê body e headers (X-GLPI-signature, X-GLPI-timestamp)
│
├── 2. _verify_webhook_signature()
│   ├── Tenta: hmac(body + timestamp, secret)  ← formato GLPI 11
│   ├── Fallback: hmac(body, secret)
│   └── Inválido → HTTP 401
│
├── 3. Parseia JSON → extrai event + item
│   └── item.id ausente → HTTP 422
│
├── 4. GLPIService.parse_ticket_content(item)  [estático]
│   ├── Regex no item.content: <b>N) Label</b>: Valor
│   ├── Verifica campos obrigatórios: nome, sobrenome, e-mail corporativo
│   └── None → retorna WebhookResponse(status="ignored")
│
├── 5. ADService.create_user(payload)
│   ├── 5.1 connection_factory()    → conexão LDAPS
│   ├── 5.2 _generate_attributes()  → sAMAccountName, UPN, CN, DN, senha
│   ├── 5.3 _check_user_exists()    → verifica duplicidade (sAM ou UPN)
│   ├── 5.4 _create_ad_object()     → cria desabilitado (UAC=514)
│   ├── 5.5 _configure_account()    → define senha + pwdLastSet=0 + habilita (512)
│   ├── 5.6 _add_to_groups()        → adiciona ao grupo AD
│   └── 5.7 (se erro) _rollback_user() → remove objeto (flag user_created)
│
├── 6. GLPIService.update_ticket(result)
│   ├── 6.1 _init_session()             → initSession + changeActiveProfile
│   ├── 6.2 _add_followup()             → POST ITILFollowup (credenciais ou erro)
│   ├── 6.3 _update_ticket_status()     → PUT Ticket/{id} → status 5 ou 4
│   └── 6.4 _kill_session()             → killSession
│
└── 7. Retorna WebhookResponse {"status": "success"|"error", ...}
```

### Endpoint `/webhook/user-creation` (legado)

Mesmo fluxo, mas sem o parse de conteúdo do ticket — recebe payload JSON explícito com os dados do usuário.

---

## 4. Detalhamento dos módulos

### `app/config.py`

`pydantic-settings` com cache `@lru_cache`:

```python
settings = get_settings()
settings.ad_domain_suffix   # "@empresa.local" (property computada)
settings.ad_use_ssl         # True (detecta "ldaps://")
settings.glpi_verify_ssl    # True
```

**Para adicionar configuração**: adicione campo na classe `Settings`, adicione ao `.env.example`, use `get_settings().nova_var` no código, use `get_settings.cache_clear()` nos testes.

### `app/models.py`

| Modelo | Uso | Campos |
|---|---|---|
| `UserCreationPayload` | Entrada | `ticket_id`, `first_name`, `last_name`, `email`, `department`, `title`, `groups` |
| `UserCreationResult` | Interno | `success`, `ticket_id`, `sam_account_name`, `user_principal_name`, `display_name`, `temporary_password`, `distinguished_name`, `groups_added`, `message`, `errors` |
| `WebhookResponse` | Saída HTTP | `status`, `message`, `ticket_id` |

Validadores no `UserCreationPayload`:
- `not_empty`: `first_name`, `last_name`, `department`, `title`
- `email: EmailStr`: validação completa de email
- `sanitize_phone`: remove caracteres não numéricos (campo legado)

### `app/services/glpi_service.py`

| Método | Descrição |
|---|---|
| `_init_session(client)` | `GET /initSession` → session_token, depois `changeActiveProfile` para maior privilégio |
| `_kill_session(client)` | `GET /killSession` |
| `_build_followup_content(result)` | `@staticmethod` — monta HTML do followup (sucesso ou erro) |
| `_add_followup(client, result)` | `POST /ITILFollowup` |
| `_update_ticket_status(client, result)` | `PUT /Ticket/{id}` → status `TicketStatus.SOLVED` (5) ou `TicketStatus.PENDING` (4) |
| `_do_update_ticket(result)` | Abre sessão, executa followup + status, fecha sessão |
| `update_ticket(result)` | Orquestra retry + `_do_update_ticket` — até 3 tentativas com backoff exponencial |
| `parse_ticket_content(item)` | `@staticmethod` — extrai dados do HTML do ticket via regex |

**`parse_ticket_content(item)`** — usa pattern compilado em nível de módulo:

```python
# Compilado uma única vez no carregamento do módulo:
_FORM_PATTERN = re.compile(r"<b>\d+\)\s*([^<]+)</b>\s*:\s*([^<]+)", re.IGNORECASE)

# Labels esperados (case-insensitive, strip):
required = {"nome", "sobrenome", "e-mail corporativo"}
# Opcionais: "departamento", "cargo", "grupo ad"
```

**`_init_session()`** — ativa o maior perfil disponível:

```python
priority = {"super-admin": 0, "admin": 1}
best = min(profiles, key=lambda p: priority.get(p["name"].lower(), 99))
await client.post(".../changeActiveProfile", json={"profiles_id": best["id"]})
```

**Status ITIL (`TicketStatus` IntEnum):**
```python
class TicketStatus(IntEnum):
    PENDING = 4   # Pendente (erro)
    SOLVED  = 5   # Resolvido (sucesso)
```

**Retry em `update_ticket`:**
```python
# Até 3 tentativas com backoff exponencial (2s, 4s, 8s) em caso de httpx.HTTPError
async for attempt in AsyncRetrying(stop=stop_after_attempt(3), ...):
    with attempt:
        await self._do_update_ticket(result)
# Após 3 falhas: loga erro, não propaga exceção ao caller
```

### `app/services/ad_service.py`

Ordem de operações (importante — cada etapa depende da anterior):

```
1. Criar desabilitado (UAC=514)  → evita conta ativa sem senha
2. Definir senha (unicodePwd)    → exige LDAPS
3. Forçar troca (pwdLastSet=0)
4. Habilitar (UAC=512)           → só após senha definida
5. Adicionar a grupos            → operação independente
```

Constantes:
```python
UAC_NORMAL_ACCOUNT   = 512  # Conta habilitada
UAC_DISABLED_ACCOUNT = 514  # Conta desabilitada (512 | 2)
```

### `app/routes/webhook.py`

**`_execute_user_creation(payload)`** — orquestrador compartilhado:

Ambos os endpoints (`/webhook/glpi-native` e `/webhook/user-creation`) delegam para esta função após validar a assinatura e parsear o payload. Centraliza a lógica: cria usuário no AD → atualiza chamado no GLPI.

**`_verify_webhook_signature(payload_body, signature, secret, timestamp=None)`:**

```python
# 1. GLPI 11 nativo: hmac(body + timestamp, secret)
if timestamp:
    data_with_ts = payload_body + timestamp.encode()
    expected_ts = hmac.new(secret.encode(), data_with_ts, hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected_ts, signature):
        return True

# 2. Fallback legado: hmac(body, secret)
expected = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
return hmac.compare_digest(expected, signature)
```

Headers lidos no endpoint nativo:
```python
signature = request.headers.get("X-GLPI-signature")   # 's' minúsculo!
timestamp  = request.headers.get("X-GLPI-timestamp")
```

### `app/utils/validators.py`

| Função | Exemplo |
|---|---|
| `normalize_name("José")` | `"Jose"` |
| `generate_sam_account_name("Rafael", "Silva")` | `"rsilva"` |
| `generate_upn("rsilva", "empresa.local")` | `"rsilva@empresa.local"` |
| `sanitize_ldap_value("test*")` | `"test\\2a"` |
| `sanitize_dn_component("Silva, Jr")` | `"Silva\\, Jr"` |

### `app/utils/password.py`

`generate_temporary_password(length=16)`:
- `secrets` (CSPRNG)
- Garante: ≥1 maiúscula, ≥1 minúscula, ≥1 dígito, ≥1 especial (`!@#$%&*`)
- Mínimo 12 chars (forçado)

---

## 5. Padrões e convenções

### Nomenclatura

| Elemento | Convenção |
|---|---|
| Arquivos | `snake_case.py` |
| Classes | `PascalCase` |
| Funções/métodos | `snake_case()` |
| Métodos privados | `_snake_case()` |
| Constantes | `UPPER_SNAKE_CASE` |
| Variáveis de ambiente | `UPPER_SNAKE_CASE` |

### Logging

```python
logger = logging.getLogger(__name__)

logger.debug(...)    # Campos extraídos, detalhes de sessão
logger.info(...)     # Operações normais (criação, followup)
logger.warning(...)  # Recuperável (webhook sem secret, falha em grupo)
logger.error(...)    # Falhas (conexão AD, erro API GLPI)
```

### Tratamento de erros

1. Operações LDAP dentro de `try/except LDAPException`
2. Operações HTTP dentro de `try/except httpx.HTTPError`
3. Erros acumulados em `result.errors[]`
4. `result.success = False` + mensagem descritiva
5. Rollback quando possível
6. Chamado GLPI sempre atualizado (mesmo em erro)

---

## 6. Testes

### Executar

```bash
pytest tests/ -v
pytest tests/ --cov=app --cov-report=term-missing

# Módulo específico:
pytest tests/test_validators.py -v
pytest tests/test_ad_service.py -v
```

### Abordagem por módulo

| Módulo | Tipo | Mocks |
|---|---|---|
| `test_validators.py` | Unitário puro | Nenhum |
| `test_password.py` | Unitário puro | Nenhum |
| `test_ad_service.py` | Unitário com mock | `ldap3.Connection` via `connection_factory` |
| `test_glpi_service.py` | Unitário puro | Nenhum (testa `_build_followup_content`, status) |
| `test_webhook.py` | Integração | `ADService` e `GLPIService` mockados, HTTP via `TestClient` |

### Padrão para mockar o AD

```python
class TestNovaFuncionalidade:
    def _make_service(self, mock_connection):
        return ADService(connection_factory=lambda: mock_connection)

    def test_cenario_sucesso(self, sample_payload, mock_ldap_connection):
        service = self._make_service(mock_ldap_connection)
        result = service.create_user(sample_payload)
        assert result.success is True

    def test_cenario_falha_conexao(self, sample_payload):
        service = ADService(connection_factory=lambda: (_ for _ in ()).throw(LDAPException("erro")))
        result = service.create_user(sample_payload)
        assert result.success is False
```

---

## 7. Como adicionar novas funcionalidades

### Novo campo no formulário

1. **`app/models.py`** — adicionar campo opcional:
   ```python
   manager_dn: str = ""  # DN do gestor no AD
   ```

2. **`app/services/ad_service.py`** — mapear para atributo AD:
   ```python
   if payload.manager_dn:
       ad_attributes["manager"] = payload.manager_dn
   ```

3. **`app/services/glpi_service.py`** — incluir no `parse_ticket_content` se vier do formulário, e no followup se relevante

4. **`tests/docker/glpi-create-form.php`** — adicionar pergunta ao formulário

5. **`tests/`** — atualizar fixtures e adicionar testes

### Novo endpoint (ex: desativação de usuário)

1. Adicionar rota em `app/routes/webhook.py`:
   ```python
   @router.post("/user-disable", response_model=WebhookResponse)
   async def handle_user_disable(request: Request, settings: Settings = Depends(get_settings)):
       ...
   ```

2. Adicionar método em `ADService`:
   ```python
   def disable_user(self, sam_account_name: str) -> UserCreationResult:
       ...
   ```

3. Adicionar testes

### Alterar regra de nomenclatura

Editar `app/utils/validators.py`, função `generate_sam_account_name()`:

```python
# Formato alternativo: nome.sobrenome
sam = f"{first}.{last}"[:20]

# Formato alternativo: sobrenome + inicial
sam = f"{last}{first[0]}"[:20]
```

Lembrete: max 20 chars, apenas `[a-z0-9._-]`.

---

## 8. Debug e desenvolvimento local

### Testar webhook nativo manualmente

```bash
# Gerar assinatura no formato GLPI (body + timestamp)
SECRET="test-webhook-secret-2024"
TIMESTAMP=$(date +%s)
BODY='{"event":"new","item":{"id":99,"content":"<b>1) Nome</b>: Teste<br><b>2) Sobrenome</b>: Dev<br><b>3) E-mail corporativo</b>: teste@empresa.com<br><b>4) Departamento</b>: TI<br><b>5) Cargo</b>: Dev<br><b>6) Grupo AD</b>: <br>"}}'

SIG=$(echo -n "${BODY}${TIMESTAMP}" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -X POST http://localhost:8443/webhook/glpi-native \
  -H "Content-Type: application/json" \
  -H "X-GLPI-signature: $SIG" \
  -H "X-GLPI-timestamp: $TIMESTAMP" \
  -d "$BODY"
```

### Testar endpoint legado

```python
import hmac, hashlib

payload = '{"ticket_id":999,"first_name":"Teste","last_name":"Dev","email":"t@e.com","department":"TI","title":"Dev"}'
secret = "minha-chave"
sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
print(sig)
```

### Ativar logs de debug

```ini
# .env
LOG_LEVEL=DEBUG
```

### Simular AD sem servidor real

```python
from unittest.mock import MagicMock
from app.services.ad_service import ADService

mock_conn = MagicMock()
mock_conn.entries = []  # Sem duplicidade
mock_conn.extend.microsoft.add_members_to_groups = MagicMock()

service = ADService(connection_factory=lambda: mock_conn)
result = service.create_user(payload)
```

---

## 9. Ambiente de teste integrado

O projeto inclui um ambiente completo de teste com GLPI 11, Samba AD DC e MariaDB.

### Subir o ambiente

```bash
bash tests/docker/setup-test-env.sh
```

### Serviços e credenciais

| Serviço | URL | Credenciais |
|---|---|---|
| GLPI | `http://localhost:8080` | `glpi / glpi` |
| GLPIADmit health | `http://localhost:8443/health` | — |
| Samba AD | `ldaps://localhost:636` | `Administrator / Admin@Teste123` |
| Conta de serviço | — | `svc-glpi-ad / SvcGlpi@Test123!` |

**Domínio de teste**: `TESTE.LOCAL`
**Grupo de teste**: `CN=GRP-TI,OU=Grupos,DC=teste,DC=local`

### Scripts de configuração

| Script | Função |
|---|---|
| `setup-test-env.sh` | Orquestra tudo — sobe containers, instala GLPI, configura API, cria formulário, webhook e GLPIADmit |
| `glpi-setup-api.php` | Habilita REST API, gera tokens (criptografados com GLPIKey) |
| `glpi-create-form.php` | Cria formulário no Catálogo de Serviços (idempotente — atualiza se já existir) |
| `glpi-create-webhook.php` | Configura webhook com secret criptografado com GLPIKey |
| `init-samba.sh` | Cria OUs, conta de serviço, grupo GRP-TI no Samba AD |

### Retry logic (tenacity)

O projeto usa `tenacity==8.5.0` para resiliência em falhas transientes:

| Onde | Trigger | Tentativas | Backoff |
|---|---|---|---|
| `_build_connection()` em `ad_service.py` | `LDAPException` | 3 | exponencial 2s→10s |
| `update_ticket()` em `glpi_service.py` | `httpx.HTTPError` | 3 | exponencial 2s→10s |

Cada tentativa intermediária é logada em `WARNING`. Após esgotar as tentativas, a exceção é tratada localmente (sem propagar para o endpoint).

---

### Caveats do ambiente de teste

- **Tokens GLPI são regenerados** a cada execução do `setup-test-env.sh`. Se o script for rodado novamente com containers já ativos, os tokens mudam mas o GLPIADmit fica com os antigos → use `up -d --force-recreate glpiadmit` para atualizar.
- **`docker compose restart` não relê `env_file`** — use sempre `up -d --force-recreate`.
- **URL do webhook sem porta**: o GLPI bloqueia `http://servidor:8443/...` → o GLPIADmit escuta na porta 80 internamente (mapeada para 8443 externamente).

---

## 10. Referência da API

### Endpoints

| Método | Path | Descrição | Auth |
|---|---|---|---|
| `GET` | `/health` | Health check | Nenhuma |
| `GET` | `/docs` | Swagger UI | Nenhuma |
| `GET` | `/redoc` | ReDoc | Nenhuma |
| `POST` | `/webhook/glpi-native` | Webhook nativo GLPI 11 | HMAC (`X-GLPI-signature` + `X-GLPI-timestamp`) |
| `POST` | `/webhook/user-creation` | Webhook legado | HMAC (`X-GLPI-Signature`) |

### POST /webhook/glpi-native

**Headers (enviados pelo GLPI):**
```
Content-Type: application/json
X-GLPI-signature: <hmac-sha256>     # 's' minúsculo
X-GLPI-timestamp: <unix-timestamp>
```

**Body (payload nativo do GLPI):**
```json
{
  "event": "new",
  "item": {
    "id": 9,
    "name": "Solicitar Criação de Usuário AD",
    "content": "<b>1) Nome</b>: Rafael<br><b>2) Sobrenome</b>: Silva<br>..."
  }
}
```

**Response (200):**
```json
{"status": "success", "message": "...", "ticket_id": 9}
{"status": "error",   "message": "...", "ticket_id": 9}
{"status": "ignored", "message": "Ticket #9 nao originou de formulario...", "ticket_id": 9}
```

### POST /webhook/user-creation

**Headers:**
```
Content-Type: application/json
X-GLPI-Signature: <hmac-sha256>     # 'S' maiúsculo (legado)
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

### Códigos de resposta

| Código | Significado |
|---|---|
| `200` | Processado — verificar campo `status` |
| `401` | Assinatura HMAC inválida |
| `422` | Payload inválido (campos faltando ou formato errado) |
