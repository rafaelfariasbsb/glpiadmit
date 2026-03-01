# Overview — GLPIADmit

## What it is

Native plugin for **GLPI 11** that automates Active Directory (AD) user creation when a user creation form is submitted through the GLPI Service Catalog. The user created in on-premises AD can be synchronized with **Azure AD / Entra ID** via Entra Connect.

## Architecture

```
                                    GLPI 11 (PHP)
                    ┌─────────────────────────────────────────┐
                    │                                         │
  Requester   ───►  │  Service Catalog                        │
  (HR/Manager)      │       │                                 │
                    │       ▼                                 │
                    │  Ticket created                         │
                    │       │                                 │
                    │       ▼  Hook ITEM_ADD                  │
                    │  ┌──────────────┐                       │
                    │  │ TicketHook   │ Parse ticket HTML      │
                    │  │ (plugin)     │ Validate fields        │
                    │  └──────┬───────┘                       │
                    │         │                               │
                    │         ▼  INSERT                       │
                    │  ┌──────────────┐                       │
                    │  │ Queue Table  │ glpi_plugin_glpiadmit │
                    │  │ (MariaDB)    │ _queues               │
                    │  └──────┬───────┘                       │
                    │         │                               │
                    │         ▼  CronTask (every 60s)         │
                    │  ┌──────────────┐                       │
                    │  │ QueueItem    │ Process queue          │
                    │  │ (CronTask)   │                       │
                    │  └──────┬───────┘                       │
                    │         │                               │
                    └─────────┼───────────────────────────────┘
                              │
                       LDAP/LDAPS (389/636)
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

## Detailed flow

```
[1] Requester fills out form in the GLPI Service Catalog
        │
        ▼
[2] GLPI creates Ticket — hook ITEM_ADD triggers TicketHook::onItemAdd()
        │
        ▼
[3] TicketHook extracts data from the ticket's HTML content
    Pattern: /<b>N) Label</b>: Value/i
    Fields: nome, sobrenome, e-mail corporativo, departamento, cargo
        │
        ▼
[4] Data sanitized (trim, strip_tags, filter_var) and inserted into the queue
    Table: glpi_plugin_glpiadmit_queues (status=PENDING)
        │
        ▼
[5] CronTask "ProcessQueue" runs every 60 seconds
    ├── Connects to AD via LDAP/LDAPS (connection reused within cycle)
    ├── Fetches PENDING items (LIMIT 10)
    ├── Atomic lock: UPDATE WHERE status=0
    └── For each item:
        │
        ├── Generates sAMAccountName, UPN, temporary password
        ├── Checks for duplicates (sAMAccountName or mail)
        ├── Creates disabled object (UAC=514)
        ├── Sets password (unicodePwd via LDAPS)
        ├── Forces password change (pwdLastSet=0)
        ├── Enables account (UAC=512)
        ├── Adds to AD groups
        └── Automatic rollback on failure after creation
            │
            ├── Success → Private followup (credentials) + public (confirmation)
            │              Status: Solved (5)
            │
            └── Error   → Public followup (generic message)
                           Status: Waiting (4)
                           Automatic retry up to 3 attempts
```

## Differences from previous version (Python/FastAPI)

| Aspect | Previous version (Python) | Current version (PHP Plugin) |
|---|---|---|
| **Architecture** | External service (FastAPI) | Native GLPI 11 plugin |
| **Trigger** | HTTP Webhook (POST) | ITEM_ADD Hook (in-process) |
| **Processing** | Synchronous (during webhook) | Asynchronous (queue + CronTask) |
| **Authentication** | HMAC-SHA256 on webhook | N/A (in-process, trusts GLPI) |
| **GLPI API** | External REST API (httpx) | Internal objects (ITILFollowup, Ticket) |
| **Configuration** | Environment variables (.env) | GLPI Config (DB + GLPIKey) |
| **Dependencies** | Python 3.11, ldap3, httpx | php-ldap (already included in GLPI) |
| **Deploy** | Separate container or systemd | GLPI plugins/ directory |
| **Resilience** | tenacity (external retry) | CronTask retry + atomic lock |
| **Concurrency** | Not handled (single webhook) | Atomic lock (UPDATE WHERE) |

## Technologies

| Component | Technology |
|---|---|
| ITSM | GLPI 11 (PHP 8.2+) |
| Plugin framework | GLPI Plugin API (CommonDBTM, CronTask, Hooks) |
| Templates | Twig (@fields macros) |
| AD communication | php-ldap (native) |
| Password generation | random_int() (CSPRNG) |
| LDAP sanitization | ldap_escape() (RFC 4514/4515) |
| Transliteration | intl (transliterator) with iconv fallback |
| Config encryption | GLPIKey (SECURED_CONFIGS) |
| Database | MariaDB (via GLPI) |
| Queue | Table with atomic lock |

## Project structure

```
glpiadmit/
├── setup.php                     # Entry point: version, hooks, registrations
├── hook.php                      # Install/uninstall: table, CronTask, config
├── src/
│   ├── Config.php                # Configuration wrapper (GLPIKey decrypt)
│   ├── TicketHook.php            # ITEM_ADD Hook: parse HTML, validate, enqueue
│   ├── ADService.php             # LDAP operations: create, password, enable, groups
│   ├── QueueItem.php             # CommonDBTM: queue, CronTask, followups
│   ├── Validators.php            # Sanitization, normalization, name generation
│   └── PasswordGenerator.php     # Password generator (CSPRNG, Fisher-Yates)
├── front/
│   ├── config.php                # Plugin configuration page
│   ├── config.form.php           # POST handler: save, test connection
│   ├── queueitem.php             # Queue listing (Search::show)
│   └── queueitem.form.php        # Item details + actions (retry, force_retry)
├── templates/
│   ├── config.html.twig          # Configuration template (AD fields)
│   └── queueitem.html.twig       # Queue item detail template
├── locales/                      # Translations (gettext)
│   ├── glpiadmit.pot             # Translation template
│   ├── en_GB.po / en_GB.mo       # English
│   └── pt_BR.po / pt_BR.mo       # Brazilian Portuguese
├── docs/                         # This documentation
├── glpiadmit.xml                 # GLPI Marketplace plugin descriptor
├── glpiadmit.png                 # Plugin icon (128x128)
├── composer.json                 # Dependencies (ext-ldap)
├── LICENSE                       # GPL-3.0-or-later
├── README.md                     # Project overview
├── CHANGELOG.md                  # Version history
├── .gitattributes                # Release archive exclusions
└── .gitignore
```
