# Nombre de archivo: botella_creacion_service.py
# Ubicación de archivo: core/services/cromo/botella_creacion_service.py
# Descripción: Alta/actualización de UNA Botella Cromo puntual por n_id, consultando Cromo en
# vivo (sólo lectura) cuando todavía no existe localmente — cierra para Botellas el mismo gap
# "ID dual" (hist[]/next_id) ya resuelto para Cables en repoblacion_service.py (2026-08-21)

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import id_dual_resolver
from core.services.cromo import ingesta
from core.services.cromo import parser as cromo_parser
from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.verificador import ObjetoNoEncontrado
from db.models.cromo import CromoBotella

logger = logging.getLogger(__name__)


class IdentidadYaResueltaError(RuntimeError):
    """La cadena hist[]/next_id de `n_id_solicitado` termina resolviendo a `n_id_resuelto`, que ya
    tiene fila local propia — crear una fila nueva bajo `n_id_solicitado` duplicaría la Botella."""

    def __init__(self, n_id_solicitado: int, n_id_resuelto: int) -> None:
        super().__init__(
            f"n_id={n_id_solicitado} resuelve a n_id={n_id_resuelto}, que ya existe localmente. "
            f"Usá n_id={n_id_resuelto} en su lugar."
        )
        self.n_id_solicitado = n_id_solicitado
        self.n_id_resuelto = n_id_resuelto


@dataclass(slots=True)
class ResultadoCrearBotellaVivo:
    n_id: int
    accion: str  # "CREADA" | "ACTUALIZADA"
    ids_cadena: list[int]
    nombre: Optional[str]
    corrida_id: Optional[int]


async def crear_o_actualizar_botella_desde_vivo(
    cliente: CromoClient, sesion: AsyncSession, *, n_id: int, usuario: str
) -> ResultadoCrearBotellaVivo:
    """Crea (o actualiza) en `app.cromo_botellas` la fila de UNA Botella puntual, consultando Cromo
    en vivo (`CromoClient` de sólo lectura) — pensado para el caso "ID dual" del Verificador Cromo:
    el `n_id` que el admin está mirando (404 local) es real en Cromo, pero la cadena `hist[]`/
    `next_id` puede resolver a otra versión vigente con los datos completos.

    La fila local queda ANCLADA a `n_id` (el solicitado, el que el admin ya está mirando), nunca al
    `id`/`n_id` que reporte el objeto vigente al final de la cadena — mismo criterio de estabilidad
    que `repoblacion_service.detectar_cables_faltantes` usa para extremos de cable.

    Usa `ingesta.upsert_forzado` (no `upsert_versionado`): el objeto viene de un fetch directo con
    topología, no de una vista parcial embebida, así que no aplica el gate de `vmax`.

    Levanta:
    - `ObjetoNoEncontrado` si `n_id` no existe en Cromo (404).
    - `IdentidadYaResueltaError` si la cadena resuelve a un n_id que ya tiene fila local propia.
    - `core.services.cromo.parser.ClaseExcluidaError` si el objeto resuelto es de una clase
      explícitamente excluida (se propaga sin capturar — la captura vive en el endpoint).
    - `CromoClientError` (status != 404) tal cual, sin envolver.
    """
    try:
        obj_inicial = await id_dual_resolver.fetch_objeto(cliente, n_id)
    except CromoClientError as exc:
        if exc.status_code == 404:
            raise ObjetoNoEncontrado(f"No existe un elemento con n_id={n_id} en Cromo.") from exc
        raise

    obj_vigente, ids_cadena = await id_dual_resolver.resolver_cadena_objetos(
        cliente, n_id, obj_inicial, esta_vigente=lambda o: bool(o.get("tp"))
    )

    botella = cromo_parser.parse_botella(obj_vigente)

    # Salvaguarda de identidad: no crear una fila duplicada cuando la cadena hist[] del n_id
    # solicitado termina resolviendo a un n_id que YA tiene fila local propia.
    n_id_reportado = obj_vigente.get("n_id") or obj_vigente.get("id")
    if n_id_reportado is not None and n_id_reportado != n_id:
        ya_existe = await sesion.get(CromoBotella, n_id_reportado)
        if ya_existe is not None:
            raise IdentidadYaResueltaError(n_id, n_id_reportado)

    # Anclar la identidad LOCAL al n_id solicitado (el que dispara el 404 en el Verificador), nunca
    # al que reporte obj_vigente al final de la cadena.
    botella.n_id = n_id

    corrida = await ingesta.iniciar_corrida(
        sesion,
        usuario=usuario,
        psize=0,
        max_paginas=0,
        clases=(),
        params_extra={"tipo": "MANUAL_CREAR_BOTELLA_VIVO", "n_id": n_id},
    )

    accion = await ingesta.upsert_forzado(sesion, CromoBotella, botella, ingesta.BOTELLA_CAMPOS)
    fila = await sesion.get(CromoBotella, n_id)
    # Mismo criterio de protección de nombre que ingesta._procesar_botella_completa: el caller del
    # endpoint va a pisar este nombre de inmediato con el valor corregido de todas formas — esto es
    # sólo para que la fila no quede sin nombre si el endpoint fallara justo después.
    if accion == "CREADA" or not fila.nombre_editado_manual:
        fila.nombre = botella.nombre

    await ingesta.registrar_evento(
        sesion, corrida.id, n_id, botella.clase, accion, f"ids_cadena={sorted(ids_cadena)}"
    )

    corrida.estado = "OK"
    corrida.finalizada_at = datetime.now(timezone.utc)
    ingesta.sincronizar_contadores(
        corrida,
        ingesta.ContadoresCorrida(
            leidas=1, creadas=int(accion == "CREADA"), actualizadas=int(accion == "ACTUALIZADA")
        ),
    )
    await sesion.commit()

    logger.info(
        "action=cromo_crear_botella_vivo evento=finalizado n_id=%s accion=%s usuario=%s corrida_id=%s ids_cadena=%s",
        n_id,
        accion,
        usuario,
        corrida.id,
        sorted(ids_cadena),
    )

    return ResultadoCrearBotellaVivo(
        n_id=n_id, accion=accion, ids_cadena=sorted(ids_cadena), nombre=fila.nombre, corrida_id=corrida.id
    )


__all__ = ["IdentidadYaResueltaError", "ResultadoCrearBotellaVivo", "crear_o_actualizar_botella_desde_vivo"]
