import io
from uuid import UUID
from zipfile import ZipFile

import asyncpg
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.core.object_storage import PREFIJOS, get_object
from app.core.roles import ROL_PADRE
from app.core.scope import sucursal_scope
from app.exceptions import NoEncontrado
from app.repositories.fotos import get_fotos_llegada_by_registro_id, get_registro_id_by_foto_ine
from app.repositories.registros import EstadoRegistro, get_registro_alcance
from app.schemas.auth import TokenData
from app.services.permission_service import has_permission

# Permisos de estancias que justifican ver la INE y las fotos de llegada
# de un registro: quien ve a los niños en estancia (Control de Acceso) y quien
# les da salida (Checkout) debe poder cotejar al tutor que los recoge. Basta
# con uno de los dos. Registrar entrada o cobrar no da acceso por sí solo.
PERMISOS_VER_ARCHIVOS_REGISTRO = ("estancias:ver_activos", "estancias:checkout")


def _no_encontrado() -> NoEncontrado:
    return NoEncontrado("Archivo")


async def autorizar_archivos_registro(
    conn: asyncpg.Connection, current_user: TokenData, registro_id: UUID
) -> None:
    """Autoriza por recurso el acceso a los archivos (INE, fotos de
    llegada) de un registro de estancia. Cualquier rechazo es 404, igual que
    si el registro no existiera, para no revelar su existencia:

    - Token de padre (PadreVisor): solo su propio registro (``sub``) y solo
      mientras siga activo (el mismo criterio que /padres/ninos-activos).
    - Staff: el rol debe tener alguno de PERMISOS_VER_ARCHIVOS_REGISTRO y el
      registro debe ser de la sucursal de la sesión (sucursal_scope; el
      AdministradorSistema sin sucursal elegida ve todas).
    """
    if current_user.role == ROL_PADRE:
        if current_user.sub != str(registro_id):
            raise _no_encontrado()
        registro = await get_registro_alcance(conn, registro_id)
        if registro is None or registro["estado"] != EstadoRegistro.ACTIVO.value:
            raise _no_encontrado()
        return

    if not any(has_permission(current_user.role, p) for p in PERMISOS_VER_ARCHIVOS_REGISTRO):
        raise _no_encontrado()

    registro = await get_registro_alcance(conn, registro_id)
    if registro is None:
        raise _no_encontrado()

    scope = sucursal_scope(current_user)
    if scope is not None and str(registro["sucursal_id"]) != scope:
        raise _no_encontrado()


async def obtener_identificacion(
    conn: asyncpg.Connection, current_user: TokenData, nombre_archivo: str
) -> StreamingResponse:
    """INE del tutor de un registro. El dueño se resuelve en BD a partir de la
    ruta guardada en ``fotos`` (no se confía en el nombre del archivo)."""
    key = f"{PREFIJOS['identificaciones']}/{nombre_archivo}"
    registro_id = await get_registro_id_by_foto_ine(conn, key)
    if registro_id is None:
        raise _no_encontrado()

    await autorizar_archivos_registro(conn, current_user, registro_id)

    body, content_type = await get_object(key)
    return StreamingResponse(body, media_type=content_type)


async def obtener_fotos_llegada_por_registro(
    conn: asyncpg.Connection,
    current_user: TokenData,
    registro_id: UUID,
) -> StreamingResponse:
    """Obtiene un ZIP con las fotos de llegada asociadas a un registro de estancia."""
    await autorizar_archivos_registro(conn, current_user, registro_id)

    fotos = await get_fotos_llegada_by_registro_id(conn, registro_id)

    if not fotos:
        raise HTTPException(
            status_code=404,
            detail="No se encontraron fotos de llegada para este registro",
        )

    zip_buffer = io.BytesIO()

    with ZipFile(zip_buffer, "w") as zip_file:
        for idx, foto in enumerate(fotos):
            storage_url = foto["storage_url"]
            nombre_archivo = storage_url.split("/")[-1]

            try:
                stream, content_type = await get_object(storage_url)
                image_data = stream.read()
                zip_file.writestr(f"foto_{idx+1}_{nombre_archivo}", image_data)
            except NoEncontrado:
                continue

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=fotos_llegada_{registro_id}.zip"},
    )
