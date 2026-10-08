"""Máquina de estados de reservación y abonos parciales contra un PostgreSQL
de verdad.

Una reservación cancelada no pasa a completada ni pierde su nota de
cancelación, ninguna se completa antes del evento y los abonos parciales
mueven el saldo. Requiere `TEST_DATABASE_URL` (BD desechable con
`sql/schema_maestro.sql`); sin ella se salta. Cada test crea y borra sus datos.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import time, timedelta
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from app.repositories import reservaciones_repository
from app.schemas.pagos_reservacion import PagosReservacionCreate
from app.schemas.reservaciones import ReservacionesUpdate
from app.services import pagos_reservacion, reservaciones
from fastapi import HTTPException

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL no está definida")

TOTAL = Decimal("7615.00")
NOTA_CANCELACION = "Cancelada automáticamente: no se liquidó una semana antes del evento."


@pytest_asyncio.fixture
async def pg() -> AsyncIterator[asyncpg.Connection]:
    assert DSN
    conn = await asyncpg.connect(DSN)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def escenario(pg: asyncpg.Connection) -> AsyncIterator[dict[str, Any]]:
    """Sucursal con paquete, tipo de evento, cajera, caja abierta y métodos de pago."""
    ids = {k: uuid.uuid4() for k in ("sucursal", "tipo", "paquete", "usuario")}
    ids.update({k: uuid.uuid4() for k in ("caja", "turno", "apertura")})
    await pg.execute(
        "INSERT INTO sucursales (id, nombre) VALUES ($1, $2)",
        ids["sucursal"],
        f"Prueba estados {ids['sucursal']}",
    )
    await pg.execute(
        "INSERT INTO tipos_evento (id, nombre, sucursal_id) VALUES ($1, 'Cumpleaños', $2)",
        ids["tipo"],
        ids["sucursal"],
    )
    await pg.execute(
        """INSERT INTO paquetes (id, sucursal_id, nombre, min_invitados, max_invitados,
               precio_base, precio_hora_pulsera, anticipo_porcentaje)
           VALUES ($1, $2, 'Básica', 5, 30, 5000, 0, 30)""",
        ids["paquete"],
        ids["sucursal"],
    )
    await pg.execute(
        """INSERT INTO usuarios (id, email, password_hash, nombre_completo, rol)
           VALUES ($1, $2, 'x', 'Cajera Prueba', 3)""",
        ids["usuario"],
        f"{ids['usuario']}@prueba.dev",
    )
    await pg.execute(
        "INSERT INTO cajas (id, sucursal_id, codigo, nombre) VALUES ($1, $2, 'C01', 'CAJA 01')",
        ids["caja"],
        ids["sucursal"],
    )
    await pg.execute(
        "INSERT INTO turnos (id, nombre, hora_inicio, hora_fin) VALUES ($1, $2, '00:00', '23:59')",
        ids["turno"],
        f"Prueba {ids['turno']}"[:50],
    )
    await pg.execute(
        """INSERT INTO apertura_caja (id, caja_id, cajero_id, turno_id, fondo_inicial, estado)
           VALUES ($1, $2, $3, $4, 1000, 'ABIERTA')""",
        ids["apertura"],
        ids["caja"],
        ids["usuario"],
        ids["turno"],
    )
    efectivo = await pg.fetchval("SELECT id FROM metodos_pago WHERE tipo = 'E' LIMIT 1")
    hoy = await reservaciones_repository.hoy_en_sucursal(pg, ids["sucursal"])
    assert hoy is not None
    yield {**ids, "efectivo": efectivo, "hoy": hoy}

    reservas = "SELECT id FROM reservaciones WHERE sucursal_id = $1"
    await pg.execute(
        "DELETE FROM movimientos_caja "
        f"WHERE apertura_caja_id = $2 OR referencia_id IN ({reservas})",
        ids["sucursal"],
        ids["apertura"],
    )
    await pg.execute(
        f"DELETE FROM pagos_reservacion WHERE reservacion_id IN ({reservas})", ids["sucursal"]
    )
    await pg.execute("DELETE FROM reservaciones WHERE sucursal_id = $1", ids["sucursal"])
    await pg.execute("DELETE FROM apertura_caja WHERE id = $1", ids["apertura"])
    await pg.execute("DELETE FROM turnos WHERE id = $1", ids["turno"])
    await pg.execute("DELETE FROM cajas WHERE id = $1", ids["caja"])
    await pg.execute("DELETE FROM usuarios WHERE id = $1", ids["usuario"])
    await pg.execute("DELETE FROM paquetes WHERE id = $1", ids["paquete"])
    await pg.execute("DELETE FROM tipos_evento WHERE id = $1", ids["tipo"])
    await pg.execute("DELETE FROM sucursales WHERE id = $1", ids["sucursal"])


async def _reservacion(
    pg: asyncpg.Connection,
    e: dict[str, Any],
    *,
    dias: int,
    estado: str = "confirmada",
    pagado: Decimal = TOTAL,
    notas: str | None = None,
) -> uuid.UUID:
    """Inserta una reservación de 11:00 a 14:00 a `dias` del hoy local de la
    sucursal (negativo = ya ocurrió)."""
    return await pg.fetchval(
        """INSERT INTO reservaciones (sucursal_id, tipo_evento_id, paquete_id, nombre_cliente,
               telefono_cliente, fecha_evento, hora_inicio, hora_fin, numero_personas,
               precio_base, precio_total, anticipo, monto_pagado, estado, notas)
           VALUES ($1, $2, $3, 'Gabriela', '3312345678', $4, '11:00', '14:00', 12,
                   5000, $5, $6, $6, $7, $8)
           RETURNING id""",
        e["sucursal"],
        e["tipo"],
        e["paquete"],
        e["hoy"] + timedelta(days=dias),
        TOTAL,
        pagado,
        estado,
        notas,
    )


async def _fila(pg: asyncpg.Connection, rid: uuid.UUID) -> asyncpg.Record:
    return await pg.fetchrow(
        "SELECT estado, notas, monto_pagado, saldo_pendiente, modificado_por "
        "FROM reservaciones WHERE id = $1",
        rid,
    )


async def test_cancelada_no_pasa_a_completada_ni_pierde_su_nota(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    rid = await _reservacion(pg, e, dias=-1, estado="cancelada", notas=NOTA_CANCELACION)

    with pytest.raises(HTTPException) as exc:
        await reservaciones.cerrar(pg, rid, "Cierre normal", e["usuario"])
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await reservaciones.actualizar(
            pg, rid, ReservacionesUpdate(estado="completada", notas="Cierre")
        )
    assert exc.value.status_code == 409

    fila = await _fila(pg, rid)
    assert fila["estado"] == "cancelada"
    assert fila["notas"] == NOTA_CANCELACION


async def test_completar_antes_del_evento_se_rechaza(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    rid = await _reservacion(pg, e, dias=1)

    with pytest.raises(HTTPException) as exc:
        await reservaciones.cerrar(pg, rid, None, e["usuario"])
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "EVENTO_NO_INICIADO"
    assert (await _fila(pg, rid))["estado"] == "confirmada"


async def test_abono_parcial_actualiza_monto_pagado_y_bloquea_el_cierre_con_saldo(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    # El evento fue ayer y solo se dio el anticipo.
    rid = await _reservacion(pg, e, dias=-1, pagado=Decimal("2285"), notas="Sin nuez")

    # Abono parcial de $2,000: monto_pagado y saldo se mueven.
    await pagos_reservacion.crear(
        pg,
        PagosReservacionCreate(reservacion_id=rid, metodo_pago_id=e["efectivo"], monto=2000),
        e["usuario"],
        str(e["apertura"]),
    )
    fila = await _fila(pg, rid)
    # monto_pagado se recalcula desde los pagos registrados (el anticipo
    # insertado a mano no tiene pago detrás): solo cuenta el abono.
    assert fila["monto_pagado"] == Decimal("2000.00")
    assert fila["saldo_pendiente"] == TOTAL - Decimal("2000.00")

    # Con saldo no se cierra.
    with pytest.raises(HTTPException) as exc:
        await reservaciones.cerrar(pg, rid, None, e["usuario"])
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "SALDO_PENDIENTE"
    assert (await _fila(pg, rid))["estado"] == "confirmada"

    # Se liquida el resto y ahora sí cierra, conservando las notas previas.
    await pagos_reservacion.crear(
        pg,
        PagosReservacionCreate(
            reservacion_id=rid, metodo_pago_id=e["efectivo"], monto=TOTAL - Decimal("2000")
        ),
        e["usuario"],
        str(e["apertura"]),
    )
    cerrada = await reservaciones.cerrar(pg, rid, "Sin incidencias", e["usuario"])
    assert cerrada.estado == "completada"
    fila = await _fila(pg, rid)
    assert fila["saldo_pendiente"] == Decimal("0.00")
    assert fila["notas"] == "Sin nuez\nCierre del evento: Sin incidencias"
    assert fila["modificado_por"] == e["usuario"]

    # Completada es terminal: ni se reabre ni se edita.
    with pytest.raises(HTTPException) as exc:
        await reservaciones.actualizar(pg, rid, ReservacionesUpdate(estado="confirmada"))
    assert exc.value.status_code == 409


async def test_patch_fuera_de_plazo_no_cambia_invitados(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    rid = await _reservacion(pg, e, dias=5)
    with pytest.raises(HTTPException) as exc:
        await reservaciones.actualizar(pg, rid, ReservacionesUpdate(numero_personas=15))
    assert exc.value.detail["code"] == "FUERA_DE_PLAZO"


async def test_scheduler_no_recancela_una_reservacion_completada(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    rid = await _reservacion(pg, e, dias=2, estado="completada", notas="Cerrada")
    await reservaciones_repository.cancelar_por_falta_de_pago(pg, rid, "Motivo")
    fila = await _fila(pg, rid)
    assert fila["estado"] == "completada"
    assert fila["notas"] == "Cerrada"


async def test_tiempo_local_de_la_sucursal_define_el_inicio(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    """El inicio se compara con la hora local de la sucursal: un evento de hoy
    a las 00:00 locales ya empezó aunque en UTC todavía sea "ayer"."""
    e = escenario
    rid = await pg.fetchval(
        """INSERT INTO reservaciones (sucursal_id, tipo_evento_id, paquete_id, nombre_cliente,
               telefono_cliente, fecha_evento, hora_inicio, hora_fin, numero_personas,
               precio_base, precio_total, monto_pagado, estado)
           VALUES ($1, $2, $3, 'Cliente', '3312345678', $4, $5, '23:59', 12,
                   5000, $6, $6, 'confirmada')
           RETURNING id""",
        e["sucursal"],
        e["tipo"],
        e["paquete"],
        e["hoy"],
        time(0, 0),
        TOTAL,
    )
    cerrada = await reservaciones.cerrar(pg, rid, None, e["usuario"])
    assert cerrada.estado == "completada"
