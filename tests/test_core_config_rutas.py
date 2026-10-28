# Nombre de archivo: test_core_config_rutas.py
# Ubicación de archivo: tests/test_core_config_rutas.py
# Descripción: Rutas de datos centralizadas en core/config (UPLOADS/REPORTS/TEMPLATES_DIR) y MESES_ES único

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from core import config as cfg

REPO = Path(__file__).resolve().parents[1]
_VARS = ("UPLOADS_DIR", "REPORTS_DIR", "TEMPLATES_DIR")


def _limpiar_env(monkeypatch) -> None:
    for var in _VARS:
        monkeypatch.delenv(var, raising=False)


def test_defaults_relativos_al_repo(monkeypatch):
    _limpiar_env(monkeypatch)
    assert cfg.PROJECT_ROOT == REPO
    assert cfg.uploads_dir() == REPO / "data" / "uploads"
    assert cfg.reports_dir() == REPO / "data" / "reports"
    assert cfg.templates_dir() == REPO / "Templates"


def test_env_manda(monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "u"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "r"))
    monkeypatch.setenv("TEMPLATES_DIR", str(tmp_path / "t"))
    assert cfg.uploads_dir() == tmp_path / "u"
    assert cfg.reports_dir() == tmp_path / "r"
    assert cfg.templates_dir() == tmp_path / "t"


def test_configs_de_informes_coinciden():
    env = {k: v for k, v in os.environ.items() if k not in _VARS}
    env["PYTHONPATH"] = str(REPO)
    codigo = (
        "import json;"
        "import core.sla.config as a;"
        "import modules.informes_repetitividad.config as b;"
        "import modules.informes_sla.config as c;"
        "print(json.dumps({n: [str(m.UPLOADS_DIR), str(m.REPORTS_DIR), str(m.TEMPLATES_DIR)] for n, m in (('a', a), ('b', b), ('c', c))}));"
        "print(json.dumps([a.MESES_ES == b.MESES_ES == c.MESES_ES, type(a.MESES_ES).__name__, type(b.MESES_ES).__name__, type(c.MESES_ES).__name__]))"
    )
    res = subprocess.run(
        [sys.executable, "-c", codigo], env=env, cwd=REPO, capture_output=True, text=True, check=True
    )
    rutas, meses = (json.loads(linea) for linea in res.stdout.strip().splitlines()[-2:])
    assert rutas["a"] == rutas["b"] == rutas["c"]
    assert rutas["a"] == [
        str(REPO / "data" / "uploads"),
        str(REPO / "data" / "reports"),
        str(REPO / "Templates"),
    ]
    assert meses == [True, "list", "list", "list"]


def test_meses_es_tupla_unica():
    assert isinstance(cfg.MESES_ES, tuple)
    assert len(cfg.MESES_ES) == 12
    assert cfg.MESES_ES[0] == "enero" and cfg.MESES_ES[-1] == "diciembre"


def test_no_crea_directorios(monkeypatch, tmp_path):
    for var, sub in zip(_VARS, ("u", "r", "t")):
        monkeypatch.setenv(var, str(tmp_path / sub))
    cfg.uploads_dir()
    cfg.reports_dir()
    cfg.templates_dir()
    assert list(tmp_path.iterdir()) == []
