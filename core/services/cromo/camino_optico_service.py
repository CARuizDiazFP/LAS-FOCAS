# Nombre de archivo: camino_optico_service.py
# Ubicación de archivo: core/services/cromo/camino_optico_service.py
# Descripción: Resolución del camino óptico de un pelo de FO desde `/network/fo/{id}/path` de Cromo, sin persistir nada

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from core.services.cromo.parser import atributo, es_numero_servicio_plausible, parsear_servicio

logger = logging.getLogger(__name__)

ESTADO_OK = "OK"
ESTADO_SIN_SEMILLA = "SIN_SEMILLA"
ESTADO_SIN_CAMINO = "SIN_CAMINO"

TIPO_PELO = "PELO"
TIPO_FUSION = "FUSION"
TIPO_CONECTOR_ODF = "CONECTOR_ODF"
TIPO_NO_RESUELTO = "NO_RESUELTO"
TIPO_CLASE_DESCONOCIDA = "CLASE_DESCONOCIDA"

# Clases medidas en un camino real (2026-09-10, pelo 10006353, 883 nodos). El catálogo de
# `app.cromo_clases` manda cuando la clase está ahí; esto es sólo el fallback para las que no
# están ingeridas — 135 (patchera) y 136 (posición patchera) se denormalizan en
# `cromo_odf_conectores` y nunca tuvieron fila propia, y 52 apareció como un segundo tipo de
# cable (de un tercero) que la ingesta no barre.
_CLASES_FALLBACK: dict[int, str] = {
    2: "CAMARA",
    51: "CABLE",
    52: "CABLE",
    68: "BOTELLA",
    69: "ODF",
    121: "BOTELLA",
    122: "BOTELLA",
    123: "BOTELLA",
    124: "BOTELLA",
    125: "BOTELLA",
    129: "TUBO",
    130: TIPO_PELO,
    132: TIPO_FUSION,
    135: "PATCHERA",
    136: TIPO_CONECTOR_ODF,
}

_CLASES_CABLE = frozenset({51, 52})
_CLASE_TUBO = 129
_CLASE_PELO = 130
_CLASE_FUSION = 132
_CLASE_PATCHERA = 135
_CLASE_CONECTOR = 136
_CLASE_ODF = 69

# Atributos, todos resueltos por `at[].id` y nunca por posición. Los nombres vienen del propio
# campo `name` que manda Cromo (verificado real), no de una interpretación nuestra.
_AT_NOMBRE_CABLE = 26
_AT_DISTANCIA_GEO = 23
_AT_DISTANCIA_REAL = 24
_AT_CAPACIDAD = 32
_AT_NOMBRE_GENERICO = 34
_AT_SERVICIO_CRUDO = 61
_AT_SERVICIO_NUMERO = 62
_AT_TUBO_ORDEN = 72
_AT_TUBO_NOMBRE = 73
_AT_PELO_ORDEN = 74
_AT_PELO_NUMERO = 75
_AT_TUBO_COLOR = 76
_AT_PELO_COLOR = 77
_AT_PATCHERA_NOMBRE = 79
_AT_CONECTOR_NUMERO = 81
_AT_FUSION_PAR = 84

# Cota defensiva: el camino real medido más largo tiene 175 elementos de un lado, así que 500 es
# ~3x el peor caso observado. Protege de un `a[]` desmedido, no de un camino normal.
MAX_NODOS_POR_LADO = 500


@dataclass(slots=True)
class VinculoLocal:
    """Fila local que corresponde a un nodo del camino, si se pudo vincular sin red."""

    tabla: str
    n_id: int
    nombre: Optional[str]
    vigente: bool
    coincide_por: str  # N_ID | VERSION_ID


