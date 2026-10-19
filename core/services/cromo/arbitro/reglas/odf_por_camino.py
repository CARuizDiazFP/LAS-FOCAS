# Nombre de archivo: odf_por_camino.py
# Ubicación de archivo: core/services/cromo/arbitro/reglas/odf_por_camino.py
# Descripción: Reglas ODF_POR_CAMINO y CONTRADICCION_SERVICIO del árbitro: ODF de un servicio sin ODF por evidencia de camino

"""Un Servicio del universo "sin ODF" cuyo camino llega a un conector de ODF.

Dos fuentes de conectores, leídas sólo de la base (el árbitro nunca llama a Cromo):

- **En vivo:** `app.cromo_evidencia_camino` que dejan las consultas del Registrador/web, completa y
  con menos de `EVIDENCIA_TTL_DIAS`. Cada extremo de tipo conector con `odf_id` es un conector.
- **Local:** sólo con alcance `TODO`, un BFS por `cromo_fusiones` vigentes desde los pelos del
  Servicio hasta un pelo conectado a un conector vigente. Sin camino en vivo, el puntaje topa en
  `TOPE_SOLO_LOCAL`.

`puntuar_servicio` es puro; las dos reglas comparten la carga vía `contexto["odf_por_camino"]`.
"""

from __future__ import annotations

import asyncio
import logging
from array import array
from bisect import bisect_left
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.arbitro.senales import (
    OBJETO_SERVICIO,
    Alcance,
    Evaluacion,
    Senal,
)
from core.services.cromo.camino_optico_service import TIPO_CONECTOR_ODF
from core.services.cromo.servicios_sin_odf import (
    _SQL_NO_TIENE_ODF_RESUELTA,
    _SUBQUERY_ANTI_AMBIGUEDAD,
    sugerencia_odf_para_servicio,
)

logger = logging.getLogger(__name__)

REGLA_ODF = "ODF_POR_CAMINO"
REGLA_CONTRADICCION = "CONTRADICCION_SERVICIO"
EVIDENCIA_TTL_DIAS = 30
TOPE_SOLO_LOCAL = 60

CAMINO_VIVO_COMPLETO = 45
AT62_COINCIDE = 25
CONECTOR_LIBRE = 10
HERMANOS_COINCIDEN = 15
EXTREMOS_COHERENTES = 5
FUSIONES_LOCALES = 45

VETO_ODF_SIN_FILA = "ODF_SIN_FILA"
VETO_CONECTOR_OTRO_SERVICIO = "CONECTOR_OTRO_SERVICIO"

# Corte del BFS local por Servicio (mismo criterio que la medición del 2026-10-19): un árbol PON
# puede tocar decenas de miles de pelos y no aporta un camino útil.
MAX_PELOS_BFS = 20_000

# Más de 2 ODF distintas entre los conectores válidos: el camino no es un tramo punto a punto.
_MAX_ODFS = 2

_CLAVE_CONTEXTO = "odf_por_camino"


@dataclass(frozen=True, slots=True)
class ServicioCandidato:
    id: int
    identidades: frozenset[str]
    # El BFS local se cortó en `MAX_PELOS_BFS`: puede haber conectores que no se vieron.
    bfs_truncado: bool = False


@dataclass(frozen=True, slots=True)
class ConectorVisto:
    conector_n_id: Optional[int]
    odf_n_id: int
    odf_tiene_fila: bool
    servicio_at62: Optional[str]
    pelo_conectado: Optional[int]
    servicio_resuelto: Optional[str]
    en_vivo: bool
    # Hay fila vigente del conector en `cromo_odf_conectores`. Sólo un conector inventariado con
    # `servicio_resuelto` vacío es "libre": de uno ausente no se sabe qué servicio tiene.
    en_inventario: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# Puntaje (puro)
# ─────────────────────────────────────────────────────────────────────────────


def _resuelto(conector: ConectorVisto) -> Optional[str]:
    """`servicio_resuelto` sin espacios; vacío o sólo espacios cuenta como conector libre."""
    valor = (conector.servicio_resuelto or "").strip()
    return valor or None


def _contradice(servicio: ServicioCandidato, conector: ConectorVisto) -> bool:
    resuelto = _resuelto(conector)
    return resuelto is not None and resuelto not in servicio.identidades


def _es_libre(c: ConectorVisto) -> bool:
    return c.en_inventario and _resuelto(c) is None


