from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, EmailStr, Field, StringConstraints
from pydantic_core import PydanticCustomError

NombreRequerido = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# M2: la regla de la UI (mínimo 8) también se valida en el servidor. Solo al
# fijar una contraseña (alta/edición): el login no la exige, para no dejar
# fuera a cuentas viejas con contraseñas más cortas.
PASSWORD_MIN_LENGTH = 8


def _validar_password(v: str) -> str:
    if len(v) < PASSWORD_MIN_LENGTH:
        raise PydanticCustomError(
            "password_corta",
            "La contraseña debe tener al menos {min} caracteres.",
            {"min": PASSWORD_MIN_LENGTH},
        )
    return v


def _normalizar_email(v: str) -> str:
    # M1: EmailStr solo pasa a minúsculas el dominio; el correo se guarda
    # completo en minúsculas para que no se dupliquen cuentas por mayúsculas.
    return v.strip().lower()


def _vacio_a_none(v: object) -> object:
    return None if v == "" else v


EmailUsuario = Annotated[EmailStr, AfterValidator(_normalizar_email)]
PasswordNueva = Annotated[str, AfterValidator(_validar_password)]

# PIN de caja (C1): 4 dígitos numéricos, igual que valida el front.
PinCaja = Annotated[str, StringConstraints(pattern=r"^\d{4}$")]


class UserCreateRequest(BaseModel):
    email: EmailUsuario
    full_name: NombreRequerido
    apellidos: str | None = None
    telefono: str | None = Field(default=None, max_length=20)
    password: PasswordNueva
    role: str
    branch_id: UUID | None = None
    pin: PinCaja | None = None


class UserUpdateRequest(BaseModel):
    email: EmailUsuario
    full_name: NombreRequerido
    apellidos: str | None = None
    telefono: str | None = Field(default=None, max_length=20)
    role: str
    branch_id: UUID | None = None
    # None (o "") = no cambiar; si viene, mínimo PASSWORD_MIN_LENGTH (M2).
    password: Annotated[PasswordNueva | None, BeforeValidator(_vacio_a_none)] = None
    is_active: bool | None = None  # None = no cambiar
    pin: PinCaja | None = None  # None = no cambiar


class UserResponse(BaseModel):
    id: UUID
    full_name: str
    apellidos: str | None = None
    telefono: str | None = None
    email: str
    role: str
    branch_id: UUID | None
    is_active: bool
    ultimo_acceso: datetime | None = None
    tiene_pin: bool = False
    # Sucursales activas del usuario. Para un Administrador (que se asigna
    # desde la sucursal y no trae `branch_id`) es la única forma de saber
    # dónde administra; para los demás roles coincide con `branch_id`.
    sucursales_ids: list[UUID] = Field(default_factory=list)


class CambiarMiPinRequest(BaseModel):
    """PUT /usuarios/me/pin — el usuario cambia su propio PIN de caja.

    `actual` acepta el PIN vigente o, si el usuario aún no tiene PIN
    configurado, su contraseña (decisión C1: "mientras el usuario no tenga
    PIN, se acepta su contraseña, igual que en el cierre").
    """

    actual: str = Field(..., min_length=1)
    pin_nuevo: PinCaja


class CambiarMiPinResponse(BaseModel):
    ok: bool
    tiene_pin: bool = True


class CambiarMiPasswordRequest(BaseModel):
    """PUT /usuarios/me/password — el usuario cambia su propia contraseña."""

    actual: str = Field(..., min_length=1)
    nueva: PasswordNueva
