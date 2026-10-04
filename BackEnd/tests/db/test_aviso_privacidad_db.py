"""Aviso de privacidad (migración 107) contra PostgreSQL real, a través de la
app completa (routers, dependencias de sesión y manejadores de errores).

- GET /api/privacidad/aviso responde sin sesión, con los marcadores llenos.
- Publicar una versión es solo del AdministradorSistema (403 a los demás) y
  no modifica las versiones anteriores.
- El check-in sin aceptar el aviso responde 422 y no guarda nada; con
  aceptación guarda en el registro la versión, la fecha y la decisión sobre
  las finalidades voluntarias.

Usa TEST_DATABASE_URL (BD desechable con sql/schema_maestro.sql) y se salta
si no existe. Todo corre en una transacción que se revierte al terminar.
"""

from __future__ import annotations

import json
import os
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL no definida")


@dataclass
class Entorno:
    client: Any
    conn: asyncpg.Connection
    sucursal: UUID
    sistema: UUID
    admin: UUID
    cajero: UUID
    pulseras: list[UUID]
    efectivo: UUID


def _token(usuario: UUID, rol: str, sucursal: UUID | None) -> dict[str, str]:
    from app.core.security import create_access_token
    from app.services.permission_service import get_permissions

    token = create_access_token(
        payload={
            "sub": str(usuario),
            "email": f"{usuario}@woowkids.dev",
            "role": rol,
            "branch_id": str(sucursal) if sucursal else None,
            "permissions": get_permissions(rol),
        },
        expires_delta=timedelta(minutes=30),
    )
    return {"Authorization": f"Bearer {token}"}


async def _usuario(conn: asyncpg.Connection, rol: int, nombre: str) -> UUID:
    usuario_id: UUID = await conn.fetchval(
        "INSERT INTO public.usuarios (email, password_hash, nombre_completo, rol) "
        "VALUES ($1, 'x', $2, $3) RETURNING id",
        f"{uuid4().hex[:10]}@privacidad.dev",
        nombre,
        rol,
    )
    return usuario_id


@pytest_asyncio.fixture
async def entorno(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Entorno]:
    import httpx
    from app.core.database import get_db
    from app.main import app
    from app.services import estancias, permission_service

    conn = await asyncpg.connect(TEST_DATABASE_URL)
    tx = conn.transaction()
    await tx.start()

    async def _get_db() -> AsyncIterator[asyncpg.Connection]:
        yield conn

    # Sin MinIO ni clientes WebSocket en la prueba: la imagen se acepta tal
    # cual y no se sube a ningún lado.
    monkeypatch.setattr(estancias, "validar_y_leer", AsyncMock(return_value=b"jpg"))
    monkeypatch.setattr(estancias, "upload_bytes", AsyncMock())
    monkeypatch.setattr(estancias.manager, "broadcast", AsyncMock())
    try:
        sufijo = uuid4().hex[:6]
        sucursal = await conn.fetchval(
            "INSERT INTO public.sucursales (nombre, clave) VALUES ($1, $2) RETURNING id",
            f"Privacidad {sufijo}",
            sufijo.upper(),
        )
        sistema = await _usuario(conn, 1, "Sistema Privacidad")
        admin = await _usuario(conn, 2, "Admin Privacidad")
        cajero = await _usuario(conn, 3, "Cajero Privacidad")
        caja = await conn.fetchval(
            "INSERT INTO public.cajas (sucursal_id, codigo, nombre, numero) "
            "VALUES ($1, $2, 'Caja privacidad', 1) RETURNING id",
            sucursal,
            f"P-{sufijo}",
        )
        turno = await conn.fetchval(
            "INSERT INTO public.turnos (nombre, hora_inicio, hora_fin) "
            "VALUES ($1, '00:00', '23:59') RETURNING id",
            f"Turno {sufijo}",
        )
        await conn.execute(
            "INSERT INTO public.apertura_caja (caja_id, cajero_id, turno_id, fondo_inicial) "
            "VALUES ($1, $2, $3, 500)",
            caja,
            cajero,
            turno,
        )
        await conn.execute(
            """
            INSERT INTO public.productos (nombre, precio_unitario, tipo, sucursal_id,
                                          config_estancia)
            VALUES ($1, 100, 'E', $2,
                    '[{"min_horas": 1, "max_horas": 5, "precio": 100}]'::jsonb)
            """,
            f"Estancia {sufijo}",
            sucursal,
        )
        pulseras = [
            await conn.fetchval(
                "INSERT INTO public.pulseras (sucursal_id, pulsera_rfid) VALUES ($1, $2) "
                "RETURNING id",
                sucursal,
                f"WK-{random.randint(0, 9_999_999):07d}",
            )
            for i in range(3)
        ]
        efectivo = await conn.fetchval("SELECT id FROM public.metodos_pago WHERE tipo = 'E'")
        await permission_service.load_cache(conn)
        app.dependency_overrides[get_db] = _get_db
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Entorno(client, conn, sucursal, sistema, admin, cajero, pulseras, efectivo)
    finally:
        app.dependency_overrides.clear()
        await tx.rollback()
        await conn.close()


