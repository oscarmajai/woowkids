"""Máquina de estados de una reservación (A8/N12).

Estados: pendiente → confirmada → (en_curso) → completada, y cancelada desde
pendiente o confirmada. `completada` y `cancelada` son terminales: de ahí no se
sale ni se edita nada. Antes cualquier PATCH podía poner cualquier estado, y así
una reservación cancelada se "cerró" como completada horas antes del evento.

Reglas por destino:
- confirmada: lo pagado cubre el anticipo mínimo del paquete (la misma regla
  con la que el alta deja una reservación confirmada).
- en_curso: el evento ya empezó.
- completada: el evento ya empezó y no queda saldo pendiente.

"Ya empezó" se mide con la fecha y hora local de la sucursal (`zona_horaria`),
no con la hora UTC del servidor.

Aquí solo vive la lógica pura; el service carga la fila, la hora local y el
anticipo mínimo y llama a `validar_transicion`.
"""

from datetime import date, datetime, time
from decimal import Decimal

from fastapi import HTTPException, status

from app.services.reservacion_precio import formato_mxn

PENDIENTE = "pendiente"
CONFIRMADA = "confirmada"
EN_CURSO = "en_curso"
COMPLETADA = "completada"
CANCELADA = "cancelada"

TERMINALES = frozenset({COMPLETADA, CANCELADA})

TRANSICIONES: dict[str, frozenset[str]] = {
    PENDIENTE: frozenset({CONFIRMADA, EN_CURSO, COMPLETADA, CANCELADA}),
    CONFIRMADA: frozenset({EN_CURSO, COMPLETADA, CANCELADA}),
    EN_CURSO: frozenset({COMPLETADA}),
    COMPLETADA: frozenset(),
    CANCELADA: frozenset(),
}

_ETIQUETAS = {
    PENDIENTE: "pendiente",
    CONFIRMADA: "confirmada",
    EN_CURSO: "en curso",
    COMPLETADA: "completada",
    CANCELADA: "cancelada",
}


def _conflicto(code: str, mensaje: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": mensaje},
    )


def etiqueta(estado: str) -> str:
    return _ETIQUETAS.get(estado, estado)


def es_terminal(estado: str) -> bool:
    return estado in TERMINALES


def asegurar_editable(estado: str) -> None:
    """409 si la reservación ya está cerrada o cancelada: no se edita nada."""
    if estado == CANCELADA:
        raise _conflicto(
            "RESERVACION_CERRADA",
            "La reservación está cancelada: ya no se puede modificar.",
        )
    if estado == COMPLETADA:
        raise _conflicto(
            "RESERVACION_CERRADA",
            "El evento ya se cerró como completado: la reservación ya no se puede modificar.",
        )


def evento_iniciado(fecha_evento: date, hora_inicio: time, ahora_local: datetime) -> bool:
    """True si la fecha/hora local de la sucursal ya alcanzó el inicio del evento."""
    return ahora_local.replace(tzinfo=None) >= datetime.combine(fecha_evento, hora_inicio)


def validar_transicion(
    actual: str,
    nuevo: str,
    *,
    fecha_evento: date,
    hora_inicio: time,
    ahora_local: datetime,
    saldo_pendiente: Decimal,
    monto_pagado: Decimal,
    anticipo_minimo: Decimal,
) -> None:
    """409 con un mensaje claro si `actual → nuevo` no está permitido."""
    asegurar_editable(actual)
    if nuevo not in TRANSICIONES.get(actual, frozenset()):
        raise _conflicto(
            "TRANSICION_INVALIDA",
            f"Una reservación {etiqueta(actual)} no puede pasar a {etiqueta(nuevo)}.",
        )

    if nuevo in (EN_CURSO, COMPLETADA) and not evento_iniciado(
        fecha_evento, hora_inicio, ahora_local
    ):
        inicio = datetime.combine(fecha_evento, hora_inicio).strftime("%d/%m/%Y a las %H:%M")
        accion = "cerrar" if nuevo == COMPLETADA else "iniciar"
        raise _conflicto(
            "EVENTO_NO_INICIADO",
            f"El evento aún no empieza (inicia el {inicio}): no se puede {accion} antes.",
        )

    if nuevo == COMPLETADA and saldo_pendiente > 0:
        raise _conflicto(
            "SALDO_PENDIENTE",
            f"La reservación tiene un saldo pendiente de {formato_mxn(saldo_pendiente)}: "
            "liquídalo antes de cerrar el evento.",
        )

    if nuevo == CONFIRMADA and monto_pagado < anticipo_minimo:
        raise _conflicto(
            "ANTICIPO_INSUFICIENTE",
            f"Para confirmar la reservación se necesita el anticipo mínimo de "
            f"{formato_mxn(anticipo_minimo)} (pagado: {formato_mxn(monto_pagado)}).",
        )


def anexar_nota(notas: str | None, nota: str | None, encabezado: str) -> str | None:
    """Agrega `nota` al final de las notas existentes sin borrarlas."""
    nota = (nota or "").strip()
    if not nota:
        return notas
    bloque = f"{encabezado}: {nota}"
    return f"{notas}\n{bloque}" if notas else bloque
