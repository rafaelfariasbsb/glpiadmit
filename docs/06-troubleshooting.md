# Troubleshooting

## Where to find logs

| Log | Location |
|---|---|
| GLPIADmit plugin | `files/_log/glpiadmit.log` (inside the GLPI directory) |
| GLPI general | `files/_log/php-errors.log` |
| CronTask | **Setup > Automatic actions > ProcessQueue > Logs** |
| Active Directory | Event Viewer > Security on the DC |

---

## Common problems

### 1. Ticket created but nothing appears in the queue

**Symptom**: Form submitted, ticket created, but no item in the `glpi_plugin_glpiadmit_queues` table.

**Checklist:**

1. **Plugin enabled?**
   - Setup > Plugins > GLPIADmit > Configuration
   - `Enabled` field must be `Yes`

2. **Ticket content format correct?**
   ```bash
   # Check content in the database:
   mysql -uglpi -pglpi glpi -e \
     "SELECT id, content FROM glpi_tickets ORDER BY id DESC LIMIT 1;"
   ```
   The content must follow the pattern: `<b>N) Label</b>: Value`

3. **Required fields present?**
   - The plugin requires: `nome`, `sobrenome`, `e-mail corporativo`
   - Check the log: `grep PATTERN_MISS files/_log/glpiadmit.log`
   - Check the log: `grep VALIDATION files/_log/glpiadmit.log`

4. **Valid email?**
   - The plugin validates with `filter_var(FILTER_VALIDATE_EMAIL)`
   - Invalid emails are silently rejected

---

### 2. Queue item stuck as PENDING indefinitely

**Symptom**: Item exists in the queue with status=0, but is never processed.

**Checklist:**

1. **CronTask running?**
   - Setup > Automatic actions > ProcessQueue
   - Check "Last execution" — should be recent (< 5 min)

2. **GLPI cron configured?**
   ```bash
   crontab -l -u www-data | grep glpi
   # Should have: */1 * * * * php /var/www/glpi/front/cron.php
   ```

3. **CronTask in correct mode?**
   - Must be in **CLI** mode (not Internal)
   - If it's in Internal, switch to CLI

4. **AD connection error?**
   - Check the log: `grep "CRON.*Failed to connect" files/_log/glpiadmit.log`

---

### 3. Queue item as ERROR

**Symptom**: Item has status=3 with an error message.

**Diagnosis:**

1. Go to **Administration > GLPIADmit Queue**
2. Click the item to see full details
3. Check the `error_message` field

**Common errors:**

| Message | Cause | Solution |
|---|---|---|
| `User already exists in AD` | Duplicate sAMAccountName or email | Create manually with a different name |
| `LDAP bind failed` | Invalid credentials | Check Bind DN and password in config |
| `Failed to initialize LDAP connection` | Server unreachable | Check hostname, port and firewall |
| `setPassword failed` | Connection is not LDAPS | Enable SSL (port 636) |
| `object class violation` | Incompatible AD schema | Check supported objectClasses |
| `constraint violation` | Password policy or invalid attribute | Check domain password policy |
| `ldap_add failed: Already exists` | Object with same DN already exists | Clean up orphan object or rename |

### Retry vs Force Retry

- **Retry**: For transient errors (connection, timeout). Returns to PENDING with attempts=0.
- **Force Retry**: For permanent errors (duplicate, constraint). Clears the `is_permanent_error` flag.

---

### 4. Test Connection fails

**Symptom**: Clicking "Test Connection" returns an error.

| Error | Cause | Solution |
|---|---|---|
| `Server, Bind DN and Bind Password are required` | Required fields empty | Fill all fields and save first |
| `Bind failed: Invalid credentials` | Wrong password | Check service account password |
| `Bind failed: Can't contact LDAP server` | Server unreachable | Check hostname, port, firewall |
| `Bind OK, but base_dn not accessible` | Incorrect Base DN | Check Base DN format |
| `Please wait 5 seconds between connection tests` | Throttle active | Wait 5 seconds |

**Connectivity debug from the GLPI server:**

```bash
# Test LDAP port
nc -zv dc01.company.local 389

# Test LDAPS port
nc -zv dc01.company.local 636

# Test bind (requires ldap-utils)
ldapsearch -x -H ldap://dc01.company.local:389 \
  -D "CN=svc-glpiadmit,OU=ServiceAccounts,DC=company,DC=local" \
  -w "PasswordHere" \
  -b "DC=company,DC=local" "(objectClass=*)" dn -s base
```

---

### 5. User created but disabled / without password

**Symptom**: User appears in AD but is disabled (UAC=514) and has no password.

**Cause**: The `setPassword` or `enableAccount` operation failed after object creation.

**Check:**
- Log: `grep "setPassword\|enableAccount" files/_log/glpiadmit.log`
- Is the connection LDAPS? (`unicodePwd` requires SSL)
- Is the DC certificate valid?

**Action:**
1. If rollback occurred, the object may have been automatically deleted
2. If `AD_ROLLBACK_FAILED` in the log, manually delete the object in AD
3. Manually set the password and enable the account (UAC=512)
4. Resolve the ticket in GLPI

---

### 6. Followup doesn't appear in the ticket

**Symptom**: Queue item as DONE but the ticket has no followup.

**Possible cause**: Error creating ITILFollowup (permissions, DB).

**Check:**
- Log: `grep "followup" files/_log/php-errors.log`
- Does the CronTask user have permission to create followups?

---

### 7. Form doesn't appear in the Service Catalog

**Checklist:**

1. **Access control active?**
   - Administration > Forms > (form) > **Access controls**
   - Toggle "Allow specific users, groups or profiles" must be **active**
   - Must have "User - All users"

2. **Form active and not a draft?**
   - In the **Form** tab: "Active" = Yes, "Draft" = No

---

## Quick diagnostic checklist

```bash
# 1. Plugin installed and active?
mysql -uglpi -pglpi glpi -e \
  "SELECT name, state FROM glpi_plugins WHERE directory='glpiadmit';"
# state=1 = Enabled

# 2. CronTask registered?
mysql -uglpi -pglpi glpi -e \
  "SELECT name, state, mode, lastrun FROM glpi_crontasks
   WHERE itemtype LIKE '%Glpiadmit%';"

# 3. Items in queue?
mysql -uglpi -pglpi glpi -e \
  "SELECT id, tickets_id, status, attempts, error_message
   FROM glpi_plugin_glpiadmit_queues ORDER BY id DESC LIMIT 10;"

# 4. Last log lines
tail -50 files/_log/glpiadmit.log

# 5. Critical errors
grep "CRITICAL" files/_log/glpiadmit.log
```
