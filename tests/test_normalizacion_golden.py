# Nombre de archivo: test_normalizacion_golden.py
# Ubicación de archivo: tests/test_normalizacion_golden.py
# Descripción: Golden snapshot de la normalización de nombres sobre corpus real de focas_dev (P11)

"""Congela la salida de las funciones de normalización (hash por bloque de 512 entradas).

Regenerar sólo si el cambio de comportamiento es intencional:
``python scripts/golden_normalizacion.py snapshot``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from core.text import mensaje_ingreso as mi
from core.text import normalizacion as nz

FIXTURES = Path(__file__).parent / "fixtures" / "normalizacion"
TAM_BLOQUE = 512

FUNCIONES_GOLDEN = {
    "limpiar_puntuacion": nz.limpiar_puntuacion,
    "normalizar": nz.normalizar,
    "expandir_abreviaturas": nz.expandir_abreviaturas,
    "aplicar_sinonimos": nz.aplicar_sinonimos,
    "expandir_abreviaturas_y_sinonimos": nz.expandir_abreviaturas_y_sinonimos,
    "normalizar_candidato": nz.normalizar_candidato,
    "limpiar_ruido_operativo": nz.limpiar_ruido_operativo,
    "preparar_nombre_busqueda": nz.preparar_nombre_busqueda,
    "quitar_botella_uno": nz.quitar_botella_uno,
    "detectar_multi_bot": nz.detectar_multi_bot,
    "separar_prefijo_empalme": nz.separar_prefijo_empalme,
    "pocos_tokens_significativos": nz.pocos_tokens_significativos,
    "re_bot_sufijo_search": lambda s: nz.RE_BOT_SUFIJO.search(s),
    "extraer_nombre_camara": mi.extraer_nombre_camara,
    "extraer_tipo_movimiento": mi.extraer_tipo_movimiento,
    "extraer_slack_user_id_autorizacion": mi.extraer_slack_user_id_autorizacion,
    "quitar_formato_slack": mi.quitar_formato_slack,
}

# Sobre qué lista del corpus se aplica cada función.
_SOBRE_MENSAJES = {
    "extraer_nombre_camara",
    "extraer_tipo_movimiento",
    "extraer_slack_user_id_autorizacion",
    "quitar_formato_slack",
}
ENTRADA_DE = {k: ("mensajes" if k in _SOBRE_MENSAJES else "nombres") for k in FUNCIONES_GOLDEN}


def _serializar(fn, entrada: str) -> str:
    try:
        return repr(fn(entrada))
    except Exception as e:  # noqa: BLE001 — se congela también la excepción
        return f"EXC:{type(e).__name__}:{e}"


@pytest.fixture(scope="module")
def corpus() -> dict[str, list[str]]:
    with gzip.open(FIXTURES / "corpus.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("funcion", list(FUNCIONES_GOLDEN))
def test_golden_normalizacion(funcion, corpus, golden):
    fn = FUNCIONES_GOLDEN[funcion]
    entradas = corpus[ENTRADA_DE[funcion]]
    esperado = golden[funcion]
    assert len(entradas) == esperado["total"], "el corpus cambió de tamaño"
    salidas = [_serializar(fn, e) for e in entradas]
    for i, bloque in enumerate(esperado["bloques"]):
        ini = i * TAM_BLOQUE
        h = hashlib.sha256("\n".join(salidas[ini:ini + TAM_BLOQUE]).encode("utf-8")).hexdigest()
        if h != bloque:
            muestra = [(entradas[j], salidas[j]) for j in range(ini, min(ini + 3, len(entradas)))]
            pytest.fail(f"{funcion}: difiere el bloque {i}; primeras 3 entradas del bloque (entrada, salida actual): {muestra}")
