from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.exceptions import Conflicto, DatosInvalidos, NoEncontrado
from app.repositories import (
    extras_repository,
    paquetes_repository,
    producto_repository,
    registros,
    reservacion_extras_repository,
    reservacion_productos_repository,
    reservaciones_repository,
)
from app.schemas.pagos_reservacion import PagosReservacionCompletarRequest, PagosReservacionOut
from app.schemas.reservacion_extras import ReservacionExtrasOut
from app.schemas.reservacion_productos import ReservacionProductosOut
from app.schemas.reservaciones import (
    EventoDelDiaOut,
    ReservacionesCrear,
    ReservacionesOut,
    ReservacionesUpdate,
)
from app.schemas.reservaciones_completa import (
    ReservacionCompletaExtraItem,
    ReservacionCompletaProductoItem,
    ReservacionCompletaRequest,
    ReservacionCompletaResponse,
)
from app.services import reservacion_estados, reservacion_precio


async def listar(
    conn: asyncpg.Connection,
    scope: str | None = None,
    desde: date | None = None,
    hasta: date | None = None,
) -> list[ReservacionesOut]:
    rows = await reservaciones_repository.listar(conn, scope, desde, hasta)
    return [ReservacionesOut.model_validate(r) for r in rows]


async def obtener_evento_cercano(
    conn: asyncpg.Connection, sucursal_id: UUID
) -> EventoDelDiaOut | None:
    row = await reservaciones_repository.obtener_evento_mas_cercano(conn, sucursal_id)
    if not row:
        return None

    registro_existente = await registros.exists_registro_by_reservacion_id(conn, row["id"])
    if registro_existente:
        return None

    return EventoDelDiaOut.model_validate(row)


async def obtener(conn: asyncpg.Connection, reservacion_id: UUID) -> ReservacionesOut:
    row = await reservaciones_repository.obtener(conn, reservacion_id)
    if not row or not row["activo"]:
        raise NoEncontrado("Reservación", genero="f")
    return ReservacionesOut.model_validate(row)


async def _paquete_de_sucursal(
    conn: asyncpg.Connection, paquete_id: UUID, sucursal_id: UUID
) -> dict[str, Any]:
    paquete = await paquetes_repository.obtener(conn, paquete_id)
    if not paquete or paquete["sucursal_id"] != sucursal_id:
        raise _invalido("PAQUETE_INVALIDO", "El paquete no existe en esta sucursal.")
    if not paquete["activo"]:
        raise Conflicto(
            f"El paquete «{paquete['nombre']}» ya no está disponible. Actualiza la reservación."
        )
    return paquete


async def _precios_extras(
    conn: asyncpg.Connection, extras: list[ReservacionCompletaExtraItem], sucursal_id: UUID
) -> list[Decimal]:
    """Precio de catálogo de cada extra elegido (nunca el del request)."""
    precios: list[Decimal] = []
    for item in extras:
        extra = await extras_repository.obtener(conn, item.extra_id)
        if not extra or extra["sucursal_id"] not in (sucursal_id, None):
            raise _invalido("EXTRA_INVALIDO", "Un extra seleccionado no existe en esta sucursal.")
        if not extra["activo"]:
            raise Conflicto(
                f"El extra «{extra['nombre']}» ya no está disponible. Actualiza la reservación."
            )
        precios.append(Decimal(extra["precio"]))
    return precios


async def _precios_productos(
    conn: asyncpg.Connection,
    productos: list[ReservacionCompletaProductoItem],
    sucursal_id: UUID,
) -> list[Decimal]:
    """Precio de catálogo de cada producto adicional (nunca el del request)."""
    precios: list[Decimal] = []
    for item in productos:
        producto = await producto_repository.obtener(conn, item.producto_id)
        if not producto or producto.sucursal_id != str(sucursal_id):
            raise _invalido(
                "PRODUCTO_INVALIDO", "Un producto adicional no existe en esta sucursal."
            )
        if not producto.activo:
            raise Conflicto(
                f"El producto «{producto.nombre}» ya no está disponible. "
                "Actualiza la reservación."
            )
        precios.append(producto.precio_unitario)
    return precios


