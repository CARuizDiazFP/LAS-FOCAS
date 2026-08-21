# Nombre de archivo: ingesta.py
# Ubicación de archivo: core/services/cromo/ingesta.py
# Descripción: Servicio de ingesta Cromo — lectura paginada, clasificación por vmax, upsert y auditoría de corridas

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import alias_service
from core.services.cromo import parser as cromo_parser
from core.services.cromo.alias_service import AliasBotella
from core.services.cromo.client import CromoClient
from core.services.cromo.config import PSIZE_PERMITIDOS, get_cromo_config

# CromoServicioMatch.servicio_id referencia "app.servicios.id" por nombre de tabla (string FK).
# SQLAlchemy sólo puede resolverla si el modelo Servicio (db/models/infra.py) ya se registró en
# Base.metadata — no ocurre solo por importar db.models.cromo. Import explícito, autocontenido:
# este módulo no debe depender de que quien lo use haya importado infra.py por otro motivo.
from db.models.infra import Servicio, ServicioOrigenDatos
from db.models.cromo import (
    CromoBotella,
    CromoCable,
    CromoFusion,
    CromoIngestaCorrida,
    CromoIngestaEvento,
    CromoPelo,
    CromoServicioMatch,
    CromoTubo,
)

logger = logging.getLogger(__name__)


class _CorridaCancelada(Exception):
    """Señal interna: la corrida fue cancelada externamente (POST .../cancelar). No es un error."""


CLASE_CABLE = 51
CLASE_FUSION = 132
CLASES_BOTELLA: tuple[int, ...] = (68, 121, 122, 123, 125)
# Clases con colección propia contable vía stats[].count (fase de conteo).
CLASES_CONTEO: tuple[int, ...] = (*CLASES_BOTELLA, CLASE_CABLE, CLASE_FUSION)

_BOTELLA_CAMPOS = (
    "version_id",
    "vmax",
    "clase",
    # "nombre" removido deliberadamente (ver CromoBotella.nombre_editado_manual, db/models/cromo.py):
    # una corrección manual vía PATCH /api/infra/botellas/{n_id}/nombre no debe perderse en la
    # próxima corrida. El caso especial vive en _procesar_botella_completa, justo después del
    # upsert de botella — mismo criterio ya usado acá para excluir camara_id/estado.
    "codigo_modelo",
    "id_legacy",
    "notas",
    "calle",
    "altura",
    "localidad",
    "provincia",
    "ubicacion_fisica",
    "tendido",
    "latitud",
    "longitud",
    "pts_raw",
    "payload_raw",
)
CABLE_CAMPOS = (
    "version_id",
    "vmax",
    "nombre",
    "capacidad",
    "capacidad_pelos",
    "propietario",
    "jerarquia",
    "tendido",
    "distancia_geo",
    "distancia_real",
    "id_legacy",
    "notas",
    "extremo_a_n_id",
    "extremo_a_clase",
    "extremo_a_legacy",
    "extremo_a_nombre",
    "extremo_b_n_id",
    "extremo_b_clase",
    "extremo_b_legacy",
    "extremo_b_nombre",
    "pts_raw",
    "payload_raw",
)
TUBO_CAMPOS = ("cable_n_id", "orden", "nombre_color")
PELO_CAMPOS = (
    "tubo_n_id",
    "cable_n_id",
    "numero_pelo",
    "orden",
    "color",
    "servicio_raw",
    "servicio_numero",
    "tipo_asociacion",
)
_FUSION_CAMPOS = ("botella_n_id", "nombre_par", "tipo", "pelo_a_n_id", "pelo_b_n_id", "latitud", "longitud")


@dataclass(slots=True)
class ContadoresCorrida:
    """Contadores en memoria de una corrida en curso; se vuelcan a `CromoIngestaCorrida` por página."""

    leidas: int = 0
    creadas: int = 0
    actualizadas: int = 0
    sin_cambios: int = 0
    errores: int = 0
    refs_colgadas: int = 0

    def contar(self, accion: str) -> None:
        if accion == "CREADA":
            self.creadas += 1
        elif accion == "ACTUALIZADA":
            self.actualizadas += 1
        elif accion == "SIN_CAMBIOS":
            self.sin_cambios += 1


def _copiar_campos(destino: Any, origen: Any, campos: tuple[str, ...]) -> None:
    for campo in campos:
        setattr(destino, campo, getattr(origen, campo))


