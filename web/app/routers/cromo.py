# Nombre de archivo: cromo.py
# Ubicación de archivo: web/app/routers/cromo.py
# Descripción: Rutas de Cromo: consultas de inventario, Botellas, huérfanos, inconsistencias y árbitro

from __future__ import annotations

import asyncio
import io
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.services.botella_recompute_queue import (
    encolar_recalculo_duplicados_botellas,
    guardar_cache_duplicados,
    leer_cache_duplicados,
)

from ..comun import (
    _CROMO_WORKER_RUN_URL,
    _encolar_arbitro,
    _es_destino_slack_valido,
    _marcar_corrida_fallida,
    _serializar_bloqueos,
    _serializar_cromo_corrida,
    _serializar_pelo_semilla,
    _servicio_existe,
    _validar_csrf,
    logger,
)
from ..dependencias import UsuarioSesion, usuario_admin, usuario_sesion
from ..errores import (
    DatoInvalido,
    ErrorDeDominio,
    NoEncontrado,
    error_interno,
    error_servicio_externo,
    nueva_ref,
)

router = APIRouter(dependencies=[Depends(usuario_sesion)])


# ── Endpoints: verificador de servicios sobre inventario Cromo (Etapa 6) ─────
# Contrato: docs/Doc Privada/ingesta_cromo.md §8.2. Sólo lectura, cualquier usuario autenticado
# (no requiere rol admin: a diferencia de disparar una ingesta, consultar el inventario ya ingerido
# no es una operación administrativa).


def _serializar_servicio_encontrado(servicio: Any) -> dict[str, Any]:
    return {
        "servicio_id": servicio.servicio_id,
        "servicio_id_externo": servicio.servicio_id_externo,
        "numero_primer_servicio": servicio.numero_primer_servicio,
        "nombre_cliente": servicio.nombre_cliente,
        "cliente": servicio.cliente,
        "estado_servicio": servicio.estado_servicio,
        "categoria": servicio.categoria,
        "tipo_servicio": servicio.tipo_servicio,
        "pelo_n_id": servicio.pelo_n_id,
        "servicio_numero_match": servicio.servicio_numero_match,
        "metodo": servicio.metodo,
    }


@router.get("/api/infra/cromo/cables/{cable_n_id}/servicios")
async def cromo_verificador_por_cable_web(cable_n_id: int) -> JSONResponse:
    """Servicios que pasan por un cable entero (cualquiera de sus tubos/pelos)."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_por_cable
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_por_cable(sesion, cable_n_id)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc

    return JSONResponse(
        {
            "cable_n_id": resultado.cable_n_id,
            "nombre": resultado.nombre,
            "capacidad": resultado.capacidad,
            "extremo_a_nombre": resultado.extremo_a_nombre,
            "extremo_b_nombre": resultado.extremo_b_nombre,
            "servicios": [_serializar_servicio_encontrado(s) for s in resultado.servicios],
        }
    )


@router.get("/api/infra/cromo/tubos/{tubo_n_id}/servicios")
async def cromo_verificador_por_tubo_web(tubo_n_id: int) -> JSONResponse:
    """Servicios que pasan por un tubo/buffer específico dentro de un cable."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_por_tubo
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_por_tubo(sesion, tubo_n_id)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc

    return JSONResponse(
        {
            "tubo_n_id": resultado.tubo_n_id,
            "cable_n_id": resultado.cable_n_id,
            "orden": resultado.orden,
            "nombre_color": resultado.nombre_color,
            "servicios": [_serializar_servicio_encontrado(s) for s in resultado.servicios],
        }
    )


@router.get("/api/infra/cromo/botellas/{botella_n_id}/servicios")
async def cromo_verificador_por_botella_web(botella_n_id: int) -> JSONResponse:
    """Servicios que pasan por los cables que tienen esta botella como uno de sus extremos, más el
    listado de esos cables (id, nombre, cantidad de servicios) para la tarjeta "Cables asociados"
    del detalle de Botella en el Verificador."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_por_botella
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_por_botella(sesion, botella_n_id)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc

    return JSONResponse(
        {
            "botella_n_id": resultado.botella_n_id,
            "nombre": resultado.nombre,
            "clase": resultado.clase,
            "localidad": resultado.localidad,
            "servicios": [_serializar_servicio_encontrado(s) for s in resultado.servicios],
            "cables": [
                {"n_id": c.n_id, "nombre": c.nombre, "cantidad_servicios": c.cantidad_servicios}
                for c in resultado.cables
            ],
        }
    )


# ── Endpoints: servicios ÚNICOS por cable/buffer + resolución de cable + refresco PROV on-demand
# (Task 10, plan "Corrección ingresos + Servicios", 2026-09-23) ─────────────────────────────────
# Vista COMPLEMENTARIA a las tres rutas de arriba (`/cables/{id}/servicios`, `/tubos/{id}/servicios`,
# `/botellas/{id}/servicios`): esas devuelven una fila por PELO (la tabla del Verificador, con su
# columna "Pelo" — varios pelos por servicio es normal, no un defecto). Estas cuatro rutas devuelven
# IDs de servicio ÚNICOS (agregados por `s.id`, `servicios_unicos_por_cable`/`_por_tubo` de la
# Task 1) — dos vistas legítimas del mismo dato que conviven; rutas nuevas, no una extensión de las
# de arriba (no las tocan).


class CromoServicioUnicoFrescuraModel(BaseModel):
    """Estado de sincronización PROV de un `ServicioUnico` puntual (Task 7:
    `core/services/prov/frescura.py`). `ultima_sincronizacion_prov` viaja como string ISO 8601 (no
    `None` salvo que el servicio nunca sincronizó con éxito)."""

    ultima_sincronizacion_prov: Optional[datetime] = Field(default=None)
    antiguedad_horas: Optional[float] = Field(default=None)
    vencida: bool


class CromoServicioUnicoResponseModel(BaseModel):
    """Un servicio único (Task 1: `ServicioUnico`) + su frescura PROV — forma que devuelven las
    tres rutas de servicios únicos (por cable, por buffer, y tras el refresco). `cantidad_pelos`/
    `pelos_n_ids` no son ruido: el ID es único, pero cuántas fibras ocupa es información real."""

    servicio_id: int
    servicio_id_externo: str
    numero_primer_servicio: Optional[str] = None
    nombre_cliente: Optional[str] = None
    cliente: Optional[str] = None
    estado_servicio: Optional[str] = None
    tipo_servicio: Optional[str] = None
    pelos_n_ids: list[int]
    cantidad_pelos: int
    numeros_en_pelo: list[str]
    metodos: list[str]
    frescura: CromoServicioUnicoFrescuraModel


class CromoBufferIdentidadModel(BaseModel):
    """Identidad de un buffer/tubo — `numero` es el 1-indexado que cuenta el técnico (`orden + 1`,
    mismo criterio que `cable_info.py::resolver_tubo_por_numero`)."""

    numero: int
    orden: int
    nombre_color: Optional[str] = None


class CromoRefrescoProvFallidoModel(BaseModel):
    servicio_id_externo: str
    motivo: Optional[str] = None


class CromoRefrescoProvModel(BaseModel):
    """`estado` en {"no_solicitado", "sin_vencidos", "completado", "parcial"}: sólo el POST
    `.../refrescar-prov` dispara un refresco de verdad (puede devolver cualquiera de los últimos
    tres); los dos GET de servicios únicos son de sólo lectura y siempre devuelven
    "no_solicitado" con `fallidos=[]` — no disparan nada."""

    estado: str
    fallidos: list[CromoRefrescoProvFallidoModel] = Field(default_factory=list)


class CromoServiciosUnicosResponseModel(BaseModel):
    cable_n_id: int
    cable_nombre: Optional[str] = None
    buffer: Optional[CromoBufferIdentidadModel] = None
    datos_al: datetime
    servicios: list[CromoServicioUnicoResponseModel]
    refresco_prov: CromoRefrescoProvModel


class CromoCableIdentidadResponseModel(BaseModel):
    n_id: int
    nombre: Optional[str] = None
    capacidad: Optional[str] = None


class CromoServiciosUnicosRefrescarRequestModel(BaseModel):
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


# ── Modelos de error, sólo para documentar `/docs` (Fix round 1, Minor: `response_model` cubre el
# 200 feliz pero `responses=` es la mitad que faltaba de la motivación original — que estas 4 rutas
# sí documenten en OpenAPI, la única desventaja real de vivir acá y no en `api/app/routes/`). Igual
# que el resto de esta sección, no se valida en runtime (los handlers siguen devolviendo
# `JSONResponse` a mano) — sólo alimenta el schema que ve `/docs`.


class CromoNoEncontradoModel(BaseModel):
    """`GET /cables/resolver` cuando `q` no matchea ningún cable vigente — no lleva `error` (a
    diferencia de las otras dos formas de 404 de acá abajo) porque no hay una excepción de dominio
    detrás, sólo "0 candidatos"."""

    codigo: Literal["NO_ENCONTRADO"] = "NO_ENCONTRADO"


class CromoCableNoEncontradoModel(BaseModel):
    """404 de los dos GET de servicios únicos por cable y del POST de refresco — el cable no existe
    ni por fila propia ni por referencia colgada (`ObjetoNoEncontrado`)."""

    codigo: Literal["NO_ENCONTRADO"] = "NO_ENCONTRADO"
    error: str


class CromoBufferNoEncontradoModel(BaseModel):
    """404 propio del GET por buffer — `total_buffers` en vez de `error`, para que el cliente pueda
    orientar al técnico ("el cable tiene 6 buffers, pediste B9")."""

    codigo: Literal["NO_ENCONTRADO"] = "NO_ENCONTRADO"
    total_buffers: int


class CromoAmbiguoModel(BaseModel):
    """409 de `GET /cables/resolver` — 2+ cables vigentes con el mismo nombre (hay al menos 2 pares
    reales conocidos, "F-ALV-2335"/"F-LEM-11-A"); la ambigüedad se hace explícita en vez de elegir
    arbitrariamente."""

    codigo: Literal["AMBIGUO"] = "AMBIGUO"
    candidatos: list[CromoCableIdentidadResponseModel]


class CromoErrorModel(BaseModel):
    """Forma genérica `{"error": "..."}` — CSRF inválido (403) y PROV no configurado (502) del
    POST de refresco."""

    error: str


async def _frescura_por_servicio(sesion: Any, servicio_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Frescura PROV cruda (timestamp + antigüedad + vencida) por `servicio_id`, para el detalle de
    cada `ServicioUnico` en la respuesta REST — a diferencia de `servicios_vencidos` (Task 7), que
    sólo devuelve el subconjunto vencido (un `set[int]`) sin el timestamp real. Reusa
    `horas_frescura()` para el umbral en vez de un segundo valor hardcodeado que se pueda
    desincronizar del real."""
    from datetime import timedelta, timezone

    from sqlalchemy import text

    from core.services.prov.frescura import horas_frescura

    if not servicio_ids:
        return {}
    ahora = datetime.now(timezone.utc)
    corte = ahora - timedelta(hours=horas_frescura())
    filas = (
        await sesion.execute(
            text(
                "SELECT servicio_id, ultima_sincronizacion_ok FROM app.servicios_sync_prov "
                "WHERE servicio_id = ANY(:ids ::integer[])"
            ),
            {"ids": servicio_ids},
        )
    ).all()
    ultimas = {fila[0]: fila[1] for fila in filas}
    resultado: dict[int, dict[str, Any]] = {}
    for servicio_id in servicio_ids:
        ultima = ultimas.get(servicio_id)
        if ultima is not None and ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        antiguedad = (ahora - ultima).total_seconds() / 3600 if ultima is not None else None
        vencida = ultima is None or ultima < corte
        resultado[servicio_id] = {
            "ultima_sincronizacion_prov": ultima.isoformat() if ultima is not None else None,
            "antiguedad_horas": antiguedad,
            "vencida": vencida,
        }
    return resultado


def _serializar_servicio_unico(servicio: Any, frescura: dict[str, Any]) -> dict[str, Any]:
    return {
        "servicio_id": servicio.servicio_id,
        "servicio_id_externo": servicio.servicio_id_externo,
        "numero_primer_servicio": servicio.numero_primer_servicio,
        "nombre_cliente": servicio.nombre_cliente,
        "cliente": servicio.cliente,
        "estado_servicio": servicio.estado_servicio,
        "tipo_servicio": servicio.tipo_servicio,
        "pelos_n_ids": list(servicio.pelos_n_ids),
        "cantidad_pelos": servicio.cantidad_pelos,
        "numeros_en_pelo": list(servicio.numeros_en_pelo),
        "metodos": list(servicio.metodos),
        "frescura": frescura,
    }


async def _identidad_cable(sesion: Any, cable_n_id: int) -> Optional[str]:
    """Nombre del cable para la identidad de la respuesta — `None` si el cable sólo se conoce por
    referencia colgada (pelos con servicio matcheado sin fila propia en `cromo_cables`, ver
    docstring de `servicios_unicos_por_cable`)."""
    from db.models.cromo import CromoCable

    cable = await sesion.get(CromoCable, cable_n_id)
    return cable.nombre if cable is not None else None


async def _resolver_cable_por_texto(sesion: Any, texto: str) -> list[tuple[int, Optional[str], Optional[str]]]:
    """Gemela async de `modules/slack_baneo_notifier/cable_info.py::buscar_cable_por_n_id_o_nombre`
    (que usa `Session` síncrona, pensada para el listener de Slack) contra `AsyncSession` — mismo
    criterio de resolución (n_id exacto si `texto` es puramente numérico, si no match exacto case-
    insensitive por `nombre`, sólo cables vigentes). Devuelve una lista para que el caller distinga
    0 (no encontrado) de 2+ (los duplicados reales conocidos, ej. "F-ALV-2335"/"F-LEM-11-A")."""
    from sqlalchemy import text

    texto_limpio = texto.strip()
    if texto_limpio.isdigit():
        filas = (
            await sesion.execute(
                text("SELECT n_id, nombre, capacidad FROM app.cromo_cables WHERE vigente = true AND n_id = :n_id"),
                {"n_id": int(texto_limpio)},
            )
        ).all()
    else:
        filas = (
            await sesion.execute(
                text(
                    "SELECT n_id, nombre, capacidad FROM app.cromo_cables "
                    "WHERE vigente = true AND lower(nombre) = lower(:nombre)"
                ),
                {"nombre": texto_limpio},
            )
        ).all()
    return [(fila[0], fila[1], fila[2]) for fila in filas]


async def _resolver_buffer_por_numero(
    sesion: Any, cable_n_id: int, numero: int
) -> tuple[Optional[tuple[int, int, Optional[str]]], int]:
    """Gemela async de `resolver_tubo_por_numero`/`contar_buffers_cable`
    (`modules/slack_baneo_notifier/cable_info.py`, síncronas) — `numero` es 1-indexado como lo
    cuenta el técnico, mapea a `cromo_tubos.orden = numero - 1` (confirmado con el usuario
    2026-08-13). Devuelve `(tubo_n_id, orden, nombre_color)` o `None` si no existe, más el total de
    buffers vigentes del cable (para que el 404 pueda orientar con `total_buffers`)."""
    from sqlalchemy import text

    fila_tubo = (
        await sesion.execute(
            text(
                "SELECT n_id, orden, nombre_color FROM app.cromo_tubos "
                "WHERE cable_n_id = :cable_n_id AND vigente = true AND orden = :orden"
            ),
            {"cable_n_id": cable_n_id, "orden": numero - 1},
        )
    ).first()
    total_buffers = (
        await sesion.execute(
            text("SELECT count(*) FROM app.cromo_tubos WHERE cable_n_id = :cable_n_id AND vigente = true"),
            {"cable_n_id": cable_n_id},
        )
    ).scalar_one()
    tubo = (fila_tubo[0], fila_tubo[1], fila_tubo[2]) if fila_tubo else None
    return tubo, int(total_buffers)


@dataclass(slots=True)
class _ResultadoRefrescoLote:
    """Resultado directo de `_ejecutar_refresco_prov_lote` — a diferencia de
    `refrescar_servicios_vencidos` (Task 9, fire-and-forget pensado para el hilo de Slack: devuelve
    `None` y postea el resultado a un canal), esta ruta REST corre ya dentro del loop async de
    FastAPI y puede simplemente awaitear el lote y devolver el resultado en la respuesta HTTP."""

    fallidos: list[dict[str, Optional[str]]]


