# Nombre de archivo: test_office_logging_setup.py
# Ubicación de archivo: tests/test_office_logging_setup.py
# Descripción: La copia del handler de logs en office_service no debe divergir de core/logging.py

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

from core.logging import BufferedAppendFileHandler

RAIZ = Path(__file__).resolve().parents[1]


def _cargar_office_logging_setup():
    spec = importlib.util.spec_from_file_location("office_logging_setup", RAIZ / "office_service/app/logging_setup.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo  # inspect.getsource lo busca ahí
    spec.loader.exec_module(modulo)
    return modulo


def test_handler_de_office_es_copia_exacta_del_de_core():
    office = _cargar_office_logging_setup()
    assert inspect.getsource(office.BufferedAppendFileHandler) == inspect.getsource(BufferedAppendFileHandler)


def test_configurar_logging_escribe_en_logs_dir(tmp_path, monkeypatch):
    import logging

    office = _cargar_office_logging_setup()
    monkeypatch.setenv("LOGS_DIR", str(tmp_path))
    root = logging.getLogger()
    antes = list(root.handlers)
    try:
        office.configurar_logging("INFO")
        logging.getLogger("office.soffice").warning("linea de soffice")
        for h in root.handlers:
            if h not in antes:
                h.flush()
        assert "linea de soffice" in (tmp_path / "office.log").read_text()
    finally:
        for h in list(root.handlers):
            if h not in antes:
                root.removeHandler(h)
                h.close()
