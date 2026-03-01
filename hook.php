<?php

/**
 * GLPIADmit - Install/Uninstall hooks
 *
 * @license GPL-3.0-or-later
 */

function plugin_glpiadmit_install(): bool
{
    global $DB;

    $migration = new Migration(PLUGIN_GLPIADMIT_VERSION);

    // Create queue table (idempotent)
    if (!$DB->tableExists('glpi_plugin_glpiadmit_queues')) {
        $query = "CREATE TABLE IF NOT EXISTS `glpi_plugin_glpiadmit_queues` (
            `id` int unsigned NOT NULL AUTO_INCREMENT,
            `tickets_id` int unsigned NOT NULL,
            `first_name` varchar(255) NOT NULL DEFAULT '',
            `last_name` varchar(255) NOT NULL DEFAULT '',
            `email` varchar(255) NOT NULL DEFAULT '',
            `department` varchar(255) NOT NULL DEFAULT '',
            `job_title` varchar(255) NOT NULL DEFAULT '',
            `status` int NOT NULL DEFAULT 0 COMMENT 'pending=0,processing=1,done=2,error=3',
            `attempts` int NOT NULL DEFAULT 0,
            `error_message` text DEFAULT NULL,
            `is_permanent_error` tinyint(1) NOT NULL DEFAULT 0,
            `date_creation` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
            `date_mod` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (`id`),
            UNIQUE KEY `tickets_id` (`tickets_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci";

        $DB->doQueryOrDie($query, sprintf(
            '[GLPIADmit %s] Error creating table glpi_plugin_glpiadmit_queues',
            PLUGIN_GLPIADMIT_VERSION
        ));
    }

    $migration->executeMigration();

    // Register CronTask (idempotent — check if already exists)
    $cron = new CronTask();
    if (!$cron->getFromDBbyName('GlpiPlugin\\Glpiadmit\\QueueItem', 'ProcessQueue')) {
        CronTask::register(
            'GlpiPlugin\\Glpiadmit\\QueueItem',
            'ProcessQueue',
            60,
            [
                'state'   => CronTask::STATE_WAITING,
                'mode'    => CronTask::MODE_EXTERNAL,
                'comment' => 'Process GLPIADmit AD user creation queue',
            ]
        );
    }

    // Set default config values (merge — only insert missing keys)
    $defaults = [
        'ad_server'        => '',
        'ad_port'          => '636',
        'ad_use_ssl'       => '1',
        'ad_bind_dn'       => '',
        'ad_bind_password' => '',
        'ad_base_dn'       => '',
        'ad_user_ou'       => '',
        'ad_domain'        => '',
        'ad_upn_suffix'    => '',
        'ad_groups'        => '',
        'enabled'          => '0',
    ];

    $existing = \Config::getConfigurationValues('plugin:glpiadmit');
    $to_set = [];
    foreach ($defaults as $key => $value) {
        if (!isset($existing[$key])) {
            $to_set[$key] = $value;
        }
    }
    if (!empty($to_set)) {
        \Config::setConfigurationValues('plugin:glpiadmit', $to_set);
    }

    return true;
}

function plugin_glpiadmit_uninstall(): bool
{
    global $DB;

    // Drop queue table
    if ($DB->tableExists('glpi_plugin_glpiadmit_queues')) {
        $DB->doQuery("DROP TABLE `glpi_plugin_glpiadmit_queues`");
    }

    // Remove config values
    $config_keys = [
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
    \Config::deleteConfigurationValues('plugin:glpiadmit', $config_keys);

    // Remove CronTask
    $cron = new CronTask();
    if ($cron->getFromDBbyName('GlpiPlugin\\Glpiadmit\\QueueItem', 'ProcessQueue')) {
        $cron->delete(['id' => $cron->fields['id']]);
    }

    return true;
}
