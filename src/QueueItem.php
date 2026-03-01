<?php

/**
 * @license GPL-3.0-or-later
 */

namespace GlpiPlugin\Glpiadmit;

use CommonDBTM;
use CommonGLPI;
use CommonITILObject;
use CronTask;
use Glpi\Application\View\TemplateRenderer;
use ITILFollowup;
use Search;
use Ticket;

class QueueItem extends CommonDBTM
{
    public static $table = 'glpi_plugin_glpiadmit_queues';
    public static $rightname = 'config';

    public const STATUS_PENDING    = 0;
    public const STATUS_PROCESSING = 1;
    public const STATUS_DONE       = 2;
    public const STATUS_ERROR      = 3;

    public const MAX_ATTEMPTS = 3;
    public const BATCH_LIMIT  = 10;

    public static function getTypeName($nb = 0): string
    {
        return _n('GLPIADmit Queue', 'GLPIADmit Queue', $nb);
    }

    /**
     * GLPI search options for the queue listing.
     */
    public function rawSearchOptions(): array
    {
        $options = parent::rawSearchOptions();

        $options[] = [
            'id'       => 2,
            'table'    => self::$table,
            'field'    => 'tickets_id',
            'name'     => __('Ticket'),
            'datatype' => 'itemlink',
            'itemtype' => 'Ticket',
        ];

        $options[] = [
            'id'    => 3,
            'table' => self::$table,
            'field' => 'first_name',
            'name'  => __('First Name'),
        ];

        $options[] = [
            'id'    => 4,
            'table' => self::$table,
            'field' => 'last_name',
            'name'  => __('Last Name'),
        ];

        $options[] = [
            'id'    => 5,
            'table' => self::$table,
            'field' => 'email',
            'name'  => __('Email'),
        ];

        $options[] = [
            'id'       => 6,
            'table'    => self::$table,
            'field'    => 'status',
            'name'     => __('Status'),
            'datatype' => 'integer',
        ];

        $options[] = [
            'id'       => 7,
            'table'    => self::$table,
            'field'    => 'attempts',
            'name'     => __('Attempts'),
            'datatype' => 'integer',
        ];

        $options[] = [
            'id'          => 8,
            'table'       => self::$table,
            'field'       => 'error_message',
            'name'        => __('Error Message'),
            'datatype'    => 'text',
            'spliceParams' => ['maxlength' => 80],
        ];

        $options[] = [
            'id'       => 9,
            'table'    => self::$table,
            'field'    => 'date_creation',
            'name'     => __('Date Created'),
            'datatype' => 'datetime',
        ];

        $options[] = [
            'id'       => 10,
            'table'    => self::$table,
            'field'    => 'date_mod',
            'name'     => __('Date Modified'),
            'datatype' => 'datetime',
        ];

        return $options;
    }

    /**
     * Display the form for a single queue item (ADR-3: Twig auto-escaping).
     */
    public function showForm($ID, array $options = []): bool
    {
        $this->initForm($ID, $options);
        $this->showFormHeader($options);

        TemplateRenderer::getInstance()->display(
            '@glpiadmit/queueitem.html.twig',
            [
                'item'      => $this,
                'can_retry' => $this->canRetry(),
                'can_force_retry' => (int) ($this->fields['status'] ?? -1) === self::STATUS_ERROR
                    && (int) ($this->fields['is_permanent_error'] ?? 0) === 1,
                'status_label' => self::getStatusLabel((int) ($this->fields['status'] ?? 0)),
            ]
        );

        return true;
    }

    /**
     * Tab name for display on Ticket (Critique C2).
     */
    public function getTabNameForItem(CommonGLPI $item, $withtemplate = 0): string
    {
        if (!($item instanceof Ticket)) {
            return '';
        }

        $queueItem = new self();
        $results = $queueItem->find(['tickets_id' => $item->getID()]);
        if (empty($results)) {
            return '';
        }

        return 'GLPIADmit';
    }

    /**
     * Display tab content on Ticket (Critique C2).
     */
    public static function displayTabContentForItem(CommonGLPI $item, $tabnum = 1, $withtemplate = 0): bool
    {
        if (!($item instanceof Ticket)) {
            return false;
        }

        $queueItem = new self();
        $results = $queueItem->find(['tickets_id' => $item->getID()]);

        if (empty($results)) {
            echo '<p>' . __('No GLPIADmit queue item for this ticket.') . '</p>';
            return true;
        }

        $data = reset($results);
        $statusLabel = self::getStatusLabel((int) ($data['status'] ?? 0));

        echo '<table class="tab_cadre_fixe">';
        echo '<tr><th colspan="2">' . __('GLPIADmit Queue Item') . '</th></tr>';
        echo '<tr><td>' . __('Status') . '</td><td>' . htmlspecialchars($statusLabel, ENT_QUOTES, 'UTF-8') . '</td></tr>';
        echo '<tr><td>' . __('Attempts') . '</td><td>' . (int) $data['attempts'] . '</td></tr>';
        if (!empty($data['error_message'])) {
            echo '<tr><td>' . __('Error') . '</td><td>' . htmlspecialchars($data['error_message'], ENT_QUOTES, 'UTF-8') . '</td></tr>';
        }
        echo '<tr><td colspan="2"><a href="' . htmlspecialchars(self::getFormURLWithID($data['id']), ENT_QUOTES, 'UTF-8') . '">' . __('View Details') . '</a></td></tr>';
        echo '</table>';

        return true;
    }

