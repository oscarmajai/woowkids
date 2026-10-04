"""Aviso de privacidad (LFPDPPP) — /api/privacidad."""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ResponsableAviso(BaseModel):
    """Datos del responsable que llenan los marcadores {{...}} del aviso. Se
    aceptan vacíos (la plantilla se puede publicar a medias), pero el aviso
    público muestra «[Pendiente de configurar: ...]» en su lugar."""

    model_config = ConfigDict(str_strip_whitespace=True)

    razon_social: str = Field("", max_length=200)
    nombre_comercial: str = Field("", max_length=150)
    domicilio: str = Field("", max_length=400)
    # Persona o departamento de datos personales que tramita las solicitudes
    # ARCO (art. 29 LFPDPPP).
    area_datos_personales: str = Field("", max_length=150)
    correo_datos_personales: str = Field("", max_length=150)
    telefono_datos_personales: str = Field("", max_length=30)
    # Dirección pública donde se consulta el aviso integral (art. 16 II).
    url_aviso: str = Field("", max_length=300)
    dias_conservacion_imagenes: int = Field(90, ge=1, le=3650)
    anios_conservacion_registros: int = Field(5, ge=1, le=20)

    @field_validator("correo_datos_personales")
    @classmethod
    def _correo_valido(cls, v: str) -> str:
        if v and not _CORREO.match(v):
            raise ValueError("debe ser un correo electrónico válido")
        return v


class AvisoPublicoOut(BaseModel):
    """GET /api/privacidad/aviso — versión vigente con los marcadores ya
    reemplazados. Público: lo consultan el tutor, la recepción y el portal."""

    version: int
    vigente_desde: datetime
    fecha_vigencia: date
    nombre_comercial: str
    texto_integral: str
    texto_simplificado: str


class VersionAvisoOut(BaseModel):
    version: int
    vigente_desde: datetime
    publicado_por: str | None
    motivo_cambio: str | None


class AvisoAdminOut(BaseModel):
    """GET /api/privacidad/admin/aviso — para editar y publicar (solo
    AdministradorSistema). Los textos van como plantilla, con sus marcadores."""

    version: int
    vigente_desde: datetime
    publicado_por: str | None
    motivo_cambio: str | None
    responsable: ResponsableAviso
    texto_integral: str
    texto_simplificado: str
    # Marcadores que se pueden usar en los textos y qué dato los llena.
    marcadores: dict[str, str]
    # Datos del responsable sin capturar (salen como «Pendiente» en el aviso).
    pendientes: list[str]
    historial: list[VersionAvisoOut]


class PublicarAvisoIn(BaseModel):
    """POST /api/privacidad/admin/aviso — publica una versión nueva. Sin
    textos, se conservan los de la versión vigente."""

    # Versión sobre la que se editó: si alguien publicó otra mientras tanto,
    # 409 en vez de pisarla sin verla.
    version_base: int = Field(..., ge=1)
    responsable: ResponsableAviso
    texto_integral: str | None = Field(None, min_length=1, max_length=100_000)
    texto_simplificado: str | None = Field(None, min_length=1, max_length=20_000)
    motivo_cambio: str | None = Field(None, max_length=500)