async def upsert_versionado(sesion: AsyncSession, modelo_cls: type, dominio_obj: Any, campos: tuple[str, ...]) -> str:
    """Clasifica y upsertea un objeto con `vmax` (botella o cable). CREADA | ACTUALIZADA | SIN_CAMBIOS | OMITIDA.

    En SIN_CAMBIOS no se toca ningún campo de datos, sólo `ultima_ingesta` — así una vista parcial
    (p.ej. un cable embebido en botella.tp[] con sólo at.26/at.23) nunca pisa una fila ya completa.

    Hallazgo real (2026-08-06, corrida de prueba): la vista de cable embebida en `botella.tp[]` a veces
    no trae `id`/`vmax` en absoluto (no sólo distinto, ausente), porque es una referencia de topología
    enriquecida, no una foto completa del objeto — esa metadata de versión sólo viene confiable del
    barrido directo (Fase 2). Sin `vmax` no hay señal de versión: si la fila ya existe se trata como
    SIN_CAMBIOS (nunca se pisa con datos parciales); si no existe todavía, se omite (`version_id`/`vmax`
    son NOT NULL) — Fase 2, que corre antes y sin este límite en producción, la va a crear igual.
    """
    ahora = datetime.now(timezone.utc)
    existente = await sesion.get(modelo_cls, dominio_obj.n_id)

    if dominio_obj.vmax is None:
        if existente is not None:
            existente.ultima_ingesta = ahora
            return "SIN_CAMBIOS"
        return "OMITIDA"

    if existente is None:
        nuevo = modelo_cls(n_id=dominio_obj.n_id)
        _copiar_campos(nuevo, dominio_obj, campos)
        nuevo.ultima_ingesta = ahora
        sesion.add(nuevo)
        return "CREADA"

    if existente.vmax == dominio_obj.vmax:
        existente.ultima_ingesta = ahora
        return "SIN_CAMBIOS"

    _copiar_campos(existente, dominio_obj, campos)
    existente.ultima_ingesta = ahora
    if hasattr(existente, "ultima_modificacion"):
        existente.ultima_modificacion = ahora
    return "ACTUALIZADA"


async def upsert_simple(sesion: AsyncSession, modelo_cls: type, dominio_obj: Any, campos: tuple[str, ...]) -> None:
    """Upsert de tubo/pelo/fusión: sin `vmax` propio, se sobrescribe siempre. Sin clasificación ni evento
    individual — el diseño (docs/Doc Privada/ingesta_cromo.md §7.1) sólo clasifica botella y cable;
    tubo/pelo/fusión "viajan" con su padre.
    """
    ahora = datetime.now(timezone.utc)
    existente = await sesion.get(modelo_cls, dominio_obj.n_id)
    if existente is None:
        nuevo = modelo_cls(n_id=dominio_obj.n_id)
        _copiar_campos(nuevo, dominio_obj, campos)
        nuevo.ultima_ingesta = ahora
        sesion.add(nuevo)
        return
    _copiar_campos(existente, dominio_obj, campos)
    existente.ultima_ingesta = ahora


async def upsert_forzado(sesion: AsyncSession, modelo_cls: type, dominio_obj: Any, campos: tuple[str, ...]) -> str:
    """Variante de `upsert_versionado` que SIEMPRE copia `campos`, sin comparar `vmax`. CREADA si
    no existe, ACTUALIZADA si existe.

    Sólo la usa `core/services/cromo/repoblacion_service.py`, nunca una corrida regular. Hallazgo
    real (Verificador Cromo, caso "ID dual" B2-FO-CAR, 2026-08-21): el `vmax` de un cable es una
    propiedad de la entidad estable, no de qué extremo trae el snapshot — un cable ya ingerido con
    `extremo_x_n_id` apuntando a un id de versión vieja de la botella (en vez de su `n_id` estable)
    puede tener el mismo `vmax` que el vigente, así que `upsert_versionado` lo clasificaría
    SIN_CAMBIOS y jamás corregiría el extremo tras el anclaje. `upsert_forzado` no tiene ese riesgo
    porque siempre persiste lo que se le pasa.
    """
    ahora = datetime.now(timezone.utc)
    existente = await sesion.get(modelo_cls, dominio_obj.n_id)
    if existente is None:
        nuevo = modelo_cls(n_id=dominio_obj.n_id)
        _copiar_campos(nuevo, dominio_obj, campos)
        nuevo.ultima_ingesta = ahora
        sesion.add(nuevo)
        return "CREADA"
    _copiar_campos(existente, dominio_obj, campos)
    existente.ultima_ingesta = ahora
    if hasattr(existente, "ultima_modificacion"):
        existente.ultima_modificacion = ahora
    return "ACTUALIZADA"


async def registrar_evento(
    sesion: AsyncSession,
    corrida_id: int,
    n_id: Optional[int],
    clase: Optional[int],
    accion: str,
    detalle: Optional[str] = None,
) -> None:
    sesion.add(CromoIngestaEvento(corrida_id=corrida_id, n_id=n_id, clase=clase, accion=accion, detalle=detalle))


def sincronizar_contadores(corrida: CromoIngestaCorrida, contadores: ContadoresCorrida) -> None:
    corrida.leidas = contadores.leidas
    corrida.creadas = contadores.creadas
    corrida.actualizadas = contadores.actualizadas
    corrida.sin_cambios = contadores.sin_cambios
    corrida.errores = contadores.errores
    corrida.refs_colgadas = contadores.refs_colgadas


async def _fue_cancelada_externamente(sesion: AsyncSession, corrida_id: int) -> bool:
    """Lee `estado` con una consulta fresca (no el objeto ya cargado en la sesión, que no ve
    cambios comiteados por otra sesión/request — p.ej. el endpoint de cancelar).
    """
    fila = (
        await sesion.execute(text("SELECT estado FROM app.cromo_ingesta_corridas WHERE id = :id"), {"id": corrida_id})
    ).first()
    return bool(fila and fila[0] == "CANCELADA")