async def _ejecutar_refresco_prov_lote(pendientes: list[Any]) -> _ResultadoRefrescoLote:
    """Corre el refresco PROV de `pendientes` (los `ServicioUnico` ya filtrados a vencidos por el
    caller) de forma síncrona con la petición HTTP — decisión de diseño de la Task 10 (ver reporte):
    reusa el tope/concurrencia/deadline/orden de prioridad y el worker por-servicio de la Task 9
    (`modules/slack_baneo_notifier/refresco_prov.py`: `priorizar_por_antiguedad`/
    `refrescar_un_servicio`, que no tienen ninguna dependencia de Slack) en vez de reimplementar la
    orquestación PROV desde cero, pero NO reusa `refrescar_servicios_vencidos` en sí: esa función
    pública es fire-and-forget, exige `client`/`channel`/`thread_ts` de Slack para postear el
    resultado, y nunca lo devuelve — pensada para encolarse desde el thread síncrono de Slack Bolt
    vía `run_coroutine_threadsafe`. Esta ruta ya corre en el loop de FastAPI (sin ese puente de
    threads) y necesita el resultado directo para la respuesta HTTP, no un canal al que postear."""
    from modules.slack_baneo_notifier.refresco_prov import (
        CONCURRENCIA_MAXIMA,
        DEADLINE_SEGUNDOS,
        TOPE_SERVICIOS_POR_COMANDO,
        ResultadoServicioRefrescado,
        priorizar_por_antiguedad,
        refrescar_un_servicio,
        sincronizar_clientes_de_resultados,
    )
    from core.services.prov.client import get_prov_client

    cliente = get_prov_client()
    ordenados = await priorizar_por_antiguedad(pendientes)
    candidatos = ordenados[:TOPE_SERVICIOS_POR_COMANDO]

    semaforo = asyncio.Semaphore(CONCURRENCIA_MAXIMA)
    resultados: dict[int, Any] = {}

    async def _tarea(servicio: Any) -> None:
        resultados[servicio.servicio_id] = await refrescar_un_servicio(servicio, semaforo, cliente)

    tareas = [asyncio.create_task(_tarea(s)) for s in candidatos]
    try:
        await asyncio.wait_for(asyncio.gather(*tareas, return_exceptions=True), timeout=DEADLINE_SEGUNDOS)
    except asyncio.TimeoutError:
        logger.warning(
            "action=cromo_servicios_unicos_refrescar_prov evento=deadline_alcanzado total=%d", len(candidatos)
        )
    finally:
        for tarea in tareas:
            if not tarea.done():
                tarea.cancel()

    for servicio in candidatos:
        if servicio.servicio_id not in resultados:
            resultados[servicio.servicio_id] = ResultadoServicioRefrescado(
                servicio.servicio_id,
                servicio.servicio_id_externo,
                False,
                "se agotó el tiempo del lote antes de poder intentarlo",
            )

    # Una sola sync de categorías de clientes para el lote, fuera del deadline. Nunca lanza.
    await sincronizar_clientes_de_resultados(resultados.values(), origen="cromo_servicios_unicos_refrescar_prov")

    fallidos = [
        {"servicio_id_externo": r.servicio_id_externo, "motivo": r.motivo_error}
        for r in resultados.values()
        if not r.ok
    ]
    return _ResultadoRefrescoLote(fallidos=fallidos)


@router.get(
    "/api/infra/cromo/cables/resolver",
    response_model=CromoCableIdentidadResponseModel,
    responses={
        404: {"model": CromoNoEncontradoModel, "description": "Ningún cable vigente matchea `q`."},
        409: {
            "model": CromoAmbiguoModel,
            "description": "2+ cables vigentes con el mismo nombre — ambigüedad explícita.",
        },
    },
)
async def cromo_cable_resolver_web(q: str) -> JSONResponse:
    """Resuelve un cable por `n_id` (si `q` es puramente numérico) o por `nombre` exacto case-
    insensitive (si no) — ver `_resolver_cable_por_texto`. 404 si no hay ningún cable vigente con
    ese criterio; 409 explícito (nunca elegir arbitrariamente) si hay 2+ — hay al menos 2 pares de
    nombres duplicados reales conocidos (`F-ALV-2335`, `F-LEM-11-A`) sobre ~32.782 cables."""
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        candidatos = await _resolver_cable_por_texto(sesion, q)

    if not candidatos:
        return JSONResponse({"codigo": "NO_ENCONTRADO"}, status_code=404)
    if len(candidatos) > 1:
        return JSONResponse(
            {
                "codigo": "AMBIGUO",
                "candidatos": [
                    {"n_id": n_id, "nombre": nombre, "capacidad": capacidad} for n_id, nombre, capacidad in candidatos
                ],
            },
            status_code=409,
        )

    n_id, nombre, capacidad = candidatos[0]
    return JSONResponse({"n_id": n_id, "nombre": nombre, "capacidad": capacidad})


@router.get(
    "/api/infra/cromo/cables/{cable_n_id}/servicios-unicos",
    response_model=CromoServiciosUnicosResponseModel,
    responses={
        404: {
            "model": CromoCableNoEncontradoModel,
            "description": "El cable no existe en el inventario ingerido (ni fila propia ni referencia colgada).",
        },
    },
)
async def cromo_servicios_unicos_por_cable_web(cable_n_id: int) -> JSONResponse:
    """IDs de servicio únicos (Task 1: `servicios_unicos_por_cable`) de un cable entero, con
    frescura PROV por servicio (Task 7) — vista complementaria a
    `/api/infra/cromo/cables/{id}/servicios` (arriba), que es por-pelo para la tabla del
    Verificador. Sólo lectura: no dispara ningún refresco (eso es el POST `.../refrescar-prov`, más
    abajo) — `refresco_prov` siempre viaja en "no_solicitado" acá."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_unicos_por_cable
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_unicos_por_cable(sesion, cable_n_id)
            cable_nombre = await _identidad_cable(sesion, cable_n_id)
            frescura = await _frescura_por_servicio(sesion, [s.servicio_id for s in resultado.servicios])
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"codigo": "NO_ENCONTRADO", "error": str(exc)}, status_code=404)

    from datetime import timezone

    return JSONResponse(
        {
            "cable_n_id": cable_n_id,
            "cable_nombre": cable_nombre,
            "buffer": None,
            "datos_al": datetime.now(timezone.utc).isoformat(),
            "servicios": [_serializar_servicio_unico(s, frescura[s.servicio_id]) for s in resultado.servicios],
            "refresco_prov": {"estado": "no_solicitado", "fallidos": []},
        }
    )


@router.get(
    "/api/infra/cromo/cables/{cable_n_id}/buffers/{numero}/servicios-unicos",
    response_model=CromoServiciosUnicosResponseModel,
    responses={
        404: {
            "model": CromoBufferNoEncontradoModel,
            "description": "El cable no tiene ese buffer (`total_buffers` orienta al cliente).",
        },
    },
)
async def cromo_servicios_unicos_por_buffer_web(cable_n_id: int, numero: int) -> JSONResponse:
    """Igual que la ruta anterior, acotado a un buffer humano `B<numero>` puntual (`numero` 1-
    indexado, mapea a `cromo_tubos.orden = numero - 1`, ver `_resolver_buffer_por_numero`). 404 con
    `total_buffers` si el cable no tiene ese buffer — para que el cliente pueda orientar al técnico
    ("el cable tiene 6 buffers, pediste B9")."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_unicos_por_tubo, ResultadoServiciosUnicos
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        tubo, total_buffers = await _resolver_buffer_por_numero(sesion, cable_n_id, numero)
        if tubo is None:
            return JSONResponse({"codigo": "NO_ENCONTRADO", "total_buffers": total_buffers}, status_code=404)
        tubo_n_id, orden, nombre_color = tubo
        cable_nombre = await _identidad_cable(sesion, cable_n_id)
        try:
            resultado = await servicios_unicos_por_tubo(sesion, tubo_n_id)
        except ObjetoNoEncontrado:
            # El tubo existe de verdad (recién resuelto por fila propia arriba) — un buffer sin
            # ningún pelo cargado todavía no es "no encontrado", es un buffer real sin servicios
            # que reportar (el criterio de "no encontrado" de `servicios_unicos_por_tubo` es
            # tolerante a la fila de TUBO faltante, no al revés: acá la fila sí existe).
            resultado = ResultadoServiciosUnicos(cable_n_id=None, tubo_n_id=tubo_n_id, servicios=[])
        frescura = await _frescura_por_servicio(sesion, [s.servicio_id for s in resultado.servicios])

    from datetime import timezone

    return JSONResponse(
        {
            "cable_n_id": cable_n_id,
            "cable_nombre": cable_nombre,
            "buffer": {"numero": numero, "orden": orden, "nombre_color": nombre_color},
            "datos_al": datetime.now(timezone.utc).isoformat(),
            "servicios": [_serializar_servicio_unico(s, frescura[s.servicio_id]) for s in resultado.servicios],
            "refresco_prov": {"estado": "no_solicitado", "fallidos": []},
        }
    )


@router.post(
    "/api/infra/cromo/cables/{cable_n_id}/servicios-unicos/refrescar-prov",
    response_model=CromoServiciosUnicosResponseModel,
    responses={
        403: {"model": CromoErrorModel, "description": "CSRF inválido."},
        404: {
            "model": CromoCableNoEncontradoModel,
            "description": "El cable no existe en el inventario ingerido.",
        },
        502: {"model": CromoErrorModel, "description": "PROV no está configurado en este entorno."},
    },
)
async def cromo_servicios_unicos_refrescar_prov_web(
    request: Request,
    cable_n_id: int,
    body: CromoServiciosUnicosRefrescarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Dispara el refresco PROV (Task 9) de los servicios únicos vencidos de este cable, awaiteado
    dentro del propio request (a diferencia del comando de Slack, fire-and-forget) — ver
    `_ejecutar_refresco_prov_lote`. Responde con el mismo cuerpo que el GET de servicios únicos por
    cable, con `refresco_prov` reflejando el resultado real del lote en vez de "no_solicitado"."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_unicos_por_cable
    from core.services.prov.config import ProvConfigError
    from core.services.prov.frescura import servicios_vencidos
    from db.session import AsyncSessionLocal

    username, _ = usuario
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=cromo_servicios_unicos_refrescar_prov result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_unicos_por_cable(sesion, cable_n_id)
            vencidos = await servicios_vencidos(sesion, [s.servicio_id for s in resultado.servicios])
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"codigo": "NO_ENCONTRADO", "error": str(exc)}, status_code=404)

    pendientes = [s for s in resultado.servicios if s.servicio_id in vencidos]
    if not pendientes:
        refresco_prov: dict[str, Any] = {"estado": "sin_vencidos", "fallidos": []}
    else:
        try:
            lote = await _ejecutar_refresco_prov_lote(pendientes)
        except ProvConfigError as exc:
            return error_servicio_externo(
                "cromo_servicios_unicos_refrescar_prov",
                exc,
                "PROV no está configurado",
                evento="prov_no_configurado",
                cable_n_id=cable_n_id,
            )
        except (HTTPException, ErrorDeDominio):
            raise
        except Exception as exc:
            return error_interno("cromo_servicios_unicos_refrescar_prov", exc, cable_n_id=cable_n_id)
        refresco_prov = {"estado": "completado" if not lote.fallidos else "parcial", "fallidos": lote.fallidos}

    async with AsyncSessionLocal() as sesion:
        resultado_final = await servicios_unicos_por_cable(sesion, cable_n_id)
        cable_nombre = await _identidad_cable(sesion, cable_n_id)
        frescura = await _frescura_por_servicio(sesion, [s.servicio_id for s in resultado_final.servicios])

    from datetime import timezone

    return JSONResponse(
        {
            "cable_n_id": cable_n_id,
            "cable_nombre": cable_nombre,
            "buffer": None,
            "datos_al": datetime.now(timezone.utc).isoformat(),
            "servicios": [
                _serializar_servicio_unico(s, frescura[s.servicio_id]) for s in resultado_final.servicios
            ],
            "refresco_prov": refresco_prov,
        }
    )


def _serializar_pelo_empalme(pelo: Any) -> Optional[dict[str, Any]]:
    if pelo is None:
        return None
    return {
        "n_id": pelo.n_id,
        "cable_n_id": pelo.cable_n_id,
        "cable_nombre": pelo.cable_nombre,
        "tubo_n_id": pelo.tubo_n_id,
        "tubo_color": pelo.tubo_color,
        "numero_pelo": pelo.numero_pelo,
        "orden": pelo.orden,
        "color": pelo.color,
        "servicio_raw": pelo.servicio_raw,
        "servicio_numero": pelo.servicio_numero,
    }


@router.get("/api/infra/cromo/botellas/{botella_n_id}/empalmes")
async def cromo_empalmes_de_botella_web(botella_n_id: int) -> JSONResponse:
    """Empalmes (fusiones) internos de una Botella, aplanados y con Splitters agrupados en una sola
    fila por pelo de origen — para la tabla dinámica de `/infra/cromo/verificador?...&n_id=.../empalmes`.
    Sólo lectura sobre `app.cromo_fusiones` ya ingerido, cualquier usuario autenticado (mismo
    criterio que el resto de `/api/infra/cromo/*`)."""
    from core.services.cromo.empalmes import empalmes_de_botella
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await empalmes_de_botella(sesion, botella_n_id)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc

    return JSONResponse(
        {
            "botella_n_id": resultado.botella_n_id,
            "nombre": resultado.nombre,
            "cables": [
                {"n_id": c.n_id, "nombre": c.nombre, "cantidad_empalmes": c.cantidad_empalmes}
                for c in resultado.cables
            ],
            "empalmes": [
                {
                    "fusion_n_id": e.fusion_n_id,
                    "nombre_par": e.nombre_par,
                    "es_splitter": e.es_splitter,
                    "pelo_origen": _serializar_pelo_empalme(e.pelo_origen),
                    "pelo_destino": _serializar_pelo_empalme(e.pelo_destino),
                    "splitter_destinos": [_serializar_pelo_empalme(p) for p in e.splitter_destinos],
                    "splitter_ratio": e.splitter_ratio,
                }
                for e in resultado.empalmes
            ],
            # Splitters tal como los declara Cromo (clase 133), con el ratio de `at.83`. Distinto de
            # `empalmes[].es_splitter`, que es la heurística de fan-out: `splitters_relevados=false`
            # significa que esta Botella todavía no se barrió con el código que los lee, no que no
            # tenga ninguno — y mientras tanto la heurística sigue siendo lo único disponible.
            "splitters": [
                {
                    "n_id": s.n_id,
                    "nombre": s.nombre,
                    "ratio": s.ratio,
                    "salidas": s.salidas,
                    "puertos_totales": s.puertos_totales,
                    "puertos_ocupados": s.puertos_ocupados,
                }
                for s in resultado.splitters
            ],
            "splitters_relevados": resultado.splitters_relevados,
        }
    )


