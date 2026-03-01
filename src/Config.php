<?php

/**
 * @license GPL-3.0-or-later
 */

namespace GlpiPlugin\Glpiadmit;

class Config
{
    private const CONTEXT = 'plugin:glpiadmit';

    private const SECURED_FIELDS = ['ad_bind_password'];

    /** @var array<string, string>|null Per-request cache (NOT decrypted). */
    private static ?array $cache = null;

    /**
     * Get all plugin config values (password stays encrypted).
     * Safe for templates and display contexts.
     *
     * @return array<string, string>
     */
    public static function getAll(): array
    {
        if (self::$cache === null) {
            self::$cache = \Config::getConfigurationValues(self::CONTEXT);
        }
        return self::$cache;
    }

    /**
     * Get all plugin config values with secured fields decrypted.
     * Use ONLY for connect() and testConnection() — never in templates.
     *
     * @return array<string, string>
     */
    public static function getAllDecrypted(): array
    {
        $config = self::getAll();
        self::decryptSecuredFields($config);
        return $config;
    }

    /**
     * Get a single configuration value (not decrypted).
     */
    public static function get(string $key, string $default = ''): string
    {
        $config = self::getAll();
        return $config[$key] ?? $default;
    }

    /**
     * Set configuration values and invalidate cache.
     *
     * @param array<string, string> $values
     */
    public static function set(array $values): void
    {
        \Config::setConfigurationValues(self::CONTEXT, $values);
        self::$cache = null;
    }

    /**
     * Decrypt secured fields in-place.
     *
     * @param array<string, string> $config
     */
    private static function decryptSecuredFields(array &$config): void
    {
        $glpiKey = new \GLPIKey();
        foreach (self::SECURED_FIELDS as $field) {
            if (!empty($config[$field])) {
                try {
                    $decrypted = $glpiKey->decrypt($config[$field]);
                    $config[$field] = $decrypted !== '' ? $decrypted : $config[$field];
                } catch (\Throwable $e) {
                    \Toolbox::logInFile('glpiadmit', sprintf(
                        "DECRYPT FAILED | field=%s | error=%s\n",
                        $field,
                        $e->getMessage()
                    ));
                }
            }
        }
    }

    /**
     * Test LDAP connection using current config.
     * Validates bind AND base_dn accessibility (Critique C6).
     *
     * @return true|string True on success, error message on failure.
     */
    public static function testConnection(): true|string
    {
        $config = self::getAllDecrypted();

        $server = $config['ad_server'] ?? '';
        $port = (int) ($config['ad_port'] ?? 636);
        $useSsl = ($config['ad_use_ssl'] ?? '1') === '1';
        $bindDn = $config['ad_bind_dn'] ?? '';
        $bindPassword = $config['ad_bind_password'] ?? '';
        $baseDn = $config['ad_base_dn'] ?? '';

        if (empty($server) || empty($bindDn) || empty($bindPassword)) {
            return 'Server, Bind DN and Bind Password are required.';
        }

        $uri = ($useSsl ? 'ldaps://' : 'ldap://') . $server . ':' . $port;

        $conn = @ldap_connect($uri);
        if ($conn === false) {
            return 'Failed to initialize LDAP connection.';
        }

        ldap_set_option($conn, LDAP_OPT_PROTOCOL_VERSION, 3);
        ldap_set_option($conn, LDAP_OPT_REFERRALS, 0);
        ldap_set_option($conn, LDAP_OPT_NETWORK_TIMEOUT, 10);

        $bound = @ldap_bind($conn, $bindDn, $bindPassword);
        if (!$bound) {
            $error = ldap_error($conn);
            @ldap_unbind($conn);
            return sprintf('Bind failed: %s', $error);
        }

        // Validate base_dn is accessible (Critique C6)
        if (!empty($baseDn)) {
            $search = @ldap_search($conn, $baseDn, '(objectClass=*)', ['dn'], 0, 1);
            if ($search === false) {
                $error = ldap_error($conn);
                @ldap_unbind($conn);
                return sprintf('Bind OK, but base_dn not accessible: %s', $error);
            }
            @ldap_free_result($search);
        }

        @ldap_unbind($conn);
        return true;
    }
}
