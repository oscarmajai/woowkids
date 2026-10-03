from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

import asyncpg


class EstadoRegistro(str, Enum):
    ACTIVO = "A"
    CERRADO = "C"
    PENDIENTE = "P"


async def registro_create(
    conn: asyncpg.Connection,
    registro_id: UUID,
    sucursal_id: UUID,
    tutor_id: UUID,
    usuario_id: UUID,
    nombre_segundo_tutor: str | None = None,
    reservacion_id: UUID | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO registros (
            id,
            sucursal_id,
            tutores_id,
            nombre_segundo_tutor,
            total,
            estado,
            creado,
            creado_por,
            reservacion_id
        )
        VALUES ($1, $2, $3, $4, 0, 'P', NOW(), $5, $6)
        """,
        registro_id,
        sucursal_id,
        tutor_id,
        nombre_segundo_tutor,
        usuario_id,
        reservacion_id,
    )


async def registro_update_total(
    conn: asyncpg.Connection, usuario_id: UUID, registro_id: UUID, total: Decimal
) -> None:
    await conn.execute(
        """
        UPDATE registros
        SET total = $1,
            modificado = NOW(),
            modificado_por = $2
        WHERE id = $3
        """,
        total,
        usuario_id,
        registro_id,
    )


async def registro_add_total(
    conn: asyncpg.Connection, total_extra: float, usuario_id: UUID, registro_id: UUID
) -> None:
    await conn.execute(
        """
        UPDATE registros
        SET total = total + $1,
            modificado = NOW(),
            modificado_por = $2
        WHERE id = $3
        """,
        total_extra,
        usuario_id,
        registro_id,
    )


async def change_registro_estado(
    conn: asyncpg.Connection, estado_nuevo: EstadoRegistro, usuario_id: UUID, registro_id: UUID
) -> None:
    await conn.execute(
        """
        UPDATE registros
        SET estado = $1,
            modificado = NOW(),
            modificado_por = $2
        WHERE id = $3
   """,
        estado_nuevo.value,
        usuario_id,
        registro_id,
    )


async def exists_registro(
    conn: asyncpg.Connection,
    registro_id: UUID,
) -> bool:
    result = await conn.fetchval(
        """
       SELECT 1
       FROM registros
       WHERE id=$1 AND activo = TRUE
   """,
        registro_id,
    )
    return bool(result)


async def exists_registro_by_reservacion_id(
    conn: asyncpg.Connection,
    reservacion_id: UUID,
) -> bool:
    result = await conn.fetchval(
        """
       SELECT 1
       FROM registros
       WHERE reservacion_id=$1 AND activo = TRUE
   """,
        reservacion_id,
    )
    return bool(result)


async def contar_ninos_registrados_por_reservacion(
    conn: asyncpg.Connection, reservacion_id: UUID
) -> int:
    total = await conn.fetchval(
        """
        SELECT COUNT(dr.id)
        FROM detalles_registro dr
        JOIN registros r ON r.id = dr.registros_id
        WHERE r.reservacion_id = $1 AND dr.activo = TRUE AND r.activo = TRUE
        """,
        reservacion_id,
    )
    return int(total or 0)


async def obtener_saldo_para_cobro(
    conn: asyncpg.Connection, registro_id: UUID
) -> dict[str, Any] | None:
    """Bloquea el registro (FOR UPDATE) y devuelve su sucursal, su total y lo
    neto ya cobrado: pagos_estancia menos el cambio entregado (movimientos de
    caja tipo 'C' del registro). Llamar dentro de una transacción."""
    row = await conn.fetchrow(
        """
        SELECT r.id, r.sucursal_id, r.total,
               COALESCE((SELECT SUM(pe.monto) FROM pagos_estancia pe
                         WHERE pe.registros_id = r.id), 0)
             - COALESCE((SELECT SUM(mc.monto) FROM movimientos_caja mc
                         WHERE mc.referencia_id = r.id AND mc.tipo_movimiento = 'C'), 0)
               AS pagado_neto
        FROM registros r
        WHERE r.id = $1 AND r.activo = TRUE
        FOR UPDATE OF r
        """,
        registro_id,
    )
    return dict(row) if row else None
