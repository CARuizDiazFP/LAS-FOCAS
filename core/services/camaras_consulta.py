# Nombre de archivo: camaras_consulta.py
# Ubicación de archivo: core/services/camaras_consulta.py
# Descripción: Consulta de Cámaras: listado simple, smart search por términos y serialización común web/API

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


def _camaras_de_servicio(session: Session, texto: str) -> list[Camara]:
    """Cámaras de las rutas del primer servicio cuyo `servicio_id` contiene `texto` (orden por
    `servicio_id`, sin repetir, en el orden en que aparecen en las rutas), con la carga por lote."""

    servicio = (
        session.query(Servicio)
        .filter(Servicio.servicio_id.ilike(f"%{texto}%"))
        .options(selectinload(Servicio.rutas).selectinload(RutaServicio.empalmes))
        .order_by(Servicio.servicio_id)
        .first()
    )
    if servicio is None:
        return []
    ids: list[int] = []
    for ruta in servicio.rutas:
        for empalme in ruta.empalmes:
            if empalme.camara_id is not None and empalme.camara_id not in ids:
                ids.append(empalme.camara_id)
    if not ids:
        return []
    por_id = {c.id: c for c in session.query(Camara).filter(Camara.id.in_(ids)).options(*_CARGA_POR_LOTE).all()}
    return [por_id[i] for i in ids if i in por_id]


def listar_camaras(session: Session, *, q: str | None, estado: str | None, limit: int) -> list[CamaraEncontrada]:
    """Listado de `GET /api/infra/camaras` (panel y API): sin filtrar Botellas ni NO_OPERATIVA, por nombre.

    `q` busca (subcadena, insensible a mayúsculas) en nombre, dirección y `fontine_id`; si no hay ninguna
    cámara, cae al primer servicio cuyo `servicio_id` contiene `q` y devuelve las cámaras de sus rutas.
    `estado` se ignora si no es un valor del enum."""

    limit = min(limit, LIMITE_MAXIMO)
    query = session.query(Camara).options(*_CARGA_POR_LOTE)
    if estado and estado.upper() in [e.value for e in _CamaraEstado]:
        query = query.filter(Camara.estado == _CamaraEstado(estado.upper()))
    texto = q.strip() if q else ""
    if texto:
        patron = f"%{texto}%"
        query = query.filter(
            Camara.nombre.ilike(patron) | Camara.direccion.ilike(patron) | Camara.fontine_id.ilike(patron)
        )
    camaras = query.order_by(Camara.nombre).limit(limit).all()
    if texto and not camaras:
        camaras = _camaras_de_servicio(session, texto)
    resultado = []
    for camara in camaras:
        rutas_info = _collect_camara_rutas_info(camara)
        resultado.append(CamaraEncontrada(camara, rutas_info, _collect_camara_servicios_ids(camara, rutas_info)))
    return resultado


def serializar_camara_basica(encontrada: CamaraEncontrada) -> dict[str, Any]:
    """Las 9 claves de `CamaraResponse` (API)."""

    cam = encontrada.camara
    return {
        "id": cam.id,
        "nombre": cam.nombre or "",
        "fontine_id": cam.fontine_id,
        "direccion": cam.direccion,
        "estado": cam.estado.value if cam.estado else "LIBRE",
        "origen_datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
        "latitud": cam.latitud,
        "longitud": cam.longitud,
        "servicios": encontrada.servicios_ids,
    }


def serializar_camara_panel(
    *,
    camara: Any,
    rutas_info: list[dict[str, Any]],
    servicios_ids: list[str],
    contexto: Any | None,
    editable: bool,
) -> dict[str, Any]:
    """Cámara del panel (21 claves): las básicas más rutas, contexto de estado y datos Cámara/Botella."""

    ticket_baneo = None
    tiene_baneo_activo = False
    tiene_ingreso_activo = False
    inconsistente = False
    estado_sugerido = None
    incidentes_activos: list[dict[str, Any]] = []

    if contexto is not None:
        ticket_baneo = contexto.ticket_baneo
        tiene_baneo_activo = contexto.tiene_baneo_activo
        tiene_ingreso_activo = contexto.tiene_ingreso_activo
        inconsistente = contexto.inconsistente
        estado_sugerido = contexto.estado_sugerido.value
        incidentes_activos = [incidente.to_dict() for incidente in contexto.incidentes_activos]

    # Navegación cruzada Botella→Cámara padre (2026-08-13): sólo tiene datos si `camara_padre_id`
    # está seteado (es una Botella legado) — el acceso a `.camara_padre` es lazy-load, pero acá
    # nunca dispara N+1 real: los listados batch (smart-search/search) sólo traen cámaras raíz
    # (`camara_padre_id IS NULL`), así que este branch sólo se ejecuta en fetches de una Botella
    # puntual (GET /api/infra/camaras/{id} con un id de Botella).
    camara_padre_id = getattr(camara, "camara_padre_id", None)
    camara_padre_nombre = None
    if camara_padre_id:
        camara_padre = getattr(camara, "camara_padre", None)
        camara_padre_nombre = camara_padre.nombre if camara_padre is not None else None

    return {
        "id": camara.id,
        "nombre": camara.nombre or "",
        "fontine_id": camara.fontine_id,
        "direccion": camara.direccion,
        "estado": camara.estado.value if camara.estado else "LIBRE",
        "origen_datos": camara.origen_datos.value if camara.origen_datos else "MANUAL",
        "latitud": camara.latitud,
        "longitud": camara.longitud,
        "servicios": servicios_ids,
        "rutas": rutas_info,
        "tiene_baneo_activo": tiene_baneo_activo,
        "tiene_ingreso_activo": tiene_ingreso_activo,
        "inconsistente": inconsistente,
        "estado_sugerido": estado_sugerido,
        "ticket_baneo": ticket_baneo,
        "editable": editable,
        "incidentes_activos": incidentes_activos,
        # Etapa Cámara/Botella: `es_botella`/`botellas_count` sólo tienen sentido si `camara` trae
        # cargada la columna/relación nueva — con getattr por si algún caller viejo pasa un objeto
        # sin esos atributos (tests con SimpleNamespace, por ejemplo).
        "es_botella": bool(camara_padre_id),
        "camara_padre_id": camara_padre_id,
        "camara_padre_nombre": camara_padre_nombre,
        "botellas_count": len(getattr(camara, "botellas", None) or []),
    }
