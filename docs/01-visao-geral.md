# Visão Geral — Integração GLPI + Active Directory

## O que é

Serviço de automação que cria usuários no **Active Directory (AD)** automaticamente quando um chamado de "Criação de Usuário" é aberto no **GLPI 11**. O usuário criado no AD on-premises é sincronizado com o **Azure AD / Entra ID** via Entra Connect.

## Arquitetura

```
┌──────────────────┐       Webhook (POST)       ┌─────────────────────┐
│                  │ ─────────────────────────►  │                     │
│   GLPI 11.0.5    │                             │  FastAPI (Python)   │
│   (Formulário)   │  ◄─────────────────────────  │  Porta 8443         │
│                  │   Atualiza chamado (API)    │                     │
└──────────────────┘                             └────────┬────────────┘
                                                          │
                                                   LDAPS (636)
                                                          │
                                                          ▼
                                                 ┌─────────────────┐
                                                 │ Active Directory │
                                                 │ Windows Server   │
                                                 └────────┬────────┘
                                                          │
                                                   Entra Connect
                                                   (sync ~30 min)
                                                          │
                                                          ▼
                                                 ┌─────────────────┐
                                                 │ Azure AD / M365  │
                                                 │ Entra ID         │
                                                 └─────────────────┘
```

## Fluxo resumido

1. Solicitante preenche o formulário "Criação de Usuário" no GLPI
2. GLPI gera um ticket e dispara um **webhook** para o serviço FastAPI
3. O serviço **valida** os dados e **cria o usuário** no AD via LDAPS
4. O serviço **atualiza o chamado** no GLPI com as credenciais ou erro
5. O **Entra Connect** sincroniza o novo usuário com Azure AD em até 30 minutos

## Tecnologias

| Componente | Tecnologia |
|---|---|
| ITSM | GLPI 11.0.5 |
| Middleware | Python 3.11+ / FastAPI |
| Validação de dados | Pydantic v2 + EmailStr |
| Comunicação com AD | ldap3 (LDAPS) |
| Comunicação com GLPI | httpx (API REST) |
| Configuração | pydantic-settings (variáveis de ambiente) |
| Deploy | systemd (Linux) |
| Diretório | Windows Server AD DS |
| Cloud | Azure AD / Entra ID (via Entra Connect) |

## Estrutura do projeto

```
integracao_glpi/
├── app/
│   ├── main.py              # App FastAPI, lifespan, health check
│   ├── config.py            # Configurações via pydantic-settings (@lru_cache)
│   ├── models.py            # Modelos Pydantic (payload, resultado, resposta)
│   ├── services/
│   │   ├── ad_service.py    # Criação de usuário no AD (connection_factory)
│   │   └── glpi_service.py  # Comunicação com API GLPI (SSL configurável)
│   ├── utils/
│   │   ├── password.py      # Geração de senha temporária (secrets/CSPRNG)
│   │   └── validators.py    # Validação e sanitização de dados
│   └── routes/
│       └── webhook.py       # Endpoint do webhook (Depends para settings)
├── tests/
│   ├── conftest.py          # Fixtures compartilhadas (settings, payloads, mocks)
│   ├── test_validators.py   # Testes de validação/sanitização
│   ├── test_ad_service.py   # Testes do serviço AD
│   ├── test_webhook.py      # Testes do endpoint HTTP
│   ├── test_password.py     # Testes de geração de senha
│   └── test_glpi_service.py # Testes do serviço GLPI
├── docs/                    # Esta documentação
├── systemd/                 # Unit file para deploy
├── .env.example             # Template de configuração
└── requirements.txt         # Dependências Python
```
