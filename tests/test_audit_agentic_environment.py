# Nombre de archivo: test_audit_agentic_environment.py
# Ubicación de archivo: tests/test_audit_agentic_environment.py
# Descripción: Pruebas del auditor determinista del entorno agéntico (archivos, exclusiones, mapa, frontmatter, contrato de cierre, mirrors y avisos de estado)

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from scripts import audit_agentic_environment as auditor
from scripts import generate_repository_map, sync_skill_mirrors

REPO = Path(__file__).resolve().parent.parent

SKILL_EJEMPLO = """# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agentes-comunes/skills/ejemplo/SKILL.md
# Descripción: Skill de ejemplo

---
name: ejemplo
description: "Usar para probar el auditor."
---

# Habilidad: Ejemplo
"""


@pytest.fixture()
def raiz(tmp_path: Path) -> Path:
    """Repo sintético que cumple todos los contratos."""
    for nombre in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        (tmp_path / nombre).write_text("# doc\n", encoding="utf-8")
    (tmp_path / "docs" / "superpowers").mkdir(parents=True)
    (tmp_path / "docs" / "superpowers" / "CATALOG.md").write_text("# catálogo\n", encoding="utf-8")
    for nombre in auditor.ARCHIVOS_IGNORE:
        shutil.copy(REPO / nombre, tmp_path / nombre)
    skills = tmp_path / ".agentes-comunes" / "skills"
    (skills / "ejemplo").mkdir(parents=True)
    (skills / "ejemplo" / "SKILL.md").write_text(SKILL_EJEMPLO, encoding="utf-8")
    (skills / "cierre-sesion").mkdir()
    shutil.copy(REPO / auditor.CIERRE_SESION, skills / "cierre-sesion" / "SKILL.md")
    sync_skill_mirrors.procesar(tmp_path, verificar=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "repository-map.json").write_text(
        json.dumps(
            {
                "title": "Mapa",
                "output": "docs/REPOSITORY_MAP.md",
                "max_output_bytes": 8192,
                "domains": [
                    {
                        "id": "governance",
                        "title": "Gobernanza",
                        "summary": "Reglas.",
                        "roots": ["AGENTS.md"],
                        "entrypoints": [],
                        "docs": [],
                        "tests": [],
                        "commands": [],
                        "exclusions": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    generate_repository_map.escribir(tmp_path)
    return tmp_path


def _errores(raiz: Path) -> list[str]:
    return [h for h in auditor.auditar(raiz, db=Path("/no/existe")) if h.startswith("error:")]


def test_un_entorno_sano_no_tiene_errores(raiz: Path) -> None:
    assert _errores(raiz) == []
    assert auditor.main(["--root", str(raiz)]) in (0,)


def test_falta_un_archivo_obligatorio(raiz: Path) -> None:
    (raiz / ".cursorignore").unlink()

    assert "error:missing_file:.cursorignore" in _errores(raiz)
    assert auditor.main(["--root", str(raiz)]) == 1


def test_un_ignore_sin_logs_falla(raiz: Path) -> None:
    ruta = raiz / ".aiderignore"
    ruta.write_text(ruta.read_text(encoding="utf-8").replace("Logs/\n", ""), encoding="utf-8")

    assert "error:ignore_pattern_missing:.aiderignore:Logs/" in _errores(raiz)


def test_mapa_vencido_falla(raiz: Path) -> None:
    mapa = raiz / "docs" / "REPOSITORY_MAP.md"
    mapa.write_text(mapa.read_text(encoding="utf-8") + "edición manual\n", encoding="utf-8")

    assert any(h.startswith("error:repository_map:") for h in _errores(raiz))


def test_frontmatter_con_name_distinto_al_directorio(raiz: Path) -> None:
    ruta = raiz / ".agentes-comunes/skills/ejemplo/SKILL.md"
    ruta.write_text(SKILL_EJEMPLO.replace("name: ejemplo", "name: otro"), encoding="utf-8")

    errores = _errores(raiz)
    assert any(h.startswith("error:skill_frontmatter_name:ejemplo:") for h in errores)


def test_frontmatter_sin_description(raiz: Path) -> None:
    ruta = raiz / ".agentes-comunes/skills/ejemplo/SKILL.md"
    ruta.write_text(SKILL_EJEMPLO.replace('description: "Usar para probar el auditor."\n', ""), encoding="utf-8")

    assert "error:skill_frontmatter_description:ejemplo" in _errores(raiz)


def test_cierre_sesion_con_un_trigger_ambiguo_falla(raiz: Path) -> None:
    ruta = raiz / ".agentes-comunes/skills/cierre-sesion/SKILL.md"
    texto = ruta.read_text(encoding="utf-8").replace(
        "- `Cerremos sesión`\n", "- `Cerremos sesión`\n- `terminamos la sesión`\n"
    )
    ruta.write_text(texto, encoding="utf-8")

    errores = _errores(raiz)
    assert any("cierre_sesion_triggers" in h and "terminamos la sesión" in h for h in errores)


def test_cierre_sesion_sin_pruebas_focales_falla(raiz: Path) -> None:
    ruta = raiz / ".agentes-comunes/skills/cierre-sesion/SKILL.md"
    ruta.write_text(ruta.read_text(encoding="utf-8").replace("pruebas focales", "pruebas"), encoding="utf-8")

    assert "error:cierre_sesion_contract:pruebas_focales" in _errores(raiz)


def test_drift_de_mirror_falla(raiz: Path) -> None:
    mirror = raiz / ".claude/skills/ejemplo/SKILL.md"
    mirror.write_text(mirror.read_text(encoding="utf-8") + "intruso\n", encoding="utf-8")

    assert "error:mirror_drift:.claude/skills/ejemplo/SKILL.md" in _errores(raiz)


def test_adaptador_de_gemini_demasiado_largo_falla(raiz: Path) -> None:
    adaptador = raiz / ".gemini/rules/skill-extra.md"
    adaptador.write_text("línea\n" * 40, encoding="utf-8")

    assert any(h.startswith("error:gemini_adapter_too_long:.gemini/rules/skill-extra.md") for h in _errores(raiz))


def test_triggers_cierre_lee_sólo_la_lista_de_triggers_directos() -> None:
    texto = "Los únicos\ntriggers directos son:\n\n- `/cierre-sesion`\n- `Cerrar sesión`\n\nOtro párrafo\n- `x`\n"

    assert auditor.triggers_cierre(texto) == {"/cierre-sesion", "Cerrar sesión"}


# --------------------------------------------------------- avisos de estado


def _db_estado(tmp_path: Path) -> Path:
    db = tmp_path / "agent_state.sqlite3"
    conexion = sqlite3.connect(db)
    conexion.executescript(
        """
        CREATE TABLE agentes (agent_id TEXT PRIMARY KEY, status TEXT, heartbeat_at REAL);
        CREATE TABLE leases (resource TEXT PRIMARY KEY, owner_agent_id TEXT, lease_expires_at REAL);
        INSERT INTO agentes VALUES ('vivo', 'active', 9000), ('dormido', 'active', 1), ('marcado', 'stale', 9000),
                                   ('cerrado', 'finished', 1);
        INSERT INTO leases VALUES ('db:migrations', 'dormido', 10), ('skill:x', 'vivo', 99999);
        """
    )
    conexion.commit()
    conexion.close()
    return db


def test_estado_reporta_leases_y_agentes_vencidos_como_avisos(tmp_path: Path) -> None:
    db = _db_estado(tmp_path)

    avisos = auditor.chequear_estado(db, momento=9000 + 60)

    assert avisos == [
        "warning:stale_lease:db:migrations:dormido",
        "warning:stale_agent:dormido:active",
        "warning:stale_agent:marcado:stale",
    ]


def test_los_avisos_de_estado_no_hacen_fallar_la_auditoria(raiz: Path, tmp_path: Path) -> None:
    db = _db_estado(tmp_path)

    hallazgos = auditor.auditar(raiz, db=db)

    assert any(h.startswith("warning:stale_lease:") for h in hallazgos)
    assert not any(h.startswith("error:") for h in hallazgos)


def test_el_auditor_no_escribe_la_base_de_estado(tmp_path: Path) -> None:
    db = _db_estado(tmp_path)
    antes = db.read_bytes()

    auditor.chequear_estado(db)

    assert db.read_bytes() == antes


def test_el_repositorio_real_cumple_los_contratos() -> None:
    errores = [h for h in auditor.auditar(REPO, db=Path("/no/existe")) if h.startswith("error:")]

    assert errores == []
