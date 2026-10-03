"""Manejadores globales de excepciones de la app FastAPI.

Red de seguridad para los datos que PostgreSQL rechaza (M3): un INSERT/UPDATE
que viola una llave foránea, un índice único o un CHECK, o un valor fuera de
rango o con formato inválido, responde 409/422 con el formato de error del
backend (``{"detail": {"code", "message"}}``) en lugar de un 500. La validación
explícita de cada endpoint sigue siendo la forma correcta de rechazar esos
datos (con un mensaje específico); esto solo cubre lo que se le escape.

El detalle técnico (constraint, tabla, columna, mensaje de PostgreSQL) se
registra en el log y nunca viaja al cliente.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import asyncpg
from asyncpg.exceptions._base import DataError as ErrorDeArgumentoAsyncpg
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions.validacion import manejar_error_validacion

logger = logging.getLogger("mercury.errores_bd")


@dataclass(frozen=True)
class RespuestaErrorBd:
    status_code: int
    code: str
    message: str


# El orden importa: se usa la primera clase que coincida (las subclases van
# antes que sus bases).
_RESPUESTAS: tuple[tuple[type[Exception], RespuestaErrorBd], ...] = (
    (
        asyncpg.UniqueViolationError,
        RespuestaErrorBd(
            status.HTTP_409_CONFLICT,
            "REGISTRO_DUPLICADO",
            "Ya existe un registro con esos datos.",
        ),
    ),
    (
        asyncpg.ExclusionViolationError,
        RespuestaErrorBd(
            status.HTTP_409_CONFLICT,
            "REGISTRO_EN_CONFLICTO",
            "Los datos chocan con otro registro existente.",
        ),
    ),
    (
        asyncpg.ForeignKeyViolationError,
        RespuestaErrorBd(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "REFERENCIA_INVALIDA",
            "Uno de los datos hace referencia a un registro que no existe.",
        ),
    ),
    (
        asyncpg.CheckViolationError,
        RespuestaErrorBd(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALOR_NO_PERMITIDO",
            "Uno de los valores enviados no está permitido.",
        ),
    ),
    (
        asyncpg.NotNullViolationError,
        RespuestaErrorBd(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "DATO_REQUERIDO",
            "Falta un dato obligatorio.",
        ),
    ),
    (
        asyncpg.IntegrityConstraintViolationError,
        RespuestaErrorBd(
            status.HTTP_409_CONFLICT,
            "CONFLICT",
            "La operación entra en conflicto con los datos existentes.",
        ),
    ),
    (
        asyncpg.NumericValueOutOfRangeError,
        RespuestaErrorBd(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALOR_FUERA_DE_RANGO",
            "Uno de los valores numéricos está fuera del rango permitido.",
        ),
    ),
    (
        asyncpg.StringDataRightTruncationError,
        RespuestaErrorBd(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "TEXTO_DEMASIADO_LARGO",
            "Uno de los textos excede la longitud permitida.",
        ),
    ),
    (
        asyncpg.InvalidTextRepresentationError,
        RespuestaErrorBd(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "FORMATO_INVALIDO",
            "Uno de los valores no tiene un formato válido.",
        ),
    ),
    (
        asyncpg.DataError,
        RespuestaErrorBd(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "DATOS_INVALIDOS",
            "Los datos enviados no son válidos.",
        ),
    ),
    # Lo rechaza asyncpg antes de llegar al servidor (p. ej. un entero que no
    # cabe en int4 o un tipo que no corresponde al parámetro).
    (
        ErrorDeArgumentoAsyncpg,
        RespuestaErrorBd(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "DATOS_INVALIDOS",
            "Los datos enviados no son válidos.",
        ),
    ),
)

# Borrar (o cambiar la llave de) un registro al que otros apuntan es una
# llave foránea "hacia atrás": el dato existe pero está en uso → 409.
_REGISTRO_EN_USO = RespuestaErrorBd(
    status.HTTP_409_CONFLICT,
    "REGISTRO_EN_USO",
    "No se puede completar la operación: el registro está en uso por otros datos.",
)

_DESCONOCIDO = RespuestaErrorBd(
    status.HTTP_422_UNPROCESSABLE_ENTITY,
    "DATOS_INVALIDOS",
    "Los datos enviados no son válidos.",
)


def _es_registro_en_uso(exc: Exception, metodo: str) -> bool:
    if not isinstance(exc, asyncpg.ForeignKeyViolationError):
        return False
    # PostgreSQL: 'update or delete on table "x" violates foreign key ...'
    # (en el sentido contrario: 'insert or update on table ...').
    mensaje = str(getattr(exc, "message", "") or "")
    return metodo == "DELETE" or mensaje.startswith("update or delete")


def respuesta_para(exc: Exception, metodo: str = "GET") -> RespuestaErrorBd:
    """Código HTTP, código de error y mensaje genérico para un error de BD."""
    if _es_registro_en_uso(exc, metodo):
        return _REGISTRO_EN_USO
    for clase, respuesta in _RESPUESTAS:
        if isinstance(exc, clase):
            return respuesta
    return _DESCONOCIDO


async def manejar_error_bd(request: Request, exc: Exception) -> JSONResponse:
    respuesta = respuesta_para(exc, request.method)
    logger.warning(
        "Error de BD convertido a %s %s en %s %s: %s sqlstate=%s constraint=%s "
        "tabla=%s columna=%s mensaje=%r detalle=%r",
        respuesta.status_code,
        respuesta.code,
        request.method,
        request.url.path,
        type(exc).__name__,
        getattr(exc, "sqlstate", None),
        getattr(exc, "constraint_name", None),
        getattr(exc, "table_name", None),
        getattr(exc, "column_name", None),
        str(exc),
        getattr(exc, "detail", None),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=respuesta.status_code,
        content={"detail": {"code": respuesta.code, "message": respuesta.message}},
    )


def registrar_manejadores(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, manejar_error_validacion)
    app.add_exception_handler(asyncpg.IntegrityConstraintViolationError, manejar_error_bd)
    app.add_exception_handler(asyncpg.DataError, manejar_error_bd)
    app.add_exception_handler(ErrorDeArgumentoAsyncpg, manejar_error_bd)