async def _dias_para_evento(conn: asyncpg.Connection, sucursal_id: UUID, fecha: date) -> int:
    """Días que faltan para el evento según la fecha local de la sucursal: la
    misma referencia que usa el scheduler para cancelar por falta de pago."""
    hoy = await reservaciones_repository.hoy_en_sucursal(conn, sucursal_id)
    if hoy is None:
        raise _invalido("SUCURSAL_INVALIDA", "La sucursal no existe.")
    return (fecha - hoy).days


def _invalido(code: str, mensaje: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": code, "message": mensaje},
    )


async def _insertar(
    conn: asyncpg.Connection,
    body: ReservacionesCrear,
    desglose: reservacion_precio.DesglosePrecio,
    anticipo: Decimal,
    estado: str,
) -> dict[str, Any]:
    """Inserta la reservación con el precio, anticipo y estado que decidió el
    servidor: los del request se descartan (C2)."""
    data = body.model_dump()
    data.update(
        precio_base=desglose.precio_base,
        precio_personas_extra=desglose.precio_pulseras,
        horas_reservadas=desglose.horas_reservadas,
        precio_horas=Decimal(0),
        precio_extras=desglose.precio_extras,
        precio_productos=desglose.precio_productos,
        descuento=Decimal(0),
        precio_total=desglose.precio_total,
        anticipo=anticipo,
        estado=estado,
    )
    data["folio"] = await reservaciones_repository.siguiente_folio(conn)
    return await reservaciones_repository.crear(conn, data)


async def crear(
    conn: asyncpg.Connection, body: ReservacionesCrear, user_id: str
) -> ReservacionesOut:
    """Alta sin cobro (POST /reservaciones): queda 'pendiente' y debe
    liquidarse una semana antes del evento. El precio lo calcula el servidor
    con el paquete; si el del cliente no coincide, 409 (C2).

    A 7 días o menos del evento no se puede reservar sin pagar: el scheduler
    la cancelaría en menos de una hora (C3). Ese caso va por
    POST /reservaciones/completa con el pago del total."""
    paquete = await _paquete_de_sucursal(conn, body.paquete_id, body.sucursal_id)
    reservacion_precio.validar_cupo(paquete, body.numero_personas)
    desglose = reservacion_precio.calcular_desglose(
        paquete, body.numero_personas, body.hora_inicio, body.hora_fin, [], []
    )
    reservacion_precio.verificar_precio_cliente(body.precio_total, desglose.precio_total)

    dias = await _dias_para_evento(conn, body.sucursal_id, body.fecha_evento)
    if reservacion_precio.exige_liquidacion(dias):
        raise _invalido(
            "LIQUIDACION_REQUERIDA",
            f"El evento es en {max(dias, 0)} días: se debe liquidar al reservar. "
            "Regístrala junto con su pago.",
        )

    row = await _insertar(conn, body, desglose, Decimal(0), "pendiente")
    return ReservacionesOut.model_validate(row)


# Campos de PATCH que cambian el precio: si llega cualquiera, el servidor
# recalcula pulseras y total desde el paquete.
_CAMPOS_DE_PRECIO = {"numero_personas", "horas_reservadas", "precio_personas_extra", "precio_total"}

# Campos que cambian el alcance del evento (invitados, horas, fecha u horario):
# solo se editan dentro del plazo, hasta una semana antes del evento, igual que
# en la pantalla de Reservaciones (N12). Los datos de contacto y las notas se
# pueden corregir mientras la reservación no esté cerrada ni cancelada.
_CAMPOS_DE_ALCANCE = _CAMPOS_DE_PRECIO | {"fecha_evento", "hora_inicio", "hora_fin"}


