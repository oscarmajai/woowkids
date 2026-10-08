"""Variables de entorno mínimas para que `app.core.config.Settings()` se
instancie al importar módulos de servicio en los tests unitarios (no hay
`.env` en los worktrees). No se usa una base de datos real: los tests
unitarios mockean los repositories."""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
os.environ.setdefault("MINIO_ACCESS_KEY", "test-access-key")
os.environ.setdefault("MINIO_SECRET_KEY", "test-secret-key")

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _turno_abierto_para_cobros() -> Iterator[AsyncMock]:
    """Cada cobro toma un bloqueo compartido de la apertura y vuelve a
    exigir que el turno esté ABIERTA (turnos_caja_service.bloquear_turno_para_cobro).
    Los tests unitarios usan conexiones falsas que no responden a ese SELECT,
    así que por defecto el turno está abierto. Los tests de ese bloqueo lo vuelven a
    parchear con el estado que quieren probar."""
    with patch(
        "app.services.turnos_caja_service.bloquear_apertura_para_cobro",
        AsyncMock(return_value={"id": "apertura", "estado": "ABIERTA"}),
    ) as mock:
        yield mock
