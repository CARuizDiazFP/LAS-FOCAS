# Nombre de archivo: parser.py
# Ubicación de archivo: core/services/cromo/parser.py
# Descripción: Parser puro de payloads de Cromo Red a dataclasses de dominio, sin I/O

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Union

from pyproj import Transformer

from core.services.cromo.modelos import Botella, Cable, Fusion, Pelo, Tubo

logger = logging.getLogger(__name__)

# Gauss-Krüger Faja 5, datum POSGAR94 — confirmado real (Etapa 8) contra dos direcciones conocidas
# (Av. Santa Fe 2600 CABA, Saenz Valiente 2420 San Isidro). Instancia a nivel de módulo: crearla es
# el costo caro de pyproj (carga la grilla de PROJ), reusarla es gratis.
_TRANSFORMER_GAUSS_KRUGER_FAJA5 = Transformer.from_crs("EPSG:22185", "EPSG:4326", always_xy=True)

# Clase 120: parcelas catastrales, no botellas. Ver docs/ingesta_cromo.md capítulo 2, fila 1.
_CLASES_EXCLUIDAS: dict[int, str] = {
    120: "clase 120 son parcelas catastrales, no botellas",
}
# Clase 124: estructuralmente una botella pero sin homologar (code = "NO-SABE").
_CLASES_NO_HOMOLOGADAS: frozenset[int] = frozenset({124})
_CLASES_BOTELLA: frozenset[int] = frozenset({68, 121, 122, 123, 124, 125})

_CLASE_CABLE = 51
_CLASE_TUBO = 129
_CLASE_PELO = 130
_CLASE_FUSION = 132

# Texto libre de at.61, p.ej. "FO 114830 - EDGE - CIRION - Pelo 1 de 2".
#
# Prefijos más allá de "FO" agregados en Etapa 9c — hallazgo real contra `lasfocasdev-postgres`: de
# los ~1,28M pelos vigentes, 96,6% queda `INDETERMINADO`; de esos, ~250K SÍ tienen `servicio_raw` pero
# el regex original (sólo "FO") nunca les extraía número. Catalogando esos ~250K por el prefijo real
# que antecede al número: "INT"/"TLS"/"EWS"/"RPV"/"DWDM"/"TDM"/"ATD"/"VID"/"TRUNK" agregan ~89.361
# pelos candidatos, de los cuales ~6.738 matchean de verdad contra `app.servicios` (que ya trackea
# esos mismos `tipo_servicio` para FO — no son inventados). Confirmado con `app.servicios.tipo_servicio`
# real: RPV/TLS/INT/EWS/FO/VID conviven en la misma tabla, mismo esquema de numeración. Prefijos con 0
# matches reales en la muestra (OS/RED/ISI/ATI/MZ/ADVA) quedaron afuera a propósito — mayor riesgo de
# falso positivo (texto libre que empieza con esas letras por coincidencia, no un código de servicio).
_REGEX_SERVICIO = re.compile(
    r"\b(?:FO|TLS|DWDM|INT|EWS|RPV|TDM|ATD|VID|TRUNK)\s*[:\-]?\s*(\d+)", re.IGNORECASE
)


class ClaseExcluidaError(ValueError):
    """Se intentó parsear un objeto de una clase explícitamente excluida (p.ej. 120)."""

    def __init__(self, clase: Optional[int], motivo: str) -> None:
        super().__init__(f"clase {clase} excluida: {motivo}")
        self.clase = clase


class ClaseNoSoportadaError(ValueError):
    """La clase del objeto no tiene parser asociado en esta etapa."""

    def __init__(self, clase: Optional[int]) -> None:
        super().__init__(f"clase {clase} no tiene parser asociado")
        self.clase = clase


@dataclass(slots=True)
class ErrorParseo:
    """Resultado de error para un objeto que no pudo parsearse, identificado por n_id y clase."""

    n_id: Optional[int]
    clase: Optional[int]
    motivo: str


