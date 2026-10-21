# Nombre de archivo: calidad.py
# Ubicación de archivo: scripts/agentes/calidad.py
# Descripción: Gate de calidad local (lint + tests focales) que corre `agent_worktree.py ready`

"""Gate de calidad local del tooling agéntico.

La CI de GitHub sólo corre a mano (no hay créditos de Actions), así que la red de seguridad
corre en la VM, dentro del flujo que ya usan todas las sesiones: ``ready`` ejecuta este gate
sobre lo que la rama cambió respecto de ``dev`` e ``integrate`` exige que el HEAD lo haya pasado.

El gate tiene dos pasos, ambos acotados a la rama:

1. ``ruff check`` sobre los ``.py`` cambiados, con la config versionada del worktree.
2. ``pytest`` sobre los tests focales: los tests cambiados, los ``tests/test_<módulo>*.py`` y los
   tests que importan un módulo cambiado, más el smoke de ``config/quality-gate.json``.

La suite completa queda para el despliegue productivo (ver la skill ``cierre-sesion``).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from scripts.agentes import gitops

ARCHIVO_CONFIG = Path("config") / "quality-gate.json"
DIRECTORIOS_TESTS = ("tests", "nlp_intent/tests")
LINEAS_SALIDA = 40
TIMEOUT_SEGUNDOS = 1800
PREFIJO_ROUTERS = "web/app/routers/"
ARCHIVO_COMUN_SPA = "web/app/comun.py"
ENTORNO_TESTS = {"LLM_PROVIDER": "heuristic", "TESTING": "true"}


@dataclass
class Paso:
    nombre: str
    comando: list[str] = field(default_factory=list)
    exit_code: int = 0
    duracion_s: float = 0.0
    salteado: bool = False
    motivo: str = ""
    salida: str = ""

    @property
    def ok(self) -> bool:
        return self.salteado or self.exit_code == 0


@dataclass
class ResultadoGate:
    sha: str
    base: str
    archivos: list[str]
    tests: list[str]
    pasos: list[Paso]

    @property
    def ok(self) -> bool:
        return all(paso.ok for paso in self.pasos)

    @property
    def fallido(self) -> Paso | None:
        return next((paso for paso in self.pasos if not paso.ok), None)

    def resumen(self) -> str:
        partes = []
        for paso in self.pasos:
            if paso.salteado:
                partes.append(f"{paso.nombre} salteado ({paso.motivo})")
            else:
                estado = "OK" if paso.ok else f"FALLÓ (exit {paso.exit_code})"
                partes.append(f"{paso.nombre} {estado} en {paso.duracion_s:.0f}s")
        return f"{len(self.archivos)} archivos, {len(self.tests)} tests focales: " + "; ".join(partes)

    def como_dict(self) -> dict[str, object]:
        datos = asdict(self)
        datos["ok"] = self.ok
        datos["resumen"] = self.resumen()
        return datos


# ------------------------------------------------------------------ alcance


def archivos_cambiados(ruta: Path, base: str) -> list[str]:
    """Archivos que la rama agregó o modificó respecto del merge-base con ``base``."""
    merge_base = gitops.salida(["merge-base", base, "HEAD"], ruta)
    crudo = gitops.salida(["diff", "--name-only", "--diff-filter=d", f"{merge_base}..HEAD"], ruta)
    return sorted(linea for linea in crudo.splitlines() if linea)


def _es_test(archivo: str) -> bool:
    nombre = Path(archivo).name
    return archivo.endswith(".py") and nombre.startswith("test_") and archivo.startswith(DIRECTORIOS_TESTS)


def _nombres_modulo(archivo: str) -> list[str]:
    """Rutas punteadas con las que un test puede importar ``archivo``.

    ``web/app/*.py`` se importa también como ``app.*``: así lo cargan los tests de la SPA y los
    contenedores (``web/`` es el directorio de trabajo de esa imagen).
    """
    partes = list(Path(archivo).with_suffix("").parts)
    if partes[-1] == "__init__":
        partes = partes[:-1]
    if not partes:
        return []
    nombres = [".".join(partes)]
    if partes[0] == "web" and len(partes) > 1:
        nombres.append(".".join(partes[1:]))
    return nombres


def _patrones_import(nombre: str) -> list[re.Pattern[str]]:
    padre, _, hoja = nombre.rpartition(".")
    patrones = [re.compile(rf"^\s*(?:from|import)\s+{re.escape(nombre)}\b", re.MULTILINE)]
    if padre:
        patrones.append(
            re.compile(rf"^\s*from\s+{re.escape(padre)}\s+import\s+[^\n]*\b{re.escape(hoja)}\b", re.MULTILINE)
        )
    return patrones


def _llega_por_main(archivo: str) -> bool:
    """Los routers de la SPA y ``comun.py`` se montan en ``web.app.main``: los tests no los importan."""
    return archivo.startswith(PREFIJO_ROUTERS) or archivo == ARCHIVO_COMUN_SPA


def _patrones_main() -> list[re.Pattern[str]]:
    """Imports de ``web.app.main`` (o ``app.main``) y el alias ``web_main`` que usan los tests de la SPA."""
    patrones = [pat for nombre in ("web.app.main", "app.main") for pat in _patrones_import(nombre)]
    patrones.append(re.compile(r"\bweb_main\b"))
    return patrones


def _smoke(ruta: Path) -> list[str]:
    config = ruta / ARCHIVO_CONFIG
    if not config.is_file():
        return []
    datos = json.loads(config.read_text(encoding="utf-8"))
    return [test for test in datos.get("smoke", []) if (ruta / test).is_file()]


def tests_focales(ruta: Path, archivos: list[str]) -> list[str]:
    """Tests a correr para los ``archivos`` cambiados (rutas relativas a ``ruta``)."""
    candidatos = sorted(
        str(test.relative_to(ruta))
        for directorio in DIRECTORIOS_TESTS
        if (ruta / directorio).is_dir()
        for test in (ruta / directorio).glob("test_*.py")
    )
    elegidos = {archivo for archivo in archivos if _es_test(archivo) and (ruta / archivo).is_file()}

    modulos = [archivo for archivo in archivos if archivo.endswith(".py") and not _es_test(archivo)]
    patrones = [patron for archivo in modulos for nombre in _nombres_modulo(archivo) for patron in _patrones_import(nombre)]
    if any(_llega_por_main(archivo) for archivo in modulos):
        patrones += _patrones_main()
    for archivo in modulos:
        stem = Path(archivo).stem
        elegidos.update(test for test in candidatos if Path(test).name.startswith(f"test_{stem}"))
    if patrones:
        for test in candidatos:
            if test in elegidos:
                continue
            contenido = (ruta / test).read_text(encoding="utf-8", errors="replace")
            if any(patron.search(contenido) for patron in patrones):
                elegidos.add(test)

    if archivos:
        elegidos.update(_smoke(ruta))
    return sorted(elegidos)


# ------------------------------------------------------------------- pasos


def _correr(nombre: str, comando: list[str], ruta: Path, *, entorno: dict[str, str] | None = None) -> Paso:
    inicio = time.monotonic()
    try:
        proceso = subprocess.run(
            comando,
            cwd=str(ruta),
            capture_output=True,
            text=True,
            check=False,
            timeout=TIMEOUT_SEGUNDOS,
            env={**os.environ, **(entorno or {})},
        )
        exit_code, texto = proceso.returncode, proceso.stdout + proceso.stderr
    except subprocess.TimeoutExpired as error:
        exit_code, texto = 124, f"timeout tras {TIMEOUT_SEGUNDOS}s\n{error.stdout or ''}"
    lineas = texto.strip().splitlines()[-LINEAS_SALIDA:]
    return Paso(
        nombre=nombre,
        comando=comando,
        exit_code=exit_code,
        duracion_s=round(time.monotonic() - inicio, 1),
        salida="\n".join(lineas),
    )


def paso_lint(ruta: Path, archivos: list[str]) -> Paso:
    python = [archivo for archivo in archivos if archivo.endswith(".py")]
    if not python:
        return Paso(nombre="lint", salteado=True, motivo="sin .py cambiados")
    return _correr("lint", [sys.executable, "-m", "ruff", "check", "--no-cache", *python], ruta)


def paso_tests(ruta: Path, tests: list[str]) -> Paso:
    if not tests:
        return Paso(nombre="tests", salteado=True, motivo="sin tests focales")
    comando = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests]
    return _correr("tests", comando, ruta, entorno=ENTORNO_TESTS)


def ejecutar_gate(ruta: Path, base: str) -> ResultadoGate:
    """Corre lint y tests focales sobre lo que HEAD cambió respecto de ``base``.

    Si el lint falla, los tests no se corren: el paso queda salteado con el motivo.
    """
    archivos = archivos_cambiados(ruta, base)
    tests = tests_focales(ruta, archivos)
    lint = paso_lint(ruta, archivos)
    if lint.ok:
        pruebas = paso_tests(ruta, tests)
    else:
        pruebas = Paso(nombre="tests", salteado=True, motivo="el lint falló")
    return ResultadoGate(
        sha=gitops.sha("HEAD", ruta),
        base=base,
        archivos=archivos,
        tests=tests,
        pasos=[lint, pruebas],
    )
