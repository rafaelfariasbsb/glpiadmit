# Configuration

## Part 1 — GLPI Plugin Configuration

Go to: **Setup > Plugins > GLPIADmit > Configuration**

### Section: AD Connection

| Field | Description | Example |
|---|---|---|
| AD Server | Domain controller hostname or IP (no protocol) | `dc01.company.local` |
| AD Port | LDAP (389) or LDAPS (636) port | `636` |
| Use SSL | Use LDAPS (required for unicodePwd in production) | `Yes` |
| Bind DN | Full DN of the service account | `CN=svc-glpiadmit,OU=ServiceAccounts,DC=company,DC=local` |
| Bind Password | Service account password (encrypted via GLPIKey) | `StrongPassword123!` |

### Section: AD Structure

| Field | Description | Example |
|---|---|---|
| Base DN | Search base for duplicate detection | `DC=company,DC=local` |
| User OU | OU where new users will be created | `OU=Users,DC=company,DC=local` |
| Domain | AD domain | `company.local` |
| UPN Suffix | Suffix for userPrincipalName (must start with @) | `@company.local` |

### Section: Groups

| Field | Description | Example |
|---|---|---|
| Groups | AD groups (one DN per line) | `CN=GRP-IT,OU=Groups,DC=company,DC=local` |

### Options

| Field | Description |
|---|---|
| Enabled | Enable/disable ticket processing |

### Buttons

- **Test Connection**: Tests bind + base_dn accessibility (5s throttle between tests)
- **Save**: Saves the configuration (with per-field validation)

### Validations applied on Save

| Field | Rule |
|---|---|
| AD Server | Only letters, numbers, `.` and `-` (no protocol) |
| AD Port | Integer between 1 and 65535 |
| Use SSL | Only `0` or `1` |
| Bind DN | Cannot be empty |
| Bind Password | Cannot be empty |
| Base DN | Cannot be empty |
| Domain | Cannot be empty |
| UPN Suffix | Must start with `@` and contain `.` |
| User OU | Cannot be empty |
| Groups | Each line must match pattern `Letters+=Value` (regex: `/^[A-Za-z]+=.+$/`) |

---

## Part 2 — Active Directory Setup

### 2.1 Create OU for new users

If it doesn't exist yet, create a dedicated OU where users will be provisioned:

```powershell
New-ADOrganizationalUnit -Name "Users" -Path "DC=company,DC=local"
```

> The OU path must match the **User OU** value in the plugin configuration.

### 2.2 Create service account

Create a dedicated service account for the integration:

```powershell
New-ADUser `
    -Name "svc-glpiadmit" `
    -SamAccountName "svc-glpiadmit" `
    -UserPrincipalName "svc-glpiadmit@company.local" `
    -Path "OU=ServiceAccounts,DC=company,DC=local" `
    -AccountPassword (ConvertTo-SecureString "StrongPassword!2026" -AsPlainText -Force) `
    -Enabled $true `
    -PasswordNeverExpires $true `
    -CannotChangePassword $true `
    -Description "Service account - GLPIADmit plugin"
```

### 2.3 Delegate permissions (principle of least privilege)

**Do not add the service account as Domain Admin.** Delegate permissions only on the users OU:

#### Via GUI (ADUC):

1. Open **Active Directory Users and Computers**
2. Right-click the `Users` OU > **Delegate Control...**
3. Add the user `svc-glpiadmit`
4. Select **Create a custom task to delegate**
5. Select **Only the following objects in the folder** > check **User objects**
6. Check:
   - **Create selected objects in this folder**
   - **Delete selected objects in this folder**
7. In permissions, check:
   - **Read All Properties**
   - **Write All Properties**
   - **Reset Password**
8. Complete the wizard

#### Via PowerShell:

```powershell
$svcAccount = Get-ADUser "svc-glpiadmit"
$ouDN = "OU=Users,DC=company,DC=local"
$acl = Get-Acl "AD:\$ouDN"

$userGUID = [GUID]"bf967aba-0de6-11d0-a285-00aa003049e2"  # User object class

# Permission: create and delete User objects
$createRule = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
    $svcAccount.SID,
    "CreateChild,DeleteChild",
    "Allow",
    $userGUID
)
$acl.AddAccessRule($createRule)

# Permission: generic properties (read/write) on descendants
$propsRule = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
    $svcAccount.SID,
    "GenericAll",
    "Allow",
    "Descendents",
    $userGUID
)
$acl.AddAccessRule($propsRule)

Set-Acl "AD:\$ouDN" $acl
```

### 2.4 Configure LDAPS (SSL)

Communication with AD **must** use LDAPS (port 636) in production because the password set operation (`unicodePwd`) requires an encrypted connection.

#### Verify if LDAPS is enabled:

```powershell
Test-NetConnection -ComputerName dc01.company.local -Port 636
```

If LDAPS is not enabled, install an SSL certificate on the domain controller:

1. Request a certificate from **AD Certificate Services** or an external CA
2. The certificate must:
   - Have the DC's FQDN in the Subject or SAN field
   - Have the "Server Authentication" purpose
   - Be installed in the computer's **Personal** store
3. After installing the certificate, restart the `Active Directory Domain Services` service

#### Test LDAPS connectivity from the GLPI server:

```bash
# Test port
nc -zv dc01.company.local 636