@dataclass(slots=True)
class ArbolBotella:
    """Resultado de recorrer una botella completa: la propia botella más su mundo interno."""

    botella: Botella
    fusiones: list[Fusion]
    cables: list[Cable]
    tubos: list[Tubo]
    pelos: list[Pelo]
    errores: list[ErrorParseo]


ObjetoDominio = Union[Botella, Cable, Tubo, Pelo, Fusion]


def atributo(obj: Mapping[str, Any], attr_id: int) -> Optional[str]:
    """Resuelve un atributo dinámico de `at[]` por `id`. Nunca por posición ni por `seq`."""
    for item in obj.get("at") or []:
        if item.get("id") == attr_id:
            return item.get("value")
    return None


def _resolver_n_id(obj: Mapping[str, Any]) -> Optional[int]:
    """`n_id` es la PK de linaje. Si falta, se usa `id` como fallback y se registra un warning."""
    n_id = obj.get("n_id")
    if n_id is None:
        id_ = obj.get("id")
        logger.warning("action=cromo_parser evento=sin_n_id id=%s clase=%s", id_, obj.get("class"))
        return id_
    return n_id


def resolver_lat_lon(ll: Optional[Iterable[float]]) -> tuple[Optional[float], Optional[float]]:
    """`ll` viene como [longitud, latitud]. Devuelve (latitud, longitud), en ese orden."""
    if ll is None:
        return None, None
    valores = list(ll)
    if len(valores) < 2:
        return None, None
    longitud, latitud = valores[0], valores[1]
    return latitud, longitud


def resolver_lat_lon_gauss_kruger(pts: Optional[Iterable[float]]) -> tuple[Optional[float], Optional[float]]:
    """`pts` viene en Gauss-Krüger Faja 5 / POSGAR94 (`EPSG:22185`) como [este, norte]. Reproyecta a
    WGS84 y devuelve (latitud, longitud) — es la clave que realmente trae el punto geográfico en la
    práctica; `ll` (`resolver_lat_lon`, documentada originalmente) nunca apareció en un barrido
    paginado real completo (Etapa 8, 11.100 botellas verificadas, 0 con clave `ll`)."""
    if pts is None:
        return None, None
    valores = list(pts)
    if len(valores) < 2:
        return None, None
    este, norte = valores[0], valores[1]
    try:
        longitud, latitud = _TRANSFORMER_GAUSS_KRUGER_FAJA5.transform(este, norte)
    except Exception:
        logger.warning("action=cromo_parser evento=error_reproyeccion_geo pts=%s", valores)
        return None, None
    return latitud, longitud


def _resolver_geo(obj: Mapping[str, Any]) -> tuple[Optional[float], Optional[float]]:
    if obj.get("ll") is not None:
        return resolver_lat_lon(obj.get("ll"))
    return resolver_lat_lon_gauss_kruger(obj.get("pts"))


def _a_entero(valor: Optional[str]) -> Optional[int]:
    if valor is None:
        return None
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _a_float(valor: Optional[str]) -> Optional[float]:
    if valor is None:
        return None
    texto = str(valor).strip().replace(",", ".")
    if not texto:
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def _capacidad_a_entero(capacidad: Optional[str]) -> Optional[int]:
    """El prefijo numérico de at.32 (p.ej. "72-BRUG" → 72) es la capacidad en pelos."""
    if not capacidad:
        return None
    coincidencia = re.match(r"^\s*(\d+)", capacidad)
    return int(coincidencia.group(1)) if coincidencia else None


