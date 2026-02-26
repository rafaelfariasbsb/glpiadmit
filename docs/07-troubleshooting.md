# Troubleshooting

## Problemas comuns e soluções

---

### 1. Serviço não inicia

**Sintoma**: `systemctl status glpi-ad-integration` mostra falha.

**Verificar logs**:
```bash
sudo journalctl -u glpi-ad-integration -n 50
```

**Causas comuns**:

| Erro no log | Causa | Solução |
|---|---|---|
| `ModuleNotFoundError` | Dependências não instaladas | `source venv/bin/activate && pip install -r requirements.txt` |
| `ValidationError` no config | Variável de ambiente ausente | Verificar `.env` — todas as variáveis obrigatórias preenchidas |
| `Permission denied` | Permissão do `.env` ou diretório | `chown -R glpi-ad-svc:glpi-ad-svc /opt/glpi-ad-integration` |
| `Address already in use` | Porta 8443 em uso | `ss -tlnp | grep 8443` para ver quem usa a porta |

---

### 2. Webhook não é recebido

**Sintoma**: Chamado é criado no GLPI mas nada acontece.

**Checklist**:

1. **Webhook está ativo no GLPI?**
   - Administração > Configuração > Webhooks — verificar se está ativo

2. **O filtro de categoria está correto?**
   - O webhook deve filtrar pela categoria "Criação de Usuário"
   - Verificar se o ID da categoria no filtro corresponde ao real

3. **O GLPI consegue alcançar o servidor?**
   ```bash
   # No servidor do GLPI, testar conectividade:
   curl -k https://<ip-servidor-fastapi>:8443/health
   ```

4. **Verificar histórico de webhooks no GLPI**:
   - Administração > Configuração > Webhooks > selecione o webhook > aba Histórico/Logs

5. **O serviço está rodando?**
   ```bash
   sudo systemctl status glpi-ad-integration
   curl http://localhost:8443/health
   ```

---

### 3. Erro 401 — Assinatura inválida

**Sintoma**: Log mostra `Webhook recebido com assinatura inválida`.

**Causa**: O `WEBHOOK_SECRET` no `.env` não corresponde ao secret configurado no webhook do GLPI.

**Solução**:
1. Acesse Administração > Configuração > Webhooks no GLPI
2. Copie o valor exato da **Chave secreta**
3. Cole no `.env` como `WEBHOOK_SECRET=<valor>`
4. Reinicie: `sudo systemctl restart glpi-ad-integration`

---

### 4. Erro 422 — Payload inválido

**Sintoma**: Log mostra `Payload inválido recebido`.

**Causa**: O payload JSON enviado pelo GLPI não contém os campos esperados.

**Verificar**:
1. Confira o formato do payload no webhook do GLPI
2. Os campos obrigatórios são: `ticket_id`, `first_name`, `last_name`, `email`, `department`, `title`
3. Teste manualmente com curl:
   ```bash
   curl -X POST http://localhost:8443/webhook/user-creation \
     -H "Content-Type: application/json" \
     -d '{
       "ticket_id": 999,
       "first_name": "Teste",
       "last_name": "Integração",
       "email": "teste@empresa.com",
       "department": "TI",
       "title": "Teste"
     }'
   ```

---

### 5. Erro de conexão com AD

**Sintoma**: Log mostra `Falha na conexão com AD`.

**Checklist**:

1. **Servidor AD acessível?**
   ```bash
   nc -zv dc01.empresa.local 636
   ```

2. **DNS resolve?**
   ```bash
   nslookup dc01.empresa.local
   ```

3. **Certificado LDAPS válido?**
   ```bash
   openssl s_client -connect dc01.empresa.local:636 -showcerts
   ```

4. **Credenciais corretas?**
   - Testar com ldapsearch:
     ```bash
     ldapsearch -H ldaps://dc01.empresa.local -D "CN=svc-glpi-ad,OU=ServiceAccounts,DC=empresa,DC=local" -W -b "DC=empresa,DC=local" "(sAMAccountName=svc-glpi-ad)"
     ```

5. **Conta de serviço bloqueada?**
   - Verificar no AD se a conta não está bloqueada ou expirada

---

### 6. Usuário criado mas sem senha / desabilitado

**Sintoma**: Usuário aparece no AD mas está desabilitado e sem senha.

**Causa**: A operação de definir senha falhou (etapa 4 do fluxo), mas a criação (etapa 3) foi bem-sucedida.

**Verificar**:
- Log mostra erro em `_set_password`?
- A conexão é realmente LDAPS? (`unicodePwd` exige SSL)
- O certificado do DC é válido e confiável?

**Ação**:
1. Defina a senha manualmente no AD
2. Habilite a conta
3. Resolva o chamado no GLPI
4. Corrija a configuração e teste novamente

---

### 7. Usuário já existe (duplicidade)

**Sintoma**: Chamado marcado como erro com "Usuário já existe no AD".

**Causa**: Já existe um usuário com o mesmo `sAMAccountName` ou `userPrincipalName`.

**Verificar**:
```powershell
Get-ADUser -Filter "sAMAccountName -eq 'msantos'" -Properties *
```

**Ação**:
- Se é homonímia: criar manualmente com sAMAccountName diferente (ex: `msantos2`, `masantos`)
- Se é duplicata real: orientar o solicitante e fechar o chamado

---

### 8. Followup não aparece no chamado

**Sintoma**: Usuário é criado no AD mas o chamado não é atualizado.

**Checklist**:

1. **Tokens do GLPI corretos?**
   - Verificar `GLPI_API_TOKEN` e `GLPI_APP_TOKEN`

2. **API do GLPI acessível?**
   ```bash
   curl -H "Content-Type: application/json" \
        -H "Authorization: user_token SEU_TOKEN" \
        -H "App-Token: SEU_APP_TOKEN" \
        https://glpi.empresa.local/apirest.php/initSession
   ```

3. **Permissões do usuário API?**
   - O usuário precisa de permissão para adicionar followups e alterar status de tickets

4. **Verificar logs do serviço** para erros HTTP na comunicação com GLPI

---

### 9. Sincronização com Azure AD não ocorre

**Sintoma**: Usuário existe no AD on-premises mas não aparece no Azure AD / M365.

**Verificar**:

1. **Ciclo de sync**:
   - O Entra Connect sincroniza a cada 30 minutos por padrão
   - Aguarde pelo menos 30-40 minutos

2. **Forçar sync** (no servidor Entra Connect):
   ```powershell
   Start-ADSyncSyncCycle -PolicyType Delta
   ```

3. **Verificar erros de sync**:
   ```powershell
   Get-ADSyncConnectorRunStatus
   ```

4. **O OU está no escopo do sync?**
   - Verificar no Entra Connect se o OU de usuários está selecionado para sincronização

5. **Conflito de atributo?**
   - Verificar no portal Entra se há erros de sync
   - UPN ou proxyAddress duplicado impede a sincronização

---

## Onde encontrar os logs

| Log | Localização |
|---|---|
| Serviço de integração | `journalctl -u glpi-ad-integration` |
| Webhooks do GLPI | Administração > Configuração > Webhooks > Histórico |
| API do GLPI | Logs do Apache/Nginx do servidor GLPI |
| Active Directory | Event Viewer > Security no controlador de domínio |
| Entra Connect | Synchronization Service Manager / Portal Entra |
