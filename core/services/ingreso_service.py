# Nombre de archivo: ingreso_service.py
# Ubicación de archivo: core/services/ingreso_service.py
# Descripción: Persistencia del movimiento Ingreso/Egreso/Intento bloqueado de un técnico a una Cámara

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models.cromo import CromoBotella
from db.models.infra import Camara, Ingreso, IngresoTipo


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
    tecnico_nombre: str | None,
) -> Ingreso:
    """Persiste un movimiento de Ingreso o Egreso REAL de un técnico a `camara` (Cámara o Botella ya
    resuelta) y comita la transacción antes de retornar. `tecnico_nombre` ya debe venir resuelto por
    el caller (ver `modules/slack_baneo_notifier/slack_user_resolver.py::resolver_nombre_tecnico`) —
    este servicio no conoce Slack, sólo persiste.

    - "Ingreso": SIEMPRE crea una fila nueva (`tipo=INGRESO`), nunca reabre ni reutiliza una fila
      existente.
    - "Egreso": busca el `Ingreso` ABIERTO (`tipo=INGRESO`, `fecha_fin IS NULL`) más reciente cuyo
      `tecnico_id`, `camara_id` y `cromo_botella_id` coincidan EXACTAMENTE (NULL-safe: `None` exige
      `IS NULL` del lado de la fila existente, nunca se trata como comodín) y lo cierra. El filtro
      `tipo=INGRESO` es deliberado: sin él, un `Intento bloqueado` (mismo `fecha_fin IS NULL`, ver
      `registrar_intento_bloqueado` más abajo) sería candidato a "cerrarse" como si fuera un ingreso
      real. Si no encuentra ninguna fila así, crea una nueva con `fecha_inicio=None` (deliberado: no
      hay forma de saber cuándo entró, y setear `fecha_inicio=fecha_fin` registraría una duración
      falsa de 0 segundos en cualquier reporte futuro, `tipo=EGRESO`) — es preferible una fila
      huérfana de más que cerrar el ingreso de otro técnico.

    Para un intento BLOQUEADO por baneo, usar `registrar_intento_bloqueado` — nunca este servicio con
    `tipo_movimiento="Ingreso"`.
    """
    ahora = datetime.now(timezone.utc)
    cromo_botella_id = botella.n_id if botella is not None else None

    if tipo_movimiento == "Ingreso":
        ingreso = Ingreso(
            camara_id=camara.id,
            cromo_botella_id=cromo_botella_id,
            tecnico_id=tecnico_nombre,
            tipo=IngresoTipo.INGRESO,
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
            _null_safe(Ingreso.tecnico_id, tecnico_nombre),
            Ingreso.camara_id == camara.id,
            _null_safe(Ingreso.cromo_botella_id, cromo_botella_id),
            Ingreso.tipo == IngresoTipo.INGRESO,
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
        tecnico_id=tecnico_nombre,
        tipo=IngresoTipo.EGRESO,
        fecha_inicio=None,
        fecha_fin=ahora,
    )
    session.add(ingreso)
    session.commit()
    return ingreso


def registrar_intento_bloqueado(
    session: Session,
    *,
    camara: Camara,
    botella: CromoBotella | None,
    tecnico_nombre: str | None,
) -> Ingreso:
    """Persiste un intento de Ingreso BLOQUEADO por baneo (de la Cámara o de una Botella del mismo
    grupo — ver `core/services/camara_estado_service.py::get_camara_estado_contexto`).

    Nunca representa un ingreso real: `fecha_fin` queda en `None` (no hay egreso posible de un
    ingreso que nunca ocurrió) pero `tipo=INTENTO_BLOQUEADO` lo distingue de un `Ingreso` real "en
    curso" en toda consulta que filtre por `tipo` — ver el filtro agregado en
    `get_camara_estado_contexto` (`tiene_ingreso_activo`) y en la búsqueda de Egreso de
    `registrar_movimiento_ingreso` (arriba), ambos ahora exigen `tipo == INGRESO` explícitamente.

    El caller (`IngresoListener._registrar_movimiento_si_corresponde`) sólo invoca esto para
    movimientos de tipo "Ingreso" — un "Egreso" nunca se bloquea (salir de una cámara que pasó a
    estar baneada durante la visita sigue permitido, no hay razón operativa para impedirlo)."""
    ahora = datetime.now(timezone.utc)
    intento = Ingreso(
        camara_id=camara.id,
        cromo_botella_id=botella.n_id if botella is not None else None,
        tecnico_id=tecnico_nombre,
        tipo=IngresoTipo.INTENTO_BLOQUEADO,
        fecha_inicio=ahora,
        fecha_fin=None,
    )
    session.add(intento)
    session.commit()
    return intento


__all__ = ["registrar_intento_bloqueado", "registrar_movimiento_ingreso"]
