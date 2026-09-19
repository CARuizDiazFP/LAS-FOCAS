# Nombre de archivo: camino_optico_service.py
# Ubicación de archivo: core/services/cromo/camino_optico_service.py
# Descripción: Resolución del camino óptico de un pelo de FO desde `/network/fo/{id}/path` de Cromo, sin persistir nada

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.client import CromoClient
from core.services.cromo.parser import atributo, es_numero_servicio_plausible, parsear_servicio
from core.services.cromo.servicios_sin_odf import IDENTIDADES_DEL_SERVICIO_SQL

logger = logging.getLogger(__name__)

ESTADO_OK = "OK"
ESTADO_SIN_SEMILLA = "SIN_SEMILLA"
ESTADO_SIN_CAMINO = "SIN_CAMINO"

TIPO_PELO = "PELO"
TIPO_FUSION = "FUSION"
TIPO_CONECTOR_ODF = "CONECTOR_ODF"
TIPO_NO_RESUELTO = "NO_RESUELTO"
TIPO_CLASE_DESCONOCIDA = "CLASE_DESCONOCIDA"
# Red de acceso PON. Diagnóstico real 2026-09-17 (ver docs/decisiones.md): el camino sembrado desde
# un pelo del lado de red **se corta en el splitter**; estas clases aparecen sólo sembrando desde
# una SALIDA del splitter hacia el cliente, que es la regla operativa que aportó el usuario.
TIPO_SPLITTER = "SPLITTER"
TIPO_PUERTO_SPLITTER = "PUERTO_SPLITTER"
TIPO_CAJA_PON = "CAJA_PON"
TIPO_ROSETA = "ROSETA"
TIPO_CABLE_BAJADA = "CABLE_BAJADA"
TIPO_NODO = "NODO"
TIPO_FUSION_ODF = "FUSION_ODF"

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
    # Red de acceso PON. Desde 2026-09-19 estas clases SÍ se ingieren (modos acotados propios), así
    # que el catálogo de la base las resuelve; esto queda como red de seguridad.
    #
    # Las cajas PON son SIETE, no dos: además de la 84 y la 137 existen 126, 127, 138, 139 y 140,
    # que no estaban en ninguna lista y el diagrama dibujaba como "CLASE_139". Suman 13.482 objetos.
    #
    # La 85 (Roseta) sigue sin observarse en ningún camino real —el recorrido termina en la caja
    # PON— pero su colección existe y tiene 17.348 objetos. Se mapea igual: que no aparezca en un
    # `/path` no es razón para no saber qué es si aparece.
    66: TIPO_CABLE_BAJADA,
    84: TIPO_CAJA_PON,
    85: TIPO_ROSETA,
    86: TIPO_NODO,
    126: TIPO_CAJA_PON,
    127: TIPO_CAJA_PON,
    133: TIPO_SPLITTER,
    134: TIPO_PUERTO_SPLITTER,
    137: TIPO_CAJA_PON,
    138: TIPO_CAJA_PON,
    139: TIPO_CAJA_PON,
    140: TIPO_CAJA_PON,
    141: TIPO_FUSION_ODF,
}

# Cables de bajada (drop). Se muestran con nombre y metraje como cualquier cable, pero NO entran en
# `_CLASES_CABLE`: esa constante define qué se puede reingerir por `extraer_tubos_y_pelos`.
#
# Corrección (2026-09-19): la razón que decía este comentario —"un cable de bajada no tiene esa
# estructura de tubos/pelos"— es falsa. Medido contra Cromo, la clase 66 trae `inner` con 1 tubo y
# 1 pelo, y `tp` con dos extremos, igual que un cable de FO. La razón real para dejarla afuera es
# otra y sigue valiendo: sus extremos son cajas PON y rosetas, no botellas, así que arrastrarla a
# la reingesta dirigida y al conteo de `cables` mezclaría dos dominios.
_CLASES_CABLE_BAJADA = frozenset({66})
# Las siete clases de caja PON, medidas contra Cromo el 2026-09-19. Gobierna qué nodos reciben el
# enriquecimiento de nombre/tendido en `_construir_lado` y qué cuenta `estadisticas.cajas_pon`.
_CLASES_CAJA_PON = frozenset({84, 126, 127, 137, 138, 139, 140})
_CLASE_SPLITTER = 133
_CLASE_PUERTO_SPLITTER = 134
_CLASE_NODO = 86
_CLASE_FUSION_ODF = 141

_CLASES_CABLE = frozenset({51, 52})
# Alias público: la reingesta dirigida necesita el mismo criterio de "qué es un cable".
# La 52 es cable de un tercero (ej. Arsat): no la barre la ingesta, pero es un cable real
# del camino y sus pelos son tan legítimos como los de un cable propio.
CLASES_CABLE = _CLASES_CABLE
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
_AT_TENDIDO = 20              # "Aereo"/"Subsuelo", en cable de bajada y caja PON
_AT_CABLE_BAJADA_TIPO = 27    # literalmente "Bajada" en los cables de bajada
_AT_SPLITTER_NOMBRE = 78      # "S-1243457-3", "SPLITTER 1"
_AT_PUERTO_NOMBRE = 80        # "S6", "E1"
_AT_SPLITTER_RATIO = 83       # "1x8", "1x4" — Cromo PUBLICA el ratio, no hay que inferirlo
_AT_PUERTO_SENTIDO = 82       # "ENTRADA"/"SALIDA"
_AT_FUSION_TIPO = 85          # "FUSION"

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
    # Contexto de la fusión (`father` = la botella donde está hecho el empalme, y `tp[]` los dos
    # pelos que une). La botella es lo que el tracking legacy imprime como `Empalme <id>: <nombre>`.
    botella_id: Optional[int] = None
    botella_nombre: Optional[str] = None
    pelos_fusionados: list[int] = field(default_factory=list)
    # Contexto del conector de ODF (`father` = patchera, `gfather` = ODF, `tp[0]` el pelo)
    pelo_conectado: Optional[int] = None
    conector_numero: Optional[str] = None
    patchera_id: Optional[int] = None
    patchera_nombre: Optional[str] = None
    odf_id: Optional[int] = None
    odf_nombre: Optional[str] = None
    servicio_at62: Optional[str] = None
    # Contexto de la red de acceso PON (clases 133/134/84/137/66). `splitter_ratio` sale de `at.83`
    # de Cromo: el ratio está PUBLICADO, no hay que inferirlo por fan-out como hace `empalmes.py`.
    splitter_ratio: Optional[str] = None
    splitter_nombre: Optional[str] = None
    splitter_id: Optional[int] = None
    puerto_nombre: Optional[str] = None
    puerto_sentido: Optional[str] = None  # ENTRADA | SALIDA
    splitter_salidas: Optional[int] = None
    tendido: Optional[str] = None  # "Aereo" / "Subsuelo" / "Canalizado"
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
    splitters: int = 0
    cajas_pon: int = 0
    cables_bajada: int = 0
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
    # El pelo consultado, con su cable y tubo resueltos. No pertenece a ningún lado (`a[]`/`b[]`
    # nacen en él) pero su cable es un tramo del camino y su nombre es la cabecera del tracking.
    raiz: Optional[NodoCamino] = None
    lado_a: list[NodoCamino] = field(default_factory=list)
    lado_b: list[NodoCamino] = field(default_factory=list)
    odfs: list[OdfDelCamino] = field(default_factory=list)
    estadisticas: EstadisticasCamino = field(default_factory=EstadisticasCamino)
    consistencia: Optional[ConsistenciaCamino] = None
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


