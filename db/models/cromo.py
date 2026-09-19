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
    Index,
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
    """Botella/empalme ingerido desde Cromo. `n_id` es la PK de linaje (estable entre versiones).

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
    __table_args__ = (
        # Índice btree explícito (no `index=True`) — nombre distinto a propósito. Hallazgo real al
        # verificar contra `lasfocasdev-postgres` (2026-08-23, migración 20260823_01): el nombre que
        # generaría `index=True` por convención (`ix_cromo_botellas_nombre`) YA existe desde la
        # Etapa 2 (`20260805_01_cromo_ingesta.py`) como un índice GIN sobre
        # `to_tsvector('spanish', nombre)` para full-text search — nunca usado hoy por ningún query
        # del repo (`grep to_tsvector` no encuentra consumidores), pero no se toca/renombra acá
        # (fuera de alcance de esta tarea). Este índice nuevo es un btree simple sobre `nombre`
        # (mismo tipo que ya tiene `CromoCable.nombre`), para la cascada ILIKE/tokens de
        # `core/services/cromo/camara_botella_busqueda.py` (Tarea 1) — esa cascada hacía table scan
        # porque ese GIN de texto completo no acelera `ILIKE '%patron%'`. El docstring de
        # `camara_botella_busqueda.py` ("CromoBotella.nombre no tiene índice") es impreciso: sí tenía
        # uno, sólo que no del tipo que esa cascada podía aprovechar.
        Index("ix_cromo_botellas_nombre_btree", "nombre"),
        {"schema": "app"},
    )

    n_id = Column(BigInteger, primary_key=True)
    version_id = Column(BigInteger, nullable=False)  # 'id' de la versión vigente en Cromo
    vmax = Column(Integer, nullable=False)  # detector de cambios
    clase = Column(SmallInteger, ForeignKey("app.cromo_clases.clase"), nullable=False)
    nombre = Column(Text, nullable=True)
    nombre_editado_manual = Column(Boolean, nullable=False, default=False, server_default=false())
    separada_manualmente = Column(Boolean, nullable=False, default=False, server_default=false())
    # `false` no significa "no tiene splitters" sino "todavía no se barrió con el código que los
    # lee". La distinción es la que le permite a `empalmes.py` saber cuándo dejar de aplicar su
    # heurística de fan-out, que inventa splitters donde Cromo no tiene ninguno.
    splitters_relevados = Column(Boolean, nullable=False, server_default=false())
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


class CromoOdf(Base):
    """ODF (Objeto Distribuidor de Fibra) ingerido desde Cromo, clase 69. `n_id` es la PK de linaje
    (estable entre versiones), mismo patrón que `CromoBotella`.

    A diferencia de `CromoBotella`, no lleva `camara_id`/`estado` (no pedidos para ODF en esta
    iteración) ni ninguna columna de "sitio": el agrupamiento de ODFs que comparten domicilio físico
    se resuelve por dirección (`calle`+`altura`+`localidad`) en la capa de consulta, no en el
    esquema — el nombre real de un ODF es texto libre (ej. `"ODF Calle 9 Nro 593 PILAR"`), sin
    ningún ID de sitio embebido pese a lo que asumía el ticket original.

    `tipo_elemento` es una clasificación heurística por nombre (ver parser de la Tarea 2), no un
    dato que traiga Cromo — arranca en `'SIN_CLASIFICAR'` hasta que ese parser la puebla.
    `cables_asociados` es un mirror crudo de n_ids de cables (tp[] de Cromo), poblado por el
    parser/ingesta de las Tareas 2/3 — este modelo sólo declara la columna.
    """

    __tablename__ = "cromo_odfs"
    __table_args__ = (
        # Índice btree explícito nombrado, mismo criterio que `ix_cromo_botellas_nombre_btree`
        # (ver docstring de CromoBotella): soporta la cascada ILIKE/tokens de búsqueda sin depender
        # de `index=True` implícito.
        Index("ix_cromo_odfs_nombre_btree", "nombre"),
        {"schema": "app"},
    )

    n_id = Column(BigInteger, primary_key=True)
    version_id = Column(BigInteger, nullable=False)  # 'id' de la versión vigente en Cromo
    vmax = Column(Integer, nullable=False)  # detector de cambios
    clase = Column(SmallInteger, ForeignKey("app.cromo_clases.clase"), nullable=False)
    nombre = Column(Text, nullable=True)
    codigo_modelo = Column(Text, nullable=True)
    id_legacy = Column(Text, nullable=True)
    notas = Column(Text, nullable=True)
    calle = Column(Text, nullable=True)
    altura = Column(Text, nullable=True)
    localidad = Column(Text, nullable=True)
    provincia = Column(Text, nullable=True)
    ubicacion_fisica = Column(Text, nullable=True)
    tendido = Column(Text, nullable=True)
    latitud = Column(Float, nullable=True)
    longitud = Column(Float, nullable=True)
    pts_raw = Column(JSONB(astext_type=Text()), nullable=True)
    payload_raw = Column(JSONB(astext_type=Text()), nullable=False)
    vigente = Column(Boolean, nullable=False, server_default=true())
    primera_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    ultima_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    ultima_modificacion = Column(DateTime(timezone=True), nullable=True)
    propietario = Column(Text, nullable=True)  # at.47 en Cromo, ej. "Metrotel"
    tipo_elemento = Column(Text, nullable=False, server_default="SIN_CLASIFICAR")  # CHECK en la migración
    cables_asociados = Column(JSONB(astext_type=Text()), nullable=True)  # n_ids de cables (tp[]), lo llena el parser

    def __repr__(self) -> str:
        return f"<CromoOdf n_id={self.n_id} nombre='{self.nombre}'>"


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
    # Verificación manual de campo — sin poblador automático todavía (deuda técnica declarada, ver
    # migración 20260825_01_cromo_pelo_verificacion.py). No vienen del payload de Cromo, por eso NO
    # están en PELO_CAMPOS (ingesta.py) — una re-ingesta no debe pisarlos.
    verificable = Column(Boolean, nullable=True)
    status = Column(Text, nullable=True)
    fecha_hora_status = Column(DateTime(timezone=True), nullable=True)

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


class CromoOdfConector(Base):
    """Conector/posición de patchera de una ODF (clase 136 de Cromo, "Posición Patchera"). No
    cuelga del árbol de Cable/Botella — viaja embebido en `inner[]` del propio objeto ODF (clase
    69, requiere `show=ALL` para que Cromo lo incluya). La "Patchera"/bandeja padre (clase 135,
    ej. "O-1238223-1") se denormaliza acá (`bandeja_*`) en vez de tener tabla propia — nunca se
    navega "a" una bandeja sola, sólo agrupa visualmente sus conectores.

    `pelo_n_id` es el mismo `n_id` que ya existe en `app.cromo_pelos` (confirmado real: a
    diferencia del "ID dual" de extremos de cable, acá `tp[].id_to` del conector SÍ es
    directamente el `n_id` estable del pelo). `servicio_numero_atributo` es el atributo id=62 de
    Cromo (vínculo directo servicio↔conector, sin regex) — puede no coincidir con
    `cromo_pelos.servicio_numero` (regex sobre la descripción del pelo) por inconsistencias
    propias de Cromo; `servicio_resuelto`/`servicio_id_historico` combinan ambos con el mismo
    criterio MAX-based ID final ya usado en Servicios SLA, calculado en la ingesta."""

    __tablename__ = "cromo_odf_conectores"
    # El índice PARCIAL sobre `servicio_resuelto` va declarado acá y no como `index=True` porque
    # `index=True` no puede expresar el `WHERE servicio_resuelto IS NOT NULL` (sólo el 5,36% de las
    # ~205k filas tiene valor). Tiene que estar en la metadata: sin él, el próximo
    # `alembic revision --autogenerate` emitiría un `drop_index` del índice que crea la migración
    # `20260908_01` — y ese índice es lo que mantiene el detector de "Servicios sin ODF"
    # (`core/services/cromo/servicios_sin_odf.py`) en ~0.15s en vez de ~24s.
    __table_args__ = (
        Index(
            "ix_cromo_odf_conectores_servicio_resuelto",
            "servicio_resuelto",
            postgresql_where=text("servicio_resuelto IS NOT NULL"),
        ),
        {"schema": "app"},
    )

    n_id = Column(BigInteger, primary_key=True)
    odf_n_id = Column(BigInteger, nullable=False, index=True)  # parent (raíz), sin FK dura
    bandeja_n_id = Column(BigInteger, nullable=True)  # parent inmediato (Patchera, clase 135)
    bandeja_nombre = Column(Text, nullable=True)  # ej. "O-1238223-1"
    bandeja_modelo = Column(Text, nullable=True)  # at.89, ej. "SC-APCx24"
    numero_conector = Column(Text, nullable=True)  # at.81 / name, ej. "15"
    pelo_n_id = Column(BigInteger, nullable=True, index=True)  # tp[].id_to (clase 130), sin FK dura
    servicio_numero_atributo = Column(Text, nullable=True)  # at.62 crudo, sólo si está en uso
    servicio_resuelto = Column(Text, nullable=True)  # MAX(atributo, regex del pelo)
    servicio_id_historico = Column(Text, nullable=True)  # MIN(...), sólo si difieren
    payload_raw = Column(JSONB(astext_type=Text()), nullable=False)
    vigente = Column(Boolean, nullable=False, server_default=true())
    primera_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    ultima_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    def __repr__(self) -> str:
        return f"<CromoOdfConector n_id={self.n_id} odf_n_id={self.odf_n_id} numero_conector='{self.numero_conector}'>"


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


class CromoServicioOdfOverride(Base):
    """Asociación manual "escudo" de un Servicio sin ODF resuelta automáticamente a su ODF real
    en Cromo — Tarea 1 del gestor "Servicios sin ODF". Un operador confirma a mano qué ODF (y
    opcionalmente qué posición de conector/pelo específico) le corresponde a un Servicio que el
    detector automático (tareas siguientes) no pudo resolver por sí solo.

    `servicio_id` es FK DURA a `app.servicios.id` (`ondelete="CASCADE"`) — a diferencia del resto
    de las referencias cruzadas de Cromo, acá sí corresponde integridad referencial real porque
    `app.servicios` es un maestro propio de este repo, no un objeto de Cromo. `odf_n_id`/
    `pelo_n_id` siguen el criterio "sin FK dura" ya establecido para todo lo que referencia a
    Cromo (ver docstrings de `CromoCable`/`CromoBotellaAlias`): Cromo puede reingerir/renumerar, y
    este repo no debe bloquear un INSERT acá por eso. `pelo_n_id` es nullable a propósito: `NULL`
    significa "asociado a la ODF en general, sin pin a una posición física específica" —
    limitación de alcance ya aceptada para esta primera iteración.

    Sin `UNIQUE` en `servicio_id` a propósito: permite reasociar sin perder historial (cada fila
    es un evento de asociación, no el estado actual único de un Servicio).

    `categoria_causa`/`subcategoria`/`senal_direccion` son `Text` + `CHECK` (nunca ENUM Postgres,
    mismo criterio ya usado en el resto del repo, ver `ck_cromo_botella_alias_accion_valida`):
    agregar un valor nuevo es un `ALTER TABLE ... DROP/ADD CONSTRAINT`, no un `ALTER TYPE`
    irreversible.
    """

    __tablename__ = "cromo_servicio_odf_override"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    servicio_id = Column(
        Integer, ForeignKey("app.servicios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    odf_n_id = Column(BigInteger, nullable=False, index=True)  # referencia blanda a cromo_odfs.n_id
    pelo_n_id = Column(BigInteger, nullable=True)  # referencia blanda a cromo_pelos.n_id; NULL = sin pin
    categoria_causa = Column(Text, nullable=False)  # CHECK en la migración
    subcategoria = Column(Text, nullable=True)  # CHECK en la migración
    senal_direccion = Column(Text, nullable=True)  # CHECK en la migración
    usuario = Column(String(128), nullable=False)
    notas = Column(Text, nullable=True)
    creado_en = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    def __repr__(self) -> str:
        return f"<CromoServicioOdfOverride servicio_id={self.servicio_id} odf_n_id={self.odf_n_id}>"


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


class CromoTrackingCache(Base):
    """Caché de salida del tracking `.txt` de un pelo, con vencimiento.

    No es inventario: el camino óptico sigue sin persistirse en las tablas `cromo_*`
    (ver `core/services/cromo/camino_optico_service.py::CaminoOptico`). Lo que se guarda acá es el
    **artefacto ya renderizado** por `camino_optico_txt.renderizar_tracking_txt`, para no pagar de
    nuevo la llamada a `/path` (medida real: 4,6-14 s por pelo) cada vez que alguien descarga el
    tracking. Un servicio con 6 pelos costaba ~30-85 s en frío; con el caché, sólo la primera vez
    del día.

    La clave es el pelo (`pelo_n_id`), no el servicio: dos servicios que compartan pelo comparten
    la entrada, y un pelo rematcheado a otro servicio reusa su tracking sin regenerarlo.
    `servicio_id` queda como dato informativo del último servicio que lo generó.

    Una entrada más vieja que el TTL se considera inexistente y se regenera; la lectura nunca
    devuelve contenido vencido. Al normalizar una inconsistencia de consistencia hay que invalidar
    la entrada del pelo afectado, porque el `.txt` pasa a estar desactualizado respecto de la base.
    """

    __tablename__ = "cromo_tracking_cache"
    __table_args__ = {"schema": "app"}

    pelo_n_id = Column(BigInteger, primary_key=True)  # n_id de linaje del pelo, sin FK dura
    servicio_id = Column(
        Integer,
        ForeignKey("app.servicios.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    nombre_archivo = Column(String(256), nullable=False)
    contenido = Column(Text, nullable=False)
    duracion_ms = Column(Integer, nullable=True)  # lo que costó generarlo, para diagnóstico
    generado_at = Column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"), index=True
    )

    def __repr__(self) -> str:
        return f"<CromoTrackingCache pelo_n_id={self.pelo_n_id} generado_at={self.generado_at}>"


class CromoSplitter(Base):
    """Splitter óptico (clase 133 de Cromo). Cuelga del `inner[]` de la Botella, como las fusiones.

    **El ratio lo publica Cromo** en `at.83` ("1x8", "1x4", "1x2"). Hasta 2026-09-17 el sistema lo
    deducía por fan-out de fusiones en `core/services/cromo/empalmes.py`; medido contra 30 botellas
    reales, esa heurística acertaba en 18 y fallaba en 12, y **nunca** devolvía un ratio cuando el
    splitter existía de verdad. El dato venía en cada barrido y se descartaba como "clase
    inesperada".

    `salidas` es el `N` de "1xN" ya parseado; `ratio` conserva el crudo porque es lo que el
    operador reconoce. Sin FK dura hacia `cromo_botellas`, mismo criterio que el resto del
    namespace: las referencias entre entidades de Cromo son blandas para tolerar colgadas.
    """

    __tablename__ = "cromo_splitters"
    __table_args__ = {"schema": "app"}

    n_id = Column(BigInteger, primary_key=True)
    botella_n_id = Column(BigInteger, nullable=True, index=True)
    nombre = Column(Text, nullable=True)
    ratio = Column(Text, nullable=True)  # "1x8" crudo, tal como lo publica at.83
    salidas = Column(Integer, nullable=True)  # el N de "1xN"; NULL si el texto no matchea
    vigente = Column(Boolean, nullable=False, server_default=true())
    ultima_ingesta = Column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    def __repr__(self) -> str:
        return f"<CromoSplitter n_id={self.n_id} ratio={self.ratio!r} botella={self.botella_n_id}>"


class CromoSplitterPuerto(Base):
    """Puerto de un splitter (clase 134). `splitter_n_id` es su `parent` dentro de la Botella.

    `sentido` distingue la ENTRADA (una sola, que agrega todos los servicios del splitter) de las
    SALIDAS (una por servicio). Dato real de la botella 8941541: un splitter 1x8 con E1 listando
    `['99250','99430','100950','106587']` y S1/S2/S3/S5 con uno cada una — S4/S6/S7/S8 libres.

    `servicios_atributo` es el `at.62` del puerto y distingue tres estados, no dos:
    **NULL = no se preguntó** (el barrido de colección no trae ese atributo, sólo `/inner`),
    `[]` = se preguntó y el puerto está libre, y una lista con valores = los servicios que sirve.
    Mezclar NULL con `[]` haría parecer libre a todo puerto que todavía no se relevó.
    """

    __tablename__ = "cromo_splitter_puertos"
    __table_args__ = {"schema": "app"}

    n_id = Column(BigInteger, primary_key=True)
    splitter_n_id = Column(BigInteger, nullable=True, index=True)
    botella_n_id = Column(BigInteger, nullable=True, index=True)
    nombre = Column(Text, nullable=True)  # at.80: "E1", "S8"
    sentido = Column(Text, nullable=True)  # at.82: ENTRADA | SALIDA (CHECK en la migración)
    # `none_as_null=True` es imprescindible, no cosmético: por defecto SQLAlchemy serializa
    # Python `None` como JSON `null`, y entonces `IS NOT NULL` da TRUE y
    # `jsonb_array_length()` revienta con "cannot get array length of a scalar" (bug real
    # encontrado corriendo contra la base). Además destruiría la distinción de tres estados
    # documentada arriba: sin esto, "no se preguntó" y "se preguntó" serían indistinguibles.
    servicios_atributo = Column(JSONB(astext_type=Text(), none_as_null=True), nullable=True)
    vigente = Column(Boolean, nullable=False, server_default=true())
    ultima_ingesta = Column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    def __repr__(self) -> str:
        return f"<CromoSplitterPuerto n_id={self.n_id} {self.nombre!r} {self.sentido!r}>"


class CromoPonElemento(Base):
    """Elemento raíz de la red de acceso PON ingerido desde Cromo: caja PON y roseta.

    **Una sola tabla para ocho clases** (84, 126, 127, 137, 138, 139, 140 = caja PON; 85 = roseta),
    discriminadas por `clase`. No es una simplificación: el esquema medido contra Cromo real
    (2026-09-19) es idéntico en las ocho — todas son objetos raíz (`parent=None`), todas traen
    `ll`/`pts`/`vmax`, y todas publican los mismos `at`. Ocho tablas serían ocho copias del mismo
    DDL con ocho modelos y ocho consultas de inventario.

    Lo que separa una caja PON de una roseta no es el esquema sino `cromo_clases.entidad`
    (`'CAJA_PON'` vs `'ROSETA'`), que es de donde `camino_optico_service._tipo_de_clase` ya saca la
    etiqueta del nodo. Cada vista de inventario filtra por su lista de clases.

    Contrapartida asumida: el nombre de la tabla no coincide con ninguno de los dos conceptos que
    ve el operador. Si algún día una de las dos necesita columnas propias, el split es un
    `CREATE TABLE AS SELECT`, mucho más barato que mantener dos tablas hoy para nada.

    Versionado (`version_id`/`vmax`) igual que `CromoOdf`, por dos razones concretas: `vmax` deja
    que `upsert_versionado` distinga CREADA/ACTUALIZADA/SIN_CAMBIOS y alimente los contadores de la
    corrida, y `version_id` es lo que habilita la segunda pasada de
    `camino_optico_service._vincular_local` — sin él, un nodo de `/path` que llega identificado por
    su id de versión nunca vincula con la fila local.

    `capacidad_puertos` (`at.46`), `tipo_conector` (`at.40`) y `propietario` (`at.47`) tienen
    columna propia porque se midieron y significan algo: sobre 81 objetos reales `at.46` tomó sólo
    los valores 8, 16 y 4, y `at.40` sólo "Fast connect", "Easy Connect", "Conector de campo" y
    "Con casquillo". En cambio `at.45` fue constante ("SI" en los 81) y `at.203` devolvió valores
    incoherentes entre sí ("00000", "0", "115124", "90933"): no se les inventa semántica, quedan
    en `payload_raw` hasta que alguien los entienda.
    """

    __tablename__ = "cromo_pon_elementos"
    __table_args__ = (
        # Mismo criterio que `ix_cromo_odfs_nombre_btree` / `ix_cromo_botellas_nombre_btree`:
        # índice btree explícito y nombrado para la cascada ILIKE/tokens del buscador.
        Index("ix_cromo_pon_elementos_nombre_btree", "nombre"),
        Index("ix_cromo_pon_elementos_clase", "clase"),
        Index("ix_cromo_pon_elementos_localidad", "localidad"),
        {"schema": "app"},
    )

    n_id = Column(BigInteger, primary_key=True)
    version_id = Column(BigInteger, nullable=False)  # 'id' de la versión vigente en Cromo
    vmax = Column(Integer, nullable=False)  # detector de cambios
    clase = Column(SmallInteger, ForeignKey("app.cromo_clases.clase"), nullable=False)
    nombre = Column(Text, nullable=True)  # at.34
    codigo_modelo = Column(Text, nullable=True)  # at.41, ej. "FASTCONNET8"
    id_legacy = Column(Text, nullable=True)  # at.91
    notas = Column(Text, nullable=True)  # at.35 (a veces una URL de Trello, texto libre real)
    calle = Column(Text, nullable=True)  # at.67
    altura = Column(Text, nullable=True)  # at.16
    localidad = Column(Text, nullable=True)  # at.68
    provincia = Column(Text, nullable=True)  # at.69
    ubicacion_fisica = Column(Text, nullable=True)  # at.118
    tendido = Column(Text, nullable=True)  # at.20, ej. "Aereo"/"Terraza"
    propietario = Column(Text, nullable=True)  # at.47, ej. "Metrotel"
    tipo_conector = Column(Text, nullable=True)  # at.40, ej. "Fast connect"
    capacidad_puertos = Column(SmallInteger, nullable=True)  # at.46, medido: 4, 8 o 16
    latitud = Column(Float, nullable=True)
    longitud = Column(Float, nullable=True)
    pts_raw = Column(JSONB(astext_type=Text()), nullable=True)
    payload_raw = Column(JSONB(astext_type=Text()), nullable=False)
    vigente = Column(Boolean, nullable=False, server_default=true())
    primera_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    ultima_ingesta = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    ultima_modificacion = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<CromoPonElemento n_id={self.n_id} clase={self.clase} nombre={self.nombre!r}>"
