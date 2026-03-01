<?php

/**
 * @license GPL-3.0-or-later
 */

namespace GlpiPlugin\Glpiadmit;

use Ticket;

class TicketHook
{
    /**
     * Pattern version for traceability when the form format changes (Critique C1).
     */
    public const FORM_PATTERN_VERSION = 1;

    /**
     * Hook called when a Ticket is added.
     * Parses HTML content, extracts form fields, and queues for AD user creation.
     */
    public static function onItemAdd(Ticket $item): void
    {
        try {
            // Check plugin enabled
            if (Config::get('enabled', '0') !== '1') {
                return;
            }

            $ticketId = $item->getID();
            $content = $item->fields['content'] ?? '';

            if (empty($content)) {
                return;
            }

            // Parse ticket content
            $fields = self::parseTicketContent($content);

            if ($fields === null) {
                // Log pattern miss with truncated HTML for debug (Pre-mortem F3)
                \Toolbox::logInFile('glpiadmit', sprintf(
                    "[PATTERN_MISS] Ticket #%d (v%d): %s\n",
                    $ticketId,
                    self::FORM_PATTERN_VERSION,
                    substr($content, 0, 500)
                ));
                return;
            }

            // Validate required fields
            $firstName = $fields['nome'] ?? '';
            $lastName = $fields['sobrenome'] ?? '';
            $email = $fields['e-mail corporativo'] ?? '';

            if (empty($firstName) || empty($lastName) || empty($email)) {
                \Toolbox::logInFile('glpiadmit', sprintf(
                    "[VALIDATION] Ticket #%d (v%d): missing required fields (nome=%s, sobrenome=%s, email=%s)\n",
                    $ticketId,
                    self::FORM_PATTERN_VERSION,
                    $firstName !== '' ? 'present' : 'missing',
                    $lastName !== '' ? 'present' : 'missing',
                    $email !== '' ? 'present' : 'missing'
                ));
                return;
            }

            // Sanitize fields before inserting into queue (Red Team R1: defense in depth)
            $firstName = trim(strip_tags($firstName));
            $lastName = trim(strip_tags($lastName));
            $email = trim(strip_tags($email));
            $department = trim(strip_tags($fields['departamento'] ?? ''));
            $jobTitle = trim(strip_tags($fields['cargo'] ?? ''));

            // F4: Validate email format
            if (filter_var($email, FILTER_VALIDATE_EMAIL) === false) {
                \Toolbox::logInFile('glpiadmit', sprintf(
                    "[VALIDATION] Ticket #%d (v%d): invalid email format: %s\n",
                    $ticketId,
                    self::FORM_PATTERN_VERSION,
                    $email
                ));
                return;
            }

            // Check for duplicate in queue (guard against duplicate ticket)
            $queueItem = new QueueItem();
            $existing = $queueItem->find(['tickets_id' => $ticketId]);
            if (!empty($existing)) {
                \Toolbox::logInFile('glpiadmit', sprintf(
                    "[DUPLICATE] Ticket #%d (v%d): already in queue, skipping\n",
                    $ticketId,
                    self::FORM_PATTERN_VERSION
                ));
                return;
            }

            // Insert into queue (First Principles S2: handle UNIQUE violation)
            try {
                $newId = $queueItem->add([
                    'tickets_id' => $ticketId,
                    'first_name' => $firstName,
                    'last_name'  => $lastName,
                    'email'      => $email,
                    'department' => $department,
                    'job_title'  => $jobTitle,
                    'status'     => QueueItem::STATUS_PENDING,
                    'attempts'   => 0,
                ]);

                // F3: CommonDBTM::add() returns false on failure (e.g. UNIQUE violation)
                if ($newId === false) {
                    \Toolbox::logInFile('glpiadmit', sprintf(
                        "[INSERT_FAILED] Ticket #%d (v%d): add() returned false (possible duplicate)\n",
                        $ticketId,
                        self::FORM_PATTERN_VERSION
                    ));
                    return;
                }

                \Toolbox::logInFile('glpiadmit', sprintf(
                    "[QUEUED] Ticket #%d (v%d): %s %s <%s>\n",
                    $ticketId,
                    self::FORM_PATTERN_VERSION,
                    $firstName,
                    $lastName,
                    $email
                ));
            } catch (\Throwable $e) {
                // DB error — log and return silently
                \Toolbox::logInFile('glpiadmit', sprintf(
                    "[INSERT_ERROR] Ticket #%d (v%d): %s\n",
                    $ticketId,
                    self::FORM_PATTERN_VERSION,
                    $e->getMessage()
                ));
            }
        } catch (\Throwable $e) {
            // Never block ticket creation — catch all and log
            \Toolbox::logInFile('glpiadmit', sprintf(
                "[HOOK_ERROR] Ticket #%d: %s\n",
                $item->getID(),
                $e->getMessage()
            ));
        }
    }

    /**
     * Parse ticket HTML content to extract form fields.
     * Applies html_entity_decode before regex matching.
     *
     * @return array<string, string>|null Associative array of field=>value, or null if no match.
     */
    public static function parseTicketContent(string $html): ?array
    {
        // Decode HTML entities before regex (content may contain &amp;, &#39; etc.)
        $html = html_entity_decode($html, ENT_QUOTES | ENT_HTML5, 'UTF-8');

        $pattern = '/<b>\d+\)\s*([^<]+)<\/b>\s*:\s*([^<]+)/i';

        if (!preg_match_all($pattern, $html, $matches, PREG_SET_ORDER)) {
            return null;
        }

        $fields = [];
        foreach ($matches as $match) {
            $label = strtolower(trim($match[1]));
            $value = trim($match[2]);
            $fields[$label] = $value;
        }

        // Verify minimum required fields are present
        $required = ['nome', 'sobrenome', 'e-mail corporativo'];
        foreach ($required as $field) {
            if (!isset($fields[$field])) {
                return null;
            }
        }

        return $fields;
    }
}
