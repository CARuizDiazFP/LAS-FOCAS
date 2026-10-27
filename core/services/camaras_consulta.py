# Nombre de archivo: camaras_consulta.py
# Ubicación de archivo: core/services/camaras_consulta.py
# Descripción: Consulta de Cámaras: smart search por términos (query, filtros, matching y paginación)

"""Smart search de Cámaras movida desde `web/app/routers/camaras.py`.

Cada término se busca en múltiples campos (nombre, dirección, fontine_id, servicios, cables,
estado, origen) y los términos se combinan con AND. Filtro, conteo y paginación corren en SQL
(`condicion_termino`); sólo la página se carga con sus relaciones.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from db.models.infra import (
    Cable,
    Camara,
    CamaraOrigenDatos,
    Empalme,
    RutaServicio,
    Servicio,
    ruta_empalme_association,
    servicio_empalme_association,
)
from db.models.infra import CamaraEstado as _CamaraEstado

LIMITE_MAXIMO = 500

# Relaciones que el matching y la serialización recorren por cámara, cargadas por lote
# (`selectinload`: una sentencia por relación cada 500 padres, sin multiplicar ni reordenar filas
# como haría un `joinedload` sobre colecciones). Sin esto, la smart search con términos hacía unas
# 34.000 sentencias (lazy load por cámara raíz: empalmes, cables origen/destino, empalmes de botellas).
# `Camara.cables` es una @property (`cables_origen + cables_destino`), por eso se cargan las dos.
# Las botellas sólo aportan sus empalmes (`_collect_camara_rutas_info`); sus cables no se leen.
# `Empalme.servicios` se lee sólo en la cámara raíz, cuando no hay rutas.
# `Empalme.rutas` (y sus empalmes, puntos terminales y servicio, que lee `_collect_camara_rutas_info`)
# también va por lote: desde que la relación tiene `order_by` por id, el lote y la carga individual
# devuelven el mismo orden (antes, sin `order_by`, diferían en 151 empalmes de dev).
_CARGA_POR_LOTE = (
    selectinload(Camara.empalmes).selectinload(Empalme.servicios),
    selectinload(Camara.cables_origen),
    selectinload(Camara.cables_destino),
    selectinload(Camara.botellas).selectinload(Camara.empalmes),
    selectinload(Camara.empalmes).selectinload(Empalme.rutas).selectinload(RutaServicio.empalmes),
    selectinload(Camara.empalmes).selectinload(Empalme.rutas).selectinload(RutaServicio.puntos_terminales),
    selectinload(Camara.empalmes).selectinload(Empalme.rutas).selectinload(RutaServicio.servicio),
    selectinload(Camara.botellas).selectinload(Camara.empalmes).selectinload(Empalme.rutas),
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


def normalizar_terminos(terminos: list[str]) -> list[str]:
    """Strip de cada término y descarte de los vacíos (se conservan repetidos y el orden)."""

    return [limpio for limpio in (t.strip() for t in terminos) if limpio]


def _raiz_del_grupo() -> tuple[Any, Any]:
    """(alias de cámara, id de la cámara raíz de su grupo): la propia si es raíz, la padre si es Botella.

    Replica `_collect_camara_rutas_info(incluir_botellas=True)`: una raíz ve los empalmes propios y los
    de sus Botellas directas (un solo nivel)."""

    grupo = aliased(Camara)
    return grupo, func.coalesce(grupo.camara_padre_id, grupo.id)


def condicion_termino(termino: str) -> Any:
    """Condición SQL de un término sobre la cámara raíz: aparece (insensible a mayúsculas, como subcadena)
    en nombre, dirección, `fontine_id`, servicios, cables, estado u origen.

    Mismo criterio que el matching en Python que reemplaza: los servicios salen de las rutas de los
    empalmes de la raíz y sus Botellas y, sólo si el grupo no tiene ninguna ruta, de la relación legacy
    `servicio_empalme_association` de los empalmes propios; los cables son los de la raíz (origen o
    destino). Estado y origen se resuelven en Python contra los valores del enum. `autoescape` neutraliza
    `%` y `_` del término."""

    termino_lower = termino.lower()

    def contiene(columna: Any) -> Any:
        return columna.icontains(termino, autoescape=True)

    grupo, raiz = _raiz_del_grupo()
    servicios_por_ruta = (
        select(raiz)
        .select_from(Servicio)
        .join(RutaServicio, RutaServicio.servicio_id == Servicio.id)
        .join(ruta_empalme_association, ruta_empalme_association.c.ruta_id == RutaServicio.id)
        .join(Empalme, Empalme.id == ruta_empalme_association.c.empalme_id)
        .join(grupo, grupo.id == Empalme.camara_id)
        .where(contiene(Servicio.servicio_id))
    )
    grupo_r, raiz_r = _raiz_del_grupo()
    grupos_con_rutas = (
        select(raiz_r)
        .select_from(ruta_empalme_association)
        .join(Empalme, Empalme.id == ruta_empalme_association.c.empalme_id)
        .join(grupo_r, grupo_r.id == Empalme.camara_id)
    )
    servicios_legacy = (
        select(Empalme.camara_id)
        .join(servicio_empalme_association, servicio_empalme_association.c.empalme_id == Empalme.id)
        .join(Servicio, Servicio.id == servicio_empalme_association.c.servicio_id)
        .where(contiene(Servicio.servicio_id))
    )

    condiciones = [
        contiene(Camara.nombre),
        contiene(Camara.direccion),
        contiene(Camara.fontine_id),
        Camara.id.in_(servicios_por_ruta),
        and_(Camara.id.in_(servicios_legacy), Camara.id.not_in(grupos_con_rutas)),
        Camara.id.in_(select(Cable.origen_camara_id).where(contiene(Cable.nombre))),
        Camara.id.in_(select(Cable.destino_camara_id).where(contiene(Cable.nombre))),
    ]
    estados = [e for e in _CamaraEstado if termino_lower in e.value.lower()]
    if estados:
        condiciones.append(Camara.estado.in_(estados))
    origenes = [o for o in CamaraOrigenDatos if termino_lower in o.value.lower()]
    if origenes:
        condiciones.append(Camara.origen_datos.in_(origenes))
    return or_(*condiciones)


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

    # Cada término es una condición SQL (AND entre términos): el filtro, el conteo y el LIMIT/OFFSET
    # corren en la base y sólo se carga la página. Antes se cargaba el grafo de todas las raíces
    # (~10.000 en dev) para matchear en Python: ~6 s por búsqueda.
    for termino in terminos_limpios:
        query = query.filter(condicion_termino(termino))
    total = query.count()
    # `Camara.id` desempata nombres repetidos: sin él, el orden entre páginas no es determinista.
    pagina = query.order_by(Camara.nombre, Camara.id).offset(offset).limit(limit).all()
    encontradas = [CamaraEncontrada(c, *_rutas_y_servicios(c)) for c in pagina]
    return ResultadoSmartSearch(total, limit, offset, estado_filter, len(terminos_limpios), encontradas)
