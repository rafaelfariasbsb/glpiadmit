# Development Guide

Technical guide for developers who need to understand, modify or extend GLPIADmit.

---

## 1. Development environment

### Requirements

- Docker Engine 24+ and Docker Compose v2
- Git

### Setup

```bash
git clone https://github.com/rafaelfariasbsb/glpiadmit.git
cd glpiadmit

cp .env.example .env
docker compose up -d

# Wait ~60s for Samba DC to initialize, then seed the AD:
docker exec glpiadmit-samba-dc bash /opt/init-samba.sh
```

### Services and URLs

| Service | URL | Credentials |
|---|---|---|
| GLPI | http://localhost:8080 | `glpi / glpi` (setup wizard) |
| Mailpit | http://localhost:8025 | — |
| DBGate | http://localhost:9000 | — |
| Samba AD (LDAP) | ldap://localhost:389 | `Administrator / Admin@Teste123` |
| Samba AD (LDAPS) | ldaps://localhost:636 | `Administrator / Admin@Teste123` |

### GLPI first-time setup

1. Access http://localhost:8080
2. Follow the wizard: DB host=`db`, DB name=`glpi`, user=`glpi`, password=`glpi`
3. Login: `glpi / glpi`
4. **Setup > Plugins > Install GLPIADmit > Enable**
5. **Setup > Plugins > GLPIADmit > Configuration**:

| Field | Value |
|---|---|
| AD Server | `dc01.glpiadmit.local` |
| AD Port | `389` |
| Use SSL | `No` |
| Bind DN | `CN=svc-glpiadmit,OU=ServiceAccounts,DC=glpiadmit,DC=local` |
| Bind Password | `SvcGlpi@Test123!` |
| Base DN | `DC=glpiadmit,DC=local` |
| User OU | `OU=Users,DC=glpiadmit,DC=local` |
| Domain | `glpiadmit.local` |
| UPN Suffix | `@glpiadmit.local` |
| Groups | `CN=GRP-TI,OU=Groups,DC=glpiadmit,DC=local` |
| Enabled | `Yes` |

6. Click **Test Connection** — should return success

### Docker Compose: Services

| Service | Image | Port | Description |
|---|---|---|---|
| glpi | build .docker-glpiadmit/ | 8080:80 | GLPI with plugin mounted via volume |
| db | mariadb:11.8 | — | MariaDB (glpi/glpi/glpi) |
| samba-dc | nowsci/samba-domain | 389, 636 | Samba AD DC (domain GLPIADMIT.LOCAL) |
| mailpit | axllent/mailpit | 8025 | Email testing (catch-all SMTP) |
| dbgate | dbgate/dbgate | 9000 | Database admin UI |

> **Note**: Docker files (`.docker-glpiadmit/`, `docker-compose.glpiadmit.yml`, `.env.example.glpiadmit`) live in the **project root**, not inside the plugin directory.

The plugin is mounted via volume: `./glpiadmit:/var/www/glpi/plugins/glpiadmit` — code changes are reflected immediately (no rebuild needed).

### Samba AD DC

The Samba DC simulates a full Active Directory with support for:
- `unicodePwd` (password setting)
- `userAccountControl` (enable/disable)
- `sAMAccountName`, `userPrincipalName`
- `pwdLastSet` (force password change)
- Group membership management

**Domain**: `GLPIADMIT.LOCAL`
**Admin**: `Administrator / Admin@Teste123`
**Fixed IP**: `172.29.0.10` (network `adnet`)

The GLPI container has `extra_hosts` to resolve `dc01.glpiadmit.local` to the Samba IP.

### Seed data (init-samba.sh)

The script `.docker/samba/init-samba.sh` creates:

| Resource | DN |
|---|---|
| OU Users | `OU=Users,DC=glpiadmit,DC=local` |
| OU ServiceAccounts | `OU=ServiceAccounts,DC=glpiadmit,DC=local` |
| OU Groups | `OU=Groups,DC=glpiadmit,DC=local` |
| Service account | `CN=svc-glpiadmit,OU=ServiceAccounts,...` (password: `SvcGlpi@Test123!`) |
| Group GRP-TI | `CN=GRP-TI,OU=Groups,...` |
| Group GRP-Users | `CN=GRP-Users,OU=Groups,...` |
| Test user | `CN=Maria Silva,OU=Users,...` (sAM: msilva, for duplicate detection testing) |

### Verify test AD

