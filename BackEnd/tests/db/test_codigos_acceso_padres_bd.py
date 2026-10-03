"""A17 / C6 contra PostgreSQL real (migración 076). Usa TEST_DATABASE_URL (una
BD desechable con sql/schema_maestro.sql cargado) y se salta si no existe.
Todo corre dentro de una transacción que se revierte al terminar."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from app.core.security import hash_codigo_acceso_padres
from app.repositories import codigos_acceso_padres
from app.repositories.fotos import get_registro_id_by_foto_ine
from app.services import padres_service

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL no definida")


@pytest_asyncio.fixture
async def conn_test():
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        yield conn
    finally:
        await tx.rollback()
        await conn.close()


async def _registro(conn: asyncpg.Connection, estado: str = "A"):
    sucursal_id = await conn.fetchval(
        """
        INSERT INTO sucursales (nombre, direccion, telefono, correo, clave)
        VALUES ('Prueba A17', 'x', '3310000099', $1, $2) RETURNING id
        """,
        f"{uuid4().hex[:8]}@prueba.dev",
        uuid4().hex[:6].upper(),
    )
    tutor_id = await conn.fetchval(
        "INSERT INTO tutores (sucursal_id, nombre_completo, telefono) "
        "VALUES ($1, 'Tutor', '5500000000') RETURNING id",
        sucursal_id,
    )
    registro_id = uuid4()
    await conn.execute(
        "INSERT INTO registros (id, sucursal_id, tutores_id, estado) VALUES ($1, $2, $3, $4)",
        registro_id,
        sucursal_id,
        tutor_id,
        estado,
    )
    return registro_id


async def test_codigo_vigente_revocado_y_expirado(conn_test):
    registro_id = await _registro(conn_test)

    codigo = await padres_service.emitir_codigo_acceso(conn_test, registro_id, None)
    guardado = await conn_test.fetchval(
        "SELECT codigo_hash FROM codigos_acceso_padres WHERE registro_id = $1", registro_id
    )
    assert guardado == hash_codigo_acceso_padres(codigo)
    assert guardado != codigo

    fila = await codigos_acceso_padres.get_registro_por_codigo(
        conn_test, hash_codigo_acceso_padres(codigo)
    )
    assert fila is not None and fila["registroId"] == registro_id

    # El UUID del registro ya no es un código.
    assert (
        await codigos_acceso_padres.get_registro_por_codigo(
            conn_test, hash_codigo_acceso_padres(str(registro_id))
        )
        is None
    )

    # Reemitir revoca el anterior.
    nuevo = await padres_service.emitir_codigo_acceso(conn_test, registro_id, None)
    assert (
        await codigos_acceso_padres.get_registro_por_codigo(
            conn_test, hash_codigo_acceso_padres(codigo)
        )
        is None
    )
    assert (
        await codigos_acceso_padres.get_registro_por_codigo(
            conn_test, hash_codigo_acceso_padres(nuevo)
        )
        is not None
    )

    # Expirado.
    await conn_test.execute(
        "UPDATE codigos_acceso_padres SET expira = $2 WHERE codigo_hash = $1",
        hash_codigo_acceso_padres(nuevo),
        datetime.now(UTC) - timedelta(seconds=1),
    )
    assert (
        await codigos_acceso_padres.get_registro_por_codigo(
            conn_test, hash_codigo_acceso_padres(nuevo)
        )
        is None
    )


async def test_codigo_de_registro_cerrado_no_vale(conn_test):
    registro_id = await _registro(conn_test)
    codigo = await padres_service.emitir_codigo_acceso(conn_test, registro_id, None)
    await conn_test.execute("UPDATE registros SET estado = 'C' WHERE id = $1", registro_id)
    assert (
        await codigos_acceso_padres.get_registro_por_codigo(
            conn_test, hash_codigo_acceso_padres(codigo)
        )
        is None
    )
    with pytest.raises(padres_service.TokenAccesoInvalidoError):
        await padres_service.get_padre_dashboard(conn_test, codigo)


async def test_dueno_de_la_ine_se_resuelve_por_la_ruta_guardada(conn_test):
    registro_id = await _registro(conn_test)
    ruta = f"uploads/identificaciones/{registro_id}.jpg"
    await conn_test.execute(
        "INSERT INTO fotos (registro_id, tipo, storage_url) VALUES ($1, 'I', $2)",
        registro_id,
        ruta,
    )
    assert await get_registro_id_by_foto_ine(conn_test, ruta) == registro_id
    assert await get_registro_id_by_foto_ine(conn_test, "uploads/identificaciones/x.jpg") is None
