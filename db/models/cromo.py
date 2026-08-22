# Nombre de archivo: cromo.py
# Ubicación de archivo: db/models/cromo.py
# Descripción: Modelos SQLAlchemy para el inventario de fibra óptica ingerido desde Cromo Red (namespace cromo_*)

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    false,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from db.base import Base

# CromoBotella.camara_id referencia "app.camaras.id" y su relationship depende de que el modelo
# Camara (db/models/infra.py) ya esté registrado en Base.metadata — no ocurre sólo por importar
# db.models.cromo. Import explícito, mismo patrón que ya usa core/services/cromo/ingesta.py para
# Servicio: este módulo no debe depender de que quien lo use haya importado infra.py por otro motivo.
from db.models.infra import Camara, CamaraEstado  # noqa: F401


class TipoAsociacionPelo(str, Enum):
    """Clasificación funcional del extremo de un pelo (fibra individual) dentro de un cable."""

    CLIENTE = "CLIENTE"
    TRUNK_DWDM = "TRUNK_DWDM"
    OLT_LASER = "OLT_LASER"
    INFRA = "INFRA"
    LIBRE = "LIBRE"
    INDETERMINADO = "INDETERMINADO"


class CromoClase(Base):
    """Catálogo de clases de objeto de Cromo (botella, cable, tubo, pelo, fusión, ODF, excluidas).

    Vive en tabla, no en un CHECK: incorporar una clase nueva es un INSERT, no una migración.
    """

    __tablename__ = "cromo_clases"
    __table_args__ = {"schema": "app"}

    clase = Column(SmallInteger, primary_key=True)
    etiqueta = Column(Text, nullable=True)
    entidad = Column(Text, nullable=False)  # BOTELLA | CABLE | TUBO | PELO | FUSION | ODF | PARCELA
    ingerible = Column(Boolean, nullable=False, server_default=true())
    homologada = Column(Boolean, nullable=False, server_default=true())
    motivo_exclusion = Column(Text, nullable=True)
    count_cromo = Column(BigInteger, nullable=True)  # último count observado en Cromo
    count_fecha = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<CromoClase clase={self.clase} entidad='{self.entidad}'>"


