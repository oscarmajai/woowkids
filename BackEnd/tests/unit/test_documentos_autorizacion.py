"""C6 — la INE y las fotos de llegada de un registro se autorizan por recurso:
staff de la sucursal del registro con permiso de estancias, o el padre dueño
del registro (sub del token). Cualquier otro caso responde 404, igual que un
registro inexistente. Los repositories se mockean (sin BD)."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.core.roles import ROL_PADRE, ROL_SISTEMA
from app.exceptions import NoEncontrado
from app.schemas.auth import TokenData
from app.services import documentos_service, permission_service

SUCURSAL_A = uuid4()
SUCURSAL_B = uuid4()


def _user(role: str, branch_id: UUID | None, sub: str | None = None) -> TokenData:
    return TokenData(
        sub=sub or str(uuid4()),
        email="x@y.z",
        role=role,
        branch_id=branch_id,
        jti=str(uuid4()),
        exp=datetime.now(UTC),
    )


@pytest.fixture(autouse=True)
def permisos(monkeypatch):
    monkeypatch.setattr(
        permission_service,
        "_cache",
        {
            "Cajero": frozenset({"estancias:ver_activos", "estancias:checkout"}),
            "PersonalAtencion": frozenset({"estancias:ver_activos"}),
            "Cocina": frozenset({"restaurante:ver_comandas"}),
            ROL_SISTEMA: frozenset({"estancias:ver_activos", "estancias:checkout"}),
        },
    )


@pytest.fixture
def registros(monkeypatch):
    """Registros simulados: {registro_id: {sucursal_id, estado}}."""
    datos: dict[UUID, dict] = {}

    async def fake_get_registro_alcance(conn, registro_id):
        r = datos.get(registro_id)
        return {"id": registro_id, **r} if r else None

    monkeypatch.setattr(documentos_service, "get_registro_alcance", fake_get_registro_alcance)
    return datos


def _registro(registros, sucursal_id=SUCURSAL_A, estado="A") -> UUID:
    rid = uuid4()
    registros[rid] = {"sucursal_id": sucursal_id, "estado": estado}
    return rid


async def test_staff_de_la_sucursal_con_permiso_puede_ver(registros):
    rid = _registro(registros)
    await documentos_service.autorizar_archivos_registro(None, _user("Cajero", SUCURSAL_A), rid)
    await documentos_service.autorizar_archivos_registro(
        None, _user("PersonalAtencion", SUCURSAL_A), rid
    )


async def test_staff_puede_ver_registro_ya_cerrado_de_su_sucursal(registros):
    rid = _registro(registros, estado="C")
    await documentos_service.autorizar_archivos_registro(None, _user("Cajero", SUCURSAL_A), rid)


async def test_staff_de_otra_sucursal_recibe_404(registros):
    rid = _registro(registros, sucursal_id=SUCURSAL_A)
    with pytest.raises(NoEncontrado):
        await documentos_service.autorizar_archivos_registro(None, _user("Cajero", SUCURSAL_B), rid)


async def test_staff_sin_sucursal_recibe_404(registros):
    rid = _registro(registros)
    with pytest.raises(NoEncontrado):
        await documentos_service.autorizar_archivos_registro(None, _user("Cajero", None), rid)


async def test_rol_sin_permiso_de_estancias_recibe_404(registros):
    rid = _registro(registros)
    with pytest.raises(NoEncontrado):
        await documentos_service.autorizar_archivos_registro(None, _user("Cocina", SUCURSAL_A), rid)


async def test_registro_inexistente_recibe_404(registros):
    with pytest.raises(NoEncontrado):
        await documentos_service.autorizar_archivos_registro(
            None, _user("Cajero", SUCURSAL_A), uuid4()
        )


async def test_sistema_sin_sucursal_elegida_ve_todas(registros):
    rid = _registro(registros, sucursal_id=SUCURSAL_B)
    await documentos_service.autorizar_archivos_registro(None, _user(ROL_SISTEMA, None), rid)


async def test_sistema_parado_en_otra_sucursal_recibe_404(registros):
    rid = _registro(registros, sucursal_id=SUCURSAL_B)
    with pytest.raises(NoEncontrado):
        await documentos_service.autorizar_archivos_registro(
            None, _user(ROL_SISTEMA, SUCURSAL_A), rid
        )


async def test_padre_ve_su_propio_registro(registros):
    rid = _registro(registros)
    await documentos_service.autorizar_archivos_registro(
        None, _user(ROL_PADRE, SUCURSAL_A, sub=str(rid)), rid
    )


async def test_padre_de_otra_familia_recibe_404(registros):
    rid_a = _registro(registros)
    rid_b = _registro(registros)
    with pytest.raises(NoEncontrado):
        await documentos_service.autorizar_archivos_registro(
            None, _user(ROL_PADRE, SUCURSAL_A, sub=str(rid_a)), rid_b
        )


async def test_padre_con_registro_cerrado_recibe_404(registros):
    rid = _registro(registros, estado="C")
    with pytest.raises(NoEncontrado):
        await documentos_service.autorizar_archivos_registro(
            None, _user(ROL_PADRE, SUCURSAL_A, sub=str(rid)), rid
        )


async def test_identificacion_sin_foto_en_bd_es_404_sin_tocar_el_storage(monkeypatch):
    async def fake_lookup(conn, key):
        return None

    async def fake_get_object(key):
        raise AssertionError("no debe leer el storage si la foto no existe en BD")

    monkeypatch.setattr(documentos_service, "get_registro_id_by_foto_ine", fake_lookup)
    monkeypatch.setattr(documentos_service, "get_object", fake_get_object)
    with pytest.raises(NoEncontrado):
        await documentos_service.obtener_identificacion(
            None, _user("Cajero", SUCURSAL_A), "loquesea.jpg"
        )


async def test_identificacion_de_otra_sucursal_no_lee_el_storage(registros, monkeypatch):
    rid = _registro(registros, sucursal_id=SUCURSAL_B)
    llaves: list[str] = []

    async def fake_lookup(conn, key):
        llaves.append(key)
        return rid

    async def fake_get_object(key):
        raise AssertionError("no debe leer el storage sin autorización")

    monkeypatch.setattr(documentos_service, "get_registro_id_by_foto_ine", fake_lookup)
    monkeypatch.setattr(documentos_service, "get_object", fake_get_object)
    with pytest.raises(NoEncontrado):
        await documentos_service.obtener_identificacion(
            None, _user("Cajero", SUCURSAL_A), f"{rid}.jpg"
        )
    assert llaves == [f"uploads/identificaciones/{rid}.jpg"]


async def test_identificacion_autorizada_se_sirve(registros, monkeypatch):
    rid = _registro(registros)

    async def fake_lookup(conn, key):
        return rid

    async def fake_get_object(key):
        import io

        return io.BytesIO(b"jpg"), "image/jpeg"

    monkeypatch.setattr(documentos_service, "get_registro_id_by_foto_ine", fake_lookup)
    monkeypatch.setattr(documentos_service, "get_object", fake_get_object)
    resp = await documentos_service.obtener_identificacion(
        None, _user(ROL_PADRE, SUCURSAL_A, sub=str(rid)), f"{rid}.jpg"
    )
    assert resp.media_type == "image/jpeg"


async def test_fotos_llegada_de_otra_familia_es_404(registros, monkeypatch):
    rid_a = _registro(registros)
    rid_b = _registro(registros)

    async def fake_fotos(conn, registro_id):
        raise AssertionError("no debe listar fotos sin autorización")

    monkeypatch.setattr(documentos_service, "get_fotos_llegada_by_registro_id", fake_fotos)
    with pytest.raises(NoEncontrado):
        await documentos_service.obtener_fotos_llegada_por_registro(
            None, _user(ROL_PADRE, SUCURSAL_A, sub=str(rid_a)), rid_b
        )
