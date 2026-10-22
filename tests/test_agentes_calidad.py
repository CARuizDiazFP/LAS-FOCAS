# Nombre de archivo: test_agentes_calidad.py
# Ubicación de archivo: tests/test_agentes_calidad.py
# Descripción: Pruebas del gate de calidad local (lint + tests focales) de scripts/agentes/calidad.py

"""El gate corre de verdad ``ruff`` y ``pytest`` contra repositorios Git temporales."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.agentes import calidad


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout


def _escribir(repo: Path, archivo: str, contenido: str) -> None:
    ruta = repo / archivo
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")


def _commit(repo: Path, archivos: dict[str, str], mensaje: str) -> None:
    for archivo, contenido in archivos.items():
        _escribir(repo, archivo, contenido)
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", mensaje], repo)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Repo con ``dev`` como base y una rama de trabajo encima."""
    destino = tmp_path / "repo"
    destino.mkdir()
    _git(["init", "-q", "-b", "dev"], destino)
    _git(["config", "user.email", "agente@las-focas.test"], destino)
    _git(["config", "user.name", "Agente"], destino)
    _git(["config", "commit.gpgsign", "false"], destino)
    _commit(
        destino,
        {
            "core/services/cromo/ingesta.py": "VALOR = 1\n",
            "web/app/main.py": "APP = 1\n",
            "tests/test_ingesta.py": "def test_x():\n    assert True\n",
            "tests/test_usa_ingesta.py": "from core.services.cromo.ingesta import VALOR\n\n\ndef test_y():\n    assert VALOR\n",
            "tests/test_usa_padre.py": "from core.services.cromo import ingesta\n\n\ndef test_z():\n    assert ingesta\n",
            "tests/test_usa_app.py": "from app.main import APP\n\n\ndef test_app():\n    assert APP\n",
            "tests/test_ajeno.py": "def test_ajeno():\n    assert True\n",
        },
        "chore: base",
    )
    _git(["checkout", "-q", "-b", "feat/tarea"], destino)
    return destino


# ------------------------------------------------------------------ alcance


def test_archivos_cambiados_es_relativo_al_merge_base(repo: Path) -> None:
    _commit(repo, {"core/services/cromo/ingesta.py": "VALOR = 2\n"}, "feat: cambio")
    _git(["checkout", "-q", "dev"], repo)
    _commit(repo, {"otro.py": "X = 1\n"}, "chore: dev avanza")
    _git(["checkout", "-q", "feat/tarea"], repo)

    assert calidad.archivos_cambiados(repo, "dev") == ["core/services/cromo/ingesta.py"]


def test_tests_focales_por_nombre_e_import(repo: Path) -> None:
    focales = calidad.tests_focales(repo, ["core/services/cromo/ingesta.py"])

    assert focales == ["tests/test_ingesta.py", "tests/test_usa_ingesta.py", "tests/test_usa_padre.py"]


def test_tests_focales_de_la_spa_incluyen_imports_como_app(repo: Path) -> None:
    assert calidad.tests_focales(repo, ["web/app/main.py"]) == ["tests/test_usa_app.py"]


def test_tests_focales_de_un_router_suman_los_que_importan_main(repo: Path) -> None:
    _commit(
        repo,
        {
            "web/app/routers/x.py": "X = 1\n",
            "web/app/comun.py": "C = 1\n",
            "tests/test_usa_main.py": "from web.app.main import app\n\n\ndef test_m():\n    assert app\n",
            "tests/test_alias_main.py": "import web.app.main as web_main\n\n\ndef test_a():\n    assert web_main\n",
        },
        "feat: router",
    )

    esperado = ["tests/test_alias_main.py", "tests/test_usa_app.py", "tests/test_usa_main.py"]
    assert calidad.tests_focales(repo, ["web/app/routers/x.py"]) == esperado
    assert calidad.tests_focales(repo, ["web/app/comun.py"]) == esperado
    assert "tests/test_usa_main.py" not in calidad.tests_focales(repo, ["core/services/cromo/ingesta.py"])


def test_tests_focales_incluyen_los_tests_cambiados_y_el_smoke(repo: Path) -> None:
    _escribir(repo, "config/quality-gate.json", json.dumps({"smoke": ["tests/test_ajeno.py", "tests/no_existe.py"]}))

    focales = calidad.tests_focales(repo, ["tests/test_usa_app.py", "docs/nota.md"])

    assert focales == ["tests/test_ajeno.py", "tests/test_usa_app.py"]


def test_sin_cambios_no_hay_tests_focales_ni_smoke(repo: Path) -> None:
    _escribir(repo, "config/quality-gate.json", json.dumps({"smoke": ["tests/test_ajeno.py"]}))

    assert calidad.tests_focales(repo, []) == []


# ------------------------------------------------------------------- gate


def test_gate_falla_por_lint_y_no_corre_los_tests(repo: Path) -> None:
    _commit(repo, {"core/services/cromo/ingesta.py": "import os\nVALOR = 2\n"}, "feat: import sin uso")

    resultado = calidad.ejecutar_gate(repo, "dev")

    assert not resultado.ok
    lint, tests = resultado.pasos
    assert lint.exit_code == 1 and "F401" in lint.salida
    assert tests.salteado and tests.motivo == "el lint falló"
    assert resultado.fallido is lint


