# Nombre de archivo: servicios_fusionar_identidades_duplicadas.py
# Ubicación de archivo: scripts/servicios_fusionar_identidades_duplicadas.py
# Descripción: Detecta y fusiona pares de app.servicios que representan el mismo servicio real bajo dos filas distintas (una "superada" cuya propia identidad ya fue absorbida como alias de otra fila "vigente")

"""Generaliza la fusión aplicada a mano el 2026-08-31 para el par id=49/id=557 (servicio
"41140->61943" de Banco Comafi SA, ticket duplicidad Buscador/ODFs) al resto de los pares del mismo
patrón encontrados en `focas_dev`: 642 pares al momento de escribir esto, ~11.000 filas de
`cromo_servicio_match` ya matcheadas contra la fila "perdedora" de cada par, al menos 15 filas
perdedoras con tracking físico real propio (`rutas_servicio`).

Un par calza el patrón cuando la fila "superada" tiene su propio `servicio_id`/`numero_primer_servicio`
ya presente en el `alias_ids` de otra fila "vigente" — la misma señal autoritativa que ahora excluye
`core/services/cromo/ingesta.py::_SQL_BUSCAR_SERVICIO` (fix hacia adelante del mismo ticket). Para
cada par:

1. Reasigna a la fila vigente las 3 tablas que referencian `app.servicios.id` sin `ON DELETE CASCADE`
   salvo `rutas_servicio` (`cromo_servicio_match`, `servicio_empalme_association`, `rutas_servicio`) —
   mismo trío que ya reasigna `api/app/routes/servicios.py::ingest_servicios` al fusionar
   placeholders, auditado real contra `information_schema` (ver docs/decisiones.md, 2026-08-31).
2. Mezcla `alias_ids` de la superada dentro de la vigente (sin perder alias legítimos, ej. "C18").
3. Libera el número contestado como `servicio_id` final de la vigente (el mismo criterio de
   "MAX-based ID final" que ya usa `consolidar_identidad_servicio`) y lo saca de `alias_ids` (ya no
   tiene sentido como alias de sí mismo).
4. Borra la fila superada.

Pares con más de un candidato "vigente" (dato ambiguo real, no un simple par 1-a-1) se SALTAN y se
listan aparte para revisión manual — el script nunca adivina cuál de varios candidatos es el
correcto. Lo mismo para pares MUTUOS (A superada de B y B superada de A a la vez, ej. ids 30338/30339
en dev: dos filas `INGEST_EXCEL` reales que se referencian una a la otra en `alias_ids` — no es una
renumeración simple, es un dato cruzado que necesita revisión humana, no una fusión automática).

**NO se corrió con `--apply` contra el resto de los 642 pares al cerrar el ticket 2026-08-31** —
sólo el par puntual 49/557 se fusionó a mano, verificado en vivo. Este script queda escrito y
auditado para una corrida posterior, con aprobación explícita separada del usuario (ver
docs/decisiones.md, entrada 2026-08-31). Por defecto corre en modo reporte: lista los pares
candidatos y cuántas filas de cada tabla se reasignarían, sin tocar nada.

Uso:
    source .venv/bin/activate
    python scripts/servicios_fusionar_identidades_duplicadas.py                    # sólo reporta
    python scripts/servicios_fusionar_identidades_duplicadas.py --apply            # fusiona todos los pares 1-a-1
    python scripts/servicios_fusionar_identidades_duplicadas.py --apply --solo-vigente-id 557  # acota a un id vigente puntual
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text

from core.logging import setup_logging
from db.session import SessionLocal

logger = setup_logging("servicios_fusionar_identidades_duplicadas")

# Un candidato "superada" puede matchear más de una fila "vigente" si el dato real es más enredado
# que un simple par 1-a-1 (ej. su número quedó como alias de DOS filas distintas por una
# inconsistencia previa) — se lista aparte, `HAVING count(DISTINCT vigente_id) = 1` filtra sólo los
# pares no ambiguos.
_SQL_PARES_CANDIDATOS = text(
    """
    SELECT a.id AS superada_id, min(b.id) AS vigente_id, count(DISTINCT b.id) AS candidatos_vigente
    FROM app.servicios a
    JOIN app.servicios b
      ON a.id <> b.id
     AND (a.servicio_id = ANY(b.alias_ids) OR a.numero_primer_servicio = ANY(b.alias_ids))
    GROUP BY a.id
    """
)

_SQL_FILA_SERVICIO = text(
    "SELECT id, servicio_id, numero_primer_servicio, alias_ids FROM app.servicios WHERE id = :id"
)

_SQL_CONTAR_REFS = text(
    """
    SELECT
        (SELECT count(*) FROM app.cromo_servicio_match WHERE servicio_id = :id) AS matches,
        (SELECT count(*) FROM app.rutas_servicio WHERE servicio_id = :id) AS rutas,
        (SELECT count(*) FROM app.servicio_empalme_association WHERE servicio_id = :id) AS empalmes
    """
)


def _identidad_contestada(superada: Any, vigente: Any) -> Optional[str]:
    """El valor de la superada (`servicio_id` o `numero_primer_servicio`) que aparece en el
    `alias_ids` de la vigente — es el número que debe liberarse como `servicio_id` final de la
    vigente al fusionar (mismo criterio "MAX-based ID final" de `consolidar_identidad_servicio`)."""
    alias_vigente = set(vigente.alias_ids or [])
    if superada.servicio_id in alias_vigente:
        return superada.servicio_id
    if superada.numero_primer_servicio in alias_vigente:
        return superada.numero_primer_servicio
    return None


def _fusionar_par(session, superada_id: int, vigente_id: int) -> dict[str, int]:
    superada = session.execute(_SQL_FILA_SERVICIO, {"id": superada_id}).first()
    vigente = session.execute(_SQL_FILA_SERVICIO, {"id": vigente_id}).first()
    if superada is None or vigente is None:
        raise RuntimeError(f"Fila ya no existe: superada_id={superada_id} vigente_id={vigente_id}")

    contestado = _identidad_contestada(superada, vigente)
    if contestado is None:
        raise RuntimeError(
            f"No se pudo determinar la identidad contestada para superada_id={superada_id} "
            f"vigente_id={vigente_id} — posible cambio de datos entre el reporte y la corrida"
        )

    refs = session.execute(_SQL_CONTAR_REFS, {"id": superada_id}).first()

    session.execute(
        text("UPDATE app.cromo_servicio_match SET servicio_id = :vigente WHERE servicio_id = :superada"),
        {"vigente": vigente_id, "superada": superada_id},
    )
    session.execute(
        text("UPDATE app.rutas_servicio SET servicio_id = :vigente WHERE servicio_id = :superada"),
        {"vigente": vigente_id, "superada": superada_id},
    )
    session.execute(
        text("UPDATE app.servicio_empalme_association SET servicio_id = :vigente WHERE servicio_id = :superada"),
        {"vigente": vigente_id, "superada": superada_id},
    )

    session.execute(
        text(
            "UPDATE app.servicios "
            "SET alias_ids = array(SELECT DISTINCT unnest(alias_ids || :nuevos_alias ::varchar[])) "
            "WHERE id = :vigente"
        ),
        {"vigente": vigente_id, "nuevos_alias": list(superada.alias_ids or [])},
    )
    session.execute(text("DELETE FROM app.servicios WHERE id = :superada"), {"superada": superada_id})
    session.execute(
        text(
            "UPDATE app.servicios "
            "SET servicio_id = :contestado, alias_ids = array_remove(alias_ids, :contestado) "
            "WHERE id = :vigente"
        ),
        {"contestado": contestado, "vigente": vigente_id},
    )

    return {"matches": refs.matches, "rutas": refs.rutas, "empalmes": refs.empalmes}


def main(apply: bool, solo_vigente_id: Optional[int]) -> None:
    inicio = time.perf_counter()
    session = SessionLocal()
    try:
        pares = session.execute(_SQL_PARES_CANDIDATOS).all()
        pares_1a1 = [p for p in pares if p.candidatos_vigente == 1]
        pares_ambiguos = [p for p in pares if p.candidatos_vigente > 1]

        # Pares MUTUOS: A superada de B y B superada de A a la vez — dato cruzado, no una
        # renumeración simple (ver docstring del módulo). Se excluyen de la fusión automática y se
        # listan aparte, igual que los ambiguos de más de un candidato.
        direcciones = {(p.superada_id, p.vigente_id) for p in pares_1a1}
        pares_mutuos = [p for p in pares_1a1 if (p.vigente_id, p.superada_id) in direcciones]
        pares_simples = [p for p in pares_1a1 if p not in pares_mutuos]

        if solo_vigente_id is not None:
            pares_simples = [p for p in pares_simples if p.vigente_id == solo_vigente_id]

        logger.info(
            "action=fusionar_identidades pares_totales=%d pares_1a1_seguros=%d pares_ambiguos_saltados=%d "
            "pares_mutuos_saltados=%d",
            len(pares),
            len(pares_simples),
            len(pares_ambiguos),
            len(pares_mutuos),
        )
        for p in pares_ambiguos:
            logger.warning(
                "action=fusionar_identidades evento=par_ambiguo_saltado superada_id=%s candidatos_vigente=%d "
                "— requiere revisión manual, no se procesa automáticamente",
                p.superada_id,
                p.candidatos_vigente,
            )
        for p in pares_mutuos:
            logger.warning(
                "action=fusionar_identidades evento=par_mutuo_saltado superada_id=%s vigente_id=%s "
                "— ambas filas se referencian mutuamente en alias_ids, requiere revisión manual",
                p.superada_id,
                p.vigente_id,
            )

        total_matches = total_rutas = total_empalmes = 0
        fusionados = 0
        for p in pares_simples:
            try:
                if apply:
                    with session.begin_nested():
                        conteos = _fusionar_par(session, p.superada_id, p.vigente_id)
                else:
                    refs = session.execute(_SQL_CONTAR_REFS, {"id": p.superada_id}).first()
                    conteos = {"matches": refs.matches, "rutas": refs.rutas, "empalmes": refs.empalmes}
                total_matches += conteos["matches"]
                total_rutas += conteos["rutas"]
                total_empalmes += conteos["empalmes"]
                fusionados += 1
                logger.info(
                    "action=fusionar_identidades evento=%s superada_id=%s vigente_id=%s "
                    "matches=%d rutas=%d empalmes=%d",
                    "fusionado" if apply else "candidato",
                    p.superada_id,
                    p.vigente_id,
                    conteos["matches"],
                    conteos["rutas"],
                    conteos["empalmes"],
                )
            except Exception as exc:  # noqa: BLE001 - un par con error no debe abortar el resto
                logger.error(
                    "action=fusionar_identidades evento=error superada_id=%s vigente_id=%s error=%s",
                    p.superada_id,
                    p.vigente_id,
                    exc,
                )

        elapsed = time.perf_counter() - inicio
        logger.info(
            "action=fusionar_identidades modo=%s pares_procesados=%d matches_reasignados=%d "
            "rutas_reasignadas=%d empalmes_reasignados=%d elapsed_seg=%.1f",
            "aplicado" if apply else "reporte",
            fusionados,
            total_matches,
            total_rutas,
            total_empalmes,
            elapsed,
        )

        if apply:
            session.commit()
            logger.info("action=fusionar_identidades modo=aplicado — cambios commiteados")
        else:
            session.rollback()
            logger.info("action=fusionar_identidades modo=reporte — no se aplicó ningún cambio")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Aplica la fusión (por defecto sólo reporta)")
    parser.add_argument(
        "--solo-vigente-id",
        type=int,
        default=None,
        help="Acota la fusión a los pares cuya fila vigente sea este id puntual",
    )
    args = parser.parse_args()
    main(apply=args.apply, solo_vigente_id=args.solo_vigente_id)
