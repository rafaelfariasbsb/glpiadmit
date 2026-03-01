<?php

/**
 * @license GPL-3.0-or-later
 */

namespace GlpiPlugin\Glpiadmit;

class ADService
{
    private const UAC_DISABLED_ACCOUNT = 514;
    private const UAC_NORMAL_ACCOUNT = 512;

    private const OBJECT_CLASSES = ['top', 'person', 'organizationalPerson', 'user'];

    /**
     * Permanent error patterns — these will NOT be retried (Adversarial F2).
     */
    private const PERMANENT_ERROR_PATTERNS = [
        'object class violation',
        'constraint violation',
        'already exists',
    ];

    /** @var callable|null Factory for creating LDAP connections (for testing). */
    private $connectionFactory;

    public function __construct(?callable $connectionFactory = null)
    {
        $this->connectionFactory = $connectionFactory;
    }

    /**
     * Connect to AD using plugin config.
     *
     * @return \LDAP\Connection LDAP connection resource
     * @throws \RuntimeException On connection failure.
     */
    public function connect(): \LDAP\Connection
    {
        if ($this->connectionFactory !== null) {
            return ($this->connectionFactory)();
        }

        $config = Config::getAllDecrypted();

        $server = $config['ad_server'] ?? '';
        $port = (int) ($config['ad_port'] ?? 636);
        $useSsl = ($config['ad_use_ssl'] ?? '1') === '1';
        $bindDn = $config['ad_bind_dn'] ?? '';
        $bindPassword = $config['ad_bind_password'] ?? '';

        $uri = ($useSsl ? 'ldaps://' : 'ldap://') . $server . ':' . $port;

        $conn = @ldap_connect($uri);
        if ($conn === false) {
            throw new \RuntimeException('Failed to initialize LDAP connection');
        }

        ldap_set_option($conn, LDAP_OPT_PROTOCOL_VERSION, 3);
        ldap_set_option($conn, LDAP_OPT_REFERRALS, 0);
        ldap_set_option($conn, LDAP_OPT_NETWORK_TIMEOUT, 10);

        $bound = @ldap_bind($conn, $bindDn, $bindPassword);
        if (!$bound) {
            $error = ldap_error($conn);
            @ldap_unbind($conn);
            throw new \RuntimeException(sprintf('LDAP bind failed: %s', $error));
        }

        return $conn;
    }

