# Nombre de archivo: test_core_text.py
# Ubicación de archivo: tests/test_core_text.py
# Descripción: Tests de core/text: el shim de camara_search/cable_info re-exporta los mismos objetos (P11)

from __future__ import annotations

import sys

import pytest

from core.text import mensaje_ingreso, normalizacion
from modules.slack_baneo_notifier import cable_info, camara_search

# nombre viejo del shim -> (módulo nuevo, nombre público)
_MOVIDOS = {
    "_expandir_abreviaturas": (normalizacion, "expandir_abreviaturas"),
    "_aplicar_sinonimos": (normalizacion, "aplicar_sinonimos"),
    "_normalizar": (normalizacion, "normalizar"),
    "_limpiar_puntuacion": (normalizacion, "limpiar_puntuacion"),
    "_pocos_tokens_significativos": (normalizacion, "pocos_tokens_significativos"),
    "_tokens_significativos": (normalizacion, "tokens_significativos"),
    "_RE_BOT_PEGADO": (normalizacion, "RE_BOT_PEGADO"),
    "_RE_NUMERO_BOTELLA": (normalizacion, "RE_NUMERO_BOTELLA"),
    "_ABREVIATURAS": (normalizacion, "ABREVIATURAS"),
    "_SINONIMOS": (normalizacion, "SINONIMOS"),
    "RE_BOT_SUFIJO": (normalizacion, "RE_BOT_SUFIJO"),
    "normalizar_candidato": (normalizacion, "normalizar_candidato"),
    "preparar_nombre_busqueda": (normalizacion, "preparar_nombre_busqueda"),
    "separar_prefijo_empalme": (normalizacion, "separar_prefijo_empalme"),
    "quitar_botella_uno": (normalizacion, "quitar_botella_uno"),
    "limpiar_ruido_operativo": (normalizacion, "limpiar_ruido_operativo"),
    "detectar_multi_bot": (normalizacion, "detectar_multi_bot"),
    "expandir_abreviaturas_y_sinonimos": (normalizacion, "expandir_abreviaturas_y_sinonimos"),
    "extraer_nombre_camara": (mensaje_ingreso, "extraer_nombre_camara"),
    "extraer_tipo_movimiento": (mensaje_ingreso, "extraer_tipo_movimiento"),
    "extraer_slack_user_id_autorizacion": (mensaje_ingreso, "extraer_slack_user_id_autorizacion"),
}


@pytest.mark.parametrize("viejo", list(_MOVIDOS))
def test_shim_reexporta_mismos_objetos(viejo):
    modulo, publico = _MOVIDOS[viejo]
    assert getattr(camara_search, viejo) is getattr(modulo, publico)


def test_shim_all_de_esta_capa_resuelve():
    for nombre in camara_search.__all__:
        assert hasattr(camara_search, nombre)


def test_quitar_formato_slack_reexportada():
    assert cable_info.quitar_formato_slack is mensaje_ingreso.quitar_formato_slack


def test_normalizar_sin_unidecode(monkeypatch):
    monkeypatch.setitem(sys.modules, "unidecode", None)
    assert normalizacion.normalizar("Cámara  X") == "cámara x"
