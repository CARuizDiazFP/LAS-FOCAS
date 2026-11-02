# Nombre de archivo: test_build_base_hash.py
# Ubicación de archivo: tests/test_build_base_hash.py
# Descripción: Pruebas del hash de common-requirements.txt que decide si build_base.sh reconstruye focas-base

"""`build_base.sh --print-hash` se ejecuta de verdad, sin Docker.

El script deriva la raíz del repo de su propia ubicación, así que se copia a un directorio
temporal junto a un `common-requirements.txt` de prueba. Un cambio sólo de comentario no debe
mover el hash (P19 lo movió y habría reconstruido la base entera); un cambio de versión sí.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "scripts" / "build_base.sh"

BASE = """# Nombre de archivo: common-requirements.txt
# Descripción: dependencias comunes

# FastAPI stack
fastapi==0.136.1  # CVEs de starlette
starlette==1.3.1
git+https://example.invalid/pkg.git#egg=pkg
"""


@pytest.fixture()
def hash_de(tmp_path: Path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(SCRIPT, scripts / "build_base.sh")

    def _hash(contenido: str) -> str:
        (tmp_path / "common-requirements.txt").write_text(contenido, encoding="utf-8")
        resultado = subprocess.run(
            ["bash", str(scripts / "build_base.sh"), "--print-hash"],
            capture_output=True, text=True, check=True,
        )
        return resultado.stdout.strip()

    return _hash


def test_hash_es_sha256(hash_de) -> None:
    assert len(hash_de(BASE)) == 64


@pytest.mark.parametrize(
    "variante",
    [
        BASE.replace("# FastAPI stack", "# FastAPI stack (comentario reescrito)"),
        BASE.replace("# CVEs de starlette", "# otro motivo del pin"),
        BASE.replace("fastapi==0.136.1  # CVEs de starlette", "fastapi==0.136.1"),
        BASE + "\n\n# comentario nuevo al final\n",
        BASE.replace("starlette==1.3.1", "starlette==1.3.1   "),
    ],
    ids=["comentario-de-linea", "comentario-en-linea", "comentario-quitado", "lineas-vacias", "espacios-finales"],
)
def test_cambio_sin_paquetes_no_mueve_el_hash(hash_de, variante: str) -> None:
    assert hash_de(variante) == hash_de(BASE)


@pytest.mark.parametrize(
    "variante",
    [
        BASE.replace("starlette==1.3.1", "starlette==1.3.2"),
        BASE + "orjson==3.11.6\n",
        BASE.replace("#egg=pkg", "#egg=otro"),
    ],
    ids=["version", "paquete-nuevo", "fragmento-de-url"],
)
def test_cambio_de_paquetes_mueve_el_hash(hash_de, variante: str) -> None:
    assert hash_de(variante) != hash_de(BASE)
