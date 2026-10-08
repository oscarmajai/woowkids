"""El código del portal de padres es opaco, aleatorio, se guarda
hasheado, caduca y deja de valer al hacer checkout del último niño. El UUID
del registro ya no sirve como código. Los repositories se mockean (sin BD)."""

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.core.config import settings
from app.core.security import generate_codigo_acceso_padres, hash_codigo_acceso_padres
from app.services import chekouts, padres_service
from app.services.padres_service import TokenAccesoInvalidoError
from jose import jwt


def test_codigo_es_opaco_aleatorio_y_se_guarda_hasheado():
    codigo, codigo_hash = generate_codigo_acceso_padres()
    otro, _ = generate_codigo_acceso_padres()
    assert codigo != otro
    assert len(codigo) >= 32
    with pytest.raises(ValueError):
        UUID(codigo)
    assert codigo_hash == hashlib.sha256(codigo.encode()).hexdigest()
    assert codigo not in codigo_hash


@pytest.fixture
def repo(monkeypatch):
    """Simula codigos_acceso_padres en memoria: {hash: {...}}."""
    estado: dict = {"codigos": {}, "llamadas": []}

    async def crear_codigo(conn, registro_id, codigo_hash, expira, creado_por):
        estado["llamadas"].append("crear")
        estado["codigos"][codigo_hash] = {
            "registro_id": registro_id,
            "expira": expira,
            "revocado": False,
        }

    async def revocar_codigos_de_registro(conn, registro_id):
        estado["llamadas"].append("revocar")
        for c in estado["codigos"].values():
            if c["registro_id"] == registro_id:
                c["revocado"] = True

    async def get_registro_por_codigo(conn, codigo_hash):
        estado["llamadas"].append(("buscar", codigo_hash))
        c = estado["codigos"].get(codigo_hash)
        if c is None or c["revocado"] or c["expira"] <= datetime.now(UTC):
            return None
        return {
            "registroId": c["registro_id"],
            "tutorId": uuid4(),
            "sucursalId": uuid4(),
            "expira": c["expira"],
        }

    r = padres_service.codigos_acceso_padres
    monkeypatch.setattr(r, "crear_codigo", crear_codigo)
    monkeypatch.setattr(r, "revocar_codigos_de_registro", revocar_codigos_de_registro)
    monkeypatch.setattr(r, "get_registro_por_codigo", get_registro_por_codigo)
    return estado


@pytest.fixture
def dashboard_deps(monkeypatch):
    async def fake_tutor(conn, tutor_id):
        return {"id": tutor_id, "nombreCompleto": "Ana", "telefono": "5512345678"}

    async def fake_sucursal(conn, sucursal_id):
        return {"id": sucursal_id, "nombre": "Centro"}

    async def fake_hijos(conn, registro_id):
        return []

    async def fake_lealtad(conn, sucursal_id, telefono):
        return padres_service.LealtadPadreInfo(saldo=0)

    monkeypatch.setattr(padres_service, "get_tutor_by_id", fake_tutor)
    monkeypatch.setattr(padres_service, "get_sucursal_by_id", fake_sucursal)
    monkeypatch.setattr(padres_service, "_get_hijos_visita", fake_hijos)
    monkeypatch.setattr(padres_service, "_get_lealtad_tutor", fake_lealtad)


async def test_emitir_revoca_el_anterior_y_guarda_solo_el_hash(repo):
    registro_id = uuid4()
    primero = await padres_service.emitir_codigo_acceso(None, registro_id, uuid4())
    segundo = await padres_service.emitir_codigo_acceso(None, registro_id, uuid4())

    assert repo["llamadas"] == ["revocar", "crear", "revocar", "crear"]
    assert primero not in repo["codigos"] and segundo not in repo["codigos"]
    assert repo["codigos"][hash_codigo_acceso_padres(primero)]["revocado"] is True
    vigente = repo["codigos"][hash_codigo_acceso_padres(segundo)]
    assert vigente["revocado"] is False
    restante = vigente["expira"] - datetime.now(UTC)
    assert timedelta(hours=23, minutes=59) < restante <= timedelta(hours=24)


