# Nombre de archivo: inconsistencias_reporte.py
# Ubicación de archivo: core/services/cromo/inconsistencias_reporte.py
# Descripción: Reporte XLSX (una hoja por localidad) de las inconsistencias de Cromo para corregirlas
# en origen, y aviso best-effort de casos nuevos (WebSocket admin + Slack con el XLSX adjunto)

"""Reporte "para corregir en Cromo" y aviso de casos nuevos del detector de inconsistencias.

- `que_falta`: texto humano de lo que hay que arreglar en Cromo, derivado del tipo y la evidencia.
- `generar_xlsx`: una hoja por localidad (sin localidad → "Sin localidad"); nombres de hoja
  saneados para Excel (<= 31 caracteres, sin `[]:*?/\\`, únicos).
- `avisar_casos_nuevos`: se llama al terminar una detección aplicada. Sin casos nuevos no hace nada.
  Con casos nuevos publica SIEMPRE en el WebSocket admin (`cromo_inconsistencias_nuevas`) y, sólo si
  la fila "Cromo Inconsistencias" de `app.config_servicios` está activa y con canales, manda el
  mensaje a Slack con el XLSX de los casos nuevos. Es best-effort: loguea y nunca levanta, para no
  hacer fallar la detección.

Guardas contra el aviso masivo: si no había ningún caso antes de la corrida (primera detección) a
Slack sólo va el resumen con los conteos, sin adjunto; si no, el XLSX se corta en
`CROMO_INCONSISTENCIAS_MAX_FILAS_AVISO` filas (default 500) con una hoja "Aviso" ("y N más").
El canal y el interruptor se editan desde el viewer (`/aviso-slack`, admin + CSRF).

El `cromo_worker` necesita `slack_sdk` y el secret `slack_bot_token_v1` para el envío a Slack (se
agregaron a su requirements y a ambos compose); si faltan, el aviso a Slack se omite con un warning.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

NOMBRE_SERVICIO_CONFIG = "Cromo Inconsistencias"
TIPO_AVISO_WS = "cromo_inconsistencias_nuevas"
# Lo que hay que corregir: no incluye lo ya cerrado (CORREGIDA) ni lo aceptado a conciencia.
ESTADOS_REPORTE: tuple[str, ...] = ("PENDIENTE", "CUARENTENA", "REPORTADA")
HOJA_SIN_LOCALIDAD = "Sin localidad"
COLUMNAS: tuple[str, ...] = (
    "Tipo",
    "Revisión",
    "Estado",
    "Objeto",
    "ID Cromo",
    "Localidad",
    "Qué falta",
    "Servicios afectados",
    "Primera vez",
    "Última vez",
)
_TIPO_LABELS = {
    "ISLA_FUSION": "Isla de fusión",
    "CABLE_SIN_EXTREMO": "Cable sin extremo",
    "ELEMENTO_ISLA": "Elemento isla",
}
_REVISION_LABELS = {"AUTO": "Automática", "MANUAL": "Manual"}
_MAX_HOJA = 31
_INVALIDOS_HOJA = re.compile(r"[\[\]:*?/\\]")
_PAGINA = 500
MAX_FILAS_AVISO_DEFAULT = 500
_MAX_SERVICIOS_EVIDENCIA = 20  # tope con que el detector guarda `evidencia.servicios`
_MAX_CANALES_CHARS = 512


def que_falta(tipo: str, evidencia: Optional[Mapping[str, Any]]) -> str:
    """Texto humano de lo que hay que corregir en Cromo para este caso."""
    ev = evidencia or {}
    if tipo == "CABLE_SIN_EXTREMO":
        cable = ev.get("cable") or {}
        sin_a = cable.get("extremo_a") in (None, 0)
        sin_b = cable.get("extremo_b") in (None, 0)
        if sin_a and sin_b:
            return "El cable no tiene extremo A ni extremo B en Cromo"
        if sin_a:
            return "El cable no tiene extremo A en Cromo"
        if sin_b:
            return "El cable no tiene extremo B en Cromo"
        return "El cable tiene un extremo sin definir en Cromo"
    if tipo == "ISLA_FUSION":
        dentro_odf = bool((ev.get("contenedor") or {}).get("es_odf"))
        base = "Fusión aislada: ningún pelo continúa"
        return f"{base} (dentro de un ODF)" if dentro_odf else base
    if tipo == "ELEMENTO_ISLA":
        return "Elemento sin continuidad en sus cables"
    return "Inconsistencia sin descripción"


def nombre_hoja(localidad: Optional[str], usadas: set[str]) -> str:
    """Nombre de hoja válido en Excel y único (comparación sin distinguir mayúsculas).

    Registra el nombre elegido en `usadas`."""
    base = _INVALIDOS_HOJA.sub(" ", (localidad or "").strip())
    base = re.sub(r"\s+", " ", base).strip().strip("'").strip()
    if not base:
        base = HOJA_SIN_LOCALIDAD
    base = base[:_MAX_HOJA].strip().strip("'").strip() or HOJA_SIN_LOCALIDAD
    candidato = base
    n = 2
    while candidato.lower() in usadas:
        sufijo = f" ({n})"
        candidato = base[: _MAX_HOJA - len(sufijo)].rstrip() + sufijo
        n += 1
    usadas.add(candidato.lower())
    return candidato


def _fecha(valor: Any) -> str:
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d %H:%M")
    return str(valor) if valor else ""


def fila_reporte(item: Mapping[str, Any]) -> dict[str, Any]:
    """Una fila del reporte desde un caso (tal como lo devuelve `listar`)."""
    evidencia = item.get("evidencia") or {}
    servicios = [str(s) for s in (evidencia.get("servicios") or [])]
    # La evidencia guarda a lo sumo 20: si hay más se marca para que no parezca la lista completa.
    total = item.get("servicios")
    if isinstance(total, int) and total > len(servicios):
        parcial = f" (+{total - len(servicios)})"
    elif len(servicios) >= _MAX_SERVICIOS_EVIDENCIA:
        parcial = f" (≥{_MAX_SERVICIOS_EVIDENCIA}, puede haber más)"
    else:
        parcial = ""
    return {
        "Tipo": _TIPO_LABELS.get(item.get("tipo"), item.get("tipo")),
        "Revisión": _REVISION_LABELS.get(item.get("revision"), item.get("revision")),
        "Estado": item.get("estado"),
        "Objeto": item.get("nombre") or "",
        "ID Cromo": item.get("objeto_n_id"),
        "Localidad": item.get("localidad") or "",
        "Qué falta": que_falta(str(item.get("tipo")), evidencia),
        "Servicios afectados": ", ".join(servicios) + parcial,
        "Primera vez": _fecha(item.get("primera_vez")),
        "Última vez": _fecha(item.get("ultima_vez")),
        "_localidad": item.get("localidad"),
    }


def generar_xlsx(filas: Iterable[Mapping[str, Any]], nota: Optional[str] = None) -> bytes:
    """XLSX con una hoja por localidad. Sin filas, una hoja vacía con los encabezados. Con `nota`
    agrega una última hoja "Aviso" con ese texto (p.ej. "y N más — ver el viewer")."""
    import pandas as pd

    por_localidad: dict[str, list[Mapping[str, Any]]] = {}
    for fila in filas:
        por_localidad.setdefault((fila.get("_localidad") or "").strip(), []).append(fila)
    salida = io.BytesIO()
    usadas: set[str] = set()
    with pd.ExcelWriter(salida, engine="openpyxl") as writer:
        if not por_localidad:
            pd.DataFrame(columns=list(COLUMNAS)).to_excel(
                writer, sheet_name=nombre_hoja(None, usadas), index=False
            )
        for localidad in sorted(por_localidad, key=lambda x: (x == "", x.lower())):
            df = pd.DataFrame(
                [{c: f.get(c) for c in COLUMNAS} for f in por_localidad[localidad]],
                columns=list(COLUMNAS),
            )
            df.to_excel(writer, sheet_name=nombre_hoja(localidad, usadas), index=False)
        if nota:
            pd.DataFrame({"Aviso": [nota]}).to_excel(
                writer, sheet_name=nombre_hoja("Aviso", usadas), index=False
            )
    return salida.getvalue()


async def filas_reporte(
    sesion: AsyncSession,
    *,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    revision: Optional[str] = None,
    localidad: Optional[str] = None,
    servicio: Optional[str] = None,
    servicio_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Todos los casos que cumplen los filtros de `listar` (paginando). Sin `estado`, sólo los
    estados accionables (`ESTADOS_REPORTE`)."""
    from core.services.cromo import inconsistencias_cromo as inc

    filas: list[dict[str, Any]] = []
    desde = 0
    while True:
        pagina = await inc.listar(
            sesion,
            tipo=tipo,
            estado=estado,
            estados=None if estado else ESTADOS_REPORTE,
            revision=revision,
            localidad=localidad,
            servicio=servicio,
            servicio_id=servicio_id,
            por_pagina=_PAGINA,
            desplazamiento=desde,
        )
        items = pagina["items"]
        filas.extend(fila_reporte(i) for i in items)
        desde += len(items)
        if not items or desde >= pagina["total"]:
            return filas


