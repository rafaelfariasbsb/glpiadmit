# Security

## Applied principles

1. **Least privilege** — AD service account with permissions only on the users OU (see [03-configuration.md](03-configuration.md))
2. **Encryption in transit** — LDAPS (port 636) for AD communication
3. **Credential encryption** — AD bind password encrypted via GLPIKey (SECURED_CONFIGS)
4. **Input sanitization** — LDAP injection protection via `ldap_escape()` (RFC 4514/4515)
5. **Layered validation** — Fields validated in the hook (trim, strip_tags, filter_var) and again in ADService
6. **Secure passwords** — Cryptographic generation (CSPRNG), mandatory change on first login
7. **Information separation** — Credentials in private followup, generic messages in public followup
8. **Automatic rollback** — Partially created account is deleted on failure

---

## Details by layer

### Active Directory communication

| Aspect | Implementation |
|---|---|
| Protocol | LDAPS (port 636, configurable to LDAP 389 in dev) |
| Authentication | Bind with service account (DN + password) |
| Timeout | 10 seconds (LDAP_OPT_NETWORK_TIMEOUT) |
| Options | LDAPv3, referrals disabled |
| Password operation | Via `unicodePwd` attribute (requires SSL) |

**Never** use plain LDAP (port 389) in production — the `unicodePwd` operation is rejected without SSL.

### Configuration encryption (GLPIKey)

The `ad_bind_password` field is declared in `SECURED_CONFIGS`:

```php
$PLUGIN_HOOKS[Hooks::SECURED_CONFIGS]['glpiadmit'] = ['ad_bind_password'];
```

GLPI automatically encrypts this field on save and decrypts on read via `GLPIKey`. The `Config::getAll()` method returns the **encrypted** value (safe for templates). Only `Config::getAllDecrypted()` returns the actual value, and is used exclusively in `connect()` and `testConnection()`.

### Data sanitization (defense in depth)

Two levels of sanitization are applied:

**Level 1 — TicketHook (input):**
- `trim()` and `strip_tags()` on all fields
- `filter_var($email, FILTER_VALIDATE_EMAIL)` for email validation
- Prevents malicious data from entering the queue

**Level 2 — ADService (LDAP output):**
- `ldap_escape($value, '', LDAP_ESCAPE_FILTER)` for search filters (RFC 4515)
- `ldap_escape($value, '', LDAP_ESCAPE_DN)` for DN components (RFC 4514)
- Uses PHP native functions (complete coverage, no gaps)

### Followup management

| Followup | Visibility | Content |
|---|---|---|
| Success (private) | Technicians only (`is_private=1`) | sAMAccountName + temporary password |
| Success (public) | Everyone (`is_private=0`) | Generic confirmation |
| Error (public) | Everyone (`is_private=0`) | Generic message (no technical details) |

Technical error details remain only in the log (`files/_log/glpiadmit.log`), never in the ticket visible to the requester.

### Concurrency and atomic lock

Queue processing uses an atomic lock via SQL:

```sql
UPDATE glpi_plugin_glpiadmit_queues
SET status = 1  -- PROCESSING
WHERE id = ? AND status = 0  -- PENDING
```

Followed by `affectedRows() === 0` to check if another process already claimed the item. This prevents duplicate processing even with multiple CronTask instances.

The table also has a `UNIQUE(tickets_id)` constraint to prevent duplicates in the queue.

### Partial creation rollback

If password setting or account enabling fails after object creation in AD:

1. The plugin attempts to delete the created object (`ldap_delete`)
2. If rollback fails (dead connection), it logs `CRITICAL [AD_ROLLBACK_FAILED]` with the orphan object's DN
3. The item is marked as a permanent error
4. IT team must manually clean up the orphan object in AD

### Permanent vs transient errors

| Type | Examples | Behavior |
|---|---|---|
| **Permanent** | "already exists", "constraint violation", "object class violation" | Does not retry (is_permanent_error=1) |
| **Transient** | Any error not matching permanent or connection patterns | Retries (up to MAX_ATTEMPTS=3) |
| **Connection** | "can't contact ldap server", "operations error", "server is busy", "connection timed out", "ldap bind failed" | Reconnects and continues the cycle |

> **Note**: Connection errors are a subset of transient errors. When a connection error is detected mid-cycle, the CronTask attempts to reconnect and resume processing remaining items. If reconnect fails, the cycle is aborted.

---

## Production recommendations

### Firewall

The GLPI server only needs outbound access to:
- AD: port 636 (LDAPS) or 389 (LDAP)

### LDAPS required

In production, configure `Use SSL = Yes` and `AD Port = 636`. The `unicodePwd` operation is rejected without SSL by AD.

### Credential rotation

| Credential | Suggested frequency |
|---|---|
| AD service account password | Every 90 days |

When rotating, update in **Setup > Plugins > GLPIADmit > Configuration** and click **Test Connection** to verify.

### Auditing

Monitor the log `files/_log/glpiadmit.log` for:
- `CRITICAL` — Requires immediate attention (connection failed, rollback failed)
- `[AD_ERROR]` with `permanent=yes` — Error that won't be resolved by retry
- `[AD_ROLLBACK_FAILED]` — Orphan object in AD

On the AD, enable auditing on the users OU:
1. **Group Policy** > Computer Configuration > Policies > Windows Settings > Security Settings > Advanced Audit Policy
2. Enable **Audit Directory Service Changes** for the users OU
