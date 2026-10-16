# Nombre de archivo: servicio_odf_confirmacion.py
# Ubicación de archivo: core/services/cromo/servicio_odf_confirmacion.py
# Descripción: ODF confirmadas por servicio (app.servicio_odf_confirmada) y cantidad de trackings esperados (app.servicios.trackings_esperados) — insumo del tracking por tramos

"""Lo que un operador declara a mano sobre los trackings de un Servicio:

- Qué ODF son parte de su recorrido (`confirmar`/`desconfirmar`/`listar`), con rol `EXTREMO` o
  `TRANSITO`. Un camino que toca una ODF confirmada es siempre `TRAMO`
  (`tracking_service.clasificar_caminos`).
- Cuántos trackings espera (`declarar_trackings_esperados`).

`trackings_del_servicio` lee ambas cosas con `declaraciones_del_servicio`; sin nada declarado todo
funciona como antes. No reemplaza `servicio_odf_override_service` (escudo de "servicios sin ODF").

Des-confirmar pone `vigente=false` y conserva la fila (historial). La existencia de la ODF se
valida con el mismo criterio ESTRICTO que el override: fila propia en `app.cromo_odfs`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.verificador import ObjetoNoEncontrado

__all__ = [
    "ROLES_VALIDOS",
    "ROL_EXTREMO",
    "ROL_TRANSITO",
    "Declaraciones",
    "confirmar",
    "declarar_trackings_esperados",
    "declaraciones_del_servicio",
    "desconfirmar",
    "listar",
]

ROL_EXTREMO = "EXTREMO"
ROL_TRANSITO = "TRANSITO"
ROLES_VALIDOS = (ROL_EXTREMO, ROL_TRANSITO)

# Los ids de los caminos pueden ser el `n_id` de linaje o el `version_id` de la ODF (ver
# `camino_optico_service._vincular_odfs`): se acepta cualquiera y se guarda siempre el `n_id`. Si un
# mismo valor es `n_id` de una fila y `version_id` de otra, gana el `n_id`.
_SQL_RESOLVER_ODF = text(
    "SELECT n_id FROM app.cromo_odfs WHERE n_id = :id OR version_id = :id "
    "ORDER BY (n_id = :id) DESC LIMIT 1"
)

# `ON CONFLICT` sobre el índice único parcial: re-confirmar una ODF ya vigente es idempotente (sólo
# actualiza el rol).
_SQL_CONFIRMAR = text(
    """
    INSERT INTO app.servicio_odf_confirmada (servicio_id, odf_n_id, rol, confirmado_por)
    VALUES (:servicio_id, :odf_n_id, :rol, :usuario)
    ON CONFLICT (servicio_id, odf_n_id) WHERE vigente
    DO UPDATE SET rol = EXCLUDED.rol
    """
)

_SQL_DESCONFIRMAR = text(
    "UPDATE app.servicio_odf_confirmada SET vigente = false "
    "WHERE servicio_id = :servicio_id AND odf_n_id = :odf_n_id AND vigente"
)

_SQL_LISTAR = text(
    """
    SELECT c.odf_n_id, c.rol, c.confirmado_por, c.confirmado_en,
           o.nombre AS odf_nombre, o.tipo_elemento AS odf_tipo, o.version_id AS odf_version_id
    FROM app.servicio_odf_confirmada c
    LEFT JOIN app.cromo_odfs o ON o.n_id = c.odf_n_id
    WHERE c.servicio_id = :servicio_id AND c.vigente
    ORDER BY c.confirmado_en, c.id
    """
)

_SQL_ESPERADOS = text("SELECT trackings_esperados FROM app.servicios WHERE id = :servicio_id")

_SQL_DECLARAR = text(
    "UPDATE app.servicios SET trackings_esperados = :cantidad WHERE id = :servicio_id"
)


@dataclass(slots=True)
class Declaraciones:
    """ODF confirmadas vigentes y trackings esperados de un Servicio.

    `odf_ids` incluye el `n_id` de linaje Y el `version_id` de cada ODF confirmada: los ids de los
    caminos pueden ser cualquiera de los dos (ver `camino_optico_service._vincular_odfs`).
    """

    odf_ids: frozenset[int] = frozenset()
    confirmadas: list[dict[str, Any]] = field(default_factory=list)
    trackings_esperados: Optional[int] = None


def _fila_a_dict(fila: Any) -> dict[str, Any]:
    return {
        "odf_n_id": int(fila.odf_n_id),
        "rol": fila.rol,
        "odf_nombre": fila.odf_nombre,
        "odf_tipo": fila.odf_tipo,
        "confirmado_por": fila.confirmado_por,
        "confirmado_en": fila.confirmado_en.isoformat() if fila.confirmado_en else None,
    }


async def listar(sesion: AsyncSession, servicio_id: int) -> list[dict[str, Any]]:
    """Las ODF confirmadas VIGENTES del Servicio, con nombre y tipo de la ODF si está ingerida."""
    filas = (await sesion.execute(_SQL_LISTAR, {"servicio_id": servicio_id})).all()
    return [_fila_a_dict(f) for f in filas]


async def confirmar(
    sesion: AsyncSession,
    servicio_id: int,
    odfs: Sequence[tuple[int, str]],
    *,
    usuario: str,
) -> list[dict[str, Any]]:
    """Confirma en lote ODF `(odf_n_id, rol)` del Servicio y devuelve la lista vigente.

    Todo o nada: valida los roles (`ValueError`) y que cada ODF tenga fila propia en
    `app.cromo_odfs` (`ObjetoNoEncontrado`) ANTES de escribir; el id puede ser `n_id` o `version_id`
    y se guarda el `n_id`. Idempotente: una ODF ya vigente sólo actualiza su rol. `servicio_id` inexistente lo rechaza la FK (`IntegrityError`).
    """
    for odf_n_id, rol in odfs:
        if rol not in ROLES_VALIDOS:
            raise ValueError(f"Rol inválido {rol!r}: debe ser uno de {', '.join(ROLES_VALIDOS)}.")
    resueltas: list[tuple[int, str]] = []
    for odf_id, rol in odfs:
        fila = (await sesion.execute(_SQL_RESOLVER_ODF, {"id": odf_id})).first()
        if fila is None:
            raise ObjetoNoEncontrado(f"No existe un ODF con n_id={odf_id} en el inventario ingerido.")
        resueltas.append((int(fila[0]), rol))
    for odf_n_id, rol in resueltas:
        await sesion.execute(
            _SQL_CONFIRMAR,
            {"servicio_id": servicio_id, "odf_n_id": odf_n_id, "rol": rol, "usuario": usuario},
        )
    await sesion.commit()
    return await listar(sesion, servicio_id)


async def desconfirmar(sesion: AsyncSession, servicio_id: int, odf_n_id: int) -> bool:
    """Des-confirma la ODF (`vigente=false`, la fila se conserva). `False` si no estaba vigente."""
    resultado = await sesion.execute(
        _SQL_DESCONFIRMAR, {"servicio_id": servicio_id, "odf_n_id": odf_n_id}
    )
    await sesion.commit()
    return bool(resultado.rowcount)


async def declarar_trackings_esperados(
    sesion: AsyncSession, servicio_id: int, cantidad: Optional[int]
) -> bool:
    """Declara cuántos trackings espera el Servicio; `None` borra la declaración.

    `ValueError` si `cantidad` no es positiva (el CHECK de la columna haría lo mismo, pero con un
    `IntegrityError` opaco). `False` si el Servicio no existe.
    """
    if cantidad is not None and cantidad <= 0:
        raise ValueError("La cantidad de trackings esperados debe ser mayor a 0.")
    resultado = await sesion.execute(
        _SQL_DECLARAR, {"servicio_id": servicio_id, "cantidad": cantidad}
    )
    await sesion.commit()
    return bool(resultado.rowcount)


async def declaraciones_del_servicio(sesion: AsyncSession, servicio_id: int) -> Declaraciones:
    """Lo declarado del Servicio, listo para `trackings_del_servicio`."""
    filas = (await sesion.execute(_SQL_LISTAR, {"servicio_id": servicio_id})).all()
    confirmadas = [_fila_a_dict(f) for f in filas]
    ids: set[int] = set()
    for fila in filas:
        ids.add(int(fila.odf_n_id))
        if fila.odf_version_id is not None:
            ids.add(int(fila.odf_version_id))
    esperados = (await sesion.execute(_SQL_ESPERADOS, {"servicio_id": servicio_id})).scalar_one_or_none()
    return Declaraciones(
        odf_ids=frozenset(ids),
        confirmadas=confirmadas,
        trackings_esperados=int(esperados) if esperados is not None else None,
    )