def _clave_objetivo(c: ConectorVisto) -> tuple[int, bool, bool, int]:
    """Desempate determinista: menor ODF; dentro de la misma, en vivo, libre y menor conector."""
    return (
        c.odf_n_id,
        not c.en_vivo,
        not _es_libre(c),
        c.conector_n_id if c.conector_n_id is not None else -1,
    )


def puntuar_servicio(
    servicio: ServicioCandidato,
    conectores: Sequence[ConectorVisto],
    odf_hermanos: Optional[int],
) -> list[Evaluacion]:
    """Evaluaciones de las dos reglas para un Servicio, a partir de los conectores que alcanza."""
    if not conectores:
        return []

    evaluaciones: list[Evaluacion] = []
    validos = [c for c in conectores if not _contradice(servicio, c)]
    contradichos = sorted(
        (c for c in conectores if _contradice(servicio, c)),
        key=lambda c: (c.odf_n_id, c.conector_n_id if c.conector_n_id is not None else -1),
    )
    odfs_contradichas = {c.odf_n_id for c in contradichos}
    if contradichos:
        # Una sola INFORMAR por Servicio: el índice de propuestas abiertas es por objeto.
        evaluaciones.append(
            Evaluacion(
                REGLA_CONTRADICCION,
                OBJETO_SERVICIO,
                servicio.id,
                "INFORMAR",
                {
                    "conectores": [
                        {
                            "conector_n_id": c.conector_n_id,
                            "odf_n_id": c.odf_n_id,
                            "servicio_conector": c.servicio_resuelto,
                        }
                        for c in contradichos
                    ]
                },
                (Senal(VETO_CONECTOR_OTRO_SERVICIO, 0, {"cantidad": len(contradichos)}),),
            )
        )

    odfs = sorted({c.odf_n_id for c in validos})
    if not validos or len(odfs) > _MAX_ODFS:
        return evaluaciones

    con_at62 = [c for c in validos if c.servicio_at62 and c.servicio_at62 in servicio.identidades]
    objetivo = min(con_at62 or validos, key=_clave_objetivo)

    # La confianza en vivo es de la ODF objetivo: un camino en vivo hacia otra ODF, o hacia un
    # conector de otro servicio, no respalda esta asociación.
    en_vivo = any(c.en_vivo and c.odf_n_id == objetivo.odf_n_id for c in validos)
    senales: list[Senal] = []
    if en_vivo:
        senales.append(Senal("CAMINO_VIVO_COMPLETO", CAMINO_VIVO_COMPLETO))
    else:
        detalle = {"truncado": True} if servicio.bfs_truncado else {}
        senales.append(Senal("FUSIONES_LOCALES", FUSIONES_LOCALES, detalle))
    if con_at62:
        senales.append(Senal("AT62_COINCIDE", AT62_COINCIDE, {"at62": objetivo.servicio_at62}))
    if _es_libre(objetivo):
        senales.append(Senal("CONECTOR_LIBRE", CONECTOR_LIBRE, {"conector_n_id": objetivo.conector_n_id}))
    if odf_hermanos is not None and odf_hermanos == objetivo.odf_n_id:
        senales.append(Senal("HERMANOS_COINCIDEN", HERMANOS_COINCIDEN))
    if len(odfs) == 2 and all(c.odf_tiene_fila for c in validos):
        senales.append(Senal("EXTREMOS_COHERENTES", EXTREMOS_COHERENTES, {"odfs": odfs}))
    if not objetivo.odf_tiene_fila:
        senales.append(Senal(VETO_ODF_SIN_FILA, 0, {"odf_n_id": objetivo.odf_n_id}, veto=True))
    if objetivo.odf_n_id in odfs_contradichas:
        senales.append(
            Senal(VETO_CONECTOR_OTRO_SERVICIO, 0, {"odf_n_id": objetivo.odf_n_id}, veto=True)
        )

    evaluaciones.append(
        Evaluacion(
            REGLA_ODF,
            OBJETO_SERVICIO,
            servicio.id,
            "ASOCIAR_ODF",
            {
                "odf_n_id": objetivo.odf_n_id,
                "pelo_n_id": objetivo.pelo_conectado,
                "odfs_extremo": odfs,
            },
            tuple(senales),
            tope=100 if en_vivo else TOPE_SOLO_LOCAL,
        )
    )
    return evaluaciones