# Test SSL certificate
openssl s_client -connect dc01.company.local:636 -showcerts
```

> **Development note**: In the Docker environment with Samba DC, you can use LDAP (port 389) without SSL. The GLPI container is configured with `TLS_REQCERT allow` to accept self-signed certificates. In production, **always use LDAPS with valid certificates**.

### 2.5 Configure groups for new users

Identify the AD groups and note the **full DN** of each:

```powershell
Get-ADGroup -Filter * -SearchBase "OU=Groups,DC=company,DC=local" |
    Select-Object Name, DistinguishedName |
    Format-Table -AutoSize
```

Examples:
```
CN=GRP-IT,OU=Groups,DC=company,DC=local
CN=GRP-VPN,OU=Groups,DC=company,DC=local
CN=GRP-Email,OU=Groups,DC=company,DC=local
```

Enter these DNs in the plugin configuration (one per line) under **Groups**.

> Adding to groups is non-blocking: if it fails, the user is created normally and the error is logged.

### 2.6 Verify password policy

```powershell
Get-ADDefaultDomainPasswordPolicy |
    Select-Object MinPasswordLength, ComplexityEnabled, PasswordHistoryCount
```

The plugin's password generator creates passwords with:
- Always **16 characters** (hard minimum enforced: 12, but the plugin always calls with 16)
- Uppercase, lowercase, numbers and special characters (`!@#$%&*`)
- Generated with `random_int()` (CSPRNG) + Fisher-Yates shuffle
- Meets most standard AD password policies

### 2.7 Entra Connect considerations

If the environment uses **Entra Connect** to synchronize with Azure AD / Microsoft 365:

- New users will be synchronized automatically (default cycle: **30 minutes**)
- To force immediate sync:

```powershell
Start-ADSyncSyncCycle -PolicyType Delta
```

- Verify that the generated `userPrincipalName` does not conflict with existing Azure AD accounts

#### Synchronized attributes

| AD Attribute | Azure AD Attribute |
|---|---|
| `userPrincipalName` | `userPrincipalName` |
| `displayName` | `displayName` |
| `givenName` | `givenName` |
| `sn` | `surname` |
| `mail` | `mail` |
| `department` | `department` |
| `title` | `jobTitle` |

---

## Part 3 — Service Catalog Form Setup

### 3.1 Form creation

1. Go to **Administration > Forms**
2. Click **Add**
3. Configure:
   - **Name**: `Request AD User Creation`
   - **Active**: Yes
   - **Draft**: No
   - **Pinned**: Yes (appears at the top of the catalog)
   - **Category**: `Access Management` (create if it doesn't exist)
   - **Description**: `Fill in the new employee's data to automatically provision the Active Directory account.`

### 3.2 Form fields

Add a section called **"New employee data"** with the following fields — the names must be **exactly** as listed:

| # | Field name | Type | Required |
|---|---|---|---|
| 1 | `Nome` | Short text | Yes |
| 2 | `Sobrenome` | Short text | Yes |
| 3 | `E-mail corporativo` | Email | Yes |
| 4 | `Departamento` | Short text | Yes |
| 5 | `Cargo` | Short text | Yes |

> The plugin looks for lowercase labels: `nome`, `sobrenome`, `e-mail corporativo`, `departamento`, `cargo`. The first three are required — without them, the ticket is ignored.

### 3.3 Form destination (Ticket)

1. Go to the **Destinations** tab of the form
2. Add a destination of type **Ticket**
3. Configure the ticket **Content** with the format below:

```html
<b>1) Nome</b>: {{answers.ID_NOME}}<br>
<b>2) Sobrenome</b>: {{answers.ID_SOBRENOME}}<br>
<b>3) E-mail corporativo</b>: {{answers.ID_EMAIL}}<br>
<b>4) Departamento</b>: {{answers.ID_DEPARTAMENTO}}<br>
<b>5) Cargo</b>: {{answers.ID_CARGO}}<br>
```

Replace `ID_*` with the actual identifier of each question (shown in the interface when configuring the destination).

> **Why this format?** The `TicketHook` uses regex `/<b>\d+\)\s*([^<]+)<\/b>\s*:\s*([^<]+)/i` to extract `Label: Value` pairs from the ticket's HTML content. The format must follow this pattern exactly.

### 3.4 Access control

1. Go to the **Access controls** tab of the form
2. Enable the option **"Allow specific users, groups or profiles"**
3. In the selection field, add **"User - All users"**
4. Click **Save changes**

The form will be visible in the **Service Catalog** to all authenticated users.

---

## Part 4 — Verify the Full Flow

1. Open GLPI and go to **Assistance > Service Catalog**
2. Click **"Request AD User Creation"**
3. Fill in the fields:
   - **Nome**: Rafael
   - **Sobrenome**: Silva
   - **E-mail corporativo**: rafael.silva@company.com
   - **Departamento**: IT
   - **Cargo**: Analyst
4. Click **Submit**
5. Check the queue: **Administration > GLPIADmit Queue**
6. Wait up to 60 seconds (CronTask cycle)
7. Refresh the ticket — a followup with confirmation should appear

### What to check if it doesn't work

| Symptom | Probable cause |
|---|---|
| Ticket created but nothing in queue | Plugin disabled (Enabled = No) |
| Ticket created but no queue item | Content format doesn't match the regex |
| Queue item stuck as PENDING | CronTask is not running |
| Queue item as ERROR | Check `error_message` field in the details |
| Followup doesn't appear | CronTask ran but failed — check log |

See [06-troubleshooting.md](06-troubleshooting.md) for detailed diagnostics.
