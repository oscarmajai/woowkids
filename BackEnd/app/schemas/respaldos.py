from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RespaldoOut(BaseModel):
    inicio: datetime
    fin: datetime | None
    exitoso: bool
    motivo: str
    nombre: str | None
    tamano_bd: int | None
    archivos: int | None
    error: str | None


class EstadoRespaldosOut(BaseModel):
    """GET /api/sistema/respaldos — para avisar al AdministradorSistema."""

    ultimo_exitoso: RespaldoOut | None
    ultimo_intento: RespaldoOut | None
    # True si nunca hubo un respaldo exitoso, el último intento falló o el
    # último exitoso tiene más de HORAS_ALERTA horas.
    alerta: bool
    mensaje: str | None
