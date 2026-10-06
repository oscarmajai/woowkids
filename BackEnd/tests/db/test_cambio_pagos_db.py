"""El cambio que se devuelve al cliente tiene que estar respaldado por
efectivo real en los tres puntos de cobro (POS, reservaciones y estancias), y
el cobro de varios pagos de una reservación es atómico. Contra PostgreSQL
real.

Migrados de tests/integration (que dependían de IDs fijos de la BD compartida
de desarrollo). El caso feliz del POS con cambio ya lo cubre
test_precios_servidor_pos_pg.py y la función pura validar_cambio,
tests/unit/test_validaciones_pago.py; aquí se prueba que cada servicio la
aplica de verdad y que no persiste nada al rechazar.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg
import pytest
from app.exceptions import DatosInvalidos
from app.repositories import caja_repository
from app.schemas.pagos import PagoCompletoRequest, PagoEstanciaExtraRequest, PagoIn, PaymentItem
from app.schemas.pagos_reservacion import PagoReservacionItem, PagosReservacionCompletarRequest
from app.schemas.registros import OnboardingRequest
from app.schemas.tutores import TutorIn
from app.services import estancias, pago_service, pagos_estancia, pagos_reservacion

from tests.db.conftest import Escenario, crear_apertura

FONDO = Decimal("1000.00")
REFERENCIA_TARJETA = "AUT-123456"


async def _metodos(conn: asyncpg.Connection) -> tuple[UUID, UUID]:
    efectivo = await conn.fetchval("SELECT id FROM public.metodos_pago WHERE tipo = 'E'")
    tarjeta = await conn.fetchval("SELECT id FROM public.metodos_pago WHERE tipo = 'T'")
    return efectivo, tarjeta


# ── POS: pago_service.completar_pago ─────────────────────────────────────────


async def _producto(conn: asyncpg.Connection, sucursal_id: UUID, precio: str) -> UUID:
    pid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO public.productos (id, nombre, precio_unitario, tipo, sucursal_id, activo) "
        "VALUES ($1, $2, $3, 'A', $4, TRUE)",
        pid,
        f"Producto cambio {pid.hex[:6]}",
        Decimal(precio),
        sucursal_id,
    )
    return pid


def _cobro(producto_id: UUID, total: str, pagos: list[PaymentItem], cambio: str) -> Any:
    return PagoCompletoRequest(
        total_final=Decimal(total),
        detalles_comanda=[
            {
                "producto_id": str(producto_id),
                "nombre": "Producto",
                "cantidad": 1,
                "precio_unitario": total,
                "subtotal": total,
            }
        ],
        pagos=pagos,
        cambio=Decimal(cambio),
    )


def _pago(metodo: UUID, monto: str, tarjeta: UUID) -> PaymentItem:
    notas = REFERENCIA_TARJETA if metodo == tarjeta else ""
    return PaymentItem(metodo_pago_id=metodo, monto=Decimal(monto), notas_pago=notas)


async def _movimientos(conn: asyncpg.Connection, apertura_id: str) -> int:
    return await conn.fetchval(
        "SELECT COUNT(*) FROM public.movimientos_caja WHERE apertura_caja_id = $1",
        uuid.UUID(apertura_id),
    )


@pytest.mark.parametrize(
    ("total", "pagos", "cambio"),
    [
        # Pago 100 % con tarjeta y cambio declarado: salida de efectivo fantasma.
        ("120.00", [("T", "200.00")], "80.00"),
        # Mixto: el cambio (150) supera el efectivo aportado (100).
        ("20.00", [("T", "100.00"), ("E", "100.00")], "150.00"),
        # Todo en efectivo, pero el cambio (50) excede el excedente (100 - 90).
        ("90.00", [("E", "100.00")], "50.00"),
    ],
    ids=["tarjeta_con_cambio", "cambio_mayor_al_efectivo", "cambio_mayor_al_excedente"],
)
async def test_pos_rechaza_cambio_no_respaldado_y_no_cobra(
    pool: asyncpg.Pool,
    escenario: Escenario,
    total: str,
    pagos: list[tuple[str, str]],
    cambio: str,
) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        efectivo, tarjeta = await _metodos(conn)
        producto = await _producto(conn, escenario.sucursal_id, total)
        por_tipo = {"E": efectivo, "T": tarjeta}
        body = _cobro(producto, total, [_pago(por_tipo[t], m, tarjeta) for t, m in pagos], cambio)
        with pytest.raises(DatosInvalidos):
            await pago_service.completar_pago(
                conn, body, escenario.usuario_id, escenario.sucursal_id, apertura
            )
        assert await _movimientos(conn, apertura) == 0
        assert (
            await conn.fetchval(
                "SELECT COUNT(*) FROM public.comandas WHERE sucursal_id = $1",
                escenario.sucursal_id,
            )
            == 0
        )


async def test_pos_mixto_con_cambio_cubierto_por_el_efectivo_se_cobra(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    # 100 tarjeta + 100 efectivo por un total de 120: el cambio de 80 cabe
    # en los 100 de efectivo (límite que debe aceptarse).
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        efectivo, tarjeta = await _metodos(conn)
        producto = await _producto(conn, escenario.sucursal_id, "120.00")
        body = _cobro(
            producto,
            "120.00",
            [_pago(tarjeta, "100.00", tarjeta), _pago(efectivo, "100.00", tarjeta)],
            "80.00",
        )
        await pago_service.completar_pago(
            conn, body, escenario.usuario_id, escenario.sucursal_id, apertura
        )
        assert await caja_repository.sumar_cambio_apertura(conn, apertura) == Decimal("80.00")


# ── Reservaciones: pagos_reservacion.completar ───────────────────────────────


async def _reservacion(conn: asyncpg.Connection, sucursal_id: UUID) -> UUID:
    sufijo = uuid.uuid4().hex[:8]
    tipo_evento = await conn.fetchval(
        "INSERT INTO public.tipos_evento (nombre, sucursal_id) VALUES ($1, $2) RETURNING id",
        f"Cumpleaños {sufijo}",
        sucursal_id,
    )
    paquete = await conn.fetchval(
        """INSERT INTO public.paquetes (sucursal_id, nombre, min_invitados, max_invitados,
               precio_base, precio_hora_pulsera, anticipo_porcentaje)
           VALUES ($1, $2, 1, 30, 500, 0, 40) RETURNING id""",
        sucursal_id,
        f"Paquete {sufijo}",
    )
    return await conn.fetchval(
        """
        INSERT INTO public.reservaciones
            (sucursal_id, tipo_evento_id, paquete_id, nombre_cliente, telefono_cliente,
             fecha_evento, hora_inicio, hora_fin, numero_personas, precio_base,
             precio_total, estado)
        VALUES ($1, $2, $3, 'Cliente de prueba', '5555555555',
                $4, '10:00', '14:00', 5, 500.00, 500.00, 'confirmada')
        RETURNING id
        """,
        sucursal_id,
        tipo_evento,
        paquete,
        date.today(),
    )


async def _pagos_de(conn: asyncpg.Connection, reservacion_id: UUID) -> int:
    return await conn.fetchval(
        "SELECT COUNT(*) FROM public.pagos_reservacion WHERE reservacion_id = $1", reservacion_id
    )


async def test_reservacion_completar_registra_varios_pagos_y_el_cambio(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        efectivo, tarjeta = await _metodos(conn)
        reservacion = await _reservacion(conn, escenario.sucursal_id)
        body = PagosReservacionCompletarRequest(
            reservacion_id=reservacion,
            pagos=[
                PagoReservacionItem(metodo_pago_id=tarjeta, monto=Decimal("50.00")),
                PagoReservacionItem(metodo_pago_id=efectivo, monto=Decimal("150.00")),
            ],
            cambio=Decimal("80.00"),
        )
        resultado = await pagos_reservacion.completar(conn, body, escenario.usuario_id, apertura)

        assert len(resultado.pagos) == 2
        assert resultado.cambio == Decimal("80.00")
        assert await _pagos_de(conn, reservacion) == 2
        assert await caja_repository.sumar_cambio_apertura(conn, apertura) == Decimal("80.00")


async def test_reservacion_completar_rechaza_cambio_sin_efectivo_y_no_persiste(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        _, tarjeta = await _metodos(conn)
        reservacion = await _reservacion(conn, escenario.sucursal_id)
        body = PagosReservacionCompletarRequest(
            reservacion_id=reservacion,
            pagos=[PagoReservacionItem(metodo_pago_id=tarjeta, monto=Decimal("200.00"))],
            cambio=Decimal("80.00"),
        )
        with pytest.raises(DatosInvalidos):
            await pagos_reservacion.completar(conn, body, escenario.usuario_id, apertura)
        assert await _pagos_de(conn, reservacion) == 0
        assert await _movimientos(conn, apertura) == 0


async def test_reservacion_completar_que_falla_a_mitad_no_deja_pagos_parciales(
    pool: asyncpg.Pool, escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.repositories import pagos_reservacion_repository

    llamadas = {"n": 0}
    original = pagos_reservacion_repository.crear

    async def crear_que_falla_en_el_segundo(*args: Any, **kwargs: Any) -> Any:
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            raise RuntimeError("fallo simulado en el segundo pago")
        return await original(*args, **kwargs)

    monkeypatch.setattr(pagos_reservacion_repository, "crear", crear_que_falla_en_el_segundo)

    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        efectivo, _ = await _metodos(conn)
        reservacion = await _reservacion(conn, escenario.sucursal_id)
        body = PagosReservacionCompletarRequest(
            reservacion_id=reservacion,
            pagos=[
                PagoReservacionItem(metodo_pago_id=efectivo, monto=Decimal("100.00")),
                PagoReservacionItem(metodo_pago_id=efectivo, monto=Decimal("100.00")),
            ],
            cambio=Decimal("0"),
        )
        with pytest.raises(RuntimeError):
            await pagos_reservacion.completar(conn, body, escenario.usuario_id, apertura)
        # El rollback deshizo también el primer pago y su movimiento de caja.
        assert await _pagos_de(conn, reservacion) == 0
        assert await _movimientos(conn, apertura) == 0
        monto_pagado = await conn.fetchval(
            "SELECT monto_pagado FROM public.reservaciones WHERE id = $1", reservacion
        )
        assert monto_pagado == Decimal("0")


# ── Estancias: check-in y pago extra ─────────────────────────────────────────


@pytest.mark.parametrize("pagos", [[], None], ids=["pagos_vacios", "pagos_omitidos"])
async def test_checkin_rechaza_cambio_sin_ningun_pago(
    pool: asyncpg.Pool, escenario: Escenario, pagos: list[PagoIn] | None
) -> None:
    """Antes, `if data.pagos:` saltaba validar_cambio con pagos vacíos u
    omitidos y el cambio se registraba sin efectivo que lo respaldara. La
    validación corre antes de tocar tutor, niños, fotos o pulseras."""
    async with pool.acquire() as conn:
        version_aviso = await conn.fetchval("SELECT max(version) FROM avisos_privacidad")
    data = OnboardingRequest(
        sucursalId=escenario.sucursal_id,
        tutor=TutorIn(nombreCompleto="Tutor Rechazo", telefono="5550000000"),
        parentesco="Padre",
        detalles=[],
        pagos=pagos,
        cambio=Decimal("100.00"),
        aceptaAvisoPrivacidad=True,
        versionAvisoPrivacidad=version_aviso,
    )
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        with pytest.raises(DatosInvalidos):
            await estancias.create_estancia(
                conn,
                data,
                foto_ine=None,  # type: ignore[arg-type]
                foto_llegadas=[],
                usuario_id=escenario.usuario_id,
                apertura_caja_id=apertura,
            )
        assert await _movimientos(conn, apertura) == 0


async def test_pago_extra_de_estancia_rechaza_tarjeta_con_cambio(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        _, tarjeta = await _metodos(conn)
        body = PagoEstanciaExtraRequest(
            pagos=[PagoIn(metodoPagoId=tarjeta, monto=200.0)], cambio=Decimal("80.00")
        )
        with pytest.raises(DatosInvalidos):
            await pagos_estancia.pago_create_service(
                conn,
                body,
                sucursal_id=escenario.sucursal_id,
                registro_id=uuid.uuid4(),
                usuario_id=escenario.usuario_id,
                apertura_caja_id=apertura,
            )
        assert await _movimientos(conn, apertura) == 0
