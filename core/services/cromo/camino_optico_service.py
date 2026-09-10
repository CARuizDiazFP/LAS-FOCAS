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
    sesion: AsyncSession, servicio_id: int, *, limite: int = 20
) -> list[PeloSemilla]:
    """Pelos candidatos a semilla de `/path` para un Servicio, ya rankeados. Una sola query.

    `servicio_id` es la PK de `app.servicios`. El predicado de identidades es el mismo que usa
    el gestor de Servicios sin ODF (importado, no copiado) para no divergir.

    El orden pone primero el pelo cuya ODF todavía no conocemos: un pelo que ya tiene conector
    no aporta una ODF nueva. Es determinista hasta el último criterio, para que dos consultas
    del mismo Servicio elijan la misma semilla y el camino sea reproducible sin pagar dos veces
    la llamada a Cromo.
    """
    filas = (await sesion.execute(_SQL_PELOS_SEMILLA, {"servicio_id": servicio_id})).mappings().all()
    ordenadas = sorted(
        filas,
        key=lambda f: (
            f["prioridad_identidad"],
            f["tiene_conector_odf"],
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
    "listar_pelos_semilla",
    "odfs_del_camino",
    "resolver_camino_de_pelo",
    "resolver_camino_de_servicio",
]
