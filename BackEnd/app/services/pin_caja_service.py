"""Validación de PIN de caja.

Reglas comunes a todos los endpoints que piden el PIN (o la contraseña de
operación) de un cajero o de un administrador:

- Un PIN mal escrito responde **403** ``PIN_INVALIDO`` (o
  ``CREDENCIALES_INVALIDAS`` en la revisión con contraseña), nunca 401: el 401
  lo reserva la API para "token de sesión vencido", y el front lo usaba para
  refrescar la sesión, reenviar el PIN equivocado y cerrar la sesión.
- Si el usuario tiene PIN configurado solo se acepta el PIN; la contraseña
  solo vale mientras no tenga PIN (decisión vigente del usuario). Vale
  también para la revisión del administrador en el cierre.
- Límite de intentos: ``MAX_FALLOS`` fallos en ``VENTANA_MINUTOS`` por
  usuario dueño del PIN + sucursal → **429** ``PIN_BLOQUEADO``. Se guarda en
  ``intentos_pin_fallidos`` (no en memoria) para que valga con varios
  workers; un candado por llave serializa los intentos simultáneos.
- El autorizador (quien aprueba un cierre) se busca solo entre los usuarios
  de la sucursal del turno —o AdministradorSistema, que no tiene sucursal— y
  debe tener el permiso de autorizar en su rol.
- Segregación de funciones: nadie autoriza el cierre de su propio
  turno; si el dueño del turno es un administrador, lo autoriza otro
  administrador de la sucursal o un AdministradorSistema.

``verificar_pin_autorizador`` es la pieza reutilizable para cualquier flujo
que pida el PIN de un administrador (cierre de caja, cancelaciones, etc.).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from typing import Any

import asyncpg
from fastapi import HTTPException, status

from app.core.roles import ROL_SISTEMA
from app.core.security import verify_password
from app.repositories import intentos_pin_repository, user_repository

MAX_FALLOS = 5
VENTANA_MINUTOS = 15

# Permiso del rol del autorizador para aprobar el arqueo (revisión y cierre).
PERMISO_REVISION_ARQUEO = "turnos_caja:revision_admin"
PERMISO_AUTORIZAR_CIERRE = "turnos_caja:confirmar"

# Propósito del token de un solo uso que se emite al validar un PIN. Un
# token solo sirve para la operación para la que se emitió.
PROPOSITO_CERRAR = "cerrar"  # revisión y confirmación del cierre de caja
PROPOSITO_CANCELAR = "cancelar"  # cancelaciones y devoluciones de órdenes cobradas
PROPOSITOS_PIN = frozenset({PROPOSITO_CERRAR, PROPOSITO_CANCELAR})


class PinInvalidoError(HTTPException):
    def __init__(
        self, mensaje: str = "El PIN ingresado es incorrecto.", code: str = "PIN_INVALIDO"
    ) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": code, "message": mensaje},
        )


class PinBloqueadoError(HTTPException):
    def __init__(self, segundos: int) -> None:
        minutos = max(1, math.ceil(segundos / 60))
        unidad = "minuto" if minutos == 1 else "minutos"
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "PIN_BLOQUEADO",
                "message": (
                    f"Demasiados intentos fallidos de PIN. Intenta de nuevo en {minutos} "
                    f"{unidad} o pide apoyo a un administrador."
                ),
            },
            headers={"Retry-After": str(max(1, segundos))},
        )


class AutorizadorNoValidoError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "AUTORIZADOR_NO_VALIDO",
                "message": (
                    "El correo no corresponde a un administrador que pueda autorizar "
                    "en esta sucursal."
                ),
            },
        )


class AutorizadorEsDuenoTurnoError(HTTPException):
    """El autorizador del cierre es el mismo dueño del turno."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "AUTORIZADOR_ES_DUENO_TURNO",
                "message": (
                    "No puedes autorizar el cierre de tu propio turno. Pide a otro "
                    "administrador de la sucursal o a un administrador del sistema "
                    "que lo autorice."
                ),
            },
        )


def es_dueno_turno(autorizador_id: str | uuid.UUID, dueno_turno_id: str | uuid.UUID) -> bool:
    return str(autorizador_id) == str(dueno_turno_id)


def _coincide(plano: str, hash_guardado: str | None) -> bool:
    if not plano or not hash_guardado:
        return False
    try:
        return verify_password(plano, hash_guardado)
    except ValueError:
        # Hash con formato inválido (dato viejo o de prueba): no coincide.
        return False


