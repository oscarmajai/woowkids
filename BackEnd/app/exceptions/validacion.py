"""Errores de validación de la petición en español (B8).

FastAPI responde los ``RequestValidationError`` con los mensajes en inglés de
Pydantic ("Input should be greater than 0"). Este manejador conserva la misma
forma de respuesta (``{"detail": [{"type", "loc", "msg", "input", "ctx"}]}``,
para los clientes que leen ``loc`` y ``type``) y solo cambia ``msg`` por un
texto en español con el campo afectado: "cantidad: debe ser mayor que 0".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, get_args

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic_core.core_schema import ErrorType

# Primer elemento de `loc` que solo dice de dónde vino el dato.
_ORIGENES = frozenset({"body", "query", "path", "header", "cookie"})

# type de Pydantic v2 → mensaje (se rellena con `ctx`).
_MENSAJES: dict[str, str] = {
    "missing": "es obligatorio",
    "extra_forbidden": "no es un campo permitido",
    "greater_than": "debe ser mayor que {gt}",
    "greater_than_equal": "debe ser mayor o igual que {ge}",
    "less_than": "debe ser menor que {lt}",
    "less_than_equal": "debe ser menor o igual que {le}",
    "multiple_of": "debe ser múltiplo de {multiple_of}",
    "finite_number": "debe ser un número finito",
    "int_type": "debe ser un número entero",
    "int_parsing": "debe ser un número entero",
    "int_parsing_size": "es un número demasiado grande",
    "int_from_float": "debe ser un número entero, sin decimales",
    "float_type": "debe ser un número",
    "float_parsing": "debe ser un número",
    "decimal_type": "debe ser un número",
    "decimal_parsing": "debe ser un número",
    "decimal_finite": "debe ser un número finito",
    "decimal_max_digits": "admite como máximo {max_digits} dígitos",
    "decimal_max_places": "admite como máximo {decimal_places} decimales",
    "decimal_whole_digits": "admite como máximo {whole_digits} dígitos enteros",
    "bool_type": "debe ser verdadero o falso",
    "bool_parsing": "debe ser verdadero o falso",
    "string_type": "debe ser un texto",
    "string_too_short": "debe tener al menos {min_length} caracteres",
    "string_too_long": "admite como máximo {max_length} caracteres",
    "string_pattern_mismatch": "no tiene un formato válido",
    "too_short": "debe tener al menos {min_length} elementos",
    "too_long": "admite como máximo {max_length} elementos",
    "list_type": "debe ser una lista",
    "tuple_type": "debe ser una lista",
    "set_type": "debe ser una lista",
    "dict_type": "debe ser un objeto",
    "model_type": "debe ser un objeto",
    "model_attributes_type": "debe ser un objeto",
    "uuid_type": "debe ser un identificador (UUID) válido",
    "uuid_parsing": "debe ser un identificador (UUID) válido",
    "uuid_version": "debe ser un identificador (UUID) válido",
    "date_type": "debe ser una fecha válida (AAAA-MM-DD)",
    "date_parsing": "debe ser una fecha válida (AAAA-MM-DD)",
    "date_from_datetime_parsing": "debe ser una fecha válida (AAAA-MM-DD)",
    "date_from_datetime_inexact": "debe ser una fecha sin hora",
    "date_past": "debe ser una fecha pasada",
    "date_future": "debe ser una fecha futura",
    "datetime_type": "debe ser una fecha y hora válidas",
    "datetime_parsing": "debe ser una fecha y hora válidas",
    "datetime_from_date_parsing": "debe ser una fecha y hora válidas",
    "datetime_object_invalid": "debe ser una fecha y hora válidas",
    "datetime_past": "debe ser una fecha y hora pasadas",
    "datetime_future": "debe ser una fecha y hora futuras",
    "time_type": "debe ser una hora válida (HH:MM)",
    "time_parsing": "debe ser una hora válida (HH:MM)",
    "time_delta_type": "debe ser una duración válida",
    "time_delta_parsing": "debe ser una duración válida",
    "enum": "debe ser uno de: {expected}",
    "literal_error": "debe ser uno de: {expected}",
    "json_invalid": "no es un JSON válido",
    "json_type": "no es un JSON válido",
    "url_type": "debe ser una URL válida",
    "url_parsing": "debe ser una URL válida",
    "url_scheme": "debe ser una URL válida",
    "bytes_too_short": "es demasiado corto",
    "bytes_too_long": "es demasiado largo",
}

_GENERICO = "no es un valor válido"
_TIPOS_DE_PYDANTIC: frozenset[str] = frozenset(get_args(ErrorType))
_PREFIJOS_PROPIOS = ("Value error, ", "Assertion failed, ")


def _nombre_campo(loc: Sequence[Any]) -> str | None:
    """Último nombre de campo de `loc` ("body", "detalles", 0, "cantidad" →
    "cantidad"). None cuando el error es de la petición completa."""
    partes = list(loc)
    if partes and partes[0] in _ORIGENES:
        partes = partes[1:]
    nombres = [str(p) for p in partes if isinstance(p, str)]
    if not nombres:
        return None
    return nombres[-1].replace("_", " ")


def _mensaje_propio(error: Mapping[str, Any]) -> str:
    """Mensaje de un `ValueError` de nuestros validadores: ya viene en
    español; solo se le quita el prefijo de Pydantic."""
    ctx = error.get("ctx") or {}
    causa = ctx.get("error")
    texto = str(causa) if causa is not None else str(error.get("msg", ""))
    for prefijo in _PREFIJOS_PROPIOS:
        if texto.startswith(prefijo):
            texto = texto[len(prefijo) :]
    # EmailStr: "value is not a valid email address: <motivo en inglés>".
    if texto.startswith("value is not a valid email address"):
        return "debe ser un correo electrónico válido"
    return texto or _GENERICO


def _texto(error: Mapping[str, Any]) -> str:
    tipo = str(error.get("type", ""))
    if tipo in ("value_error", "assertion_error"):
        return _mensaje_propio(error)
    if tipo not in _TIPOS_DE_PYDANTIC:
        # PydanticCustomError propio (p. ej. "password_corta"): ya está en español.
        return str(error.get("msg") or _GENERICO)
    plantilla = _MENSAJES.get(tipo)
    if plantilla is None:
        return _GENERICO
    ctx = {k: str(v).replace(" or ", " o ") for k, v in (error.get("ctx") or {}).items()}
    if tipo == "string_too_short" and ctx.get("min_length") == "1":
        return "no puede estar vacío"
    try:
        return plantilla.format(**ctx)
    except (KeyError, IndexError):
        return _GENERICO


def mensaje_en_espanol(error: Mapping[str, Any]) -> str:
    """ "campo: motivo" en español para un error de `RequestValidationError.errors()`."""
    texto = _texto(error)
    campo = _nombre_campo(error.get("loc") or ())
    return f"{campo}: {texto}" if campo else texto


def traducir_errores(errores: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Los mismos errores (type, loc, input, ctx…) con `msg` en español."""
    return [{**dict(e), "msg": mensaje_en_espanol(e)} for e in errores]


async def manejar_error_validacion(request: Request, exc: Exception) -> JSONResponse:
    errores = exc.errors() if isinstance(exc, RequestValidationError) else []
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": jsonable_encoder(traducir_errores(errores))},
    )