async def actualizar(
    conn: asyncpg.Connection, reservacion_id: UUID, body: ReservacionesUpdate
) -> ReservacionesOut:
    """Edición parcial. Una reservación cancelada o completada no se edita
    (409), el alcance solo cambia dentro del plazo y `estado` solo cambia por
    la máquina de estados (A8/N12)."""
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    async with conn.transaction():
        # Bloqueo: un cobro simultáneo no debe validar contra un total viejo.
        actual = await reservaciones_repository.obtener_para_actualizar(conn, reservacion_id)
        if not actual or not actual["activo"]:
            raise NoEncontrado("Reservación", genero="f")
        reservacion_estados.asegurar_editable(actual["estado"])

        if updates.get("estado") == actual["estado"]:
            updates.pop("estado")
        if "estado" in updates:
            await _validar_cambio_estado(conn, actual, updates["estado"])

        if _CAMPOS_DE_ALCANCE & updates.keys():
            await _asegurar_dentro_de_plazo(conn, actual, updates.get("fecha_evento"))

        hora_inicio = updates.get("hora_inicio", actual["hora_inicio"])
        hora_fin = updates.get("hora_fin", actual["hora_fin"])
        if hora_fin <= hora_inicio:
            raise DatosInvalidos("hora_fin debe ser mayor a hora_inicio")

        if _CAMPOS_DE_PRECIO & updates.keys():
            updates.update(await _recalcular_precio_edicion(conn, actual, updates))

        row = await reservaciones_repository.actualizar(conn, reservacion_id, updates)
    if not row:
        raise NoEncontrado("Reservación", genero="f")
    return ReservacionesOut.model_validate(row)


async def cerrar(
    conn: asyncpg.Connection,
    reservacion_id: UUID,
    notas_cierre: str | None,
    usuario_id: UUID,
) -> ReservacionesOut:
    """Cierre del evento (POST /reservaciones/{id}/cerrar): pasa a 'completada'
    por la máquina de estados (evento ya iniciado y sin saldo) y AGREGA las
    notas del cierre a las existentes; antes se sobrescribían y se perdía, por
    ejemplo, el motivo de una cancelación (A8)."""
    async with conn.transaction():
        actual = await reservaciones_repository.obtener_para_actualizar(conn, reservacion_id)
        if not actual or not actual["activo"]:
            raise NoEncontrado("Reservación", genero="f")
        await _validar_cambio_estado(conn, actual, reservacion_estados.COMPLETADA)
        row = await reservaciones_repository.actualizar(
            conn,
            reservacion_id,
            {
                "estado": reservacion_estados.COMPLETADA,
                "notas": reservacion_estados.anexar_nota(
                    actual["notas"], notas_cierre, "Cierre del evento"
                ),
                "modificado_por": usuario_id,
            },
        )
    if not row:
        raise NoEncontrado("Reservación", genero="f")
    return ReservacionesOut.model_validate(row)


async def _validar_cambio_estado(
    conn: asyncpg.Connection, actual: dict[str, Any], nuevo: str
) -> None:
    """Carga la hora local de la sucursal y, si hace falta, el anticipo mínimo
    del paquete, y aplica la máquina de estados (409 si no procede)."""
    ahora = await reservaciones_repository.ahora_en_sucursal(conn, actual["sucursal_id"])
    if ahora is None:
        raise _invalido("SUCURSAL_INVALIDA", "La sucursal no existe.")
    anticipo_minimo = Decimal(0)
    if nuevo == reservacion_estados.CONFIRMADA:
        paquete = await paquetes_repository.obtener(conn, actual["paquete_id"])
        porcentaje = reservacion_precio.porcentaje_anticipo(
            paquete["anticipo_porcentaje"] if paquete else None
        )
        total = Decimal(actual["precio_total"])
        anticipo_minimo = min(total, reservacion_precio.monto_por_porcentaje(total, porcentaje))
    reservacion_estados.validar_transicion(
        actual["estado"],
        nuevo,
        fecha_evento=actual["fecha_evento"],
        hora_inicio=actual["hora_inicio"],
        ahora_local=ahora,
        saldo_pendiente=Decimal(actual["saldo_pendiente"]),
        monto_pagado=Decimal(actual["monto_pagado"]),
        anticipo_minimo=anticipo_minimo,
    )


