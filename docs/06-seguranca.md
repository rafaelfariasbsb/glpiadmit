# Segurança

## Princípios aplicados

1. **Menor privilégio** — Conta de serviço AD com permissão apenas no OU de usuários
2. **Criptografia em trânsito** — LDAPS (porta 636) para comunicação com AD; HTTPS para GLPI
3. **Validação de origem** — Webhook autenticado com assinatura HMAC-SHA256
4. **Sanitização de entrada** — Proteção contra injeção LDAP (RFC 4514/4515)
5. **Senhas seguras** — Geração criptográfica (CSPRNG), troca obrigatória no primeiro login
6. **Isolamento de processo** — Serviço roda com usuário dedicado sem privilégios root

---

## Detalhes por camada

### Comunicação com Active Directory

| Aspecto | Implementação |
|---|---|
| Protocolo | LDAPS (LDAP over SSL/TLS, porta 636) |
| Autenticação | Bind com conta de serviço (DN + senha) |
| Validação de certificado | Habilitada (`ssl.CERT_REQUIRED`) |
| Operação de senha | Via atributo `unicodePwd` (exige SSL obrigatoriamente) |

**Nunca** use LDAP simples (porta 389) em produção — a operação `unicodePwd` é rejeitada sem SSL.

### Validação do Webhook (GLPI 11 nativo)

O GLPI 11 assina o webhook com:

```
X-GLPI-signature = hmac-sha256(body + timestamp, secret)
X-GLPI-timestamp = <unix timestamp>
```

O GLPIADmit valida:
1. Tenta `hmac(body + timestamp, secret)` — formato GLPI 11 nativo
2. Fallback: `hmac(body, secret)` — endpoint legado `/webhook/user-creation`

Usa `hmac.compare_digest()` (constant-time) para prevenir timing attacks.

Se `WEBHOOK_SECRET` não estiver configurado, um warning é logado e a validação é ignorada. **Em produção, sempre configure o `WEBHOOK_SECRET`.**

### Secret do Webhook — GLPIKey

O GLPI 11 armazena o secret do webhook **criptografado com `GLPIKey`** no banco de dados. Se o secret for inserido em texto plano, o GLPI não consegue descriptografar e usa uma string vazia como chave → todas as assinaturas serão inválidas.

**Sempre use** `$glpikey->encrypt($secret)` ao inserir o secret no banco. O script `glpi-create-webhook.php` faz isso automaticamente.

### Comunicação com GLPI (API REST)

| Aspecto | Implementação |
|---|---|
| Protocolo | HTTPS (recomendado) ou HTTP |
| Verificação de certificado | Configurável via `GLPI_VERIFY_SSL` (padrão: `true`) |
| Autenticação | `user_token` + `App-Token` (headers centralizados) |
| Sessão | Iniciada e encerrada a cada operação (`initSession` / `killSession`) |
| Perfil API | Ativado automaticamente para o maior privilégio disponível |

> Use `GLPI_VERIFY_SSL=false` apenas em ambientes de desenvolvimento com certificados auto-assinados.

### Sanitização de dados

Dois níveis aplicados antes de qualquer operação LDAP:

1. **`sanitize_ldap_value()`** — Escapa `*`, `(`, `)`, `\`, `\0` em filtros de busca (RFC 4515, previne LDAP injection)
2. **`sanitize_dn_component()`** — Escapa `\`, `,`, `+`, `"`, `<`, `>`, `;`, `=` em Distinguished Names (RFC 4514, backslash escapado primeiro para evitar re-escape)

### Validação de email

O campo `email` é validado automaticamente pelo Pydantic usando `EmailStr` (biblioteca `email-validator`), garantindo conformidade com RFCs de email.

### Gerenciamento de credenciais

| Credencial | Armazenamento |
|---|---|
| Senha da conta de serviço AD | Variável de ambiente (`AD_BIND_PASSWORD`) |
| Token API do GLPI | Variável de ambiente (`GLPI_API_TOKEN`) |
| App Token do GLPI | Variável de ambiente (`GLPI_APP_TOKEN`) |
| Secret do Webhook | Variável de ambiente (`WEBHOOK_SECRET`) |

