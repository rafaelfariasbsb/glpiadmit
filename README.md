# GLPIADmit

> Automated Active Directory user provisioning from GLPI helpdesk tickets.

When a "User Creation" ticket is submitted in **GLPI 11**, GLPIADmit automatically creates the user account in **Active Directory** via LDAPS, sets a temporary password, adds the user to groups, and updates the GLPI ticket with the credentials. The new account syncs to **Azure AD / Entra ID** via Entra Connect.

---

## How It Works

```
 Requester fills out           GLPI fires            FastAPI service
 "New User" form        ──►   webhook (POST)   ──►  validates & creates
 in GLPI 11                                          user in AD via LDAPS
                                                           │
                                                           ▼
                                                     Updates GLPI
                                                     ticket with
                                                     credentials
                                                           │
                                                           ▼
                                                     Entra Connect
                                                     syncs to Azure AD
                                                     (~30 min)
```

**Full flow:**

1. Requester submits the structured form in GLPI
2. GLPI creates a ticket and fires a **webhook** to the FastAPI service
3. The service **validates** the payload and **creates the user** in AD over LDAPS
4. The service **updates the GLPI ticket** with credentials (success) or error details
5. **Entra Connect** synchronizes the new user to Azure AD / Entra ID

## Features

- **Automatic user creation** in Active Directory from GLPI tickets
- **LDAPS only** (port 636) — passwords are never sent in plaintext
- **Duplicate detection** — checks `sAMAccountName` and `userPrincipalName` before creating
- **Temporary password** — cryptographically secure, forced change on first login
- **Group membership** — automatically adds user to specified AD groups
- **Rollback on failure** — if creation partially fails, the user is removed
- **GLPI ticket feedback** — ticket is updated with credentials or error details
- **HMAC webhook validation** — prevents unauthorized requests
- **LDAP injection protection** — inputs sanitized per RFC 4514/4515
- **Systemd hardening** — runs as dedicated service user, restricted filesystem access

## Tech Stack

| Component | Technology |
|---|---|
| ITSM | GLPI 11.0.5 |
| Middleware | Python 3.11+ / FastAPI |
| Data validation | Pydantic v2 + EmailStr |
| AD communication | ldap3 (LDAPS) |
| GLPI communication | httpx (REST API) |
| Configuration | pydantic-settings (environment variables) |
| Deployment | systemd (Linux) |
| Directory | Windows Server AD DS |
| Cloud sync | Azure AD / Entra ID (via Entra Connect) |

## Project Structure

```
├── app/
│   ├── main.py              # FastAPI app, lifespan, health check
│   ├── config.py            # Configuration via pydantic-settings (@lru_cache)
│   ├── models.py            # Pydantic models (payload, result, response)
│   ├── services/
│   │   ├── ad_service.py    # AD user creation logic (connection_factory DI)
│   │   └── glpi_service.py  # GLPI REST API communication (configurable SSL)
│   ├── utils/
│   │   ├── password.py      # Secure temporary password generation (secrets/CSPRNG)
│   │   └── validators.py    # Data validation and sanitization
│   └── routes/
│       └── webhook.py       # Webhook endpoint (FastAPI Depends for settings)
├── tests/
│   ├── conftest.py          # Shared fixtures (settings, payloads, mocks)
│   ├── test_validators.py   # Validation/sanitization tests
│   ├── test_ad_service.py   # AD service tests (mocked ldap3)
│   ├── test_webhook.py      # HTTP endpoint tests (TestClient)
│   ├── test_password.py     # Password generation tests
│   └── test_glpi_service.py # GLPI service tests
├── docs/                    # Detailed documentation (Portuguese)
├── systemd/                 # Systemd unit file
├── install.sh               # Automated installation script
├── .env.example             # Environment variables template
└── requirements.txt         # Python dependencies
```

## Quick Start

### Prerequisites

- **Python 3.11+** on a Linux server
- **Network access** from server to AD (port 636/LDAPS)
- **Network access** from server to GLPI (port 443/HTTPS)
- **Network access** from GLPI to server (port 8443)
- **AD service account** with user creation permissions on the target OU
- **GLPI REST API** enabled with configured tokens

### Installation

**Automated (recommended):**

```bash
git clone https://github.com/yourusername/glpiadmit.git
cd glpiadmit
sudo bash install.sh
```

The `install.sh` script automates the entire setup process:

| Step | What it does |
|---|---|
| 1. Preflight checks | Verifies root access, Python 3.11+, and port 8443 availability |
| 2. Service user | Creates `glpi-ad-svc` system user (no shell, no home) |
| 3. File deployment | Copies application files to `/opt/glpi-ad-integration` |
| 4. Virtual environment | Creates Python venv and installs all dependencies |
| 5. Permissions | Sets `chmod 600` on `.env`, ownership to service user |
| 6. Systemd service | Installs and enables `glpi-ad-integration.service` |
| 7. Firewall guidance | Detects UFW/firewalld and suggests appropriate rules |

