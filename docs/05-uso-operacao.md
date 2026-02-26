# Uso e Operação

## Como solicitar criação de usuário

### Para o solicitante (RH / Gestor)

1. Acesse o GLPI: `https://glpi.suaempresa.com.br`
2. Vá em **Assistência > Catálogo de Serviços**
3. Clique em **"Solicitar Criação de Usuário AD"** (fixado no topo da categoria "Gestão de Acessos")
4. Preencha os campos:

| Campo | Exemplo | Obrigatório | Observações |
|---|---|---|---|
| Nome | Rafael | Sim | Primeiro nome |
| Sobrenome | Silva | Sim | Sobrenome |
| E-mail corporativo | rafael.silva@empresa.com | Sim | Email válido |
| Departamento | Tecnologia da Informação | Sim | |
| Cargo | Analista de Sistemas | Sim | |
| Grupo AD | `CN=GRP-TI,OU=Grupos,DC=empresa,DC=local` | Não | **Apenas o DN completo** — não repita o nome do campo |

> **Atenção no campo "Grupo AD"**: preencha **somente** o Distinguished Name (DN) do grupo. Exemplo correto:
> ```
> CN=GRP-TI,OU=Grupos,DC=empresa,DC=local
> ```
> Exemplo **incorreto** (não inclua o prefixo "Grupo AD:"):
> ```
> Grupo AD: CN=GRP-TI,OU=Grupos,DC=empresa,DC=local
> ```

5. Clique em **Enviar**
6. Um chamado será criado automaticamente
7. Aguarde alguns segundos — o chamado será atualizado com as credenciais do novo usuário

### O que acontece após o envio

```
[Formulário enviado]
        │
        ▼
[Ticket criado no GLPI]  ──  Status: Novo
        │
        ▼
[Webhook disparado para o GLPIADmit]
        │
        ▼
[Dados extraídos do conteúdo do ticket]
        │
        ▼
[Usuário criado no AD via LDAPS]
        │
        ├── Sucesso ──► Followup com credenciais ──► Status: Resolvido
        │
        └── Erro ──► Followup com detalhes do erro ──► Status: Pendente
```

### Informações retornadas no chamado (sucesso)

O followup no chamado conterá:

- **Login (sAMAccountName)**: ex: `rsilva`
- **UPN**: ex: `rsilva@empresa.local`
- **Nome de exibição**: ex: `Rafael Silva`
- **Senha temporária**: gerada automaticamente (16 caracteres)
- **DN**: localização do objeto no AD
- **Grupos**: grupos aos quais o usuário foi adicionado
- Aviso de troca obrigatória de senha no primeiro login
- Aviso de sincronização com Azure AD em até 30 minutos

> **Segurança**: Comunique a senha temporária ao novo colaborador de forma segura (presencialmente ou por canal criptografado). Nunca por email.

### Em caso de erro

O followup conterá:
- Descrição do erro
- Detalhes técnicos
- Instrução para verificação manual
- O chamado ficará com status **Pendente** — a equipe de TI deve resolver manualmente

---

## Gerenciamento do serviço

### Docker (deploy recomendado)

```bash
# Ver status
docker compose ps

# Iniciar
docker compose up -d

# Parar
docker compose down

# Reiniciar (sem perder configurações)
# ATENÇÃO: use --force-recreate quando o .env for alterado
docker compose up -d --force-recreate

# Ver logs em tempo real
docker compose logs -f glpiadmit

# Últimas 100 linhas
docker compose logs --tail=100 glpiadmit

# Rebuild e reiniciar (nova versão)
docker compose build --no-cache && docker compose up -d
```

> **Importante**: `docker compose restart` **não relê o `env_file`**. Use `up -d --force-recreate` ao alterar o `.env`.

### systemd (deploy alternativo)

