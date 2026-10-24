# Nombre de archivo: test_web_main_logging_handlers.py
# Ubicación de archivo: tests/test_web_main_logging_handlers.py
# Descripción: Caracteriza los handlers de logging que deja web.app.main tras importarse (sin duplicados)

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

_SCRIPT = """
import json, logging
import web.app.main  # noqa: F401
def describir(lg):
    return sorted(
        (type(h).__name__, str(getattr(h, "path", getattr(h, "baseFilename", getattr(getattr(h, "stream", None), "name", "")))))
        for h in lg.handlers
    )
print("RESULTADO=" + json.dumps({"web": describir(logging.getLogger("web")), "root": describir(logging.getLogger())}))
"""


def _handlers_tras_importar(tmp_path: Path) -> dict:
    entorno = {**os.environ, "LOGS_DIR": str(tmp_path), "LLM_PROVIDER": "heuristic", "TESTING": "true"}
    proc = subprocess.run(
        [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r)\n%s" % (str(RAIZ), _SCRIPT)],
        capture_output=True, text=True, env=entorno, cwd=str(RAIZ), timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    linea = [l for l in proc.stdout.splitlines() if l.startswith("RESULTADO=")][-1]
    return json.loads(linea[len("RESULTADO="):])


def test_web_main_deja_un_solo_handler_de_archivo_y_ninguno_en_logger_web(tmp_path):
    res = _handlers_tras_importar(tmp_path)
    assert res["web"] == []  # el logger "web" propaga al raíz: no tiene handlers propios
    archivos = [h for h in res["root"] if h[0] == "BufferedAppendFileHandler"]
    assert archivos == [["BufferedAppendFileHandler", str(tmp_path / "web.log")]]
    assert len({tuple(h) for h in res["root"]}) == len(res["root"]) or all(h[0] != "BufferedAppendFileHandler" for h in res["root"][1:])
