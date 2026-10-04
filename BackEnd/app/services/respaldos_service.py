"""Estado de los respaldos automáticos (los hace scripts/respaldos.py, fuera
de la API) para avisar al AdministradorSistema si fallan o dejan de hacerse."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import asyncpg

from app.repositories import respaldos_repository
from app.schemas.respaldos import EstadoRespaldosOut, RespaldoOut

# El respaldo programado corre cada 6 h por defecto y al encender el equipo; dos
# días sin uno exitoso (p. ej. un fin de semana apagado no llega) es una falla.
HORAS_ALERTA = 48


async def estado(conn: asyncpg.Connection) -> EstadoRespaldosOut:
    exitoso = await respaldos_repository.ultimo(conn, exitoso=True)
    intento = await respaldos_repository.ultimo(conn)
    mensaje: str | None = None
    if exitoso is None:
        mensaje = "Todavía no hay ningún respaldo automático de la información."
    elif intento is not None and not intento["exitoso"]:
        mensaje = "El último respaldo automático falló. Revisa el registro del servidor."
    elif datetime.now(UTC) - exitoso["inicio"] > timedelta(hours=HORAS_ALERTA):
        mensaje = f"No se ha hecho un respaldo automático en más de {HORAS_ALERTA} horas."
    return EstadoRespaldosOut(
        ultimo_exitoso=RespaldoOut.model_validate(exitoso) if exitoso else None,
        ultimo_intento=RespaldoOut.model_validate(intento) if intento else None,
        alerta=mensaje is not None,
        mensaje=mensaje,
    )
