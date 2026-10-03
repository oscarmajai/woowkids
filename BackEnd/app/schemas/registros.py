import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.ninos import NinoIn
from app.schemas.pagos import PagoIn
from app.schemas.producto import TramoEstanciaSchema
from app.schemas.tutores import TutorIn


class DetalleIn(BaseModel):
    nino: NinoIn
    productoId: UUID | None = None  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    # N6: horas contratadas; con 0 se registraba una estancia de 0 h (y $0).
    # En modo evento el servidor toma las horas del evento y la ignora.
    cantidad: int = Field(default=1, ge=1)
    pulseraId: UUID  # noqa: N815 — camelCase requerido por el contrato JSON del frontend


class OnboardingRequest(BaseModel):
    sucursalId: UUID  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    tutor: TutorIn
    nombreSegundoTutor: str | None = None  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    parentesco: str
    detalles: list[DetalleIn]
    pagos: list[PagoIn] | None = None
    cambio: Decimal = Field(Decimal("0"), ge=0)
    reservacionId: UUID | None = None  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    puntosARedimir: int = Field(default=0, ge=0)  # noqa: N815 — camelCase requerido por el contrato JSON del frontend


class OnboardingResponse(BaseModel):
    registroId: UUID  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    total: float
    pagado: float
    estado: str
    advertenciaEfectivo: str | None = None  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    # A17 — código opaco del QR del portal de padres, en claro solo en esta
    # respuesta (en BD queda su sha256). Caduca a las 24 h o al checkout del
    # último niño del registro.
    codigoAccesoPadres: str  # noqa: N815 — camelCase requerido por el contrato JSON del frontend


class NinoComprobanteResponse(BaseModel):
    nombre: str
    edad: int
    # M26: notas / alergias del niño, para que salgan en el comprobante.
    notas: str | None = None
    pulsera: str
    horas: int
    salidaEsperada: str  # noqa: N815 — camelCase requerido por el contrato JSON del frontend


class ComprobanteEstanciaResponse(BaseModel):
    """N5 — datos para reimprimir el comprobante de un registro activo, con un
    código nuevo del portal de padres (el anterior queda revocado)."""

    registroId: UUID  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    codigoAccesoPadres: str  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    sucursal: str
    cajero: str | None = None
    tutor: str
    telefono: str
    entrada: str
    total: float
    ninos: list[NinoComprobanteResponse]


class CheckoutRequest(BaseModel):
    pagos: list[PagoIn] = []


class CheckoutResponse(BaseModel):
    detalleId: str  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    registroId: str  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    horasExtra: int  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    totalExtra: float  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    ninosRestantes: int  # noqa: N815 — camelCase requerido por el contrato JSON del frontend


class CotizacionCheckoutResponse(BaseModel):
    detalleId: str  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    horasExtra: int  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    totalExtra: float  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    cotizadoEn: str  # noqa: N815 — camelCase requerido por el contrato JSON del frontend


class ProductoResponse(BaseModel):
    id: UUID
    nombre: str
    precioUnitario: float  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    descripcion: str | None


class DetalleActivoResponse(BaseModel):
    registroId: UUID  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    nombreSegundoTutor: str | None = None  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    detalleId: UUID  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    nino: str
    notas: str | None
    edad: int
    tutor: str
    telefono: str
    parentesco: str
    pulsera: str
    minutosPagados: float  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    minutosTranscurridos: float  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    horaEntrada: str  # noqa: N815 — camelCase requerido por el contrato JSON del frontend
    cargoExtra: float = 0.0  # noqa: N815 — camelCase requerido por el contrato JSON del frontend


class ProductoEstanciaResponse(BaseModel):
    id: UUID
    config_estancia: list[TramoEstanciaSchema] = []

    model_config = ConfigDict(from_attributes=True)

    @field_validator("config_estancia", mode="before")
    @classmethod
    def parsear_config_estancia(cls, v: Any) -> Any:
        if v is None:
            return []

        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return []
        return v
