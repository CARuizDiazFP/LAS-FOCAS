# Nombre de archivo: camara_merge_service.py
# Ubicación de archivo: core/services/camara_merge_service.py
# Descripción: Fusión Cámara-a-Cámara de raíces duplicadas — la principal hereda todo lo heredable de la secundaria y la secundaria se elimina físicamente

"""Unifica dos Cámaras raíz duplicadas (`camara_padre_id IS NULL`) en una fusión real
Cámara-a-Cámara: la secundaria deja de existir como entidad tras transferir a la principal todo lo
heredable (Botellas propias, Botellas Cromo, Cables, Empalmes, Ingresos, alias y auditoría/historial).

Reemplaza el diseño previo (2026-08-11, ver `docs/decisiones.md`) que evitaba el hard delete
re-parentando la secundaria como Botella de la principal. El usuario aclaró explícitamente
(2026-08-14) que Cámara y Botella son conceptos distintos y que este flujo es entre Cámaras: la
secundaria no debe sobrevivir como Botella, debe desaparecer tras heredar todo hacia la principal.

Para que el hard delete no pierda nada por una cascada (`ON DELETE CASCADE` de Postgres o
`cascade="all, delete-orphan"` del ORM), TODA FK hacia `app.camaras.id` se reasigna explícitamente
a la principal, con `session.flush()`, antes de `session.delete(secundaria)`:

1. `Camara.camara_padre_id` (self-FK) — Botellas propias de la secundaria.
2. `CromoBotella.camara_id` — Botellas Cromo vinculadas a la secundaria.
3. `Cable.origen_camara_id` / `Cable.destino_camara_id`.
4. `Empalme.camara_id` — sin esto, `Camara.empalmes` (`cascade="all, delete-orphan"`) borraría
   empalmes reales de servicios/rutas activos al eliminar la secundaria.
5. `Ingreso.camara_id` — mismo riesgo de cascada ORM que Empalme.
6. `CamaraAlias.camara_id` — alias que la secundaria ya tenía (no sólo su nombre propio).
7. `CamaraEstadoAuditoria.camara_id` — tiene `ondelete="CASCADE"` a nivel de Postgres: sin
   reasignar, el DELETE borraría el historial completo de la secundaria pase lo que pase con el ORM.

`CromoPelo`/`CromoFusion`/`CromoCable`/`CromoTubo` no tienen `camara_id` propio (cuelgan de
`CromoBotella`/`CromoCable` por `n_id`, sin FK dura) — viajan solos en cuanto se reasigna
`CromoBotella.camara_id`, no requieren tratamiento propio.
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


class MergeCamarasError(Exception):
    """Error de validación al intentar unificar dos Cámaras — no es un error de programación,
    el llamador (endpoint) debe traducirlo a un 400, no a un 500."""


@dataclass(slots=True)
class ResultadoMergeCamaras:
    principal_id: int
    secundaria_id: int
    secundaria_nombre: str
    botellas_legado_migradas: int
    botellas_cromo_migradas: int
    cables_migrados: int
    empalmes_migrados: int
    ingresos_migrados: int
    aliases_migrados: int
    alias_creado: bool
    estado_final: str


def unificar_camaras(
    session: Session,
    *,
    principal_id: int,
    secundaria_id: int,
    usuario: str,
    guardar_alias: bool = True,
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

    nombre_secundaria = (secundaria.nombre or "").strip()
    nombre_principal = (principal.nombre or "").strip()
    estado_secundaria = secundaria.estado
    estado_principal_original = principal.estado

    # 1. Botellas propias (self-FK) de la secundaria -> hijas directas de la principal.
    botellas_legado_migradas = 0
    for botella in list(secundaria.botellas):
        botella.camara_padre_id = principal.id
        botellas_legado_migradas += 1

    # 2. Botellas Cromo vinculadas a la secundaria.
    botellas_cromo_migradas = (
        session.query(CromoBotella)
        .filter(CromoBotella.camara_id == secundaria.id)
        .update({CromoBotella.camara_id: principal.id}, synchronize_session=False)
    )

    # 3. Cables con extremo en la secundaria (ambas columnas, un cable puede tener las dos).
    cables_migrados = (
        session.query(Cable)
        .filter(Cable.origen_camara_id == secundaria.id)
        .update({Cable.origen_camara_id: principal.id}, synchronize_session=False)
    )
    cables_migrados += (
        session.query(Cable)
        .filter(Cable.destino_camara_id == secundaria.id)
        .update({Cable.destino_camara_id: principal.id}, synchronize_session=False)
    )

    # 4. Empalmes de la secundaria -> deben reasignarse ANTES del delete: `Camara.empalmes` tiene
    #    cascade="all, delete-orphan" y borraría empalmes reales de servicios/rutas activos.
    empalmes_migrados = (
        session.query(Empalme)
        .filter(Empalme.camara_id == secundaria.id)
        .update({Empalme.camara_id: principal.id}, synchronize_session=False)
    )

    # 5. Ingresos de técnico -> mismo riesgo de cascade="all, delete-orphan" que Empalme.
    ingresos_migrados = (
        session.query(Ingreso)
        .filter(Ingreso.camara_id == secundaria.id)
        .update({Ingreso.camara_id: principal.id}, synchronize_session=False)
    )

    # 6. Auditoría/historial de la secundaria -> tiene ondelete="CASCADE" en Postgres: sin
    #    reasignar, el DELETE borra este historial pase lo que pase con el ORM.
    session.query(CamaraEstadoAuditoria).filter(
        CamaraEstadoAuditoria.camara_id == secundaria.id
    ).update({CamaraEstadoAuditoria.camara_id: principal.id}, synchronize_session=False)

    # 7. Alias que la secundaria ya tenía (no sólo su nombre propio) -> se migran a la principal,
    #    evitando duplicar un alias_nombre que la principal ya tuviera (case-insensitive).
    aliases_principal_existentes = {
        (nombre or "").strip().lower()
        for (nombre,) in session.query(CamaraAlias.alias_nombre).filter(CamaraAlias.camara_id == principal.id).all()
    }
    aliases_principal_existentes.add(nombre_principal.lower())
    aliases_migrados = 0
    for alias in list(secundaria.aliases):
        clave = (alias.alias_nombre or "").strip().lower()
        if clave in aliases_principal_existentes:
            session.delete(alias)
            continue
        alias.camara_id = principal.id
        aliases_principal_existentes.add(clave)
        aliases_migrados += 1

    # 8. Alias con el nombre propio de la secundaria, sólo si el usuario lo pidió explícitamente.
    alias_creado = False
    if guardar_alias and nombre_secundaria and nombre_secundaria.lower() not in aliases_principal_existentes:
        session.add(CamaraAlias(camara_id=principal.id, alias_nombre=nombre_secundaria))
        alias_creado = True

    session.flush()

    # 9. Estado final: el más restrictivo entre el grupo de la principal (ella + sus propias
    #    Botellas, incluidas las recién heredadas) y el estado que tenía la secundaria (que está a
    #    punto de desaparecer y no puede seguir apareciendo en ningún chequeo posterior).
    grupo_principal = miembros_del_grupo(principal)
    estado_final = estado_mas_restrictivo([m.estado for m in grupo_principal] + [estado_secundaria])
    if any(m.estado != estado_final for m in grupo_principal):
        aplicar_estado_a_grupo(
            session,
            principal,
            estado_final,
            usuario=usuario,
            motivo=(
                f"Unificación de Cámaras: #{secundaria.id} ('{nombre_secundaria}') fusionada dentro de esta cámara"
            ),
        )

    # 10. Evento explícito de fusión en el historial de la principal — siempre, incluso si el
    #     estado no cambió (a diferencia de `aplicar_estado_a_grupo`, que sólo audita cambios reales).
    session.add(
        CamaraEstadoAuditoria(
            camara_id=principal.id,
            usuario=usuario,
            motivo=f"Cámara '{nombre_secundaria}' (ID {secundaria.id}) fusionada dentro de esta cámara",
            estado_anterior=estado_principal_original,
            estado_nuevo=estado_final,
        )
    )

    # 11. La secundaria ya no tiene ninguna FK real apuntándole (todo reasignado arriba) — el
    #     delete físico no dispara ninguna cascada destructiva.
    session.delete(secundaria)
    session.flush()

    return ResultadoMergeCamaras(
        principal_id=principal.id,
        secundaria_id=secundaria_id,
        secundaria_nombre=nombre_secundaria,
        botellas_legado_migradas=botellas_legado_migradas,
        botellas_cromo_migradas=botellas_cromo_migradas,
        cables_migrados=cables_migrados,
        empalmes_migrados=empalmes_migrados,
        ingresos_migrados=ingresos_migrados,
        aliases_migrados=aliases_migrados,
        alias_creado=alias_creado,
        estado_final=estado_final.value if isinstance(estado_final, CamaraEstado) else str(estado_final),
    )


@dataclass(slots=True)
class ResultadoMergeGrupo:
    principal_id: int
    secundarias_fusionadas: list[int]
    secundarias_nombres: list[str]
    botellas_legado_migradas: int
    botellas_cromo_migradas: int
    cables_migrados: int
    empalmes_migrados: int
    ingresos_migrados: int
    aliases_migrados: int
    aliases_creados: int
    estado_final: str
    resultados_individuales: list[ResultadoMergeCamaras]


def fusionar_grupo_camaras(
    session: Session,
    *,
    principal_id: int,
    secundaria_ids: list[int],
    usuario: str,
    guardar_alias: bool = True,
) -> ResultadoMergeGrupo:
    """Fusiona TODAS las Cámaras de `secundaria_ids` dentro de `principal_id` — N llamadas a
    `unificar_camaras()` (1-a-1, ya probada), no una implementación nueva.

    **`session.expire_all()` obligatorio entre cada llamada** (hallazgo real, no teórico):
    `unificar_camaras` reasigna la FK de las Botellas propias de la secundaria escribiendo la columna
    cruda (`botella.camara_padre_id = principal.id`), no el atributo de relación — el back_populates de
    SQLAlchemy no sincroniza `principal.botellas` en memoria. Sin expirar, la SIGUIENTE llamada de este
    loop leería `miembros_del_grupo(principal)` (que usa `principal.botellas`) desde una colección ya
    cacheada que no incluye lo recién reparentado por la llamada anterior, y `aplicar_estado_a_grupo`
    dejaría esas botellas con `Camara.estado` desincronizado en silencio. `session.flush()` (que
    `unificar_camaras` ya hace internamente) NO invalida colecciones ya cargadas.

    `estado_final` = el de la ÚLTIMA llamada — cada llamada ya pliega el estado de su secundaria sobre
    el grupo consolidado hasta ese punto de la principal, así que el último resultado ya es acumulado
    correctamente sin necesidad de recalcular nada acá.

    Transaccional: si cualquier `unificar_camaras()` intermedio lanza `MergeCamarasError`, el caller
    (endpoint) hace `session.rollback()` sobre TODA la sesión — no queda ninguna fusión parcial
    committeada, aunque varias llamadas anteriores del loop ya hayan hecho `flush()`.
    """
    if not secundaria_ids:
        raise MergeCamarasError("Debe indicarse al menos una Cámara secundaria para fusionar")
    if principal_id in secundaria_ids:
        raise MergeCamarasError("La Cámara principal no puede estar en la lista de Cámaras secundarias")
    if len(set(secundaria_ids)) != len(secundaria_ids):
        raise MergeCamarasError("La lista de Cámaras secundarias no puede tener ids repetidos")

    resultados: list[ResultadoMergeCamaras] = []
    for secundaria_id in secundaria_ids:
        resultado = unificar_camaras(
            session,
            principal_id=principal_id,
            secundaria_id=secundaria_id,
            usuario=usuario,
            guardar_alias=guardar_alias,
        )
        resultados.append(resultado)
        session.expire_all()

    ultimo = resultados[-1]
    return ResultadoMergeGrupo(
        principal_id=principal_id,
        secundarias_fusionadas=[r.secundaria_id for r in resultados],
        secundarias_nombres=[r.secundaria_nombre for r in resultados],
        botellas_legado_migradas=sum(r.botellas_legado_migradas for r in resultados),
        botellas_cromo_migradas=sum(r.botellas_cromo_migradas for r in resultados),
        cables_migrados=sum(r.cables_migrados for r in resultados),
        empalmes_migrados=sum(r.empalmes_migrados for r in resultados),
        ingresos_migrados=sum(r.ingresos_migrados for r in resultados),
        aliases_migrados=sum(r.aliases_migrados for r in resultados),
        aliases_creados=sum(1 for r in resultados if r.alias_creado),
        estado_final=ultimo.estado_final,
        resultados_individuales=resultados,
    )


__all__ = [
    "MergeCamarasError",
    "ResultadoMergeCamaras",
    "unificar_camaras",
    "ResultadoMergeGrupo",
    "fusionar_grupo_camaras",
]
