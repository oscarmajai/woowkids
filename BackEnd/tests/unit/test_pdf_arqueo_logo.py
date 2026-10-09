from app.schemas.caja import DetalleArqueoResponse
from app.services import pdf_service


def _detalle() -> DetalleArqueoResponse:
    return DetalleArqueoResponse(
        id="arq-1",
        cajero_nombre="Ana",
        terminal="CAJA 01",
        sucursal_nombre="Plaza Colibríes",
        fecha_apertura="2026-10-08T15:00:00+00:00",
        fecha_cierre="2026-10-08T23:00:00+00:00",
        fondo_inicial=500,
        total_declarado=1500,
        total_esperado=1500,
        diferencia_neta=0,
    )


def test_el_pdf_de_arqueo_lleva_el_logo() -> None:
    pdf = pdf_service.generar_pdf_arqueo(_detalle())
    assert pdf.startswith(b"%PDF")
    assert b"/Subtype /Image" in pdf


def test_sin_el_archivo_del_logo_el_pdf_se_genera_igual(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(pdf_service, "_LOGO", pdf_service._LOGO.with_name("no-existe.png"))
    pdf = pdf_service.generar_pdf_arqueo(_detalle())
    assert pdf.startswith(b"%PDF")
    assert b"/Subtype /Image" not in pdf