    /**
     * Process AD user creation for a queue item.
     *
     * @param \LDAP\Connection $conn Active LDAP connection
     * @param array $queueData Queue item fields
     * @return array{success: bool, message: string, sam: string, password: string, is_permanent: bool}
     */
    public function processUserCreation(\LDAP\Connection $conn, array $queueData): array
    {
        $result = [
            'success'      => false,
            'message'      => '',
            'sam'          => '',
            'password'     => '',
            'is_permanent' => false,
        ];

        $firstName = $queueData['first_name'] ?? '';
        $lastName = $queueData['last_name'] ?? '';
        $email = $queueData['email'] ?? '';
        $department = $queueData['department'] ?? '';
        $jobTitle = $queueData['job_title'] ?? '';
        $ticketId = (int) ($queueData['tickets_id'] ?? 0);

        // Validate input
        if (empty($firstName) || empty($lastName) || empty($email)) {
            $result['message'] = 'Missing required fields (first_name, last_name, email)';
            $result['is_permanent'] = true;
            return $result;
        }

        $config = Config::getAllDecrypted();

        try {
            // Generate attributes
            $sam = Validators::generateSamAccountName($firstName, $lastName);
            $upnSuffix = $config['ad_upn_suffix'] ?? '';
            $upn = Validators::generateUpn($sam, $upnSuffix);
            $displayName = Validators::generateDisplayName($firstName, $lastName);
            $cn = $displayName;
            $safeCn = Validators::sanitizeDnComponent($cn);
            $userOu = $config['ad_user_ou'] ?? '';
            $dn = sprintf('CN=%s,%s', $safeCn, $userOu);

            $result['sam'] = $sam;

            \Toolbox::logInFile('glpiadmit', sprintf(
                "[AD_CREATE] Ticket #%d: sAM=%s, UPN=%s, DN=%s\n",
                $ticketId,
                $sam,
                $upn,
                $dn
            ));

            // Check for duplicate user
            $this->checkDuplicateUser($conn, $sam, $email, $config['ad_base_dn'] ?? '');

            // Create user (disabled)
            $this->createUser($conn, $dn, [
                'sAMAccountName'     => $sam,
                'userPrincipalName'  => $upn,
                'givenName'          => $firstName,
                'sn'                 => $lastName,
                'displayName'        => $displayName,
                'mail'               => $email,
                'department'         => $department,
                'title'              => $jobTitle,
                'userAccountControl' => (string) self::UAC_DISABLED_ACCOUNT,
            ]);

            // Generate password and configure account
            $password = PasswordGenerator::generate(16);
            $result['password'] = $password;

            try {
                $this->setPassword($conn, $dn, $password);
                $this->enableAccount($conn, $dn);
            } catch (\Throwable $e) {
                // Password/enable failed — rollback user creation
                $this->rollback($conn, $dn, $ticketId);
                throw $e;
            }

            // Add to groups (non-blocking)
            $groupsRaw = $config['ad_groups'] ?? '';
            $groups = array_filter(array_map('trim', explode("\n", $groupsRaw)));
            if (!empty($groups)) {
                $this->addToGroups($conn, $dn, $groups, $ticketId);
            }

            $result['success'] = true;
            $result['message'] = sprintf(
                'User %s (%s) created successfully in AD.',
                $displayName,
                $sam
            );

            // Red Team R3: NEVER log the temporary password
            \Toolbox::logInFile('glpiadmit', sprintf(
                "[AD_SUCCESS] Ticket #%d: sAM=%s created\n",
                $ticketId,
                $sam
            ));
        } catch (\RuntimeException $e) {
            $result['message'] = $e->getMessage();
            $result['is_permanent'] = $this->isPermanentError($e->getMessage());

            \Toolbox::logInFile('glpiadmit', sprintf(
                "[AD_ERROR] Ticket #%d: %s (permanent=%s)\n",
                $ticketId,
                $e->getMessage(),
                $result['is_permanent'] ? 'yes' : 'no'
            ));
        } catch (\Throwable $e) {
            $result['message'] = $e->getMessage();
            $result['is_permanent'] = $this->isPermanentError($e->getMessage());

            \Toolbox::logInFile('glpiadmit', sprintf(
                "[AD_ERROR] Ticket #%d: %s (permanent=%s)\n",
                $ticketId,
                $e->getMessage(),
                $result['is_permanent'] ? 'yes' : 'no'
            ));
        }

        return $result;
    }

    /**
     * Check if a user with the same sAMAccountName or email already exists in AD.
     *
     * @throws \RuntimeException If duplicate found (permanent error).
     */
    private function checkDuplicateUser(\LDAP\Connection $conn, string $sam, string $email, string $baseDn): void
    {
        $safeSam = Validators::sanitizeLdapValue($sam);
        $safeEmail = Validators::sanitizeLdapValue($email);

        $filter = sprintf(
            '(|(sAMAccountName=%s)(mail=%s))',
            $safeSam,
            $safeEmail
        );

        $search = @ldap_search($conn, $baseDn, $filter, ['sAMAccountName'], 0, 1);
        if ($search === false) {
            return; // Search failed — don't block creation
        }

        $count = ldap_count_entries($conn, $search);
        ldap_free_result($search);

        if ($count > 0) {
            throw new \RuntimeException(
                sprintf('User already exists in AD: sAMAccountName=%s or mail=%s', $sam, $email)
            );
        }
    }

    /**
     * Create user object in AD (disabled).
     */
    private function createUser(\LDAP\Connection $conn, string $dn, array $attrs): void
    {
        $entry = $attrs;
        $entry['objectClass'] = self::OBJECT_CLASSES;

        $added = @ldap_add($conn, $dn, $entry);
        if (!$added) {
            throw new \RuntimeException(sprintf('ldap_add failed: %s', ldap_error($conn)));
        }
    }

