# Nombre de archivo: fo_monitor.py
# Ubicación de archivo: db/models/fo_monitor.py
# Descripción: Modelos de FO Monitor — intervenciones, consultas a burritoIA, resultados PRE/POST y geometría de cables

"""Tablas de FO Monitor (migración `20261014_02`).

- `FomonConfig`: singleton (id=1) con ventana del piloto, tope diario, timeouts y la marca de agua
  `ultimo_ingreso_id_procesado`. El kill switch (`activo`) y el canal viven en la fila `fo_monitor`
  de `app.config_servicios`, igual que el resto de los servicios.
- `FomonIntervencion` + `FomonIntervencionIngreso` + `FomonIntervencionServicio`: qué se verifica
  (lista congelada en el PRE; `servicio_pk` NULL = cable sin servicios verificables).
- `FomonConsulta`: un mensaje a burritoIA. `FomonResultado` y `FomonReconocimiento` son
  append-only (trigger en la DB). `FomonConfigAuditoria` registra quién activó/cambió el piloto.
- `FomonCableGeo`: polilínea WGS84 simplificada por cable (precalculada desde `pts_raw`).

`servicio_pk` no tiene FK a `app.servicios` a propósito: la fusión por cadena PROV borra filas
superadas (`core/services/servicios_fusion_prov.py`) y el histórico de FO Monitor no debe romperse.
Estados/fases como String + CHECK (crecen sin `ALTER TYPE`).
"""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from db.base import Base

ESTADOS_INTERVENCION = (
    "PRE_PENDIENTE", "PRE_EN_CURSO", "EN_CURSO", "POST_PENDIENTE", "POST_EN_CURSO",
    "CERRADA", "SIN_EGRESO", "CANCELADA",
)
FASES_CONSULTA = ("PRE", "POST", "REVERIF")
ESTADOS_CONSULTA = ("PENDIENTE", "ENVIADA", "RESPONDIDA", "TIMEOUT", "ERROR", "CANCELADA")
ESTADOS_SERVICIO = ("UP", "DOWN", "ADMIN_DOWN", "DESCONOCIDO", "NO_SOPORTADO")