async def filas_de_casos(
    sesion: AsyncSession, claves: Sequence[tuple[str, int]]
) -> list[dict[str, Any]]:
    """Filas del reporte de casos puntuales, por `(tipo, objeto_n_id)` (los nuevos de una corrida)."""
    if not claves:
        return []
    resultado = (
        await sesion.execute(
            text(
                "SELECT i.tipo, i.objeto_n_id, i.nombre, i.localidad, i.revision, i.estado, "
                "i.evidencia, i.primera_vez, i.ultima_vez "
                "FROM app.cromo_inconsistencia i "
                "JOIN unnest(CAST(:tipos AS text[]), CAST(:objetos AS bigint[])) AS k(tipo, objeto) "
                "ON k.tipo = i.tipo AND k.objeto = i.objeto_n_id "
                "ORDER BY i.localidad NULLS LAST, i.tipo, i.nombre"
            ),
            {"tipos": [c[0] for c in claves], "objetos": [int(c[1]) for c in claves]},
        )
    ).mappings().all()
    return [fila_reporte(dict(r)) for r in resultado]


# ── Aviso de casos nuevos ────────────────────────────────────────────────────


async def _publicar_ws(payload: Mapping[str, Any]) -> None:
    from core.cache.redis_client import get_redis
    from core.services.botella_recompute_queue import ADMIN_NOTIFICATIONS_CHANNEL

    await get_redis().publish(ADMIN_NOTIFICATIONS_CHANNEL, json.dumps(payload))