@dataclass(slots=True)
class NodoCamino:
    """Un elemento del recorrido, en su posición dentro del lado."""

    orden: int
    lado: str
    id_cromo: int
    clase: Optional[int]
    tipo: str
    nombre: Optional[str] = None
    repetido: bool = False
    # Contexto del pelo (`father` = tubo, `gfather` = cable, ambos ya resueltos por Cromo)
    numero_pelo: Optional[str] = None
    orden_pelo: Optional[str] = None
    color_pelo: Optional[str] = None
    tubo_id: Optional[int] = None
    tubo_color: Optional[str] = None
    tubo_orden: Optional[str] = None
    cable_id: Optional[int] = None
    cable_nombre: Optional[str] = None
    cable_capacidad: Optional[str] = None
    distancia_geo_m: Optional[float] = None
    distancia_real_m: Optional[float] = None
    # Contexto del conector de ODF (`father` = patchera, `gfather` = ODF)
    conector_numero: Optional[str] = None
    patchera_id: Optional[int] = None
    patchera_nombre: Optional[str] = None
    odf_id: Optional[int] = None
    odf_nombre: Optional[str] = None
    servicio_at62: Optional[str] = None
    vinculo_local: Optional[VinculoLocal] = None


@dataclass(slots=True)
class OdfDelCamino:
    """ODF descubierta en un extremo del camino. Es la candidata a asociar al Servicio."""

    odf_id: int
    nombre: Optional[str]
    lado: str
    conector_numero: Optional[str]
    patchera_nombre: Optional[str]
    servicio_at62: Optional[str]
    es_extremo: bool
    vinculo_local: Optional[VinculoLocal] = None


@dataclass(slots=True)
class EstadisticasCamino:
    """Resumen del camino. Calca el panel "Estadísticas" que muestra la propia web de Cromo,
    salvo la atenuación total: Cromo no la publica por API (verificado sobre los 883 nodos de un
    camino real) y no se fabrica acá — ver docs/decisiones.md."""

    nodos: int = 0
    pelos: int = 0
    fusiones: int = 0
    conectores: int = 0
    cables: int = 0
    odfs: int = 0
    no_resueltos: int = 0
    longitud_geo_m: float = 0.0
    longitud_optica_m: float = 0.0


@dataclass(slots=True)
class DiscrepanciaAt62:
    """Comparación entre el servicio que declara Cromo (`at.62`, sólo disponible vía `/path`) y
    el que extrae el regex sobre el texto libre `at.61` (lo único que tiene la ingesta)."""

    at62: Optional[str]
    at61: Optional[str]
    numero_regex: Optional[str]
    veredicto: str  # COINCIDE | DIFIERE | SOLO_AT62 | SOLO_REGEX | SIN_DATO | AT62_NO_PLAUSIBLE


@dataclass(slots=True)
class CaminoOptico:
    """Resultado de resolver un camino. Nunca se persiste: se descarta al responder el request."""

    estado: str
    pelo_n_id: Optional[int] = None
    motivo: Optional[str] = None
    id_pedido: Optional[int] = None
    id_raiz: Optional[int] = None
    raiz_es_mismo_id: bool = False
    servicio_at62: Optional[str] = None
    servicio_at61: Optional[str] = None
    numero_pelo: Optional[str] = None
    color_pelo: Optional[str] = None
    cable_id: Optional[int] = None
    cable_nombre: Optional[str] = None
    tubo_id: Optional[int] = None
    lado_a: list[NodoCamino] = field(default_factory=list)
    lado_b: list[NodoCamino] = field(default_factory=list)
    odfs: list[OdfDelCamino] = field(default_factory=list)
    estadisticas: EstadisticasCamino = field(default_factory=EstadisticasCamino)
    discrepancia: Optional[DiscrepanciaAt62] = None
    ids_no_resueltos: list[int] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    duracion_ms: Optional[int] = None
    payload_raw: Optional[dict[str, Any]] = None


def _desenvolver_dict(payload: Any) -> dict[int, dict[str, Any]]:
    """Normaliza la respuesta de `/path` a un diccionario indexado por id entero.

    Verificado contra Cromo real (2026-09-10): la forma es `payload['dict']`, con claves de
    nivel superior `['dict', 'msg', 'st']`. Se prueban las otras tres envolturas posibles porque
    el resto del cliente sí usa `{'st', 'response'}` y un cambio de versión del proveedor no
    debería romper esto en silencio.

    Las claves JSON son strings (`"10006353"`) pero `a[]`/`b[]` traen enteros: sin normalizar a
    `int`, cualquier lookup del módulo sería una bomba de tipos.
    """
    if not isinstance(payload, Mapping):
        return {}
    respuesta = payload.get("response")
    candidatos: list[Any] = [
        payload.get("dict"),
        respuesta.get("dict") if isinstance(respuesta, Mapping) else None,
        respuesta,
        payload,
    ]
    for candidato in candidatos:
        if not isinstance(candidato, Mapping):
            continue
        numericas = {
            int(clave): valor
            for clave, valor in candidato.items()
            if str(clave).lstrip("-").isdigit() and isinstance(valor, Mapping)
        }
        if numericas:
            return numericas
    return {}


