"""C4: operaciones de caja que leen, validan y escriben el efectivo o el estado
de un turno, lanzadas en paralelo con conexiones distintas del pool. Antes del
arreglo, N retiros simultáneos pasaban todos la validación de efectivo
disponible (la caja quedaba en negativo) y N cierres simultáneos chocaban con
el índice único de cierre_caja (500 en vez de 409)."""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
from app.core.config import settings
from app.schemas.caja import (
    ConfirmarCierrePayload,
    ConteoPayload,
    DesgloseEfectivoPayload,
    RetiroParcialCreate,
    TipoDestinatario,
)
from app.services import turnos_caja_service
from app.services.turnos_caja_service import (
    EfectivoInsuficienteError,
    TransicionInvalidaError,
)

from tests.db.conftest import N_CONCURRENTES, Escenario, crear_apertura


async def _en_paralelo(
    pool: asyncpg.Pool, n: int, fn: Callable[[asyncpg.Connection, int], Awaitable[Any]]
) -> list[Any]:
    """Lanza `fn` n veces a la vez, cada una con su propia conexión del pool."""

    async def una(i: int) -> Any:
        async with pool.acquire() as conn:
            return await fn(conn, i)

    return await asyncio.gather(*(una(i) for i in range(n)), return_exceptions=True)


def _retiro(apertura_id: str, monto: str) -> RetiroParcialCreate:
    return RetiroParcialCreate(
        apertura_caja_id=apertura_id,
        tipo_destinatario=TipoDestinatario.EMPLEADO,
        monto=Decimal(monto),
    )


async def _disponible(pool: asyncpg.Pool, apertura_id: str) -> Decimal:
    async with pool.acquire() as conn:
        return await turnos_caja_service.efectivo_disponible_actual(conn, apertura_id)


