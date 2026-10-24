# Nombre de archivo: servicio_posicion_vigente.py
# Ubicación de archivo: core/services/cromo/servicio_posicion_vigente.py
# Descripción: Posición vigente por conector de un Servicio (app.servicio_posicion_vigente): posiciones posibles, declarar/retirar, validación contra el inventario y el camino, retiro del par y textos de aviso

"""La posición de ODF por la que hoy va un Servicio, cuando la etiqueta de los pelos no alcanza.

Caso real (93150, 2026-10-21): el camino viejo está entero en Cromo, pero sus 98 pelos llevan la
etiqueta `FO 44649` (otro servicio, de Baja). Sólo los conectores dicen 93150 (`servicio_resuelto`).
Como las semillas del tracking salen de pelos etiquetados, ese camino nunca se calculaba.

- **Posiciones posibles** (`posiciones_posibles`): conectores con `servicio_resuelto` igual a una
  identidad del Servicio, o cuyo pelo matchea el Servicio. Mismo `UNION` por identidad que
  `verificador._SQL_ODFS_POR_SERVICIO`, para que el planner use el índice parcial de
  `servicio_resuelto`. Dos filtros compartidos con la guarda del `.txt` (`pelo_es_de_posicion`):
  los pelos excluidos a mano (`_SIN_EXCLUIDOS_SQL`) y el conector cuyo pelo matchea a **otro
  servicio Activo** (`SIN_PELO_DE_OTRO_SERVICIO_ACTIVO_SQL`). Sin el segundo, el 42352 (Edge, sin
  semillas propias) tomaba como suyos los caminos del 42351: la ingesta da por ganador al número
  mayor del conector como si fuera una renumeración, y acá son dos servicios Activos distintos.
- **Camino ajeno** (`caminos_de_otro_servicio_activo`): el filtro anterior sólo mira el pelo semilla.
  Un camino de posición ya resuelto es de otro servicio Activo sólo si entre sus pelos con match
  domina (estrictamente) la etiqueta de ese otro Activo. Un pelo suelto no alcanza: el hilo 2 del
  camino viejo del 93150 recorre 4 pelos de 61972 (Activo, mal cargados en Cromo) entre 42 de 44649.
- **Declarar** (`declarar`): un admin elige conectores entre las posibles. Todo o nada, serializado
  por servicio con `pg_advisory_xact_lock`. Se guarda una foto (ODF, bandeja, número, pelo) y los
  pelos candidatos del conector (`pelo_n_id` más los de `tp[]`): la ingesta puede cambiar cuál
  elige como `pelo_n_id` cuando entra el cable de un tercero, y eso no es un cambio de pelo.
- **Retirar** (`retirar`): `vigente=false`, condicionado por id **y** por el pelo leído, para que un
  retiro automático calculado con datos viejos nunca pise una re-declaración concurrente. Un retiro
  efectivo le saca al Servicio la atribución del caché de esos pelos (salvo etiquetados u otra
  declarada vigente), para que la traza no siga mostrando el camino retirado.
- **Validación**: `validar_en_db` (pura) retira por conector inexistente, sin pelo o con un pelo
  que ya no es ninguno de los candidatos. `validar_camino` detecta pelos Cortados/Dañados o cables
  "Sin Uso" en el camino declarado, y `decidir_retiro` sólo retira por eso si existe otro camino
  completo sano: `estado_cromo` cubre a medias y tiene falsos positivos (el tramo 6731007 del
  111835, en uso, tiene un pelo "Dañado"). En los demás casos la declaración se mantiene y se avisa.
- **Retiro del par** (`arrastrar_par`): un retiro automático arrastra, en la misma corrida, a las
  demás declaradas vigentes del Servicio en la misma patchera (`bandeja_n_id`), con el mismo motivo
  y `detalle_retiro = {"arrastrada_por": <conector que lo disparó>, ...}`. El Servicio es un par de
  pelos que van juntos (93150 = O-1252871-1:1 y :2, siempre 2 trackings): retirando sólo :1, esa
  corrida usaba el cálculo automático y la siguiente aplicaba sólo :2, así que dos `track`
  seguidos daban resultados distintos y quedaba un tracking suelto. El retiro manual no arrastra.

`tracking_service` importa este módulo a nivel de módulo: los tipos del tracking van bajo
`TYPE_CHECKING` y `auditoria_huerfanos` (que importa `tracking_service`) se importa diferido.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime
from collections import Counter
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.camino_optico_service import _SIN_EXCLUIDOS_SQL
from core.services.cromo.servicios_sin_odf import IDENTIDADES_DEL_SERVICIO_SQL

if TYPE_CHECKING:
    from core.services.cromo.tracking_service import TrackingGenerado

__all__ = [
    "AVISO_CAMINO_INCOMPLETO",
    "AVISO_CAMINO_NO_RESUELTO",
    "MOTIVOS_RETIRO",
    "MOTIVO_CABLE_SIN_USO",
    "MOTIVO_CONECTOR_INEXISTENTE",
    "MOTIVO_MANUAL",
    "MOTIVO_PELO_CAMBIO",
    "MOTIVO_PELO_DANADO",
    "MOTIVO_SIN_PELO",
    "SIN_PELO_DE_OTRO_SERVICIO_ACTIVO_SQL",
    "TEXTO_CALCULO_AUTOMATICO",
    "AvisoPosicion",
    "MatchDePelo",
    "PosicionDeclarada",
    "PosicionNoValida",
    "PosicionPosible",
    "aplicar_retiros",
    "arrastrar_par",
    "caminos_ajenos_por_etiqueta",
    "caminos_de_otro_servicio_activo",
    "declaradas_validas",
    "declarar",
    "decidir_retiro",
    "domina_otro_servicio_activo",
    "es_estado_pelo_danado",
    "etiqueta_posiciones",
    "listar_declaradas",
    "par_sugerido",
    "pelo_es_de_posicion",
    "pelos_de_posiciones",
    "posiciones_posibles",
    "retirar",
    "retirar_manual",
    "texto_aviso",
    "textos_avisos",
    "tiene_posiciones",
    "validar_camino",
    "validar_en_db",
]

MOTIVO_MANUAL = "MANUAL"
MOTIVO_SIN_PELO = "SIN_PELO"
MOTIVO_PELO_CAMBIO = "PELO_CAMBIO"
MOTIVO_PELO_DANADO = "PELO_DANADO"
MOTIVO_CABLE_SIN_USO = "CABLE_SIN_USO"
MOTIVO_CONECTOR_INEXISTENTE = "CONECTOR_INEXISTENTE"
# Los mismos valores que el CHECK `ck_servicio_posicion_vigente_motivo` (migración 20261021_01).
MOTIVOS_RETIRO = (
    MOTIVO_MANUAL,
    MOTIVO_SIN_PELO,
    MOTIVO_PELO_CAMBIO,
    MOTIVO_PELO_DANADO,
    MOTIVO_CABLE_SIN_USO,
    MOTIVO_CONECTOR_INEXISTENTE,
)
# Avisos que nunca retiran: esa corrida usa el cálculo automático y la declaración se mantiene.
AVISO_CAMINO_NO_RESUELTO = "CAMINO_NO_RESUELTO"
AVISO_CAMINO_INCOMPLETO = "CAMINO_INCOMPLETO"

TEXTO_CALCULO_AUTOMATICO = (
    "Se usó el cálculo automático. Declarar la posición vigente en el Detalle de Servicio."
)

_CLASE_PELO = 130  # clase de los `tp[]` del conector que son pelos (ver `parser.py`)

# Clave del advisory lock por servicio (`pg_advisory_xact_lock(int, int)`): dos admins declarando a
# la vez sobre el mismo Servicio se serializan; sobre servicios distintos no se esperan.
_LOCK_POSICION_VIGENTE = 0x50564947  # "PVIG"


# ── Filtro compartido: pelo de otro servicio Activo ─────────────────────────────────────────

# Plantilla con `{pelo}` (la columna o el bind del pelo) que exige el alias `s` de `app.servicios`.
# Excluye el conector cuyo pelo matchea a otro servicio Activo y no matchea a este. Es el único
# criterio de "posición ajena": lo usan las semillas de posiciones, el selector del portal y la
# guarda del `.txt`, igual que `_SIN_EXCLUIDOS_SQL`, para que lista, semillas y pertenencia no
# diverjan. Un pelo que matchea a los dos (compartido) no se excluye: ya es semilla etiquetada.
# Medido en dev (2026-10-21): saca 94 conectores en 54 servicios, entre ellos los 11 del 42352.
SIN_PELO_DE_OTRO_SERVICIO_ACTIVO_SQL = f"""AND NOT (
        EXISTS (
            SELECT 1 FROM app.v_cromo_servicio_match_vigente mo
            JOIN app.servicios so ON so.id = mo.servicio_id
            WHERE mo.pelo_n_id = {{pelo}} AND so.id <> s.id AND so.estado_servicio ILIKE 'activo'
        )
        AND NOT EXISTS (
            SELECT 1 FROM app.v_cromo_servicio_match_vigente m
            WHERE m.pelo_n_id = {{pelo}} AND ({IDENTIDADES_DEL_SERVICIO_SQL})
        )
    )"""

# Universo de conectores del Servicio, con de dónde vino cada uno (resuelto y/o pelo).
_CTE_POSICIONES = f"""
    WITH s AS (
        SELECT id, servicio_id, numero_primer_servicio, alias_ids
        FROM app.servicios WHERE id = :servicio_id
    ),
    por_resuelto AS (
        SELECT c.n_id FROM app.cromo_odf_conectores c JOIN s ON c.servicio_resuelto = s.servicio_id
        UNION
        SELECT c.n_id FROM app.cromo_odf_conectores c JOIN s ON c.servicio_resuelto = s.numero_primer_servicio
        UNION
        SELECT c.n_id FROM app.cromo_odf_conectores c JOIN s ON c.servicio_resuelto = ANY(s.alias_ids)
    ),
    por_pelo AS (
        SELECT c.n_id FROM s
        JOIN app.v_cromo_servicio_match_vigente m ON ({IDENTIDADES_DEL_SERVICIO_SQL})
        JOIN app.cromo_odf_conectores c ON c.pelo_n_id = m.pelo_n_id
    ),
    universo AS (
        SELECT n_id, bool_or(r) AS por_resuelto, bool_or(NOT r) AS por_pelo
        FROM (
            SELECT n_id, true AS r FROM por_resuelto
            UNION ALL
            SELECT n_id, false AS r FROM por_pelo
        ) u
        GROUP BY n_id
    )
