<?php
/**
 * glpi-create-form.php — Cria (ou atualiza) o formulário "Solicitar Criação de Usuário AD"
 *
 * O formulário é publicado no Catálogo de Serviços (is_pinned=1) na categoria
 * "Gestão de Acessos", acessível por todos os perfis autenticados do GLPI.
 *
 * O conteúdo gerado no ticket segue o padrão esperado por parse_ticket_content():
 *   <b>1) Nome</b>: {valor}<br>
 *   <b>2) Sobrenome</b>: {valor}<br>
 *   ...
 */

chdir('/var/www/html/glpi');
require_once '/var/www/html/glpi/src/Glpi/Application/ResourcesChecker.php';
require_once '/var/www/html/glpi/vendor/autoload.php';

$kernel = new \Glpi\Kernel\Kernel('production');
$kernel->boot();

global $DB;

$form_name = 'Solicitar Criação de Usuário AD';

// ── 0. Categoria no Catálogo de Serviços ──────────────────────────────────
$cat_name = 'Gestão de Acessos';
$cat_existing = $DB->request(['FROM' => 'glpi_forms_categories', 'WHERE' => ['name' => $cat_name]]);
if (count($cat_existing) > 0) {
    $cat_id = $cat_existing->current()['id'];
    echo "[0] Categoria '$cat_name' já existe (id=$cat_id)\n";
} else {
    $DB->insert('glpi_forms_categories', [
        'name'                => $cat_name,
        'description'         => 'Solicitações relacionadas a criação e gestão de contas de acesso',
        'illustration'        => 'person-badge',
        'forms_categories_id' => 0,
        'completename'        => $cat_name,
        'level'               => 1,
    ]);
    $cat_id = $DB->insertId();
    echo "[0] Categoria '$cat_name' criada (id=$cat_id)\n";
}

// ── Verificar se o formulário já existe ───────────────────────────────────
$existing = $DB->request(['FROM' => 'glpi_forms_forms', 'WHERE' => ['name' => $form_name]]);
$is_update = (count($existing) > 0);

if ($is_update) {
    $form_id = $existing->current()['id'];
    echo "Formulário já existe (id=$form_id). Atualizando configurações...\n";

    // Atualiza is_pinned e categoria
    $DB->update('glpi_forms_forms', [
        'is_pinned'           => 1,
        'forms_categories_id' => $cat_id,
        'date_mod'            => date('Y-m-d H:i:s'),
    ], ['id' => $form_id]);
    echo "[1] Formulário atualizado (is_pinned=1, categoria=$cat_id)\n";

    // Remove controles de acesso antigos e recria
    $DB->delete('glpi_forms_accesscontrols_formaccesscontrols', ['forms_forms_id' => $form_id]);
    echo "[5] Controles de acesso anteriores removidos\n";
} else {
    // ── 1. Criar formulário ────────────────────────────────────────────────
    $DB->insert('glpi_forms_forms', [
        'uuid'                              => \Ramsey\Uuid\Uuid::uuid4()->toString(),
        'entities_id'                       => 0,
        'is_recursive'                      => 1,
        'is_active'                         => 1,
        'is_deleted'                        => 0,
        'is_draft'                          => 0,
        'is_pinned'                         => 1,
        'render_layout'                     => 'tabbedlayout',
        'name'                              => $form_name,
        'header'                            => null,
        'illustration'                      => 'form-creation',
        'description'                       => 'Preencha os dados do novo colaborador para provisionar automaticamente a conta no Active Directory.',
        'forms_categories_id'               => $cat_id,
        'usage_count'                       => 0,
        'submit_button_visibility_strategy' => 'always',
        'submit_button_conditions'          => '[]',
        'date_creation'                     => date('Y-m-d H:i:s'),
        'date_mod'                          => date('Y-m-d H:i:s'),
    ]);
    $form_id = $DB->insertId();
    echo "[1] Formulário criado (id=$form_id)\n";

    // ── 2. Seção ───────────────────────────────────────────────────────────
    $section_uuid = \Ramsey\Uuid\Uuid::uuid4()->toString();
    $DB->insert('glpi_forms_sections', [
        'uuid'                => $section_uuid,
        'forms_forms_id'      => $form_id,
        'name'                => 'Dados do novo colaborador',
        'description'         => null,
        'rank'                => 0,
        'visibility_strategy' => 'always',
        'conditions'          => '[]',
    ]);
    $section_id = $DB->insertId();
    echo "[2] Seção id=$section_id\n";

    // ── 3. Perguntas ───────────────────────────────────────────────────────
    $questions_def = [
        ['nome',      'Nome',               'QuestionTypeShortText', 1, 0, null],
        ['sobrenome', 'Sobrenome',          'QuestionTypeShortText', 1, 1, null],
        ['email',     'E-mail corporativo', 'QuestionTypeEmail',     1, 2, null],
        ['depto',     'Departamento',       'QuestionTypeShortText', 1, 3, null],
        ['cargo',     'Cargo',              'QuestionTypeShortText', 1, 4, null],
        ['grupo',     'Grupo AD',           'QuestionTypeShortText', 0, 5,
            'DN completo do grupo AD. Ex: CN=GRP-TI,OU=Grupos,DC=empresa,DC=local'],
    ];

    $qids = [];
    foreach ($questions_def as [$key, $name, $type_class, $mandatory, $rank, $desc]) {
        $DB->insert('glpi_forms_questions', [
            'uuid'                  => \Ramsey\Uuid\Uuid::uuid4()->toString(),
            'forms_sections_id'     => $section_id,
            'forms_sections_uuid'   => $section_uuid,
            'name'                  => $name,
            'type'                  => "Glpi\\Form\\QuestionType\\$type_class",
            'is_mandatory'          => $mandatory,
            'vertical_rank'         => $rank,
            'horizontal_rank'       => null,
            'description'           => $desc,
            'default_value'         => null,
            'extra_data'            => null,
            'visibility_strategy'   => 'always',
            'conditions'            => '[]',
            'validation_strategy'   => 'no_validation',
            'validation_conditions' => '[]',
        ]);
        $qids[$key] = $DB->insertId();
        echo "[3] Pergunta '$name' id={$qids[$key]}\n";
    }

    // ── 4. Destino: Ticket ─────────────────────────────────────────────────
    // Formato <b>N) Label</b>: {{answers.X}}<br> necessário para parse_ticket_content()
    $titulo = 'Criação de conta AD: {{answers.' . $qids['nome'] . '}} {{answers.' . $qids['sobrenome'] . '}}';
    $conteudo = implode('', [
        '<b>1) Nome</b>: {{answers.' . $qids['nome'] . '}}<br>',
        '<b>2) Sobrenome</b>: {{answers.' . $qids['sobrenome'] . '}}<br>',
        '<b>3) E-mail corporativo</b>: {{answers.' . $qids['email'] . '}}<br>',
        '<b>4) Departamento</b>: {{answers.' . $qids['depto'] . '}}<br>',
        '<b>5) Cargo</b>: {{answers.' . $qids['cargo'] . '}}<br>',
        '<b>6) Grupo AD</b>: {{answers.' . $qids['grupo'] . '}}<br>',
    ]);

    $DB->insert('glpi_forms_destinations_formdestinations', [
        'forms_forms_id'    => $form_id,
        'itemtype'          => 'Glpi\\Form\\Destination\\FormDestinationTicket',
        'name'              => 'Criar chamado no GLPI',
        'config'            => json_encode([
            'name'    => ['strategy' => 'specific_value', 'specific_value' => $titulo],
            'content' => ['strategy' => 'specific_value', 'specific_value' => $conteudo],
            'itilcategories_id' => ['strategy' => 'no_strategy'],
            'requesttypes_id'   => ['strategy' => 'no_strategy'],
            'urgency'           => ['strategy' => 'no_strategy'],
            '_actors'           => [],
        ]),
        'creation_strategy' => 'always',
        'conditions'        => '[]',
    ]);
    echo "[4] Destino (ticket) criado\n";
}

