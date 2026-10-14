# Nombre de archivo: prompt.py
# Ubicación de archivo: core/services/fo_monitor/prompt.py
# Descripción: Arma el mensaje de Slack que le pide a burritoIA el estado de última milla de una lista de servicios

"""Prompt de FO Monitor para burritoIA.

burritoIA responde en lenguaje natural; para poder comparar PRE/POST le pedimos, al final de su
respuesta, un bloque con una línea por servicio (`FOMON|id|ESTADO|extremo|motivo`) que parsea
`core/services/fo_monitor/parser.py`. Sólo cuenta la última milla (puerto de acceso / ONT) en
este momento: reclamos, historial y tráfico se ignoran a propósito (relevamiento 2026-10-14,
Q22/Q23).

El token `FOMON-Q<id>` identifica la consulta en el canal: sirve para trazabilidad y para que el
worker reconcilie, tras un reinicio, un mensaje que se publicó pero cuyo `ts` no llegó a guardarse.
"""

from __future__ import annotations

from typing import Sequence

PROMPT_VERSION = "v2"

ESTADOS_VALIDOS = ("UP", "DOWN", "ADMIN_DOWN", "DESCONOCIDO", "NO_SOPORTADO")

_BLOQUE_SALIDA = (
    "Al final de tu respuesta incluí un bloque de código con exactamente una línea por servicio, "
    "con este formato:\n"
    "FOMON|<id>|<ESTADO>|<extremo>|<motivo>\n"
    "ESTADO: UP (acceso operativo en todos los extremos), DOWN (algún extremo operativamente "
    "caído), ADMIN_DOWN (apagado administrativamente), DESCONOCIDO (no se pudo verificar), "
    "NO_SOPORTADO (tipo de servicio no soportado).\n"
    "extremo: el extremo caído (1, 2) o - si no aplica. motivo: hasta 80 caracteres, sin el "
    "carácter |."
)


def token_consulta(consulta_id: int | str) -> str:
    return f"FOMON-Q{consulta_id}"


def construir_prompt(
    burrito_user_id: str, consulta_id: int | str, servicio_ids: Sequence[str], version: str = PROMPT_VERSION
) -> str:
    """`v1` pedía "SOLO el estado de última milla" y burritoIA lo resolvió con un perfil de tráfico
    que no consulta el puerto de acceso (PoC 2026-10-14, ref #eece → DESCONOCIDO). `v2` pide el
    diagnóstico de acceso explícitamente y recorta sólo la respuesta."""
    if not servicio_ids:
        raise ValueError("servicio_ids no puede estar vacío")
    ids = ", ".join(str(s) for s in servicio_ids)
    if version == "v3":
        # v3: arranca igual que un operador humano ("verificar servicio X"), que es lo que dispara el
        # diagnóstico completo con estado de puertos; v1/v2 terminaban en el perfil "tráfico" (PoC
        # 2026-10-14, refs #eece y #ec8a). El token va al final para que no lo confunda con el id.
        verbo = "verificar servicio" if len(servicio_ids) == 1 else "verificar servicios"
        return (
            f"<@{burrito_user_id}> {verbo} {ids}\n"
            "Al final de tu respuesta agregá un bloque de código con exactamente una línea por servicio:\n"
            "FOMON|<número de servicio>|<ESTADO>|<extremo>|<motivo>\n"
            "ESTADO según el estado operativo ACTUAL de la última milla (puerto de acceso u ONT) en "
            "cada extremo: UP (operativo en todos los extremos), DOWN (algún extremo operativamente "
            "caído), ADMIN_DOWN (apagado administrativamente), DESCONOCIDO (no se pudo verificar el "
            "acceso), NO_SOPORTADO (tipo de servicio no soportado). No uses reclamos, historial ni "
            "tráfico para decidir el ESTADO.\n"
            "extremo: el extremo caído (1, 2) o -. motivo: hasta 80 caracteres, sin el carácter |.\n"
            f"(ref. interna {token_consulta(consulta_id)}, no la incluyas en el bloque)"
        )
    encabezado = f"<@{burrito_user_id}> FOMON {version} · {token_consulta(consulta_id)}\n"
    if version == "v1":
        cuerpo = (
            f"Verificá SOLO el estado operativo ACTUAL de la última milla (puerto de acceso u ONT, "
            f"estado operativo y administrativo) en cada extremo de estos servicios: {ids}.\n"
            "Ignorá reclamos, historial, disponibilidad, tráfico y saturación.\n"
        )
    else:
        cuerpo = (
            f"Verificar servicios {ids}: ejecutá el chequeo del acceso en cada extremo (estado "
            "operativo y administrativo del puerto de acceso, o estado de la ONT si es GPON) y las "
            "alarmas de red actuales.\n"
            "En la respuesta informá sólo la última milla: no incluyas reclamos, historial, "
            "disponibilidad, tráfico ni saturación.\n"
        )
    return encabezado + cuerpo + _BLOQUE_SALIDA
