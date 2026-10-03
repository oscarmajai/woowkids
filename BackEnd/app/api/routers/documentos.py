from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user, get_db
from app.core.object_storage import PREFIJOS, get_object
from app.schemas.auth import TokenData
from app.services.documentos_service import (
    obtener_fotos_llegada_por_registro,
    obtener_identificacion,
)

router = APIRouter(prefix="/api/uploads", tags=["Archivos Protegidos"])


@router.get("/productos/{nombre_archivo}")
async def descargar_imagen_producto(nombre_archivo: str) -> StreamingResponse:
    """Sirve las fotos de productos sin autenticación: se muestran en <img>/q-img
    en la caja y el catálogo, que no pueden enviar el header Authorization."""
    key = f"{PREFIJOS['productos']}/{nombre_archivo}"
    body, content_type = await get_object(key)

    return StreamingResponse(body, media_type=content_type)


@router.get("/registros/{registro_id}/llegadas")
async def descargar_imagenes_llegada(
    registro_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
) -> StreamingResponse:
    """ZIP con las fotos de llegada de un registro. Autorizado por recurso (C6):
    staff de la sucursal del registro con permiso de estancias, o el padre
    dueño del registro; cualquier otro caso es 404."""
    return await obtener_fotos_llegada_por_registro(conn, current_user, registro_id)


@router.get("/identificaciones/{nombre_archivo}")
async def descargar_identificacion(
    nombre_archivo: str,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
) -> StreamingResponse:
    """INE del tutor de un registro. Autorizada por recurso (C6), igual que las
    fotos de llegada; cualquier caso no autorizado es 404."""
    return await obtener_identificacion(conn, current_user, nombre_archivo)
