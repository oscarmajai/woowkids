"""
app/schemas/horarios_cajas.py
Schemas Pydantic para los CRUDs administrativos de horarios (turnos) y cajas.
"""

from __future__ import annotations

from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, field_validator

# 0 = lunes ... 6 = domingo; None = todos los días.
DiasSemana = list[int] | None


def _validar_dias(dias: DiasSemana) -> DiasSemana:
    if dias is not None and any(d < 0 or d > 6 for d in dias):
        raise ValueError("Cada día debe estar entre 0 (lunes) y 6 (domingo).")
    return dias


def _validar_hora(valor: str | None) -> str | None:
    """M3: una hora mal escrita ("xx", "25:00") reventaba con 500 en el
    repositorio; ahora es un 422 de validación."""
    if valor is None:
        return None
    try:
        time.fromisoformat(valor)
    except ValueError:
        raise ValueError("Hora inválida: usa el formato HH:MM (de 00:00 a 23:59).") from None
    return valor


# ── Horarios (turnos de trabajo) ──────────────────────────────────────────────


class HorarioCreate(BaseModel):
    nombre: str
    hora_inicio: str  # "HH:MM"
    hora_fin: str  # "HH:MM"
    dias: DiasSemana = None
    # M19: sucursal del horario. Roles con sucursal fija: solo la suya (es la
    # que se usa si no viene). AdministradorSistema: la indicada, la del
    # selector o, sin ninguna, un horario global.
    sucursal_id: UUID | None = None

    @field_validator("dias")
    @classmethod
    def _check_dias(cls, v: DiasSemana) -> DiasSemana:
        return _validar_dias(v)

    @field_validator("hora_inicio", "hora_fin")
    @classmethod
    def _check_hora(cls, v: str) -> str:
        return _validar_hora(v) or v


class HorarioUpdate(BaseModel):
    nombre: str | None = None
    hora_inicio: str | None = None
    hora_fin: str | None = None
    activo: bool | None = None
    dias: DiasSemana = None

    @field_validator("dias")
    @classmethod
    def _check_dias(cls, v: DiasSemana) -> DiasSemana:
        return _validar_dias(v)

    @field_validator("hora_inicio", "hora_fin")
    @classmethod
    def _check_hora(cls, v: str | None) -> str | None:
        return _validar_hora(v)


class HorarioResponse(BaseModel):
    id: str
    nombre: str
    hora_inicio: str
    hora_fin: str
    activo: bool
    dias: DiasSemana = None
    # M19: None = horario global (todas las sucursales).
    sucursal_id: str | None = None


# ── Cajas físicas (gestión administrativa) ────────────────────────────────────


class TurnoActualCaja(BaseModel):
    """Turno abierto en este momento sobre esa caja física."""

    id: str
    cajero: str
    apertura: datetime


class CajaAdminCreate(BaseModel):
    nombre: str
    numero: int
    impresora: str | None = None


class CajaAdminUpdate(BaseModel):
    nombre: str | None = None
    numero: int | None = None
    activo: bool | None = None
    impresora: str | None = None


class CajaAdminResponse(BaseModel):
    id: str
    nombre: str
    numero: int
    activo: bool
    impresora: str | None = None
    turno_actual: TurnoActualCaja | None = None