    /**
     * CronTask information.
     */
    public static function cronInfo(string $name): array
    {
        if ($name === 'ProcessQueue') {
            return [
                'description' => __('Process GLPIADmit AD user creation queue'),
            ];
        }
        return [];
    }

    /**
     * CronTask: process pending queue items.
     * Reuses LDAP connection within a cycle (ADR-4).
     * ldap_unbind in finally (First Principles S4).
     */
    public static function cronProcessQueue(CronTask $task): int
    {
        global $DB;

        $adService = new ADService();
        $conn = null;
        $processed = 0;
        $successes = 0;
        $failures = 0;
        $allConnectionErrors = true;

        try {
            // Connect once for the entire cycle (ADR-4)
            try {
                $conn = $adService->connect();
            } catch (\Throwable $e) {
                \Toolbox::logInFile('glpiadmit', sprintf(
                    "CRITICAL [CRON] Failed to connect to AD: %s\n",
                    $e->getMessage()
                ));
                return 0;
            }

            // Fetch pending items (BATCH_LIMIT)
            $items = $DB->request([
                'FROM'  => self::$table,
                'WHERE' => ['status' => self::STATUS_PENDING],
                'ORDER' => ['date_creation ASC'],
                'LIMIT' => self::BATCH_LIMIT,
            ]);

            foreach ($items as $row) {
                $itemId = (int) $row['id'];
                $ticketId = (int) $row['tickets_id'];

                // Atomic lock: UPDATE WHERE status=0 (concurrency guard)
                $locked = $DB->update(
                    self::$table,
                    ['status' => self::STATUS_PROCESSING],
                    ['id' => $itemId, 'status' => self::STATUS_PENDING]
                );
                if ($DB->affectedRows() === 0) {
                    continue; // Another process got this item
                }

                $processed++;

                // Process
                $result = $adService->processUserCreation($conn, $row);

                if ($result['success']) {
                    $successes++;
                    $allConnectionErrors = false;

                    // Mark done
                    $DB->update(self::$table, [
                        'status'       => self::STATUS_DONE,
                        'error_message' => null,
                    ], ['id' => $itemId]);

                    // Add followups (First Principles S3: private + public)
                    self::addFollowupSuccess($ticketId, $result['sam'], $result['password']);
                } else {
                    $failures++;
                    $attempts = (int) $row['attempts'] + 1;
                    $isPermanent = $result['is_permanent'];

                    // Check if this was a connection error
                    if (!$adService->isConnectionError($result['message'])) {
                        $allConnectionErrors = false;
                    }

                    if ($isPermanent || $attempts >= self::MAX_ATTEMPTS) {
                        // Mark as ERROR
                        $errorMsg = $result['message'];
                        // Adversarial F14: check for orphan
                        if (str_contains($result['message'], 'orphan') || str_contains($result['message'], 'ROLLBACK_FAILED')) {
                            $isPermanent = true;
                        }

                        $DB->update(self::$table, [
                            'status'             => self::STATUS_ERROR,
                            'attempts'           => $attempts,
                            'error_message'      => $errorMsg,
                            'is_permanent_error' => $isPermanent ? 1 : 0,
                        ], ['id' => $itemId]);

                        // Red Team R8: generic error in followup
                        self::addFollowupError(
                            $ticketId,
                            sprintf('Falha ao criar usuário no AD. Tentativa %d de %d. Limite atingido.', $attempts, self::MAX_ATTEMPTS)
                        );
                    } else {
                        // Return to PENDING for retry
                        $DB->update(self::$table, [
                            'status'        => self::STATUS_PENDING,
                            'attempts'      => $attempts,
                            'error_message' => $result['message'],
                        ], ['id' => $itemId]);

                        // Red Team R8: generic error in followup
                        self::addFollowupError(
                            $ticketId,
                            sprintf('Falha ao criar usuário no AD. Tentativa %d de %d.', $attempts, self::MAX_ATTEMPTS)
                        );
                    }

                    // Adversarial F13: reconnect on connection error
                    if ($adService->isConnectionError($result['message']) && $conn !== null) {
                        \Toolbox::logInFile('glpiadmit', sprintf(
                            "[CRON] Connection error detected, attempting reconnect...\n"
                        ));
                        try {
                            @ldap_unbind($conn);
                        } catch (\Throwable $e) {
                            // Ignore
                        }
                        try {
                            $conn = $adService->connect();
                        } catch (\Throwable $e) {
                            \Toolbox::logInFile('glpiadmit', sprintf(
                                "CRITICAL [CRON] Reconnect failed, aborting cycle: %s\n",
                                $e->getMessage()
                            ));
                            break;
                        }
                    }
                }

                $task->addVolume(1);
            }
        } finally {
            // First Principles S4: always unbind
            if ($conn !== null) {
                try {
                    @ldap_unbind($conn);
                } catch (\Throwable $e) {
                    // Ignore
                }
            }
        }

        // Pre-mortem F5: critical alert if all items failed with connection error
        if ($processed > 0 && $failures === $processed && $allConnectionErrors) {
            \Toolbox::logInFile('glpiadmit', sprintf(
                "CRITICAL [CRON] All %d items failed with connection error — check AD credentials/connectivity\n",
                $processed
            ));
        }

        // Critique C5: cycle summary
        \Toolbox::logInFile('glpiadmit', sprintf(
            "[CRON] Cycle complete: %d processed, %d success, %d failures\n",
            $processed,
            $successes,
            $failures
        ));

        return $processed;
    }

