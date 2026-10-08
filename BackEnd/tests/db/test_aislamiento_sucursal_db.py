"""Aislamiento por sucursal contra PostgreSQL real.

Siembra dos sucursales (A con datos de todos los módulos, B con su propio
admin y caja abierta) en una BD **desechable** y, para cada endpoint de
sucursal, comprueba:

- cruce: el admin de B pide los datos de A → 403 (parámetro/body con otra
  sucursal) o 404 (recurso por id de otra sucursal);
- positivo: el admin de A pide sus propios datos → no se bloquea.

Requiere ``TEST_DATABASE_URL`` apuntando a una BD con
``sql/schema_maestro.sql`` cargado; si no existe, se salta. Cada test corre
en una transacción que se revierte al final, así que la BD debe estar limpia
de estos ids (el barrido con uvicorn, que sí confirma, usa otra BD).

Para agregar un endpoint basta con sumarlo a ``CASOS``. El mismo sembrado y
la misma tabla los usa el barrido contra un backend levantado con uvicorn
(ver ``sembrar`` y ``CASOS``).
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL no definida (BD desechable)"
)

# Hash bcrypt de '12345678' (mismo que sql/seed_local.sql).
PASSWORD = "12345678"
_HASH = "$2b$12$jGOsFgnr5KIF6TB6gbQ7A.tDGDQ56EsXo8NhGA9oPBYOgAvGIGLWO"


def _u(n: int) -> str:
    return f"c1000000-0000-0000-0000-{n:012d}"


SUC_A = _u(1)
SUC_B = _u(2)

USUARIOS = {
    # clave: (id, email, rol_id, sucursal)
    "admin_a": (_u(11), "aislamiento.admin.a@woowkids.dev", 2, SUC_A),
    "admin_b": (_u(12), "aislamiento.admin.b@woowkids.dev", 2, SUC_B),
    "cajero_b": (_u(13), "aislamiento.cajero.b@woowkids.dev", 3, SUC_B),
    "sistema": (_u(14), "aislamiento.sistema@woowkids.dev", 1, None),
}

# Recursos de la sucursal A.
IDS = {
    "insumo": _u(101),
    "presentacion": _u(102),
    "proveedor": _u(103),
    "compra": _u(104),
    "paquete": _u(105),
    "pulsera": _u(106),
    "caja": _u(107),
    "apertura": _u(108),
    "tipo_evento": _u(109),
    "extra": _u(110),
    "producto": _u(111),
    "producto2": _u(112),
    "reservacion": _u(113),
    "reservacion_extra": _u(114),
    "reservacion_producto": _u(115),
    "pago_reservacion": _u(116),
    "comanda": _u(117),
    "tutor": _u(118),
    "nino": _u(119),
    "registro": _u(120),
    "detalle_registro": _u(121),
    "detalle_compra": _u(122),
    "combo": _u(123),
    # Sucursal B: su caja abierta (los endpoints de cobro exigen turno).
    "caja_b": _u(201),
    "apertura_b": _u(202),
}


async def sembrar(conn: asyncpg.Connection) -> None:
    """Idempotente (ON CONFLICT DO NOTHING) para reusarlo en el barrido con
    uvicorn, donde el sembrado sí se confirma."""
    unidad = await conn.fetchval("SELECT id FROM public.unidades_medida ORDER BY codigo LIMIT 1")
    turno = await conn.fetchval("SELECT id FROM public.turnos ORDER BY nombre LIMIT 1")
    metodo = await conn.fetchval("SELECT id FROM public.metodos_pago ORDER BY nombre LIMIT 1")
    i = IDS
    sql = f"""
    INSERT INTO public.sucursales (id, nombre, clave) VALUES
      ('{SUC_A}', 'Aislamiento Sucursal A', 'AISA'), ('{SUC_B}', 'Aislamiento Sucursal B', 'AISB')
      ON CONFLICT DO NOTHING;
    INSERT INTO public.usuarios (id, email, password_hash, nombre_completo, rol) VALUES
      {
        ", ".join(
            f"('{uid}', '{email}', '{_HASH}', 'Aislamiento {clave}', {rol})"
            for clave, (uid, email, rol, _s) in USUARIOS.items()
        )
    }
      ON CONFLICT DO NOTHING;
    INSERT INTO public.usuarios_sucursal (usuario_id, sucursal_id) VALUES
      {
        ", ".join(
            f"('{uid}', '{suc}')" for uid, _e, _r, suc in USUARIOS.values() if suc is not None
        )
    }
      ON CONFLICT DO NOTHING;
    INSERT INTO public.proveedores (id, sucursal_id, nombre)
      VALUES ('{i["proveedor"]}', '{SUC_A}', 'Aislamiento Proveedor A') ON CONFLICT DO NOTHING;
    INSERT INTO public.insumos (id, sucursal_id, nombre, unidad_base_id, unidad_compra_id)
      VALUES ('{i["insumo"]}', '{SUC_A}', 'Aislamiento Leche A', '{unidad}', '{unidad}')
      ON CONFLICT DO NOTHING;
    INSERT INTO public.presentaciones_insumo (id, insumo_id, nombre, equivalencia_base)
      VALUES ('{i["presentacion"]}', '{i["insumo"]}', 'Aislamiento Caja', 12)
      ON CONFLICT DO NOTHING;
    INSERT INTO public.compras (id, sucursal_id, proveedor_id)
      VALUES ('{i["compra"]}', '{SUC_A}', '{i["proveedor"]}') ON CONFLICT DO NOTHING;
    INSERT INTO public.detalle_compras
        (id, compra_id, insumo_id, cantidad, costo_unitario, unidad_medida_id)
      VALUES ('{i["detalle_compra"]}', '{i["compra"]}', '{i["insumo"]}', 1, 10, '{unidad}')
      ON CONFLICT DO NOTHING;
    INSERT INTO public.productos (id, sucursal_id, nombre, precio_unitario, tipo) VALUES
      ('{i["producto"]}', '{SUC_A}', 'Aislamiento Pizza A', 95, 'A'),
      ('{i["producto2"]}', '{SUC_A}', 'Aislamiento Refresco A', 22, 'B')
      ON CONFLICT DO NOTHING;
    INSERT INTO public.productos (id, sucursal_id, nombre, precio_unitario, tipo, es_combo)
      VALUES ('{i["combo"]}', '{SUC_A}', 'Aislamiento Combo A', 110, 'C', TRUE)
      ON CONFLICT DO NOTHING;
    INSERT INTO public.producto_combo (combo_id, producto_id, cantidad)
      VALUES ('{i["combo"]}', '{i["producto"]}', 1) ON CONFLICT DO NOTHING;
    INSERT INTO public.paquetes (id, sucursal_id, nombre, precio_base, max_invitados)
      VALUES ('{i["paquete"]}', '{SUC_A}', 'Aislamiento Paquete A', 1000, 30)
      ON CONFLICT DO NOTHING;
    INSERT INTO public.tipos_evento (id, sucursal_id, nombre)
      VALUES ('{i["tipo_evento"]}', '{SUC_A}', 'Aislamiento Cumpleaños A') ON CONFLICT DO NOTHING;
    INSERT INTO public.paquete_tipos_evento (paquete_id, tipo_evento_id)
      VALUES ('{i["paquete"]}', '{i["tipo_evento"]}') ON CONFLICT DO NOTHING;
    INSERT INTO public.extras (id, sucursal_id, nombre, precio)
      VALUES ('{i["extra"]}', '{SUC_A}', 'Aislamiento Piñata A', 100) ON CONFLICT DO NOTHING;
    INSERT INTO public.pulseras (id, sucursal_id, pulsera_rfid)
      VALUES ('{i["pulsera"]}', '{SUC_A}', 'WK-9100001') ON CONFLICT DO NOTHING;
    INSERT INTO public.cajas (id, sucursal_id, codigo, nombre, numero) VALUES
      ('{i["caja"]}', '{SUC_A}', 'AIS-A', 'Aislamiento Caja A', 91),
      ('{i["caja_b"]}', '{SUC_B}', 'AIS-B', 'Aislamiento Caja B', 92)
      ON CONFLICT DO NOTHING;
    INSERT INTO public.apertura_caja (id, caja_id, cajero_id, turno_id, fondo_inicial, estado)
      VALUES
      ('{i["apertura"]}', '{i["caja"]}', '{USUARIOS["admin_a"][0]}', '{turno}', 1000, 'ABIERTA'),
      ('{i["apertura_b"]}', '{i["caja_b"]}', '{USUARIOS["admin_b"][0]}', '{turno}', 1000,
       'ABIERTA')
      ON CONFLICT DO NOTHING;
    INSERT INTO public.reservaciones
        (id, sucursal_id, tipo_evento_id, paquete_id, nombre_cliente, telefono_cliente,
         email_cliente, fecha_evento, hora_inicio, hora_fin, numero_personas, precio_base,
         precio_total)
      VALUES ('{i["reservacion"]}', '{SUC_A}', '{i["tipo_evento"]}', '{i["paquete"]}',
              'Cliente Privado A', '3300000001', 'privado.a@correo.test',
              CURRENT_DATE + 30, '16:00', '19:00', 10, 1000, 1000)
      ON CONFLICT DO NOTHING;
    INSERT INTO public.reservacion_extras (id, reservacion_id, extra_id, cantidad,
                                           precio_unitario)
      VALUES ('{i["reservacion_extra"]}', '{i["reservacion"]}', '{i["extra"]}', 1, 100)
      ON CONFLICT DO NOTHING;
    INSERT INTO public.reservacion_productos (id, reservacion_id, producto_id, cantidad,
                                              precio_unitario)
      VALUES ('{i["reservacion_producto"]}', '{i["reservacion"]}', '{i["producto"]}', 1, 95)
      ON CONFLICT DO NOTHING;
    INSERT INTO public.pagos_reservacion (id, reservacion_id, metodo_pago_id, monto)
      VALUES ('{i["pago_reservacion"]}', '{i["reservacion"]}', '{metodo}', 100)
      ON CONFLICT DO NOTHING;
    INSERT INTO public.comandas (id, sucursal_id, ticket_numero, total_final)
      VALUES ('{i["comanda"]}', '{SUC_A}', 'AIS-0001', 95) ON CONFLICT DO NOTHING;
    INSERT INTO public.tutores (id, sucursal_id, nombre_completo, telefono)
      VALUES ('{i["tutor"]}', '{SUC_A}', 'Tutor Privado A', '3300000002')
      ON CONFLICT DO NOTHING;
    INSERT INTO public.ninos (id, sucursal_id, nombre_completo, edad)
      VALUES ('{i["nino"]}', '{SUC_A}', 'Niño A', 6) ON CONFLICT DO NOTHING;
    INSERT INTO public.registros (id, sucursal_id, tutores_id)
      VALUES ('{i["registro"]}', '{SUC_A}', '{i["tutor"]}') ON CONFLICT DO NOTHING;
    INSERT INTO public.detalles_registro
        (id, sucursal_id, registros_id, ninos_id, pulseras_id, productos_id, cantidad, precio,
         parentesco, entrada, salida_esperada)
      VALUES ('{i["detalle_registro"]}', '{SUC_A}', '{i["registro"]}', '{i["nino"]}',
              '{i["pulsera"]}', '{i["producto"]}', 1, 150, 'Madre', NOW(),
              NOW() + INTERVAL '1 hour')
      ON CONFLICT DO NOTHING;
    INSERT INTO public.configuracion_lealtad (sucursal_id, dias_caducidad) VALUES
      ('{SUC_A}', 30), ('{SUC_B}', 30) ON CONFLICT DO NOTHING;
    """
    await conn.execute(sql)


def token_para(clave: str) -> str:
    """JWT firmado igual que en el login (para el test en proceso)."""
    from app.core.security import create_access_token
    from app.services.permission_service import get_permissions

    uid, email, rol_id, suc = USUARIOS[clave]
    rol = {1: "AdministradorSistema", 2: "Administrador", 3: "Cajero"}[rol_id]
    return create_access_token(
        payload={
            "sub": uid,
            "email": email,
            "role": rol,
            "branch_id": suc,
            "permissions": get_permissions(rol),
        },
        expires_delta=timedelta(minutes=30),
    )


# ── Tabla de endpoints ─────────────────────────────────────────────────────


@dataclass
class Caso:
    metodo: str
    ruta: str  # admite {suc} y {<clave de IDS>}
    cruce: int  # 403 (otra sucursal por parámetro/body) o 404 (recurso por id)
    json: Callable[[str], Any] | None = None  # recibe la sucursal del body
    form: Callable[[str], dict[str, Any]] | None = None
    archivos: bool = False
    # Códigos aceptables para el dueño (None = no se prueba el positivo, p. ej.
    # cuando requiere MinIO). Por defecto, cualquier 2xx.
    positivo: tuple[int, ...] | None = field(default=(200, 201, 204))

    @property
    def id(self) -> str:
        return f"{self.metodo} {self.ruta}"

    def url(self, suc: str) -> str:
        return self.ruta.format(suc=suc, **IDS)


_FECHA = "fecha=2030-01-15"
_RANGO = "desde=2026-01-01&hasta=2030-12-31"


def _reservacion(suc: str) -> dict[str, Any]:
    return {
        "sucursal_id": suc,
        "tipo_evento_id": IDS["tipo_evento"],
        "paquete_id": IDS["paquete"],
        "nombre_cliente": "Nuevo",
        "telefono_cliente": "3300000003",
        "fecha_evento": "2030-01-20",
        "hora_inicio": "16:00:00",
        "hora_fin": "19:00:00",
        "numero_personas": 10,
        "precio_base": 1000,
        "precio_total": 1000,
    }


def _venta() -> dict[str, Any]:
    """Venta POS con un producto de la sucursal A (para B: 422)."""
    return {
        "total_final": 95,
        "detalles_comanda": [
            {
                "producto_id": IDS["producto"],
                "nombre": "Aislamiento Pizza A",
                "cantidad": 1,
                "precio_unitario": 95,
                "subtotal": 95,
            }
        ],
        "pagos": [{"metodo_pago_id": IDS["_efectivo"], "monto": 95}],
    }


CASOS: list[Caso] = [
    # ── Inventario ──
    Caso("GET", "/api/insumos?sucursal_id={suc}", 403),
    Caso("GET", "/api/insumos/alertas?sucursal_id={suc}", 403),
    Caso("GET", "/api/insumos/estimaciones?sucursal_id={suc}", 403),
    Caso("GET", "/api/insumos/export?sucursal_id={suc}", 403),
    Caso("GET", "/api/insumos/reporte-cogs?sucursal_id={suc}", 403),
    Caso("GET", "/api/insumos/reporte-cogs/resumen?sucursal_id={suc}", 403),
    Caso("GET", "/api/insumos/reporte-cogs/export?sucursal_id={suc}", 403),
    Caso(
        "POST",
        "/api/insumos",
        403,
        json=lambda s: {
            "sucursal_id": s,
            "nombre": "Aislamiento Insumo nuevo",
            "unidad_base_id": IDS["_unidad"],
            "unidad_compra_id": IDS["_unidad"],
        },
    ),
    Caso("GET", "/api/insumos/{insumo}", 404),
    Caso("PATCH", "/api/insumos/{insumo}", 404, json=lambda s: {"descripcion": "x"}),
    Caso("GET", "/api/insumos/{insumo}/movimientos", 404),
    Caso("GET", "/api/insumos/{insumo}/movimientos/export", 404),
    Caso(
        "POST",
        "/api/insumos/{insumo}/movimientos",
        404,
        json=lambda s: {"tipo": "E", "cantidad": 1},
    ),
    Caso("POST", "/api/insumos/{insumo}/conteo", 404, json=lambda s: {"stock_contado": 5}),
    Caso("GET", "/api/insumos/{insumo}/presentaciones", 404),
    Caso(
        "POST",
        "/api/insumos/{insumo}/presentaciones",
        404,
        json=lambda s: {"nombre": "Aislamiento Six", "equivalencia_base": 6},
    ),
    Caso(
        "PATCH",
        "/api/insumos/{insumo}/presentaciones/{presentacion}",
        404,
        json=lambda s: {"nombre": "Aislamiento Caja 12"},
    ),
    Caso("DELETE", "/api/insumos/{insumo}/presentaciones/{presentacion}", 404),
    Caso("GET", "/api/proveedores?sucursal_id={suc}", 403),
    Caso(
        "POST",
        "/api/proveedores",
        403,
        json=lambda s: {"sucursal_id": s, "nombre": "Aislamiento Proveedor 2"},
    ),
    Caso("GET", "/api/proveedores/{proveedor}", 404),
    Caso("PATCH", "/api/proveedores/{proveedor}", 404, json=lambda s: {"nombre": "Aislamiento P"}),
    Caso("GET", "/api/compras?sucursal_id={suc}", 403),
    Caso(
        "POST",
        "/api/compras",
        403,
        json=lambda s: {
            "sucursal_id": s,
            "proveedor_id": IDS["proveedor"],
            "detalles": [
                {
                    "insumo_id": IDS["insumo"],
                    "unidad_medida_id": IDS["_unidad"],
                    "cantidad": 1,
                    "costo_unitario": 10,
                }
            ],
        },
    ),
    Caso("GET", "/api/compras/{compra}", 404),
    Caso("PATCH", "/api/compras/{compra}", 404, json=lambda s: {"notas": "Aislamiento"}),
    Caso("POST", "/api/compras/{compra}/recibir", 404),
    # 409 si ya se recibió (en el barrido con uvicorn el estado se acumula).
    Caso("POST", "/api/compras/{compra}/cancelar", 404, positivo=(200, 409)),
    Caso("DELETE", "/api/insumos/{insumo}", 404, positivo=(204, 409)),
    Caso("DELETE", "/api/proveedores/{proveedor}", 404, positivo=(204, 409)),
    # ── Productos y receta ──
    Caso("GET", "/api/productos/admin?sucursal_id={suc}", 403),
    Caso(
        "POST",
        "/api/productos",
        403,
        form=lambda s: {
            "sucursal_id": s,
            "nombre": "Aislamiento Hot dog",
            "precio_unitario": 50,
            "tipo": "A",
        },
    ),
    Caso("GET", "/api/productos/{producto}", 404),
    Caso("GET", "/api/productos/{combo}/combo-hijos", 404),
    Caso("PATCH", "/api/productos/{producto}", 404, form=lambda s: {"descripcion": "Aislamiento"}),
    Caso("GET", "/api/productos/{producto}/receta", 404),
    Caso("PUT", "/api/productos/{producto}/receta/{insumo}", 404, json=lambda s: {"cantidad": 1}),
    Caso("DELETE", "/api/productos/{producto}/receta/{insumo}", 404, positivo=(204, 404)),
    # ── Paquetes, pulseras, extras y tipos de evento ──
    Caso("GET", "/api/paquetes?sucursal_id={suc}", 403),
    Caso(
        "POST",
        "/api/paquetes",
        403,
        json=lambda s: {"sucursal_id": s, "nombre": "Aislamiento Paquete 2", "precio_base": 10},
    ),
    Caso("GET", "/api/paquetes/{paquete}", 404),
    Caso("PATCH", "/api/paquetes/{paquete}", 404, json=lambda s: {"descripcion": "Aislamiento"}),
    Caso("POST", "/api/paquetes/{paquete}/duplicar", 404),
    Caso("GET", "/api/paquete-tipos-evento/{paquete}", 404),
    Caso("DELETE", "/api/paquete-tipos-evento/{paquete}/{tipo_evento}", 404),
    Caso("GET", "/api/pulseras/sucursal/{suc}", 403),
    Caso("GET", "/api/pulseras/inventario/{suc}", 403),
    Caso("GET", "/api/pulseras/admin/{suc}", 403),
    Caso(
        "POST",
        "/api/pulseras",
        403,
        json=lambda s: {"sucursal_id": s, "pulsera_rfid": "WK-9100002"},
    ),
    Caso("PATCH", "/api/pulseras/{pulsera}", 404, json=lambda s: {"activo": True}),
    Caso(
        "POST",
        "/api/extras",
        403,
        json=lambda s: {"sucursal_id": s, "nombre": "Aislamiento E", "precio": 1},
    ),
    Caso("GET", "/api/extras/{extra}", 404),
    Caso("PATCH", "/api/extras/{extra}", 404, json=lambda s: {"descripcion": "Aislamiento"}),
    Caso(
        "POST",
        "/api/tipos-evento",
        403,
        json=lambda s: {"sucursal_id": s, "nombre": "Aislamiento T"},
    ),
    Caso("GET", "/api/tipos-evento/{tipo_evento}", 404),
    Caso(
        "PATCH",
        "/api/tipos-evento/{tipo_evento}",
        404,
        json=lambda s: {"descripcion": "Aislamiento"},
    ),
    # ── Reservaciones (datos personales) ──
    Caso("GET", f"/api/reservaciones/disponibilidad?sucursal_id={{suc}}&{_FECHA}", 403),
    Caso("GET", "/api/reservaciones/evento-cercano/{suc}", 403),
    Caso("GET", "/api/reservaciones/{reservacion}", 404),
    Caso("PATCH", "/api/reservaciones/{reservacion}", 404, json=lambda s: {"notas": "Aislamiento"}),
    Caso("POST", "/api/reservaciones", 403, json=_reservacion),
    Caso("GET", "/api/reservacion-extras/reservacion/{reservacion}", 404),
    Caso("GET", "/api/reservacion-extras/{reservacion_extra}", 404),
    Caso(
        "PATCH", "/api/reservacion-extras/{reservacion_extra}", 404, json=lambda s: {"cantidad": 2}
    ),
    Caso(
        "POST",
        "/api/reservacion-extras",
        404,
        json=lambda s: {
            "reservacion_id": IDS["reservacion"],
            "extra_id": IDS["extra"],
            "cantidad": 1,
            "precio_unitario": 100,
        },
    ),
    Caso("GET", "/api/reservacion-productos/reservacion/{reservacion}", 404),
    Caso("GET", "/api/reservacion-productos/{reservacion_producto}", 404),
    Caso(
        "PATCH",
        "/api/reservacion-productos/{reservacion_producto}",
        404,
        json=lambda s: {"cantidad": 2},
    ),
    Caso("GET", "/api/pagos-reservacion/reservacion/{reservacion}", 404),
    Caso("GET", "/api/pagos-reservacion/{pago_reservacion}", 404),
    Caso(
        "PATCH",
        "/api/pagos-reservacion/{pago_reservacion}",
        404,
        json=lambda s: {"notas": "Aislamiento"},
    ),
    Caso(
        "POST",
        "/api/pagos-reservacion",
        404,
        json=lambda s: {
            "reservacion_id": IDS["reservacion"],
            "metodo_pago_id": IDS["_metodo"],
            "monto": 50,
        },
    ),
    Caso("DELETE", "/api/reservacion-extras/{reservacion_extra}", 404),
    Caso("DELETE", "/api/reservacion-productos/{reservacion_producto}", 404),
    # Un pago registrado no se borra (409); el alcance se valida antes.
    Caso("DELETE", "/api/pagos-reservacion/{pago_reservacion}", 404, positivo=(409,)),
    Caso("DELETE", "/api/reservaciones/{reservacion}", 404),
    # ── Cajas y arqueos ──
    Caso("GET", "/api/turnos-caja/cajas?sucursal_id={suc}", 403),
    Caso("GET", "/api/turnos-caja/historial?sucursal_id={suc}", 403),
    Caso("GET", "/api/turnos-caja/historial/resumen?sucursal_id={suc}", 403),
    Caso("GET", "/api/turnos-caja/{apertura}/retiros", 404),
    Caso("GET", "/api/cajas?sucursal_id={suc}", 403),
    Caso("PATCH", "/api/cajas/{caja}", 404, json=lambda s: {"nombre": "Aislamiento Caja 2"}),
    # ── Estancias, comandas y pagos ──
    Caso("GET", "/api/estancias/activos/{suc}", 403),
    Caso("GET", "/api/estancias/productos/{suc}", 403),
    Caso("GET", "/api/estancias/{detalle_registro}/checkout/cotizacion", 404),
    Caso(
        "POST",
        "/api/estancias",
        403,
        form=lambda s: {
            "sucursalId": s,
            "tutor": {"nombreCompleto": "T", "telefono": "3300000004"},
            "parentesco": "Madre",
            "detalles": [],
        },
        archivos=True,
        positivo=None,
    ),
    Caso("GET", "/api/pagos/detalles/comanda/{comanda}", 404),
    Caso("GET", "/api/pagos/detalles/estancia/{registro}", 404),
    Caso("GET", "/api/pagos/detalles/reservacion/{reservacion}", 404),
    Caso("PATCH", "/api/comandas/{comanda}/estado", 404, json=lambda s: {"estado_actual": "E"}),
    # Producto de otra sucursal: lo rechaza el cálculo de precios del servidor.
    Caso("POST", "/api/pagos/completar", 422, json=lambda s: _venta()),
    # ── Lealtad y sucursal ──
    Caso("GET", "/api/lealtad/configuracion?sucursal_id={suc}", 403),
    Caso("GET", "/api/lealtad/reporte?sucursal_id={suc}", 403),
    Caso("GET", "/api/lealtad/saldo?celular=3300000001&sucursal_id={suc}", 403),
    Caso("GET", "/api/sucursales/{suc}", 403),
    Caso("GET", f"/api/sucursales/{{suc}}/indicadores?{_RANGO}", 403),
]


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def entorno() -> AsyncIterator[Any]:
    """Conexión con el sembrado dentro de una transacción revertida al final,
    y un cliente HTTP en proceso que usa esa misma conexión."""
    import httpx
    from app.core.database import get_db
    from app.main import app
    from app.services import permission_service

    conn = await asyncpg.connect(TEST_DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        await sembrar(conn)
        IDS["_unidad"] = str(
            await conn.fetchval("SELECT id FROM public.unidades_medida ORDER BY codigo LIMIT 1")
        )
        IDS["_metodo"] = str(
            await conn.fetchval("SELECT id FROM public.metodos_pago ORDER BY nombre LIMIT 1")
        )
        IDS["_efectivo"] = str(
            await conn.fetchval("SELECT id FROM public.metodos_pago WHERE nombre = 'Efectivo'")
        )
        await permission_service.load_cache(conn)

        async def _get_db() -> AsyncIterator[asyncpg.Connection]:
            yield conn

        app.dependency_overrides[get_db] = _get_db
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, conn
    finally:
        app.dependency_overrides.clear()
        await tx.rollback()
        await conn.close()


async def enviar(client: Any, caso: Caso, token: str, suc: str) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    url = caso.url(suc)
    if caso.form is not None:
        files: Any = None
        if caso.archivos:
            files = [
                ("fotoIne", ("ine.jpg", b"x", "image/jpeg")),
                ("fotosLlegada", ("llegada.jpg", b"x", "image/jpeg")),
            ]
        return await client.request(
            caso.metodo,
            url,
            data={"payload": json.dumps(caso.form(suc))},
            files=files,
            headers=headers,
        )
    body = caso.json(suc) if caso.json is not None else None
    return await client.request(caso.metodo, url, json=body, headers=headers)


@pytest.mark.parametrize("caso", CASOS, ids=[c.id for c in CASOS])
async def test_otra_sucursal_bloqueada(entorno: Any, caso: Caso) -> None:
    client, _conn = entorno
    resp = await enviar(client, caso, token_para("admin_b"), SUC_A)
    assert resp.status_code == caso.cruce, resp.text


@pytest.mark.parametrize(
    "caso", [c for c in CASOS if c.positivo], ids=[c.id for c in CASOS if c.positivo]
)
async def test_propia_sucursal_permitida(entorno: Any, caso: Caso) -> None:
    client, _conn = entorno
    resp = await enviar(client, caso, token_para("admin_a"), SUC_A)
    assert caso.positivo is not None
    assert resp.status_code in caso.positivo, resp.text


async def test_listado_sin_sucursal_id_no_devuelve_otra_sucursal(entorno: Any) -> None:
    """Antes, GET /proveedores, /insumos, /compras, /paquetes y
    /turnos-caja/cajas sin sucursal_id devolvían los de todas las sucursales."""
    client, _conn = entorno
    headers = {"Authorization": f"Bearer {token_para('admin_b')}"}
    for ruta in (
        "/api/proveedores",
        "/api/insumos",
        "/api/compras",
        "/api/paquetes",
        "/api/turnos-caja/cajas",
        "/api/productos/admin",
    ):
        resp = await client.get(ruta, headers=headers)
        assert resp.status_code == 200, (ruta, resp.text)
        sucursales = {str(item["sucursal_id"]) for item in resp.json()}
        assert sucursales <= {SUC_B}, (ruta, sucursales)


async def test_cajero_no_lee_reservacion_de_otra_sucursal(entorno: Any) -> None:
    client, _conn = entorno
    headers = {"Authorization": f"Bearer {token_para('cajero_b')}"}
    resp = await client.get(f"/api/reservaciones/{IDS['reservacion']}", headers=headers)
    assert resp.status_code == 404
    assert "Cliente Privado A" not in resp.text


async def test_cruce_no_modifica_datos(entorno: Any) -> None:
    """Las escrituras bloqueadas no tocan la BD de la sucursal A."""
    client, conn = entorno
    headers = {"Authorization": f"Bearer {token_para('admin_b')}"}
    await client.patch(
        f"/api/reservaciones/{IDS['reservacion']}",
        json={"estado": "cancelada", "nombre_cliente": "Hackeado"},
        headers=headers,
    )
    await client.delete(f"/api/insumos/{IDS['insumo']}", headers=headers)
    fila = await conn.fetchrow(
        "SELECT nombre_cliente, estado FROM public.reservaciones WHERE id = $1",
        UUID(IDS["reservacion"]),
    )
    assert fila["nombre_cliente"] == "Cliente Privado A"
    assert fila["estado"] != "cancelada"
    assert await conn.fetchval(
        "SELECT activo FROM public.insumos WHERE id = $1", UUID(IDS["insumo"])
    )


async def test_sistema_ve_todas_y_se_para_en_una(entorno: Any) -> None:
    client, _conn = entorno
    headers = {"Authorization": f"Bearer {token_para('sistema')}"}
    resp = await client.get("/api/proveedores", headers=headers)
    assert resp.status_code == 200
    assert SUC_A in {str(p["sucursal_id"]) for p in resp.json()}
    resp = await client.get(f"/api/reservaciones/{IDS['reservacion']}", headers=headers)
    assert resp.status_code == 200
    vista_b = {**headers, "X-Sucursal-Vista": SUC_B}
    resp = await client.get("/api/proveedores", headers=vista_b)
    assert resp.status_code == 200
    assert {str(p["sucursal_id"]) for p in resp.json()} <= {SUC_B}
    resp = await client.get(f"/api/insumos?sucursal_id={SUC_A}", headers=vista_b)
    assert resp.status_code == 200
    assert {str(p["sucursal_id"]) for p in resp.json()} == {SUC_A}
