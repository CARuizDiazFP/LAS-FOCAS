# Nombre de archivo: servicios_fusion_prov.py
# Ubicación de archivo: core/services/servicios_fusion_prov.py
# Descripción: Fusión de filas de app.servicios que PROV identifica como el mismo servicio (misma cadena de upgrades) y regla del ID operativo

"""Una fila por servicio real, usando la cadena de upgrades de PROV como fuente de la verdad.

Contexto real (backfill PROV en prod, 2026-09-30): 437 pares de filas de `app.servicios` eran el
mismo servicio de PROV (una fila con el ID viejo y otra con el nuevo), 387 de ellos con pelos de
Cromo en las dos filas. Consecuencias: "Servicios por cable/buffer" listaba el mismo servicio dos
veces, los pelos quedaban repartidos entre las dos filas (tracking y ODF incompletos) y la regla
anti-ambigüedad de las búsquedas descartaba las dos filas de un par mutuo (625 servicios daban 404
por su propio ID en la API v1).

**ID operativo** (decisión del usuario, 2026-09-30): el eslabón `INSTALADO` más reciente de la
cadena. PROV puede marcar como vigente un eslabón `PENDIENTE CPS` (upgrade no implementado),
`ANULADO` o `SOL BAJA` (baja administrativa pendiente de la técnica); en todos esos casos el
servicio sigue funcionando con el `INSTALADO` anterior, y ese es el ID que usan las áreas. Si la
cadena no tiene ningún `INSTALADO`, se usa el que PROV marca vigente.

**Vínculo entre filas**: sólo la cadena de PROV (`servicios_historial_id.numero_id` de una fila
contra `servicio_id`/`numero_primer_servicio` de otra). Nunca `alias_ids` a secas: hay alias que no
son IDs de PROV (ej. "C22", nombre de pelo) y unirían servicios distintos. Medido en prod: de los 437
pares, 113 tienen una fila sin cliente y ninguno tiene dos clientes distintos.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ESTADO_INSTALADO = "INSTALADO"


@dataclass(frozen=True)
class Eslabon:
    numero_id: str
    orden: int  # 0 = el más reciente, crece hacia atrás
    estado_comercial: Optional[str]
    es_vigente: bool


def id_operativo(eslabones: Iterable[Eslabon]) -> Optional[str]:
    """ID con el que el servicio funciona hoy: el `INSTALADO` más reciente, si no el vigente de PROV."""

    ordenados = sorted((e for e in eslabones if e.numero_id), key=lambda e: e.orden)
    for eslabon in ordenados:
        if (eslabon.estado_comercial or "").strip().upper() == ESTADO_INSTALADO:
            return eslabon.numero_id
    for eslabon in ordenados:
        if eslabon.es_vigente:
            return eslabon.numero_id
    return None


def agrupar(pares: Iterable[tuple[int, int]]) -> list[list[int]]:
    """Componentes conexos de los pares (union-find). Cada grupo, ordenado; los grupos, por su menor id."""

    padre: dict[int, int] = {}

    def raiz(x: int) -> int:
        padre.setdefault(x, x)
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for a, b in pares:
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            padre[max(ra, rb)] = min(ra, rb)
    grupos: dict[int, list[int]] = {}
    for x in padre:
        grupos.setdefault(raiz(x), []).append(x)
    return sorted((sorted(g) for g in grupos.values()), key=lambda g: g[0])


@dataclass(frozen=True)
class FilaServicio:
    id: int
    servicio_id: str
    numero_primer_servicio: Optional[str]
    alias_ids: tuple[str, ...]
    nombre_cliente: Optional[str]
    matches: int
    eslabones: tuple[Eslabon, ...]


def elegir_sobreviviente(filas: Sequence[FilaServicio]) -> FilaServicio:
    """La fila más completa: con cliente, con cadena de PROV, con más pelos; a igualdad, el menor id."""

    return min(
        filas,
        key=lambda f: (f.nombre_cliente is None, not f.eslabones, -f.matches, f.id),
    )


@dataclass
class PlanGrupo:
    sobreviviente: FilaServicio
    perdedores: list[FilaServicio]
    id_final: str
    alias_final: list[str]
    motivo_salteo: Optional[str] = None
    ids_operativos: set[str] = field(default_factory=set)


def planificar(filas: Sequence[FilaServicio]) -> PlanGrupo:
    """Decide sobreviviente, ID final y alias de un grupo. Si el grupo es ambiguo, lo marca para saltear."""

    operativos = {op for f in filas if (op := id_operativo(f.eslabones))}
    sobreviviente = elegir_sobreviviente(filas)
    perdedores = [f for f in filas if f.id != sobreviviente.id]
    clientes = {f.nombre_cliente.strip().upper() for f in filas if f.nombre_cliente}

    motivo = None
    if len(operativos) > 1:
        motivo = "cadenas_con_distinto_id_operativo"
    elif len(clientes) > 1:
        motivo = "clientes_distintos"

    id_final = next(iter(operativos)) if len(operativos) == 1 else sobreviviente.servicio_id
    todos: list[str] = []
    for f in [sobreviviente, *perdedores]:
        todos.extend([f.servicio_id, f.numero_primer_servicio or "", *f.alias_ids])
        todos.extend(e.numero_id for e in f.eslabones)
    alias_final = sorted({a for a in todos if a and a != id_final})
    return PlanGrupo(
        sobreviviente=sobreviviente,
        perdedores=perdedores,
        id_final=id_final,
        alias_final=alias_final,
        motivo_salteo=motivo,
        ids_operativos=operativos,
    )


# ── Acceso a datos ────────────────────────────────────────────────────────────

_SQL_PARES_POR_CADENA = text(
    """
    WITH cadena AS (SELECT servicio_id AS pk, numero_id AS n FROM app.servicios_historial_id),
    identidad AS (
        SELECT id AS pk, x AS n
        FROM app.servicios, unnest(ARRAY[servicio_id, numero_primer_servicio]) AS x
        WHERE x IS NOT NULL
    )
    SELECT DISTINCT least(c.pk, i.pk) AS a, greatest(c.pk, i.pk) AS b
    FROM cadena c JOIN identidad i ON i.n = c.n AND i.pk <> c.pk
    """
)

_SQL_FILAS = text(
    """
    SELECT s.id, s.servicio_id, s.numero_primer_servicio, coalesce(s.alias_ids, '{}'), s.nombre_cliente,
           (SELECT count(*) FROM app.cromo_servicio_match m WHERE m.servicio_id = s.id) AS matches
    FROM app.servicios s WHERE s.id = ANY(:ids ::integer[])
    """
)

_SQL_ESLABONES = text(
    """
    SELECT servicio_id, numero_id, orden, estado_comercial, es_vigente
    FROM app.servicios_historial_id WHERE servicio_id = ANY(:ids ::integer[])
    """
)


def cargar_grupos(session: Session) -> list[list[FilaServicio]]:
    pares = [(a, b) for a, b in session.execute(_SQL_PARES_POR_CADENA).all()]
    grupos = agrupar(pares)
    filas = cargar_filas(session, [i for g in grupos for i in g])
    return [[filas[i] for i in g if i in filas] for g in grupos]


def cargar_filas(session: Session, ids: list[int]) -> dict[int, FilaServicio]:
    if not ids:
        return {}
    eslabones: dict[int, list[Eslabon]] = {}
    for pk, numero, orden, estado, vigente in session.execute(_SQL_ESLABONES, {"ids": ids}).all():
        eslabones.setdefault(pk, []).append(Eslabon(numero, orden, estado, bool(vigente)))
    return {
        f[0]: FilaServicio(
            id=f[0],
            servicio_id=f[1],
            numero_primer_servicio=f[2],
            alias_ids=tuple(f[3]),
            nombre_cliente=f[4],
            matches=f[5],
            eslabones=tuple(sorted(eslabones.get(f[0], []), key=lambda e: e.orden)),
        )
        for f in session.execute(_SQL_FILAS, {"ids": ids}).all()
    }


# Tablas con FK a app.servicios (auditadas en prod el 2026-09-30, 8 en total). Las que se reasignan
# siempre: el perdedor no debe perder nada de esto. `servicio_empalme_association` tiene PK
# (servicio_id, empalme_id): se inserta lo que falte y se borra lo del perdedor.
_REASIGNAR = ("cromo_servicio_match", "rutas_servicio", "cromo_servicio_odf_override", "cromo_tracking_cache")
# Datos propios de PROV (se borran en cascada con el perdedor): se conservan los del sobreviviente;
# sólo se mueven los del perdedor si el sobreviviente no tiene ninguno.
_DATOS_PROV = ("servicios_historial_id", "servicios_equipos_ultima_milla", "servicios_sync_prov")


def aplicar_plan(session: Session, plan: PlanGrupo) -> dict[str, int]:
    """Ejecuta la fusión de un grupo. No hace commit: el caller decide (savepoint por grupo)."""

    sid = plan.sobreviviente.id
    movidos = {"matches": 0}
    for perdedor in plan.perdedores:
        pid = perdedor.id
        for tabla in _REASIGNAR:
            r = session.execute(
                text(f"UPDATE app.{tabla} SET servicio_id = :s WHERE servicio_id = :p"), {"s": sid, "p": pid}
            )
            if tabla == "cromo_servicio_match":
                movidos["matches"] += r.rowcount
        session.execute(
            text(
                "INSERT INTO app.servicio_empalme_association (servicio_id, empalme_id) "
                "SELECT :s, empalme_id FROM app.servicio_empalme_association WHERE servicio_id = :p "
                "ON CONFLICT DO NOTHING"
            ),
            {"s": sid, "p": pid},
        )
        session.execute(text("DELETE FROM app.servicio_empalme_association WHERE servicio_id = :p"), {"p": pid})
        for tabla in _DATOS_PROV:
            tiene = session.execute(text(f"SELECT 1 FROM app.{tabla} WHERE servicio_id = :s LIMIT 1"), {"s": sid}).first()
            if tiene is None:
                session.execute(text(f"UPDATE app.{tabla} SET servicio_id = :s WHERE servicio_id = :p"), {"s": sid, "p": pid})
        session.execute(text("DELETE FROM app.servicios WHERE id = :p"), {"p": pid})

    # Recién con los perdedores borrados quedan libres su servicio_id y numero_primer_servicio (UNIQUE).
    numero_primer = plan.sobreviviente.numero_primer_servicio or next(
        (p.numero_primer_servicio for p in plan.perdedores if p.numero_primer_servicio), None
    )
    session.execute(
        text(
            "UPDATE app.servicios SET servicio_id = :id_final, numero_linea = :id_final, "
            "alias_ids = :alias ::varchar[], numero_primer_servicio = :primer WHERE id = :s"
        ),
        {"id_final": plan.id_final, "alias": plan.alias_final, "primer": numero_primer, "s": sid},
    )
    return movidos


# ── Realineación de filas sueltas ─────────────────────────────────────────────

# Filas sin duplicado cuyo `servicio_id` no es su ID operativo: el backfill PROV del 2026-09-30 corrió
# con la regla anterior ("el ID más alto") y dejó como ID un upgrade `PENDIENTE CPS` (31 casos con pelos
# en dev, ej. 120393 → 112763). Sólo se realinea si el ID operativo no lo usa otra fila (UNIQUE); si lo
# usa, es un grupo y lo resuelve la fusión.
_SQL_DESALINEADAS = text(
    """
    SELECT s.id, s.servicio_id, op.numero_id AS operativo
    FROM app.servicios s
    JOIN LATERAL (
        SELECT h.numero_id FROM app.servicios_historial_id h
        WHERE h.servicio_id = s.id AND upper(btrim(h.estado_comercial)) = 'INSTALADO'
        ORDER BY h.orden LIMIT 1
    ) op ON true
    WHERE op.numero_id <> s.servicio_id
      AND NOT EXISTS (SELECT 1 FROM app.servicios o WHERE o.id <> s.id AND o.servicio_id = op.numero_id)
    ORDER BY s.id
    """
)


@dataclass(frozen=True)
class Realineacion:
    id: int
    servicio_id_antes: str
    operativo: str


def cargar_desalineadas(session: Session) -> list[Realineacion]:
    return [Realineacion(pk, antes, op) for pk, antes, op in session.execute(_SQL_DESALINEADAS).all()]


def realinear(session: Session, r: Realineacion) -> None:
    session.execute(
        text(
            # CAST explícito: psycopg3 no deduce un único tipo si `:op` aparece como varchar y como text.
            "UPDATE app.servicios SET servicio_id = CAST(:op AS varchar), numero_linea = CAST(:op AS varchar), "
            "alias_ids = array(SELECT DISTINCT a FROM unnest(coalesce(alias_ids, '{}') || ARRAY[CAST(:antes AS varchar)]) a "
            "WHERE a <> CAST(:op AS varchar)) WHERE id = :id"
        ),
        {"op": r.operativo, "antes": r.servicio_id_antes, "id": r.id},
    )