def _ids_de_tp(crudo: Mapping[str, Any]) -> list[int]:
    """Los `id_to` de `tp[]`, que es donde viajan las conexiones de una fusión o un conector."""
    ids: list[int] = []
    for punto in crudo.get("tp") or []:
        destino = punto.get("id_to") if isinstance(punto, Mapping) else None
        if destino:
            ids.append(int(destino))
    return ids


def _completar_contexto_fusion(
    nodo: NodoCamino, crudo: Mapping[str, Any], dic: Mapping[int, Any]
) -> None:
    """Una fusión (132) trae `father` = **la botella** donde está hecho el empalme y `tp[]` los dos
    pelos que une.

    Verificado real (2026-09-10): 96 de 96 fusiones de un camino traen padre, y su clase es
    siempre de botella (68/121/122/125). Ese id es exactamente lo que el tracking legacy imprime
    como `Empalme <id>: <nombre de la botella>`.
    """
    nodo.nombre = atributo(crudo, _AT_FUSION_PAR) or nodo.nombre
    nodo.pelos_fusionados = _ids_de_tp(crudo)

    botella_id = crudo.get("father")
    botella = dic.get(botella_id) if botella_id else None
    if botella is not None:
        nodo.botella_id = botella_id
        nodo.botella_nombre = atributo(botella, _AT_NOMBRE_GENERICO) or botella.get("name")


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
    pelos = _ids_de_tp(crudo)
    nodo.pelo_conectado = pelos[0] if pelos else None

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


def _completar_contexto_cable_bajada(nodo: NodoCamino, crudo: Mapping[str, Any]) -> None:
    """Cable de bajada (drop, clase 66): el tramo final hacia el domicilio del cliente.

    Comparte con el cable común el atributo de nombre (`at.26`) y el de distancia (`at.23`), así
    que se muestra igual. Lo que lo distingue es `at.27 = "Bajada"` y el tipo de tendido
    (`at.20`: "Aereo", "Subsuelo"). No se cuenta como cable en las estadísticas: tiene su propio
    contador, porque mezclarlo con la troncal distorsionaría la longitud óptica del backbone.
    """
    nodo.cable_nombre = atributo(crudo, _AT_NOMBRE_CABLE) or atributo(crudo, _AT_NOMBRE_GENERICO)
    nodo.nombre = nodo.nombre or nodo.cable_nombre
    nodo.distancia_geo_m = _a_float(atributo(crudo, _AT_DISTANCIA_GEO))
    nodo.distancia_real_m = _a_float(atributo(crudo, _AT_DISTANCIA_REAL))
    nodo.tendido = atributo(crudo, _AT_TENDIDO)


def _completar_contexto_splitter(nodo: NodoCamino, crudo: Mapping[str, Any]) -> None:
    """Splitter (clase 133). **Cromo publica el ratio** en `at.83` ("1x8", "1x4").

    Esto es dato, no inferencia: `core/services/cromo/empalmes.py` deduce hoy el ratio por fan-out
    de fusiones, con los falsos "Splitter 1-1"/"Splitter 1-3" ya documentados. Cuando un camino
    pasa por el splitter, acá el ratio viene dado por el propio Cromo.
    """
    nodo.splitter_id = nodo.id_cromo
    nodo.splitter_nombre = atributo(crudo, _AT_SPLITTER_NOMBRE) or atributo(crudo, _AT_NOMBRE_GENERICO)
    nodo.splitter_ratio = atributo(crudo, _AT_SPLITTER_RATIO)
    nodo.nombre = nodo.nombre or nodo.splitter_nombre


def _completar_contexto_puerto_splitter(
    nodo: NodoCamino, crudo: Mapping[str, Any], dic: Mapping[int, Any]
) -> None:
    """Puerto de splitter (clase 134): `father` es el splitter y `gfather` su contenedor.

    `splitter_a` (cuando viene) trae la topología explícita del splitter —`c_in` y `c_out`— así
    que el fan-out real no hay que contarlo: está publicado. Sembrar el camino desde uno de esos
    `c_out` es lo que revela la red de acceso (caja PON y cables de bajada); desde el lado de red,
    el recorrido se corta acá.
    """
    nodo.puerto_nombre = atributo(crudo, _AT_PUERTO_NOMBRE)
    nodo.puerto_sentido = atributo(crudo, _AT_PUERTO_SENTIDO)
    nodo.nombre = nodo.nombre or nodo.puerto_nombre

    splitter_id = crudo.get("father")
    splitter = dic.get(splitter_id) if splitter_id else None
    if splitter is not None:
        nodo.splitter_id = splitter_id
        nodo.splitter_nombre = atributo(splitter, _AT_SPLITTER_NOMBRE) or atributo(
            splitter, _AT_NOMBRE_GENERICO
        )
        nodo.splitter_ratio = atributo(splitter, _AT_SPLITTER_RATIO)

    topologia = crudo.get("splitter_a")
    if isinstance(topologia, dict):
        salidas = topologia.get("c_out") or []
        nodo.splitter_salidas = len(salidas) or None


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
            _completar_contexto_fusion(nodo, crudo, dic)
        elif clase in _CLASES_CABLE:
            nodo.cable_id = id_cromo
            nodo.cable_nombre = atributo(crudo, _AT_NOMBRE_CABLE) or atributo(crudo, _AT_NOMBRE_GENERICO)
            nodo.distancia_geo_m = _a_float(atributo(crudo, _AT_DISTANCIA_GEO))
            nodo.distancia_real_m = _a_float(atributo(crudo, _AT_DISTANCIA_REAL))
        elif clase in _CLASES_CABLE_BAJADA:
            _completar_contexto_cable_bajada(nodo, crudo)
        elif clase == _CLASE_SPLITTER:
            _completar_contexto_splitter(nodo, crudo)
        elif clase == _CLASE_PUERTO_SPLITTER:
            _completar_contexto_puerto_splitter(nodo, crudo, dic)
        elif clase in _CLASES_CAJA_PON or clase == _CLASE_NODO:
            nodo.nombre = atributo(crudo, _AT_NOMBRE_GENERICO) or nodo.nombre
            nodo.tendido = atributo(crudo, _AT_TENDIDO)
        elif clase == _CLASE_FUSION_ODF:
            nodo.nombre = atributo(crudo, _AT_FUSION_PAR) or nodo.nombre
            nodo.pelos_fusionados = _ids_de_tp(crudo)
        elif nodo.nombre is None:
            nodo.nombre = atributo(crudo, _AT_NOMBRE_GENERICO)

        nodos.append(nodo)

    return nodos, no_resueltos


