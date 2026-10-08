from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.core.scope import sucursal_scope
from app.exceptions import NoEncontrado
from app.repositories import (
    metodos_pago_repository,
    pagos_reservacion_repository,
    reservaciones_repository,
)
from app.repositories.caja_repository import registrar_cambio_caja, registrar_movimiento_caja
from app.schemas.auth import TokenData
from app.schemas.pagos_reservacion import (
    PagoReservacionItem,
    PagosReservacionCompletarRequest,
    PagosReservacionCompletarResponse,
    PagosReservacionCreate,
    PagosReservacionOut,
    PagosReservacionUpdate,
)
from app.services import lealtad_service, turnos_caja_service
from app.services.validaciones_pago import validar_cambio


async def listar_todos(
    conn: asyncpg.Connection, scope: str | None = None
) -> list[PagosReservacionOut]:
    rows = await pagos_reservacion_repository.listar_todos(conn, scope)
    return [PagosReservacionOut.model_validate(r) for r in rows]


async def listar_por_reservacion(
    conn: asyncpg.Connection, reservacion_id: UUID, current_user: TokenData
) -> list[PagosReservacionOut]:
    reservacion = await reservaciones_repository.obtener(conn, reservacion_id)
    if not reservacion:
        raise NoEncontrado("Reservación", genero="f")

    scope = sucursal_scope(current_user)
    if scope is not None and str(reservacion["sucursal_id"]) != scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puede consultar pagos de reservaciones de otra sucursal.",
        )

    rows = await pagos_reservacion_repository.listar_por_reservacion(conn, reservacion_id)
    return [PagosReservacionOut.model_validate(r) for r in rows]


async def obtener(conn: asyncpg.Connection, pago_id: UUID) -> PagosReservacionOut:
    row = await pagos_reservacion_repository.obtener(conn, pago_id)
    if not row:
        raise NoEncontrado("Pago")
    return PagosReservacionOut.model_validate(row)


async def _resolver_tipo(
    conn: asyncpg.Connection, reservacion_id: UUID, monto: Decimal, tipo_solicitado: str | None
) -> str:
    """Si este pago deja el saldo de la reservación en 0 (o menos, por un
    sobrepago), siempre se marca como 'liquidacion' sin importar lo que se
    haya pedido -- regla de negocio explícita para distinguir
    el anticipo de la liquidación. En cualquier otro caso se respeta `tipo_solicitado`
    (o 'pago' si no se mandó ninguno)."""
    reservacion = await reservaciones_repository.obtener(conn, reservacion_id)
    if reservacion is not None:
        pagado_previo = await pagos_reservacion_repository.sumar_pagos(conn, reservacion_id)
        saldo_tras_pago = reservacion["precio_total"] - (pagado_previo + monto)
        if saldo_tras_pago <= 0:
            return "liquidacion"
    return tipo_solicitado or "pago"


async def _validar_metodo_pago(conn: asyncpg.Connection, metodo_pago_id: UUID) -> None:
    """Sin esto un metodo_pago_id inexistente llegaba hasta el INSERT y la
    llave foránea respondía 500 en lugar de un error de validación."""
    if not await metodos_pago_repository.existe(conn, metodo_pago_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El método de pago no existe.",
        )


def _excede_saldo(monto: Decimal, saldo: Decimal) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "PAGO_EXCEDE_SALDO",
            "message": (
                f"El pago (${monto:,.2f}) excede el saldo pendiente de la "
                f"reservación (${max(saldo, Decimal(0)):,.2f})."
            ),
            "saldo_pendiente": str(max(saldo, Decimal(0))),
        },
    )


async def _otorgar_puntos(
    conn: asyncpg.Connection, reservacion_id: UUID, monto: Decimal, usuario_id: UUID
) -> None:
    reservacion = await reservaciones_repository.obtener(conn, reservacion_id)
    celular = (reservacion["telefono_cliente"] or "").strip() if reservacion else ""
    if reservacion and celular and monto > 0:
        await lealtad_service.otorgar_puntos(
            conn,
            reservacion["sucursal_id"],
            celular,
            monto,
            usuario_id,
            reservacion_id=reservacion_id,
        )


async def _saldo_bloqueado(conn: asyncpg.Connection, reservacion_id: UUID) -> Decimal:
    """Bloquea la reservación (los cobros simultáneos se aplican en orden)
    y devuelve su saldo pendiente real."""
    bloqueada = await reservaciones_repository.obtener_para_actualizar(conn, reservacion_id)
    if bloqueada is None:
        raise NoEncontrado("Reservación", genero="f")
    return Decimal(str(bloqueada["saldo_pendiente"]))


