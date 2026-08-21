# Nombre de archivo: repoblacion_service.py
# Ubicación de archivo: core/services/cromo/repoblacion_service.py
# Descripción: Detección y repoblación de cables faltantes/desactualizados en una Botella Cromo con historial "ID dual" (hist[]/next_id)

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import alias_service
from core.services.cromo import ingesta
from core.services.cromo import parser as cromo_parser
from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.modelos import Cable, Pelo, Tubo
from core.services.cromo.verificador import ObjetoNoEncontrado
from db.models.cromo import CromoBotella, CromoCable, CromoPelo, CromoTubo

logger = logging.getLogger(__name__)

# Cota defensiva de saltos hist[]/next_id: el caso real observado (B2-FO-CAR, 2026-08-21)
# resuelve en 1-2 requests porque hist[] trae la cadena completa de entrada — este límite sólo
# protege contra una cadena rota, cíclica o anormalmente larga.
MAX_HOPS_HIST = 5


@dataclass(slots=True)
class CableDetectado:
    """Un cable conectado (según Cromo, en vivo) a la botella consultada, ya con extremos
    resueltos (alias local + anclaje de identidad hist/next_id) y comparado contra la fila local.
    `cable`/`tubos`/`pelos` viajan listos para `repoblar_cables` sin volver a pedirle nada a Cromo.
    """

    n_id: int
    nombre: Optional[str]
    extremo_a_n_id: Optional[int]
    extremo_b_n_id: Optional[int]
    estado_local: str  # "OK" | "FALTA" | "DESACTUALIZADO"
    cable: Cable = field(repr=False)
    tubos: list[Tubo] = field(default_factory=list, repr=False)
    pelos: list[Pelo] = field(default_factory=list, repr=False)


@dataclass(slots=True)
class ResultadoDeteccionCables:
    botella_n_id: int
    ids_cadena: list[int]
    cables: list[CableDetectado]

    @property
    def cables_pendientes(self) -> list[CableDetectado]:
        return [c for c in self.cables if c.estado_local != "OK"]


@dataclass(slots=True)
class ItemRepoblado:
    n_id: int
    accion: str  # CREADA | ACTUALIZADA | SIN_CAMBIOS | ERROR
    detalle: Optional[str] = None


@dataclass(slots=True)
class ResultadoRepoblarCables:
    corrida_id: Optional[int]
    botella_n_id: int
    creados: int
    actualizados: int
    sin_cambios: int
    errores: int
    detalle: list[ItemRepoblado]


def _ids_de_hist(obj: dict[str, Any]) -> set[int]:
    return {entrada["id"] for entrada in (obj.get("hist") or []) if isinstance(entrada, dict) and entrada.get("id") is not None}


def _next_id_de(obj: dict[str, Any], id_actual: Optional[int]) -> Optional[int]:
    """Busca, dentro del propio `hist[]` de `obj`, la entrada cuyo `id` es `id_actual` y devuelve
    su `next_id` (0 = no hay más — es la vigente). Sigue la cadena salto a salto por el id propio
    de cada objeto, no "salta directo" a la entrada con `next_id == 0`: así funciona igual si
    `hist[]` trae la cadena completa (confirmado real, caso B2-FO-CAR, 2 saltos) o sólo una
    ventana parcial alrededor del id consultado."""
    for entrada in obj.get("hist") or []:
        if isinstance(entrada, dict) and entrada.get("id") == id_actual:
            return entrada.get("next_id") or None
    return None


async def _fetch_objeto(cliente: CromoClient, n_id: int) -> dict[str, Any]:
    """Desenvuelve el `{"st": ..., "response": {...}}` con el que responde Cromo — confirmado real
    contra `GET /db/objects/{id}?show=TOPOLOGIES&show=REL_ATTRIBUTE` (Paso 0, 2026-08-21)."""
    respuesta = await cliente.get_objeto_con_topologia(n_id)
    return respuesta.get("response", respuesta)


