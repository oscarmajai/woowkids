"""Contra PostgreSQL real: sucursales de un Administrador en el usuario y
correo del administrador en la sucursal."""

import uuid

import asyncpg
import pytest
from app.repositories import branch_repository, user_repository

pytestmark = pytest.mark.asyncio


async def _sucursal(conn: asyncpg.Connection, zona: str = "America/Mexico_City") -> uuid.UUID:
    sufijo = uuid.uuid4().hex[:10]
    sucursal_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO public.sucursales (nombre, correo, zona_horaria) VALUES ($1, $2, $3) "
        "RETURNING id",
        f"Sucursal Usuarios Admin {sufijo}",
        f"sucursal.{sufijo}@test.local",
        zona,
    )
    return sucursal_id


async def _usuario(conn: asyncpg.Connection, rol_id: int, nombre: str) -> uuid.UUID:
    sufijo = uuid.uuid4().hex[:10]
    usuario_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO public.usuarios (email, password_hash, nombre_completo, rol) "
        "VALUES ($1, 'x', $2, $3) RETURNING id",
        f"usuarios.admin.{sufijo}@test.local",
        nombre,
        rol_id,
    )
    return usuario_id


async def _asignar(conn: asyncpg.Connection, usuario_id: uuid.UUID, sucursal_id: uuid.UUID) -> None:
    await conn.execute(
        "INSERT INTO public.usuarios_sucursal (usuario_id, sucursal_id) VALUES ($1, $2)",
        usuario_id,
        sucursal_id,
    )


async def test_administrador_trae_sus_sucursales_y_la_sucursal_su_correo(
    pool: asyncpg.Pool,
) -> None:
    async with pool.acquire() as conn:
        s1 = await _sucursal(conn)
        s2 = await _sucursal(conn)
        admin = await _usuario(conn, 2, "Sofía Admin")
        cajero = await _usuario(conn, 3, "Diego Cajero")
        await _asignar(conn, admin, s1)
        await _asignar(conn, admin, s2)
        await _asignar(conn, cajero, s1)

        reg_admin = await user_repository.get_usuario_by_id(conn, admin)
        reg_cajero = await user_repository.get_usuario_by_id(conn, cajero)
        sucursal = await branch_repository.get_sucursal_by_id(conn, s1)

    assert reg_admin is not None and reg_cajero is not None and sucursal is not None
    # El Administrador sigue sin sucursal fija, pero se sabe dónde administra.
    assert reg_admin["sucursal_id"] is None
    assert sorted(reg_admin["sucursales_ids"]) == sorted([s1, s2])
    assert reg_cajero["sucursal_id"] == s1
    assert reg_cajero["sucursales_ids"] == [s1]
    assert sucursal["administrador_id"] == admin
    assert sucursal["administrador_email"] is not None
    assert sucursal["administrador_email"].startswith("usuarios.admin.")
    assert sucursal["administrador_email"] != sucursal["correo"]
