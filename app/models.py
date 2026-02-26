import re

from pydantic import BaseModel, EmailStr, field_validator


class UserCreationPayload(BaseModel):
    """Payload recebido do webhook do GLPI ao criar chamado de novo usuario."""

    ticket_id: int
    first_name: str
    last_name: str
    email: EmailStr
    department: str
    title: str
    phone: str = ""
    manager: str = ""
    groups: list[str] = []

    @field_validator("first_name", "last_name", "department", "title")
    @classmethod
    def not_empty(cls, v: str, info) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError(f"{info.field_name} is required and cannot be empty")
        return stripped

    @field_validator("phone")
    @classmethod
    def sanitize_phone(cls, v: str) -> str:
        return re.sub(r"[^\d+\-() ]", "", v.strip())


class UserCreationResult(BaseModel):
    """Resultado da criacao do usuario no AD."""

    success: bool
    ticket_id: int
    sam_account_name: str = ""
    user_principal_name: str = ""
    display_name: str = ""
    temporary_password: str = ""
    distinguished_name: str = ""
    message: str = ""
    groups_added: list[str] = []
    errors: list[str] = []


class WebhookResponse(BaseModel):
    """Resposta retornada ao GLPI apos processar o webhook."""

    status: str
    message: str
    ticket_id: int | None = None
