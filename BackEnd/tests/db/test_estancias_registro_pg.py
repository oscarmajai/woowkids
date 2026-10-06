"""Estancias contra PostgreSQL real. Usa TEST_DATABASE_URL
(una BD desechable con sql/schema_maestro.sql cargado) y se salta si no existe.
Todo corre dentro de una transacción que se revierte al terminar.

- Reimprimir el comprobante revoca el código anterior del portal de padres.
- Con dos productos de estancia activos se elige siempre el más reciente.
- La referencia del pago de estancia se guarda (migración 104) y sale en
  el detalle del historial.
"""

import os
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from app.core.security import hash_codigo_acceso_padres
from app.repositories import codigos_acceso_padres
from app.repositories.pagos_comanda import pago_create
from app.repositories.producto_repository import get_producto_estancia_by_branch_id
from app.services import estancias, padres_service
from fastapi import HTTPException

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


async def _sucursal(conn: asyncpg.Connection) -> UUID:
    return await conn.fetchval(
        """
        INSERT INTO sucursales (nombre, direccion, telefono, correo, clave)
        VALUES ($1, 'x', '3310000099', $2, $3) RETURNING id
        """,
        f"Prueba Estancias {uuid4().hex[:6]}",
        f"{uuid4().hex[:8]}@prueba.dev",
        uuid4().hex[:6].upper(),
    )


async def _producto_estancia(
    conn: asyncpg.Connection, sucursal_id: UUID, creado: datetime, precio: str
) -> UUID:
    return await conn.fetchval(
        """
        INSERT INTO productos (nombre, precio_unitario, tipo, sucursal_id, creado,
                               config_estancia)
        VALUES ($1, $2, 'E', $3, $4, $5::jsonb) RETURNING id
        """,
        f"Estancia {uuid4().hex[:6]}",
        Decimal(precio),
        sucursal_id,
        creado,
        f'[{{"min_horas": 1, "max_horas": 5, "precio": {precio}}}]',
    )


async def _registro_con_nino(
    conn: asyncpg.Connection, sucursal_id: UUID, notas: str | None
) -> tuple[UUID, UUID]:
    tutor_id = await conn.fetchval(
        "INSERT INTO tutores (sucursal_id, nombre_completo, telefono) "
        "VALUES ($1, 'Ana Gómez', '3312345678') RETURNING id",
        sucursal_id,
    )
    registro_id = uuid4()
    await conn.execute(
        "INSERT INTO registros (id, sucursal_id, tutores_id, estado, total) "
        "VALUES ($1, $2, $3, 'A', 240)",
        registro_id,
        sucursal_id,
        tutor_id,
    )
    nino_id = await conn.fetchval(
        "INSERT INTO ninos (sucursal_id, nombre_completo, edad, notas) "
        "VALUES ($1, 'Leo Gómez', 5, $2) RETURNING id",
        sucursal_id,
        notas,
    )
    pulsera_id = await conn.fetchval(
        "INSERT INTO pulseras (sucursal_id, pulsera_rfid) VALUES ($1, $2) RETURNING id",
        sucursal_id,
        f"WK-{random.randint(0, 9_999_999):07d}",
    )
    producto_id = await _producto_estancia(conn, sucursal_id, datetime.now(UTC), "120")
    entrada = datetime.now(UTC)
    detalle_id = await conn.fetchval(
        """
        INSERT INTO detalles_registro (sucursal_id, registros_id, ninos_id, pulseras_id,
            productos_id, cantidad, precio, parentesco, entrada, salida_esperada)
        VALUES ($1, $2, $3, $4, $5, 2, 120, 'Madre', $6, $7) RETURNING id
        """,
        sucursal_id,
        registro_id,
        nino_id,
        pulsera_id,
        producto_id,
        entrada,
        entrada + timedelta(hours=2),
    )
    return registro_id, detalle_id