async def _registrar_pagina(
    sesion: AsyncSession, corrida_id: int, fase: str, numero_pagina: int, pagina: dict[str, Any], contadores: ContadoresCorrida
) -> None:
    detalle = json.dumps(
        {
            "fase": fase,
            "pagina": numero_pagina,
            "next": pagina.get("next"),
            "leidas": contadores.leidas,
            "creadas": contadores.creadas,
            "actualizadas": contadores.actualizadas,
            "sin_cambios": contadores.sin_cambios,
            "errores": contadores.errores,
        }
    )
    await registrar_evento(sesion, corrida_id, None, None, "PAGINA", detalle)


async def _registrar_inicio_fase(sesion: AsyncSession, corrida_id: int, fase: str, descripcion: str) -> None:
    await registrar_evento(sesion, corrida_id, None, None, "FASE", json.dumps({"fase": fase, "descripcion": descripcion}))
    await sesion.commit()


async def iniciar_corrida(
    sesion: AsyncSession,
    *,
    usuario: str,
    psize: int,
    max_paginas: Optional[int],
    clases: Iterable[int],
    params_extra: Optional[dict[str, Any]] = None,
) -> CromoIngestaCorrida:
    """`params_extra` es aditivo: sin pasarlo, reproduce el `params` de siempre byte a byte. Lo usa
    `core/services/cromo/repoblacion_service.py` para marcar una corrida sintética de un solo
    click (`{"tipo": "MANUAL_REPOBLAR_CABLES", "botella_n_id": ...}`), visible en el mismo
    histórico admin que una corrida regular."""
    params: dict[str, Any] = {"psize": psize, "max_paginas": max_paginas, "clases": list(clases)}
    if params_extra:
        params.update(params_extra)
    corrida = CromoIngestaCorrida(
        usuario=usuario,
        estado="EN_CURSO",
        params=params,
    )
    sesion.add(corrida)
    await sesion.commit()
    await sesion.refresh(corrida)
    logger.info("action=cromo_ingesta evento=corrida_iniciada corrida_id=%s usuario=%s", corrida.id, usuario)
    return corrida


async def fase_conteo(cliente: CromoClient) -> dict[int, int]:
    """FASE 1 · CONTEO: requests baratos (psize=1&show=BASIC) para el `total_objetivo`, uno por clase
    en `CLASES_CONTEO` (botellas + cables + fusiones)."""
    totales: dict[int, int] = {}
    for clase in CLASES_CONTEO:
        respuesta = await cliente.get_coleccion(str(clase), psize=1, show=["BASIC"])
        stats = respuesta.get("stats") or []
        conteo = next((s.get("count") for s in stats if s.get("id") == clase), None)
        if conteo is not None:
            totales[clase] = conteo
    return totales


async def _procesar_cable_directo(
    sesion: AsyncSession,
    corrida_id: int,
    obj: dict[str, Any],
    contadores: ContadoresCorrida,
    *,
    alias_por_origen: Optional[dict[int, AliasBotella]] = None,
) -> None:
    """Procesa un cable del barrido directo (filter=51). Un savepoint propio: si falla, no aborta la página."""
    alias_por_origen = alias_por_origen or {}
    try:
        async with sesion.begin_nested():
            cable = cromo_parser.parse_cable(obj)
            cable.extremo_a_n_id = alias_service.resolver_referencia(cable.extremo_a_n_id, alias_por_origen)
            cable.extremo_b_n_id = alias_service.resolver_referencia(cable.extremo_b_n_id, alias_por_origen)
            accion = await upsert_versionado(sesion, CromoCable, cable, CABLE_CAMPOS)
            contadores.leidas += 1
            contadores.contar(accion)
            await registrar_evento(sesion, corrida_id, cable.n_id, CLASE_CABLE, accion)
    except Exception as exc:  # noqa: BLE001 - tolerancia deliberada: un objeto no aborta la página
        contadores.errores += 1
        n_id = obj.get("n_id") or obj.get("id")
        logger.error("action=cromo_ingesta evento=error_cable n_id=%s error=%s", n_id, exc)
        await registrar_evento(sesion, corrida_id, n_id, obj.get("class"), "ERROR", str(exc))


async def fase_cables(
    cliente: CromoClient,
    sesion: AsyncSession,
    corrida: CromoIngestaCorrida,
    contadores: ContadoresCorrida,
    *,
    psize: int,
    max_paginas: Optional[int],
    alias_por_origen: Optional[dict[int, AliasBotella]] = None,
) -> None:
    """FASE 2 · CABLES: maestro de cables (atributos + extremos). No trae tubos/pelos (ver §2, corrección 8)."""
    await _registrar_inicio_fase(sesion, corrida.id, "CABLES", "Barrido directo de cables (filter=51)")
    numero_pagina = 0
    async for pagina in cliente.iterar_coleccion(str(CLASE_CABLE), psize=psize, show=["SHOW", "TIME"], max_paginas=max_paginas):
        numero_pagina += 1
        objetos = pagina.get("response") or pagina.get("data") or []
        for obj in objetos:
            await _procesar_cable_directo(sesion, corrida.id, obj, contadores, alias_por_origen=alias_por_origen)
        sincronizar_contadores(corrida, contadores)
        await _registrar_pagina(sesion, corrida.id, "CABLES", numero_pagina, pagina, contadores)
        await sesion.commit()
        if await _fue_cancelada_externamente(sesion, corrida.id):
            raise _CorridaCancelada()


