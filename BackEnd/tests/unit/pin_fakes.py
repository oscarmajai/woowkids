"""Dobles de prueba para la validación de PIN de caja (A5/A16).

``LimiteEnMemoria`` reemplaza ``intentos_pin_repository`` por un contador en
memoria con la misma semántica (llave usuario + sucursal, ventana fija), y
``ConexionConTransaccion`` es un conn falso que solo soporta
``conn.transaction()``: si el código toca la BD por otro lado, revienta.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.repositories import intentos_pin_repository


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: Any) -> bool:
        return False


class ConexionConTransaccion:
    def transaction(self) -> _Tx:
        return _Tx()


class LimiteEnMemoria:
    def __init__(self) -> None:
        self.fallos: dict[tuple[str, str | None], int] = {}
        self.tipos: list[str] = []

    @staticmethod
    def _llave(usuario_id: Any, sucursal_id: Any) -> tuple[str, str | None]:
        return str(usuario_id), str(sucursal_id) if sucursal_id else None

    def instalar(self, monkeypatch: pytest.MonkeyPatch) -> LimiteEnMemoria:
        async def bloquear_llave(_conn: Any, _u: Any, _s: Any) -> None:
            return None

        async def segundos_de_bloqueo(
            _conn: Any, usuario_id: Any, sucursal_id: Any, max_fallos: int, _ventana: int
        ) -> int:
            fallos = self.fallos.get(self._llave(usuario_id, sucursal_id), 0)
            return 600 if fallos >= max_fallos else 0

        async def registrar_fallo(
            _conn: Any, usuario_id: Any, sucursal_id: Any, tipo: str, _por: Any
        ) -> None:
            llave = self._llave(usuario_id, sucursal_id)
            self.fallos[llave] = self.fallos.get(llave, 0) + 1
            self.tipos.append(tipo)

        async def limpiar(_conn: Any, usuario_id: Any, sucursal_id: Any) -> None:
            self.fallos.pop(self._llave(usuario_id, sucursal_id), None)

        async def purgar_viejos(_conn: Any, _u: Any) -> None:
            return None

        for nombre, fn in {
            "bloquear_llave": bloquear_llave,
            "segundos_de_bloqueo": segundos_de_bloqueo,
            "registrar_fallo": registrar_fallo,
            "limpiar": limpiar,
            "purgar_viejos": purgar_viejos,
        }.items():
            monkeypatch.setattr(intentos_pin_repository, nombre, fn)
        return self

    def total(self) -> int:
        return sum(self.fallos.values())