@router.get("/api/infra/cromo/cables")
async def cromo_inventario_cables_web(
    q: Optional[str] = None,
    jerarquia: Optional[str] = None,
    propietario: Optional[str] = None,
    vigente: Optional[bool] = None,
    n_id: Optional[int] = None,
    botella: Optional[str] = None,
    servicio: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Inventario navegable de cables ya ingeridos (Etapa 8b, filtros extendidos en Etapa 9) —
    búsqueda + paginación. Sólo lectura, cualquier usuario autenticado (es consulta, no
    administración, mismo criterio que el verificador)."""
    from core.services.cromo.inventario import buscar_cables
    from db.session import AsyncSessionLocal

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_cables(
            sesion,
            q=q,
            jerarquia=jerarquia,
            propietario=propietario,
            vigente=vigente,
            n_id=n_id,
            botella=botella,
            servicio=servicio,
            limit=limit,
            offset=offset,
        )

    return JSONResponse(
        {
            "total": resultado.total,
            "limit": resultado.limit,
            "offset": resultado.offset,
            "cables": [
                {
                    "n_id": c.n_id,
                    "nombre": c.nombre,
                    "capacidad": c.capacidad,
                    "capacidad_pelos": c.capacidad_pelos,
                    "jerarquia": c.jerarquia,
                    "propietario": c.propietario,
                    "extremo_a_nombre": c.extremo_a_nombre,
                    "extremo_b_nombre": c.extremo_b_nombre,
                    "vigente": c.vigente,
                    "cantidad_servicios": c.cantidad_servicios,
                }
                for c in resultado.cables
            ],
        }
    )


@router.get("/api/infra/cromo/pon")
async def cromo_inventario_pon_web(
    q: Optional[str] = None,
    n_id: Optional[int] = None,
    clases: Optional[str] = None,
    vigente: Optional[bool] = None,
    localidad: Optional[str] = None,
    propietario: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Inventario navegable de la red de acceso PON: cajas PON y rosetas ya ingeridas.

    Sólo lectura, cualquier usuario autenticado — mismo criterio que los inventarios de cables y
    ODFs.

    `clases` llega como lista separada por comas (`?clases=84,137`) porque cajas PON y rosetas
    comparten tabla: es el parámetro que distingue una vista de la otra. Se ignoran los valores no
    numéricos en vez de devolver 400: un filtro de listado mal tipeado no debería romper la
    pantalla, y el resto de la lista sigue siendo un filtro válido.
    """
    from core.services.cromo.pon_inventario import buscar_pon_elementos
    from db.session import AsyncSessionLocal

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    clases_filtro: Optional[list[int]] = None
    if clases:
        clases_filtro = [int(c) for c in clases.split(",") if c.strip().lstrip("-").isdigit()] or None

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_pon_elementos(
            sesion,
            q=q,
            n_id=n_id,
            clases=clases_filtro,
            vigente=vigente,
            localidad=localidad,
            propietario=propietario,
            limit=limit,
            offset=offset,
        )

    return JSONResponse(
        {
            "total": resultado.total,
            "limit": resultado.limit,
            "offset": resultado.offset,
            "elementos": [
                {
                    "n_id": e.n_id,
                    "clase": e.clase,
                    "nombre": e.nombre,
                    "localidad": e.localidad,
                    "calle": e.calle,
                    "altura": e.altura,
                    "propietario": e.propietario,
                    "tipo_conector": e.tipo_conector,
                    "capacidad_puertos": e.capacidad_puertos,
                    "latitud": e.latitud,
                    "longitud": e.longitud,
                    "vigente": e.vigente,
                    "cantidad_splitters": e.cantidad_splitters,
                }
                for e in resultado.elementos
            ],
        }
    )


@router.get("/api/infra/cromo/odfs")
async def cromo_inventario_odfs_web(
    q: Optional[str] = None,
    n_id: Optional[int] = None,
    vigente: Optional[bool] = None,
    tipo_elemento: Optional[str] = None,
    servicio: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Inventario navegable de ODFs ya ingeridos (Tarea 4 del plan ODFs) — búsqueda + paginación.
    Sólo lectura, cualquier usuario autenticado (mismo criterio que el inventario de cables)."""
    from core.services.cromo.odf_inventario import buscar_odfs
    from db.session import AsyncSessionLocal

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_odfs(
            sesion,
            q=q,
            n_id=n_id,
            vigente=vigente,
            tipo_elemento=tipo_elemento,
            servicio=servicio,
            limit=limit,
            offset=offset,
        )

    return JSONResponse(
        {
            "total": resultado.total,
            "limit": resultado.limit,
            "offset": resultado.offset,
            "odfs": [
                {
                    "n_id": o.n_id,
                    "nombre": o.nombre,
                    "tipo_elemento": o.tipo_elemento,
                    "localidad": o.localidad,
                    "calle": o.calle,
                    "altura": o.altura,
                    "propietario": o.propietario,
                    "vigente": o.vigente,
                    "cantidad_cables_asociados": o.cantidad_cables_asociados,
                    "cantidad_servicios": o.cantidad_servicios,
                }
                for o in resultado.odfs
            ],
        }
    )


def _serializar_detalle_odf(detalle: Any) -> dict[str, Any]:
    return {
        "n_id": detalle.n_id,
        "nombre": detalle.nombre,
        "tipo_elemento": detalle.tipo_elemento,
        "propietario": detalle.propietario,
        "codigo_modelo": detalle.codigo_modelo,
        "id_legacy": detalle.id_legacy,
        "notas": detalle.notas,
        "calle": detalle.calle,
        "altura": detalle.altura,
        "localidad": detalle.localidad,
        "provincia": detalle.provincia,
        "ubicacion_fisica": detalle.ubicacion_fisica,
        "tendido": detalle.tendido,
        "latitud": detalle.latitud,
        "longitud": detalle.longitud,
        "vigente": detalle.vigente,
        "cables_asociados": list(detalle.cables_asociados),
        "odfs_en_la_misma_direccion": list(detalle.odfs_en_la_misma_direccion),
    }


@router.get("/api/infra/cromo/odfs/{n_id}/detalle")
async def cromo_odf_detalle_web(n_id: int) -> JSONResponse:
    """Detalle de un ODF: metadata, cables asociados resueltos (n_id + nombre) y otros ODFs que
    comparten domicilio físico (Tarea 4 del plan ODFs). Sólo lectura, cualquier usuario autenticado
    (mismo criterio que el detalle de cable)."""
    from core.services.cromo.odf_detalle import obtener_detalle_odf
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion:
            detalle = await obtener_detalle_odf(sesion, n_id)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc

    return JSONResponse(_serializar_detalle_odf(detalle))


@router.get("/api/infra/cromo/odfs/{odf_n_id}/servicios")
async def cromo_verificador_por_odf_web(odf_n_id: int) -> JSONResponse:
    """Servicios que pasan por los cables asociados a este ODF, más el listado de esos cables (id,
    nombre, cantidad de servicios) — mismo formato de tarjeta "Cables asociados" que el verificador
    de Botella (Tarea 4 del plan ODFs). Sólo lectura, cualquier usuario autenticado."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_por_odf
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_por_odf(sesion, odf_n_id)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc

    return JSONResponse(
        {
            "odf_n_id": resultado.odf_n_id,
            "nombre": resultado.nombre,
            "tipo_elemento": resultado.tipo_elemento,
            "localidad": resultado.localidad,
            "servicios": [_serializar_servicio_encontrado(s) for s in resultado.servicios],
            "cables": [
                {"n_id": c.n_id, "nombre": c.nombre, "cantidad_servicios": c.cantidad_servicios}
                for c in resultado.cables
            ],
        }
    )


@router.get("/api/infra/cromo/odfs/{odf_n_id}/conectores")
async def cromo_conectores_de_odf_web(odf_n_id: int) -> JSONResponse:
    """Conectores/posiciones de patchera de esta ODF, con Cliente/Estado ya resueltos (atributo
    directo de Cromo + regex del pelo, combinados por MAX-based ID final — ver
    `core/services/cromo/odf_conectores.py`). Sólo lectura, cualquier usuario autenticado."""
    from core.services.cromo.odf_conectores import ObjetoNoEncontrado, conectores_de_odf
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await conectores_de_odf(sesion, odf_n_id)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc

    return JSONResponse(
        {
            "odf_n_id": resultado.odf_n_id,
            "odf_nombre": resultado.odf_nombre,
            "conectores": [
                {
                    "n_id": c.n_id,
                    "bandeja_n_id": c.bandeja_n_id,
                    "bandeja_nombre": c.bandeja_nombre,
                    "numero_conector": c.numero_conector,
                    "pelo_n_id": c.pelo_n_id,
                    "pelo_numero": c.pelo_numero,
                    "servicio_resuelto": c.servicio_resuelto,
                    "servicio_id_historico": c.servicio_id_historico,
                    "servicio_id_externo": c.servicio_id_externo,
                    "nombre_cliente": c.nombre_cliente,
                    "cliente": c.cliente,
                    "estado_servicio": c.estado_servicio,
                }
                for c in resultado.conectores
            ],
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Servicios sin ODF — gestor de asociación manual Servicio→ODF (Tasks 2-4: Cromo)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/infra/botellas/buscar")
async def botellas_unificadas_buscar_web(
    q: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
    incluir_no_operativas: bool = False,
) -> JSONResponse:
    """Listado unificado de Botellas: `app.cromo_botellas` (Cromo, siempre primero) + `app.camaras`
    con `camara_padre_id` seteado (legado Infra/Baneos) — ambos con estado real desde 2026-08-11.
    `incluir_no_operativas=False` (default) oculta infraestructura fantasma/sin señal real de
    ambos orígenes. Sólo lectura, cualquier usuario autenticado — es consulta, no administración."""
    from core.services.botellas_unificadas_service import buscar_botellas_unificadas
    from db.session import AsyncSessionLocal

    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_botellas_unificadas(
            sesion, q=q, limit=limit, offset=offset, incluir_no_operativas=incluir_no_operativas
        )

    return JSONResponse(
        {
            "total": resultado.total,
            "limit": resultado.limit,
            "offset": resultado.offset,
            "incluir_no_operativas": incluir_no_operativas,
            "botellas": [
                {"origen": b.origen, "id": b.id, "nombre": b.nombre, "estado": b.estado}
                for b in resultado.botellas
            ],
        }
    )


class BotellaEstadoMasivoItemModel(BaseModel):
    """Item de la clave compuesta `{origen, id}` del inventario unificado — nunca un id numérico
    solo (`CromoBotella.n_id` y `Camara.id` son espacios de ID independientes que pueden colisionar
    en valor)."""

    origen: str  # "cromo" | "legado"
    id: int


class BotellasEstadoMasivoRequestModel(BaseModel):
    """Payload para cambiar el estado de un lote de Botellas de origen mixto (Cromo + legado)."""

    items: list[BotellaEstadoMasivoItemModel]
    estado: str
    motivo: str = "Cambio de estado masivo"
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.put("/api/infra/botellas/estado")
def botellas_estado_masivo_web(
    request: Request,
    body: BotellasEstadoMasivoRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Cambia el estado de un lote de Botellas (Cromo + legado) en una sola operación. Legado
    cascadea por grupo completo vía `aplicar_estado_a_grupo`; Cromo actualiza `CromoBotella.estado`
    directo (foto propia, ver `core/services/botellas_estado_masivo_service.py`)."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_estado_masivo result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    if not body.items:
        return JSONResponse({"error": "No se especificaron botellas a actualizar"}, status_code=400)

    try:
        from core.services.botellas_estado_masivo_service import (
            ESTADOS_ADMISIBLES,
            EstadoMasivoError,
            ItemBotellaEstado,
            actualizar_estado_masivo,
        )
        from db.models.infra import CamaraEstado
        from db.session import SessionLocal

        estado_normalizado = body.estado.strip().upper()
        if estado_normalizado not in {estado.value for estado in ESTADOS_ADMISIBLES}:
            return JSONResponse({"error": "Estado inválido"}, status_code=400)

        items = [ItemBotellaEstado(origen=item.origen, id=item.id) for item in body.items]

        with SessionLocal() as session:
            try:
                resultado = actualizar_estado_masivo(
                    session,
                    items,
                    CamaraEstado(estado_normalizado),
                    usuario=username,
                    motivo=body.motivo.strip() or "Cambio de estado masivo",
                )
            except EstadoMasivoError as exc:
                session.rollback()
                raise ErrorDeDominio(str(exc)) from exc

            session.commit()
            logger.info(
                "action=botellas_estado_masivo user=%s estado_nuevo=%s legado=%d cromo=%d no_encontrados=%d",
                username,
                resultado.estado_nuevo,
                resultado.legado_actualizadas,
                resultado.cromo_actualizadas,
                len(resultado.no_encontrados),
            )
            return JSONResponse({"ok": True, **resultado.to_dict()})
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("botellas_estado_masivo", exc, user=username)


@router.get("/api/admin/infra/botellas/viewer", dependencies=[Depends(usuario_admin)])
async def botellas_viewer_listado_web(
    q: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
    incluir_no_operativas: bool = False,
) -> JSONResponse:
    """Listado paginado dual (Cromo + legado) para `/admin/servicios/viewer/Botellas` — delega
    íntegramente en `buscar_botellas_unificadas` (mismo servicio y patrón `AsyncSessionLocal` que ya
    usa `GET /api/infra/botellas/buscar`), con guarda admin adicional para el namespace del dashboard."""
    try:
        from core.services.botellas_unificadas_service import buscar_botellas_unificadas
        from db.session import AsyncSessionLocal

        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        async with AsyncSessionLocal() as sesion:
            resultado = await buscar_botellas_unificadas(
                sesion, q=q, limit=limit, offset=offset, incluir_no_operativas=incluir_no_operativas
            )

        return JSONResponse({
            "total": resultado.total,
            "limit": resultado.limit,
            "offset": resultado.offset,
            "incluir_no_operativas": incluir_no_operativas,
            "botellas": [
                {"origen": b.origen, "id": b.id, "nombre": b.nombre, "estado": b.estado}
                for b in resultado.botellas
            ],
        })
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("botellas_viewer_listado", exc)


def _detectar_grupos_duplicados_en_sesion_propia() -> list[Any]:
    """Detección de Botellas duplicadas con una `Session` abierta y cerrada en el mismo hilo (se
    llama con `asyncio.to_thread`): una `Session` no debe cruzar entre el event loop y otro hilo."""
    from core.services.botella_duplicados_service import detectar_grupos_duplicados_botellas
    from db.session import SessionLocal

    with SessionLocal() as session:
        return detectar_grupos_duplicados_botellas(session)


@router.get("/api/admin/infra/botellas/viewer/duplicados", dependencies=[Depends(usuario_admin)])
async def botellas_viewer_duplicados_web(refrescar: bool = False) -> JSONResponse:
    """Grupos de Botellas (Cromo + legado) candidatas a duplicado dentro de la misma Cámara padre.
    Sin paginar — ver `core/services/botella_duplicados_service.py`. Cada miembro Cromo lleva
    `tiene_cables` (señal "operativa" para elegir el destino al consolidar un grupo no `resoluble`,
    ver `core/services/cromo/verificador.py::tiene_cables_asociados_batch_sync` — una sola query
    batcheada para todos los n_ids de la página, nunca una por miembro); `None` para legado, donde esa
    señal no existe.

    Cada grupo también lleva `sugerencia_placeholders` (`{id_destino_cromo, ids_origen_cromo}` o
    `null`) — patrón "ID dual" (ver `core/services/botella_duplicados_service.py::
    sugerir_consolidacion_placeholders`): grupo 100% Cromo con exactamente un miembro operativo y el
    resto placeholders vacíos del mismo nombre. Es sólo detección/exposición para que un admin la
    consolide manualmente vía `POST /api/infra/botellas/consolidar` — no ejecuta nada acá.

    `?refrescar=true` (el botón "Actualizar" del visor) saltea la lectura de caché y fuerza el cómputo
    síncrono, repoblando la caché con el resultado fresco. Es la escotilla manual para los escritores
    que NO invalidan la caché (ingesta Cromo, cambios de estado/baneo, merge/eliminar Cámaras, el
    backfill de Cámara padre): sin esto, un admin que sabe que algo cambió por fuera de los 7
    mutadores cableados tendría que esperar hasta el TTL de 24h — ver `docs/decisiones.md`,
    entrada 2026-08-21 (cont.). El cómputo (cache miss o `refrescar=true`) corre en un hilo aparte
    (`asyncio.to_thread`) para no bloquear el event loop del proceso `web` — mismo patrón ya usado en
    `modules/botellas_recalculo_worker/worker.py`, ver `docs/decisiones.md`, entrada 2026-08-22."""
    try:
        from core.services.botella_duplicados_service import (
            detectar_grupos_duplicados_botellas,
            sugerir_consolidacion_placeholders,
        )
        from core.services.cromo.verificador import tiene_cables_asociados_batch_sync
        from db.session import SessionLocal

        # Toda la sesión sync vive en un solo hilo: una `Session` no es thread-safe, y antes se
        # pasaba a `to_thread` para detectar y después se seguía usando en el event loop.
        def _detectar_y_operativos(grupos_cache):
            with SessionLocal() as session:
                grupos = grupos_cache if grupos_cache is not None else detectar_grupos_duplicados_botellas(session)
                ids_cromo = [m.id for g in grupos for m in g.miembros if m.origen == "cromo"]
                return grupos, tiene_cables_asociados_batch_sync(session, ids_cromo)

        grupos_cache = None if refrescar else await leer_cache_duplicados()
        grupos, operativos = await asyncio.to_thread(_detectar_y_operativos, grupos_cache)
        if grupos_cache is None:
            await guardar_cache_duplicados(grupos)
        return JSONResponse({
            "total_grupos": len(grupos),
            "grupos": [
                {
                    "camara_padre_id": g.camara_padre_id,
                    "camara_padre_nombre": g.camara_padre_nombre,
                    "clave_normalizada": g.clave_normalizada,
                    "criterio": g.criterio,
                    "estados_en_conflicto": g.estados_en_conflicto,
                    "estado_mas_restrictivo": g.estado_mas_restrictivo,
                    "resoluble": g.resoluble,
                    "sugerencia_placeholders": (
                        {"id_destino_cromo": s.id_destino_cromo, "ids_origen_cromo": s.ids_origen_cromo}
                        if (s := sugerir_consolidacion_placeholders(g, operativos))
                        else None
                    ),
                    "miembros": [
                        {
                            "origen": m.origen,
                            "id": m.id,
                            "nombre": m.nombre,
                            "estado": m.estado,
                            "tiene_cables": (m.id in operativos) if m.origen == "cromo" else None,
                        }
                        for m in g.miembros
                    ],
                }
                for g in grupos
            ],
        })
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("botellas_viewer_duplicados", exc)


class BotellasOperatividadRequestModel(BaseModel):
    """Payload para consultar, en lote, cuáles de los n_ids Cromo dados tienen cables asociados."""

    n_ids: list[int]


@router.post("/api/admin/infra/botellas/operatividad", dependencies=[Depends(usuario_admin)])
def botellas_operatividad_web(body: BotellasOperatividadRequestModel) -> JSONResponse:
    """Cuáles de los n_ids Cromo dados tienen al menos un cable asociado (extremo_a/b) — señal
    "operativa" para el flujo de consolidación manual con IDs tipeados a mano (sin pasar por un grupo
    ya detectado). Una sola query batcheada, sin N+1."""
    try:
        from core.services.cromo.verificador import tiene_cables_asociados_batch_sync
        from db.session import SessionLocal

        with SessionLocal() as session:
            operativos = tiene_cables_asociados_batch_sync(session, body.n_ids)
        return JSONResponse({"operativos": sorted(operativos)})
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("botellas_operatividad", exc)


class BotellaApropiarRequestModel(BaseModel):
    """Payload para apropiar una Botella legado hacia su CromoBotella hermana (mismo padre)."""

    legado_id: int
    cromo_n_id: int
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/infra/botellas/apropiar")
async def botellas_apropiar_web(
    request: Request,
    body: BotellaApropiarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Apropia una Botella legado hacia su CromoBotella hermana: Cromo se conserva, la legado se
    elimina físicamente tras reasignar sus FKs reales a la Cámara padre. Ver
    `core/services/botella_merge_service.py`."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_apropiar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.botella_merge_service import ApropiacionBotellaError, apropiar_legado_a_cromo
        from db.session import SessionLocal

        # Sync (Session): corre en un hilo para no frenar el event loop; las colas (async) quedan afuera.
        def _en_hilo():
            with SessionLocal() as session:
                try:
                    resultado = apropiar_legado_a_cromo(
                        session, legado_id=body.legado_id, cromo_n_id=body.cromo_n_id, usuario=username,
                    )
                except ApropiacionBotellaError as exc:
                    session.rollback()
                    raise ErrorDeDominio(str(exc)) from exc

                session.commit()
                return resultado

        resultado = await asyncio.to_thread(_en_hilo)
        logger.info(
            "action=botellas_apropiar user=%s legado_id=%s cromo_n_id=%s camara_padre_id=%s "
            "estado_final=%s cables=%d empalmes=%d ingresos=%d aliases=%d",
            username,
            resultado.legado_id,
            resultado.cromo_n_id,
            resultado.camara_padre_id,
            resultado.estado_final,
            resultado.cables_migrados,
            resultado.empalmes_migrados,
            resultado.ingresos_migrados,
            resultado.aliases_migrados,
        )
        await encolar_recalculo_duplicados_botellas(
            motivo=f"apropiar legado_id={resultado.legado_id} cromo_n_id={resultado.cromo_n_id} usuario={username}"
        )
        await _encolar_arbitro(
            "BOTELLAS", [resultado.cromo_n_id], f"apropiar cromo_n_id={resultado.cromo_n_id}"
        )
        return JSONResponse({
            "ok": True,
            "legado_id": resultado.legado_id,
            "legado_nombre": resultado.legado_nombre,
            "cromo_n_id": resultado.cromo_n_id,
            "cromo_nombre": resultado.cromo_nombre,
            "camara_padre_id": resultado.camara_padre_id,
            "camara_padre_nombre": resultado.camara_padre_nombre,
            "botellas_legado_migradas": resultado.botellas_legado_migradas,
            "cromo_reasignadas": resultado.cromo_reasignadas,
            "cables_migrados": resultado.cables_migrados,
            "empalmes_migrados": resultado.empalmes_migrados,
            "ingresos_migrados": resultado.ingresos_migrados,
            "aliases_migrados": resultado.aliases_migrados,
            "estado_final": resultado.estado_final,
        })
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("botellas_apropiar", exc, user=username)


class BotellaApropiarMasivoRequestModel(BaseModel):
    """Payload para apropiar automáticamente TODOS los grupos de Botellas duplicadas resolubles."""

    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/infra/botellas/apropiar-masivo")
async def botellas_apropiar_masivo_web(
    request: Request,
    body: BotellaApropiarMasivoRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Apropia automáticamente TODOS los grupos de Botellas duplicadas `resoluble` (1 legado + 1
    Cromo dentro del mismo padre) detectados en este momento — mismo patrón que
    `POST /api/infra/camaras/merge-masivo`: cada grupo corre en su PROPIA transacción, así que un
    fallo aislado no revierte los grupos ya apropiados exitosamente. Grupos no `resoluble` (todo
    legado, todo cromo, o mixto con 2+ legado) se omiten — no tienen política de resolución
    automática definida, ver `core/services/botella_duplicados_service.py`."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_apropiar_masivo result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.botella_duplicados_service import (
            sugerir_apropiacion,
        )
        from core.services.botella_merge_service import ApropiacionBotellaError, apropiar_legado_a_cromo
        from db.session import SessionLocal

        grupos = await leer_cache_duplicados()
        if grupos is None:
            grupos = await asyncio.to_thread(_detectar_grupos_duplicados_en_sesion_propia)
            await guardar_cache_duplicados(grupos)

        resolubles = [(grupo, sugerir_apropiacion(grupo)) for grupo in grupos]
        resolubles = [(grupo, par) for grupo, par in resolubles if par is not None]

        # Sync (una Session por grupo): todo el lote corre en un hilo para no frenar el event loop.
        def _apropiar_resolubles() -> list[dict[str, Any]]:
            detalle: list[dict[str, Any]] = []
            for grupo, (legado_id, cromo_n_id) in resolubles:
                with SessionLocal() as session:
                    try:
                        resultado = apropiar_legado_a_cromo(
                            session, legado_id=legado_id, cromo_n_id=cromo_n_id, usuario=username,
                        )
                    except ApropiacionBotellaError as exc:
                        session.rollback()
                        detalle.append({
                            "exito": False,
                            "legado_id": legado_id,
                            "cromo_n_id": cromo_n_id,
                            "camara_padre_nombre": grupo.camara_padre_nombre,
                            "error": str(exc),
                        })
                        continue

                    session.commit()
                    detalle.append({
                        "exito": True,
                        "legado_id": resultado.legado_id,
                        "cromo_n_id": resultado.cromo_n_id,
                        "camara_padre_nombre": resultado.camara_padre_nombre,
                        "estado_final": resultado.estado_final,
                    })
            return detalle

        detalle = await asyncio.to_thread(_apropiar_resolubles)

        grupos_apropiados = sum(1 for item in detalle if item["exito"])
        grupos_con_error = len(detalle) - grupos_apropiados
        logger.info(
            "action=botellas_apropiar_masivo user=%s total_grupos=%d grupos_resolubles=%d "
            "grupos_apropiados=%d grupos_con_error=%d",
            username,
            len(grupos),
            len(resolubles),
            grupos_apropiados,
            grupos_con_error,
        )
        if grupos_apropiados > 0:
            await encolar_recalculo_duplicados_botellas(motivo=f"apropiar-masivo usuario={username}")
        return JSONResponse({
            "ok": True,
            "total_grupos": len(grupos),
            "grupos_resolubles": len(resolubles),
            "grupos_apropiados": grupos_apropiados,
            "grupos_con_error": grupos_con_error,
            "detalle": detalle,
        })
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("botellas_apropiar_masivo", exc, user=username)


class BotellaConsolidarRequestModel(BaseModel):
    """Payload para consolidar un grupo LIBRE de n_ids Cromo (no restringido a un grupo detectado
    automáticamente) hacia un único n_id destino, más opcionalmente una o más Botellas legado y un
    nombre corregido para el destino. `force_camera_association=True` bypasea el guard de "misma
    Cámara padre" de `apropiar_legado_a_cromo` para los `ids_legado` incluidos — no afecta la
    consolidación Cromo↔Cromo (`ids_origen_cromo`), que no tiene ese guard (ver docs/decisiones.md
    2026-08-24)."""

    ids_origen_cromo: list[int] = Field(default_factory=list)
    id_destino_cromo: int
    ids_legado: list[int] = Field(default_factory=list)
    nombre_destino: str | None = None
    motivo: str | None = None
    force_camera_association: bool = False
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/infra/botellas/consolidar")
async def botellas_consolidar_web(
    request: Request,
    body: BotellaConsolidarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Consolida un grupo libre de Botellas Cromo duplicadas hacia un único n_id destino: crea/
    actualiza filas en `app.cromo_botella_alias` (`accion='fusionar'`), opcionalmente migra una o más
    Botellas legado hacia el destino (reusa `apropiar_legado_a_cromo` tal cual) y opcionalmente
    corrige el nombre del destino si falta. Cierra el gap "Revisión manual" documentado 2026-08-14 en
    `core/services/botella_duplicados_service.py`. Ver `core/services/cromo/consolidacion_service.py`."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_consolidar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.botella_merge_service import ApropiacionBotellaError
        from core.services.cromo.consolidacion_service import (
            ConsolidacionBotellaError,
            consolidar_grupo_botellas,
        )
        from db.session import SessionLocal

        # Sync (Session): corre en un hilo para no frenar el event loop; las colas (async) quedan afuera.
        def _en_hilo():
            with SessionLocal() as session:
                try:
                    resultado = consolidar_grupo_botellas(
                        session,
                        ids_origen_cromo=body.ids_origen_cromo,
                        id_destino_cromo=body.id_destino_cromo,
                        ids_legado=body.ids_legado,
                        nombre_destino=body.nombre_destino,
                        motivo=body.motivo,
                        usuario=username,
                        force_camera_association=body.force_camera_association,
                    )
                except (ConsolidacionBotellaError, ApropiacionBotellaError) as exc:
                    session.rollback()
                    raise ErrorDeDominio(str(exc)) from exc

                session.commit()
                return resultado

        resultado = await asyncio.to_thread(_en_hilo)
        logger.info(
            "action=botellas_consolidar user=%s destino=%s origenes=%s legados=%s "
            "alias_creados=%d alias_actualizados=%d repuntados=%d",
            username,
            resultado.id_destino_cromo,
            body.ids_origen_cromo,
            body.ids_legado,
            resultado.alias_creados,
            resultado.alias_actualizados,
            len(resultado.alias_repuntados),
        )
        await encolar_recalculo_duplicados_botellas(
            motivo=f"consolidar destino={resultado.id_destino_cromo} usuario={username}"
        )
        await _encolar_arbitro(
            "BOTELLAS",
            [resultado.id_destino_cromo, *body.ids_origen_cromo],
            f"consolidar destino={resultado.id_destino_cromo}",
        )
        return JSONResponse({
            "ok": True,
            "id_destino_cromo": resultado.id_destino_cromo,
            "alias_creados": resultado.alias_creados,
            "alias_actualizados": resultado.alias_actualizados,
            "alias_repuntados": resultado.alias_repuntados,
            "alias_dependientes_recableados": resultado.alias_dependientes_recableados,
            "cables_existentes_recableados": resultado.cables_existentes_recableados,
            "fusiones_existentes_recableadas": resultado.fusiones_existentes_recableadas,
            "legados_migrados": resultado.legados_migrados,
            "cables_migrados": resultado.cables_migrados,
            "empalmes_migrados": resultado.empalmes_migrados,
            "ingresos_migrados": resultado.ingresos_migrados,
            "camara_aliases_migrados": resultado.camara_aliases_migrados,
            "nombre_anterior": resultado.nombre_anterior,
            "nombre_nuevo": resultado.nombre_nuevo,
            "legados_con_camara_forzada": resultado.legados_con_camara_forzada,
        })
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("botellas_consolidar", exc, user=username)


@router.get("/api/admin/infra/botellas/inconsistencias/exportar")
async def botellas_inconsistencias_exportar_web(usuario: UsuarioSesion = Depends(usuario_admin)) -> Response:
    """Excel de inconsistencias de Botellas sin resolver: huérfanas (sin Cámara padre) + miembros de
    grupos duplicados no `resoluble` automáticamente. Columnas: ID Cromo, Nombre, Cámara Padre,
    Motivo — mismo patrón de export ya usado en este archivo para Cámaras (`pd.ExcelWriter(engine=
    "openpyxl")` + `Response` con `Content-Disposition`)."""
    username = usuario.username
    try:
        from datetime import datetime, timezone

        import pandas as pd

        from core.services.cromo.orfanas_service import buscar_huerfanas
        from db.session import AsyncSessionLocal

        rows: list[dict[str, Any]] = []

        async with AsyncSessionLocal() as sesion:
            huerfanas = await buscar_huerfanas(sesion, limit=100_000, offset=0)
        for h in huerfanas.botellas:
            rows.append({
                "ID Cromo": h.n_id,
                "Nombre": h.nombre or "",
                "Cámara Padre": "",
                "Motivo": "Huérfana — sin Cámara padre asociada",
            })

        grupos = await leer_cache_duplicados()
        if grupos is None:
            grupos = await asyncio.to_thread(_detectar_grupos_duplicados_en_sesion_propia)
            await guardar_cache_duplicados(grupos)
        for g in grupos:
            if g.resoluble:
                continue
            cuenta_cromo = sum(1 for m in g.miembros if m.origen == "cromo")
            cuenta_legado = sum(1 for m in g.miembros if m.origen == "legado")
            descripcion_grupo = (
                f"Duplicado no resoluble — grupo de {len(g.miembros)} miembros "
                f"({cuenta_cromo} Cromo, {cuenta_legado} legado)"
            )
            for m in g.miembros:
                motivo = descripcion_grupo
                if m.origen == "legado":
                    motivo += f"; miembro legado (Camara.id={m.id})"
                rows.append({
                    "ID Cromo": m.id if m.origen == "cromo" else "",
                    "Nombre": m.nombre,
                    "Cámara Padre": g.camara_padre_nombre,
                    "Motivo": motivo,
                })

        logger.info("action=botellas_inconsistencias_exportar user=%s filas=%d", username, len(rows))

        df = pd.DataFrame(rows, columns=["ID Cromo", "Nombre", "Cámara Padre", "Motivo"])
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Inconsistencias", index=False)
        output.seek(0)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="botellas_inconsistencias_{timestamp}.xlsx"'},
        )
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("botellas_inconsistencias_exportar", exc)


class BotellaEliminarRequestModel(BaseModel):
    """Payload para eliminar permanentemente una Botella (legado o Cromo) genuinamente vacía."""

    origen: str
    id: int
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/infra/botellas/eliminar")
async def botellas_eliminar_web(
    request: Request,
    body: BotellaEliminarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Elimina permanentemente una Botella (legado o Cromo) — se rechaza si tiene Cables/Empalmes/
    Ingresos (legado) o Cables/Fusiones Cromo (o si ya es destino de otra fila de alias) asociados;
    sólo se puede eliminar lo que esté genuinamente vacío. Para Cromo, registra automáticamente el
    n_id en `app.cromo_botella_alias` (`accion='ignorar'`) para que la ingesta no la resucite. Si la
    Cámara padre queda vacía como consecuencia, también se elimina. Ver
    `core/services/camara_botella_delete_service.py`."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_eliminar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.camara_botella_delete_service import EliminacionBloqueadaError, eliminar_botella
        from db.session import SessionLocal

        # Sync (Session): corre en un hilo para no frenar el event loop; las colas (async) quedan afuera.
        def _en_hilo():
            with SessionLocal() as session:
                try:
                    resultado = eliminar_botella(session, origen=body.origen, id=body.id, usuario=username)
                except EliminacionBloqueadaError as exc:
                    session.rollback()
                    return JSONResponse(
                        {"error": str(exc), "bloqueos": _serializar_bloqueos(exc.bloqueos)}, status_code=400
                    )

                session.commit()
                return resultado

        resultado = await asyncio.to_thread(_en_hilo)
        if isinstance(resultado, JSONResponse):  # eliminación bloqueada: 400 con los bloqueos
            return resultado
        logger.info(
            "action=botellas_eliminar user=%s origen=%s id=%s camara_padre_eliminada=%s alias_registrado=%s",
            username,
            resultado.origen,
            resultado.id,
            resultado.camara_padre_eliminada,
            resultado.alias_registrado,
        )
        await encolar_recalculo_duplicados_botellas(
            motivo=f"eliminar origen={resultado.origen} id={resultado.id} usuario={username}"
        )
        # Legado/cámara no tienen n_id Cromo: el alcance BOTELLAS del árbitro sólo habla de n_id.
        if resultado.origen == "cromo":
            await _encolar_arbitro("BOTELLAS", [resultado.id], f"eliminar cromo_n_id={resultado.id}")
        return JSONResponse({
            "ok": True,
            "origen": resultado.origen,
            "id": resultado.id,
            "camara_padre_eliminada": resultado.camara_padre_eliminada,
            "alias_registrado": resultado.alias_registrado,
        })
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("botellas_eliminar", exc, user=username)


class BotellaEliminarGrupoRequestModel(BaseModel):
    """Payload para "Borrar y Excluir Cromo": borrado físico FORZADO de un grupo de `CromoBotella`
    conflictivas (botón de grupo del visor de duplicados). A diferencia de
    `BotellaEliminarRequestModel`, ignora deliberadamente la política "bloquear, nunca forzar" —
    ver `core/services/camara_botella_delete_service.py::eliminar_y_excluir_grupo_cromo`."""

    ids_cromo: list[int] = Field(default_factory=list)
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/infra/botellas/eliminar-grupo")
async def botellas_eliminar_grupo_web(
    request: Request, body: BotellaEliminarGrupoRequestModel, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Elimina físicamente un grupo de Botellas Cromo conflictivas (residuo de cambios de nombre en
    la ingesta) junto con sus `CromoCable`/`CromoFusion` asociados, SIN bloquear por datos reales —
    a diferencia de `/api/infra/botellas/eliminar`. Registra cada n_id en `app.cromo_botella_alias`
    (`accion='ignorar'`) para que la ingesta no las resucite. Ver
    `core/services/camara_botella_delete_service.py::eliminar_y_excluir_grupo_cromo`."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_eliminar_grupo result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.camara_botella_delete_service import (
            EliminacionBloqueadaError,
            eliminar_y_excluir_grupo_cromo,
        )
        from db.session import SessionLocal

        # Sync (Session): corre en un hilo para no frenar el event loop; las colas (async) quedan afuera.
        def _en_hilo():
            with SessionLocal() as session:
                try:
                    resultado = eliminar_y_excluir_grupo_cromo(
                        session, ids_cromo=body.ids_cromo, usuario=username
                    )
                except EliminacionBloqueadaError as exc:
                    session.rollback()
                    raise ErrorDeDominio(str(exc)) from exc

                session.commit()
                return resultado

        resultado = await asyncio.to_thread(_en_hilo)
        logger.info(
            "action=botellas_eliminar_grupo user=%s botellas=%s cables=%d fusiones=%d "
            "aliases=%d no_encontradas=%s",
            username,
            resultado.botellas_eliminadas,
            resultado.cables_eliminados,
            resultado.fusiones_eliminadas,
            resultado.aliases_registrados,
            resultado.no_encontradas,
        )
        await encolar_recalculo_duplicados_botellas(
            motivo=f"eliminar-grupo botellas={resultado.botellas_eliminadas} usuario={username}"
        )
        if resultado.botellas_eliminadas:
            await _encolar_arbitro(
                "BOTELLAS", body.ids_cromo, f"eliminar-grupo botellas={resultado.botellas_eliminadas}"
            )
        return JSONResponse({
            "ok": True,
            "botellas_eliminadas": resultado.botellas_eliminadas,
            "cables_eliminados": resultado.cables_eliminados,
            "fusiones_eliminadas": resultado.fusiones_eliminadas,
            "aliases_registrados": resultado.aliases_registrados,
            "no_encontradas": resultado.no_encontradas,
        })
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("botellas_eliminar_grupo", exc, user=username)


@router.get("/api/infra/cromo-botellas/{n_id}/estado-asociacion")
async def cromo_botella_estado_asociacion_web(n_id: int) -> JSONResponse:
    """Chequeo liviano de una Botella Cromo puntual: ¿está huérfana (sin `camara_id`)? Usado por
    `BotellaDetalleUnificadaView.vue` para decidir si mostrar el panel de resolución individual en
    vez de redirigir directo al Verificador Cromo. Desde 2026-08-13 también trae `camara_id`/
    `camara_nombre` (Cámara padre) cuando no está huérfana, para la navegación cruzada del
    Verificador hacia `CamaraDetailView.vue`."""
    from sqlalchemy import select

    from db.models.cromo import CromoBotella
    from db.models.infra import Camara
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        botella = (
            await sesion.execute(
                select(
                    CromoBotella.n_id,
                    CromoBotella.nombre,
                    CromoBotella.camara_id,
                    Camara.nombre,
                )
                .outerjoin(Camara, Camara.id == CromoBotella.camara_id)
                .where(CromoBotella.n_id == n_id)
            )
        ).first()
    if botella is None:
        return JSONResponse({"error": "Botella no encontrada"}, status_code=404)
    return JSONResponse({
        "n_id": botella[0],
        "nombre": botella[1],
        "huerfana": botella[2] is None,
        "camara_id": botella[2],
        "camara_nombre": botella[3],
    })


@router.get("/api/infra/cromo-botellas/huerfanas")
async def cromo_botellas_huerfanas_web(
    q: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
) -> JSONResponse:
    """Botellas Cromo vigentes sin `camara_id` — no matchearon el regex del backfill automático.
    Sólo lectura, cualquier usuario autenticado. Ver `core/services/cromo/orfanas_service.py`."""
    from core.services.cromo.orfanas_service import buscar_huerfanas
    from db.session import AsyncSessionLocal

    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_huerfanas(sesion, q=q, limit=limit, offset=offset)

    return JSONResponse({
        "total": resultado.total,
        "limit": resultado.limit,
        "offset": resultado.offset,
        "botellas": [
            {"n_id": b.n_id, "nombre": b.nombre, "calle": b.calle, "localidad": b.localidad}
            for b in resultado.botellas
        ],
    })


class CromoBotellasAsociarRequestModel(BaseModel):
    """Payload para asociar una o más Botellas Cromo huérfanas a una Cámara (existente o nueva)."""

    n_ids: list[int]
    camara_id: Optional[int] = None
    nombre_nueva_camara: Optional[str] = None
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/infra/cromo-botellas/asociar")
def cromo_botellas_asociar_web(
    request: Request,
    body: CromoBotellasAsociarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Asocia una o más Botellas Cromo huérfanas a una Cámara existente o recién creada — resolución
    manual individual o masiva (Caso 1, huérfanas). Ver `core/services/cromo/orfanas_service.py`."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=cromo_botellas_asociar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.cromo.orfanas_service import AsociarHuerfanasError, asociar_huerfanas
        from db.session import SessionLocal

        with SessionLocal() as session:
            try:
                resultado = asociar_huerfanas(
                    session,
                    n_ids=body.n_ids,
                    camara_id=body.camara_id,
                    nombre_nueva_camara=body.nombre_nueva_camara,
                    usuario=username,
                )
            except AsociarHuerfanasError as exc:
                session.rollback()
                raise ErrorDeDominio(str(exc)) from exc

            session.commit()
            logger.info(
                "action=cromo_botellas_asociar user=%s camara_id=%s camara_creada=%s botellas=%d",
                username,
                resultado.camara_id,
                resultado.camara_creada,
                resultado.botellas_vinculadas,
            )
            return JSONResponse({
                "ok": True,
                "camara_id": resultado.camara_id,
                "camara_creada": resultado.camara_creada,
                "botellas_vinculadas": resultado.botellas_vinculadas,
                "estado_asignado": resultado.estado_asignado,
            })
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("cromo_botellas_asociar", exc, user=username)


def _serializar_extremo_cable(n_id: Any, clase: Any, legacy: Any, nombre: Any) -> dict[str, Any]:
    return {"n_id": n_id, "clase": clase, "legacy": legacy, "nombre": nombre}


def _serializar_pelo_detalle(pelo: Any) -> dict[str, Any]:
    from core.services.cromo.parser import extraer_tipo_servicio_display

    # "Línea"/"Cliente" reciclan el match ya resuelto por `obtener_detalle_cable`/`pelos_de_tubo_sync`
    # (`v_cromo_servicio_match_vigente` → `app.servicios`, sin JOIN nuevo) — el primero de `pelo.servicios` si
    # existe alguno (ver PeloDetalle.servicios). "-"/None si no hay match, ningún JOIN nuevo por
    # `Servicio.numero_linea`.
    primer_match = pelo.servicios[0] if pelo.servicios else None
    return {
        "n_id": pelo.n_id,
        "numero_pelo": pelo.numero_pelo,
        "orden": pelo.orden,
        "color": pelo.color,
        "tipo_asociacion": pelo.tipo_asociacion,
        "servicio_raw": pelo.servicio_raw,
        "servicio_numero": pelo.servicio_numero,
        "vigente": pelo.vigente,
        "servicios": [_serializar_servicio_encontrado(s) for s in pelo.servicios],
        "tipo_servicio": extraer_tipo_servicio_display(pelo.servicio_raw),
        "linea": primer_match.servicio_id_externo if primer_match else None,
        "cliente": (primer_match.nombre_cliente or primer_match.cliente) if primer_match else None,
        "verificable": pelo.verificable,
        "status": pelo.status,
        "fecha_hora_status": pelo.fecha_hora_status.isoformat() if pelo.fecha_hora_status else None,
        # Pelo de un caso de inconsistencia de Cromo en CUARENTENA: `servicios` viene vacío pero el
        # pelo no está libre; el SPA lo marca "en cuarentena (inconsistencia Cromo)".
        "en_cuarentena": pelo.en_cuarentena,
    }


def _serializar_detalle_cable(detalle: Any) -> dict[str, Any]:
    return {
        "n_id": detalle.n_id,
        "nombre": detalle.nombre,
        "capacidad": detalle.capacidad,
        "capacidad_pelos": detalle.capacidad_pelos,
        "jerarquia": detalle.jerarquia,
        "propietario": detalle.propietario,
        "tendido": detalle.tendido,
        # Decimal no es serializable por JSONResponse/json.dumps — a float explícito.
        "distancia_geo": float(detalle.distancia_geo) if detalle.distancia_geo is not None else None,
        "distancia_real": float(detalle.distancia_real) if detalle.distancia_real is not None else None,
        "id_legacy": detalle.id_legacy,
        "notas": detalle.notas,
        "vigente": detalle.vigente,
        "extremo_a": _serializar_extremo_cable(
            detalle.extremo_a_n_id, detalle.extremo_a_clase, detalle.extremo_a_legacy, detalle.extremo_a_nombre
        ),
        "extremo_b": _serializar_extremo_cable(
            detalle.extremo_b_n_id, detalle.extremo_b_clase, detalle.extremo_b_legacy, detalle.extremo_b_nombre
        ),
        "tubos": [
            {
                "n_id": t.n_id,
                "orden": t.orden,
                "nombre_color": t.nombre_color,
                "vigente": t.vigente,
                "tiene_fila_propia": t.tiene_fila_propia,
                "pelos": [_serializar_pelo_detalle(p) for p in t.pelos],
            }
            for t in detalle.tubos
        ],
    }


@router.get("/api/infra/cromo/cables/{n_id}/detalle")
async def cromo_cable_detalle_web(n_id: int) -> JSONResponse:
    """Detalle jerárquico completo de un cable: metadata, extremos, tubos/buffers y pelos con su
    servicio matcheado (Etapa 9). Sólo lectura, cualquier usuario autenticado (mismo criterio que el
    verificador/inventario)."""
    from core.services.cromo.detalle import obtener_detalle_cable
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion:
            detalle = await obtener_detalle_cable(sesion, n_id)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc

    return JSONResponse(_serializar_detalle_cable(detalle))


def _serializar_elemento_vivo(elemento: Any) -> dict[str, Any]:
    return {
        "n_id": elemento.n_id,
        "version_id": elemento.version_id,
        "clase": elemento.clase,
        "clase_etiqueta": elemento.clase_etiqueta,
        "clase_entidad": elemento.clase_entidad,
        "nombre": elemento.nombre,
        "notas": elemento.notas,
        "atributos": [{"id": a.id, "etiqueta": a.etiqueta, "valor": a.valor} for a in elemento.atributos],
        "payload_raw": elemento.payload_raw,
    }


@router.get("/api/infra/cromo/elementos/{n_id}/vivo")
async def cromo_elemento_vivo_web(n_id: int) -> JSONResponse:
    """Visor en vivo de un elemento Cromo por `n_id` — GET directo contra Cromo (nunca contra las
    tablas ya ingeridas), para auditar inconsistencias sin esperar a la próxima corrida de ingesta.
    Sólo lectura, cualquier usuario autenticado (mismo criterio que el resto de `/api/infra/cromo/*`).
    Nunca persiste nada."""
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.live_lookup_service import obtener_elemento_vivo
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion, CromoClient(config=get_cromo_config()) as cliente:
            elemento = await obtener_elemento_vivo(cliente, sesion, n_id)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc
    except CromoClientError as exc:
        return error_servicio_externo("cromo_elemento_vivo", exc, "Cromo no respondió", n_id=n_id)

    return JSONResponse(_serializar_elemento_vivo(elemento))


def _serializar_pelo_excluido(excluido: Any) -> dict[str, Any]:
    return {
        "pelo_n_id": excluido.pelo_n_id,
        "numero_pelo": excluido.numero_pelo,
        "color": excluido.color,
        "cable_nombre": excluido.cable_nombre,
        "motivo": excluido.motivo,
        "excluido_por": excluido.excluido_por,
        "created_at": excluido.created_at.isoformat() if excluido.created_at else None,
        "origen": getattr(excluido, "origen", "MANUAL"),
    }


@router.get("/api/infra/cromo/servicios/{servicio_id}/odfs")
async def cromo_odfs_de_servicio_web(
    servicio_id: int,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """ODFs de Cromo a las que llega un Servicio — el canal por defecto del Detalle de Servicio.

    SQL local sobre lo ya ingerido: **no toca Cromo en vivo**. La consulta en vivo es el segundo
    canal y ya existe como el botón "Resolver camino" del mismo panel; el tracking manual es el
    tercero, sólo para regularizar lo que Cromo no resuelve solo.

    Sistema distinto del endpoint legacy `GET /api/infra/servicios/{servicio_id}/odfs`, que deriva
    las ODFs del archivo de tracking subido a mano (27 Servicios de 14.147 en dev). Éste toma
    `servicio_id` como **PK interna**, igual que el resto de la familia `/cromo/servicios/...`;
    el legacy toma el ID de origen. No son intercambiables.
    """
    from core.services.cromo.verificador import odfs_por_servicio
    from db.session import AsyncSessionLocal

    username, _ = usuario

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        odfs = await odfs_por_servicio(sesion, servicio_id)

    logger.info(
        "action=cromo_odfs_de_servicio user=%s servicio_id=%s odfs=%d",
        username,
        servicio_id,
        len(odfs),
    )

    return JSONResponse(
        {
            "servicio_id": servicio_id,
            "total": len(odfs),
            "odfs": [
                {
                    "odf_n_id": odf.odf_n_id,
                    "nombre": odf.nombre,
                    "calle": odf.calle,
                    "altura": odf.altura,
                    "localidad": odf.localidad,
                    "conectores": odf.conectores,
                    "pelos": odf.pelos,
                    "origen": odf.origen,
                }
                for odf in odfs
            ],
        }
    )


@router.get("/api/infra/cromo/servicios/{servicio_id}/camino-optico/pelos")
async def cromo_camino_pelos_web(
    servicio_id: int, priorizar_conector: bool = False
) -> JSONResponse:
    """Pelos de Cromo con los que se puede pedir el camino óptico de un Servicio.

    SQL local barato: **no toca Cromo**. Existe para que el Detalle de Servicio sepa si el botón
    de descarga va habilitado ANTES del click — de los 2.891 Servicios sin ODF, 2.228 (77%) no
    tienen ningún pelo y para ellos `/path` no tiene input posible.
    """
    from core.services.cromo import tracking_cache
    from core.services.cromo.camino_optico_service import (
        caminos_esperados,
        contar_semillas,
        listar_pelos_semilla,
        semillas_por_defecto,
    )
    from core.services.cromo.pelos_excluidos import listar_excluidos
    from core.services.cromo.servicio_posicion_vigente import tiene_posiciones
    from db.session import AsyncSessionLocal


    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        semillas = await listar_pelos_semilla(
            sesion, servicio_id, priorizar_conector=priorizar_conector
        )
        frescura = await tracking_cache.frescura(sesion, [s.pelo_n_id for s in semillas])
        total_matcheados, total_con_conector = await contar_semillas(sesion, servicio_id)
        esperados = await caminos_esperados(sesion, servicio_id)
        excluidos = await listar_excluidos(sesion, servicio_id)
        hay_posiciones = await tiene_posiciones(sesion, servicio_id)

    preseleccionados = [s.pelo_n_id for s in semillas_por_defecto(semillas)]
    # Si ninguna semilla tiene conector, la ODF del Servicio todavía no fue relevada y la
    # preselección cae al comportamiento histórico (el primer pelo del ranking). La UI necesita
    # distinguir ese caso para explicar por qué el default no son las posiciones de la ODF.
    odf_relevada = any(s.tiene_conector_odf for s in semillas)

    pelos = []
    for semilla in semillas:
        dato = _serializar_pelo_semilla(semilla)
        generado_at = frescura.get(semilla.pelo_n_id)
        dato["tracking_en_cache"] = generado_at.isoformat() if generado_at else None
        pelos.append(dato)

    return JSONResponse(
        {
            "servicio_id": servicio_id,
            "total": len(semillas),
            "pelos": pelos,
            "preseleccionados": preseleccionados,
            "odf_relevada": odf_relevada,
            # `total` es la lista ya truncada; estos dos son el universo real. Sin ellos la UI no
            # puede distinguir "este Servicio tiene 20 pelos" de "tiene 227 y ves 20". El número de
            # servicio viaja en el `at.61` de TODOS los pelos del recorrido, así que el total es
            # grande por diseño y los pelos que el operador llama "del Servicio" son los que son
            # posición de ODF.
            "total_matcheados": total_matcheados,
            "total_con_posicion_odf": total_con_conector,
            # Regla de operaciones: tantos caminos (y `.txt`) como pelos del Servicio en un mismo
            # cable u ODF. Cuáles son esos caminos lo resuelve `/caminos`, que sí va a Cromo.
            "caminos_esperados": esperados,
            "excluidos": [_serializar_pelo_excluido(x) for x in excluidos],
            # Hay posiciones de ODF con pelo (o una declarada vigente) con las que resolver aunque
            # no haya semillas etiquetadas: el 93150 va por pelos con la etiqueta 44649. El endpoint
            # de posiciones es admin; esto es lo que necesita el panel de un no admin para no decir
            # «no tiene ningún pelo» ni ocultar Resolver / Descargar todos.
            "tiene_posiciones": hay_posiciones,
        }
    )


@router.get("/api/infra/cromo/servicios/{servicio_id}/camino-optico/tracking.txt")
async def cromo_camino_tracking_txt_web(
    servicio_id: int,
    pelo_n_id: Optional[int] = None,
    tramo: Optional[int] = Query(default=None, ge=1),
    adicional: Optional[int] = Query(default=None, ge=1),
    sesion_usuario: UsuarioSesion = Depends(usuario_sesion),
) -> Response:
    """Tracking óptico de un Servicio, generado desde Cromo, en el formato `.txt` legacy.

    `tramo` (opcional, con `pelo_n_id`) es el número de tramo que ya conoce el frontend desde
    `/caminos`: el archivo se llama `{servicio} CROMO T{n} pelo {n_id}.txt`, igual que en Slack.
    `adicional` es lo mismo para un camino adicional (`{servicio} CROMO A{n} pelo {n_id}.txt`); los
    dos juntos son 400.

    El pelo puede ser una semilla etiquetada del Servicio o el de una de sus posiciones (posible o
    declarada vigente, `servicio_posicion_vigente`): el 93150 va por pelos con la etiqueta 44649.
    Un pelo que sólo es de posición se nombra siempre con el número del Servicio, nunca con el
    at.62 (el de esos pelos es `4649`), y si no está declarado se cachea sin servicio.

    Sesión de usuario (`usuario_sesion`) con el mismo criterio que `/api/infra/tracking/{ruta_id}/download`, que ya
    entrega el tracking completo de una ruta a cualquier usuario autenticado.

    `SIN_SEMILLA`/`SIN_CAMINO` responden **409** y no 200: no hay archivo que adjuntar, y un
    `.txt` que dice "no hay datos" es basura en la carpeta de Descargas de alguien.
    """
    from core.services.cromo.camino_optico_service import (
        ESTADO_SIN_SEMILLA,
        contar_semillas,
        listar_pelos_semilla,
        pelo_pertenece_al_servicio,
        semillas_por_defecto,
    )
    from core.services.cromo.camino_optico_txt import (
        nombre_archivo_adicional,
        nombre_archivo_tracking,
    )
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo import tracking_service
    from core.services.cromo.servicio_posicion_vigente import (
        declaradas_validas,
        pelos_de_posiciones,
        posiciones_posibles,
    )
    from core.services.cromo.tracking_service import (
        TrackingNoDisponible,
        nombre_archivo_tramo,
        nombre_distinguible,
        obtener_tracking,
    )
    from db.session import AsyncSessionLocal

    usuario = sesion_usuario.username
    if tramo is not None and adicional is not None:
        return JSONResponse(
            {"error": "Pedí un tramo o un adicional, no los dos a la vez."}, status_code=400
        )

    try:
        async with AsyncSessionLocal() as sesion:
            if not await _servicio_existe(sesion, servicio_id):
                return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)

            # El universo real, sin el tope de `listar_pelos_semilla`. Es lo que decide tanto si
            # hay camino posible como si el nombre del archivo tiene que distinguir el pelo.
            total_pelos, _con_odf = await contar_semillas(sesion, servicio_id)
            # El pelo no tiene la etiqueta del Servicio: es de una de sus posiciones. Se nombra con
            # el número del Servicio y, si no está declarado, se cachea sin servicio (la traza y la
            # API v1 leen esa columna).
            solo_de_posicion = False
            servicio_cache: Optional[int] = servicio_id

            if pelo_n_id is not None:
                # Pertenencia por consulta directa, NO contra la lista truncada de semillas: con
                # el tope de 20 sobre cientos de pelos matcheados, un pelo legítimo que el propio
                # selector acababa de ofrecer se rechazaba como ajeno (bug real, Servicio 93154).
                # Va antes del 409 "sin semilla": un pelo ajeno pedido desde un Servicio sin
                # semillas etiquetadas (el 42352 pidiendo uno del 42351) es 400.
                if not await pelo_pertenece_al_servicio(sesion, servicio_id, pelo_n_id):
                    # Sólo las declaradas que el inventario sostiene (`declaradas_validas`): el pelo
                    # viejo de una con PELO_CAMBIO pendiente de retiro ni pasa la guarda por ser
                    # "declarado" ni se cachea con el Servicio (re-atribuiría la fila a la traza y a
                    # la API v1). Si sigue siendo posición posible se baja, sin servicio.
                    validos = {d.pelo_declarado for d in await declaradas_validas(sesion, servicio_id)}
                    if pelo_n_id in validos:
                        servicio_cache = servicio_id
                    elif pelo_n_id in pelos_de_posiciones(
                        await posiciones_posibles(sesion, servicio_id)
                    ):
                        servicio_cache = None
                    else:
                        return JSONResponse(
                            {"error": f"El pelo {pelo_n_id} no pertenece al Servicio {servicio_id}."},
                            status_code=400,
                        )
                    solo_de_posicion = True
                elegido = pelo_n_id
            elif total_pelos > 0:
                # Sin pedido explícito, la posición de ODF del Servicio: mismo criterio que el
                # default del selector, así que pedir el `.txt` "a secas" baja lo mismo que el
                # botón de la pantalla.
                semillas = await listar_pelos_semilla(
                    sesion, servicio_id, priorizar_conector=True
                )
                elegido = semillas_por_defecto(semillas)[0].pelo_n_id
            else:
                # Sin semillas etiquetadas: la posición vigente declarada que el inventario sostiene
                # o, si no hay, la primera posición posible. Sin ninguna de las dos no hay camino que
                # resolver. Una declarada que `validar_en_db` ya invalidó no es candidata ni da
                # motivo para cachear con el Servicio.
                declarados_lista = [
                    d.pelo_declarado for d in await declaradas_validas(sesion, servicio_id)
                ]
                candidatos = declarados_lista or pelos_de_posiciones(
                    await posiciones_posibles(sesion, servicio_id)
                )
                if not candidatos:
                    return JSONResponse(
                        {
                            "error": (
                                "El Servicio no tiene ningún pelo en Cromo, así que no hay camino "
                                "que resolver."
                            ),
                            "estado": ESTADO_SIN_SEMILLA,
                        },
                        status_code=409,
                    )
                elegido = candidatos[0]
                solo_de_posicion = True
                servicio_cache = servicio_id if declarados_lista else None

            async with CromoClient(config=get_cromo_config()) as cliente:
                tracking = await obtener_tracking(
                    cliente, sesion, servicio_id=servicio_cache, pelo_n_id=elegido
                )
            if not tracking.desde_cache:
                # Evidencia para el árbitro, sólo del camino recién traído de Cromo. Nunca cambia
                # la respuesta HTTP.
                try:
                    from core.services.cromo.arbitro.evidencia import (
                        entradas_de_trackings,
                        registrar_y_encolar,
                    )

                    await registrar_y_encolar(
                        sesion,
                        servicio_id,
                        entradas_de_trackings([tracking]),
                        # Un solo tracking de Cromo; TrackingGenerado no informa truncamiento.
                        completo=True,
                        fuente="WEB",
                    )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "action=arbitro_evidencia evento=enganche_fallido servicio_id=%s",
                        servicio_id,
                        exc_info=True,
                    )
            numero_servicio = (
                await tracking_service.numero_del_servicio(sesion, servicio_id)
                if adicional is not None
                or solo_de_posicion
                or (tramo is not None and pelo_n_id is not None)
                else None
            )
    except TrackingNoDisponible as exc:
        return JSONResponse({"error": exc.motivo, "estado": exc.estado}, status_code=409)
    except CromoClientError as exc:
        return error_servicio_externo(
            "cromo_camino_tracking", exc, "Cromo no respondió", user=usuario, servicio_id=servicio_id
        )

    # Con un solo pelo (el caso PON) el nombre queda idéntico al de siempre; con varios se
    # intercala el n_id, porque si no los N archivos del mismo Servicio se pisan entre sí en la
    # carpeta de Descargas y se pierde cuál es cuál.
    # El nombre de tramo lleva el número del Servicio en LAS-FOCAS, no el at.62 del pelo (que Cromo
    # a veces trae mal); el at.62 del nombre base queda sólo como respaldo.
    # Un pelo que sólo es de posición nunca cae al at.62: es justamente el que está mal.
    base_at62 = None if solo_de_posicion else re.match(r"^(\d+) CROMO", tracking.nombre_archivo)
    if adicional is not None:
        nombre = nombre_archivo_adicional(numero_servicio, adicional, tracking.pelo_n_id)
    elif tramo is not None and pelo_n_id is not None:
        nombre = nombre_archivo_tramo(
            numero_servicio or (base_at62.group(1) if base_at62 else None), tramo, tracking.pelo_n_id
        )
    elif solo_de_posicion:
        nombre = nombre_distinguible(
            nombre_archivo_tracking(numero_servicio, tracking.pelo_n_id),
            tracking.pelo_n_id,
            distinguir=True,
        )
    else:
        nombre = nombre_distinguible(
            tracking.nombre_archivo, tracking.pelo_n_id, distinguir=total_pelos > 1
        )
    logger.info(
        "action=cromo_camino_tracking user=%s servicio_id=%s pelo_n_id=%s desde_cache=%s duracion_ms=%s",
        usuario,
        servicio_id,
        tracking.pelo_n_id,
        tracking.desde_cache,
        tracking.duracion_ms,
    )
    return Response(
        content=tracking.contenido,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


async def _inconsistencias_del_servicio(sesion: Any, servicio_id: int) -> dict[str, int]:
    """Casos de inconsistencias de Cromo que tocan al Servicio, para el aviso del panel Camino.
    Es accesorio: si falla (tabla sin migrar, DB caída) los caminos se devuelven igual."""
    from core.services.cromo.inconsistencias_cromo import resumen_de_servicio

    try:
        return await resumen_de_servicio(sesion, servicio_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "action=cromo_camino_inconsistencias_error servicio_id=%s error=%s", servicio_id, exc
        )
        return {"cuarentena": 0, "en_revision": 0}


@router.get("/api/infra/cromo/servicios/{servicio_id}/camino-optico/caminos")
async def cromo_camino_caminos_web(
    servicio_id: int,
    sesion_usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Los caminos del Servicio, separados en tramos y residuales.

    Es lo mismo que hace `@bot track` en Slack (`tracking_service.trackings_del_servicio`): recorre
    todas las semillas —posiciones de ODF primero, después los pelos de los cables— descartando
    las que ya recorrió un camino, sin cortar en los caminos esperados (tope de llamadas
    `CROMO_TRACKING_MAX_LLAMADAS`), y clasifica cada camino como TRAMO o RESIDUAL. **Va a Cromo**:
    4,6-14 s por camino en frío; deja cacheado cada tracking, así que bajar los `.txt` después es
    inmediato.

    Contrato: `tramos[{n, pelo_n_id, nombre_archivo, pelos_en_camino, desde_cache, extremos,
    odfs}]` (ya ordenados; `n` es el número de tramo del nombre del `.txt`), `residuales[...]` sin
    `n` ni `desde_cache` (no se descargan), `esperados_declarados` (o `null`, lo declara el
    operador), `completo`, `errores`, `no_cubiertos` (cantidad de semillas sin camino: fallaron o no
    se llegaron a pedir), `tope_llamadas` (se tocó `CROMO_TRACKING_MAX_LLAMADAS`) y `segmentos`
    (grupos de tramos que comparten cables). `odf_confirmadas` son las ODF que un admin confirmó
    para el Servicio (`odf_n_id`, `rol`, `odf_nombre`, `odf_tipo`, ...). `extremos` es `{a, b}`
    con `tipo`, `odf_n_id`, `odf_nombre`, `odf_clase`, `patchera_nombre`, `conector` e `id_cromo`.
    `odfs` son TODAS las ODF que toca el camino (extremos e intermedias) con `odf_n_id` de linaje,
    `odf_nombre` y `odf_clase`: la UI ofrece confirmar cualquiera, también las de un residual.

    Posición vigente (aditivo): cada tramo suma `rol` (`VIGENTE` si sale de la posición declarada,
    `TRAMO` si no) y `completo` (ODF en los dos extremos). `adicionales[{n, pelo_n_id,
    nombre_archivo, pelos_en_camino, extremos, odfs, desde_cache, completo, origen, posiciones,
    etiquetas}]` son recorridos reales del Servicio que no son por donde va (`n` es el `A{n}` del
    `.txt`; `origen` es `DECLARADO`, `ETIQUETADO` o `POSICION`; `posiciones`, `"O-1252871-1:1,2"`;
    `etiquetas`, las de sus pelos). `caminos_resueltos` = tramos + adicionales (lo que baja `track
    N full`). `posicion_vigente` es `{declarada, aplicada, posiciones, avisos[{conector_n_id,
    posicion, codigo, retirada, texto}]}`: `aplicada=False` con declaración quiere decir que esta
    corrida usó el cálculo automático.

    Existe porque la preselección de `/pelos` es SQL local y sin ODF no puede saber qué pelos son
    del mismo hilo: el 94673 (sin ODF en sus extremos) preseleccionaba uno solo de sus 2 caminos.
    """
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.servicio_odf_confirmacion import datos_de_odfs, n_ids_de_odfs
    from core.services.cromo.servicio_posicion_vigente import etiqueta_posiciones, texto_aviso
    from core.services.cromo.tracking_service import es_camino_completo, trackings_del_servicio
    from db.session import AsyncSessionLocal

    usuario = sesion_usuario.username
    try:
        async with AsyncSessionLocal() as sesion:
            if not await _servicio_existe(sesion, servicio_id):
                return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
            async with CromoClient(config=get_cromo_config()) as cliente:
                resultado = await trackings_del_servicio(cliente, sesion, servicio_id)
            # Los caminos pueden traer el id de versión de la ODF: se expone siempre el n_id. Entran
            # las de los extremos y las intermedias (`odfs`), de tramos, adicionales y residuales.
            ids_odf: list[int] = []
            for t in (*resultado.tramos, *resultado.adicionales, *resultado.residuales):
                if not t.extremos:
                    continue
                ids_odf.extend(e.odf_id for e in t.extremos.extremos if e.odf_id is not None)
                ids_odf.extend(t.extremos.odfs)
            ids_odf = list(dict.fromkeys(ids_odf))
            n_ids_odf = await n_ids_de_odfs(sesion, ids_odf)
            # Nombre y clase de cada ODF, también de las intermedias: una sola query.
            datos_odf = await datos_de_odfs(
                sesion, list(dict.fromkeys(n_ids_odf.get(i, i) for i in ids_odf))
            )
            inconsistencias = await _inconsistencias_del_servicio(sesion, servicio_id)
    except CromoClientError as exc:
        return error_servicio_externo(
            "cromo_camino_caminos", exc, "Cromo no respondió", user=usuario, servicio_id=servicio_id
        )

    logger.info(
        "action=cromo_camino_caminos user=%s servicio_id=%s tramos=%s adicionales=%s residuales=%s "
        "completo=%s posicion_aplicada=%s",
        usuario,
        servicio_id,
        len(resultado.tramos),
        len(resultado.adicionales),
        len(resultado.residuales),
        resultado.completo,
        resultado.posicion.aplicada,
    )

    def _extremo(e: Any) -> Optional[dict[str, Any]]:
        if e is None:
            return None
        return {
            "tipo": e.tipo,
            "id_cromo": e.id_cromo,
            "odf_n_id": n_ids_odf.get(e.odf_id, e.odf_id) if e.odf_id is not None else None,
            "odf_nombre": e.odf_nombre,
            "odf_clase": e.odf_clase,
            "patchera_nombre": e.patchera_nombre,
            "conector": e.conector_numero,
        }

    def _odfs(resumen: Any) -> list[dict[str, Any]]:
        """Todas las ODF del camino, por n_id y sin repetir. Si la ODF no está ingerida, el nombre y
        la clase salen del extremo del payload (cuando es uno)."""
        if resumen is None:
            return []
        del_payload = {
            n_ids_odf.get(e.odf_id, e.odf_id): (e.odf_nombre, e.odf_clase)
            for e in resumen.extremos
            if e.odf_id is not None
        }
        salida: dict[int, dict[str, Any]] = {}
        for odf_id in (*resumen.odfs, *del_payload):
            n_id = n_ids_odf.get(odf_id, odf_id)
            if n_id in salida:
                continue
            nombre, clase = datos_odf.get(n_id) or del_payload.get(n_id) or (None, None)
            salida[n_id] = {"odf_n_id": n_id, "odf_nombre": nombre, "odf_clase": clase}
        return list(salida.values())

    def _camino(t: Any) -> dict[str, Any]:
        resumen = t.extremos
        return {
            "pelo_n_id": t.pelo_n_id,
            "nombre_archivo": t.nombre_archivo,
            "pelos_en_camino": len(t.pelos_camino),
            "extremos": {
                "a": _extremo(resumen.inicio) if resumen else None,
                "b": _extremo(resumen.fin) if resumen else None,
            },
            "odfs": _odfs(resumen),
        }

    tramos = [
        {
            "n": n,
            **_camino(t),
            "desde_cache": t.desde_cache,
            "rol": t.rol,
            "completo": es_camino_completo(t),
        }
        for n, t in enumerate(resultado.tramos, start=1)
    ]
    # `info_adicionales` viene alineada con `adicionales`; se cruza por pelo por si no lo estuviera.
    info_por_pelo = {i.pelo_n_id: i for i in resultado.info_adicionales}

    def _adicional(n: int, t: Any) -> dict[str, Any]:
        info = info_por_pelo.get(t.pelo_n_id)
        return {
            "n": n,
            **_camino(t),
            "desde_cache": t.desde_cache,
            "completo": es_camino_completo(t),
            "origen": info.origen if info else None,
            "posiciones": etiqueta_posiciones(info.posiciones) if info else "",
            "etiquetas": list(info.etiquetas) if info else [],
        }

    adicionales = [_adicional(n, t) for n, t in enumerate(resultado.adicionales, start=1)]
    posicion = resultado.posicion
    return JSONResponse(
        {
            "tramos": tramos,
            "adicionales": adicionales,
            "caminos_resueltos": len(tramos) + len(adicionales),
            "posicion_vigente": {
                "declarada": bool(posicion.declaradas),
                "aplicada": posicion.aplicada,
                "posiciones": posicion.etiqueta,
                "avisos": [
                    {
                        "conector_n_id": a.conector_n_id,
                        "posicion": a.posicion,
                        "codigo": a.codigo,
                        "retirada": a.retirada,
                        "texto": texto_aviso(a),
                    }
                    for a in posicion.avisos
                ],
            },
            "residuales": [_camino(t) for t in resultado.residuales],
            "esperados_declarados": resultado.esperados_declarados,
            "odf_confirmadas": resultado.odf_confirmadas,
            "completo": resultado.completo,
            "errores": resultado.errores,
            "no_cubiertos": len(resultado.no_cubiertos),
            "tope_llamadas": resultado.tope_llamadas,
            "segmentos": resultado.segmentos,
            "inconsistencias": inconsistencias,
        }
    )


class HuerfanosRevisarRequestModel(BaseModel):
    """Payload para normalizar o descartar filas de la auditoría de huérfanos, en lote."""

    ids: list[int] = Field(min_length=1, max_length=500, description="Ids de cromo_auditoria_huerfanos")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class HuerfanosAuditoriaGlobalRequestModel(BaseModel):
    """Payload para lanzar la auditoría global de huérfanos (corrida en el cromo_worker)."""

    max_servicios: int | None = Field(
        default=None, ge=1, le=2000, description="Tope de Servicios; default CROMO_AUDITORIA_MAX_SERVICIOS"
    )
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.get("/api/admin/infra/huerfanos", dependencies=[Depends(usuario_admin)])
async def huerfanos_listar_web(
    servicio_id: Optional[int] = None,
    causa: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Viewer de huérfanos: pelos de caminos RESIDUALES con causa sugerida, evidencia y estado.

    Filtros `servicio_id` (PK de `app.servicios`), `causa` y `estado`. `conteos_por_causa` sale con
    los filtros de servicio y estado, antes del de causa (chips). Admin.
    """
    from core.services.cromo.auditoria_huerfanos import CAUSAS, ESTADOS, listar_huerfanos
    from db.session import AsyncSessionLocal

    if causa is not None and causa not in CAUSAS:
        return JSONResponse({"error": f"causa inválida. Valores: {list(CAUSAS)}"}, status_code=400)
    if estado is not None and estado not in ESTADOS:
        return JSONResponse({"error": f"estado inválido. Valores: {list(ESTADOS)}"}, status_code=400)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    async with AsyncSessionLocal() as sesion:
        pagina = await listar_huerfanos(
            sesion, servicio_id=servicio_id, causa=causa, estado=estado, limit=limit, offset=offset
        )
    return JSONResponse(pagina)


@router.post("/api/admin/infra/huerfanos/normalizar")
async def huerfanos_normalizar_web(
    request: Request,
    body: HuerfanosRevisarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Normaliza en lote: excluye del Servicio el pelo de cada fila (`origen=AUDITORIA`).

    Qué se puede normalizar lo decide el servidor con la fila guardada: sólo PENDIENTE, no
    protegida y con causa habilitada (hoy sólo `CABLE_DESUSO`). Lo demás vuelve en `rechazados`
    con su motivo. Reversible con "Restaurar" del panel del camino. Admin + CSRF.
    """
    from core.services.cromo.auditoria_huerfanos import normalizar
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_huerfanos_normalizar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        resultado = await normalizar(sesion, body.ids, usuario=username)
    return JSONResponse(
        {"ok": True, "aplicados": resultado.aplicados, "rechazados": resultado.rechazados}
    )


@router.post("/api/admin/infra/huerfanos/descartar")
async def huerfanos_descartar_web(
    request: Request,
    body: HuerfanosRevisarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Marca DESCARTADO las filas PENDIENTE elegidas (revisadas, no son huérfanos). Admin + CSRF."""
    from core.services.cromo.auditoria_huerfanos import descartar
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_huerfanos_descartar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        resultado = await descartar(sesion, body.ids, usuario=username)
    return JSONResponse(
        {"ok": True, "aplicados": resultado.aplicados, "rechazados": resultado.rechazados}
    )


@router.get("/api/admin/infra/huerfanos/auditoria-global", dependencies=[Depends(usuario_admin)])
async def huerfanos_auditoria_global_estado_web() -> JSONResponse:
    """Última auditoría global (o `null`), para que el Viewer muestre su estado al abrir. Admin."""
    from core.services.cromo.auditoria_huerfanos_global import (
        max_servicios_configurado,
        ultima_auditoria,
    )
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        corrida = await ultima_auditoria(sesion)
    return JSONResponse(
        {
            "corrida": _serializar_cromo_corrida(corrida) if corrida is not None else None,
            "max_servicios_default": max_servicios_configurado(),
        }
    )


@router.post("/api/admin/infra/huerfanos/auditoria-global")
async def huerfanos_auditoria_global_iniciar_web(
    request: Request,
    body: HuerfanosAuditoriaGlobalRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Lanza la auditoría global: corrida sintética que ejecuta el `cromo_worker` (tiene las
    credenciales de Cromo). Recorre los Servicios Activos con más pelos hasta el tope. El progreso
    se sigue con el SSE de corridas (`/api/admin/ingesta/cromo/corridas/{id}/stream`).
    Una sola a la vez: si hay otra EN_CURSO devuelve 409 con su id. Admin + CSRF.
    """
    from core.services.cromo.auditoria_huerfanos_global import (
        iniciar_si_no_hay_otra,
        max_servicios_configurado,
    )
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_huerfanos_auditoria_global", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    tope = body.max_servicios or max_servicios_configurado()
    async with AsyncSessionLocal() as sesion:
        # Chequeo + alta bajo advisory lock: dos POST simultáneos no lanzan dos auditorías.
        corrida, en_curso = await iniciar_si_no_hay_otra(
            sesion, usuario=username, max_servicios=tope
        )
        if corrida is None:
            return JSONResponse(
                {"error": "Ya hay una auditoría global en curso.", "corrida_id": en_curso},
                status_code=409,
            )
        corrida_id = corrida.id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _CROMO_WORKER_RUN_URL, json={"corrida_id": corrida_id, "usuario": username}
            )
            response.raise_for_status()
    except Exception as exc:
        # El texto de la excepción (puede traer la URL interna del worker) va sólo al log; el evento
        # ERROR de la corrida, que ve la UI de admin, lleva un motivo fijo con la misma ref.
        ref = nueva_ref()
        logger.error(
            "action=cromo_huerfanos_auditoria_global_error corrida_id=%s error=%s ref=%s", corrida_id, exc, ref
        )
        await _marcar_corrida_fallida(
            corrida_id, f"No se pudo delegar la auditoría al worker de Cromo (ref {ref})"
        )
        return JSONResponse(
            {"error": "El worker de Cromo no está disponible. Intentá nuevamente en unos segundos."},
            status_code=503,
        )
    logger.info(
        "action=cromo_huerfanos_auditoria_global user=%s corrida_id=%s max_servicios=%s",
        username,
        corrida_id,
        tope,
    )
    return JSONResponse({"corrida_id": corrida_id, "max_servicios": tope}, status_code=202)


class InconsistenciasEstadoRequestModel(BaseModel):
    """Payload para cambiar el estado de casos de inconsistencias, en lote."""

    ids: list[int] = Field(min_length=1, max_length=500, description="Ids de cromo_inconsistencia")
    estado: str = Field(description="CUARENTENA | ACEPTADA | REPORTADA | PENDIENTE (liberar)")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class InconsistenciasDeteccionRequestModel(BaseModel):
    """Payload para lanzar la detección manual de inconsistencias."""

    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.get("/api/admin/infra/inconsistencias-cromo", dependencies=[Depends(usuario_admin)])
async def inconsistencias_cromo_listar_web(
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    revision: Optional[str] = None,
    localidad: Optional[str] = None,
    servicio: Optional[str] = None,
    servicio_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Viewer de inconsistencias de Cromo: casos detectados (isla de fusiones, cable sin extremo,
    elemento isla) con revisión, estado y evidencia. Filtros `tipo`, `estado`, `revision`,
    `localidad` (ILIKE), `servicio` (número) y `servicio_id` (PK de `app.servicios`).
    `conteos_por_tipo` sale con todos los filtros salvo el de tipo (chips). Admin."""
    from fastapi.encoders import jsonable_encoder

    from core.services.cromo.inconsistencias_cromo import (
        ESTADOS,
        REVISIONES,
        TIPOS,
        listar,
    )
    from db.session import AsyncSessionLocal

    if tipo is not None and tipo not in TIPOS:
        return JSONResponse({"error": f"tipo inválido. Valores: {list(TIPOS)}"}, status_code=400)
    if estado is not None and estado not in ESTADOS:
        return JSONResponse({"error": f"estado inválido. Valores: {list(ESTADOS)}"}, status_code=400)
    if revision is not None and revision not in REVISIONES:
        return JSONResponse(
            {"error": f"revision inválida. Valores: {list(REVISIONES)}"}, status_code=400
        )
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    async with AsyncSessionLocal() as sesion:
        pagina = await listar(
            sesion,
            tipo=tipo,
            estado=estado,
            revision=revision,
            localidad=localidad or None,
            servicio=servicio or None,
            servicio_id=servicio_id,
            por_pagina=limit,
            desplazamiento=offset,
        )
    return JSONResponse(jsonable_encoder(pagina))


@router.get("/api/admin/infra/inconsistencias-cromo/exportar.xlsx")
async def inconsistencias_cromo_exportar_web(
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    revision: Optional[str] = None,
    localidad: Optional[str] = None,
    servicio: Optional[str] = None,
    servicio_id: Optional[int] = None, usuario: UsuarioSesion = Depends(usuario_admin),
) -> Response:
    """XLSX "para corregir en Cromo": una hoja por localidad, con tipo, revisión, estado, objeto,
    ID Cromo, qué falta, servicios afectados y fechas. Mismos filtros que el listado; sin `estado`
    exporta sólo lo accionable (PENDIENTE, CUARENTENA, REPORTADA). Admin."""
    from core.services.cromo import inconsistencias_reporte as reporte
    from core.services.cromo.inconsistencias_cromo import ESTADOS, REVISIONES, TIPOS
    from db.session import AsyncSessionLocal

    username = usuario.username
    if tipo is not None and tipo not in TIPOS:
        return JSONResponse({"error": f"tipo inválido. Valores: {list(TIPOS)}"}, status_code=400)
    if estado is not None and estado not in ESTADOS:
        return JSONResponse({"error": f"estado inválido. Valores: {list(ESTADOS)}"}, status_code=400)
    if revision is not None and revision not in REVISIONES:
        return JSONResponse(
            {"error": f"revision inválida. Valores: {list(REVISIONES)}"}, status_code=400
        )
    try:
        async with AsyncSessionLocal() as sesion:
            filas = await reporte.filas_reporte(
                sesion,
                tipo=tipo,
                estado=estado,
                revision=revision,
                localidad=localidad or None,
                servicio=servicio or None,
                servicio_id=servicio_id,
            )
        contenido = await asyncio.to_thread(reporte.generar_xlsx, filas)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("inconsistencias_cromo_exportar", exc)
    logger.info("action=inconsistencias_cromo_exportar user=%s filas=%d", username, len(filas))
    sello = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="inconsistencias_cromo_{sello}.xlsx"'},
    )


class InconsistenciasAvisoSlackRequestModel(BaseModel):
    """Payload para configurar el aviso de casos nuevos a Slack."""

    slack_channels: str = Field(default="", description="Canales (#nombre o ID C/G/D...) separados por coma")
    activo: bool = Field(default=False, description="Si el aviso a Slack está encendido")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.get("/api/admin/infra/inconsistencias-cromo/aviso-slack", dependencies=[Depends(usuario_admin)])
async def inconsistencias_cromo_aviso_slack_get_web() -> JSONResponse:
    """Config del aviso de casos nuevos a Slack (fila "Cromo Inconsistencias"). Admin."""
    from core.services.cromo.inconsistencias_reporte import leer_config_aviso
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        return JSONResponse(await leer_config_aviso(sesion))


@router.post("/api/admin/infra/inconsistencias-cromo/aviso-slack")
async def inconsistencias_cromo_aviso_slack_post_web(
    request: Request,
    body: InconsistenciasAvisoSlackRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Guarda canales y activación del aviso a Slack. Mismas reglas de formato de canal que el
    resto de los servicios de Slack. Admin + CSRF."""
    from core.services.cromo.inconsistencias_reporte import guardar_config_aviso, normalizar_canales
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_inconsistencias_aviso_slack", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    canales = normalizar_canales(body.slack_channels)
    if len(canales) > 512:
        return JSONResponse({"error": "Los canales no deben superar 512 caracteres"}, status_code=400)
    if any(not _es_destino_slack_valido(c) for c in canales.split(",") if c):
        return JSONResponse(
            {"error": "Cada destino debe ser un nombre de canal con # o un ID de Slack tipo C/G/D..."},
            status_code=400,
        )
    if body.activo and not canales:
        return JSONResponse({"error": "Para activar el aviso hay que indicar al menos un canal"}, status_code=400)
    async with AsyncSessionLocal() as sesion:
        await guardar_config_aviso(sesion, canales, body.activo)
        await sesion.commit()
    logger.info(
        "action=cromo_inconsistencias_aviso_slack user=%s activo=%s canales=%s", username, body.activo, canales
    )
    return JSONResponse({"ok": True, "slack_channels": canales, "activo": body.activo})


@router.post("/api/admin/infra/inconsistencias-cromo/estado")
async def inconsistencias_cromo_estado_web(
    request: Request,
    body: InconsistenciasEstadoRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Cambia el estado de los casos elegidos (cuarentena, aceptar, reportar o liberar a
    PENDIENTE). Las transiciones válidas las decide el servidor (`cambiar_estado`): lo que no se
    puede vuelve en `rechazados` con su motivo. Admin + CSRF."""
    from core.services.cromo.inconsistencias_cromo import ESTADOS_DESTINO_MANUAL, cambiar_estado
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_inconsistencias_estado", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    if body.estado not in ESTADOS_DESTINO_MANUAL:
        return JSONResponse(
            {"error": f"estado inválido. Valores: {sorted(ESTADOS_DESTINO_MANUAL)}"}, status_code=400
        )
    async with AsyncSessionLocal() as sesion:
        resultado = await cambiar_estado(sesion, body.ids, body.estado, username)
        await sesion.commit()
    if resultado["actualizados"]:
        await _encolar_arbitro("TODO", [], f"inconsistencias-estado estado={body.estado}")
    logger.info(
        "action=cromo_inconsistencias_estado user=%s estado=%s aplicados=%s rechazados=%s",
        username,
        body.estado,
        len(resultado["actualizados"]),
        len(resultado["rechazados"]),
    )
    return JSONResponse(
        {"ok": True, "aplicados": resultado["actualizados"], "rechazados": resultado["rechazados"]}
    )


@router.get("/api/admin/infra/inconsistencias-cromo/deteccion", dependencies=[Depends(usuario_admin)])
async def inconsistencias_cromo_deteccion_estado_web() -> JSONResponse:
    """Última corrida del detector (o `null`), para que el Viewer muestre su estado al abrir. Admin."""
    from core.services.cromo.inconsistencias_cromo import ultima_deteccion
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        corrida = await ultima_deteccion(sesion)
    return JSONResponse(
        {"corrida": _serializar_cromo_corrida(corrida) if corrida is not None else None}
    )


@router.post("/api/admin/infra/inconsistencias-cromo/deteccion")
async def inconsistencias_cromo_deteccion_iniciar_web(
    request: Request,
    body: InconsistenciasDeteccionRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Lanza el detector a mano: corrida sintética que ejecuta el `cromo_worker` (tiene las
    credenciales de Cromo para confirmar cables en vivo). El progreso se sigue con el SSE de
    corridas. Una sola a la vez: si hay otra detección o una ingesta EN_CURSO devuelve 409 con su
    id. Admin + CSRF."""
    from core.services.cromo.inconsistencias_cromo import iniciar_si_no_hay_otra
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_inconsistencias_deteccion", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        corrida, en_curso = await iniciar_si_no_hay_otra(sesion, usuario=username, origen="MANUAL")
        if corrida is None:
            return JSONResponse(
                {"error": "Hay una detección o una ingesta en curso.", "corrida_id": en_curso},
                status_code=409,
            )
        corrida_id = corrida.id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _CROMO_WORKER_RUN_URL, json={"corrida_id": corrida_id, "usuario": username}
            )
            response.raise_for_status()
    except Exception as exc:
        # El texto de la excepción (puede traer la URL interna del worker) va sólo al log; el evento
        # ERROR de la corrida, que ve la UI de admin, lleva un motivo fijo con la misma ref.
        ref = nueva_ref()
        logger.error(
            "action=cromo_inconsistencias_deteccion_error corrida_id=%s error=%s ref=%s", corrida_id, exc, ref
        )
        await _marcar_corrida_fallida(
            corrida_id, f"No se pudo delegar la detección al worker de Cromo (ref {ref})"
        )
        return JSONResponse(
            {"error": "El worker de Cromo no está disponible. Intentá nuevamente en unos segundos."},
            status_code=503,
        )
    logger.info("action=cromo_inconsistencias_deteccion user=%s corrida_id=%s", username, corrida_id)
    return JSONResponse({"corrida_id": corrida_id}, status_code=202)


class ArbitroPropuestasRequestModel(BaseModel):
    """Payload para decidir propuestas del árbitro de Cromo (aplicar, rechazar, revertir), en lote."""

    ids: list[int] = Field(min_length=1, max_length=500, description="Ids de cromo_propuesta")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class ArbitroReglaRequestModel(BaseModel):
    """Payload para cambiar la configuración de una regla del árbitro."""

    codigo: str
    modo: str = Field(description="APAGADA | SOMBRA | AUTO")
    umbral: int
    presupuesto_por_corrida: int
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class ArbitroNormalizarRequestModel(BaseModel):
    """Payload del análisis retroactivo: reglas a correr (None = todas)."""

    reglas: Optional[list[str]] = None
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.get("/api/admin/infra/arbitro-cromo/propuestas", dependencies=[Depends(usuario_admin)])
async def arbitro_cromo_propuestas_web(
    regla: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    """Lista paginada de propuestas del árbitro de Cromo, filtrable por regla y estado. Admin."""
    from fastapi.encoders import jsonable_encoder
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        resultado = await motor.listar_propuestas(
            sesion, regla=regla, estado=estado, limit=limit, offset=offset
        )
    return JSONResponse(jsonable_encoder(resultado))


async def _encolar_arbitro_tras_decision(sesion, ids: Sequence[int], motivo: str) -> None:
    """Encola una evaluación VIEWER por tipo de objeto tocado. Best-effort: nunca altera la respuesta."""
    try:
        from core.services.cromo.arbitro import evaluaciones

        alcances = await evaluaciones.alcances_de_propuestas(sesion, ids)
        for tipo, objeto_ids in alcances.items():
            await _encolar_arbitro(tipo, objeto_ids, motivo)
    except Exception:  # noqa: BLE001
        logger.warning("action=arbitro_encolar_viewer result=fail motivo=%s", motivo, exc_info=True)


@router.post("/api/admin/infra/arbitro-cromo/propuestas/aplicar")
async def arbitro_cromo_aplicar_web(
    request: Request, body: ArbitroPropuestasRequestModel, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Aplica propuestas a mano. Lo que no se puede vuelve en `rechazados` con su motivo. Admin + CSRF."""
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "arbitro_cromo_propuestas", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        resultado = await motor.aplicar_manual(sesion, body.ids, username)
        await sesion.commit()
        if resultado["aplicados"]:
            await _encolar_arbitro_tras_decision(sesion, resultado["aplicados"], f"arbitro-aplicar user={username}")
    return JSONResponse({"ok": True, **resultado})


@router.post("/api/admin/infra/arbitro-cromo/propuestas/rechazar")
async def arbitro_cromo_rechazar_web(
    request: Request, body: ArbitroPropuestasRequestModel, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Rechaza propuestas (la decisión humana bloquea re-proponer con la misma evidencia). Admin + CSRF."""
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "arbitro_cromo_propuestas", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        resultado = await motor.rechazar(sesion, body.ids, username)
        await sesion.commit()
    return JSONResponse({"ok": True, **resultado})


@router.post("/api/admin/infra/arbitro-cromo/propuestas/revertir")
async def arbitro_cromo_revertir_web(
    request: Request, body: ArbitroPropuestasRequestModel, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Revierte propuestas en observación o aplicadas. Lo que no se puede vuelve en `omitidos`. Admin + CSRF."""
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "arbitro_cromo_propuestas", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        resultado = await motor.revertir_manual(sesion, body.ids, username)
        await sesion.commit()
        if resultado["revertidos"]:
            await _encolar_arbitro_tras_decision(sesion, resultado["revertidos"], f"arbitro-revertir user={username}")
    return JSONResponse({"ok": True, **resultado})


@router.get("/api/admin/infra/arbitro-cromo/reglas", dependencies=[Depends(usuario_admin)])
async def arbitro_cromo_reglas_web() -> JSONResponse:
    """Configuración de cada regla con su precisión histórica y si conviene pasarla a AUTO. Admin."""
    from fastapi.encoders import jsonable_encoder
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        reglas = await motor.precision_por_regla(sesion)
    return JSONResponse({"reglas": jsonable_encoder(reglas)})


@router.post("/api/admin/infra/arbitro-cromo/reglas")
async def arbitro_cromo_reglas_actualizar_web(
    request: Request, body: ArbitroReglaRequestModel, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Cambia modo, umbral y presupuesto de una regla. 422 ante valores inválidos. Admin + CSRF."""
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "arbitro_cromo_reglas", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        try:
            await motor.actualizar_regla(
                sesion,
                body.codigo,
                modo=body.modo,
                umbral=body.umbral,
                presupuesto_por_corrida=body.presupuesto_por_corrida,
                usuario=username,
            )
        except ValueError as exc:
            raise DatoInvalido(str(exc)) from exc
        await sesion.commit()
    return JSONResponse({"ok": True})


@router.post("/api/admin/infra/arbitro-cromo/normalizar")
async def arbitro_cromo_normalizar_web(
    request: Request, body: ArbitroNormalizarRequestModel, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Lanza el análisis retroactivo (alcance TODO) en el worker. 409 si ya hay otro en curso
    (EN_COLA/EN_CURSO de las últimas 6 h); 422 si alguna regla no existe. Admin + CSRF."""
    from core.services.cromo.arbitro import evaluaciones
    from core.services.cromo.arbitro.cola import encolar_evaluacion
    from core.services.cromo.arbitro.reglas import REGLAS
    from core.services.cromo.arbitro.senales import Alcance
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "arbitro_cromo_normalizar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    reglas = body.reglas or None  # lista vacía = todas las reglas
    desconocidas = sorted(set(reglas or []) - {r.codigo for r in REGLAS})
    if desconocidas:
        return JSONResponse({"error": f"Reglas inexistentes: {desconocidas}"}, status_code=422)
    async with AsyncSessionLocal() as sesion:
        evaluacion_id, en_curso = await evaluaciones.crear_evaluacion_normalizador(
            sesion, username, reglas
        )
        if evaluacion_id is None:
            return JSONResponse(
                {"error": "Ya hay un análisis retroactivo en curso.", "evaluacion_id": en_curso},
                status_code=409,
            )
        await sesion.commit()
    encolada = await encolar_evaluacion(
        Alcance("TODO"), "NORMALIZADOR", motivo=f"manual:{username}",
        evaluacion_id=evaluacion_id, reglas=reglas,
    )
    if not encolada:
        # Sin cola no hay worker que la tome: se cierra la fila para no bloquear con 409 durante 6 h.
        async with AsyncSessionLocal() as sesion:
            await evaluaciones.marcar_fallida(sesion, evaluacion_id, evaluaciones.ERROR_NO_ENCOLADA)
            await sesion.commit()
        return JSONResponse(
            {"error": "No se pudo encolar el análisis retroactivo. Intentá nuevamente.", "evaluacion_id": evaluacion_id},
            status_code=503,
        )
    logger.info("action=arbitro_cromo_normalizar user=%s evaluacion_id=%s", username, evaluacion_id)
    return JSONResponse({"evaluacion_id": evaluacion_id}, status_code=202)


@router.get("/api/admin/infra/arbitro-cromo/evaluaciones", dependencies=[Depends(usuario_admin)])
async def arbitro_cromo_evaluaciones_web(
    limit: int = Query(10, ge=1, le=50)
) -> JSONResponse:
    """Últimas evaluaciones del árbitro y el id de la que está en curso (o `null`). Admin."""
    from fastapi.encoders import jsonable_encoder
    from core.services.cromo.arbitro import evaluaciones
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        resultado = await evaluaciones.listar_evaluaciones(sesion, limit)
    return JSONResponse(jsonable_encoder(resultado))


def _serializar_cable_validacion(cable: Any) -> dict[str, Any]:
    return {
        "n_id": cable.n_id,
        "nombre": cable.nombre,
        "capacidad": cable.capacidad,
        "extremo_a_n_id": cable.extremo_a_n_id,
        "extremo_a_nombre": cable.extremo_a_nombre,
        "extremo_b_n_id": cable.extremo_b_n_id,
        "extremo_b_nombre": cable.extremo_b_nombre,
    }


def _serializar_tubo_validacion(tubo: Any) -> dict[str, Any]:
    return {"n_id": tubo.n_id, "cable_n_id": tubo.cable_n_id, "orden": tubo.orden, "nombre_color": tubo.nombre_color}


def _serializar_pelo_validacion(pelo: Any) -> dict[str, Any]:
    return {
        "n_id": pelo.n_id,
        "tubo_n_id": pelo.tubo_n_id,
        "cable_n_id": pelo.cable_n_id,
        "numero_pelo": pelo.numero_pelo,
        "color": pelo.color,
        "servicio_raw": pelo.servicio_raw,
        "servicio_numero": pelo.servicio_numero,
    }


def _serializar_fusion_validacion(fusion: Any) -> dict[str, Any]:
    return {
        "n_id": fusion.n_id,
        "botella_n_id": fusion.botella_n_id,
        "nombre_par": fusion.nombre_par,
        "pelo_a_n_id": fusion.pelo_a_n_id,
        "pelo_b_n_id": fusion.pelo_b_n_id,
    }


def _serializar_validacion_cromo(resultado: Any) -> dict[str, Any]:
    return {
        "n_id": resultado.n_id,
        "clase": resultado.clase,
        "tipo_objeto": resultado.tipo_objeto,
        "nombre": resultado.nombre,
        "notas": resultado.notas,
        "latitud": resultado.latitud,
        "longitud": resultado.longitud,
        "codigo_modelo": resultado.codigo_modelo,
        "id_legacy": resultado.id_legacy,
        "cables": [_serializar_cable_validacion(c) for c in resultado.cables],
        "tubos": [_serializar_tubo_validacion(t) for t in resultado.tubos],
        "pelos": [_serializar_pelo_validacion(p) for p in resultado.pelos],
        "fusiones": [_serializar_fusion_validacion(f) for f in resultado.fusiones],
        "errores_parseo": [{"n_id": e.n_id, "clase": e.clase, "motivo": e.motivo} for e in resultado.errores_parseo],
        "payload_raw": resultado.payload_raw,
    }


@router.get("/api/infra/cromo/validar/{n_id}")
async def cromo_validar_datos_web(n_id: int) -> JSONResponse:
    """"Validar datos DB Cromo" (Tool Kit) — consulta un n_id en vivo contra Cromo y le aplica el
    MISMO parseo que usa la ingesta (`parse_objeto`/`parse_arbol_botella`/`extraer_tubos_y_pelos`):
    árbol completo de cables/tubos/pelos/fusiones, no sólo los atributos planos del objeto. Distinto
    de `GET /api/infra/cromo/elementos/{n_id}/vivo` (ese es plano, sin árbol) y de
    `VerificadorCromoView.vue` (que consulta servicios ya matcheados contra el inventario YA
    ingerido) — herramienta separada, confirmada explícitamente con el usuario. Sin sesión de DB en
    absoluto: cero acceso a la base de datos local, ni siquiera en lectura. Los servicios de cada
    pelo se devuelven crudos (`servicio_raw`/`servicio_numero`), nunca matcheados contra
    `app.servicios`. Sólo lectura, cualquier usuario autenticado."""
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.validador_datos_service import validar_elemento_cromo
    from core.services.cromo.verificador import ObjetoNoEncontrado

    try:
        async with CromoClient(config=get_cromo_config()) as cliente:
            resultado = await validar_elemento_cromo(cliente, n_id)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc
    except CromoClientError as exc:
        return error_servicio_externo("cromo_validar_datos", exc, "Cromo no respondió", n_id=n_id)

    return JSONResponse(_serializar_validacion_cromo(resultado))


def _serializar_cable_detectado(cable: Any) -> dict[str, Any]:
    return {
        "n_id": cable.n_id,
        "nombre": cable.nombre,
        "extremo_a_n_id": cable.extremo_a_n_id,
        "extremo_b_n_id": cable.extremo_b_n_id,
        "estado_local": cable.estado_local,
    }


@router.get("/api/infra/cromo/botellas/{n_id}/cables-detectados")
async def cromo_botella_cables_detectados_web(n_id: int) -> JSONResponse:
    """Verificador Cromo — "Cables detectados en Cromo": consulta la botella en vivo (siguiendo
    `hist[]`/`next_id` si el `n_id` quedó vacío por un caso de "ID dual") y compara sus cables
    contra `app.cromo_cables` local. Sólo lectura, nunca persiste — mismo criterio que el resto de
    `/api/infra/cromo/*`, cualquier usuario autenticado. El botón de escritura correspondiente es
    `POST /api/infra/botellas/{n_id}/repoblar-cables` (sólo admin)."""
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.repoblacion_service import detectar_cables_faltantes
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion, CromoClient(config=get_cromo_config()) as cliente:
            resultado = await detectar_cables_faltantes(cliente, sesion, n_id)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc
    except CromoClientError as exc:
        return error_servicio_externo("cromo_botella_cables_detectados", exc, "Cromo no respondió", n_id=n_id)

    return JSONResponse(
        {
            "botella_n_id": resultado.botella_n_id,
            "ids_cadena": resultado.ids_cadena,
            "cables": [_serializar_cable_detectado(c) for c in resultado.cables],
        }
    )


class BotellaRepoblarCablesRequestModel(BaseModel):
    """Payload para repoblar los cables detectados en Cromo hacia la base local de una Botella."""

    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/infra/botellas/{n_id}/repoblar-cables")
async def botella_repoblar_cables_web(
    request: Request,
    n_id: int,
    body: BotellaRepoblarCablesRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Verificador Cromo — "Repoblar Cables": toma los cables que `GET .../cables-detectados`
    encontró faltantes o desactualizados y los persiste en `app.cromo_cables`/`cromo_tubos`/
    `cromo_pelos` local, con el extremo correctamente anclado a esta Botella. Nunca escribe hacia
    Cromo (`CromoClient` es de sólo lectura por diseño) ni toca `CromoBotella`/`CromoFusion`. Sólo
    admin — ver `core/services/cromo/repoblacion_service.py::repoblar_cables`."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botella_repoblar_cables result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.repoblacion_service import repoblar_cables
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion, CromoClient(config=get_cromo_config()) as cliente:
            resultado = await repoblar_cables(cliente, sesion, botella_n_id=n_id, usuario=username)
    except ObjetoNoEncontrado as exc:
        raise NoEncontrado(str(exc)) from exc
    except CromoClientError as exc:
        return error_servicio_externo("botella_repoblar_cables", exc, "Cromo no respondió", user=username, n_id=n_id)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("botella_repoblar_cables", exc, user=username, n_id=n_id)

    if resultado.corrida_id is not None:
        await encolar_recalculo_duplicados_botellas(motivo=f"repoblar-cables n_id={n_id} usuario={username}")
    return JSONResponse(
        {
            "ok": True,
            "corrida_id": resultado.corrida_id,
            "botella_n_id": resultado.botella_n_id,
            "creados": resultado.creados,
            "actualizados": resultado.actualizados,
            "sin_cambios": resultado.sin_cambios,
            "errores": resultado.errores,
            "detalle": [{"n_id": i.n_id, "accion": i.accion, "detalle": i.detalle} for i in resultado.detalle],
        }
    )


class BotellaActualizarNombreRequestModel(BaseModel):
    """Payload para corregir a mano el nombre de una Botella Cromo."""

    nombre: str = Field(min_length=1, max_length=500)
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.patch("/api/infra/botellas/{n_id}/nombre")
async def botella_actualizar_nombre_web(
    request: Request,
    n_id: int,
    body: BotellaActualizarNombreRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Verificador Cromo — corrección manual de nombre duplicado/incorrecto. Marca
    `nombre_editado_manual=True` para que ninguna corrida de ingesta futura la pise (ver
    `core/services/cromo/ingesta.py::_procesar_botella_completa`). Si la Botella ya existe
    localmente es escritura local pura y no toca Cromo. Si todavía no existe
    localmente (caso "ID dual": Cromo reportó la misma Botella física bajo otro n_id en una corrida
    anterior), LEE Cromo en vivo (`CromoClient` de sólo lectura) para crearla antes de aplicar la
    corrección — nunca escribe hacia Cromo. En ese camino la fila puede quedar bajo un n_id DISTINTO
    al de la URL (el de la URL puede ser un id de versión; Cromo manda con su n_id de linaje), así
    que el `n_id` de la respuesta es siempre el real, más `n_id_solicitado` cuando difieren.
    Sólo admin."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botella_actualizar_nombre result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    from db.models.cromo import CromoBotella
    from db.session import AsyncSessionLocal

    nombre_normalizado = body.nombre.strip()
    if not nombre_normalizado:
        return JSONResponse({"error": "El nombre no puede quedar vacío."}, status_code=400)

    async with AsyncSessionLocal() as sesion:
        botella = await sesion.get(CromoBotella, n_id)
        if botella is None:
            from core.services.cromo.botella_creacion_service import (
                IdentidadYaResueltaError,
                crear_o_actualizar_botella_desde_vivo,
            )
            from core.services.cromo.client import CromoClient, CromoClientError
            from core.services.cromo.config import CromoConfigError, get_cromo_config
            from core.services.cromo.parser import ClaseExcluidaError
            from core.services.cromo.verificador import ObjetoNoEncontrado

            try:
                async with CromoClient(config=get_cromo_config()) as cliente:
                    resultado = await crear_o_actualizar_botella_desde_vivo(
                        cliente, sesion, n_id=n_id, usuario=username
                    )
            except ObjetoNoEncontrado as exc:
                raise NoEncontrado(str(exc)) from exc
            except IdentidadYaResueltaError as exc:
                return JSONResponse(
                    {"error": str(exc), "n_id_correcto": exc.n_id_resuelto}, status_code=409
                )
            except ClaseExcluidaError as exc:
                raise ErrorDeDominio(f"n_id={n_id} no es una Botella: {exc}") from exc
            except CromoClientError as exc:
                return error_servicio_externo(
                    "botella_actualizar_nombre", exc, "Cromo no respondió", user=username, n_id=n_id
                )
            except CromoConfigError as exc:
                # Faltan credenciales/URL de Cromo: no es un 500 opaco, es "no pudimos hablar con
                # Cromo" — mismo 502 que `CromoClientError`, con la causa real en el log (con ref).
                return error_servicio_externo(
                    "botella_actualizar_nombre",
                    exc,
                    "Cromo no está configurado",
                    result="fail",
                    reason="cromo_no_configurado",
                    n_id=n_id,
                )
            except (HTTPException, ErrorDeDominio):
                raise
            except Exception as exc:
                # Red de seguridad final, mismo patrón que `botella_repoblar_cables_web`: cualquier
                # otra falla queda logueada con traza y la ref en vez de propagarse como 500 sin
                # contexto. No pasa por `error_interno` para conservar el texto `action=` de este log
                # (no termina en `_error`); la respuesta es la misma: 500 con ref, sin texto interno.
                ref = nueva_ref()
                logger.exception(
                    "action=botella_actualizar_nombre result=fail reason=error_inesperado n_id=%s error=%s ref=%s",
                    n_id,
                    exc,
                    ref,
                )
                return JSONResponse({"error": f"Error interno (ref {ref})"}, status_code=500)

            logger.info(
                "action=botella_creada_desde_vivo user=%s n_id=%s n_id_solicitado=%s accion=%s corrida_id=%s",
                username,
                resultado.n_id,
                n_id,
                resultado.accion,
                resultado.corrida_id,
            )
            # La fila puede haber quedado bajo un n_id distinto al del path: el solicitado puede ser
            # un id de versión y `crear_o_actualizar_botella_desde_vivo` ancla a la identidad de
            # linaje que reporta Cromo (ver su docstring).
            botella = await sesion.get(CromoBotella, resultado.n_id)

        n_id_final = botella.n_id
        botella.nombre = nombre_normalizado
        botella.nombre_editado_manual = True
        await sesion.commit()

    logger.info(
        "action=botella_actualizar_nombre user=%s n_id=%s n_id_solicitado=%s nombre=%r",
        username,
        n_id_final,
        n_id,
        nombre_normalizado,
    )
    await encolar_recalculo_duplicados_botellas(
        motivo=f"actualizar-nombre n_id={n_id_final} usuario={username}"
    )
    respuesta = {"ok": True, "n_id": n_id_final, "nombre": nombre_normalizado}
    if n_id_final != n_id:
        respuesta["n_id_solicitado"] = n_id
    return JSONResponse(respuesta)


class BotellaSepararPadreRequestModel(BaseModel):
    """Payload para separar una Botella Cromo de su Cámara padre actual hacia una Cámara nueva."""

    nombre: str = Field(min_length=1, max_length=255)
    motivo: str = Field(min_length=1, max_length=1000)
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/infra/botellas/{n_id}/separar-padre")
async def botella_separar_padre_web(
    request: Request,
    n_id: int,
    body: BotellaSepararPadreRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Verificador Cromo — separa una Botella agrupada erróneamente por nombre bajo una Cámara
    padre compartida: crea una Cámara nueva e independiente y reasigna `camara_id`. Rechaza si el
    nombre (siempre editable en el modal) colisiona, tras normalizar, con cualquier Cámara raíz
    existente. Nunca toca la Cámara padre anterior. Sólo admin — ver
    `core/services/cromo/separacion_service.py::separar_botella_de_padre`."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botella_separar_padre result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    from core.services.cromo.separacion_service import (
        BotellaNoEncontradaError,
        SeparacionBotellaError,
        separar_botella_de_padre,
    )
    from db.session import SessionLocal

    # Sync (Session): corre en un hilo para no frenar el event loop; las colas (async) quedan afuera.
    def _en_hilo():
        with SessionLocal() as session:
            try:
                resultado = separar_botella_de_padre(
                    session, botella_n_id=n_id, nombre=body.nombre, motivo=body.motivo, usuario=username
                )
            except BotellaNoEncontradaError as exc:
                session.rollback()
                raise NoEncontrado(str(exc)) from exc
            except SeparacionBotellaError as exc:
                session.rollback()
                raise ErrorDeDominio(str(exc)) from exc
            session.commit()
            return resultado

    resultado = await asyncio.to_thread(_en_hilo)

    logger.info(
        "action=botella_separar_padre user=%s botella_n_id=%s camara_anterior_id=%s camara_nueva_id=%s",
        username, resultado.botella_n_id, resultado.camara_anterior_id, resultado.camara_nueva_id,
    )
    await encolar_recalculo_duplicados_botellas(motivo=f"separar-padre n_id={n_id} usuario={username}")
    await _encolar_arbitro("BOTELLAS", [n_id], f"separar-padre n_id={n_id}")
    return JSONResponse({
        "ok": True,
        "botella_n_id": resultado.botella_n_id,
        "camara_anterior_id": resultado.camara_anterior_id,
        "camara_nueva_id": resultado.camara_nueva_id,
        "camara_nueva_nombre": resultado.camara_nueva_nombre,
    })
