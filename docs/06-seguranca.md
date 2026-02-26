# Segurança

## Princípios aplicados

1. **Menor privilégio** — Conta de serviço com permissão apenas no OU de usuários
2. **Criptografia em trânsito** — LDAPS (porta 636) para comunicação com AD
3. **Validação de origem** — Webhook autenticado com assinatura HMAC
4. **Sanitização de entrada** — Proteção contra injeção LDAP
5. **Senhas seguras** — Geração criptográfica, troca obrigatória no primeiro login
6. **Isolamento** — Serviço roda com usuário dedicado, sem privilégios root

---

## Detalhes por camada

### Comunicação com Active Directory

| Aspecto | Implementação |
|---|---|
| Protocolo | LDAPS (LDAP over SSL/TLS, porta 636) |
| Autenticação | Bind com conta de serviço (DN + senha) |
| Validação de certificado | Habilitada (ssl.CERT_REQUIRED) |
| Operação de senha | Via atributo `unicodePwd` (exige SSL) |

**Nunca** usar LDAP simples (porta 389) em produção — a senha do `unicodePwd` é rejeitada sem SSL.

### Validação do Webhook

O serviço valida a assinatura HMAC-SHA256 do webhook:

```
HMAC-SHA256(webhook_secret, request_body) == X-GLPI-Signature header
```

- Se `WEBHOOK_SECRET` não estiver configurado, um warning é logado e a validação é ignorada (apenas para desenvolvimento)
- Em produção, **sempre configure** o `WEBHOOK_SECRET`
- Recomenda-se também restringir por IP via firewall (aceitar apenas o IP do GLPI)

### Comunicação com GLPI (API REST)

| Aspecto | Implementação |
|---|---|
| Protocolo | HTTPS |
| Verificação de certificado | Configurável via `GLPI_VERIFY_SSL` (padrão: `true`) |
| Autenticação | `user_token` + `App-Token` (headers centralizados) |
| Sessão | Iniciada e encerrada a cada operação (`initSession` / `killSession`) |

> **Importante**: Em produção, mantenha `GLPI_VERIFY_SSL=true`. Use `false` apenas em ambientes de desenvolvimento com certificados auto-assinados.

### Sanitização de dados

Dois níveis de sanitização são aplicados:

1. **Valores LDAP** (`sanitize_ldap_value`) — Escapa `*`, `(`, `)`, `\`, `\0` em filtros de busca para prevenir injeção LDAP (RFC 4515)
2. **Componentes de DN** (`sanitize_dn_component`) — Escapa `\`, `,`, `+`, `"`, `<`, `>`, `;`, `=` em Distinguished Names (RFC 4514, backslash escapado primeiro para evitar re-escape)

### Validação de email

O campo `email` no payload é validado automaticamente pelo Pydantic usando `EmailStr` (biblioteca `email-validator`), garantindo conformidade com RFCs de email sem necessidade de regex manual.

### Gerenciamento de credenciais

| Credencial | Armazenamento |
|---|---|
| Senha da conta de serviço AD | Variável de ambiente (`AD_BIND_PASSWORD`) |
| Token API do GLPI | Variável de ambiente (`GLPI_API_TOKEN`) |
| App Token do GLPI | Variável de ambiente (`GLPI_APP_TOKEN`) |
| Secret do Webhook | Variável de ambiente (`WEBHOOK_SECRET`) |

O arquivo `.env`:
- Permissão `600` (somente o owner lê)
- Não é versionado no git (adicionar ao `.gitignore`)
- Nunca contém valores padrão reais
- Carregado via `pydantic-settings` com cache (`@lru_cache`) — instância única em memória

### Processo do serviço

O unit file do systemd aplica hardening:

```ini
NoNewPrivileges=true     # Impede escalação de privilégio
ProtectSystem=strict     # Sistema de arquivos read-only exceto WorkingDirectory
ProtectHome=true         # /home inacessível
PrivateTmp=true          # /tmp isolado
```

O serviço roda com o usuário `glpi-ad-svc` (sem shell, sem home directory).

---

## Recomendações adicionais

### Firewall

```bash
# Aceitar conexões na porta 8443 apenas do IP do GLPI
sudo ufw allow from <IP_DO_GLPI> to any port 8443

# Ou com iptables:
sudo iptables -A INPUT -p tcp --dport 8443 -s <IP_DO_GLPI> -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 8443 -j DROP
```

### HTTPS (TLS) no FastAPI

Para produção, configure TLS no uvicorn ou use um reverse proxy:

**Opção 1 — TLS direto no uvicorn** (alterar o ExecStart no systemd):
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8443 \
    --ssl-keyfile /etc/ssl/private/glpi-ad.key \
    --ssl-certfile /etc/ssl/certs/glpi-ad.crt
```

**Opção 2 — Reverse proxy com Nginx** (recomendado):
```nginx
server {
    listen 8443 ssl;
    server_name glpi-ad.empresa.local;

    ssl_certificate     /etc/ssl/certs/glpi-ad.crt;
    ssl_certificate_key /etc/ssl/private/glpi-ad.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-GLPI-Signature $http_x_glpi_signature;
    }
}
```

### Rotação de credenciais

Recomenda-se rotacionar periodicamente:

| Credencial | Frequência sugerida |
|---|---|
| Senha da conta de serviço AD | A cada 90 dias |
| GLPI API Token | A cada 6 meses |
| Webhook Secret | A cada 6 meses |

Ao rotacionar, atualize o `.env` e reinicie o serviço:
```bash
sudo systemctl restart glpi-ad-integration
```

### Auditoria

Monitore os logs do serviço para:
- Tentativas de webhook com assinatura inválida (possível ataque)
- Erros de conexão com AD (possível problema de rede/credencial)
- Criações duplicadas (possível homonímia ou reenvio)

No AD, habilite auditoria de criação de objetos na OU:
1. **Group Policy** > Computer Configuration > Policies > Windows Settings > Security Settings > Advanced Audit Policy
2. Habilite **Audit Directory Service Changes** para a OU de usuários