async def _asegurar_dentro_de_plazo(
    conn: asyncpg.Connection, actual: dict[str, Any], nueva_fecha: date | None
) -> None:
    """El alcance solo se modifica hasta una semana antes del evento (el mismo
    plazo de liquidación que usa el scheduler). Si se cambia la fecha, la nueva
    también debe quedar fuera de esa semana."""
    for fecha in {actual["fecha_evento"], nueva_fecha or actual["fecha_evento"]}:
        dias = await _dias_para_evento(conn, actual["sucursal_id"], fecha)
        if reservacion_precio.exige_liquidacion(dias):
            # Último día editable: dias_para_evento > DIAS_LIMITE_LIQUIDACION.
            limite = fecha - timedelta(days=reservacion_precio.DIAS_LIMITE_LIQUIDACION + 1)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "FUERA_DE_PLAZO",
                    "message": (
                        "Fuera de plazo: invitados, horas, fecha y horario solo se pueden "
                        f"modificar hasta el {limite.strftime('%d/%m/%Y')} (el evento es el "
                        f"{fecha.strftime('%d/%m/%Y')})."
                    ),
                },
            )


async def _recalcular_precio_edicion(
    conn: asyncpg.Connection, actual: dict[str, Any], updates: dict[str, Any]
) -> dict[str, Any]:
    """Pulseras y total al cambiar invitados u horas, con la tarifa vigente
    del paquete (como `recalcularReservacion()` del frontend). El total que
    manda el cliente solo se compara: si no coincide, 409."""
    paquete = await paquetes_repository.obtener(conn, actual["paquete_id"])
    if paquete is None:
        raise NoEncontrado("Paquete")
    invitados = int(updates.get("numero_personas", actual["numero_personas"]))
    horas = max(1, int(updates.get("horas_reservadas", actual["horas_reservadas"])))
    if invitados != actual["numero_personas"]:
        reservacion_precio.validar_cupo(paquete, invitados)

    pulseras, total = reservacion_precio.recalcular_total_edicion(
        actual, paquete["precio_hora_pulsera"] or Decimal(0), invitados, horas
    )
    if "precio_total" in updates:
        reservacion_precio.verificar_precio_cliente(updates["precio_total"], total)

    pagado = Decimal(actual["monto_pagado"])
    if total < pagado:
        raise Conflicto(
            f"El nuevo total ({reservacion_precio.formato_mxn(total)}) queda por debajo de lo "
            f"ya pagado ({reservacion_precio.formato_mxn(pagado)}). Devuelve la diferencia "
            "antes de reducir el evento."
        )
    return {
        "numero_personas": invitados,
        "horas_reservadas": horas,
        "precio_personas_extra": pulseras,
        "precio_total": total,
    }


async def eliminar(conn: asyncpg.Connection, reservacion_id: UUID) -> None:
    await obtener(conn, reservacion_id)
    await reservaciones_repository.eliminar(conn, reservacion_id)


