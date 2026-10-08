from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    sucursal_id: Annotated[UUID | None, Field(alias="sucursalId")] = None
    email: EmailStr
    password: str
    remember_me: Annotated[bool, Field(alias="rememberMe")] = False

    model_config = {"populate_by_name": True}


class RefreshRequest(BaseModel):
    # Opcional: el refresh token puede llegar por la cookie
    # HttpOnly en vez del body (clientes viejos siguen mandándolo en el body).
    refresh_token: Annotated[str | None, Field(alias="refreshToken")] = None

    model_config = {"populate_by_name": True}


class UserOut(BaseModel):
    id: UUID
    full_name: str
    email: str
    role: str
    branch_id: UUID | None
    branch_name: str | None = None
    permissions: list[str] = []
    # Para que Inicio pueda avisar "Configura tu PIN de caja" sin requerir
    # usuarios:ver (que el Cajero no tiene). Login, refresh y /auth/me lo
    # calculan a partir de pin_hash.
    tiene_pin: bool = False
    # El administrador inicial y quien entra con la contraseña de fábrica deben
    # cambiarla antes de usar el sistema (ver deps.get_current_user).
    debe_cambiar_password: bool = False


class LoginResponse(BaseModel):
    requires_branch_selection: Literal[False] = False
    token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: UserOut


class BranchOption(BaseModel):
    id: UUID
    nombre: str


class BranchSelectionRequired(BaseModel):
    """Respuesta de login cuando un Administrador con 2+ sucursales no indicó cuál usar."""

    requires_branch_selection: Literal[True] = True
    sucursales: list[BranchOption]


class TokenData(BaseModel):
    sub: str
    email: str
    role: str
    branch_id: UUID | None
    permissions: list[str] = []
    jti: str
    exp: datetime
    debe_cambiar_password: bool = False


class WsTicketResponse(BaseModel):
    """Ticket efímero de un solo uso para WebSockets (comandas, estancias)."""

    ticket: str
    expires_in: int