    /**
     * Add success followups: private (credentials) + public (confirmation).
     * First Principles S3: two separate followups.
     */
    private static function addFollowupSuccess(int $ticketId, string $sam, string $password): void
    {
        // Private followup with credentials (visible to technicians only)
        $privateContent = sprintf(
            "<b>Usuário criado com sucesso no Active Directory</b><br><br>"
            . "<b>Login (sAMAccountName):</b> %s<br>"
            . "<b>Senha temporária:</b> %s<br><br>"
            . "<i>O usuário deve trocar a senha no primeiro login.</i>",
            htmlspecialchars($sam, ENT_QUOTES, 'UTF-8'),
            htmlspecialchars($password, ENT_QUOTES, 'UTF-8')
        );

        $followup = new ITILFollowup();
        $followup->add([
            'itemtype'   => 'Ticket',
            'items_id'   => $ticketId,
            'content'    => $privateContent,
            'users_id'   => 0,
            'is_private' => 1,
        ]);

        // Public followup (visible to requester)
        $publicContent = '<b>Usuário criado com sucesso no Active Directory.</b><br>'
            . 'As credenciais foram encaminhadas ao responsável.';

        $followup2 = new ITILFollowup();
        $followup2->add([
            'itemtype'   => 'Ticket',
            'items_id'   => $ticketId,
            'content'    => $publicContent,
            'users_id'   => 0,
            'is_private' => 0,
        ]);

        // Update ticket status to SOLVED
        $ticket = new Ticket();
        if ($ticket->getFromDB($ticketId)) {
            $ticket->update([
                'id'     => $ticketId,
                'status' => CommonITILObject::SOLVED,
            ]);
        }
    }

    /**
     * Add error followup (public, generic message).
     * Red Team R8: technical details go to log only.
     */
    private static function addFollowupError(int $ticketId, string $message): void
    {
        $followup = new ITILFollowup();
        $followup->add([
            'itemtype'   => 'Ticket',
            'items_id'   => $ticketId,
            'content'    => '<b>Erro na criação de usuário AD</b><br>' . htmlspecialchars($message, ENT_QUOTES, 'UTF-8'),
            'users_id'   => 0,
            'is_private' => 0,
        ]);

        // Update ticket status to WAITING
        $ticket = new Ticket();
        if ($ticket->getFromDB($ticketId)) {
            $ticket->update([
                'id'     => $ticketId,
                'status' => CommonITILObject::WAITING,
            ]);
        }
    }

    /**
     * Check if this item can be retried (ADR-5).
     */
    public function canRetry(): bool
    {
        return (int) ($this->fields['status'] ?? -1) === self::STATUS_ERROR
            && (int) ($this->fields['is_permanent_error'] ?? 1) === 0;
    }

    /**
     * Get human-readable status label.
     */
    public static function getStatusLabel(int $status): string
    {
        return match ($status) {
            self::STATUS_PENDING    => __('Pending'),
            self::STATUS_PROCESSING => __('Processing'),
            self::STATUS_DONE       => __('Done'),
            self::STATUS_ERROR      => __('Error'),
            default                 => __('Unknown'),
        };
    }
}