async def _leer_config_slack(sesion: AsyncSession) -> tuple[list[str], bool]:
    """(canales, activo) de la fila "Cromo Inconsistencias"; sin fila → ([], False)."""
    fila = (
        await sesion.execute(
            text(
                "SELECT slack_channels, activo FROM app.config_servicios "
                "WHERE nombre_servicio = :nombre"
            ),
            {"nombre": NOMBRE_SERVICIO_CONFIG},
        )
    ).first()
    if fila is None:
        return [], False
    canales = [c.strip() for c in (fila[0] or "").split(",") if c.strip()]
    return canales, bool(fila[1])


def max_filas_aviso() -> int:
    """Tope de filas del XLSX del aviso (`CROMO_INCONSISTENCIAS_MAX_FILAS_AVISO`, default 500)."""
    try:
        return max(1, int(os.getenv("CROMO_INCONSISTENCIAS_MAX_FILAS_AVISO", MAX_FILAS_AVISO_DEFAULT)))
    except ValueError:
        return MAX_FILAS_AVISO_DEFAULT


def normalizar_canales(crudo: str) -> str:
    """Lista de canales separada por comas, sin espacios ni vacíos."""
    return ",".join(c.strip() for c in (crudo or "").split(",") if c.strip())


async def leer_config_aviso(sesion: AsyncSession) -> dict[str, Any]:
    """Config del aviso para el admin: `{slack_channels, activo, existe}`."""
    canales, activo = await _leer_config_slack(sesion)
    fila = (
        await sesion.execute(
            text("SELECT 1 FROM app.config_servicios WHERE nombre_servicio = :n"),
            {"n": NOMBRE_SERVICIO_CONFIG},
        )
    ).first()
    return {"slack_channels": ",".join(canales), "activo": activo, "existe": fila is not None}


async def guardar_config_aviso(sesion: AsyncSession, canales: str, activo: bool) -> None:
    """Upsert de la fila "Cromo Inconsistencias". No hace commit."""
    params = {"n": NOMBRE_SERVICIO_CONFIG, "c": canales, "a": activo}
    actualizadas = await sesion.execute(
        text(
            "UPDATE app.config_servicios SET slack_channels = :c, activo = :a "
            "WHERE nombre_servicio = :n"
        ),
        params,
    )
    if actualizadas.rowcount == 0:
        await sesion.execute(
            text(
                "INSERT INTO app.config_servicios (nombre_servicio, intervalo_horas, slack_channels, activo) "
                "VALUES (:n, 0, :c, :a)"
            ),
            params,
        )


def _token_slack() -> str:
    from core.config import get_secret

    return get_secret("slack_bot_token_v1", "SLACK_BOT_TOKEN")


