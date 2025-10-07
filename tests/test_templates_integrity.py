# Nombre de archivo: test_templates_integrity.py
# Ubicación de archivo: tests/test_templates_integrity.py
# Descripción: Verifica la integridad de las plantillas oficiales almacenadas en Templates/

import hashlib
from pathlib import Path

import pytest

TEMPLATES_DIR = Path("Templates")
EXPECTED_HASHES = {
    "Template_Informe_SLA.docx": "fe49e0ec088dd7bfb014826d48ab9c2d2431ca1efa840b48debb574308979ec0",
    "Plantilla_Informe_Repetitividad.docx": "468d4a4432674f4b948255db589c6975e0c9e6b88714b3e07302eaea9afc212f",
}


@pytest.mark.parametrize("filename,expected_hash", EXPECTED_HASHES.items())
def test_template_files_checksum(filename: str, expected_hash: str) -> None:
    plantilla = TEMPLATES_DIR / filename
    assert plantilla.exists(), f"La plantilla {filename} no existe en {TEMPLATES_DIR}"
    digest = hashlib.sha256(plantilla.read_bytes()).hexdigest()
    assert digest == expected_hash, (
        "El contenido de la plantilla ha cambiado. Si el cambio es intencional, "
        "actualizá EXPECTED_HASHES en tests/test_templates_integrity.py"
    )