```bash
# Search all objects
docker exec glpiadmit-samba-dc \
  ldapsearch -x -H ldap://localhost \
  -b "DC=glpiadmit,DC=local" \
  -D "CN=Administrator,CN=Users,DC=glpiadmit,DC=local" \
  -w "Admin@Teste123" "(objectClass=*)" dn

# Search test user
docker exec glpiadmit-samba-dc \
  ldapsearch -x -H ldap://localhost \
  -b "OU=Users,DC=glpiadmit,DC=local" \
  -D "CN=Administrator,CN=Users,DC=glpiadmit,DC=local" \
  -w "Admin@Teste123" "(sAMAccountName=msilva)"
```

### Useful commands

```bash
# View GLPI logs (plugin)
docker exec glpiadmit-app cat /var/www/glpi/files/_log/glpiadmit.log

# Follow log in real time
docker exec glpiadmit-app tail -f /var/www/glpi/files/_log/glpiadmit.log

# Run CronTask manually
docker exec glpiadmit-app php /var/www/glpi/front/cron.php

# View queue items
docker exec glpiadmit-db mysql -uglpi -pglpi glpi -e \
  "SELECT * FROM glpi_plugin_glpiadmit_queues;"

# Reset environment (removes all data)
docker compose down -v
docker compose up -d
# Wait ~60s, then:
docker exec glpiadmit-samba-dc bash /opt/init-samba.sh
```

---

## 2. Code architecture

### Dependency diagram

```
setup.php ─── Registers hooks, SECURED_CONFIGS, CronTask, menu
hook.php  ─── Install (table, CronTask, config defaults) / Uninstall

src/Config.php         ─── Wrapper for Config::getConfigurationValues()
                           getAll() = encrypted (templates)
                           getAllDecrypted() = decrypted (LDAP)

src/TicketHook.php     ─── ITEM_ADD Hook on Ticket
  ├── parseTicketContent() ─── Regex on HTML
  ├── Validates fields (trim, strip_tags, filter_var)
  └── Inserts into queue (QueueItem::add)

src/QueueItem.php      ─── CommonDBTM (table glpi_plugin_glpiadmit_queues)
  ├── rawSearchOptions() ─── Listing columns
  ├── showForm()         ─── Twig template
  ├── getTabNameForItem/displayTabContentForItem ─── Tab on Ticket
  ├── cronProcessQueue() ─── Main CronTask
  │   ├── connect() once per cycle
  │   ├── Atomic lock (UPDATE WHERE status=0)
  │   ├── ADService::processUserCreation()
  │   ├── addFollowupSuccess() ─── Private + public
  │   ├── addFollowupError()   ─── Generic public
  │   └── Reconnect on connection error
  ├── canRetry() ─── Checks if retry is possible
  └── getStatusLabel()

src/ADService.php      ─── LDAP operations
  ├── connect()              ─── ldap_connect + ldap_bind
  ├── processUserCreation()  ─── Full orchestrator
  │   ├── checkDuplicateUser() ─── ldap_search (sAM or mail)
  │   ├── createUser()         ─── ldap_add (UAC=514)
  │   ├── setPassword()        ─── ldap_modify_batch (unicodePwd)
  │   ├── enableAccount()      ─── ldap_modify_batch (UAC=512, pwdLastSet=0)
  │   ├── addToGroups()        ─── ldap_mod_add (non-blocking)
  │   └── rollback()           ─── ldap_delete
  ├── isPermanentError()
  └── isConnectionError()

src/Validators.php     ─── Sanitization and name generation
  ├── normalizeName()          ─── intl transliterator + iconv fallback
  ├── generateSamAccountName() ─── first[0]+last, lowercase, max 20
  ├── generateUpn()            ─── sam + upnSuffix
  ├── generateDisplayName()    ─── first + last
  ├── sanitizeLdapValue()      ─── ldap_escape(FILTER)
  └── sanitizeDnComponent()    ─── ldap_escape(DN)

src/PasswordGenerator.php ─── Password generation
  └── generate()           ─── CSPRNG, Fisher-Yates shuffle

front/config.php       ─── Configuration page
front/config.form.php  ─── POST handler (save + test)
front/queueitem.php    ─── Queue listing
front/queueitem.form.php ─── Details + actions (retry, force_retry)
```

### Design principles

| Principle | Application |
|---|---|
| **Never block ticket** | TicketHook has a global try/catch — errors are logged, ticket never fails |
| **Asynchronous processing** | Hook only enqueues; CronTask processes |
| **Connection reuse** | ADService.connect() called once per CronTask cycle |
| **Atomic lock** | UPDATE WHERE status=0 + affectedRows() prevents duplication |
| **Defense in depth** | Sanitization in hook (input) + in ADService (LDAP output) |
| **Fail-safe with rollback** | Partial creation failure -> ADService.rollback() deletes object |
| **Dependency injection** | ADService accepts optional `connectionFactory` (testing) |

