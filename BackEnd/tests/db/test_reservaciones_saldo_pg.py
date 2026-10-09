"""Saldo real de reservaciones, scheduler y precio del servidor contra un
PostgreSQL de verdad.

Requiere `TEST_DATABASE_URL` apuntando a una BD DESECHABLE con
`sql/schema_maestro.sql` cargado (incluye la migración 075); sin esa variable
se salta. Cada test crea su propia sucursal, paquete, caja y turno con ids
nuevos y los borra al terminar.

    docker run -d --name wk-pg -e POSTGRES_USER=dev -e POSTGRES_PASSWORD=dev \\
        -e POSTGRES_DB=woowkids -p 0:5432 postgres:16-alpine
    psql ... < sql/schema_maestro.sql
    TEST_DATABASE_URL=postgresql://dev:dev@localhost:<puerto>/woowkids \\
        pytest tests/db/test_reservaciones_saldo_pg.py
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import date, time, timedelta
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from app.repositories import reservaciones_repository
from app.schemas.pagos_reservacion import (
    PagoReservacionItem,
    PagosReservacionCompletarRequest,
    PagosReservacionCreate,
)
from app.schemas.reservaciones import ReservacionesCrear
from app.schemas.reservaciones_completa import (
    ReservacionCompletaExtraItem,
    ReservacionCompletaRequest,
)
from app.services import pagos_reservacion, reservaciones, reservaciones_vencidas_scheduler
from fastapi import HTTPException

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL no está definida")


@pytest_asyncio.fixture
async def pg() -> AsyncIterator[asyncpg.Connection]:
    assert DSN
    conn = await asyncpg.connect(DSN)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def escenario(pg: asyncpg.Connection) -> AsyncIterator[dict[str, Any]]:
    """Sucursal con paquete Premium (10-30 invitados, $6,900 + $60/h por
    pulsera, anticipo 40 %), un extra, caja abierta y métodos de pago."""
    ids = {k: uuid.uuid4() for k in ("sucursal", "tipo", "paquete", "extra", "usuario")}
    ids.update({k: uuid.uuid4() for k in ("caja", "turno", "apertura")})
    await pg.execute(
        "INSERT INTO sucursales (id, nombre) VALUES ($1, $2)",
        ids["sucursal"],
        f"Prueba saldo {ids['sucursal']}",
    )
    await pg.execute(
        "INSERT INTO tipos_evento (id, nombre, sucursal_id) VALUES ($1, 'Cumpleaños', $2)",
        ids["tipo"],
        ids["sucursal"],
    )
    await pg.execute(
        """INSERT INTO paquetes (id, sucursal_id, nombre, min_invitados, max_invitados,
               precio_base, precio_hora_pulsera, anticipo_porcentaje)
           VALUES ($1, $2, 'Premium', 10, 30, 6900, 60, 40)""",
        ids["paquete"],
        ids["sucursal"],
    )
    # Por evento: se cobra una vez. Los extras por hora/persona se
    # prueban en test_reservacion_partidas_pg.py.
    await pg.execute(
        """INSERT INTO extras (id, sucursal_id, nombre, precio, unidad)
           VALUES ($1, $2, 'Animador adicional', 350, 'evento')""",
        ids["extra"],
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
    tarjeta = await pg.fetchval("SELECT id FROM metodos_pago WHERE tipo = 'T' LIMIT 1")
    hoy = await reservaciones_repository.hoy_en_sucursal(pg, ids["sucursal"])
    assert hoy is not None
    yield {**ids, "efectivo": efectivo, "tarjeta": tarjeta, "hoy": hoy}

    reservas = "SELECT id FROM reservaciones WHERE sucursal_id = $1"
    await pg.execute(
        "DELETE FROM movimientos_caja "
        f"WHERE apertura_caja_id = $2 OR referencia_id IN ({reservas})",
        ids["sucursal"],
        ids["apertura"],
    )
    for tabla in ("pagos_reservacion", "reservacion_extras", "reservacion_productos"):
        await pg.execute(
            f"DELETE FROM {tabla} WHERE reservacion_id IN ({reservas})", ids["sucursal"]
        )
    await pg.execute("DELETE FROM reservaciones WHERE sucursal_id = $1", ids["sucursal"])
    await pg.execute("DELETE FROM apertura_caja WHERE id = $1", ids["apertura"])
    await pg.execute("DELETE FROM turnos WHERE id = $1", ids["turno"])
    await pg.execute("DELETE FROM cajas WHERE id = $1", ids["caja"])
    await pg.execute("DELETE FROM usuarios WHERE id = $1", ids["usuario"])
    await pg.execute("DELETE FROM extras WHERE id = $1", ids["extra"])
    await pg.execute("DELETE FROM paquetes WHERE id = $1", ids["paquete"])
    await pg.execute("DELETE FROM tipos_evento WHERE id = $1", ids["tipo"])
    await pg.execute("DELETE FROM sucursales WHERE id = $1", ids["sucursal"])


# Premium, 20 niños, 11:00-15:00 (4 h) + animador: 6900 + 4800 + 350 = 12050.
TOTAL = Decimal("12050.00")


def _alta(
    e: dict[str, Any], dias: int, pagos: list[tuple[Any, str]], **cambios: Any
) -> ReservacionCompletaRequest:
    datos: dict[str, Any] = {
        "sucursal_id": e["sucursal"],
        "tipo_evento_id": e["tipo"],
        "paquete_id": e["paquete"],
        "nombre_cliente": "Cliente Prueba",
        "telefono_cliente": "3312345678",
        "fecha_evento": e["hoy"] + timedelta(days=dias),
        "hora_inicio": time(11, 0),
        "hora_fin": time(15, 0),
        "numero_personas": 20,
        "precio_base": Decimal("6900"),
        "precio_total": TOTAL,
    }
    datos.update(cambios)
    return ReservacionCompletaRequest(
        reservacion=ReservacionesCrear(**datos),
        extras=[ReservacionCompletaExtraItem(extra_id=e["extra"], precio_unitario=Decimal(1))],
        pagos=[PagoReservacionItem(metodo_pago_id=m, monto=Decimal(x)) for m, x in pagos],
        cambio=Decimal(0),
    )


async def _saldo(pg: asyncpg.Connection, reservacion_id: uuid.UUID) -> asyncpg.Record:
    return await pg.fetchrow(
        "SELECT anticipo, monto_pagado, saldo_pendiente, estado FROM reservaciones WHERE id = $1",
        reservacion_id,
    )


async def test_saldo_refleja_anticipo_abonos_y_cambio(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    # Anticipo 40 % = 4820: entrega $5,000 en efectivo y se le devuelven $180.
    body = _alta(e, 30, [(e["efectivo"], "5000")])
    body.cambio = Decimal("180")
    alta = await reservaciones.crear_completa(pg, body, e["usuario"], str(e["apertura"]))
    rid = alta.reservacion.id
    assert alta.reservacion.estado == "confirmada"
    assert alta.reservacion.saldo_pendiente == TOTAL - Decimal("4820")

    # Abono parcial de $2,000: mueve el saldo.
    await pagos_reservacion.crear(
        pg,
        PagosReservacionCreate(reservacion_id=rid, metodo_pago_id=e["tarjeta"], monto=2000),
        e["usuario"],
        str(e["apertura"]),
    )
    fila = await _saldo(pg, rid)
    assert fila["anticipo"] == Decimal("4820.00")
    assert fila["monto_pagado"] == Decimal("6820.00")
    assert fila["saldo_pendiente"] == Decimal("5230.00")

    # Liquida en el cierre entregando de más: 5300 efectivo, cambio 70.
    await pagos_reservacion.completar(
        pg,
        PagosReservacionCompletarRequest(
            reservacion_id=rid,
            pagos=[PagoReservacionItem(metodo_pago_id=e["efectivo"], monto=Decimal("5300"))],
            cambio=Decimal("70"),
        ),
        e["usuario"],
        str(e["apertura"]),
    )
    fila = await _saldo(pg, rid)
    assert fila["monto_pagado"] == TOTAL
    assert fila["saldo_pendiente"] == Decimal("0.00")

    # Liquidada, ya no se acepta otro pago, ni por encima del saldo.
    with pytest.raises(HTTPException) as exc:
        await pagos_reservacion.crear(
            pg,
            PagosReservacionCreate(reservacion_id=rid, metodo_pago_id=e["tarjeta"], monto=1),
            e["usuario"],
            str(e["apertura"]),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PAGO_EXCEDE_SALDO"

    # Un pago registrado no se borra (dejaría la caja y los puntos como
    # estaban); el saldo no cambia.
    pago_id = await pg.fetchval(
        "SELECT id FROM pagos_reservacion WHERE reservacion_id = $1 AND monto = 2000", rid
    )
    with pytest.raises(HTTPException) as exc:
        await pagos_reservacion.eliminar(pg, pago_id)
    assert exc.value.detail["code"] == "PAGO_NO_ELIMINABLE"
    assert (await _saldo(pg, rid))["saldo_pendiente"] == Decimal("0.00")


async def test_completar_no_acepta_mas_que_el_saldo_mas_el_cambio(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    alta = await reservaciones.crear_completa(
        pg, _alta(e, 30, [(e["efectivo"], "4820")]), e["usuario"], str(e["apertura"])
    )
    rid = alta.reservacion.id
    saldo = TOTAL - Decimal("4820")
    # Efectivo de más con su cambio: se aplica justo el saldo.
    exceso = PagosReservacionCompletarRequest(
        reservacion_id=rid,
        pagos=[PagoReservacionItem(metodo_pago_id=e["tarjeta"], monto=saldo + 1)],
        cambio=Decimal(0),
    )
    with pytest.raises(HTTPException) as exc:
        await pagos_reservacion.completar(pg, exceso, e["usuario"], str(e["apertura"]))
    assert exc.value.detail["code"] == "PAGO_EXCEDE_SALDO"
    assert (await _saldo(pg, rid))["saldo_pendiente"] == saldo

    await pagos_reservacion.completar(
        pg,
        PagosReservacionCompletarRequest(
            reservacion_id=rid,
            pagos=[PagoReservacionItem(metodo_pago_id=e["efectivo"], monto=saldo + 500)],
            cambio=Decimal(500),
        ),
        e["usuario"],
        str(e["apertura"]),
    )
    assert (await _saldo(pg, rid))["saldo_pendiente"] == Decimal("0.00")


async def test_scheduler_solo_cancela_las_que_siguen_debiendo(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    # Dos reservaciones a 20 días (se pudo dejar solo anticipo) que luego
    # "llegan" a 5 días del evento: una se liquidó después del anticipo
    # (R-0008) y otra sólo abonó (R-0009).
    pagada = await reservaciones.crear_completa(
        pg, _alta(e, 20, [(e["efectivo"], "4820")]), e["usuario"], str(e["apertura"])
    )
    debe = await reservaciones.crear_completa(
        pg, _alta(e, 20, [(e["efectivo"], "4820")]), e["usuario"], str(e["apertura"])
    )
    await pagos_reservacion.crear(
        pg,
        PagosReservacionCreate(
            reservacion_id=pagada.reservacion.id, metodo_pago_id=e["tarjeta"], monto=7230
        ),
        e["usuario"],
        str(e["apertura"]),
    )
    await pg.execute(
        "UPDATE reservaciones SET fecha_evento = $2 WHERE id = ANY($1::uuid[])",
        [pagada.reservacion.id, debe.reservacion.id],
        e["hoy"] + timedelta(days=5),
    )

    vencidas = {r["id"] for r in await reservaciones_repository.listar_vencidas_sin_liquidar(pg, 7)}
    assert debe.reservacion.id in vencidas
    assert pagada.reservacion.id not in vencidas

    await reservaciones_vencidas_scheduler.revisar_reservaciones_vencidas(pg)
    assert (await _saldo(pg, pagada.reservacion.id))["estado"] == "confirmada"
    assert (await _saldo(pg, debe.reservacion.id))["estado"] == "cancelada"


async def test_alta_a_7_dias_liquidada_no_la_cancela_el_scheduler(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    with pytest.raises(HTTPException) as exc:
        await reservaciones.crear_completa(
            pg, _alta(e, 7, [(e["efectivo"], "4820")]), e["usuario"], str(e["apertura"])
        )
    assert exc.value.detail["code"] == "LIQUIDACION_REQUERIDA"

    alta = await reservaciones.crear_completa(
        pg, _alta(e, 7, [(e["tarjeta"], str(TOTAL))]), e["usuario"], str(e["apertura"])
    )
    await reservaciones_vencidas_scheduler.revisar_reservaciones_vencidas(pg)
    assert (await _saldo(pg, alta.reservacion.id))["estado"] == "confirmada"


async def test_alta_con_precio_manipulado_da_409_y_no_crea_nada(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    contar = "SELECT COUNT(*) FROM reservaciones WHERE sucursal_id = $1"
    antes = await pg.fetchval(contar, e["sucursal"])
    movimientos = "SELECT COUNT(*) FROM movimientos_caja WHERE apertura_caja_id = $1"
    movs_antes = await pg.fetchval(movimientos, e["apertura"])

    # El ataque de R-0011: $1, sin anticipo, "confirmada".
    with pytest.raises(HTTPException) as exc:
        await reservaciones.crear_completa(
            pg,
            _alta(
                e,
                90,
                [(e["efectivo"], "1")],
                precio_total=Decimal("1"),
                anticipo=Decimal("0"),
                estado="confirmada",
            ),
            e["usuario"],
            str(e["apertura"]),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["message"] == (
        "El precio de la reservación cambió: $12,050.00. Actualiza la reservación."
    )

    # 40 invitados en un paquete de máximo 30, aun con el total "correcto".
    with pytest.raises(HTTPException) as exc:
        await reservaciones.crear_completa(
            pg,
            _alta(e, 90, [(e["efectivo"], "6000")], numero_personas=40),
            e["usuario"],
            str(e["apertura"]),
        )
    assert exc.value.status_code == 422

    assert await pg.fetchval(contar, e["sucursal"]) == antes
    assert await pg.fetchval(movimientos, e["apertura"]) == movs_antes


async def test_dos_abonos_simultaneos_no_se_pisan(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    alta = await reservaciones.crear_completa(
        pg, _alta(e, 30, [(e["efectivo"], "4820")]), e["usuario"], str(e["apertura"])
    )
    rid = alta.reservacion.id
    assert DSN
    conexiones = [await asyncpg.connect(DSN) for _ in range(4)]
    try:
        await asyncio.gather(
            *(
                pagos_reservacion.crear(
                    c,
                    PagosReservacionCreate(
                        reservacion_id=rid, metodo_pago_id=e["tarjeta"], monto=1000
                    ),
                    e["usuario"],
                    str(e["apertura"]),
                )
                for c in conexiones
            )
        )
    finally:
        for c in conexiones:
            await c.close()
    fila = await _saldo(pg, rid)
    assert fila["monto_pagado"] == Decimal("8820.00")
    assert fila["saldo_pendiente"] == TOTAL - Decimal("8820")


async def test_checkin_muestra_evento_de_hoy_liquidado_tras_el_anticipo(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    hoy_bd: date = e["hoy"]
    rid = await pg.fetchval(
        """INSERT INTO reservaciones (sucursal_id, tipo_evento_id, paquete_id, nombre_cliente,
               telefono_cliente, fecha_evento, hora_inicio, hora_fin, numero_personas,
               precio_base, precio_total, anticipo, estado)
           VALUES ($1, $2, $3, 'Fiesta hoy', '3312345678', $4, '00:00', '23:59', 20,
                   6900, 6900, 2760, 'confirmada')
           RETURNING id""",
        e["sucursal"],
        e["tipo"],
        e["paquete"],
        hoy_bd,
    )
    for monto in ("2760", "4140"):
        await pagos_reservacion.crear(
            pg,
            PagosReservacionCreate(reservacion_id=rid, metodo_pago_id=e["efectivo"], monto=monto),
            e["usuario"],
            str(e["apertura"]),
        )
    evento = await reservaciones_repository.obtener_evento_mas_cercano(pg, e["sucursal"])
    assert evento is not None and evento["id"] == rid


async def _evento_liquidado(
    pg: asyncpg.Connection, e: dict[str, Any], fecha: date, inicio: time, fin: time
) -> uuid.UUID:
    return await pg.fetchval(
        """INSERT INTO reservaciones (sucursal_id, tipo_evento_id, paquete_id, nombre_cliente,
               telefono_cliente, fecha_evento, hora_inicio, hora_fin, numero_personas,
               precio_base, precio_total, anticipo, estado)
           VALUES ($1, $2, $3, 'Fiesta', '3312345678', $4, $5, $6, 20,
                   0, 0, 0, 'confirmada')
           RETURNING id""",
        e["sucursal"],
        e["tipo"],
        e["paquete"],
        fecha,
        inicio,
        fin,
    )


# A cualquier hora, en al menos una de las dos primeras zonas la fecha local es
# distinta a la de UTC: con CURRENT_DATE (UTC) el check-in fallaba ahí.
@pytest.mark.parametrize("zona", ["Etc/GMT+12", "Pacific/Kiritimati", "America/Mexico_City"])
async def test_checkin_usa_la_fecha_de_la_sucursal_y_no_la_de_utc(
    pg: asyncpg.Connection, escenario: dict[str, Any], zona: str
) -> None:
    e = escenario
    await pg.execute("UPDATE sucursales SET zona_horaria = $2 WHERE id = $1", e["sucursal"], zona)
    hoy_local = await reservaciones_repository.hoy_en_sucursal(pg, e["sucursal"])
    assert hoy_local is not None
    rid = await _evento_liquidado(pg, e, hoy_local, time(0, 0), time(23, 59, 59))
    # Un evento con la fecha de UTC (si es otra) no es de hoy en la sucursal.
    hoy_utc: date = await pg.fetchval("SELECT (NOW() AT TIME ZONE 'UTC')::date")
    if hoy_utc != hoy_local:
        await _evento_liquidado(pg, e, hoy_utc, time(0, 0), time(23, 59, 59))

    evento = await reservaciones_repository.obtener_evento_mas_cercano(pg, e["sucursal"])
    assert evento is not None and evento["id"] == rid


async def test_checkin_liga_el_evento_elegido_y_no_otro_simultaneo(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    primero = await _evento_liquidado(pg, e, e["hoy"], time(0, 0), time(23, 59, 59))
    segundo = await _evento_liquidado(pg, e, e["hoy"], time(0, 1), time(23, 59, 59))

    sin_elegir = await reservaciones_repository.obtener_evento_mas_cercano(pg, e["sucursal"])
    assert sin_elegir is not None and sin_elegir["id"] == primero
    elegido = await reservaciones_repository.obtener_evento_mas_cercano(pg, e["sucursal"], segundo)
    assert elegido is not None and elegido["id"] == segundo
    ajeno = await reservaciones_repository.obtener_evento_mas_cercano(
        pg, e["sucursal"], uuid.uuid4()
    )
    assert ajeno is None


async def _evento_que_empieza_en(
    pg: asyncpg.Connection, e: dict[str, Any], minutos: int
) -> uuid.UUID:
    """Evento confirmado que empieza dentro de `minutos`, medidos en la hora
    LOCAL de la sucursal (la que se captura al reservar), no en UTC."""
    ahora_local = await pg.fetchval(
        "SELECT (NOW() AT TIME ZONE zona_horaria) FROM sucursales WHERE id = $1", e["sucursal"]
    )
    inicio = ahora_local + timedelta(minutes=minutos)
    hora_inicio = inicio.time().replace(microsecond=0)
    fin = time(23, 59, 59)
    if hora_inicio >= fin:
        pytest.skip("Muy cerca de la medianoche: el evento cruzaría de día.")
    return await _evento_liquidado(pg, e, inicio.date(), hora_inicio, fin)


async def test_comanda_de_evento_no_sale_a_cocina_antes_de_tiempo(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    """La comanda sale 2 h antes del evento. El horario es local: comparado
    contra NOW() (UTC) sin convertir, un evento de dentro de 3 h ya salía."""
    rid = await _evento_que_empieza_en(pg, escenario, 180)
    pendientes = await reservaciones_repository.listar_pendientes_de_comanda(pg, 120)
    assert rid not in {p["id"] for p in pendientes}


async def test_comanda_de_evento_sale_cuando_entra_a_la_ventana(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    rid = await _evento_que_empieza_en(pg, escenario, 90)
    pendientes = await reservaciones_repository.listar_pendientes_de_comanda(pg, 120)
    assert rid in {p["id"] for p in pendientes}
