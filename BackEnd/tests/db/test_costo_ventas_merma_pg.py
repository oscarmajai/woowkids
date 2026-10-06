"""Contra PostgreSQL real: el faltante por conteo físico aparece en los KPI del
Costo de Ventas y el margen resta la merma."""

from decimal import Decimal

import asyncpg
from app.schemas.movimiento_inventario import ConteoFisicoCreate, MovimientoManualCreate
from app.services import inventario_service

from tests.db.conftest import Escenario
from tests.db.inventario_datos import crear_insumo


async def test_merma_por_conteo_fisico_entra_al_kpi_y_al_margen(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        insumo_id = await crear_insumo(conn, escenario, stock="100", costo="2")
        # Merma manual de 5 ($10) y faltante por conteo de 20 ($40).
        await inventario_service.registrar_ajuste_manual(
            conn,
            insumo_id,
            MovimientoManualCreate(tipo="M", cantidad=Decimal("5")),
            escenario.usuario_id,
        )
        await inventario_service.registrar_conteo_fisico(
            conn,
            insumo_id,
            ConteoFisicoCreate(stock_contado=Decimal("75")),
            escenario.usuario_id,
        )
        # Un sobrante posterior no reduce la merma del periodo.
        await inventario_service.registrar_conteo_fisico(
            conn,
            insumo_id,
            ConteoFisicoCreate(stock_contado=Decimal("76")),
            escenario.usuario_id,
        )

        resumen = await inventario_service.resumen_cogs(conn, escenario.sucursal_id)

    assert resumen.merma_manual == Decimal("10")
    assert resumen.merma_conteo == Decimal("40")
    assert resumen.merma == Decimal("50")
    assert resumen.ventas_totales == 0
    assert resumen.margen == Decimal("-50")