def credencial_valida(secreto: str, pin_hash: str | None, password_hash: str | None) -> bool:
    """Con PIN configurado solo vale el PIN; sin PIN, la contraseña hace las
    veces de PIN."""
    if pin_hash:
        return _coincide(secreto, pin_hash)
    return _coincide(secreto, password_hash)


async def verificar_con_limite(
    conn: asyncpg.Connection,
    *,
    usuario_id: str | uuid.UUID,
    sucursal_id: str | uuid.UUID | None,
    tipo: str,
    verificar: Callable[[], bool],
    error: HTTPException,
    intentado_por: str | uuid.UUID | None = None,
) -> None:
    """Ejecuta ``verificar`` respetando el límite de intentos de la llave
    (usuario, sucursal). Lanza ``PinBloqueadoError`` (429) si la llave está
    bloqueada —sin verificar nada— o ``error`` si no coincide.

    El fallo se registra en su propia transacción, que se confirma ANTES de
    lanzar el error: si el llamador estuviera dentro de otra transacción que
    se revierte, el intento no debe perderse. No llamar dentro de una
    transacción abierta del llamador."""
    bloqueado = 0
    ok = False
    async with conn.transaction():
        await intentos_pin_repository.bloquear_llave(conn, usuario_id, sucursal_id)
        bloqueado = await intentos_pin_repository.segundos_de_bloqueo(
            conn, usuario_id, sucursal_id, MAX_FALLOS, VENTANA_MINUTOS
        )
        if not bloqueado:
            ok = verificar()
            if ok:
                await intentos_pin_repository.limpiar(conn, usuario_id, sucursal_id)
            else:
                await intentos_pin_repository.registrar_fallo(
                    conn, usuario_id, sucursal_id, tipo, intentado_por
                )
                await intentos_pin_repository.purgar_viejos(conn, usuario_id)
    if bloqueado:
        raise PinBloqueadoError(bloqueado)
    if not ok:
        raise error


async def buscar_autorizador(
    conn: asyncpg.Connection,
    email: str,
    sucursal_id: str | uuid.UUID | None,
    permiso: str,
    *,
    dueno_turno_id: str | uuid.UUID | None = None,
) -> dict[str, Any]:
    """Usuario activo con ese correo que puede autorizar en la sucursal: su rol
    tiene ``permiso`` y está asignado a la sucursal (``usuarios_sucursal``), o
    es AdministradorSistema (sin sucursal, autoriza en todas). Cualquier otro
    caso —no existe, otra sucursal, rol sin permiso— responde 403 sin llegar
    a verificar el PIN, para no dar pistas sobre PINs de otras sucursales.

    Con ``dueno_turno_id`` (autorizar un cierre), el autorizador no puede ser
    el dueño del turno: 403 ``AUTORIZADOR_ES_DUENO_TURNO``, también sin llegar
    a verificar el PIN."""
    row = await user_repository.get_autorizador_por_email(conn, email, sucursal_id, permiso)
    if not row:
        raise AutorizadorNoValidoError()
    es_sistema = row["rol"] == ROL_SISTEMA
    if not es_sistema and not (row["tiene_permiso"] and row["en_sucursal"]):
        raise AutorizadorNoValidoError()
    if dueno_turno_id is not None and es_dueno_turno(row["id"], dueno_turno_id):
        raise AutorizadorEsDuenoTurnoError()
    return row


async def verificar_pin_autorizador(
    conn: asyncpg.Connection,
    *,
    email: str,
    pin: str,
    sucursal_id: str | uuid.UUID | None,
    permiso: str = PERMISO_AUTORIZAR_CIERRE,
    tipo: str = "admin",
    intentado_por: str | uuid.UUID | None = None,
    dueno_turno_id: str | uuid.UUID | None = None,
    error: HTTPException | None = None,
) -> dict[str, Any]:
    """Busca al autorizador (``buscar_autorizador``) y valida su PIN con el
    límite de intentos. Devuelve la fila del autorizador (id, email,
    nombre_completo, rol, pin_hash)."""
    autorizador = await buscar_autorizador(
        conn, email, sucursal_id, permiso, dueno_turno_id=dueno_turno_id
    )
    await verificar_con_limite(
        conn,
        usuario_id=autorizador["id"],
        sucursal_id=sucursal_id,
        tipo=tipo,
        verificar=lambda: credencial_valida(
            pin, autorizador["pin_hash"], autorizador["password_hash"]
        ),
        error=error or PinInvalidoError("El PIN ingresado para el Administrador es incorrecto."),
        intentado_por=intentado_por,
    )
    return autorizador