// ── 5. Controle de acesso: "Todos os usuários" ────────────────────────────
// O GLPI usa namespace ControlType (não FormAccessControlStrategy) e
// user_ids=["all"] para representar "Todos os usuários".
// O GLPI pode ter criado registros com is_active=0 — faz UPDATE ou INSERT.
$strategy_class = 'Glpi\\Form\\AccessControl\\ControlType\\AllowList';
$access_config  = json_encode(['user_ids' => ['all'], 'group_ids' => [], 'profile_ids' => []]);

// Remove quaisquer registros com namespace antigo/errado
$DB->delete('glpi_forms_accesscontrols_formaccesscontrols', [
    'forms_forms_id' => $form_id,
    'strategy'       => 'Glpi\\Form\\AccessControl\\FormAccessControlStrategy\\AllowList',
]);

// Atualiza o registro existente de AllowList (criado pelo GLPI) ou insere novo
$existing_ac = $DB->request([
    'FROM'  => 'glpi_forms_accesscontrols_formaccesscontrols',
    'WHERE' => ['forms_forms_id' => $form_id, 'strategy' => $strategy_class],
]);
if (count($existing_ac) > 0) {
    $DB->update('glpi_forms_accesscontrols_formaccesscontrols', [
        'config'    => $access_config,
        'is_active' => 1,
    ], ['forms_forms_id' => $form_id, 'strategy' => $strategy_class]);
    echo "[5] Controle de acesso atualizado (AllowList → todos os usuários, is_active=1)\n";
} else {
    $DB->insert('glpi_forms_accesscontrols_formaccesscontrols', [
        'forms_forms_id' => $form_id,
        'strategy'       => $strategy_class,
        'config'         => $access_config,
        'is_active'      => 1,
    ]);
    echo "[5] Controle de acesso criado (AllowList → todos os usuários)\n";
}

echo "\n Formulário publicado no Catálogo de Serviços!\n";
echo "  Categoria:      $cat_name (is_pinned=1)\n";
echo "  Ver formulário: http://localhost:8080/front/form/form.form.php?id=$form_id\n";
echo "  Catálogo:       http://localhost:8080/index.php?redirect=Glpi%5CForm%5CForm_$form_id\n";
echo "FORM_ID=$form_id\n";