def test_gate_falla_con_el_exit_code_real_de_pytest(repo: Path) -> None:
    _commit(repo, {"tests/test_ingesta.py": "def test_x():\n    assert False\n"}, "test: rompe")

    resultado = calidad.ejecutar_gate(repo, "dev")

    assert not resultado.ok
    assert resultado.fallido is not None and resultado.fallido.nombre == "tests"
    assert resultado.fallido.exit_code == 1
    assert "1 failed" in resultado.fallido.salida


def test_gate_ok_corre_lint_y_tests_focales(repo: Path) -> None:
    _commit(repo, {"core/services/cromo/ingesta.py": "VALOR = 3\n"}, "feat: cambio limpio")

    resultado = calidad.ejecutar_gate(repo, "dev")

    assert resultado.ok
    assert resultado.sha == _git(["rev-parse", "HEAD"], repo).strip()
    assert resultado.tests == ["tests/test_ingesta.py", "tests/test_usa_ingesta.py", "tests/test_usa_padre.py"]
    assert "3 tests focales" in resultado.resumen()


def test_gate_sin_python_saltea_ambos_pasos(repo: Path) -> None:
    _commit(repo, {"docs/nota.md": "# nota\n"}, "docs: nota")

    resultado = calidad.ejecutar_gate(repo, "dev")

    assert resultado.ok
    assert [paso.salteado for paso in resultado.pasos] == [True, True]
    assert resultado.como_dict()["ok"] is True


def test_gate_sin_cambios_de_frontend_no_agrega_type_check(repo: Path) -> None:
    _commit(repo, {"core/services/cromo/ingesta.py": "VALOR = 4\n"}, "feat: sólo backend")

    resultado = calidad.ejecutar_gate(repo, "dev")

    assert [paso.nombre for paso in resultado.pasos] == ["lint", "tests"]


def test_gate_con_cambios_de_frontend_corre_type_check(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calidad, "COMANDO_TYPE_CHECK", [sys.executable, "-c", "import sys; sys.exit(3)"])
    (repo / "web" / "frontend" / "node_modules").mkdir(parents=True)
    _commit(repo, {"web/frontend/src/views/Vista.vue": "<template><div /></template>\n"}, "feat: vista")

    resultado = calidad.ejecutar_gate(repo, "dev")

    tipos = resultado.pasos[-1]
    assert tipos.nombre == "type-check"
    assert not tipos.salteado
    assert tipos.exit_code == 3
    assert not resultado.ok
    assert resultado.fallido is tipos


def test_gate_con_cambios_de_frontend_sin_node_modules_saltea_con_motivo(repo: Path) -> None:
    _commit(repo, {"web/frontend/src/api/cliente.ts": "export const x = 1\n"}, "feat: api")

    resultado = calidad.ejecutar_gate(repo, "dev")

    tipos = resultado.pasos[-1]
    assert tipos.nombre == "type-check"
    assert tipos.salteado
    assert tipos.motivo == "sin node_modules (correr npm ci)"
    assert resultado.ok
    assert "type-check salteado (sin node_modules (correr npm ci))" in resultado.resumen()


# ------------------------------------------------- huecos: negativo de main, filtro de type-check, npm ausente


def test_tests_focales_de_un_router_no_incluyen_los_que_importan_main_de_la_api(repo: Path) -> None:
    _commit(
        repo,
        {
            "web/app/routers/x.py": "X = 1\n",
            "tests/test_usa_main_api.py": "from api.app.main import app\n\n\ndef test_api():\n    assert app\n",
        },
        "feat: router",
    )

    assert "tests/test_usa_main_api.py" not in calidad.tests_focales(repo, ["web/app/routers/x.py"])


def test_gate_type_check_ignora_md_bajo_src_y_ts_fuera_de_src(repo: Path) -> None:
    (repo / "web" / "frontend" / "node_modules").mkdir(parents=True)
    _commit(
        repo,
        {"web/frontend/src/README.md": "# nota\n", "web/frontend/vite.config.ts": "export default {}\n"},
        "chore: no cuentan para type-check",
    )

    resultado = calidad.ejecutar_gate(repo, "dev")

    assert [paso.nombre for paso in resultado.pasos] == ["lint", "tests"]


def test_correr_sin_el_comando_en_el_path_devuelve_paso_fallido_127(tmp_path: Path) -> None:
    paso = calidad._correr("type-check", ["comando-que-no-existe-xyz", "run"], tmp_path)

    assert not paso.ok
    assert paso.exit_code == 127
    assert paso.salida == "comando no encontrado: comando-que-no-existe-xyz"


def test_gate_con_node_modules_pero_sin_npm_falla_sin_romper(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calidad, "COMANDO_TYPE_CHECK", ["comando-que-no-existe-xyz", "run", "type-check"])
    (repo / "web" / "frontend" / "node_modules").mkdir(parents=True)
    _commit(repo, {"web/frontend/src/views/Vista.vue": "<template><div /></template>\n"}, "feat: vista")

    resultado = calidad.ejecutar_gate(repo, "dev")

    assert not resultado.ok
    assert resultado.fallido is not None and resultado.fallido.nombre == "type-check"
    assert resultado.fallido.exit_code == 127
