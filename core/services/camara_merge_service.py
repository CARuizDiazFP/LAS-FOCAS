# Nombre de archivo: camara_merge_service.py
# Ubicación de archivo: core/services/camara_merge_service.py
# Descripción: Unificación de Cámaras raíz duplicadas — la secundaria pasa a ser Botella de la principal, conservando auditoría e historial

"""Unifica dos Cámaras raíz duplicadas (`camara_padre_id IS NULL`) — decisión de diseño explícita
(2026-08-11, confirmada por el usuario): en vez de un hard delete o un flag "archivada" nuevo,
reutiliza el mecanismo ya existente de la jerarquía Cámara/Botella (`Camara.camara_padre_id`
self-FK): la Cámara secundaria queda re-parentada como Botella de la principal.

Esto da, gratis y sin reasignar FKs a mano en 4 tablas:
- Conserva el 100% de la auditoría/historial de la secundaria (`CamaraEstadoAuditoria`, sin `ondelete
  CASCADE` disparado porque la fila nunca se borra).
- Desaparece sola del dashboard de Cámaras raíz (que ya filtra `camara_padre_id IS NULL`).
- Sus rutas/servicios/empalmes propios se agregan automáticamente al ver el detalle de la principal,
  vía la misma lógica de "grupo" (`miembros_del_grupo`, `_collect_camara_rutas_info(...,
  incluir_botellas=True)`) que ya usa toda la jerarquía Cámara/Botella legado.

Lo que SÍ hay que mover explícitamente (no viaja gratis con el reparent):
- Las Botellas propias de la secundaria (si ya era ella misma un padre) — se aplanan directo a la
  principal, para no crear una cadena de 3 niveles (invariante "exactamente 2 niveles" de toda la
  jerarquía).
- Las `CromoBotella` vinculadas a la secundaria (`camara_id`) — la agregación de Botellas Cromo NO es
  recursiva por grupo (`get_camara_botellas_web` busca por `camara_id` exacto), así que quedarían
  invisibles bajo la principal si no se reasignan.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from core.services.camara_estado_service import aplicar_estado_a_grupo, miembros_del_grupo
from core.services.camara_hierarchy_service import estado_mas_restrictivo
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraAlias, CamaraEstado


class MergeCamarasError(Exception):
    """Error de validación al intentar unificar dos Cámaras — no es un error de programación,
    el llamador (endpoint) debe traducirlo a un 400, no a un 500."""


@dataclass(slots=True)
class ResultadoMergeCamaras:
    principal_id: int
    secundaria_id: int
    botellas_legado_migradas: int
    botellas_cromo_migradas: int
    alias_creado: bool
    estado_final: str


def unificar_camaras(
    session: Session,
    *,
    principal_id: int,
    secundaria_id: int,
    usuario: str,
) -> ResultadoMergeCamaras:
    if principal_id == secundaria_id:
        raise MergeCamarasError("La Cámara principal y la secundaria no pueden ser la misma")

    principal = session.query(Camara).filter(Camara.id == principal_id).first()
    if principal is None:
        raise MergeCamarasError("Cámara principal no encontrada")
    secundaria = session.query(Camara).filter(Camara.id == secundaria_id).first()
    if secundaria is None:
        raise MergeCamarasError("Cámara secundaria no encontrada")

    if principal.camara_padre_id is not None or secundaria.camara_padre_id is not None:
        raise MergeCamarasError("Sólo se pueden unificar Cámaras raíz — ninguna de las dos puede ser ya una Botella")

    # 1. Aplanar: las Botellas propias de la secundaria pasan a ser Botellas directas de la
    #    principal (nunca cadenas de 3 niveles).
    botellas_legado_migradas = 0
    for botella in list(secundaria.botellas):
        botella.camara_padre_id = principal.id
        botellas_legado_migradas += 1

    # 2. Las Botellas Cromo vinculadas a la secundaria se reasignan directo a la principal.
    botellas_cromo_migradas = (
        session.query(CromoBotella)
        .filter(CromoBotella.camara_id == secundaria.id)
        .update({CromoBotella.camara_id: principal.id}, synchronize_session=False)
    )

    # 3. La secundaria misma pasa a ser Botella de la principal.
    secundaria.camara_padre_id = principal.id

    # 4. El nombre de la secundaria queda como alias de la principal (si difiere y no existe ya).
    alias_creado = False
    nombre_secundaria = (secundaria.nombre or "").strip()
    nombre_principal = (principal.nombre or "").strip()
    if nombre_secundaria and nombre_secundaria.lower() != nombre_principal.lower():
        ya_existe = (
            session.query(CamaraAlias)
            .filter(
                CamaraAlias.camara_id == principal.id,
                CamaraAlias.alias_nombre == nombre_secundaria,
            )
            .first()
        )
        if ya_existe is None:
            session.add(CamaraAlias(camara_id=principal.id, alias_nombre=nombre_secundaria))
            alias_creado = True

    session.flush()

    # 5. Estado final del grupo completo (principal + todas sus Botellas, incluida la secundaria ya
    #    reparentada) — el más restrictivo gana, mismo criterio que la cascada de baneo existente.
    grupo = miembros_del_grupo(principal)
    estado_final = estado_mas_restrictivo(m.estado for m in grupo)
    if any(m.estado != estado_final for m in grupo):
        aplicar_estado_a_grupo(
            session,
            principal,
            estado_final,
            usuario=usuario,
            motivo=(
                f"Unificación de Cámaras duplicadas: #{secundaria.id} ('{nombre_secundaria}') "
                f"pasó a ser Botella de #{principal.id}"
            ),
        )

    return ResultadoMergeCamaras(
        principal_id=principal.id,
        secundaria_id=secundaria.id,
        botellas_legado_migradas=botellas_legado_migradas,
        botellas_cromo_migradas=botellas_cromo_migradas,
        alias_creado=alias_creado,
        estado_final=estado_final.value if isinstance(estado_final, CamaraEstado) else str(estado_final),
    )


__all__ = ["MergeCamarasError", "ResultadoMergeCamaras", "unificar_camaras"]
