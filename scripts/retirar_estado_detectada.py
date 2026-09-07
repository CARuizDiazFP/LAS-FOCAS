# Nombre de archivo: retirar_estado_detectada.py
# Ubicación de archivo: scripts/retirar_estado_detectada.py
# Descripción: Migra retroactivamente toda Cámara/Botella con estado=DETECTADA a su estado real (LIBRE/OCUPADA/BANEADA), retirando DETECTADA del vocabulario operable

"""Retira `CamaraEstado.DETECTADA` del vocabulario operable del sistema (2026-08-11, decisión
explícita del usuario): el estado de Cámara/Botella se redujo a LIBRE/OCUPADA/BANEADA/NO_OPERATIVA.

`DETECTADA` sigue existiendo en el enum de Postgres (no se puede remover un valor de enum sin
recrear el tipo) — este script no toca el esquema, sólo migra los DATOS: para cada grupo (Cámara
padre + sus Botellas) que tenga al menos un miembro en `DETECTADA`, calcula el estado real vigente
vía `get_camara_estado_contexto` (que ya evalúa baneos/ingresos activos reales, independiente del
valor guardado en la columna `estado`) y lo aplica a TODO el grupo vía `aplicar_estado_a_grupo` —
mismo criterio de cascada completa que usa `create_ban`/`lift_ban`/el override manual, para que el
grupo quede consistente, no sólo la fila que estaba en `DETECTADA`.

Verificado contra `lasfocasdev-postgres` antes de escribir este script: 0 incidentes de baneo
activos y 0 ingresos activos en todo el sistema al 2026-08-11 — con ese estado real, cualquier grupo
tocado por este script resuelve a `LIBRE`. El código no asume eso (calcula el contexto real en cada
corrida), pero si el resultado observado NO es 100% `LIBRE`, vale la pena revisarlo con atención en
vez de asumir que es un bug del script.

**Fase 2 (hallazgo real de la primera corrida, no teórico)**: `aplicar_estado_a_grupo`/
`miembros_del_grupo` sólo recorren UN nivel de `.botellas` — no alcanzan una fila cuyo
`camara_padre_id` apunta a otra fila que a su vez ES botella de una tercera (cadena de más de 2
niveles, viola la invariante "exactamente 2 niveles" que toda la jerarquía Cámara/Botella asume;
confirmado real en dev, ej. ids 163→2552→2553). La Fase 1 deja esas filas sin tocar; una Fase 2
las corrige con una escritura directa + auditoría propia (sin cascada de grupo posible sobre una
cadena ya rota) y deja logueada la anomalía explícitamente. La cadena de más de 2 niveles en sí
**no se corrige acá** — es un problema de integridad de datos preexistente y más amplio (mismo tipo
de anomalía que los duplicados de Cámara sin sufijo Bot-N ya documentados en `docs/infra.md`),
fuera de alcance de este script.

No pega contra ningún sistema externo — sólo lee/escribe `app.camaras` y su auditoría ya poblada.

Uso:
    source .venv/bin/activate
    python scripts/retirar_estado_detectada.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datetime import datetime, timezone

from core.logging import setup_logging
from core.services.camara_estado_service import aplicar_estado_a_grupo, get_camara_estado_contexto, miembros_del_grupo
from db.models.infra import Camara, CamaraEstado, CamaraEstadoAuditoria
from db.session import SessionLocal

logger = setup_logging("retirar_estado_detectada")


def main(dry_run: bool) -> None:
    session = SessionLocal()
    try:
        detectadas = session.query(Camara).filter(Camara.estado == CamaraEstado.DETECTADA).all()
        logger.info("action=retirar_detectada filas_detectada=%d", len(detectadas))

        raices_a_migrar: dict[int, Camara] = {}
        for camara in detectadas:
            raiz = camara.camara_padre or camara
            raices_a_migrar.setdefault(raiz.id, raiz)
        logger.info("action=retirar_detectada grupos_afectados=%d", len(raices_a_migrar))

        resultado_por_estado: dict[str, int] = {"LIBRE": 0, "OCUPADA": 0, "BANEADA": 0}
        for raiz in raices_a_migrar.values():
            contexto = get_camara_estado_contexto(session, raiz.id)
            if contexto is None:
                continue
            nuevo_estado = contexto.estado_sugerido
            miembros_antes = {m.id: m.estado for m in miembros_del_grupo(raiz)}
            aplicar_estado_a_grupo(
                session,
                raiz,
                nuevo_estado,
                usuario="retiro_detectada",
                motivo="Retiro del estado DETECTADA del sistema — migrado al estado real vigente",
            )
            resultado_por_estado[nuevo_estado.value] += 1
            logger.info(
                "action=retirar_detectada grupo_raiz_id=%s nuevo_estado=%s miembros_previos=%s",
                raiz.id,
                nuevo_estado.value,
                {mid: (est.value if est else None) for mid, est in miembros_antes.items()},
            )

        logger.info("action=retirar_detectada resultado=%s", resultado_por_estado)

        # Fase 2 — red de seguridad para cadenas de más de 2 niveles (hallazgo real, no teórico):
        # `aplicar_estado_a_grupo`/`miembros_del_grupo` sólo recorren UN nivel de `.botellas` — si una
        # fila DETECTADA es "nieta" (su `camara_padre_id` apunta a otra fila que a su vez tiene
        # `camara_padre_id` seteado, violando la invariante de exactamente 2 niveles), la cascada de
        # la Fase 1 nunca la alcanza. Se corrige acá con una fila directa + auditoría propia (no hay
        # cascada de grupo posible sobre una cadena que ya está rota), y se deja constancia explícita
        # de la anomalía — la jerarquía de más de 2 niveles en sí NO se corrige en este script, es un
        # problema de integridad de datos preexistente y más amplio, fuera de alcance de este pase.
        remanentes = session.query(Camara).filter(Camara.estado == CamaraEstado.DETECTADA).all()
        if remanentes:
            ids_cadena_rota = [c.id for c in remanentes]
            logger.warning(
                "action=retirar_detectada hallazgo=cadena_mas_de_2_niveles ids=%s — la cascada de "
                "grupo no las alcanzó porque su camara_padre_id apunta a una fila que a su vez es "
                "botella de otra (invariante de 2 niveles rota preexistente); corrigiendo estado "
                "directo por fila, jerarquía NO corregida",
                ids_cadena_rota,
            )
            ahora = datetime.now(timezone.utc)
            for camara in remanentes:
                contexto_directo = get_camara_estado_contexto(session, camara.id)
                nuevo_estado_directo = contexto_directo.estado_sugerido if contexto_directo else CamaraEstado.LIBRE
                session.add(
                    CamaraEstadoAuditoria(
                        camara_id=camara.id,
                        usuario="retiro_detectada",
                        motivo=(
                            "Retiro del estado DETECTADA del sistema — fila alcanzada por fuera de la "
                            "cascada de grupo (cadena de más de 2 niveles preexistente, ver logs)"
                        ),
                        estado_anterior=camara.estado,
                        estado_nuevo=nuevo_estado_directo,
                    )
                )
                camara.estado = nuevo_estado_directo
                camara.last_update = ahora
                resultado_por_estado[nuevo_estado_directo.value] += 1
            session.flush()
            logger.info("action=retirar_detectada resultado_final=%s", resultado_por_estado)

        if dry_run:
            logger.info("action=retirar_detectada modo=dry_run — no se aplican cambios, rollback")
            session.rollback()
        else:
            session.commit()
            logger.info("action=retirar_detectada modo=aplicado — cambios commiteados")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Sólo reporta qué se migraría, sin aplicar cambios")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
