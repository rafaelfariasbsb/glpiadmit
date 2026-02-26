# Visão Geral — GLPIADmit

## O que é

Serviço de automação que cria usuários no **Active Directory (AD)** automaticamente quando um formulário de criação de usuário é submetido no **GLPI 11**. O usuário criado no AD on-premises é sincronizado com o **Azure AD / Entra ID** via Entra Connect.

## Arquitetura

```
┌──────────────────────┐     Webhook nativo POST      ┌──────────────────────┐
│                      │ ───────────────────────────► │                      │
│   GLPI 11            │   {event:"new", item:{...}}  │  GLPIADmit           │
│   Catálogo de        │                              │  FastAPI (Python)    │
│   Serviços           │ ◄─────────────────────────── │  Porta 80 (interno)  │
│   Formulário         │   Atualiza chamado (API REST) │                      │
└──────────────────────┘                              └──────────┬───────────┘
                                                                 │
                                                          LDAPS (636)
                                                                 │
                                                                 ▼
                                                      ┌──────────────────────┐
                                                      │  Active Directory     │
                                                      │  Windows Server       │
                                                      └──────────┬───────────┘
                                                                 │
                                                          Entra Connect
                                                          (sync ~30 min)
                                                                 │
                                                                 ▼
                                                      ┌──────────────────────┐
                                                      │  Azure AD / M365      │
                                                      │  Entra ID             │
                                                      └──────────────────────┘
```

## Fluxo detalhado

```
[1] Solicitante preenche formulário no Catálogo de Serviços do GLPI
        │
        ▼
[2] GLPI cria Ticket e dispara webhook nativo
    POST http://glpiadmit/webhook/glpi-native
    Headers: X-GLPI-signature, X-GLPI-timestamp
    Body: {"event":"new", "item": {"id": 9, "content": "<b>1) Nome</b>: Rafael<br>..."}}
        │
        ▼
[3] GLPIADmit valida assinatura HMAC
    hmac(body + timestamp, WEBHOOK_SECRET) == X-GLPI-signature
        │
        ▼
[4] GLPIADmit extrai dados do conteúdo HTML do ticket
    parse_ticket_content() → UserCreationPayload
    (nome, sobrenome, e-mail, departamento, cargo, grupo AD)
        │
        ▼
[5] GLPIADmit cria usuário no AD via LDAPS
    ├── Gera sAMAccountName, UPN, senha temporária
    ├── Verifica duplicidade
    ├── Cria objeto desabilitado (UAC=514)
    ├── Define senha (unicodePwd, exige SSL)
    ├── Força troca de senha (pwdLastSet=0)
    ├── Habilita conta (UAC=512)
    ├── Adiciona ao grupo AD
    └── Rollback automático se falhar
        │
        ├── Sucesso ──► Followup com credenciais + Status: Resolvido (5)
        └── Erro    ──► Followup com detalhe do erro + Status: Pendente (4)
        │
        ▼
[6] Entra Connect sincroniza com Azure AD (~30 min)
```

## Tecnologias

| Componente | Tecnologia |
|---|---|
| ITSM | GLPI 11 |
| Middleware | Python 3.11+ / FastAPI |
| Validação de dados | Pydantic v2 + EmailStr |
| Comunicação com AD | ldap3 (LDAPS) |
| Comunicação com GLPI | httpx (REST API assíncrona) |
| Configuração | pydantic-settings (variáveis de ambiente, `@lru_cache`) |
| Deploy | Docker (recomendado) ou systemd |
| Diretório | Windows Server AD DS |
| Cloud sync | Azure AD / Entra ID (via Entra Connect) |

## Estrutura do projeto

```
glpiadmit/
├── app/
│   ├── main.py              # App FastAPI, lifespan, health check
│   ├── config.py            # Configurações via pydantic-settings (@lru_cache)
│   ├── models.py            # Modelos Pydantic (payload, resultado, resposta)
│   ├── services/
│   │   ├── ad_service.py    # Criação de usuário no AD (connection_factory DI)
│   │   └── glpi_service.py  # Cliente REST API GLPI + parse de conteúdo do ticket
│   ├── utils/
│   │   ├── password.py      # Geração de senha temporária (secrets/CSPRNG)
│   │   └── validators.py    # Validação e sanitização de dados (RFC 4514/4515)
│   └── routes/
│       └── webhook.py       # Endpoints webhook (glpi-native + user-creation legado)
├── tests/
│   ├── conftest.py          # Fixtures compartilhadas (settings, payloads, mocks)
│   ├── test_validators.py
│   ├── test_ad_service.py
│   ├── test_webhook.py
│   ├── test_password.py
│   └── test_glpi_service.py
├── tests/docker/            # Ambiente de teste completo
│   ├── setup-test-env.sh    # Setup automático (GLPI + Samba AD + GLPIADmit)
│   ├── glpi-create-form.php # Cria formulário no GLPI (Catálogo de Serviços)
│   ├── glpi-create-webhook.php # Configura webhook GLPI → GLPIADmit
│   ├── glpi-setup-api.php   # Habilita REST API e gera tokens
│   └── init-samba.sh        # Inicializa AD de teste
├── docs/                    # Esta documentação
├── docker-compose.test.yml  # Ambiente de teste: MariaDB + GLPI + Samba DC + GLPIADmit
├── Dockerfile               # Imagem Docker (multi-stage, non-root)
├── systemd/                 # Unit file para deploy systemd
├── .env.example             # Template de configuração
└── requirements.txt         # Dependências Python
```

## Endpoints do serviço

| Método | Path | Descrição |
|---|---|---|
| `POST` | `/webhook/glpi-native` | Webhook nativo GLPI 11 (principal) |
| `POST` | `/webhook/user-creation` | Webhook legado com payload JSON explícito |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Swagger UI (documentação interativa) |

## Observações importantes

### URL do webhook sem porta
O GLPI 11 bloqueia URLs com porta explícita (ex: `:8443`) na validação `isUrlSafe()`. O serviço deve ser acessível via **porta 80 sem porta explícita na URL** (ex: `http://glpiadmit/webhook/glpi-native`). Em produção, use um reverse proxy ou mapeie a porta 80.

### Assinatura do webhook
O GLPI 11 assina o webhook com: `hmac-sha256(body + timestamp, secret)`. O `secret` deve estar **criptografado com `GLPIKey`** no banco de dados do GLPI — não pode ser inserido em texto plano.

### Parse do conteúdo do ticket
O endpoint `/webhook/glpi-native` não usa a API de respostas do formulário (`Glpi\Form\AnswersSet`) porque `canView()` retorna `false` no GLPI 11. Em vez disso, o conteúdo HTML do ticket é parseado diretamente pelo método `parse_ticket_content()`, que extrai campos no formato `<b>N) Label</b>: Valor<br>`.