async def _vigente(conn: asyncpg.Connection) -> int:
    version: int = await conn.fetchval("SELECT max(version) FROM public.avisos_privacidad")
    return version


async def test_el_aviso_vigente_es_publico_y_sale_con_los_marcadores_llenos(
    entorno: Entorno,
) -> None:
    resp = await entorno.client.get("/api/privacidad/aviso")
    assert resp.status_code == 200, resp.text
    datos = resp.json()
    assert datos["version"] == await _vigente(entorno.conn)
    assert datos["texto_integral"].startswith("# AVISO DE PRIVACIDAD INTEGRAL")
    assert datos["texto_simplificado"].startswith("# AVISO DE PRIVACIDAD SIMPLIFICADO")
    for texto in (datos["texto_integral"], datos["texto_simplificado"]):
        assert "{{" not in texto


@pytest.mark.parametrize("rol", ["Administrador", "Cajero"])
async def test_solo_el_administrador_del_sistema_publica(entorno: Entorno, rol: str) -> None:
    usuario, sucursal = (
        (entorno.admin, None) if rol == "Administrador" else (entorno.cajero, entorno.sucursal)
    )
    antes = await _vigente(entorno.conn)
    headers = _token(usuario, rol, sucursal)
    body = {"version_base": antes, "responsable": {"razon_social": "Intruso SA"}}

    assert (
        await entorno.client.get("/api/privacidad/admin/aviso", headers=headers)
    ).status_code == 403
    resp = await entorno.client.post("/api/privacidad/admin/aviso", json=body, headers=headers)
    assert resp.status_code == 403
    assert await _vigente(entorno.conn) == antes