class FomonConfig(Base):
    __tablename__ = "fomon_config"
    __table_args__ = {"schema": "app"}

    id = Column(SmallInteger, primary_key=True, default=1)
    ventana_desde = Column(DateTime(timezone=True), nullable=True)
    ventana_hasta = Column(DateTime(timezone=True), nullable=True)
    tope_mensajes_diario = Column(Integer, nullable=False, default=400)
    max_ids_por_mensaje = Column(Integer, nullable=False, default=10)
    timeout_base_s = Column(Integer, nullable=False, default=240)
    timeout_por_servicio_s = Column(Integer, nullable=False, default=20)
    concurrencia = Column(Integer, nullable=False, default=3)
    burrito_user_id = Column(String(32), nullable=False, default="U0A2HE3K950")
    prompt_version = Column(String(8), nullable=False, default="v3")
    ultimo_ingreso_id_procesado = Column(Integer, nullable=False, default=0)
    actualizado_por = Column(String(128), nullable=True)
    actualizado_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FomonConfigAuditoria(Base):
    __tablename__ = "fomon_config_auditoria"
    __table_args__ = {"schema": "app"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    usuario = Column(String(128), nullable=False)
    cambios = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FomonIntervencion(Base):
    __tablename__ = "fomon_intervenciones"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    origen = Column(String(16), nullable=False)  # INGRESO | MANUAL
    camara_id = Column(Integer, ForeignKey("app.camaras.id", ondelete="SET NULL"), nullable=True, index=True)
    botella_objetivo_n_id = Column(BigInteger, nullable=True)
    botella_1_inferida = Column(Boolean, nullable=False, default=False)
    cable_n_id_manual = Column(BigInteger, nullable=True)
    tecnico = Column(String(128), nullable=True)
    thread_ts_ingreso = Column(String(32), nullable=True)
    canal_ingreso = Column(String(32), nullable=True)
    estado = Column(String(24), nullable=False, default="PRE_PENDIENTE", index=True)
    fecha_ingreso = Column(DateTime(timezone=True), nullable=True)
    fecha_egreso = Column(DateTime(timezone=True), nullable=True)
    sin_linea_base = Column(Boolean, nullable=False, default=False)
    post_tardio = Column(Boolean, nullable=False, default=False)
    egreso_inferido = Column(Boolean, nullable=False, default=False)
    atribucion_compartida = Column(Boolean, nullable=False, default=False)
    aviso_canal = Column(String(32), nullable=True)
    aviso_ts = Column(String(32), nullable=True)
    proximo_evento_en = Column(DateTime(timezone=True), nullable=True, index=True)
    iniciada_por = Column(String(128), nullable=True)
    creada_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actualizada_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    cerrada_at = Column(DateTime(timezone=True), nullable=True)


class FomonIntervencionIngreso(Base):
    __tablename__ = "fomon_intervencion_ingresos"
    __table_args__ = {"schema": "app"}

    intervencion_id = Column(Integer, ForeignKey("app.fomon_intervenciones.id", ondelete="CASCADE"), primary_key=True)
    ingreso_id = Column(Integer, ForeignKey("app.ingresos.id", ondelete="CASCADE"), primary_key=True, unique=True)


class FomonIntervencionServicio(Base):
    __tablename__ = "fomon_intervencion_servicios"
    __table_args__ = (
        UniqueConstraint("intervencion_id", "cable_n_id", "servicio_pk", name="uq_fomon_interv_serv"),
        {"schema": "app"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    intervencion_id = Column(Integer, ForeignKey("app.fomon_intervenciones.id", ondelete="CASCADE"), nullable=False, index=True)
    cable_n_id = Column(BigInteger, nullable=False, index=True)
    cable_nombre = Column(Text, nullable=True)
    cable_clase = Column(SmallInteger, nullable=True)
    botella_n_id = Column(BigInteger, nullable=True)
    es_objetivo = Column(Boolean, nullable=False, default=False)
    servicio_pk = Column(Integer, nullable=True)
    servicio_id_externo = Column(String(64), nullable=True)
    tipo_servicio = Column(String(64), nullable=True)
    categoria = Column(SmallInteger, nullable=True)
    cliente = Column(Text, nullable=True)


class FomonConsulta(Base):
    __tablename__ = "fomon_consultas"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    intervencion_id = Column(Integer, ForeignKey("app.fomon_intervenciones.id"), nullable=False, index=True)
    fase = Column(String(8), nullable=False)
    intento = Column(SmallInteger, nullable=False, default=1)
    estado = Column(String(12), nullable=False, default="PENDIENTE", index=True)
    servicios_pk = Column(ARRAY(Integer), nullable=False)
    ids_solicitados = Column(ARRAY(String(64)), nullable=False)
    prompt_version = Column(String(8), nullable=True)
    canal = Column(String(32), nullable=True)
    slack_ts = Column(String(32), nullable=True)
    permalink = Column(Text, nullable=True)
    texto_crudo = Column(Text, nullable=True)
    ref_burrito = Column(String(16), nullable=True)
    completa = Column(Boolean, nullable=True)
    lineas_invalidas = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    creada_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    enviada_at = Column(DateTime(timezone=True), nullable=True, index=True)
    respondida_at = Column(DateTime(timezone=True), nullable=True)
    proximo_evento_en = Column(DateTime(timezone=True), nullable=True)


class FomonResultado(Base):
    __tablename__ = "fomon_resultados"
    __table_args__ = {"schema": "app"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    consulta_id = Column(Integer, ForeignKey("app.fomon_consultas.id"), nullable=False, index=True)
    intervencion_id = Column(Integer, nullable=False, index=True)
    fase = Column(String(8), nullable=False)
    servicio_pk = Column(Integer, nullable=False)
    servicio_id_externo = Column(String(64), nullable=False)
    estado = Column(String(16), nullable=False)
    extremo = Column(String(16), nullable=True)
    motivo = Column(Text, nullable=True)
    parseado = Column(Boolean, nullable=False)
    medido_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FomonReconocimiento(Base):
    __tablename__ = "fomon_reconocimientos"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    intervencion_id = Column(Integer, ForeignKey("app.fomon_intervenciones.id"), nullable=False, index=True)
    servicio_pk = Column(Integer, nullable=True)
    usuario = Column(String(128), nullable=False)
    motivo = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FomonCableGeo(Base):
    __tablename__ = "fomon_cable_geo"
    __table_args__ = {"schema": "app"}

    cable_n_id = Column(BigInteger, primary_key=True)
    coords = Column(JSONB, nullable=False)  # [[lon, lat], ...] WGS84 simplificado
    min_lon = Column(Float, nullable=False)
    min_lat = Column(Float, nullable=False)
    max_lon = Column(Float, nullable=False)
    max_lat = Column(Float, nullable=False)
    vmax = Column(Integer, nullable=True)
    calidad = Column(String(32), nullable=True)
    actualizado_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
