# Nombre de archivo: ingreso_service.py
# Ubicación de archivo: core/services/ingreso_service.py
# Descripción: Persistencia del movimiento Ingreso/Egreso de un técnico a una Cámara (Tarea 3 del
# refactor "ingreso a cámara" — hasta esta tarea, el bot de Slack sólo respondía sin guardar nada).

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models.cromo import CromoBotella
from db.models.infra import Camara, Ingreso


def _null_safe(columna, valor):
    """Comparación NULL-safe de una columna contra un valor Python ya conocido (no otra columna).

    En SQL, `columna = NULL` nunca es verdadero — ni siquiera cuando la fila también tiene esa
    columna en NULL — así que un `columna == valor` naive con `valor is None` fallaría en encontrar
    esas filas. Acá alcanza con `columna.is_(None)` para ese caso puntual (comparar contra un literal
    conocido, no NULL-safe entre dos columnas, que requeriría `is_not_distinct_from`)."""
    return columna.is_(None) if valor is None else columna == valor


def registrar_movimiento_ingreso(
    session: Session,
    *,
    camara: Camara,
    botella: CromoBotella | None,
    tipo_movimiento: str,  # "Ingreso" | "Egreso" (ya validado por el caller, no se revalida acá)
    slack_user_id: str | None,
) -> Ingreso:
    """Persiste un movimiento de Ingreso o Egreso de un técnico a `camara` (Cámara o Botella ya
    resuelta) y comita la transacción antes de retornar (mismo patrón que el registro de
    `IngresoSinMatch` en `modules/slack_baneo_notifier/listener.py`) — no deja el commit a cargo de
    un caller externo.

    - "Ingreso": SIEMPRE crea una fila nueva, nunca reabre ni reutiliza una fila existente.
    - "Egreso": busca el `Ingreso` ABIERTO (`fecha_fin IS NULL`) más reciente cuyo `tecnico_id`,
      `camara_id` y `cromo_botella_id` coincidan EXACTAMENTE (NULL-safe: `None` exige `IS NULL` del
      lado de la fila existente, nunca se trata como comodín) y lo cierra. Si no encuentra ninguna
      fila así, crea una nueva con `fecha_inicio=None` (deliberado: no hay forma de saber cuándo
      entró, y setear `fecha_inicio=fecha_fin` registraría una duración falsa de 0 segundos en
      cualquier reporte futuro) — es preferible una fila huérfana de más que cerrar el ingreso de
      otro técnico.
    """
    ahora = datetime.now(timezone.utc)
    cromo_botella_id = botella.n_id if botella is not None else None

    if tipo_movimiento == "Ingreso":
        ingreso = Ingreso(
            camara_id=camara.id,
            cromo_botella_id=cromo_botella_id,
            tecnico_id=slack_user_id,
            fecha_inicio=ahora,
            fecha_fin=None,
        )
        session.add(ingreso)
        session.commit()
        return ingreso

    # tipo_movimiento == "Egreso"
    ingreso_abierto = (
        session.query(Ingreso)
        .filter(
            _null_safe(Ingreso.tecnico_id, slack_user_id),
            Ingreso.camara_id == camara.id,
            _null_safe(Ingreso.cromo_botella_id, cromo_botella_id),
            Ingreso.fecha_fin.is_(None),
        )
        .order_by(Ingreso.fecha_inicio.desc())
        .first()
    )

    if ingreso_abierto is not None:
        ingreso_abierto.fecha_fin = ahora
        session.commit()
        return ingreso_abierto

    ingreso = Ingreso(
        camara_id=camara.id,
        cromo_botella_id=cromo_botella_id,
        tecnico_id=slack_user_id,
        fecha_inicio=None,
        fecha_fin=ahora,
    )
    session.add(ingreso)
    session.commit()
    return ingreso


__all__ = ["registrar_movimiento_ingreso"]
