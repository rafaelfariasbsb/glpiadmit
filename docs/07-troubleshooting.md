# Troubleshooting

## Onde encontrar os logs

| Log | Docker | systemd |
|---|---|---|
| GLPIADmit | `docker compose logs -f glpiadmit` | `journalctl -u glpi-ad-integration -f` |
| Webhooks GLPI | Administração > Webhooks > (selecione) > Histórico | — |
| Active Directory | Event Viewer > Security no DC | — |
| Entra Connect | Synchronization Service Manager / Portal Entra | — |

---

## Problemas comuns

### 1. Serviço não inicia

**Docker:**
```bash
docker compose logs glpiadmit
docker compose ps   # verificar se status é "Exited"
```

| Erro no log | Causa | Solução |
|---|---|---|
| `ValidationError` | Variável de ambiente ausente no `.env` | Verificar se todas as variáveis obrigatórias estão preenchidas |
| `Address already in use` | Porta 80 ou 8443 em uso | `ss -tlnp \| grep 80` |
| Container em `unhealthy` | Health check falhou | `docker inspect test-glpiadmit \| grep -A5 Health` |

**systemd:**
```bash
sudo journalctl -u glpi-ad-integration -n 50
```

---

### 2. Webhook não é recebido pelo GLPIADmit

**Sintoma**: Chamado criado no GLPI, mas nada acontece no GLPIADmit (sem logs de webhook recebido).

**Checklist:**

1. **O GLPIADmit está rodando?**
   ```bash
   curl http://localhost:8443/health
   ```

2. **O webhook está ativo no GLPI?**
   - Administração > Webhooks → verificar se está ativo

3. **A URL do webhook usa porta explícita?**
   - O GLPI bloqueia URLs com porta (ex: `http://servidor:8443/...`)
   - A URL deve ser `http://glpiadmit/webhook/glpi-native` (sem porta)
   - O GLPIADmit deve estar acessível na porta 80

4. **O GLPI consegue alcançar o GLPIADmit?**
   ```bash
   # No container GLPI:
   docker exec test-glpi curl -sf http://glpiadmit/health
   ```

5. **Verificar fila de webhooks no GLPI:**
   - Administração > Webhooks > selecione o webhook > aba **Histórico**
   - Se aparece `last_status_code=NULL` com tentativas enviadas, provavelmente é problema de conectividade

---

### 3. Erro 401 — Assinatura inválida

**Sintoma**: Log mostra `Webhook recebido com assinatura inválida` ou `Webhook nativo recebido com assinatura invalida`.

**Causas e soluções:**

| Causa | Diagnóstico | Solução |
|---|---|---|
| `WEBHOOK_SECRET` diferente | Comparar valor no `.env` com o configurado no webhook | Alinhar os dois valores e reiniciar |
| Secret em texto plano no banco | O GLPI usou string vazia como chave | Recriar o webhook com `$glpikey->encrypt($secret)` |
| Formato de assinatura errado | Conferir se o endpoint correto está sendo usado | Usar `/webhook/glpi-native` para webhook nativo do GLPI 11 |

**Verificar se o secret está criptografado corretamente:**
```bash
docker exec test-mariadb mysql -uglpi -pglpipass glpidb -e \
  "SELECT name, secret FROM glpi_webhooks WHERE name LIKE '%GLPIADmit%';"
```
O campo `secret` deve ter uma string longa e criptografada — não o valor em texto plano.

---

### 4. Chamado criado mas ignorado ("não originou de formulário")

**Sintoma**: Log mostra `Ticket #X nao originou de formulario de criacao de usuario — ignorando`.

**Causa**: O conteúdo do ticket não está no formato esperado `<b>N) Label</b>: Valor<br>`.

**Diagnóstico:**
```bash
# Ver conteúdo do ticket no banco:
docker exec test-mariadb mysql -uglpi -pglpipass glpidb -e \
  "SELECT id, content FROM glpi_tickets WHERE id=<TICKET_ID>;"
```