# ─────────────────────────────────────────────────────────────────────────────
# Carga desde la base
# ─────────────────────────────────────────────────────────────────────────────

# Mismo universo que `servicios_sin_odf._PLANTILLA_LISTADO`, salvo el override: un MANUAL siempre
# saca al Servicio; uno AUTO también (ya salió del listado "sin ODF"), excepto si el Servicio está
# en observación de esta regla (`propios`), que se reevalúa ignorando su propia asociación.
_PLANTILLA_UNIVERSO = """
    WITH verificables AS (
        SELECT s.id, s.servicio_id, s.numero_primer_servicio, s.alias_ids
        FROM app.servicios s
        WHERE s.estado_servicio ILIKE 'activo'
          AND s.es_verificable = true
          AND s.numero_primer_servicio IS NOT NULL
{filtro_ids}          AND {anti_ambiguedad}
    )
    SELECT v.id, v.servicio_id, v.numero_primer_servicio, v.alias_ids
    FROM verificables v
    WHERE {no_tiene_odf}
      AND NOT EXISTS (
          SELECT 1 FROM app.cromo_servicio_odf_override o
          WHERE o.servicio_id = v.id
            AND (o.origen = 'MANUAL' OR NOT (v.id = ANY(:propios ::int[])))
      )
    ORDER BY v.id
"""

_SQL_UNIVERSO_TODO = text(
    _PLANTILLA_UNIVERSO.format(
        filtro_ids="",
        anti_ambiguedad=_SUBQUERY_ANTI_AMBIGUEDAD,
        no_tiene_odf=_SQL_NO_TIENE_ODF_RESUELTA,
    )
)
_SQL_UNIVERSO_SERVICIOS = text(
    _PLANTILLA_UNIVERSO.format(
        filtro_ids="          AND s.id = ANY(:ids ::int[])\n",
        anti_ambiguedad=_SUBQUERY_ANTI_AMBIGUEDAD,
        no_tiene_odf=_SQL_NO_TIENE_ODF_RESUELTA,
    )
)

_SQL_EXTREMOS_VIVOS = text(
    """
    SELECT e.servicio_id,
           (x.extremo->>'id_cromo')::bigint AS conector_n_id,
           (x.extremo->>'odf_id')::bigint AS odf_id,
           x.extremo->>'servicio_at62' AS servicio_at62,
           (x.extremo->>'pelo_conectado')::bigint AS pelo_conectado
    FROM app.cromo_evidencia_camino e
    CROSS JOIN LATERAL jsonb_array_elements(e.extremos) AS x(extremo)
    WHERE e.completo
      AND e.generado_at >= now() - make_interval(days => :ttl)
      AND e.servicio_id = ANY(:sids ::int[])
      AND x.extremo->>'tipo' = :tipo_conector
      AND x.extremo->>'odf_id' IS NOT NULL
    ORDER BY e.generado_at, e.pelo_n_id
    """
)

# `odf_id` de un extremo puede ser el `version_id` de la ODF; se resuelve al `n_id`. Una ODF no
# vigente cuenta como sin fila (veto `ODF_SIN_FILA`).
_SQL_RESOLVER_ODFS = text(
    """
    SELECT n_id, version_id FROM app.cromo_odfs
    WHERE vigente AND (n_id = ANY(:ids ::bigint[]) OR version_id = ANY(:ids ::bigint[]))
    """
)

# Un conector en vivo que no está (o no está vigente) en `cromo_odf_conectores` queda con
# `en_inventario=False`: no contradice, pero tampoco suma `CONECTOR_LIBRE`.
_SQL_CONECTORES_POR_ID = text(
    """
    SELECT n_id, servicio_resuelto FROM app.cromo_odf_conectores
    WHERE vigente AND n_id = ANY(:ids ::bigint[])
    """
)

_SQL_SEMILLAS = text(
    """
    SELECT m.servicio_id, m.pelo_n_id
    FROM app.v_cromo_servicio_match_vigente m
    JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id AND p.vigente
    WHERE m.servicio_id = ANY(:sids ::int[])
    """
)

_SQL_ARISTAS = text(
    """
    SELECT a, b FROM (
        SELECT pelo_a_n_id AS a, pelo_b_n_id AS b FROM app.cromo_fusiones
        WHERE vigente AND pelo_a_n_id IS NOT NULL AND pelo_b_n_id IS NOT NULL
        UNION ALL
        SELECT pelo_b_n_id, pelo_a_n_id FROM app.cromo_fusiones
        WHERE vigente AND pelo_a_n_id IS NOT NULL AND pelo_b_n_id IS NOT NULL
    ) t
    ORDER BY a
    """
)

