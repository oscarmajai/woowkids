"""Contra PostgreSQL real: `PATCH activo=false` sobre una compra recibida
responde 409 en vez de 200 sin efecto (seguiría en el listado y el stock no se
revertiría)."""

import asyncpg
import pytest
from app.exceptions import Conflicto
from app.schemas.compra import CompraUpdate
from app.services import compra_service

from tests.db.conftest import Escenario
from tests.db.inventario_datos import crear_compra, crear_insumo, linea, unidad


async def test_compra_recibida_no_acepta_activo_false(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        pza = await unidad(conn, "pza")
        insumo_id = await crear_insumo(conn, escenario)
        compra_id = await crear_compra(conn, escenario, [linea(insumo_id, pza, "4", "1")])
        await compra_service.recibir(conn, compra_id, escenario.usuario_id)

        with pytest.raises(Conflicto) as exc:
            await compra_service.actualizar(conn, compra_id, CompraUpdate(activo=False))
        assert exc.value.status_code == 409
        assert (
            await conn.fetchval("SELECT activo FROM public.compras WHERE id = $1", compra_id)
            is True
        )

        # Las notas de una compra recibida se siguen pudiendo editar.
        out = await compra_service.actualizar(conn, compra_id, CompraUpdate(notas="Factura 12"))
        assert out.notas == "Factura 12"
