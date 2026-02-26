import re
import unicodedata

# Caracteres que devem ser escapados em filtros LDAP (RFC 4515)
_LDAP_FILTER_ESCAPES: dict[str, str] = {
    "\\": "\\5c",
    "*": "\\2a",
    "(": "\\28",
    ")": "\\29",
    "\x00": "\\00",
}

# Caracteres que devem ser escapados em componentes de DN (RFC 4514)
# Ordem importa: backslash PRIMEIRO para nao re-escapar
_DN_SPECIAL_CHARS: list[str] = ["\\", ",", "+", '"', "<", ">", ";", "="]


def normalize_name(name: str) -> str:
    """Remove acentos e caracteres especiais de um nome."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = nfkd.encode("ASCII", "ignore").decode("ASCII")
    return ascii_only.strip()


def generate_sam_account_name(first_name: str, last_name: str) -> str:
    """Gera sAMAccountName a partir do nome (max 20 chars).

    Formato: primeira letra do nome + sobrenome, tudo minusculo, sem acentos.
    Ex: Rafael Silva -> rsilva
    """
    first = normalize_name(first_name).lower().replace(" ", "")
    last = normalize_name(last_name).lower().split()[0] if last_name.strip() else ""

    if not first or not last:
        raise ValueError("Nome e sobrenome sao obrigatorios para gerar sAMAccountName")

    sam = f"{first[0]}{last}"
    sam = re.sub(r"[^a-z0-9._-]", "", sam)

    return sam[:20]


def generate_upn(sam_account_name: str, domain: str) -> str:
    """Gera userPrincipalName no formato usuario@dominio."""
    return f"{sam_account_name}@{domain}"


def generate_display_name(first_name: str, last_name: str) -> str:
    """Gera displayName no formato 'Nome Sobrenome'."""
    return f"{first_name.strip()} {last_name.strip()}"


def generate_cn(first_name: str, last_name: str) -> str:
    """Gera CN (Common Name). Mesmo que displayName."""
    return generate_display_name(first_name, last_name)


def sanitize_ldap_value(value: str) -> str:
    """Escapa caracteres especiais para prevenir injecao LDAP (RFC 4515)."""
    for char, escaped in _LDAP_FILTER_ESCAPES.items():
        value = value.replace(char, escaped)
    return value


def sanitize_dn_component(value: str) -> str:
    """Escapa caracteres especiais em componentes de DN (RFC 4514).

    Backslash e processado primeiro para evitar re-escape dos
    backslashes inseridos ao escapar outros caracteres.
    """
    for char in _DN_SPECIAL_CHARS:
        value = value.replace(char, f"\\{char}")
    return value
