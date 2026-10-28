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

from modules.slack_baneo_notifier import camara_search as cs
from modules.slack_baneo_notifier import cable_info

FIXTURES = Path(__file__).parent / "fixtures" / "normalizacion"
TAM_BLOQUE = 512

FUNCIONES_GOLDEN = {
    "limpiar_puntuacion": cs._limpiar_puntuacion,
    "normalizar": cs._normalizar,
    "expandir_abreviaturas": cs._expandir_abreviaturas,
    "aplicar_sinonimos": cs._aplicar_sinonimos,
    "expandir_abreviaturas_y_sinonimos": cs.expandir_abreviaturas_y_sinonimos,
    "normalizar_candidato": cs.normalizar_candidato,
    "limpiar_ruido_operativo": cs.limpiar_ruido_operativo,
    "preparar_nombre_busqueda": cs.preparar_nombre_busqueda,
    "quitar_botella_uno": cs.quitar_botella_uno,
    "detectar_multi_bot": cs.detectar_multi_bot,
    "separar_prefijo_empalme": cs.separar_prefijo_empalme,
    "pocos_tokens_significativos": cs._pocos_tokens_significativos,
    "re_bot_sufijo_search": lambda s: cs.RE_BOT_SUFIJO.search(s),
    "extraer_nombre_camara": cs.extraer_nombre_camara,
    "extraer_tipo_movimiento": cs.extraer_tipo_movimiento,
    "extraer_slack_user_id_autorizacion": cs.extraer_slack_user_id_autorizacion,
    "quitar_formato_slack": cable_info.quitar_formato_slack,
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
