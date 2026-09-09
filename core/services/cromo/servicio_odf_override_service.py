# Nombre de archivo: servicio_odf_override_service.py
# Ubicación de archivo: core/services/cromo/servicio_odf_override_service.py
# Descripción: Escritura y lectura de la asociación manual Servicio→ODF (tabla escudo cromo_servicio_odf_override) — lado de escritura del gestor "Servicios sin ODF"

"""Crea y consulta `app.cromo_servicio_odf_override`: la asociación manual Servicio→ODF que un
operador confirma cuando el detector automático (`core/services/cromo/servicios_sin_odf.py`) no
pudo resolver la ODF real de un Servicio por sí solo.

Cada fila es un EVENTO de asociación, no el estado actual de un Servicio — no hay `UNIQUE` en
`servicio_id` (Task 1, ver `db/models/cromo.py::CromoServicioOdfOverride`) a propósito, para
permitir reasociar corrigiendo un error humano sin perder historial. La lectura SIEMPRE toma la
fila más reciente por `servicio_id` (`ORDER BY creado_en DESC, id DESC`).

No reimplementa el matching Servicio↔ODF por texto ya establecido en
`odf_conectores.py`/`servicios_sin_odf.py`: acá `servicio_id` siempre es la FK dura a
`app.servicios.id`, nunca un número de texto — la asociación es explícita, confirmada a mano, no
inferida.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.direccion_comparacion import SenalDireccion
from core.services.cromo.verificador import ObjetoNoEncontrado
from db.models.cromo import CromoServicioOdfOverride

__all__ = [
    "crear_override",
    "override_vigente_de_servicio",
    "overrides_vigentes_por_odf",
]

# Mismo criterio tolerante que `odf_conectores.py::conectores_de_odf` para decidir "existe la ODF":
# fila propia en `cromo_odfs`, O al menos una referencia real desde `cromo_odf_conectores` — un ODF
# puede conocerse sólo por sus conectores si la ingesta de su fila propia todavía no bajó (misma
# "referencia colgada" que el resto del módulo Cromo tolera, ver `verificador.py`). Sin este
# chequeo, un typo de n_id en el modal de asociación manual crearía un override colgado que nunca
# aparece en ningún lado (ni en `servicios_por_odf`, porque esa ODF nunca se puede abrir).
_SQL_EXISTE_ODF = text("SELECT 1 FROM app.cromo_odfs WHERE n_id = :n_id")
_SQL_EXISTE_ODF_POR_CONECTORES = text(
    "SELECT 1 FROM app.cromo_odf_conectores WHERE odf_n_id = :n_id LIMIT 1"
)


async def crear_override(
    sesion: AsyncSession,
    *,
    servicio_id: int,
    odf_n_id: int,
    pelo_n_id: Optional[int] = None,
    categoria_causa: str,
    subcategoria: Optional[str] = None,
    usuario: str,
    notas: Optional[str] = None,
    senal_direccion: Optional[SenalDireccion] = None,
) -> CromoServicioOdfOverride:
    """Inserta un nuevo evento de asociación manual Servicio→ODF.

    INSERT puro, nunca upsert: reasociar (el operador corrige una asociación previa) crea una fila
    NUEVA en vez de pisar la anterior — coherente con la ausencia de `UNIQUE(servicio_id)` en la
    tabla (Task 1).

    Valida que `odf_n_id` exista en el inventario Cromo ya ingerido ANTES de insertar — un typo de
    n_id no debe crear un override colgado silenciosamente. Levanta `ObjetoNoEncontrado` (la misma
    excepción que ya usa el resto del módulo Cromo para "no existe", ver
    `odf_conectores.py::conectores_de_odf`) si no lo encuentra.

    `servicio_id` inexistente NO se valida acá a propósito: `CromoServicioOdfOverride.servicio_id`
    es FK DURA a `app.servicios.id` (`ondelete=CASCADE`) — Postgres ya lo rechaza con un
    `IntegrityError` explícito, revalidarlo a mano sería reimplementar lo que la FK ya garantiza.
    Mismo criterio para los 3 CHECK de `categoria_causa`/`subcategoria`/`senal_direccion`: el
    vocabulario vive en el CHECK de la migración (fuente de verdad, ver docstring de
    `CromoServicioOdfOverride`), no en Python — un valor inválido levanta `IntegrityError` real, sin
    revalidación duplicada acá.

    `senal_direccion` recibe el enum `SenalDireccion` (Task 2), no un string suelto — se persiste
    como su `.value` (mismos literales que el CHECK de la migración).
    """
    existe = (await sesion.execute(_SQL_EXISTE_ODF, {"n_id": odf_n_id})).first()
    if existe is None:
        existe_por_conector = (
            await sesion.execute(_SQL_EXISTE_ODF_POR_CONECTORES, {"n_id": odf_n_id})
        ).first()
        if existe_por_conector is None:
            raise ObjetoNoEncontrado(
                f"No existe un ODF con n_id={odf_n_id} en el inventario ingerido."
            )

    override = CromoServicioOdfOverride(
        servicio_id=servicio_id,
        odf_n_id=odf_n_id,
        pelo_n_id=pelo_n_id,
        categoria_causa=categoria_causa,
        subcategoria=subcategoria,
        senal_direccion=senal_direccion.value if senal_direccion is not None else None,
        usuario=usuario,
        notas=notas,
    )
    sesion.add(override)
    await sesion.commit()
    await sesion.refresh(override)
    return override


async def override_vigente_de_servicio(
    sesion: AsyncSession, servicio_id: int
) -> Optional[CromoServicioOdfOverride]:
    """La asociación manual VIGENTE de un Servicio: la fila más reciente por `servicio_id`
    (`ORDER BY creado_en DESC, id DESC`), o `None` si nunca se asoció a mano.

    `id DESC` como desempate, no sólo `creado_en DESC`: dos overrides creados en la misma
    transacción (o dentro de la resolución del reloj de `timestamptz`) pueden empatar en
    `creado_en`, y `id` autoincrementa en el mismo orden de inserción — nunca ambiguo.
    """
    stmt = (
        select(CromoServicioOdfOverride)
        .where(CromoServicioOdfOverride.servicio_id == servicio_id)
        .order_by(CromoServicioOdfOverride.creado_en.desc(), CromoServicioOdfOverride.id.desc())
        .limit(1)
    )
    return (await sesion.execute(stmt)).scalar_one_or_none()


async def overrides_vigentes_por_odf(
    sesion: AsyncSession, odf_n_id: int
) -> list[CromoServicioOdfOverride]:
    """Todas las asociaciones manuales VIGENTES que apuntan a esta ODF: una fila por `servicio_id`
    (la más reciente de cada uno) — nunca el historial completo de reasociaciones de cada Servicio.

    `DISTINCT ON (servicio_id)` vía `Select.distinct(columna)` (SQLAlchemy lo traduce a `DISTINCT
    ON` sólo en el dialecto Postgres): mismo desempate `creado_en DESC, id DESC` de
    `override_vigente_de_servicio`, aplicado por grupo en una sola query en vez de N.

    Alimenta `verificador.py::servicios_por_odf`, que suma estos Servicios a los que ya trae por
    matching automático.
    """
    stmt = (
        select(CromoServicioOdfOverride)
        .where(CromoServicioOdfOverride.odf_n_id == odf_n_id)
        .distinct(CromoServicioOdfOverride.servicio_id)
        .order_by(
            CromoServicioOdfOverride.servicio_id,
            CromoServicioOdfOverride.creado_en.desc(),
            CromoServicioOdfOverride.id.desc(),
        )
    )
    resultado = await sesion.execute(stmt)
    return list(resultado.scalars().all())
