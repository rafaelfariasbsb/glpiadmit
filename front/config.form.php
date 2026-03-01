<?php

/**
 * GLPIADmit - Configuration form handler
 *
 * @license GPL-3.0-or-later
 */

use GlpiPlugin\Glpiadmit\Config;

include('../../../inc/includes.php');

Session::checkRight('config', UPDATE);

if (isset($_POST['action']) && $_POST['action'] === 'save') {
    $fields = [
        'ad_server',
        'ad_port',
        'ad_use_ssl',
        'ad_bind_dn',
        'ad_bind_password',
        'ad_base_dn',
        'ad_user_ou',
        'ad_domain',
        'ad_upn_suffix',
        'ad_groups',
        'enabled',
    ];

    // Validation rules
    $validations = [
        'ad_server' => static function (string $v): bool {
            // Red Team R4: hostname/IP only, no protocol prefix
            return $v !== '' && (bool) preg_match('/^[a-zA-Z0-9.\-]+$/', $v);
        },
        'ad_port' => static function (string $v): bool {
            $port = (int) $v;
            return $port >= 1 && $port <= 65535;
        },
        'ad_use_ssl' => static function (string $v): bool {
            return in_array($v, ['0', '1'], true);
        },
        'ad_bind_dn' => static function (string $v): bool {
            return $v !== '';
        },
        'ad_bind_password' => static function (string $v): bool {
            return $v !== '';
        },
        'ad_base_dn' => static function (string $v): bool {
            return $v !== '';
        },
        'ad_domain' => static function (string $v): bool {
            return $v !== '';
        },
        'ad_upn_suffix' => static function (string $v): bool {
            // Adversarial F15: must start with @ and contain at least one .
            return $v !== '' && str_starts_with($v, '@') && str_contains($v, '.');
        },
        'ad_user_ou' => static function (string $v): bool {
            return $v !== '';
        },
    ];

    $values = [];
    $hasError = false;

    foreach ($fields as $field) {
        if (!isset($_POST[$field])) {
            continue;
        }

        $value = $_POST[$field];

        // Enabled: validate boolean
        if ($field === 'enabled') {
            $value = in_array($value, ['0', '1'], true) ? $value : '0';
        }

        // Port: clamp to range
        if ($field === 'ad_port') {
            $value = (string) max(1, min(65535, (int) $value));
        }

        // ad_groups: validate each line as DN format (Red Team R11)
        if ($field === 'ad_groups' && $value !== '') {
            $lines = array_filter(array_map('trim', explode("\n", $value)));
            foreach ($lines as $line) {
                if (!preg_match('/^[A-Za-z]+=.+$/', $line)) {
                    Session::addMessageAfterRedirect(
                        htmlescape(sprintf(__('Invalid DN format in groups: "%s"'), $line)),
                        false,
                        ERROR
                    );
                    $hasError = true;
                    break;
                }
            }
            if ($hasError) {
                continue;
            }
        }

        // Validate format fields
        if (isset($validations[$field]) && $value !== '' && !$validations[$field]($value)) {
            Session::addMessageAfterRedirect(
                htmlescape(sprintf(__('Invalid value for field "%s". Please check the format.'), $field)),
                false,
                ERROR
            );
            $hasError = true;
            continue;
        }

        $values[$field] = $value;
    }

    if ($hasError) {
        Html::back();
    }

    Config::set($values);

    Session::addMessageAfterRedirect(
        __('Configuration updated successfully.'),
        true,
        INFO
    );

    Html::back();
}

if (isset($_POST['action']) && $_POST['action'] === 'test') {
    // Red Team R12: throttle — 5 seconds between tests
    $lastTest = $_SESSION['glpiadmit_last_test'] ?? 0;
    if ($lastTest > time() - 5) {
        Session::addMessageAfterRedirect(
            __('Please wait 5 seconds between connection tests.'),
            false,
            ERROR
        );
        Html::back();
    }
    $_SESSION['glpiadmit_last_test'] = time();

    $result = Config::testConnection();

    if ($result === true) {
        Session::addMessageAfterRedirect(
            __('LDAP connection successful!'),
            true,
            INFO
        );
    } else {
        Session::addMessageAfterRedirect(
            htmlescape(sprintf(__('Connection test failed: %s'), $result)),
            true,
            ERROR
        );
    }

    Html::back();
}