def calcular_estadisticas(
    lado_a: list[NodoCamino],
    lado_b: list[NodoCamino],
    raiz: Optional[NodoCamino] = None,
) -> EstadisticasCamino:
    """Resumen del camino, contando cada cable una sola vez para las longitudes.

    `raiz` es el pelo consultado y hay que pasarlo: **no está en `a[]` ni en `b[]`**, pero su
    propio cable es un tramo del camino. Encontrado comparando contra el panel de la web de
    Cromo sobre un camino real: faltaban exactamente los 295 m del cable del pelo raíz
    (72.754 m calculados vs. 73.049 m que muestra Cromo).

    Un id repetido en la secuencia no vuelve a sumar metros: duplicaría la longitud de un mismo
    cable físico.
    """
    estadisticas = EstadisticasCamino()
    cables_contados: set[int] = set()
    odfs: set[int] = set()

    for nodo in ([raiz] if raiz is not None else []) + list(lado_a) + list(lado_b):
        estadisticas.nodos += 1
        if nodo.tipo == TIPO_PELO:
            estadisticas.pelos += 1
        elif nodo.tipo == TIPO_FUSION:
            estadisticas.fusiones += 1
        elif nodo.tipo == TIPO_CONECTOR_ODF:
            estadisticas.conectores += 1
        elif nodo.tipo == TIPO_NO_RESUELTO:
            estadisticas.no_resueltos += 1
        elif nodo.tipo == TIPO_SPLITTER:
            estadisticas.splitters += 1
        elif nodo.tipo == TIPO_CAJA_PON:
            estadisticas.cajas_pon += 1
        elif nodo.tipo == TIPO_CABLE_BAJADA:
            estadisticas.cables_bajada += 1

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


# ── Auditoría: lo que declara el camino vs. lo que tenemos ingerido ─────────────────────────

REGLA_PELO_CABLE = "PELO_CABLE"
REGLA_PELO_TUBO = "PELO_TUBO"
REGLA_FUSION_BOTELLA = "FUSION_BOTELLA"
REGLA_FUSION_PELOS = "FUSION_PELOS"
REGLA_CONECTOR = "CONECTOR_PELO_ODF"

TIPO_DISCREPA = "DISCREPA"
TIPO_NO_INGERIDO = "NO_INGERIDO"

# Texto que acompaña a cada regla en la UI. Redacción deliberada: dice que el camino DIFIERE de lo
# ingerido, no que la base esté mal. El camino es un elemento vivo (cambia ante cortes) y nuestra
# ingesta es una foto anterior, así que una diferencia puede ser deriva legítima. En los dos casos
# la referencia es Cromo.
DESCRIPCION_REGLAS: dict[str, str] = {
    REGLA_PELO_CABLE: "Cable declarado para cada pelo del camino",
    REGLA_PELO_TUBO: "Tubo declarado para cada pelo del camino",
    REGLA_FUSION_BOTELLA: "Botella donde el camino ubica cada fusión",
    REGLA_FUSION_PELOS: "Par de pelos que une cada fusión",
    REGLA_CONECTOR: "Pelo y ODF de cada conector de patchera",
}


@dataclass(slots=True)
class InconsistenciaCamino:
    """Un elemento donde el camino y la base no dicen lo mismo, o que la base no tiene."""

    regla: str
    elemento_id: int
    tipo: str  # DISCREPA | NO_INGERIDO
    valor_path: Any = None
    valor_local: Any = None


@dataclass(slots=True)
class ResultadoRegla:
    regla: str
    descripcion: str
    total: int = 0
    coincide: int = 0
    discrepa: int = 0
    no_ingerido: int = 0


@dataclass(slots=True)
class ConsistenciaCamino:
    """Resultado de comparar el camino contra lo ingerido. Informa, no corrige nada."""

    reglas: list[ResultadoRegla] = field(default_factory=list)
    inconsistencias: list[InconsistenciaCamino] = field(default_factory=list)

    @property
    def total_discrepa(self) -> int:
        return sum(r.discrepa for r in self.reglas)

    @property
    def total_no_ingerido(self) -> int:
        return sum(r.no_ingerido for r in self.reglas)


def pares_declarados(nodos: list[NodoCamino]) -> dict[str, dict[int, Any]]:
    """Extrae, de los nodos ya construidos, las relaciones que el camino AFIRMA.

    Función pura: es la mitad testeable sin base de la auditoría. Cada regla queda como
    `{id_del_elemento: valor_que_declara_el_path}`.
    """
    pelo_cable: dict[int, Any] = {}
    pelo_tubo: dict[int, Any] = {}
    fusion_botella: dict[int, Any] = {}
    fusion_pelos: dict[int, Any] = {}
    conector: dict[int, Any] = {}

    for nodo in nodos:
        if nodo.repetido:
            continue
        if nodo.tipo == TIPO_PELO:
            if nodo.cable_id:
                pelo_cable[nodo.id_cromo] = nodo.cable_id
            if nodo.tubo_id:
                pelo_tubo[nodo.id_cromo] = nodo.tubo_id
        elif nodo.tipo == TIPO_FUSION:
            if nodo.botella_id:
                fusion_botella[nodo.id_cromo] = nodo.botella_id
            if nodo.pelos_fusionados:
                fusion_pelos[nodo.id_cromo] = sorted(nodo.pelos_fusionados)
        elif nodo.tipo == TIPO_CONECTOR_ODF:
            conector[nodo.id_cromo] = {"pelo": nodo.pelo_conectado, "odf": nodo.odf_id}

    return {
        REGLA_PELO_CABLE: pelo_cable,
        REGLA_PELO_TUBO: pelo_tubo,
        REGLA_FUSION_BOTELLA: fusion_botella,
        REGLA_FUSION_PELOS: fusion_pelos,
        REGLA_CONECTOR: conector,
    }


