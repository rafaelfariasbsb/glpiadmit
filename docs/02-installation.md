# Installation

## Prerequisites

| Requirement | Details |
|---|---|
| **GLPI** | 11.0.0 or higher |
| **PHP** | 8.2 or higher |
| **php-ldap** | Required extension (checked by the plugin) |
| **php-intl** | Recommended (iconv fallback for transliteration) |
| **LDAP/LDAPS access** | GLPI server must reach the AD on ports 389/636 |
| **AD service account** | With permission to create users in the designated OU |

---

## 1. Install the plugin

### Option A: Via Git (recommended for development)

```bash
cd /var/www/glpi/plugins
git clone https://github.com/rafaelfariasbsb/glpiadmit.git glpiadmit
```

### Option B: Manual download

1. Download the release from https://github.com/rafaelfariasbsb/glpiadmit/releases
2. Extract to `/var/www/glpi/plugins/glpiadmit/`
3. Verify that `setup.php` is at `/var/www/glpi/plugins/glpiadmit/setup.php`

> The plugin folder **must** be named `glpiadmit` (lowercase, no hyphens).

### Option C: Via GLPI Marketplace

When available, the plugin can be installed directly from the Marketplace:
**Setup > Plugins > Marketplace > Search "GLPIADmit" > Install**

---

## 2. Activate the plugin in GLPI

1. Go to **Setup > Plugins**
2. Find **GLPIADmit** in the list
3. Click **Install**
   - Creates the `glpi_plugin_glpiadmit_queues` table
   - Registers the `ProcessQueue` CronTask
   - Inserts default configuration values
4. Click **Enable**

### Verify prerequisites

If installation fails, check:

```bash
# php-ldap installed?
php -m | grep ldap

# php-intl installed? (recommended)
php -m | grep intl

# PHP version
php -v
```

To install missing extensions (Debian/Ubuntu):

```bash
sudo apt-get install php-ldap php-intl
sudo systemctl restart apache2   # or php-fpm
```

---

## 3. Configure the plugin

After activation, access the configuration:

**Setup > Plugins > GLPIADmit > Configuration**

Fill in the Active Directory connection fields. See:
- [03-configuration.md](03-configuration.md) — Plugin settings, AD setup, form configuration

---

## 4. Verify CronTask

The plugin registers a CronTask called `ProcessQueue` that processes the queue every 60 seconds.

### Verify the CronTask is active

**Setup > Automatic actions** > Search for "ProcessQueue"

| Field | Expected value |
|---|---|
| Name | ProcessQueue |
| ItemType | GlpiPlugin\Glpiadmit\QueueItem |
| Frequency | 60 seconds |
| Status | Waiting |
| Mode | External |

### CronTask in CLI mode

The CronTask runs via GLPI's `cron.php`. Verify that GLPI's cron is configured:

```bash
# Check if cron is in crontab
crontab -l -u www-data | grep glpi

# Should have something like:
# */1 * * * * php /var/www/glpi/front/cron.php
```

If not present, add it:

```bash
echo "*/1 * * * * php /var/www/glpi/front/cron.php" | sudo crontab -u www-data -
```

> **Important**: If the CronTask is not running, items will remain in the queue indefinitely. The plugin configuration page displays a warning when the CronTask hasn't run in the last 5 minutes.

---

## 5. Verify installation

1. **Plugin active**: Setup > Plugins — GLPIADmit shows "Enabled"
2. **Configuration accessible**: Setup > Plugins > GLPIADmit > Configuration
3. **Test Connection**: Fill in the AD fields and click "Test Connection" — should return success
4. **CronTask**: Setup > Automatic actions > ProcessQueue — status "Scheduled"
5. **Queue menu**: Administration > GLPIADmit Queue — empty listing (normal)
6. **Plugin log**: `files/_log/glpiadmit.log` — no errors

---

## Upgrade

To upgrade the plugin:

```bash
cd /var/www/glpi/plugins/glpiadmit
git pull origin main
```

Then in GLPI:
1. Go to **Setup > Plugins**
2. If there's a schema update, click **Install** again (idempotent)
3. The plugin will be updated without data loss

---

## Uninstallation

1. Go to **Setup > Plugins**
2. Click **Disable** on GLPIADmit
3. Click **Uninstall**
   - Removes the `glpi_plugin_glpiadmit_queues` table
   - Removes configuration from the database
   - Removes the CronTask
4. (Optional) Delete the folder: `rm -rf /var/www/glpi/plugins/glpiadmit`

> **Warning**: Uninstallation removes all queue data. Pending items will be lost.