async def crear_completa(
    conn: asyncpg.Connection,
    body: ReservacionCompletaRequest,
    usuario_id: UUID,
    apertura_caja_id: str,
) -> ReservacionCompletaResponse:
    """Alta atómica de la reservación con sus extras, productos y pagos (QA
    #10): si algo falla, nada se persiste. Reusa pagos_reservacion.completar()
    (cambio + lealtad + monto_pagado) dentro de la misma transacción -- los
    extras y productos se insertan por repository directo, sin la validación
    de scope de TokenData que ahí no aplica (el usuario ya quedó autorizado a
    nivel de endpoint).

    El servidor recalcula el precio (paquete, pulseras, extras y productos de
    catálogo), valida cupo, catálogo de la sucursal y anticipo mínimo (o el
    100 % si el evento es en 7 días o menos), y decide el estado (C2/C3). Si
    el total que vio el cliente no coincide, 409 y no se crea nada."""
    # Import diferido: evita el ciclo de imports de pagos_reservacion <->
    # reservaciones que ya existe entre sus services.
    from app.services import pagos_reservacion as pagos_reservacion_svc

    reservacion = body.reservacion
    async with conn.transaction():
        # Todo lo que se cobra sale del catálogo y del paquete, no del request (C2).
        paquete = await _paquete_de_sucursal(conn, reservacion.paquete_id, reservacion.sucursal_id)
        reservacion_precio.validar_cupo(paquete, reservacion.numero_personas)
        precios_extras = await _precios_extras(conn, body.extras, reservacion.sucursal_id)
        precios_productos = await _precios_productos(conn, body.productos, reservacion.sucursal_id)
        desglose = reservacion_precio.calcular_desglose(
            paquete,
            reservacion.numero_personas,
            reservacion.hora_inicio,
            reservacion.hora_fin,
            precios_extras,
            [(p, item.cantidad) for p, item in zip(precios_productos, body.productos, strict=True)],
        )
        reservacion_precio.verificar_precio_cliente(reservacion.precio_total, desglose.precio_total)

        # Lo cobrado de verdad: lo entregado menos el cambio devuelto.
        cambio = body.cambio.quantize(reservacion_precio.CENTAVO)
        pagado = sum((p.monto for p in body.pagos), Decimal(0)) - cambio
        dias = await _dias_para_evento(conn, reservacion.sucursal_id, reservacion.fecha_evento)
        reservacion_precio.validar_anticipo(
            desglose.precio_total,
            pagado,
            reservacion_precio.porcentaje_anticipo(paquete["anticipo_porcentaje"]),
            dias,
        )

        # Con el anticipo mínimo cubierto la reservación queda confirmada; el
        # estado lo decide el servidor, no el cliente.
        fila = await _insertar(conn, reservacion, desglose, pagado, "confirmada")
        reservacion_id: UUID = fila["id"]

        extras_out: list[ReservacionExtrasOut] = []
        for extra_item, precio in zip(body.extras, precios_extras, strict=True):
            fila_extra = await reservacion_extras_repository.crear(
                conn,
                reservacion_id=reservacion_id,
                extra_id=extra_item.extra_id,
                # Cada extra se cobra una vez, como hoy el asistente (pendiente M15:
                # los "por persona"/"por hora" deberían multiplicarse).
                cantidad=1,
                precio_unitario=precio,
            )
            extras_out.append(ReservacionExtrasOut.model_validate(fila_extra))

        productos_out: list[ReservacionProductosOut] = []
        for producto_item, precio in zip(body.productos, precios_productos, strict=True):
            fila_producto = await reservacion_productos_repository.crear(
                conn,
                reservacion_id=reservacion_id,
                producto_id=producto_item.producto_id,
                cantidad=producto_item.cantidad,
                precio_unitario=precio,
                notas=producto_item.notas,
                creado_por=usuario_id,
            )
            productos_out.append(ReservacionProductosOut.model_validate(fila_producto))

        pagos_out: list[PagosReservacionOut] = []
        if body.pagos:
            resultado_pagos = await pagos_reservacion_svc.completar(
                conn,
                PagosReservacionCompletarRequest(
                    reservacion_id=reservacion_id,
                    pagos=body.pagos,
                    cambio=cambio,
                ),
                usuario_id,
                apertura_caja_id,
            )
            pagos_out = resultado_pagos.pagos
            cambio = resultado_pagos.cambio
        advertencia_efectivo: str | None = None

        # Se relee para devolver el monto_pagado / saldo que dejaron los pagos.
        fila = await reservaciones_repository.obtener(conn, reservacion_id) or fila
        reservacion_out = ReservacionesOut.model_validate(fila)

    return ReservacionCompletaResponse(
        reservacion=reservacion_out,
        extras=extras_out,
        productos=productos_out,
        pagos=pagos_out,
        cambio=cambio,
        advertencia_efectivo=advertencia_efectivo,
    )
