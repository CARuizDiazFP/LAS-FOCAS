# Nombre de archivo: consolidacion_service.py
# Ubicación de archivo: core/services/cromo/consolidacion_service.py
# Descripción: Consolidación manual de un grupo LIBRE de Botellas Cromo duplicadas (más, opcionalmente, una o más Botellas legado) hacia un único n_id destino

"""Cierra el gap documentado 2026-08-14 en `core/services/botella_duplicados_service.py`: un grupo de
Botellas duplicadas no `resoluble` (2+ Cromo, 2+ legado, o mixto) quedaba marcado "Revisión manual" sin
ninguna acción. Política confirmada por el usuario: Cromo siempre gana — si el grupo incluye una o más
Botellas legado, sus datos se heredan a la `CromoBotella` elegida como destino (reusando
`apropiar_legado_a_cromo` tal cual, sin envolver su validación de mismo padre). El conjunto de n_ids
Cromo a consolidar es LIBRE — no está restringido a los miembros de un grupo que
`detectar_grupos_duplicados_botellas` ya haya armado por nombre normalizado; esto cubre el caso real
que motivó `app.cromo_botella_alias` (botellas sin nombre, que ese detector nunca agrupa).

Sesión SÍNCRONA (`sqlalchemy.orm.Session`), igual que `apropiar_legado_a_cromo`/
`detectar_grupos_duplicados_botellas` — deliberadamente NO reusa `core/services/cromo/alias_service.py`
(async, pensado sólo para el loop de ingesta)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.services.botella_merge_service import apropiar_legado_a_cromo
from db.models.cromo import CromoBotella, CromoBotellaAlias, CromoCable, CromoFusion

ACCION_FUSIONAR = "fusionar"


class ConsolidacionBotellaError(Exception):
    """Error de validación — el llamador (endpoint) debe traducirlo a un 400, no a un 500."""


@dataclass(slots=True)
class ResultadoConsolidacion:
    id_destino_cromo: int
    alias_creados: int = 0
    alias_actualizados: int = 0
    # [{"origen": int, "destino_anterior": int | None, "destino_nuevo": int}] — nunca silencioso: un
    # origen que ya apuntaba a OTRO destino se repuntea, pero queda reportado acá, no perdido dentro
    # de `alias_actualizados`.
    alias_repuntados: list[dict] = field(default_factory=list)
    # Alias preexistentes cuyo `id_cromo_destino` era uno de los orígenes que ahora desaparecen —
    # recableados directo al destino final para no dejar una cadena de 2 saltos (resolver_referencia,
    # en la ingesta, nunca persigue cadenas — ver core/services/cromo/alias_service.py).
    alias_dependientes_recableados: int = 0
    # `CromoCable`/`CromoFusion` YA ingeridos que apuntaban al origen antes de consolidar — el
    # `resolver_referencia` de la ingesta sólo redirige referencias que lleguen en una corrida
    # futura, así que estos hay que recablearlos ahora mismo o quedan huérfanos.
    cables_existentes_recableados: int = 0
    fusiones_existentes_recableadas: int = 0
    legados_migrados: list[int] = field(default_factory=list)
    cables_migrados: int = 0
    empalmes_migrados: int = 0
    ingresos_migrados: int = 0
    # OJO: distinto de `alias_*` de arriba — son filas `CamaraAlias` (nombres alternativos de Cámara),
    # no `CromoBotellaAlias`. Mismo campo que `ResultadoApropiacionBotella.aliases_migrados`.
    camara_aliases_migrados: int = 0
    nombre_anterior: Optional[str] = None
    nombre_nuevo: Optional[str] = None
    # legado_id de cada Botella legado apropiada donde `force_camera_association` tuvo que bypasear
    # el guard de "misma Cámara padre" — nunca silencioso, mismo criterio que `alias_repuntados`.
    legados_con_camara_forzada: list[int] = field(default_factory=list)


def consolidar_grupo_botellas(
    session: Session,
    *,
    ids_origen_cromo: list[int],
    id_destino_cromo: int,
    ids_legado: Optional[list[int]] = None,
    nombre_destino: Optional[str] = None,
    motivo: Optional[str] = None,
    usuario: str,
    force_camera_association: bool = False,
) -> ResultadoConsolidacion:
    ids_legado = ids_legado or []
    # De-dup preservando orden — un checkbox repetido o un id tipeado dos veces no debe intentar
    # crear la misma fila de alias dos veces en la misma llamada.
    ids_origen_cromo = list(dict.fromkeys(ids_origen_cromo))
    nombre_limpio = (nombre_destino or "").strip()

    if not ids_origen_cromo and not ids_legado and not nombre_limpio:
        raise ConsolidacionBotellaError(
            "Nada para consolidar: indicá al menos un origen Cromo, una Botella legado, o un nombre nuevo."
        )

    if id_destino_cromo in ids_origen_cromo:
        raise ConsolidacionBotellaError("El n_id destino no puede ser también uno de los orígenes.")

    destino = session.query(CromoBotella).filter(CromoBotella.n_id == id_destino_cromo).first()
    if destino is None:
        raise ConsolidacionBotellaError(f"No existe una Botella Cromo con n_id={id_destino_cromo}.")

    # El destino elegido no puede ser, a su vez, basura ya marcada por una decisión previa — sería
    # promover como "golden record" algo que otro alias ya declaró junk/duplicado de otra cosa.
    destino_ya_marcado = (
        session.query(CromoBotellaAlias).filter(CromoBotellaAlias.id_cromo_origen == id_destino_cromo).first()
    )
    if destino_ya_marcado is not None:
        raise ConsolidacionBotellaError(
            f"El n_id={id_destino_cromo} elegido como destino ya está marcado como "
            f"'{destino_ya_marcado.accion}' hacia otro n_id — elegí otro destino o revertí esa fila primero."
        )

    motivo_final = motivo or f"Consolidado manualmente en Visor de Botellas Duplicadas por {usuario}"

    alias_creados = 0
    alias_actualizados = 0
    alias_repuntados: list[dict] = []
    for origen in ids_origen_cromo:
        existente = session.query(CromoBotellaAlias).filter(CromoBotellaAlias.id_cromo_origen == origen).first()
        if existente is None:
            session.add(
                CromoBotellaAlias(
                    id_cromo_origen=origen,
                    id_cromo_destino=id_destino_cromo,
                    accion=ACCION_FUSIONAR,
                    motivo=motivo_final,
                    creado_por=usuario,
                )
            )
            alias_creados += 1
            continue

        if existente.id_cromo_destino != id_destino_cromo or existente.accion != ACCION_FUSIONAR:
            alias_repuntados.append(
                {
                    "origen": origen,
                    "destino_anterior": existente.id_cromo_destino,
                    "destino_nuevo": id_destino_cromo,
                }
            )
        existente.id_cromo_destino = id_destino_cromo
        existente.accion = ACCION_FUSIONAR
        existente.motivo = motivo_final
        existente.creado_por = usuario
        alias_actualizados += 1

    dependientes = (
        session.query(CromoBotellaAlias)
        .filter(CromoBotellaAlias.id_cromo_destino.in_(ids_origen_cromo))
        .all()
        if ids_origen_cromo
        else []
    )
    for dependiente in dependientes:
        dependiente.id_cromo_destino = id_destino_cromo

    cables_existentes_recableados = 0
    fusiones_existentes_recableadas = 0
    if ids_origen_cromo:
        cables_afectados = (
            session.query(CromoCable)
            .filter(
                or_(
                    CromoCable.extremo_a_n_id.in_(ids_origen_cromo),
                    CromoCable.extremo_b_n_id.in_(ids_origen_cromo),
                )
            )
            .all()
        )
        for cable in cables_afectados:
            if cable.extremo_a_n_id in ids_origen_cromo:
                cable.extremo_a_n_id = id_destino_cromo
            if cable.extremo_b_n_id in ids_origen_cromo:
                cable.extremo_b_n_id = id_destino_cromo
        cables_existentes_recableados = len(cables_afectados)

        fusiones_afectadas = (
            session.query(CromoFusion).filter(CromoFusion.botella_n_id.in_(ids_origen_cromo)).all()
        )
        for fusion in fusiones_afectadas:
            fusion.botella_n_id = id_destino_cromo
        fusiones_existentes_recableadas = len(fusiones_afectadas)

        # El origen deja de contar como Botella Cromo vigente — mismo flag que ya filtran
        # `detectar_grupos_duplicados_botellas`/`buscar_huerfanas`/`buscar_botellas_unificadas`;
        # sin esto, el grupo "duplicado" recién consolidado sigue apareciendo tal cual.
        for origen_botella in session.query(CromoBotella).filter(CromoBotella.n_id.in_(ids_origen_cromo)).all():
            origen_botella.vigente = False

    session.flush()

    legados_migrados: list[int] = []
    legados_con_camara_forzada: list[int] = []
    cables_migrados = 0
    empalmes_migrados = 0
    ingresos_migrados = 0
    camara_aliases_migrados = 0
    for legado_id in ids_legado:
        resultado_legado = apropiar_legado_a_cromo(
            session,
            legado_id=legado_id,
            cromo_n_id=id_destino_cromo,
            usuario=usuario,
            forzar_camara=force_camera_association,
        )
        legados_migrados.append(legado_id)
        cables_migrados += resultado_legado.cables_migrados
        empalmes_migrados += resultado_legado.empalmes_migrados
        ingresos_migrados += resultado_legado.ingresos_migrados
        camara_aliases_migrados += resultado_legado.aliases_migrados
        if resultado_legado.camara_forzada:
            legados_con_camara_forzada.append(legado_id)

    nombre_anterior = destino.nombre
    nombre_nuevo = None
    if nombre_limpio:
        destino.nombre = nombre_limpio
        nombre_nuevo = nombre_limpio

    session.flush()

    return ResultadoConsolidacion(
        id_destino_cromo=id_destino_cromo,
        alias_creados=alias_creados,
        alias_actualizados=alias_actualizados,
        alias_repuntados=alias_repuntados,
        alias_dependientes_recableados=len(dependientes),
        cables_existentes_recableados=cables_existentes_recableados,
        fusiones_existentes_recableadas=fusiones_existentes_recableadas,
        legados_migrados=legados_migrados,
        cables_migrados=cables_migrados,
        empalmes_migrados=empalmes_migrados,
        ingresos_migrados=ingresos_migrados,
        camara_aliases_migrados=camara_aliases_migrados,
        nombre_anterior=nombre_anterior,
        nombre_nuevo=nombre_nuevo,
        legados_con_camara_forzada=legados_con_camara_forzada,
    )


__all__ = ["ConsolidacionBotellaError", "ResultadoConsolidacion", "consolidar_grupo_botellas"]
