from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from app.core.roles import ROL_PADRE
from app.core.security import (
    create_access_token,
    generate_codigo_acceso_padres,
    hash_codigo_acceso_padres,
)
from app.repositories import codigos_acceso_padres, lealtad_repository
from app.repositories.branch_repository import get_sucursal_by_id
from app.repositories.tutores import get_tutor_by_id
from app.schemas.padres import (
    LealtadPadreInfo,
    NinoActivoResponse,
    PadreDashboardResponse,
    PadreNinosActivosResponse,
    SucursalInfo,
    TutorInfo,
)
from app.services.lealtad_service import DIAS_POR_VENCER
from app.services.permission_service import get_permissions


async def _get_lealtad_tutor(
    conn: asyncpg.Connection, sucursal_id: UUID, telefono: str
) -> LealtadPadreInfo:
    """WP B4, pendiente 5 — saldo de puntos de lealtad del tutor (celular =
    telefono del tutor), para la tarjeta "Tus puntos Woow" del portal de
    padres. No requiere que exista configuracion_lealtad para la sucursal:
    sin movimientos, el saldo simplemente es 0."""
    saldo = await lealtad_repository.calcular_saldo(conn, sucursal_id, telefono)
    por_vencer = await lealtad_repository.calcular_por_vencer(
        conn, sucursal_id, telefono, DIAS_POR_VENCER
    )
    return LealtadPadreInfo(saldo=saldo, por_vencer=por_vencer)


class TokenAccesoInvalidoError(Exception):
    pass


# A17 — vigencia máxima del código del QR (además deja de valer al hacer
# checkout del último niño del registro) y de la sesión que se obtiene con él.
VIGENCIA_CODIGO_ACCESO = timedelta(hours=24)
VIGENCIA_SESION_PADRE = timedelta(hours=2)
# token_urlsafe(24) produce 32 caracteres; cualquier cosa mucho más larga no
# es un código nuestro y no vale la pena ni hashearla.
_LONGITUD_MAXIMA_CODIGO = 128


async def emitir_codigo_acceso(
    conn: asyncpg.Connection, registro_id: UUID, usuario_id: UUID | None
) -> str:
    """A17 — emite el código opaco del QR del comprobante para un registro y
    revoca cualquier código anterior del mismo registro (un solo código vigente
    por registro: reimprimir el comprobante debe invalidar el QR viejo).
    Devuelve el código en claro; en BD solo queda su sha256."""
    codigo, codigo_hash = generate_codigo_acceso_padres()
    await codigos_acceso_padres.revocar_codigos_de_registro(conn, registro_id)
    await codigos_acceso_padres.crear_codigo(
        conn,
        registro_id,
        codigo_hash,
        datetime.now(UTC) + VIGENCIA_CODIGO_ACCESO,
        usuario_id,
    )
    return codigo


async def revocar_codigos_acceso(conn: asyncpg.Connection, registro_id: UUID) -> None:
    """A17 — el QR deja de valer al hacer checkout de todos los niños."""
    await codigos_acceso_padres.revocar_codigos_de_registro(conn, registro_id)