async def test_retiros_simultaneos_no_dejan_la_caja_en_negativo(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura_id = await crear_apertura(pool, escenario, Decimal("1000.00"))
    user_id = str(escenario.usuario_id)

    resultados = await _en_paralelo(
        pool,
        N_CONCURRENTES,
        lambda c, _i: turnos_caja_service.crear_retiro(c, user_id, _retiro(apertura_id, "600")),
    )

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    rechazos = [r for r in resultados if isinstance(r, EfectivoInsuficienteError)]
    otros = [r for r in resultados if isinstance(r, BaseException) and r not in rechazos]
    assert otros == []
    assert len(exitos) == 1
    assert len(rechazos) == N_CONCURRENTES - 1
    assert await _disponible(pool, apertura_id) == Decimal("400.00")


async def test_retiros_simultaneos_pasan_solo_los_que_caben(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura_id = await crear_apertura(pool, escenario, Decimal("1000.00"))
    user_id = str(escenario.usuario_id)

    resultados = await _en_paralelo(
        pool,
        N_CONCURRENTES,
        lambda c, _i: turnos_caja_service.crear_retiro(c, user_id, _retiro(apertura_id, "300")),
    )

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    assert len(exitos) == 3
    assert all(
        isinstance(r, EfectivoInsuficienteError) for r in resultados if isinstance(r, BaseException)
    )
    assert await _disponible(pool, apertura_id) == Decimal("100.00")


async def test_retiros_e_ingresos_simultaneos_nunca_dejan_la_caja_en_negativo(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    from app.schemas.caja import IngresoEfectivoCreate

    apertura_id = await crear_apertura(pool, escenario, Decimal("500.00"))
    user_id = str(escenario.usuario_id)

    async def op(c: asyncpg.Connection, i: int) -> Any:
        if i % 2 == 0:
            return await turnos_caja_service.crear_retiro(c, user_id, _retiro(apertura_id, "400"))
        return await turnos_caja_service.crear_ingreso(
            c, user_id, IngresoEfectivoCreate(apertura_caja_id=apertura_id, monto=Decimal("100"))
        )

    resultados = await _en_paralelo(pool, N_CONCURRENTES, op)

    assert all(
        isinstance(r, EfectivoInsuficienteError) for r in resultados if isinstance(r, BaseException)
    )
    assert await _disponible(pool, apertura_id) >= Decimal("0")


async def test_iniciar_conteo_simultaneo_solo_transiciona_una_vez(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura_id = await crear_apertura(pool, escenario, Decimal("1000.00"))
    user_id = str(escenario.usuario_id)

    resultados = await _en_paralelo(
        pool,
        N_CONCURRENTES,
        lambda c, _i: turnos_caja_service.iniciar_conteo(c, user_id, apertura_id),
    )

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    assert len(exitos) == 1
    assert all(
        isinstance(r, TransicionInvalidaError) for r in resultados if isinstance(r, BaseException)
    )


async def test_enviar_conteo_simultaneo_no_sobrescribe_el_primero(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura_id = await crear_apertura(pool, escenario, Decimal("1000.00"), estado="EN_CORTE")
    user_id = str(escenario.usuario_id)

    def conteo(i: int) -> ConteoPayload:
        total = Decimal(100 + i)
        return ConteoPayload(
            turno_id=apertura_id,
            desglose_efectivo=DesgloseEfectivoPayload(total=total),
            metodos_pago=[],
            total_declarado=total,
        )

    resultados = await _en_paralelo(
        pool,
        N_CONCURRENTES,
        lambda c, i: turnos_caja_service.enviar_conteo(c, user_id, conteo(i)),
    )

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    assert len(exitos) == 1
    assert all(
        isinstance(r, TransicionInvalidaError) for r in resultados if isinstance(r, BaseException)
    )
    async with pool.acquire() as conn:
        fila = await conn.fetchrow(
            "SELECT monto_declarado, conteo_json FROM public.apertura_caja WHERE id = $1",
            uuid.UUID(apertura_id),
        )
    # El monto y el JSON guardados son del mismo envío (no una mezcla de dos).
    assert (
        Decimal(json.loads(fila["conteo_json"])["desglose_efectivo"]["total"])
        == (fila["monto_declarado"])
    )


async def test_confirmar_cierre_simultaneo_cierra_una_vez_y_el_resto_es_409(
    pool: asyncpg.Pool, escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "exigir_pin_token", False)
    apertura_id = await crear_apertura(pool, escenario, Decimal("1000.00"), estado="EN_CORTE")
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE public.apertura_caja
            SET monto_declarado = 1000, conteo_json = $2, token_admin_jti = $3
            WHERE id = $1
            """,
            uuid.UUID(apertura_id),
            json.dumps({"desglose_efectivo": {"total": "1000"}, "metodos_pago": []}),
            escenario.usuario_id,
        )
    user_id = str(escenario.usuario_id)

    resultados = await _en_paralelo(
        pool,
        N_CONCURRENTES,
        lambda c, _i: turnos_caja_service.confirmar_cierre(
            c, user_id, ConfirmarCierrePayload(turno_id=apertura_id)
        ),
    )

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    errores = [r for r in resultados if isinstance(r, BaseException)]
    assert len(exitos) == 1
    assert all(isinstance(e, TransicionInvalidaError) for e in errores), errores
    async with pool.acquire() as conn:
        estado = await conn.fetchval(
            "SELECT estado FROM public.apertura_caja WHERE id = $1", uuid.UUID(apertura_id)
        )
        cierres = await conn.fetchval(
            "SELECT COUNT(*) FROM public.cierre_caja WHERE apertura_caja_id = $1",
            uuid.UUID(apertura_id),
        )
    assert estado == "CERRADA"
    assert cierres == 1


async def test_el_bloqueo_de_la_apertura_no_frena_los_cobros_del_pos(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    """Mientras un retiro/cierre tiene bloqueada la apertura, un cobro (que solo
    inserta en movimientos_caja con llave foránea a la apertura) no espera."""
    from app.repositories.caja_repository import bloquear_apertura, registrar_movimiento_caja

    apertura_id = await crear_apertura(pool, escenario, Decimal("1000.00"))
    async with pool.acquire() as bloqueo, pool.acquire() as cobro:
        async with bloqueo.transaction():
            assert await bloquear_apertura(bloqueo, apertura_id) is not None
            async with cobro.transaction():
                await cobro.execute("SET LOCAL lock_timeout = '1s'")
                await registrar_movimiento_caja(
                    cobro,
                    apertura_caja_id=apertura_id,
                    tipo_movimiento="E",
                    referencia_id=apertura_id,
                    metodo_pago_id=None,
                    monto=Decimal("50"),
                    creado_por=str(escenario.usuario_id),
                )
            # Un segundo retiro sí espera al primero: no puede bloquear la fila.
            async with cobro.transaction():
                await cobro.execute("SET LOCAL lock_timeout = '200ms'")
                with pytest.raises(asyncpg.exceptions.LockNotAvailableError):
                    await bloquear_apertura(cobro, apertura_id)