After the script completes, it displays next steps including the `.env` file location to configure.

> **Note:** The script installs to `/opt/glpi-ad-integration` by default. The `.env` file is created from `.env.example` but **not overwritten** if it already exists (safe for upgrades).

**Manual:**

```bash
git clone https://github.com/yourusername/glpiadmit.git
cd glpiadmit

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
chmod 600 .env    # Restrict permissions — IMPORTANT

# Create service user (production)
sudo useradd -r -s /usr/sbin/nologin glpi-ad-svc

# Install systemd service (production)
sudo cp systemd/glpi-ad-integration.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable glpi-ad-integration
```

### Configuration

Edit `.env` with your environment values:

```ini
# --- GLPI ---
GLPI_URL=https://glpi.yourcompany.com
GLPI_API_TOKEN=your_user_token
GLPI_APP_TOKEN=your_app_token
GLPI_VERIFY_SSL=true

# --- Active Directory ---
AD_SERVER=ldaps://dc01.yourcompany.local
AD_DOMAIN=yourcompany.local
AD_BASE_DN=DC=yourcompany,DC=local
AD_USER_OU=OU=Users,DC=yourcompany,DC=local
AD_BIND_USER=CN=svc-glpi-ad,OU=ServiceAccounts,DC=yourcompany,DC=local
AD_BIND_PASSWORD=your_service_account_password
AD_DEFAULT_COMPANY=Your Company

# --- Webhook ---
WEBHOOK_SECRET=your_webhook_secret_key

# --- Logging ---
LOG_LEVEL=INFO
```

<details>
<summary>Environment variables reference</summary>

| Variable | Description | Required |
|---|---|---|
| `GLPI_URL` | GLPI base URL (no trailing slash) | Yes |
| `GLPI_API_TOKEN` | GLPI user API token (Preferences > Remote API Token) | Yes |
| `GLPI_APP_TOKEN` | GLPI application token (Setup > General > API) | Yes |
| `GLPI_VERIFY_SSL` | Verify GLPI SSL certificate (`true`/`false`, default: `true`) | No |
| `AD_SERVER` | Domain controller address (**must** start with `ldaps://`) | Yes |
| `AD_DOMAIN` | AD domain (e.g., `company.local`) | Yes |
| `AD_BASE_DN` | Base DN for searches (e.g., `DC=company,DC=local`) | Yes |
| `AD_USER_OU` | OU where new users will be created | Yes |
| `AD_BIND_USER` | Full DN of the service account | Yes |
| `AD_BIND_PASSWORD` | Service account password | Yes |
| `AD_DEFAULT_COMPANY` | Company name (`company` AD attribute) | No |
| `WEBHOOK_SECRET` | Secret key for HMAC-SHA256 webhook signature validation | Yes* |
| `LOG_LEVEL` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` | No |

*Required in production. If empty, signature validation is skipped (development only).

</details>

### Run

```bash
# Development (with hot-reload)
uvicorn app.main:app --host 0.0.0.0 --port 8443 --reload

# Production (systemd)
sudo systemctl start glpi-ad-integration
sudo systemctl status glpi-ad-integration
```

Verify it's running:

```bash
curl http://localhost:8443/health
# {"status": "ok", "service": "glpi-ad-integration"}
```

Interactive API docs: `http://localhost:8443/docs`

## API Reference

### `POST /webhook/user-creation`

Receives GLPI webhook and creates user in AD.

**Headers:**
```
Content-Type: application/json
X-GLPI-Signature: <hmac-sha256-hex>   (optional if WEBHOOK_SECRET is empty)
```

