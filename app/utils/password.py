import secrets
import string

_SPECIAL_CHARS = "!@#$%&*"
_ALPHABET = string.ascii_letters + string.digits + _SPECIAL_CHARS
_MIN_LENGTH = 12
_SHUFFLE = secrets.SystemRandom().shuffle


def generate_temporary_password(length: int = 16) -> str:
    """Gera senha temporaria segura que atende politicas padrao do AD.

    Garante pelo menos: 1 maiuscula, 1 minuscula, 1 digito, 1 caractere especial.
    Usa secrets (CSPRNG) para geracao criptograficamente segura.
    """
    length = max(length, _MIN_LENGTH)

    # Garantir complexidade minima
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(_SPECIAL_CHARS),
    ]

    remaining = [secrets.choice(_ALPHABET) for _ in range(length - len(required))]

    password_chars = required + remaining
    _SHUFFLE(password_chars)

    return "".join(password_chars)