async def auditar_consistencia(
    sesion: AsyncSession, nodos: list[NodoCamino]
) -> ConsistenciaCamino:
    """Compara las relaciones que declara el camino contra las que tenemos ingeridas.

    Cinco reglas, **una query batcheada por regla** y cero llamadas a Cromo: se calcula con el
    mismo payload que ya se trajo. Medido sobre un camino real: 0 discrepancias en cuatro de las
    cinco reglas, 2 en `FUSION_PELOS`, y 6 elementos que Cromo conoce y la base no.

    No corrige nada ni escribe: es auditoría. Y una discrepancia no implica que la base esté mal
    —el camino es vivo y la ingesta es una foto anterior— pero la referencia es Cromo.
    """
    declarado = pares_declarados(nodos)
    consistencia = ConsistenciaCamino()

    async def _comparar_columna(regla: str, tabla: str, columna: str) -> None:
        pares = declarado[regla]
        resultado = ResultadoRegla(regla=regla, descripcion=DESCRIPCION_REGLAS[regla], total=len(pares))
        if pares:
            filas = dict(
                (
                    await sesion.execute(
                        text(f"SELECT n_id, {columna} FROM app.{tabla} WHERE n_id = ANY(:ids)"),
                        {"ids": sorted(pares)},
                    )
                ).all()
            )
            for elemento, valor_path in pares.items():
                if elemento not in filas:
                    resultado.no_ingerido += 1
                    consistencia.inconsistencias.append(
                        InconsistenciaCamino(
                            regla=regla, elemento_id=elemento, tipo=TIPO_NO_INGERIDO, valor_path=valor_path
                        )
                    )
                elif filas[elemento] == valor_path:
                    resultado.coincide += 1
                else:
                    resultado.discrepa += 1
                    consistencia.inconsistencias.append(
                        InconsistenciaCamino(
                            regla=regla,
                            elemento_id=elemento,
                            tipo=TIPO_DISCREPA,
                            valor_path=valor_path,
                            valor_local=filas[elemento],
                        )
                    )
        consistencia.reglas.append(resultado)

    await _comparar_columna(REGLA_PELO_CABLE, "cromo_pelos", "cable_n_id")
    await _comparar_columna(REGLA_PELO_TUBO, "cromo_pelos", "tubo_n_id")
    await _comparar_columna(REGLA_FUSION_BOTELLA, "cromo_fusiones", "botella_n_id")

    # Los pelos de una fusión viven en dos columnas y el orden A/B es arbitrario de los dos lados,
    # así que se comparan como conjunto.
    pares_fusion = declarado[REGLA_FUSION_PELOS]
    resultado = ResultadoRegla(
        regla=REGLA_FUSION_PELOS, descripcion=DESCRIPCION_REGLAS[REGLA_FUSION_PELOS], total=len(pares_fusion)
    )
    if pares_fusion:
        filas = {
            fila[0]: sorted(p for p in (fila[1], fila[2]) if p)
            for fila in (
                await sesion.execute(
                    text(
                        "SELECT n_id, pelo_a_n_id, pelo_b_n_id FROM app.cromo_fusiones "
                        "WHERE n_id = ANY(:ids)"
                    ),
                    {"ids": sorted(pares_fusion)},
                )
            ).all()
        }
        for elemento, pelos_path in pares_fusion.items():
            if elemento not in filas:
                resultado.no_ingerido += 1
                consistencia.inconsistencias.append(
                    InconsistenciaCamino(
                        regla=REGLA_FUSION_PELOS,
                        elemento_id=elemento,
                        tipo=TIPO_NO_INGERIDO,
                        valor_path=pelos_path,
                    )
                )
            elif filas[elemento] == list(pelos_path):
                resultado.coincide += 1
            else:
                resultado.discrepa += 1
                consistencia.inconsistencias.append(
                    InconsistenciaCamino(
                        regla=REGLA_FUSION_PELOS,
                        elemento_id=elemento,
                        tipo=TIPO_DISCREPA,
                        valor_path=pelos_path,
                        valor_local=filas[elemento],
                    )
                )
    consistencia.reglas.append(resultado)

    # El conector se compara por sus dos vínculos a la vez: pelo y ODF.
    pares_conector = declarado[REGLA_CONECTOR]
    resultado = ResultadoRegla(
        regla=REGLA_CONECTOR, descripcion=DESCRIPCION_REGLAS[REGLA_CONECTOR], total=len(pares_conector)
    )
    if pares_conector:
        filas = {
            fila[0]: {"pelo": fila[1], "odf": fila[2]}
            for fila in (
                await sesion.execute(
                    text(
                        "SELECT n_id, pelo_n_id, odf_n_id FROM app.cromo_odf_conectores "
                        "WHERE n_id = ANY(:ids)"
                    ),
                    {"ids": sorted(pares_conector)},
                )
            ).all()
        }
        for elemento, vinculos_path in pares_conector.items():
            if elemento not in filas:
                resultado.no_ingerido += 1
                consistencia.inconsistencias.append(
                    InconsistenciaCamino(
                        regla=REGLA_CONECTOR,
                        elemento_id=elemento,
                        tipo=TIPO_NO_INGERIDO,
                        valor_path=vinculos_path,
                    )
                )
            elif filas[elemento] == vinculos_path:
                resultado.coincide += 1
            else:
                resultado.discrepa += 1
                consistencia.inconsistencias.append(
                    InconsistenciaCamino(
                        regla=REGLA_CONECTOR,
                        elemento_id=elemento,
                        tipo=TIPO_DISCREPA,
                        valor_path=vinculos_path,
                        valor_local=filas[elemento],
                    )
                )
    consistencia.reglas.append(resultado)

    return consistencia


# ── Semillas: de un Servicio a los pelos con los que se puede pedir el camino ───────────────

