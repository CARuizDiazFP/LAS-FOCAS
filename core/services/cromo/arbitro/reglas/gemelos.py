# Nombre de archivo: gemelos.py
# Ubicación de archivo: core/services/cromo/arbitro/reglas/gemelos.py
# Descripción: Reglas GEMELO_VACIO, GEMELO_OPERATIVO y ODF_GEMELA_ISLA del árbitro: homónimos cruzados con islas

"""Cruce de la detección de homónimos con el detector de islas.

- **Botellas:** `cromo_botellas` vigentes agrupadas por `(normalizar_para_agrupar_extendido(nombre),
  clase)` (sin exigir Cámara padre; nunca se mezclan clases, p. ej. botella 68 con caja PON 121-125). Con una sola operativa (con cables), cada vacía (sin cables ni
  fusiones) se propone fusionar en ella (`GEMELO_VACIO`); un miembro isla se informa en vez de
  fusionarse. Con 2 o más operativas se informa el grupo (`GEMELO_OPERATIVO`).
- **ODF:** cada caso `ELEMENTO_ISLA` de clase 69/86 en estado PENDIENTE o CUARENTENA contra las `cromo_odfs` vigentes con el mismo
  `lower(trim(nombre))` (`ODF_GEMELA_ISLA`, sólo informa). Una sola evaluación por isla, con la
  gemela de mayor puntaje (desempate: menor `n_id`).

`puntuar_grupo_botellas` y `puntuar_odf_isla` son puros; las tres reglas comparten la carga vía
`contexto["gemelos"]`. El árbitro nunca llama a Cromo: todo sale de la base.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.camara_hierarchy_service import normalizar_para_agrupar_extendido
from core.services.cromo.arbitro.senales import (
    OBJETO_BOTELLA,
    OBJETO_ODF,
    USUARIO_ARBITRO,
    Alcance,
    Evaluacion,
    Senal,
    puntaje,
)
from core.services.cromo.verificador import tiene_cables_asociados_batch_sync

logger = logging.getLogger(__name__)

REGLA_GEMELO_VACIO = "GEMELO_VACIO"
REGLA_GEMELO_OPERATIVO = "GEMELO_OPERATIVO"
REGLA_ODF_GEMELA_ISLA = "ODF_GEMELA_ISLA"

MISMA_LOCALIDAD = 20
CERCA_50M = 30
CERCA_300M = 10
VACIA_SIN_FUSIONES = 30
MISMA_CAMARA = 15
COMPARTEN_CABLES = 40
CABLES_DISJUNTOS = -30

VETO_LEJOS_300M = "LEJOS_300M"
VETO_SEPARADA_MANUAL = "SEPARADA_MANUAL"
VETO_ALIAS_PREVIO = "ALIAS_PREVIO"

_RADIO_TIERRA_M = 6_371_008.8
_CLAVE_CONTEXTO = "gemelos"
_ESTADOS_ISLA = ("PENDIENTE", "CUARENTENA")
_CLASES_ODF_ISLA = (69, 86)


@dataclass(frozen=True, slots=True)
class MiembroGemelo:
    n_id: int
    nombre: str
    localidad: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    camara_id: Optional[int]
    con_cables: bool
    con_fusiones: bool
    es_isla: bool
    separada_manualmente: bool
    alias_previo: bool
    cables: frozenset[int]


# ─────────────────────────────────────────────────────────────────────────────
# Puntaje (puro)
# ─────────────────────────────────────────────────────────────────────────────


def distancia_m(a: MiembroGemelo, b: MiembroGemelo) -> Optional[float]:
    """Distancia haversine en metros; `None` si falta alguna coordenada."""
    if a.lat is None or a.lon is None or b.lat is None or b.lon is None:
        return None
    fi1, fi2 = math.radians(a.lat), math.radians(b.lat)
    dfi = fi2 - fi1
    dlambda = math.radians(b.lon - a.lon)
    h = math.sin(dfi / 2) ** 2 + math.cos(fi1) * math.cos(fi2) * math.sin(dlambda / 2) ** 2
    return 2 * _RADIO_TIERRA_M * math.asin(min(1.0, math.sqrt(h)))


def _localidad(m: MiembroGemelo) -> Optional[str]:
    valor = (m.localidad or "").strip().lower()
    return valor or None


def senales_de_cercania(a: MiembroGemelo, b: MiembroGemelo) -> list[Senal]:
    senales: list[Senal] = []
    loc_a = _localidad(a)
    if loc_a is not None and loc_a == _localidad(b):
        senales.append(Senal("MISMA_LOCALIDAD", MISMA_LOCALIDAD, {"localidad": loc_a}))
    distancia = distancia_m(a, b)
    if distancia is not None:
        detalle = {"metros": round(distancia, 1)}
        if distancia <= 50:
            senales.append(Senal("CERCA_50M", CERCA_50M, detalle))
        elif distancia <= 300:
            senales.append(Senal("CERCA_300M", CERCA_300M, detalle))
        else:
            senales.append(Senal(VETO_LEJOS_300M, 0, detalle, veto=True))
    if a.camara_id is not None and a.camara_id == b.camara_id:
        senales.append(Senal("MISMA_CAMARA", MISMA_CAMARA, {"camara_id": a.camara_id}))
    return senales


def _es_vacia(m: MiembroGemelo) -> bool:
    return not m.con_cables and not m.con_fusiones


def _evaluacion_gemelo(m: MiembroGemelo, destino: MiembroGemelo, accion: str) -> Evaluacion:
    senales: list[Senal] = []
    if _es_vacia(m):
        senales.append(Senal("VACIA_SIN_FUSIONES", VACIA_SIN_FUSIONES))
    senales.extend(senales_de_cercania(m, destino))
    separadas = sorted(x.n_id for x in (m, destino) if x.separada_manualmente)
    if separadas:
        senales.append(Senal(VETO_SEPARADA_MANUAL, 0, {"n_ids": separadas}, veto=True))
    con_alias = sorted(x.n_id for x in (m, destino) if x.alias_previo)
    if con_alias:
        senales.append(Senal(VETO_ALIAS_PREVIO, 0, {"n_ids": con_alias}, veto=True))
    return Evaluacion(
        REGLA_GEMELO_VACIO,
        OBJETO_BOTELLA,
        m.n_id,
        accion,
        {"origen": m.n_id, "destino": destino.n_id},
        tuple(senales),
    )


def puntuar_grupo_botellas(miembros: Sequence[MiembroGemelo]) -> list[Evaluacion]:
    """Evaluaciones de un grupo de Botellas homónimas.

    - Con exactamente 1 operativa, cada vacía propone `FUSIONAR_GEMELO` en ella.
    - Con exactamente 1 operativa no-isla, cada miembro isla se `INFORMAR` en vez de fusionarse
      (el índice de propuestas abiertas admite una sola por regla y objeto). La señal
      `VACIA_SIN_FUSIONES` se agrega sólo si la isla realmente está vacía (sin cables ni fusiones).
    - Con 2 o más operativas, una `GEMELO_OPERATIVO` sobre la de menor `n_id`; `miembros` lista sólo
      las operativas (las vacías de ese grupo no reciben evaluación).
    """
    ordenados = sorted(miembros, key=lambda m: m.n_id)
    operativas = [m for m in ordenados if m.con_cables]
    no_isla = [m for m in operativas if not m.es_isla]
    evaluaciones: list[Evaluacion] = []

    destino: Optional[MiembroGemelo] = None
    if len(operativas) == 1:
        destino = operativas[0]
    elif len(no_isla) == 1:
        destino = no_isla[0]
    if destino is not None:
        for m in ordenados:
            if m.n_id == destino.n_id:
                continue
            if m.es_isla and not destino.es_isla:
                evaluaciones.append(_evaluacion_gemelo(m, destino, "INFORMAR"))
            elif len(operativas) == 1 and _es_vacia(m):
                evaluaciones.append(_evaluacion_gemelo(m, destino, "FUSIONAR_GEMELO"))

    if len(operativas) >= 2:
        compartidos = sorted(
            {
                c
                for i, a in enumerate(operativas)
                for b in operativas[i + 1 :]
                for c in a.cables & b.cables
            }
        )
        senales: list[Senal] = [
            Senal("COMPARTEN_CABLES", COMPARTEN_CABLES, {"cables": compartidos})
            if compartidos
            else Senal("CABLES_DISJUNTOS", CABLES_DISJUNTOS)
        ]
        senales.extend(senales_de_cercania(operativas[0], operativas[1]))
        evaluaciones.append(
            Evaluacion(
                REGLA_GEMELO_OPERATIVO,
                OBJETO_BOTELLA,
                operativas[0].n_id,
                "INFORMAR",
                {"miembros": [m.n_id for m in operativas]},
                tuple(senales),
            )
        )
    return evaluaciones


def puntuar_odf_isla(isla: MiembroGemelo, gemela: MiembroGemelo) -> Evaluacion:
    return Evaluacion(
        REGLA_ODF_GEMELA_ISLA,
        OBJETO_ODF,
        isla.n_id,
        "INFORMAR",
        {"isla": isla.n_id, "gemela": gemela.n_id},
        tuple(senales_de_cercania(isla, gemela)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Carga desde la base
# ─────────────────────────────────────────────────────────────────────────────

_SQL_NOMBRES_BOTELLAS = text(
    """
    SELECT n_id, nombre, clase
    FROM app.cromo_botellas
    WHERE (vigente OR n_id = ANY(:propios ::bigint[]))
      AND nombre IS NOT NULL AND btrim(nombre) <> ''
    """
)

_SQL_DETALLE_BOTELLAS = text(
    """
    SELECT b.n_id, b.nombre, b.localidad, b.latitud, b.longitud, b.camara_id, b.separada_manualmente,
           EXISTS (
               SELECT 1 FROM app.cromo_fusiones f WHERE f.botella_n_id = b.n_id AND f.vigente
           ) AS con_fusiones,
           EXISTS (
               SELECT 1 FROM app.cromo_inconsistencia i
               WHERE i.tipo = 'ELEMENTO_ISLA' AND i.objeto_n_id = b.n_id
                 AND i.estado = ANY(:estados_isla ::text[])
           ) AS es_isla,
           EXISTS (
               SELECT 1 FROM app.cromo_botella_alias a
               WHERE a.id_cromo_origen = b.n_id
                 -- IS NOT DISTINCT FROM: un alias con creado_por NULL no es del árbitro y veta.
                 AND NOT (a.creado_por IS NOT DISTINCT FROM :usuario
                          AND a.id_cromo_origen = ANY(:propios ::bigint[]))
           ) AS alias_previo
    FROM app.cromo_botellas b
    WHERE b.n_id = ANY(:ids ::bigint[])
    """
)

_SQL_CABLES_DE_BOTELLAS = text(
    """
    SELECT n_id, extremo_a_n_id AS extremo FROM app.cromo_cables
    WHERE vigente AND extremo_a_n_id = ANY(:ids ::bigint[])
    UNION
    SELECT n_id, extremo_b_n_id AS extremo FROM app.cromo_cables
    WHERE vigente AND extremo_b_n_id = ANY(:ids ::bigint[])
    """
)

_SQL_ODF_ISLAS = text(
    """
    SELECT i.objeto_n_id, COALESCE(o.nombre, i.nombre) AS nombre,
           COALESCE(o.localidad, i.localidad) AS localidad, o.latitud, o.longitud,
           g.n_id AS g_n_id, g.nombre AS g_nombre, g.localidad AS g_localidad,
           g.latitud AS g_latitud, g.longitud AS g_longitud
    FROM app.cromo_inconsistencia i
    LEFT JOIN app.cromo_odfs o ON o.n_id = i.objeto_n_id
    JOIN app.cromo_odfs g
      ON g.vigente
     AND g.n_id <> i.objeto_n_id
     AND lower(btrim(g.nombre)) = lower(btrim(COALESCE(o.nombre, i.nombre)))
    WHERE i.tipo = 'ELEMENTO_ISLA'
      AND i.objeto_clase = ANY(:clases ::smallint[])
      AND i.estado = ANY(:estados_isla ::text[])
      AND btrim(COALESCE(o.nombre, i.nombre, '')) <> ''
      AND (:todas OR i.objeto_n_id = ANY(:ids ::bigint[]))
    """
)


def _odf(n_id: int, nombre: Optional[str], localidad, lat, lon, *, es_isla: bool) -> MiembroGemelo:
    return MiembroGemelo(
        n_id=n_id,
        nombre=nombre or "",
        localidad=localidad,
        lat=lat,
        lon=lon,
        camara_id=None,
        con_cables=False,
        con_fusiones=False,
        es_isla=es_isla,
        separada_manualmente=False,
        alias_previo=False,
        cables=frozenset(),
    )


async def _cargar_grupos_botellas(
    sesion: AsyncSession, alcance: Alcance, propios: frozenset[int]
) -> list[list[MiembroGemelo]]:
    propios_lista = sorted(propios)
    filas = (await sesion.execute(_SQL_NOMBRES_BOTELLAS, {"propios": propios_lista})).all()
    # La clase es parte de la clave: una caja PON nunca es gemela de una botella homónima.
    por_clave: dict[tuple[str, int], list[int]] = defaultdict(list)
    for n_id, nombre, clase in filas:
        clave = normalizar_para_agrupar_extendido(nombre)
        if clave:
            por_clave[(clave, clase)].append(n_id)
    grupos_ids = [ids for ids in por_clave.values() if len(ids) >= 2]
    if alcance.tipo == "BOTELLAS":
        pedidos = set(alcance.ids)
        grupos_ids = [ids for ids in grupos_ids if pedidos.intersection(ids)]
    ids = sorted({n for grupo in grupos_ids for n in grupo})
    if not ids:
        return []

    detalle = (
        await sesion.execute(
            _SQL_DETALLE_BOTELLAS,
            {
                "ids": ids,
                "propios": propios_lista,
                "usuario": USUARIO_ARBITRO,
                "estados_isla": list(_ESTADOS_ISLA),
            },
        )
    ).mappings().all()
    con_cables = await sesion.run_sync(lambda s: tiene_cables_asociados_batch_sync(s, ids))
    cables: dict[int, set[int]] = defaultdict(set)
    for cable_n_id, extremo in (await sesion.execute(_SQL_CABLES_DE_BOTELLAS, {"ids": ids})).all():
        cables[extremo].add(cable_n_id)

    miembros = {
        f["n_id"]: MiembroGemelo(
            n_id=f["n_id"],
            nombre=f["nombre"] or "",
            localidad=f["localidad"],
            lat=f["latitud"],
            lon=f["longitud"],
            camara_id=f["camara_id"],
            con_cables=f["n_id"] in con_cables,
            con_fusiones=bool(f["con_fusiones"]),
            es_isla=bool(f["es_isla"]),
            separada_manualmente=bool(f["separada_manualmente"]),
            alias_previo=bool(f["alias_previo"]),
            cables=frozenset(cables.get(f["n_id"], ())),
        )
        for f in detalle
    }
    return [[miembros[n] for n in sorted(grupo) if n in miembros] for grupo in grupos_ids]


async def _cargar_odf_islas(
    sesion: AsyncSession, alcance: Alcance
) -> list[tuple[MiembroGemelo, list[MiembroGemelo]]]:
    filas = (
        await sesion.execute(
            _SQL_ODF_ISLAS,
            {
                "clases": list(_CLASES_ODF_ISLA),
                "estados_isla": list(_ESTADOS_ISLA),
                "todas": alcance.tipo == "TODO",
                "ids": list(alcance.ids),
            },
        )
    ).mappings().all()
    islas: dict[int, tuple[MiembroGemelo, list[MiembroGemelo]]] = {}
    for f in filas:
        n_id = f["objeto_n_id"]
        if n_id not in islas:
            isla = _odf(n_id, f["nombre"], f["localidad"], f["latitud"], f["longitud"], es_isla=True)
            islas[n_id] = (isla, [])
        islas[n_id][1].append(
            _odf(
                f["g_n_id"], f["g_nombre"], f["g_localidad"], f["g_latitud"], f["g_longitud"],
                es_isla=False,
            )
        )
    return [islas[n] for n in sorted(islas)]


def _mejor_odf(isla: MiembroGemelo, gemelas: Sequence[MiembroGemelo]) -> Evaluacion:
    """Una sola evaluación por isla: la gemela de mayor puntaje; empate, la de menor `n_id`."""
    evaluaciones = [puntuar_odf_isla(isla, g) for g in sorted(gemelas, key=lambda g: g.n_id)]
    return max(evaluaciones, key=lambda ev: puntaje(ev.senales, ev.tope))


async def _evaluaciones_botellas(
    sesion: AsyncSession, alcance: Alcance, propios: frozenset[int], contexto: dict[str, Any]
) -> list[Evaluacion]:
    cargas = contexto.setdefault(_CLAVE_CONTEXTO, {}).setdefault("botellas", {})
    clave = (alcance, propios)
    if clave not in cargas:
        grupos = await _cargar_grupos_botellas(sesion, alcance, propios)
        # Con alcance BOTELLAS el grupo que contiene un id pedido se evalúa entero.
        evaluaciones = [ev for grupo in grupos for ev in puntuar_grupo_botellas(grupo)]
        cargas[clave] = evaluaciones
        logger.info(
            "action=arbitro_cromo evento=gemelos_botellas_cargado alcance=%s grupos=%s evaluaciones=%s",
            alcance.tipo,
            len(grupos),
            len(evaluaciones),
        )
    return cargas[clave]


async def _evaluaciones_odf(
    sesion: AsyncSession, alcance: Alcance, contexto: dict[str, Any]
) -> list[Evaluacion]:
    cargas = contexto.setdefault(_CLAVE_CONTEXTO, {}).setdefault("odf", {})
    if alcance not in cargas:
        islas = await _cargar_odf_islas(sesion, alcance)
        cargas[alcance] = [_mejor_odf(isla, gemelas) for isla, gemelas in islas]
        logger.info(
            "action=arbitro_cromo evento=gemelos_odf_cargado alcance=%s islas=%s",
            alcance.tipo,
            len(islas),
        )
    return cargas[alcance]


class ReglaGemeloVacio:
    codigo = REGLA_GEMELO_VACIO

    async def evaluar(
        self,
        sesion: AsyncSession,
        alcance: Alcance,
        *,
        propios: frozenset[int],
        contexto: dict[str, Any],
    ) -> list[Evaluacion]:
        if alcance.tipo not in ("TODO", "BOTELLAS"):
            return []
        evaluaciones = await _evaluaciones_botellas(sesion, alcance, propios, contexto)
        return [ev for ev in evaluaciones if ev.regla == self.codigo]


class ReglaGemeloOperativo:
    codigo = REGLA_GEMELO_OPERATIVO

    async def evaluar(
        self,
        sesion: AsyncSession,
        alcance: Alcance,
        *,
        propios: frozenset[int],
        contexto: dict[str, Any],
    ) -> list[Evaluacion]:
        if alcance.tipo not in ("TODO", "BOTELLAS"):
            return []
        evaluaciones = await _evaluaciones_botellas(sesion, alcance, propios, contexto)
        return [ev for ev in evaluaciones if ev.regla == self.codigo]


class ReglaOdfGemelaIsla:
    codigo = REGLA_ODF_GEMELA_ISLA

    async def evaluar(
        self,
        sesion: AsyncSession,
        alcance: Alcance,
        *,
        propios: frozenset[int],
        contexto: dict[str, Any],
    ) -> list[Evaluacion]:
        if alcance.tipo not in ("TODO", "ODFS"):
            return []
        return await _evaluaciones_odf(sesion, alcance, contexto)


__all__ = [
    "CABLES_DISJUNTOS",
    "CERCA_300M",
    "CERCA_50M",
    "COMPARTEN_CABLES",
    "MISMA_CAMARA",
    "MISMA_LOCALIDAD",
    "REGLA_GEMELO_OPERATIVO",
    "REGLA_GEMELO_VACIO",
    "REGLA_ODF_GEMELA_ISLA",
    "VACIA_SIN_FUSIONES",
    "VETO_ALIAS_PREVIO",
    "VETO_LEJOS_300M",
    "VETO_SEPARADA_MANUAL",
    "MiembroGemelo",
    "ReglaGemeloOperativo",
    "ReglaGemeloVacio",
    "ReglaOdfGemelaIsla",
    "distancia_m",
    "puntuar_grupo_botellas",
    "puntuar_odf_isla",
    "senales_de_cercania",
]
