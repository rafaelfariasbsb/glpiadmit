<?php

/**
 * GLPIADmit - Queue item listing
 *
 * @license GPL-3.0-or-later
 */

use GlpiPlugin\Glpiadmit\QueueItem;

include('../../../inc/includes.php');

Session::checkRight('config', READ);

Html::header(
    QueueItem::getTypeName(2),
    $_SERVER['PHP_SELF'],
    'admin',
    'GlpiPlugin\\Glpiadmit\\QueueItem'
);

Search::show(QueueItem::class);

Html::footer();
