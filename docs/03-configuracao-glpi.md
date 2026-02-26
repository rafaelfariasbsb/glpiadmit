# Configuração do GLPI 11

Este guia detalha a configuração necessária no GLPI 11 para que a integração funcione.

---

## 1. Habilitar a API REST

1. Acesse **Configuração > Geral > API**
2. Marque **Habilitar API REST**
3. Em **Clientes API**, crie um novo cliente:
   - **Nome**: `GLPIADmit`
   - **Ativo**: Sim
   - **Token de aplicação (App Token)**: gerado automaticamente — copie para `GLPI_APP_TOKEN` no `.env`
   - **Faixa de IP**: restrinja ao IP do servidor GLPIADmit (recomendado)

---

## 2. Criar usuário de API

1. Acesse **Administração > Usuários**
2. Crie (ou use um existente) um usuário dedicado:
   - **Login**: `api-glpi-ad`
   - **Perfil**: **Super-Admin** ou um perfil com permissões para:
     - Ler tickets
     - Adicionar followups (ITILFollowup)
     - Atualizar status de tickets
3. Em **Preferências** do usuário, gere o **Token de API Remota** → copie para `GLPI_API_TOKEN` no `.env`

> **Importante**: O GLPIADmit chama `changeActiveProfile` após o `initSession` para ativar o perfil de maior privilégio disponível (Super-Admin > Admin > outros). Isso garante permissão para atualizar tickets independentemente do perfil padrão da sessão.

---

## 3. Criar o formulário no Catálogo de Serviços

### 3.1 Criação do formulário

1. Acesse **Administração > Formulários**
2. Clique em **Adicionar**
3. Configure:
   - **Nome**: `Solicitar Criação de Usuário AD`
   - **Ativo**: Sim
   - **Rascunho**: Não
   - **Fixado**: Sim (aparece no topo do catálogo)
   - **Categoria**: `Gestão de Acessos` (crie se não existir)
   - **Descrição**: `Preencha os dados do novo colaborador para provisionar automaticamente a conta no Active Directory.`

### 3.2 Campos do formulário

Adicione uma seção chamada **"Dados do novo colaborador"** com os seguintes campos — os nomes devem ser **exatamente** como listado (o sistema busca pelos nomes em minúsculo):

| # | Nome do campo | Tipo | Obrigatório |
|---|---|---|---|
| 1 | `Nome` | Texto curto | Sim |
| 2 | `Sobrenome` | Texto curto | Sim |
| 3 | `E-mail corporativo` | E-mail | Sim |
| 4 | `Departamento` | Texto curto | Sim |
| 5 | `Cargo` | Texto curto | Sim |
| 6 | `Grupo AD` | Texto curto | Não |

> **Campo "Grupo AD"**: O usuário deve preencher com o **DN completo** do grupo, por exemplo:
> `CN=GRP-TI,OU=Grupos,DC=empresa,DC=local`
> Não inclua o nome do campo como prefixo — preencha apenas o DN.

### 3.3 Destino do formulário (Ticket)

1. Acesse a aba **Destinos** do formulário
2. Adicione um destino do tipo **Ticket**
3. Configure o **Conteúdo** do ticket com o formato abaixo — este formato é obrigatório para que o GLPIADmit extraia os campos corretamente:

```html
<b>1) Nome</b>: {{answers.ID_NOME}}<br>
<b>2) Sobrenome</b>: {{answers.ID_SOBRENOME}}<br>
<b>3) E-mail corporativo</b>: {{answers.ID_EMAIL}}<br>
<b>4) Departamento</b>: {{answers.ID_DEPARTAMENTO}}<br>
<b>5) Cargo</b>: {{answers.ID_CARGO}}<br>
<b>6) Grupo AD</b>: {{answers.ID_GRUPO_AD}}<br>
```

Substitua `ID_*` pelo identificador real de cada pergunta (mostrado na interface ao configurar o destino).

> **Por quê este formato?** O GLPIADmit usa `parse_ticket_content()` que faz regex no conteúdo HTML do ticket para extrair os pares `Label: Valor`. O padrão esperado é `<b>N) Label</b>: Valor`. A API de respostas do formulário (`Glpi\Form\AnswersSet`) não é acessível via REST API no GLPI 11 (`canView()` sempre retorna `false`), por isso o parse do conteúdo é a abordagem correta.

### 3.4 Controle de acesso

1. Acesse a aba **Controles de acesso** do formulário
2. Ative a opção **"Permitir usuários, grupos ou perfis específicos"**
3. No campo de seleção, adicione **"Usuário - Todos os usuários"**
4. Clique em **Salvar alterações**

O formulário ficará visível no **Catálogo de Serviços** para todos os usuários autenticados.

### 3.5 Automação via script (ambiente de teste/produção)

O projeto inclui um script PHP que faz todo o setup do formulário automaticamente:

```bash
# Copiar e executar no servidor GLPI:
php glpi-create-form.php
```

O script (`tests/docker/glpi-create-form.php`) pode ser usado como referência para produção. Ele:
- Cria a categoria "Gestão de Acessos" (idempotente)
- Cria o formulário com todos os campos e destino configurados
- Configura o controle de acesso corretamente (`ControlType\AllowList`, `user_ids: ["all"]`)
- Atualiza o formulário se já existir

---

## 4. Configurar o Webhook

### 4.1 Criação do webhook

1. Acesse **Administração > Webhooks** (ou **Configuração > Webhooks** dependendo da versão)
2. Clique em **Adicionar**
3. Configure:

**Informações gerais:**
- **Nome**: `GLPIADmit - Criação de Usuário AD`
- **Ativo**: Sim
- **Tipo de item**: `Ticket`
- **Evento**: `new` (criação)

**URL de destino:**
```
http://glpiadmit/webhook/glpi-native
```

> **Crítico — URL sem porta**: O GLPI 11 bloqueia URLs com porta explícita (ex: `http://servidor:8443/...`) pela validação `isUrlSafe()`. A URL do webhook **não pode ter porta**. O GLPIADmit deve estar acessível na porta 80. Configure um reverse proxy ou mapeie a porta 80 no Docker.

**Método HTTP**: `POST`

**Chave secreta (Secret)**:
- Defina uma chave forte (mínimo 32 caracteres)
- Use o **mesmo valor** que o `WEBHOOK_SECRET` no `.env` do GLPIADmit
- **O GLPI armazena o secret criptografado com `GLPIKey`** — o script `glpi-create-webhook.php` faz isso automaticamente. Se inserir manualmente via banco de dados, use `$glpikey->encrypt($secret)`.

**Payload**: Use o payload padrão do GLPI (`use_default_payload = 1`) — **não configure payload customizado**.

**Tentativas de reenvio**: 3

### 4.2 Como o GLPI assina o webhook

O GLPI 11 calcula a assinatura com:

```php
hash_hmac('sha256', $body . $timestamp, $secret)
```

E envia nos headers:
- `X-GLPI-signature` (note: **'s' minúsculo**)
- `X-GLPI-timestamp`

O GLPIADmit valida com a mesma fórmula: tenta `hmac(body + timestamp, secret)` primeiro (formato GLPI nativo), depois `hmac(body, secret)` como fallback para o endpoint legado.

### 4.3 Automação via script

```bash
# Executar no servidor GLPI com a variável WEBHOOK_SECRET:
WEBHOOK_SECRET=sua-chave-secreta php glpi-create-webhook.php
```

O script `tests/docker/glpi-create-webhook.php` pode ser usado como referência para produção.

---

## 5. Verificar o fluxo completo

1. Acesse o GLPI e abra o **Catálogo de Serviços** (Assistência > Catálogo de Serviços)
2. Clique em **"Solicitar Criação de Usuário AD"**
3. Preencha os campos:
   - **Nome**: Rafael
   - **Sobrenome**: Silva
   - **E-mail corporativo**: rafael.silva@empresa.com
   - **Departamento**: TI
   - **Cargo**: Analista
   - **Grupo AD**: `CN=GRP-TI,OU=Grupos,DC=empresa,DC=local` *(apenas o DN, sem prefixo)*
4. Clique em **Enviar**
5. Aguarde alguns segundos e atualize o chamado — deve aparecer um followup com as credenciais do usuário criado

### O que verificar se não funcionar

| Sintoma | Causa provável |
|---|---|
| Chamado criado mas sem followup | Webhook não disparou ou não chegou ao GLPIADmit |
| Erro 401 nos logs do GLPIADmit | `WEBHOOK_SECRET` diferente do configurado no GLPI |
| Chamado com "não originou de formulário" | Formato do conteúdo do ticket não corresponde ao esperado |
| Erro 400 no `initSession` | Tokens GLPI expirados/inválidos — regenere e reinicie |
| Grupo não adicionado (warning nos logs) | Campo "Grupo AD" preenchido com prefixo (ex: "Grupo AD: CN=...") — use apenas o DN |

Ver [07-troubleshooting.md](07-troubleshooting.md) para diagnóstico detalhado.

---

## 6. Referência dos tokens GLPI

| Token | Onde obter | Variável no `.env` |
|---|---|---|
| User Token (API Token) | Preferências do usuário API > Token de API Remota | `GLPI_API_TOKEN` |
| App Token | Configuração > Geral > API > Clientes API | `GLPI_APP_TOKEN` |
| Webhook Secret | Definido na criação do webhook | `WEBHOOK_SECRET` |

> **Atenção**: Os tokens do GLPI são criptografados com `GLPIKey` no banco. O script `glpi-setup-api.php` cuida disso automaticamente. Se regenerar tokens pela interface web do GLPI, atualize o `.env` e reinicie o GLPIADmit.
