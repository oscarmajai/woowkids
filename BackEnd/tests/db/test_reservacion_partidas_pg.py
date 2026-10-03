"""Extras y productos de una reservación ya levantada (N11), cantidad de los
extras por persona / por hora (M15) y auditoría (M18), contra un PostgreSQL
de verdad.

E2E: `POST/PATCH /reservacion-extras` y `/reservacion-productos` guardaban el
precio del request y no movían el total; R-0008 cobró la "Bolsita de dulces"
($35 por persona, 12 niños) como $35; `creado_por`/`modificado_por` quedaban
en NULL. Requiere `TEST_DATABASE_URL`; sin ella se salta. Cada test crea y
borra sus datos.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from app.repositories import reservaciones_repository
from app.schemas.auth import TokenData
from app.schemas.reservacion_extras import ReservacionExtrasCreate, ReservacionExtrasUpdate
from app.schemas.reservacion_productos import (
    ReservacionProductosCreate,
    ReservacionProductosUpdate,
)
from app.schemas.reservaciones import ReservacionesUpdate
from app.services import reservacion_extras, reservacion_productos, reservaciones
from fastapi import HTTPException

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL no está definida")

# Paquete $3,800 + pulseras 12 niños x 3 h x $70 = $2,520 -> $6,320.
TOTAL_BASE = Decimal("6320.00")


@pytest_asyncio.fixture
async def pg() -> AsyncIterator[asyncpg.Connection]:
    assert DSN
    conn = await asyncpg.connect(DSN)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def esc(pg: asyncpg.Connection) -> AsyncIterator[dict[str, Any]]:
    claves = ("sucursal", "tipo", "paquete", "usuario", "bolsita", "animador", "pastel", "pizza")
    ids = {k: uuid.uuid4() for k in claves}
    await pg.execute(
        "INSERT INTO sucursales (id, nombre) VALUES ($1, $2)",
        ids["sucursal"],
        f"QA partidas {ids['sucursal']}",
    )
    await pg.execute(
        "INSERT INTO tipos_evento (id, nombre, sucursal_id) VALUES ($1, 'Cumpleaños', $2)",
        ids["tipo"],
        ids["sucursal"],
    )
    await pg.execute(
        """INSERT INTO paquetes (id, sucursal_id, nombre, min_invitados, max_invitados,
               precio_base, precio_hora_pulsera)
           VALUES ($1, $2, 'Básico', 5, 30, 3800, 70)""",
        ids["paquete"],
        ids["sucursal"],
    )
    await pg.execute(
        """INSERT INTO usuarios (id, email, password_hash, nombre_completo, rol)
           VALUES ($1, $2, 'x', 'Cajera QA', 3)""",
        ids["usuario"],
        f"{ids['usuario']}@qa.dev",
    )
    for clave, nombre, precio, unidad in (
        ("bolsita", "Bolsita de dulces", 35, "persona"),
        ("animador", "Animador adicional", 350, "hora"),
        ("pastel", "Pastel", 450, "evento"),
    ):
        await pg.execute(
            "INSERT INTO extras (id, sucursal_id, nombre, precio, unidad) "
            "VALUES ($1, $2, $3, $4, $5)",
            ids[clave],
            ids["sucursal"],
            nombre,
            precio,
            unidad,
        )
    await pg.execute(
        "INSERT INTO productos (id, sucursal_id, nombre, precio_unitario, tipo) "
        "VALUES ($1, $2, 'Pizza QA', 135, 'A')",
        ids["pizza"],
        ids["sucursal"],
    )
    hoy = await reservaciones_repository.hoy_en_sucursal(pg, ids["sucursal"])
    assert hoy is not None
    yield {**ids, "hoy": hoy}

    reservas = "SELECT id FROM reservaciones WHERE sucursal_id = $1"
    await pg.execute(
        f"DELETE FROM reservacion_extras WHERE reservacion_id IN ({reservas})", ids["sucursal"]
    )
    await pg.execute(
        f"DELETE FROM reservacion_productos WHERE reservacion_id IN ({reservas})", ids["sucursal"]
    )
    await pg.execute("DELETE FROM reservaciones WHERE sucursal_id = $1", ids["sucursal"])
    await pg.execute("DELETE FROM productos WHERE id = $1", ids["pizza"])
    await pg.execute("DELETE FROM extras WHERE sucursal_id = $1", ids["sucursal"])
    await pg.execute("DELETE FROM usuarios WHERE id = $1", ids["usuario"])
    await pg.execute("DELETE FROM paquetes WHERE id = $1", ids["paquete"])
    await pg.execute("DELETE FROM tipos_evento WHERE id = $1", ids["tipo"])
    await pg.execute("DELETE FROM sucursales WHERE id = $1", ids["sucursal"])


async def _reservacion(
    pg: asyncpg.Connection,
    e: dict[str, Any],
    *,
    dias: int = 30,
    estado: str = "confirmada",
    pagado: Decimal = Decimal("2000"),
) -> uuid.UUID:
    """12 niños, 16:00-19:00 (3 h), sin extras ni productos."""
    return await pg.fetchval(
        """INSERT INTO reservaciones (sucursal_id, tipo_evento_id, paquete_id, nombre_cliente,
               telefono_cliente, fecha_evento, hora_inicio, hora_fin, numero_personas,
               horas_reservadas, precio_base, precio_personas_extra, precio_total,
               anticipo, monto_pagado, estado)
           VALUES ($1, $2, $3, 'Gabriela', '3312345678', $4, '16:00', '19:00', 12, 3,
                   3800, 2520, $5, $6, $6, $7)
           RETURNING id""",
        e["sucursal"],
        e["tipo"],
        e["paquete"],
        e["hoy"] + timedelta(days=dias),
        TOTAL_BASE,
        pagado,
        estado,
    )


def _usuario(e: dict[str, Any]) -> TokenData:
    return TokenData(
        sub=str(e["usuario"]),
        email="cajera@qa.dev",
        role="Cajero",
        branch_id=e["sucursal"],
        jti="qa",
        exp=datetime.now(UTC) + timedelta(hours=1),
    )


async def _fila(pg: asyncpg.Connection, reservacion_id: uuid.UUID) -> asyncpg.Record:
    return await pg.fetchrow(
        "SELECT precio_extras, precio_productos, precio_total, modificado_por "
        "FROM reservaciones WHERE id = $1",
        reservacion_id,
    )


# ── N11 + M15: extras ────────────────────────────────────────────────────────


async def test_n11_extra_toma_precio_de_catalogo_y_mueve_el_total(
    pg: asyncpg.Connection, esc: dict[str, Any]
) -> None:
    rid = await _reservacion(pg, esc)
    out = await reservacion_extras.crear(
        pg,
        ReservacionExtrasCreate(
            reservacion_id=rid, extra_id=esc["bolsita"], cantidad=1, precio_unitario=Decimal("1")
        ),
        esc["usuario"],
    )
    # $35 de catálogo x 12 invitados, no $1 x 1 del request.
    assert out.precio_unitario == Decimal("35.00")
    assert out.cantidad == 12
    assert out.creado_por == esc["usuario"]  # M18
    fila = await _fila(pg, rid)
    assert fila["precio_extras"] == Decimal("420.00")
    assert fila["precio_total"] == TOTAL_BASE + Decimal("420")
    assert fila["modificado_por"] == esc["usuario"]


async def test_n11_extra_por_hora_y_actualizar_refresca_el_precio(
    pg: asyncpg.Connection, esc: dict[str, Any]
) -> None:
    rid = await _reservacion(pg, esc)
    out = await reservacion_extras.crear(
        pg, ReservacionExtrasCreate(reservacion_id=rid, extra_id=esc["animador"]), esc["usuario"]
    )
    assert (out.cantidad, out.subtotal) == (3, Decimal("1050.00"))

    await pg.execute("UPDATE extras SET precio = 400 WHERE id = $1", esc["animador"])
    out = await reservacion_extras.actualizar(
        pg,
        out.id,
        ReservacionExtrasUpdate(cantidad=1, precio_unitario=Decimal("0")),
        esc["usuario"],
    )
    assert (out.cantidad, out.precio_unitario) == (3, Decimal("400.00"))
    assert (await _fila(pg, rid))["precio_total"] == TOTAL_BASE + Decimal("1200")


async def test_n11_total_del_cliente_que_no_coincide_responde_409_sin_guardar(
    pg: asyncpg.Connection, esc: dict[str, Any]
) -> None:
    rid = await _reservacion(pg, esc)
    with pytest.raises(HTTPException) as exc:
        await reservacion_extras.crear(
            pg,
            ReservacionExtrasCreate(
                reservacion_id=rid, extra_id=esc["pastel"], precio_total=TOTAL_BASE
            ),
            esc["usuario"],
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PRECIO_CAMBIADO"
    assert (
        await pg.fetchval("SELECT count(*) FROM reservacion_extras WHERE reservacion_id = $1", rid)
        == 0
    )
    assert (await _fila(pg, rid))["precio_total"] == TOTAL_BASE

    out = await reservacion_extras.crear(
        pg,
        ReservacionExtrasCreate(
            reservacion_id=rid, extra_id=esc["pastel"], precio_total=TOTAL_BASE + 450
        ),
        esc["usuario"],
    )
    assert out.cantidad == 1


async def test_n11_quitar_extra_recalcula_y_no_baja_de_lo_pagado(
    pg: asyncpg.Connection, esc: dict[str, Any]
) -> None:
    rid = await _reservacion(pg, esc, pagado=TOTAL_BASE)
    out = await reservacion_extras.crear(
        pg, ReservacionExtrasCreate(reservacion_id=rid, extra_id=esc["pastel"]), esc["usuario"]
    )
    await pg.execute("UPDATE reservaciones SET monto_pagado = precio_total WHERE id = $1", rid)
    with pytest.raises(HTTPException) as exc:
        await reservacion_extras.eliminar(pg, out.id, esc["usuario"])
    assert exc.value.status_code == 409
    assert "ya pagado" in exc.value.detail["message"]
    assert await pg.fetchval("SELECT count(*) FROM reservacion_extras WHERE id = $1", out.id) == 1

    await pg.execute("UPDATE reservaciones SET monto_pagado = $2 WHERE id = $1", rid, TOTAL_BASE)
    await reservacion_extras.eliminar(pg, out.id, esc["usuario"])
    fila = await _fila(pg, rid)
    assert (fila["precio_extras"], fila["precio_total"]) == (Decimal("0.00"), TOTAL_BASE)


@pytest.mark.parametrize(
    ("estado", "dias", "code"),
    [
        ("cancelada", 30, "RESERVACION_CERRADA"),
        ("completada", 30, "RESERVACION_CERRADA"),
        ("confirmada", 5, "FUERA_DE_PLAZO"),
    ],
)
async def test_n11_respeta_estados_y_plazo(
    pg: asyncpg.Connection, esc: dict[str, Any], estado: str, dias: int, code: str
) -> None:
    rid = await _reservacion(pg, esc, estado=estado, dias=dias)
    with pytest.raises(HTTPException) as exc:
        await reservacion_extras.crear(
            pg, ReservacionExtrasCreate(reservacion_id=rid, extra_id=esc["pastel"]), esc["usuario"]
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == code
    with pytest.raises(HTTPException) as exc:
        await reservacion_productos.crear(
            pg,
            ReservacionProductosCreate(reservacion_id=rid, producto_id=esc["pizza"], cantidad=1),
            _usuario(esc),
        )
    assert exc.value.status_code == 409


# ── N11: productos ───────────────────────────────────────────────────────────


async def test_n11_producto_toma_precio_de_catalogo_y_mueve_el_total(
    pg: asyncpg.Connection, esc: dict[str, Any]
) -> None:
    rid = await _reservacion(pg, esc)
    out = await reservacion_productos.crear(
        pg,
        ReservacionProductosCreate(
            reservacion_id=rid, producto_id=esc["pizza"], cantidad=6, precio_unitario=Decimal("1")
        ),
        _usuario(esc),
    )
    assert (out.precio_unitario, out.subtotal) == (Decimal("135.00"), Decimal("810.00"))
    fila = await _fila(pg, rid)
    assert fila["precio_productos"] == Decimal("810.00")
    assert fila["precio_total"] == TOTAL_BASE + Decimal("810")

    out = await reservacion_productos.actualizar(
        pg,
        out.id,
        ReservacionProductosUpdate(cantidad=2, precio_unitario=Decimal("1")),
        esc["usuario"],
    )
    assert (out.cantidad, out.precio_unitario) == (2, Decimal("135.00"))
    assert (await _fila(pg, rid))["precio_total"] == TOTAL_BASE + Decimal("270")

    await reservacion_productos.eliminar(pg, out.id, esc["usuario"])
    assert (await _fila(pg, rid))["precio_total"] == TOTAL_BASE


# ── M15: PATCH de invitados u horas ──────────────────────────────────────────


async def test_m15_patch_recalcula_extras_por_persona_y_por_hora(
    pg: asyncpg.Connection, esc: dict[str, Any]
) -> None:
    rid = await _reservacion(pg, esc)
    for extra in ("bolsita", "animador", "pastel"):
        await reservacion_extras.crear(
            pg, ReservacionExtrasCreate(reservacion_id=rid, extra_id=esc[extra]), esc["usuario"]
        )
    # 12 x 35 + 3 x 350 + 450 = 1920
    assert (await _fila(pg, rid))["precio_extras"] == Decimal("1920.00")

    # 15 niños y 4 h: pulseras 15 x 4 x 70 = 4200; extras 15 x 35 + 4 x 350 + 450 = 2375.
    out = await reservaciones.actualizar(
        pg,
        rid,
        ReservacionesUpdate(
            numero_personas=15,
            horas_reservadas=4,
            hora_fin="20:00",
            precio_total=Decimal("3800") + Decimal("4200") + Decimal("2375"),
        ),
        esc["usuario"],
    )
    assert out.precio_extras == Decimal("2375.00")
    assert out.precio_total == Decimal("10375.00")
    assert out.modificado_por == esc["usuario"]  # M18
    cantidades = dict(
        await pg.fetch(
            "SELECT extra_id, cantidad FROM reservacion_extras WHERE reservacion_id = $1", rid
        )
    )
    assert cantidades == {esc["bolsita"]: 15, esc["animador"]: 4, esc["pastel"]: 1}