**Formato esperado:**
```html
<b>1) Nome</b>: Rafael<br>
<b>2) Sobrenome</b>: Silva<br>
<b>3) E-mail corporativo</b>: rafael@empresa.com<br>
<b>4) Departamento</b>: TI<br>
<b>5) Cargo</b>: Analista<br>
<b>6) Grupo AD</b>: CN=GRP-TI,OU=Grupos,DC=empresa,DC=local<br>
```

**Solução**: Verificar o destino do formulário no GLPI. O template de conteúdo do ticket deve usar o formato HTML exato acima. Consulte [03-configuracao-glpi.md](03-configuracao-glpi.md) — seção 3.3.

---

### 5. Erro 400 no initSession (tokens inválidos/expirados)

**Sintoma**: Log mostra `Erro ao atualizar chamado #X no GLPI: Client error '400 Bad Request' for url '.../initSession'`.

**Causa**: Os tokens GLPI no `.env` estão expirados ou diferentes dos que estão no banco do GLPI (comum após rodar o `setup-test-env.sh` novamente ou regenerar tokens pela interface).

**Solução:**
```bash
# 1. Regenerar tokens via script
NEW_TOKENS=$(docker exec -w /var/www/html/glpi test-glpi php /tmp/glpi-setup-api.php 2>/dev/null | tail -1)
NEW_API=$(echo "$NEW_TOKENS" | grep -oP 'API_TOKEN=\K\S+')
NEW_APP=$(echo "$NEW_TOKENS" | grep -oP 'APP_TOKEN=\K\S+')

# 2. Atualizar .env
sed -i "s|^GLPI_API_TOKEN=.*|GLPI_API_TOKEN=${NEW_API}|" .env
sed -i "s|^GLPI_APP_TOKEN=.*|GLPI_APP_TOKEN=${NEW_APP}|" .env

# 3. Reiniciar o GLPIADmit (com --force-recreate para reler o env_file)
docker compose up -d --force-recreate glpiadmit
```

---

### 6. Grupo AD não adicionado

**Sintoma**: Log mostra `Falha ao adicionar ao grupo ...: character ' ' not allowed in attribute type`.

**Causa**: O campo "Grupo AD" foi preenchido com o nome do campo como prefixo:
```
# ERRADO:
Grupo AD: CN=GRP-TI,OU=Grupos,DC=teste,DC=local

# CORRETO:
CN=GRP-TI,OU=Grupos,DC=teste,DC=local
```

**Solução**: O usuário deve preencher apenas o DN no campo "Grupo AD", sem nenhum prefixo. A descrição do campo no formulário deve orientar sobre isso.

Outros erros possíveis no campo Grupo AD:

| Erro | Causa | Solução |
|---|---|---|
| `No such object` | DN do grupo não existe no AD | Verificar o DN correto com `Get-ADGroup` |
| `Insufficient access rights` | Conta de serviço sem permissão | Verificar delegação de permissões no OU de grupos |
| `Already member` | Usuário já está no grupo | Não é um erro crítico — o usuário é criado normalmente |

---

### 7. Usuário criado mas desabilitado / sem senha

**Sintoma**: Usuário aparece no AD mas está desabilitado e sem senha.

**Causa**: A operação `_configure_account()` falhou após a criação do objeto.

**Verificar:**
- O log mostra erro em `_set_password` ou `_configure_account`?
- A conexão é realmente LDAPS? (`unicodePwd` exige SSL)
- O certificado do DC é válido?

**Ação:**
1. Defina a senha manualmente no AD
2. Habilite a conta (`userAccountControl = 512`)
3. Resolva o chamado no GLPI manualmente

---

### 8. Usuário já existe (duplicidade)

**Sintoma**: Log mostra `Usuário já existe no AD`.

**Verificar:**
```powershell
Get-ADUser -Filter "sAMAccountName -eq 'rsilva'" -Properties *
```

**Ação:**
- Homonímia real: criar manualmente com sAMAccountName diferente (ex: `rsilva2`, `rnsilva`)
- Duplicata: orientar o solicitante e fechar o chamado

---

### 9. Followup não aparece no chamado (usuário criado no AD)

