# Nombre de archivo: ingreso_reproceso_service.py
# Ubicación de archivo: core/services/ingreso_reproceso_service.py
# Descripción: Reproceso por lote de los casos app.ingresos_sin_match de Slack con la búsqueda actual — registra los movimientos que ahora resuelven, con su horario original

"""Reproceso por lote de `app.ingresos_sin_match` (origen Slack).

Es el "Revalidar ingreso" del listener aplicado a todos los casos pendientes de una vez, sin
postear en Slack. Nace de la mejora de búsqueda del 2026-09-28
(`docs/relevamiento_ingresos_sin_match_2026-09-28.md`): los casos históricos no se reintentan solos.

**Qué procesa**: casos `origen='slack'` con `texto_mensaje` y todavía pendientes (sin `ingreso_id`,
no resueltos por empalme ni por revalidación —incluye los cerrados con "Forzar ingreso/egreso", que
los marca resueltos—, `revisado=false`). Tracking y Excel no traen movimiento de técnico: quedan
fuera.

**Mismo pipeline que el listener en vivo**, sobre el `texto_mensaje` completo: extracción → ¿Nodo? →
multi-bot → `limpiar_ruido_operativo` → `buscar_camara_o_botella_cromo`. Diferencias deliberadas con
`_procesar_revalidacion_ingreso`:

- **Nodo** → el caso se marca `revisado=true` (no es una cámara; en vivo el mensaje se ignoraría).
- **Multi-bot**: si el mensaje nombra varias botellas y el caso es una de ellas (el listener viejo ya
  lo había separado), se procesa sólo esa; si el listener viejo no lo separaba ("bot1 y bot2"), todas.
- **Siempre un `INGRESO` real, nunca `INTENTO_BLOQUEADO`**: el estado de baneo de HOY no es evidencia
  de lo que pasó hace semanas — mismo criterio que "Forzar ingreso" (`docs/decisiones.md` 2026-09-23).
- **Egreso acotado en el tiempo** (`registrar_egreso_historico`): sólo cierra un ingreso que haya
  empezado antes del egreso.
- **Orden cronológico** (`created_at`, `id`): el Ingreso de una visita se registra antes que su
  Egreso, así el Egreso lo encuentra y lo cierra.
- **Sin duplicar** lo que ya existe: si el hilo ya tiene un `Ingreso` del mismo tipo para la misma
  cámara/botella (p. ej. la otra botella de un multi-bot que sí matcheó en vivo), no se registra otro.

Cada caso se procesa y se comita por separado: un error en uno no frena el lote, y una segunda corrida
no reprocesa lo ya resuelto (queda enlazado por `ingreso_id`/`resuelto_via_revalidacion`).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from core.services.cromo.camara_botella_busqueda import buscar_camara_o_botella_cromo
from core.services.ingreso_service import registrar_egreso_historico, registrar_movimiento_ingreso
from core.services.nodos_catalogo import corresponde_a_nodo
from db.models.infra import Ingreso, IngresoSinMatch, IngresoTipo
from modules.slack_baneo_notifier.camara_search import (
    AmbiguousSearchError,
    detectar_multi_bot,
    extraer_nombre_camara,
    extraer_slack_user_id_autorizacion,
    extraer_tipo_movimiento,
    limpiar_ruido_operativo,
    normalizar_candidato,
    preparar_nombre_busqueda,
)
from modules.slack_baneo_notifier.slack_user_resolver import resolver_nombre_tecnico

logger = logging.getLogger(__name__)

# Estados del reporte, por caso.
REGISTRADO = "REGISTRADO"
NODO = "NODO"
AMBIGUO = "AMBIGUO"
SIN_MATCH = "SIN_MATCH"
SIN_TIPO = "SIN_TIPO"  # resuelve la cámara, pero el mensaje no dice Ingreso/Egreso
YA_EXISTIA = "YA_EXISTIA"
ERROR = "ERROR"


@dataclass(slots=True)
class MovimientoReprocesado:
    nombre_buscado: str
    camara_id: int
    camara_nombre: str
    cromo_botella_id: int | None
    tipo: str
    ingreso_id: int | None
    accion: str  # "ingreso_creado" | "egreso_cerro_existente" | "egreso_huerfano" | "ya_existia"


@dataclass(slots=True)
class CasoReprocesado:
    caso_id: int
    created_at: str
    texto_original: str
    estado: str
    detalle: str = ""
    movimientos: list[MovimientoReprocesado] = field(default_factory=list)


def _candidatos(session: Session, ids: list[int] | None) -> list[IngresoSinMatch]:
    query = session.query(IngresoSinMatch).filter(
        IngresoSinMatch.origen == "slack",
        IngresoSinMatch.texto_mensaje.isnot(None),
        IngresoSinMatch.ingreso_id.is_(None),
        IngresoSinMatch.resuelto_via_revalidacion.is_(False),
        IngresoSinMatch.resuelto_via_empalme.is_(False),
        IngresoSinMatch.revisado.is_(False),
    )
    if ids:
        query = query.filter(IngresoSinMatch.id.in_(ids))
    return query.order_by(IngresoSinMatch.created_at.asc(), IngresoSinMatch.id.asc()).all()


def _nombres_del_caso(caso: IngresoSinMatch, nombre_raw: str) -> list[str]:
    """Nombres a buscar para este caso. Si el mensaje es multi-bot y el listener viejo ya lo había
    separado (el `texto_original` del caso es una de las partes), sólo esa parte; si no, todas."""
    partes = detectar_multi_bot(preparar_nombre_busqueda(nombre_raw)) or [nombre_raw]
    if len(partes) == 1:
        return partes
    propio = normalizar_candidato(preparar_nombre_busqueda(caso.texto_original or ""))
    coinciden = [p for p in partes if normalizar_candidato(limpiar_ruido_operativo(p)) == propio]
    return coinciden or partes


def _ya_registrado(session: Session, caso: IngresoSinMatch, camara_id: int, botella_id: int | None, tipo: IngresoTipo) -> Ingreso | None:
    if not caso.thread_ts:
        return None
    query = session.query(Ingreso).filter(
        Ingreso.thread_ts == caso.thread_ts,
        Ingreso.camara_id == camara_id,
        Ingreso.tipo == tipo,
    )
    query = query.filter(Ingreso.cromo_botella_id.is_(None) if botella_id is None else Ingreso.cromo_botella_id == botella_id)
    return query.first()


def _procesar_caso(session: Session, caso: IngresoSinMatch, client: Any) -> CasoReprocesado:
    item = CasoReprocesado(
        caso_id=caso.id,
        created_at=caso.created_at.isoformat() if caso.created_at else "",
        texto_original=caso.texto_original,
        estado=SIN_MATCH,
    )
    nombre_raw = extraer_nombre_camara(caso.texto_mensaje)
    if corresponde_a_nodo(nombre_raw, session):
        caso.revisado = True
        session.commit()
        item.estado, item.detalle = NODO, nombre_raw
        return item

    tipo = extraer_tipo_movimiento(caso.texto_mensaje)
    slack_user_id = extraer_slack_user_id_autorizacion(caso.texto_mensaje)
    momento: datetime = caso.created_at
    resueltos = []
    for nombre in _nombres_del_caso(caso, nombre_raw):
        nombre = limpiar_ruido_operativo(nombre)
        try:
            resultado = buscar_camara_o_botella_cromo(nombre, session)
        except AmbiguousSearchError as exc:
            item.estado, item.detalle = AMBIGUO, f"{nombre} ({exc.cantidad} candidatas)"
            return item
        if resultado.camara is None:
            item.estado, item.detalle = SIN_MATCH, nombre
            return item
        resueltos.append((nombre, resultado))

    if tipo is None:
        item.estado = SIN_TIPO
        item.detalle = ", ".join(r.camara.nombre for _, r in resueltos)
        return item

    tecnico_nombre = resolver_nombre_tecnico(client, slack_user_id) if client is not None else slack_user_id
    tipo_fila = IngresoTipo.INGRESO if tipo == "Ingreso" else IngresoTipo.EGRESO
    primero: Ingreso | None = None
    for nombre, resultado in resueltos:
        camara, botella = resultado.camara, resultado.botella
        botella_id = botella.n_id if botella is not None else None
        existente = _ya_registrado(session, caso, camara.id, botella_id, tipo_fila)
        if existente is not None:
            fila, accion = existente, "ya_existia"
        elif tipo == "Ingreso":
            fila = registrar_movimiento_ingreso(
                session,
                camara=camara,
                botella=botella,
                tipo_movimiento="Ingreso",
                tecnico_nombre=tecnico_nombre,
                slack_user_id=slack_user_id,
                momento=momento,
                thread_ts=caso.thread_ts,
                canal_id=caso.contexto,
            )
            accion = "ingreso_creado"
        else:
            fila, cerro = registrar_egreso_historico(
                session,
                camara=camara,
                botella=botella,
                tecnico_nombre=tecnico_nombre,
                slack_user_id=slack_user_id,
                momento=momento,
                thread_ts=caso.thread_ts,
                canal_id=caso.contexto,
            )
            accion = "egreso_cerro_existente" if cerro else "egreso_huerfano"
        primero = primero or fila
        item.movimientos.append(
            MovimientoReprocesado(
                nombre_buscado=nombre,
                camara_id=camara.id,
                camara_nombre=camara.nombre,
                cromo_botella_id=botella_id,
                tipo=tipo,
                ingreso_id=fila.id,
                accion=accion,
            )
        )

    caso.ingreso_id = primero.id if primero is not None else None
    caso.resuelto_via_revalidacion = True
    session.commit()
    item.estado = YA_EXISTIA if all(m.accion == "ya_existia" for m in item.movimientos) else REGISTRADO
    return item


def reprocesar_ingresos_sin_match(
    session: Session, *, client: Any = None, ids: list[int] | None = None
) -> list[CasoReprocesado]:
    """Reprocesa los casos pendientes en orden cronológico y devuelve el reporte por caso.

    `client` (opcional): `slack_sdk.WebClient` para resolver el nombre del técnico como el listener
    en vivo. Sin él se guarda el ID crudo de Slack en `tecnico_id` — `registrar_egreso_historico` y el
    Egreso en vivo matchean por nombre O por ID, así que el cierre posterior sigue funcionando.

    Cada caso comita por separado (los servicios de `ingreso_service` comitean). Un error en un caso
    se registra como `ERROR`, hace rollback y el lote sigue."""
    reporte: list[CasoReprocesado] = []
    for caso in _candidatos(session, ids):
        caso_id = caso.id
        try:
            reporte.append(_procesar_caso(session, caso, client))
        except Exception as exc:
            session.rollback()
            logger.exception("action=reproceso_ingreso_sin_match_error caso_id=%s", caso_id)
            reporte.append(CasoReprocesado(caso_id=caso_id, created_at="", texto_original="", estado=ERROR, detalle=repr(exc)[:300]))
    return reporte


def reporte_como_dicts(reporte: list[CasoReprocesado]) -> list[dict[str, Any]]:
    return [asdict(item) for item in reporte]


__all__ = [
    "AMBIGUO",
    "CasoReprocesado",
    "ERROR",
    "NODO",
    "REGISTRADO",
    "SIN_MATCH",
    "SIN_TIPO",
    "YA_EXISTIA",
    "reporte_como_dicts",
    "reprocesar_ingresos_sin_match",
]