def _localizar_raiz(
    dic: dict[int, dict[str, Any]], id_pedido: int
) -> tuple[Optional[int], Optional[dict[str, Any]], bool]:
    """Ubica el pelo consultado dentro del `dict`, devolviendo `(id, nodo, es_el_id_pedido)`.

    Medido real: `/path` acepta el `n_id` de linaje y devuelve la raíz bajo ese mismo id. El
    camino alternativo —buscar el único nodo que trae `a[]` y `b[]` a la vez, que según el manual
    es exclusivo de los pelos solicitados— queda como instrumentación: si algún día Cromo
    respondiera en ids de versión, se detecta y se reporta en vez de fallar.
    """
    if id_pedido in dic:
        return id_pedido, dic[id_pedido], True

    con_ambos_lados = [
        oid for oid, nodo in dic.items() if nodo.get("a") is not None and nodo.get("b") is not None
    ]
    if len(con_ambos_lados) == 1:
        id_raiz = con_ambos_lados[0]
        logger.warning(
            "action=cromo_camino evento=raiz_con_otro_id id_pedido=%s id_raiz=%s", id_pedido, id_raiz
        )
        return id_raiz, dic[id_raiz], False
    return None, None, False


def _tipo_de_clase(clase: Optional[int], catalogo: Mapping[int, str]) -> str:
    if clase is None:
        return TIPO_CLASE_DESCONOCIDA
    return catalogo.get(clase) or _CLASES_FALLBACK.get(clase) or f"CLASE_{clase}"


def _a_float(valor: Optional[str]) -> Optional[float]:
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _completar_contexto_pelo(nodo: NodoCamino, crudo: Mapping[str, Any], dic: Mapping[int, Any]) -> None:
    """Un pelo del camino trae su tubo en `father` y su cable en `gfather`, ya resueltos por
    Cromo dentro del mismo `dict` — de ahí salen el color de tubo, el nombre del cable y las
    distancias que necesita el tracking, sin una sola llamada extra."""
    nodo.numero_pelo = atributo(crudo, _AT_PELO_NUMERO)
    nodo.orden_pelo = atributo(crudo, _AT_PELO_ORDEN)
    nodo.color_pelo = atributo(crudo, _AT_PELO_COLOR)
    nodo.nombre = nodo.nombre or nodo.numero_pelo

    tubo_id = crudo.get("father")
    tubo = dic.get(tubo_id) if tubo_id else None
    if tubo is not None:
        nodo.tubo_id = tubo_id
        nodo.tubo_color = atributo(tubo, _AT_TUBO_COLOR) or atributo(tubo, _AT_TUBO_NOMBRE)
        nodo.tubo_orden = atributo(tubo, _AT_TUBO_ORDEN)

    cable_id = crudo.get("gfather")
    cable = dic.get(cable_id) if cable_id else None
    if cable is not None:
        nodo.cable_id = cable_id
        nodo.cable_nombre = atributo(cable, _AT_NOMBRE_CABLE) or atributo(cable, _AT_NOMBRE_GENERICO)
        nodo.cable_capacidad = atributo(cable, _AT_CAPACIDAD)
        nodo.distancia_geo_m = _a_float(atributo(cable, _AT_DISTANCIA_GEO))
        nodo.distancia_real_m = _a_float(atributo(cable, _AT_DISTANCIA_REAL))


