<?php
/**
 * glpi-setup-api.php — Configura a API REST do GLPI automaticamente
 *
 * Executado pelo setup-test-env.sh via:
 *   docker exec test-glpi php /tmp/glpi-setup-api.php
 *
 * O que faz:
 *   1. Habilita a REST API
 *   2. Gera e armazena User Token (api_token) para o usuário glpi
 *   3. Gera e armazena App Token no cliente API padrão (sem restrição de IP)
 *   4. Imprime os tokens em formato ENV para o setup-test-env.sh capturar
 *
 * Saída (última linha): "API_TOKEN=<token> APP_TOKEN=<token>"
 */

chdir('/var/www/html/glpi');
require_once '/var/www/html/glpi/src/Glpi/Application/ResourcesChecker.php';
require_once '/var/www/html/glpi/vendor/autoload.php';

$kernel = new \Glpi\Kernel\Kernel('production');
$kernel->boot();

global $DB;
$glpikey = new GLPIKey();

// Tokens em texto claro (estes vão para o .env.test)
$api_token_plain = bin2hex(random_bytes(20));
$app_token_plain = bin2hex(random_bytes(20));

// 1. Habilitar REST API
$DB->updateOrInsert(
    'glpi_configs',
    ['value' => '1'],
    ['name' => 'enable_api', 'context' => 'core']
);

// 2. User api_token — encriptado com GLPIKey
$DB->update('glpi_users', [
    'api_token'      => $glpikey->encrypt($api_token_plain),
    'api_token_date' => date('Y-m-d H:i:s'),
], ['name' => 'glpi']);

// 3. App Token — encriptado com GLPIKey, sem restrição de IP
$existing = $DB->request(['FROM' => 'glpi_apiclients', 'LIMIT' => 1]);
if (count($existing) > 0) {
    $row = $existing->current();
    $DB->update('glpi_apiclients', [
        'name'            => 'GLPIADmit',
        'app_token'       => $glpikey->encrypt($app_token_plain),
        'app_token_date'  => date('Y-m-d H:i:s'),
        'is_active'       => 1,
        'ipv4_range_start' => null,
        'ipv4_range_end'   => null,
        'ipv6'             => null,
    ], ['id' => $row['id']]);
} else {
    $DB->insert('glpi_apiclients', [
        'name'            => 'GLPIADmit',
        'app_token'       => $glpikey->encrypt($app_token_plain),
        'app_token_date'  => date('Y-m-d H:i:s'),
        'is_active'       => 1,
        'entities_id'     => 0,
        'is_recursive'    => 1,
        'ipv4_range_start' => null,
        'ipv4_range_end'   => null,
        'ipv6'             => null,
        'date_creation'   => date('Y-m-d H:i:s'),
        'date_mod'        => date('Y-m-d H:i:s'),
    ]);
}

// Saída capturada pelo setup-test-env.sh
echo "API_TOKEN={$api_token_plain} APP_TOKEN={$app_token_plain}\n";
