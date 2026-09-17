# Nombre de archivo: normalizacion_consistencia_service.py
# Ubicación de archivo: core/services/cromo/normalizacion_consistencia_service.py
# Descripción: Normaliza las discrepancias de la auditoría del camino óptico reingiriendo desde
# Cromo el objeto real involucrado, y releva una ODF puntual para poblar sus posiciones

"""Cierra el ciclo de la tabla "Consistencia con lo ingerido", que hasta ahora sólo informaba.

**Cromo es la referencia, y se lo trata como tal**: no se escribe el valor que declara el camino,
se vuelve a traer el objeto real desde la API de Cromo y se lo reingiere por el mismo parser y los
mismos upserts que usa la ingesta regular. Es más lento (una llamada por objeto) pero no abre una
segunda vía de escritura sobre las tablas de inventario, y todo queda auditado en una corrida
sintética visible en el mismo histórico que cualquier otra.

Las inconsistencias a corregir **se recalculan en el servidor**, resolviendo el camino de nuevo.
No se confía en la lista que manda el navegador: el cliente dice *qué* quiere normalizar, pero
*qué está realmente mal* lo decide el backend, que es quien va a escribir.

Reparto por regla de la auditoría:

- `PELO_CABLE` / `PELO_TUBO` → el elemento es un pelo (clase 130). Se reingiere el pelo y, si hace
  falta, su tubo. Ojo: `parser.parse_pelo` deja `cable_n_id=None` a propósito —la desnormalización
  la calcula la ingesta recorriendo el árbol del cable—, así que acá el cable se resuelve desde el
  tubo (local si ya está, y si no, trayéndolo de Cromo). Sin esto, reingerir un pelo le borraría
  el cable a la fila existente.
- `FUSION_BOTELLA` / `FUSION_PELOS` → el elemento es una fusión (clase 132). Se reingiere directo.
- `CONECTOR_PELO_ODF` → el elemento es una posición de patchera (clase 136), que no existe como
  objeto suelto en la ingesta: viaja dentro del `inner[]` de su ODF. Se normaliza **relevando la
  ODF entera**, que es la misma operación que necesita el Detalle de Servicio cuando la ODF de un
  Servicio todavía no fue relevada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import alias_service, id_dual_resolver, ingesta, tracking_cache
from core.services.cromo import parser as cromo_parser
from core.services.cromo.camino_optico_service import (
    CLASES_CABLE,
    ESTADO_OK,
    REGLA_CONECTOR,
    REGLA_FUSION_BOTELLA,
    REGLA_FUSION_PELOS,
    REGLA_PELO_CABLE,
    REGLA_PELO_TUBO,
    CaminoOptico,
    NodoCamino,
    resolver_camino_de_pelo,
)
from core.services.cromo.client import CromoClient, CromoClientError
from db.models.cromo import (
    CromoCable,
    CromoFusion,
    CromoOdf,
    CromoOdfConector,
    CromoPelo,
    CromoTubo,
)

logger = logging.getLogger(__name__)

_CLASE_PELO = 130
_CLASE_TUBO = 129
_CLASE_CONECTOR = 136

_REGLAS_DE_PELO = frozenset({REGLA_PELO_CABLE, REGLA_PELO_TUBO})
_REGLAS_DE_FUSION = frozenset({REGLA_FUSION_BOTELLA, REGLA_FUSION_PELOS})


class CaminoNoResoluble(RuntimeError):
    """No se pudo resolver el camino, así que no hay nada que auditar ni normalizar."""

    def __init__(self, motivo: Optional[str], estado: str) -> None:
        super().__init__(motivo or f"El camino no resolvió (estado {estado}).")
        self.motivo = motivo
        self.estado = estado


@dataclass(slots=True)
class ItemNormalizado:
    elemento_id: int
    regla: str
    accion: str  # CREADA | ACTUALIZADA | SIN_CAMBIOS | ERROR | OMITIDA
    detalle: Optional[str] = None


@dataclass(slots=True)
class ResultadoNormalizacion:
    pelo_n_id: int
    corrida_id: Optional[int] = None
    creados: int = 0
    actualizados: int = 0
    sin_cambios: int = 0
    errores: int = 0
    omitidos: int = 0
    detalle: list[ItemNormalizado] = field(default_factory=list)
    total_discrepa_previo: int = 0
    total_no_ingerido_previo: int = 0

    @property
    def normalizados(self) -> int:
        return self.creados + self.actualizados + self.sin_cambios


def _nodos_por_id(camino: CaminoOptico) -> dict[int, NodoCamino]:
    """Índice de los nodos del camino, para ubicar el contexto de cada elemento inconsistente."""
    nodos: dict[int, NodoCamino] = {}
    for nodo in ([camino.raiz] if camino.raiz else []) + camino.lado_a + camino.lado_b:
        nodos.setdefault(nodo.id_cromo, nodo)
    return nodos


def _id_de_parent(obj: dict) -> Optional[int]:
    """`parent` de un objeto traído por `/db/objects/{id}`, como id.

    Hallazgo real (2026-09-17, verificando contra Cromo): en un fetch directo `parent` viene como
    **objeto** (`{"id": 10127039, "class": 51, "name": "F-VIN-CAR2"}`), mientras que durante la
    ingesta regular el recorrido del árbol lo inyecta como entero. Pasarle el dict crudo a los
    parsers produce basura silenciosa —un `tubo_n_id` que es un diccionario— así que se normaliza
    acá, en un solo lugar.
    """
    parent = obj.get("parent")
    if isinstance(parent, dict):
        return parent.get("id")
    return parent


async def _n_id_de_linaje(cliente: CromoClient, id_version: Optional[int]) -> Optional[int]:
    """Traduce un id de versión al `n_id` de linaje que usa el inventario local.

    Los ids que devuelve `parent` en un fetch directo son de **versión**, no de linaje: para el
    cable del pelo 10126944, `parent.id` es 10127039 mientras que el camino declara 10126920. Los
    parsers ya saben resolverlo (`_resolver_n_id`), así que alcanza con traer el objeto y parsearlo.
    """
    if id_version is None:
        return None
    obj = await id_dual_resolver.fetch_objeto(cliente, id_version)
    clase = obj.get("class")
    if clase in CLASES_CABLE:
        return cromo_parser.parse_cable(obj).n_id
    if clase in cromo_parser.CLASES_BOTELLA:
        return cromo_parser.parse_botella(obj).n_id
    return obj.get("n_id") or obj.get("id")


async def _normalizar_pelo(
    cliente: CromoClient, sesion: AsyncSession, corrida_id: int, elemento_id: int
) -> str:
    """Reingiere el pelo a través del **árbol de su cable**, que es como lo hace la ingesta.

    Parsear un pelo traído suelto no sirve: `parse_pelo` toma `tubo_n_id` de `parent`, y en un
    fetch directo ese `parent` es el **cable**, no el tubo (verificado real contra Cromo). El árbol
    del cable, en cambio, produce exactamente lo que declara el camino — para el pelo 10126944,
    `tubo_n_id=10126934` y `cable_n_id=10126920`, idénticos al `/path`. Por eso una sola reingesta
    de cable resuelve a la vez las reglas `PELO_CABLE` y `PELO_TUBO` de todos sus pelos.

    El cable sólo se crea si falta: si ya existe no se lo toca, porque la inconsistencia era de
    pelos y sobrescribir sus extremos con los de un fetch parcial degradaría una fila sana.
    """
    obj = await id_dual_resolver.fetch_objeto(cliente, elemento_id)
    if obj.get("class") != _CLASE_PELO:
        raise ValueError(
            f"El elemento {elemento_id} no es un pelo en Cromo (clase {obj.get('class')})."
        )

    cable_id_version = _id_de_parent(obj)
    if cable_id_version is None:
        raise ValueError(f"El pelo {elemento_id} no declara cable padre en Cromo.")

    cable_obj = await id_dual_resolver.fetch_objeto(cliente, cable_id_version)
    # Se acepta también la clase 52 (cable de un tercero, ej. Arsat): la ingesta no la barre, pero
    # es un cable real del camino y sus pelos son tan legítimos como los de un cable propio.
    # `cromo_cables` no tiene columna de clase, así que guardarlo no rompe ninguna FK de catálogo.
    # Caso real que lo destapó: el pelo 7967645 del servicio 93154 cuelga de un cable clase 52.
    if cable_obj.get("class") not in CLASES_CABLE:
        raise ValueError(
            f"El padre del pelo {elemento_id} no es un cable (clase {cable_obj.get('class')})."
        )

    cable = cromo_parser.parse_cable(cable_obj)
    tubos, pelos, _errores = cromo_parser.extraer_tubos_y_pelos(cable_obj)
    if not any(p.n_id == elemento_id for p in pelos):
        raise ValueError(
            f"El árbol del cable {cable.n_id} no contiene al pelo {elemento_id}."
        )

    if await sesion.get(CromoCable, cable.n_id) is None:
        await ingesta.upsert_versionado(sesion, CromoCable, cable, ingesta.CABLE_CAMPOS)
        await ingesta.registrar_evento(
            sesion, corrida_id, cable.n_id, ingesta.CLASE_CABLE, "CREADA"
        )

    existia = await sesion.get(CromoPelo, elemento_id) is not None
    for tubo in tubos:
        await ingesta.upsert_simple(sesion, CromoTubo, tubo, ingesta.TUBO_CAMPOS)
    for pelo in pelos:
        await ingesta.upsert_simple(sesion, CromoPelo, pelo, ingesta.PELO_CAMPOS)
    return "ACTUALIZADA" if existia else "CREADA"


async def _normalizar_fusion(
    cliente: CromoClient,
    sesion: AsyncSession,
    corrida_id: int,
    elemento_id: int,
    alias_por_origen: dict,
) -> str:
    """Reingiere una fusión, resolviendo su botella al `n_id` de linaje y respetando los alias.

    `parse_fusion` toma la botella de `parent`, que en un fetch directo es un objeto y además
    trae el id de **versión**: para la fusión 10277390, `parent.id` es 10277058 mientras el camino
    declara 10276670. Sin traducir eso, la fusión quedaría colgando de una botella que el
    inventario local no conoce.
    """
    obj = await id_dual_resolver.fetch_objeto(cliente, elemento_id)
    if obj.get("class") != ingesta.CLASE_FUSION:
        raise ValueError(
            f"El elemento {elemento_id} no es una fusión en Cromo (clase {obj.get('class')})."
        )
    fusion = cromo_parser.parse_fusion(obj)
    fusion.botella_n_id = await _n_id_de_linaje(cliente, _id_de_parent(obj))
    # Mismo escudo que la ingesta regular: un n_id de botella aliaseado nunca se resucita acá.
    fusion.botella_n_id = alias_service.resolver_referencia(fusion.botella_n_id, alias_por_origen)

    existia = await sesion.get(CromoFusion, fusion.n_id) is not None
    await ingesta.upsert_simple(sesion, CromoFusion, fusion, ingesta.FUSION_CAMPOS)
    return "ACTUALIZADA" if existia else "CREADA"


async def relevar_odf(
    cliente: CromoClient, sesion: AsyncSession, corrida_id: int, odf_n_id: int
) -> str:
    """Trae una ODF de Cromo con sus posiciones de patchera y las reingiere.

    A diferencia del barrido de la fase de ODFs, acá siempre se pide `inner` explícitamente: se
    está relevando UNA ODF puntual justamente porque interesan sus conectores, así que ahorrarse
    la llamada cuando el objeto liviano no los trae dejaría el relevamiento a medias.

    El atributo id=62 (servicio declarado directo sobre el conector) sólo viaja en la respuesta de
    `/inner`, nunca en el objeto liviano — de ahí que esa llamada sea la que da el dato que después
    permite preseleccionar las posiciones de ODF de un Servicio.
    """
    obj = await id_dual_resolver.fetch_objeto(cliente, odf_n_id)
    if obj.get("class") != ingesta.CLASE_ODF:
        raise ValueError(f"El elemento {odf_n_id} no es una ODF en Cromo (clase {obj.get('class')}).")

    odf = cromo_parser.parse_odf(obj)
    accion = await ingesta.upsert_forzado(sesion, CromoOdf, odf, ingesta.ODF_CAMPOS)
    await ingesta.registrar_evento(sesion, corrida_id, odf.n_id, ingesta.CLASE_ODF, accion)

    conectores = []
    try:
        inner = await cliente.get_inner(odf.n_id)
        conectores = cromo_parser.parse_odf_conectores({**obj, "inner": inner.get("response") or []})
    except CromoClientError as exc:
        # Un fallo puntual de red no debe perder la ODF ya reingerida: se degrada a lo que traiga
        # el objeto, igual que hace la fase regular.
        logger.warning(
            "action=cromo_relevar_odf evento=error_get_inner odf_n_id=%s error=%s", odf_n_id, exc
        )
        conectores = cromo_parser.parse_odf_conectores(obj)

    if conectores:
        await ingesta.resolver_servicio_conectores(sesion, conectores)
        for conector in conectores:
            await ingesta.upsert_simple(
                sesion, CromoOdfConector, conector, ingesta.CONECTOR_ODF_CAMPOS
            )
    return accion


async def relevar_odfs_del_servicio(
    cliente: CromoClient,
    sesion: AsyncSession,
    *,
    pelo_n_id: int,
    usuario: str,
    odfs_n_id: Optional[Iterable[int]] = None,
) -> ResultadoNormalizacion:
    """Releva las ODFs que atraviesa el camino de un pelo, para poblar sus posiciones.

    Es la acción que destraba el caso "la ODF de este Servicio no está relevada": sin conectores
    ingeridos no hay forma de saber qué posición de patchera le corresponde al Servicio, y por
    eso la descarga de trackings no puede preseleccionar nada.

    Se releva sólo lo que el camino ya descubrió, no todo el universo de ODFs: es una acción
    puntual del operador sobre un Servicio, no una corrida de inventario.
    """
    camino = await resolver_camino_de_pelo(cliente, sesion, pelo_n_id, auditar=False)
    if camino.estado != ESTADO_OK:
        raise CaminoNoResoluble(camino.motivo, camino.estado)

    descubiertas = [odf.odf_id for odf in camino.odfs if odf.odf_id is not None]
    objetivo = (
        [o for o in descubiertas if o in set(int(x) for x in odfs_n_id)]
        if odfs_n_id is not None
        else descubiertas
    )
    resultado = ResultadoNormalizacion(pelo_n_id=pelo_n_id)
    if not objetivo:
        return resultado

    corrida = await ingesta.iniciar_corrida(
        sesion,
        usuario=usuario,
        psize=0,
        max_paginas=0,
        clases=(),
        params_extra={"tipo": "MANUAL_RELEVAR_ODF", "pelo_n_id": pelo_n_id, "odfs": objetivo},
    )
    resultado.corrida_id = corrida.id

    for odf_n_id in objetivo:
        try:
            async with sesion.begin_nested():
                accion = await relevar_odf(cliente, sesion, corrida.id, odf_n_id)
        except Exception as exc:  # noqa: BLE001 - una ODF no aborta el lote
            resultado.errores += 1
            logger.error(
                "action=cromo_relevar_odf evento=error odf_n_id=%s error=%s", odf_n_id, exc
            )
            await ingesta.registrar_evento(
                sesion, corrida.id, odf_n_id, ingesta.CLASE_ODF, "ERROR", str(exc)
            )
            resultado.detalle.append(
                ItemNormalizado(elemento_id=odf_n_id, regla=REGLA_CONECTOR, accion="ERROR", detalle=str(exc))
            )
            continue
        _contar(resultado, accion)
        resultado.detalle.append(
            ItemNormalizado(elemento_id=odf_n_id, regla=REGLA_CONECTOR, accion=accion)
        )

    await sesion.commit()
    return resultado


def _contar(resultado: ResultadoNormalizacion, accion: str) -> None:
    if accion == "CREADA":
        resultado.creados += 1
    elif accion == "ACTUALIZADA":
        resultado.actualizados += 1
    elif accion == "SIN_CAMBIOS":
        resultado.sin_cambios += 1
    elif accion == "OMITIDA":
        resultado.omitidos += 1


async def normalizar_inconsistencias(
    cliente: CromoClient,
    sesion: AsyncSession,
    *,
    pelo_n_id: int,
    usuario: str,
    elemento_ids: Optional[Iterable[int]] = None,
) -> ResultadoNormalizacion:
    """Reingiere desde Cromo los objetos que la auditoría marcó como `DIFIERE` o `NO_INGERIDO`.

    `elemento_ids` acota qué corregir (el operador puede normalizar un caso puntual); sin él se
    normaliza todo lo que la auditoría encontró. En ambos casos la lista real sale de recalcular
    la auditoría acá, no de lo que haya mandado el navegador.

    Al terminar invalida el tracking cacheado del pelo: el `.txt` generado antes describe un
    estado de la base que ya cambió.
    """
    camino = await resolver_camino_de_pelo(cliente, sesion, pelo_n_id, auditar=True)
    if camino.estado != ESTADO_OK:
        raise CaminoNoResoluble(camino.motivo, camino.estado)

    resultado = ResultadoNormalizacion(pelo_n_id=pelo_n_id)
    consistencia = camino.consistencia
    if consistencia is None or not consistencia.inconsistencias:
        return resultado

    resultado.total_discrepa_previo = consistencia.total_discrepa
    resultado.total_no_ingerido_previo = consistencia.total_no_ingerido

    pedidos = {int(e) for e in elemento_ids} if elemento_ids is not None else None
    # Un mismo pelo puede aparecer en PELO_CABLE y PELO_TUBO a la vez: reingerirlo dos veces sería
    # una llamada de red al pedo. Se colapsa por elemento, quedándose con la primera regla.
    por_elemento: dict[int, str] = {}
    for inc in consistencia.inconsistencias:
        if pedidos is not None and inc.elemento_id not in pedidos:
            continue
        por_elemento.setdefault(inc.elemento_id, inc.regla)

    if not por_elemento:
        return resultado

    nodos = _nodos_por_id(camino)
    alias_por_origen = await alias_service.cargar_alias_vigentes(sesion)

    corrida = await ingesta.iniciar_corrida(
        sesion,
        usuario=usuario,
        psize=0,
        max_paginas=0,
        clases=(),
        params_extra={
            "tipo": "MANUAL_NORMALIZAR_CONSISTENCIA",
            "pelo_n_id": pelo_n_id,
            "elementos": sorted(por_elemento),
        },
    )
    resultado.corrida_id = corrida.id
    odfs_relevadas: set[int] = set()

    for elemento_id, regla in sorted(por_elemento.items()):
        try:
            async with sesion.begin_nested():
                if regla in _REGLAS_DE_PELO:
                    accion = await _normalizar_pelo(cliente, sesion, corrida.id, elemento_id)
                    clase = _CLASE_PELO
                elif regla in _REGLAS_DE_FUSION:
                    accion = await _normalizar_fusion(
                        cliente, sesion, corrida.id, elemento_id, alias_por_origen
                    )
                    clase = ingesta.CLASE_FUSION
                elif regla == REGLA_CONECTOR:
                    # Un conector no existe como objeto suelto en la ingesta: se releva su ODF.
                    odf_n_id = nodos.get(elemento_id).odf_id if nodos.get(elemento_id) else None
                    if odf_n_id is None:
                        raise ValueError(
                            "El camino no resolvió a qué ODF pertenece este conector, así que no "
                            "hay nada que relevar."
                        )
                    if odf_n_id in odfs_relevadas:
                        accion = "SIN_CAMBIOS"
                    else:
                        accion = await relevar_odf(cliente, sesion, corrida.id, odf_n_id)
                        odfs_relevadas.add(odf_n_id)
                    clase = _CLASE_CONECTOR
                else:
                    raise ValueError(f"Regla de consistencia no soportada: {regla}.")
                await ingesta.registrar_evento(sesion, corrida.id, elemento_id, clase, accion)
        except Exception as exc:  # noqa: BLE001 - un elemento no aborta el lote
            resultado.errores += 1
            logger.error(
                "action=cromo_normalizar evento=error pelo_n_id=%s elemento_id=%s regla=%s error=%s",
                pelo_n_id,
                elemento_id,
                regla,
                exc,
            )
            await ingesta.registrar_evento(
                sesion, corrida.id, elemento_id, None, "ERROR", str(exc)
            )
            resultado.detalle.append(
                ItemNormalizado(elemento_id=elemento_id, regla=regla, accion="ERROR", detalle=str(exc))
            )
            continue
        _contar(resultado, accion)
        resultado.detalle.append(
            ItemNormalizado(elemento_id=elemento_id, regla=regla, accion=accion)
        )

    # El .txt cacheado describe un estado de la base que acaba de cambiar.
    await tracking_cache.invalidar(sesion, [pelo_n_id])
    await sesion.commit()

    logger.info(
        "action=cromo_normalizar resultado=ok pelo_n_id=%s corrida_id=%s creados=%s actualizados=%s errores=%s",
        pelo_n_id,
        resultado.corrida_id,
        resultado.creados,
        resultado.actualizados,
        resultado.errores,
    )
    return resultado
