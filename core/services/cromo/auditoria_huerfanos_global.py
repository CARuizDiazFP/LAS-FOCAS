# Nombre de archivo: auditoria_huerfanos_global.py
# Ubicación de archivo: core/services/cromo/auditoria_huerfanos_global.py
# Descripción: Auditoría global de huérfanos — corrida sintética del cromo_worker que resuelve los
# caminos de los Servicios con más pelos y registra sus residuales, un evento por Servicio

"""Auditoría de huérfanos de muchos Servicios en una sola corrida.

Corre en `cromo_worker` (tiene las credenciales de Cromo), disparada por un admin desde el Viewer
de huérfanos. Se registra como corrida sintética en `cromo_ingesta_corridas` (`params.tipo =
AUDITORIA_HUERFANOS`), con el mismo patrón que `normalizar_inconsistencias`, así que el progreso
viaja por el SSE de corridas que ya existe (`/api/admin/ingesta/cromo/corridas/{id}/stream`):
un evento `PAGINA` por Servicio con `leidas`/`total`.

Por cada Servicio llama a `trackings_del_servicio`, que ya audita los residuales al final: la
auditoría global no tiene lógica de clasificación propia. Va primero por los Servicios Activos con
más pelos, hasta `CROMO_AUDITORIA_MAX_SERVICIOS` (default 50). Cada Servicio cuesta hasta
`CROMO_TRACKING_MAX_LLAMADAS` llamadas a Cromo de 4,6-14 s en frío: 50 Servicios pueden ser horas.
Se puede cancelar desde el histórico de corridas (chequeo cooperativo entre Servicios).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import ingesta
from core.services.cromo.client import CromoClient, CromoClientError
from db.models.cromo import CromoIngestaCorrida

logger = logging.getLogger(__name__)

TIPO_CORRIDA_AUDITORIA = "AUDITORIA_HUERFANOS"
MAX_SERVICIOS_DEFAULT = 50
# Cromo caído no es un error por Servicio: tras estos fallos de red seguidos se corta la corrida.
_MAX_FALLOS_CROMO_SEGUIDOS = 3


def max_servicios_configurado() -> int:
    """`CROMO_AUDITORIA_MAX_SERVICIOS` (default 50). Un valor inválido o <= 0 cae al default."""
    crudo = os.getenv("CROMO_AUDITORIA_MAX_SERVICIOS")
    if not crudo:
        return MAX_SERVICIOS_DEFAULT
    try:
        valor = int(crudo)
    except ValueError:
        valor = 0
    if valor <= 0:
        logger.warning(
            "action=cromo_auditoria_global evento=config_invalida CROMO_AUDITORIA_MAX_SERVICIOS=%r",
            crudo,
        )
        return MAX_SERVICIOS_DEFAULT
    return valor


# Mismo predicado de identidad que `IDENTIDADES_DEL_SERVICIO_SQL`, pero partido en arms de igualdad
# para que el planner haga hash joins: con el OR sobre todos los Servicios la query no terminó en
# 2 minutos sobre la DB de dev; así tarda ~2 s (medido 2026-10-16).
_SQL_SERVICIOS_POR_PELOS = text(
    """
    WITH activos AS (
        SELECT id, servicio_id, numero_primer_servicio, alias_ids
        FROM app.servicios WHERE estado_servicio ILIKE 'activo'
    ), identidades AS (
        SELECT id, servicio_id AS numero FROM activos
        UNION SELECT id, numero_primer_servicio FROM activos WHERE numero_primer_servicio IS NOT NULL
        UNION SELECT id, unnest(alias_ids) FROM activos
    ), pares AS (
        SELECT i.id, m.pelo_n_id
        FROM identidades i JOIN app.v_cromo_servicio_match_vigente m ON m.servicio_numero = i.numero
        UNION
        SELECT a.id, m.pelo_n_id
        FROM activos a JOIN app.v_cromo_servicio_match_vigente m ON m.servicio_id = a.id
    )
    SELECT pr.id, COUNT(*) AS pelos
    FROM pares pr
    JOIN app.cromo_pelos p ON p.n_id = pr.pelo_n_id AND p.vigente = true
    WHERE NOT EXISTS (
        SELECT 1 FROM app.cromo_servicio_pelo_excluido x
        WHERE x.servicio_id = pr.id AND x.pelo_n_id = pr.pelo_n_id
    )
    GROUP BY pr.id
    ORDER BY pelos DESC, pr.id
    LIMIT :limite
    """
)


async def servicios_por_pelos(sesion: AsyncSession, limite: int) -> list[tuple[int, int]]:
    """`[(servicio_id, pelos)]` de los Servicios Activos con más pelos, de mayor a menor."""
    filas = (await sesion.execute(_SQL_SERVICIOS_POR_PELOS, {"limite": limite})).all()
    return [(int(sid), int(pelos)) for sid, pelos in filas]


async def iniciar_corrida_auditoria(
    sesion: AsyncSession, *, usuario: str, max_servicios: int
) -> CromoIngestaCorrida:
    """Crea la corrida sintética EN_CURSO (la ejecuta el worker con `auditar_global`)."""
    return await ingesta.iniciar_corrida(
        sesion,
        usuario=usuario,
        psize=0,
        max_paginas=0,
        clases=(),
        params_extra={"tipo": TIPO_CORRIDA_AUDITORIA, "max_servicios": max_servicios},
    )


async def auditoria_en_curso(sesion: AsyncSession) -> Optional[int]:
    """Id de una auditoría global EN_CURSO, si hay. Dos a la vez se pisarían en Cromo."""
    fila = (
        await sesion.execute(
            text(
                "SELECT id FROM app.cromo_ingesta_corridas "
                "WHERE estado = 'EN_CURSO' AND params ->> 'tipo' = :tipo "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"tipo": TIPO_CORRIDA_AUDITORIA},
        )
    ).first()
    return int(fila[0]) if fila else None


# Clave del advisory lock que serializa "¿hay otra en curso? → crear" entre requests concurrentes.
_LOCK_AUDITORIA_GLOBAL = 0x41554449_4855  # "AUDI" "HU"


async def iniciar_si_no_hay_otra(
    sesion: AsyncSession, *, usuario: str, max_servicios: int
) -> tuple[Optional[CromoIngestaCorrida], Optional[int]]:
    """`(corrida nueva, None)` o `(None, id de la que ya está EN_CURSO)`.

    El chequeo y el alta corren bajo `pg_advisory_xact_lock`: dos POST simultáneos no pueden ver
    "ninguna en curso" a la vez. El lock se suelta con el commit de `iniciar_corrida` (o el
    rollback si ya había una).
    """
    await sesion.execute(
        text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": _LOCK_AUDITORIA_GLOBAL}
    )
    en_curso = await auditoria_en_curso(sesion)
    if en_curso is not None:
        await sesion.rollback()
        return None, en_curso
    corrida = await iniciar_corrida_auditoria(sesion, usuario=usuario, max_servicios=max_servicios)
    return corrida, None


async def ultima_auditoria(sesion: AsyncSession) -> Optional[CromoIngestaCorrida]:
    fila = (
        await sesion.execute(
            text(
                "SELECT id FROM app.cromo_ingesta_corridas WHERE params ->> 'tipo' = :tipo "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"tipo": TIPO_CORRIDA_AUDITORIA},
        )
    ).first()
    return await sesion.get(CromoIngestaCorrida, int(fila[0])) if fila else None


async def auditar_global(
    cliente: CromoClient,
    sesion: AsyncSession,
    corrida_id: int,
    *,
    max_servicios: Optional[int] = None,
) -> str:
    """Ejecuta la corrida. Nunca levanta: la cierra OK, OK_CON_ERRORES, CANCELADA o FALLIDA."""
    from core.services.cromo.tracking_service import trackings_del_servicio

    corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
    if corrida is None:
        raise ValueError(f"No existe la corrida {corrida_id}")
    tope = max_servicios or max_servicios_configurado()
    errores = 0
    omitidos = 0
    procesados = 0
    pendientes = 0
    estado_final = "OK"
    try:
        servicios = await servicios_por_pelos(sesion, tope)
        corrida.total_objetivo = len(servicios)
        await ingesta.registrar_evento(
            sesion,
            corrida_id,
            None,
            None,
            "INICIO",
            json.dumps(
                {
                    "corrida_id": corrida_id,
                    "tipo": TIPO_CORRIDA_AUDITORIA,
                    "total_objetivo": len(servicios),
                    "max_servicios": tope,
                }
            ),
        )
        await sesion.commit()

        fallos_cromo_seguidos = 0
        for numero, (servicio_id, pelos) in enumerate(servicios, start=1):
            if await ingesta._fue_cancelada_externamente(sesion, corrida_id):
                estado_final = "CANCELADA"
                break
            detalle: dict = {
                "fase": TIPO_CORRIDA_AUDITORIA,
                "pagina": numero,
                "servicio_id": servicio_id,
                "pelos": pelos,
            }
            try:
                resultado = await trackings_del_servicio(
                    cliente, sesion, servicio_id, corrida_id=corrida_id, fuente_evidencia="AUDITORIA_GLOBAL"
                )
                fallos_cromo_seguidos = 0
                auditoria = resultado.auditoria
                omitida = (
                    getattr(resultado, "auditoria_omitida", None) is not None
                    or not resultado.completo
                )
                detalle.update(
                    auditoria="OMITIDA_INCOMPLETO" if omitida else (
                        "OK" if auditoria is not None else "ERROR"
                    ),
                    tramos=len(resultado.tramos),
                    residuales=len(resultado.residuales),
                    completo=resultado.completo,
                    nuevos=auditoria.nuevos if auditoria else None,
                    actualizados=auditoria.actualizados if auditoria else None,
                    por_causa=auditoria.por_causa if auditoria else None,
                    auditado=auditoria is not None,
                )
                if auditoria is not None:
                    pendientes += auditoria.nuevos + auditoria.actualizados
                elif not omitida:
                    errores += 1
                else:
                    omitidos += 1
            except Exception as exc:  # noqa: BLE001 - un Servicio no corta la corrida
                errores += 1
                await sesion.rollback()
                if isinstance(exc, CromoClientError):
                    fallos_cromo_seguidos += 1
                logger.error(
                    "action=cromo_auditoria_global evento=error_servicio corrida_id=%s "
                    "servicio_id=%s error=%s",
                    corrida_id,
                    servicio_id,
                    exc,
                )
                await ingesta.registrar_evento(
                    sesion, corrida_id, None, None, "ERROR", f"Servicio {servicio_id}: {exc}"
                )
                detalle["error"] = str(exc)[:300]
            procesados = numero
            detalle.update(
                leidas=procesados, total=len(servicios), errores=errores, omitidos=omitidos
            )
            corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
            # Se reusan los contadores de la corrida: `leidas` = Servicios auditados,
            # `actualizadas` = filas PENDIENTE escritas (nuevas o refrescadas).
            corrida.leidas = procesados
            corrida.actualizadas = pendientes
            corrida.errores = errores
            await ingesta.registrar_evento(
                sesion, corrida_id, None, None, "PAGINA", json.dumps(detalle)
            )
            await sesion.commit()
            if fallos_cromo_seguidos >= _MAX_FALLOS_CROMO_SEGUIDOS:
                estado_final = "FALLIDA"
                break
        else:
            estado_final = "OK" if errores == 0 else "OK_CON_ERRORES"
    except Exception as exc:  # noqa: BLE001 - una falla inesperada cierra la corrida
        await sesion.rollback()
        logger.error(
            "action=cromo_auditoria_global evento=corrida_fallida corrida_id=%s error=%s",
            corrida_id,
            exc,
        )
        await ingesta.registrar_evento(sesion, corrida_id, None, None, "ERROR", str(exc)[:500])
        estado_final = "FALLIDA"

    corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
    corrida.estado = estado_final
    corrida.finalizada_at = datetime.now(timezone.utc)
    corrida.leidas = procesados
    corrida.actualizadas = pendientes
    corrida.errores = errores
    await ingesta.registrar_evento(
        sesion,
        corrida_id,
        None,
        None,
        "RESUMEN",
        json.dumps(
            {
                "estado": estado_final,
                "tipo": TIPO_CORRIDA_AUDITORIA,
                "leidas": procesados,
                "pendientes": pendientes,
                "errores": errores,
                "omitidos_incompletos": omitidos,
            }
        ),
    )
    await sesion.commit()
    logger.info(
        "action=cromo_auditoria_global evento=fin corrida_id=%s estado=%s servicios=%s "
        "pendientes=%s errores=%s",
        corrida_id,
        estado_final,
        procesados,
        pendientes,
        errores,
    )
    return estado_final


__all__ = [
    "MAX_SERVICIOS_DEFAULT",
    "TIPO_CORRIDA_AUDITORIA",
    "auditar_global",
    "auditoria_en_curso",
    "iniciar_corrida_auditoria",
    "iniciar_si_no_hay_otra",
    "max_servicios_configurado",
    "servicios_por_pelos",
    "ultima_auditoria",
]
