# Nombre de archivo: test_core_logging.py
# Ubicación de archivo: tests/test_core_logging.py
# Descripción: Pruebas del handler de archivo con buffer (borrar/truncar en uso) y de setup_logging en el logger raíz

from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

from core import logging as core_logging
from core.logging import BufferedAppendFileHandler, setup_logging


def _handler(path: Path, **kwargs) -> BufferedAppendFileHandler:
    h = BufferedAppendFileHandler(path, **kwargs)
    h.setFormatter(logging.Formatter("%(message)s"))
    return h


def _record(msg: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord("t", level, __file__, 1, msg, None, None)


def _esperar(condicion, timeout: float = 2.0) -> bool:
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.01)
    return condicion()


def test_bufferiza_y_escribe_al_vencer_el_intervalo(tmp_path):
    path = tmp_path / "svc.log"
    h = _handler(path, flush_interval=0.1)
    try:
        h.emit(_record("uno"))
        assert not path.exists()  # todavía en el buffer: el archivo no está abierto
        assert _esperar(lambda: path.exists() and path.read_text() == "uno\n")
    finally:
        h.close()


def test_error_se_escribe_de_inmediato(tmp_path):
    path = tmp_path / "svc.log"
    h = _handler(path, flush_interval=60)
    try:
        h.emit(_record("info"))
        h.emit(_record("boom", logging.ERROR))
        assert path.read_text() == "info\nboom\n"
    finally:
        h.close()


def test_capacidad_llena_fuerza_escritura(tmp_path):
    path = tmp_path / "svc.log"
    h = _handler(path, flush_interval=60, capacity=3)
    try:
        for i in range(3):
            h.emit(_record(f"l{i}"))
        assert path.read_text() == "l0\nl1\nl2\n"
    finally:
        h.close()


def test_borrar_el_archivo_en_uso_lo_recrea_en_el_siguiente_flush(tmp_path):
    path = tmp_path / "svc.log"
    h = _handler(path, flush_interval=60)
    try:
        h.emit(_record("antes"))
        h.flush()
        path.unlink()  # como `rm Logs/svc.log` con el servicio corriendo
        h.emit(_record("despues"))
        h.flush()
        assert path.read_text() == "despues\n"
    finally:
        h.close()


def test_truncar_en_uso_no_deja_huecos(tmp_path):
    path = tmp_path / "svc.log"
    h = _handler(path, flush_interval=60)
    try:
        h.emit(_record("x" * 100))
        h.flush()
        path.write_text("")  # `truncate -s 0`
        h.emit(_record("nuevo"))
        h.flush()
        assert path.read_bytes() == b"nuevo\n"  # sin bytes nulos: el handler no guarda offset
    finally:
        h.close()


def test_rotar_por_renombre_en_uso_sigue_escribiendo_en_la_ruta(tmp_path):
    path = tmp_path / "svc.log"
    h = _handler(path, flush_interval=60)
    try:
        h.emit(_record("viejo"))
        h.flush()
        path.rename(tmp_path / "svc.log.20260930-120000")
        h.emit(_record("nuevo"))
        h.flush()
        assert path.read_text() == "nuevo\n"
        assert (tmp_path / "svc.log.20260930-120000").read_text() == "viejo\n"
    finally:
        h.close()


def test_directorio_borrado_se_recrea(tmp_path):
    path = tmp_path / "sub" / "svc.log"
    h = _handler(path, flush_interval=60)
    try:
        h.emit(_record("ok"))
        h.flush()
        assert path.read_text() == "ok\n"
    finally:
        h.close()


def test_close_vuelca_lo_pendiente(tmp_path):
    path = tmp_path / "svc.log"
    h = _handler(path, flush_interval=60)
    h.emit(_record("pendiente"))
    h.close()
    assert path.read_text() == "pendiente\n"


@pytest.fixture
def root_limpio():
    """Aísla el logger raíz y los de uvicorn: en la suite completa, módulos importados antes (p.ej.
    `web/app/main.py`) ya colgaron su handler de archivo, y `setup_logging` reutiliza el existente."""
    nombres = ("", *core_logging._LOGGERS_SIN_PROPAGACION)
    guardados = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).propagate) for n in nombres}
    for n in nombres:
        lg = logging.getLogger(n)
        for h in list(lg.handlers):
            if isinstance(h, BufferedAppendFileHandler):
                lg.removeHandler(h)
    # Como los deja uvicorn CLI (`uvicorn app.main:app`) antes de importar la app.
    logging.getLogger("uvicorn").propagate = False
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("uvicorn.error").propagate = True
    yield
    for n, (handlers, propagate) in guardados.items():
        lg = logging.getLogger(n)
        for h in list(lg.handlers):
            if h not in handlers:
                lg.removeHandler(h)
                if n == "":
                    h.close()
        for h in handlers:
            if h not in lg.handlers:
                lg.addHandler(h)
        lg.propagate = propagate


def _handlers_de_archivo(logger: logging.Logger) -> list[BufferedAppendFileHandler]:
    return [h for h in logger.handlers if isinstance(h, BufferedAppendFileHandler)]


def test_setup_logging_captura_loggers_de_cualquier_modulo(tmp_path, root_limpio):
    setup_logging("svc", enable_file=True, logs_dir=tmp_path)
    logging.getLogger("modules.algo.worker").error("desde un modulo")
    logging.getLogger("uvicorn.access").warning("GET /health 200")
    for h in _handlers_de_archivo(logging.getLogger()):
        h.flush()
    contenido = (tmp_path / "svc.log").read_text()
    assert "service=modules.algo.worker" in contenido and "desde un modulo" in contenido
    assert "GET /health 200" in contenido


def test_setup_logging_dos_veces_no_duplica_handlers(tmp_path, root_limpio):
    setup_logging("svc", enable_file=True, logs_dir=tmp_path)
    setup_logging("svc", enable_file=True, logs_dir=tmp_path)
    assert len(_handlers_de_archivo(logging.getLogger())) == 1
    assert len(_handlers_de_archivo(logging.getLogger("uvicorn.access"))) == 1


def test_logs_dir_por_defecto_es_logs_del_repo(monkeypatch):
    monkeypatch.delenv("LOGS_DIR", raising=False)
    assert core_logging._logs_dir_por_defecto() == Path(core_logging.__file__).resolve().parents[1] / "Logs"
    monkeypatch.setenv("LOGS_DIR", "/app/Logs")
    assert core_logging._logs_dir_por_defecto() == Path("/app/Logs")


def test_uvicorn_error_no_duplica_porque_propaga_a_uvicorn(tmp_path, root_limpio):
    setup_logging("svc", enable_file=True, logs_dir=tmp_path)
    assert _handlers_de_archivo(logging.getLogger("uvicorn.error")) == []
    logging.getLogger("uvicorn.error").warning("una sola vez")
    for h in _handlers_de_archivo(logging.getLogger()):
        h.flush()
    assert (tmp_path / "svc.log").read_text().count("una sola vez") == 1


def test_uvicorn_con_log_config_none_propaga_y_no_se_cuelga(tmp_path, root_limpio):
    for nombre in core_logging._LOGGERS_SIN_PROPAGACION:
        logging.getLogger(nombre).propagate = True
    setup_logging("svc", enable_file=True, logs_dir=tmp_path)
    logging.getLogger("uvicorn.access").warning("GET / 200")
    for h in _handlers_de_archivo(logging.getLogger()):
        h.flush()
    assert (tmp_path / "svc.log").read_text().count("GET / 200") == 1
