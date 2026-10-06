"""PIN de caja y apertura de turnos contra PostgreSQL real.

- Límite de intentos de PIN persistido en BD: N validaciones simultáneas con
  PIN equivocado (cada una con su conexión, como varios workers) registran
  exactamente MAX_FALLOS fallos y el resto recibe 429; después ni el PIN
  correcto pasa.
- El administrador que autoriza se busca solo en la sucursal del turno y debe
  tener permiso de autorizar cierres.
- Aperturas simultáneas no dan 500 por los índices únicos.
"""

import asyncio
import itertools
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
from app.core.security import hash_password
from app.schemas.caja import AbrirTurnoPayload
from app.services import pin_caja_service, turnos_caja_service
from app.services.pin_caja_service import (
    AutorizadorNoValidoError,
    PinBloqueadoError,
    PinInvalidoError,
)
from app.services.turnos_caja_service import CajaOcupadaError, TurnoYaAbiertoError

from tests.db.conftest import N_CONCURRENTES, Escenario, crear_apertura

PIN = "4821"
PIN_HASH = hash_password(PIN)
PASS_HASH = hash_password("contraseña-larga")

ROL_SISTEMA, ROL_ADMIN, ROL_CAJERO, ROL_COCINA = 1, 2, 3, 4

# cajas.numero es único por sucursal (uq_cajas_numero_sucursal_activo).
_NUMERO_CAJA = itertools.count(1)


async def _en_paralelo(
    pool: asyncpg.Pool, n: int, fn: Callable[[asyncpg.Connection, int], Awaitable[Any]]
) -> list[Any]:
    async def una(i: int) -> Any:
        async with pool.acquire() as conn:
            return await fn(conn, i)

    return await asyncio.gather(*(una(i) for i in range(n)), return_exceptions=True)


async def _usuario(
    pool: asyncpg.Pool,
    rol: int,
    sucursal_id: uuid.UUID | None = None,
    pin_hash: str | None = PIN_HASH,
) -> tuple[uuid.UUID, str]:
    sufijo = uuid.uuid4().hex[:10]
    email = f"u{rol}.{sufijo}@test.local"
    async with pool.acquire() as conn:
        usuario_id = await conn.fetchval(
            """
            INSERT INTO public.usuarios (email, password_hash, pin_hash, nombre_completo, rol)
            VALUES ($1, $2, $3, $4, $5) RETURNING id
            """,
            email,
            PASS_HASH,
            pin_hash,
            f"Usuario {sufijo}",
            rol,
        )
        if sucursal_id is not None:
            await conn.execute(
                "INSERT INTO public.usuarios_sucursal (usuario_id, sucursal_id) VALUES ($1, $2)",
                usuario_id,
                sucursal_id,
            )
    return usuario_id, email


async def _poner_pin(pool: asyncpg.Pool, usuario_id: uuid.UUID) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.usuarios SET pin_hash = $2, password_hash = $3 WHERE id = $1",
            usuario_id,
            PIN_HASH,
            PASS_HASH,
        )


async def _fallos(pool: asyncpg.Pool, usuario_id: uuid.UUID) -> int:
    async with pool.acquire() as conn:
        return int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM public.intentos_pin_fallidos WHERE usuario_id = $1",
                usuario_id,
            )
        )


async def _sucursal(pool: asyncpg.Pool) -> uuid.UUID:
    async with pool.acquire() as conn:
        return await conn.fetchval(  # type: ignore[no-any-return]
            "INSERT INTO public.sucursales (nombre) VALUES ($1) RETURNING id",
            f"Otra sucursal {uuid.uuid4().hex[:8]}",
        )


