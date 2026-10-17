# Nombre de archivo: test_sync_skill_mirrors.py
# Ubicación de archivo: tests/test_sync_skill_mirrors.py
# Descripción: Pruebas del propagador de skills a los mirrors por plataforma (transformaciones, adaptadores livianos de Gemini, mirror .agents, preservación de frontmatter, drift e idempotencia)

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sync_skill_mirrors import (
    MAX_LINEAS_ADAPTADOR,
    PLATAFORMAS,
    frontmatter_de,
    lista_frontmatter,
    partes_fuente,
    procesar,
    render,
    transformar,
)

FUENTE_EJEMPLO = """# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agentes-comunes/skills/ejemplo/SKILL.md
# Descripción: Skill de ejemplo para las pruebas

---
name: ejemplo
description: "Usar para probar el propagador."
argument-hint: "contexto"
---

# Habilidad: Ejemplo

Cuerpo con espacios al final.\x20\x20
Y una referencia a [docker-rebuild](../docker-rebuild/SKILL.md) que debe reescribirse.
Detalle en [recetas](./references/recetas.md).

## Guardrails

1. Nada destructivo.
"""


def _plataforma(clave: str):
    return next(p for p in PLATAFORMAS if p.clave == clave)


@pytest.fixture()
def raiz(tmp_path: Path) -> Path:
    destino = tmp_path / ".agentes-comunes" / "skills" / "ejemplo"
    destino.mkdir(parents=True)
    (destino / "SKILL.md").write_text(FUENTE_EJEMPLO, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------- parsing


def test_partes_fuente_separa_descripcion_frontmatter_y_cuerpo(raiz: Path) -> None:
    descripcion, frontmatter, cuerpo = partes_fuente(
        raiz / ".agentes-comunes/skills/ejemplo/SKILL.md"
    )

    assert descripcion == "Skill de ejemplo para las pruebas"
    assert 'name: ejemplo' in frontmatter
    assert cuerpo.startswith("# Habilidad: Ejemplo")
    assert "name: ejemplo" not in cuerpo


def test_partes_fuente_no_corta_el_cuerpo_en_una_regla_horizontal(tmp_path: Path) -> None:
    """Varias skills usan `---` como separador visual dentro del cuerpo."""
    ruta = tmp_path / "SKILL.md"
    ruta.write_text(
        FUENTE_EJEMPLO + "\n---\n\n## Sección posterior al separador\n\nTexto final.\n",
        encoding="utf-8",
    )

    _, _, cuerpo = partes_fuente(ruta)

    assert "## Sección posterior al separador" in cuerpo
    assert "Texto final." in cuerpo


# ----------------------------------------------------------- transformaciones


def test_transformar_reescribe_los_enlaces_segun_la_plataforma() -> None:
    cuerpo = "ver [docker-rebuild](../docker-rebuild/SKILL.md) para el detalle"

    assert "](../docker-rebuild/SKILL.md)" in transformar(cuerpo, _plataforma("claude"))
    assert "](skill-docker-rebuild.md)" in transformar(cuerpo, _plataforma("gemini"))
    assert "](../las-focas-docker-rebuild/SKILL.md)" in transformar(cuerpo, _plataforma("codex"))


def test_transformar_quita_espacios_al_final_de_linea() -> None:
    resultado = transformar("linea con espacios   \notra\t\n", _plataforma("gemini"))

    assert resultado == "linea con espacios\notra"


def test_transformar_no_toca_rutas_que_no_son_enlaces() -> None:
    cuerpo = "la fuente vive en `.agentes-comunes/skills/docker-rebuild/SKILL.md`"

    assert transformar(cuerpo, _plataforma("gemini")) == cuerpo


# ------------------------------------------------------------------- render


def test_render_apunta_el_encabezado_a_la_ubicacion_real_del_mirror(raiz: Path) -> None:
    fuente = raiz / ".agentes-comunes/skills/ejemplo/SKILL.md"

    contenido = render(_plataforma("claude"), "ejemplo", fuente)

    assert "# Ubicación de archivo: .claude/skills/ejemplo/SKILL.md" in contenido
    assert "mirror de .agentes-comunes/skills/ejemplo/SKILL.md" in contenido


def test_render_preserva_triggers_y_globs_en_el_adaptador_de_gemini(raiz: Path, monkeypatch) -> None:
    """Cada plataforma tiene sus propios triggers/globs; el cuerpo ya no se copia a Gemini."""
    monkeypatch.chdir(raiz)
    mirror = raiz / ".gemini/rules/skill-ejemplo.md"
    mirror.parent.mkdir(parents=True)
    mirror.write_text(
        '# Nombre de archivo: skill-ejemplo.md\n'
        '# Ubicación de archivo: .gemini/rules/skill-ejemplo.md\n'
        '# Descripción: vieja\n'
        '---\nname: "skill-ejemplo"\ntriggers:\n  - "disparador-propio-de-gemini"\n---\n\n'
        "# Habilidad: Ejemplo\n\ncontenido viejo\n",
        encoding="utf-8",
    )

    contenido = render(_plataforma("gemini"), "ejemplo", raiz / ".agentes-comunes/skills/ejemplo/SKILL.md")

    assert "disparador-propio-de-gemini" in contenido
    assert "contenido viejo" not in contenido
    assert "Cuerpo con espacios al final." not in contenido
    assert "Usar para probar el propagador." in contenido  # description sale de la fuente
    assert "`.agentes-comunes/skills/ejemplo/SKILL.md`" in contenido
    assert len(contenido.splitlines()) <= MAX_LINEAS_ADAPTADOR


def test_el_adaptador_de_gemini_es_estable_al_regenerarse(raiz: Path) -> None:
    """El adaptador usa listas en estilo flujo y se vuelve a leer igual (idempotencia)."""
    procesar(raiz, verificar=False)
    mirror = raiz / ".gemini/rules/skill-ejemplo.md"
    primero = mirror.read_text(encoding="utf-8")

    procesar(raiz, verificar=False)

    assert mirror.read_text(encoding="utf-8") == primero
    assert lista_frontmatter(frontmatter_de(mirror) or "", "triggers") == ["ejemplo"]


def test_lista_frontmatter_lee_bloque_y_flujo() -> None:
    bloque = 'name: "x"\ntriggers:\n  - "a"\n  - b\nglobs:\n  - "**/*"\n'
    flujo = 'triggers: ["a", "b"]\nglobs: ["**/*"]'

    assert lista_frontmatter(bloque, "triggers") == ["a", "b"]
    assert lista_frontmatter(flujo, "triggers") == ["a", "b"]
    assert lista_frontmatter(flujo, "commands") == []


def test_render_agents_lleva_frontmatter_primero_y_references_a_la_fuente(raiz: Path) -> None:
    contenido = render(
        _plataforma("agents"), "ejemplo", raiz / ".agentes-comunes/skills/ejemplo/SKILL.md", raiz
    )

    assert contenido.startswith("---\nname: ejemplo\n")
    assert "Cuerpo con espacios al final." in contenido
    assert "](../docker-rebuild/SKILL.md)" in contenido
    assert "](../../../.agentes-comunes/skills/ejemplo/references/recetas.md)" in contenido


def test_render_genera_frontmatter_si_el_mirror_no_existe(raiz: Path, monkeypatch) -> None:
    monkeypatch.chdir(raiz)

    gemini = render(_plataforma("gemini"), "ejemplo", raiz / ".agentes-comunes/skills/ejemplo/SKILL.md")
    assert 'triggers: ["ejemplo"]' in gemini
    codex = render(_plataforma("codex"), "ejemplo", raiz / ".agentes-comunes/skills/ejemplo/SKILL.md")

    assert 'name: "skill-ejemplo"' in gemini
    assert 'name: "las-focas-ejemplo"' in codex
    assert "Usar para probar el propagador." in gemini
    # Codex lleva el frontmatter antes del encabezado de archivo.
    assert codex.startswith("---\n")


# ---------------------------------------------------------------- propagación


def test_procesar_crea_los_cuatro_mirrors(raiz: Path) -> None:
    diferencias = procesar(raiz, verificar=False)

    assert len(diferencias) == 4
    assert (raiz / ".agents/skills/ejemplo/SKILL.md").is_file()
    assert (raiz / ".claude/skills/ejemplo/SKILL.md").is_file()
    assert (raiz / ".gemini/rules/skill-ejemplo.md").is_file()
    assert (raiz / ".codex-skills/skills/las-focas-ejemplo/SKILL.md").is_file()


def test_procesar_es_idempotente(raiz: Path) -> None:
    procesar(raiz, verificar=False)

    assert procesar(raiz, verificar=False) == []
    assert procesar(raiz, verificar=True) == []


def test_procesar_en_modo_check_no_escribe(raiz: Path) -> None:
    diferencias = procesar(raiz, verificar=True)

    assert len(diferencias) == 4
    assert not (raiz / ".claude/skills/ejemplo/SKILL.md").exists()


def test_procesar_detecta_un_mirror_editado_a_mano(raiz: Path) -> None:
    procesar(raiz, verificar=False)
    mirror = raiz / ".gemini/rules/skill-ejemplo.md"
    mirror.write_text(mirror.read_text(encoding="utf-8") + "\nlínea intrusa\n", encoding="utf-8")

    diferencias = procesar(raiz, verificar=True)

    assert diferencias == [".gemini/rules/skill-ejemplo.md"]


def test_procesar_propaga_un_cambio_de_la_fuente(raiz: Path) -> None:
    procesar(raiz, verificar=False)
    fuente = raiz / ".agentes-comunes/skills/ejemplo/SKILL.md"
    fuente.write_text(
        fuente.read_text(encoding="utf-8") + "\n2. Guardrail nuevo de la fuente.\n", encoding="utf-8"
    )

    procesar(raiz, verificar=False)

    for mirror in (
        raiz / ".claude/skills/ejemplo/SKILL.md",
        raiz / ".agents/skills/ejemplo/SKILL.md",
        raiz / ".codex-skills/skills/las-focas-ejemplo/SKILL.md",
    ):
        assert "Guardrail nuevo de la fuente." in mirror.read_text(encoding="utf-8")
    # Gemini sólo apunta a la fuente: el cambio llega sin tocar el adaptador.
    assert "Guardrail nuevo" not in (raiz / ".gemini/rules/skill-ejemplo.md").read_text(encoding="utf-8")


def test_procesar_acota_a_una_skill(raiz: Path) -> None:
    otra = raiz / ".agentes-comunes" / "skills" / "otra"
    otra.mkdir(parents=True)
    (otra / "SKILL.md").write_text(
        FUENTE_EJEMPLO.replace("ejemplo", "otra"), encoding="utf-8"
    )

    procesar(raiz, verificar=False, filtro="otra")

    assert (raiz / ".claude/skills/otra/SKILL.md").is_file()
    assert not (raiz / ".claude/skills/ejemplo/SKILL.md").exists()


def test_frontmatter_de_devuelve_none_si_no_existe_el_archivo(tmp_path: Path) -> None:
    assert frontmatter_de(tmp_path / "no-existe.md") is None
