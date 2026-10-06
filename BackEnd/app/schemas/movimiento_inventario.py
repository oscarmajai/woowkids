from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.limites_inventario import DECIMALES_CANTIDAD, MAX_CANTIDAD


class MovimientoManualCreate(BaseModel):
    tipo: Literal["E", "M"]  # E entrada manual | M merma
    # Acotada a movimientos_inventario.cantidad numeric(12,3), para que valores
    # como 1e10 o 0.0004 no respondan 500.
    cantidad: Decimal = Field(..., gt=0, le=MAX_CANTIDAD, decimal_places=DECIMALES_CANTIDAD)
    notas: str | None = None


class ConteoFisicoCreate(BaseModel):
    """Conteo físico: el usuario captura el stock real que ve en el anaquel y el
    sistema calcula el ajuste (entrada si sobra, merma si falta)."""

    stock_contado: Decimal = Field(..., ge=0, le=MAX_CANTIDAD, decimal_places=DECIMALES_CANTIDAD)
    notas: str | None = None


class CogsRenglonOut(BaseModel):
    insumo_id: UUID
    insumo_nombre: str
    cantidad_salida: Decimal
    costo_total: Decimal

    model_config = {"from_attributes": True}


class ResumenCogsOut(BaseModel):
    """KPIs agregados del reporte de costo de ventas.

    `margen` = ventas - costo de ventas - merma. `merma` = merma manual +
    faltante de conteos físicos, con su desglose."""

    ventas_totales: Decimal
    costo_ventas: Decimal
    margen: Decimal
    merma: Decimal
    merma_manual: Decimal = Decimal("0")
    merma_conteo: Decimal = Decimal("0")

    model_config = {"from_attributes": True}


class MovimientoInventarioOut(BaseModel):
    id: UUID
    sucursal_id: UUID
    insumo_id: UUID
    insumo_nombre: str
    tipo: str
    cantidad: Decimal
    stock_resultante: Decimal
    motivo: str
    referencia_id: UUID | None
    notas: str | None
    costo_total: Decimal | None
    creado: datetime
    creado_por: UUID | None
    creado_por_nombre: str | None = None

    model_config = {"from_attributes": True}
