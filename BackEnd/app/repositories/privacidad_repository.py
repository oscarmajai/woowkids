from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

# Columnas del responsable, en el orden de ResponsableAviso.
COLUMNAS_RESPONSABLE = (
    "razon_social",
    "nombre_comercial",
    "domicilio",
    "area_datos_personales",
    "correo_datos_personales",
    "telefono_datos_personales",
    "url_aviso",
    "dias_conservacion_imagenes",
    "anios_conservacion_registros",
)

# La fecha de vigencia que se lee en el aviso es la del centro del país: el
# aviso es uno solo para toda la instalación, no por sucursal.
_SELECT = """
    SELECT a.version, a.texto_integral, a.texto_simplificado,
           a.razon_social, a.nombre_comercial, a.domicilio, a.area_datos_personales,
           a.correo_datos_personales, a.telefono_datos_personales, a.url_aviso,
           a.dias_conservacion_imagenes, a.anios_conservacion_registros,
           a.motivo_cambio, a.vigente_desde,
           (a.vigente_desde AT TIME ZONE 'America/Mexico_City')::date AS fecha_vigencia,
           u.nombre_completo AS publicado_por
    FROM public.avisos_privacidad a
    LEFT JOIN public.usuarios u ON u.id = a.publicado_por
"""


async def obtener_vigente(conn: asyncpg.Connection) -> dict[str, Any] | None:
    """La versión vigente: la de número más alto."""
    row = await conn.fetchrow(_SELECT + " ORDER BY a.version DESC LIMIT 1")
    return dict(row) if row else None


async def version_vigente(conn: asyncpg.Connection) -> int | None:
    valor: int | None = await conn.fetchval("SELECT max(version) FROM public.avisos_privacidad")
    return valor


async def historial(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT a.version, a.vigente_desde, a.motivo_cambio,
               u.nombre_completo AS publicado_por
        FROM public.avisos_privacidad a
        LEFT JOIN public.usuarios u ON u.id = a.publicado_por
        ORDER BY a.version DESC
        """
    )
    return [dict(r) for r in rows]


async def bloquear_para_publicar(conn: asyncpg.Connection) -> None:
    """Serializa las publicaciones (dentro de una transacción): dos
    AdministradorSistema publicando a la vez calcularían el mismo número de
    versión. EXCLUSIVE deja leer el aviso mientras tanto."""
    await conn.execute("LOCK TABLE public.avisos_privacidad IN EXCLUSIVE MODE")


async def insertar_version(
    conn: asyncpg.Connection,
    version: int,
    texto_integral: str,
    texto_simplificado: str,
    responsable: dict[str, Any],
    motivo_cambio: str | None,
    usuario_id: UUID,
) -> None:
    await conn.execute(
        """
        INSERT INTO public.avisos_privacidad (
            version, texto_integral, texto_simplificado,
            razon_social, nombre_comercial, domicilio, area_datos_personales,
            correo_datos_personales, telefono_datos_personales, url_aviso,
            dias_conservacion_imagenes, anios_conservacion_registros,
            motivo_cambio, publicado_por
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        """,
        version,
        texto_integral,
        texto_simplificado,
        *(responsable[c] for c in COLUMNAS_RESPONSABLE),
        motivo_cambio,
        usuario_id,
    )
