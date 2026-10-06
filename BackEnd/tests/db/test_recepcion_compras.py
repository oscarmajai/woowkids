"""Recepción parcial de compras contra PostgreSQL real.

- Una línea en 0 (o ausente de la lista) no se recibe: "línea ausente" no
  significa "todo lo pendiente".
- Pedir más de lo pendiente responde 422 en vez de recibir lo pendiente en
  silencio."""

import uuid
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
from app.exceptions import RecepcionInvalidaError
from app.schemas.compra import LineaRecepcion, RecibirCompraRequest
from app.services import compra_service

from tests.db.conftest import Escenario


async def _crear_compra_dos_lineas(
    pool: asyncpg.Pool, esc: Escenario
) -> tuple[uuid.UUID, dict[str, uuid.UUID], dict[str, uuid.UUID]]:
    """Compra pendiente con dos líneas de 10 pza (Jamón y Aceite, stock 0).
    Devuelve (compra_id, {nombre: detalle_id}, {nombre: insumo_id})."""
    sufijo = uuid.uuid4().hex[:8]
    detalles: dict[str, uuid.UUID] = {}
    insumos: dict[str, uuid.UUID] = {}
    async with pool.acquire() as conn:
        pza = await conn.fetchval("SELECT id FROM public.unidades_medida WHERE codigo = 'pza'")
        proveedor_id = await conn.fetchval(
            "INSERT INTO public.proveedores (sucursal_id, nombre) VALUES ($1, $2) RETURNING id",
            esc.sucursal_id,
            f"Proveedor {sufijo}",
        )
        compra_id = await conn.fetchval(
            "INSERT INTO public.compras (sucursal_id, proveedor_id, total) "
            "VALUES ($1, $2, 10) RETURNING id",
            esc.sucursal_id,
            proveedor_id,
        )
        for nombre in ("jamon", "aceite"):
            insumos[nombre] = await conn.fetchval(
                """
                INSERT INTO public.insumos (sucursal_id, nombre, unidad_base_id, unidad_compra_id)
                VALUES ($1, $2, $3, $3) RETURNING id
                """,
                esc.sucursal_id,
                f"{nombre} {sufijo}",
                pza,
            )
            detalles[nombre] = await conn.fetchval(
                """
                INSERT INTO public.detalle_compras
                    (compra_id, insumo_id, unidad_medida_id, cantidad, costo_unitario)
                VALUES ($1, $2, $3, 10, 0.5) RETURNING id
                """,
                compra_id,
                insumos[nombre],
                pza,
            )
    return compra_id, detalles, insumos