async def _procesar_fusion_directa(
    sesion: AsyncSession,
    corrida_id: int,
    obj: dict[str, Any],
    contadores: ContadoresCorrida,
    *,
    alias_por_origen: Optional[dict[int, AliasBotella]] = None,
) -> None:
    """Procesa una fusión del barrido directo (filter=132). Un savepoint propio: si falla, no aborta
    la página. Sin vmax propio: se sobreescribe siempre, sin evento individual de auditoría — mismo
    criterio que tubo/pelo/fusión embebidos (`upsert_simple`, ver docstring). `leidas` sí se
    incrementa porque, a diferencia de tubo/pelo, la clase 132 ahora tiene colección propia contada en
    `CLASES_CONTEO` — si no incrementara acá, la barra de progreso nunca llegaría al 100%."""
    alias_por_origen = alias_por_origen or {}
    try:
        async with sesion.begin_nested():
            fusion = cromo_parser.parse_fusion(obj)
            fusion.botella_n_id = alias_service.resolver_referencia(fusion.botella_n_id, alias_por_origen)
            await upsert_simple(sesion, CromoFusion, fusion, _FUSION_CAMPOS)
            contadores.leidas += 1
    except Exception as exc:  # noqa: BLE001 - tolerancia deliberada: un objeto no aborta la página
        contadores.errores += 1
        n_id = obj.get("n_id") or obj.get("id")
        logger.error("action=cromo_ingesta evento=error_fusion n_id=%s error=%s", n_id, exc)
        await registrar_evento(sesion, corrida_id, n_id, obj.get("class"), "ERROR", str(exc))


async def fase_fusiones(
    cliente: CromoClient,
    sesion: AsyncSession,
    corrida: CromoIngestaCorrida,
    contadores: ContadoresCorrida,
    *,
    psize: int,
    max_paginas: Optional[int],
    alias_por_origen: Optional[dict[int, AliasBotella]] = None,
) -> None:
    """FASE 4 · FUSIONES: barrido directo de clase 132 (Etapa 8).

    Hallazgo real: pese a que el diseño documentaba que `botella.inner[]` trae las fusiones embebidas
    (`show=SHOW,REL_ATTRIBUTE,TIME` sobre `filter=68,121,122,123,125`), un barrido paginado real
    completo (corrida real de producción dev, 11.100 botellas) no trajo la clave `inner` en ninguna —
    la fase de Etapa 3 que procesa botellas queda como estaba (sigue leyendo fusiones embebidas si
    algún día aparecen, es una lectura sin costo), pero la única fuente real de fusiones es este
    barrido directo, confirmado contra Cromo real: `filter=132&show=SHOW,TIME` sí devuelve objetos.

    Los objetos de este barrido no traen `parent` (a diferencia de los embebidos en `botella.inner[]`,
    que si algún día aparecen sí lo traerían) — por eso `cromo_fusiones.botella_n_id` es nullable
    (migración `20260807_01`): no hay forma de resolver la botella contenedora sin un request por
    fusión a `GET /db/objects/{id}/container`, que no se justifica a esta escala (miles de fusiones).
    """
    await _registrar_inicio_fase(sesion, corrida.id, "FUSIONES", "Barrido directo de fusiones (filter=132)")
    numero_pagina = 0
    async for pagina in cliente.iterar_coleccion(str(CLASE_FUSION), psize=psize, show=["SHOW", "TIME"], max_paginas=max_paginas):
        numero_pagina += 1
        objetos = pagina.get("response") or pagina.get("data") or []
        for obj in objetos:
            await _procesar_fusion_directa(sesion, corrida.id, obj, contadores, alias_por_origen=alias_por_origen)
        sincronizar_contadores(corrida, contadores)
        await _registrar_pagina(sesion, corrida.id, "FUSIONES", numero_pagina, pagina, contadores)
        await sesion.commit()
        if await _fue_cancelada_externamente(sesion, corrida.id):
            raise _CorridaCancelada()


