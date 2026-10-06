"""Reportes de ventas contra un PostgreSQL real.

Escenario del día 15 de septiembre de 2026 en una sucursal de Ciudad de México
(UTC-6), con la BD en UTC:

- Comanda A: $161 pagada en 2 partes (efectivo $100 + tarjeta $61).
- Comanda B: $165 pagada con $500 en efectivo y $335 de cambio.
- Comanda C: $170 cancelada desde cocina (activo = FALSE, estado 'T'), pagada
  con $200 en efectivo y $30 de cambio.
- Comanda D: $100 cobrada a las 19:00 hora de México (01:00 UTC del día 16)
  y todavía en cocina (estado 'P').
- Reservación R: $7,185 con 4 pagos que suman $4,500.
- Estancia E: $260 pagada en un solo pago.
- Y un pago de estancia del día 16 que no debe entrar en el día 15.

Requiere `TEST_DATABASE_URL` con `sql/schema_maestro.sql` cargado; sin ella
se salta. Cada test crea sus datos con ids nuevos y los borra al terminar.
"""

import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from app.repositories import branch_repository, movimiento_inventario_repository, sucursales
from app.services import pago_service

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL no está definida")

MX = timezone(timedelta(hours=-6))  # America/Mexico_City no tiene horario de verano.
DIA = date(2026, 9, 15)


def _local(hora: int, dia: date = DIA) -> datetime:
    return datetime(dia.year, dia.month, dia.day, hora, 0, tzinfo=MX)


@pytest.fixture(autouse=True)
def proceso_en_utc() -> Iterator[None]:
    """El contenedor del backend corre en UTC. asyncpg interpreta los datetime
    sin zona con la zona del proceso, así que en una máquina con hora de México
    un error de zona horaria pasaría inadvertido: se fuerza UTC durante cada
    prueba."""
    anterior = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if anterior is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = anterior
    time.tzset()


@pytest_asyncio.fixture
async def pg() -> AsyncIterator[asyncpg.Connection]:
    assert DSN
    conn = await asyncpg.connect(DSN)
    yield conn
    await conn.close()


async def _comanda(
    pg: asyncpg.Connection,
    e: dict[str, Any],
    total: str,
    momento: datetime,
    pagos: list[tuple[uuid.UUID, str]],
    *,
    estado: str = "T",
    activo: bool = True,
    cambio: str | None = None,
) -> uuid.UUID:
    comanda_id = uuid.uuid4()
    await pg.execute(
        """INSERT INTO comandas (id, ticket_numero, estado_actual, total_final, sucursal_id,
               fecha_hora, activo, creado_por)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
        comanda_id,
        f"T{comanda_id.hex[:6]}",
        estado,
        Decimal(total),
        e["sucursal"],
        momento,
        activo,
        e["usuario"],
    )
    for metodo, monto in pagos:
        await pg.execute(
            """INSERT INTO pagos_ordenes (comanda_id, metodo_pago_id, monto, sucursal_id,
                   creado, creado_por)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            comanda_id,
            metodo,
            Decimal(monto),
            e["sucursal"],
            momento,
            e["usuario"],
        )
        await _movimiento(pg, e, "O", comanda_id, metodo, monto, momento)
    if cambio:
        await _movimiento(pg, e, "C", comanda_id, None, cambio, momento)
    return comanda_id