# Ranking deliberado, ver docstring de `listar_pelos_semilla`. `tiene_conector_odf` ASC pone
# primero el pelo cuya ODF NO conocemos, que es justamente el que aporta información nueva
# (medido: 124.371 de 132.962 pelos matcheados no tienen conector).
_SQL_PELOS_SEMILLA = text(
    f"""
    SELECT DISTINCT ON (m.pelo_n_id)
           m.pelo_n_id,
           m.servicio_numero,
           m.metodo,
           m.confianza,
           p.numero_pelo,
           p.color,
           p.cable_n_id,
           cab.nombre AS cable_nombre,
           EXISTS (
               SELECT 1 FROM app.cromo_odf_conectores c WHERE c.pelo_n_id = m.pelo_n_id
           ) AS tiene_conector_odf,
           CASE WHEN m.servicio_numero = s.servicio_id            THEN 0
                WHEN m.servicio_numero = s.numero_primer_servicio THEN 1
                ELSE 2 END AS prioridad_identidad,
           p.servicio_raw
    FROM app.servicios s
    JOIN app.cromo_servicio_match m ON ({IDENTIDADES_DEL_SERVICIO_SQL})
    JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id AND p.vigente = true
    LEFT JOIN app.cromo_cables cab ON cab.n_id = p.cable_n_id
    WHERE s.id = :servicio_id
    ORDER BY m.pelo_n_id,
             prioridad_identidad,
             tiene_conector_odf,
             m.confianza DESC NULLS LAST
    """
)

_SQL_CATALOGO_CLASES = text(
    "SELECT clase, entidad FROM app.cromo_clases WHERE clase = ANY(:clases)"
)

# Vinculación local sin red: primero por `n_id` (la PK), y sólo con los que no resolvieron, por
# `version_id`. Las tres tablas que tienen `version_id` son las únicas donde un id de versión de
# Cromo puede resolverse localmente; `cromo_pelos`/`cromo_tubos`/`cromo_fusiones` sólo tienen
# `n_id`. Resolver por red con `id_dual_resolver` costaría 1 request por nodo (100-600 por
# camino): inviable frente a los ~12 s que ya cuesta el propio `/path`.
#
# La columna de nombre NO es uniforme entre tablas (verificado contra el esquema real: los
# pelos tienen `numero_pelo`, los tubos `nombre_color`, las fusiones `nombre_par`) y sólo las
# tres primeras tienen `version_id`. Un smoke real contra la base lo encontró: asumir `nombre`
# en todas revienta con `column "nombre" does not exist`.
_TABLAS_VINCULABLES: tuple[tuple[str, str, str, bool], ...] = (
    ("cromo_odfs", "ODF", "nombre", True),
    ("cromo_cables", "CABLE", "nombre", True),
    ("cromo_botellas", "BOTELLA", "nombre", True),
    ("cromo_pelos", TIPO_PELO, "numero_pelo", False),
    ("cromo_tubos", "TUBO", "nombre_color", False),
    ("cromo_fusiones", TIPO_FUSION, "nombre_par", False),
    # Red de acceso PON (2026-09-19). Hasta ahora estos nodos llegaban siempre con
    # `vinculo_local=None`, no porque fallara la resolución sino porque no había fila local que
    # resolver. Con los modos de ingesta propios, ahora la hay.
    #
    # Cajas PON y rosetas comparten tabla (`cromo_pon_elementos`) y por eso aparecen dos veces
    # apuntando a ella: los `n_id` son disjuntos y cada entrada resuelve su propio tipo de nodo, así
    # que no hace falta filtrar por clase en la consulta.
    ("cromo_pon_elementos", TIPO_CAJA_PON, "nombre", True),
    ("cromo_pon_elementos", TIPO_ROSETA, "nombre", True),
    # `cromo_cables` aparece dos veces por el mismo motivo: aloja los de FO (51) y los de bajada
    # (66), que son nodos de tipo distinto en el diagrama.
    ("cromo_cables", TIPO_CABLE_BAJADA, "nombre", True),
    # Splitters y puertos no tienen `version_id`: su tabla es liviana, sin versionado, así que sólo
    # se resuelven por `n_id` (la segunda pasada del vinculador no aplica).
    ("cromo_splitters", TIPO_SPLITTER, "nombre", False),
    ("cromo_splitter_puertos", TIPO_PUERTO_SPLITTER, "nombre", False),
)


@dataclass(slots=True)
class PeloSemilla:
    """Pelo de Cromo con el que se puede pedir el camino de un Servicio."""

    pelo_n_id: int
    servicio_numero: Optional[str]
    metodo: Optional[str]
    confianza: Optional[int]
    numero_pelo: Optional[str]
    color: Optional[str]
    cable_n_id: Optional[int]
    cable_nombre: Optional[str]
    tiene_conector_odf: bool
    servicio_raw: Optional[str]


async def listar_pelos_semilla(
    sesion: AsyncSession, servicio_id: int, *, limite: int = 20, priorizar_conector: bool = False
) -> list[PeloSemilla]:
    """Pelos candidatos a semilla de `/path` para un Servicio, ya rankeados. Una sola query.

    `servicio_id` es la PK de `app.servicios`. El predicado de identidades es el mismo que usa
    el gestor de Servicios sin ODF (importado, no copiado) para no divergir.

    **Dos consumidores con criterios opuestos, y por eso el flag.**

    - Por defecto (`priorizar_conector=False`) el orden pone primero el pelo cuya ODF todavía no
      conocemos: un pelo que ya tiene conector no aporta una ODF nueva. Es lo que necesita el
      gestor de Servicios sin ODF, cuyo fin es **descubrir** ODFs.
    - Con `priorizar_conector=True` se invierte ese criterio: primero los pelos que **sí** son
      posición de patchera del Servicio. Es lo que necesita la descarga de trackings, donde esos
      son los pelos reales del Servicio.

    Por qué no alcanzaba con reordenar en el consumidor: la lista viene **truncada** en `limite`.
    Medido real sobre el Servicio 93154, cuyo número matchea 227 pelos por regex —todos los del
    recorrido llevan la etiqueta del servicio en `at.61`, no sólo los extremos— pero del que sólo
    **2** son posición de ODF: con el orden de descubrimiento, esos 2 caen fuera del tope de 20 y
    el consumidor nunca llega a verlos.

    Es determinista hasta el último criterio, para que dos consultas del mismo Servicio elijan la
    misma semilla y el camino sea reproducible sin pagar dos veces la llamada a Cromo.
    """
    filas = (await sesion.execute(_SQL_PELOS_SEMILLA, {"servicio_id": servicio_id})).mappings().all()
    ordenadas = sorted(
        filas,
        key=lambda f: (
            f["prioridad_identidad"],
            (not f["tiene_conector_odf"]) if priorizar_conector else f["tiene_conector_odf"],
            -(f["confianza"] or 0),
            f["pelo_n_id"],
        ),
    )
    return [
        PeloSemilla(
            pelo_n_id=fila["pelo_n_id"],
            servicio_numero=fila["servicio_numero"],
            metodo=fila["metodo"],
            confianza=fila["confianza"],
            numero_pelo=fila["numero_pelo"],
            color=fila["color"],
            cable_n_id=fila["cable_n_id"],
            cable_nombre=fila["cable_nombre"],
            tiene_conector_odf=bool(fila["tiene_conector_odf"]),
            servicio_raw=fila["servicio_raw"],
        )
        for fila in ordenadas[:limite]
    ]


