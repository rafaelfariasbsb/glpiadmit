# Configuração do Active Directory

Este guia detalha os pré-requisitos e configurações necessárias no Active Directory.

---

## 1. Criar OU para novos usuários

Se ainda não existir, crie uma OU dedicada onde os usuários serão provisionados:

```powershell
New-ADOrganizationalUnit -Name "Usuarios" -Path "DC=empresa,DC=local"
```

> O caminho da OU deve corresponder ao valor de `AD_USER_OU` no `.env`.

## 2. Criar conta de serviço

Crie uma conta de serviço dedicada para a integração:

```powershell
New-ADUser `
    -Name "svc-glpi-ad" `
    -SamAccountName "svc-glpi-ad" `
    -UserPrincipalName "svc-glpi-ad@empresa.local" `
    -Path "OU=ServiceAccounts,DC=empresa,DC=local" `
    -AccountPassword (ConvertTo-SecureString "SenhaForte!2026" -AsPlainText -Force) `
    -Enabled $true `
    -PasswordNeverExpires $true `
    -CannotChangePassword $true `
    -Description "Conta de servico - Integracao GLPI-AD"
```

## 3. Delegar permissões (princípio do menor privilégio)

**Não adicione a conta de serviço como Domain Admin.** Em vez disso, delegue permissões apenas na OU de usuários:

### Via interface gráfica (ADUC):

1. Abra **Active Directory Users and Computers**
2. Clique com botão direito na OU `Usuarios` > **Delegate Control...**
3. Adicione o usuário `svc-glpi-ad`
4. Selecione **Create a custom task to delegate**
5. Selecione **Only the following objects in the folder** > marque **User objects**
6. Marque:
   - **Create selected objects in this folder**
   - **Delete selected objects in this folder**
7. Em permissões, marque:
   - **Read All Properties**
   - **Write All Properties**
   - **Reset Password**
8. Conclua o wizard

### Via PowerShell:

```powershell
# Obter o SID da conta de serviço
$svcAccount = Get-ADUser "svc-glpi-ad"

# Obter a OU
$ouDN = "OU=Usuarios,DC=empresa,DC=local"
$ou = Get-ADOrganizationalUnit -Identity $ouDN

# Importar módulo de ACL
Import-Module ActiveDirectory
$acl = Get-Acl "AD:\$ouDN"

# GUIDs necessários
$userGUID = [GUID]"bf967aba-0de6-11d0-a285-00aa003049e2"  # User object class

# Permissão: criar e deletar objetos User
$createRule = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
    $svcAccount.SID,
    "CreateChild,DeleteChild",
    "Allow",
    $userGUID
)
$acl.AddAccessRule($createRule)

# Permissão: propriedades genéricas (leitura/escrita)
$propsRule = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
    $svcAccount.SID,
    "GenericAll",
    "Allow",
    "Descendents",
    $userGUID
)
$acl.AddAccessRule($propsRule)

Set-Acl "AD:\$ouDN" $acl
```

## 4. Configurar LDAPS (SSL)

A comunicação com o AD **deve** usar LDAPS (porta 636) porque a operação de definir senha (`unicodePwd`) exige conexão criptografada.

### Verificar se LDAPS está habilitado:

```powershell
# No controlador de domínio:
Test-NetConnection -ComputerName dc01.empresa.local -Port 636
```

Se LDAPS não estiver habilitado, é necessário instalar um certificado SSL no controlador de domínio:

1. Solicite um certificado ao **AD Certificate Services** ou a uma CA externa
2. O certificado deve:
   - Ter o FQDN do DC no campo Subject ou SAN
   - Ter o propósito "Server Authentication"
   - Estar instalado no store **Personal** do computador
3. Após instalar o certificado, reinicie o serviço `Active Directory Domain Services` ou o servidor

### Testar conectividade LDAPS a partir do servidor Linux:

```bash
# Testar porta
nc -zv dc01.empresa.local 636

# Testar certificado SSL
openssl s_client -connect dc01.empresa.local:636 -showcerts
```

## 5. Configurar grupos para novos usuários

Crie ou identifique os grupos AD que serão oferecidos no formulário GLPI. Anote o **DN completo** de cada grupo:

```powershell
# Listar grupos de uma OU
Get-ADGroup -Filter * -SearchBase "OU=Grupos,DC=empresa,DC=local" |
    Select-Object Name, DistinguishedName |
    Format-Table -AutoSize
```

Exemplo de DNs de grupos:
```
CN=GRP-VPN,OU=Grupos,DC=empresa,DC=local
CN=GRP-Email,OU=Grupos,DC=empresa,DC=local
CN=GRP-Financeiro,OU=Grupos,DC=empresa,DC=local
CN=GRP-RH,OU=Grupos,DC=empresa,DC=local
```

> Estes DNs devem ser usados no campo "Grupos AD" do formulário GLPI.

## 6. Verificar política de senha

Confirme a política de senha do domínio para que as senhas geradas automaticamente sejam aceitas:

```powershell
Get-ADDefaultDomainPasswordPolicy |
    Select-Object MinPasswordLength, ComplexityEnabled, PasswordHistoryCount
```

O gerador de senhas do serviço cria senhas com:
- Mínimo 16 caracteres
- Letras maiúsculas, minúsculas, números e caracteres especiais
- Isso atende a maioria das políticas padrão do AD

## 7. Considerações sobre Entra Connect

Se o ambiente usa **Entra Connect** (Azure AD Connect) para sincronizar com Azure AD / Microsoft 365:

- Novos usuários criados no AD on-premises serão sincronizados automaticamente
- O ciclo de sync padrão é de **30 minutos**
- Para forçar sync imediato (se necessário):

```powershell
# No servidor do Entra Connect:
Start-ADSyncSyncCycle -PolicyType Delta
```

- Certifique-se de que o `userPrincipalName` gerado **não conflita** com contas existentes no Azure AD
- O serviço valida duplicidade antes de criar, mas é importante monitorar os erros de sync no portal do Entra

### Atributos sincronizados

Os seguintes atributos preenchidos pelo serviço são sincronizados para o Azure AD:

| Atributo AD | Atributo Azure AD |
|---|---|
| `userPrincipalName` | `userPrincipalName` |
| `displayName` | `displayName` |
| `givenName` | `givenName` |
| `sn` | `surname` |
| `mail` | `mail` |
| `department` | `department` |
| `title` | `jobTitle` |
| `telephoneNumber` | `telephoneNumber` |
| `company` | `companyName` |
