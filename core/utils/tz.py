# Nombre de archivo: tz.py
# Ubicación de archivo: core/utils/tz.py
# Descripción: Utilidades de zona horaria para el proyecto LAS-FOCAS (GMT-3 / America/Argentina/Buenos_Aires)

"""Todo el proyecto usa UTC para almacenamiento interno pero GMT-3 para
cualquier texto visible al usuario: mensajes de Slack, reportes Excel,
emails y plantillas de texto.

Usar estas funciones siempre que se necesite mostrar una fecha/hora:

    from core.utils.tz import ahora_local, fmt_local, ahora_fmt, TZ_ARG

- ``ahora_local()``     → datetime actual en GMT-3 (awareness completo)
- ``fmt_local(dt)``     → convierte datetime UTC/aware a string GMT-3
- ``ahora_fmt()``       → string del momento actual en GMT-3
- ``TZ_ARG``            → ZoneInfo de referencia (America/Argentina/Buenos_Aires)

Para almacenamiento en DB / logs internos seguir usando ``datetime.now(timezone.utc)``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ_ARG = ZoneInfo("America/Argentina/Buenos_Aires")

_FMT_DEFAULT = "%d/%m/%Y %H:%M"
_SUFIJO = " (GMT-3)"


def ahora_local() -> datetime:
    """Retorna el datetime actual en zona horaria America/Argentina/Buenos_Aires."""
    return datetime.now(TZ_ARG)


def fmt_local(dt: datetime | None, fmt: str = _FMT_DEFAULT) -> str:
    """Convierte un datetime (UTC u otro aware) a string formateado en GMT-3.

    Si *dt* es None retorna "-".
    Si *dt* es naive se asume UTC antes de convertir.
    """
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_ARG).strftime(fmt) + _SUFIJO


def ahora_fmt(fmt: str = _FMT_DEFAULT) -> str:
    """Retorna el momento actual formateado en GMT-3 con sufijo '(GMT-3)'."""
    return ahora_local().strftime(fmt) + _SUFIJO