async def test_publicar_crea_una_version_nueva_sin_tocar_la_anterior(entorno: Entorno) -> None:
    headers = _token(entorno.sistema, "AdministradorSistema", None)
    anterior = await _vigente(entorno.conn)
    texto_anterior = await entorno.conn.fetchval(
        "SELECT texto_integral FROM public.avisos_privacidad WHERE version = $1", anterior
    )
    body = {
        "version_base": anterior,
        "responsable": {
            "razon_social": "Diversión Infantil del Bajío SA de CV",
            "nombre_comercial": "Woow Kids",
            "domicilio": "Av. Vallarta 1000, Guadalajara, Jalisco",
            "area_datos_personales": "Departamento de Datos Personales",
            "correo_datos_personales": "privacidad@woowkids.dev",
            "telefono_datos_personales": "3312345678",
            "url_aviso": "https://woowkids.dev/aviso-de-privacidad",
            "dias_conservacion_imagenes": 60,
            "anios_conservacion_registros": 5,
        },
        "motivo_cambio": "Datos del responsable",
    }

    resp = await entorno.client.post("/api/privacidad/admin/aviso", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    admin = resp.json()
    assert admin["version"] == anterior + 1
    assert admin["publicado_por"] == "Sistema Privacidad"
    assert admin["pendientes"] == []
    assert admin["historial"][0]["version"] == anterior + 1

    publico = (await entorno.client.get("/api/privacidad/aviso")).json()
    assert publico["version"] == anterior + 1
    assert "Diversión Infantil del Bajío SA de CV" in publico["texto_integral"]
    assert "60 días naturales" in publico["texto_integral"]
    assert "Pendiente de configurar" not in publico["texto_simplificado"]
    assert (
        await entorno.conn.fetchval(
            "SELECT texto_integral FROM public.avisos_privacidad WHERE version = $1", anterior
        )
        == texto_anterior
    )

    # Publicar de nuevo sobre la versión ya reemplazada: 409.
    resp = await entorno.client.post("/api/privacidad/admin/aviso", json=body, headers=headers)
    assert resp.status_code == 409


def _checkin(entorno: Entorno, **consentimiento: Any) -> dict[str, Any]:
    payload = {
        "sucursalId": str(entorno.sucursal),
        "tutor": {"nombreCompleto": "Ana Privacidad", "telefono": "3311112222"},
        "parentesco": "Madre",
        "detalles": [
            {
                "nino": {"nombreCompleto": "Leo Privacidad", "edad": 5, "notas": None},
                "cantidad": 1,
                "pulseraId": str(entorno.pulseras[0]),
            }
        ],
        "pagos": [{"metodoPagoId": str(entorno.efectivo), "monto": 100}],
        **consentimiento,
    }
    return {
        "data": {"payload": json.dumps(payload)},
        "files": [
            ("fotoIne", ("ine.jpg", b"jpg", "image/jpeg")),
            ("fotosLlegada", ("llegada.jpg", b"jpg", "image/jpeg")),
        ],
        "headers": _token(entorno.cajero, "Cajero", entorno.sucursal),
    }


async def _registros_de_la_sucursal(entorno: Entorno) -> list[asyncpg.Record]:
    rows: list[asyncpg.Record] = await entorno.conn.fetch(
        "SELECT aviso_privacidad_version, aviso_privacidad_aceptado_en, "
        "acepta_finalidades_secundarias FROM public.registros WHERE sucursal_id = $1",
        entorno.sucursal,
    )
    return rows


async def test_checkin_sin_aceptar_el_aviso_da_422_y_no_registra_nada(entorno: Entorno) -> None:
    resp = await entorno.client.post("/api/estancias", **_checkin(entorno))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "AVISO_PRIVACIDAD_NO_ACEPTADO"
    assert await _registros_de_la_sucursal(entorno) == []
    assert (
        await entorno.conn.fetchval(
            "SELECT count(*) FROM public.tutores WHERE sucursal_id = $1", entorno.sucursal
        )
        == 0
    )


async def test_checkin_con_una_version_que_ya_no_es_la_vigente_da_422(entorno: Entorno) -> None:
    vieja = await _vigente(entorno.conn)
    await entorno.conn.execute(
        "INSERT INTO public.avisos_privacidad (version, texto_integral, texto_simplificado) "
        "VALUES ($1, 'Integral', 'Simplificado')",
        vieja + 1,
    )
    resp = await entorno.client.post(
        "/api/estancias",
        **_checkin(entorno, aceptaAvisoPrivacidad=True, versionAvisoPrivacidad=vieja),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "AVISO_PRIVACIDAD_DESACTUALIZADO"
    assert await _registros_de_la_sucursal(entorno) == []


async def test_checkin_aceptado_guarda_version_fecha_y_finalidades(entorno: Entorno) -> None:
    version = await _vigente(entorno.conn)
    resp = await entorno.client.post(
        "/api/estancias",
        **_checkin(
            entorno,
            aceptaAvisoPrivacidad=True,
            versionAvisoPrivacidad=version,
            aceptaFinalidadesSecundarias=False,
        ),
    )
    assert resp.status_code == 201, resp.text

    (registro,) = await _registros_de_la_sucursal(entorno)
    assert registro["aviso_privacidad_version"] == version
    assert registro["aviso_privacidad_aceptado_en"] is not None
    assert registro["acepta_finalidades_secundarias"] is False
