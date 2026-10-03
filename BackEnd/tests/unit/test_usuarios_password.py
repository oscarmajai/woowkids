"""M2 — el servidor exige contraseñas de al menos 8 caracteres al fijarlas."""

import pytest
from app.schemas.auth import LoginRequest
from app.schemas.user import UserCreateRequest, UserUpdateRequest
from pydantic import ValidationError

ROL_CAJERO = "Cajero"


_BASE = {"full_name": "Juan", "role": ROL_CAJERO}


# ── M2: longitud mínima de contraseña ──────────────────────────────────────


@pytest.mark.parametrize("password", ["1", "1234567", ""])
def test_alta_rechaza_contrasenas_cortas(password):
    with pytest.raises(ValidationError) as exc:
        UserCreateRequest(email="a@b.com", password=password, **_BASE)
    assert "al menos 8 caracteres" in str(exc.value)


def test_edicion_rechaza_contrasena_corta_y_acepta_no_cambiarla():
    with pytest.raises(ValidationError):
        UserUpdateRequest(email="a@b.com", password="1234567", **_BASE)
    assert UserUpdateRequest(email="a@b.com", **_BASE).password is None
    assert UserUpdateRequest(email="a@b.com", password="", **_BASE).password is None
    assert UserUpdateRequest(email="a@b.com", password="12345678", **_BASE).password == "12345678"


def test_login_no_exige_longitud_minima():
    """Las cuentas viejas con contraseñas cortas siguen pudiendo entrar."""
    assert LoginRequest(email="a@b.com", password="1").password == "1"
