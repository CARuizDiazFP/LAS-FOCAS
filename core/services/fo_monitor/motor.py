# Nombre de archivo: motor.py
# Ubicación de archivo: core/services/fo_monitor/motor.py
# Descripción: Máquina de estados de FO Monitor — detecta ingresos/egresos, consulta a burritoIA y cierra intervenciones

"""Motor de FO Monitor. Síncrono y sin estado en memoria: todo lo que importa (timers, intentos,
`ts` de Slack) vive en las tablas `app.fomon_*`, así que un reinicio del worker retoma donde quedó.

Un `tick()` hace, en orden y comiteando entre pasos:

1. `reconciliar_envios`   — consultas ENVIADA sin `slack_ts` (el worker murió entre publicar y
   guardar): se busca el token `FOMON-Q<id>` en el canal; si no aparece, vuelve a PENDIENTE.
2. `detectar_ingresos`    — filas nuevas de `app.ingresos` (marca de agua por id, no por fecha:
   revalidar/forzar ingreso escriben `fecha_inicio` en el pasado). Sólo con el piloto activo; la
   marca avanza siempre, así al reactivar no se procesa lo viejo.
3. `detectar_egresos`     — POST cuando todas las filas vinculadas tienen `fecha_fin`, cuando hay un
   EGRESO huérfano posterior en la misma cámara, o con una fila cerrada y otra abierta > 30 min.
   8 h sin egreso → SIN_EGRESO (un egreso posterior igual dispara un POST tardío).
4. `planificar_consultas` — arma las consultas PRE/POST en lotes (objetivo primero).
5. `enviar_consultas`     — respeta concurrencia, tope diario (hora AR) y `proximo_evento_en`.
6. `recibir_respuestas`   — `conversations.replies`, parser FOMON, reintento de los IDs sin línea.
7. `avanzar_intervenciones` — PRE completo → EN_CURSO; POST completo → reverificación de caídas
   nuevas (4 min) → CERRADA, con avisos en el hilo del canal de prueba.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.services.fo_monitor import avisos
from core.services.fo_monitor.alcance import resolver_alcance
from core.services.fo_monitor.estado import (
    PRE_VALIDO_DESPUES,
    estado_intervencion,
    post_efectivo,
    pre_valido,
    ultimos_por_fase,
)
from core.services.fo_monitor.parser import parsear_respuesta
from core.services.fo_monitor.prompt import construir_prompt, token_consulta
from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_unicos_por_cable_sync
from core.services.fo_monitor.slack_gateway import SlackGateway
from db.models.cromo import CromoBotella, CromoCable
from db.models.fo_monitor import (
    FomonConfig,
    FomonConsulta,
    FomonIntervencion,
    FomonIntervencionIngreso,
    FomonIntervencionServicio,
    FomonResultado,
)
from db.models.infra import Camara, Ingreso, IngresoTipo
from db.models.servicios import ConfigServicios

logger = logging.getLogger(__name__)

NOMBRE_SERVICIO = "fo_monitor"
TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")

FRESCURA_PRE = timedelta(minutes=20)
MAX_ANTIGUEDAD_INGRESO = timedelta(hours=8)
SIN_EGRESO_TRAS = timedelta(hours=8)
POST_TARDIO_TRAS = timedelta(minutes=30)
EGRESO_PARCIAL_TRAS = timedelta(minutes=30)
AGRUPACION_DELTA = timedelta(minutes=2)
REVERIF_DEMORA = timedelta(minutes=4)
POLL_RESPUESTA = timedelta(seconds=15)
SILENCIO_TRAS_REF = timedelta(seconds=20)
MAX_INTENTOS = 3
BACKOFF_BASE = timedelta(seconds=60)
RECONCILIAR_TRAS = timedelta(seconds=60)

ESTADOS_ABIERTOS = ("PRE_PENDIENTE", "PRE_EN_CURSO", "EN_CURSO", "POST_PENDIENTE", "POST_EN_CURSO", "SIN_EGRESO")


@dataclass
class Config:
    fila: FomonConfig
    activo: bool
    canal: str
    en_ventana: bool

    @property
    def operativo(self) -> bool:
        return self.activo and self.en_ventana and bool(self.canal)


@dataclass
class ResumenTick:
    intervenciones_nuevas: int = 0
    consultas_enviadas: int = 0
    consultas_finalizadas: int = 0
    intervenciones_cerradas: int = 0
    mensajes_hoy: int = 0
    operativo: bool = False
    errores: list[str] = field(default_factory=list)


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------------------------------


def cargar_config(session: Session, ahora: datetime) -> Config:
    fila = session.get(FomonConfig, 1)
    if fila is None:
        fila = FomonConfig(id=1, ultimo_ingreso_id_procesado=session.query(func.coalesce(func.max(Ingreso.id), 0)).scalar())
        session.add(fila)
        session.flush()
    cs = session.query(ConfigServicios).filter(ConfigServicios.nombre_servicio == NOMBRE_SERVICIO).first()
    activo = bool(cs and cs.activo)
    canal = ((cs.slack_channels if cs else "") or "").split(",")[0].strip()
    en_ventana = (fila.ventana_desde is None or ahora >= fila.ventana_desde) and (
        fila.ventana_hasta is None or ahora < fila.ventana_hasta
    )
    return Config(fila=fila, activo=activo, canal=canal, en_ventana=en_ventana)


def mensajes_enviados_hoy(session: Session, ahora: datetime) -> int:
    inicio_dia = ahora.astimezone(TZ_AR).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        session.query(func.count(FomonConsulta.id))
        .filter(FomonConsulta.enviada_at >= inicio_dia, FomonConsulta.slack_ts.isnot(None))
        .scalar()
        or 0
    )


# --------------------------------------------------------------------------------------------------
# Creación de intervenciones
# --------------------------------------------------------------------------------------------------


def _permalink_slack(slack: SlackGateway, canal: Optional[str], ts: Optional[str]) -> Optional[str]:
    if not canal or not ts:
        return None
    try:
        return slack.permalink(canal, ts)
    except Exception:  # noqa: BLE001 — el aviso no debe frenar la intervención
        return None


def crear_intervencion(
    session: Session,
    *,
    origen: str,
    camara_id: Optional[int],
    botella_objetivo_n_id: Optional[int],
    fecha_ingreso: Optional[datetime],
    ahora: datetime,
    tecnico: Optional[str] = None,
    thread_ts: Optional[str] = None,
    canal_ingreso: Optional[str] = None,
    ingreso_ids: tuple[int, ...] = (),
    sin_linea_base: bool = False,
    iniciada_por: Optional[str] = None,
) -> FomonIntervencion:
    """Congela el alcance (cables y servicios verificables) y deja la intervención en PRE_PENDIENTE."""
    alcance = resolver_alcance(session, camara_id, botella_objetivo_n_id) if camara_id else None
    abierta_misma_camara = (
        session.query(FomonIntervencion)
        .filter(FomonIntervencion.camara_id == camara_id, FomonIntervencion.estado.in_(ESTADOS_ABIERTOS))
        .all()
        if camara_id
        else []
    )
    interv = FomonIntervencion(
        origen=origen,
        camara_id=camara_id,
        botella_objetivo_n_id=alcance.botella_objetivo_n_id if alcance else botella_objetivo_n_id,
        botella_1_inferida=bool(alcance and alcance.botella_1_inferida),
        tecnico=tecnico,
        thread_ts_ingreso=thread_ts,
        canal_ingreso=canal_ingreso,
        estado="PRE_PENDIENTE",
        fecha_ingreso=fecha_ingreso,
        sin_linea_base=sin_linea_base,
        atribucion_compartida=bool(abierta_misma_camara),
        proximo_evento_en=ahora,
        iniciada_por=iniciada_por,
    )
    session.add(interv)
    session.flush()
    for otra in abierta_misma_camara:
        otra.atribucion_compartida = True
    for ingreso_id in ingreso_ids:
        session.add(FomonIntervencionIngreso(intervencion_id=interv.id, ingreso_id=ingreso_id))
    for cable in alcance.cables if alcance else []:
        if not cable.servicios:
            session.add(FomonIntervencionServicio(
                intervencion_id=interv.id, cable_n_id=cable.n_id, cable_nombre=cable.nombre,
                cable_clase=cable.clase, botella_n_id=cable.botella_n_id, es_objetivo=cable.es_objetivo,
            ))
        for s in cable.servicios:
            session.add(FomonIntervencionServicio(
                intervencion_id=interv.id, cable_n_id=cable.n_id, cable_nombre=cable.nombre,
                cable_clase=cable.clase, botella_n_id=cable.botella_n_id, es_objetivo=cable.es_objetivo,
                servicio_pk=s.servicio_id, servicio_id_externo=s.servicio_id_externo,
                tipo_servicio=s.tipo_servicio, categoria=s.categoria, cliente=s.nombre_cliente or s.cliente,
            ))
    session.flush()
    return interv


def crear_intervencion_manual(
    session: Session,
    *,
    usuario: str,
    ahora: datetime,
    camara_id: Optional[int] = None,
    botella_n_id: Optional[int] = None,
    cable_n_id: Optional[int] = None,
) -> FomonIntervencion:
    """Verificación manual de admin (Q10): una foto PRE sin ingreso ni comparación. Por cámara
    (todas sus botellas), por botella (su cámara, con ella como objetivo) o por un único cable."""
    if cable_n_id is not None:
        cable = session.get(CromoCable, cable_n_id)
        if cable is None or not cable.vigente:
            raise ValueError(f"cable {cable_n_id} inexistente o no vigente")
        interv = crear_intervencion(session, origen="MANUAL", camara_id=None, botella_objetivo_n_id=None,
                                    fecha_ingreso=None, ahora=ahora, iniciada_por=usuario)
        interv.cable_n_id_manual = cable_n_id
        try:
            servicios = servicios_unicos_por_cable_sync(session, cable_n_id).servicios
        except ObjetoNoEncontrado:
            servicios = []
        activos = [x for x in servicios if x.es_verificable and (x.estado_servicio or "").strip().lower() == "activo"]
        base = dict(intervencion_id=interv.id, cable_n_id=cable_n_id, cable_nombre=cable.nombre,
                    cable_clase=cable.clase, es_objetivo=True)
        if not activos:
            session.add(FomonIntervencionServicio(**base))
        for x in activos:
            session.add(FomonIntervencionServicio(
                **base, servicio_pk=x.servicio_id, servicio_id_externo=x.servicio_id_externo,
                tipo_servicio=x.tipo_servicio, categoria=x.categoria, cliente=x.nombre_cliente or x.cliente,
            ))
        session.flush()
        return interv
    if botella_n_id is not None:
        botella = session.get(CromoBotella, botella_n_id)
        if botella is None or not botella.camara_id:
            raise ValueError(f"botella {botella_n_id} inexistente o sin cámara padre")
        camara_id = botella.camara_id
    if camara_id is None:
        raise ValueError("indicar camara_id, botella_n_id o cable_n_id")
    return crear_intervencion(session, origen="MANUAL", camara_id=camara_id, botella_objetivo_n_id=botella_n_id,
                              fecha_ingreso=None, ahora=ahora, iniciada_por=usuario)


def _publicar_raiz(session: Session, cfg: Config, slack: SlackGateway, interv: FomonIntervencion) -> None:
    camara = session.get(Camara, interv.camara_id) if interv.camara_id else None
    botella = session.get(CromoBotella, interv.botella_objetivo_n_id) if interv.botella_objetivo_n_id else None
    filas = session.query(FomonIntervencionServicio).filter(FomonIntervencionServicio.intervencion_id == interv.id).all()
    texto = avisos.texto_raiz(
        interv.id,
        camara.nombre if camara else None,
        (botella.nombre if botella else None) or ("Botella 1" if interv.camara_id else None),
        interv.tecnico,
        len({f.cable_n_id for f in filas}),
        len({f.servicio_pk for f in filas if f.servicio_pk is not None}),
        _permalink_slack(slack, interv.canal_ingreso, interv.thread_ts_ingreso),
        origen=interv.origen,
        sin_linea_base=interv.sin_linea_base,
        botella_1_inferida=interv.botella_1_inferida,
    )
    try:
        interv.aviso_ts = slack.publicar(cfg.canal, texto)
        interv.aviso_canal = cfg.canal
    except Exception as exc:  # noqa: BLE001
        logger.warning("action=fomon_aviso_raiz error=%s intervencion=%s", exc, interv.id)


def _avisar(cfg: Config, slack: SlackGateway, interv: FomonIntervencion, texto: str) -> None:
    if not interv.aviso_ts:
        return
    try:
        slack.publicar(interv.aviso_canal or cfg.canal, texto, thread_ts=interv.aviso_ts)
    except Exception as exc:  # noqa: BLE001
        logger.warning("action=fomon_aviso error=%s intervencion=%s", exc, interv.id)


def detectar_ingresos(session: Session, cfg: Config, slack: SlackGateway, ahora: datetime) -> int:
    marca = cfg.fila.ultimo_ingreso_id_procesado
    nuevos = (
        session.query(Ingreso)
        .filter(Ingreso.id > marca)
        .order_by(Ingreso.id)
        .all()
    )
    if not nuevos:
        return 0
    cfg.fila.ultimo_ingreso_id_procesado = max(i.id for i in nuevos)
    if not cfg.operativo:
        return 0

    permitidos = {c.strip() for c in (cfg.fila.canales_ingreso or "").split(",") if c.strip()}
    candidatos = [
        i for i in nuevos
        if i.tipo == IngresoTipo.INGRESO and i.fecha_inicio is not None
        and i.anulado_at is None  # mismo criterio que `Ingreso.vigente()`; la marca de agua sí cuenta todos
        and (not permitidos or i.canal_id in permitidos)
    ]
    creadas = 0
    grupos: list[list[Ingreso]] = []
    for ing in candidatos:
        if ahora - ing.fecha_inicio > MAX_ANTIGUEDAD_INGRESO:
            continue  # reproceso histórico
        destino = None
        for g in grupos:
            cabeza = g[0]
            mismo_hilo = ing.thread_ts and ing.thread_ts == cabeza.thread_ts
            sin_hilo = (
                not ing.thread_ts and not cabeza.thread_ts and ing.camara_id == cabeza.camara_id
                and ing.tecnico_id == cabeza.tecnico_id
                and abs(ing.fecha_inicio - cabeza.fecha_inicio) <= AGRUPACION_DELTA
            )
            if mismo_hilo or sin_hilo:
                destino = g
                break
        if destino is None:
            grupos.append([ing])
        else:
            destino.append(ing)

    for grupo in grupos:
        cabeza = grupo[0]
        # Segunda fila de "Botella 1 y 2" procesada en un tick posterior: se suma a la existente.
        existente = None
        if cabeza.thread_ts:
            existente = (
                session.query(FomonIntervencion)
                .filter(FomonIntervencion.thread_ts_ingreso == cabeza.thread_ts,
                        FomonIntervencion.camara_id == cabeza.camara_id,
                        FomonIntervencion.estado.in_(ESTADOS_ABIERTOS))
                .first()
            )
        if existente is not None:
            for ing in grupo:
                session.add(FomonIntervencionIngreso(intervencion_id=existente.id, ingreso_id=ing.id))
            continue
        crear_intervencion(
            session,
            origen="INGRESO",
            camara_id=cabeza.camara_id,
            botella_objetivo_n_id=cabeza.cromo_botella_id,
            fecha_ingreso=cabeza.fecha_inicio,
            ahora=ahora,
            tecnico=cabeza.tecnico_id,
            thread_ts=cabeza.thread_ts,
            canal_ingreso=cabeza.canal_id,
            ingreso_ids=tuple(i.id for i in grupo),
            sin_linea_base=ahora - cabeza.fecha_inicio > FRESCURA_PRE,
        )
        creadas += 1
    return creadas


# --------------------------------------------------------------------------------------------------
# Egresos
# --------------------------------------------------------------------------------------------------


def _pasar_a_post(interv: FomonIntervencion, fecha_egreso: datetime, ahora: datetime, *, inferido: bool) -> None:
    interv.fecha_egreso = fecha_egreso
    interv.egreso_inferido = interv.egreso_inferido or inferido
    interv.post_tardio = ahora - fecha_egreso > POST_TARDIO_TRAS
    interv.estado = "POST_PENDIENTE"
    interv.proximo_evento_en = ahora


def detectar_egresos(session: Session, cfg: Config, slack: SlackGateway, ahora: datetime) -> None:
    abiertas = (
        session.query(FomonIntervencion)
        .filter(FomonIntervencion.origen == "INGRESO", FomonIntervencion.estado.in_(("EN_CURSO", "SIN_EGRESO")))
        .all()
    )
    for interv in abiertas:
        ingresos = (
            session.query(Ingreso)
            .join(FomonIntervencionIngreso, FomonIntervencionIngreso.ingreso_id == Ingreso.id)
            .filter(FomonIntervencionIngreso.intervencion_id == interv.id)
            .all()
        )
        # Un vinculado anulado desde el portal nunca ocurrió: no bloquea el paso a POST.
        ingresos = [i for i in ingresos if i.anulado_at is None]
        cerrados = [i for i in ingresos if i.fecha_fin is not None]
        if ingresos and len(cerrados) == len(ingresos):
            _pasar_a_post(interv, max(i.fecha_fin for i in cerrados), ahora, inferido=False)
            continue
        huerfano = (
            session.query(Ingreso)
            .filter(Ingreso.tipo == IngresoTipo.EGRESO, Ingreso.camara_id == interv.camara_id,
                    Ingreso.fecha_fin.isnot(None), Ingreso.fecha_fin > interv.fecha_ingreso,
                    Ingreso.vigente())
            .order_by(Ingreso.fecha_fin)
            .first()
            if interv.fecha_ingreso
            else None
        )
        if huerfano is not None:
            _pasar_a_post(interv, huerfano.fecha_fin, ahora, inferido=True)
            continue
        if cerrados and ahora - max(i.fecha_fin for i in cerrados) > EGRESO_PARCIAL_TRAS:
            _pasar_a_post(interv, max(i.fecha_fin for i in cerrados), ahora, inferido=True)
            continue
        if interv.estado == "EN_CURSO" and interv.fecha_ingreso and ahora - interv.fecha_ingreso >= SIN_EGRESO_TRAS:
            interv.estado = "SIN_EGRESO"
            _avisar(cfg, slack, interv, avisos.texto_sin_egreso(int(SIN_EGRESO_TRAS.total_seconds() // 3600)))


# --------------------------------------------------------------------------------------------------
# Consultas a burritoIA
# --------------------------------------------------------------------------------------------------


def _servicios_intervencion(session: Session, intervencion_id: int) -> list[tuple[int, str]]:
    """(servicio_pk, id externo) únicos, objetivo primero — un servicio en varios cables se consulta una vez."""
    filas = (
        session.query(FomonIntervencionServicio)
        .filter(FomonIntervencionServicio.intervencion_id == intervencion_id,
                FomonIntervencionServicio.servicio_pk.isnot(None))
        .order_by(FomonIntervencionServicio.es_objetivo.desc(), FomonIntervencionServicio.servicio_pk)
        .all()
    )
    vistos: dict[int, str] = {}
    for f in filas:
        vistos.setdefault(f.servicio_pk, f.servicio_id_externo or str(f.servicio_pk))
    return list(vistos.items())


def _crear_consultas(
    session: Session, cfg: Config, interv: FomonIntervencion, fase: str, servicios: list[tuple[int, str]],
    cuando: datetime, intento: int = 1,
) -> int:
    lote = max(1, cfg.fila.max_ids_por_mensaje)
    creadas = 0
    for i in range(0, len(servicios), lote):
        parte = servicios[i : i + lote]
        session.add(FomonConsulta(
            intervencion_id=interv.id, fase=fase, intento=intento, estado="PENDIENTE",
            servicios_pk=[pk for pk, _ in parte], ids_solicitados=[ext for _, ext in parte],
            prompt_version=cfg.fila.prompt_version, proximo_evento_en=cuando,
        ))
        creadas += 1
    return creadas


def planificar_consultas(session: Session, cfg: Config, slack: SlackGateway, ahora: datetime) -> None:
    for interv in session.query(FomonIntervencion).filter(
        FomonIntervencion.estado.in_(("PRE_PENDIENTE", "POST_PENDIENTE"))
    ):
        fase = "PRE" if interv.estado == "PRE_PENDIENTE" else "POST"
        if fase == "PRE" and not interv.aviso_ts and cfg.canal:
            _publicar_raiz(session, cfg, slack, interv)
        servicios = _servicios_intervencion(session, interv.id)
        _crear_consultas(session, cfg, interv, fase, servicios, ahora)
        interv.estado = "PRE_EN_CURSO" if fase == "PRE" else "POST_EN_CURSO"
        interv.proximo_evento_en = ahora


def _cancelar_pre_vencidas(session: Session, ahora: datetime) -> None:
    """Una consulta PRE que no salió antes de +20 min del ingreso ya no sirve como línea base."""
    pendientes = (
        session.query(FomonConsulta, FomonIntervencion)
        .join(FomonIntervencion, FomonIntervencion.id == FomonConsulta.intervencion_id)
        .filter(FomonConsulta.fase == "PRE", FomonConsulta.estado == "PENDIENTE",
                FomonIntervencion.origen == "INGRESO", FomonIntervencion.fecha_ingreso.isnot(None))
        .all()
    )
    for consulta, interv in pendientes:
        if ahora > interv.fecha_ingreso + PRE_VALIDO_DESPUES:
            consulta.estado = "CANCELADA"
            consulta.error = "ventana_pre_vencida"


def enviar_consultas(session: Session, cfg: Config, slack: SlackGateway, ahora: datetime) -> int:
    _cancelar_pre_vencidas(session, ahora)
    if not cfg.canal:
        return 0
    abiertas = session.query(func.count(FomonConsulta.id)).filter(FomonConsulta.estado == "ENVIADA").scalar() or 0
    cupo_concurrencia = cfg.fila.concurrencia - abiertas
    cupo_dia = cfg.fila.tope_mensajes_diario - mensajes_enviados_hoy(session, ahora)
    cupo = min(cupo_concurrencia, cupo_dia)
    if cupo <= 0:
        return 0
    # POST/REVERIF antes que PRE nuevos: cerrar una intervención vale más que abrir otra.
    candidatas = (
        session.query(FomonConsulta)
        .filter(FomonConsulta.estado == "PENDIENTE",
                (FomonConsulta.proximo_evento_en.is_(None)) | (FomonConsulta.proximo_evento_en <= ahora))
        .order_by((FomonConsulta.fase == "PRE").asc(), FomonConsulta.id)
        .limit(cupo)
        .all()
    )
    enviadas = 0
    for consulta in candidatas:
        consulta.estado = "ENVIADA"
        consulta.enviada_at = ahora
        consulta.canal = cfg.canal
        session.commit()  # marca ANTES de publicar: un reinicio acá se reconcilia por token
        texto = construir_prompt(cfg.fila.burrito_user_id, consulta.id, consulta.ids_solicitados,
                                 version=consulta.prompt_version or cfg.fila.prompt_version)
        try:
            consulta.slack_ts = slack.publicar(cfg.canal, texto)
            consulta.permalink = _permalink_slack(slack, cfg.canal, consulta.slack_ts)
            consulta.proximo_evento_en = ahora + POLL_RESPUESTA
            enviadas += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("action=fomon_enviar error=%s consulta=%s", exc, consulta.id)
            consulta.estado = "ERROR" if consulta.intento >= MAX_INTENTOS else "PENDIENTE"
            consulta.error = str(exc)[:500]
            consulta.intento += 1
            consulta.enviada_at = None
            consulta.proximo_evento_en = ahora + BACKOFF_BASE * consulta.intento
        session.commit()
    return enviadas


def reconciliar_envios(session: Session, cfg: Config, slack: SlackGateway, ahora: datetime) -> None:
    huerfanas = (
        session.query(FomonConsulta)
        .filter(FomonConsulta.estado == "ENVIADA", FomonConsulta.slack_ts.is_(None),
                FomonConsulta.enviada_at < ahora - RECONCILIAR_TRAS)
        .all()
    )
    for consulta in huerfanas:
        ts = None
        try:
            ts = slack.buscar_token(consulta.canal or cfg.canal, token_consulta(consulta.id),
                                    (consulta.enviada_at - RECONCILIAR_TRAS).timestamp())
        except Exception as exc:  # noqa: BLE001
            logger.warning("action=fomon_reconciliar error=%s consulta=%s", exc, consulta.id)
            continue
        if ts:
            consulta.slack_ts = ts
            consulta.proximo_evento_en = ahora
        else:
            consulta.estado = "PENDIENTE"
            consulta.enviada_at = None
            consulta.proximo_evento_en = ahora


def _limite_respuesta(cfg: Config, consulta: FomonConsulta) -> datetime:
    segundos = cfg.fila.timeout_base_s + cfg.fila.timeout_por_servicio_s * len(consulta.ids_solicitados)
    return consulta.enviada_at + timedelta(seconds=segundos)


def _es_de_burrito(mensaje: dict, burrito_user_id: str) -> bool:
    if mensaje.get("user") == burrito_user_id:
        return True
    return (mensaje.get("bot_profile") or {}).get("name", "").lower().startswith("burrito")


def recibir_respuestas(session: Session, cfg: Config, slack: SlackGateway, ahora: datetime) -> int:
    finalizadas = 0
    for consulta in (
        session.query(FomonConsulta)
        .filter(FomonConsulta.estado == "ENVIADA", FomonConsulta.slack_ts.isnot(None),
                FomonConsulta.proximo_evento_en <= ahora)
        .all()
    ):
        try:
            mensajes = slack.respuestas(consulta.canal or cfg.canal, consulta.slack_ts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("action=fomon_recibir error=%s consulta=%s", exc, consulta.id)
            consulta.proximo_evento_en = ahora + POLL_RESPUESTA
            continue
        de_burrito = [m for m in mensajes if _es_de_burrito(m, cfg.fila.burrito_user_id)]
        parse = parsear_respuesta([m.get("text", "") for m in de_burrito], consulta.ids_solicitados)
        ultimo = max((float(m.get("ts", 0)) for m in de_burrito), default=0.0)
        silencio = de_burrito and ahora.timestamp() - ultimo >= SILENCIO_TRAS_REF.total_seconds()
        vencida = ahora >= _limite_respuesta(cfg, consulta)
        if not (parse.completa or (parse.ref and silencio) or vencida):
            consulta.proximo_evento_en = ahora + POLL_RESPUESTA
            continue

        consulta.estado = "RESPONDIDA" if de_burrito else "TIMEOUT"
        consulta.respondida_at = ahora
        consulta.texto_crudo = "\n\n---\n\n".join(m.get("text", "") for m in de_burrito) or None
        consulta.ref_burrito = parse.ref
        consulta.completa = parse.completa
        consulta.lineas_invalidas = len(parse.lineas_invalidas)
        consulta.proximo_evento_en = None
        faltantes: list[tuple[int, str]] = []
        for pk, externo in zip(consulta.servicios_pk, consulta.ids_solicitados):
            r = parse.resultados[externo]
            session.add(FomonResultado(
                consulta_id=consulta.id, intervencion_id=consulta.intervencion_id, fase=consulta.fase,
                servicio_pk=pk, servicio_id_externo=externo, estado=r.estado, extremo=r.extremo,
                motivo=r.motivo, parseado=r.parseado, medido_at=ahora,
            ))
            if not r.parseado or r.estado == "DESCONOCIDO":
                faltantes.append((pk, externo))
        if faltantes and consulta.intento < MAX_INTENTOS:
            interv = session.get(FomonIntervencion, consulta.intervencion_id)
            # Reintento de a uno: un lote 100 % inválido hace que burritoIA corte sin bloque (PoC S5),
            # y un DESCONOCIDO explícito suele ser un timeout de sus tools (E2E dev 2026-10-14:
            # "Estado_Interfaz_Acceso timeout x3"), que se resuelve al reintentar.
            for pk, externo in faltantes:
                _crear_consultas(session, cfg, interv, consulta.fase, [(pk, externo)],
                                 ahora + BACKOFF_BASE * consulta.intento, intento=consulta.intento + 1)
        finalizadas += 1
    return finalizadas


# --------------------------------------------------------------------------------------------------
# Transiciones de intervención
# --------------------------------------------------------------------------------------------------


def _consultas_pendientes(session: Session, intervencion_id: int, fases: tuple[str, ...]) -> int:
    return (
        session.query(func.count(FomonConsulta.id))
        .filter(FomonConsulta.intervencion_id == intervencion_id, FomonConsulta.fase.in_(fases),
                FomonConsulta.estado.in_(("PENDIENTE", "ENVIADA")))
        .scalar()
        or 0
    )


def avanzar_intervenciones(session: Session, cfg: Config, slack: SlackGateway, ahora: datetime) -> int:
    cerradas = 0
    for interv in session.query(FomonIntervencion).filter(
        FomonIntervencion.estado.in_(("PRE_EN_CURSO", "POST_EN_CURSO"))
    ):
        if interv.estado == "PRE_EN_CURSO":
            if _consultas_pendientes(session, interv.id, ("PRE",)):
                continue
            por_fase = ultimos_por_fase(session, interv.id)
            tiene_servicios = bool(_servicios_intervencion(session, interv.id))
            if tiene_servicios and not any(
                pre_valido(interv, m) and m.estado in ("UP", "DOWN") for m in por_fase["PRE"].values()
            ):
                interv.sin_linea_base = True
            _avisar(cfg, slack, interv, avisos.texto_pre(estado_intervencion(session, interv)))
            if interv.origen == "MANUAL":
                interv.estado = "CERRADA"
                interv.cerrada_at = ahora
                cerradas += 1
            else:
                interv.estado = "EN_CURSO"
            continue

        # POST_EN_CURSO
        if _consultas_pendientes(session, interv.id, ("POST", "REVERIF")):
            continue
        por_fase = ultimos_por_fase(session, interv.id)
        ya_reverificado = bool(
            session.query(FomonConsulta.id)
            .filter(FomonConsulta.intervencion_id == interv.id, FomonConsulta.fase == "REVERIF")
            .first()
        )
        if not ya_reverificado and not interv.sin_linea_base:
            post = post_efectivo(por_fase)
            externos = dict(_servicios_intervencion(session, interv.id))
            candidatos = [
                (pk, externos.get(pk, str(pk)))
                for pk, m in por_fase["PRE"].items()
                if pre_valido(interv, m) and m.estado == "UP" and pk in post and post[pk].estado == "DOWN"
            ]
            if candidatos:
                _crear_consultas(session, cfg, interv, "REVERIF", candidatos, ahora + REVERIF_DEMORA)
                continue
        cables = estado_intervencion(session, interv)
        _avisar(cfg, slack, interv, avisos.texto_post(cables, interv.post_tardio, interv.egreso_inferido))
        interv.estado = "CERRADA"
        interv.cerrada_at = ahora
        cerradas += 1
    return cerradas


# --------------------------------------------------------------------------------------------------
# Tick
# --------------------------------------------------------------------------------------------------


def tick(session: Session, slack: SlackGateway, ahora_fn: Callable[[], datetime] = _ahora_utc) -> ResumenTick:
    resumen = ResumenTick()
    ahora = ahora_fn()
    cfg = cargar_config(session, ahora)
    resumen.operativo = cfg.operativo

    pasos = (
        ("reconciliar", lambda: reconciliar_envios(session, cfg, slack, ahora)),
        ("ingresos", lambda: setattr(resumen, "intervenciones_nuevas", detectar_ingresos(session, cfg, slack, ahora))),
        ("egresos", lambda: detectar_egresos(session, cfg, slack, ahora)),
        ("planificar", lambda: planificar_consultas(session, cfg, slack, ahora)),
        ("enviar", lambda: setattr(resumen, "consultas_enviadas", enviar_consultas(session, cfg, slack, ahora))),
        ("recibir", lambda: setattr(resumen, "consultas_finalizadas", recibir_respuestas(session, cfg, slack, ahora))),
        ("avanzar", lambda: setattr(resumen, "intervenciones_cerradas", avanzar_intervenciones(session, cfg, slack, ahora))),
    )
    for nombre, paso in pasos:
        try:
            paso()
            session.commit()
        except Exception as exc:  # noqa: BLE001 — un paso roto no frena a los demás
            session.rollback()
            logger.exception("action=fomon_tick paso=%s error=%s", nombre, exc)
            resumen.errores.append(f"{nombre}: {exc}")
            cfg = cargar_config(session, ahora)
    resumen.mensajes_hoy = mensajes_enviados_hoy(session, ahora)
    return resumen
