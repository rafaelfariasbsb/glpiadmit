# Uso e Operação

## Como solicitar criação de usuário

### Para o solicitante (RH / Gestor)

1. Acesse o GLPI: `https://glpi.suaempresa.com.br`
2. Vá em **Assistência > Criar um ticket** ou acesse o **Catálogo de Serviços**
3. Selecione o formulário **"Criação de Usuário - AD"**
4. Preencha os campos:

| Campo | Exemplo | Obrigatório |
|---|---|---|
| Nome | Maria | Sim |
| Sobrenome | Santos | Sim |
| Email corporativo | maria.santos@empresa.com | Sim |
| Departamento | Recursos Humanos | Sim |
| Cargo | Analista de RH | Sim |
| Telefone | (11) 99999-0000 | Não |
| Gestor direto | João Silva | Não |
| Grupos AD | VPN, Email | Não |

5. Clique em **Enviar**
6. Um chamado será aberto automaticamente
7. Aguarde alguns segundos — o chamado será atualizado com as credenciais do novo usuário

### O que acontece após o envio

```
[Envio do formulário]
        │
        ▼
[Chamado criado no GLPI] ──── Status: Novo
        │
        ▼
[Webhook disparado para o serviço]
        │
        ▼
[Usuário criado no AD]
        │
        ├── Sucesso ──► Chamado atualizado com credenciais ──► Status: Resolvido
        │
        └── Erro ──► Chamado atualizado com detalhes do erro ──► Status: Pendente
```

### Informações retornadas no chamado (sucesso)

O followup no chamado conterá:

- **Login (sAMAccountName)**: ex: `msantos`
- **UPN**: ex: `msantos@empresa.local`
- **Nome de exibição**: ex: `Maria Santos`
- **Senha temporária**: senha gerada automaticamente
- **DN**: localização do objeto no AD
- **Grupos**: grupos aos quais o usuário foi adicionado
- Aviso de troca obrigatória de senha no primeiro login
- Aviso de sincronização com Azure AD em até 30 minutos

### Em caso de erro

O followup no chamado conterá:

- Descrição do erro
- Detalhes técnicos
- Instrução para verificação manual
- O chamado ficará com status **Pendente** para ação da equipe de TI

---

## Gerenciamento do serviço

### Comandos systemd

```bash
# Ver status do serviço
sudo systemctl status glpi-ad-integration

# Iniciar o serviço
sudo systemctl start glpi-ad-integration

# Parar o serviço
sudo systemctl stop glpi-ad-integration

# Reiniciar o serviço
sudo systemctl restart glpi-ad-integration

# Ver logs em tempo real
sudo journalctl -u glpi-ad-integration -f

# Ver logs das últimas 2 horas
sudo journalctl -u glpi-ad-integration --since "2 hours ago"

# Ver apenas erros
sudo journalctl -u glpi-ad-integration -p err
```

### Health check

O serviço expõe um endpoint de verificação de saúde:

```bash
curl http://localhost:8443/health
```

Resposta esperada:
```json
{"status": "ok", "service": "glpi-ad-integration"}
```

Use este endpoint para monitoramento (Zabbix, Nagios, Uptime Kuma, etc.).

### Documentação da API (OpenAPI)

O FastAPI gera documentação interativa automaticamente:

- **Swagger UI**: `http://<servidor>:8443/docs`
- **ReDoc**: `http://<servidor>:8443/redoc`

Nesses endpoints é possível ver todos os campos esperados, testar o endpoint manualmente e verificar os modelos de dados.

---

## Regras de nomenclatura

O serviço gera automaticamente os identificadores do usuário:

| Atributo | Regra | Exemplo |
|---|---|---|
| `sAMAccountName` | Primeira letra do nome + primeiro sobrenome, sem acentos, minúsculo (max 20 chars) | `Maria Santos` → `msantos` |
| `userPrincipalName` | sAMAccountName + @domínio | `msantos@empresa.local` |
| `displayName` | Nome + Sobrenome | `Maria Santos` |
| `cn` (Common Name) | Mesmo que displayName | `Maria Santos` |

### Tratamento de nomes com acentos

Acentos e caracteres especiais são removidos automaticamente:

| Nome original | sAMAccountName gerado |
|---|---|
| José Gonçalves | `jgoncalves` |
| João da Conceição | `jconceicao` |
| André Müller | `amuller` |

### Em caso de duplicidade

Se o `sAMAccountName` ou `userPrincipalName` já existir no AD, o chamado será marcado como **erro** e a equipe de TI deverá:

1. Verificar se é um duplicado real ou homonímia
2. Criar manualmente com um sAMAccountName alternativo (ex: `msantos2`)
3. Resolver o chamado no GLPI

---

## Senha temporária

- Gerada automaticamente com 16 caracteres (mínimo 12, configurável)
- Contém: maiúsculas, minúsculas, números e caracteres especiais (`!@#$%&*`)
- Gerada com `secrets` (CSPRNG — criptograficamente seguro)
- O usuário **deve trocar a senha** no primeiro login (forçado via `pwdLastSet=0`)
- A senha temporária é registrada no followup do chamado

> **Segurança**: Recomenda-se que o solicitante (RH/Gestor) comunique a senha temporária ao novo colaborador de forma segura (presencialmente ou por canal criptografado), e nunca por email.
