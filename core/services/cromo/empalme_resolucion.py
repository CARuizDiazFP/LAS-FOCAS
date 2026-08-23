# Nombre de archivo: empalme_resolucion.py
# Ubicación de archivo: core/services/cromo/empalme_resolucion.py
# Descripción: Resolución inversa "ID de empalme → Botella dueña", para el seguimiento por hilo del listener de ingresos

"""Resuelve "a qué Botella pertenece esta fusión (empalme)" — la pregunta inversa de
`core/services/cromo/empalmes.py` (que responde "qué empalmes tiene esta Botella"). Pensado para el
mecanismo de "hilo esperando ID de empalme" del listener de Slack de ingreso de técnicos
(`modules/slack_baneo_notifier/listener.py`): cuando el técnico no puede identificar la cámara por
nombre, se le ofrece responder con el ID de empalme más cercano, y este módulo resuelve la Botella
(y su Cámara padre) a partir de ese ID — síncrono porque corre dentro de un callback síncrono de
Slack Bolt (mismo motivo que `verificador.servicios_por_tubo_sync`).

Prioridad 1: `CromoFusion.botella_n_id` (`app.cromo_fusiones`), cuando está poblado — consulta
barata, no rompe nada si sigue vacío (mismo criterio documentado en `empalmes.py`: en la práctica
casi nunca lo está, ver docstring de ese módulo). Si apunta a un `n_id` sin fila propia en
`app.cromo_botellas` (puntero obsoleto), se trata como si no hubiera estado poblado y se cae a
Prioridad 2 — no se devuelve una `BotellaDeFusion` fabricada con datos inexistentes.

Prioridad 2 (el caso real): se resuelven los cables de `pelo_a_n_id`/`pelo_b_n_id` de la fusión (vía
`app.cromo_pelos.cable_n_id`) y se busca la `CromoBotella` que aparece como extremo compartido
(`extremo_a_n_id`/`extremo_b_n_id` de `app.cromo_cables`) entre AMBOS cables — la fusión ocurre
físicamente dentro de la Botella que es el extremo común de los dos cables que entran a ella.

Referencia colgada (documentado con el mismo criterio que `empalmes.py`): si uno de los dos pelos no
tiene fila propia en `app.cromo_pelos`, o su `cable_n_id` no tiene fila propia en
`app.cromo_cables`, sólo se puede resolver UN cable — en ese caso se usa el único extremo resuelto
de ese cable que efectivamente tiene fila en `app.cromo_botellas` (el otro extremo del mismo cable
puede no existir como Botella ingerida, o ser el extremo lejano sin relación con esta fusión).

Empate/ambigüedad: si tras filtrar por existencia real en `app.cromo_botellas` quedan 2 o más
Botellas candidatas con igual "peso" (ambas aparecen como extremo compartido, o ambos extremos del
único cable resuelto existen como Botella), se devuelve `None` — no se elige arbitrariamente.

SQL crudo (`sqlalchemy.text()`), mismo estilo que `empalmes.py`/`verificador.py` — sin relationships
ORM nuevas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_SQL_FUSION_POR_N_ID = text(
    "SELECT botella_n_id, pelo_a_n_id, pelo_b_n_id FROM app.cromo_fusiones WHERE n_id = :fusion_n_id"
)

# Batcheada (mismo espíritu que `verificador.tiene_cables_asociados_batch_sync`): una sola query
# para resolver los extremos de ambos pelos de la fusión, en vez de una por pelo — y como side
# effect, sirve como el chequeo natural de "referencia colgada": si un pelo no tiene fila propia en
# `cromo_pelos`, o su cable no tiene fila propia en `cromo_cables`, el JOIN simplemente no devuelve
# fila para ese `pelo_n_id`.
_SQL_EXTREMOS_DE_PELOS = text(
    """
    SELECT p.n_id, c.extremo_a_n_id, c.extremo_b_n_id
    FROM app.cromo_pelos p
    JOIN app.cromo_cables c ON c.n_id = p.cable_n_id
    WHERE p.n_id = ANY(:pelo_ids ::bigint[])
    """
)

# Batcheada también: resuelve de una sola vez cuáles de los `n_id` candidatos tienen fila propia en
# `cromo_botellas` (y con qué datos) — se usa tanto para el chequeo directo de Prioridad 1 como para
# filtrar los candidatos de Prioridad 2 a los que realmente existen como Botella ingerida.
_SQL_BOTELLAS_POR_N_IDS = text(
    """
    SELECT n_id, nombre, camara_id
    FROM app.cromo_botellas
    WHERE n_id = ANY(:n_ids ::bigint[])
    """
)


@dataclass(slots=True)
class BotellaDeFusion:
    """Botella resuelta como dueña de una fusión — sólo los campos que necesita el listener de
    ingresos para aplicar el chequeo de acceso (`camara_id` → `Camara` raíz)."""

    n_id: int
    nombre: Optional[str]
    camara_id: Optional[int]


def _fetch_botellas(session: Session, n_ids: list[int]) -> dict[int, BotellaDeFusion]:
    """Resuelve, de un solo query, cuáles de `n_ids` tienen fila propia en `cromo_botellas`.

    Retorna sólo las que existen — un `n_id` sin fila propia (referencia colgada) simplemente no
    aparece en el dict resultante.
    """
    if not n_ids:
        return {}
    filas = session.execute(_SQL_BOTELLAS_POR_N_IDS, {"n_ids": list(n_ids)}).all()
    return {fila[0]: BotellaDeFusion(n_id=fila[0], nombre=fila[1], camara_id=fila[2]) for fila in filas}


def resolver_botella_por_fusion_sync(session: Session, fusion_n_id: int) -> Optional[BotellaDeFusion]:
    """Resuelve la `CromoBotella` dueña de una fusión (empalme) a partir de su `n_id`.

    Ver docstring del módulo para la cascada de prioridades, el criterio de referencia colgada y el
    criterio de empate/ambigüedad.

    Args:
        session:     Sesión SQLAlchemy activa (síncrona, `sqlalchemy.orm.Session`).
        fusion_n_id: `n_id` de la fusión (`app.cromo_fusiones`), típicamente extraído de un mensaje
            de Slack con el ID de empalme.

    Returns:
        `BotellaDeFusion` cuando se resuelve una única Botella dueña sin ambigüedad, o `None` si la
        fusión no existe, si ningún pelo resuelve un cable, si ningún extremo resuelto existe como
        Botella, o si hay un empate entre 2+ candidatas.
    """
    fila_fusion = session.execute(_SQL_FUSION_POR_N_ID, {"fusion_n_id": fusion_n_id}).first()
    if fila_fusion is None:
        return None

    botella_n_id, pelo_a_n_id, pelo_b_n_id = fila_fusion

    # ── Prioridad 1: botella_n_id directo (casi nunca poblado en la práctica, ver docstring) ────
    if botella_n_id is not None:
        directa = _fetch_botellas(session, [botella_n_id]).get(botella_n_id)
        if directa is not None:
            return directa
        # Puntero obsoleto (n_id sin fila propia en cromo_botellas) — cae a Prioridad 2 igual que
        # si botella_n_id nunca hubiera estado poblado.

    # ── Prioridad 2: extremo compartido entre los cables de ambos pelos ──────────────────────────
    pelo_ids = [p for p in (pelo_a_n_id, pelo_b_n_id) if p is not None]
    if not pelo_ids:
        return None

    filas_extremos = session.execute(_SQL_EXTREMOS_DE_PELOS, {"pelo_ids": pelo_ids}).all()
    extremos_por_pelo = {fila[0]: (fila[1], fila[2]) for fila in filas_extremos}

    extremos_a = extremos_por_pelo.get(pelo_a_n_id) if pelo_a_n_id is not None else None
    extremos_b = extremos_por_pelo.get(pelo_b_n_id) if pelo_b_n_id is not None else None

    if extremos_a is not None and extremos_b is not None:
        # Caso normal: ambos pelos resolvieron cable con fila propia — el extremo COMPARTIDO entre
        # los dos es la Botella donde ocurre la fusión.
        candidatos = {n for n in extremos_a if n is not None} & {n for n in extremos_b if n is not None}
    elif extremos_a is not None or extremos_b is not None:
        # Referencia colgada: sólo un pelo resolvió cable+fila — se consideran los 2 extremos de
        # ese único cable, filtrados más abajo a los que realmente existen como Botella.
        unico = extremos_a if extremos_a is not None else extremos_b
        candidatos = {n for n in unico if n is not None}
    else:
        # Ningún pelo resolvió cable — no hay nada de qué partir.
        return None

    if not candidatos:
        return None

    candidatos_validos = list(_fetch_botellas(session, list(candidatos)).values())

    if len(candidatos_validos) == 1:
        return candidatos_validos[0]
    # 0 candidatas válidas (ninguna existe como Botella) o 2+ (empate) — no se elige arbitrariamente.
    return None


__all__ = [
    "BotellaDeFusion",
    "resolver_botella_por_fusion_sync",
]