```bash
# Ver status
sudo systemctl status glpi-ad-integration

# Iniciar / Parar / Reiniciar
sudo systemctl start glpi-ad-integration
sudo systemctl stop glpi-ad-integration
sudo systemctl restart glpi-ad-integration

# Logs em tempo real
sudo journalctl -u glpi-ad-integration -f

# Logs das últimas 2 horas
sudo journalctl -u glpi-ad-integration --since "2 hours ago"

# Apenas erros
sudo journalctl -u glpi-ad-integration -p err
```

### Health check

```bash
curl http://localhost:8443/health
# {"status": "ok", "service": "glpi-ad-integration"}
```

Use este endpoint para monitoramento (Zabbix, Nagios, Uptime Kuma, etc.).

### Retry automático em falhas transientes

O serviço recupera falhas transientes sem intervenção manual:

| Operação | Trigger | Tentativas | Espera entre tentativas |
|---|---|---|---|
| Conexão LDAP com o AD | `LDAPException` | 3 | Exponencial: 2s → 4s → 8s |
| Atualização de chamado no GLPI | `httpx.HTTPError` | 3 | Exponencial: 2s → 4s → 8s |

Cada tentativa intermediária gera um log `WARNING: Retrying...`. Após esgotar todas as tentativas, o erro é registrado com `ERROR: ... após 3 tentativas` e o ticket permanece sem atualização — verificar o chamado no GLPI manualmente.

> **Nota**: Falhas na criação do usuário no AD **não** são re-tentadas automaticamente; em caso de erro, o chamado é marcado como **Pendente** no GLPI com as instruções para reprocessamento manual.

### Documentação interativa

- **Swagger UI**: `http://<servidor>:8443/docs`
- **ReDoc**: `http://<servidor>:8443/redoc`

---

## Regras de nomenclatura

O serviço gera automaticamente os identificadores do usuário:

| Atributo | Regra | Exemplo |
|---|---|---|
| `sAMAccountName` | Primeira letra do nome + sobrenome, minúsculo, sem acentos (max 20 chars) | `Rafael Silva` → `rsilva` |
| `userPrincipalName` | sAMAccountName + @domínio | `rsilva@empresa.local` |
| `displayName` | Nome + Sobrenome | `Rafael Silva` |
| `cn` | Mesmo que `displayName` | `Rafael Silva` |

### Tratamento de acentos

Acentos e caracteres especiais são removidos automaticamente:

| Nome original | sAMAccountName |
|---|---|
| José Gonçalves | `jgoncalves` |
| João da Conceição | `jconceicao` |
| André Müller | `amuller` |
| María García | `mgarcia` |

### Em caso de duplicidade

Se o `sAMAccountName` ou `userPrincipalName` já existir no AD, o chamado será marcado como **Pendente** e a equipe de TI deverá:

1. Verificar se é duplicata real ou homonímia
2. Criar manualmente com sAMAccountName alternativo (ex: `rsilva2`, `rnsilva`)
3. Resolver o chamado no GLPI

---

## Senha temporária

- Gerada automaticamente com **16 caracteres** (mínimo 12)
- Contém: maiúsculas, minúsculas, números e caracteres especiais (`!@#$%&*`)
- Gerada com `secrets` (CSPRNG — criptograficamente seguro)
- O usuário **deve trocar a senha** no primeiro login (forçado via `pwdLastSet=0`)
- Registrada no followup do chamado

---

## Ambiente de teste

Para testar o fluxo completo sem afetar o AD de produção:

```bash
# Subir ambiente completo (GLPI + Samba AD + GLPIADmit)
bash tests/docker/setup-test-env.sh
```

Após o setup:
- **GLPI**: `http://localhost:8080` (glpi/glpi)
- **Catálogo de Serviços**: URL exibida no resumo do script
- **GLPIADmit**: `http://localhost:8443`
- **Domínio AD de teste**: `TESTE.LOCAL`
- **Grupo de teste**: `CN=GRP-TI,OU=Grupos,DC=teste,DC=local`
