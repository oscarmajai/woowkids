"""Precisión y rangos de inventario contra PostgreSQL real.

- El costo unitario se guarda con 6 decimales en insumos, capas y líneas de
  compra (migración 097): con 2 (insumos) o 4 (capas), en insumos por gramo o
  mililitro el error llegaba a ±6 %.
- Una línea válida en su unidad que, convertida a la unidad base, no cabe en el
  stock responde 422 al crear la compra, en vez de 500 al recibir."""

from decimal import Decimal

import asyncpg
import pytest
from app.exceptions.inventario import CantidadFueraDeRangoError
from app.repositories import compra_repository
from app.services import compra_service

from tests.db.conftest import Escenario
from tests.db.inventario_datos import crear_compra, crear_insumo, linea, unidad


async def test_costo_unitario_conserva_seis_decimales(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        ml = await unidad(conn, "ml")
        # Aceite: 1000 ml iniciales a $0.042692/ml (antes se guardaba 0.04).
        insumo_id = await crear_insumo(
            conn, escenario, codigo_unidad="ml", stock="1000", costo="0.042692"
        )
        assert await conn.fetchval(
            "SELECT costo_unitario FROM public.insumos WHERE id = $1", insumo_id
        ) == Decimal("0.042692")

        # Compra en ml a $0.123456/ml: la línea y la capa guardan el costo exacto.
        compra_id = await crear_compra(conn, escenario, [linea(insumo_id, ml, "1000", "0.123456")])
        detalle = (await compra_repository.listar_detalles(conn, compra_id))[0]
        assert detalle["costo_unitario"] == Decimal("0.123456")
        await compra_service.recibir(conn, compra_id, escenario.usuario_id)

        capas = await conn.fetch(
            "SELECT costo_unitario FROM public.capas_costo_insumo "
            "WHERE insumo_id = $1 ORDER BY secuencia",
            insumo_id,
        )
        assert [c["costo_unitario"] for c in capas] == [Decimal("0.042692"), Decimal("0.123456")]
        # Promedio ponderado (1000 * 0.042692 + 1000 * 0.123456) / 2000 = 0.083074.
        assert await conn.fetchval(
            "SELECT costo_unitario FROM public.insumos WHERE id = $1", insumo_id
        ) == Decimal("0.083074")


async def test_linea_que_desborda_al_convertir_a_unidad_base_responde_422(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        kg = await unidad(conn, "kg")
        insumo_id = await crear_insumo(conn, escenario, codigo_unidad="g")
        # 9,999,999 kg = 9,999,999,000 g: no cabe en stock_actual numeric(12,3).
        with pytest.raises(CantidadFueraDeRangoError) as exc:
            await crear_compra(conn, escenario, [linea(insumo_id, kg, "9999999", "1")])
        assert exc.value.status_code == 422