async def crear(
    conn: asyncpg.Connection,
    body: PagosReservacionCreate,
    usuario_id: UUID,
    apertura_caja_id: str,
    *,
    desde_completar: bool = False,
) -> PagosReservacionOut:
    """Registra un pago de reservación con su movimiento de caja y sus puntos.

    El pago no puede exceder el saldo pendiente
    (409 PAGO_EXCEDE_SALDO); si no, se aceptaría cualquier monto y se otorgarían
    puntos sobre él. `completar()` ya valida el saldo de todo el cobro (con el
    cambio) y otorga los puntos sobre lo neto, así que con `desde_completar`
    este paso no repite ninguna de las dos cosas."""
    # Transacción propia (o savepoint si ya hay una, p. ej. desde completar()):
    # pago, movimiento de caja, puntos y monto_pagado quedan juntos o no quedan.
    async with conn.transaction():
        # Primero la apertura (orden de bloqueo de caja) y el turno debe
        # seguir ABIERTA hasta que el cobro confirme.
        await turnos_caja_service.bloquear_turno_para_cobro(conn, apertura_caja_id)
        # Bloquea la reservación: dos cobros simultáneos se aplican en orden y el
        # segundo recalcula monto_pagado viendo el primero.
        saldo = await _saldo_bloqueado(conn, body.reservacion_id)
        if not desde_completar and body.monto > saldo:
            raise _excede_saldo(body.monto, saldo)
        await _validar_metodo_pago(conn, body.metodo_pago_id)
        tipo = await _resolver_tipo(conn, body.reservacion_id, body.monto, body.tipo)
        row = await pagos_reservacion_repository.crear(
            conn,
            reservacion_id=body.reservacion_id,
            metodo_pago_id=body.metodo_pago_id,
            monto=body.monto,
            fecha_pago=datetime.now(UTC),
            notas=body.notas,
            tipo=tipo,
            # Sin esto la columna quedaba siempre en NULL y el historial no podía
            # decir quién cobró el evento, a diferencia de las ventas de mostrador.
            creado_por=usuario_id,
        )

        await registrar_movimiento_caja(
            conn,
            apertura_caja_id=apertura_caja_id,
            tipo_movimiento="R",
            referencia_id=str(row["id"]),
            metodo_pago_id=str(body.metodo_pago_id),
            monto=body.monto,
            creado_por=str(usuario_id),
        )

        if not desde_completar:
            await _otorgar_puntos(conn, body.reservacion_id, body.monto, usuario_id)

        # El saldo de la reservación refleja todos los pagos, no solo el anticipo.
        await reservaciones_repository.recalcular_monto_pagado(conn, body.reservacion_id)

    return PagosReservacionOut.model_validate(row)


async def completar(
    conn: asyncpg.Connection,
    body: PagosReservacionCompletarRequest,
    usuario_id: UUID,
    apertura_caja_id: str,
) -> PagosReservacionCompletarResponse:
    """Agrupa N pagos + 1 cambio opcional en una transacción atómica -- la
    arquitectura objetivo (alternativa B) para Reservaciones, análoga a
    pago_service.completar_pago del POS. Reusa crear() por cada pago sin
    modificar su firma ni su comportamiento (movimiento 'R' + lealtad, sin
    cambios); solo agrega la validación de cambio y el movimiento 'C' una
    vez al final, dentro de la misma transacción."""
    ids_efectivo = await metodos_pago_repository.obtener_ids_por_tipo(conn, "E")
    cambio = body.cambio.quantize(Decimal("0.01"))
    validar_cambio(
        [(p.metodo_pago_id, p.monto) for p in body.pagos],
        cambio,
        ids_efectivo,
    )

    pagos_creados: list[PagosReservacionOut] = []
    neto = sum((p.monto for p in body.pagos), Decimal(0)) - cambio
    async with conn.transaction():
        # También aquí, por si no hay pagos y solo se registra el cambio.
        await turnos_caja_service.bloquear_turno_para_cobro(conn, apertura_caja_id)
        # Lo que se aplica (pagos menos el cambio devuelto) no puede
        # exceder el saldo. El efectivo sí puede pasarse, por el cambio.
        saldo = await _saldo_bloqueado(conn, body.reservacion_id)
        if neto > saldo:
            raise _excede_saldo(neto, saldo)
        item: PagoReservacionItem
        for item in body.pagos:
            pago_out = await crear(
                conn,
                PagosReservacionCreate(
                    reservacion_id=body.reservacion_id,
                    metodo_pago_id=item.metodo_pago_id,
                    monto=item.monto,
                    notas=item.notas,
                    tipo=item.tipo,
                ),
                usuario_id,
                apertura_caja_id,
                desde_completar=True,
            )
            pagos_creados.append(pago_out)
        if cambio > 0:
            await registrar_cambio_caja(
                conn,
                apertura_caja_id=apertura_caja_id,
                referencia_id=str(body.reservacion_id),
                monto=cambio,
                creado_por=str(usuario_id),
            )
            # El cambio devuelto no es ingreso del evento: se descuenta de lo pagado.
            await reservaciones_repository.recalcular_monto_pagado(conn, body.reservacion_id)
        # Puntos sobre lo cobrado neto: el cambio devuelto no genera puntos.
        await _otorgar_puntos(conn, body.reservacion_id, neto, usuario_id)

    return PagosReservacionCompletarResponse(pagos=pagos_creados, cambio=cambio)


_PAGO_REGISTRADO = (
    "Un pago registrado no se modifica ni se borra: ya movió la caja y los puntos "
    "de lealtad del cliente. Si se registró por error, el administrador hace el "
    "ajuste (retiro de caja y ajuste de puntos)."
)


async def actualizar(
    conn: asyncpg.Connection, pago_id: UUID, body: PagosReservacionUpdate
) -> PagosReservacionOut:
    """Solo se corrigen las notas. Cambiar el
    monto o el método recalcularía `monto_pagado`, pero dejaría el movimiento de
    caja y los puntos como estaban, y cualquier cajero podría reducir el pago de
    un cliente sin autorización."""
    updates = body.model_dump(exclude_unset=True)
    if set(updates) - {"notas"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PAGO_NO_EDITABLE", "message": _PAGO_REGISTRADO},
        )
    async with conn.transaction():
        await obtener(conn, pago_id)
        row = await pagos_reservacion_repository.actualizar(conn, pago_id, updates)
        if not row:
            raise NoEncontrado("Pago")
    return PagosReservacionOut.model_validate(row)


async def eliminar(conn: asyncpg.Connection, pago_id: UUID) -> None:
    """Un pago registrado no se borra: borrarlo dejaría en el turno el
    movimiento de caja y los puntos otorgados."""
    await obtener(conn, pago_id)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "PAGO_NO_ELIMINABLE", "message": _PAGO_REGISTRADO},
    )