async def _get_hijos_visita(conn: asyncpg.Connection, registro_id: UUID) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT
            n.id,
            n.nombre_completo AS "nombreCompleto",
            n.edad,
            CASE
                WHEN dr.salida IS NULL THEN 'activo'
                ELSE 'terminado'
            END AS "estadoVisita",
            dr.entrada AT TIME ZONE 'America/Mexico_City' AS "horaEntrada",
            dr.salida_esperada AT TIME ZONE 'America/Mexico_City' AS "horaSalidaEsperada",
            dr.salida AT TIME ZONE 'America/Mexico_City' AS "horaSalida",
            CASE
                WHEN dr.salida IS NULL
                THEN FLOOR(EXTRACT(EPOCH FROM (NOW() - dr.entrada)) / 60)::int
                ELSE FLOOR(EXTRACT(EPOCH FROM (dr.salida - dr.entrada)) / 60)::int
            END AS "minutosTranscurridos",
            (dr.cantidad * 60)::int AS "minutosPagados",
            p.pulsera_rfid AS "pulsera",
            dr.precio AS "precio",
            dr.cantidad AS "cantidad",
            dr.salida_esperada AS "salidaEsperadaRaw",
            (
                SELECT COALESCE(SUM(ce.total), 0)
                FROM cargos_extra_estancia ce
                WHERE ce.detalles_registro_id = dr.id
            ) AS "cargoExtraCobrado",
            (
                SELECT COALESCE(SUM(mp.puntos), 0)
                FROM movimientos_puntos mp
                WHERE mp.registro_id = r.id AND mp.tipo = 'O'
            ) AS "puntosGanadosRegistro"
        FROM detalles_registro dr
        JOIN registros r ON r.id = dr.registros_id
        JOIN ninos n ON n.id = dr.ninos_id
        JOIN pulseras p ON p.id = dr.pulseras_id
        WHERE r.id = $1
          AND r.estado = 'A'
          AND dr.activo = TRUE
        ORDER BY
            CASE WHEN dr.salida IS NULL THEN 0 ELSE 1 END,
            dr.entrada DESC
        """,
        registro_id,
    )
    return [dict(r) for r in rows]


def _build_nino_activo(hijo: dict[str, Any], now: datetime) -> NinoActivoResponse:
    """Agrega cargoExtra (visita activa) o importe/puntosGanados (visita
    terminada) al DTO de un hijo, reusando la misma fórmula de excedente que
    cotizar_checkout para no desincronizarse de ella (ver chekouts.py)."""
    # Import local para evitar un ciclo: chekouts no importa este módulo.
    from app.services.chekouts import _calcular_cargo_extra_sync

    cargo_extra = 0.0
    importe: float | None = None
    puntos_ganados: int | None = None

    if hijo["estadoVisita"] == "activo":
        _, cargo_extra = _calcular_cargo_extra_sync(hijo["salidaEsperadaRaw"], hijo["precio"], now)
    else:
        importe = float(hijo["precio"]) * hijo["cantidad"] + float(hijo["cargoExtraCobrado"])
        puntos_ganados = int(hijo["puntosGanadosRegistro"])

    return NinoActivoResponse(
        id=UUID(str(hijo["id"])),
        nombreCompleto=hijo["nombreCompleto"],
        edad=hijo["edad"],
        estadoVisita=hijo["estadoVisita"],
        horaEntrada=hijo["horaEntrada"],
        horaSalidaEsperada=hijo["horaSalidaEsperada"],
        horaSalida=hijo["horaSalida"],
        minutosTranscurridos=hijo["minutosTranscurridos"],
        minutosPagados=hijo["minutosPagados"],
        pulsera=hijo["pulsera"],
        cargoExtra=cargo_extra,
        importe=importe,
        puntosGanados=puntos_ganados,
    )


async def get_padre_dashboard(conn: asyncpg.Connection, raw_code: str) -> PadreDashboardResponse:
    """A17 — canjea el código opaco del QR por una sesión de padre. El código
    se busca por su sha256 (índice único): no se compara el código en claro y
    la respuesta es la misma excepción para código mal formado, inexistente,
    revocado, expirado o de un registro ya cerrado. Los códigos viejos (el
    UUID del registro) ya no existen en la tabla y se rechazan igual."""
    if not raw_code or len(raw_code) > _LONGITUD_MAXIMA_CODIGO:
        raise TokenAccesoInvalidoError

    registro = await codigos_acceso_padres.get_registro_por_codigo(
        conn, hash_codigo_acceso_padres(raw_code)
    )
    if registro is None:
        raise TokenAccesoInvalidoError
    registro_id: UUID = registro["registroId"]

    tutor = await get_tutor_by_id(conn, registro["tutorId"])
    if tutor is None:
        raise TokenAccesoInvalidoError

    sucursal = await get_sucursal_by_id(conn, registro["sucursalId"])
    if sucursal is None:
        raise TokenAccesoInvalidoError

    hijos = await _get_hijos_visita(conn, registro_id)
    now = datetime.now(UTC)
    lealtad = await _get_lealtad_tutor(conn, sucursal["id"], tutor["telefono"])

    # La sesión nunca dura más que el código con el que se obtuvo.
    expires_delta = min(VIGENCIA_SESION_PADRE, registro["expira"] - now)
    access_token = create_access_token(
        payload={
            "sub": str(registro_id),
            "email": f"{tutor['telefono']}@tutor.woowkids.local",
            "tutor_id": str(tutor["id"]),
            "branch_id": str(sucursal["id"]),
            "role": ROL_PADRE,
            "permissions": get_permissions(ROL_PADRE),
        },
        expires_delta=expires_delta,
    )

    return PadreDashboardResponse(
        token=access_token,
        expires_in=int(expires_delta.total_seconds()),
        tutor=TutorInfo(
            id=tutor["id"],
            nombreCompleto=tutor["nombreCompleto"],
            telefono=tutor["telefono"],
            sucursal=SucursalInfo(
                id=sucursal["id"],
                nombre=sucursal["nombre"],
            ),
            lealtad=lealtad,
        ),
        ninosActivos=[_build_nino_activo(h, now) for h in hijos],
    )


async def get_ninos_activos(
    conn: asyncpg.Connection, registro_id: UUID
) -> PadreNinosActivosResponse:
    """QA #31 — polling autenticado con el token de sesión del padre (no vuelve
    a canjear el código). Si el registro ya no está activo (p. ej. se cerró o
    se revocó), el token deja de servir: el front recibe 400 y cierra sesión."""
    registro = await conn.fetchrow(
        "SELECT 1 FROM registros WHERE id = $1 AND activo = TRUE AND estado = 'A'",
        registro_id,
    )
    if registro is None:
        raise TokenAccesoInvalidoError

    hijos = await _get_hijos_visita(conn, registro_id)
    now = datetime.now(UTC)
    return PadreNinosActivosResponse(ninosActivos=[_build_nino_activo(h, now) for h in hijos])
