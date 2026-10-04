"""Aviso de privacidad (LFPDPPP, DOF 20-03-2025) por versiones.

Los textos se guardan como plantilla con marcadores ``{{...}}`` que se llenan
con los datos del responsable de la misma versión. Cada publicación crea una
versión nueva (nunca se edita una anterior), para poder demostrar qué texto
aceptó cada tutor en el check-in (registros.aviso_privacidad_version)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.exceptions import Conflicto, NoEncontrado
from app.repositories import privacidad_repository
from app.schemas.privacidad import (
    AvisoAdminOut,
    AvisoPublicoOut,
    PublicarAvisoIn,
    ResponsableAviso,
    VersionAvisoOut,
)

# Marcador → qué lo llena. Los del responsable salen de las columnas del
# mismo nombre; version y fecha_vigencia los pone el sistema.
MARCADORES: dict[str, str] = {
    "razon_social": "Razón social",
    "nombre_comercial": "Nombre comercial",
    "domicilio": "Domicilio",
    "area_datos_personales": "Persona o departamento de datos personales",
    "correo_datos_personales": "Correo para derechos ARCO",
    "telefono_datos_personales": "Teléfono para derechos ARCO",
    "url_aviso": "Dirección web del aviso integral",
    "dias_conservacion_imagenes": "Días de conservación de INE y fotografías",
    "anios_conservacion_registros": "Años de conservación de registros",
    "version": "Número de versión (automático)",
    "fecha_vigencia": "Fecha de vigencia (automática)",
}

_MARCADOR = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")

_MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

_SIN_AVISO = NoEncontrado(
    mensaje="Todavía no hay un aviso de privacidad publicado.",
)


def fecha_larga(d: date) -> str:
    """3 de octubre de 2026."""
    return f"{d.day} de {_MESES[d.month - 1]} de {d.year}"


def _responsable(aviso: dict[str, Any]) -> ResponsableAviso:
    return ResponsableAviso.model_validate(
        {c: aviso[c] for c in privacidad_repository.COLUMNAS_RESPONSABLE}
    )


def pendientes(aviso: dict[str, Any]) -> list[str]:
    """Datos del responsable que siguen vacíos (los números siempre tienen valor)."""
    return [
        MARCADORES[c]
        for c in privacidad_repository.COLUMNAS_RESPONSABLE
        if isinstance(aviso[c], str) and not aviso[c].strip()
    ]


def rellenar(texto: str, aviso: dict[str, Any]) -> str:
    """Reemplaza los marcadores con los datos de la versión. Un dato sin
    capturar se ve como «[Pendiente de configurar: ...]» en vez de dejar un
    hueco que pase desapercibido."""
    valores: dict[str, str] = {
        c: str(aviso[c]).strip() for c in privacidad_repository.COLUMNAS_RESPONSABLE
    }
    valores["version"] = str(aviso["version"])
    valores["fecha_vigencia"] = fecha_larga(aviso["fecha_vigencia"])

    def reemplazo(m: re.Match[str]) -> str:
        nombre = m.group(1)
        if nombre not in valores:
            return m.group(0)
        return valores[nombre] or f"[Pendiente de configurar: {MARCADORES[nombre]}]"

    return _MARCADOR.sub(reemplazo, texto)


def marcadores_desconocidos(texto: str) -> list[str]:
    return sorted({m for m in _MARCADOR.findall(texto) if m not in MARCADORES})


async def aviso_publico(conn: asyncpg.Connection) -> AvisoPublicoOut:
    aviso = await privacidad_repository.obtener_vigente(conn)
    if aviso is None:
        raise _SIN_AVISO
    return AvisoPublicoOut(
        version=aviso["version"],
        vigente_desde=aviso["vigente_desde"],
        fecha_vigencia=aviso["fecha_vigencia"],
        nombre_comercial=aviso["nombre_comercial"],
        texto_integral=rellenar(aviso["texto_integral"], aviso),
        texto_simplificado=rellenar(aviso["texto_simplificado"], aviso),
    )


async def aviso_admin(conn: asyncpg.Connection) -> AvisoAdminOut:
    aviso = await privacidad_repository.obtener_vigente(conn)
    if aviso is None:
        raise _SIN_AVISO
    versiones = await privacidad_repository.historial(conn)
    return AvisoAdminOut(
        version=aviso["version"],
        vigente_desde=aviso["vigente_desde"],
        publicado_por=aviso["publicado_por"],
        motivo_cambio=aviso["motivo_cambio"],
        responsable=_responsable(aviso),
        texto_integral=aviso["texto_integral"],
        texto_simplificado=aviso["texto_simplificado"],
        marcadores=MARCADORES,
        pendientes=pendientes(aviso),
        historial=[VersionAvisoOut.model_validate(v) for v in versiones],
    )


async def publicar(
    conn: asyncpg.Connection, body: PublicarAvisoIn, usuario_id: UUID
) -> AvisoAdminOut:
    """Publica una versión nueva con los datos del responsable y, si vienen,
    los textos nuevos (si no, los de la versión vigente). Pasa a ser la
    vigente: los check-in siguientes deben aceptar esta."""
    for campo, texto in (
        ("texto integral", body.texto_integral),
        ("texto simplificado", body.texto_simplificado),
    ):
        desconocidos = marcadores_desconocidos(texto or "")
        if desconocidos:
            lista = ", ".join("{{" + m + "}}" for m in desconocidos)
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "MARCADOR_DESCONOCIDO",
                    "message": f"El {campo} usa marcadores que no existen: {lista}.",
                },
            )

    async with conn.transaction():
        await privacidad_repository.bloquear_para_publicar(conn)
        actual = await privacidad_repository.obtener_vigente(conn)
        if actual is None:
            raise _SIN_AVISO
        if actual["version"] != body.version_base:
            raise Conflicto(
                f"Mientras editabas se publicó la versión {actual['version']} del aviso. "
                "Recarga la página y vuelve a aplicar tus cambios."
            )
        await privacidad_repository.insertar_version(
            conn,
            actual["version"] + 1,
            body.texto_integral or actual["texto_integral"],
            body.texto_simplificado or actual["texto_simplificado"],
            body.responsable.model_dump(),
            body.motivo_cambio or None,
            usuario_id,
        )
    return await aviso_admin(conn)


async def exigir_aceptacion(
    conn: asyncpg.Connection, aceptado: bool, version_aceptada: int | None
) -> int:
    """Check-in: el tutor debe aceptar el aviso vigente. Devuelve la versión
    aceptada para guardarla en el registro; 422 si no lo aceptó o si aceptó
    una versión que ya no es la vigente (se publicó otra mientras capturaban)."""
    if not aceptado or version_aceptada is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "AVISO_PRIVACIDAD_NO_ACEPTADO",
                "message": (
                    "Para registrar la entrada, el tutor debe leer y aceptar el aviso "
                    "de privacidad."
                ),
            },
        )
    vigente = await privacidad_repository.version_vigente(conn)
    if vigente is None:
        raise _SIN_AVISO
    if version_aceptada != vigente:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "AVISO_PRIVACIDAD_DESACTUALIZADO",
                "message": (
                    "El aviso de privacidad cambió mientras se capturaba el registro. "
                    "Muestra al tutor la versión vigente y pide que la acepte de nuevo."
                ),
                "versionVigente": vigente,
            },
        )
    return vigente