_SQL_CONTAR_SEMILLAS = text(
    f"""
    SELECT s.id, COUNT(DISTINCT m.pelo_n_id) AS pelos
    FROM app.servicios s
    JOIN app.cromo_servicio_match m ON ({IDENTIDADES_DEL_SERVICIO_SQL})
    JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id AND p.vigente = true
    WHERE s.id = ANY(:ids)
    GROUP BY s.id
    """
)


_SQL_TOTAL_SEMILLAS = text(
    f"""
    SELECT COUNT(DISTINCT m.pelo_n_id) AS pelos,
           COUNT(DISTINCT m.pelo_n_id) FILTER (
               WHERE EXISTS (
                   SELECT 1 FROM app.cromo_odf_conectores c WHERE c.pelo_n_id = m.pelo_n_id
               )
           ) AS con_conector
    FROM app.servicios s
    JOIN app.cromo_servicio_match m ON ({IDENTIDADES_DEL_SERVICIO_SQL})
    JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id AND p.vigente = true
    WHERE s.id = :servicio_id
    """
)


_SQL_PELO_PERTENECE = text(
    f"""
    SELECT 1
    FROM app.servicios s
    JOIN app.cromo_servicio_match m ON ({IDENTIDADES_DEL_SERVICIO_SQL})
    JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id AND p.vigente = true
    WHERE s.id = :servicio_id AND m.pelo_n_id = :pelo_n_id
    LIMIT 1
    """
)


async def pelo_pertenece_al_servicio(
    sesion: AsyncSession, servicio_id: int, pelo_n_id: int
) -> bool:
    """¿Este pelo es del Servicio? Consulta directa, **sin** el tope de `listar_pelos_semilla`.

    Validar la pertenencia contra la lista de semillas está mal por construcción: esa lista viene
    truncada en 20 y ordenada con un criterio (descubrir ODFs) opuesto al de la descarga. Bug real
    encontrado verificando el Servicio 93154: `/pelos?priorizar_conector=true` devolvía el pelo
    6822061 como suyo y la descarga lo rechazaba con "no pertenece al Servicio", porque caía fuera
    del tope de la otra lista. La pertenencia es un hecho del dato, no de la ventana que se listó.
    """
    fila = (
        await sesion.execute(
            _SQL_PELO_PERTENECE, {"servicio_id": servicio_id, "pelo_n_id": pelo_n_id}
        )
    ).first()
    return fila is not None


async def contar_semillas(sesion: AsyncSession, servicio_id: int) -> tuple[int, int]:
    """`(total, con_posicion_de_odf)` de pelos del Servicio, **sin** el tope de `listar_pelos_semilla`.

    La lista de semillas viene truncada, así que sin este conteo la UI no puede distinguir "este
    Servicio tiene 20 pelos" de "tiene 227 y te estoy mostrando 20". La diferencia no es cosmética:
    el número de servicio viaja en el `at.61` de **todos** los pelos del recorrido, así que el
    total es grande por diseño y lo que el operador llama "los pelos del Servicio" son los que son
    posición de ODF (2, en el Servicio 93154, contra 227 matcheados).
    """
    fila = (
        await sesion.execute(_SQL_TOTAL_SEMILLAS, {"servicio_id": servicio_id})
    ).mappings().first()
    if fila is None:
        return 0, 0
    return int(fila["pelos"] or 0), int(fila["con_conector"] or 0)


async def contar_semillas_por_servicio(
    sesion: AsyncSession, servicio_ids: list[int]
) -> dict[int, int]:
    """Cuántos pelos semilla tiene cada Servicio de una lista. UNA query para toda la página.

    Existe para que el listado del gestor pueda decidir si muestra el botón de camino sin pedir
    un request por tarjeta. Se resuelve en una pasada batcheada y **no se toca la query de
    detección de Servicios sin ODF**, que costó bajar de 23,9 s a ~150 ms: agregarle una
    subconsulta por fila era el camino fácil y el riesgoso.

    Un Servicio ausente del resultado tiene cero semillas — es el 77% del universo del gestor.
    """
    if not servicio_ids:
        return {}
    filas = (await sesion.execute(_SQL_CONTAR_SEMILLAS, {"ids": sorted(set(servicio_ids))})).all()
    return {int(servicio_id): int(pelos) for servicio_id, pelos in filas}


async def _catalogo_clases(sesion: AsyncSession, clases: set[int]) -> dict[int, str]:
    """Traduce clase → entidad con el catálogo de la base, en una sola query.

    `app.cromo_clases` es la fuente: incorporar una clase nueva ahí es un INSERT, no una
    migración ni un cambio de código.
    """
    if not clases:
        return {}
    filas = (await sesion.execute(_SQL_CATALOGO_CLASES, {"clases": sorted(clases)})).all()
    return {int(clase): entidad for clase, entidad in filas if entidad}


