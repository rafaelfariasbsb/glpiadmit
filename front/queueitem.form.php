<?php

/**
 * GLPIADmit - Queue item actions (retry, force_retry)
 *
 * @license GPL-3.0-or-later
 */

use GlpiPlugin\Glpiadmit\QueueItem;

include('../../../inc/includes.php');

Session::checkRight('config', UPDATE);

// Handle GET request — show form
if (isset($_GET['id'])) {
    Html::header(
        QueueItem::getTypeName(1),
        $_SERVER['PHP_SELF'],
        'admin',
        'GlpiPlugin\\Glpiadmit\\QueueItem'
    );

    $queueItem = new QueueItem();
    $queueItem->display(['id' => (int) $_GET['id']]);

    Html::footer();
    return;
}

// Handle POST actions
if (isset($_POST['action'])) {
    $itemId = (int) ($_POST['id'] ?? 0);

    if ($itemId <= 0) {
        Session::addMessageAfterRedirect(__('Invalid queue item.'), false, ERROR);
        Html::back();
    }

    $queueItem = new QueueItem();
    if (!$queueItem->getFromDB($itemId)) {
        Session::addMessageAfterRedirect(__('Queue item not found.'), false, ERROR);
        Html::back();
    }

    if ($_POST['action'] === 'retry') {
        // Red Team R13: server-side verification
        if (!$queueItem->canRetry()) {
            Session::addMessageAfterRedirect(
                __('This item cannot be retried (permanent error or not in error state).'),
                false,
                ERROR
            );
            Html::back();
        }

        $queueItem->update([
            'id'       => $itemId,
            'status'   => QueueItem::STATUS_PENDING,
            'attempts' => 0,
        ]);

        Session::addMessageAfterRedirect(
            __('Item queued for retry.'),
            true,
            INFO
        );
    }

    if ($_POST['action'] === 'force_retry') {
        // Adversarial F1/F9: force retry resets everything including is_permanent_error
        if ((int) $queueItem->fields['status'] !== QueueItem::STATUS_ERROR) {
            Session::addMessageAfterRedirect(
                __('Force retry is only available for items in error state.'),
                false,
                ERROR
            );
            Html::back();
        }

        $queueItem->update([
            'id'                 => $itemId,
            'status'             => QueueItem::STATUS_PENDING,
            'attempts'           => 0,
            'is_permanent_error' => 0,
        ]);

        Session::addMessageAfterRedirect(
            __('Item queued for forced retry (permanent error flag cleared).'),
            true,
            INFO
        );
    }

    Html::back();
}
