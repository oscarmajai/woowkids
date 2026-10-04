"""B9 + M7: el conteo del cierre es a ciegas.

Las respuestas del turno traen el efectivo esperado y las ventas por método
(M7), pero solo a quien puede revisar el arqueo (turnos_caja:revision_admin).
Al cajero que cuenta se le omiten.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.routers import turnos_caja as router
from app.schemas.auth import TokenData
from app.schemas.caja import TurnoActivoResponse, VentaPorMetodo


def _activo() -> TurnoActivoResponse:
    return TurnoActivoResponse.model_construct(
        turno_id="t1",
        estado="ABIERTA",
        fondo_inicial=Decimal("2000"),
        fecha_apertura=datetime(2026, 10, 3, 9, 0),
        efectivo_esperado=Decimal("1500"),
        ventas_por_metodo=[
            VentaPorMetodo.model_construct(
                metodo="efectivo", label="Efectivo", total=Decimal("880")
            )
        ],
    )


def _usuario(rol: str) -> TokenData:
    return TokenData.model_construct(sub="u1", role=rol, branch_id=None, permissions=[])


@pytest.mark.parametrize(
    ("revisa", "ve_esperado"),
    [(False, False), (True, True)],
)
async def test_esperado_solo_para_quien_revisa_el_arqueo(
    monkeypatch: pytest.MonkeyPatch, revisa: bool, ve_esperado: bool
) -> None:
    monkeypatch.setattr(
        router.turnos_caja_service, "obtener_turno_activo", AsyncMock(return_value=_activo())
    )
    monkeypatch.setattr(
        router,
        "has_permission",
        lambda _rol, codigo: revisa and codigo == "turnos_caja:revision_admin",
    )

    resp = await router.obtener_activo(
        sucursal_id=None, opcional=False, current_user=_usuario("Cajero"), conn=MagicMock()
    )

    assert resp is not None
    if ve_esperado:
        assert resp.efectivo_esperado == Decimal("1500")
        assert resp.ventas_por_metodo
    else:
        assert resp.efectivo_esperado is None
        assert resp.ventas_por_metodo is None


# R1 (prueba E2E de v1.2.0): /abrir, /iniciar-conteo, /conteo y /cancelar
# devolvían el esperado al cajero aunque GET /activo ya lo ocultara.
_LLAMADAS = {
    "abrir_turno": lambda u: router.abrir_turno(
        payload=MagicMock(), current_user=u, conn=MagicMock()
    ),
    "iniciar_conteo": lambda u: router.iniciar_conteo(
        body={"turno_id": "t1"}, current_user=u, conn=MagicMock()
    ),
    "enviar_conteo": lambda u: router.enviar_conteo(
        payload=MagicMock(), current_user=u, conn=MagicMock()
    ),
    "cancelar_conteo": lambda u: router.cancelar_conteo(
        body={"turno_id": "t1"}, current_user=u, conn=MagicMock()
    ),
}


@pytest.mark.parametrize("servicio", list(_LLAMADAS))
@pytest.mark.parametrize("revisa", [False, True])
async def test_ninguna_respuesta_del_turno_revela_el_esperado_al_cajero(
    monkeypatch: pytest.MonkeyPatch, servicio: str, revisa: bool
) -> None:
    monkeypatch.setattr(router.turnos_caja_service, servicio, AsyncMock(return_value=_activo()))
    monkeypatch.setattr(
        router,
        "has_permission",
        lambda _rol, codigo: revisa and codigo == "turnos_caja:revision_admin",
    )

    resp = await _LLAMADAS[servicio](_usuario("Cajero"))

    if revisa:
        assert resp.efectivo_esperado == Decimal("1500")
    else:
        assert resp.efectivo_esperado is None
        assert resp.ventas_por_metodo is None