async def _procesar_botella_completa(
    sesion: AsyncSession,
    corrida_id: int,
    obj: dict[str, Any],
    contadores: ContadoresCorrida,
    *,
    alias_por_origen: Optional[dict[int, AliasBotella]] = None,
) -> None:
    """Procesa una botella y todo su árbol (fusiones, cables embebidos, tubos, pelos) en un savepoint propio."""
    alias_por_origen = alias_por_origen or {}
    try:
        async with sesion.begin_nested():
            arbol = cromo_parser.parse_arbol_botella(obj)

            alias_botella = alias_por_origen.get(arbol.botella.n_id)
            if alias_botella is not None:
                # n_id marcado como basura/duplicado ('ignorar') o como el mismo objeto que otro
                # n_id ya bueno ('fusionar') — en ambos casos no se crea/actualiza una CromoBotella
                # propia para este origen; sus fusiones/cables/tubos/pelos embebidos sí se procesan
                # más abajo, con cualquier referencia a este n_id ya redirigida por
                # `alias_service.resolver_referencia`.
                contadores.leidas += 1
                if alias_botella.accion == alias_service.ACCION_FUSIONAR:
                    await registrar_evento(
                        sesion,
                        corrida_id,
                        arbol.botella.n_id,
                        arbol.botella.clase,
                        "ALIAS_FUSIONADA",
                        f"id_cromo_destino={alias_botella.id_cromo_destino}",
                    )
                else:
                    await registrar_evento(
                        sesion, corrida_id, arbol.botella.n_id, arbol.botella.clase, "ALIAS_IGNORADA"
                    )
            else:
                accion_botella = await upsert_versionado(sesion, CromoBotella, arbol.botella, _BOTELLA_CAMPOS)
                contadores.leidas += 1
                contadores.contar(accion_botella)
                if accion_botella in ("CREADA", "ACTUALIZADA"):
                    # "nombre" no está en _BOTELLA_CAMPOS (ver comentario ahí): una corrección
                    # manual vía PATCH /api/infra/botellas/{n_id}/nombre marca
                    # nombre_editado_manual=True para que la próxima corrida no la pise. Ya está
                    # en el identity map (lo acaba de tocar upsert_versionado), sin round-trip extra.
                    fila_botella = await sesion.get(CromoBotella, arbol.botella.n_id)
                    if accion_botella == "CREADA" or not fila_botella.nombre_editado_manual:
                        fila_botella.nombre = arbol.botella.nombre
                await registrar_evento(
                    sesion, corrida_id, arbol.botella.n_id, arbol.botella.clase, accion_botella
                )

            for fusion in arbol.fusiones:
                fusion.botella_n_id = alias_service.resolver_referencia(fusion.botella_n_id, alias_por_origen)
                await upsert_simple(sesion, CromoFusion, fusion, _FUSION_CAMPOS)

            for cable in arbol.cables:
                # Duplicación deliberada (§6.1): el mismo cable llega una vez por cada botella extremo.
                # El segundo arribo es un upsert sin cambios — control de consistencia gratuito.
                cable.extremo_a_n_id = alias_service.resolver_referencia(cable.extremo_a_n_id, alias_por_origen)
                cable.extremo_b_n_id = alias_service.resolver_referencia(cable.extremo_b_n_id, alias_por_origen)
                accion_cable = await upsert_versionado(sesion, CromoCable, cable, CABLE_CAMPOS)
                contadores.leidas += 1
                contadores.contar(accion_cable)
                await registrar_evento(sesion, corrida_id, cable.n_id, CLASE_CABLE, accion_cable)

            for tubo in arbol.tubos:
                await upsert_simple(sesion, CromoTubo, tubo, TUBO_CAMPOS)
            for pelo in arbol.pelos:
                await upsert_simple(sesion, CromoPelo, pelo, PELO_CAMPOS)

            for error in arbol.errores:
                contadores.errores += 1
                await registrar_evento(sesion, corrida_id, error.n_id, error.clase, "ERROR", error.motivo)
    except Exception as exc:  # noqa: BLE001 - tolerancia deliberada: un objeto no aborta la página
        contadores.errores += 1
        n_id = obj.get("n_id") or obj.get("id")
        logger.error("action=cromo_ingesta evento=error_botella n_id=%s error=%s", n_id, exc)
        await registrar_evento(sesion, corrida_id, n_id, obj.get("class"), "ERROR", str(exc))


async def fase_botellas(
    cliente: CromoClient,
    sesion: AsyncSession,
    corrida: CromoIngestaCorrida,
    contadores: ContadoresCorrida,
    *,
    psize: int,
    max_paginas: Optional[int],
    clases: Iterable[int],
    alias_por_origen: Optional[dict[int, AliasBotella]] = None,
) -> None:
    """FASE 3 · BOTELLAS: botellas + fusiones + cables/tubos/pelos embebidos en cada una."""
    await _registrar_inicio_fase(sesion, corrida.id, "BOTELLAS", "Barrido de botellas con árbol completo")
    filtro = ",".join(str(c) for c in clases)
    numero_pagina = 0
    async for pagina in cliente.iterar_coleccion(
        filtro, psize=psize, show=["SHOW", "REL_ATTRIBUTE", "TIME"], max_paginas=max_paginas
    ):
        numero_pagina += 1
        objetos = pagina.get("response") or pagina.get("data") or []
        for obj in objetos:
            await _procesar_botella_completa(sesion, corrida.id, obj, contadores, alias_por_origen=alias_por_origen)
        sincronizar_contadores(corrida, contadores)
        await _registrar_pagina(sesion, corrida.id, "BOTELLAS", numero_pagina, pagina, contadores)
        await sesion.commit()
        if await _fue_cancelada_externamente(sesion, corrida.id):
            raise _CorridaCancelada()


_RECONCILIACIONES: tuple[tuple[str, int, str], ...] = (
    (
        "extremo_a de cable sin botella",
        CLASE_CABLE,
        """
        SELECT n_id FROM app.cromo_cables c
        WHERE extremo_a_n_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM app.cromo_botellas b WHERE b.n_id = c.extremo_a_n_id)
        """,
    ),
    (
        "extremo_b de cable sin botella",
        CLASE_CABLE,
        """
        SELECT n_id FROM app.cromo_cables c
        WHERE extremo_b_n_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM app.cromo_botellas b WHERE b.n_id = c.extremo_b_n_id)
        """,
    ),
    (
        "tubo sin cable",
        129,
        """
        SELECT n_id FROM app.cromo_tubos t
        WHERE NOT EXISTS (SELECT 1 FROM app.cromo_cables c WHERE c.n_id = t.cable_n_id)
        """,
    ),
    (
        "pelo sin tubo",
        130,
        """
        SELECT n_id FROM app.cromo_pelos p
        WHERE NOT EXISTS (SELECT 1 FROM app.cromo_tubos t WHERE t.n_id = p.tubo_n_id)
        """,
    ),
    (
        "fusión sin botella",
        132,
        """
        SELECT n_id FROM app.cromo_fusiones f
        WHERE f.botella_n_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM app.cromo_botellas b WHERE b.n_id = f.botella_n_id)
        """,
        # `botella_n_id IS NULL` es la norma para fusiones del barrido directo (Etapa 8, filter=132):
        # no traen `parent`, así que NULL no es una referencia colgada, es la forma esperada del dato.
    ),
)


