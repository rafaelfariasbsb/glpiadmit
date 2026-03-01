<?php

/**
 * GLPIADmit - Automated AD user creation from GLPI tickets
 *
 * @license GPL-3.0-or-later
 */

use Glpi\Plugin\Hooks;
use GlpiPlugin\Glpiadmit\TicketHook;
use GlpiPlugin\Glpiadmit\QueueItem;

define('PLUGIN_GLPIADMIT_VERSION', '1.0.0');
define('PLUGIN_GLPIADMIT_MIN_GLPI_VERSION', '11.0.0');
define('PLUGIN_GLPIADMIT_MAX_GLPI_VERSION', '11.0.99');

function plugin_version_glpiadmit(): array
{
    return [
        'name'         => 'GLPIADmit',
        'version'      => PLUGIN_GLPIADMIT_VERSION,
        'author'       => 'Rafael Farias',
        'license'      => 'GPLv3+',
        'homepage'     => 'https://github.com/rafaelfariasbsb/glpiadmit',
        'requirements' => [
            'glpi' => [
                'min' => PLUGIN_GLPIADMIT_MIN_GLPI_VERSION,
                'max' => PLUGIN_GLPIADMIT_MAX_GLPI_VERSION,
            ],
            'php' => [
                'min' => '8.2',
                'exts' => ['ldap'],
            ],
        ],
    ];
}

function plugin_glpiadmit_check_prerequisites(): bool
{
    if (!extension_loaded('ldap')) {
        Session::addMessageAfterRedirect(
            __('GLPIADmit plugin requires the php-ldap extension.'),
            false,
            ERROR
        );
        return false;
    }

    if (!extension_loaded('intl')) {
        // intl is recommended but not required (iconv fallback exists)
        trigger_error(
            '[GLPIADmit] php-intl extension not loaded. Using iconv fallback for transliteration.',
            E_USER_NOTICE
        );
    }

    return true;
}

function plugin_glpiadmit_check_config($verbose = false): bool
{
    return true;
}

function plugin_init_glpiadmit(): void
{
    global $PLUGIN_HOOKS;

    $PLUGIN_HOOKS[Hooks::CSRF_COMPLIANT]['glpiadmit'] = true;

    $plugin = new Plugin();
    if (!$plugin->isActivated('glpiadmit')) {
        return;
    }

    // Config page
    $PLUGIN_HOOKS[Hooks::CONFIG_PAGE]['glpiadmit'] = 'front/config.php';

    // Encrypt sensitive config values
    $PLUGIN_HOOKS[Hooks::SECURED_CONFIGS]['glpiadmit'] = [
        'ad_bind_password',
    ];

    // Hook on Ticket creation
    $PLUGIN_HOOKS[Hooks::ITEM_ADD]['glpiadmit'] = [
        'Ticket' => [TicketHook::class, 'onItemAdd'],
    ];

    // QueueItem as navigable itemtype with tab on Ticket
    Plugin::registerClass(QueueItem::class, ['addtabon' => ['Ticket']]);

    // Menu entry under Admin
    $PLUGIN_HOOKS[Hooks::MENU_TOADD]['glpiadmit'] = ['admin' => QueueItem::class];
}
