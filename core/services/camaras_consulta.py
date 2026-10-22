# Nombre de archivo: camaras_consulta.py
# Ubicación de archivo: core/services/camaras_consulta.py
# Descripción: Consulta de Cámaras: smart search por términos (query, filtros, matching y paginación)

"""Smart search de Cámaras movida desde `web/app/routers/camaras.py`.

Cada término se busca en múltiples campos (nombre, dirección, fontine_id, servicios, cables,
estado, origen) y los términos se combinan con AND. El orden de evaluación es: query -> filtros ->
matching -> paginación. La query se ordena por nombre y se filtra en Python ANTES de paginar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, selectinload

from db.models.infra import Camara, Empalme
from db.models.infra import CamaraEstado as _CamaraEstado

LIMITE_MAXIMO = 500

# Relaciones que el matching y la serialización recorren por cámara, cargadas por lote
# (`selectinload`: una sentencia por relación cada 500 padres, sin multiplicar ni reordenar filas
# como haría un `joinedload` sobre colecciones). Sin esto, la smart search con términos hacía unas
# 34.000 sentencias (lazy load por cámara raíz: empalmes, cables origen/destino, empalmes de botellas).
# `Camara.cables` es una @property (`cables_origen + cables_destino`), por eso se cargan las dos.
# Las botellas sólo aportan sus empalmes (`_collect_camara_rutas_info`); sus cables no se leen.
# `Empalme.servicios` se lee sólo en la cámara raíz, cuando no hay rutas.
# `Empalme.rutas` queda lazy A PROPÓSITO: es many-to-many sin `order_by` y el lote devuelve las
# rutas de un empalme en otro orden que la carga individual (151 empalmes en dev), lo que cambiaría
# el orden de `rutas` en la respuesta. Se mantiene hasta que se decida un orden explícito.
_CARGA_POR_LOTE = (
    selectinload(Camara.empalmes).selectinload(Empalme.servicios),
    selectinload(Camara.cables_origen),
    selectinload(Camara.cables_destino),
    selectinload(Camara.botellas).selectinload(Camara.empalmes),
)


@dataclass(frozen=True)
class CamaraEncontrada:
    """Cámara de la página con las rutas y servicios ya calculados (no se recalculan al serializar)."""

    camara: Camara
    rutas_info: list[dict[str, Any]]
    servicios_ids: list[str]


@dataclass(frozen=True)
class ResultadoSmartSearch:
    """Página de resultados: cámaras ya filtradas y en orden."""

    total: int
    limit: int
    offset: int
    estado_filter: str | None
    terminos_aplicados: int
    camaras: list[CamaraEncontrada]


def _collect_camara_rutas_info(camara: Any, *, incluir_botellas: bool = False) -> list[dict[str, Any]]:
    """Obtiene las rutas asociadas a una cámara a través de sus empalmes.

    `incluir_botellas=True` (Etapa Cámara/Botella) también recorre los empalmes de todas las Botellas
    de `camara` — para que una cámara-raíz muestre los servicios de todo su grupo físico, no sólo los
    que pasan por su propia fila (los empalmes reales de un grupo suelen vivir en las botellas, no en
    la cámara padre sintetizada por el backfill)."""

    camaras_a_recorrer = [camara]
    if incluir_botellas:
        camaras_a_recorrer.extend(getattr(camara, "botellas", None) or [])

    rutas_info: list[dict[str, Any]] = []
    seen_rutas: set[int] = set()
    for cam in camaras_a_recorrer:
        for empalme in cam.empalmes:
            for ruta in empalme.rutas:
                if ruta.id in seen_rutas:
                    continue
                seen_rutas.add(ruta.id)
                alias_ids = ruta.servicio.alias_ids or []
                transitos_count = sum(1 for item in ruta.empalmes if item.es_transito)
                punta_a_sitio = ruta.punta_a.sitio_descripcion if ruta.punta_a else None
                punta_b_sitio = ruta.punta_b.sitio_descripcion if ruta.punta_b else None
                rutas_info.append(
                    {
                        "ruta_id": ruta.id,
                        "servicio_id": ruta.servicio.servicio_id,
                        "ruta_nombre": ruta.nombre,
                        "ruta_tipo": ruta.tipo.value,
                        "alias_ids": alias_ids,
                        "transitos_count": transitos_count,
                        "punta_a_sitio": punta_a_sitio,
                        "punta_b_sitio": punta_b_sitio,
                    }
                )
    return rutas_info


def _collect_camara_servicios_ids(camara: Any, rutas_info: list[dict[str, Any]] | None = None) -> list[str]:
    """Obtiene servicios asociados a una cámara desde rutas o relación legacy."""

    if rutas_info:
        return sorted({str(ruta["servicio_id"]) for ruta in rutas_info if ruta.get("servicio_id")})

    servicios_ids: list[str] = []
    for empalme in camara.empalmes:
        for servicio in empalme.servicios:
            if servicio.servicio_id and servicio.servicio_id not in servicios_ids:
                servicios_ids.append(servicio.servicio_id)
    return servicios_ids


def _cables_nombres(camara: Any) -> list[str]:
    cables_nombres: list[str] = []
    for cable in camara.cables:
        if cable.nombre and cable.nombre not in cables_nombres:
            cables_nombres.append(cable.nombre)
    return cables_nombres


def normalizar_terminos(terminos: list[str]) -> list[str]:
    """Strip de cada término y descarte de los vacíos (se conservan repetidos y el orden)."""

    return [limpio for limpio in (t.strip() for t in terminos) if limpio]


def termino_coincide(termino: str, camara: Any, servicios_ids: list[str], cables_nombres: list[str]) -> bool:
    """`True` si el término (insensible a mayúsculas) aparece en algún campo de la cámara."""

    termino_lower = termino.lower()

    if camara.nombre and termino_lower in camara.nombre.lower():
        return True
    if camara.direccion and termino_lower in camara.direccion.lower():
        return True
    if camara.fontine_id and termino_lower in camara.fontine_id.lower():
        return True
    for svc_id in servicios_ids:
        if termino_lower in svc_id.lower():
            return True
    for cable_nombre in cables_nombres:
        if termino_lower in cable_nombre.lower():
            return True

    estado_actual = camara.estado.value if camara.estado else "LIBRE"
    if termino_lower in estado_actual.lower():
        return True

    origen_actual = camara.origen_datos.value if camara.origen_datos else "MANUAL"
    return termino_lower in origen_actual.lower()


def _consulta_base(session: Session, estado: str | None, incluir_no_operativas: bool) -> tuple[Any, str | None]:
    """Query de cámaras-raíz con el filtro de estado y el de NO_OPERATIVA. Devuelve (query, estado_filter)."""

    # Etapa Cámara/Botella: el dashboard sólo muestra cámaras-raíz — sus Botellas viven en el
    # detalle. `_CARGA_POR_LOTE` (incluye `Camara.botellas`) evita las queries lazy por cámara.
    query = session.query(Camara).filter(Camara.camara_padre_id.is_(None)).options(*_CARGA_POR_LOTE)
    estado_filter: str | None = None
    if estado:
        estado_upper = estado.strip().upper()
        if estado_upper in [e.value for e in _CamaraEstado]:
            query = query.filter(Camara.estado == _CamaraEstado(estado_upper))
            estado_filter = estado_upper

    # Filtro ADICIONAL (AND), independiente del chip de estado: por defecto nunca se traen cámaras
    # NO_OPERATIVA salvo que el toggle esté activo, o que el chip de estado ya apunte a NO_OPERATIVA.
    if not incluir_no_operativas and estado_filter != _CamaraEstado.NO_OPERATIVA.value:
        query = query.filter(Camara.estado != _CamaraEstado.NO_OPERATIVA)
    return query, estado_filter


def _rutas_y_servicios(camara: Any) -> tuple[list[dict[str, Any]], list[str]]:
    rutas_info = _collect_camara_rutas_info(camara, incluir_botellas=True)
    return rutas_info, _collect_camara_servicios_ids(camara, rutas_info)


def _coincide_con_todos(camara: Any, terminos_limpios: list[str]) -> CamaraEncontrada | None:
    """Devuelve la cámara con lo calculado si cumple todos los términos (AND); si no, `None`."""

    rutas_info, servicios_ids = _rutas_y_servicios(camara)
    cables_nombres = _cables_nombres(camara)
    if all(termino_coincide(t, camara, servicios_ids, cables_nombres) for t in terminos_limpios):
        return CamaraEncontrada(camara, rutas_info, servicios_ids)
    return None


def buscar_camaras_por_terminos(
    session: Session,
    terminos: list[str],
    *,
    estado: str | None,
    incluir_no_operativas: bool,
    limit: int,
    offset: int,
) -> ResultadoSmartSearch:
    """Query, filtros, matching AND y paginación de la smart search."""

    limit = min(limit, LIMITE_MAXIMO)
    offset = max(offset, 0)
    query, estado_filter = _consulta_base(session, estado, incluir_no_operativas)
    terminos_limpios = normalizar_terminos(terminos)

    # Sin términos (lista vacía): LIMIT/OFFSET real en SQL, no hay nada que matchear en Python.
    if not terminos:
        total = query.count()
        pagina = query.order_by(Camara.nombre).offset(offset).limit(limit).all()
        encontradas = [CamaraEncontrada(c, *_rutas_y_servicios(c)) for c in pagina]
        return ResultadoSmartSearch(total, limit, offset, estado_filter, 0, encontradas)

    # Con términos: el match incluye campos computados (servicios/cables/rutas), se filtra en
    # Python sobre el set completo ordenado y DESPUÉS se pagina.
    todas = query.order_by(Camara.nombre).all()
    coinciden = [e for e in (_coincide_con_todos(c, terminos_limpios) for c in todas) if e is not None]
    return ResultadoSmartSearch(
        len(coinciden), limit, offset, estado_filter, len(terminos_limpios),
        coinciden[offset:offset + limit],
    )
