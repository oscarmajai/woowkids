from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.textos import Nombre150


class ProveedorBase(BaseModel):
    nombre: Nombre150
    contacto_nombre: str | None = Field(None, max_length=150)
    telefono: str | None = Field(None, max_length=20)
    email: EmailStr | None = None
    notas: str | None = None
    # RFC mexicano: 12 caracteres (moral) o 13 (física).
    rfc: str | None = Field(None, min_length=12, max_length=13)
    dias_entrega: int | None = Field(None, ge=0)


class ProveedorCrear(ProveedorBase):
    sucursal_id: UUID


class ProveedorUpdate(BaseModel):
    nombre: Nombre150 | None = None
    contacto_nombre: str | None = Field(None, max_length=150)
    telefono: str | None = Field(None, max_length=20)
    email: EmailStr | None = None
    notas: str | None = None
    rfc: str | None = Field(None, min_length=12, max_length=13)
    dias_entrega: int | None = Field(None, ge=0)
    activo: bool | None = None


class ProveedorOut(ProveedorBase):
    id: UUID
    sucursal_id: UUID
    activo: bool
    creado: datetime | None
    creado_por: UUID | None
    modificado: datetime | None
    modificado_por: UUID | None

    model_config = {"from_attributes": True}
