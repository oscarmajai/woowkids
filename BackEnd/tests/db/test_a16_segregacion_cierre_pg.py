"""A16 contra PostgreSQL real: segregación de funciones en el cierre de caja.

- Un administrador que abrió caja no autoriza su propio cierre: lo autoriza
  otro administrador de la sucursal o un AdministradorSistema.
- El token del PIN de administrador guarda su propósito (migración 109): el de
  cancelar una orden no cierra la caja, ni al revés, y el rechazo no lo consume.
"""

import json
import uuid
from decimal import Decimal

import asyncpg
import pytest
from app.core.config import settings
from app.core.security import hash_password
from app.exceptions import PinTokenPropositoError
from app.schemas.caja import ConfirmarCierrePayload, RevisionAdminPayload
from app.services import turnos_caja_service
from app.services.pin_caja_service import (
    PROPOSITO_CANCELAR,
    PROPOSITO_CERRAR,
    AutorizadorEsDuenoTurnoError,
    AutorizadorNoValidoError,
)

from tests.db.conftest import Escenario, crear_apertura

PIN = "4821"
PIN_HASH = hash_password(PIN)
PASSWORD = "contraseña-larga"
PASS_HASH = hash_password(PASSWORD)

ROL_SISTEMA, ROL_ADMIN = 1, 2


async def _usuario(
    pool: asyncpg.Pool,
    rol: int,
    sucursal_id: uuid.UUID | None,
    pin_hash: str | None = PIN_HASH,
) -> tuple[uuid.UUID, str]:
    sufijo = uuid.uuid4().hex[:10]
    email = f"a16.{rol}.{sufijo}@test.local"
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


