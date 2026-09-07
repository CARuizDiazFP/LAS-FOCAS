# Nombre de archivo: odf_conectores.py
# Ubicación de archivo: core/services/cromo/odf_conectores.py
# Descripción: Conectores/posiciones de patchera de una ODF Cromo, con el servicio ya resuelto (atributo directo + regex del pelo) enriquecido con Cliente/Estado real

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
resuelta el 2026-08-31 (ver docs/decisiones.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

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

# `length(c.numero_conector), c.numero_conector` en vez de `::int`: `numero_conector` es texto, un
# CAST revienta si algún valor no es puramente numérico (dato de Cromo, no garantizado). Mismo
# largo + orden alfabético da orden numérico correcto para el rango real observado (1-24 por
# bandeja), sin arriesgar una excepción por un valor inesperado.
_SQL_CONECTORES_DE_ODF = text(
    """
    SELECT
        c.n_id, c.bandeja_n_id, c.bandeja_nombre, c.numero_conector,
        c.pelo_n_id, p.numero_pelo,
        c.servicio_resuelto, c.servicio_id_historico,
        s.servicio_id, s.nombre_cliente, s.cliente, s.estado_servicio
    FROM app.cromo_odf_conectores c
    LEFT JOIN app.cromo_pelos p ON p.n_id = c.pelo_n_id
    LEFT JOIN LATERAL (
        SELECT sv.servicio_id, sv.nombre_cliente, sv.cliente, sv.estado_servicio
        FROM app.servicios sv
        WHERE c.servicio_resuelto IS NOT NULL
          AND (
            sv.servicio_id = c.servicio_resuelto
            OR sv.numero_primer_servicio = c.servicio_resuelto
            OR c.servicio_resuelto = ANY(sv.alias_ids)
          )
          AND NOT EXISTS (
              SELECT 1 FROM app.servicios vigente
              WHERE vigente.id <> sv.id
                AND (
                  sv.servicio_id = ANY(vigente.alias_ids)
                  OR sv.numero_primer_servicio = ANY(vigente.alias_ids)
                )
          )
        LIMIT 1
    ) s ON true
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


__all__ = ["ConectorOdfResuelto", "ResultadoConectoresOdf", "conectores_de_odf"]
