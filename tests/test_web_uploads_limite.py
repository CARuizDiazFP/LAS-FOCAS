# Nombre de archivo: test_web_uploads_limite.py
# Ubicación de archivo: tests/test_web_uploads_limite.py
# Descripción: Tope de tamaño de uploads del panel (leer_upload / leer_upload_sync → 413) sin DB ni red

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from web.app import comun
from web.app.comun import UploadDemasiadoGrande, leer_upload, leer_upload_sync
from web.app.main import app

MB = 1024 * 1024


class _Contador(io.BytesIO):
    def __init__(self, contenido: bytes) -> None:
        super().__init__(contenido)
        self.lecturas = 0

    def read(self, size: int | None = -1) -> bytes:
        self.lecturas += 1
        return super().read(size)


def _upload(contenido: bytes, nombre: str = "a.xlsx") -> UploadFile:
    return UploadFile(file=_Contador(contenido), filename=nombre)


@pytest.mark.asyncio
async def test_bajo_el_tope_devuelve_todo() -> None:
    contenido = b"x" * (MB + 7)
    assert await leer_upload(_upload(contenido), max_mb=2) == contenido


@pytest.mark.asyncio
async def test_sobre_el_tope_corta_sin_leer_todo() -> None:
    archivo = _upload(b"x" * (5 * MB), "grande.xlsx")
    with pytest.raises(UploadDemasiadoGrande) as exc:
        await leer_upload(archivo, max_mb=1)
    assert exc.value.status_code == 413
    assert exc.value.mensaje == "grande.xlsx supera el límite de 1 MB"
    assert archivo.file.lecturas == 2  # 1 MB + el chunk que pasa el tope; no los 5


def test_variante_sync() -> None:
    assert leer_upload_sync(_upload(b"abc")) == b"abc"
    with pytest.raises(UploadDemasiadoGrande):
        leer_upload_sync(_upload(b"x" * (MB + 1)), max_mb=1)


def test_tope_por_defecto_configurable(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(comun, "MAX_UPLOAD_MB", 1)
    with pytest.raises(UploadDemasiadoGrande):
        leer_upload_sync(_upload(b"x" * (MB + 1)))


def test_ingesta_de_servicios_responde_413(con_sesion, monkeypatch) -> None:  # noqa: ANN001
    con_sesion("admin")
    monkeypatch.setattr(comun, "MAX_UPLOAD_MB", 1)
    res = TestClient(app).post("/api/servicios/ingest", files={"file": ("s.xlsx", b"x" * (MB + 1))})
    assert (res.status_code, res.json()) == (413, {"error": "s.xlsx supera el límite de 1 MB"})


def test_analisis_de_tracking_responde_413(con_sesion) -> None:  # noqa: ANN001
    con_sesion("user")
    res = TestClient(app).post("/api/infra/trackings/analyze", files={"file": ("t.txt", b"x" * (5 * MB + 1))})
    assert (res.status_code, res.json()) == (413, {"error": "t.txt supera el límite de 5 MB"})