async def _vincular_local(sesion: AsyncSession, nodos: list[NodoCamino]) -> None:
    """Vincula cada nodo con su fila local, en dos pasadas batcheadas por tabla y CERO red.

    Muta los nodos in place. Un nodo sin vínculo no es un error: puede ser una clase que la
    ingesta no barre (84 caja PON, 66 cable bajada, 85 roseta, 52 cable de tercero) o un objeto
    que Cromo movió y la ingesta local todavía no refleja. `vigente=false` tampoco se oculta: es
    dato de auditoría.
    """
    por_tipo: dict[str, dict[int, list[NodoCamino]]] = {}
    for nodo in nodos:
        if nodo.tipo == TIPO_NO_RESUELTO:
            continue
        por_tipo.setdefault(nodo.tipo, {}).setdefault(nodo.id_cromo, []).append(nodo)

    for tabla, tipo, columna_nombre, tiene_version_id in _TABLAS_VINCULABLES:
        pendientes = por_tipo.get(tipo)
        if not pendientes:
            continue
        ids = sorted(pendientes)

        filas = (
            await sesion.execute(
                text(
                    f"SELECT n_id, {columna_nombre} AS nombre, vigente FROM app.{tabla} "
                    "WHERE n_id = ANY(:ids)"
                ),
                {"ids": ids},
            )
        ).all()
        for n_id, nombre, vigente in filas:
            for nodo in pendientes.pop(int(n_id), []):
                nodo.vinculo_local = VinculoLocal(
                    tabla=tabla, n_id=int(n_id), nombre=nombre, vigente=bool(vigente), coincide_por="N_ID"
                )

        if not pendientes or not tiene_version_id:
            continue
        filas = (
            await sesion.execute(
                text(
                    f"SELECT n_id, version_id, {columna_nombre} AS nombre, vigente "
                    f"FROM app.{tabla} WHERE version_id = ANY(:ids)"
                ),
                {"ids": sorted(pendientes)},
            )
        ).all()
        for n_id, version_id, nombre, vigente in filas:
            for nodo in pendientes.pop(int(version_id), []):
                nodo.vinculo_local = VinculoLocal(
                    tabla=tabla,
                    n_id=int(n_id),
                    nombre=nombre,
                    vigente=bool(vigente),
                    coincide_por="VERSION_ID",
                )


async def resolver_camino_de_pelo(
    cliente: CromoClient,
    sesion: AsyncSession,
    pelo_n_id: int,
    *,
    vincular_local: bool = True,
    auditar: bool = True,
    incluir_raw: bool = False,
) -> CaminoOptico:
    """Resuelve el camino óptico de un pelo. UNA llamada a Cromo, cero requests por nodo.

    Nunca persiste nada: el resultado se descarta al responder el request, igual que
    `live_lookup_service`. Cromo se consulta sólo por GET.
    """
    inicio = perf_counter()
    payload = await cliente.get_camino_optico(pelo_n_id)
    duracion_ms = int((perf_counter() - inicio) * 1000)

    dic = _desenvolver_dict(payload)
    if not dic:
        claves = sorted(payload)[:8] if isinstance(payload, Mapping) else []
        logger.warning(
            "action=cromo_camino evento=sin_dict pelo_n_id=%s claves=%s", pelo_n_id, claves
        )
        return CaminoOptico(
            estado=ESTADO_SIN_CAMINO,
            pelo_n_id=pelo_n_id,
            id_pedido=pelo_n_id,
            motivo="Cromo no devolvió ningún elemento para este pelo.",
            duracion_ms=duracion_ms,
            payload_raw=payload if incluir_raw else None,
        )

    id_raiz, raiz, es_mismo_id = _localizar_raiz(dic, pelo_n_id)
    if raiz is None:
        return CaminoOptico(
            estado=ESTADO_SIN_CAMINO,
            pelo_n_id=pelo_n_id,
            id_pedido=pelo_n_id,
            motivo=(
                "El camino no tiene un pelo raíz identificable: Cromo devolvió elementos pero "
                "ninguno con los dos extremos resueltos."
            ),
            ids_no_resueltos=[],
            duracion_ms=duracion_ms,
            payload_raw=payload if incluir_raw else None,
        )

    clases = {nodo.get("class") for nodo in dic.values() if nodo.get("class") is not None}
    catalogo = await _catalogo_clases(sesion, {int(c) for c in clases})

    lado_a, no_resueltos_a = _construir_lado(dic, raiz.get("a"), "A", catalogo)
    lado_b, no_resueltos_b = _construir_lado(dic, raiz.get("b"), "B", catalogo)

    advertencias: list[str] = []
    if not es_mismo_id:
        advertencias.append(
            f"Cromo devolvió la raíz bajo el id {id_raiz} y no el pedido {pelo_n_id}: "
            "puede ser un id de versión."
        )
    for lado, secuencia in (("A", raiz.get("a")), ("B", raiz.get("b"))):
        if secuencia and len(list(secuencia)) > MAX_NODOS_POR_LADO:
            advertencias.append(f"El lado {lado} se cortó en {MAX_NODOS_POR_LADO} elementos.")

    if vincular_local:
        await _vincular_local(sesion, lado_a + lado_b)

    raiz_nodo = NodoCamino(orden=-1, lado="RAIZ", id_cromo=id_raiz or pelo_n_id, clase=_CLASE_PELO, tipo=TIPO_PELO)
    _completar_contexto_pelo(raiz_nodo, raiz, dic)

    odfs = odfs_del_camino(lado_a, lado_b)
    if vincular_local and odfs:
        await _vincular_odfs(sesion, odfs)

    consistencia = (
        await auditar_consistencia(sesion, [raiz_nodo] + lado_a + lado_b) if auditar else None
    )

    at62 = atributo(raiz, _AT_SERVICIO_NUMERO)
    at61 = atributo(raiz, _AT_SERVICIO_CRUDO)

    return CaminoOptico(
        estado=ESTADO_OK,
        pelo_n_id=pelo_n_id,
        id_pedido=pelo_n_id,
        id_raiz=id_raiz,
        raiz_es_mismo_id=es_mismo_id,
        servicio_at62=at62,
        servicio_at61=at61,
        numero_pelo=raiz_nodo.numero_pelo,
        color_pelo=raiz_nodo.color_pelo,
        cable_id=raiz_nodo.cable_id,
        cable_nombre=raiz_nodo.cable_nombre,
        tubo_id=raiz_nodo.tubo_id,
        raiz=raiz_nodo,
        lado_a=lado_a,
        lado_b=lado_b,
        odfs=odfs,
        estadisticas=calcular_estadisticas(lado_a, lado_b, raiz_nodo),
        consistencia=consistencia,
        discrepancia=comparar_at62_vs_regex(at62, at61),
        ids_no_resueltos=no_resueltos_a + no_resueltos_b,
        advertencias=advertencias,
        duracion_ms=duracion_ms,
        payload_raw=payload if incluir_raw else None,
    )