O arquivo `.env`:
- Permissão `600` (somente o owner lê): `chmod 600 .env`
- **Nunca** versionado no git (listado no `.gitignore`)
- **Nunca** copiado para a imagem Docker (listado no `.dockerignore`) — montado via `env_file`
- Carregado via `pydantic-settings` com cache (`@lru_cache`) — instância única em memória

### Processo do serviço — systemd

O unit file aplica hardening:

```ini
NoNewPrivileges=true     # Impede escalação de privilégio
ProtectSystem=strict     # Sistema de arquivos read-only exceto WorkingDirectory
ProtectHome=true         # /home inacessível
PrivateTmp=true          # /tmp isolado
```

Roda com o usuário `glpi-ad-svc` (sem shell, sem home directory).

### Processo do serviço — Docker

- Roda como usuário não-root `appuser` (UID/GID criados no Dockerfile)
- `.env` nunca copiado para a imagem (`.dockerignore`) — montado apenas em runtime via `env_file`
- `PYTHONDONTWRITEBYTECODE=1` evita geração de `.pyc` no container
- Imagem base `python:3.11-slim` (superfície de ataque mínima)

> **Nunca** faça `docker commit` de um container com `.env` carregado — variáveis de ambiente ficam visíveis em `docker inspect`.

---

## Recomendações adicionais

### Firewall

```bash
# Aceitar conexões apenas do IP do GLPI
sudo ufw allow from <IP_DO_GLPI> to any port 80

# Com iptables:
sudo iptables -A INPUT -p tcp --dport 80 -s <IP_DO_GLPI> -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 80 -j DROP
```

> A porta 8443 pode ser exposta para monitoramento interno, mas o webhook do GLPI deve sempre apontar para a porta 80 (sem porta explícita na URL).

### HTTPS (TLS) no GLPIADmit

Para produção com TLS, use um reverse proxy:

**Nginx (recomendado):**

```nginx
server {
    listen 443 ssl;
    server_name glpiadmit.empresa.local;

    ssl_certificate     /etc/ssl/certs/glpiadmit.crt;
    ssl_certificate_key /etc/ssl/private/glpiadmit.key;

    # Proxy para o GLPIADmit na porta 80
    location / {
        proxy_pass http://127.0.0.1:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-GLPI-signature $http_x_glpi_signature;
        proxy_set_header X-GLPI-timestamp $http_x_glpi_timestamp;
    }
}
```

> **Atenção**: Se usar HTTPS, certifique-se de que o GLPI consegue fazer a requisição para a URL do webhook com HTTPS. O certificado deve ser válido ou o GLPI deve ter o CA configurado.

### Rotação de credenciais

| Credencial | Frequência sugerida |
|---|---|
| Senha da conta de serviço AD | A cada 90 dias |
| GLPI API Token | A cada 6 meses |
| GLPI App Token | A cada 6 meses |
| Webhook Secret | A cada 6 meses |

Ao rotacionar, atualize o `.env` e reinicie:

```bash
# Docker
docker compose up -d --force-recreate

# systemd
sudo systemctl restart glpi-ad-integration
```

> Após rotacionar o Webhook Secret, atualize também no GLPI (Administração > Webhooks) e no `.env`. O GLPI re-criptografa com GLPIKey automaticamente ao salvar pela interface.

### Auditoria

Monitore os logs do serviço para:
- Tentativas com assinatura inválida (`Webhook recebido com assinatura inválida`)
- Erros de conexão com AD (possível problema de rede/credencial)
- Criações duplicadas (possível homonímia ou reenvio do webhook)

No AD, habilite auditoria na OU de usuários:
1. **Group Policy** > Computer Configuration > Policies > Windows Settings > Security Settings > Advanced Audit Policy
2. Habilite **Audit Directory Service Changes** para a OU de usuários
