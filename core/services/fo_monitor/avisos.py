# Nombre de archivo: avisos.py
# Ubicación de archivo: core/services/fo_monitor/avisos.py
# Descripción: Textos (Slack mrkdwn) de los avisos de FO Monitor en el canal de prueba — funciones puras

"""Avisos de FO Monitor. Durante el piloto van sólo a #baneo-de-camaras-prueba (relevamiento A5):
un mensaje raíz por intervención y, en su hilo, PRE completo / POST con colores / alertas.

El técnico se muestra como texto plano (sin `<@U…>`) para no notificarlo desde el canal de prueba.
"""

from __future__ import annotations

from typing import Optional, Sequence

from core.services.fo_monitor.estado import EstadoCable

EMOJI = {
    "VERDE": ":large_green_circle:",
    "AMARILLO": ":large_yellow_circle:",
    "NARANJA": ":large_orange_circle:",
    "ROJO": ":red_circle:",
    "GRIS": ":white_circle:",
}


def _linea_cable(c: EstadoCable) -> str:
    s = c.semaforo
    objetivo = " _(objetivo)_" if c.es_objetivo else ""
    if s.evaluables == 0:
        detalle = "sin servicios verificables"
    else:
        detalle = f"{s.up}/{s.evaluables} UP"
        if s.conocidos < s.evaluables:
            detalle += f" · {s.evaluables - s.conocidos} sin dato"
    return f"{EMOJI[s.color]} *{c.nombre or c.cable_n_id}*{objetivo} — {detalle}"


def texto_raiz(
    intervencion_id: int,
    camara: Optional[str],
    botella: Optional[str],
    tecnico: Optional[str],
    cables: int,
    servicios: int,
    permalink_ingreso: Optional[str],
    origen: str = "INGRESO",
    sin_linea_base: bool = False,
    botella_1_inferida: bool = False,
) -> str:
    lineas = [f":mag: *FO Monitor* · intervención #{intervencion_id} · {camara or 'cámara sin nombre'}"]
    lineas.append(
        f"Botella objetivo: {botella or '—'} · Técnico: {tecnico or '—'} · "
        f"{cables} cables / {servicios} servicios verificables"
    )
    if botella_1_inferida:
        lineas.append(
            ":warning: La cámara no tiene una Botella 1 propia en Cromo (¿cámara duplicada?); "
            "se tomó como objetivo la de número más bajo."
        )
    if origen == "MANUAL":
        lineas.append("Verificación manual (sin ingreso asociado).")
    elif permalink_ingreso:
        lineas.append(f"Ingreso: <{permalink_ingreso}|ver hilo original>")
    if sin_linea_base:
        lineas.append(":warning: Ingreso detectado tarde: sin línea base PRE (no se pueden marcar caídas nuevas).")
    return "\n".join(lineas)


def texto_pre(cables: Sequence[EstadoCable]) -> str:
    cuerpo = "\n".join(_linea_cable(c) for c in cables) or "Sin cables con servicios verificables."
    return f"*PRE completo* (estado al ingreso)\n{cuerpo}"


def texto_post(cables: Sequence[EstadoCable], post_tardio: bool, egreso_inferido: bool) -> str:
    marcas = []
    if post_tardio:
        marcas.append("POST tardío")
    if egreso_inferido:
        marcas.append("egreso inferido")
    titulo = "*POST completo* (estado al egreso)" + (f" — _{', '.join(marcas)}_" if marcas else "")
    lineas = [titulo] + [_linea_cable(c) for c in cables]

    caidas = []
    recuperaciones = []
    for c in cables:
        por_pk = {s.servicio_pk: s for s in c.servicios}
        caidas += [(por_pk[pk], c) for pk in c.semaforo.caidas_nuevas if pk in por_pk]
        recuperaciones += [(por_pk[pk], c) for pk in c.semaforo.recuperaciones if pk in por_pk]
    if caidas:
        lineas.append("\n:rotating_light: *Caídas nuevas* (UP al ingreso → DOWN al egreso, reverificadas):")
        vistos = set()
        for s, c in sorted(caidas, key=lambda x: -(x[0].categoria or 0)):
            if s.servicio_pk in vistos:
                continue
            vistos.add(s.servicio_pk)
            extremo = f" · extremo {s.post.extremo}" if s.post and s.post.extremo else ""
            motivo = f" — {s.post.motivo}" if s.post and s.post.motivo else ""
            lineas.append(
                f"• {s.servicio_id_externo} {s.tipo_servicio or ''} C{s.categoria if s.categoria is not None else '?'} "
                f"{s.cliente or ''} (cable {c.nombre}){extremo}{motivo}"
            )
    if recuperaciones:
        lineas.append("\n:information_source: Recuperados durante la intervención: " + ", ".join(
            sorted({s.servicio_id_externo or str(s.servicio_pk) for s, _ in recuperaciones})
        ))
    return "\n".join(lineas)


def texto_sin_egreso(horas: int) -> str:
    return f":hourglass: Sin egreso registrado después de {horas} h. No se toma POST hasta que llegue el egreso."
