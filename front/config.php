<?php

/**
 * GLPIADmit - Configuration page
 *
 * @license GPL-3.0-or-later
 */

use Glpi\Application\View\TemplateRenderer;
use GlpiPlugin\Glpiadmit\Config;

include('../../../inc/includes.php');

Session::checkRight('config', READ);

Html::header(
    __('GLPIADmit'),
    $_SERVER['PHP_SELF'],
    'config',
    'plugins'
);

$config = Config::getAll();

// Pre-mortem F2: CronTask health indicator
$cronHealthWarning = '';
$cron = new CronTask();
if ($cron->getFromDBbyName('GlpiPlugin\\Glpiadmit\\QueueItem', 'ProcessQueue')) {
    $lastRun = $cron->fields['lastrun'] ?? null;
    if ($lastRun !== null && strtotime($lastRun) < time() - 300) {
        $cronHealthWarning = sprintf(
            __('Warning: CronTask last executed at %s (more than 5 minutes ago).'),
            $lastRun
        );
    } elseif ($lastRun === null) {
        $cronHealthWarning = __('Warning: CronTask has never been executed.');
    }
}

TemplateRenderer::getInstance()->display(
    '@glpiadmit/config.html.twig',
    [
        'config'              => $config,
        'canedit'             => Session::haveRight('config', UPDATE),
        'cron_health_warning' => $cronHealthWarning,
    ]
);

Html::footer();
