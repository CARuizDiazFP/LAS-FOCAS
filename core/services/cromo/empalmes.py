# Nombre de archivo: empalmes.py
# Ubicación de archivo: core/services/cromo/empalmes.py
# Descripción: Empalmes (fusiones) internos de una Botella Cromo, aplanados para la tabla del verificador, con detección de Splitters

"""Resuelve "mostrame los empalmes de esta Botella" a partir de `app.cromo_fusiones` ya ingerido —
sin llamar nunca a Cromo. Distinto de `verificador.servicios_por_botella` (qué servicios pasan por
los cables que tienen esta botella como extremo): acá el foco es la topología interna de fusiones
pelo↔pelo dentro de la botella.

Hallazgo real (sondeo 2026-08-22 contra `lasfocasdev-postgres`, ver `docs/modulo_ingesta_cromo.md`):

- `app.cromo_fusiones` NUNCA tiene `botella_n_id` poblado en la práctica: el único camino que lo
  completaría (fusiones embebidas en `botella.inner[]`) no ocurre en el dataset real (Etapa 8), y el
  barrido directo de clase 132 no trae `parent`. Por eso acá se resuelve la pertenencia de una fusión
  a una botella de forma indirecta: una fusión "pertenece" a la botella si al menos uno de sus dos
  pelos está en un cable que tiene esa botella como extremo A o B (mismo join que ya usa
  `verificador._SQL_CABLES_DE_BOTELLA`) — más el join directo por `botella_n_id` por si algún día ese
  camino aparece con datos reales (lectura sin costo, no rompe nada si sigue vacío).
- Los "Splitter" no son una clase Cromo propia homologada en `app.cromo_clases` (sólo hay BOTELLA/
  CABLE/TUBO/PELO/FUSION) — no hay un ID de clase que detectar. La única señal real observada en
  `nombre_par` (at.84) para fusiones de splitter es un prefijo "S" (ej. "S7-1", "S4-1", contra sólo 2
  filas reales en toda la base dev), con un solo pelo resuelto (el otro lado del par es el propio
  componente splitter, que Cromo no modela como pelo). Señal estructural más robusta, agnóstica del
  prefijo: un mismo pelo (`n_id`) que aparece en 2 o más filas de `cromo_fusiones` de la misma botella
  es el pelo de entrada de un Splitter (fan-out 1 a N) — se agrupa en una sola fila con
  `es_splitter=True` y `splitter_ratio=N`. El prefijo "S" se usa sólo como señal secundaria para el
  caso (visto en datos reales) de una pata aislada con referencia colgada, sin par para agrupar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.verificador import ObjetoNoEncontrado

# "S7-1", "s4-1" — prefijo "S" seguido de dígitos, guion, dígitos. Señal secundaria, ver docstring.
_REGEX_NOMBRE_PAR_SPLITTER = re.compile(r"^[Ss]\d+-\d+$")


@dataclass(slots=True)
class PeloEmpalme:
    """Un extremo (pelo) de una fusión, con el cable/tubo al que pertenece ya resueltos."""

    n_id: int
    cable_n_id: Optional[int]
    cable_nombre: Optional[str]
    tubo_n_id: Optional[int]
    tubo_color: Optional[str]
    numero_pelo: Optional[str]
    orden: Optional[int]
    color: Optional[str]
    servicio_raw: Optional[str]
    servicio_numero: Optional[str]


@dataclass(slots=True)
class EmpalmeDeBotella:
    """Una fila aplanada de la tabla de empalmes: fusión simple (2 pelos) o Splitter agrupado
    (1 pelo de origen, N pelos de destino) en una sola fila."""

    fusion_n_id: int
    nombre_par: Optional[str]
    es_splitter: bool
    pelo_origen: Optional[PeloEmpalme]
    pelo_destino: Optional[PeloEmpalme]
    splitter_destinos: list[PeloEmpalme] = field(default_factory=list)
    splitter_ratio: Optional[int] = None  # cantidad de patas de salida agrupadas, para "Splitter 1-N"


@dataclass(slots=True)
class CableDeEmpalmes:
    """Un cable candidato para el selector "Cable Origen" — sólo cables que efectivamente aparecen
    como origen de al menos un empalme de esta botella."""

    n_id: int
    nombre: Optional[str]
    cantidad_empalmes: int


@dataclass(slots=True)
class ResultadoEmpalmesBotella:
    botella_n_id: int
    nombre: Optional[str]
    cables: list[CableDeEmpalmes] = field(default_factory=list)
    empalmes: list[EmpalmeDeBotella] = field(default_factory=list)


@dataclass(slots=True)
class _Leg:
    """Fila cruda de `cromo_fusiones` con ambos pelos ya resueltos (o `None` si es referencia
    colgada) — paso intermedio antes de agrupar Splitters."""

    fusion_n_id: int
    nombre_par: Optional[str]
    pelo_a: Optional[PeloEmpalme]
    pelo_b: Optional[PeloEmpalme]


_SQL_BOTELLA_POR_N_ID = text("SELECT n_id, nombre FROM app.cromo_botellas WHERE n_id = :n_id")

_SQL_EXISTE_BOTELLA_POR_CABLES = text(
    "SELECT 1 FROM app.cromo_cables WHERE extremo_a_n_id = :botella_n_id OR extremo_b_n_id = :botella_n_id LIMIT 1"
)

# Fusiones que pertenecen a esta botella: por `botella_n_id` directo (nunca poblado hoy, ver
# docstring del módulo) o porque alguno de sus 2 pelos está en un cable que tiene la botella como
# extremo A o B (mismo `cables_botella` que usa `verificador._SQL_CABLES_DE_BOTELLA`).
_SQL_EMPALMES_DE_BOTELLA = text(
    """
    WITH cables_botella AS (
        SELECT n_id FROM app.cromo_cables
        WHERE extremo_a_n_id = :botella_n_id OR extremo_b_n_id = :botella_n_id
    )
    SELECT
        f.n_id, f.nombre_par,
        pa.n_id, pa.cable_n_id, ca.nombre, pa.tubo_n_id, ta.nombre_color, pa.numero_pelo, pa.orden, pa.color, pa.servicio_raw, pa.servicio_numero,
        pb.n_id, pb.cable_n_id, cb.nombre, pb.tubo_n_id, tb.nombre_color, pb.numero_pelo, pb.orden, pb.color, pb.servicio_raw, pb.servicio_numero
    FROM app.cromo_fusiones f
    LEFT JOIN app.cromo_pelos pa ON pa.n_id = f.pelo_a_n_id
    LEFT JOIN app.cromo_cables ca ON ca.n_id = pa.cable_n_id
    LEFT JOIN app.cromo_tubos ta ON ta.n_id = pa.tubo_n_id
    LEFT JOIN app.cromo_pelos pb ON pb.n_id = f.pelo_b_n_id
    LEFT JOIN app.cromo_cables cb ON cb.n_id = pb.cable_n_id
    LEFT JOIN app.cromo_tubos tb ON tb.n_id = pb.tubo_n_id
    WHERE f.botella_n_id = :botella_n_id
       OR pa.cable_n_id IN (SELECT n_id FROM cables_botella)
       OR pb.cable_n_id IN (SELECT n_id FROM cables_botella)
    ORDER BY f.n_id
    """
)


def _pelo_desde_fila(fila: tuple) -> Optional[PeloEmpalme]:
    n_id = fila[0]
    if n_id is None:
        return None
    return PeloEmpalme(
        n_id=n_id,
        cable_n_id=fila[1],
        cable_nombre=fila[2],
        tubo_n_id=fila[3],
        tubo_color=fila[4],
        numero_pelo=fila[5],
        orden=fila[6],
        color=fila[7],
        servicio_raw=fila[8],
        servicio_numero=fila[9],
    )


def _agrupar_splitters(legs: list[_Leg]) -> list[EmpalmeDeBotella]:
    """Agrupa las patas de Splitter (mismo pelo de origen repetido en 2+ fusiones) en una sola fila
    por pelo de origen. Ver docstring del módulo para la justificación de la heurística."""
    conteo_pelos: dict[int, int] = {}
    for leg in legs:
        for pelo in (leg.pelo_a, leg.pelo_b):
            if pelo is not None:
                conteo_pelos[pelo.n_id] = conteo_pelos.get(pelo.n_id, 0) + 1
    origenes_splitter = {n_id for n_id, cantidad in conteo_pelos.items() if cantidad >= 2}

    grupos: dict[int, dict] = {}
    filas: list[EmpalmeDeBotella] = []
    consumidas: set[int] = set()

    for leg in legs:
        origen: Optional[PeloEmpalme] = None
        destino: Optional[PeloEmpalme] = None
        if leg.pelo_a is not None and leg.pelo_a.n_id in origenes_splitter:
            origen, destino = leg.pelo_a, leg.pelo_b
        elif leg.pelo_b is not None and leg.pelo_b.n_id in origenes_splitter:
            origen, destino = leg.pelo_b, leg.pelo_a

        if origen is None:
            continue
        grupo = grupos.setdefault(origen.n_id, {"origen": origen, "destinos": [], "fusion_n_id": leg.fusion_n_id})
        if destino is not None:
            grupo["destinos"].append(destino)
        consumidas.add(leg.fusion_n_id)

    for grupo in grupos.values():
        filas.append(
            EmpalmeDeBotella(
                fusion_n_id=grupo["fusion_n_id"],
                nombre_par=None,
                es_splitter=True,
                pelo_origen=grupo["origen"],
                pelo_destino=None,
                splitter_destinos=grupo["destinos"],
                splitter_ratio=len(grupo["destinos"]),
            )
        )

    for leg in legs:
        if leg.fusion_n_id in consumidas:
            continue
        # Pata aislada con nombre "S..." (ver regex) pero sin par que agrupar — referencia colgada
        # real observada (S7-1, n_id 9997965): se muestra igual como Splitter, sin proporción.
        es_splitter_nombre = bool(leg.nombre_par and _REGEX_NOMBRE_PAR_SPLITTER.match(leg.nombre_par))
        filas.append(
            EmpalmeDeBotella(
                fusion_n_id=leg.fusion_n_id,
                nombre_par=leg.nombre_par,
                es_splitter=es_splitter_nombre,
                pelo_origen=leg.pelo_a,
                pelo_destino=leg.pelo_b,
                splitter_destinos=[],
                splitter_ratio=None,
            )
        )

    filas.sort(key=lambda f: f.fusion_n_id)
    return filas


def _cables_origen(empalmes: list[EmpalmeDeBotella]) -> list[CableDeEmpalmes]:
    """Cables candidatos para el selector "Cable Origen".

    Incluye todos los cables que aparecen en cualquier extremo de un empalme (origen, destino o
    patas de splitter) para cubrir casos reales donde la orientación A/B de la fusión en Cromo no
    coincide con el "origen" visual que necesita elegir el operador en la UI.
    """
    por_cable: dict[int, CableDeEmpalmes] = {}

    def _sumar(pelo: Optional[PeloEmpalme]) -> None:
        if pelo is None or pelo.cable_n_id is None:
            return
        existente = por_cable.get(pelo.cable_n_id)
        if existente is None:
            por_cable[pelo.cable_n_id] = CableDeEmpalmes(
                n_id=pelo.cable_n_id, nombre=pelo.cable_nombre, cantidad_empalmes=1
            )
        else:
            existente.cantidad_empalmes += 1

    for empalme in empalmes:
        cables_vistos_en_fila: set[int] = set()

        for pelo in [empalme.pelo_origen, empalme.pelo_destino, *empalme.splitter_destinos]:
            if pelo is None or pelo.cable_n_id is None:
                continue
            if pelo.cable_n_id in cables_vistos_en_fila:
                continue
            cables_vistos_en_fila.add(pelo.cable_n_id)
            _sumar(pelo)

    return sorted(por_cable.values(), key=lambda c: (c.nombre or "", c.n_id))


async def empalmes_de_botella(sesion: AsyncSession, botella_n_id: int) -> ResultadoEmpalmesBotella:
    """Empalmes (fusiones) internos de una Botella, aplanados y con Splitters agrupados.

    Tolerante a referencia colgada, mismo criterio que el resto de `verificador.py`/`detalle.py`: si
    la botella no tiene fila propia pero sí tiene cables que la referencian como extremo, no es
    "no encontrada" (sólo `nombre` queda en `None`).
    """
    botella = (await sesion.execute(_SQL_BOTELLA_POR_N_ID, {"n_id": botella_n_id})).first()
    filas = (await sesion.execute(_SQL_EMPALMES_DE_BOTELLA, {"botella_n_id": botella_n_id})).all()

    if botella is None and not filas:
        existe = (await sesion.execute(_SQL_EXISTE_BOTELLA_POR_CABLES, {"botella_n_id": botella_n_id})).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe una botella con n_id={botella_n_id} en el inventario ingerido.")

    legs = [
        _Leg(
            fusion_n_id=fila[0],
            nombre_par=fila[1],
            pelo_a=_pelo_desde_fila(fila[2:12]),
            pelo_b=_pelo_desde_fila(fila[12:22]),
        )
        for fila in filas
    ]
    empalmes = _agrupar_splitters(legs)

    return ResultadoEmpalmesBotella(
        botella_n_id=botella_n_id,
        nombre=botella[1] if botella else None,
        cables=_cables_origen(empalmes),
        empalmes=empalmes,
    )


__all__ = [
    "PeloEmpalme",
    "EmpalmeDeBotella",
    "CableDeEmpalmes",
    "ResultadoEmpalmesBotella",
    "empalmes_de_botella",
]