def parsear_servicio(servicio_raw: Optional[str]) -> tuple[Optional[str], str]:
    """Extrae el número de servicio de at.61 (texto libre). Nunca descarta el pelo si no matchea.

    Pública (no `_parsear_servicio`) a propósito desde Etapa 9c: además de `parse_pelo()` la usa
    `scripts/cromo_backfill_servicio_prefijos.py` para reintentar la extracción sobre pelos ya
    ingeridos con el regex viejo, sin duplicar la lógica.

    Hallazgo real (Etapa 8): un pelo con número de servicio extraído quedaba clasificado `LIBRE`
    ("pelo libre/sin asignar" según el propio enum `TipoAsociacionPelo`) — semánticamente invertido,
    un match significa justamente lo contrario: está asignado a un cliente. Corregido a `CLIENTE`.

    `TRUNK_DWDM`/`OLT_LASER`/`INFRA` (tráfico de infraestructura interna, no de cliente) y `LIBRE`
    propiamente dicho (pelo con `at.61` presente pero indicando explícitamente que no hay asignación)
    quedan sin implementar — requieren mirar una muestra real de valores de `at.61` que no matchean el
    regex de número de servicio para saber qué patrones usa Metrotel, no se puede diseñar a ciegas.
    Mientras tanto, todo lo que no matchea (incluido ese tráfico) cae en `INDETERMINADO`.
    """
    if not servicio_raw:
        return None, "INDETERMINADO"
    coincidencia = _REGEX_SERVICIO.search(servicio_raw)
    if not coincidencia:
        return None, "INDETERMINADO"
    return coincidencia.group(1), "CLIENTE"


def parse_botella(obj: Mapping[str, Any]) -> Botella:
    """Parsea botella/empalme (class 68·121·122·123·124·125). Rechaza la clase 120 explícitamente."""
    clase = obj.get("class")
    if clase in _CLASES_EXCLUIDAS:
        raise ClaseExcluidaError(clase, _CLASES_EXCLUIDAS[clase])

    n_id = _resolver_n_id(obj)
    latitud, longitud = _resolver_geo(obj)
    return Botella(
        n_id=n_id,
        version_id=obj.get("id"),
        vmax=obj.get("vmax"),
        clase=clase,
        nombre=atributo(obj, 34) or obj.get("name"),
        codigo_modelo=atributo(obj, 41) or obj.get("code"),
        id_legacy=atributo(obj, 91),
        notas=atributo(obj, 35),
        calle=atributo(obj, 67),
        altura=atributo(obj, 16),
        localidad=atributo(obj, 68),
        provincia=atributo(obj, 69),
        ubicacion_fisica=atributo(obj, 118),
        tendido=atributo(obj, 20),
        latitud=latitud,
        longitud=longitud,
        pts_raw=obj.get("pts"),
        clase_no_homologada=clase in _CLASES_NO_HOMOLOGADAS,
        payload_raw=dict(obj),
    )


def _resolver_extremos(obj: Mapping[str, Any]) -> tuple[Optional[Mapping[str, Any]], Optional[Mapping[str, Any]]]:
    extremo_a: Optional[Mapping[str, Any]] = None
    extremo_b: Optional[Mapping[str, Any]] = None
    for item in obj.get("tp") or []:
        if item.get("nfrom") == 0 and extremo_a is None:
            extremo_a = item
        elif item.get("nfrom") == 1 and extremo_b is None:
            extremo_b = item
    return extremo_a, extremo_b


def parse_cable(obj: Mapping[str, Any]) -> Cable:
    """Parsea cable de FO (class 51). Sirve tanto para el barrido directo como para el embebido en botella.tp[]."""
    n_id = _resolver_n_id(obj)
    capacidad = atributo(obj, 32)
    extremo_a, extremo_b = _resolver_extremos(obj)
    return Cable(
        n_id=n_id,
        version_id=obj.get("id"),
        vmax=obj.get("vmax"),
        nombre=atributo(obj, 26) or obj.get("name"),
        capacidad=capacidad,
        capacidad_pelos=_capacidad_a_entero(capacidad),
        propietario=atributo(obj, 25),
        jerarquia=atributo(obj, 27),
        tendido=atributo(obj, 20),
        distancia_geo=_a_float(atributo(obj, 23)),
        distancia_real=_a_float(atributo(obj, 24)),
        id_legacy=atributo(obj, 91),
        notas=atributo(obj, 35),
        extremo_a_n_id=extremo_a.get("id_to") if extremo_a else None,
        extremo_a_clase=extremo_a.get("class") if extremo_a else None,
        extremo_a_legacy=atributo(obj, 28),
        extremo_a_nombre=atributo(obj, 34),
        extremo_b_n_id=extremo_b.get("id_to") if extremo_b else None,
        extremo_b_clase=extremo_b.get("class") if extremo_b else None,
        extremo_b_legacy=atributo(obj, 29),
        extremo_b_nombre=atributo(obj, 37),
        pts_raw=obj.get("pts"),
        payload_raw=dict(obj),
    )


