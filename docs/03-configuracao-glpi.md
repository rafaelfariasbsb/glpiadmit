# Configuração do GLPI 11

Este guia detalha a configuração necessária no GLPI para que a integração funcione.

---

## 1. Habilitar a API REST

1. Acesse **Configuração > Geral > API**
2. Marque **Habilitar API REST**
3. Em **Clientes API**, crie um novo cliente:
   - **Nome**: `Integração AD`
   - **Ativo**: Sim
   - **Token de aplicação (App Token)**: será gerado automaticamente — copie para o `.env`
   - **Faixa de IP**: restrinja ao IP do servidor FastAPI (recomendado)

## 2. Criar usuário de API

1. Acesse **Administração > Usuários**
2. Crie um novo usuário (ou use um existente):
   - **Login**: `api-glpi-ad`
   - **Perfil**: atribua um perfil com permissões para:
     - Ler tickets
     - Adicionar followups em tickets
     - Atualizar status de tickets
3. Nas **Preferências** do usuário:
   - Gere o **Token de API Remota** — copie para o `.env` como `GLPI_API_TOKEN`

## 3. Criar categoria de ticket

1. Acesse **Configuração > Dropdowns > Categorias de tickets**
2. Crie uma nova categoria:
   - **Nome**: `Criação de Usuário`
   - **Ativo**: Sim
   - **É um template de incidente**: Não
   - **É um template de requisição**: Sim

> Anote o **ID** desta categoria — será usado no filtro do webhook.

## 4. Criar formulário de solicitação

1. Acesse **Administração > Formulários**
2. Clique em **Adicionar**
3. Configure:

**Informações gerais:**
- **Nome**: `Criação de Usuário - AD`
- **Ativo**: Sim
- **Acesso**: Restrito aos perfis autorizados (ex: RH, Gestores)

**Campos do formulário (seção "Dados do Novo Usuário"):**

| # | Campo | Tipo | Obrigatório | Observações |
|---|---|---|---|---|
| 1 | Nome | Texto curto | Sim | Primeiro nome do colaborador |
| 2 | Sobrenome | Texto curto | Sim | Sobrenome do colaborador |
| 3 | Email corporativo | Texto curto | Sim | Validado automaticamente pelo serviço (`EmailStr` do Pydantic) |
| 4 | Departamento | Dropdown | Sim | Lista de departamentos da empresa |
| 5 | Cargo | Texto curto | Sim | Cargo/função do colaborador |
| 6 | Telefone | Texto curto | Não | Ramal ou celular corporativo |
| 7 | Gestor direto | Seleção de ator | Não | Seleciona usuário GLPI (mapear para DN do AD) |
| 8 | Grupos AD | Checkbox múltiplo | Não | Grupos de acesso (ex: VPN, Email, Financeiro) |

**Destino do formulário:**
- **Tipo de destino**: Ticket
- **Categoria**: `Criação de Usuário`
- **Tipo**: Requisição
- Mapear os campos do formulário para o conteúdo do ticket

> **Importante**: O conteúdo do ticket deve ser estruturado em formato que o webhook consiga extrair os campos. Recomenda-se usar JSON no corpo ou mapear para campos customizados.

## 5. Configurar Webhook

1. Acesse **Administração > Configuração > Webhooks**
2. Clique em **Adicionar** e configure:

**Configuração geral:**
- **Nome**: `Webhook - Criação de Usuário AD`
- **Ativo**: Sim
- **Tipo de item**: `Ticket`
- **Evento**: `Criação`

**Filtros:**
- Adicione filtro: **Categoria** = `Criação de Usuário`

**Destino HTTP:**
- **URL**: `https://<ip-do-servidor>:8443/webhook/user-creation`
- **Método HTTP**: `POST`

**Headers:**
```
Content-Type: application/json
```

**Segurança:**
- **Chave secreta (Secret key)**: Defina uma chave forte — copie para o `.env` como `WEBHOOK_SECRET`

**Payload (corpo da requisição):**

Configure o payload no formato JSON. Use as variáveis do GLPI para preencher:

```json
{
  "ticket_id": {{item.id}},
  "first_name": "{{campo_nome}}",
  "last_name": "{{campo_sobrenome}}",
  "email": "{{campo_email}}",
  "department": "{{campo_departamento}}",
  "title": "{{campo_cargo}}",
  "phone": "{{campo_telefone}}",
  "manager": "{{campo_gestor}}",
  "groups": [{{campo_grupos}}]
}
```

> **Nota**: As variáveis exatas dependem de como o formulário foi configurado. Substitua `{{campo_nome}}`, etc., pelas variáveis reais dos campos do formulário do GLPI 11. Consulte a documentação do GLPI para os nomes corretos das variáveis de template.

**Retry:**
- **Tentativas de reenvio**: 3
- **Intervalo entre tentativas**: 60 segundos

3. Salve e **teste** o webhook clicando em "Enviar teste" (se disponível).

## 6. Testar o fluxo completo

1. Acesse o GLPI como um usuário com acesso ao formulário
2. Vá em **Assistência > Criar um ticket** (ou acesse via catálogo de serviços)
3. Preencha o formulário "Criação de Usuário - AD"
4. Submeta o formulário
5. Verifique:
   - O chamado foi criado na categoria correta
   - O webhook foi disparado (verifique logs: `journalctl -u glpi-ad-integration -f`)
   - O usuário foi criado no AD (verifique via `Active Directory Users and Computers`)
   - O chamado recebeu um followup com as credenciais
   - O chamado foi resolvido automaticamente

## Troubleshooting

| Problema | Verificação |
|---|---|
| Webhook não dispara | Verificar se o evento e filtro de categoria estão corretos |
| Erro 401 no webhook | Verificar `WEBHOOK_SECRET` no `.env` e na config do webhook GLPI |
| Erro 422 no webhook | Verificar formato do payload JSON — campos faltando ou com nome errado |
| Followup não aparece | Verificar `GLPI_API_TOKEN` e `GLPI_APP_TOKEN`. Verificar permissões do usuário API |
| Ticket não resolve | Verificar se o usuário API tem permissão para alterar status de tickets |