_SQL_INDICE_CONECTORES = text(
    """
    SELECT pelo_n_id, n_id, odf_n_id, servicio_resuelto, servicio_numero_atributo
    FROM app.cromo_odf_conectores
    WHERE vigente AND pelo_n_id IS NOT NULL
    """
)


class _GrafoFusiones:
    """Adyacencia de pelos por fusiones vigentes en formato CSR (tres `array('q')`).

    ~1M aristas dirigidas en dev: ~20 MB, contra ~150 MB de un `dict[int, list[int]]`.
    """

    __slots__ = ("claves", "inicios", "vecinos")

    def __init__(self) -> None:
        self.claves = array("q")
        self.inicios = array("q")
        self.vecinos = array("q")

    def agregar(self, a: int, b: int) -> None:
        """Las aristas deben llegar ordenadas por `a`."""
        if not self.claves or self.claves[-1] != a:
            self.claves.append(a)
            self.inicios.append(len(self.vecinos))
        self.vecinos.append(b)

    def de(self, pelo: int) -> Iterable[int]:
        i = bisect_left(self.claves, pelo)
        if i == len(self.claves) or self.claves[i] != pelo:
            return ()
        fin = self.inicios[i + 1] if i + 1 < len(self.inicios) else len(self.vecinos)
        return self.vecinos[self.inicios[i] : fin]


# pelo_n_id -> [(conector n_id, odf_n_id, servicio_resuelto, at62)]
_IndiceConectores = dict[int, list[tuple[int, int, Optional[str], Optional[str]]]]


async def _cargar_grafo(sesion: AsyncSession) -> tuple[_GrafoFusiones, _IndiceConectores]:
    grafo = _GrafoFusiones()
    resultado = await sesion.stream(_SQL_ARISTAS)
    async for filas in resultado.partitions(50_000):
        for a, b in filas:
            grafo.agregar(int(a), int(b))
    indice: _IndiceConectores = {}
    for pelo, n_id, odf, resuelto, at62 in (await sesion.execute(_SQL_INDICE_CONECTORES)).all():
        indice.setdefault(int(pelo), []).append((int(n_id), int(odf), resuelto, at62))
    logger.info(
        "action=arbitro_cromo evento=grafo_fusiones_cargado pelos=%s aristas=%s pelos_con_conector=%s",
        len(grafo.claves),
        len(grafo.vecinos),
        len(indice),
    )
    return grafo, indice


def _bfs_conectores(
    semillas: Iterable[int],
    grafo: _GrafoFusiones,
    indice: _IndiceConectores,
    limite: int = MAX_PELOS_BFS,
) -> tuple[list[tuple[int, tuple[int, int, Optional[str], Optional[str]]]], bool]:
    """((pelo, conector) alcanzados desde las semillas, si se cortó en `limite` pelos)."""
    visitados: set[int] = set()
    cola: deque[int] = deque()
    for s in semillas:
        if s not in visitados:
            visitados.add(s)
            cola.append(s)
    hallados = []
    while cola:
        pelo = cola.popleft()
        for conector in indice.get(pelo, ()):
            hallados.append((pelo, conector))
        for vecino in grafo.de(pelo):
            if vecino not in visitados:
                if len(visitados) >= limite:
                    return hallados, True
                visitados.add(vecino)
                cola.append(vecino)
    return hallados, False


def _bfs_por_servicio(
    semillas: dict[int, list[int]], grafo: _GrafoFusiones, indice: _IndiceConectores
) -> dict[int, tuple[list[tuple[int, tuple[int, int, Optional[str], Optional[str]]]], bool]]:
    return {sid: _bfs_conectores(pelos, grafo, indice) for sid, pelos in semillas.items()}


def _identidades(servicio_id, numero, alias) -> frozenset[str]:
    valores = [servicio_id, numero, *(alias or ())]
    return frozenset(v for v in valores if v)