    /**
     * Set user password via unicodePwd (requires LDAPS).
     */
    private function setPassword(\LDAP\Connection $conn, string $dn, string $password): void
    {
        $encodedPassword = iconv('UTF-8', 'UTF-16LE', '"' . $password . '"');

        $modifications = [
            [
                'attrib'  => 'unicodePwd',
                'modtype' => LDAP_MODIFY_BATCH_REPLACE,
                'values'  => [$encodedPassword],
            ],
        ];

        $result = @ldap_modify_batch($conn, $dn, $modifications);
        if (!$result) {
            throw new \RuntimeException(sprintf('setPassword failed: %s', ldap_error($conn)));
        }
    }

    /**
     * Enable user account (UAC 512) and force password change at next login.
     */
    private function enableAccount(\LDAP\Connection $conn, string $dn): void
    {
        $modifications = [
            [
                'attrib'  => 'userAccountControl',
                'modtype' => LDAP_MODIFY_BATCH_REPLACE,
                'values'  => [(string) self::UAC_NORMAL_ACCOUNT],
            ],
            [
                'attrib'  => 'pwdLastSet',
                'modtype' => LDAP_MODIFY_BATCH_REPLACE,
                'values'  => ['0'],
            ],
        ];

        $result = @ldap_modify_batch($conn, $dn, $modifications);
        if (!$result) {
            throw new \RuntimeException(sprintf('enableAccount failed: %s', ldap_error($conn)));
        }
    }

    /**
     * Add user to AD groups. Non-blocking — logs errors but does not throw.
     */
    private function addToGroups(\LDAP\Connection $conn, string $userDn, array $groups, int $ticketId): void
    {
        if (empty($groups)) {
            return;
        }

        foreach ($groups as $groupDn) {
            $groupDn = trim($groupDn);
            if (empty($groupDn)) {
                continue;
            }

            $result = @ldap_mod_add($conn, $groupDn, ['member' => [$userDn]]);
            if (!$result) {
                \Toolbox::logInFile('glpiadmit', sprintf(
                    "[AD_GROUP_WARN] Ticket #%d: failed to add to group %s: %s\n",
                    $ticketId,
                    $groupDn,
                    ldap_error($conn)
                ));
            }
        }
    }

    /**
     * Rollback: delete the created user object.
     * If rollback fails (e.g. connection dead), mark as permanent with orphan warning (Adversarial F14).
     */
    private function rollback(\LDAP\Connection $conn, string $dn, int $ticketId): void
    {
        $deleted = @ldap_delete($conn, $dn);
        if ($deleted) {
            \Toolbox::logInFile('glpiadmit', sprintf(
                "[AD_ROLLBACK] Ticket #%d: user %s rolled back (deleted)\n",
                $ticketId,
                $dn
            ));
        } else {
            // Adversarial F14: rollback failed — orphan object in AD
            \Toolbox::logInFile('glpiadmit', sprintf(
                "CRITICAL [AD_ROLLBACK_FAILED] Ticket #%d: orphan object in AD: %s — manual cleanup required. Error: %s\n",
                $ticketId,
                $dn,
                ldap_error($conn)
            ));
        }
    }

    /**
     * Determine if an error is permanent (should not be retried).
     */
    private function isPermanentError(string $message): bool
    {
        $messageLower = strtolower($message);
        foreach (self::PERMANENT_ERROR_PATTERNS as $pattern) {
            if (str_contains($messageLower, $pattern)) {
                return true;
            }
        }
        return false;
    }

    /**
     * Check if an error indicates a connection problem (for reconnection logic).
     */
    public function isConnectionError(string $message): bool
    {
        $patterns = [
            "can't contact ldap server",
            'operations error',
            'server is busy',
            'connection timed out',
            'ldap bind failed',
        ];
        $messageLower = strtolower($message);
        foreach ($patterns as $pattern) {
            if (str_contains($messageLower, $pattern)) {
                return true;
            }
        }
        return false;
    }
}
