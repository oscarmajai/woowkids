from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ReservacionExtrasBase(BaseModel):
    reservacion_id: UUID
    extra_id: UUID
    cantidad: int = Field(..., ge=1)
    precio_unitario: Decimal = Field(..., ge=0)


class ReservacionExtrasCreate(BaseModel):
    """Agrega un extra a una reservación. El precio sale del catálogo y la
    cantidad de la unidad del extra (por persona = invitados, por hora = horas
    del evento, por evento = 1); `cantidad` y `precio_unitario` se aceptan por
    compatibilidad pero se ignoran (N11/M15). El total de la reservación se
    recalcula; si se manda `precio_total` (lo que espera el cliente) y no
    coincide, 409."""

    reservacion_id: UUID
    extra_id: UUID
    cantidad: int | None = Field(None, ge=1)
    precio_unitario: Decimal | None = Field(None, ge=0)
    precio_total: Decimal | None = Field(None, ge=0)


class ReservacionExtrasUpdate(BaseModel):
    """Vuelve a tomar el precio del catálogo y la cantidad de la unidad del
    extra; `cantidad` y `precio_unitario` se ignoran (N11). `precio_total`,
    igual que en el alta."""

    cantidad: int | None = Field(None, ge=1)
    precio_unitario: Decimal | None = Field(None, ge=0)
    precio_total: Decimal | None = Field(None, ge=0)


class ReservacionExtrasOut(ReservacionExtrasBase):
    id: UUID
    subtotal: Decimal
    creado: datetime
    creado_por: UUID | None

    model_config = {"from_attributes": True}