**Request body:**
```json
{
  "ticket_id": 123,
  "first_name": "John",
  "last_name": "Smith",
  "email": "john.smith@company.com",
  "department": "Engineering",
  "title": "Software Engineer",
  "phone": "+1 555-0100",
  "manager": "CN=Manager,OU=Users,DC=company,DC=local",
  "groups": [
    "CN=GRP-Engineering,OU=Groups,DC=company,DC=local",
    "CN=GRP-VPN,OU=Groups,DC=company,DC=local"
  ]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `ticket_id` | int | Yes | GLPI ticket ID |
| `first_name` | string | Yes | First name (cannot be empty) |
| `last_name` | string | Yes | Last name (cannot be empty) |
| `email` | string | Yes | Corporate email (validated by `EmailStr`) |
| `department` | string | Yes | Department (cannot be empty) |
| `title` | string | Yes | Job title (cannot be empty) |
| `phone` | string | No | Phone number (invalid chars stripped automatically) |
| `manager` | string | No | Manager's full DN in AD |
| `groups` | list[string] | No | List of AD group DNs |

**Response (200):**
```json
{
  "status": "success",
  "message": "User John Smith (jsmith) created in AD. Temporary password generated. Must change on first login.",
  "ticket_id": 123
}
```

| Status Code | Meaning |
|---|---|
| `200` | Processed (check `status` field for success/error) |
| `401` | Invalid HMAC signature |
| `422` | Invalid JSON payload (missing or malformed fields) |

### `GET /health`

```json
{"status": "ok", "service": "glpi-ad-integration"}
```

## Naming Convention

The service automatically generates user identifiers:

| Attribute | Rule | Example |
|---|---|---|
| `sAMAccountName` | First letter of first name + last name, lowercase, no accents (max 20 chars) | `John Smith` → `jsmith` |
| `userPrincipalName` | sAMAccountName + @domain | `jsmith@company.local` |
| `displayName` | First Name + Last Name | `John Smith` |

Accents are automatically stripped: `José Gonçalves` → `jgoncalves`, `André Müller` → `amuller`.

## Security

| Layer | Implementation |
|---|---|
| AD communication | LDAPS only (port 636, SSL/TLS) |
| Webhook authentication | HMAC-SHA256 signature validation (`X-GLPI-Signature`) |
| LDAP injection prevention | Input sanitization per RFC 4514/4515 |
| Password generation | `secrets` module (CSPRNG), min 12 chars, forced change on first login |
| Credentials storage | Environment variables (`.env` with `chmod 600`), never in code |
| GLPI SSL verification | Configurable via `GLPI_VERIFY_SSL` (default: `true`) |
| Service process | Dedicated user, `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp` |
| Rollback | Failed partial creation triggers automatic user removal |

## Testing

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov httpx

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing
```

**60 tests, ~92% code coverage** across 5 test modules:

| Module | Tests | Approach |
|---|---|---|
| `test_validators.py` | Name normalization, sAMAccountName generation, LDAP/DN sanitization | Pure unit tests |
| `test_password.py` | Length, character types, uniqueness, minimum enforcement | Pure unit tests |
| `test_ad_service.py` | Creation, duplication, rollback, connection failure, unbind | Mocked via `connection_factory` |
| `test_glpi_service.py` | Followup content, ticket status mapping | Pure unit tests |
| `test_webhook.py` | HTTP responses, validation, signature, GLPI integration | TestClient with mocked services |

## GLPI Setup

1. **Enable REST API** — Setup > General > API
2. **Create API user** — with permissions to read tickets, add followups, update ticket status
3. **Create ticket category** — "User Creation"
4. **Create form** — with fields: first name, last name, email, department, title, phone, manager, AD groups
5. **Configure webhook** — Administration > Configuration > Webhooks, filtered by "User Creation" category

See [docs/03-configuracao-glpi.md](docs/03-configuracao-glpi.md) for detailed step-by-step instructions (Portuguese).

## AD Setup

1. **Create a dedicated OU** for new users
2. **Create a service account** with delegated permissions (create/delete users in the OU)
3. **Ensure LDAPS** is enabled (port 636) with a valid certificate
4. **Configure Entra Connect** to sync the OU

See [docs/04-configuracao-ad.md](docs/04-configuracao-ad.md) for detailed instructions (Portuguese).

## Documentation

Detailed documentation is available in Portuguese in the [docs/](docs/) folder:

| Document | Content |
|---|---|
| [01-visao-geral.md](docs/01-visao-geral.md) | Architecture overview |
| [02-instalacao.md](docs/02-instalacao.md) | Installation guide |
| [03-configuracao-glpi.md](docs/03-configuracao-glpi.md) | GLPI configuration |
| [04-configuracao-ad.md](docs/04-configuracao-ad.md) | Active Directory setup |
| [05-uso-operacao.md](docs/05-uso-operacao.md) | Usage and operations |
| [06-seguranca.md](docs/06-seguranca.md) | Security details |
| [07-troubleshooting.md](docs/07-troubleshooting.md) | Troubleshooting guide |
| [08-guia-desenvolvimento.md](docs/08-guia-desenvolvimento.md) | Developer guide |

## Roadmap

- [ ] **Containerização** — Dockerfile + docker-compose para deploy simplificado
- [ ] **CI/CD** — Pipeline com GitHub Actions (lint, testes, build)
- [ ] **Desativação de usuários** — Webhook para desabilitar contas AD a partir de tickets GLPI
- [ ] **Reset de senha** — Webhook para reset de senha via ticket GLPI
- [ ] **Notificações por e-mail** — Envio de credenciais por e-mail ao gestor/usuário
- [ ] **Dashboard de monitoramento** — Métricas e status das operações (Prometheus/Grafana)

## License

MIT