async def _resolver_odfs(sesion: AsyncSession, ids: set[int]) -> dict[int, int]:
    """id crudo (n_id o version_id) -> n_id; prioriza la coincidencia por `n_id`."""
    if not ids:
        return {}
    filas = (await sesion.execute(_SQL_RESOLVER_ODFS, {"ids": sorted(ids)})).all()
    mapa: dict[int, int] = {}
    for n_id, version_id in filas:
        mapa.setdefault(int(version_id), int(n_id))
    for n_id, _ in filas:
        mapa[int(n_id)] = int(n_id)
    return mapa


async def _cargar(
    sesion: AsyncSession,
    alcance: Alcance,
    propios: frozenset[int],
    *,
    contexto: Optional[dict[str, Any]] = None,
) -> dict[int, tuple[ServicioCandidato, list[ConectorVisto], Optional[int]]]:
    """Servicio del universo -> (candidato, conectores alcanzados, ODF sugerida por hermanos)."""
    if alcance.tipo == "TODO":
        filas = (await sesion.execute(_SQL_UNIVERSO_TODO, {"propios": sorted(propios)})).all()
    elif alcance.tipo == "SERVICIOS":
        if not alcance.ids:
            return {}
        filas = (
            await sesion.execute(
                _SQL_UNIVERSO_SERVICIOS, {"ids": list(alcance.ids), "propios": sorted(propios)}
            )
        ).all()
    else:
        return {}

    candidatos = {
        int(f.id): ServicioCandidato(
            int(f.id), _identidades(f.servicio_id, f.numero_primer_servicio, f.alias_ids)
        )
        for f in filas
    }
    if not candidatos:
        return {}
    sids = sorted(candidatos)

    # En vivo.
    vivos = (
        await sesion.execute(
            _SQL_EXTREMOS_VIVOS,
            {"ttl": EVIDENCIA_TTL_DIAS, "sids": sids, "tipo_conector": TIPO_CONECTOR_ODF},
        )
    ).all()

    # Local (sólo TODO).
    locales: dict[int, list[tuple[int, tuple[int, int, Optional[str], Optional[str]]]]] = {}
    truncados: set[int] = set()
    if alcance.tipo == "TODO":
        cache = contexto.setdefault(_CLAVE_CONTEXTO, {}) if contexto is not None else {}
        if "grafo" not in cache:
            cache["grafo"] = await _cargar_grafo(sesion)
        grafo, indice = cache["grafo"]
        semillas: dict[int, list[int]] = {}
        for sid, pelo in (await sesion.execute(_SQL_SEMILLAS, {"sids": sids})).all():
            semillas.setdefault(int(sid), []).append(int(pelo))
        recorridos = await asyncio.to_thread(_bfs_por_servicio, semillas, grafo, indice)
        for sid, (hallados, truncado) in recorridos.items():
            locales[sid] = hallados
            if truncado:
                truncados.add(sid)
                logger.info(
                    "action=arbitro_cromo evento=bfs_truncado servicio_id=%s limite=%s",
                    sid,
                    MAX_PELOS_BFS,
                )

    ids_odf = {int(v.odf_id) for v in vivos}
    ids_odf |= {c[1] for hallados in locales.values() for _, c in hallados}
    odfs = await _resolver_odfs(sesion, ids_odf)

    ids_conector_vivo = sorted({int(v.conector_n_id) for v in vivos if v.conector_n_id is not None})
    resueltos: dict[int, Optional[str]] = {}
    if ids_conector_vivo:
        resueltos = {
            int(n): r
            for n, r in (
                await sesion.execute(_SQL_CONECTORES_POR_ID, {"ids": ids_conector_vivo})
            ).all()
        }

    por_servicio: dict[int, dict[tuple[Optional[int], int], ConectorVisto]] = {}
    for v in vivos:
        crudo = int(v.odf_id)
        conector = int(v.conector_n_id) if v.conector_n_id is not None else None
        visto = ConectorVisto(
            conector_n_id=conector,
            odf_n_id=odfs.get(crudo, crudo),
            odf_tiene_fila=crudo in odfs,
            servicio_at62=v.servicio_at62,
            pelo_conectado=int(v.pelo_conectado) if v.pelo_conectado is not None else None,
            servicio_resuelto=resueltos.get(conector) if conector is not None else None,
            en_vivo=True,
            en_inventario=conector is not None and conector in resueltos,
        )
        # Filas ordenadas por `generado_at`: si varias evidencias reportan el mismo conector, gana
        # la más nueva.
        por_servicio.setdefault(int(v.servicio_id), {})[(conector, visto.odf_n_id)] = visto
    for sid, hallados in locales.items():
        vistos = por_servicio.setdefault(sid, {})
        for pelo, (conector, odf, resuelto, at62) in hallados:
            # Mismo mapeo que en vivo: el `odf_n_id` del conector se resuelve contra `cromo_odfs`.
            odf_n_id = odfs.get(odf, odf)
            # El camino en vivo manda: un conector ya visto en vivo no se pisa con el local.
            vistos.setdefault(
                (conector, odf_n_id),
                ConectorVisto(
                    conector_n_id=conector,
                    odf_n_id=odf_n_id,
                    odf_tiene_fila=odf in odfs,
                    servicio_at62=at62,
                    pelo_conectado=pelo,
                    servicio_resuelto=resuelto,
                    en_vivo=False,
                ),
            )

    salida: dict[int, tuple[ServicioCandidato, list[ConectorVisto], Optional[int]]] = {}
    for sid in sids:
        conectores = sorted(
            (por_servicio.get(sid) or {}).values(),
            key=lambda c: (c.odf_n_id, c.conector_n_id if c.conector_n_id is not None else -1),
        )
        hermanos: Optional[int] = None
        if conectores:
            sugerencia = await sugerencia_odf_para_servicio(sesion, sid)
            hermanos = sugerencia.odf_n_id if sugerencia is not None else None
        candidato = candidatos[sid]
        if sid in truncados:
            candidato = ServicioCandidato(candidato.id, candidato.identidades, bfs_truncado=True)
        salida[sid] = (candidato, conectores, hermanos)

    logger.info(
        "action=arbitro_cromo evento=odf_por_camino_cargado alcance=%s servicios=%s con_conectores=%s",
        alcance.tipo,
        len(salida),
        sum(1 for _, c, _ in salida.values() if c),
    )
    return salida