async def _movimiento(
    pg: asyncpg.Connection,
    e: dict[str, Any],
    tipo: str,
    referencia: uuid.UUID,
    metodo: uuid.UUID | None,
    monto: str,
    momento: datetime,
) -> None:
    await pg.execute(
        """INSERT INTO movimientos_caja (apertura_caja_id, tipo_movimiento, referencia_id,
               metodo_pago_id, monto, creado, creado_por)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        e["apertura"],
        tipo,
        referencia,
        metodo,
        Decimal(monto),
        momento,
        e["usuario"],
    )


@pytest_asyncio.fixture
async def escenario(pg: asyncpg.Connection) -> AsyncIterator[dict[str, Any]]:
    ids: dict[str, Any] = {
        k: uuid.uuid4()
        for k in (
            "sucursal",
            "usuario",
            "caja",
            "turno",
            "apertura",
            "tutor",
            "tipo",
            "paquete",
            "reservacion",
            "registro",
            "registro_16",
            "insumo",
        )
    }
    await pg.execute(
        "INSERT INTO sucursales (id, nombre, zona_horaria) VALUES ($1, $2, 'America/Mexico_City')",
        ids["sucursal"],
        f"Prueba reportes {ids['sucursal']}",
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
    ids.update(efectivo=efectivo, tarjeta=tarjeta)

    ids["A"] = await _comanda(pg, ids, "161", _local(12), [(efectivo, "100"), (tarjeta, "61")])
    ids["B"] = await _comanda(pg, ids, "165", _local(13), [(efectivo, "500")], cambio="335")
    ids["C"] = await _comanda(
        pg, ids, "170", _local(14), [(efectivo, "200")], activo=False, cambio="30"
    )
    ids["D"] = await _comanda(pg, ids, "100", _local(19), [(tarjeta, "100")], estado="P")

    # Reservación de $7,185 con 4 pagos ($4,500): cada pago de reservación
    # registra su movimiento de caja con el id del pago, no de la reservación.
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
    await pg.execute(
        """INSERT INTO reservaciones (id, sucursal_id, tipo_evento_id, paquete_id,
               nombre_cliente, telefono_cliente, fecha_evento, hora_inicio, hora_fin,
               numero_personas, precio_base, precio_total, estado, monto_pagado, creado)
           VALUES ($1, $2, $3, $4, 'Gabriela', '3312345678', $5, '11:00', '15:00',
                   20, 6900, 7185, 'confirmada', 4500, $6)""",
        ids["reservacion"],
        ids["sucursal"],
        ids["tipo"],
        ids["paquete"],
        DIA + timedelta(days=5),
        _local(15),
    )
    for monto in ("1000", "1000", "1000", "1500"):
        pago_id = await pg.fetchval(
            """INSERT INTO pagos_reservacion (reservacion_id, metodo_pago_id, monto,
                   fecha_pago, creado_por)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            ids["reservacion"],
            tarjeta,
            Decimal(monto),
            _local(15),
            ids["usuario"],
        )
        await _movimiento(pg, ids, "R", pago_id, tarjeta, monto, _local(15))

    # Estancia de $260 el día 15 y otra de $90 el día 16 (fuera del periodo).
    await pg.execute(
        "INSERT INTO tutores (id, sucursal_id, nombre_completo, telefono) "
        "VALUES ($1, $2, 'Ana López', '3311111111')",
        ids["tutor"],
        ids["sucursal"],
    )
    for clave, total, momento in (
        ("registro", "260", _local(16)),
        ("registro_16", "90", _local(10, DIA + timedelta(days=1))),
    ):
        await pg.execute(
            """INSERT INTO registros (id, sucursal_id, tutores_id, total, estado, creado)
               VALUES ($1, $2, $3, $4, 'F', $5)""",
            ids[clave],
            ids["sucursal"],
            ids["tutor"],
            Decimal(total),
            momento,
        )
        await pg.execute(
            """INSERT INTO pagos_estancia (sucursal_id, registros_id, metodos_pago_id, monto,
                   creado, creado_por)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            ids["sucursal"],
            ids[clave],
            efectivo,
            Decimal(total),
            momento,
            ids["usuario"],
        )
        await _movimiento(pg, ids, "E", ids[clave], efectivo, total, momento)

    # Costo de lo vendido: A consumió $50 y C $40; la cancelación de C devolvió
    # sus $40 al inventario al día siguiente.
    unidad = await pg.fetchval("SELECT id FROM unidades_medida WHERE codigo = 'g'")
    await pg.execute(
        """INSERT INTO insumos (id, sucursal_id, nombre, unidad_base_id, unidad_compra_id)
           VALUES ($1, $2, 'Pan Prueba', $3, $3)""",
        ids["insumo"],
        ids["sucursal"],
        unidad,
    )
    for tipo, motivo, comanda, costo, momento in (
        ("S", "venta_comanda", ids["A"], "50", _local(12)),
        ("S", "venta_comanda", ids["C"], "40", _local(14)),
        ("A", "cancelacion_comanda", ids["C"], "40", _local(9, DIA + timedelta(days=1))),
    ):
        await pg.execute(
            """INSERT INTO movimientos_inventario (sucursal_id, insumo_id, tipo, cantidad,
                   stock_resultante, motivo, referencia_id, costo_total, creado)
               VALUES ($1, $2, $3, 1, 10, $4::motivo_movimiento_inventario, $5, $6, $7)""",
            ids["sucursal"],
            ids["insumo"],
            tipo,
            motivo,
            comanda,
            Decimal(costo),
            momento,
        )

    yield ids

    suc = ids["sucursal"]
    await pg.execute("DELETE FROM movimientos_inventario WHERE sucursal_id = $1", suc)
    await pg.execute("DELETE FROM insumos WHERE sucursal_id = $1", suc)
    await pg.execute("DELETE FROM movimientos_caja WHERE apertura_caja_id = $1", ids["apertura"])
    await pg.execute("DELETE FROM pagos_ordenes WHERE sucursal_id = $1", suc)
    await pg.execute("DELETE FROM comandas WHERE sucursal_id = $1", suc)
    await pg.execute("DELETE FROM pagos_estancia WHERE sucursal_id = $1", suc)
    await pg.execute("DELETE FROM registros WHERE sucursal_id = $1", suc)
    await pg.execute("DELETE FROM tutores WHERE sucursal_id = $1", suc)
    await pg.execute("DELETE FROM pagos_reservacion WHERE reservacion_id = $1", ids["reservacion"])
    await pg.execute("DELETE FROM reservaciones WHERE sucursal_id = $1", suc)
    await pg.execute("DELETE FROM paquetes WHERE id = $1", ids["paquete"])
    await pg.execute("DELETE FROM tipos_evento WHERE id = $1", ids["tipo"])
    await pg.execute("DELETE FROM apertura_caja WHERE id = $1", ids["apertura"])
    await pg.execute("DELETE FROM turnos WHERE id = $1", ids["turno"])
    await pg.execute("DELETE FROM cajas WHERE id = $1", ids["caja"])
    await pg.execute("DELETE FROM usuarios WHERE id = $1", ids["usuario"])
    await pg.execute("DELETE FROM sucursales WHERE id = $1", suc)


async def _historial(
    pg: asyncpg.Connection, e: dict[str, Any], estado: str = "todos", **filtros: Any
) -> dict[uuid.UUID, Any]:
    filas = await pago_service.obtener_historial(
        pg,
        e["sucursal"],
        "hoy",
        estado,
        fecha_inicio=DIA.isoformat(),
        fecha_fin=DIA.isoformat(),
        **filtros,
    )
    return {f.referencia_id: f for f in filas}


@pytest.mark.asyncio
async def test_historial_cuenta_cada_orden_una_vez_aunque_tenga_varios_pagos(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    filas = await _historial(pg, e)

    # Sin multiplicar por pago: A no sale con $322 ni la reservación con $28,740.
    assert filas[e["A"]].total_final == Decimal("161.00")
    assert filas[e["reservacion"]].total_final == Decimal("7185.00")
    # Lo cobrado por método sale de los pagos, uno por pago, sin duplicar.
    assert sorted(m.monto for m in filas[e["A"]].metodos_pago) == [
        Decimal("61.00"),
        Decimal("100.00"),
    ]
    assert len(filas[e["reservacion"]].metodos_pago) == 4
    assert sum(m.monto for m in filas[e["reservacion"]].metodos_pago) == Decimal("4500.00")


@pytest.mark.asyncio
async def test_historial_muestra_cancelada_la_comanda_cancelada_desde_cocina(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    todos = await _historial(pg, e)
    assert todos[e["C"]].estado_actual == "C"

    pagados = await _historial(pg, e, "pagado")
    assert e["C"] not in pagados
    assert e["A"] in pagados

    cancelados = await _historial(pg, e, "cancelado")
    assert set(cancelados) == {e["C"]}


@pytest.mark.asyncio
async def test_historial_toma_el_dia_en_la_zona_de_la_sucursal(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    filas = await _historial(pg, e)
    # D se cobró a las 19:00 de México (01:00 UTC del día 16) y es del 15;
    # la estancia del 16 a las 10:00 no lo es.
    assert e["D"] in filas
    assert e["registro_16"] not in filas
    assert set(filas) == {e["A"], e["B"], e["C"], e["D"], e["reservacion"], e["registro"]}


@pytest.mark.asyncio
async def test_historial_filtra_por_metodo_y_por_caja_sin_inflar(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    con_tarjeta = await _historial(pg, e, metodo_pago_id=e["tarjeta"])
    assert set(con_tarjeta) == {e["A"], e["D"], e["reservacion"]}
    assert con_tarjeta[e["A"]].total_final == Decimal("161.00")

    # Los pagos de reservación registran el movimiento de caja con el id del pago.
    en_caja = await _historial(pg, e, caja_id=e["caja"])
    assert e["reservacion"] in en_caja
    assert en_caja[e["reservacion"]].total_final == Decimal("7185.00")
    otra_caja = await _historial(pg, e, caja_id=uuid.uuid4())
    assert otra_caja == {}


@pytest.mark.asyncio
async def test_estadisticas_suman_cada_orden_una_vez_y_sin_canceladas(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    stats = await pago_service.obtener_estadisticas(
        pg, e["sucursal"], "hoy", fecha_inicio=DIA.isoformat(), fecha_fin=DIA.isoformat()
    )
    # A 161 + B 165 + D 100 + reservación 7185 + estancia 260; sin C (cancelada).
    assert stats.total_ventas == pytest.approx(7871.0)
    assert stats.total_ordenes == 5
    assert stats.ticket_promedio == pytest.approx(7871.0 / 5)


@pytest.mark.asyncio
async def test_indicador_ventas_suma_lo_cobrado_de_todas_las_fuentes(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    indicadores = await branch_repository.get_indicadores_sucursal(pg, e["sucursal"], DIA, DIA)
    # Ventas: A 161 + B (500 - 335 de cambio) + D 100 (aún en cocina, cobrada a las
    # 19:00) + reservación 4500 cobrados + estancia 260. Sin C (cancelada) ni la
    # estancia del día 16.
    assert indicadores["ventas"] == Decimal("5186.00")

    dia_16 = await branch_repository.get_indicadores_sucursal(
        pg, e["sucursal"], DIA + timedelta(days=1), DIA + timedelta(days=1)
    )
    assert dia_16["ventas"] == Decimal("90.00")


@pytest.mark.asyncio
async def test_costo_de_ventas_sin_canceladas_y_en_dias_de_la_sucursal(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    e = escenario
    resumen = await movimiento_inventario_repository.resumen_costo_ventas(
        pg, e["sucursal"], DIA, DIA
    )
    # A 161 + B 165 + D 100 (19:00 de México); sin C.
    assert resumen["ventas_totales"] == Decimal("426.00")
    # Lo que C consumió volvió al inventario al cancelarla.
    assert resumen["costo_ventas"] == Decimal("50.00")
    assert resumen["margen"] == Decimal("376.00")


@pytest.mark.asyncio
async def test_ahora_en_sucursal_es_la_hora_local_y_no_la_utc(
    pg: asyncpg.Connection, escenario: dict[str, Any]
) -> None:
    ahora_local = await sucursales.ahora_en_sucursal(pg, escenario["sucursal"])
    ahora_utc = await pg.fetchval("SELECT NOW() AT TIME ZONE 'UTC'")
    assert ahora_local is not None and ahora_local.tzinfo is None
    assert round((ahora_utc - ahora_local).total_seconds() / 3600) == 6