async def test_codigo_nuevo_entrega_sesion_de_padre(repo, dashboard_deps):
    registro_id = uuid4()
    codigo = await padres_service.emitir_codigo_acceso(None, registro_id, uuid4())

    resp = await padres_service.get_padre_dashboard(None, codigo)

    claims = jwt.decode(resp.token, settings.secret_key, algorithms=[settings.algorithm])
    assert claims["sub"] == str(registro_id)
    assert claims["role"] == "PadreVisor"
    assert resp.expires_in <= 2 * 3600


async def test_sesion_no_dura_mas_que_el_codigo(repo, dashboard_deps):
    registro_id = uuid4()
    codigo = await padres_service.emitir_codigo_acceso(None, registro_id, uuid4())
    repo["codigos"][hash_codigo_acceso_padres(codigo)]["expira"] = datetime.now(UTC) + timedelta(
        minutes=10
    )

    resp = await padres_service.get_padre_dashboard(None, codigo)
    assert resp.expires_in <= 600


async def test_uuid_del_registro_ya_no_es_un_codigo_valido(repo, dashboard_deps):
    registro_id = uuid4()
    await padres_service.emitir_codigo_acceso(None, registro_id, uuid4())

    with pytest.raises(TokenAccesoInvalidoError):
        await padres_service.get_padre_dashboard(None, str(registro_id))


async def test_codigo_revocado_o_expirado_se_rechaza(repo, dashboard_deps):
    registro_id = uuid4()
    codigo = await padres_service.emitir_codigo_acceso(None, registro_id, uuid4())
    await padres_service.revocar_codigos_acceso(None, registro_id)
    with pytest.raises(TokenAccesoInvalidoError):
        await padres_service.get_padre_dashboard(None, codigo)

    codigo2 = await padres_service.emitir_codigo_acceso(None, registro_id, uuid4())
    repo["codigos"][hash_codigo_acceso_padres(codigo2)]["expira"] = datetime.now(UTC) - timedelta(
        seconds=1
    )
    with pytest.raises(TokenAccesoInvalidoError):
        await padres_service.get_padre_dashboard(None, codigo2)


@pytest.mark.parametrize("codigo", ["", "x" * 129])
async def test_codigo_mal_formado_se_rechaza_sin_consultar(repo, codigo):
    with pytest.raises(TokenAccesoInvalidoError):
        await padres_service.get_padre_dashboard(None, codigo)
    assert repo["llamadas"] == []


class _FakeConn:
    @asynccontextmanager
    async def transaction(self):
        yield


@pytest.fixture
def checkout_deps(monkeypatch):
    registro_id = uuid4()
    estado = {"abiertos": 0, "revocados": []}

    async def fake_detalle(conn, detalle_id):
        return {
            "salida": None,
            "sucursal_id": uuid4(),
            "registros_id": registro_id,
            "salida_esperada": datetime.now(UTC) + timedelta(hours=1),
            "precio": Decimal("100"),
        }

    async def noop(*args, **kwargs):
        return None

    async def fake_count(conn, rid):
        return estado["abiertos"]

    async def fake_revocar(conn, rid):
        estado["revocados"].append(rid)

    async def fake_broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr(chekouts, "get_detalle_registro_by_id", fake_detalle)
    monkeypatch.setattr(chekouts, "put_hora_salida_by_id", noop)
    monkeypatch.setattr(chekouts, "count_detalles_registro_abiertos", fake_count)
    monkeypatch.setattr(chekouts, "change_registro_estado", noop)
    monkeypatch.setattr(chekouts, "revocar_codigos_acceso", fake_revocar)
    monkeypatch.setattr(chekouts.manager, "broadcast", fake_broadcast)
    estado["registro_id"] = registro_id
    return estado


async def test_checkout_del_ultimo_nino_revoca_el_codigo(checkout_deps):
    await chekouts.create_chekout(_FakeConn(), uuid4(), uuid4(), [], "apertura")
    assert checkout_deps["revocados"] == [checkout_deps["registro_id"]]


async def test_checkout_con_hermanos_pendientes_no_revoca(checkout_deps):
    checkout_deps["abiertos"] = 1
    await chekouts.create_chekout(_FakeConn(), uuid4(), uuid4(), [], "apertura")
    assert checkout_deps["revocados"] == []
