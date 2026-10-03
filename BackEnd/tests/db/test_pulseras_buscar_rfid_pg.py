"""B14: la consulta de pulsera por RFID distingue libre, usada, inactiva e
inexistente contra PostgreSQL real, y no ve pulseras de otra sucursal."""

import uuid

import asyncpg
import pytest
from app.repositories import pulseras as pulseras_repository

from tests.db.conftest import Escenario


async def _crear_pulsera(
    conn: asyncpg.Connection, sucursal_id: uuid.UUID, rfid: str, activo: bool = True
) -> uuid.UUID:
    return await conn.fetchval(
        "INSERT INTO public.pulseras (sucursal_id, pulsera_rfid, activo) "
        "VALUES ($1, $2, $3) RETURNING id",
        sucursal_id,
        rfid,
        activo,
    )


async def _asignar_a_nino(
    conn: asyncpg.Connection, sucursal_id: uuid.UUID, pulsera_id: uuid.UUID
) -> None:
    producto_id = await conn.fetchval(
        "INSERT INTO public.productos (sucursal_id, nombre, precio_unitario, tipo) "
        "VALUES ($1, 'Estancia', 150, 'E') RETURNING id",
        sucursal_id,
    )
    tutor_id = await conn.fetchval(
        "INSERT INTO public.tutores (sucursal_id, nombre_completo, telefono) "
        "VALUES ($1, 'Tutor Prueba', '3300000001') RETURNING id",
        sucursal_id,
    )
    nino_id = await conn.fetchval(
        "INSERT INTO public.ninos (sucursal_id, nombre_completo, edad) "
        "VALUES ($1, 'Niño Prueba', 6) RETURNING id",
        sucursal_id,
    )
    registro_id = await conn.fetchval(
        "INSERT INTO public.registros (sucursal_id, tutores_id) VALUES ($1, $2) RETURNING id",
        sucursal_id,
        tutor_id,
    )
    await conn.execute(
        """
        INSERT INTO public.detalles_registro
            (sucursal_id, registros_id, ninos_id, pulseras_id, productos_id, cantidad, precio,
             parentesco, entrada, salida_esperada)
        VALUES ($1, $2, $3, $4, $5, 1, 150, 'Madre', NOW(), NOW() + INTERVAL '1 hour')
        """,
        sucursal_id,
        registro_id,
        nino_id,
        pulsera_id,
        producto_id,
    )


@pytest.mark.asyncio
async def test_buscar_por_rfid_distingue_estados(pool: asyncpg.Pool, escenario: Escenario):
    suc = escenario.sucursal_id
    async with pool.acquire() as conn:
        await _crear_pulsera(conn, suc, "WK-0000001")
        usada_id = await _crear_pulsera(conn, suc, "WK-0000002")
        await _crear_pulsera(conn, suc, "WK-0000003", activo=False)
        await _asignar_a_nino(conn, suc, usada_id)

        libre = await pulseras_repository.buscar_por_rfid(conn, suc, "WK-0000001")
        usada = await pulseras_repository.buscar_por_rfid(conn, suc, "WK-0000002")
        inactiva = await pulseras_repository.buscar_por_rfid(conn, suc, "WK-0000003")
        inexistente = await pulseras_repository.buscar_por_rfid(conn, suc, "WK-0000099")

    assert libre is not None and libre["usada"] is False and libre["activo"] is True
    assert usada is not None and usada["usada"] is True
    assert inactiva is not None and inactiva["activo"] is False and inactiva["usada"] is False
    assert inexistente is None


@pytest.mark.asyncio
async def test_buscar_por_rfid_no_ve_pulseras_de_otra_sucursal(
    pool: asyncpg.Pool, escenario: Escenario
):
    async with pool.acquire() as conn:
        otra_suc = await conn.fetchval(
            "INSERT INTO public.sucursales (nombre) VALUES ($1) RETURNING id",
            f"Otra sucursal {uuid.uuid4().hex[:10]}",
        )
        await _crear_pulsera(conn, otra_suc, "WK-0000005")

        resultado = await pulseras_repository.buscar_por_rfid(
            conn, escenario.sucursal_id, "WK-0000005"
        )

    assert resultado is None
