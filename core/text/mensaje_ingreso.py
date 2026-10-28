# Nombre de archivo: mensaje_ingreso.py
# Ubicación de archivo: core/text/mensaje_ingreso.py
# Descripción: Parseo puro del mensaje del Workflow de Slack de ingresos/egresos (nombre, movimiento, solicitante)

from __future__ import annotations

import re

from core.text.normalizacion import pocos_tokens_significativos

# Regex principal: campo del Workflow "*Nombre: Nodo/Camara/botella*\n[valor]"
_RE_NOMBRE_WORKFLOW = re.compile(
    r"(?i)\*?Nombre:\s*Nodo[/\\]C[aá]mara[/\\]botella\*?\n(.+?)(?:\n|$)"
)
# Fallback cuando la primera línea capturada por `_RE_NOMBRE_WORKFLOW` resulta demasiado corta/
# insuficiente (`pocos_tokens_significativos`, mismo umbral que la heurística de ambigüedad de
# `buscar_camara`): probablemente un salto de línea accidental del técnico al copiar/pegar el
# nombre — real en prod, ticket MKT 122293, 2026-09-07: campo cargado como "e:\nCra Curupayti 2951
# CF - CURUPAYTI 2964 - Capital Federal - Capital Federal". En ese caso se extiende la captura hasta
# el próximo campo en negrita ("\n*") o el fin del mensaje — `re.DOTALL` permite que `(.+?)` cruce
# los saltos de línea intermedios. No se usa como regex principal para no swallowear contenido de
# otro campo cuando la primera línea YA es un nombre válido y autosuficiente.
_RE_NOMBRE_WORKFLOW_EXTENDIDO = re.compile(
    r"(?i)\*?Nombre:\s*Nodo[/\\]C[aá]mara[/\\]botella\*?\n(.+?)(?=\n\*|\Z)",
    re.DOTALL,
)
# Primera línea residual de copy/paste antes del nombre real ("me:\nCra Acevedo 396 CF - …"): 1 a 3
# caracteres seguidos de ":". Sólo se quita en la captura extendida (la primera línea ya se juzgó
# insuficiente), nunca de un nombre de una sola línea.
_RE_PREFIJO_BASURA = re.compile(r"^\w{1,3}:\s+")
# Regex fallback: campo libre "Cámara: [valor]" o "Cámara, [valor]"
_RE_CAMPO_CAMARA = re.compile(r"(?i)c[aá]maras?\s*[,:]\s*(.+?)(?:\n|$)")

# Regex para extraer tipo de movimiento (Ingreso/Egreso)
_RE_TIPO_MOVIMIENTO_WORKFLOW = re.compile(r"(?i)\*?Ingreso o Egreso\*?\n\s*(Ingreso|Egreso)\b")
# Regex para extraer Slack user ID de la mención de persona que solicitó autorización
_RE_PERSONA_AUTORIZACION_WORKFLOW = re.compile(
    r"(?i)Persona que solicito La Autorizacion\s*\n\s*<@(U[A-Z0-9]+)"
)


def extraer_nombre_camara(mensaje: str) -> str:
    """Extrae el nombre de cámara del mensaje.

    Prioridad:
      1. Formato Workflow: ``*Nombre: Nodo/Camara/botella*\\n[valor]``
      2. Campo libre: ``Cámara: [valor]``
      3. Fallback: primera línea del mensaje.

    Si la primera línea del formato Workflow resulta insuficiente (`pocos_tokens_significativos`),
    se asume que es un salto de línea accidental del técnico al copiar/pegar y se extiende la
    captura a las líneas siguientes hasta el próximo campo (`_RE_NOMBRE_WORKFLOW_EXTENDIDO`).
    """
    match = _RE_NOMBRE_WORKFLOW.search(mensaje)
    if match:
        primera_linea = match.group(1).strip()
        if pocos_tokens_significativos(primera_linea):
            match_extendido = _RE_NOMBRE_WORKFLOW_EXTENDIDO.search(mensaje)
            if match_extendido:
                extendido = re.sub(r"\s*\n\s*", " ", match_extendido.group(1)).strip()
                # Una primera línea de basura de copy/paste ("me:", caso real 2026-09-15/17, 5 filas)
                # no es parte del nombre: sin esto "me: Cra Acevedo 396 CF" no matchea.
                return _RE_PREFIJO_BASURA.sub("", extendido)
        return primera_linea
    match = _RE_CAMPO_CAMARA.search(mensaje)
    if match:
        return match.group(1).strip()
    # Fallback: usar solo la primera línea del mensaje
    return mensaje.split("\n")[0].strip()


def extraer_tipo_movimiento(mensaje: str) -> str | None:
    """Extrae el tipo de movimiento (Ingreso o Egreso) del mensaje del Workflow.

    Retorna exactamente ``"Ingreso"`` o ``"Egreso"`` si el campo está presente, ``None`` si no.
    """
    match = _RE_TIPO_MOVIMIENTO_WORKFLOW.search(mensaje)
    if match:
        # El regex es (?i): group(1) preserva el casing tal como llegó en la fuente
        # (ej. "ingreso", "INGRESO"), NO el casing literal del patrón. Normalizar acá
        # es obligatorio porque `registrar_movimiento_ingreso` hace un chequeo de
        # string exacto contra "Ingreso" y trata cualquier otro valor como Egreso —
        # sin este .capitalize(), un "ingreso" en minúsculas del Workflow de Slack
        # se registraría silenciosamente como Egreso.
        return match.group(1).capitalize()
    return None


def extraer_slack_user_id_autorizacion(mensaje: str) -> str | None:
    """Extrae el Slack user ID de la mención de persona que solicitó la autorización.

    Retorna el ID del usuario (ej. ``U0AUB6CRE4A``) sin el nombre mostrado, ``None`` si no existe.
    """
    match = _RE_PERSONA_AUTORIZACION_WORKFLOW.search(mensaje)
    if match:
        return match.group(1)
    return None


_RE_FORMATO_SLACK = re.compile(r"[*_`~]")


def quitar_formato_slack(texto: str) -> str:
    return _RE_FORMATO_SLACK.sub("", texto)
