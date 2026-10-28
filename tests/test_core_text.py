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


def test_errores_son_la_misma_clase():
    from core.services import camara_busqueda_nombre

    assert camara_search.AmbiguousSearchError is camara_busqueda_nombre.AmbiguousSearchError
    assert camara_search.NumeroNoCoincideError is camara_busqueda_nombre.NumeroNoCoincideError


def test_shim_no_define_funciones():
    import inspect

    propios = [
        nombre
        for nombre, obj in vars(camara_search).items()
        if (inspect.isfunction(obj) or inspect.isclass(obj))
        and getattr(obj, "__module__", None) == "modules.slack_baneo_notifier.camara_search"
    ]
    assert propios == []


@pytest.mark.parametrize(
    "shim_mod, core_mod",
    [
        ("modules.slack_baneo_notifier.correccion_ingreso", "core.services.ingreso_correccion_comandos"),
        ("modules.slack_baneo_notifier.slack_user_resolver", "core.services.slack_usuarios"),
    ],
)
def test_shims_slack_identidad_y_sin_definiciones_propias(shim_mod, core_mod):
    import importlib
    import inspect

    shim = importlib.import_module(shim_mod)
    nuevo = importlib.import_module(core_mod)
    assert shim.__all__ == nuevo.__all__
    for nombre in nuevo.__all__:
        assert getattr(shim, nombre) is getattr(nuevo, nombre)
    propios = [
        n
        for n, obj in vars(shim).items()
        if (inspect.isfunction(obj) or inspect.isclass(obj)) and getattr(obj, "__module__", None) == shim_mod
    ]
    assert propios == []


def test_logger_slack_usuarios_conserva_nombre():
    from core.services import slack_usuarios

    assert slack_usuarios.logger.name == "slack_baneo_worker.slack_user_resolver"


def test_core_no_importa_el_worker_de_slack():
    """Invariante de P11: `core/` no depende del worker de Slack.

    Verifica dos cosas sobre `core/**/*.py`: (1) ningún import real (incluidos los perezosos
    indentados) del paquete `modules.slack_baneo_notifier`; (2) el grep literal del spec
    (`modules.slack_baneo_notifier`, donde el `.` también matchea `/`) devuelve 0.
    """
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent / "core"
    re_import = re.compile(
        r"^\s*(from\s+modules\.slack_baneo_notifier\b|import\s+modules\.slack_baneo_notifier\b)"
    )
    re_literal = re.compile(r"modules.slack_baneo_notifier")
    fallas = []
    for archivo in sorted(raiz.rglob("*.py")):
        for nro, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), start=1):
            if re_import.search(linea):
                fallas.append(f"{archivo}:{nro}: import del worker de Slack: {linea.strip()}")
            elif re_literal.search(linea):
                fallas.append(f"{archivo}:{nro}: menciona el worker de Slack: {linea.strip()}")
    assert not fallas, "core/ no debe depender del worker de Slack:\n" + "\n".join(fallas)
