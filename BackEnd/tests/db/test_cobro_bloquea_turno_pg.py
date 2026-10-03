"""N1 contra PostgreSQL real: un cobro ya no entra a la mitad del inicio de
un conteo o de un cierre. Antes, el cobro validaba el turno ABIERTA fuera
de cualquier bloqueo (dependencia apertura_operando_id) y registraba la
venta aunque el turno ya estuviera EN_CORTE; ahora la transacción del cobro
toma un FOR SHARE de la apertura y vuelve a validar."""

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from app.repositories import caja_repository
from app.services import turnos_caja_service
from fastapi import HTTPException

from tests.db.conftest import N_CONCURRENTES
from tests.db.pos_fixtures import (
    ESPERA,
    Pos,
    _cobrar,
    _estado_y_ventas,
    _venta,
    crear_pos,
)


@pytest_asyncio.fixture
async def pos(pool: asyncpg.Pool) -> Pos:
    return await crear_pos(pool)


# ── N1 ────────────────────────────────────────────────────────────────────────


async def test_el_conteo_espera_a_que_termine_un_cobro_en_curso(
    pool: asyncpg.Pool, pos: Pos
) -> None:
    async with pool.acquire() as conn_cobro, pool.acquire() as conn_conteo:
        tx = conn_cobro.transaction()
        await tx.start()
        await turnos_caja_service.bloquear_turno_para_cobro(conn_cobro, pos.apertura)

        conteo = asyncio.create_task(
            turnos_caja_service.iniciar_conteo(conn_conteo, str(pos.cajero), pos.apertura)
        )
        await asyncio.sleep(ESPERA)
        assert not conteo.done(), "el conteo no debe empezar con un cobro a medias"

        await caja_repository.registrar_movimiento_caja(
            conn_cobro,
            apertura_caja_id=pos.apertura,
            tipo_movimiento="O",
            referencia_id=str(uuid.uuid4()),
            metodo_pago_id=str(pos.efectivo),
            monto=Decimal("95"),
        )
        await tx.commit()
        turno = await conteo

    assert turno.estado == "EN_CONTEO"
    assert await _estado_y_ventas(pool, pos.apertura) == ("EN_CORTE", 1)


async def test_un_cobro_que_llega_durante_el_inicio_del_conteo_no_se_registra(
    pool: asyncpg.Pool, pos: Pos
) -> None:
    async with pool.acquire() as conn_conteo, pool.acquire() as conn_cobro:
        tx = conn_conteo.transaction()
        await tx.start()
        await caja_repository.bloquear_apertura(conn_conteo, pos.apertura)
        await caja_repository.actualizar_estado_apertura(conn_conteo, pos.apertura, "EN_CORTE")

        cobro = asyncio.create_task(_cobrar(conn_cobro, pos, _venta(pos, [(pos.efectivo, "95")])))
        await asyncio.sleep(ESPERA)
        assert not cobro.done(), "el cobro debe esperar a que la transición confirme"

        await tx.commit()
        with pytest.raises(HTTPException) as exc_info:
            await cobro

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "TURNO_NO_ABIERTO"
    assert await _estado_y_ventas(pool, pos.apertura) == ("EN_CORTE", 0)
    async with pool.acquire() as conn:
        comandas = await conn.fetchval(
            "SELECT COUNT(*) FROM public.comandas WHERE sucursal_id = $1", pos.sucursal
        )
    assert comandas == 0


async def test_cobros_simultaneos_del_mismo_turno_pasan_todos(pool: asyncpg.Pool, pos: Pos) -> None:
    async def uno(_i: int) -> Any:
        async with pool.acquire() as conn:
            return await _cobrar(conn, pos, _venta(pos, [(pos.efectivo, "95")]))

    resultados = await asyncio.gather(
        *(uno(i) for i in range(N_CONCURRENTES)), return_exceptions=True
    )

    assert [r for r in resultados if isinstance(r, BaseException)] == []
    assert await _estado_y_ventas(pool, pos.apertura) == ("ABIERTA", N_CONCURRENTES)


async def test_cobros_e_inicio_de_conteo_simultaneos_no_dejan_ventas_despues_del_corte(
    pool: asyncpg.Pool, pos: Pos
) -> None:
    """Toda venta registrada entró antes del corte: ninguna movida 'O' con la
    apertura ya EN_CORTE salvo las que confirmaron antes de la transición."""

    async def op(i: int) -> Any:
        async with pool.acquire() as conn:
            if i == N_CONCURRENTES // 2:
                return await turnos_caja_service.iniciar_conteo(conn, str(pos.cajero), pos.apertura)
            return await _cobrar(conn, pos, _venta(pos, [(pos.efectivo, "95")]))

    resultados = await asyncio.gather(
        *(op(i) for i in range(N_CONCURRENTES)), return_exceptions=True
    )

    errores = [r for r in resultados if isinstance(r, BaseException)]
    assert all(
        isinstance(e, HTTPException) and e.detail["code"] == "TURNO_NO_ABIERTO" for e in errores
    )
    cobros_ok = N_CONCURRENTES - 1 - len(errores)
    async with pool.acquire() as conn:
        modificado = await conn.fetchval(
            "SELECT modificado FROM public.apertura_caja WHERE id = $1", uuid.UUID(pos.apertura)
        )
        despues = await conn.fetchval(
            "SELECT COUNT(*) FROM public.movimientos_caja "
            "WHERE apertura_caja_id = $1 AND tipo_movimiento = 'O' AND creado > $2",
            uuid.UUID(pos.apertura),
            modificado,
        )
    assert await _estado_y_ventas(pool, pos.apertura) == ("EN_CORTE", cobros_ok)
    assert despues == 0
