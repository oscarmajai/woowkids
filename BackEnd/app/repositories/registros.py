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
    aviso_privacidad_version: int | None = None,
    acepta_finalidades_secundarias: bool | None = None,
) -> None:
    """Crea el registro en estado P. Con `aviso_privacidad_version` deja
    constancia de que el tutor aceptó esa versión del aviso, en este momento."""
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
            reservacion_id,
            aviso_privacidad_version,
            aviso_privacidad_aceptado_en,
            acepta_finalidades_secundarias
        )
        VALUES ($1, $2, $3, $4, 0, 'P', NOW(), $5, $6, $7::int,
                CASE WHEN $7::int IS NULL THEN NULL ELSE NOW() END, $8)
        """,
        registro_id,
        sucursal_id,
        tutor_id,
        nombre_segundo_tutor,
        usuario_id,
        reservacion_id,
        aviso_privacidad_version,
        acepta_finalidades_secundarias,
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


async def get_registro_alcance(
    conn: asyncpg.Connection, registro_id: UUID
) -> dict[str, Any] | None:
    """Sucursal y estado de un registro activo (no borrado), para autorizar el
    acceso a sus archivos. None si no existe o está desactivado."""
    row = await conn.fetchrow(
        """
        SELECT id, sucursal_id, estado
        FROM registros
        WHERE id = $1 AND activo = TRUE
        """,
        registro_id,
    )
    return dict(row) if row else None


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


async def get_registro_para_comprobante(
    conn: asyncpg.Connection, registro_id: UUID
) -> dict[str, Any] | None:
    """Encabezado del comprobante de un registro (tutor, sucursal, quién
    lo registró, total). Bloquea la fila del registro (FOR UPDATE) para que la
    reimpresión no se cruce con el checkout del último niño, que revoca el
    código del QR. Llamar dentro de una transacción."""
    row = await conn.fetchrow(
        """
        SELECT r.id, r.sucursal_id, r.estado, r.total, r.creado,
               t.nombre_completo AS tutor, t.telefono,
               s.nombre AS sucursal,
               u.nombre_completo AS cajero
        FROM registros r
        JOIN tutores t ON t.id = r.tutores_id
        JOIN sucursales s ON s.id = r.sucursal_id
        LEFT JOIN usuarios u ON u.id = r.creado_por
        WHERE r.id = $1 AND r.activo = TRUE
        FOR UPDATE OF r
        """,
        registro_id,
    )
    return dict(row) if row else None


async def get_ninos_en_estancia_de_registro(
    conn: asyncpg.Connection, registro_id: UUID
) -> list[dict[str, Any]]:
    """Niños del registro que siguen dentro (sin salida), con sus notas /
    alergias, para el comprobante reimpreso."""
    rows = await conn.fetch(
        """
        SELECT n.nombre_completo AS nombre, n.edad, n.notas,
               p.pulsera_rfid AS pulsera, dr.cantidad AS horas,
               dr.salida_esperada
        FROM detalles_registro dr
        JOIN ninos n ON n.id = dr.ninos_id
        JOIN pulseras p ON p.id = dr.pulseras_id
        WHERE dr.registros_id = $1 AND dr.activo = TRUE AND dr.salida IS NULL
        ORDER BY dr.creado, n.nombre_completo
        """,
        registro_id,
    )
    return [dict(r) for r in rows]