def parse_tubo(obj: Mapping[str, Any]) -> Tubo:
    """Parsea tubo/buffer (class 129). `parent` ya es el `n_id` del cable."""
    return Tubo(
        n_id=_resolver_n_id(obj),
        cable_n_id=obj.get("parent"),
        orden=_a_entero(atributo(obj, 72)),
        nombre_color=atributo(obj, 73) or atributo(obj, 76),
    )


def parse_pelo(obj: Mapping[str, Any]) -> Pelo:
    """Parsea pelo/hilo (class 130). Un pelo sin at.61 se parsea igual, sin excepción."""
    servicio_raw = atributo(obj, 61)
    servicio_numero, tipo_asociacion = parsear_servicio(servicio_raw)
    return Pelo(
        n_id=_resolver_n_id(obj),
        tubo_n_id=obj.get("parent"),
        cable_n_id=None,
        numero_pelo=atributo(obj, 75) or obj.get("name"),
        orden=_a_entero(atributo(obj, 74)),
        color=atributo(obj, 77),
        servicio_raw=servicio_raw,
        servicio_numero=servicio_numero,
        tipo_asociacion=tipo_asociacion,
    )


def parse_fusion(obj: Mapping[str, Any]) -> Fusion:
    """Parsea fusión (class 132). No asume que el tipo (at.85) sea siempre "FUSION"."""
    latitud, longitud = _resolver_geo(obj)
    pelos_tp = [item for item in (obj.get("tp") or []) if item.get("class") == _CLASE_PELO]
    pelo_a = pelos_tp[0].get("id_to") if len(pelos_tp) > 0 else None
    pelo_b = pelos_tp[1].get("id_to") if len(pelos_tp) > 1 else None
    return Fusion(
        n_id=_resolver_n_id(obj),
        botella_n_id=obj.get("parent"),
        nombre_par=atributo(obj, 84) or obj.get("name"),
        tipo=atributo(obj, 85),
        pelo_a_n_id=pelo_a,
        pelo_b_n_id=pelo_b,
        latitud=latitud,
        longitud=longitud,
    )


_DISPATCH = {
    68: parse_botella,
    121: parse_botella,
    122: parse_botella,
    123: parse_botella,
    124: parse_botella,
    125: parse_botella,
    _CLASE_CABLE: parse_cable,
    _CLASE_TUBO: parse_tubo,
    _CLASE_PELO: parse_pelo,
    _CLASE_FUSION: parse_fusion,
}


def parse_objeto(obj: Mapping[str, Any]) -> ObjetoDominio:
    """Despacha el parseo según `class`. Levanta error explícito para clases excluidas o no soportadas."""
    clase = obj.get("class")
    if clase in _CLASES_EXCLUIDAS:
        raise ClaseExcluidaError(clase, _CLASES_EXCLUIDAS[clase])
    parser_fn = _DISPATCH.get(clase)
    if parser_fn is None:
        raise ClaseNoSoportadaError(clase)
    return parser_fn(obj)


