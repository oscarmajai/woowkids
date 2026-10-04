from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.limites_inventario import DECIMALES_CANTIDAD, MAX_CANTIDAD
from app.schemas.textos import Nombre100


class PresentacionCrear(BaseModel):
    nombre: Nombre100
    equivalencia_base: Decimal = Field(
        ..., gt=0, le=MAX_CANTIDAD, decimal_places=DECIMALES_CANTIDAD
    )


class PresentacionUpdate(BaseModel):
    nombre: Nombre100 | None = None
    equivalencia_base: Decimal | None = Field(
        None, gt=0, le=MAX_CANTIDAD, decimal_places=DECIMALES_CANTIDAD
    )
    activo: bool | None = None


class PresentacionOut(BaseModel):
    id: UUID
    insumo_id: UUID
    nombre: str
    equivalencia_base: Decimal
    activo: bool
    creado: datetime | None
    creado_por: UUID | None
    modificado: datetime | None
    modificado_por: UUID | None

    model_config = {"from_attributes": True}
