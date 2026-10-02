# Nombre de archivo: bajas_service.py
# Ubicación de archivo: core/services/cromo/bajas_service.py
# Descripción: Detección de cables que Cromo ya no tiene (borrados o reemplazados) y relevamiento de sucesores y cobertura de servicios

"""Cables "fantasma": vigentes en la base local y borrados en Cromo.

Hasta 2026-10-02 ningún código ponía `vigente=false` en cables, tubos ni pelos (el diseño lo pedía
en `docs/Doc Privada/ingesta_cromo.md`, nunca se implementó). Caso real: F-TIG-003-B 9609095 se
partió en Cromo el 2026-09-10 en F-TIG-003-A 10277059 + F-TIG-003-B 10277060, y el bot de Slack
respondía "2 cables con ese código".

**Señal de borrado, medida contra Cromo real (2026-10-02)**: `GET /db/objects/{id}` sigue
respondiendo `st=0` para un cable borrado, así que un 404 NO es la señal. Lo que cambia es la
vigencia de la última versión del linaje: la entrada de `hist[]` con `next_id == 0` tiene `to != 0`.
Que el objeto pedido tenga `to`/`vto` no alcanza: 10259700 (F-ROW-K52JAAA) los tiene porque es una
versión vieja, y su última versión (10259871) sigue abierta (`to == 0`) — está vivo. Un borrado,
además, viene sin `code`/`name` y con `/inner` vacío, pero eso es síntoma, no criterio.

El `vto` de la última versión del borrado coincide con el `vfrom` del cable que lo reemplazó en la
misma operación de Cromo (275695 en F-TIG-003-B, 272304 en F-LEM-11-A, 272203 en F-ROW-K52JAAA):
es la mejor pista de sucesor, más precisa que el nombre.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.pelo_servicios import METODOS_AUTOMATICOS
from db.models.cromo import CromoIngestaEvento

logger = logging.getLogger(__name__)

CLASES_CABLE = (51, 52, 59, 60, 66)
METODO_MANUAL = "MANUAL"
# Tope de bajas por clase y por corrida. Medido 2026-10-02 en dev: los fantasmas reales son decenas,
# no cientos. Un número mayor huele a barrido incompleto o a un cambio de API de Cromo, y dar de baja
# en masa por eso borraría asignaciones de servicio reales: se aborta y se exige `forzar=True`.
TOPE_BAJAS_POR_CLASE = 300
_CONCURRENCIA_CONFIRMACION = 4


@dataclass(slots=True, frozen=True)
class EstadoEnCromo:
    """Lo que Cromo dice hoy de un `n_id` local."""

    borrado: bool
    id_ultima_version: Optional[int]
    vto_final: Optional[int]  # versión de Cromo en la que se cerró; None si sigue vivo


def estado_en_cromo(objeto: dict[str, Any]) -> EstadoEnCromo:
    """Interpreta la respuesta (ya desenvuelta de `response`) de `GET /db/objects/{id}`."""
    hist = objeto.get("hist") or []
    ultima = next((h for h in hist if not h.get("next_id")), None)
    if ultima is not None:
        to = ultima.get("to") or 0
        return EstadoEnCromo(borrado=to != 0, id_ultima_version=ultima.get("id"), vto_final=ultima.get("vto") if to else None)
    # Sin historial: objeto de una sola versión. Vivo salvo que la propia vigencia esté cerrada.
    to = objeto.get("to") or 0
    return EstadoEnCromo(borrado=to != 0, id_ultima_version=objeto.get("id"), vto_final=objeto.get("vto") if to else None)


async def consultar_estado(cliente: CromoClient, n_id: int) -> EstadoEnCromo:
    respuesta = await cliente.get_objeto(n_id)
    return estado_en_cromo(respuesta.get("response") or {})


async def ids_en_cromo(cliente: CromoClient, clase: int, *, psize: int = 50) -> tuple[set[int], set[int], int]:
    """Barrido liviano (`show=BASIC`) de una clase. Devuelve `(vistos, linajes, count)`:

    - `vistos`: `id` y `n_id` de cada objeto. Un objeto versionado puede listarse con el id de su
      versión vigente y la base local guarda el de linaje; para decidir ausencias valen los dos.
    - `linajes`: un id por objeto (`n_id` si viene, si no `id`, igual que `parser`), para contar
      faltantes sin inflar por la versión.
    - `count`: el `stats[].count` que informa Cromo.
    """
    vistos: set[int] = set()
    linajes: set[int] = set()
    conteo = 0
    async for pagina in cliente.iterar_coleccion(str(clase), psize=psize, show=["BASIC"]):
        for stat in pagina.get("stats") or []:
            if stat.get("id") == clase and stat.get("count"):
                conteo = int(stat["count"])
        for obj in pagina.get("response") or []:
            for clave in ("id", "n_id"):
                if obj.get(clave):
                    vistos.add(int(obj[clave]))
            linaje = obj.get("n_id") or obj.get("id")
            if linaje:
                linajes.add(int(linaje))
    return vistos, linajes, conteo


_SQL_VIGENTES_DE_CLASE = text("SELECT n_id FROM app.cromo_cables WHERE vigente AND clase = :clase")


async def cables_ausentes(sesion: AsyncSession, clase: int, vistos: set[int]) -> list[int]:
    """Vigentes locales de la clase que el barrido no vio. Son CANDIDATOS: se confirman uno por uno
    con `consultar_estado` antes de cualquier baja."""
    locales = (await sesion.execute(_SQL_VIGENTES_DE_CLASE, {"clase": clase})).scalars().all()
    return sorted(n for n in locales if n not in vistos)


async def cables_faltantes(sesion: AsyncSession, clase: int, linajes: set[int]) -> list[int]:
    """Objetos que Cromo lista y no tienen fila local (ni vigente ni no vigente). Los da de alta el
    barrido directo de la clase (`SOLO_CABLES`)."""
    locales = set(
        (await sesion.execute(text("SELECT n_id FROM app.cromo_cables WHERE clase = :clase"), {"clase": clase}))
        .scalars()
        .all()
    )
    return sorted(linajes - locales)


@dataclass(slots=True)
class Sucesor:
    n_id: int
    nombre: Optional[str]
    motivo: str  # "vfrom=vto" | "nombre" | "extremo"


@dataclass(slots=True)
class DetalleFantasma:
    n_id: int
    nombre: Optional[str]
    clase: Optional[int]
    extremo_a_n_id: Optional[int]
    extremo_b_n_id: Optional[int]
    vto_final: Optional[int]
    pelos: int = 0
    pelos_con_servicio: int = 0
    matches_por_metodo: dict[str, int] = field(default_factory=dict)
    servicios: list[str] = field(default_factory=list)
    servicios_manual: list[str] = field(default_factory=list)
    sucesores: list[Sucesor] = field(default_factory=list)
    servicios_sin_cobertura: list[str] = field(default_factory=list)
    manual_sin_cobertura: list[str] = field(default_factory=list)

    def como_dict(self) -> dict[str, Any]:
        return {
            "n_id": self.n_id, "nombre": self.nombre, "clase": self.clase,
            "extremos": [self.extremo_a_n_id, self.extremo_b_n_id], "vto_final": self.vto_final,
            "pelos": self.pelos, "pelos_con_servicio": self.pelos_con_servicio,
            "matches_por_metodo": self.matches_por_metodo, "servicios": self.servicios,
            "servicios_manual": self.servicios_manual,
            "sucesores": [{"n_id": s.n_id, "nombre": s.nombre, "motivo": s.motivo} for s in self.sucesores],
            "servicios_sin_cobertura": self.servicios_sin_cobertura,
            "manual_sin_cobertura": self.manual_sin_cobertura,
        }


_SQL_CABLE = text(
    "SELECT n_id, nombre, clase, extremo_a_n_id, extremo_b_n_id FROM app.cromo_cables WHERE n_id = :n_id"
)
_SQL_PELOS_DE_CABLE = text(
    "SELECT count(*) AS pelos, count(*) FILTER (WHERE servicio_numero IS NOT NULL) AS con_servicio "
    "FROM app.cromo_pelos WHERE cable_n_id = :n_id AND vigente"
)
_SQL_MATCHES_DE_CABLES = text(
    "SELECT p.cable_n_id, m.servicio_numero, m.metodo FROM app.cromo_servicio_match m "
    "JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id WHERE p.cable_n_id = ANY(:ids) AND p.vigente"
)
# Sucesores: cables vigentes que NO son fantasmas y que (a) nacieron en la misma versión de Cromo en
# que murió el fantasma, (b) se llaman igual, o (c) comparten algún extremo. El orden de `motivo`
# es el de confianza.
_SQL_SUCESORES = text(
    """
    SELECT n_id, nombre,
           CASE WHEN (payload_raw->>'vfrom') = CAST(:vto AS text) THEN 'vfrom=vto'
                WHEN lower(nombre) = lower(:nombre) THEN 'nombre'
                ELSE 'extremo' END AS motivo
    FROM app.cromo_cables
    WHERE vigente AND n_id <> ALL(:excluir)
      AND ( (CAST(:vto AS text) IS NOT NULL AND (payload_raw->>'vfrom') = CAST(:vto AS text)
             AND (extremo_a_n_id IN (:a, :b) OR extremo_b_n_id IN (:a, :b)))
            OR lower(nombre) = lower(:nombre)
            OR (extremo_a_n_id IN (:a, :b) AND extremo_b_n_id IN (:a, :b)) )
    ORDER BY motivo DESC, n_id
    """
)


async def detallar_fantasma(
    sesion: AsyncSession, n_id: int, vto_final: Optional[int], fantasmas: Iterable[int]
) -> DetalleFantasma:
    """Arma el detalle de un fantasma confirmado: pelos, asignaciones, sucesores y cobertura.

    Cobertura = cada servicio del fantasma aparece en algún pelo vigente de un sucesor. Es la regla
    que decidió el usuario (2026-10-02) para las asignaciones MANUAL: si el cable vigente que lo
    reemplaza tiene los mismos servicios, se borran; si no, se conservan y se reportan.

    El sucesor "extremo" exige que comparta AMBOS extremos (cable paralelo entre las mismas botellas)
    salvo que además coincida `vfrom=vto`: compartir uno solo es lo normal entre cables vecinos y
    convertiría a cualquier cable de la cámara en "sucesor".
    """
    fila = (await sesion.execute(_SQL_CABLE, {"n_id": n_id})).one()
    det = DetalleFantasma(
        n_id=n_id, nombre=fila.nombre, clase=fila.clase,
        extremo_a_n_id=fila.extremo_a_n_id, extremo_b_n_id=fila.extremo_b_n_id, vto_final=vto_final,
    )
    pelos = (await sesion.execute(_SQL_PELOS_DE_CABLE, {"n_id": n_id})).one()
    det.pelos, det.pelos_con_servicio = pelos.pelos, pelos.con_servicio

    a, b = fila.extremo_a_n_id or -1, fila.extremo_b_n_id or -1
    sucesores = (
        await sesion.execute(
            _SQL_SUCESORES,
            {"vto": str(vto_final) if vto_final is not None else None, "nombre": fila.nombre or "", "a": a, "b": b, "excluir": list(fantasmas)},
        )
    ).all()
    det.sucesores = [Sucesor(s.n_id, s.nombre, s.motivo) for s in sucesores]

    ids = [n_id, *(s.n_id for s in det.sucesores)]
    servicios_propios: set[str] = set()
    manual: set[str] = set()
    servicios_sucesores: set[str] = set()
    for m in (await sesion.execute(_SQL_MATCHES_DE_CABLES, {"ids": ids})).all():
        if m.cable_n_id == n_id:
            servicios_propios.add(m.servicio_numero)
            det.matches_por_metodo[m.metodo] = det.matches_por_metodo.get(m.metodo, 0) + 1
            if m.metodo == METODO_MANUAL:
                manual.add(m.servicio_numero)
        else:
            servicios_sucesores.add(m.servicio_numero)
    det.servicios = sorted(servicios_propios)
    det.servicios_manual = sorted(manual)
    det.servicios_sin_cobertura = sorted(servicios_propios - servicios_sucesores)
    det.manual_sin_cobertura = sorted(manual - servicios_sucesores)
    return det


_SQL_PELOS_VIGENTES = text("SELECT n_id FROM app.cromo_pelos WHERE cable_n_id = :n_id AND vigente")
_SQL_MATCHES_DE_PELOS = text(
    "SELECT id, pelo_n_id, servicio_numero, servicio_id, metodo FROM app.cromo_servicio_match "
    "WHERE pelo_n_id = ANY(:ids) ORDER BY id"
)


@dataclass(slots=True)
class ResultadoBaja:
    pelos: int = 0
    tubos: int = 0
    matches_retirados: int = 0
    manual_retirados: int = 0
    manual_conservados: int = 0
    tracking_borrados: int = 0


def _evento(sesion: AsyncSession, corrida_id: int, n_id: Optional[int], clase: Optional[int], accion: str,
            detalle: Optional[str] = None) -> None:
    # Mismo INSERT que `ingesta.registrar_evento`, sin importar `ingesta` (que importa este módulo).
    sesion.add(CromoIngestaEvento(corrida_id=corrida_id, n_id=n_id, clase=clase, accion=accion, detalle=detalle))


async def aplicar_baja_cable(sesion: AsyncSession, corrida_id: int, detalle: DetalleFantasma) -> ResultadoBaja:
    """Baja lógica de un cable que Cromo borró, en un savepoint propio.

    - Cable, tubos y pelos → `vigente = false`. Nunca `DELETE`: si Cromo lo reactiva, la próxima
      ingesta lo vuelve a encender (`reactivar_cable`).
    - Asignaciones automáticas (`METODOS_AUTOMATICOS`) → se borran con `MATCH_RETIRADO`, mismo formato
      de detalle que `ingesta.conciliar_matches_de_cable`. No se reusa esa función porque saltea por
      diseño todo pelo con algún vínculo MANUAL, y acá esos pelos también se apagan.
    - Asignaciones MANUAL (o cualquier método no automático: lo decidió una persona) → se borran sólo
      si el servicio está cubierto por un sucesor vigente (`detalle.manual_sin_cobertura`), con
      `MATCH_MANUAL_RETIRADO` y todos los campos para poder reponerla; si no, se conservan con
      `MATCH_MANUAL_CONSERVADO` y quedan en el informe. Regla decidida por el usuario (2026-10-02).
    - `cromo_tracking_cache` de esos pelos → se borra: es caché, se regenera.

    No toca `cromo_fusiones`, `cromo_odf_conectores` ni `cromo_servicio_odf_override`: referencian
    pelos por id blando y sus consumidores filtran por pelo vigente.
    """
    resultado = ResultadoBaja()
    sin_cobertura = set(detalle.manual_sin_cobertura)
    async with sesion.begin_nested():
        pelos = list((await sesion.execute(_SQL_PELOS_VIGENTES, {"n_id": detalle.n_id})).scalars().all())
        resultado.pelos = len(pelos)
        for m in (await sesion.execute(_SQL_MATCHES_DE_PELOS, {"ids": pelos})).all():
            info = f"servicio_numero={m.servicio_numero} servicio_id={m.servicio_id} metodo={m.metodo}"
            if m.metodo in METODOS_AUTOMATICOS:
                accion = "MATCH_RETIRADO"
                resultado.matches_retirados += 1
            elif m.servicio_numero in sin_cobertura:
                _evento(sesion, corrida_id, m.pelo_n_id, 130, "MATCH_MANUAL_CONSERVADO", f"{info} cable={detalle.n_id}")
                resultado.manual_conservados += 1
                continue
            else:
                accion = "MATCH_MANUAL_RETIRADO"
                resultado.manual_retirados += 1
            await sesion.execute(text("DELETE FROM app.cromo_servicio_match WHERE id = :id"), {"id": m.id})
            _evento(sesion, corrida_id, m.pelo_n_id, 130, accion, f"{info} cable={detalle.n_id}")
        if pelos:
            borrados = await sesion.execute(
                text("DELETE FROM app.cromo_tracking_cache WHERE pelo_n_id = ANY(:ids)"), {"ids": pelos}
            )
            resultado.tracking_borrados = borrados.rowcount or 0
        await sesion.execute(
            text("UPDATE app.cromo_pelos SET vigente = false WHERE cable_n_id = :n_id AND vigente"), {"n_id": detalle.n_id}
        )
        tubos = await sesion.execute(
            text("UPDATE app.cromo_tubos SET vigente = false WHERE cable_n_id = :n_id AND vigente"), {"n_id": detalle.n_id}
        )
        resultado.tubos = tubos.rowcount or 0
        await sesion.execute(text("UPDATE app.cromo_cables SET vigente = false WHERE n_id = :n_id"), {"n_id": detalle.n_id})
        _evento(
            sesion, corrida_id, detalle.n_id, detalle.clase, "CABLE_BAJA_LOGICA",
            json.dumps({"nombre": detalle.nombre, "vto_final": detalle.vto_final, "pelos": resultado.pelos,
                        "tubos": resultado.tubos, "matches_retirados": resultado.matches_retirados,
                        "manual_retirados": resultado.manual_retirados,
                        "manual_conservados": resultado.manual_conservados,
                        "sucesores": [s.n_id for s in detalle.sucesores]}, ensure_ascii=False),
        )
    return resultado


async def reactivar_cable(sesion: AsyncSession, corrida_id: int, n_id: int, clase: Optional[int]) -> None:
    """Un cable dado de baja volvió a aparecer en un barrido directo de Cromo: se enciende con sus
    tubos y pelos. Las asignaciones retiradas NO se reponen acá: las recrea `fase_servicios` (REGEX) o
    el barrido `/inner` (atributos); las MANUAL retiradas quedan en el evento para reponer a mano."""
    await sesion.execute(text("UPDATE app.cromo_cables SET vigente = true WHERE n_id = :n_id"), {"n_id": n_id})
    await sesion.execute(text("UPDATE app.cromo_tubos SET vigente = true WHERE cable_n_id = :n_id"), {"n_id": n_id})
    await sesion.execute(text("UPDATE app.cromo_pelos SET vigente = true WHERE cable_n_id = :n_id"), {"n_id": n_id})
    _evento(sesion, corrida_id, n_id, clase, "CABLE_REACTIVADO")


@dataclass(slots=True)
class ResumenBajas:
    candidatos: int = 0
    vivos_no_listados: int = 0
    errores_confirmacion: int = 0
    bajas: int = 0
    abortado: bool = False
    pelos: int = 0
    matches_retirados: int = 0
    manual_retirados: int = 0
    manual_conservados: int = 0


async def confirmar_borrados(
    cliente: CromoClient, candidatos: list[int], *, concurrencia: int = _CONCURRENCIA_CONFIRMACION
) -> tuple[list[tuple[int, Optional[int]]], list[int], list[tuple[int, str]]]:
    """Doble señal: cada candidato (ausente del barrido) se consulta a Cromo. Devuelve
    `(borrados [(n_id, vto_final)], vivos, errores)`. Un error de consulta NUNCA cuenta como borrado."""
    semaforo = asyncio.Semaphore(concurrencia)

    async def _uno(n_id: int):
        async with semaforo:
            try:
                return n_id, await consultar_estado(cliente, n_id), None
            except CromoClientError as exc:
                return n_id, None, f"{exc.status_code}: {str(exc)[:200]}"

    borrados, vivos, errores = [], [], []
    for n_id, estado, error in await asyncio.gather(*(_uno(n) for n in candidatos)):
        if error is not None:
            errores.append((n_id, error))
        elif estado.borrado:
            borrados.append((n_id, estado.vto_final))
        else:
            vivos.append(n_id)
    return borrados, vivos, errores


async def conciliar_bajas_de_clase(
    cliente: CromoClient,
    sesion: AsyncSession,
    corrida_id: int,
    clase: int,
    vistos: set[int],
    *,
    forzar: bool = False,
    tope: int = TOPE_BAJAS_POR_CLASE,
) -> ResumenBajas:
    """Después de un barrido COMPLETO de `clase` (el llamador lo garantiza: sin `max_paginas`, sin
    cancelación ni excepción), da de baja los vigentes locales que Cromo ya no lista y confirma
    borrados. Commitea al final; un abort por tope no escribe ninguna baja."""
    resumen = ResumenBajas()
    candidatos = await cables_ausentes(sesion, clase, vistos)
    resumen.candidatos = len(candidatos)
    if not candidatos:
        return resumen
    borrados, vivos, errores = await confirmar_borrados(cliente, candidatos)
    resumen.vivos_no_listados, resumen.errores_confirmacion = len(vivos), len(errores)
    for n_id in vivos:
        _evento(sesion, corrida_id, n_id, clase, "CABLE_AUSENTE_VIVO", "no listado en el barrido pero vivo en Cromo")
    for n_id, error in errores:
        _evento(sesion, corrida_id, n_id, clase, "CABLE_AUSENTE_ERROR", error)
    if len(borrados) > tope and not forzar:
        resumen.abortado = True
        _evento(sesion, corrida_id, None, clase, "BAJAS_ABORTADAS",
                f"{len(borrados)} cables borrados en Cromo superan el tope {tope}; reintentar con forzar_bajas")
        logger.warning("action=cromo_bajas evento=abortado clase=%s borrados=%s tope=%s", clase, len(borrados), tope)
        await sesion.commit()
        return resumen
    ids = [n for n, _ in borrados]
    for n_id, vto in borrados:
        detalle = await detallar_fantasma(sesion, n_id, vto, ids)
        r = await aplicar_baja_cable(sesion, corrida_id, detalle)
        resumen.bajas += 1
        resumen.pelos += r.pelos
        resumen.matches_retirados += r.matches_retirados
        resumen.manual_retirados += r.manual_retirados
        resumen.manual_conservados += r.manual_conservados
    await sesion.commit()
    logger.info("action=cromo_bajas evento=conciliado clase=%s candidatos=%s bajas=%s vivos=%s errores=%s",
                clase, resumen.candidatos, resumen.bajas, resumen.vivos_no_listados, resumen.errores_confirmacion)
    return resumen


__all__ = [
    "CLASES_CABLE",
    "ResultadoBaja",
    "ResumenBajas",
    "TOPE_BAJAS_POR_CLASE",
    "aplicar_baja_cable",
    "confirmar_borrados",
    "conciliar_bajas_de_clase",
    "reactivar_cable",
    "DetalleFantasma",
    "EstadoEnCromo",
    "Sucesor",
    "cables_ausentes",
    "cables_faltantes",
    "consultar_estado",
    "detallar_fantasma",
    "estado_en_cromo",
    "ids_en_cromo",
]
