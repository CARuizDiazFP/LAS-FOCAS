# Nombre de archivo: ingesta.py
# Ubicación de archivo: core/services/prov/ingesta.py
# Descripción: Mapea el contexto de servicio de PROV a los campos/tablas de Servicio y aplica la consolidación de identidad ya existente

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.servicios_consolidacion_service import (
    consolidar_identidad_servicio,
    es_verificable_por_tipo_y_estado,
    resolver_estado_servicio,
)
from db.models.infra import Servicio, ServicioEquipoUltimaMilla, ServicioHistorialId, ServicioOrigenDatos

logger = logging.getLogger(__name__)

_TRADUCCION_ESTADO_COMERCIAL = {
    "INSTALADO": "Activo",
    "DADO BAJA": "Baja",
}


def _traducir_estado_comercial(estado_comercial: str | None) -> str:
    """Traduce el vocabulario de PROV (`estado_comercial`) al propio (`estado_servicio`).

    Sólo se conocen dos valores reales (ver los payloads verificados en
    docs/superpowers/specs/2026-09-02-servicios-prov-integracion-design.md); un valor nuevo no
    mapeado se pasa tal cual, en vez de perderlo silenciosamente, y se loguea con un warning para
    poder detectarlo en datos reales y ampliar el diccionario (sin el log, "pasarlo tal cual" era
    indetectable salvo mirando la columna en la DB).
    """
    if not estado_comercial:
        return "DESCONOCIDO"
    clave = estado_comercial.strip().upper()
    if clave in _TRADUCCION_ESTADO_COMERCIAL:
        return _TRADUCCION_ESTADO_COMERCIAL[clave]
    logger.warning("action=prov_ingesta evento=estado_comercial_no_mapeado valor=%s", estado_comercial.strip())
    return estado_comercial.strip()


def _es_estado_comercial_vigente(estado_comercial: str | None) -> bool:
    """¿Este `estado_comercial` de PROV describe un servicio todavía vigente?

    Se lee del mismo diccionario de traducción (única fuente de verdad del vocabulario), sin pasar
    por `_traducir_estado_comercial` para no duplicar su warning de valor no mapeado. Un valor
    ausente o desconocido NO se asume vigente: marcar `es_vigente=True` a ciegas era exactamente lo
    que producía la contradicción "chip DADO BAJA junto a la palabra Vigente" en el detalle.
    """
    if not estado_comercial:
        return False
    return _TRADUCCION_ESTADO_COMERCIAL.get(estado_comercial.strip().upper()) == "Activo"


