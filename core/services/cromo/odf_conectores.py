# Nombre de archivo: odf_conectores.py
# Ubicación de archivo: core/services/cromo/odf_conectores.py
# Descripción: Conectores/posiciones de patchera de una ODF Cromo (o de una patchera por nombre, para "track odf"), con el servicio ya resuelto (atributo directo + regex del pelo) enriquecido con Cliente/Estado real

"""Resuelve "mostrame los conectores de esta ODF" a partir de `app.cromo_odf_conectores` ya
ingerido — distinto de `verificador.servicios_por_odf` (que atraviesa `cables_asociados` +
regex sobre pelos sin pasar por la jerarquía de patcheras/conectores).

`servicio_resuelto` ya viene calculado por la ingesta (`ingesta.py::resolver_servicio_conectores`,
MAX entre el atributo directo de Cromo y el regex del pelo). Para Cliente/Estado, esta consulta NO
reusa directamente `cromo_servicio_match` del pelo: cuando el atributo le "gana" al regex (el pelo
matchea a un número MENOR que el resuelto), el match del pelo apuntaría a un servicio distinto del
que `servicio_resuelto` realmente representa. En cambio, resuelve `servicio_resuelto` contra
`app.servicios` con el mismo criterio anti-ambigüedad ya usado en
`core/services/cromo/ingesta.py::_SQL_BUSCAR_SERVICIO` (excluye una fila cuya identidad ya fue
absorbida como alias de otra) — evita reabrir la misma ambigüedad de identidad de servicios
resuelta el 2026-08-31 (ver docs/decisiones.md).

Desde 2026-10-21 también resuelve una patchera por nombre (`bandejas_por_nombre`) y sus conectores
pedidos (`conectores_de_bandeja`) para el comando de Slack `track odf <patchera>:<conectores>`. El
LATERAL anti-ambigüedad es una sola plantilla (`lateral_servicio`) para los dos usos."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.verificador import ObjetoNoEncontrado


@dataclass(slots=True)
class ConectorOdfResuelto:
    n_id: int
    bandeja_n_id: Optional[int]
    bandeja_nombre: Optional[str]
    numero_conector: Optional[str]
    pelo_n_id: Optional[int]
    pelo_numero: Optional[str]
    servicio_resuelto: Optional[str]
    servicio_id_historico: Optional[str]
    servicio_id_externo: Optional[str]  # s.servicio_id ya resuelto, para el link de navegación
    nombre_cliente: Optional[str]
    cliente: Optional[str]
    estado_servicio: Optional[str]


@dataclass(slots=True)
class ResultadoConectoresOdf:
    odf_n_id: int
    odf_nombre: Optional[str]
    conectores: list[ConectorOdfResuelto] = field(default_factory=list)


_SQL_ODF_NOMBRE = text("SELECT nombre FROM app.cromo_odfs WHERE n_id = :n_id")
_SQL_EXISTE_ODF_POR_CONECTORES = text(
    "SELECT 1 FROM app.cromo_odf_conectores WHERE odf_n_id = :n_id LIMIT 1"
)

# Servicio de `app.servicios` al que apunta un número de servicio de la columna `{col}` (texto), con
# el criterio anti-ambigüedad de `ingesta.py::_SQL_BUSCAR_SERVICIO`: se descarta la fila cuya
# identidad ya fue absorbida como alias de otra. Una sola plantilla para `conectores_de_odf` (sobre
# `servicio_resuelto`) y `conectores_de_bandeja` (sobre `servicio_resuelto` y
# `servicio_id_historico`), para que no puedan divergir.
_LATERAL_SERVICIO = """(
        SELECT sv.id, sv.servicio_id, sv.nombre_cliente, sv.cliente, sv.estado_servicio
        FROM app.servicios sv
        WHERE {col} IS NOT NULL
          AND (
            sv.servicio_id = {col}
            OR sv.numero_primer_servicio = {col}
            OR {col} = ANY(sv.alias_ids)
          )
          AND NOT EXISTS (
              SELECT 1 FROM app.servicios vigente
              WHERE vigente.id <> sv.id
                AND (
                  sv.servicio_id = ANY(vigente.alias_ids)
                  OR sv.numero_primer_servicio = ANY(vigente.alias_ids)
                )
                -- Par mutuo: no se descarta ninguna fila (mismo criterio que `_SQL_BUSCAR_SERVICIO`).
                AND NOT COALESCE(
                  vigente.servicio_id = ANY(sv.alias_ids) OR vigente.numero_primer_servicio = ANY(sv.alias_ids),
                  false
                )
          )
        ORDER BY (sv.servicio_id = {col}) DESC, sv.id DESC
        LIMIT 1
    )"""


def lateral_servicio(col: str) -> str:
    """El subselect del LATERAL anti-ambigüedad sobre la columna `col` (una expresión SQL fija del
    módulo, nunca un dato del usuario)."""
    return _LATERAL_SERVICIO.format(col=col)


# `length(c.numero_conector), c.numero_conector` en vez de `::int`: `numero_conector` es texto, un
# CAST revienta si algún valor no es puramente numérico (dato de Cromo, no garantizado). Mismo
# largo + orden alfabético da orden numérico correcto para el rango real observado (1-24 por
# bandeja), sin arriesgar una excepción por un valor inesperado.
_SQL_CONECTORES_DE_ODF = text(
    f"""
    SELECT
        c.n_id, c.bandeja_n_id, c.bandeja_nombre, c.numero_conector,
        c.pelo_n_id, p.numero_pelo,
        c.servicio_resuelto, c.servicio_id_historico,
        s.servicio_id, s.nombre_cliente, s.cliente, s.estado_servicio
    FROM app.cromo_odf_conectores c
    LEFT JOIN app.cromo_pelos p ON p.n_id = c.pelo_n_id
    LEFT JOIN LATERAL {lateral_servicio("c.servicio_resuelto")} s ON true
    WHERE c.odf_n_id = :odf_n_id
    ORDER BY c.bandeja_nombre NULLS LAST, length(c.numero_conector), c.numero_conector
    """
)


async def conectores_de_odf(sesion: AsyncSession, odf_n_id: int) -> ResultadoConectoresOdf:
    """Conectores de patchera de una ODF, con Cliente/Estado ya resueltos.

    "No encontrado" se decide por si la ODF aparece en algún lado (fila propia en `cromo_odfs` o
    al menos un conector que la referencia) — mismo criterio tolerante a referencia colgada que
    `verificador.servicios_por_cable`.
    """
    fila_odf = (await sesion.execute(_SQL_ODF_NOMBRE, {"n_id": odf_n_id})).first()
    filas = (await sesion.execute(_SQL_CONECTORES_DE_ODF, {"odf_n_id": odf_n_id})).all()

    if fila_odf is None and not filas:
        existe = (await sesion.execute(_SQL_EXISTE_ODF_POR_CONECTORES, {"n_id": odf_n_id})).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe una ODF con n_id={odf_n_id} en el inventario ingerido.")

    conectores = [
        ConectorOdfResuelto(
            n_id=fila[0],
            bandeja_n_id=fila[1],
            bandeja_nombre=fila[2],
            numero_conector=fila[3],
            pelo_n_id=fila[4],
            pelo_numero=fila[5],
            servicio_resuelto=fila[6],
            servicio_id_historico=fila[7],
            servicio_id_externo=fila[8],
            nombre_cliente=fila[9],
            cliente=fila[10],
            estado_servicio=fila[11],
        )
        for fila in filas
    ]
    return ResultadoConectoresOdf(
        odf_n_id=odf_n_id,
        odf_nombre=fila_odf[0] if fila_odf else None,
        conectores=conectores,
    )


# ── `track odf <patchera>:<conectores>` ─────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class BandejaCandidata:
    """Una patchera (bandeja) cuyo nombre coincide con el pedido. Un mismo nombre puede estar en
    varias ODF (medido en dev: "O-1249273-1" en 2, "ODF 1" en 491)."""

    bandeja_n_id: int
    bandeja_nombre: str
    odf_n_id: int
    odf_nombre: Optional[str]


@dataclass(slots=True, frozen=True)
class ConectorDePatchera:
    """Un conector de una patchera, con lo necesario para pedir su tracking y explicarlo.

    `servicio_*` es el servicio de `servicio_resuelto` (lo que dice el conector); `historico_*`, el
    de `servicio_id_historico`; `etiqueta_*`, la del pelo (`cromo_pelos.servicio_numero` crudo y el
    servicio que matchea). En el 93150, O-1252871-1:1 dice 93150 (Activo) y su pelo, 44649 (Baja).
    Si el conector no tiene pelo pero tiene patch, `patch_pelo_n_id` es el pelo del conector de
    destino (un solo salto) y el pelo, el cable y la etiqueta son los de ese pelo.
    """

    n_id: int
    numero_conector: Optional[str]
    pelo_n_id: Optional[int]
    patch_conector_n_id: Optional[int]
    patch_pelo_n_id: Optional[int]
    numero_pelo: Optional[str]
    cable_nombre: Optional[str]
    servicio_resuelto: Optional[str]
    servicio_pk: Optional[int]
    servicio_numero: Optional[str]
    nombre_cliente: Optional[str]
    cliente: Optional[str]
    estado_servicio: Optional[str]
    historico_numero: Optional[str]
    historico_estado: Optional[str]
    etiqueta_pelo: Optional[str]
    etiqueta_numero: Optional[str]
    etiqueta_estado: Optional[str]

    @property
    def pelo_efectivo(self) -> Optional[int]:
        """El pelo del conector o, si no tiene, el del conector al que tiene patch."""
        return self.pelo_n_id if self.pelo_n_id is not None else self.patch_pelo_n_id


_RE_ESPACIOS = re.compile(r"\s+")


def variantes_nombre_patchera(nombre: str) -> list[str]:
    """Formas en que se busca una patchera: en mayúsculas, sin espacios de más y, si empieza por
    `O-` o `0-`, también con el otro prefijo (es un error de tipeo habitual; hay 2.760 conectores
    reales con patchera "0-…", así que ninguna de las dos se descarta)."""
    base = _RE_ESPACIOS.sub(" ", nombre).strip().upper()
    if not base:
        return []
    variantes = [base]
    if base[:2] in ("O-", "0-"):
        variantes.append(("0-" if base[0] == "O" else "O-") + base[2:])
    return variantes


# Sin índice por nombre de patchera: es un seq scan de ~430 ms sobre ~268 mil conectores (medido en
# dev el 2026-10-21), aceptable para un comando de chat. Del lado de la DB se normaliza igual que en
# `variantes_nombre_patchera` (hay nombres reales con doble espacio).
_SQL_BANDEJAS_POR_NOMBRE = text(
    """
    SELECT DISTINCT c.bandeja_n_id, c.bandeja_nombre, c.odf_n_id, o.nombre AS odf_nombre
    FROM app.cromo_odf_conectores c
    LEFT JOIN app.cromo_odfs o ON o.n_id = c.odf_n_id
    WHERE c.vigente
      AND c.bandeja_n_id IS NOT NULL
      AND upper(regexp_replace(btrim(c.bandeja_nombre), '[[:space:]]+', ' ', 'g')) = ANY(:nombres)
    ORDER BY c.odf_n_id, c.bandeja_n_id
    """
)


async def bandejas_por_nombre(sesion: AsyncSession, nombre: str) -> list[BandejaCandidata]:
    """Las patcheras vigentes cuyo nombre coincide con `nombre` (sin distinguir mayúsculas,
    aceptando `0-` por `O-`). Más de una = ambigua: el llamador lista y no elige."""
    nombres = variantes_nombre_patchera(nombre)
    if not nombres:
        return []
    filas = (await sesion.execute(_SQL_BANDEJAS_POR_NOMBRE, {"nombres": nombres})).all()
    return [BandejaCandidata(int(f[0]), f[1], int(f[2]), f[3]) for f in filas]


# El salto de patch es uno solo (`pc`), y sólo si el conector no tiene pelo: hay 1.416 patches
# mutuos en dev, así que seguirlos en cadena ciclaría. `bandeja_n_id` no tiene índice: sólo por
# bandeja es un seq scan de ~2,1 s; con la ODF (`{filtro_odf}`) usa `ix_cromo_odf_conectores_odf_n_id`.
_CONECTORES_DE_BANDEJA = f"""
    SELECT
        c.n_id, c.numero_conector, c.pelo_n_id, c.patch_conector_n_id, pc.pelo_n_id AS patch_pelo_n_id,
        p.numero_pelo, cab.nombre AS cable_nombre,
        c.servicio_resuelto, sr.id, sr.servicio_id, sr.nombre_cliente, sr.cliente, sr.estado_servicio,
        c.servicio_id_historico, sh.estado_servicio,
        p.servicio_numero, sp.servicio_id, sp.estado_servicio
    FROM app.cromo_odf_conectores c
    LEFT JOIN app.cromo_odf_conectores pc
        ON c.pelo_n_id IS NULL AND pc.n_id = c.patch_conector_n_id AND pc.vigente
    LEFT JOIN app.cromo_pelos p ON p.n_id = COALESCE(c.pelo_n_id, pc.pelo_n_id)
    LEFT JOIN app.cromo_cables cab ON cab.n_id = p.cable_n_id
    LEFT JOIN LATERAL {lateral_servicio("c.servicio_resuelto")} sr ON true
    LEFT JOIN LATERAL {lateral_servicio("c.servicio_id_historico")} sh ON true
    LEFT JOIN LATERAL (
        SELECT s.servicio_id, s.estado_servicio
        FROM app.v_cromo_servicio_match_vigente m
        JOIN app.servicios s ON s.id = m.servicio_id
        WHERE m.pelo_n_id = p.n_id
        ORDER BY m.confianza DESC NULLS LAST, s.id DESC
        LIMIT 1
    ) sp ON true
    WHERE c.vigente AND c.bandeja_n_id = :bandeja_n_id AND c.numero_conector = ANY(:numeros)
      {{filtro_odf}}
    ORDER BY length(c.numero_conector), c.numero_conector
    """
_SQL_CONECTORES_DE_BANDEJA = text(_CONECTORES_DE_BANDEJA.format(filtro_odf=""))
# Los dos LATERAL de servicio estiman ~1,2 M de costo (el NOT EXISTS anti-ambigüedad sobre
# `servicios`) y pasan el `jit_above_cost` de 100 mil: medido en dev (2026-10-21), la compilación
# JIT eran 1,5 s de 1,6 s para devolver 3 filas; sin JIT, 65 ms. `SET LOCAL` vale hasta el próximo
# commit o rollback de la transacción del llamador, no para la conexión.
_SQL_SIN_JIT = text("SET LOCAL jit = off")
_SQL_CONECTORES_DE_BANDEJA_Y_ODF = text(
    _CONECTORES_DE_BANDEJA.format(filtro_odf="AND c.odf_n_id = :odf_n_id")
)


async def conectores_de_bandeja(
    sesion: AsyncSession,
    bandeja_n_id: int,
    numeros: Sequence[str],
    *,
    odf_n_id: Optional[int] = None,
) -> list[ConectorDePatchera]:
    """Los conectores vigentes `numeros` de la patchera, con servicio resuelto, histórico y
    etiqueta del pelo. Un número que no está en la patchera simplemente no vuelve. `odf_n_id` (la
    ODF de la bandeja, que `bandejas_por_nombre` ya trae) sólo acelera la consulta."""
    params: dict[str, object] = {"bandeja_n_id": bandeja_n_id, "numeros": list(numeros)}
    sql = _SQL_CONECTORES_DE_BANDEJA
    if odf_n_id is not None:
        sql, params["odf_n_id"] = _SQL_CONECTORES_DE_BANDEJA_Y_ODF, odf_n_id
    await sesion.execute(_SQL_SIN_JIT)
    filas = (await sesion.execute(sql, params)).all()
    return [
        ConectorDePatchera(
            n_id=int(f[0]),
            numero_conector=f[1],
            pelo_n_id=f[2],
            patch_conector_n_id=f[3],
            patch_pelo_n_id=f[4],
            numero_pelo=f[5],
            cable_nombre=f[6],
            servicio_resuelto=f[7],
            servicio_pk=f[8],
            servicio_numero=f[9],
            nombre_cliente=f[10],
            cliente=f[11],
            estado_servicio=f[12],
            historico_numero=f[13],
            historico_estado=f[14],
            etiqueta_pelo=f[15],
            etiqueta_numero=f[16],
            etiqueta_estado=f[17],
        )
        for f in filas
    ]


__all__ = [
    "BandejaCandidata",
    "ConectorDePatchera",
    "ConectorOdfResuelto",
    "ResultadoConectoresOdf",
    "bandejas_por_nombre",
    "conectores_de_bandeja",
    "conectores_de_odf",
    "lateral_servicio",
    "variantes_nombre_patchera",
]