async def _turno_de_admin_en_corte(
    pool: asyncpg.Pool, escenario: Escenario
) -> tuple[str, uuid.UUID, str]:
    """Turno EN_CORTE, con el conteo ya enviado, abierto por un Administrador
    de la sucursal del escenario. Devuelve (apertura_id, dueño_id, dueño_email)."""
    dueno_id, dueno_email = await _usuario(pool, ROL_ADMIN, escenario.sucursal_id)
    apertura_id = await crear_apertura(
        pool,
        Escenario(sucursal_id=escenario.sucursal_id, usuario_id=dueno_id),
        Decimal("500"),
        estado="EN_CORTE",
    )
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE public.apertura_caja SET monto_declarado = 500, conteo_json = $2
            WHERE id = $1
            """,
            uuid.UUID(apertura_id),
            json.dumps({"desglose_efectivo": {"total": "500"}, "metodos_pago": []}),
        )
    return apertura_id, dueno_id, dueno_email


async def _otra_sucursal(pool: asyncpg.Pool) -> uuid.UUID:
    async with pool.acquire() as conn:
        return await conn.fetchval(  # type: ignore[no-any-return]
            "INSERT INTO public.sucursales (nombre) VALUES ($1) RETURNING id",
            f"Otra sucursal A16 {uuid.uuid4().hex[:8]}",
        )


async def _revisar(
    conn: asyncpg.Connection, apertura_id: str, dueno_id: uuid.UUID, email: str, secreto: str
) -> object:
    return await turnos_caja_service.autenticar_admin_revision(
        conn,
        str(dueno_id),
        RevisionAdminPayload(turno_id=apertura_id, admin_email=email, admin_password=secreto),
    )


async def _usado(pool: asyncpg.Pool, token: str) -> bool:
    async with pool.acquire() as conn:
        return bool(
            await conn.fetchval("SELECT usado FROM public.pin_tokens WHERE token = $1", token)
        )


async def test_revision_del_cierre_de_un_admin_la_autoriza_otro(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura_id, dueno_id, dueno_email = await _turno_de_admin_en_corte(pool, escenario)
    otro_id, otro_admin = await _usuario(pool, ROL_ADMIN, escenario.sucursal_id)
    _, admin_otra_sucursal = await _usuario(pool, ROL_ADMIN, await _otra_sucursal(pool))
    sistema_id, sistema = await _usuario(pool, ROL_SISTEMA, None)

    async with pool.acquire() as conn:
        with pytest.raises(AutorizadorEsDuenoTurnoError) as exc:
            await _revisar(conn, apertura_id, dueno_id, dueno_email, PIN)
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "AUTORIZADOR_ES_DUENO_TURNO"

        with pytest.raises(AutorizadorNoValidoError):
            await _revisar(conn, apertura_id, dueno_id, admin_otra_sucursal, PIN)

        await _revisar(conn, apertura_id, dueno_id, otro_admin, PIN)
        jti = await conn.fetchval(
            "SELECT token_admin_jti FROM public.apertura_caja WHERE id = $1",
            uuid.UUID(apertura_id),
        )
        assert str(jti) == str(otro_id)

        # Un AdministradorSistema (sin sucursal) también autoriza.
        await _revisar(conn, apertura_id, dueno_id, sistema, PIN)
        jti = await conn.fetchval(
            "SELECT token_admin_jti FROM public.apertura_caja WHERE id = $1",
            uuid.UUID(apertura_id),
        )
        assert str(jti) == str(sistema_id)


async def test_pin_admin_para_cerrar_no_lo_da_el_dueno_pero_si_para_cancelar(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura_id, _, dueno_email = await _turno_de_admin_en_corte(pool, escenario)
    async with pool.acquire() as conn:
        with pytest.raises(AutorizadorEsDuenoTurnoError):
            await turnos_caja_service.validar_pin_admin(
                conn, apertura_id, dueno_email, PIN, proposito=PROPOSITO_CERRAR
            )
        # La regla es del cierre; autorizar cancelaciones no cambia (fuera de A16).
        resp = await turnos_caja_service.validar_pin_admin(
            conn, apertura_id, dueno_email, PIN, proposito=PROPOSITO_CANCELAR
        )
        proposito = await conn.fetchval(
            "SELECT proposito FROM public.pin_tokens WHERE token = $1", resp["token_pin"]
        )
    assert proposito == PROPOSITO_CANCELAR


async def test_tokens_de_admin_no_se_cruzan_entre_cancelar_y_cerrar(
    pool: asyncpg.Pool, escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "exigir_pin_token", True)
    apertura_id, dueno_id, _ = await _turno_de_admin_en_corte(pool, escenario)
    _, otro_admin = await _usuario(pool, ROL_ADMIN, escenario.sucursal_id)

    async with pool.acquire() as conn:
        await _revisar(conn, apertura_id, dueno_id, otro_admin, PIN)
        cajero = await turnos_caja_service.validar_pin_cajero(conn, str(dueno_id), apertura_id, PIN)
        cancelar = await turnos_caja_service.validar_pin_admin(
            conn, apertura_id, otro_admin, PIN, proposito=PROPOSITO_CANCELAR
        )
        cerrar = await turnos_caja_service.validar_pin_admin(
            conn, apertura_id, otro_admin, PIN, proposito=PROPOSITO_CERRAR
        )

        # Token de cancelar presentado para cerrar: rechazado y nada se consume.
        with pytest.raises(PinTokenPropositoError) as exc:
            await turnos_caja_service.confirmar_cierre(
                conn,
                str(dueno_id),
                ConfirmarCierrePayload(
                    turno_id=apertura_id,
                    token_pin_cajero=cajero["token_pin"],
                    token_pin_admin=cancelar["token_pin"],
                ),
            )
        assert exc.value.detail["code"] == "PIN_TOKEN_PROPOSITO_INVALIDO"

        # Token de cerrar presentado para cancelar/devolver una orden: rechazado.
        with pytest.raises(PinTokenPropositoError):
            async with conn.transaction():
                await turnos_caja_service.consumir_token_pin_admin(
                    conn, cerrar["token_pin"], apertura_id
                )

    for token in (cajero["token_pin"], cancelar["token_pin"], cerrar["token_pin"]):
        assert not await _usado(pool, token)

    # Con los tokens correctos, el cierre pasa.
    async with pool.acquire() as conn:
        resp = await turnos_caja_service.confirmar_cierre(
            conn,
            str(dueno_id),
            ConfirmarCierrePayload(
                turno_id=apertura_id,
                token_pin_cajero=cajero["token_pin"],
                token_pin_admin=cerrar["token_pin"],
            ),
        )
        estado = await conn.fetchval(
            "SELECT estado FROM public.apertura_caja WHERE id = $1", uuid.UUID(apertura_id)
        )
    assert resp.estado == "CERRADO"
    assert estado == "CERRADA"
    assert await _usado(pool, cerrar["token_pin"])
    assert not await _usado(pool, cancelar["token_pin"])