async def _vincular_odfs(sesion: AsyncSession, odfs: list[OdfDelCamino]) -> None:
    """Resuelve el `n_id` local de cada ODF descubierta, en una pasada por `n_id` y otra por
    `version_id`. Sin vínculo local no se puede armar la asociación, así que este dato decide si
    la ODF se puede proponer o sólo mostrar."""
    pendientes = {odf.odf_id: odf for odf in odfs}
    if not pendientes:
        return

    filas = (
        await sesion.execute(
            text("SELECT n_id, nombre, vigente FROM app.cromo_odfs WHERE n_id = ANY(:ids)"),
            {"ids": sorted(pendientes)},
        )
    ).all()
    for n_id, nombre, vigente in filas:
        odf = pendientes.pop(int(n_id), None)
        if odf is not None:
            odf.vinculo_local = VinculoLocal(
                tabla="cromo_odfs", n_id=int(n_id), nombre=nombre, vigente=bool(vigente), coincide_por="N_ID"
            )

    if not pendientes:
        return
    filas = (
        await sesion.execute(
            text(
                "SELECT n_id, version_id, nombre, vigente FROM app.cromo_odfs "
                "WHERE version_id = ANY(:ids)"
            ),
            {"ids": sorted(pendientes)},
        )
    ).all()
    for n_id, version_id, nombre, vigente in filas:
        odf = pendientes.pop(int(version_id), None)
        if odf is not None:
            odf.vinculo_local = VinculoLocal(
                tabla="cromo_odfs",
                n_id=int(n_id),
                nombre=nombre,
                vigente=bool(vigente),
                coincide_por="VERSION_ID",
            )


async def resolver_camino_de_servicio(
    cliente: CromoClient,
    sesion: AsyncSession,
    servicio_id: int,
    *,
    pelo_n_id: Optional[int] = None,
    incluir_raw: bool = False,
) -> tuple[CaminoOptico, list[PeloSemilla]]:
    """Elige la semilla de un Servicio (o valida la pinneada) y resuelve su camino.

    Devuelve además las semillas disponibles, para que la UI muestre cuál se usó y ofrezca las
    otras sin pagar una segunda llamada. Si el Servicio no tiene ningún pelo en Cromo se
    devuelve `SIN_SEMILLA` **sin llamar a Cromo**: es el 77% de los Servicios del gestor
    (2.228 de 2.891), y para ellos `/path` no tiene input posible.

    Una sola llamada a `/path` por invocación: sin fan-out. Pedir otra semilla es una acción
    explícita del operador con `pelo_n_id`.
    """
    semillas = await listar_pelos_semilla(sesion, servicio_id)
    if not semillas:
        return (
            CaminoOptico(
                estado=ESTADO_SIN_SEMILLA,
                motivo=(
                    "El Servicio no tiene ningún pelo en `cromo_servicio_match`, así que "
                    "`/path` no tiene input posible."
                ),
            ),
            [],
        )

    if pelo_n_id is not None:
        elegida = next((s for s in semillas if s.pelo_n_id == pelo_n_id), None)
        if elegida is None:
            raise PeloAjenoAlServicio(
                f"El pelo {pelo_n_id} no pertenece al Servicio {servicio_id}."
            )
    else:
        elegida = semillas[0]

    camino = await resolver_camino_de_pelo(
        cliente, sesion, elegida.pelo_n_id, incluir_raw=incluir_raw
    )
    return camino, semillas


class PeloAjenoAlServicio(ValueError):
    """El `pelo_n_id` pinneado no pertenece al Servicio pedido — evita usar el endpoint como un
    `/path` genérico sobre cualquier pelo de la red."""



def semillas_por_defecto(semillas: list[PeloSemilla]) -> list[PeloSemilla]:
    """Semillas a preseleccionar para descargar el tracking de un Servicio.

    Criterio pedido por operaciones: **las posiciones de ODF asociadas al Servicio**, que pueden
    ser más de una. Un pelo que ya tiene conector de ODF ingerido es una posición de patchera real
    del Servicio, y es el tracking que el operador quiere bajar.

    Ojo con la asimetría respecto de `listar_pelos_semilla`, que ordena al revés a propósito
    (`tiene_conector_odf` ASC): aquella función existe para **descubrir** ODFs nuevas, y para eso
    el pelo interesante es justamente el que todavía no tiene conector. Acá el objetivo es el
    opuesto — bajar el tracking de lo que ya se conoce — así que el criterio vive en este
    consumidor y el ranking de descubrimiento queda intacto.

    Si ninguna semilla tiene conector (la ODF del Servicio todavía no fue relevada) se cae a la
    primera del ranking, que es el comportamiento histórico, y la UI avisa por qué.
    """
    con_conector = [s for s in semillas if s.tiene_conector_odf]
    if con_conector:
        return con_conector
    return semillas[:1]


def seleccionar_semillas(
    semillas: list[PeloSemilla], pelos_n_id: Optional[Iterable[int]]
) -> list[PeloSemilla]:
    """Traduce los `pelo_n_id` pedidos a semillas del Servicio, preservando el orden del ranking.

    Sin pedido explícito devuelve `semillas_por_defecto`. Cada id pedido tiene que pertenecer al
    Servicio: si no, `PeloAjenoAlServicio`, el mismo guard que ya protege al endpoint de un solo
    pelo de usarse como un `/path` genérico sobre cualquier pelo de la red.

    Los duplicados se colapsan —pedir dos veces el mismo pelo no debe generar dos entradas
    idénticas en el ZIP— y el orden de salida es el del ranking, no el del query string, para que
    dos pedidos con los mismos ids produzcan exactamente el mismo archivo.
    """
    if pelos_n_id is None:
        return semillas_por_defecto(semillas)
    pedidos = {int(p) for p in pelos_n_id}
    if not pedidos:
        return semillas_por_defecto(semillas)
    por_id = {s.pelo_n_id: s for s in semillas}
    ajenos = sorted(pedidos - set(por_id))
    if ajenos:
        raise PeloAjenoAlServicio(
            "Estos pelos no pertenecen al Servicio: " + ", ".join(str(p) for p in ajenos) + "."
        )
    return [s for s in semillas if s.pelo_n_id in pedidos]


__all__ = [
    "ConsistenciaCamino",
    "InconsistenciaCamino",
    "ResultadoRegla",
    "DESCRIPCION_REGLAS",
    "REGLA_CONECTOR",
    "REGLA_FUSION_BOTELLA",
    "REGLA_FUSION_PELOS",
    "REGLA_PELO_CABLE",
    "REGLA_PELO_TUBO",
    "TIPO_DISCREPA",
    "TIPO_NO_INGERIDO",
    "auditar_consistencia",
    "pares_declarados",
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
    "PeloAjenoAlServicio",
    "PeloSemilla",
    "VinculoLocal",
    "calcular_estadisticas",
    "comparar_at62_vs_regex",
    "CLASES_CABLE",
    "contar_semillas",
    "pelo_pertenece_al_servicio",
    "listar_pelos_semilla",
    "seleccionar_semillas",
    "semillas_por_defecto",
    "odfs_del_camino",
    "resolver_camino_de_pelo",
    "resolver_camino_de_servicio",
]