async def _estado(
    pool: asyncpg.Pool, compra_id: uuid.UUID, insumos: dict[str, uuid.UUID]
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        estado: dict[str, Any] = {
            "estado": await conn.fetchval(
                "SELECT estado FROM public.compras WHERE id = $1", compra_id
            ),
            "movimientos": await conn.fetchval(
                "SELECT COUNT(*) FROM public.movimientos_inventario WHERE referencia_id = $1",
                compra_id,
            ),
        }
        for nombre, insumo_id in insumos.items():
            estado[nombre] = await conn.fetchval(
                "SELECT stock_actual FROM public.insumos WHERE id = $1", insumo_id
            )
            estado[f"{nombre}_recibido"] = await conn.fetchval(
                "SELECT cantidad_recibida FROM public.detalle_compras "
                "WHERE compra_id = $1 AND insumo_id = $2",
                compra_id,
                insumo_id,
            )
    return estado


async def test_recepcion_parcial_con_una_linea_en_cero_no_la_recibe(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    compra_id, detalles, insumos = await _crear_compra_dos_lineas(pool, escenario)
    body = RecibirCompraRequest(
        lineas=[
            LineaRecepcion(detalle_id=detalles["jamon"], cantidad=Decimal("4")),
            LineaRecepcion(detalle_id=detalles["aceite"], cantidad=Decimal("0")),
        ]
    )

    async with pool.acquire() as conn:
        out = await compra_service.recibir(conn, compra_id, escenario.usuario_id, body)

    assert out.estado == "PARCIAL"
    assert await _estado(pool, compra_id, insumos) == {
        "estado": "PARCIAL",
        "movimientos": 1,
        "jamon": 4,
        "jamon_recibido": 4,
        "aceite": 0,
        "aceite_recibido": 0,
    }


async def test_recepcion_con_lista_trata_la_linea_ausente_como_cero(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    compra_id, detalles, insumos = await _crear_compra_dos_lineas(pool, escenario)
    body = RecibirCompraRequest(
        lineas=[LineaRecepcion(detalle_id=detalles["jamon"], cantidad=Decimal("10"))]
    )

    async with pool.acquire() as conn:
        await compra_service.recibir(conn, compra_id, escenario.usuario_id, body)

    estado = await _estado(pool, compra_id, insumos)
    assert (estado["estado"], estado["jamon"], estado["aceite"]) == ("PARCIAL", 10, 0)


async def test_recepcion_sin_lineas_sigue_recibiendo_todo_lo_pendiente(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    compra_id, _, insumos = await _crear_compra_dos_lineas(pool, escenario)

    async with pool.acquire() as conn:
        await compra_service.recibir(conn, compra_id, escenario.usuario_id, RecibirCompraRequest())

    estado = await _estado(pool, compra_id, insumos)
    assert (estado["estado"], estado["jamon"], estado["aceite"]) == ("R", 10, 10)


async def test_recepcion_excedida_responde_422_con_la_linea_y_no_toca_stock(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    compra_id, detalles, insumos = await _crear_compra_dos_lineas(pool, escenario)
    body = RecibirCompraRequest(
        lineas=[
            LineaRecepcion(detalle_id=detalles["jamon"], cantidad=Decimal("4")),
            LineaRecepcion(detalle_id=detalles["aceite"], cantidad=Decimal("50")),
        ]
    )

    async with pool.acquire() as conn:
        with pytest.raises(RecepcionInvalidaError) as exc:
            await compra_service.recibir(conn, compra_id, escenario.usuario_id, body)

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "RECEPCION_INVALIDA"
    assert exc.value.detail["linea"] == {
        "detalle_id": str(detalles["aceite"]),
        "insumo_nombre": exc.value.detail["linea"]["insumo_nombre"],
        "solicitado": "50",
        "pendiente": "10",
    }
    assert exc.value.detail["linea"]["insumo_nombre"].startswith("aceite")
    # Nada se aplicó, ni siquiera la línea válida que venía antes.
    assert await _estado(pool, compra_id, insumos) == {
        "estado": "P",
        "movimientos": 0,
        "jamon": 0,
        "jamon_recibido": 0,
        "aceite": 0,
        "aceite_recibido": 0,
    }


async def test_recepcion_excedida_sobre_lo_que_queda_de_una_parcial_responde_422(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    compra_id, detalles, insumos = await _crear_compra_dos_lineas(pool, escenario)
    primera = RecibirCompraRequest(
        lineas=[LineaRecepcion(detalle_id=detalles["jamon"], cantidad=Decimal("7"))]
    )
    segunda = RecibirCompraRequest(
        lineas=[LineaRecepcion(detalle_id=detalles["jamon"], cantidad=Decimal("7"))]
    )

    async with pool.acquire() as conn:
        await compra_service.recibir(conn, compra_id, escenario.usuario_id, primera)
        with pytest.raises(RecepcionInvalidaError) as exc:
            await compra_service.recibir(conn, compra_id, escenario.usuario_id, segunda)

    assert exc.value.detail["linea"]["pendiente"] == "3"
    estado = await _estado(pool, compra_id, insumos)
    assert (estado["estado"], estado["jamon"], estado["movimientos"]) == ("PARCIAL", 7, 1)
