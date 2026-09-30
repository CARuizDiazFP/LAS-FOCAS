# Nombre de archivo: test_logs_cleanup.py
# Ubicación de archivo: tests/test_logs_cleanup.py
# Descripción: Pruebas de scripts/logs_cleanup.py — rotación por renombre, retención, tope total, truncado y protección por ERROR reciente

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta

from core.logging import BufferedAppendFileHandler
from scripts import logs_cleanup as lc

_MB = 1024 * 1024


def _plan(carpeta, **kwargs):
    base = dict(max_mb=1, dias=14, max_total_mb=500, truncar=[], ventana_error_min=10, forzar=False)
    base.update(kwargs)
    return lc.armar_plan(carpeta, **base)


def _escribir(ruta, tamano_mb=0.0, texto="", edad_dias=0.0):
    """`texto` va al FINAL, como en un log real: lo más reciente es lo último."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"x" * int(tamano_mb * _MB) + b"\n" + texto.encode())
    if edad_dias:
        viejo = time.time() - edad_dias * 86400
        os.utime(ruta, (viejo, viejo))
    return ruta


def _linea(nivel: str, hace_min: float) -> str:
    momento = datetime.now() - timedelta(minutes=hace_min)
    return f"{momento:%Y-%m-%d %H:%M:%S},000 service=x level={nivel} msg=algo\n"


def test_rota_activos_grandes_y_deja_chicos(tmp_path):
    grande = _escribir(tmp_path / "web.log", 2)
    _escribir(tmp_path / "api.log", 0.1)
    plan = _plan(tmp_path)
    assert plan.rotar == [grande]
    lc.aplicar(plan)
    assert not grande.exists()
    assert len(list(tmp_path.glob("web.log.*"))) == 1


def test_borra_rotados_viejos_incluidos_los_del_formato_anterior(tmp_path):
    viejo = _escribir(tmp_path / "dev" / "web.log.20260801-000000", 0.1, edad_dias=30)
    viejo_numerico = _escribir(tmp_path / "web.log.3", 0.1, edad_dias=30)
    reciente = _escribir(tmp_path / "web.log.20260929-000000", 0.1, edad_dias=1)
    plan = _plan(tmp_path)
    assert sorted(plan.borrar) == sorted([viejo, viejo_numerico])
    lc.aplicar(plan)
    assert reciente.exists() and not viejo.exists()


def test_tope_total_borra_los_rotados_mas_viejos_primero(tmp_path):
    a = _escribir(tmp_path / "x.log.20260920-000000", 1, edad_dias=3)
    b = _escribir(tmp_path / "x.log.20260925-000000", 1, edad_dias=2)
    _escribir(tmp_path / "x.log", 0.5)
    plan = _plan(tmp_path, max_mb=10, max_total_mb=2)
    assert plan.borrar == [a]
    assert b not in plan.borrar


def test_error_reciente_protege_el_archivo(tmp_path):
    ruta = _escribir(tmp_path / "cromo_worker.log", 2, texto=_linea("ERROR", hace_min=1))
    plan = _plan(tmp_path, truncar=[ruta])
    assert plan.rotar == [] and plan.truncar == []
    assert [p for p, _ in plan.protegidos] == [ruta]
    assert _plan(tmp_path, forzar=True).rotar == [ruta]


def test_error_reciente_lejos_del_final_igual_se_detecta(tmp_path):
    # 3 MB de líneas INFO recientes después del ERROR: ya no entra en un bloque de 256 KB.
    info = _linea("INFO", hace_min=0.5) * (3 * _MB // 60)
    ruta = _escribir(tmp_path / "web.log", 0, texto=_linea("ERROR", hace_min=2) + info)
    assert ruta.stat().st_size > 2 * _MB  # supera max_mb=1: sin la protección, se rotaría
    plan = _plan(tmp_path)
    assert plan.rotar == []
    assert [p for p, _ in plan.protegidos] == [ruta]


def test_error_viejo_no_protege(tmp_path):
    ruta = _escribir(tmp_path / "cromo_worker.log", 2, texto=_linea("ERROR", hace_min=120))
    assert _plan(tmp_path).rotar == [ruta]


def test_rotar_y_truncar_con_el_servicio_escribiendo(tmp_path):
    """El caso para el que existe todo esto: limpiar mientras el handler sigue logueando."""
    ruta = tmp_path / "svc.log"
    h = BufferedAppendFileHandler(ruta, flush_interval=60)
    h.setFormatter(logging.Formatter("%(message)s"))
    try:
        h.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "x" * (2 * _MB), None, None))
        h.flush()
        lc.aplicar(_plan(tmp_path))  # rota por renombre
        h.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "despues de rotar", None, None))
        h.flush()
        assert ruta.read_text() == "despues de rotar\n"

        lc.aplicar(_plan(tmp_path, max_mb=10, truncar=[ruta]))
        h.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "despues de truncar", None, None))
        h.flush()
        assert ruta.read_text() == "despues de truncar\n"
    finally:
        h.close()
