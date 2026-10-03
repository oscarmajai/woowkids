"""C4: las operaciones que leen, validan y escriben el efectivo o el estado de un
turno bloquean la fila de apertura_caja DENTRO de una transacción y ANTES de
validar. Sin BD: un conn falso registra el orden BEGIN / bloqueo / escrituras /
COMMIT. La prueba de concurrencia real está en tests/db/test_carrera_turnos_caja.py."""

import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.repositories import caja_repository
from app.schemas.caja import (
    ConfirmarCierrePayload,
    ConteoPayload,
    DesgloseEfectivoPayload,
    IngresoEfectivoCreate,
    RetiroParcialCreate,
    RevisionAdminPayload,
    TipoDestinatario,
)
from app.services import turnos_caja_service
from app.services.turnos_caja_service import EfectivoInsuficienteError

SVC = "app.services.turnos_caja_service"
USER_ID = str(uuid4())
APERTURA_ID = str(uuid4())


class _Tx:
    def __init__(self, eventos: list[str]) -> None:
        self.eventos = eventos

    async def __aenter__(self) -> None:
        self.eventos.append("BEGIN")

    async def __aexit__(self, exc_type: Any, *_: Any) -> bool:
        self.eventos.append("ROLLBACK" if exc_type else "COMMIT")
        return False


class FakeConn:
    def __init__(self) -> None:
        self.eventos: list[str] = []
        self.sql: list[str] = []

    def transaction(self) -> _Tx:
        return _Tx(self.eventos)

    async def fetchrow(self, sql: str, *_args: Any) -> None:
        self.sql.append(sql)
        return None


def _apertura(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": APERTURA_ID,
        "cajero_id": USER_ID,
        "estado": "ABIERTA",
        "fondo_inicial": Decimal("1000"),
        "monto_declarado": None,
        "token_admin_jti": None,
        "conteo_json": None,
        "sucursal_id": None,
    }
    base.update(overrides)
    return base


def _registra(conn: FakeConn, nombre: str, retorno: Any = None) -> AsyncMock:
    async def _fn(*_a: Any, **_k: Any) -> Any:
        conn.eventos.append(nombre)
        return retorno

    return AsyncMock(side_effect=_fn)


def _sin_lectura_sin_bloqueo() -> Any:
    """get_apertura_por_id (lectura sin bloqueo) ya no debe usarse en estas rutas."""
    return patch(
        f"{SVC}.get_apertura_por_id",
        AsyncMock(side_effect=AssertionError("se leyó la apertura sin bloqueo")),
    )


def _retiro(monto: str) -> RetiroParcialCreate:
    return RetiroParcialCreate(
        apertura_caja_id=APERTURA_ID,
        tipo_destinatario=TipoDestinatario.EMPLEADO,
        monto=Decimal(monto),
    )


async def test_crear_retiro_bloquea_la_apertura_antes_de_calcular_el_disponible() -> None:
    conn = FakeConn()
    fila = {
        "id": 1,
        "apertura_caja_id": APERTURA_ID,
        "concepto": "Gastos varios",
        "tipo_destinatario": "Empleado",
        "monto": Decimal("600"),
        "observaciones": None,
        "creado": "2026-10-03T10:00:00",
    }
    with (
        _sin_lectura_sin_bloqueo(),
        patch(f"{SVC}.bloquear_apertura", _registra(conn, "bloquear", _apertura())),
        patch(
            f"{SVC}.calcular_efectivo_disponible",
            _registra(conn, "calcular", Decimal("1000")),
        ),
        patch(f"{SVC}.crear_retiro_parcial", _registra(conn, "insertar_retiro", fila)),
        patch(f"{SVC}.registrar_movimiento_caja", _registra(conn, "insertar_movimiento")),
    ):
        await turnos_caja_service.crear_retiro(conn, USER_ID, _retiro("600"))  # type: ignore[arg-type]

    assert conn.eventos == [
        "BEGIN",
        "bloquear",
        "calcular",
        "insertar_retiro",
        "insertar_movimiento",
        "COMMIT",
    ]


async def test_crear_retiro_que_excede_el_disponible_no_inserta_y_revierte() -> None:
    conn = FakeConn()
    with (
        _sin_lectura_sin_bloqueo(),
        patch(f"{SVC}.bloquear_apertura", _registra(conn, "bloquear", _apertura())),
        patch(
            f"{SVC}.calcular_efectivo_disponible",
            _registra(conn, "calcular", Decimal("400")),
        ),
        patch(f"{SVC}.crear_retiro_parcial", _registra(conn, "insertar_retiro")),
    ):
        with pytest.raises(EfectivoInsuficienteError):
            await turnos_caja_service.crear_retiro(conn, USER_ID, _retiro("600"))  # type: ignore[arg-type]

    assert conn.eventos == ["BEGIN", "bloquear", "calcular", "ROLLBACK"]