async def _cargar_cacheado(
    sesion: AsyncSession, alcance: Alcance, propios: frozenset[int], contexto: dict[str, Any]
) -> dict[int, tuple[ServicioCandidato, list[ConectorVisto], Optional[int]]]:
    cache = contexto.setdefault(_CLAVE_CONTEXTO, {})
    cargas = cache.setdefault("cargas", {})
    clave = (alcance, propios)
    if clave not in cargas:
        cargas[clave] = await _cargar(sesion, alcance, propios, contexto=contexto)
    return cargas[clave]


async def _evaluar_regla(
    codigo: str,
    sesion: AsyncSession,
    alcance: Alcance,
    propios: frozenset[int],
    contexto: dict[str, Any],
) -> list[Evaluacion]:
    datos = await _cargar_cacheado(sesion, alcance, propios, contexto)
    return [
        ev
        for servicio, conectores, hermanos in datos.values()
        for ev in puntuar_servicio(servicio, conectores, hermanos)
        if ev.regla == codigo
    ]


class ReglaOdfPorCamino:
    codigo = REGLA_ODF

    async def evaluar(
        self,
        sesion: AsyncSession,
        alcance: Alcance,
        *,
        propios: frozenset[int],
        contexto: dict[str, Any],
    ) -> list[Evaluacion]:
        return await _evaluar_regla(self.codigo, sesion, alcance, propios, contexto)


class ReglaContradiccionServicio:
    codigo = REGLA_CONTRADICCION

    async def evaluar(
        self,
        sesion: AsyncSession,
        alcance: Alcance,
        *,
        propios: frozenset[int],
        contexto: dict[str, Any],
    ) -> list[Evaluacion]:
        return await _evaluar_regla(self.codigo, sesion, alcance, propios, contexto)


__all__ = [
    "AT62_COINCIDE",
    "CAMINO_VIVO_COMPLETO",
    "CONECTOR_LIBRE",
    "EVIDENCIA_TTL_DIAS",
    "EXTREMOS_COHERENTES",
    "FUSIONES_LOCALES",
    "HERMANOS_COINCIDEN",
    "MAX_PELOS_BFS",
    "REGLA_CONTRADICCION",
    "REGLA_ODF",
    "TOPE_SOLO_LOCAL",
    "VETO_CONECTOR_OTRO_SERVICIO",
    "VETO_ODF_SIN_FILA",
    "ConectorVisto",
    "ReglaContradiccionServicio",
    "ReglaOdfPorCamino",
    "ServicioCandidato",
    "puntuar_servicio",
]