async def fase_reconciliacion(sesion: AsyncSession, corrida: CromoIngestaCorrida, contadores: ContadoresCorrida) -> None:
    """FASE 5 · RECONCILIACIÓN: detecta referencias cruzadas colgadas (sin FK dura, ver Etapa 2).

    No repara nada — sólo reporta. Un evento agregado por tipo de relación, no uno por fila, para no
    inflar `cromo_ingesta_eventos` en un universo con muchas referencias colgadas.
    """
    await _registrar_inicio_fase(sesion, corrida.id, "RECONCILIACION", "Detección de referencias colgadas")
    for descripcion, clase, sql in _RECONCILIACIONES:
        filas = (await sesion.execute(text(sql))).scalars().all()
        if not filas:
            continue
        contadores.refs_colgadas += len(filas)
        await registrar_evento(
            sesion,
            corrida.id,
            None,
            clase,
            "REF_COLGADA",
            f"{descripcion}: {len(filas)} fila(s), ejemplos n_id={filas[:10]}",
        )
    sincronizar_contadores(corrida, contadores)
    await sesion.commit()


_SQL_PELOS_SIN_MATCH = text(
    """
    SELECT p.n_id, p.servicio_numero
    FROM app.cromo_pelos p
    WHERE p.servicio_numero IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM app.cromo_servicio_match m
          WHERE m.pelo_n_id = p.n_id AND m.servicio_numero = p.servicio_numero
      )
    """
)

_SQL_BUSCAR_SERVICIO = text(
    """
    SELECT id FROM app.servicios
    WHERE servicio_id = :numero OR numero_primer_servicio = :numero OR :numero = ANY(alias_ids)
    LIMIT 1
    """
)

# `ON CONFLICT DO NOTHING` sin nombrar índice a propósito: `servicio_id` y `numero_primer_servicio`
# son DOS unique constraints independientes sobre la misma tabla, y acá se inserta el mismo valor en
# ambas columnas — cualquiera de los dos puede disparar el conflicto (ej. otra sesión/corrida ganó la
# carrera de creación para el mismo número). Sin `DO NOTHING` sobre un índice puntual, absorbe
# cualquiera de los dos en vez de acoplarse al nombre de uno.
_SQL_CREAR_PLACEHOLDER_SERVICIO = text(
    """
    INSERT INTO app.servicios (servicio_id, numero_primer_servicio, categoria, origen_datos, estado_servicio)
    VALUES (:numero, :numero, 0, :origen::app.servicio_origen_datos, 'DESCONOCIDO')
    ON CONFLICT DO NOTHING
    RETURNING id
    """
)


async def _resolver_o_crear_servicio(
    sesion: AsyncSession, numero: str, cache: dict[str, Optional[int]]
) -> tuple[Optional[int], bool]:
    """Resuelve `servicio_id` para `numero`. Devuelve `(servicio_id, fue_creado_ahora)`.

    Tres capas, en orden:
    1. Cache en memoria de ESTA corrida (`numero -> servicio_id`) — evita repetir la consulta o el
       intento de creación para números que se repiten entre muchos pelos (hallazgo real: un mismo
       número puede aparecer en cientos de pelos distintos). Sin esto, una corrida con miles de
       pendientes reintentaría crear el MISMO placeholder cientos de veces.
    2. Búsqueda real (`_SQL_BUSCAR_SERVICIO`) — cubre tanto servicios reales como placeholders ya
       creados por una corrida ANTERIOR o por `scripts/cromo_backfill_placeholders_servicios.py`.
    3. Si no existe y `numero` es plausible (`es_numero_servicio_plausible`, 4-6 dígitos), intenta
       crear un placeholder con `INSERT ... ON CONFLICT DO NOTHING RETURNING id`. Si el INSERT no
       devuelve fila (otra sesión ganó la carrera — otra corrida solapada, o este mismo backfill
       corriendo en paralelo), se relee con `_SQL_BUSCAR_SERVICIO` para tomar el id de quien ganó. No
       es un error: es el resultado esperado de una carrera legítima.

    Deliberadamente NO usa un advisory lock (patrón ya establecido en
    `core/services/camara_hierarchy_service.py` para la jerarquía Cámara/Botella): acá el `INSERT ...
    ON CONFLICT` resuelve la carrera en el momento exacto del intento, sin retener nada por más
    tiempo. Un advisory lock transaccional se libera recién al COMMIT/ROLLBACK final de
    `fase_servicios` — con miles de pendientes en una corrida, retendría el lock de un número por toda
    la duración de la fase, bloqueando una corrida concurrente mucho más de lo necesario.
    """
    if numero in cache:
        return cache[numero], False

    fila = (await sesion.execute(_SQL_BUSCAR_SERVICIO, {"numero": numero})).first()
    if fila:
        cache[numero] = fila[0]
        return fila[0], False

    if not cromo_parser.es_numero_servicio_plausible(numero):
        cache[numero] = None
        return None, False

    creado = (
        await sesion.execute(
            _SQL_CREAR_PLACEHOLDER_SERVICIO,
            {"numero": numero, "origen": ServicioOrigenDatos.INFERIDO_CROMO.value},
        )
    ).first()
    if creado:
        cache[numero] = creado[0]
        return creado[0], True

    # Perdió la carrera de creación: otra sesión ya comiteó una fila para este número.
    fila = (await sesion.execute(_SQL_BUSCAR_SERVICIO, {"numero": numero})).first()
    cache[numero] = fila[0] if fila else None
    return cache[numero], False


