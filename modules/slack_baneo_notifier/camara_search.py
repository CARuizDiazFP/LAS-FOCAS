# Nombre de archivo: camara_search.py
# Ubicación de archivo: modules/slack_baneo_notifier/camara_search.py
# Descripción: Shim de re-exports de la búsqueda de cámaras por nombre (vive en core/services y core/text)

"""Shim de compatibilidad: la cascada de búsqueda vive en `core/services/camara_busqueda_nombre.py`
y la capa de texto en `core/text/` (P11). Este módulo sólo re-exporta, con los nombres históricos
(privados incluidos), para no romper a los callers del listener y de los tests."""

from __future__ import annotations

# Exportado explícitamente para reuso desde `core/services/cromo/camara_botella_busqueda.py`
# (búsqueda extendida Camara + CromoBotella): esa cascada equivalente contra `CromoBotella.nombre`
# reusa este mismo pipeline de normalización sin duplicarlo. `_limpiar_puntuacion` se agrega además
# de los 4 helpers pedidos porque es el primer paso del pipeline (limpiar puntuación → expandir
# abreviaturas → normalizar → sinónimos) — omitirlo produciría una normalización distinta a la que
# usa `buscar_camara()` internamente para el mismo input. `_filtrar_bots_secundarios` (agregado en
# la revisión del 2026-08-23) sólo toca `.nombre` vía regex — nada específico de `Camara` — así que
# también se reusa contra candidatas `CromoBotella` para evitar que "Cra Mitre 440" (sin mención de
# "bot"/"botella") empareje incorrectamente "Bot 2 Cra Mitre 440".
__all__ = [
    "_expandir_abreviaturas",
    "_aplicar_sinonimos",
    "_normalizar",
    "_filtrar_por_numeros",
    "_filtrar_bots_secundarios",
    "_filtrar_numero_de_botella",
    "tiene_gemela_critica",
    "recorte_pierde_la_botella",
    "_limpiar_puntuacion",
    "buscar_camara",
    "normalizar_candidato",
    "preparar_nombre_busqueda",
    "separar_prefijo_empalme",
    "botella_cromo_por_n_id",
    "resto_corrobora_botella",
    "camara_por_prefijo_empalme",
    "quitar_botella_uno",
    "extraer_tipo_movimiento",
    "extraer_slack_user_id_autorizacion",
    "AmbiguousSearchError",
    "NumeroNoCoincideError",
]

# La capa pura de normalización y el parseo del mensaje del Workflow viven en `core/text/` (P11). Se
# re-exportan acá con los nombres históricos (privados incluidos) para no romper a los callers; la
# cascada con DB que sigue en este módulo las usa con esos mismos alias.
from core.text.mensaje_ingreso import (  # noqa: F401
    extraer_nombre_camara,
    extraer_slack_user_id_autorizacion,
    extraer_tipo_movimiento,
)
from core.text.normalizacion import (  # noqa: F401
    ABREVIATURAS as _ABREVIATURAS,
    RE_BOT_PEGADO as _RE_BOT_PEGADO,
    RE_BOT_SUFIJO,
    RE_NUMERO_BOTELLA as _RE_NUMERO_BOTELLA,
    SINONIMOS as _SINONIMOS,
    aplicar_sinonimos as _aplicar_sinonimos,
    detectar_multi_bot,
    expandir_abreviaturas as _expandir_abreviaturas,
    expandir_abreviaturas_y_sinonimos,
    limpiar_puntuacion as _limpiar_puntuacion,
    limpiar_ruido_operativo,
    normalizar as _normalizar,
    normalizar_candidato,
    pocos_tokens_significativos as _pocos_tokens_significativos,
    preparar_nombre_busqueda,
    quitar_botella_uno,
    separar_prefijo_empalme,
    tokens_significativos as _tokens_significativos,
)
from core.services.camara_busqueda_nombre import (  # noqa: F401
    AmbiguousSearchError,
    NumeroNoCoincideError,
    botella_cromo_por_n_id,
    _buscar_camara_intento,
    _contiene_numero,
    buscar_camara,
    camara_por_prefijo_empalme,
    filtrar_bots_secundarios as _filtrar_bots_secundarios,
    filtrar_numero_de_botella as _filtrar_numero_de_botella,
    filtrar_por_numeros as _filtrar_por_numeros,
    recorte_pierde_la_botella,
    resto_corrobora_botella,
    tiene_gemela_critica,
)