def _a_fecha(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


@dataclass(slots=True)
class EslabonHistorial:
    numero_id: str
    orden: int
    fecha_instalacion: date | None
    fecha_baja: date | None
    estado_comercial: str | None
    motivo_baja: str | None
    es_vigente: bool


@dataclass(slots=True)
class EquipoUltimaMilla:
    extremo: int
    nodo: str | None
    equipo: str | None
    puerto: str | None
    direccion: str | None
    provincia: str | None


@dataclass(slots=True)
class ContextoProvParseado:
    nro_servicio_vigente: str
    nro_servicio_original: str
    tipo_servicio: str | None
    nombre_cliente: str | None
    estado_comercial: str | None
    historial: list[EslabonHistorial]
    equipos: list[EquipoUltimaMilla]


def parsear_contexto_prov(contexto_raw: dict[str, Any]) -> ContextoProvParseado:
    """Parsea el dict de `Resultado:` (ya validado como éxito por `ProvClient`)."""
    nro_servicio_vigente = str(contexto_raw.get("nro_servicio") or "").strip()
    nro_servicio_original = str(contexto_raw.get("nro_servicio_original") or nro_servicio_vigente).strip()

    cadena = contexto_raw.get("cadena_upgrade")
    historial: list[EslabonHistorial]
    if isinstance(cadena, list) and cadena:
        historial = [
            EslabonHistorial(
                numero_id=str(eslabon.get("nro_servicio") or "").strip(),
                orden=indice,
                fecha_instalacion=_a_fecha(eslabon.get("fecha_instalacion")),
                fecha_baja=_a_fecha(eslabon.get("fecha_baja")),
                estado_comercial=eslabon.get("estado_comercial"),
                motivo_baja=eslabon.get("motivo_baja") or None,
                es_vigente=bool(eslabon.get("es_vigente")),
            )
            for indice, eslabon in enumerate(cadena)
            if str(eslabon.get("nro_servicio") or "").strip()
        ]
    else:
        historial = [
            EslabonHistorial(
                numero_id=nro_servicio_original,
                orden=0,
                fecha_instalacion=_a_fecha(contexto_raw.get("creacion")),
                fecha_baja=None,
                estado_comercial=contexto_raw.get("estado_comercial"),
                motivo_baja=None,
                es_vigente=_es_estado_comercial_vigente(contexto_raw.get("estado_comercial")),
            )
        ]

    equipos: list[EquipoUltimaMilla] = []
    for extremo in (1, 2):
        nodo = contexto_raw.get(f"Nodo{extremo}")
        equipo = contexto_raw.get(f"Equipo{extremo}")
        puerto = contexto_raw.get(f"Port{extremo}")
        direccion = contexto_raw.get(f"Direccion{extremo}")
        provincia = contexto_raw.get(f"Provincia{extremo}")
        if not any((nodo, equipo, puerto, direccion, provincia)):
            continue
        equipos.append(
            EquipoUltimaMilla(
                extremo=extremo, nodo=nodo, equipo=equipo, puerto=puerto, direccion=direccion, provincia=provincia
            )
        )

    return ContextoProvParseado(
        nro_servicio_vigente=nro_servicio_vigente,
        nro_servicio_original=nro_servicio_original,
        tipo_servicio=contexto_raw.get("id_servicio"),
        nombre_cliente=contexto_raw.get("Descripcion"),
        estado_comercial=contexto_raw.get("estado_comercial"),
        historial=historial,
        equipos=equipos,
    )


async def ingerir_contexto_prov(session: AsyncSession, servicio: Servicio, contexto_raw: dict[str, Any]) -> None:
    """Aplica un contexto de PROV ya obtenido a un `Servicio` existente, en memoria — el caller hace
    `session.commit()`. Reusa la consolidación de identidad y la regla de estado ya validadas para
    Excel (`servicios_consolidacion_service.py`, sin modificar): son agnósticas de la fuente.
    """
    parseado = parsear_contexto_prov(contexto_raw)

    # Todos los IDs de la cadena (salvo el vigente, que ya entra como `numero_linea_excel`) se
    # tratan como aliases ya conocidos — `consolidar_identidad_servicio` los combina con los
    # aliases existentes en DB y dedupe. No hace falta usar `linea_upgrade_de`/`linea_upgrade_a`
    # (esos parámetros modelan un puntero simple; PROV ya da la cadena completa).
    ids_de_la_cadena = {eslabon.numero_id for eslabon in parseado.historial if eslabon.numero_id}
    ids_de_la_cadena.discard(parseado.nro_servicio_vigente)
    alias_combinados = sorted(set(servicio.alias_ids or []) | ids_de_la_cadena)

    identidad = consolidar_identidad_servicio(
        numero_primer_servicio=parseado.nro_servicio_original,
        numero_linea_excel=parseado.nro_servicio_vigente,
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual=servicio.servicio_id,
        numero_linea_actual=servicio.numero_linea,
        alias_ids_actual=alias_combinados,
    )

    estado_prov = _traducir_estado_comercial(parseado.estado_comercial)
    servicio.estado_servicio = resolver_estado_servicio(
        estado_actual=servicio.estado_servicio,
        estado_excel=estado_prov,
        avanza_identidad=identidad.avanza_por_excel,
    )

    # `app.servicios.servicio_id` tiene índice UNIQUE (`ix_servicios_servicio_id`): si otra fila ya
    # ocupa el ID vigente que esta consolidación calculó, pisarlo revienta el commit con
    # `duplicate key value` (176 colisiones reales medidas en dev por la ingesta Excel, ~14% de las
    # filas — ver la sección "Fusión de placeholders Cromo puros" en
    # `api/app/routes/servicios.py`). Se degrada igual que ahí: se conserva el `servicio_id` actual,
    # el ID rechazado baja a `alias_ids` (para que el matching de Cromo lo resuelva de todas formas)
    # y se loguea. Fusionar dos registros reales sin confirmación humana está fuera de alcance a
    # propósito; la fusión de placeholders Cromo puros del camino Excel es específica de un batch
    # (dos filas del MISMO archivo) y no aplica a este refresco fila-por-fila.
    servicio_id_final = identidad.servicio_id
    alias_ids_final = list(identidad.alias_ids)
    if servicio_id_final != servicio.servicio_id:  # una asignación no-op nunca puede colisionar
        condiciones = [Servicio.servicio_id == servicio_id_final]
        if servicio.id is not None:
            # Sólo tiene sentido excluirse a sí misma si ya existe un PK — una fila nueva sin
            # persistir no puede aparecer como "otra fila" en esta consulta de todas formas, así
            # que el filtro de auto-exclusión se omite (no hace falta) en vez de agregarse.
            condiciones.append(Servicio.id != servicio.id)
        id_en_colision = (
            (await session.execute(select(Servicio.id).where(*condiciones).limit(1))).scalars().first()
        )
        if id_en_colision is not None:
            logger.warning(
                "action=prov_ingesta evento=servicio_id_colision_no_fusionable servicio_id_deseado=%s "
                "servicio_id_actual=%s colision_con_id=%s",
                identidad.servicio_id,
                servicio.servicio_id,
                id_en_colision,
            )
            servicio_id_final = servicio.servicio_id
            # `consolidar_identidad_servicio` excluyó de los alias al ID que iba a ser el
            # `servicio_id` (el rechazado). Al degradar se invierte: el valor que se conserva no
            # tiene sentido como su propio alias, y el rechazado sí entra como alias.
            if servicio_id_final in alias_ids_final:
                alias_ids_final.remove(servicio_id_final)
            if identidad.servicio_id != servicio_id_final and identidad.servicio_id not in alias_ids_final:
                alias_ids_final.append(identidad.servicio_id)

    servicio.servicio_id = servicio_id_final
    # `numero_linea` no tiene constraint UNIQUE: siempre refleja el ID vigente que calculó la
    # consolidación, incluso cuando `servicio_id` no pudo avanzar (mismo criterio que el Excel).
    servicio.numero_linea = identidad.numero_linea
    servicio.alias_ids = alias_ids_final
    if not servicio.numero_primer_servicio:
        servicio.numero_primer_servicio = parseado.nro_servicio_original

    if parseado.nombre_cliente:
        servicio.nombre_cliente = parseado.nombre_cliente
        servicio.cliente = parseado.nombre_cliente
    if parseado.tipo_servicio:
        servicio.tipo_servicio = parseado.tipo_servicio
    if parseado.equipos:
        primero = parseado.equipos[0]
        if primero.direccion:
            servicio.direccion = primero.direccion
        if primero.provincia:
            servicio.provincia = primero.provincia
        if len(parseado.equipos) > 1 and parseado.equipos[1].direccion:
            servicio.direccion_2 = parseado.equipos[1].direccion

    if servicio.es_verificable_override is not None:
        servicio.es_verificable = servicio.es_verificable_override
    else:
        servicio.es_verificable = es_verificable_por_tipo_y_estado(servicio.tipo_servicio, servicio.estado_servicio)

    # Mismo criterio que ya usa `POST /servicios/ingest`: cada ingesta re-etiqueta `origen_datos`
    # con su propia fuente incondicionalmente (ver `api/app/routes/servicios.py::ingest_servicios`,
    # `set_map["origen_datos"] = excluded.origen_datos`) — no hay una jerarquía de "orígenes más
    # autoritativos" implementada hoy en el repo.
    servicio.origen_datos = ServicioOrigenDatos.INGEST_PROV

    await session.execute(delete(ServicioHistorialId).where(ServicioHistorialId.servicio_id == servicio.id))
    for eslabon in parseado.historial:
        session.add(
            ServicioHistorialId(
                servicio_id=servicio.id,
                numero_id=eslabon.numero_id,
                orden=eslabon.orden,
                fecha_instalacion=eslabon.fecha_instalacion,
                fecha_baja=eslabon.fecha_baja,
                estado_comercial=eslabon.estado_comercial,
                motivo_baja=eslabon.motivo_baja,
                es_vigente=eslabon.es_vigente,
            )
        )

    await session.execute(
        delete(ServicioEquipoUltimaMilla).where(ServicioEquipoUltimaMilla.servicio_id == servicio.id)
    )
    for equipo in parseado.equipos:
        session.add(
            ServicioEquipoUltimaMilla(
                servicio_id=servicio.id,
                extremo=equipo.extremo,
                nodo=equipo.nodo,
                equipo=equipo.equipo,
                puerto=equipo.puerto,
                direccion=equipo.direccion,
                provincia=equipo.provincia,
            )
        )


__all__ = ["parsear_contexto_prov", "ingerir_contexto_prov", "ContextoProvParseado", "EslabonHistorial", "EquipoUltimaMilla"]