def _completar_contexto_conector(
    nodo: NodoCamino, crudo: Mapping[str, Any], dic: Mapping[int, Any]
) -> None:
    """Un conector de patchera (136) trae `father` = patchera (135) y `gfather` = la ODF (69).

    Hallazgo real (2026-09-10) que hace viable proponer una ODF desde el camino: la cadena
    conector → patchera → ODF se resuelve dentro del mismo payload, y `at.79` de la patchera es
    exactamente el identificador de terminal que usan los trackings legacy (`O-1249382-1`).
    """
    nodo.conector_numero = atributo(crudo, _AT_CONECTOR_NUMERO)
    nodo.servicio_at62 = atributo(crudo, _AT_SERVICIO_NUMERO)

    patchera_id = crudo.get("father")
    patchera = dic.get(patchera_id) if patchera_id else None
    if patchera is not None:
        nodo.patchera_id = patchera_id
        nodo.patchera_nombre = atributo(patchera, _AT_PATCHERA_NOMBRE) or atributo(
            patchera, _AT_NOMBRE_GENERICO
        )

    odf_id = crudo.get("gfather")
    odf = dic.get(odf_id) if odf_id else None
    if odf is not None:
        nodo.odf_id = odf_id
        nodo.odf_nombre = atributo(odf, _AT_NOMBRE_GENERICO)
    nodo.nombre = nodo.nombre or nodo.patchera_nombre


def _construir_lado(
    dic: dict[int, dict[str, Any]],
    secuencia: Optional[Iterable[Any]],
    lado: str,
    catalogo: Mapping[int, str],
    *,
    max_nodos: int = MAX_NODOS_POR_LADO,
) -> tuple[list[NodoCamino], list[int]]:
    """Convierte un `a[]`/`b[]` en nodos ordenados, resolviendo el contexto de cada uno.

    Medido real: `a[]`/`b[]` sólo traen pelos (130), fusiones (132) y conectores de patchera
    (136); los cables, botellas y ODFs viven en el `dict` pero no en la secuencia, y se alcanzan
    por `father`/`gfather` de cada elemento. No recorremos el grafo nosotros: Cromo ya devolvió
    la secuencia resuelta, así que no hay recursión que pueda ciclar.
    """
    nodos: list[NodoCamino] = []
    no_resueltos: list[int] = []
    vistos: set[int] = set()

    for orden, id_crudo in enumerate(secuencia or []):
        if orden >= max_nodos:
            break
        try:
            id_cromo = int(id_crudo)
        except (TypeError, ValueError):
            continue

        crudo = dic.get(id_cromo)
        if crudo is None:
            # Se conserva la posición a propósito: dice DÓNDE se rompió el camino.
            nodos.append(
                NodoCamino(orden=orden, lado=lado, id_cromo=id_cromo, clase=None, tipo=TIPO_NO_RESUELTO)
            )
            no_resueltos.append(id_cromo)
            continue

        clase = crudo.get("class")
        nodo = NodoCamino(
            orden=orden,
            lado=lado,
            id_cromo=id_cromo,
            clase=clase,
            tipo=_tipo_de_clase(clase, catalogo),
            nombre=crudo.get("name"),
            repetido=id_cromo in vistos,
        )
        vistos.add(id_cromo)

        if clase == _CLASE_PELO:
            _completar_contexto_pelo(nodo, crudo, dic)
        elif clase == _CLASE_CONECTOR:
            _completar_contexto_conector(nodo, crudo, dic)
        elif clase == _CLASE_FUSION:
            nodo.nombre = atributo(crudo, _AT_FUSION_PAR) or nodo.nombre
        elif clase in _CLASES_CABLE:
            nodo.cable_id = id_cromo
            nodo.cable_nombre = atributo(crudo, _AT_NOMBRE_CABLE) or atributo(crudo, _AT_NOMBRE_GENERICO)
            nodo.distancia_geo_m = _a_float(atributo(crudo, _AT_DISTANCIA_GEO))
            nodo.distancia_real_m = _a_float(atributo(crudo, _AT_DISTANCIA_REAL))
        elif nodo.nombre is None:
            nodo.nombre = atributo(crudo, _AT_NOMBRE_GENERICO)

        nodos.append(nodo)

    return nodos, no_resueltos


