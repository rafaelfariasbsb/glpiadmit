# GLPIADmit

Native GLPI 11 plugin that automates **Active Directory user creation** from Service Catalog tickets.

When a user creation form is submitted in the GLPI Service Catalog, GLPIADmit automatically:

1. Parses the ticket content and extracts employee data
2. Queues the request for asynchronous processing
3. Creates the user in Active Directory (disabled → set password → enable)
4. Adds the user to configured AD groups
5. Posts credentials in a private followup (technicians only)
6. Resolves the ticket with a public confirmation

## Features

- **Asynchronous processing** — Queue + CronTask, never blocks ticket creation
- **Secure password generation** — 16 chars, CSPRNG, forced change on first login
- **Duplicate detection** — Checks sAMAccountName and email before creation
- **Automatic rollback** — Deletes partially created accounts on failure
- **Retry mechanism** — Up to 3 attempts for transient errors, permanent error detection
- **Credential encryption** — AD bind password encrypted via GLPIKey
- **LDAP injection protection** — ldap_escape() for filters and DN components
- **Information separation** — Credentials in private followup, generic messages in public
- **Connection reuse** — Single LDAP connection per CronTask cycle
- **Atomic locking** — Prevents duplicate processing across multiple instances

## Requirements

| Requirement | Version |
|---|---|
| GLPI | 11.0.0+ |
| PHP | 8.2+ |
| php-ldap | Required |
| php-intl | Recommended (iconv fallback available) |
| AD service account | With delegated permissions on the users OU |

## Quick Start

### Installation

```bash
cd /var/www/glpi/plugins
git clone https://github.com/rafaelfariasbsb/glpiadmit.git glpiadmit
```

Then in GLPI:

1. Go to **Setup > Plugins**
2. Click **Install** then **Enable** on GLPIADmit
3. Go to **Setup > Plugins > GLPIADmit > Configuration**
4. Fill in the AD connection details and click **Test Connection**

### Development Environment

```bash
git clone https://github.com/rafaelfariasbsb/glpiadmit.git
cd glpiadmit
cp .env.example .env
docker compose up -d

# Wait ~60s for Samba DC to initialize, then seed the AD:
docker exec glpiadmit-samba-dc bash /opt/init-samba.sh
```

| Service | URL |
|---|---|
| GLPI | http://localhost:8080 |
| Mailpit | http://localhost:8025 |
| DBGate | http://localhost:9000 |
| Samba AD (LDAP) | ldap://localhost:389 |

## How It Works

```
Service Catalog Form
        │
        ▼
   Ticket Created ──► Hook ITEM_ADD ──► TicketHook parses HTML
        │                                    │
        │                                    ▼
        │                              Queue Table (PENDING)
        │                                    │
        │                              CronTask (every 60s)
        │                                    │
        │                                    ▼
        │                              ADService creates user
        │                                    │
        ▼                          ┌─────────┴─────────┐
   Ticket Updated            Success                Error
                          (Resolved)             (Pending)
                        Private followup      Public followup
                        + Public followup     + Retry (up to 3x)
```

### AD Operation Order

1. **Create disabled** (UAC=514) — Prevents active account without password
2. **Set password** (unicodePwd) — Requires LDAPS in production
3. **Enable + force change** (UAC=512 + pwdLastSet=0) — Single atomic operation
4. **Add to groups** — Non-blocking (logged on failure)

If steps 2-3 fail, automatic rollback deletes the object from step 1.

## Configuration

### Plugin Settings

| Field | Description |
|---|---|
| AD Server | Domain controller hostname or IP |
| AD Port | 636 (LDAPS) or 389 (LDAP) |
| Use SSL | Required for production (unicodePwd needs LDAPS) |
| Bind DN | Service account distinguished name |
| Bind Password | Encrypted via GLPIKey |
| Base DN | Search base for duplicate detection |
| User OU | OU where new users are created |
| Domain | AD domain name |
| UPN Suffix | e.g., @company.local |
| Groups | One DN per line |

### Service Catalog Form

Create a form with fields: `Nome`, `Sobrenome`, `E-mail corporativo`, `Departamento`, `Cargo`.

The ticket destination content must use the format:
```html
<b>1) Nome</b>: {{answers.ID}}<br>
<b>2) Sobrenome</b>: {{answers.ID}}<br>
<b>3) E-mail corporativo</b>: {{answers.ID}}<br>
```

See [docs/03-configuration.md](docs/03-configuration.md) for detailed setup.

## Documentation

| Document | Description |
|---|---|
| [01-overview.md](docs/01-overview.md) | Architecture and flow |
| [02-installation.md](docs/02-installation.md) | Installation and upgrade |
| [03-configuration.md](docs/03-configuration.md) | Plugin settings, AD setup, form configuration |
| [04-usage.md](docs/04-usage.md) | Usage and queue management |
| [05-security.md](docs/05-security.md) | Security details |
| [06-troubleshooting.md](docs/06-troubleshooting.md) | Troubleshooting guide |
| [07-development-guide.md](docs/07-development-guide.md) | Development guide |

## License

This project is licensed under the [GPL-3.0-or-later](LICENSE) license.

## Author

**Rafael Farias** — [GitHub](https://github.com/rafaelfariasbsb)
