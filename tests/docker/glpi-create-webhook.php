<?php
/**
 * glpi-create-webhook.php — Configura o webhook do GLPI → GLPIADmit
 *
 * Executado pelo setup-test-env.sh via:
 *   docker exec test-glpi php /tmp/glpi-create-webhook.php
 *
 * Cria um webhook que dispara ao criar um Ticket e chama:
 *   POST http://glpiadmit/webhook/glpi-native
 *
 * O payload é o padrão do GLPI: {"event": "new", "item": {...ticket data...}}
 * O GLPIADmit usa o item.id para buscar as respostas do formulário via API.
 *
 * ATENÇÃO: O campo 'secret' no GLPI 11 é criptografado com GLPIKey.
 * Se armazenado em texto plano, o GLPI não consegue descriptografar e usa
 * string vazia como segredo ao calcular a assinatura HMAC.
 * O GLPIADmit valida a assinatura com o secret configurado; se o secret
 * está em branco no GLPI (descriptografia falhou), a validação é ignorada.
 */

chdir('/var/www/html/glpi');
require_once '/var/www/html/glpi/src/Glpi/Application/ResourcesChecker.php';
require_once '/var/www/html/glpi/vendor/autoload.php';

$kernel = new \Glpi\Kernel\Kernel('production');
$kernel->boot();

global $DB;

$webhook_name   = 'GLPIADmit - Criação de Usuário AD';
$webhook_url    = 'http://glpiadmit/webhook/glpi-native';
$webhook_secret = getenv('WEBHOOK_SECRET') ?: 'test-webhook-secret-2024';

// Criptografar o secret com GLPIKey para que o GLPI possa usá-lo corretamente
$glpikey = new GLPIKey();
$webhook_secret_encrypted = $glpikey->encrypt($webhook_secret);

// Verificar se já existe
$existing = $DB->request(['FROM' => 'glpi_webhooks', 'WHERE' => ['name' => $webhook_name]]);
if (count($existing) > 0) {
    $row = $existing->current();
    echo "Webhook já existe (id={$row['id']}). Atualizando secret e URL...\n";
    $DB->update('glpi_webhooks', [
        'url'       => $webhook_url,
        'secret'    => $webhook_secret_encrypted,
        'is_active' => 1,
        'date_mod'  => date('Y-m-d H:i:s'),
    ], ['id' => $row['id']]);
    echo "Webhook atualizado.\n";
    exit(0);
}

// Criar webhook para evento de criação de Ticket
$DB->insert('glpi_webhooks', [
    'entities_id'        => 0,
    'is_recursive'       => 1,
    'name'               => $webhook_name,
    'comment'            => 'Dispara ao criar um ticket originado do formulário de criação de usuário AD',
    'webhookcategories_id' => 0,
    'itemtype'           => 'Ticket',
    'event'              => 'new',
    'payload'            => null,          // usa payload padrão do GLPI
    'use_default_payload'=> 1,
    'custom_headers'     => null,
    'url'                => $webhook_url,
    'secret'             => $webhook_secret_encrypted,
    'use_cra_challenge'  => 0,
    'http_method'        => 'POST',
    'sent_try'           => 3,
    'expiration'         => 0,
    'is_active'          => 1,
    'save_response_body' => 0,
    'log_in_item_history'=> 0,
    'date_creation'      => date('Y-m-d H:i:s'),
    'date_mod'           => date('Y-m-d H:i:s'),
    'use_oauth'          => 0,
    'oauth_url'          => null,
    'clientid'           => null,
    'clientsecret'       => null,
]);
$webhook_id = $DB->insertId();

echo "Webhook criado (id=$webhook_id)\n";
echo "  Evento:  Ticket - new\n";
echo "  URL:     $webhook_url\n";
echo "  Secret:  $webhook_secret (armazenado criptografado)\n";