async def _vigente(conn: asyncpg.Connection, codigo: str) -> bool:
    fila = await codigos_acceso_padres.get_registro_por_codigo(
        conn, hash_codigo_acceso_padres(codigo)
    )
    return fila is not None


async def test_con_dos_productos_de_estancia_usa_el_mas_reciente(
    conn_test: asyncpg.Connection,
) -> None:
    sucursal_id = await _sucursal(conn_test)
    ahora = datetime.now(UTC)
    # El viejo se inserta primero: sin ORDER BY, LIMIT 1 lo devolvía a él.
    await _producto_estancia(conn_test, sucursal_id, ahora - timedelta(days=30), "90")
    reciente = await _producto_estancia(conn_test, sucursal_id, ahora, "150")

    for _ in range(5):
        fila = await get_producto_estancia_by_branch_id(conn_test, str(sucursal_id))
        assert fila is not None and fila["id"] == reciente

    await conn_test.execute("UPDATE productos SET activo = FALSE WHERE id = $1", reciente)
    fila = await get_producto_estancia_by_branch_id(conn_test, str(sucursal_id))
    assert fila is not None and fila["id"] != reciente


async def test_la_referencia_del_pago_se_guarda_y_sale_en_el_detalle(
    conn_test: asyncpg.Connection,
) -> None:
    from app.repositories import pago_repository

    sucursal_id = await _sucursal(conn_test)
    registro_id, _ = await _registro_con_nino(conn_test, sucursal_id, None)
    metodo_id = await conn_test.fetchval("SELECT id FROM metodos_pago ORDER BY nombre LIMIT 1")

    await pago_create(conn_test, sucursal_id, registro_id, metodo_id, 240.0, None, "VOUCHER-77")

    guardada = await conn_test.fetchval(
        "SELECT notas_pago FROM pagos_estancia WHERE registros_id = $1", registro_id
    )
    assert guardada == "VOUCHER-77"
    pagos = await conn_test.fetch(pago_repository._SELECT_DETALLE_PAGOS_ESTANCIA, registro_id)
    assert [p["notas_pago"] for p in pagos] == ["VOUCHER-77"]


async def test_reimprimir_revoca_el_qr_anterior(conn_test: asyncpg.Connection) -> None:
    sucursal_id = await _sucursal(conn_test)
    registro_id, _ = await _registro_con_nino(conn_test, sucursal_id, "Asma, trae inhalador")
    codigo_original = await padres_service.emitir_codigo_acceso(conn_test, registro_id, None)
    assert await _vigente(conn_test, codigo_original)

    datos = await estancias.reimprimir_comprobante(conn_test, registro_id, sucursal_id, None)

    assert datos["codigoAccesoPadres"] != codigo_original
    assert await _vigente(conn_test, datos["codigoAccesoPadres"])
    assert not await _vigente(conn_test, codigo_original)
    assert datos["tutor"] == "Ana Gómez"
    assert [n["notas"] for n in datos["ninos"]] == ["Asma, trae inhalador"]
    assert datos["total"] == 240.0


async def test_no_reimprime_si_todos_salieron_o_es_de_otra_sucursal(
    conn_test: asyncpg.Connection,
) -> None:
    sucursal_id = await _sucursal(conn_test)
    registro_id, detalle_id = await _registro_con_nino(conn_test, sucursal_id, None)

    with pytest.raises(HTTPException) as exc:
        await estancias.reimprimir_comprobante(
            conn_test, registro_id, await _sucursal(conn_test), None
        )
    assert exc.value.status_code == 404

    await conn_test.execute("UPDATE detalles_registro SET salida = now() WHERE id = $1", detalle_id)
    with pytest.raises(HTTPException) as exc:
        await estancias.reimprimir_comprobante(conn_test, registro_id, sucursal_id, None)
    assert exc.value.status_code == 409
    total_codigos = await conn_test.fetchval(
        "SELECT count(*) FROM codigos_acceso_padres WHERE registro_id = $1", registro_id
    )
    assert total_codigos == 0
