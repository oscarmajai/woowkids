from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.repositories import metodos_pago_repository
from app.repositories.caja_repository import registrar_cambio_caja, registrar_movimiento_caja
from app.repositories.pagos_comanda import pago_create
from app.repositories.registros import obtener_saldo_para_cobro
from app.schemas.pagos import PagoEstanciaExtraRequest
from app.services import turnos_caja_service
from app.services.validaciones_pago import validar_cambio


async def pago_create_service(
    conn: asyncpg.Connection,
    body: PagoEstanciaExtraRequest,
    sucursal_id: UUID,
    registro_id: UUID,
    usuario_id: UUID,
    apertura_caja_id: str,
) -> None:
    ids_efectivo = await metodos_pago_repository.obtener_ids_por_tipo(conn, "E")
    cambio = body.cambio.quantize(Decimal("0.01"))
    validar_cambio(
        [(p.metodoPagoId, Decimal(str(p.monto))) for p in body.pagos],
        cambio,
        ids_efectivo,
    )

    async with conn.transaction():
        # N1: el turno debe seguir ABIERTA bajo bloqueo hasta que el cobro confirme.
        await turnos_caja_service.bloquear_turno_para_cobro(conn, apertura_caja_id)
        registro = await obtener_saldo_para_cobro(conn, registro_id)
        if not registro or registro["sucursal_id"] != sucursal_id:
            raise HTTPException(404, "Registro no encontrado")

        # C2: lo que se puede cobrar lo dice el servidor (total del registro
        # menos lo ya cobrado), no el cliente. Un abono parcial se acepta;
        # cobrar de más, no.
        saldo = Decimal(registro["total"]) - Decimal(registro["pagado_neto"])
        neto = sum((Decimal(str(p.monto)) for p in body.pagos), Decimal(0)) - cambio
        if neto > saldo:
            raise HTTPException(
                409,
                detail={
                    "code": "MONTO_NO_COINCIDE",
                    "message": (
                        f"El saldo pendiente del registro es ${max(saldo, Decimal(0)):,.2f}; "
                        f"no se pueden cobrar ${neto:,.2f}."
                    ),
                    "saldo": float(max(saldo, Decimal(0))),
                },
            )

        for pago in body.pagos:
            await pago_create(
                conn,
                sucursal_id,
                registro_id,
                pago.metodoPagoId,
                pago.monto,
                usuario_id,
            )
            await registrar_movimiento_caja(
                conn,
                apertura_caja_id=apertura_caja_id,
                tipo_movimiento="E",
                referencia_id=str(registro_id),
                metodo_pago_id=str(pago.metodoPagoId),
                monto=Decimal(str(pago.monto)),
                creado_por=str(usuario_id),
            )
        if cambio > 0:
            await registrar_cambio_caja(
                conn,
                apertura_caja_id=apertura_caja_id,
                referencia_id=str(registro_id),
                monto=cambio,
                creado_por=str(usuario_id),
            )