async def test_pines_equivocados_simultaneos_respetan_el_limite(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    await _poner_pin(pool, escenario.usuario_id)
    apertura_id = await crear_apertura(pool, escenario, Decimal("500"), estado="EN_CORTE")
    user_id = str(escenario.usuario_id)
    n = pin_caja_service.MAX_FALLOS + 3
    assert n <= N_CONCURRENTES

    resultados = await _en_paralelo(
        pool,
        n,
        lambda c, _i: turnos_caja_service.validar_pin_cajero(c, user_id, apertura_id, "0000"),
    )

    invalidos = [r for r in resultados if isinstance(r, PinInvalidoError)]
    bloqueados = [r for r in resultados if isinstance(r, PinBloqueadoError)]
    assert len(invalidos) == pin_caja_service.MAX_FALLOS, resultados
    assert len(bloqueados) == n - pin_caja_service.MAX_FALLOS, resultados
    assert await _fallos(pool, escenario.usuario_id) == pin_caja_service.MAX_FALLOS

    # Bloqueado: ni el PIN correcto pasa.
    async with pool.acquire() as conn:
        with pytest.raises(PinBloqueadoError) as exc:
            await turnos_caja_service.validar_pin_cajero(conn, user_id, apertura_id, PIN)
    assert exc.value.status_code == 429
    assert exc.value.headers and int(exc.value.headers["Retry-After"]) > 0


async def test_un_acierto_limpia_los_fallos(pool: asyncpg.Pool, escenario: Escenario) -> None:
    await _poner_pin(pool, escenario.usuario_id)
    apertura_id = await crear_apertura(pool, escenario, Decimal("500"), estado="EN_CORTE")
    user_id = str(escenario.usuario_id)
    async with pool.acquire() as conn:
        for _ in range(pin_caja_service.MAX_FALLOS - 1):
            with pytest.raises(PinInvalidoError):
                await turnos_caja_service.validar_pin_cajero(conn, user_id, apertura_id, "0000")
        # La contraseña tampoco vale: el cajero ya tiene PIN. Cuenta como fallo.
        with pytest.raises(PinInvalidoError):
            await turnos_caja_service.validar_pin_cajero(
                conn, user_id, apertura_id, "contraseña-larga"
            )
        assert await _fallos(pool, escenario.usuario_id) == pin_caja_service.MAX_FALLOS
    # Ya bloqueado: se simula que la ventana venció envejeciendo los fallos.
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE public.intentos_pin_fallidos SET creado = creado - INTERVAL '16 minutes'
            WHERE usuario_id = $1
            """,
            escenario.usuario_id,
        )
        resp = await turnos_caja_service.validar_pin_cajero(conn, user_id, apertura_id, PIN)
    assert resp["ok"] is True
    assert await _fallos(pool, escenario.usuario_id) == 0


async def test_autorizador_solo_de_la_sucursal_del_turno_y_con_permiso(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura_id = await crear_apertura(pool, escenario, Decimal("500"), estado="EN_CORTE")
    otra = await _sucursal(pool)
    _, admin_local = await _usuario(pool, ROL_ADMIN, escenario.sucursal_id)
    _, admin_otra = await _usuario(pool, ROL_ADMIN, otra)
    _, cajero_local = await _usuario(pool, ROL_CAJERO, escenario.sucursal_id)
    _, cocina_local = await _usuario(pool, ROL_COCINA, escenario.sucursal_id)
    _, sistema = await _usuario(pool, ROL_SISTEMA)

    async with pool.acquire() as conn:
        for email in (admin_otra, cajero_local, cocina_local, "no.existe@test.local"):
            with pytest.raises(AutorizadorNoValidoError):
                await turnos_caja_service.validar_pin_admin(conn, apertura_id, email, PIN)

        # Con PIN configurado la contraseña no vale.
        with pytest.raises(PinInvalidoError):
            await turnos_caja_service.validar_pin_admin(
                conn, apertura_id, admin_local, "contraseña-larga"
            )

        for email in (admin_local, sistema):
            resp = await turnos_caja_service.validar_pin_admin(conn, apertura_id, email, PIN)
            assert resp["ok"] is True and resp["token_pin"]


async def test_admin_con_varias_sucursales_autoriza_en_cualquiera_de_ellas(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    """Antes se tomaba UNA fila de usuarios_sucursal al azar (LIMIT 1) y un
    administrador con dos sucursales podía quedar rechazado en la suya."""
    apertura_id = await crear_apertura(pool, escenario, Decimal("500"), estado="EN_CORTE")
    otra = await _sucursal(pool)
    admin_id, admin = await _usuario(pool, ROL_ADMIN, otra)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO public.usuarios_sucursal (usuario_id, sucursal_id) VALUES ($1, $2)",
            admin_id,
            escenario.sucursal_id,
        )
        resp = await turnos_caja_service.validar_pin_admin(conn, apertura_id, admin, PIN)
    assert resp["ok"] is True


async def _caja_y_turno(pool: asyncpg.Pool, sucursal_id: uuid.UUID) -> tuple[str, str, str]:
    sufijo = uuid.uuid4().hex[:8]
    async with pool.acquire() as conn:
        caja_id = await conn.fetchval(
            "INSERT INTO public.cajas (sucursal_id, codigo, nombre, numero) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            sucursal_id,
            f"C-{sufijo}",
            f"Caja {sufijo}",
            next(_NUMERO_CAJA),
        )
        turno_id = await conn.fetchval(
            "INSERT INTO public.turnos (nombre, hora_inicio, hora_fin) "
            "VALUES ($1, '08:00', '16:00') RETURNING id",
            f"Turno {sufijo}",
        )
    return str(caja_id), f"C-{sufijo}", str(turno_id)


def _abrir(caja_id: str, turno_id: str, fondo: str = "500") -> AbrirTurnoPayload:
    return AbrirTurnoPayload(
        fondo_inicial=Decimal(fondo), caja_id=caja_id, turno_id=turno_id, pin=PIN
    )


async def _aperturas_activas(pool: asyncpg.Pool, columna: str, valor: Any) -> int:
    async with pool.acquire() as conn:
        return int(
            await conn.fetchval(
                f"SELECT COUNT(*) FROM public.apertura_caja WHERE {columna} = $1 "
                "AND estado <> 'CERRADA'",
                valor,
            )
        )


async def test_aperturas_identicas_simultaneas_no_dan_500(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    await _poner_pin(pool, escenario.usuario_id)
    caja_id, _, turno_id = await _caja_y_turno(pool, escenario.sucursal_id)
    user_id = str(escenario.usuario_id)
    sucursal = str(escenario.sucursal_id)

    resultados = await _en_paralelo(
        pool,
        N_CONCURRENTES,
        lambda c, _i: turnos_caja_service.abrir_turno(
            c, user_id, sucursal, _abrir(caja_id, turno_id)
        ),
    )

    errores = [r for r in resultados if isinstance(r, BaseException)]
    assert errores == [], errores
    # Todas devuelven el mismo turno: el reintento idéntico es idempotente.
    assert len({r.id for r in resultados}) == 1
    assert await _aperturas_activas(pool, "cajero_id", escenario.usuario_id) == 1


async def test_aperturas_simultaneas_en_cajas_distintas_dan_una_y_409(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    await _poner_pin(pool, escenario.usuario_id)
    cajas = [await _caja_y_turno(pool, escenario.sucursal_id) for _ in range(N_CONCURRENTES)]
    user_id = str(escenario.usuario_id)
    sucursal = str(escenario.sucursal_id)

    resultados = await _en_paralelo(
        pool,
        N_CONCURRENTES,
        lambda c, i: turnos_caja_service.abrir_turno(
            c, user_id, sucursal, _abrir(cajas[i][0], cajas[i][2])
        ),
    )

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    errores = [r for r in resultados if isinstance(r, BaseException)]
    assert len(exitos) == 1
    assert all(isinstance(e, TurnoYaAbiertoError) for e in errores), errores
    assert await _aperturas_activas(pool, "cajero_id", escenario.usuario_id) == 1


async def test_cajeros_distintos_abriendo_la_misma_caja_dan_una_y_409(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    caja_id, _, turno_id = await _caja_y_turno(pool, escenario.sucursal_id)
    cajeros = [
        str((await _usuario(pool, ROL_CAJERO, escenario.sucursal_id))[0])
        for _ in range(N_CONCURRENTES)
    ]
    sucursal = str(escenario.sucursal_id)

    resultados = await _en_paralelo(
        pool,
        N_CONCURRENTES,
        lambda c, i: turnos_caja_service.abrir_turno(
            c, cajeros[i], sucursal, _abrir(caja_id, turno_id)
        ),
    )

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    errores = [r for r in resultados if isinstance(r, BaseException)]
    assert len(exitos) == 1
    assert all(isinstance(e, CajaOcupadaError) for e in errores), errores
    assert all(e.status_code == 409 for e in errores)
    assert await _aperturas_activas(pool, "caja_id", uuid.UUID(caja_id)) == 1


async def test_abrir_con_turno_abierto_valida_pin_y_rechaza_otra_caja(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    """No devuelve 201 con el turno existente sin validar PIN ni caja."""
    await _poner_pin(pool, escenario.usuario_id)
    caja1, _, turno_id = await _caja_y_turno(pool, escenario.sucursal_id)
    caja2, _, _ = await _caja_y_turno(pool, escenario.sucursal_id)
    user_id = str(escenario.usuario_id)
    sucursal = str(escenario.sucursal_id)
    async with pool.acquire() as conn:
        abierto = await turnos_caja_service.abrir_turno(
            conn, user_id, sucursal, _abrir(caja1, turno_id)
        )
        malo = _abrir(caja2, turno_id).model_copy(update={"pin": "0000"})
        with pytest.raises(PinInvalidoError):
            await turnos_caja_service.abrir_turno(conn, user_id, sucursal, malo)
        with pytest.raises(TurnoYaAbiertoError):
            await turnos_caja_service.abrir_turno(conn, user_id, sucursal, _abrir(caja2, turno_id))
        with pytest.raises(TurnoYaAbiertoError):
            await turnos_caja_service.abrir_turno(
                conn, user_id, sucursal, _abrir(caja1, turno_id, fondo="900")
            )
        mismo = await turnos_caja_service.abrir_turno(
            conn, user_id, sucursal, _abrir(caja1, turno_id)
        )
    assert mismo.id == abierto.id