def _enviar_slack_sync(
    canales: Sequence[str], token: str, texto: str, xlsx: Optional[bytes], archivo: str
) -> int:
    """Manda el mensaje a cada canal, con el XLSX adjunto si hay (sin XLSX, mensaje solo).
    Devuelve cuántos envíos salieron bien."""
    from slack_sdk import WebClient

    cliente = WebClient(token=token, timeout=60)
    enviados = 0
    for canal in canales:
        try:
            if xlsx is None:
                cliente.chat_postMessage(channel=canal, text=texto, mrkdwn=True)
                enviados += 1
                continue
            cliente.files_upload_v2(
                channel=canal,
                file=io.BytesIO(xlsx),
                filename=archivo,
                title="Inconsistencias nuevas de Cromo",
                initial_comment=texto,
            )
            enviados += 1
        except Exception as exc:  # noqa: BLE001 - un canal caído no corta a los demás
            logger.error(
                "action=cromo_inconsistencias evento=aviso_slack_error canal=%s error=%s", canal, exc
            )
    return enviados


def _mensaje_slack(nuevos: int, cuarentena_auto: int, *, primera: bool = False, mostrados: int = 0) -> str:
    base = (
        ":warning: *Cromo: inconsistencias nuevas detectadas*\n"
        f"• Casos nuevos: *{nuevos}*\n"
        f"• En cuarentena automática: *{cuarentena_auto}*\n"
        f"• A revisar a mano: *{nuevos - cuarentena_auto}*\n"
    )
    if primera:
        return base + (
            "_Es la primera detección: no se adjunta el detalle. "
            "Exportalo desde el viewer de Inconsistencias Cromo (Infra > Servicios)._"
        )
    if mostrados < nuevos:
        return base + (
            f"_Se adjuntan los primeros {mostrados}; y {nuevos - mostrados} más — ver el viewer._"
        )
    return base + "_Se adjunta el detalle con lo que falta corregir en Cromo, una hoja por localidad._"


async def avisar_casos_nuevos(
    sesion: AsyncSession, resumen: Any, *, corrida_id: Optional[int] = None
) -> dict[str, bool]:
    """Avisa de los casos nuevos de una detección. Nunca levanta. Devuelve qué canales avisó."""
    avisado = {"ws": False, "slack": False}
    try:
        nuevos = int(getattr(resumen, "nuevos", 0) or 0)
        if nuevos <= 0:
            return avisado
        cuarentena_auto = int(getattr(resumen, "cuarentena_auto", 0) or 0)
        try:
            await _publicar_ws(
                {
                    "type": TIPO_AVISO_WS,
                    "nuevos": nuevos,
                    "cuarentena_auto": cuarentena_auto,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            avisado["ws"] = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("action=cromo_inconsistencias evento=aviso_ws_error error=%s", exc)

        try:
            canales, activo = await _leer_config_slack(sesion)
            if not (activo and canales):
                return avisado
            token = _token_slack()
            if not token:
                logger.warning(
                    "action=cromo_inconsistencias evento=aviso_slack_omitido motivo=sin_token"
                )
                return avisado
            # Primera detección (no había ningún caso antes): todo es "nuevo", sólo un resumen.
            primera = getattr(resumen, "casos_previos", None) == 0
            xlsx: Optional[bytes] = None
            mostrados = 0
            if not primera:
                claves = sorted(getattr(resumen, "nuevos_claves", ()) or ())
                tope = max_filas_aviso()
                filas = await filas_de_casos(sesion, claves[:tope])
                mostrados = len(filas)
                resto = max(0, nuevos - mostrados)
                nota = f"y {resto} más — ver el viewer" if resto else None
                xlsx = await asyncio.to_thread(generar_xlsx, filas, nota)
            sello = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            enviados = await asyncio.to_thread(
                _enviar_slack_sync,
                canales,
                token,
                _mensaje_slack(nuevos, cuarentena_auto, primera=primera, mostrados=mostrados),
                xlsx,
                f"cromo_inconsistencias_nuevas_{sello}.xlsx",
            )
            avisado["slack"] = enviados > 0
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "action=cromo_inconsistencias evento=aviso_slack_error corrida_id=%s error=%s",
                corrida_id,
                exc,
            )
    except Exception as exc:  # noqa: BLE001 - el aviso jamás hace fallar la detección
        logger.warning("action=cromo_inconsistencias evento=aviso_error error=%s", exc)
    return avisado
