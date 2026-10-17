# Nombre de archivo: test_generate_repository_map.py
# Ubicación de archivo: tests/test_generate_repository_map.py
# Descripción: Pruebas del generador del mapa canónico del repositorio (render, metadatos, rutas, tope de bytes y --check)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import generate_repository_map as mapa


def _manifiesto(**extra: object) -> dict:
    base = {
        "title": "Mapa de prueba",
        "output": "docs/REPOSITORY_MAP.md",
        "max_output_bytes": 8192,
        "global_exclusions": [".venv/"],
        "domains": [
            {
                "id": "api",
                "title": "API",
                "summary": "Endpoints.",
                "roots": ["api/"],
                "entrypoints": ["api/main.py"],
                "docs": [],
                "tests": ["tests/test_api_*.py"],
                "commands": ["pytest tests/test_api_x.py -q"],
                "exclusions": ["api/cache/"],
            }
        ],
    }
    base.update(extra)
    return base


@pytest.fixture()
def raiz(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_api_x.py").write_text("", encoding="utf-8")
    _guardar(tmp_path, _manifiesto())
    return tmp_path


def _guardar(raiz: Path, manifiesto: dict) -> None:
    (raiz / "config" / "repository-map.json").write_text(json.dumps(manifiesto), encoding="utf-8")


def _main(raiz: Path, *args: str) -> int:
    return mapa.main([*args, "--root", str(raiz)])


def test_write_genera_el_mapa_con_metadatos(raiz: Path) -> None:
    assert _main(raiz, "--write") == 0

    texto = (raiz / "docs" / "REPOSITORY_MAP.md").read_text(encoding="utf-8")
    metadata, cuerpo = mapa.separar_metadata(texto)
    assert set(metadata) == {"source_commit", "generated_at_utc", "manifest_sha256"}
    assert "## `api` — API" in cuerpo
    assert "- Raíces: `api/`" in cuerpo
    assert "- No indexar: `api/cache/`" in cuerpo
    assert "- Docs" not in cuerpo  # campos vacíos no se imprimen


def test_check_pasa_con_el_mapa_recien_generado(raiz: Path) -> None:
    _main(raiz, "--write")

    assert _main(raiz, "--check") == 0


def test_check_falla_si_cambia_el_manifiesto(raiz: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _main(raiz, "--write")
    _guardar(raiz, _manifiesto(title="Otro título"))

    assert _main(raiz, "--check") == 1
    assert "otro manifiesto" in capsys.readouterr().err


def test_check_falla_si_el_mapa_se_edito_a_mano(raiz: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _main(raiz, "--write")
    salida = raiz / "docs" / "REPOSITORY_MAP.md"
    salida.write_text(salida.read_text(encoding="utf-8") + "línea a mano\n", encoding="utf-8")

    assert _main(raiz, "--check") == 1
    assert "difiere" in capsys.readouterr().err


def test_check_ignora_commit_y_fecha_de_generacion(raiz: Path) -> None:
    _main(raiz, "--write")
    salida = raiz / "docs" / "REPOSITORY_MAP.md"
    texto = salida.read_text(encoding="utf-8")
    metadata, cuerpo = mapa.separar_metadata(texto)
    metadata.update(source_commit="000000000000", generated_at_utc="2000-01-01T00:00:00Z")
    salida.write_text(f"<!-- repository-map: {json.dumps(metadata)} -->\n{cuerpo}", encoding="utf-8")

    assert _main(raiz, "--check") == 0


def test_rutas_inexistentes_bloquean_write_y_check(raiz: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _main(raiz, "--write")
    manifiesto = _manifiesto()
    manifiesto["domains"][0]["entrypoints"] = ["api/no_existe.py"]
    manifiesto["domains"][0]["tests"] = ["tests/test_nada_*.py"]
    _guardar(raiz, manifiesto)

    assert _main(raiz, "--write") == 1
    assert _main(raiz, "--check") == 1
    error = capsys.readouterr().err
    assert "api.entrypoints: api/no_existe.py" in error
    assert "api.tests: tests/test_nada_*.py" in error


def test_las_exclusiones_no_se_validan_contra_disco(raiz: Path) -> None:
    """Una exclusión (p. ej. node_modules) puede no existir en un worktree recién creado."""
    assert mapa.rutas_faltantes(raiz, _manifiesto()) == []


def test_write_respeta_el_tope_de_bytes(raiz: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _guardar(raiz, _manifiesto(max_output_bytes=200))

    assert _main(raiz, "--write") == 1
    assert "tope 200" in capsys.readouterr().err
    assert not (raiz / "docs" / "REPOSITORY_MAP.md").exists()


def test_manifiesto_invalido_reporta_la_clave_faltante(raiz: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifiesto = _manifiesto()
    del manifiesto["domains"][0]["commands"]
    _guardar(raiz, manifiesto)

    assert _main(raiz, "--check") == 1
    assert "'commands'" in capsys.readouterr().err


def test_el_manifiesto_real_genera_un_mapa_vigente_y_bajo_el_tope() -> None:
    """El mapa versionado del repo está al día con su manifiesto."""
    assert mapa.verificar(mapa.RAIZ) == []
