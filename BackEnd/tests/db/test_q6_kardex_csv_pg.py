"""Q6 contra PostgreSQL real: el kardex trae el nombre de quien registró el
movimiento y la zona de la sucursal (para el CSV en hora local)."""

import uuid
from decimal import Decimal

import asyncpg
import pytest
from app.repositories import movimiento_inventario_repository

pytestmark = pytest.mark.asyncio


async def _sucursal(conn: asyncpg.Connection, zona: str = "America/Mexico_City") -> uuid.UUID:
    sufijo = uuid.uuid4().hex[:10]
    sucursal_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO public.sucursales (nombre, correo, zona_horaria) VALUES ($1, $2, $3) "
        "RETURNING id",
        f"Sucursal Q6 {sufijo}",
        f"sucursal.{sufijo}@test.local",
        zona,
    )
    return sucursal_id


async def _usuario(conn: asyncpg.Connection, rol_id: int, nombre: str) -> uuid.UUID:
    sufijo = uuid.uuid4().hex[:10]
    usuario_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO public.usuarios (email, password_hash, nombre_completo, rol) "
        "VALUES ($1, 'x', $2, $3) RETURNING id",
        f"q6.{sufijo}@test.local",
        nombre,
        rol_id,
    )
    return usuario_id


async def test_kardex_trae_nombre_del_usuario_y_zona_de_la_sucursal(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        sucursal_id = await _sucursal(conn, zona="America/Tijuana")
        usuario = await _usuario(conn, 2, "Sofía Kardex")
        unidad_id = await conn.fetchval("SELECT id FROM public.unidades_medida LIMIT 1")
        insumo_id = await conn.fetchval(
            "INSERT INTO public.insumos (sucursal_id, nombre, unidad_base_id, unidad_compra_id) "
            "VALUES ($1, $2, $3, $3) RETURNING id",
            sucursal_id,
            f"Insumo Q6 {uuid.uuid4().hex[:8]}",
            unidad_id,
        )
        await movimiento_inventario_repository.registrar(
            conn,
            sucursal_id=sucursal_id,
            insumo_id=insumo_id,
            tipo="E",
            cantidad=Decimal("10"),
            stock_resultante=Decimal("10"),
            motivo="entrada_manual",
            referencia_id=None,
            notas=None,
            creado_por=usuario,
        )
        filas = await movimiento_inventario_repository.listar_por_insumo(conn, insumo_id)

    assert len(filas) == 1
    assert filas[0]["creado_por_nombre"] == "Sofía Kardex"
    assert filas[0]["zona_horaria"] == "America/Tijuana"