def parse_pagina(objetos: Iterable[Mapping[str, Any]]) -> tuple[list[ObjetoDominio], list[ErrorParseo]]:
    """Parsea una página de objetos. Un objeto malformado no aborta el resto de la página."""
    ok: list[ObjetoDominio] = []
    errores: list[ErrorParseo] = []
    for obj in objetos:
        try:
            ok.append(parse_objeto(obj))
        except Exception as exc:  # noqa: BLE001 - tolerancia deliberada por objeto, ver docstring
            errores.append(
                ErrorParseo(n_id=obj.get("n_id") or obj.get("id"), clase=obj.get("class"), motivo=str(exc))
            )
    return ok, errores


def extraer_tubos_y_pelos(
    cable_obj: Mapping[str, Any],
) -> tuple[list[Tubo], list[Pelo], list[ErrorParseo]]:
    """`cable.inner[]` es una lista plana de tubos y pelos hermanos, sin anidamiento."""
    n_id_cable = _resolver_n_id(cable_obj)
    tubos: list[Tubo] = []
    pelos: list[Pelo] = []
    errores: list[ErrorParseo] = []
    for item in cable_obj.get("inner") or []:
        clase = item.get("class")
        try:
            if clase == _CLASE_TUBO:
                tubos.append(parse_tubo(item))
            elif clase == _CLASE_PELO:
                pelo = parse_pelo(item)
                pelo.cable_n_id = n_id_cable
                pelos.append(pelo)
            else:
                errores.append(
                    ErrorParseo(
                        n_id=item.get("n_id") or item.get("id"),
                        clase=clase,
                        motivo="clase inesperada en cable.inner[], se esperaba 129 (tubo) o 130 (pelo)",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - tolerancia deliberada por objeto
            errores.append(ErrorParseo(n_id=item.get("n_id") or item.get("id"), clase=clase, motivo=str(exc)))
    return tubos, pelos, errores


def parse_arbol_botella(obj: Mapping[str, Any]) -> ArbolBotella:
    """Recorre una botella completa: `inner[]` → fusiones; `tp[]` → cables y su mundo interno."""
    botella = parse_botella(obj)
    fusiones: list[Fusion] = []
    cables: list[Cable] = []
    tubos: list[Tubo] = []
    pelos: list[Pelo] = []
    errores: list[ErrorParseo] = []

    for item in obj.get("inner") or []:
        clase = item.get("class")
        if clase != _CLASE_FUSION:
            errores.append(
                ErrorParseo(
                    n_id=item.get("n_id") or item.get("id"),
                    clase=clase,
                    motivo="clase inesperada en botella.inner[], se esperaba únicamente 132 (fusión)",
                )
            )
            continue
        try:
            fusiones.append(parse_fusion(item))
        except Exception as exc:  # noqa: BLE001 - tolerancia deliberada por objeto
            errores.append(ErrorParseo(n_id=item.get("n_id") or item.get("id"), clase=clase, motivo=str(exc)))

    for item in obj.get("tp") or []:
        if item.get("class") != _CLASE_CABLE:
            continue
        try:
            cable = parse_cable(item)
        except Exception as exc:  # noqa: BLE001 - tolerancia deliberada por objeto
            errores.append(
                ErrorParseo(n_id=item.get("n_id") or item.get("id"), clase=item.get("class"), motivo=str(exc))
            )
            continue
        cables.append(cable)
        item_tubos, item_pelos, item_errores = extraer_tubos_y_pelos(item)
        tubos.extend(item_tubos)
        pelos.extend(item_pelos)
        errores.extend(item_errores)

    return ArbolBotella(botella=botella, fusiones=fusiones, cables=cables, tubos=tubos, pelos=pelos, errores=errores)


__all__ = [
    "ArbolBotella",
    "ErrorParseo",
    "ClaseExcluidaError",
    "ClaseNoSoportadaError",
    "atributo",
    "resolver_lat_lon",
    "parse_objeto",
    "parse_pagina",
    "parse_botella",
    "parse_cable",
    "parse_tubo",
    "parse_pelo",
    "parsear_servicio",
    "parse_fusion",
    "parse_arbol_botella",
    "extraer_tubos_y_pelos",
]