async def _resolver_cadena_objetos(
    cliente: CromoClient, n_id: int, obj_inicial: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Devuelve el objeto con la topología VIGENTE (`tp[]` poblado) + el set de ids de toda la
    cadena `hist` (insumo del anclaje de extremo, ver `_anclar_extremo_a_botella`).

    Confirmado con datos reales: `hist[]` trae la cadena completa sin importar qué id de la cadena
    se consulte, así que 1-2 requests alcanzan casi siempre — el loop acotado por
    `MAX_HOPS_HIST` es puramente defensivo (cadena que sigue en movimiento, respuesta parcial).
    """
    obj = obj_inicial
    id_actual = obj.get("id", n_id)
    ids_cadena = {n_id} | _ids_de_hist(obj)
    visitados = {n_id}
    saltos = 0
    while not (obj.get("tp") or []) and saltos < MAX_HOPS_HIST:
        siguiente_id = _next_id_de(obj, id_actual)
        if siguiente_id is None or siguiente_id in visitados:
            break
        visitados.add(siguiente_id)
        try:
            obj = await _fetch_objeto(cliente, siguiente_id)
        except CromoClientError as exc:
            logger.warning(
                "action=cromo_repoblar_cables evento=hop_no_resuelve botella_n_id=%s siguiente_id=%s error=%s",
                n_id,
                siguiente_id,
                exc,
            )
            break
        id_actual = siguiente_id
        ids_cadena.add(siguiente_id)
        ids_cadena |= _ids_de_hist(obj)
        saltos += 1
    return obj, ids_cadena


def _anclar_extremo_a_botella(cable: Cable, botella_n_id: int, ids_cadena: set[int]) -> None:
    """Confirmado con datos reales (Paso 0, caso B2-FO-CAR): el extremo de un cable conectado a
    una botella con historial reporta el id de VERSIÓN vigente (ej. 9057952 = next_id), no el
    `n_id` ESTABLE de la botella (9057909) que usa la fila local — nunca matchean entre sí. Si un
    extremo está en `ids_cadena` (cualquier id de la cadena hist de ESTA botella) y no es ya el
    `n_id` local, se normaliza a `botella_n_id`."""
    if cable.extremo_a_n_id in ids_cadena and cable.extremo_a_n_id != botella_n_id:
        cable.extremo_a_n_id = botella_n_id
    if cable.extremo_b_n_id in ids_cadena and cable.extremo_b_n_id != botella_n_id:
        cable.extremo_b_n_id = botella_n_id


async def detectar_cables_faltantes(
    cliente: CromoClient, sesion: AsyncSession, botella_n_id: int
) -> ResultadoDeteccionCables:
    """Sólo lectura: no persiste nada. La botella debe existir ya en `app.cromo_botellas` local —
    si no, 404 (`ObjetoNoEncontrado`) antes de pegarle a Cromo."""
    botella_local = await sesion.get(CromoBotella, botella_n_id)
    if botella_local is None:
        raise ObjetoNoEncontrado(f"No existe una Botella con n_id={botella_n_id} en el inventario local.")

    try:
        obj_inicial = await _fetch_objeto(cliente, botella_n_id)
    except CromoClientError as exc:
        if exc.status_code == 404:
            raise ObjetoNoEncontrado(f"No existe un elemento con n_id={botella_n_id} en Cromo.") from exc
        raise

    obj_vigente, ids_cadena = await _resolver_cadena_objetos(cliente, botella_n_id, obj_inicial)

    candidatos_id = [
        item.get("id_to")
        for item in (obj_vigente.get("tp") or [])
        if item.get("class") == ingesta.CLASE_CABLE and item.get("id_to")
    ]

    alias_por_origen = await alias_service.cargar_alias_vigentes(sesion)
    cables: list[CableDetectado] = []
    for id_to in candidatos_id:
        try:
            # Fetch DIRECTO del cable por su propio id — el ítem embebido en botella.tp[] es una
            # vista PARCIAL (sin vmax/id de versión, con un solo extremo, at[] recortado; ver Paso
            # 0) y no alcanza para upsertear un CromoCable completo.
            cable_obj = await _fetch_objeto(cliente, id_to)
        except CromoClientError as exc:
            logger.warning(
                "action=cromo_repoblar_cables evento=cable_no_resuelve botella_n_id=%s cable_id=%s error=%s",
                botella_n_id,
                id_to,
                exc,
            )
            continue

        cable = cromo_parser.parse_cable(cable_obj)
        cable.extremo_a_n_id = alias_service.resolver_referencia(cable.extremo_a_n_id, alias_por_origen)
        cable.extremo_b_n_id = alias_service.resolver_referencia(cable.extremo_b_n_id, alias_por_origen)
        _anclar_extremo_a_botella(cable, botella_n_id, ids_cadena)
        tubos, pelos, _errores_parseo = cromo_parser.extraer_tubos_y_pelos(cable_obj)

        fila_local = await sesion.get(CromoCable, cable.n_id)
        if fila_local is None:
            estado = "FALTA"
        elif {fila_local.extremo_a_n_id, fila_local.extremo_b_n_id} != {cable.extremo_a_n_id, cable.extremo_b_n_id}:
            estado = "DESACTUALIZADO"
        else:
            estado = "OK"

        cables.append(
            CableDetectado(
                n_id=cable.n_id,
                nombre=cable.nombre,
                extremo_a_n_id=cable.extremo_a_n_id,
                extremo_b_n_id=cable.extremo_b_n_id,
                estado_local=estado,
                cable=cable,
                tubos=tubos,
                pelos=pelos,
            )
        )

    return ResultadoDeteccionCables(botella_n_id=botella_n_id, ids_cadena=sorted(ids_cadena), cables=cables)


async def repoblar_cables(
    cliente: CromoClient, sesion: AsyncSession, *, botella_n_id: int, usuario: str
) -> ResultadoRepoblarCables:
    """Repuebla en la base LOCAL — nunca escribe hacia Cromo (`CromoClient` es de sólo lectura por
    diseño). Nunca toca `CromoBotella`/`CromoFusion` — sólo `CromoCable`/`CromoTubo`/`CromoPelo`,
    para no crear una fila de botella espuria bajo un id intermedio de la cadena hist.

    Si no hay cables pendientes (todos `OK`), no crea corrida (evita ensuciar el histórico admin
    con corridas vacías por clicks repetidos). Si hay, crea una corrida sintética de un solo click
    (`ingesta.iniciar_corrida(..., params_extra=...)`), visible en el mismo histórico que una
    corrida regular, y por cada cable pendiente: `upsert_versionado` si falta local (clasifica
    CREADA normalmente), `upsert_forzado` si ya existe pero desactualizado (bypassa el gate de
    `vmax` — ver docstring de `ingesta.upsert_forzado`, necesario porque el `vmax` de un cable no
    cambia sólo porque el extremo apuntaba a un id de versión vieja de la botella). Tubos/pelos
    vía `upsert_simple`. Mismo savepoint-por-objeto que una corrida regular: un cable roto no
    aborta el resto del lote.
    """
    deteccion = await detectar_cables_faltantes(cliente, sesion, botella_n_id)
    pendientes = deteccion.cables_pendientes
    if not pendientes:
        return ResultadoRepoblarCables(
            corrida_id=None, botella_n_id=botella_n_id, creados=0, actualizados=0, sin_cambios=0, errores=0, detalle=[]
        )

    corrida = await ingesta.iniciar_corrida(
        sesion,
        usuario=usuario,
        psize=0,
        max_paginas=0,
        clases=(),
        params_extra={"tipo": "MANUAL_REPOBLAR_CABLES", "botella_n_id": botella_n_id},
    )

    creados = actualizados = sin_cambios = errores = 0
    detalle: list[ItemRepoblado] = []
    for candidato in pendientes:
        try:
            async with sesion.begin_nested():
                if candidato.estado_local == "FALTA":
                    accion = await ingesta.upsert_versionado(sesion, CromoCable, candidato.cable, ingesta.CABLE_CAMPOS)
                else:
                    accion = await ingesta.upsert_forzado(sesion, CromoCable, candidato.cable, ingesta.CABLE_CAMPOS)
                for tubo in candidato.tubos:
                    await ingesta.upsert_simple(sesion, CromoTubo, tubo, ingesta.TUBO_CAMPOS)
                for pelo in candidato.pelos:
                    await ingesta.upsert_simple(sesion, CromoPelo, pelo, ingesta.PELO_CAMPOS)
                await ingesta.registrar_evento(sesion, corrida.id, candidato.n_id, ingesta.CLASE_CABLE, accion)
        except Exception as exc:  # noqa: BLE001 - tolerancia deliberada: un cable no aborta el lote
            errores += 1
            logger.error(
                "action=cromo_repoblar_cables evento=error_cable botella_n_id=%s cable_n_id=%s error=%s",
                botella_n_id,
                candidato.n_id,
                exc,
            )
            await ingesta.registrar_evento(sesion, corrida.id, candidato.n_id, ingesta.CLASE_CABLE, "ERROR", str(exc))
            detalle.append(ItemRepoblado(n_id=candidato.n_id, accion="ERROR", detalle=str(exc)))
            continue

        detalle.append(ItemRepoblado(n_id=candidato.n_id, accion=accion))
        if accion == "CREADA":
            creados += 1
        elif accion == "ACTUALIZADA":
            actualizados += 1
        elif accion == "SIN_CAMBIOS":
            sin_cambios += 1

    contadores = ingesta.ContadoresCorrida(
        leidas=len(pendientes), creadas=creados, actualizadas=actualizados, sin_cambios=sin_cambios, errores=errores
    )
    corrida.estado = "OK" if errores == 0 else "OK_CON_ERRORES"
    corrida.finalizada_at = datetime.now(timezone.utc)
    ingesta.sincronizar_contadores(corrida, contadores)
    await ingesta.registrar_evento(
        sesion,
        corrida.id,
        None,
        None,
        "RESUMEN",
        json.dumps(
            {
                "botella_n_id": botella_n_id,
                "creadas": creados,
                "actualizadas": actualizados,
                "sin_cambios": sin_cambios,
                "errores": errores,
            }
        ),
    )
    await sesion.commit()

    logger.info(
        "action=cromo_repoblar_cables evento=finalizado corrida_id=%s botella_n_id=%s usuario=%s "
        "creados=%d actualizados=%d sin_cambios=%d errores=%d",
        corrida.id,
        botella_n_id,
        usuario,
        creados,
        actualizados,
        sin_cambios,
        errores,
    )
    return ResultadoRepoblarCables(
        corrida_id=corrida.id,
        botella_n_id=botella_n_id,
        creados=creados,
        actualizados=actualizados,
        sin_cambios=sin_cambios,
        errores=errores,
        detalle=detalle,
    )


__all__ = [
    "CableDetectado",
    "ItemRepoblado",
    "ResultadoDeteccionCables",
    "ResultadoRepoblarCables",
    "detectar_cables_faltantes",
    "repoblar_cables",
]
