# Guia de Desenvolvimento

Guia técnico para desenvolvedores que precisam entender, modificar ou estender o projeto de integração GLPI + Active Directory.

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
9. [Referência da API](#9-referência-da-api)

---

## 1. Ambiente de desenvolvimento

### Requisitos

- Python 3.11+
- pip ou pipenv
- Git
- Acesso a um AD de teste (opcional, pode usar mocks)

### Setup inicial

```bash
# Clonar o repositório
git clone <repositorio> integracao_glpi
cd integracao_glpi

# Criar ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependências
pip install -r requirements.txt

# Instalar dependências de desenvolvimento
pip install pytest pytest-asyncio pytest-cov httpx
```

### Configuração local

```bash
cp .env.example .env
```

Para desenvolvimento local, edite o `.env` com valores de teste. Se não tiver AD disponível, os testes unitários usam mocks e não precisam de conexão real.

### Executar o servidor em modo desenvolvimento

```bash
# Com hot-reload (recarrega ao salvar arquivos)
uvicorn app.main:app --host 0.0.0.0 --port 8443 --reload

# Acessar documentação interativa
# Swagger UI:  http://localhost:8443/docs
# ReDoc:       http://localhost:8443/redoc
# Health:      http://localhost:8443/health
```

---

## 2. Arquitetura do código

### Diagrama de dependências

```
app/main.py
 └── app/routes/webhook.py          ← Entrada HTTP (endpoint)
      ├── app/services/ad_service.py ← Lógica de criação no AD
      │    ├── app/utils/validators.py
      │    ├── app/utils/password.py
      │    └── app/config.py
      └── app/services/glpi_service.py ← Feedback no chamado GLPI
           └── app/config.py
```

### Princípios de design

| Princípio | Aplicação |
|---|---|
| **Separação de responsabilidades** | Cada módulo tem um papel único: rota, serviço AD, serviço GLPI, validadores, config |
| **Injeção de dependência** | `ADService` recebe `connection_factory` no construtor; webhook usa `Depends(get_settings)` do FastAPI |
| **Configuração centralizada** | Todas as variáveis ficam em `config.py` via `pydantic-settings` + `@lru_cache`, sem valores espalhados |
| **Validação na borda** | Pydantic valida o payload na entrada (`models.py` com `EmailStr`); a lógica interna confia nos dados já validados |
| **Fail-safe com rollback** | Se a criação do usuário falha parcialmente, o `ADService` faz rollback (remove). Usa flag `user_created` para evitar rollback indevido |

---

## 3. Fluxo de execução

### Fluxo completo de um webhook recebido

```
POST /webhook/user-creation
│
├── 1. webhook.py: verify_webhook_signature()
│   └── Valida HMAC-SHA256 do header X-GLPI-Signature
│       ├── Inválido → HTTP 401
│       └── Válido → continua
│
├── 2. webhook.py: parseia JSON → UserCreationPayload (Pydantic)
│   └── Validação automática dos campos (not_empty, email, phone)
│       ├── Inválido → HTTP 422
│       └── Válido → continua
│
├── 3. ad_service.py: create_user(payload)
│   ├── 3.1 connection_factory()    → Conexão LDAPS com AD (injetável)
│   ├── 3.2 _generate_attributes()  → sAMAccountName, UPN, CN, DN (via validators.py)
│   ├── 3.3 _check_user_exists()    → Busca duplicidade por sAM ou UPN
│   ├── 3.4 _create_ad_object()     → Cria usuário desabilitado (UAC=514)
│   ├── 3.5 _configure_account()    → Define senha + pwdLastSet=0 + habilita (512)
│   ├── 3.6 _add_to_groups()        → Adiciona a cada grupo
│   └── 3.7 (se erro) _rollback_user() → Remove (flag user_created)
│       └── Retorna UserCreationResult
│
├── 4. glpi_service.py: update_ticket(result)
│   ├── 4.1 _init_session()          → Obtém session_token da API GLPI
│   ├── 4.2 _add_followup()          → POST ITILFollowup (credenciais ou erro)
│   ├── 4.3 _update_ticket_status()  → PUT Ticket/{id} → Status 5 ou 4
│   └── 4.4 _kill_session()          → Encerra sessão GLPI
│
└── 5. webhook.py: retorna WebhookResponse (JSON)
    └── {"status": "success"|"error", "message": "...", "ticket_id": N}
```

---

## 4. Detalhamento dos módulos

### `app/config.py` — Configurações

Usa `pydantic-settings` para carregar variáveis do `.env` com tipagem e validação. A instância é cacheada via `@lru_cache` (padrão singleton).

```python
from app.config import get_settings

settings = get_settings()
settings.ad_server          # "ldaps://dc01.empresa.local"
settings.ad_domain_suffix   # "@empresa.local" (property computada)
settings.ad_use_ssl         # True (property computada, detecta "ldaps://")
settings.glpi_verify_ssl    # True (verificação de certificado SSL do GLPI)
settings.log_level          # "INFO"
```

**Properties computadas:**
- `ad_domain_suffix` — retorna `@{ad_domain}` (ex: `@empresa.local`)
- `ad_use_ssl` — retorna `True` se `ad_server` começa com `ldaps://`

**Adicionar nova configuração:**
1. Adicione o atributo na classe `Settings` com tipo e valor padrão
2. Adicione a variável no `.env.example`
3. Use `get_settings().nova_variavel` onde precisar
4. Em testes, use `get_settings.cache_clear()` para resetar o cache

### `app/models.py` — Modelos de dados

Três modelos Pydantic:

| Modelo | Uso | Campos-chave |
|---|---|---|
| `UserCreationPayload` | Entrada — payload do webhook | `ticket_id`, `first_name`, `last_name`, `email`, `department`, `title`, `phone`, `manager`, `groups` |
| `UserCreationResult` | Interno — resultado da operação AD | `success`, `sam_account_name`, `temporary_password`, `errors` |
| `WebhookResponse` | Saída — resposta HTTP ao GLPI | `status`, `message`, `ticket_id` |

**Validadores ativos no `UserCreationPayload`:**
- `not_empty`: `first_name`, `last_name`, `department`, `title` não podem ser vazios (rejeita strings com apenas espaços)
- `email: EmailStr`: validação de email via Pydantic/email-validator (substitui regex manual)
- `sanitize_phone`: remove caracteres não numéricos do telefone

**Adicionar novo campo ao payload:**
1. Adicione o campo na classe `UserCreationPayload` (com valor padrão se opcional)
2. Se precisar de validação, adicione um `@field_validator`
3. Use o campo em `ad_service.py` no dicionário `attributes`
4. Atualize o `UserCreationResult` se o campo deve ser retornado
5. Atualize os testes

### `app/services/ad_service.py` — Serviço Active Directory

Classe `ADService` com injeção de `connection_factory` para facilitar testes:

```python
# Produção (usa _build_connection padrão)
service = ADService()

# Testes (injeta mock)
service = ADService(connection_factory=lambda: mock_connection)
```

**Funções de módulo (fora da classe):**

| Função | Responsabilidade |
|---|---|
| `_build_connection()` | Factory padrão — cria conexão LDAPS com o AD via `ldap3` |
| `_generate_attributes(payload)` | Gera sAMAccountName, UPN, CN, DN, senha temporária. Retorna `_UserAttributes` |

**Métodos da classe `ADService`:**

| Método | Responsabilidade |
|---|---|
| `_check_user_exists(conn, sam, upn)` | Busca no AD por sAMAccountName ou UPN duplicado |
| `_set_password(conn, dn, password)` | Define senha via `unicodePwd` (UTF-16-LE, entre aspas) |
| `_configure_account(conn, dn, password)` | Define senha + `pwdLastSet=0` + habilita conta (UAC=512) |
| `_add_to_groups(conn, dn, groups)` | Itera grupos e adiciona via extensão Microsoft do ldap3 |
| `_rollback_user(conn, dn)` | Remove o usuário em caso de falha |
| `_create_ad_object(conn, attrs, payload)` | Cria o objeto usuário no AD (desabilitado, UAC=514) |
| `create_user(payload)` | Método público — orquestra todo o fluxo. Retorna `UserCreationResult` |

**Constantes:**
```python
UAC_NORMAL_ACCOUNT = 512    # Conta habilitada
UAC_DISABLED_ACCOUNT = 514  # Conta desabilitada
```

**Ordem das operações é importante:**
1. Criar desabilitado (514) — evita janela de conta ativa sem senha
2. Definir senha — requer LDAPS
3. Forçar troca — `pwdLastSet = 0`
4. Habilitar (512) — só após senha definida
5. Adicionar a grupos — operação independente

### `app/services/glpi_service.py` — Serviço GLPI

Classe `GLPIService` com comunicação assíncrona via `httpx`. Verificação de SSL configurável via `GLPI_VERIFY_SSL`.

| Método | Responsabilidade |
|---|---|
| `_headers(with_session)` | Monta headers base (App-Token, Session-Token) centralizados |
| `_init_session(client)` | `GET /initSession` — obtém `session_token` |
| `_kill_session(client)` | `GET /killSession` — encerra sessão |
| `_build_followup_content(result)` | `@staticmethod` — monta HTML do followup (sucesso ou erro) |
| `_add_followup(client, result)` | `POST /ITILFollowup` — adiciona followup ao chamado |
| `_update_ticket_status(client, result)` | `PUT /Ticket/{id}` — altera status do chamado |
| `update_ticket(result)` | Método público — orquestra followup + status + sessão |

**Constantes de status:**
```python
_STATUS_PENDING = 4   # Pendente (erro — aguarda ação manual)
_STATUS_SOLVED = 5    # Resolvido (sucesso)
```

**Endpoint da API GLPI:**
```
POST /apirest.php/ITILFollowup    → Adiciona followup
PUT  /apirest.php/Ticket/{id}     → Atualiza status
```

### `app/utils/validators.py` — Validação e sanitização

| Função | Entrada | Saída | Exemplo |
|---|---|---|---|
| `normalize_name(name)` | String com acentos | String ASCII | `"José"` → `"Jose"` |
| `generate_sam_account_name(first, last)` | Nome e sobrenome | sAMAccountName (max 20) | `"Rafael", "Silva"` → `"rsilva"` |
| `generate_upn(sam, domain)` | sAM + domínio | UPN | `"rsilva", "empresa.local"` → `"rsilva@empresa.local"` |
| `generate_display_name(first, last)` | Nome e sobrenome | Display name | `"Rafael", "Silva"` → `"Rafael Silva"` |
| `generate_cn(first, last)` | Nome e sobrenome | Common Name | Mesmo que `display_name` |
| `sanitize_ldap_value(value)` | String bruta | String escapada para filtro LDAP | `"test*"` → `"test\\2a"` |
| `sanitize_dn_component(value)` | String bruta | String escapada para DN | `"Silva, Jr"` → `"Silva\\, Jr"` |

**Regra de nomenclatura do sAMAccountName:**
- Primeira letra do primeiro nome + primeiro sobrenome
- Tudo minúsculo, sem acentos, max 20 caracteres
- Regex final remove qualquer caractere inválido: `[^a-z0-9._-]`

### `app/utils/password.py` — Geração de senha

Função `generate_temporary_password(length=16)`:
- Usa `secrets` (CSPRNG — criptograficamente seguro)
- Garante pelo menos 1 maiúscula, 1 minúscula, 1 dígito, 1 especial (`!@#$%&*`)
- Mínimo 12 caracteres (forçado mesmo se `length < 12`)
- Caracteres embaralhados com `secrets.SystemRandom().shuffle()`

### `app/routes/webhook.py` — Endpoint HTTP

Rota `POST /webhook/user-creation`:
- Prefixo do router: `/webhook`
- Tag OpenAPI: `webhook`
- Modelo de resposta: `WebhookResponse`
- Settings injetado via `Depends(get_settings)` (facilita testes com `dependency_overrides`)
- Captura `ValidationError` específico do Pydantic (não `Exception` genérico)

Função auxiliar `_verify_webhook_signature(body, signature, secret)`:
- Se `WEBHOOK_SECRET` não está configurado: aceita (com warning no log)
- Compara HMAC-SHA256 com `hmac.compare_digest()` (constant-time, previne timing attack)
- Header esperado: `X-GLPI-Signature`

### `app/main.py` — Aplicação FastAPI

- Usa `lifespan` async context manager (substituindo o deprecated `@app.on_event`)
- Logging configurado no startup via `_setup_logging()` (não mais como efeito colateral no `config.py`)
- Registra o router de webhook
- Endpoint `GET /health` para monitoramento

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    logger.info("Servico de integracao GLPI-AD iniciado")
    yield
    logger.info("Servico de integracao GLPI-AD encerrado")

app = FastAPI(title="...", version="1.0.0", lifespan=lifespan)
```

---

## 5. Padrões e convenções

### Nomenclatura

| Elemento | Convenção | Exemplo |
|---|---|---|
| Arquivos | snake_case | `ad_service.py` |
| Classes | PascalCase | `ADService`, `GLPIService` |
| Funções/métodos | snake_case | `create_user()`, `_set_password()` |
| Constantes | UPPER_SNAKE_CASE | `UAC_NORMAL_ACCOUNT` |
| Variáveis de ambiente | UPPER_SNAKE_CASE | `AD_BIND_PASSWORD` |
| Métodos privados | Prefixo `_` | `_connect()`, `_rollback_user()` |

### Logging

Cada módulo cria seu próprio logger:

```python
import logging
logger = logging.getLogger(__name__)
```

Níveis usados:
- `logger.info()` — Operações normais (conexão, criação, etc.)
- `logger.warning()` — Situações recuperáveis (duplicidade, webhook sem secret)
- `logger.error()` — Falhas (conexão recusada, erro LDAP, erro API GLPI)

Formato configurado em `main.py` (via `_setup_logging()` no lifespan):
```
2026-02-25 14:30:00 [INFO] app.services.ad_service: Usuário criado com sucesso: rsilva (ticket #123)
```

### Tratamento de erros

Padrão seguido:
1. Operações LDAP dentro de `try/except LDAPException`
2. Operações HTTP dentro de `try/except httpx.HTTPError`
3. Erros registrados em `result.errors[]` (lista cumulativa)
4. `result.success = False` + mensagem descritiva
5. Rollback quando possível
6. Chamado GLPI sempre atualizado (mesmo em erro)

### Segurança

- Inputs sanitizados com `sanitize_ldap_value()` e `sanitize_dn_component()`
- Senha via `secrets` (não `random`)
- HMAC com `compare_digest()` (constant-time)
- Password encoding: `f'"{password}"'.encode("utf-16-le")` (requisito do AD)

---

## 6. Testes

### Estrutura de testes

```
tests/
├── conftest.py              ← Fixtures compartilhadas (settings, payloads, mocks)
├── test_validators.py       ← Testes de validação/sanitização (puros, sem mock)
├── test_password.py         ← Testes de geração de senha (puros)
├── test_ad_service.py       ← Testes do serviço AD (com mock do ldap3)
├── test_glpi_service.py     ← Testes do serviço GLPI (conteúdo e status)
└── test_webhook.py          ← Testes do endpoint HTTP (com mock de serviços)
```

**Cobertura atual: 60 testes, ~92% de cobertura.**

### Executar testes

```bash
# Todos os testes
pytest tests/ -v

# Apenas um módulo
pytest tests/test_validators.py -v
pytest tests/test_ad_service.py -v
pytest tests/test_password.py -v
pytest tests/test_glpi_service.py -v
pytest tests/test_webhook.py -v

# Com cobertura
pytest tests/ --cov=app --cov-report=term-missing
```

### Abordagem de testes

| Módulo | Tipo de teste | Mocks usados |
|---|---|---|
| `validators.py` | Unitário puro | Nenhum — funções puras |
| `password.py` | Unitário puro | Nenhum — função pura |
| `ad_service.py` | Unitário com mock | `ldap3.Connection` mockado via `connection_factory` (sem `@patch`) |
| `glpi_service.py` | Unitário puro | Nenhum — testa `_build_followup_content` e lógica de status |
| `webhook.py` | Integração com mock | `ADService` e `GLPIService` mockados, HTTP via `TestClient` |

### Fixtures compartilhadas (`tests/conftest.py`)

Todas as fixtures são centralizadas no `conftest.py`:

```python
# Settings de teste com dependency_overrides no FastAPI
@pytest.fixture
def test_settings():
    """Fornece settings de teste e faz override no FastAPI."""

# TestClient com settings de teste injetadas
@pytest.fixture
def client(test_settings):
    """TestClient do FastAPI com settings de teste."""

# Payloads de exemplo
@pytest.fixture
def sample_payload():
    """Payload com todos os campos preenchidos."""

@pytest.fixture
def sample_payload_minimal():
    """Payload mínimo (apenas campos obrigatórios)."""

# Mock de conexão LDAP
@pytest.fixture
def mock_ldap_connection():
    """Conexão ldap3 mockada com entries vazio e extensões Microsoft."""
```

### Cenários testados

**Validadores (`test_validators.py`):**
- Remoção de acentos (José → Jose, Conceição → Conceicao)
- Geração de sAMAccountName (formato, limite 20 chars, nomes compostos)
- Sanitização LDAP (parênteses, asterisco, backslash)
- Sanitização DN (vírgula, mais, aspas, backslash primeiro)
- Erros em nomes vazios

**Senha (`test_password.py`):**
- Comprimento padrão e customizado
- Mínimo de 12 caracteres forçado
- Contém todos os tipos de caractere
- Unicidade entre gerações
- Apenas caracteres válidos

**AD Service (`test_ad_service.py`):**
- Criação com sucesso (verifica sAM, UPN, displayName, atributos)
- Senha definida e conta habilitada (3 chamadas a modify)
- Grupos adicionados (extensão Microsoft chamada)
- Criação sem grupos (extensão não chamada)
- Rejeição de duplicata (entries não vazio → success=False)
- Falha de conexão (LDAPException no connect → mensagem de erro)
- Rollback em caso de erro LDAP (delete chamado)
- Unbind chamado mesmo em sucesso e erro
- Validação Pydantic rejeita first_name vazio

**GLPI Service (`test_glpi_service.py`):**
- Conteúdo do followup de sucesso (credenciais no HTML)
- Conteúdo do followup de erro (mensagem de erro)
- Status 5 (Resolvido) quando sucesso
- Status 4 (Pendente) quando erro

**Webhook (`test_webhook.py`):**
- Criação com sucesso (HTTP 200, status=success)
- Criação com falha (HTTP 200, status=error)
- Payload inválido (HTTP 422)
- Campos faltando (HTTP 422)
- Assinatura inválida (HTTP 401)
- Health check (HTTP 200, status=ok)
- GLPI service chamado após criação

### Escrever novos testes

Ao adicionar funcionalidade, use `connection_factory` para injetar mocks (sem `@patch`):

```python
class TestMinhaNovaFuncionalidade:
    def _make_service(self, mock_connection):
        """Cria ADService com factory de conexão mockada."""
        return ADService(connection_factory=lambda: mock_connection)

    def test_cenario_sucesso(self, sample_payload, mock_ldap_connection):
        service = self._make_service(mock_ldap_connection)
        result = service.create_user(sample_payload)

        assert result.success is True
        # ... mais asserções

    def test_cenario_erro(self, sample_payload):
        def failing_factory():
            raise LDAPException("erro")

        service = ADService(connection_factory=failing_factory)
        result = service.create_user(sample_payload)

        assert result.success is False
```

---

## 7. Como adicionar novas funcionalidades

### Adicionar novo campo ao formulário (ex: ramal)

1. **`app/models.py`** — adicionar campo ao `UserCreationPayload`:
   ```python
   extension: str = ""  # Ramal telefônico
   ```

2. **`app/services/ad_service.py`** — mapear para atributo AD em `_create_ad_object()`:
   ```python
   if payload.extension:
       ad_attributes["ipPhone"] = payload.extension
   ```

3. **`app/services/glpi_service.py`** — incluir no followup se relevante:
   ```python
   f"<b>Ramal:</b> {result.extension}",
   ```

4. **`tests/`** — atualizar fixtures e adicionar caso de teste

5. **Webhook GLPI** — adicionar campo no payload JSON do webhook

### Adicionar novo endpoint (ex: desativação de usuário)

1. Criar rota em `app/routes/webhook.py` (ou novo arquivo de rota):
   ```python
   @router.post("/user-disable", response_model=WebhookResponse)
   async def handle_user_disable(request: Request):
       ...
   ```

2. Adicionar método em `ADService`:
   ```python
   def disable_user(self, sam_account_name: str) -> UserCreationResult:
       ...
   ```

3. Registrar rota em `app/main.py` se for arquivo novo:
   ```python
   from app.routes.novo_modulo import router as novo_router
   app.include_router(novo_router)
   ```

4. Adicionar testes para o novo endpoint

### Alterar regra de nomenclatura do sAMAccountName

Editar `app/utils/validators.py`, função `generate_sam_account_name()`.

Exemplos de formato alternativo:
```python
# nome.sobrenome (ao invés de primeira letra + sobrenome)
sam = f"{first}.{last}"

# nome_sobrenome
sam = f"{first}_{last}"

# sobrenome + primeira letra do nome
sam = f"{last}{first[0]}"
```

Lembre-se: max 20 caracteres, apenas `[a-z0-9._-]`.

---

## 8. Debug e desenvolvimento local

### Testar o webhook manualmente com curl

```bash
# Teste simples (sem assinatura — funciona se WEBHOOK_SECRET estiver vazio)
curl -X POST http://localhost:8443/webhook/user-creation \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": 999,
    "first_name": "Teste",
    "last_name": "Desenvolvimento",
    "email": "teste.dev@empresa.com",
    "department": "TI",
    "title": "Desenvolvedor",
    "phone": "(11) 99999-0000",
    "manager": "",
    "groups": []
  }'
```

### Testar com assinatura HMAC

```python
# Gerar assinatura para teste
import hmac, hashlib, json

payload = '{"ticket_id":999,"first_name":"Teste","last_name":"Dev","email":"t@e.com","department":"TI","title":"Dev"}'
secret = "minha-chave-secreta"
signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
print(signature)
```

```bash
curl -X POST http://localhost:8443/webhook/user-creation \
  -H "Content-Type: application/json" \
  -H "X-GLPI-Signature: <assinatura_gerada>" \
  -d '<payload_json>'
```

### Ativar logs de debug

No `.env`:
```ini
LOG_LEVEL=DEBUG
```

Reiniciar o servidor para ver logs detalhados de cada operação.

### Debugar com breakpoints (VSCode)

Criar `.vscode/launch.json`:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "FastAPI Debug",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": ["app.main:app", "--host", "0.0.0.0", "--port", "8443", "--reload"],
      "env": {
        "PYTHONPATH": "${workspaceFolder}"
      }
    }
  ]
}
```

### Simular AD sem servidor real

Para desenvolvimento sem AD disponível, use `connection_factory` para injetar um mock:

```python
from unittest.mock import MagicMock
from app.services.ad_service import ADService

# Criar mock de conexão que simula sucesso
mock_conn = MagicMock()
mock_conn.entries = []  # Sem duplicidade
mock_conn.extend.microsoft.add_members_to_groups = MagicMock()

# Injetar no ADService
service = ADService(connection_factory=lambda: mock_conn)
result = service.create_user(payload)
# result.success será True (mock não levanta exceções)
```

Ou crie um `FakeADService` para testes manuais locais:

```python
class FakeADService(ADService):
    def create_user(self, payload):
        from app.utils.validators import generate_sam_account_name
        sam = generate_sam_account_name(payload.first_name, payload.last_name)
        return UserCreationResult(
            success=True,
            ticket_id=payload.ticket_id,
            sam_account_name=sam,
            user_principal_name=f"{sam}@empresa.local",
            display_name=f"{payload.first_name} {payload.last_name}",
            temporary_password="FakeTempPass123!",
            distinguished_name=f"CN={payload.first_name} {payload.last_name},OU=Fake",
            message="[FAKE] Usuário simulado com sucesso",
        )
```

---

## 9. Referência da API

### Endpoints

| Método | Path | Descrição | Auth |
|---|---|---|---|
| `GET` | `/health` | Health check | Nenhuma |
| `GET` | `/docs` | Swagger UI (documentação interativa) | Nenhuma |
| `GET` | `/redoc` | ReDoc (documentação alternativa) | Nenhuma |
| `POST` | `/webhook/user-creation` | Cria usuário no AD | HMAC (X-GLPI-Signature) |

### POST /webhook/user-creation

**Request:**

Headers:
```
Content-Type: application/json
X-GLPI-Signature: <hmac-sha256-hex>   (opcional se WEBHOOK_SECRET vazio)
```

Body:
```json
{
  "ticket_id": 123,
  "first_name": "Rafael",
  "last_name": "Silva",
  "email": "rafael.silva@empresa.com",
  "department": "TI",
  "title": "Analista de Sistemas",
  "phone": "(11) 99999-0000",
  "manager": "CN=Gestor,OU=Usuarios,DC=empresa,DC=local",
  "groups": [
    "CN=GRP-TI,OU=Grupos,DC=empresa,DC=local",
    "CN=GRP-VPN,OU=Grupos,DC=empresa,DC=local"
  ]
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `ticket_id` | int | Sim | ID do chamado no GLPI |
| `first_name` | string | Sim | Primeiro nome (não pode ser vazio) |
| `last_name` | string | Sim | Sobrenome (não pode ser vazio) |
| `email` | string | Sim | Email corporativo (validado por `EmailStr` do Pydantic) |
| `department` | string | Sim | Departamento (não pode ser vazio) |
| `title` | string | Sim | Cargo (não pode ser vazio) |
| `phone` | string | Não | Telefone (caracteres inválidos removidos automaticamente) |
| `manager` | string | Não | DN completo do gestor no AD |
| `groups` | list[string] | Não | Lista de DNs dos grupos AD |

**Response (200):**

```json
{
  "status": "success",
  "message": "Usuário Rafael Silva (rsilva) criado com sucesso no AD. Senha temporária gerada. Troca obrigatória no primeiro login.",
  "ticket_id": 123
}
```

```json
{
  "status": "error",
  "message": "Usuário já existe no AD: rsilva ou rsilva@empresa.local",
  "ticket_id": 123
}
```

**Códigos de resposta:**

| Código | Significado |
|---|---|
| `200` | Processado (verificar campo `status` para sucesso ou erro) |
| `401` | Assinatura HMAC inválida |
| `422` | Payload JSON inválido (campos faltando ou formato errado) |

### GET /health

**Response (200):**
```json
{
  "status": "ok",
  "service": "glpi-ad-integration"
}
```