class CromoIngestaCorrida(Base):
    """Auditoría de una corrida de ingesta completa (una fila por ejecución)."""

    __tablename__ = "cromo_ingesta_corridas"
    __table_args__ = {"schema": "app"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    usuario = Column(String(128), nullable=False)
    estado = Column(String(32), nullable=False)  # EN_CURSO | OK | OK_CON_ERRORES | FALLIDA | CANCELADA
    params = Column(JSONB(astext_type=Text()), nullable=False)  # clases, psize, max_paginas, show
    total_objetivo = Column(Integer, nullable=True)
    leidas = Column(Integer, nullable=False, server_default=text("0"))
    creadas = Column(Integer, nullable=False, server_default=text("0"))
    actualizadas = Column(Integer, nullable=False, server_default=text("0"))
    sin_cambios = Column(Integer, nullable=False, server_default=text("0"))
    errores = Column(Integer, nullable=False, server_default=text("0"))
    refs_colgadas = Column(Integer, nullable=False, server_default=text("0"))
    iniciada_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    finalizada_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<CromoIngestaCorrida id={self.id} estado='{self.estado}'>"


class CromoIngestaEvento(Base):
    """Evento puntual de una corrida (por objeto): creado, actualizado, sin cambios, error o referencia colgada."""

    __tablename__ = "cromo_ingesta_eventos"
    __table_args__ = {"schema": "app"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    corrida_id = Column(
        BigInteger, ForeignKey("app.cromo_ingesta_corridas.id", ondelete="CASCADE"), nullable=False
    )
    n_id = Column(BigInteger, nullable=True)
    clase = Column(SmallInteger, nullable=True)
    accion = Column(String(32), nullable=False)  # CREADA | ACTUALIZADA | SIN_CAMBIOS | ERROR | REF_COLGADA
    detalle = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    def __repr__(self) -> str:
        return f"<CromoIngestaEvento id={self.id} corrida_id={self.corrida_id} accion='{self.accion}'>"


class CromoBotella(Base):
    """Botella/empalme/ODF ingerido desde Cromo. `n_id` es la PK de linaje (estable entre versiones).

    `camara_id`/`estado` (desde 2026-08-11) los pone `core/services/cromo/camara_padre_service.py`
    vía `scripts/cromo_backfill_camara_padre.py` — deliberadamente excluidos de `BOTELLA_CAMPOS`
    (`core/services/cromo/ingesta.py`) para que ninguna re-ingesta futura los pise (ver ese módulo).

    `nombre_editado_manual` (desde 2026-08-21) lo pone `PATCH /api/infra/botellas/{n_id}/nombre`
    (Verificador Cromo) — cuando está en `True`, `_procesar_botella_completa` deja de pisar
    `nombre` en corridas futuras (mismo criterio de protección que `camara_id`/`estado`, pero
    condicional en vez de estructural, porque `nombre` sí debe seguir viniendo de Cromo para el
    resto de las botellas nunca editadas a mano).

    `separada_manualmente`/`separada_motivo`/`separada_por`/`separada_at` (desde 2026-08-22) los
    pone `POST /api/infra/botellas/{n_id}/separar-padre` (admin) cuando se separa una Botella
    agrupada erróneamente por nombre bajo una Cámara padre compartida —
    `core/services/cromo/separacion_service.py`. `scripts/cromo_backfill_camara_padre.py` excluye
    estas filas de su filtro de idempotencia como blindaje explícito adicional (ver ese script).
    """

    __tablename__ = "cromo_botellas"
    __table_args__ = {"schema": "app"}

    n_id = Column(BigInteger, primary_key=True)
    version_id = Column(BigInteger, nullable=False)  # 'id' de la versión vigente en Cromo
    vmax = Column(Integer, nullable=False)  # detector de cambios
    clase = Column(SmallInteger, ForeignKey("app.cromo_clases.clase"), nullable=False)
    nombre = Column(Text, nullable=True)
    nombre_editado_manual = Column(Boolean, nullable=False, default=False, server_default=false())
    separada_manualmente = Column(Boolean, nullable=False, default=False, server_default=false())
    separada_motivo = Column(Text, nullable=True)
    separada_por = Column(String(128), nullable=True)
    separada_at = Column(DateTime(timezone=True), nullable=True)
    codigo_modelo = Column(Text, nullable=True)
    id_legacy = Column(Text, nullable=True)  # at.91, candidato a ID de FOntime
    notas = Column(Text, nullable=True)
    calle = Column(Text, nullable=True)
    altura = Column(Text, nullable=True)
    localidad = Column(Text, nullable=True)
    provincia = Column(Text, nullable=True)
    ubicacion_fisica = Column(Text, nullable=True)
    tendido = Column(Text, nullable=True)
    latitud = Column(Float, nullable=True)
    longitud = Column(Float, nullable=True)
    pts_raw = Column(JSONB(astext_type=Text()), nullable=True)  # Gauss-Krüger faja 5, sin reproyectar
    payload_raw = Column(JSONB(astext_type=Text()), nullable=False)
    vigente = Column(Boolean, nullable=False, server_default=true())
    primera_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    ultima_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    ultima_modificacion = Column(DateTime(timezone=True), nullable=True)
    camara_id = Column(
        Integer,
        ForeignKey("app.camaras.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    estado = Column(
        SQLEnum(CamaraEstado, name="camara_estado", create_type=False, schema="app"),
        nullable=False,
        server_default="LIBRE",
    )

    camara = relationship("Camara", back_populates="cromo_botellas", foreign_keys=[camara_id])

    def __repr__(self) -> str:
        return f"<CromoBotella n_id={self.n_id} nombre='{self.nombre}'>"


class CromoCable(Base):
    """Cable de FO ingerido desde Cromo. Extremos sin FK dura: pueden apuntar a una botella que todavía no bajó."""

    __tablename__ = "cromo_cables"
    __table_args__ = {"schema": "app"}

    n_id = Column(BigInteger, primary_key=True)
    version_id = Column(BigInteger, nullable=False)
    vmax = Column(Integer, nullable=False)
    nombre = Column(Text, nullable=True, index=True)
    capacidad = Column(Text, nullable=True)  # at.32 crudo, ej. "72-BRUG"
    capacidad_pelos = Column(SmallInteger, nullable=True)  # derivado: prefijo numérico de capacidad
    propietario = Column(Text, nullable=True)
    jerarquia = Column(Text, nullable=True)  # Acceso | Troncal | Subtroncal
    tendido = Column(Text, nullable=True)
    distancia_geo = Column(Numeric(12, 2), nullable=True)
    distancia_real = Column(Numeric(12, 2), nullable=True)
    id_legacy = Column(Text, nullable=True)
    notas = Column(Text, nullable=True)
    extremo_a_n_id = Column(BigInteger, nullable=True)  # sin FK dura
    extremo_a_clase = Column(SmallInteger, nullable=True)
    extremo_a_legacy = Column(Text, nullable=True)
    extremo_a_nombre = Column(Text, nullable=True)
    extremo_b_n_id = Column(BigInteger, nullable=True)  # sin FK dura
    extremo_b_clase = Column(SmallInteger, nullable=True)
    extremo_b_legacy = Column(Text, nullable=True)
    extremo_b_nombre = Column(Text, nullable=True)
    pts_raw = Column(JSONB(astext_type=Text()), nullable=True)  # polilínea completa
    payload_raw = Column(JSONB(astext_type=Text()), nullable=False)
    vigente = Column(Boolean, nullable=False, server_default=true())
    primera_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    ultima_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    def __repr__(self) -> str:
        return f"<CromoCable n_id={self.n_id} nombre='{self.nombre}'>"


class CromoTubo(Base):
    """Tubo/buffer dentro de un cable. `cable_n_id` es el `parent` (n_id), sin FK dura."""

    __tablename__ = "cromo_tubos"
    __table_args__ = {"schema": "app"}

    n_id = Column(BigInteger, primary_key=True)
    cable_n_id = Column(BigInteger, nullable=False, index=True)
    orden = Column(SmallInteger, nullable=True)
    nombre_color = Column(Text, nullable=True)
    vigente = Column(Boolean, nullable=False, server_default=true())
    ultima_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    def __repr__(self) -> str:
        return f"<CromoTubo n_id={self.n_id} cable_n_id={self.cable_n_id}>"


class CromoPelo(Base):
    """Pelo/hilo dentro de un tubo. Pertenece al tubo, nunca directamente a la botella."""

    __tablename__ = "cromo_pelos"
    __table_args__ = {"schema": "app"}

    n_id = Column(BigInteger, primary_key=True)
    tubo_n_id = Column(BigInteger, nullable=False, index=True)  # parent, sin FK dura
    cable_n_id = Column(BigInteger, nullable=False, index=True)  # derivado del tubo, desnormalizado a propósito
    numero_pelo = Column(Text, nullable=True)
    orden = Column(SmallInteger, nullable=True)
    color = Column(Text, nullable=True)
    servicio_raw = Column(Text, nullable=True)  # at.61 sin tocar
    servicio_numero = Column(Text, nullable=True)  # parseado de at.61
    tipo_asociacion = Column(
        # schema="app" explícito: asyncpg no reconoce el tipo por nombre corto porque el
        # search_path de la conexión no incluye "app" (confirmado real, ver docs/db.md).
        # Sin esto, cualquier INSERT/UPDATE vía AsyncSession falla con "type ... does not exist".
        SQLEnum(TipoAsociacionPelo, name="cromo_tipo_asociacion_pelo", schema="app", create_type=False),
        nullable=False,
        server_default=TipoAsociacionPelo.LIBRE.value,
    )
    vigente = Column(Boolean, nullable=False, server_default=true())
    ultima_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    def __repr__(self) -> str:
        return f"<CromoPelo n_id={self.n_id} tubo_n_id={self.tubo_n_id} tipo_asociacion='{self.tipo_asociacion}'>"


class CromoFusion(Base):
    """Fusión entre dos pelos. Puede llegar embebida en `botella.inner[]` (nunca visto en la práctica
    contra el barrido paginado real, Etapa 8) o por barrido directo de clase 132 (Etapa 8, fase propia
    como cables) — este segundo camino no trae `parent`, por eso `botella_n_id` es nullable."""

    __tablename__ = "cromo_fusiones"
    __table_args__ = {"schema": "app"}

    n_id = Column(BigInteger, primary_key=True)
    botella_n_id = Column(BigInteger, nullable=True, index=True)  # parent, sin FK dura; ver docstring
    nombre_par = Column(Text, nullable=True)  # at.84 / name, ej. "53-17"
    tipo = Column(Text, nullable=True)  # at.85, no siempre "FUSION"
    pelo_a_n_id = Column(BigInteger, nullable=True)  # tp[0].id_to
    pelo_b_n_id = Column(BigInteger, nullable=True)  # tp[1].id_to
    latitud = Column(Float, nullable=True)
    longitud = Column(Float, nullable=True)
    vigente = Column(Boolean, nullable=False, server_default=true())
    ultima_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    def __repr__(self) -> str:
        return f"<CromoFusion n_id={self.n_id} botella_n_id={self.botella_n_id}>"


class CromoBotellaAlias(Base):
    """Aliasing manual de un n_id de Cromo "junk/duplicado" — fusionado a un golden record o
    ignorado directamente. `id_cromo_origen`/`id_cromo_destino` son referencias blandas (mismo
    criterio "sin FK dura" que el resto de Cromo, ver docstrings de CromoCable/CromoFusion):
    Cromo puede tener el destino en una clase que este repo nunca ingiere (ODF, clase excluida),
    y el origen puede no tener nunca una fila propia en `cromo_botellas` (si sólo existe como
    referencia colgada desde un cable/fusión). Cargada una vez por corrida en memoria — ver
    `core/services/cromo/alias_service.py::cargar_alias_vigentes` — nunca una query por objeto.

    Riesgo a tener presente al cargar filas a mano: si `id_cromo_destino` corresponde a una clase
    que este repo nunca ingiere como `CromoBotella` (ODF, o cualquier clase fuera de
    `CLASES_BOTELLA`), esa fila queda como `REF_COLGADA` permanente en `fase_reconciliacion` —
    comportamiento esperado, no un bug: el destino de una fusión debe ser un n_id de botella real
    e ingerible.
    """

    __tablename__ = "cromo_botella_alias"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    id_cromo_origen = Column(BigInteger, nullable=False, unique=True, index=True)
    id_cromo_destino = Column(BigInteger, nullable=True, index=True)
    accion = Column(String(20), nullable=False)  # 'fusionar' | 'ignorar' — CHECK en la migración
    motivo = Column(Text, nullable=True)
    creado_por = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<CromoBotellaAlias id_cromo_origen={self.id_cromo_origen} accion='{self.accion}'>"


class CromoServicioMatch(Base):
    """Puente entre un pelo con servicio parseado (`at.61`) y el maestro `app.servicios`."""

    __tablename__ = "cromo_servicio_match"
    __table_args__ = {"schema": "app"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    pelo_n_id = Column(BigInteger, ForeignKey("app.cromo_pelos.n_id", ondelete="CASCADE"), nullable=False)
    servicio_numero = Column(Text, nullable=False)
    servicio_id = Column(Integer, ForeignKey("app.servicios.id"), nullable=True, index=True)  # NULL si no matcheó
    metodo = Column(String(32), nullable=False)  # REGEX_EXACTO | REGEX_PARCIAL | MANUAL
    confianza = Column(SmallInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    def __repr__(self) -> str:
        return f"<CromoServicioMatch pelo_n_id={self.pelo_n_id} servicio_numero='{self.servicio_numero}'>"


class CromoIngestaConfig(Base):
    """Configuración persistente del scheduler de ingesta automática (Etapa 7). Fila única (id=1)."""

    __tablename__ = "cromo_ingesta_config"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    habilitado = Column(Boolean, nullable=False, server_default=false())  # arranca deshabilitado
    intervalo_horas = Column(Integer, nullable=False, server_default=text("24"))
    hora_inicio = Column(SmallInteger, nullable=True)  # 0-23, ancla el ciclo; NULL = sin anclar
    psize = Column(Integer, nullable=False, server_default=text("5"))
    max_paginas = Column(Integer, nullable=True)  # NULL = corrida real completa, sin límite
    clases = Column(JSONB(astext_type=Text()), nullable=False)  # lista de int, ej. [68,121,122,123,125]
    ultima_ejecucion = Column(DateTime(timezone=True), nullable=True)
    ultimo_error = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<CromoIngestaConfig habilitado={self.habilitado} intervalo_horas={self.intervalo_horas}>"