def _conteo() -> ConteoPayload:
    return ConteoPayload(
        turno_id=APERTURA_ID,
        desglose_efectivo=DesgloseEfectivoPayload(total=Decimal("100")),
        metodos_pago=[],
        total_declarado=Decimal("100"),
    )


_CASOS = {
    "iniciar_conteo": (
        lambda c: turnos_caja_service.iniciar_conteo(c, USER_ID, APERTURA_ID),
        _apertura(),
        ["actualizar_estado_apertura"],
    ),
    "enviar_conteo": (
        lambda c: turnos_caja_service.enviar_conteo(c, USER_ID, _conteo()),
        _apertura(estado="EN_CORTE"),
        ["actualizar_conteo_apertura", "actualizar_estado_apertura"],
    ),
    "cancelar_conteo": (
        lambda c: turnos_caja_service.cancelar_conteo(c, USER_ID, APERTURA_ID),
        _apertura(estado="EN_CORTE", monto_declarado=Decimal("100")),
        ["resetear_conteo_apertura", "actualizar_estado_apertura"],
    ),
    "crear_ingreso": (
        lambda c: turnos_caja_service.crear_ingreso(
            c, USER_ID, IngresoEfectivoCreate(apertura_caja_id=APERTURA_ID, monto=Decimal("50"))
        ),
        _apertura(),
        ["registrar_ingreso_efectivo"],
    ),
    "autenticar_admin_revision": (
        lambda c: turnos_caja_service.autenticar_admin_revision(
            c,
            USER_ID,
            RevisionAdminPayload(
                turno_id=APERTURA_ID, admin_email="admin@test.local", admin_password="x"
            ),
        ),
        _apertura(estado="EN_CORTE", monto_declarado=Decimal("100")),
        ["actualizar_admin_autorizacion"],
    ),
    "confirmar_cierre": (
        lambda c: turnos_caja_service.confirmar_cierre(
            c, USER_ID, ConfirmarCierrePayload(turno_id=APERTURA_ID)
        ),
        _apertura(
            estado="EN_CORTE",
            monto_declarado=Decimal("100"),
            token_admin_jti=str(uuid4()),
            conteo_json=json.dumps({"desglose_efectivo": {"total": "100"}}),
        ),
        ["crear_cierre_caja", "actualizar_estado_apertura"],
    ),
}


@pytest.mark.parametrize("caso", list(_CASOS))
async def test_transiciones_del_turno_validan_y_escriben_bajo_el_bloqueo(
    caso: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    llamar, apertura, escrituras = _CASOS[caso]
    conn = FakeConn()
    monkeypatch.setattr(turnos_caja_service.settings, "exigir_pin_token", False)
    for nombre in (
        "actualizar_estado_apertura",
        "actualizar_conteo_apertura",
        "resetear_conteo_apertura",
        "actualizar_admin_autorizacion",
    ):
        monkeypatch.setattr(f"{SVC}.{nombre}", _registra(conn, nombre))
    monkeypatch.setattr(
        f"{SVC}.registrar_ingreso_efectivo",
        _registra(
            conn,
            "registrar_ingreso_efectivo",
            {"id": 1, "apertura_caja_id": APERTURA_ID, "monto": 50, "creado": "2026-10-03"},
        ),
    )
    monkeypatch.setattr(
        f"{SVC}.crear_cierre_caja", _registra(conn, "crear_cierre_caja", {"id": uuid4()})
    )
    monkeypatch.setattr(
        f"{SVC}._calcular_balance",
        AsyncMock(return_value=(Decimal("0"), Decimal("0"), Decimal("0"), [])),
    )
    monkeypatch.setattr(
        f"{SVC}._verificar_credenciales_usuario",
        AsyncMock(return_value={"id": uuid4(), "sucursal_id": None, "nombre_completo": "A"}),
    )
    monkeypatch.setattr(f"{SVC}.obtener_turno_activo", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(
        f"{SVC}.get_apertura_por_id",
        AsyncMock(side_effect=AssertionError("se leyó la apertura sin bloqueo")),
    )
    monkeypatch.setattr(f"{SVC}.bloquear_apertura", _registra(conn, "bloquear", apertura))

    await llamar(conn)

    assert conn.eventos == ["BEGIN", "bloquear", *escrituras, "COMMIT"]


async def test_bloquear_apertura_usa_for_no_key_update_sobre_apertura_caja() -> None:
    """FOR NO KEY UPDATE OF a: serializa retiros/cierres entre sí pero no choca con
    el FOR KEY SHARE de la llave foránea que toma cada cobro al insertar en
    movimientos_caja (el POS no espera)."""
    conn = FakeConn()
    await caja_repository.bloquear_apertura(conn, APERTURA_ID)  # type: ignore[arg-type]
    assert conn.sql and conn.sql[0].rstrip().endswith("FOR NO KEY UPDATE OF a")


async def test_bloquear_apertura_con_id_invalido_no_consulta() -> None:
    conn = FakeConn()
    assert await caja_repository.bloquear_apertura(conn, "no-es-uuid") is None  # type: ignore[arg-type]
    assert conn.sql == []
