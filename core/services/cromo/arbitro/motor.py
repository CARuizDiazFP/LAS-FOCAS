# Nombre de archivo: motor.py
# Ubicación de archivo: core/services/cromo/arbitro/motor.py
# Descripción: Motor del árbitro de Cromo: corre las reglas, persiste propuestas, aplica AUTO y decide la observación

"""Orquesta las reglas del árbitro sobre un alcance.

Ciclo de vida de una propuesta (una sola abierta por `(regla, objeto_tipo, objeto_id)`, garantizado
por el índice único parcial `ux_cromo_propuesta_abierta`):

- `PROPUESTA` → `EN_OBSERVACION` (AUTO, dentro de umbral y presupuesto) → `APLICADA` (la evaluación
  post-ingesta la confirma) o `REVERTIDA` (la contradice: confianza bajo umbral, otro objetivo, o
  ya no sale);
- `PROPUESTA` → `APLICADA` / `RECHAZADA` por decisión manual;
- `PROPUESTA` → `OBSOLETA` cuando deja de salir dentro del alcance evaluado.

Nada acá hace commit: lo hace el llamador (worker o endpoint). Las acciones y reversiones corren en
`begin_nested()`, así que una `AccionNoAplicable` deshace sólo lo de esa propuesta. Las corridas se
serializan con `pg_try_advisory_xact_lock(LOCK_ARBITRO)`: si hay otra, ésta se omite.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.arbitro.acciones import AccionNoAplicable, aplicar, revertir
from core.services.cromo.arbitro.reglas import REGLAS
from core.services.cromo.arbitro.senales import (
    DISPAROS,
    ESTADOS_ABIERTOS,
    MODOS,
    USUARIO_ARBITRO,
    Alcance,
    Evaluacion,
    Regla,
    evidencia_hash,
    puntaje,
)
from core.services.cromo.inconsistencias_cromo import ingesta_en_curso
from db.models.cromo import CromoPropuesta, CromoReglaCorreccion

__all__ = [
    "LOCK_ARBITRO",
    "ResumenEvaluacion",
    "actualizar_regla",
    "aplicar_manual",
    "evaluar",
    "listar_propuestas",
    "precision_por_regla",
    "rechazar",
    "revertir_manual",
]

logger = logging.getLogger(__name__)

LOCK_ARBITRO = 0x4152_4249_5452  # "ARBITR"; distinto de los locks de inconsistencias_cromo

# Para sugerir pasar una regla a AUTO.
_MIN_DECIDIDAS_SUGERIR = 30
_PRECISION_SUGERIR = 0.95


@dataclass
class ResumenEvaluacion:
    nuevas: int = 0
    actualizadas: int = 0
    obsoletas: int = 0
    aplicadas_auto: list[int] = field(default_factory=list)
    confirmadas: list[int] = field(default_factory=list)
    revertidas: list[int] = field(default_factory=list)
    presupuesto_excedido: list[str] = field(default_factory=list)
    omitida: Optional[str] = None
    por_regla: dict[str, dict] = field(default_factory=dict)

    def a_dict(self) -> dict:
        return {
            "nuevas": self.nuevas,
            "actualizadas": self.actualizadas,
            "obsoletas": self.obsoletas,
            "aplicadas_auto": list(self.aplicadas_auto),
            "confirmadas": list(self.confirmadas),
            "revertidas": list(self.revertidas),
            "presupuesto_excedido": list(self.presupuesto_excedido),
            "omitida": self.omitida,
            "por_regla": {k: dict(v) for k, v in self.por_regla.items()},
        }


def _contadores() -> dict:
    return {
        "nuevas": 0,
        "actualizadas": 0,
        "obsoletas": 0,
        "aplicadas_auto": 0,
        "confirmadas": 0,
        "revertidas": 0,
        "presupuesto_excedido": False,
    }


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _json(valor: Any) -> Any:
    """Copia JSON-serializable (lo no serializable pasa a str), igual que `evidencia_hash`."""
    return json.loads(json.dumps(valor, sort_keys=True, default=str))


def _senales_json(ev: Evaluacion) -> list[dict]:
    return _json(
        [
            {"codigo": s.codigo, "peso": s.peso, "detalle": dict(s.detalle), "veto": s.veto}
            for s in ev.senales
        ]
    )


def _vetada(senales: Any) -> bool:
    """Alguna señal de veto (en `Senal` o en su forma JSON persistida en `cromo_propuesta.senales`).
    Un veto nunca se aplica ni se confirma solo, aunque el umbral lo admita."""
    return any(
        (s.get("veto") if isinstance(s, Mapping) else getattr(s, "veto", False))
        for s in (senales or ())
    )


def _objetivo(accion: str, parametros: Mapping[str, Any]) -> Any:
    """Lo que la acción efectivamente cambia: confirmar una observación exige el mismo objetivo."""
    parametros = parametros or {}
    if accion == "ASOCIAR_ODF":
        return (accion, parametros.get("odf_n_id"))
    if accion == "FUSIONAR_GEMELO":
        return (accion, parametros.get("origen"), parametros.get("destino"))
    return (accion, _json(dict(parametros)))


# ── Evaluación ──────────────────────────────────────────────────────────────────────────────────


async def evaluar(
    sesion: AsyncSession,
    alcance: Alcance,
    disparo: str,
    *,
    reglas: Optional[Sequence[Regla]] = None,
    codigos: Optional[Sequence[str]] = None,
) -> ResumenEvaluacion:
    """Corre las reglas sobre `alcance`. No hace commit (savepoints sí)."""
    if disparo not in DISPAROS:
        raise ValueError(f"Disparo inválido: {disparo!r}")
    catalogo = list(REGLAS if reglas is None else reglas)
    if codigos is not None:
        conocidos = {r.codigo for r in catalogo}
        desconocidos = sorted(set(codigos) - conocidos)
        if desconocidos:
            raise ValueError(f"Reglas desconocidas: {desconocidos}")
        pedidos = set(codigos)
        catalogo = [r for r in catalogo if r.codigo in pedidos]

    resumen = ResumenEvaluacion()
    if await ingesta_en_curso(sesion) is not None:
        resumen.omitida = "ingesta_en_curso"
        _log_resumen(resumen, alcance, disparo)
        return resumen
    tomado = (
        await sesion.execute(text("SELECT pg_try_advisory_xact_lock(:clave)"), {"clave": LOCK_ARBITRO})
    ).scalar_one()
    if not tomado:
        resumen.omitida = "otra_evaluacion"
        _log_resumen(resumen, alcance, disparo)
        return resumen

    config = {
        c.codigo: c
        for c in (
            await sesion.execute(
                select(CromoReglaCorreccion).where(
                    CromoReglaCorreccion.codigo.in_([r.codigo for r in catalogo])
                )
            )
        ).scalars()
    }
    contexto: dict[str, Any] = {}
    for regla in catalogo:
        cfg = config.get(regla.codigo)
        if cfg is None:
            logger.warning(
                "action=arbitro_cromo evento=regla_sin_config regla=%s", regla.codigo
            )
            resumen.por_regla[regla.codigo] = {**_contadores(), "omitida": "sin_config"}
            continue
        if cfg.modo == "APAGADA":
            resumen.por_regla[regla.codigo] = {**_contadores(), "omitida": "apagada"}
            continue
        await _evaluar_regla(
            sesion, regla, cfg.modo, int(cfg.umbral), int(cfg.presupuesto_por_corrida),
            alcance, disparo, contexto, resumen,
        )

    _log_resumen(resumen, alcance, disparo)
    return resumen


async def _evaluar_regla(  # noqa: C901
    sesion: AsyncSession,
    regla: Regla,
    modo: str,
    umbral: int,
    presupuesto: int,
    alcance: Alcance,
    disparo: str,
    contexto: dict[str, Any],
    resumen: ResumenEvaluacion,
) -> None:
    codigo = regla.codigo
    cuenta = _contadores()
    resumen.por_regla[codigo] = cuenta

    # Filas abiertas de la regla, bloqueadas hasta el commit del llamador.
    abiertas: dict[tuple[str, int], CromoPropuesta] = {
        (p.objeto_tipo, int(p.objeto_id)): p
        for p in (
            await sesion.execute(
                select(CromoPropuesta)
                .where(
                    CromoPropuesta.regla == codigo,
                    CromoPropuesta.estado.in_(ESTADOS_ABIERTOS),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars()
    }
    propios = frozenset(
        oid for (_tipo, oid), p in abiertas.items() if p.estado == "EN_OBSERVACION"
    )

    try:
        # Savepoint: un error SQL dentro de la regla no aborta la transacción entera.
        async with sesion.begin_nested():
            evaluaciones = await regla.evaluar(
                sesion, alcance, propios=propios, contexto=contexto
            )
    except Exception as exc:  # noqa: BLE001 — una regla rota no tumba las demás
        logger.exception(
            "action=arbitro_cromo evento=regla_fallida regla=%s error=%s", codigo, type(exc).__name__
        )
        # Sólo el tipo: el mensaje puede traer SQL o datos; el traceback completo queda en el log.
        cuenta["error"] = type(exc).__name__
        return

    # Una evaluación por objeto: si la regla repite, gana la de mayor confianza.
    por_objeto: dict[tuple[str, int], tuple[Evaluacion, int]] = {}
    for ev in evaluaciones:
        clave = (ev.objeto_tipo, int(ev.objeto_id))
        confianza = puntaje(ev.senales, ev.tope)
        previa = por_objeto.get(clave)
        if previa is None or confianza > previa[1]:
            por_objeto[clave] = (ev, confianza)
    if len(por_objeto) != len(evaluaciones):
        logger.warning(
            "action=arbitro_cromo evento=evaluaciones_repetidas regla=%s total=%s objetos=%s",
            codigo, len(evaluaciones), len(por_objeto),
        )

    bloqueadas = await _ultimos_hash_bloqueantes(sesion, codigo, [oid for _t, oid in por_objeto])
    ahora = _ahora()
    candidatas: list[CromoPropuesta] = []

    for clave, (ev, confianza) in por_objeto.items():
        hash_ev = evidencia_hash(ev)
        fila = abiertas.get(clave)
        if fila is not None and fila.estado == "PROPUESTA":
            if fila.evidencia_hash != hash_ev:
                fila.nota = None  # evidencia nueva: el último intento fallido ya no aplica
            fila.accion = ev.accion
            fila.parametros = _json(dict(ev.parametros))
            fila.senales = _senales_json(ev)
            fila.confianza = confianza
            fila.evidencia_hash = hash_ev
            fila.disparo = disparo
            fila.actualizada_en = ahora
            cuenta["actualizadas"] += 1
            resumen.actualizadas += 1
            candidatas.append(fila)
        elif fila is not None:  # EN_OBSERVACION
            if disparo != "INGESTA":
                continue
            confirma = (
                confianza >= umbral
                and not _vetada(ev.senales)
                and _objetivo(ev.accion, ev.parametros) == _objetivo(fila.accion, fila.parametros)
            )
            if confirma:
                fila.estado = "APLICADA"
                fila.actualizada_en = ahora
                cuenta["confirmadas"] += 1
                resumen.confirmadas.append(int(fila.id))
            else:
                await _revertir_observacion(sesion, fila, cuenta, resumen, ahora)
        else:
            if bloqueadas.get(clave) == hash_ev:
                continue
            nueva = CromoPropuesta(
                regla=codigo,
                objeto_tipo=ev.objeto_tipo,
                objeto_id=int(ev.objeto_id),
                accion=ev.accion,
                parametros=_json(dict(ev.parametros)),
                confianza=confianza,
                senales=_senales_json(ev),
                evidencia_hash=hash_ev,
                estado="PROPUESTA",
                modo_al_evaluar=modo,
                disparo=disparo,
            )
            sesion.add(nueva)
            cuenta["nuevas"] += 1
            resumen.nuevas += 1
            candidatas.append(nueva)

    # Obsoletas: abiertas dentro del alcance que esta corrida ya no produjo.
    for clave, fila in abiertas.items():
        if clave in por_objeto or not alcance.cubre(*clave):
            continue
        if fila.estado == "PROPUESTA":
            fila.estado = "OBSOLETA"
            fila.actualizada_en = ahora
            cuenta["obsoletas"] += 1
            resumen.obsoletas += 1
        elif disparo == "INGESTA":
            await _revertir_observacion(sesion, fila, cuenta, resumen, ahora)

    await sesion.flush()

    if modo != "AUTO":
        return
    # Sólo lo que esta corrida evaluó: una PROPUESTA vieja fuera del alcance no se aplica a ciegas.
    # `nota` en una PROPUESTA sólo la escribe un intento de aplicar fallido (`AccionNoAplicable`) y
    # se limpia cuando cambia la evidencia: con nota, el mismo hash volvería a fallar, así que no se
    # reintenta ni consume presupuesto.
    aplicables = [
        p for p in candidatas
        if p.confianza >= umbral
        and p.accion != "INFORMAR"
        and p.nota is None
        and not _vetada(p.senales)
    ]
    if not aplicables:
        return
    if len(aplicables) > presupuesto:
        cuenta["presupuesto_excedido"] = True
        resumen.presupuesto_excedido.append(codigo)
        logger.warning(
            "action=arbitro_cromo evento=presupuesto_excedido regla=%s candidatas=%s presupuesto=%s",
            codigo, len(aplicables), presupuesto,
        )
        return
    for propuesta in aplicables:
        propuesta_id = int(propuesta.id)
        try:
            async with sesion.begin_nested():
                reversion = await aplicar(sesion, propuesta)
        except AccionNoAplicable as exc:
            propuesta.nota = str(exc.args[0]) if exc.args else "no_aplicable"
            propuesta.actualizada_en = _ahora()
            logger.info(
                "action=arbitro_cromo evento=auto_no_aplicable regla=%s propuesta_id=%s motivo=%s",
                codigo, propuesta_id, propuesta.nota,
            )
            continue
        momento = _ahora()
        propuesta.estado = "EN_OBSERVACION"
        propuesta.reversion = _json(reversion)
        propuesta.aplicada_en = momento
        propuesta.decidida_por = USUARIO_ARBITRO
        propuesta.decidida_en = momento
        propuesta.actualizada_en = momento
        propuesta.nota = None
        cuenta["aplicadas_auto"] += 1
        resumen.aplicadas_auto.append(propuesta_id)
    await sesion.flush()


async def _revertir_observacion(
    sesion: AsyncSession,
    fila: CromoPropuesta,
    cuenta: dict,
    resumen: ResumenEvaluacion,
    ahora: datetime,
) -> None:
    """Revierte una EN_OBSERVACION contradicha. Si la reversión ya no es posible (el mundo cambió
    debajo: un operador tocó el override o el alias), queda OBSOLETA con la nota y decide un humano."""
    fila_id = int(fila.id)
    try:
        async with sesion.begin_nested():
            await revertir(sesion, fila)
    except AccionNoAplicable as exc:
        motivo = str(exc.args[0]) if exc.args else "no_aplicable"
        fila.estado = "OBSOLETA"
        fila.nota = f"revertir:{motivo}"
        fila.actualizada_en = ahora
        logger.warning(
            "action=arbitro_cromo evento=reversion_no_aplicable propuesta_id=%s motivo=%s",
            fila_id, motivo,
        )
        return
    fila.estado = "REVERTIDA"
    fila.decidida_en = ahora
    fila.actualizada_en = ahora
    cuenta["revertidas"] += 1
    resumen.revertidas.append(fila_id)


# Decisiones humanas que bloquean re-proponer con la misma evidencia: un rechazo, o una reversión
# hecha por un operador (las reversiones automáticas del árbitro no cuentan).
_SQL_ULTIMOS_BLOQUEANTES = text(
    """
    SELECT DISTINCT ON (objeto_tipo, objeto_id) objeto_tipo, objeto_id, evidencia_hash
    FROM app.cromo_propuesta
    WHERE regla = :regla AND objeto_id = ANY(:ids ::bigint[])
      AND (
        estado = 'RECHAZADA'
        OR (estado = 'REVERTIDA' AND decidida_por IS DISTINCT FROM :arbitro)
      )
    ORDER BY objeto_tipo, objeto_id, decidida_en DESC NULLS LAST, id DESC
    """
)


async def _ultimos_hash_bloqueantes(
    sesion: AsyncSession, regla: str, ids: list[int]
) -> dict[tuple[str, int], str]:
    if not ids:
        return {}
    filas = (
        await sesion.execute(
            _SQL_ULTIMOS_BLOQUEANTES,
            {"regla": regla, "ids": sorted(set(ids)), "arbitro": USUARIO_ARBITRO},
        )
    ).all()
    return {(f.objeto_tipo, int(f.objeto_id)): f.evidencia_hash for f in filas}


def _log_resumen(resumen: ResumenEvaluacion, alcance: Alcance, disparo: str) -> None:
    logger.info(
        "action=arbitro_cromo evento=evaluacion disparo=%s alcance=%s omitida=%s nuevas=%s "
        "actualizadas=%s obsoletas=%s aplicadas_auto=%s confirmadas=%s revertidas=%s "
        "presupuesto_excedido=%s errores=%s",
        disparo,
        alcance.tipo,
        resumen.omitida,
        resumen.nuevas,
        resumen.actualizadas,
        resumen.obsoletas,
        len(resumen.aplicadas_auto),
        len(resumen.confirmadas),
        len(resumen.revertidas),
        ",".join(resumen.presupuesto_excedido) or "-",
        ",".join(c for c, v in resumen.por_regla.items() if "error" in v) or "-",
    )


# ── Operaciones manuales ────────────────────────────────────────────────────────────────────────


async def _bloquear(sesion: AsyncSession, ids: Sequence[int]) -> dict[int, CromoPropuesta]:
    if not ids:
        return {}
    filas = (
        await sesion.execute(
            select(CromoPropuesta)
            .where(CromoPropuesta.id.in_([int(i) for i in ids]))
            .order_by(CromoPropuesta.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalars()
    return {int(p.id): p for p in filas}


def _ids_unicos(ids: Sequence[int]) -> list[int]:
    return list(dict.fromkeys(int(i) for i in ids))


async def aplicar_manual(sesion: AsyncSession, ids: Sequence[int], usuario: str) -> dict:
    """PROPUESTA → APLICADA por decisión de `usuario` (sin observación). No hace commit."""
    ids = _ids_unicos(ids)
    filas = await _bloquear(sesion, ids)
    aplicados: list[int] = []
    rechazados: list[dict] = []
    for pid in ids:
        propuesta = filas.get(pid)
        if propuesta is None:
            rechazados.append({"id": pid, "motivo": "inexistente"})
            continue
        if propuesta.estado != "PROPUESTA":
            rechazados.append({"id": pid, "motivo": "estado_invalido"})
            continue
        if propuesta.accion != "INFORMAR":
            try:
                async with sesion.begin_nested():
                    reversion = await aplicar(sesion, propuesta)
            except AccionNoAplicable as exc:
                motivo = str(exc.args[0]) if exc.args else "no_aplicable"
                propuesta.nota = motivo
                propuesta.actualizada_en = _ahora()
                rechazados.append({"id": pid, "motivo": motivo})
                continue
            propuesta.reversion = _json(reversion)
            propuesta.aplicada_en = _ahora()
        momento = _ahora()
        propuesta.estado = "APLICADA"
        propuesta.decidida_por = usuario
        propuesta.decidida_en = momento
        propuesta.actualizada_en = momento
        aplicados.append(pid)
    await sesion.flush()
    logger.info(
        "action=arbitro_cromo evento=aplicar_manual usuario=%s aplicados=%s rechazados=%s",
        usuario, len(aplicados), len(rechazados),
    )
    return {"aplicados": aplicados, "rechazados": rechazados}


async def rechazar(sesion: AsyncSession, ids: Sequence[int], usuario: str) -> dict:
    """PROPUESTA → RECHAZADA. Devuelve `{"rechazados": [ids], "omitidos": [{id, motivo}]}`."""
    ids = _ids_unicos(ids)
    filas = await _bloquear(sesion, ids)
    rechazados: list[int] = []
    omitidos: list[dict] = []
    for pid in ids:
        propuesta = filas.get(pid)
        if propuesta is None:
            omitidos.append({"id": pid, "motivo": "inexistente"})
            continue
        if propuesta.estado != "PROPUESTA":
            omitidos.append({"id": pid, "motivo": "estado_invalido"})
            continue
        momento = _ahora()
        propuesta.estado = "RECHAZADA"
        propuesta.decidida_por = usuario
        propuesta.decidida_en = momento
        propuesta.actualizada_en = momento
        rechazados.append(pid)
    await sesion.flush()
    logger.info(
        "action=arbitro_cromo evento=rechazar usuario=%s rechazados=%s omitidos=%s",
        usuario, len(rechazados), len(omitidos),
    )
    return {"rechazados": rechazados, "omitidos": omitidos}


async def revertir_manual(sesion: AsyncSession, ids: Sequence[int], usuario: str) -> dict:
    """EN_OBSERVACION/APLICADA (no INFORMAR) → REVERTIDA. Si `revertir` no puede, la propuesta no
    cambia y va a `omitidos` con el motivo. Devuelve `{"revertidos": [ids], "omitidos": [...]}`."""
    ids = _ids_unicos(ids)
    filas = await _bloquear(sesion, ids)
    revertidos: list[int] = []
    omitidos: list[dict] = []
    for pid in ids:
        propuesta = filas.get(pid)
        if propuesta is None:
            omitidos.append({"id": pid, "motivo": "inexistente"})
            continue
        if propuesta.estado not in ("EN_OBSERVACION", "APLICADA"):
            omitidos.append({"id": pid, "motivo": "estado_invalido"})
            continue
        if propuesta.accion == "INFORMAR":
            omitidos.append({"id": pid, "motivo": "solo_informativa"})
            continue
        try:
            async with sesion.begin_nested():
                await revertir(sesion, propuesta)
        except AccionNoAplicable as exc:
            omitidos.append({"id": pid, "motivo": str(exc.args[0]) if exc.args else "no_aplicable"})
            continue
        momento = _ahora()
        propuesta.estado = "REVERTIDA"
        propuesta.decidida_por = usuario
        propuesta.decidida_en = momento
        propuesta.actualizada_en = momento
        revertidos.append(pid)
    await sesion.flush()
    logger.info(
        "action=arbitro_cromo evento=revertir_manual usuario=%s revertidos=%s omitidos=%s",
        usuario, len(revertidos), len(omitidos),
    )
    return {"revertidos": revertidos, "omitidos": omitidos}


# ── Lecturas y configuración ────────────────────────────────────────────────────────────────────


def _iso(valor: Optional[datetime]) -> Optional[str]:
    return valor.isoformat() if valor is not None else None


async def listar_propuestas(
    sesion: AsyncSession,
    *,
    regla: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    filtros = ["(CAST(:regla AS text) IS NULL OR regla = :regla)",
               "(CAST(:estado AS text) IS NULL OR estado = :estado)"]
    where = " AND ".join(filtros)
    params = {"regla": regla, "estado": estado}
    total = (
        await sesion.execute(text(f"SELECT count(*) FROM app.cromo_propuesta WHERE {where}"), params)
    ).scalar_one()
    filas = (
        await sesion.execute(
            text(
                "SELECT id, regla, objeto_tipo, objeto_id, accion, parametros, confianza, senales, "
                "estado, disparo, modo_al_evaluar, nota, creada_en, actualizada_en, decidida_por "
                f"FROM app.cromo_propuesta WHERE {where} "
                "ORDER BY confianza DESC, id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": int(limit), "offset": int(offset)},
        )
    ).mappings().all()
    items = []
    for f in filas:
        item = dict(f)
        item["id"] = int(item["id"])
        item["objeto_id"] = int(item["objeto_id"])
        item["creada_en"] = _iso(item["creada_en"])
        item["actualizada_en"] = _iso(item["actualizada_en"])
        items.append(item)
    return {"items": items, "total": int(total)}


_SQL_PRECISION = text(
    """
    SELECT
        r.codigo, r.descripcion, r.modo, r.umbral, r.presupuesto_por_corrida,
        count(p.id) FILTER (
            WHERE p.estado = 'APLICADA' AND p.decidida_por IS DISTINCT FROM :arbitro
        ) AS aceptadas,
        count(p.id) FILTER (
            WHERE p.estado = 'RECHAZADA'
               OR (p.estado = 'REVERTIDA' AND p.decidida_por IS DISTINCT FROM :arbitro)
        ) AS rechazadas
    FROM app.cromo_regla_correccion r
    LEFT JOIN app.cromo_propuesta p ON p.regla = r.codigo
    GROUP BY r.codigo, r.descripcion, r.modo, r.umbral, r.presupuesto_por_corrida
    ORDER BY r.codigo
    """
)


async def precision_por_regla(sesion: AsyncSession) -> list[dict]:
    filas = (await sesion.execute(_SQL_PRECISION, {"arbitro": USUARIO_ARBITRO})).all()
    salida = []
    for f in filas:
        aceptadas, rechazadas = int(f.aceptadas), int(f.rechazadas)
        decididas = aceptadas + rechazadas
        precision = aceptadas / decididas if decididas else None
        salida.append(
            {
                "codigo": f.codigo,
                "descripcion": f.descripcion,
                "modo": f.modo,
                "umbral": int(f.umbral),
                "presupuesto_por_corrida": int(f.presupuesto_por_corrida),
                "aceptadas": aceptadas,
                "rechazadas": rechazadas,
                "decididas": decididas,
                "precision": precision,
                "sugerir_auto": bool(
                    decididas >= _MIN_DECIDIDAS_SUGERIR
                    and precision is not None
                    and precision >= _PRECISION_SUGERIR
                ),
            }
        )
    return salida


def _entero(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


async def actualizar_regla(
    sesion: AsyncSession,
    codigo: str,
    *,
    modo: str,
    umbral: int,
    presupuesto_por_corrida: int,
    usuario: str,
) -> None:
    """Cambia la config de una regla. `ValueError` ante valores inválidos o código inexistente.
    No hace commit."""
    if modo not in MODOS:
        raise ValueError(f"Modo inválido: {modo!r}")
    if not _entero(umbral) or not 0 <= umbral <= 100:
        raise ValueError(f"Umbral inválido: {umbral!r}")
    if modo == "AUTO" and umbral < 1:
        # Con umbral 0 todo pasaría el corte, incluso lo de confianza 0.
        raise ValueError("Umbral inválido para AUTO: debe ser al menos 1")
    if not _entero(presupuesto_por_corrida) or presupuesto_por_corrida < 0:
        raise ValueError(f"Presupuesto inválido: {presupuesto_por_corrida!r}")
    cfg = (
        await sesion.execute(
            select(CromoReglaCorreccion)
            .where(CromoReglaCorreccion.codigo == codigo)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if cfg is None:
        raise ValueError(f"Regla inexistente: {codigo!r}")
    cfg.modo = modo
    cfg.umbral = umbral
    cfg.presupuesto_por_corrida = presupuesto_por_corrida
    cfg.actualizado_por = usuario
    cfg.actualizado_en = _ahora()
    await sesion.flush()
    logger.info(
        "action=arbitro_cromo evento=regla_actualizada regla=%s modo=%s umbral=%s presupuesto=%s "
        "usuario=%s",
        codigo, modo, umbral, presupuesto_por_corrida, usuario,
    )