**Sintoma**: Usuário foi criado no AD mas o chamado não foi atualizado.

**Checklist:**

1. **Tokens GLPI corretos?** → ver problema #5 acima

2. **Usuário API tem permissões?**
   ```bash
   # Testar initSession manualmente:
   curl -H "Authorization: user_token SEU_TOKEN" \
        -H "App-Token: SEU_APP_TOKEN" \
        http://glpi.empresa.local/apirest.php/initSession
   ```

3. **Perfil do usuário API tem permissão para atualizar tickets?**
   - O GLPIADmit chama `changeActiveProfile` para o maior perfil disponível
   - Verificar se o usuário API tem pelo menos perfil "Técnico" ou "Admin"

---

### 10. Formulário não aparece no Catálogo de Serviços

**Sintoma**: Usuário acessa Assistência > Catálogo de Serviços mas o formulário não aparece.

**Checklist:**

1. **Controle de acesso está ativo?**
   - Acessar o formulário em Administração > Formulários > (formulário) > **Controles de acesso**
   - O toggle "Permitir usuários, grupos ou perfis específicos" deve estar **ativo**
   - Deve ter "Usuário - Todos os usuários" configurado

2. **Formulário está ativo e não é rascunho?**
   - Na aba **Formulário**: "Ativo" = Sim, "Rascunho" = Não

3. **Recriar configuração de acesso via script:**
   ```bash
   docker cp tests/docker/glpi-create-form.php test-glpi:/tmp/glpi-create-form.php
   docker exec -w /var/www/html/glpi test-glpi php /tmp/glpi-create-form.php 2>/dev/null
   ```

---

### 11. Sincronização com Azure AD não ocorre

**Verificar:**

1. Aguardar 30-40 minutos (ciclo padrão do Entra Connect)

2. Forçar sync:
   ```powershell
   Start-ADSyncSyncCycle -PolicyType Delta
   ```

3. Verificar erros:
   ```powershell
   Get-ADSyncConnectorRunStatus
   ```

4. O OU de usuários está no escopo do sync?
   - Verificar no Entra Connect se o OU está selecionado

5. Conflito de atributo?
   - UPN ou proxyAddress duplicado impede sincronização
   - Verificar no Portal Entra se há erros de sync

---

### 12. Logs mostram "Retrying" ou tentativas repetidas

**Sintoma**: Log mostra mensagens como `Retrying app.services...` com WARNING.

**O que está acontecendo**: O serviço detectou uma falha transiente (conexão LDAP ou HTTP) e está tentando novamente automaticamente (até 3 tentativas com backoff exponencial de 2s a 10s).

**Ação:**
- Se as retentativas tiverem sucesso (log volta ao INFO normal), não é necessária intervenção
- Se todas as tentativas falharem, o log mostrará `ERRO ... após 3 tentativas` — investigar causa raiz:
  - Para AD: verificar conectividade LDAPS, certificado, senha da conta de serviço
  - Para GLPI: verificar tokens, disponibilidade da API REST

---

## Checklist de diagnóstico rápido

Ao investigar qualquer problema, verifique nesta ordem:

```bash
# 1. GLPIADmit está rodando?
curl http://localhost:8443/health

# 2. Logs do GLPIADmit (últimas 50 linhas)
docker compose logs --tail=50 glpiadmit

# 3. GLPI consegue chamar o GLPIADmit?
docker exec test-glpi curl -sf http://glpiadmit/health

# 4. Tokens GLPI válidos?
docker exec -w /var/www/html/glpi test-glpi php /tmp/glpi-setup-api.php 2>/dev/null

# 5. Webhook existe no GLPI?
docker exec test-mariadb mysql -uglpi -pglpipass glpidb -e \
  "SELECT id, name, is_active, url, sent_try FROM glpi_webhooks;"

# 6. Histórico de envios do webhook
docker exec test-mariadb mysql -uglpi -pglpipass glpidb -e \
  "SELECT id, itemtype, event, last_status_code, sent_try, date_mod
   FROM glpi_queued_webhooks ORDER BY id DESC LIMIT 5;" 2>/dev/null
```