async def fase_servicios(sesion: AsyncSession, corrida: CromoIngestaCorrida, contadores: ContadoresCorrida) -> None:
    """FASE 6 · SERVICIOS: matchea `cromo_pelos.servicio_numero` contra `app.servicios`.

    Match exacto contra `servicio_id`, `numero_primer_servicio` o `alias_ids` (método
    REGEX_EXACTO). Se deja constancia por cada pelo con servicio parseado, matchee o no.

    Desde 2026-08-14: si `servicio_numero` no matchea NINGÚN `Servicio` existente y tiene 4-6
    dígitos (heurística de plausibilidad, ver `core/services/cromo/parser.py::
    es_numero_servicio_plausible` y docs/decisiones.md — descarta basura de 1-3 dígitos y ruido de
    8+ sin perder servicios reales), se crea un `Servicio` placeholder (`categoria=0`,
    `origen_datos=INFERIDO_CROMO`) para que el pelo quede matcheado igual. Un futuro ingest real
    por Excel lo enriquece vía el `ON CONFLICT (numero_primer_servicio) DO UPDATE` ya existente en
    `api/app/routes/servicios.py::ingest_servicios` (mismo `numero_primer_servicio`), que también
    re-etiqueta `origen_datos=INGEST_EXCEL` al enriquecerlo.

    `metodo`/`confianza` de `CromoServicioMatch` NO distinguen "matchee contra un Servicio real" de
    "matchee contra un placeholder recién creado" — la procedencia real/placeholder es una propiedad
    de `Servicio.origen_datos`, no de cada match (se consulta con un join trivial).
    """
    await _registrar_inicio_fase(sesion, corrida.id, "SERVICIOS", "Matching de servicio_numero contra app.servicios")
    pendientes = (await sesion.execute(_SQL_PELOS_SIN_MATCH)).all()
    cache_servicio_id: dict[str, Optional[int]] = {}
    placeholders_creados = 0
    for pelo_n_id, servicio_numero in pendientes:
        try:
            async with sesion.begin_nested():
                servicio_id, fue_creado = await _resolver_o_crear_servicio(sesion, servicio_numero, cache_servicio_id)
                if fue_creado:
                    placeholders_creados += 1
                    await registrar_evento(
                        sesion,
                        corrida.id,
                        pelo_n_id,
                        130,
                        "PLACEHOLDER_CREADO",
                        f"servicio_numero={servicio_numero} servicio_id={servicio_id}",
                    )
                sesion.add(
                    CromoServicioMatch(
                        pelo_n_id=pelo_n_id,
                        servicio_numero=servicio_numero,
                        servicio_id=servicio_id,
                        metodo="REGEX_EXACTO",
                        confianza=100 if servicio_id else 0,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - tolerancia deliberada: un match no aborta el resto
            contadores.errores += 1
            logger.error(
                "action=cromo_ingesta evento=error_match pelo_n_id=%s servicio_numero=%s error=%s",
                pelo_n_id,
                servicio_numero,
                exc,
            )
            await registrar_evento(sesion, corrida.id, pelo_n_id, 130, "ERROR", str(exc))
    if placeholders_creados:
        logger.info(
            "action=cromo_ingesta evento=placeholders_creados corrida_id=%s cantidad=%d",
            corrida.id,
            placeholders_creados,
        )
    sincronizar_contadores(corrida, contadores)
    await sesion.commit()


async def ejecutar_ingesta(
    cliente: CromoClient,
    sesion: AsyncSession,
    *,
    usuario: str,
    psize: Optional[int] = None,
    max_paginas: Optional[int] = None,
    clases: Optional[Iterable[int]] = None,
) -> CromoIngestaCorrida:
    """Crea la corrida y corre las 5 fases de punta a punta, en la misma sesión/tarea.

    Conveniencia para scripts/tests/uso síncrono. El endpoint web (Etapa 4) necesita el `corrida_id`
    de inmediato para responder, así que llama `iniciar_corrida()` y `continuar_corrida()` por separado
    (esta función es sólo azúcar sintáctica sobre esas dos).
    """
    psize_final = psize if psize is not None else get_cromo_config().psize_default
    if psize_final not in PSIZE_PERMITIDOS:
        raise ValueError(f"psize={psize_final} no es válido. Valores permitidos: {sorted(PSIZE_PERMITIDOS)}")
    clases_final = tuple(clases) if clases is not None else CLASES_BOTELLA

    corrida = await iniciar_corrida(
        sesion, usuario=usuario, psize=psize_final, max_paginas=max_paginas, clases=clases_final
    )
    return await continuar_corrida(
        cliente, sesion, corrida.id, psize=psize_final, max_paginas=max_paginas, clases=clases_final
    )


async def continuar_corrida(
    cliente: CromoClient,
    sesion: AsyncSession,
    corrida_id: int,
    *,
    psize: int,
    max_paginas: Optional[int],
    clases: Iterable[int],
) -> CromoIngestaCorrida:
    """Corre las 6 fases sobre una corrida ya creada (`iniciar_corrida()`), en su propia sesión.

    Pensado para lanzarse en una tarea de background separada del request que la disparó — por eso
    recibe `corrida_id`, no el objeto ORM (que pertenece a la sesión donde se creó, no a esta).
    Cierra la corrida como OK, OK_CON_ERRORES, CANCELADA o FALLIDA. Nunca lanza: una falla inesperada
    se registra como FALLIDA en la propia corrida en vez de propagar la excepción al llamador.
    """
    clases_final = tuple(clases)
    contadores = ContadoresCorrida()
    corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
    if corrida is None:
        raise ValueError(f"No existe la corrida {corrida_id}")

    try:
        totales = await fase_conteo(cliente)
        corrida.total_objetivo = sum(totales.get(c, 0) for c in (*clases_final, CLASE_CABLE, CLASE_FUSION))
        await registrar_evento(
            sesion,
            corrida.id,
            None,
            None,
            "INICIO",
            json.dumps({"corrida_id": corrida.id, "total_objetivo": corrida.total_objetivo, "clases": list(clases_final)}),
        )
        await sesion.commit()

        # Una sola carga en memoria para toda la corrida (nunca una query por objeto) — ver
        # `alias_service.cargar_alias_vigentes`. Una corrida es una unidad snapshot-consistente
        # (nunca se resume desde una página intermedia), así que un alias creado mientras esta
        # corrida ya está en curso recién aplica en la corrida siguiente.
        alias_por_origen = await alias_service.cargar_alias_vigentes(sesion)

        await fase_cables(
            cliente, sesion, corrida, contadores, psize=psize, max_paginas=max_paginas, alias_por_origen=alias_por_origen
        )
        await fase_botellas(
            cliente,
            sesion,
            corrida,
            contadores,
            psize=psize,
            max_paginas=max_paginas,
            clases=clases_final,
            alias_por_origen=alias_por_origen,
        )
        await fase_fusiones(
            cliente, sesion, corrida, contadores, psize=psize, max_paginas=max_paginas, alias_por_origen=alias_por_origen
        )
        await fase_reconciliacion(sesion, corrida, contadores)
        await fase_servicios(sesion, corrida, contadores)

        estado_final = "OK" if contadores.errores == 0 else "OK_CON_ERRORES"
    except _CorridaCancelada:
        # No es una falla: alguien pidió cancelar (POST .../cancelar) y el chequeo cooperativo entre
        # páginas la interrumpió al cerrar la página en curso, tal como especifica el diseño.
        await sesion.rollback()
        logger.info("action=cromo_ingesta evento=corrida_cancelada corrida_id=%s", corrida.id)
        estado_final = "CANCELADA"
    except Exception as exc:  # noqa: BLE001 - una falla inesperada cierra la corrida, no propaga
        # Una excepción no capturada por los savepoints de cada fase deja la transacción de la sesión
        # abortada (p.ej. un error de flush fuera de un begin_nested()). Hay que rollback-earla antes de
        # tocar `corrida` de nuevo, o hasta leer `corrida.id` revienta con PendingRollbackError.
        await sesion.rollback()
        logger.error("action=cromo_ingesta evento=corrida_fallida corrida_id=%s error=%s", corrida.id, exc)
        estado_final = "FALLIDA"

    corrida.estado = estado_final
    corrida.finalizada_at = datetime.now(timezone.utc)
    sincronizar_contadores(corrida, contadores)
    await registrar_evento(
        sesion,
        corrida.id,
        None,
        None,
        "RESUMEN",
        json.dumps(
            {
                "estado": estado_final,
                "leidas": contadores.leidas,
                "creadas": contadores.creadas,
                "actualizadas": contadores.actualizadas,
                "sin_cambios": contadores.sin_cambios,
                "errores": contadores.errores,
                "refs_colgadas": contadores.refs_colgadas,
            }
        ),
    )
    await sesion.commit()
    logger.info(
        "action=cromo_ingesta evento=corrida_finalizada corrida_id=%s estado=%s leidas=%d creadas=%d actualizadas=%d sin_cambios=%d errores=%d refs_colgadas=%d",
        corrida.id,
        estado_final,
        contadores.leidas,
        contadores.creadas,
        contadores.actualizadas,
        contadores.sin_cambios,
        contadores.errores,
        contadores.refs_colgadas,
    )
    return corrida


__all__ = [
    "CABLE_CAMPOS",
    "CLASE_CABLE",
    "CLASES_BOTELLA",
    "CLASES_CONTEO",
    "ContadoresCorrida",
    "PELO_CAMPOS",
    "TUBO_CAMPOS",
    "continuar_corrida",
    "ejecutar_ingesta",
    "fase_botellas",
    "fase_cables",
    "fase_conteo",
    "fase_reconciliacion",
    "fase_servicios",
    "iniciar_corrida",
    "registrar_evento",
    "sincronizar_contadores",
    "upsert_forzado",
    "upsert_simple",
    "upsert_versionado",
]
