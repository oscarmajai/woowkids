from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ReservacionProductosBase(BaseModel):
    reservacion_id: UUID
    producto_id: UUID
    cantidad: int = Field(..., ge=1)
    precio_unitario: Decimal = Field(..., ge=0)
    notas: str | None = None


class ReservacionProductosCreate(BaseModel):
    """Agrega un producto a una reservación. El precio sale del catálogo;
    `precio_unitario` se acepta por compatibilidad pero se ignora (N11). El
    total de la reservación se recalcula; si se manda `precio_total` (lo que
    espera el cliente) y no coincide, 409."""

    reservacion_id: UUID
    producto_id: UUID
    cantidad: int = Field(..., ge=1)
    precio_unitario: Decimal | None = Field(None, ge=0)
    notas: str | None = None
    precio_total: Decimal | None = Field(None, ge=0)


class ReservacionProductosUpdate(BaseModel):
    """Cambia cantidad o notas; el precio se vuelve a tomar del catálogo
    (`precio_unitario` se ignora, N11). `precio_total`, igual que en el alta."""

    cantidad: int | None = Field(None, ge=1)
    precio_unitario: Decimal | None = Field(None, ge=0)
    notas: str | None = None
    precio_total: Decimal | None = Field(None, ge=0)


class ReservacionProductosOut(ReservacionProductosBase):
    id: UUID
    subtotal: Decimal
    creado: datetime
    creado_por: UUID | None

    model_config = {"from_attributes": True}