def calcular_estadisticas(
    lado_a: list[NodoCamino], lado_b: list[NodoCamino]
) -> EstadisticasCamino:
    """Resumen del camino, contando cada cable una sola vez para las longitudes.

    Un id repetido en la secuencia no vuelve a sumar metros: duplicaría la longitud de un mismo
    cable físico.
    """
    estadisticas = EstadisticasCamino()
    cables_contados: set[int] = set()
    odfs: set[int] = set()

    for nodo in list(lado_a) + list(lado_b):
        estadisticas.nodos += 1
        if nodo.tipo == TIPO_PELO:
            estadisticas.pelos += 1
        elif nodo.tipo == TIPO_FUSION:
            estadisticas.fusiones += 1
        elif nodo.tipo == TIPO_CONECTOR_ODF:
            estadisticas.conectores += 1
        elif nodo.tipo == TIPO_NO_RESUELTO:
            estadisticas.no_resueltos += 1

        if nodo.odf_id:
            odfs.add(nodo.odf_id)

        if nodo.cable_id and nodo.cable_id not in cables_contados:
            cables_contados.add(nodo.cable_id)
            estadisticas.longitud_geo_m += nodo.distancia_geo_m or 0.0
            estadisticas.longitud_optica_m += nodo.distancia_real_m or 0.0

    estadisticas.cables = len(cables_contados)
    estadisticas.odfs = len(odfs)
    return estadisticas


def odfs_del_camino(lado_a: list[NodoCamino], lado_b: list[NodoCamino]) -> list[OdfDelCamino]:
    """ODFs descubiertas en el camino, sin ninguna llamada extra: salen del `gfather` de cada
    conector de patchera. Se marca `es_extremo` cuando el conector es el último nodo de su lado,
    que es el caso normal (los dos lados de un camino real terminan en un conector)."""
    encontradas: dict[int, OdfDelCamino] = {}

    for nodos in (lado_a, lado_b):
        ultimo = nodos[-1].id_cromo if nodos else None
        for nodo in nodos:
            if nodo.tipo != TIPO_CONECTOR_ODF or not nodo.odf_id:
                continue
            if nodo.odf_id in encontradas:
                continue
            encontradas[nodo.odf_id] = OdfDelCamino(
                odf_id=nodo.odf_id,
                nombre=nodo.odf_nombre,
                lado=nodo.lado,
                conector_numero=nodo.conector_numero,
                patchera_nombre=nodo.patchera_nombre,
                servicio_at62=nodo.servicio_at62,
                es_extremo=nodo.id_cromo == ultimo,
                vinculo_local=nodo.vinculo_local,
            )
    return list(encontradas.values())


def comparar_at62_vs_regex(at62: Optional[str], at61: Optional[str]) -> DiscrepanciaAt62:
    """Compara el servicio que declara Cromo con el que extrae el regex sobre el texto libre.

    Función PURA y único lugar donde vive esta regla: la usan tanto la lectura (para mostrar la
    discrepancia) como cualquier escritura futura de reconciliación. No decide nada de flujo ni
    escribe en la base — v1 sólo informa.

    `at.62` es el único dato limpio de servicio de un pelo y **sólo** llega por `/path`
    (verificado real); `at.61` es texto libre y deja el 96,6% de los pelos sin número extraído.
    """
    numero_regex, _ = parsear_servicio(at61)

    if at62 and not es_numero_servicio_plausible(at62):
        veredicto = "AT62_NO_PLAUSIBLE"
    elif at62 and numero_regex:
        veredicto = "COINCIDE" if at62 == numero_regex else "DIFIERE"
    elif at62:
        veredicto = "SOLO_AT62"
    elif numero_regex:
        veredicto = "SOLO_REGEX"
    else:
        veredicto = "SIN_DATO"

    return DiscrepanciaAt62(at62=at62, at61=at61, numero_regex=numero_regex, veredicto=veredicto)


__all__ = [
    "ESTADO_OK",
    "ESTADO_SIN_CAMINO",
    "ESTADO_SIN_SEMILLA",
    "MAX_NODOS_POR_LADO",
    "TIPO_CLASE_DESCONOCIDA",
    "TIPO_CONECTOR_ODF",
    "TIPO_FUSION",
    "TIPO_NO_RESUELTO",
    "TIPO_PELO",
    "CaminoOptico",
    "DiscrepanciaAt62",
    "EstadisticasCamino",
    "NodoCamino",
    "OdfDelCamino",
    "VinculoLocal",
    "calcular_estadisticas",
    "comparar_at62_vs_regex",
    "odfs_del_camino",
]
