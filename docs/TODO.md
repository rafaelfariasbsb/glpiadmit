# GLPIADmit Plugin — TODO

---

## P0 — Infraestrutura de Testes (setup antes de qualquer teste)

- [ ] Criar `phpunit.xml` na raiz do plugin
- [ ] Criar `tests/bootstrap.php` (inclui GLPI bootstrap)
- [ ] Adicionar `phpunit/phpunit` e `mikey179/vfsstream` ao `require-dev` do composer.json
- [ ] Criar estrutura de diretórios `tests/Unit/` e `tests/Functional/`

---

## P1 — Testes Unitários Puros (sem DB, sem infra externa)

Base class: `GLPITestCase`. Rápidos, sem dependências, ideais para CI.

- [ ] **PasswordGeneratorTest** (`tests/Unit/PasswordGeneratorTest.php`)
  - Comprimento mínimo (12) e customizado (16, 20)
  - Complexidade garantida (pelo menos 1 upper, 1 lower, 1 digit, 1 special)
  - Unicidade entre chamadas consecutivas
  - Edge case: length < MIN_LENGTH eleva para 12
- [ ] **ValidatorsTest** (`tests/Unit/ValidatorsTest.php`)
  - `normalizeName`: acentos (`João`→`Joao`), cedilha, ñ, ü, caracteres CJK
  - `generateSamAccountName`: formato `jsilva`, truncamento 20 chars, nomes com hífens/espaços, nomes curtos (1 char)
  - `generateUpn`: concatenação correta com sufixo
  - `generateDisplayName`: concatenação com espaço
  - `sanitizeLdapValue` / `sanitizeDnComponent`: caracteres especiais LDAP (`*`, `(`, `)`, `\`, NUL)
  - **Testes de LDAP injection**: payloads conhecidos (`*)(uid=*))(|(uid=*`, `\00`, etc.) confirmam que `ldap_escape()` neutraliza
- [ ] **TicketHookParsingTest** (`tests/Unit/TicketHookParsingTest.php`)
  - HTML válido do Service Catalog → array com campos corretos
  - HTML com entidades encodadas (`&amp;`, `&#39;`) → decodifica corretamente
  - Campos obrigatórios faltando → retorna null
  - Campos opcionais ausentes → retorna array sem eles
  - HTML malformado / sem padrão → retorna null
  - HTML com tags extras / espaços → extrai corretamente

---

## P2 — Tipagem e Qualidade de Código (PHP 8.2+)

Código já está em ~85% de cobertura de tipos. Melhorias cirúrgicas:

- [ ] Adicionar `declare(strict_types=1)` nos 6 arquivos `src/` + `hook.php` (não nos `front/` — padrão GLPI com `$_POST`/`$_GET`)
- [ ] Marcar `PasswordGenerator` e `Validators` como `final` (classes utilitárias, só métodos estáticos)
- [ ] Adicionar `@throws RuntimeException` no PHPDoc de `ADService::processUserCreation()`, `connect()`, `checkDuplicateUser()`, `createUser()`
- [ ] Tipar `$connectionFactory` como `private ?callable $connectionFactory` em `ADService`
- [ ] Adicionar `bool` ao parâmetro `$verbose` em `plugin_glpiadmit_check_config()` no `setup.php`

---

## P3 — Testes com DB (framework GLPI)

Base class: `DbTestCase`. Usam transaction rollback automático.

- [ ] **TicketHookTest** (`tests/Functional/TicketHookTest.php`)
  - `onItemAdd` com ticket válido → cria QueueItem com status PENDING
  - `onItemAdd` com ticket sem padrão → não cria QueueItem, loga PATTERN_MISS
  - `onItemAdd` com email inválido → não cria QueueItem, loga VALIDATION
  - `onItemAdd` duplicado (mesmo ticket_id) → rejeitado, loga DUPLICATE
  - `onItemAdd` com plugin desabilitado → ignorado
- [ ] **QueueItemTest** (`tests/Functional/QueueItemTest.php`)
  - Status transitions: PENDING→PROCESSING (lock atômico)
  - PROCESSING→DONE (sucesso)
  - PROCESSING→ERROR (erro permanente ou attempts >= 3)
  - PROCESSING→PENDING (retry com attempts++)
  - Lock atômico: UPDATE WHERE status=0 retorna affected_rows=0 se já lockado
  - `canRetry()`: true quando attempts < 3 e não permanente
  - `getStatusLabel()`: labels corretos para cada status
  - `rawSearchOptions()`: opções de busca válidas
- [ ] **ConfigTest** (`tests/Functional/ConfigTest.php`)
  - `get()` / `set()` / `getAll()`: CRUD de configuração
  - `SECURED_CONFIGS`: ad_bind_password é encriptado automaticamente
  - `getAllDecrypted()`: retorna password descriptografado
  - Valores default quando config não existe

---

## P4 — Testes com LDAP Mock (via connectionFactory)

Base class: `DbTestCase` + mock do connection via `connectionFactory` injetável do ADService.
Não precisa de container LDAP — o ADService já suporta injeção de dependência.

- [ ] **ADServiceTest** (`tests/Functional/ADServiceTest.php`)
  - `processUserCreation`: fluxo completo (create→password→enable→groups)
  - `checkDuplicateUser`: sAMAccountName ou email existente → RuntimeException
  - `createUser`: ldap_add chamado com atributos corretos (objectClass, UAC=514)
  - `setPassword`: unicodePwd em UTF-16LE, ldap_modify_batch chamado
  - `enableAccount`: UAC=512 + pwdLastSet=0
  - `rollback`: ldap_delete chamado quando password/enable falha
  - `addToGroups`: falha non-blocking (log warning, não throw)
  - `isPermanentError`: patterns conhecidos retornam true
  - `isConnectionError`: patterns de conexão retornam true
  - Erro de conexão mid-batch → tenta reconectar

---

## P5 — Substituir HTML Parsing por Dados Estruturados

- [ ] **Investigar API de Forms do GLPI 11** — Verificar se `Glpi\Form\Answer` expõe dados estruturados de respostas e se existe hook quando um formulário gera um ticket. Arquivos-chave: `glpi/src/Form/Answer.php`, `glpi/src/Form/Form.php`
- [ ] **Implementar extração via Form Answer** — Se a API permitir, criar tela de mapeamento (Form ID + Question IDs → campos do plugin). Manter regex como fallback configurável durante transição

---

## P6 — Funcionalidades Novas

- [ ] **Implementar front/queueitem.form.php** — Handler para ações de retry/force_retry na UI (template já existe, handler é stub)
- [ ] **Tratamento de colisão de sAMAccountName** — Quando `jsilva` já existe no AD, gerar automaticamente `jsilva2`, `jsilva3`, etc. Hoje resulta em erro permanente
- [ ] **Notificação de erro para admins** — Enviar email/notificação GLPI quando um item da fila falha permanentemente (status=ERROR), em vez de apenas logar
- [ ] **Comando console `glpiadmit:retry-failed`** — Permite reprocessar itens em ERROR permanente via CLI, sem acesso à UI web
- [ ] **Circuit-breaker no CronTask** — Parar ciclo quando AD está offline N vezes consecutivas (hoje tenta reconectar indefinidamente). Alertar admin

---

## P7 — Melhorias de Baixa Prioridade

- [ ] **Rate limiting na criação de usuários** — Limitar criações por ciclo de CronTask para evitar sobrecarga no AD em lotes grandes
- [ ] **Internacionalização dos labels de parsing** — Permitir configurar os labels esperados no HTML (hoje hardcoded: `nome`, `sobrenome`, `e-mail corporativo`) para suportar outros idiomas
- [ ] **Dashboard de métricas** — Painel com estatísticas: total criados, taxa de erro, tempo médio de processamento, itens pendentes
- [ ] **php-cs-fixer + GitHub Action** — Padronizar estilo de código, lint automático em PRs

---

## P8 — Futuro / Quando Houver Demanda

- [ ] **Suporte a Managed Identity (Azure AD)** — Alternativa ao bind DN + password para ambientes Azure
- [ ] **Audit trail de operações** — Tabela dedicada para auditoria (criação, retry, erro), além do log em arquivo
- [ ] **Documentar rotação de bind password** — Adicionar em `docs/05-security.md` recomendação de rotação periódica via Ansible/GPO (responsabilidade infra, não do plugin)
- [ ] **Suporte a múltiplos domínios/forests** — Para empresas com múltiplos ADs (feature major)
