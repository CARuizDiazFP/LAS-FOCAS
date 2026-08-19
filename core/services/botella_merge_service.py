# Nombre de archivo: botella_merge_service.py
# Ubicación de archivo: core/services/botella_merge_service.py
# Descripción: Apropiación legado→Cromo de Botellas duplicadas dentro de la misma Cámara padre — Cromo se conserva, la legado se elimina tras reasignar sus datos reales al padre compartido

"""Política de resolución de duplicados de Botella (confirmada explícitamente por el usuario,
2026-08-14): "Cromo es la fuente de verdad. Lo legado queda eliminado en caso de duplicados. Las
Botellas de Cromo y sus respectivas Cámaras son las que deben apropiarse de los datos que no estén
duplicados."

Sólo se resuelve automáticamente el caso mixto de exactamente 1 Botella legado + 1 `CromoBotella`
hermanas (mismo padre) — ver `core/services/botella_duplicados_service.py::GrupoBotellasDuplicadas.
resoluble`. La `CromoBotella` se conserva intacta; la Botella legado se elimina físicamente tras
reasignar sus FKs reales hacia la Cámara PADRE compartida — nunca hacia la `CromoBotella`, que vive
en otra tabla con otra PK (`n_id`) y estructuralmente no puede recibir FKs de tipo `Camara`.

Mismo esqueleto que `camara_merge_service.py::unificar_camaras` (no un rewrite desde cero), adaptado
a la asimetría legado→Cromo:
1. `Camara.camara_padre_id` (self-FK) — hijas propias de la legado (caso-borde defensivo: viola el
   invariante de 2 niveles, pero hay 6 filas reales que ya lo violan, ver docs/decisiones.md).
2. `CromoBotella.camara_id` que apuntara a la legado (defensivo — no debería pasar nunca).
3. `Cable.origen_camara_id` / `Cable.destino_camara_id`.
4. `Empalme.camara_id` — `Camara.empalmes` tiene `cascade="all, delete-orphan"`.
5. `Ingreso.camara_id`.
6. `CamaraAlias.camara_id` — se migran los alias que la legado ya tenía, SIN crear uno nuevo con su
   nombre propio (a diferencia de `unificar_camaras`; no fue pedido para este flujo).
7. `CamaraEstadoAuditoria.camara_id` — `ondelete="CASCADE"` en Postgres, preserva el historial.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from core.services.camara_estado_service import aplicar_estado_a_grupo, miembros_del_grupo
from core.services.camara_hierarchy_service import estado_mas_restrictivo
from db.models.cromo import CromoBotella
from db.models.infra import (
    Cable,
    Camara,
    CamaraAlias,
    CamaraEstado,
    CamaraEstadoAuditoria,
    Empalme,
    Ingreso,
)


class ApropiacionBotellaError(Exception):
    """Error de validación — el llamador (endpoint) debe traducirlo a un 400, no a un 500."""


@dataclass(slots=True)
class ResultadoApropiacionBotella:
    legado_id: int
    legado_nombre: str
    cromo_n_id: int
    cromo_nombre: str | None
    camara_padre_id: int
    camara_padre_nombre: str
    botellas_legado_migradas: int
    cromo_reasignadas: int
    cables_migrados: int
    empalmes_migrados: int
    ingresos_migrados: int
    aliases_migrados: int
    estado_final: str


def apropiar_legado_a_cromo(
    session: Session,
    *,
    legado_id: int,
    cromo_n_id: int,
    usuario: str,
) -> ResultadoApropiacionBotella:
    legado = session.query(Camara).filter(Camara.id == legado_id).first()
    if legado is None:
        raise ApropiacionBotellaError("Botella legado no encontrada")
    if legado.camara_padre_id is None:
        raise ApropiacionBotellaError("La fila indicada no es una Botella (no tiene Cámara padre)")

    cromo = session.query(CromoBotella).filter(CromoBotella.n_id == cromo_n_id).first()
    if cromo is None:
        raise ApropiacionBotellaError("Botella Cromo no encontrada")

    if cromo.camara_id != legado.camara_padre_id:
        raise ApropiacionBotellaError(
            "La Botella Cromo no pertenece a la misma Cámara padre que la Botella legado"
        )

    padre = session.query(Camara).filter(Camara.id == legado.camara_padre_id).first()
    if padre is None:
        raise ApropiacionBotellaError("Cámara padre no encontrada")

    nombre_legado = legado.nombre or ""
    estado_legado = legado.estado
    estado_padre_original = padre.estado

    # 1. Hijas propias de la legado (defensivo — no debería tener por el invariante de 2 niveles).
    botellas_legado_migradas = (
        session.query(Camara)
        .filter(Camara.camara_padre_id == legado.id)
        .update({Camara.camara_padre_id: padre.id}, synchronize_session=False)
    )

    # 2. CromoBotella que apuntaran a la legado (defensivo — no debería pasar nunca).
    cromo_reasignadas = (
        session.query(CromoBotella)
        .filter(CromoBotella.camara_id == legado.id)
        .update({CromoBotella.camara_id: padre.id}, synchronize_session=False)
    )

    # 3. Cables con extremo en la legado.
    cables_migrados = (
        session.query(Cable)
        .filter(Cable.origen_camara_id == legado.id)
        .update({Cable.origen_camara_id: padre.id}, synchronize_session=False)
    )
    cables_migrados += (
        session.query(Cable)
        .filter(Cable.destino_camara_id == legado.id)
        .update({Cable.destino_camara_id: padre.id}, synchronize_session=False)
    )

    # 4. Empalmes — crítico: Camara.empalmes tiene cascade="all, delete-orphan".
    empalmes_migrados = (
        session.query(Empalme)
        .filter(Empalme.camara_id == legado.id)
        .update({Empalme.camara_id: padre.id}, synchronize_session=False)
    )

    # 5. Ingresos de técnico — mismo riesgo de cascada que Empalme.
    ingresos_migrados = (
        session.query(Ingreso)
        .filter(Ingreso.camara_id == legado.id)
        .update({Ingreso.camara_id: padre.id}, synchronize_session=False)
    )

    # 6. Alias que la legado ya tenía — se migran, sin crear uno nuevo con su nombre propio.
    aliases_padre_existentes = {
        (nombre or "").strip().lower()
        for (nombre,) in session.query(CamaraAlias.alias_nombre).filter(CamaraAlias.camara_id == padre.id).all()
    }
    aliases_migrados = 0
    for alias in list(legado.aliases):
        clave = (alias.alias_nombre or "").strip().lower()
        if clave in aliases_padre_existentes:
            session.delete(alias)
            continue
        alias.camara_id = padre.id
        aliases_padre_existentes.add(clave)
        aliases_migrados += 1

    session.flush()

    # 7. Estado final: más restrictivo entre el grupo del padre y el estado de la legado, que está a
    #    punto de desaparecer y no puede seguir apareciendo en ningún chequeo posterior.
    grupo_padre = miembros_del_grupo(padre)
    estado_final = estado_mas_restrictivo([m.estado for m in grupo_padre] + [estado_legado])
    if any(m.estado != estado_final for m in grupo_padre):
        aplicar_estado_a_grupo(
            session,
            padre,
            estado_final,
            usuario=usuario,
            motivo=(
                f"Apropiación de Botella: '{nombre_legado}' (ID {legado.id}) absorbida por "
                f"Botella Cromo '{cromo.nombre}' (n_id {cromo.n_id})"
            ),
        )

    # 8. Evento explícito de apropiación en el historial del padre — siempre, incluso sin cambio de estado.
    session.add(
        CamaraEstadoAuditoria(
            camara_id=padre.id,
            usuario=usuario,
            motivo=(
                f"Botella legado '{nombre_legado}' (ID {legado.id}) apropiada por Botella Cromo "
                f"'{cromo.nombre}' (n_id {cromo.n_id}); datos reasignados a esta Cámara"
            ),
            estado_anterior=estado_padre_original,
            estado_nuevo=estado_final,
        )
    )

    # 9. La legado ya no tiene ninguna FK real apuntándole — el delete físico no dispara cascadas.
    session.delete(legado)
    session.flush()

    return ResultadoApropiacionBotella(
        legado_id=legado_id,
        legado_nombre=nombre_legado,
        cromo_n_id=cromo.n_id,
        cromo_nombre=cromo.nombre,
        camara_padre_id=padre.id,
        camara_padre_nombre=padre.nombre or "",
        botellas_legado_migradas=botellas_legado_migradas,
        cromo_reasignadas=cromo_reasignadas,
        cables_migrados=cables_migrados,
        empalmes_migrados=empalmes_migrados,
        ingresos_migrados=ingresos_migrados,
        aliases_migrados=aliases_migrados,
        estado_final=estado_final.value if isinstance(estado_final, CamaraEstado) else str(estado_final),
    )


__all__ = ["ApropiacionBotellaError", "ResultadoApropiacionBotella", "apropiar_legado_a_cromo"]
