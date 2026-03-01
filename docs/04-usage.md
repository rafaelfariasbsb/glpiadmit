# Usage and Operations

## How to request user creation

### For the requester (HR / Manager)

1. Access GLPI: `https://glpi.yourcompany.com`
2. Go to **Assistance > Service Catalog**
3. Click **"Request AD User Creation"**
4. Fill in the fields:

| Field | Example | Required |
|---|---|---|
| Nome | Rafael | Yes |
| Sobrenome | Silva | Yes |
| E-mail corporativo | rafael.silva@company.com | Yes |
| Departamento | Information Technology | Yes |
| Cargo | Systems Analyst | Yes |

5. Click **Submit**
6. A ticket will be created automatically
7. Wait up to 60 seconds — the ticket will be updated with a confirmation

### What happens after submission

```
[Form submitted]
        |
        v
[Ticket created in GLPI]  --  Status: New
        |
        v
[Hook ITEM_ADD: TicketHook::onItemAdd()]
        |
        v
[Data extracted and inserted into queue]  --  Status: Pending
        |
        v
[CronTask ProcessQueue (every 60s)]
        |
        v
[User created in AD via LDAP/LDAPS]
        |
        +-- Success --> Private followup (credentials)
        |               Public followup (confirmation)
        |               Status: Solved (5)
        |
        +-- Error   --> Public followup (generic message)
                        Status: Waiting (4)
                        Automatic retry (up to 3 attempts)
```

### Information returned in the ticket (success)

**Private followup** (visible only to technicians):
- **Login (sAMAccountName)**: e.g., `rsilva`
- **Temporary password**: automatically generated (16 characters)
- Mandatory password change notice on first login

**Public followup** (visible to the requester):
- Confirmation that the user was created
- Indication that credentials were sent to the responsible person

> **Security**: Communicate the temporary password to the new employee securely (in person or via an encrypted channel). Never via email.

### In case of error

The public followup will contain a generic message about the failure. Technical details remain only in the log (`files/_log/glpiadmit.log`). The ticket status will be **Waiting**.

---

## Queue management

### Accessing the queue

**Administration > GLPIADmit Queue**

The listing shows all items with columns: Ticket, First Name, Last Name, Email, Status, Attempts, Error, Date.

### Item statuses

| Status | Code | Description |
|---|---|---|
| Pending | 0 | Waiting for CronTask processing |
| Processing | 1 | Being processed (atomic lock active) |
| Done | 2 | User created successfully |
| Error | 3 | Failed after all attempts |

### Item details

Click an item in the listing to see full details, including error message.

### Manual retry

On the error item's detail page:

- **Retry**: Available for non-permanent errors. Returns the item to PENDING with attempts=0.
- **Force Retry**: Available for permanent errors. Clears the `is_permanent_error` flag and returns to PENDING.

> Force Retry asks for confirmation before executing, as permanent errors (duplicate, schema violation) are generally not resolved by retry.

### Tab on Ticket

Tickets that have a queue item display a **GLPIADmit** tab with summary: status, attempts, error, and link to details.

---

## Naming rules

The plugin automatically generates user identifiers:

| Attribute | Rule | Example |
|---|---|---|
| `sAMAccountName` | First letter of first name + full last name (no spaces/accents/special chars), lowercase (max 20 chars) | `Rafael Silva` -> `rsilva` |
| `userPrincipalName` | sAMAccountName + UPN suffix | `rsilva@company.local` |
| `displayName` | First Name + Last Name | `Rafael Silva` |
| `cn` | Same as `displayName` | `Rafael Silva` |

### Accent handling

Accents and special characters are removed via transliteration (`intl` or `iconv`):

| Original name | sAMAccountName |
|---|---|
| Jose Goncalves | `jgoncalves` |
| Joao da Conceicao | `jdaconceicao` |
| Andre Muller | `amuller` |
| Maria Garcia | `mgarcia` |
| Ana de Souza | `jdesouza` |

> **Note**: Prepositions like "da", "de", "dos" are NOT stripped — they become part of the sAMAccountName. All non-alphanumeric characters (spaces, hyphens, accents) are removed after transliteration.

### In case of duplicate

If the `sAMAccountName` or `mail` already exists in AD, the item is marked as a **permanent error**. The IT team must:

1. Verify if it's a real duplicate or a name collision
2. Create manually with an alternative sAMAccountName (e.g., `rsilva2`, `rnsilva`)
3. Resolve the ticket in GLPI

---

## Temporary password

- Generated with **16 characters** (minimum 12)
- Contains: uppercase, lowercase, numbers and special characters (`!@#$%&*`)
- Generated with `random_int()` (CSPRNG)
- Shuffled via Fisher-Yates with CSPRNG
- User **must change password** on first login (forced via `pwdLastSet=0`)
- Recorded in the ticket's **private** followup (visible only to technicians)

---

## Logs

The plugin logs events to `files/_log/glpiadmit.log`:

| Prefix | Meaning |
|---|---|
| `[QUEUED]` | Item added to queue |
| `[PATTERN_MISS]` | Ticket did not match expected format |
| `[VALIDATION]` | Required fields missing or invalid email |
| `[DUPLICATE]` | Ticket already exists in queue |
| `[AD_CREATE]` | AD user creation attempt |
| `[AD_SUCCESS]` | User created successfully |
| `[AD_ERROR]` | Creation error |
| `[AD_ROLLBACK]` | User deleted (rollback) |
| `[AD_ROLLBACK_FAILED]` | CRITICAL: rollback failed, orphan object in AD |
| `[AD_GROUP_WARN]` | Failed to add to group (non-blocking) |
| `[INSERT_FAILED]` | Queue insert affected 0 rows |
| `[INSERT_ERROR]` | Queue insert threw exception |
| `[CRON]` | CronTask cycle summary |
| `[CRON] Connection error` | AD connection lost mid-cycle, reconnect attempt |
| `[CRON] Reconnect failed` | Reconnect failed, cycle aborted |
| `DECRYPT FAILED` | GLPIKey failed to decrypt a config field |
| `CRITICAL` | Critical error requiring immediate attention |
