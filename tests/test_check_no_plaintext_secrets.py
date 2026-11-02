# Nombre de archivo: test_check_no_plaintext_secrets.py
# Ubicación de archivo: tests/test_check_no_plaintext_secrets.py
# Descripción: Pruebas de scripts/check_no_plaintext_secrets.sh contra un repo git temporal

"""`check_no_plaintext_secrets.sh` se ejecuta de verdad sobre un repo git descartable.

El script deriva la raíz del repo de su propia ubicación y usa `git grep` (sólo archivos
versionados), así que se copia a un repo temporal y cada caso se agrega al índice. Un literal
tiene que dar 1; lo que el shell resuelve al correr (`$(cat .secrets/…)`, `$VAR`, `${VAR}`, comilla
invertida), el placeholder y el marcador `# secreto-ok:` tienen que dar 0. Las claves se arman
con `{clave}` para que este archivo no dispare el chequeo sobre el repo real.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "scripts" / "check_no_plaintext_secrets.sh"

CLAVES = ["POSTGRES_PASSWORD", "SMTP_PASS", "WEB_SECRET_KEY", "LAS_FOCAS_API_KEY"]


@pytest.fixture()
def correr_chequeo(tmp_path: Path):
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCRIPT, tmp_path / "scripts" / SCRIPT.name)
    (tmp_path / "deploy").mkdir()
    for compose in ("docker-compose.dev.yml", "compose.yml"):
        (tmp_path / "deploy" / compose).write_text("services: {}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def _correr(contenido: str) -> subprocess.CompletedProcess[str]:
        (tmp_path / "caso.sh").write_text(contenido, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        return subprocess.run(
            ["bash", str(tmp_path / "scripts" / SCRIPT.name)],
            capture_output=True, text=True, check=False,
        )

    return _correr


def test_repo_sin_asignaciones_da_0(correr_chequeo) -> None:
    resultado = correr_chequeo("echo hola\n")

    assert resultado.returncode == 0, resultado.stderr


@pytest.mark.parametrize("clave", CLAVES)
@pytest.mark.parametrize(
    "plantilla",
    [
        "{clave}=hunter2\n",
        'export {clave}="hunter2"\n',
        "{clave}='hunter2' comando\n",
        'X="$(cat .secrets/x.txt)" {clave}=hunter2\n',
    ],
    ids=["sin-comillas", "comillas-dobles", "comillas-simples", "literal-junto-a-sustitucion"],
)
def test_literal_da_1(correr_chequeo, clave: str, plantilla: str) -> None:
    resultado = correr_chequeo(plantilla.format(clave=clave))

    assert resultado.returncode == 1
    assert "asignaciones sensibles" in resultado.stderr
    assert "caso.sh:1:" in resultado.stderr


def test_clave_openai_con_prefijo_sk_da_1(correr_chequeo) -> None:
    resultado = correr_chequeo("{clave}=sk-abc\n".format(clave="OPENAI_API_KEY"))

    assert resultado.returncode == 1


@pytest.mark.parametrize("clave", CLAVES)
@pytest.mark.parametrize(
    "plantilla",
    [
        '{clave}="$(cat .secrets/Dev_db_password_v1.txt)" pytest\n',
        "export {clave}=$(cat .secrets/x.txt)\n",
        '-e {clave}="$CLAVE" -e OTRA=1\n',
        "{clave}=${{CLAVE_DE_ENTORNO}}\n",
        "{clave}=$CLAVE\n",
        "{clave}=`cat .secrets/x.txt`\n",
        "La regla (`{clave}=`) ignora lo no literal.\n",
        "{clave}=cambiar_por_algo\n",
        "{clave}=\n",
        "    '{clave}=\"$(cat .secrets/x.txt)\" pytest'\n",
        '"{clave}=hunter2\\n",  # secreto-ok: valor falso del test\n',
    ],
    ids=[
        "sustitucion-entre-comillas", "sustitucion-sin-comillas", "variable-entre-comillas",
        "variable-con-llaves", "variable-sin-comillas", "sustitucion-con-backticks", "markdown-codigo",
        "placeholder", "vacio", "dentro-de-string-python",
        "marcador-secreto-ok",
    ],
)
def test_valor_no_literal_o_declarado_da_0(correr_chequeo, clave: str, plantilla: str) -> None:
    resultado = correr_chequeo(plantilla.format(clave=clave))

    assert resultado.returncode == 0, resultado.stderr