---

## 3. AD operation order

The order is critical — each step depends on the previous one:

```
1. Create disabled (UAC=514)         → Prevents active account without password
2. Set password (unicodePwd)         → Requires LDAPS
3. Enable + force change (UAC=512    → Steps 3+4 are a single ldap_modify_batch call
   + pwdLastSet=0)                     (UAC=512 and pwdLastSet=0 applied atomically)
4. Add to groups                     → Independent operation (non-blocking)
```

If step 2 or 3 fails, rollback deletes the object created in step 1.

---

## 4. How to add new features

### New form field

1. **Ticket template in GLPI**: Add `<b>6) New Field</b>: {{answers.ID}}<br>`
2. **TicketHook.php**: The regex already captures any `<b>N) Label</b>: Value` pair. Just use the lowercase label as the key.
3. **QueueItem**: If it needs to be persisted, add a column to the table (migration in `hook.php`)
4. **ADService**: Map to AD attribute in `processUserCreation()`

### New AD attribute

1. **ADService.php** — In `createUser()`, add to the `$attrs` array:
   ```php
   'telephoneNumber' => $queueData['phone'] ?? '',
   ```

2. **QueueItem** — If the field isn't in the table, add a column

### Change naming rule

Edit `Validators::generateSamAccountName()`:

```php
// Alternative format: first.last
$sam = $first . '.' . $last;
return substr($sam, 0, 20);
```

Reminder: max 20 chars, only `[a-z0-9]` after normalization.

### Add a new translation

The plugin uses gettext for internationalization. Translation files are in `locales/`.

1. **Extract translatable strings** — Generate or update the `.pot` template:

   ```bash
   # From the plugin directory
   xgettext --language=PHP --from-code=UTF-8 \
     --keyword=__ --keyword=_n:1,2 --keyword=_x:1c,2 \
     -o locales/glpiadmit.pot \
     setup.php hook.php src/*.php front/*.php
   ```

2. **Create a new language** (e.g., `fr_FR`):

   ```bash
   msginit --input=locales/glpiadmit.pot \
     --locale=fr_FR --output=locales/fr_FR.po
   ```

3. **Update existing `.po` files** after changing the `.pot`:

   ```bash
   msgmerge --update locales/pt_BR.po locales/glpiadmit.pot
   msgmerge --update locales/en_GB.po locales/glpiadmit.pot
   ```

4. **Translate** — Edit the `.po` file (use a tool like Poedit or edit manually)

5. **Compile** — Generate the `.mo` binary:

   ```bash
   msgfmt locales/fr_FR.po -o locales/fr_FR.mo
   ```

> **Available languages**: `pt_BR` (Brazilian Portuguese), `en_GB` (English). GLPI auto-detects the user's language and loads the appropriate `.mo` file.

---

## 5. Debugging

### Test flow manually

1. Create a ticket with HTML content in the expected format
2. Check if it appears in the queue: `SELECT * FROM glpi_plugin_glpiadmit_queues`
3. Run CronTask: `php /var/www/glpi/front/cron.php`
4. Check log: `tail -f files/_log/glpiadmit.log`
5. Check AD:
   ```bash
   docker exec glpiadmit-samba-dc \
     ldapsearch -x -H ldap://localhost \
     -b "OU=Users,DC=glpiadmit,DC=local" \
     -D "CN=Administrator,CN=Users,DC=glpiadmit,DC=local" \
     -w "Admin@Teste123" "(objectClass=user)" sAMAccountName displayName
   ```

### Test ticket parsing

```php
// In a temporary PHP script:
require_once 'src/TicketHook.php';

$html = '<b>1) Nome</b>: Rafael<br><b>2) Sobrenome</b>: Silva<br><b>3) E-mail corporativo</b>: r@e.com<br>';
$fields = GlpiPlugin\Glpiadmit\TicketHook::parseTicketContent($html);
var_dump($fields);
// array(3) { ["nome"]=> "Rafael", ["sobrenome"]=> "Silva", ["e-mail corporativo"]=> "r@e.com" }
```

### Simulate AD without a real server

```php
use GlpiPlugin\Glpiadmit\ADService;

// Inject connection mock via connectionFactory
$service = new ADService(function () {
    // Returns a mock or connection to test environment
    return ldap_connect('ldap://test-server:389');
});
```
