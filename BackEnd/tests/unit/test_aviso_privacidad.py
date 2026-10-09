"""Aviso de privacidad (LFPDPPP): consulta pública, publicación de versiones
(solo AdministradorSistema) y aceptación obligatoria en el check-in.

Sin BD: los repositorios se simulan (la prueba con PostgreSQL real está en
tests/db/test_aviso_privacidad_db.py).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.schemas.auth import TokenData
from app.schemas.ninos import NinoIn
from app.schemas.pagos import PagoIn
from app.schemas.registros import DetalleIn, OnboardingRequest
from app.schemas.tutores import TutorIn
from app.services import estancias, privacidad_service
from fastapi import HTTPException
from fastapi.testclient import TestClient

repo = privacidad_service.privacidad_repository


def _aviso(version: int = 3, **cambios: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": version,
        "texto_integral": (
            "{{razon_social}} («{{nombre_comercial}}») en {{domicilio}}. "
            "ARCO: {{correo_datos_personales}}. Versión {{version}} del {{fecha_vigencia}}. "
            "INE {{dias_conservacion_imagenes}} días."
        ),
        "texto_simplificado": "Responsable: {{razon_social}}. Integral en {{url_aviso}}.",
        "razon_social": "Diversión Infantil SA de CV",
        "nombre_comercial": "Woow Kids",
        "domicilio": "Av. Siempre Viva 742, Guadalajara",
        "area_datos_personales": "Departamento de Datos Personales",
        "correo_datos_personales": "privacidad@woowkids.mx",
        "telefono_datos_personales": "3312345678",
        "url_aviso": "",
        "dias_conservacion_imagenes": 90,
        "anios_conservacion_registros": 5,
        "motivo_cambio": None,
        "vigente_desde": datetime(2026, 10, 3, 18, tzinfo=UTC),
        "fecha_vigencia": date(2026, 10, 3),
        "publicado_por": None,
    }
    base.update(cambios)
    return base


def _usuario(rol: str) -> TokenData:
    return TokenData(
        sub=str(uuid4()),
        email="persona@woowkids.test",
        role=rol,
        branch_id=None if rol == "AdministradorSistema" else uuid4(),
        permissions=[],
        jti=str(uuid4()),
        exp=datetime.now(tz=UTC) + timedelta(hours=1),
    )


def _conn() -> MagicMock:
    conn = MagicMock()

    @asynccontextmanager
    async def transaccion() -> Any:
        yield

    conn.transaction = transaccion
    return conn


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = _conn
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def con_aviso(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "obtener_vigente": AsyncMock(return_value=_aviso()),
        "historial": AsyncMock(return_value=[]),
        "bloquear_para_publicar": AsyncMock(),
        "insertar_version": AsyncMock(),
        "version_vigente": AsyncMock(return_value=3),
    }
    for nombre, mock in mocks.items():
        monkeypatch.setattr(repo, nombre, mock)
    return mocks


# ── Texto ──────────────────────────────────────────────────────────────────


def test_rellenar_reemplaza_marcadores_y_marca_los_pendientes() -> None:
    aviso = _aviso()
    texto = privacidad_service.rellenar(aviso["texto_integral"], aviso)
    assert "Diversión Infantil SA de CV («Woow Kids»)" in texto
    assert "Versión 3 del 3 de octubre de 2026" in texto
    assert "INE 90 días" in texto
    assert "{{" not in texto

    simplificado = privacidad_service.rellenar(aviso["texto_simplificado"], aviso)
    assert "[Pendiente de configurar: Dirección web del aviso integral]" in simplificado
    assert privacidad_service.pendientes(aviso) == ["Dirección web del aviso integral"]


def test_rellenar_deja_intacto_un_marcador_desconocido() -> None:
    assert privacidad_service.rellenar("{{otro}}", _aviso()) == "{{otro}}"


def test_la_plantilla_de_la_migracion_solo_usa_marcadores_conocidos() -> None:
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[2] / "sql" / "migrations" / "107_aviso_privacidad.sql"
    ).read_text()
    assert privacidad_service.marcadores_desconocidos(sql) == []
    for marcador in ("razon_social", "domicilio", "correo_datos_personales", "url_aviso"):
        assert "{{" + marcador + "}}" in sql


# ── GET /api/privacidad/aviso (público) ────────────────────────────────────


def test_aviso_publico_no_pide_sesion(cliente: TestClient, con_aviso: dict) -> None:
    resp = cliente.get("/api/privacidad/aviso")
    assert resp.status_code == 200, resp.text
    datos = resp.json()
    assert datos["version"] == 3
    assert datos["nombre_comercial"] == "Woow Kids"
    assert datos["fecha_vigencia"] == "2026-10-03"
    assert "Diversión Infantil SA de CV" in datos["texto_integral"]
    assert "{{" not in datos["texto_integral"] + datos["texto_simplificado"]
    # No expone la plantilla ni quién publicó.
    assert "publicado_por" not in datos and "responsable" not in datos


def test_aviso_publico_sin_ninguna_version_da_404(cliente: TestClient, con_aviso: dict) -> None:
    con_aviso["obtener_vigente"].return_value = None
    assert cliente.get("/api/privacidad/aviso").status_code == 404


# ── Administración (solo AdministradorSistema) ─────────────────────────────


@pytest.mark.parametrize("rol", ["Administrador", "Cajero", "Personal de atención de niños"])
def test_otros_roles_no_ven_ni_publican(cliente: TestClient, con_aviso: dict, rol: str) -> None:
    app.dependency_overrides[get_current_user] = lambda: _usuario(rol)
    assert cliente.get("/api/privacidad/admin/aviso").status_code == 403
    body = {"version_base": 3, "responsable": {"razon_social": "X"}}
    assert cliente.post("/api/privacidad/admin/aviso", json=body).status_code == 403
    con_aviso["insertar_version"].assert_not_awaited()


def test_sin_sesion_no_hay_administracion(cliente: TestClient, con_aviso: dict) -> None:
    assert cliente.get("/api/privacidad/admin/aviso").status_code in (401, 403)


def test_sistema_ve_la_plantilla_y_los_pendientes(cliente: TestClient, con_aviso: dict) -> None:
    app.dependency_overrides[get_current_user] = lambda: _usuario("AdministradorSistema")
    resp = cliente.get("/api/privacidad/admin/aviso")
    assert resp.status_code == 200, resp.text
    datos = resp.json()
    assert "{{razon_social}}" in datos["texto_integral"]
    assert datos["responsable"]["razon_social"] == "Diversión Infantil SA de CV"
    assert datos["pendientes"] == ["Dirección web del aviso integral"]
    assert "url_aviso" in datos["marcadores"]


def test_sistema_publica_una_version_nueva_conservando_los_textos(
    cliente: TestClient, con_aviso: dict
) -> None:
    usuario = _usuario("AdministradorSistema")
    app.dependency_overrides[get_current_user] = lambda: usuario
    body = {
        "version_base": 3,
        "responsable": {
            "razon_social": "  Otra Razón SA  ",
            "correo_datos_personales": "arco@woowkids.mx",
            "dias_conservacion_imagenes": 30,
        },
        "motivo_cambio": "Cambio de domicilio",
    }
    resp = cliente.post("/api/privacidad/admin/aviso", json=body)
    assert resp.status_code == 201, resp.text
    con_aviso["bloquear_para_publicar"].assert_awaited_once()
    args = con_aviso["insertar_version"].await_args.args
    version, integral, simplificado, responsable, motivo, usuario_id = args[1:]
    assert version == 4
    assert integral == _aviso()["texto_integral"]
    assert simplificado == _aviso()["texto_simplificado"]
    assert responsable["razon_social"] == "Otra Razón SA"
    assert responsable["dias_conservacion_imagenes"] == 30
    assert motivo == "Cambio de domicilio"
    assert usuario_id == UUID(usuario.sub)


def test_publicar_sobre_una_version_vieja_da_409(cliente: TestClient, con_aviso: dict) -> None:
    app.dependency_overrides[get_current_user] = lambda: _usuario("AdministradorSistema")
    body = {"version_base": 2, "responsable": {}}
    resp = cliente.post("/api/privacidad/admin/aviso", json=body)
    assert resp.status_code == 409
    assert "versión 3" in resp.json()["detail"]["message"]
    con_aviso["insertar_version"].assert_not_awaited()


def test_publicar_con_un_marcador_inexistente_da_422(cliente: TestClient, con_aviso: dict) -> None:
    app.dependency_overrides[get_current_user] = lambda: _usuario("AdministradorSistema")
    body = {"version_base": 3, "responsable": {}, "texto_simplificado": "Hola {{razon_socail}}"}
    resp = cliente.post("/api/privacidad/admin/aviso", json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "MARCADOR_DESCONOCIDO"
    con_aviso["insertar_version"].assert_not_awaited()


def test_publicar_con_correo_invalido_da_422(cliente: TestClient, con_aviso: dict) -> None:
    app.dependency_overrides[get_current_user] = lambda: _usuario("AdministradorSistema")
    body = {"version_base": 3, "responsable": {"correo_datos_personales": "no-es-correo"}}
    assert cliente.post("/api/privacidad/admin/aviso", json=body).status_code == 422


# ── Aceptación en el check-in ──────────────────────────────────────────────


@pytest.mark.parametrize(("aceptado", "version"), [(False, 3), (True, None), (False, None)])
async def test_exigir_aceptacion_sin_aceptar_da_422(
    con_aviso: dict, aceptado: bool, version: int | None
) -> None:
    with pytest.raises(HTTPException) as exc:
        await privacidad_service.exigir_aceptacion(MagicMock(), aceptado, version)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "AVISO_PRIVACIDAD_NO_ACEPTADO"
    assert "aceptar el aviso de privacidad" in exc.value.detail["message"]


async def test_exigir_aceptacion_de_una_version_vieja_da_422(con_aviso: dict) -> None:
    with pytest.raises(HTTPException) as exc:
        await privacidad_service.exigir_aceptacion(MagicMock(), True, 2)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "AVISO_PRIVACIDAD_DESACTUALIZADO"
    assert exc.value.detail["versionVigente"] == 3


async def test_exigir_aceptacion_de_la_vigente_la_devuelve(con_aviso: dict) -> None:
    assert await privacidad_service.exigir_aceptacion(MagicMock(), True, 3) == 3


SUCURSAL = uuid4()
EFECTIVO = uuid4()
TRAMOS = [{"min_horas": 1, "max_horas": 5, "precio": 60}]
METODO_EFECTIVO = {"nombre": "Efectivo", "requiere_referencia": False, "activo": True}


@pytest.fixture
def checkin(monkeypatch: pytest.MonkeyPatch, con_aviso: dict) -> dict[str, AsyncMock]:
    m = estancias
    mocks = {
        "validar_y_leer": AsyncMock(return_value=b"jpg"),
        "registro_create": AsyncMock(),
        "otorgar": AsyncMock(),
        "redimir": AsyncMock(return_value=Decimal("0")),
    }
    monkeypatch.setattr(
        m.metodos_pago_repository, "obtener_ids_por_tipo", AsyncMock(return_value={EFECTIVO})
    )
    monkeypatch.setattr(
        m.metodos_pago_repository,
        "obtener",
        AsyncMock(
            return_value={"nombre": "Efectivo", "requiere_referencia": False, "activo": True}
        ),
    )
    monkeypatch.setattr(m, "esta_disponible_para_asignar", AsyncMock(return_value=True))
    monkeypatch.setattr(m, "get_tutores_by_phone", AsyncMock(return_value=[]))
    monkeypatch.setattr(m, "tutor_create", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(m, "validar_y_leer", mocks["validar_y_leer"])
    monkeypatch.setattr(m, "upload_bytes", AsyncMock())
    monkeypatch.setattr(m, "registro_create", mocks["registro_create"])
    monkeypatch.setattr(m, "foto_create", AsyncMock())
    monkeypatch.setattr(m, "nino_create", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(
        m,
        "get_producto_estancia_by_branch_id",
        AsyncMock(return_value={"id": uuid4(), "config_estancia": TRAMOS, "precio_unitario": 0}),
    )
    monkeypatch.setattr(m, "insert_detalle_registro", AsyncMock())
    monkeypatch.setattr(m, "pago_create", AsyncMock())
    monkeypatch.setattr(m, "registrar_movimiento_caja", AsyncMock())
    monkeypatch.setattr(m, "registrar_cambio_caja", AsyncMock())
    monkeypatch.setattr(m.lealtad_service, "otorgar_puntos", mocks["otorgar"])
    monkeypatch.setattr(m.lealtad_service, "redimir_puntos", mocks["redimir"])
    monkeypatch.setattr(m, "registro_update_total", AsyncMock())
    monkeypatch.setattr(m, "change_registro_estado", AsyncMock())
    monkeypatch.setattr(m.manager, "broadcast", AsyncMock())
    monkeypatch.setattr(m, "emitir_codigo_acceso", AsyncMock(return_value="codigo"))
    return mocks


def _onboarding(**consentimiento: Any) -> OnboardingRequest:
    return OnboardingRequest(
        sucursalId=SUCURSAL,
        tutor=TutorIn(nombreCompleto="Ana Gómez", telefono="3312345678"),
        parentesco="Madre",
        detalles=[DetalleIn(nino=NinoIn(nombreCompleto="Leo", edad=5), pulseraId=uuid4())],
        pagos=[PagoIn(metodoPagoId=EFECTIVO, monto=60)],
        **consentimiento,
    )


async def _registrar(data: OnboardingRequest) -> dict[str, Any]:
    return await estancias.create_estancia(
        _conn(), data, MagicMock(), [MagicMock()], uuid4(), str(uuid4())
    )


async def test_checkin_sin_aceptar_el_aviso_da_422_y_no_guarda_nada(checkin: dict) -> None:
    with pytest.raises(HTTPException) as exc:
        await _registrar(_onboarding())
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "AVISO_PRIVACIDAD_NO_ACEPTADO"
    # Ni siquiera se leen la INE ni las fotos.
    checkin["validar_y_leer"].assert_not_awaited()
    checkin["registro_create"].assert_not_awaited()


async def test_checkin_aceptado_guarda_la_version_en_el_registro(checkin: dict) -> None:
    await _registrar(_onboarding(aceptaAvisoPrivacidad=True, versionAvisoPrivacidad=3))
    kwargs = checkin["registro_create"].await_args.kwargs
    assert kwargs["aviso_privacidad_version"] == 3
    assert kwargs["acepta_finalidades_secundarias"] is True
    checkin["otorgar"].assert_awaited_once()


async def test_checkin_que_rechaza_finalidades_secundarias_no_acumula_puntos(
    checkin: dict,
) -> None:
    await _registrar(
        _onboarding(
            aceptaAvisoPrivacidad=True,
            versionAvisoPrivacidad=3,
            aceptaFinalidadesSecundarias=False,
        )
    )
    assert checkin["registro_create"].await_args.kwargs["acepta_finalidades_secundarias"] is False
    checkin["otorgar"].assert_not_awaited()


async def test_checkin_que_rechaza_lealtad_no_puede_canjear_puntos(checkin: dict) -> None:
    data = _onboarding(
        aceptaAvisoPrivacidad=True,
        versionAvisoPrivacidad=3,
        aceptaFinalidadesSecundarias=False,
        puntosARedimir=10,
    )
    with pytest.raises(HTTPException) as exc:
        await _registrar(data)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "LEALTAD_RECHAZADA"
    checkin["redimir"].assert_not_awaited()


async def test_checkin_de_evento_tambien_exige_el_aviso(checkin: dict) -> None:
    data = _onboarding()
    data.reservacionId = uuid4()
    data.pagos = []
    with pytest.raises(HTTPException) as exc:
        await _registrar(data)
    assert exc.value.detail["code"] == "AVISO_PRIVACIDAD_NO_ACEPTADO"
    checkin["registro_create"].assert_not_awaited()


async def test_checkin_de_evento_aceptado_guarda_la_version(
    checkin: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import time

    evento = {
        "id": uuid4(),
        "nombre_cliente": "Luis",
        "apellidos_cliente": "Pérez",
        "telefono_cliente": "3398765432",
        "hora_inicio": time(16),
        "hora_fin": time(18),
        "numero_personas": 10,
        "fecha_evento": date(2026, 10, 3),
    }
    monkeypatch.setattr(estancias, "obtener_evento_mas_cercano", AsyncMock(return_value=evento))
    monkeypatch.setattr(
        estancias, "get_precio_pulsera_by_reserva_id", AsyncMock(return_value=Decimal("0"))
    )
    monkeypatch.setattr(
        estancias,
        "get_datos_operativos",
        AsyncMock(return_value={"zona_horaria": "America/Mexico_City"}),
    )
    insert_detalle = AsyncMock()
    monkeypatch.setattr(estancias, "insert_detalle_registro", insert_detalle)
    data = _onboarding(aceptaAvisoPrivacidad=True, versionAvisoPrivacidad=3)
    data.reservacionId = evento["id"]
    data.pagos = []
    await _registrar(data)
    assert checkin["registro_create"].await_args.kwargs["aviso_privacidad_version"] == 3
    # El evento de las 16:00 en México se guarda como 22:00 UTC, no como 16:00 UTC.
    entrada, salida_esperada = insert_detalle.await_args.args[6:8]
    assert entrada.astimezone(UTC).hour == 22
    assert salida_esperada.astimezone(UTC).hour == 0  # 18:00 en México
