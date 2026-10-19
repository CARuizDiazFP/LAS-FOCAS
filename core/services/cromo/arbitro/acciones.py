# Nombre de archivo: acciones.py
# Ubicación de archivo: core/services/cromo/arbitro/acciones.py
# Descripción: Acciones aplicables y reversibles del árbitro de Cromo (asociar ODF, fusionar gemelo)

"""Las únicas funciones del árbitro que mutan datos reales. Ninguna hace commit: la transacción la
cierra el llamador (worker o endpoint), así que un error posterior revierte también la acción.

`aplicar` revalida el estado actual antes de mutar (la propuesta pudo quedar vieja) y lanza
`AccionNoAplicable` con un motivo corto si ya no corresponde; `revertir` deshace exactamente lo que
`aplicar` cambió, usando el dict de reversión que `aplicar` devolvió.

Qué cambia `consolidar_grupo_botellas` para un origen vacío (sin cables ni fusiones, sin legados y
sin nombre nuevo), y por eso qué restaura `revertir`:

- crea el alias `fusionar` origen→destino con `creado_por = USUARIO_ARBITRO` (si el origen ya tenía
  alias lo pisaría; por eso `aplicar` lo rechaza antes);
- pone `vigente = false` en la botella origen;
- repunta al destino los alias cuyo destino era el origen (alias dependientes). Sus ids se guardan
  en la reversión (`alias_dependientes`, sólo si hay) para devolverlos al origen.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.arbitro.senales import USUARIO_ARBITRO
from core.services.cromo.consolidacion_service import ACCION_FUSIONAR, consolidar_grupo_botellas
from core.services.cromo.servicio_odf_override_service import crear_override
from core.services.cromo.verificador import ObjetoNoEncontrado
from db.models.cromo import CromoPropuesta

__all__ = ["AccionNoAplicable", "aplicar", "revertir"]

logger = logging.getLogger(__name__)


class AccionNoAplicable(Exception):
    """La propuesta ya no se puede aplicar (o revertir) tal como está; el mensaje es el motivo
    corto (`override_manual`, `gemelo_cambio`, `solo_informativa`, ...). La propuesta no cambia de
    estado: lo decide el llamador."""


# "Posterior" = creado después de la propuesta. Se compara contra `creada_en` leída de la base y no
# contra el atributo ORM, que tras un flush puede estar expirado (y en async no se recarga solo).
_SQL_OVERRIDE_MANUAL_POSTERIOR = text(
    """
    SELECT 1
    FROM app.cromo_servicio_odf_override o
    JOIN app.cromo_propuesta p ON p.id = :propuesta_id
    WHERE o.servicio_id = :servicio_id
      AND o.origen = 'MANUAL'
      AND o.creado_en > p.creada_en
    LIMIT 1
    """
)

_SQL_BORRAR_OVERRIDE_AUTO = text(
    "DELETE FROM app.cromo_servicio_odf_override WHERE id = :id AND origen = 'AUTO'"
)

_SQL_ESTADO_ORIGEN = text(
    """
    SELECT
        b.vigente,
        EXISTS (
            SELECT 1 FROM app.cromo_cables c
            WHERE c.extremo_a_n_id = b.n_id OR c.extremo_b_n_id = b.n_id
        ) AS tiene_cables,
        EXISTS (SELECT 1 FROM app.cromo_fusiones f WHERE f.botella_n_id = b.n_id) AS tiene_fusiones,
        EXISTS (SELECT 1 FROM app.cromo_botella_alias a WHERE a.id_cromo_origen = b.n_id) AS aliasada
    FROM app.cromo_botellas b
    WHERE b.n_id = :n_id
    """
)

_SQL_ALIAS_DEPENDIENTES = text(
    "SELECT id FROM app.cromo_botella_alias WHERE id_cromo_destino = :n_id ORDER BY id"
)

_SQL_BORRAR_ALIAS_ARBITRO = text(
    """
    DELETE FROM app.cromo_botella_alias
    WHERE id_cromo_origen = :origen AND accion = :accion AND creado_por = :usuario
    RETURNING id_cromo_destino
    """
)

_SQL_RESTITUIR_VIGENTE = text("UPDATE app.cromo_botellas SET vigente = true WHERE n_id = :n_id")

# Sólo los que siguen apuntando al destino de la fusión: si alguien los repuntó después, no se tocan.
_SQL_RESTITUIR_DEPENDIENTES = text(
    """
    UPDATE app.cromo_botella_alias SET id_cromo_destino = :origen
    WHERE id = ANY(:ids ::int[]) AND id_cromo_destino = :destino
    """
)


async def aplicar(sesion: AsyncSession, propuesta: CromoPropuesta) -> dict:
    """Aplica la acción de la propuesta y devuelve el dict de reversión. No hace commit."""
    if propuesta.accion == "ASOCIAR_ODF":
        reversion = await _aplicar_asociar_odf(sesion, propuesta)
    elif propuesta.accion == "FUSIONAR_GEMELO":
        reversion = await _aplicar_fusionar_gemelo(sesion, propuesta)
    elif propuesta.accion == "INFORMAR":
        raise AccionNoAplicable("solo_informativa")
    else:
        raise AccionNoAplicable("accion_desconocida")
    logger.info(
        "action=arbitro_cromo evento=accion_aplicada propuesta_id=%s accion=%s objeto_id=%s",
        propuesta.id,
        propuesta.accion,
        propuesta.objeto_id,
    )
    return reversion


async def revertir(sesion: AsyncSession, propuesta: CromoPropuesta) -> None:
    """Deshace lo que `aplicar` hizo, según `propuesta.reversion`. No hace commit."""
    if propuesta.accion == "INFORMAR":
        raise AccionNoAplicable("solo_informativa")
    if propuesta.accion not in ("ASOCIAR_ODF", "FUSIONAR_GEMELO"):
        raise AccionNoAplicable("accion_desconocida")
    reversion = propuesta.reversion
    if not reversion:
        raise AccionNoAplicable("sin_reversion")

    if propuesta.accion == "ASOCIAR_ODF":
        # `origen = 'AUTO'` protege una fila MANUAL aunque la reversión trajera su id.
        await sesion.execute(_SQL_BORRAR_OVERRIDE_AUTO, {"id": reversion["override_id"]})
    else:
        await _revertir_fusionar_gemelo(sesion, reversion)

    logger.info(
        "action=arbitro_cromo evento=accion_revertida propuesta_id=%s accion=%s objeto_id=%s",
        propuesta.id,
        propuesta.accion,
        propuesta.objeto_id,
    )


async def _aplicar_asociar_odf(sesion: AsyncSession, propuesta: CromoPropuesta) -> dict:
    parametros = propuesta.parametros or {}
    posterior = (
        await sesion.execute(
            _SQL_OVERRIDE_MANUAL_POSTERIOR,
            {"propuesta_id": propuesta.id, "servicio_id": propuesta.objeto_id},
        )
    ).first()
    if posterior is not None:
        raise AccionNoAplicable("override_manual")

    try:
        override = await crear_override(
            sesion,
            servicio_id=propuesta.objeto_id,
            odf_n_id=parametros["odf_n_id"],
            pelo_n_id=parametros.get("pelo_n_id"),
            categoria_causa="EVIDENCIA_CAMINO",
            usuario=USUARIO_ARBITRO,
            notas=f"Árbitro propuesta {propuesta.id}",
            origen="AUTO",
            propuesta_id=propuesta.id,
            confirmar=False,
        )
    except ObjetoNoEncontrado as exc:
        # La ODF dejó de existir en el inventario entre la propuesta y la aplicación.
        raise AccionNoAplicable("odf_inexistente") from exc
    return {"override_id": override.id}


async def _aplicar_fusionar_gemelo(sesion: AsyncSession, propuesta: CromoPropuesta) -> dict:
    parametros = propuesta.parametros or {}
    origen = int(parametros["origen"])
    destino = int(parametros["destino"])

    estado_origen = (await sesion.execute(_SQL_ESTADO_ORIGEN, {"n_id": origen})).first()
    estado_destino = (await sesion.execute(_SQL_ESTADO_ORIGEN, {"n_id": destino})).first()
    origen_valido = (
        estado_origen is not None
        and estado_origen.vigente
        and not estado_origen.tiene_cables
        and not estado_origen.tiene_fusiones
        # Consolidar pisaría su alias previo y `revertir` lo borraría: no sería reversible.
        and not estado_origen.aliasada
    )
    destino_valido = (
        estado_destino is not None
        and estado_destino.vigente
        and estado_destino.tiene_cables
        # Un destino ya fusionado hacia otra botella no puede ser el golden record.
        and not estado_destino.aliasada
    )
    if origen == destino or not origen_valido or not destino_valido:
        raise AccionNoAplicable("gemelo_cambio")

    dependientes = list((await sesion.execute(_SQL_ALIAS_DEPENDIENTES, {"n_id": origen})).scalars())

    await sesion.run_sync(
        lambda s: consolidar_grupo_botellas(
            s,
            ids_origen_cromo=[origen],
            id_destino_cromo=destino,
            usuario=USUARIO_ARBITRO,
            motivo=f"arbitro propuesta {propuesta.id}",
        )
    )

    reversion: dict = {"alias_origen": origen}
    if dependientes:
        reversion["alias_dependientes"] = dependientes
    return reversion


async def _revertir_fusionar_gemelo(sesion: AsyncSession, reversion: dict) -> None:
    origen = int(reversion["alias_origen"])
    borrado = (
        await sesion.execute(
            _SQL_BORRAR_ALIAS_ARBITRO,
            {"origen": origen, "accion": ACCION_FUSIONAR, "usuario": USUARIO_ARBITRO},
        )
    ).first()
    if borrado is None:
        # El alias ya no es el que creó el árbitro (un operador lo cambió o lo borró): restituir
        # `vigente` sin él dejaría la botella a medio revertir.
        raise AccionNoAplicable("alias_cambio")

    await sesion.execute(_SQL_RESTITUIR_VIGENTE, {"n_id": origen})
    dependientes = reversion.get("alias_dependientes") or []
    if dependientes:
        await sesion.execute(
            _SQL_RESTITUIR_DEPENDIENTES,
            {"ids": dependientes, "origen": origen, "destino": borrado.id_cromo_destino},
        )