"""

# `m` (lateral) le da al pelo del conector el alias que espera `_SIN_EXCLUIDOS_SQL`. Un conector sin
# pelo pasa los dos filtros (no matchea nada) y se lista: el selector lo muestra como "sin pelo".
# `{joins}` va antes del WHERE: el listado suma pelo, cable y ODF; las guardas (EXISTS) no los usan.
_FROM_POSICIONES_PLANTILLA = f"""
    FROM universo u
    JOIN app.cromo_odf_conectores c ON c.n_id = u.n_id
    CROSS JOIN s
    CROSS JOIN LATERAL (SELECT c.pelo_n_id) AS m
    {{joins}}
    WHERE c.vigente
    {_SIN_EXCLUIDOS_SQL}
    {SIN_PELO_DE_OTRO_SERVICIO_ACTIVO_SQL.format(pelo="c.pelo_n_id")}
"""
_FROM_POSICIONES = _FROM_POSICIONES_PLANTILLA.format(joins="")
_FROM_POSICIONES_CON_DETALLE = _FROM_POSICIONES_PLANTILLA.format(
    joins="""LEFT JOIN app.cromo_pelos p ON p.n_id = c.pelo_n_id AND p.vigente
    LEFT JOIN app.cromo_cables cab ON cab.n_id = p.cable_n_id
    LEFT JOIN app.cromo_odfs o ON o.n_id = c.odf_n_id"""
)

# Pelos candidatos del conector: `pelo_n_id` más los `tp[]` de clase pelo del payload. El pelo de una
# fusión de ODF (141) no está en el payload del conector; si la ingesta lo eligió, entra por
# `pelo_n_id`.
_PELOS_CANDIDATOS_SQL = f"""ARRAY(
        SELECT DISTINCT x FROM unnest(
            ARRAY[c.pelo_n_id] || ARRAY(
                SELECT (t ->> 'id_to')::bigint
                FROM jsonb_array_elements(
                    CASE WHEN jsonb_typeof(c.payload_raw -> 'tp') = 'array'
                         THEN c.payload_raw -> 'tp' ELSE '[]'::jsonb END
                ) t
                WHERE t ->> 'class' = '{_CLASE_PELO}' AND t ->> 'id_to' IS NOT NULL
            )
        ) x
        WHERE x IS NOT NULL ORDER BY x
    )"""

_SQL_POSICIONES_POSIBLES = text(
    f"""
    {_CTE_POSICIONES}
    SELECT c.n_id AS conector_n_id, c.odf_n_id, o.nombre AS odf_nombre, o.clase AS odf_clase,
           c.bandeja_n_id, c.bandeja_nombre, c.numero_conector,
           c.pelo_n_id, p.numero_pelo, p.cable_n_id, cab.nombre AS cable_nombre,
           p.servicio_numero AS etiqueta_pelo, p.estado_cromo AS estado_pelo,
           c.servicio_resuelto, c.servicio_id_historico, c.patch_conector_n_id,
           u.por_resuelto, u.por_pelo,
           s.servicio_id AS s_id, s.numero_primer_servicio AS s_primero, s.alias_ids AS s_alias,
           {_PELOS_CANDIDATOS_SQL} AS pelos_candidatos,
           (SELECT so.servicio_id FROM app.v_cromo_servicio_match_vigente mo
            JOIN app.servicios so ON so.id = mo.servicio_id
            WHERE mo.pelo_n_id = c.pelo_n_id AND so.id <> s.id AND so.estado_servicio ILIKE 'activo'
            ORDER BY so.id LIMIT 1) AS servicio_activo_ajeno
    {_FROM_POSICIONES_CON_DETALLE}
    ORDER BY c.odf_n_id, c.bandeja_nombre NULLS LAST, length(c.numero_conector), c.numero_conector
    """
).columns()

# Bloque reusable "hay una declaración vigente de este Servicio" (con filtro opcional al final).
_DECLARADA_VIGENTE_SQL = (
    "SELECT 1 FROM app.servicio_posicion_vigente d WHERE d.servicio_id = :servicio_id AND d.vigente"
)

# La rama de declaradas replica `validar_en_db`: el conector sigue vigente, con pelo, y ese pelo es el
# declarado o uno de los candidatos. Una declarada con PELO_CAMBIO, SIN_PELO o CONECTOR_INEXISTENTE
# pendiente de retiro no habilita su pelo viejo en la guarda del `.txt` (bajaría el camino viejo con
# el número del Servicio y re-atribuiría el caché a su traza).
_SQL_PELO_ES_DE_POSICION = text(
    f"""
    {_CTE_POSICIONES}
    SELECT EXISTS (SELECT 1 {_FROM_POSICIONES} AND c.pelo_n_id = :pelo_n_id)
        OR EXISTS (
            SELECT 1 FROM app.servicio_posicion_vigente d
            JOIN app.cromo_odf_conectores cd ON cd.n_id = d.conector_n_id AND cd.vigente
            WHERE d.servicio_id = :servicio_id AND d.vigente AND d.pelo_n_id = :pelo_n_id
              AND cd.pelo_n_id IS NOT NULL
              AND (cd.pelo_n_id = d.pelo_n_id OR cd.pelo_n_id = ANY(d.pelos_candidatos))
        )
    """
)

# El match vigente de cada pelo de los caminos ya resueltos, visto desde el Servicio: a qué servicio
# (o etiqueta, si el match no tiene servicio), si es una identidad de este y si es Activo. Mismas
# identidades que el resto del módulo. Un pelo sin match no sale (no cuenta). Si un pelo tuviera dos
# matches (en dev, 0 de 209 960), gana el propio y después el Activo, como en
# `SIN_PELO_DE_OTRO_SERVICIO_ACTIVO_SQL`. Una sola consulta por corrida; la moda va en Python.
_SQL_MATCHES_DE_PELOS = text(
    f"""
    WITH s AS (
        SELECT id, servicio_id, numero_primer_servicio, alias_ids
        FROM app.servicios WHERE id = :servicio_id
    )
    SELECT DISTINCT ON (u.pelo_n_id)
           u.pelo_n_id,
           m.servicio_id AS match_servicio_id,
           m.servicio_numero AS match_numero,
           COALESCE(({IDENTIDADES_DEL_SERVICIO_SQL}), false) AS propio,
           COALESCE(so.estado_servicio ILIKE 'activo', false) AS activo
    FROM unnest(CAST(:pelos AS bigint[])) AS u(pelo_n_id)
    CROSS JOIN s
    JOIN app.v_cromo_servicio_match_vigente m ON m.pelo_n_id = u.pelo_n_id
    LEFT JOIN app.servicios so ON so.id = m.servicio_id
    ORDER BY u.pelo_n_id, propio DESC, activo DESC, m.servicio_id NULLS LAST
    """
)

_SQL_TIENE_POSICIONES = text(
    f"""
    {_CTE_POSICIONES}
    SELECT EXISTS (SELECT 1 {_FROM_POSICIONES} AND c.pelo_n_id IS NOT NULL)
        OR EXISTS ({_DECLARADA_VIGENTE_SQL})
    """
)

_SQL_LISTAR_DECLARADAS = text(
    """
    SELECT d.id, d.conector_n_id, d.odf_n_id, o.nombre AS odf_nombre, d.bandeja_n_id, d.bandeja_nombre,
           d.numero_conector, d.pelo_n_id AS pelo_declarado, d.pelos_candidatos,
           d.declarado_por, d.declarado_en,
           (c.n_id IS NOT NULL AND c.vigente) AS conector_existe, c.pelo_n_id AS pelo_actual
    FROM app.servicio_posicion_vigente d
    LEFT JOIN app.cromo_odf_conectores c ON c.n_id = d.conector_n_id
    LEFT JOIN app.cromo_odfs o ON o.n_id = d.odf_n_id
    WHERE d.servicio_id = :servicio_id AND d.vigente
    ORDER BY d.bandeja_nombre NULLS LAST, length(d.numero_conector), d.numero_conector, d.id
    """
)

_SQL_LOCK = text("SELECT pg_advisory_xact_lock(CAST(:clave AS integer), CAST(:servicio_id AS integer))")

# `ON CONFLICT` sobre el índice único parcial: re-declarar un conector ya vigente refresca la foto,
# los candidatos y el autor, y conserva el id (y por eso el retiro condicionado por pelo).
_SQL_DECLARAR = text(
    """
    INSERT INTO app.servicio_posicion_vigente
        (servicio_id, conector_n_id, odf_n_id, bandeja_n_id, bandeja_nombre, numero_conector,
         pelo_n_id, pelos_candidatos, declarado_por)
    VALUES (:servicio_id, :conector_n_id, :odf_n_id, :bandeja_n_id, :bandeja_nombre, :numero_conector,
            :pelo_n_id, CAST(:pelos_candidatos AS bigint[]), :usuario)
    ON CONFLICT (servicio_id, conector_n_id) WHERE vigente
    DO UPDATE SET pelo_n_id = EXCLUDED.pelo_n_id, pelos_candidatos = EXCLUDED.pelos_candidatos,
                  odf_n_id = EXCLUDED.odf_n_id, bandeja_n_id = EXCLUDED.bandeja_n_id,
                  bandeja_nombre = EXCLUDED.bandeja_nombre, numero_conector = EXCLUDED.numero_conector,
                  declarado_por = EXCLUDED.declarado_por, declarado_en = CURRENT_TIMESTAMP
    """
)

# Condicionado por id y por el pelo leído: si un admin re-declaró con otro pelo mientras se calculaba
# el retiro automático, el UPDATE no encuentra la fila y no retira nada.
_SQL_RETIRAR = text(
    """
    UPDATE app.servicio_posicion_vigente
    SET vigente = false, retirado_en = CURRENT_TIMESTAMP, retirado_por = :usuario,
        motivo_retiro = :motivo, detalle_retiro = CAST(:detalle AS jsonb)
    WHERE id = :id AND vigente AND pelo_n_id = :pelo_leido
    """
)

# Después de un retiro efectivo (misma transacción): el caché deja de atribuir al Servicio los pelos de
# la declaración retirada (`pelo_n_id` y candidatos). Sin esto, el upsert con `COALESCE` de
# `tracking_cache.guardar` conservaba el Servicio cuando la fase de posiciones volvía a sembrar el
# pelo con `servicio_id=None`, y la traza (y la API v1) seguía mostrando el camino retirado. Se
# conserva si el pelo está etiquetado al Servicio o si lo sostiene otra declaración vigente suya.
_SQL_LIMPIAR_CACHE_RETIRADA = text(
    f"""
    UPDATE app.cromo_tracking_cache tc
    SET servicio_id = NULL
    FROM app.servicio_posicion_vigente d
    JOIN app.servicios s ON s.id = d.servicio_id
    WHERE d.id = :id
      AND tc.servicio_id = d.servicio_id
      AND tc.pelo_n_id = ANY(ARRAY[d.pelo_n_id] || COALESCE(d.pelos_candidatos, ARRAY[]::bigint[]))
      AND NOT EXISTS (
          SELECT 1 FROM app.v_cromo_servicio_match_vigente m
          WHERE m.pelo_n_id = tc.pelo_n_id AND ({IDENTIDADES_DEL_SERVICIO_SQL})
      )
      AND NOT EXISTS (
          SELECT 1 FROM app.servicio_posicion_vigente d2
          WHERE d2.servicio_id = d.servicio_id AND d2.vigente AND d2.id <> d.id
            AND d2.pelo_n_id = tc.pelo_n_id
      )
    """
)

_SQL_ESTADOS_PELOS = text(
    """
    SELECT n_id, estado_cromo, atributos_leidos_at FROM app.cromo_pelos
    WHERE n_id = ANY(:pelos) AND estado_cromo IS NOT NULL
    ORDER BY n_id
    """
)

# El id del camino puede ser `n_id` o `version_id` del cable (ver `auditoria_huerfanos.cables_sin_uso`).
_SQL_NOMBRE_CABLE = text(
    "SELECT n_id, nombre FROM app.cromo_cables WHERE n_id = :id OR version_id = :id "
    "ORDER BY (n_id = :id) DESC LIMIT 1"
)


# ── Tipos ────────────────────────────────────────────────────────────────────────────────────


class PosicionNoValida(ValueError):
    """El conector pedido no es una posición posible del Servicio, o no tiene pelo en Cromo."""


def _posicion(bandeja_nombre: Optional[str], numero_conector: Optional[str], conector_n_id: int) -> str:
    if bandeja_nombre and numero_conector:
        return f"{bandeja_nombre}:{numero_conector}"
    return f"conector {conector_n_id}"


@dataclass(slots=True, frozen=True)
class PosicionPosible:
    conector_n_id: int
    odf_n_id: int
    odf_nombre: Optional[str]
    odf_clase: Optional[int]
    bandeja_n_id: Optional[int]
    bandeja_nombre: Optional[str]
    numero_conector: Optional[str]
    pelo_n_id: Optional[int]
    numero_pelo: Optional[str]
    cable_n_id: Optional[int]
    cable_nombre: Optional[str]
    etiqueta_pelo: Optional[str]  # `cromo_pelos.servicio_numero` del pelo del conector
    etiqueta_ajena: bool  # la etiqueta no es ninguna identidad del Servicio (caso 44649 del 93150)
    estado_pelo: Optional[str]
    servicio_resuelto: Optional[str]
    servicio_id_historico: Optional[str]
    patch_conector_n_id: Optional[int]
    por_resuelto: bool
    por_pelo: bool
    pelos_candidatos: tuple[int, ...] = ()
    # Otro servicio Activo que también matchea el pelo (sólo puede pasar si matchea a este también).
    servicio_activo_ajeno: Optional[str] = None

    @property
    def posicion(self) -> str:
        """`"O-1252871-1:1"` (patchera:conector)."""
        return _posicion(self.bandeja_nombre, self.numero_conector, self.conector_n_id)


@dataclass(slots=True, frozen=True)
class PosicionDeclarada:
    id: int
    conector_n_id: int
    odf_n_id: int
    odf_nombre: Optional[str]
    bandeja_n_id: Optional[int]
    bandeja_nombre: Optional[str]
    numero_conector: Optional[str]
    pelo_declarado: int
    pelos_candidatos: tuple[int, ...]
    pelo_actual: Optional[int]  # el pelo del conector en la ingesta vigente
    conector_existe: bool
    declarado_por: str
    declarado_en: Optional[datetime]

    @property
    def posicion(self) -> str:
        return _posicion(self.bandeja_nombre, self.numero_conector, self.conector_n_id)


@dataclass(slots=True, frozen=True)
class AvisoPosicion:
    """Algo que el operador tiene que saber de una posición declarada. `retirada` dice si se retira
    (o se retiró); `declaracion_id` y `pelo_declarado` son lo que condiciona el retiro.
    `arrastrada_con` es la posición cuyo retiro la arrastró (`arrastrar_par`), para el texto."""

    conector_n_id: int
    posicion: str
    codigo: str
    retirada: bool
    declaracion_id: Optional[int] = None
    pelo_declarado: Optional[int] = None
    detalle: dict[str, Any] = field(default_factory=dict)
    arrastrada_con: Optional[str] = None


def _int_o_none(valor: Any) -> Optional[int]:
    return None if valor is None else int(valor)


def _posible_de_fila(fila: Any) -> PosicionPosible:
    identidades = {fila.s_id, fila.s_primero, *(fila.s_alias or ())} - {None}
    etiqueta = fila.etiqueta_pelo or None
    return PosicionPosible(
        conector_n_id=int(fila.conector_n_id),
        odf_n_id=int(fila.odf_n_id),
        odf_nombre=fila.odf_nombre,
        odf_clase=_int_o_none(fila.odf_clase),
        bandeja_n_id=_int_o_none(fila.bandeja_n_id),
        bandeja_nombre=fila.bandeja_nombre,
        numero_conector=fila.numero_conector,
        pelo_n_id=_int_o_none(fila.pelo_n_id),
        numero_pelo=fila.numero_pelo,
        cable_n_id=_int_o_none(fila.cable_n_id),
        cable_nombre=fila.cable_nombre,
        etiqueta_pelo=etiqueta,
        etiqueta_ajena=etiqueta is not None and etiqueta not in identidades,
        estado_pelo=fila.estado_pelo,
        servicio_resuelto=fila.servicio_resuelto,
        servicio_id_historico=fila.servicio_id_historico,
        patch_conector_n_id=_int_o_none(fila.patch_conector_n_id),
        por_resuelto=bool(fila.por_resuelto),
        por_pelo=bool(fila.por_pelo),
        pelos_candidatos=tuple(int(p) for p in (fila.pelos_candidatos or ())),
        servicio_activo_ajeno=fila.servicio_activo_ajeno,
    )


def _declarada_de_fila(fila: Any) -> PosicionDeclarada:
    return PosicionDeclarada(
        id=int(fila.id),
        conector_n_id=int(fila.conector_n_id),
        odf_n_id=int(fila.odf_n_id),
        odf_nombre=fila.odf_nombre,
        bandeja_n_id=_int_o_none(fila.bandeja_n_id),
        bandeja_nombre=fila.bandeja_nombre,
        numero_conector=fila.numero_conector,
        pelo_declarado=int(fila.pelo_declarado),
        pelos_candidatos=tuple(int(p) for p in (fila.pelos_candidatos or ())),
        pelo_actual=_int_o_none(fila.pelo_actual),
        conector_existe=bool(fila.conector_existe),
        declarado_por=fila.declarado_por,
        declarado_en=fila.declarado_en,
    )


# ── Posiciones posibles (lectura) ──────────────────────────────────────────────────────────────


async def posiciones_posibles(sesion: AsyncSession, servicio_id: int) -> list[PosicionPosible]:
    """Los conectores que pueden ser la posición vigente del Servicio, ordenados por ODF y patchera.

    Ya vienen sin los pelos excluidos a mano y sin los conectores cuyo pelo es de otro servicio
    Activo. Incluye conectores sin pelo (para mostrarlos); `pelos_de_posiciones` los descarta.
    """
    filas = (await sesion.execute(_SQL_POSICIONES_POSIBLES, {"servicio_id": servicio_id})).all()
    return [_posible_de_fila(f) for f in filas]


def pelos_de_posiciones(posibles: Sequence[PosicionPosible]) -> list[int]:
    """Pelos semilla de las posiciones: no nulos y sin repetir, en el orden del SQL."""
    return list(dict.fromkeys(p.pelo_n_id for p in posibles if p.pelo_n_id is not None))


async def tiene_posiciones(sesion: AsyncSession, servicio_id: int) -> bool:
    """¿Hay alguna posición posible con pelo o alguna declarada vigente? Para las guardas "sin semilla"."""
    return bool(
        (await sesion.execute(_SQL_TIENE_POSICIONES, {"servicio_id": servicio_id})).scalar()
    )


async def pelo_es_de_posicion(sesion: AsyncSession, servicio_id: int, pelo_n_id: int) -> bool:
    """¿El pelo es de una posición posible (mismos filtros) o de una declarada vigente que el
    inventario todavía sostiene (mismo criterio que `validar_en_db`)? Guarda del `.txt`."""
    resultado = await sesion.execute(
        _SQL_PELO_ES_DE_POSICION, {"servicio_id": servicio_id, "pelo_n_id": pelo_n_id}
    )
    return bool(resultado.scalar())


# ── Camino de posición ajeno: etiqueta dominante ───────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class MatchDePelo:
    """A qué servicio matchea un pelo (`app.v_cromo_servicio_match_vigente`), visto desde un
    Servicio. `servicio` es la clave del voto: `"servicio:<app.servicios.id>"`, o
    `"etiqueta:<número>"` si el match no tiene servicio (nunca es Activo)."""

    servicio: str
    propio: bool
    activo: bool


_VOTO_PROPIO = "propio"  # todas las identidades del Servicio (número, primero, alias) votan juntas


def domina_otro_servicio_activo(matches: Iterable[Optional[MatchDePelo]]) -> bool:
    """¿La etiqueta más frecuente entre los pelos con match es la de OTRO servicio Activo? Pura.

    Cada pelo con match vota una vez por su servicio; `None` (sin match) no vota y las identidades
    de este Servicio votan como una sola. Es ajeno sólo si el más votado es otro Activo y supera
    estrictamente a cada uno de los demás: un empate no es ajeno. Caso real (93150, 2026-10-22):
    el hilo 2 del camino viejo tiene 42 pelos de 44649 (Baja), 4 de 61972 (Activo) y 2 de 64586
    (Baja): domina 44649, no es ajeno. El camino del 42351 pedido desde el 42352 sí.
    """
    votos: Counter[str] = Counter()
    activos: set[str] = set()
    for m in matches:
        if m is None:
            continue
        clave = _VOTO_PROPIO if m.propio else m.servicio
        votos[clave] += 1
        if m.activo and not m.propio:
            activos.add(clave)
    if not votos:
        return False
    (primero, cuenta), *resto = votos.most_common(2)
    if resto and resto[0][1] == cuenta:
        return False
    return primero != _VOTO_PROPIO and primero in activos


def caminos_ajenos_por_etiqueta(
    caminos: Mapping[int, Iterable[int]], matches: Mapping[int, MatchDePelo]
) -> frozenset[int]:
    """Las semillas de `caminos` ({semilla: pelos del camino}) en los que domina la etiqueta de otro
    servicio Activo (`domina_otro_servicio_activo`), con `matches` por pelo. Pura."""
    return frozenset(
        semilla
        for semilla, pelos in caminos.items()
        if domina_otro_servicio_activo(matches.get(int(p)) for p in set(pelos))
    )


def _match_de_fila(fila: Any) -> Optional[MatchDePelo]:
    if fila.match_servicio_id is not None:
        clave = f"servicio:{int(fila.match_servicio_id)}"
    elif fila.match_numero:
        clave = f"etiqueta:{fila.match_numero}"
    else:
        return None
    return MatchDePelo(servicio=clave, propio=bool(fila.propio), activo=bool(fila.activo))


async def _matches_de_pelos(
    sesion: AsyncSession, servicio_id: int, pelos: Sequence[int]
) -> dict[int, MatchDePelo]:
    """El match vigente de cada pelo (los sin match no aparecen), en UNA consulta."""
    filas = (
        await sesion.execute(_SQL_MATCHES_DE_PELOS, {"servicio_id": servicio_id, "pelos": list(pelos)})
    ).all()
    matches = {int(f.pelo_n_id): _match_de_fila(f) for f in filas}
    return {p: m for p, m in matches.items() if m is not None}


async def caminos_de_otro_servicio_activo(
    sesion: AsyncSession, servicio_id: int, caminos: Mapping[int, Iterable[int]]
) -> frozenset[int]:
    """Las semillas de `caminos` ({pelo semilla: pelos del camino}) que son el camino de otro
    servicio Activo: entre sus pelos con match domina estrictamente la etiqueta de ese otro Activo.

    El filtro de las posiciones (`SIN_PELO_DE_OTRO_SERVICIO_ACTIVO_SQL`) sólo mira el pelo semilla:
    un conector resuelto a este Servicio con un pelo sin etiqueta pasa, y su `/path` puede ser el
    camino de otro Activo (42352 ↔ 42351). Por mayoría y no por "algún pelo": las etiquetas sueltas
    mal cargadas en Cromo (4 pelos de 61972 en los 49 del hilo 2 del 93150) no hacen ajeno un
    camino. UNA sola consulta con todos los pelos de todos los caminos.
    """
    caminos = {int(semilla): frozenset(int(p) for p in pelos) for semilla, pelos in caminos.items()}
    todos = sorted(frozenset().union(*caminos.values())) if caminos else []
    if not todos:
        return frozenset()
    return caminos_ajenos_por_etiqueta(caminos, await _matches_de_pelos(sesion, servicio_id, todos))


def _numero(conector: Optional[str]) -> Optional[int]:
    limpio = (conector or "").strip()
    return int(limpio) if limpio.isdigit() else None


def par_sugerido(p: PosicionPosible, posibles: Sequence[PosicionPosible]) -> Optional[int]:
    """`conector_n_id` del otro hilo del par Tx/Rx que conviene declarar junto con `p`, o `None`.

    El par natural es el contiguo de la misma bandeja (`:1↔:2`, `:3↔:4`) con pelo. Si ese va por
    otro cable y el vecino del otro lado va por el mismo cable que `p`, se sugiere el vecino; si no
    hay vecino del mismo cable, queda el par natural.
    """
    n = _numero(p.numero_conector)
    if n is None or p.bandeja_n_id is None:
        return None
    vecinos = {
        _numero(x.numero_conector): x
        for x in posibles
        if x.bandeja_n_id == p.bandeja_n_id
        and x.conector_n_id != p.conector_n_id
        and x.pelo_n_id is not None
        and _numero(x.numero_conector) is not None
    }
    natural = vecinos.get(n + 1 if n % 2 else n - 1)
    otro_lado = vecinos.get(n - 1 if n % 2 else n + 1)
    mismo_cable = p.cable_n_id is not None
    if natural is not None and (not mismo_cable or natural.cable_n_id == p.cable_n_id):
        return natural.conector_n_id
    if otro_lado is not None and mismo_cable and otro_lado.cable_n_id == p.cable_n_id:
        return otro_lado.conector_n_id
    return natural.conector_n_id if natural is not None else None


def etiqueta_posiciones(pares: Iterable[tuple[str, str]]) -> str:
    """`[("O-1252871-1", "1"), ("O-1252871-1", "2")]` → `"O-1252871-1:1,2"`; varias patcheras con `" y "`.

    Respeta el orden en que aparece cada patchera; dentro de cada una, los números en orden numérico.
    """
    por_patchera: dict[str, list[str]] = {}
    for patchera, conector in pares:
        numeros = por_patchera.setdefault(patchera, [])
        if conector not in numeros:
            numeros.append(conector)
    partes = []
    for patchera, numeros in por_patchera.items():
        ordenados = sorted(numeros, key=lambda c: (_numero(c) is None, _numero(c) or 0, c))
        partes.append(f"{patchera}:{','.join(ordenados)}")
    return " y ".join(partes)


# ── Declaradas: listar, declarar, retirar ────────────────────────────────────────────────────


async def listar_declaradas(sesion: AsyncSession, servicio_id: int) -> list[PosicionDeclarada]:
    """Las posiciones declaradas VIGENTES del Servicio, con el estado actual del conector en la ingesta."""
    filas = (await sesion.execute(_SQL_LISTAR_DECLARADAS, {"servicio_id": servicio_id})).all()
    return [_declarada_de_fila(f) for f in filas]


async def declaradas_validas(sesion: AsyncSession, servicio_id: int) -> list[PosicionDeclarada]:
    """Las declaradas vigentes que el inventario ingerido todavía sostiene (sin aviso de
    `validar_en_db`). Las demás están pendientes de retiro: no sirven como candidatas ni para
    atribuir el caché al Servicio (endpoint del `.txt`). Tampoco las que arrastra su par
    (`arrastrar_par`): la próxima corrida las retira juntas."""
    declaradas = await listar_declaradas(sesion, servicio_id)
    invalidas = {a.declaracion_id for a in arrastrar_par(declaradas, validar_en_db(declaradas))}
    return [d for d in declaradas if d.id not in invalidas]


async def declarar(
    sesion: AsyncSession,
    servicio_id: int,
    conectores_n_id: Sequence[int],
    *,
    usuario: str,
) -> list[PosicionDeclarada]:
    """Declara en lote los conectores como posición vigente del Servicio y devuelve las vigentes.

    Todo o nada, bajo `pg_advisory_xact_lock` por servicio: cada conector tiene que estar en
    `posiciones_posibles` y tener pelo, si no `PosicionNoValida` (con rollback: suelta el lock y no
    escribe nada). Upsert sobre el índice único parcial y commit adentro, como
    `servicio_odf_confirmacion.confirmar`.
    """
    pedidos = list(dict.fromkeys(int(c) for c in conectores_n_id))
    if not pedidos:
        raise PosicionNoValida("Hay que elegir al menos un conector.")
    await sesion.execute(_SQL_LOCK, {"clave": _LOCK_POSICION_VIGENTE, "servicio_id": servicio_id})
    posibles = {p.conector_n_id: p for p in await posiciones_posibles(sesion, servicio_id)}
    elegidas: list[PosicionPosible] = []
    for conector in pedidos:
        p = posibles.get(conector)
        if p is None:
            await sesion.rollback()
            raise PosicionNoValida(
                f"El conector {conector} no es una posición posible del Servicio {servicio_id}."
            )
        if p.pelo_n_id is None:
            await sesion.rollback()
            raise PosicionNoValida(f"La posición {p.posicion} no tiene pelo en Cromo.")
        elegidas.append(p)
    for p in elegidas:
        await sesion.execute(
            _SQL_DECLARAR,
            {
                "servicio_id": servicio_id,
                "conector_n_id": p.conector_n_id,
                "odf_n_id": p.odf_n_id,
                "bandeja_n_id": p.bandeja_n_id,
                "bandeja_nombre": p.bandeja_nombre,
                "numero_conector": p.numero_conector,
                "pelo_n_id": p.pelo_n_id,
                "pelos_candidatos": list(dict.fromkeys([p.pelo_n_id, *p.pelos_candidatos])),
                "usuario": usuario,
            },
        )
    await sesion.commit()
    return await listar_declaradas(sesion, servicio_id)


async def retirar(
    sesion: AsyncSession,
    declaracion_id: int,
    *,
    pelo_leido: int,
    motivo: str,
    usuario: str = "auto",
    detalle: Optional[dict[str, Any]] = None,
) -> bool:
    """Retira la declaración (`vigente=false`, se conserva la fila) en su propia transacción.

    Condicionado por id y por el pelo con que se leyó: `False` si ya no estaba vigente o si se
    re-declaró con otro pelo mientras tanto. `ValueError` si el motivo no es uno del CHECK. Un
    retiro efectivo además le saca al Servicio la atribución del caché de esos pelos
    (`_SQL_LIMPIAR_CACHE_RETIRADA`), en la misma transacción.
    """
    if motivo not in MOTIVOS_RETIRO:
        raise ValueError(f"Motivo inválido {motivo!r}: debe ser uno de {', '.join(MOTIVOS_RETIRO)}.")
    resultado = await sesion.execute(
        _SQL_RETIRAR,
        {
            "id": declaracion_id,
            "pelo_leido": pelo_leido,
            "motivo": motivo,
            "usuario": usuario,
            "detalle": json.dumps(detalle, ensure_ascii=False, default=str) if detalle else None,
        },
    )
    retirada = bool(resultado.rowcount)
    if retirada:
        await sesion.execute(_SQL_LIMPIAR_CACHE_RETIRADA, {"id": declaracion_id})
    await sesion.commit()
    return retirada


async def retirar_manual(
    sesion: AsyncSession, servicio_id: int, conector_n_id: int, *, usuario: str
) -> bool:
    """Retiro pedido por un admin (`MANUAL`). `False` si el conector no tenía declaración vigente."""
    for d in await listar_declaradas(sesion, servicio_id):
        if d.conector_n_id == conector_n_id:
            return await retirar(
                sesion, d.id, pelo_leido=d.pelo_declarado, motivo=MOTIVO_MANUAL, usuario=usuario
            )
    return False


async def aplicar_retiros(
    sesion: AsyncSession, avisos: Sequence[AvisoPosicion], *, usuario: str = "auto"
) -> int:
    """Retira cada aviso con `retirada=True` (condicionado por su id y pelo). Devuelve cuántos retiró."""
    retiradas = 0
    for aviso in avisos:
        if not aviso.retirada or aviso.declaracion_id is None or aviso.pelo_declarado is None:
            continue
        if await retirar(
            sesion,
            aviso.declaracion_id,
            pelo_leido=aviso.pelo_declarado,
            motivo=aviso.codigo,
            usuario=usuario,
            detalle=aviso.detalle or None,
        ):
            retiradas += 1
    return retiradas


# ── Validación y retiro automático ───────────────────────────────────────────────────────────

# Sobre el texto sin tildes y en mayúsculas. Cubre las 12 variantes reales de dev (2026-10-21):
# "Cortado", "CORTADO AL RAZ", "Cortado dentro del BUFFER", "Fibra Dañada", "Fibra dañana" (sic)...
_RE_PELO_DANADO = re.compile(r"CORTAD|DANAD|DANAN")


def _normalizar(texto: Optional[str]) -> str:
    # Mismo criterio que `pelo_servicios._normalizar`.
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return sin_tildes.upper().strip()


def es_estado_pelo_danado(estado: Optional[str]) -> bool:
    """¿El `estado_cromo` (at.63) del pelo dice Cortado o Dañado, en cualquiera de sus variantes?"""
    return bool(_RE_PELO_DANADO.search(_normalizar(estado)))


def _aviso(d: PosicionDeclarada, codigo: str, *, retirada: bool, **detalle: Any) -> AvisoPosicion:
    return AvisoPosicion(
        conector_n_id=d.conector_n_id,
        posicion=d.posicion,
        codigo=codigo,
        retirada=retirada,
        declaracion_id=d.id,
        pelo_declarado=d.pelo_declarado,
        detalle=detalle,
    )


def validar_en_db(declaradas: Sequence[PosicionDeclarada]) -> list[AvisoPosicion]:
    """Un aviso (con `retirada=True`) por cada declarada que el inventario ingerido ya no sostiene.

    `CONECTOR_INEXISTENTE` si el conector no está (o no está vigente), `SIN_PELO` si se quedó sin
    pelo, `PELO_CAMBIO` si su pelo actual no es ninguno de los candidatos guardados al declarar.
    """
    avisos: list[AvisoPosicion] = []
    for d in declaradas:
        if not d.conector_existe:
            avisos.append(_aviso(d, MOTIVO_CONECTOR_INEXISTENTE, retirada=True, conector=d.conector_n_id))
        elif d.pelo_actual is None:
            avisos.append(_aviso(d, MOTIVO_SIN_PELO, retirada=True, declarado=d.pelo_declarado))
        elif d.pelo_actual not in {d.pelo_declarado, *d.pelos_candidatos}:
            avisos.append(
                _aviso(d, MOTIVO_PELO_CAMBIO, retirada=True, declarado=d.pelo_declarado, actual=d.pelo_actual)
            )
    return avisos


ARRASTRADA_POR = "arrastrada_por"


def arrastrar_par(
    declaradas: Sequence[PosicionDeclarada], avisos: Sequence[AvisoPosicion]
) -> list[AvisoPosicion]:
    """Los `avisos` más un retiro por cada declarada vigente arrastrada por su par. Pura.

    Un aviso con `retirada=True` que no es `MANUAL` (de `validar_en_db` o de `decidir_retiro`)
    arrastra a las demás `declaradas` con el mismo `bandeja_n_id` (misma patchera) que no tengan ya
    un retiro propio: mismo `codigo` (motivo del retiro), su propio id y pelo leído (el retiro sigue
    condicionado y no pisa una re-declaración concurrente) y `detalle = {"arrastrada_por": <conector
    que lo disparó>, **detalle del disparo}`. El aviso propio que no retiraba de una arrastrada
    (p. ej. `CAMINO_INCOMPLETO`) se reemplaza; cada arrastrada va después de su disparo.
    Declaradas sin `bandeja_n_id` no arrastran ni son arrastradas. Idempotente: un aviso ya
    arrastrado no dispara otro arrastre.

    Caso real 93150 (2026-10-22): O-1252871-1:1 y :2 van juntos. Retirar sólo :1 dejaba la corrida
    en el cálculo automático y la siguiente aplicaba sólo :2 (dos `track` seguidos distintos).
    """
    por_id = {d.id: d for d in declaradas}
    con_retiro = {a.declaracion_id for a in avisos if a.retirada}
    arrastradas: dict[int, AvisoPosicion] = {}
    por_disparo: dict[int, list[AvisoPosicion]] = {}
    for i, aviso in enumerate(avisos):
        if not aviso.retirada or aviso.codigo == MOTIVO_MANUAL or ARRASTRADA_POR in aviso.detalle:
            continue
        disparo = por_id.get(aviso.declaracion_id) if aviso.declaracion_id is not None else None
        if disparo is None or disparo.bandeja_n_id is None:
            continue
        for d in declaradas:
            if (
                d.id == disparo.id
                or d.bandeja_n_id != disparo.bandeja_n_id
                or d.id in con_retiro
                or d.id in arrastradas
            ):
                continue
            arrastrada = AvisoPosicion(
                conector_n_id=d.conector_n_id,
                posicion=d.posicion,
                codigo=aviso.codigo,
                retirada=True,
                declaracion_id=d.id,
                pelo_declarado=d.pelo_declarado,
                detalle={ARRASTRADA_POR: aviso.conector_n_id, **aviso.detalle},
                arrastrada_con=aviso.posicion,
            )
            arrastradas[d.id] = arrastrada
            por_disparo.setdefault(i, []).append(arrastrada)
    if not arrastradas:
        return list(avisos)
    salida: list[AvisoPosicion] = []
    for i, aviso in enumerate(avisos):
        if aviso.declaracion_id not in arrastradas:
            salida.append(aviso)
        salida.extend(por_disparo.get(i, ()))
    return salida


def _pelos_de(tracking: "TrackingGenerado") -> frozenset[int]:
    return frozenset(tracking.pelos_camino) | {tracking.pelo_n_id}


async def _problema_del_camino(
    sesion: AsyncSession, tracking: "TrackingGenerado"
) -> Optional[tuple[str, dict[str, Any]]]:
    """`(código, detalle)` del primer problema del camino (pelo Cortado/Dañado o cable "Sin Uso")."""
    filas = (
        await sesion.execute(_SQL_ESTADOS_PELOS, {"pelos": sorted(_pelos_de(tracking))})
    ).all()
    for fila in filas:
        if es_estado_pelo_danado(fila.estado_cromo):
            leido = fila.atributos_leidos_at
            return MOTIVO_PELO_DANADO, {
                "pelo": int(fila.n_id),
                "estado": fila.estado_cromo,
                "leido_en": leido.isoformat() if leido else None,
            }
    from core.services.cromo import auditoria_huerfanos  # diferido: importa tracking_service

    cables = tuple(tracking.extremos.cables) if tracking.extremos else ()
    sin_uso = await auditoria_huerfanos.cables_sin_uso(sesion, cables)
    cable = next((c for c in cables if c in sin_uso), None)
    if cable is None:
        return None
    fila = (await sesion.execute(_SQL_NOMBRE_CABLE, {"id": cable})).first()
    return MOTIVO_CABLE_SIN_USO, {"cable": cable, "nombre": fila.nombre if fila else None}


async def validar_camino(
    sesion: AsyncSession, declarada: PosicionDeclarada, tracking: "TrackingGenerado"
) -> Optional[AvisoPosicion]:
    """Aviso `PELO_DANADO` o `CABLE_SIN_USO` si el camino declarado pasa por un pelo Cortado/Dañado o
    por un cable con tendido "Sin Uso"; `None` si está sano. Nunca retira: eso lo decide
    `decidir_retiro`, que necesita los demás caminos."""
    problema = await _problema_del_camino(sesion, tracking)
    if problema is None:
        return None
    codigo, detalle = problema
    return _aviso(declarada, codigo, retirada=False, **detalle)


async def decidir_retiro(
    sesion: AsyncSession,
    aviso: AvisoPosicion,
    *,
    declarado: "TrackingGenerado",
    caminos: Sequence["TrackingGenerado"],
    es_completo: Callable[["TrackingGenerado"], bool],
) -> AvisoPosicion:
    """Marca para retiro un aviso de estado o tendido sólo si existe otro camino completo sano.

    `caminos` son los ya resueltos en esta corrida; se ignoran el declarado y los que comparten
    pelos con él (es el mismo camino sembrado desde otro pelo). `es_completo` es el criterio del
    tracking (`tracking_service.es_camino_completo`). Los avisos de inventario se devuelven tal cual.
    Si ningún alternativo está completo y sano, la declaración se mantiene y sólo se avisa.
    """
    if aviso.codigo not in (MOTIVO_PELO_DANADO, MOTIVO_CABLE_SIN_USO):
        return aviso
    pelos_declarado = _pelos_de(declarado)
    for camino in caminos:
        if camino is declarado or _pelos_de(camino) & pelos_declarado or not es_completo(camino):
            continue
        if await _problema_del_camino(sesion, camino) is None:
            return replace(
                aviso, retirada=True, detalle={**aviso.detalle, "camino_alternativo": camino.pelo_n_id}
            )
    return aviso


# ── Textos (Slack y web) ─────────────────────────────────────────────────────────────────────


def _causa_de_retiro(codigo: str, d: Mapping[str, Any]) -> Optional[str]:
    """La causa de un retiro (sin punto final), o `None` si el código no es un motivo de retiro."""
    if codigo == MOTIVO_SIN_PELO:
        return "el conector ya no tiene pelo en Cromo"
    if codigo == MOTIVO_CONECTOR_INEXISTENTE:
        return "el conector ya no está en el inventario de Cromo"
    if codigo == MOTIVO_PELO_CAMBIO:
        return f"el pelo del conector cambió en Cromo (declarado {d.get('declarado')}, ahora {d.get('actual')})"
    if codigo == MOTIVO_PELO_DANADO:
        return f"su camino pasa por el pelo {d.get('pelo')} en estado «{d.get('estado')}»"
    if codigo == MOTIVO_CABLE_SIN_USO:
        return f"su camino pasa por el cable {d.get('nombre') or d.get('cable')} con tendido «Sin Uso»"
    return None


def texto_aviso(aviso: AvisoPosicion) -> str:
    """Texto del aviso para el operador (Slack le antepone `:warning: `). Una arrastrada por su par
    (`arrastrar_par`) dice junto con cuál se retiró y la causa de esa otra."""
    pos, d = aviso.posicion, aviso.detalle
    if aviso.codigo == AVISO_CAMINO_NO_RESUELTO:
        return (
            f"No se pudo usar la posición vigente {pos}: Cromo no resolvió su camino "
            f"({d.get('motivo') or 'sin detalle'}). Se usó el cálculo automático; la declaración se mantiene."
        )
    if aviso.codigo == AVISO_CAMINO_INCOMPLETO:
        return (
            f"No se pudo usar la posición vigente {pos}: su camino no termina en ODF en ambos "
            "extremos. Se usó el cálculo automático; la declaración se mantiene."
        )
    causa = _causa_de_retiro(aviso.codigo, d)
    if causa is None:
        return f"Posición vigente {pos}: {aviso.codigo}."
    if aviso.arrastrada_con:
        return f"Se retiró la posición vigente {pos} junto con {aviso.arrastrada_con} (mismo par): {causa}."
    # Los de inventario siempre retiran; los de estado/tendido sólo con otro camino completo sano.
    if aviso.retirada or aviso.codigo in (MOTIVO_SIN_PELO, MOTIVO_CONECTOR_INEXISTENTE, MOTIVO_PELO_CAMBIO):
        return f"Se retiró la posición vigente {pos}: {causa}."
    return f"La posición vigente {pos} se mantiene, pero {causa} y no hay otro camino completo sano."


def textos_avisos(avisos: Sequence[AvisoPosicion]) -> list[str]:
    """Un texto por aviso y, si alguno retiró la declaración, una sola vez `TEXTO_CALCULO_AUTOMATICO`."""
    textos = [texto_aviso(a) for a in avisos]
    if any(a.retirada for a in avisos):
        textos.append(TEXTO_CALCULO_AUTOMATICO)
    return textos
