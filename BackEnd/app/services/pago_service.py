import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import asyncpg

from app.exceptions import (
    Conflicto,
    DatosInvalidos,
    IdempotenciaConflictoError,
    IdempotenciaEnCursoError,
    NoEncontrado,
    PedidoInvalidoError,
)
from app.models.comanda import Comanda
from app.repositories import (
    comanda_repository,
    folio_repository,
    metodos_pago_repository,
    pago_repository,
    sucursales,
)
from app.repositories.caja_repository import registrar_cambio_caja, registrar_movimiento_caja
from app.schemas.comanda import ComandaCreate, EstadoComanda
from app.schemas.pagos import (
    DetalleOrdenOut,
    EstadisticasOut,
    HistorialOut,
    PagoCompletoRequest,
    PaymentItem,
    PaymentOut,
    PaymentRequest,
)
from app.services import inventario_service, lealtad_service, precios_venta
from app.services.validaciones_pago import validar_cambio


def _hash_payload(body: PagoCompletoRequest) -> str:
    """Hash estable del payload para detectar reintentos con la misma
    Idempotency-Key pero datos distintos (QA #20)."""
    payload_json = json.dumps(body.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


# Lo que arma el POS cuando la tarjeta no trae folio: "CREDITO - Folio: ".
_PREFIJO_FOLIO_TARJETA = re.compile(r"^\s*(DEBITO|CREDITO)\s*-\s*Folio:\s*", re.IGNORECASE)


def _referencia_de_pago(pago: PaymentItem) -> str:
    return _PREFIJO_FOLIO_TARJETA.sub("", pago.notas_pago or "").strip()


async def _validar_metodos_pago(
    conn: asyncpg.Connection, sucursal_id: UUID, pagos: list[PaymentItem]
) -> None:
    """Cada pago debe usar un método que exista y esté activo en la sucursal,
    y traer referencia (folio, autorización) si el método la exige (M11:
    antes solo lo validaba la UI)."""
    for pago in pagos:
        metodo = await metodos_pago_repository.obtener(conn, pago.metodo_pago_id, sucursal_id)
        if metodo is None:
            raise PedidoInvalidoError("El método de pago no existe.", code="METODO_PAGO_INVALIDO")
        if not metodo["activo"]:
            raise PedidoInvalidoError(
                f"El método de pago «{metodo['nombre']}» no está activo en esta sucursal.",
                code="METODO_PAGO_INVALIDO",
            )
        if metodo["requiere_referencia"] and not _referencia_de_pago(pago):
            raise PedidoInvalidoError(
                f"El pago con «{metodo['nombre']}» requiere la referencia o el folio "
                "de autorización.",
                code="REFERENCIA_REQUERIDA",
            )


async def procesar_pagos(
    conn: asyncpg.Connection,
    body: PaymentRequest,
    usuario_id: UUID,
) -> list[PaymentOut]:
    total_pagos: Decimal = sum((p.monto for p in body.pagos), Decimal(0))

    if total_pagos != body.total_esperado:
        raise DatosInvalidos(
            f"El total de los pagos ({total_pagos}) no coincide "
            f"con el total esperado ({body.total_esperado})."
        )

    rows = await pago_repository.crear_pagos(
        conn,
        comanda_id=body.comanda_id,
        sucursal_id=body.sucursal_id,
        pagos=body.pagos,
        usuario_id=usuario_id,
    )

    return [PaymentOut.model_validate(r) for r in rows]


async def _comanda_idempotente(
    conn: asyncpg.Connection, clave: str, hash_payload: str | None
) -> Comanda | None:
    """La comanda que ya se cobró con `clave` (con sus combos expandidos), o
    None si la clave no se ha usado. 409 IDEMPOTENCIA_CONFLICTO si se usó con
    otros datos."""
    from app.services.comanda_service import expandir_detalles_comanda

    existente = await pago_repository.obtener_idempotencia(conn, clave)
    if not existente:
        return None
    if existente["hash_payload"] != hash_payload:
        raise IdempotenciaConflictoError()
    comanda = await comanda_repository.get_comanda_por_id(conn, str(existente["comanda_id"]))
    if comanda is None:
        return None
    comanda.detalles = await expandir_detalles_comanda(conn, comanda.detalles)
    return comanda


async def completar_pago(
    conn: asyncpg.Connection,
    body: PagoCompletoRequest,
    usuario_id: UUID,
    sucursal_id: UUID,
    apertura_caja_id: str,
    idempotency_key: str | None = None,
) -> Comanda:
    """Crea la comanda, registra los pagos, el movimiento de caja de cada uno
    y, si hubo cambio, su propio movimiento
    (multimodal: una comanda puede pagarse con varios métodos) en una única
    transacción. Si falla cualquiera de los dos, nada se persiste (rollback
    automático). Después del commit, expande los detalles de combos y
    notifica a cocina vía WebSocket.

    Si viene `idempotency_key` (header Idempotency-Key, QA #20): si la clave
    ya existe con el mismo hash de payload, devuelve la comanda original sin
    volver a cobrar ni descontar inventario; si existe con un hash distinto,
    lanza 409 IDEMPOTENCIA_CONFLICTO. Sin header, el comportamiento es idéntico
    al previo.
    """
    from app.core.ws_manager import manager
    from app.services.comanda_service import expandir_detalles_comanda

    hash_payload = _hash_payload(body) if idempotency_key else None

    if idempotency_key:
        original = await _comanda_idempotente(conn, idempotency_key, hash_payload)
        if original is not None:
            return original

    await _validar_metodos_pago(conn, sucursal_id, body.pagos)

    # C2: el precio, el importe y el total salen del catálogo de la sucursal de
    # la sesión, no del request. Si el cliente mandó otra cosa, 409 sin cobrar.
    venta = await precios_venta.calcular_venta(conn, sucursal_id, body.detalles_comanda)
    descuento_esperado = Decimal("0")
    if body.puntos_a_redimir > 0:
        descuento_esperado = await lealtad_service.calcular_descuento(
            conn, sucursal_id, body.puntos_a_redimir
        )
    total_final = precios_venta.a_centavos(venta.subtotal - descuento_esperado)
    if total_final <= 0:
        raise DatosInvalidos(
            f"El descuento por puntos ({precios_venta.formatear_pesos(descuento_esperado)}) "
            f"no puede cubrir todo el pedido ({precios_venta.formatear_pesos(venta.subtotal)})."
        )
    precios_venta.verificar_total(body.total_final, total_final)

    total_pagos: Decimal = sum((p.monto for p in body.pagos), Decimal(0))
    if total_pagos < total_final:
        raise DatosInvalidos(
            f"El total de los pagos ({total_pagos}) es menor "
            f"al total de la comanda ({total_final})."
        )

    ids_efectivo = await metodos_pago_repository.obtener_ids_por_tipo(conn, "E")
    cambio = body.cambio.quantize(Decimal("0.01"))
    if cambio > total_pagos - total_final:
        raise DatosInvalidos(
            f"El cambio declarado ({cambio}) es mayor al excedente pagado "
            f"({total_pagos - total_final})."
        )
    validar_cambio(
        [(p.metodo_pago_id, p.monto) for p in body.pagos],
        cambio,
        ids_efectivo,
    )
    # Lo que entra a caja menos el cambio tiene que ser exactamente el total:
    # un excedente sin cambio declarado descuadra el arqueo.
    if total_pagos - cambio != total_final:
        raise DatosInvalidos(
            f"Los pagos ({total_pagos}) menos el cambio ({cambio}) deben sumar "
            f"exactamente el total de la comanda ({total_final})."
        )

    async with conn.transaction():
        if idempotency_key:
            # M3: dos cobros simultáneos con la misma clave pasaban los dos la
            # revisión de arriba y el segundo chocaba con la llave primaria de
            # pagos_idempotencia (500). Ahora el segundo espera aquí a que el
            # primero termine y devuelve su venta.
            await pago_repository.bloquear_clave_idempotencia(conn, idempotency_key)
            original = await _comanda_idempotente(conn, idempotency_key, hash_payload)
            if original is not None:
                return original

        # Folio de ticket secuencial por sucursal (QA #21): el backend asigna
        # ticket_numero de forma atómica dentro de esta transacción.
        # body.ticket_numero (lo que mande el front, si manda algo) queda solo
        # como fallback si por algún motivo siguiente_folio no devuelve nada;
        # como último recurso, un folio temporal para no bloquear el cobro.
        ticket_numero = (
            await folio_repository.siguiente_folio(conn, sucursal_id)
            or body.ticket_numero
            or f"T{uuid4().hex[:7].upper()}"
        )

        comanda_in = ComandaCreate(
            ticket_numero=ticket_numero,
            total_final=total_final,
            estado_actual=EstadoComanda.PENDIENTE,
            detalles_comanda=venta.detalles,
            notas_generales=body.notas_generales,
            sucursal_id=sucursal_id,
            nombre_cliente=body.nombre_cliente,
            mesa=body.mesa,
        )

        comanda = await comanda_repository.crear_comanda_con_detalles(
            conn,
            comanda_in,
            None,
            str(usuario_id),
        )
        await inventario_service.descontar_por_venta(
            conn,
            str(sucursal_id),
            venta.detalles,
            comanda.id,
            usuario_id,
        )
        await pago_repository.crear_pagos(
            conn,
            comanda_id=UUID(comanda.id),
            sucursal_id=sucursal_id,
            pagos=body.pagos,
            usuario_id=usuario_id,
        )
        if idempotency_key and hash_payload:
            try:
                await pago_repository.registrar_idempotencia(
                    conn,
                    clave=idempotency_key,
                    sucursal_id=sucursal_id,
                    usuario_id=usuario_id,
                    hash_payload=hash_payload,
                    comanda_id=UUID(comanda.id),
                )
            except asyncpg.UniqueViolationError:
                # No debería pasar con el candado de arriba; si pasa, nada se
                # cobra dos veces (la transacción se revierte) y el cliente
                # recibe un 409 claro en vez de un 500.
                raise IdempotenciaEnCursoError() from None
        for pago in body.pagos:
            await registrar_movimiento_caja(
                conn,
                apertura_caja_id=apertura_caja_id,
                tipo_movimiento="O",
                referencia_id=comanda.id,
                metodo_pago_id=str(pago.metodo_pago_id),
                monto=pago.monto,
                creado_por=str(usuario_id),
            )
        if cambio > 0:
            await registrar_cambio_caja(
                conn,
                apertura_caja_id=apertura_caja_id,
                referencia_id=comanda.id,
                monto=cambio,
                creado_por=str(usuario_id),
            )
        if body.puntos_a_redimir > 0:
            # celular_cliente es obligatorio en este caso (validado en el schema).
            descuento = await lealtad_service.redimir_puntos(
                conn,
                sucursal_id,
                body.celular_cliente,  # type: ignore[arg-type]
                body.puntos_a_redimir,
                UUID(comanda.id),
                usuario_id,
            )
            # La configuración pudo cambiar entre la validación y el canje.
            if descuento != descuento_esperado:
                raise Conflicto(
                    "El valor del punto de lealtad cambió mientras se cobraba. "
                    "Vuelve a cobrar el pedido."
                )
        if body.celular_cliente:
            await lealtad_service.otorgar_puntos(
                conn,
                sucursal_id,
                body.celular_cliente,
                total_final,
                usuario_id,
                comanda_id=UUID(comanda.id),
            )

    comanda.detalles = await expandir_detalles_comanda(conn, comanda.detalles)

    await manager.broadcast(
        str(sucursal_id),
        {"type": "comanda_creada", "comanda": asdict(comanda)},
    )

    return comanda


def _calcular_desde(filtro: str, ahora: datetime) -> datetime:
    """Inicio del periodo hoy/semana/mes a partir de `ahora`, la hora local
    de la sucursal sin zona (M4: antes era la hora del servidor, en UTC)."""
    if filtro == "hoy":
        return ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    if filtro == "semana":
        inicio_semana = ahora - timedelta(days=ahora.weekday())
        return inicio_semana.replace(hour=0, minute=0, second=0, microsecond=0)
    return ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _parsear_fecha(valor: str, campo: str) -> datetime:
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        raise DatosInvalidos(
            f"La fecha «{valor}» de {campo} no es válida; usa el formato AAAA-MM-DD."
        ) from None


async def _a_hora_local(conn: asyncpg.Connection, sucursal_id: UUID, momento: datetime) -> datetime:
    """Las fechas sin zona ya son hora local de la sucursal; las que traen zona
    se convierten a la hora local de la sucursal."""
    if momento.tzinfo is None:
        return momento
    local = await sucursales.a_hora_local(conn, sucursal_id, momento)
    if local is None:
        raise NoEncontrado("Sucursal")
    return local


async def _periodo(
    conn: asyncpg.Connection,
    sucursal_id: UUID,
    filtro: str,
    fecha_inicio: str | None,
    fecha_fin: str | None,
) -> tuple[datetime, datetime | None]:
    """Límites [desde, hasta) del periodo en hora local de la sucursal, sin
    zona; el repository los convierte con la `zona_horaria` de la sucursal.

    `fecha_fin` es un día completo: el periodo termina al empezar el día
    siguiente."""
    ahora = await sucursales.ahora_en_sucursal(conn, sucursal_id)
    if ahora is None:
        raise NoEncontrado("Sucursal")
    desde = _calcular_desde(filtro, ahora)
    hasta = None
    if fecha_inicio:
        desde = await _a_hora_local(conn, sucursal_id, _parsear_fecha(fecha_inicio, "fecha_inicio"))
    if fecha_fin:
        fin = await _a_hora_local(conn, sucursal_id, _parsear_fecha(fecha_fin, "fecha_fin"))
        hasta = datetime.combine(fin.date() + timedelta(days=1), datetime.min.time())
    return desde, hasta


async def obtener_historial(
    conn: asyncpg.Connection,
    sucursal_id: UUID,
    filtro: str = "hoy",
    estado: str = "todos",
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    caja_id: UUID | None = None,
    metodo_pago_id: UUID | None = None,
) -> list[HistorialOut]:
    desde, hasta = await _periodo(conn, sucursal_id, filtro, fecha_inicio, fecha_fin)
    rows = await pago_repository.historial(
        conn, sucursal_id, desde, estado, hasta, caja_id, metodo_pago_id
    )
    return [HistorialOut.model_validate(r) for r in rows]


async def obtener_detalle(
    conn: asyncpg.Connection,
    tipo_origen: str,
    referencia_id: UUID,
) -> DetalleOrdenOut | None:
    data = await pago_repository.detalle_por_referencia(conn, tipo_origen, referencia_id)
    if data is None:
        return None
    return DetalleOrdenOut.model_validate(data)


async def obtener_estadisticas(
    conn: asyncpg.Connection,
    sucursal_id: UUID,
    filtro: str = "hoy",
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
) -> EstadisticasOut:
    desde, hasta = await _periodo(conn, sucursal_id, filtro, fecha_inicio, fecha_fin)
    data = await pago_repository.estadisticas(conn, sucursal_id, desde, hasta)
    total_ventas = float(data["total_ventas"])
    total_ordenes = int(data["total_ordenes"])
    ticket_promedio = total_ventas / total_ordenes if total_ordenes > 0 else 0.0
    return EstadisticasOut(
        total_ventas=total_ventas,
        total_ordenes=total_ordenes,
        ticket_promedio=ticket_promedio,
    )
