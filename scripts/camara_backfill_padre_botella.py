# Nombre de archivo: camara_backfill_padre_botella.py
# Ubicación de archivo: scripts/camara_backfill_padre_botella.py
# Descripción: Backfill one-off de la jerarquía Cámara/Botella (camaras.camara_padre_id) sobre filas ya ingeridas

"""Aplica retroactivamente la jerarquía Cámara/Botella a las filas de `app.camaras` ya existentes.

Para cada fila cuyo nombre matchea el sufijo "Bot N" (`core/services/camara_hierarchy_service.py`,
regex `RE_BOT_SUFIJO` de `modules/slack_baneo_notifier/camara_search.py`), resuelve (o crea) su cámara
padre vía `resolver_o_crear_padre()` — la misma función que usan los 6 caminos de alta en vivo, sin
duplicar lógica. Esa función:

- Nunca promueve una fila existente a "padre": si ya existe una fila raíz "pelada" (sin sufijo) con
  el mismo nombre base, la absorbe como botella del padre nuevo en vez de convertirla ella misma en
  padre (ej. real: "Cra 14 de Julio 240 CF" y "Cra 14 de Julio 240 Bot 2 CF" — ninguna de las dos se
  promueve, se crea una tercera fila `INFERIDO` como padre y ambas quedan como sus botellas).
- Reusa un padre ya creado si corre dos veces sobre el mismo nombre — idempotente.

Fuera de alcance de este backfill (ver plan, sección 3): fusión de duplicados exactos por nombre
normalizado que NO tienen sufijo Bot-N (clusters de variantes de escritura, ej. "Cra Est. Avellaneda" /
"Cámara Estacion Avellaneda" — ninguna normalización de string los une) — se reportan en el log como
hallazgo de calidad de datos, sin auto-fusionar.

No pega contra Cromo ni contra ningún sistema externo — sólo lee/escribe `app.camaras` ya poblada.

Uso:
    source .venv/bin/activate
    python scripts/camara_backfill_padre_botella.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.logging import setup_logging
from core.services.camara_estado_service import aplicar_estado_a_grupo, miembros_del_grupo
from core.services.camara_hierarchy_service import (
    estado_mas_restrictivo,
    extraer_base,
    normalizar_para_agrupar,
    resolver_o_crear_padre,
)
from db.models.infra import Camara, CamaraEstado
from db.session import SessionLocal

logger = setup_logging("camara_backfill_padre_botella")


def _detectar_duplicados_sin_sufijo(camaras: list[Camara]) -> dict[str, list[Camara]]:
    """Agrupa por nombre normalizado las filas SIN sufijo Bot-N que comparten nombre — hallazgo de
    calidad de datos, sólo para el log (ver docstring del módulo, no se auto-fusiona)."""
    grupos: dict[str, list[Camara]] = defaultdict(list)
    for camara in camaras:
        if extraer_base(camara.nombre) is not None:
            continue
        grupos[normalizar_para_agrupar(camara.nombre)].append(camara)
    return {clave: filas for clave, filas in grupos.items() if len(filas) > 1}


def main(dry_run: bool) -> None:
    session = SessionLocal()
    try:
        candidatas = (
            session.query(Camara)
            .filter(Camara.camara_padre_id.is_(None))
            .order_by(Camara.id)
            .all()
        )
        logger.info("action=camara_backfill total_raices=%d", len(candidatas))

        con_sufijo = [c for c in candidatas if extraer_base(c.nombre) is not None]
        logger.info("action=camara_backfill con_sufijo_bot_n=%d", len(con_sufijo))

        padres_creados: set[int] = set()
        vinculadas = 0
        for camara in con_sufijo:
            padre = resolver_o_crear_padre(session, camara.nombre, usuario="backfill")
            if padre is None:
                continue
            if padre.id not in padres_creados:
                padres_creados.add(padre.id)
            if camara.camara_padre_id is None:
                camara.camara_padre_id = padre.id
                vinculadas += 1

        logger.info(
            "action=camara_backfill padres_resueltos=%d filas_vinculadas=%d",
            len(padres_creados),
            vinculadas,
        )

        # Si algún miembro del grupo ya estaba en un estado más restrictivo que LIBRE ANTES del
        # backfill (ej. una botella BANEADA por un incidente ya activo), propagarlo retroactivamente
        # a todo el grupo — mismo criterio de cascada completa que usan create_ban/lift_ban/
        # override_camara_estado_manual en vivo (`aplicar_estado_a_grupo`).
        #
        # Grupos con algún miembro PENDIENTE_REVISION se saltan por completo (ni siquiera se calcula
        # `estado_mas_restrictivo` sobre ellos) — bug real encontrado corriendo este script contra
        # datos reales: `aplicar_estado_a_grupo` aplica el mismo estado a TODOS los miembros sin
        # excepción, así que aunque `estado_mas_restrictivo` ya ignora PENDIENTE_REVISION al elegir el
        # estado ganador, seguiría sobreescribiendo la fila PENDIENTE_REVISION con ese resultado — una
        # cámara pendiente de triage admin no debe salir de ese estado por este backfill.
        grupos_escalados = 0
        grupos_con_pendiente_revision = 0
        for padre_id in padres_creados:
            padre = session.query(Camara).filter(Camara.id == padre_id).first()
            if padre is None:
                continue
            grupo = miembros_del_grupo(padre)
            if any(m.estado == CamaraEstado.PENDIENTE_REVISION for m in grupo):
                grupos_con_pendiente_revision += 1
                logger.warning(
                    "action=camara_backfill hallazgo=grupo_con_pendiente_revision padre_id=%s "
                    "miembros=%s — no se toca el estado, requiere triage admin normal",
                    padre_id,
                    [m.id for m in grupo],
                )
                continue
            estado_grupo = estado_mas_restrictivo(m.estado for m in grupo)
            if any(m.estado != estado_grupo for m in grupo):
                aplicar_estado_a_grupo(
                    session,
                    padre,
                    estado_grupo,
                    usuario="backfill",
                    motivo="Backfill jerarquía Cámara/Botella — estado heredado del grupo preexistente",
                )
                grupos_escalados += 1
        logger.info(
            "action=camara_backfill grupos_con_estado_escalado=%d grupos_con_pendiente_revision=%d",
            grupos_escalados,
            grupos_con_pendiente_revision,
        )

        duplicados = _detectar_duplicados_sin_sufijo(candidatas)
        if duplicados:
            logger.warning(
                "action=camara_backfill hallazgo=duplicados_sin_sufijo grupos=%d — "
                "no se auto-fusionan, requieren revisión manual",
                len(duplicados),
            )
            for clave, filas in duplicados.items():
                logger.warning(
                    "action=camara_backfill duplicado nombre_norm='%s' ids=%s nombres=%s",
                    clave,
                    [c.id for c in filas],
                    [c.nombre for c in filas],
                )

        if dry_run:
            logger.info("action=camara_backfill modo=dry_run — no se aplican cambios, rollback")
            session.rollback()
        else:
            session.commit()
            logger.info("action=camara_backfill modo=aplicado — cambios commiteados")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Sólo reporta qué se crearía/vincularía, sin aplicar cambios")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
