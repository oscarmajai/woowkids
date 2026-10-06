import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import UUID4, BaseModel, Field, field_validator


class EstadoComanda(str, Enum):
    PENDIENTE = "P"
    EN_PROCESO = "E"
    LISTO = "L"
    ENTREGADO = "T"
    CANCELADO = "C"


# Esquema para los productos dentro de la comanda
class DetalleCreate(BaseModel):
    id: str = Field(..., alias="producto_id")
    nombre: str
    cantidad: int
    precio_unitario: Decimal
    subtotal: Decimal
    notas_especiales: str | None = None
    nombre_combo_padre: str | None = None
    es_hijo_de: str | None = None
    es_hijo_combo: bool = False
    id_combo_padre: str | None = None

    class Config:
        populate_by_name = True


# Esquema para recibir la creación de la comanda
class ComandaCreate(BaseModel):
    notas_generales: str | None = None
    estado_actual: EstadoComanda = EstadoComanda.PENDIENTE
    detalles_comanda: list[DetalleCreate]
    # max_length=10 coincide con comandas.ticket_numero VARCHAR(10) en BD.
    ticket_numero: str = Field(..., max_length=10)
    total_final: Decimal
    sucursal_id: uuid.UUID | None = None
    nombre_cliente: str | None = None
    # Mesa del pedido, opcional. max_length=20 coincide con
    # comandas.mesa VARCHAR(20) en BD.
    mesa: str | None = Field(default=None, max_length=20)


# PATCH /comandas/{id}/estado. `estado_actual` es el enum, así que un valor
# fuera de P/E/L/T/C ("X", "") es 422 antes de llegar al service.
class CambioEstadoRequest(BaseModel):
    estado_actual: EstadoComanda
    motivo_cancelacion: str | None = None
    # Token de un solo uso de POST /turnos-caja/validar-pin-admin. Solo se
    # exige para cancelar una comanda con pagos.
    token_pin_admin: str | None = None


# POST /comandas/{id}/devolucion: devolver el dinero de una comanda ya
# entregada, sin regresar su stock. Mismo flujo de autorización que cancelar
# una comanda cobrada: sin token responde 403 AUTORIZACION_ADMIN_REQUERIDA con
# el turno_id para POST /turnos-caja/validar-pin-admin.
class DevolucionEntregadaRequest(BaseModel):
    motivo: str = Field(..., min_length=1, max_length=500)
    token_pin_admin: str | None = None


# Esquema para cancelación parcial (eliminar productos de una comanda Pendiente)
class ComandaModifyRequest(BaseModel):
    detalles_ids_a_eliminar: list[str] = Field(..., min_length=1)
    motivo_cancelacion: str | None = None
    # Control optimista. El `modificado` que devolvió GET
    # /pagos/detalles/comanda/{id}; si la comanda cambió desde entonces, 409
    # COMANDA_MODIFICADA sin tocar nada. Opcional por compatibilidad.
    modificado_esperado: datetime | None = None

    @field_validator("detalles_ids_a_eliminar")
    @classmethod
    def _validate_uuids(cls, v: list[str]) -> list[str]:
        validos: list[str] = []
        for raw in v:
            if not raw or not raw.strip():
                continue
            try:
                uuid.UUID(raw.strip())
            except ValueError as exc:
                raise ValueError(
                    f"ID de detalle inválido: '{raw}'. Se esperaba un UUID válido."
                ) from exc
            validos.append(raw.strip())
        if not validos:
            raise ValueError("No se proporcionó ningún ID de detalle válido.")
        return validos


# Esquema de respuesta
class Comanda(BaseModel):
    id: UUID4
    ticket_numero: str
    total_final: Decimal
    sucursal_id: UUID4
    estado_actual: EstadoComanda
    fecha_hora: datetime
    mesa: str | None = None

    class Config:
        from_attributes = True
