# Nombre de archivo: cromo_sonda.py
# Ubicación de archivo: scripts/cromo_sonda.py
# Descripción: Script de descubrimiento de sólo lectura contra Cromo Red para cerrar puntos abiertos de docs/ingesta_cromo.md

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.logging import setup_logging
from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.config import CromoConfigError, get_cromo_config
from core.services.cromo.parser import ATRIBUTOS_CONOCIDOS, atributo

logger = setup_logging("cromo_sonda")

CLASES_BOTELLA = [68, 121, 122, 123, 125]
CLASES_CONTROL_COUNTS = [68, 121, 122, 123, 125, 51]
PSIZES_A_MEDIR = [1, 5, 10]


class SeccionSonda:
    def __init__(self, titulo: str) -> None:
        self.titulo = titulo
        self.lineas: list[str] = []
        self.error: str | None = None

    def agregar(self, linea: str) -> None:
        self.lineas.append(linea)

    def marcar_error(self, mensaje: str) -> None:
        self.error = mensaje
        logger.error("action=cromo_sonda seccion=%s resultado=error detalle=%s", self.titulo, mensaje)

    def a_markdown(self) -> str:
        partes = [f"## {self.titulo}", ""]
        if self.error:
            partes.append(f"**No se pudo completar:** {self.error}")
        else:
            partes.extend(self.lineas)
        partes.append("")
        return "\n".join(partes)


async def _sondear_clase_69(cliente: CromoClient) -> SeccionSonda:
    """Sonda ampliada de clase 69 (ODF) para la Tarea 0 del submódulo ODFs.

    La sonda original (psize=1, show=["SHOW"]) sólo confirmó que la clase existe;
    nunca reveló relaciones (`tp`/`inner`) ni una muestra suficiente para validar
    el clasificador ODF/EMPALME por nombre (ver docs/superpowers/specs — plan ODFs).
    Usa el mismo `show` que `fase_botellas` en ingesta.py para poder ver `tp[]`.
    """
    seccion = SeccionSonda("1. Identificación de la clase 69 (ODF) — sonda ampliada")
    respuesta = await cliente.get_coleccion("69", psize=30, show=["SHOW", "REL_ATTRIBUTE", "TIME"])
    datos = respuesta.get("data") or respuesta.get("response") or []
    if not datos:
        seccion.agregar("La colección de clase 69 devolvió cero objetos.")
        return seccion

    seccion.agregar(f"- objetos devueltos: {len(datos)}")

    con_id = sum(1 for o in datos if o.get("id") is not None)
    con_vmax = sum(1 for o in datos if o.get("vmax") is not None)
    seccion.agregar(f"- objetos con `id`: {con_id}/{len(datos)}")
    seccion.agregar(f"- objetos con `vmax`: {con_vmax}/{len(datos)}")

    con_tp = [o for o in datos if o.get("tp")]
    con_inner = [o for o in datos if o.get("inner")]
    seccion.agregar(f"- objetos con `tp[]`: {len(con_tp)}/{len(datos)}")
    seccion.agregar(f"- objetos con `inner[]`: {len(con_inner)}/{len(datos)}")
    if con_tp:
        seccion.agregar(f"- ejemplo de `tp[]` (primer objeto que lo trae): `{con_tp[0].get('tp')}`")
    if con_inner:
        seccion.agregar(f"- ejemplo de `inner[]` (primer objeto que lo trae): `{con_inner[0].get('inner')}`")

    seccion.agregar("")
    seccion.agregar("| at.id | name | frecuencia | valores de muestra |")
    seccion.agregar("|---:|---|---:|---|")
    frecuencia: Counter[int] = Counter()
    nombres: dict[int, str] = {}
    muestras: dict[int, list[str]] = {}
    for obj in datos:
        for item in obj.get("at") or []:
            attr_id = item.get("id")
            frecuencia[attr_id] += 1
            if item.get("name"):
                nombres[attr_id] = item["name"]
            valores = muestras.setdefault(attr_id, [])
            valor = str(item.get("value"))
            if valor not in valores and len(valores) < 5:
                valores.append(valor)
    for attr_id in sorted(frecuencia):
        seccion.agregar(
            f"| {attr_id} | {nombres.get(attr_id, '')} | {frecuencia[attr_id]} | {', '.join(muestras[attr_id])} |"
        )

    seccion.agregar("")
    seccion.agregar("### Nombres de muestra (para validar clasificador ODF/EMPALME/SIN_CLASIFICAR)")
    for obj in datos:
        nombre = obj.get("name") or ""
        seccion.agregar(f"- `{nombre}`")

    return seccion


async def _medir_peso_pagina_botellas(cliente: CromoClient) -> SeccionSonda:
    seccion = SeccionSonda("2. Peso de la página del barrido de botellas")
    seccion.agregar("| psize | tamaño (bytes) | tiempo (s) |")
    seccion.agregar("|---:|---:|---:|")

    config = get_cromo_config()
    token = await cliente.token_bearer()
    async with httpx.AsyncClient(
        base_url=config.url_servidor,
        timeout=httpx.Timeout(config.timeout),
    ) as crudo:
        for psize in PSIZES_A_MEDIR:
            filtro = ",".join(str(c) for c in CLASES_BOTELLA)
            inicio = time.monotonic()
            respuesta = await crudo.get(
                "/db/select/model",
                params={"filter": filtro, "show": "SHOW,REL_ATTRIBUTE,TIME", "psize": psize},
                headers={"Authorization": f"Bearer {token}"},
            )
            duracion = time.monotonic() - inicio
            seccion.agregar(f"| {psize} | {len(respuesta.content)} | {duracion:.2f} |")
    return seccion


async def _sondear_inner_de_cable(cliente: CromoClient, n_id_cable: int | None) -> SeccionSonda:
    seccion = SeccionSonda("3. ¿/db/objects/{id_cable}/inner expande tubos y pelos?")
    if n_id_cable is None:
        seccion.marcar_error("No se obtuvo un n_id de cable del barrido para probar.")
        return seccion

    respuesta = await cliente.get_inner(n_id_cable)
    datos = respuesta.get("response") or respuesta.get("data") or []
    clases = Counter(item.get("class") for item in datos)
    seccion.agregar(f"- n_id de cable probado: `{n_id_cable}`")
    seccion.agregar(f"- objetos devueltos: {len(datos)}")
    seccion.agregar(f"- distribución por clase: {dict(clases)}")
    tiene_tubos_o_pelos = any(c in (129, 130) for c in clases)
    seccion.agregar(
        f"- **Conclusión:** {'SÍ expande tubos/pelos' if tiene_tubos_o_pelos else 'NO expande tubos/pelos (sólo fusiones u otra cosa)'}"
    )
    return seccion


async def _contar_clases(cliente: CromoClient) -> SeccionSonda:
    seccion = SeccionSonda("4. Counts actuales por clase")
    seccion.agregar("| clase | count |")
    seccion.agregar("|---:|---:|")
    for clase in CLASES_CONTROL_COUNTS:
        respuesta = await cliente.get_coleccion(str(clase), psize=1, show=["BASIC"])
        stats = respuesta.get("stats") or []
        count = next((s.get("count") for s in stats if s.get("id") == clase), None)
        seccion.agregar(f"| {clase} | {count} |")
    return seccion


async def _inventariar_atributos(cliente: CromoClient) -> tuple[SeccionSonda, list[dict[str, Any]], list[dict[str, Any]]]:
    seccion = SeccionSonda("5. Inventario de atributos (10 botellas · 10 cables)")

    respuesta_botellas = await cliente.get_coleccion(
        ",".join(str(c) for c in CLASES_BOTELLA), psize=10, show=["SHOW", "REL_ATTRIBUTE", "TIME"]
    )
    botellas = respuesta_botellas.get("data") or respuesta_botellas.get("response") or []

    respuesta_cables = await cliente.get_coleccion("51", psize=10, show=["SHOW", "TIME"])
    cables = respuesta_cables.get("data") or respuesta_cables.get("response") or []

    for etiqueta, objetos in (("Botellas", botellas), ("Cables", cables)):
        seccion.agregar(f"### {etiqueta}")
        seccion.agregar("")
        seccion.agregar("| at.id | name | frecuencia | valores de muestra |")
        seccion.agregar("|---:|---|---:|---|")

        frecuencia: Counter[int] = Counter()
        nombres: dict[int, str] = {}
        muestras: dict[int, list[str]] = {}
        for obj in objetos:
            for item in obj.get("at") or []:
                attr_id = item.get("id")
                frecuencia[attr_id] += 1
                if item.get("name"):
                    nombres[attr_id] = item["name"]
                valores = muestras.setdefault(attr_id, [])
                valor = str(item.get("value"))
                if valor not in valores and len(valores) < 3:
                    valores.append(valor)

        for attr_id in sorted(frecuencia):
            seccion.agregar(
                f"| {attr_id} | {nombres.get(attr_id, '')} | {frecuencia[attr_id]} | {', '.join(muestras[attr_id])} |"
            )
        seccion.agregar("")

    return seccion, botellas, cables


async def _controlar_capacidad(cliente: CromoClient, cables: list[dict[str, Any]]) -> SeccionSonda:
    """Compara at.32 contra los class 130 reales, obtenidos vía /inner por cable.

    El barrido directo (`filter=51`) nunca trae `inner[]` (ver docs/ingesta_cromo.md
    capítulo 2, corrección 8): comparar contra ese `inner[]` ausente da 0 pelos siempre,
    un falso positivo de divergencia. El punto 3 de esta sonda confirma que `/inner`
    por cable sí expande tubos y pelos, así que se usa ese endpoint para el conteo real.
    """
    seccion = SeccionSonda("6. Control de capacidad declarada vs. pelos recibidos")
    seccion.agregar("| cable n_id | at.32 | capacidad declarada | class 130 recibidos (vía /inner) | diverge |")
    seccion.agregar("|---|---|---:|---:|:---:|")

    for cable in cables:
        n_id = cable.get("n_id") or cable.get("id")
        capacidad_raw = atributo(cable, 32)
        coincidencia = re.match(r"^\s*(\d+)", capacidad_raw) if capacidad_raw else None
        capacidad_declarada = int(coincidencia.group(1)) if coincidencia else None
        if n_id is None:
            continue
        respuesta_inner = await cliente.get_inner(n_id)
        objetos_inner = respuesta_inner.get("response") or respuesta_inner.get("data") or []
        pelos_recibidos = sum(1 for item in objetos_inner if item.get("class") == 130)
        diverge = capacidad_declarada is not None and capacidad_declarada != pelos_recibidos
        seccion.agregar(
            f"| {n_id} | {capacidad_raw} | {capacidad_declarada} | {pelos_recibidos} | {'⚠️' if diverge else 'ok'} |"
        )
    return seccion


def _extraer_primer_n_id_cable(botellas: list[dict[str, Any]]) -> int | None:
    for botella in botellas:
        for item in botella.get("tp") or []:
            if item.get("class") == 51:
                return item.get("n_id") or item.get("id_to")
    return None


_CLASES_ETIQUETA = {
    2: "cámara",
    51: "cable",
    68: "botella 6-1",
    69: "ODF",
    121: "botella 16-1",
    122: "botella",
    123: "botella",
    124: "botella",
    125: "botella",
    129: "tubo",
    130: "pelo",
    132: "fusión",
    135: "patchera",
    136: "posición patchera",
}


def _desenvolver_dict_sonda(payload: Any) -> tuple[dict[int, dict[str, Any]], str]:
    """Prueba las tres envolturas posibles de `/path` y normaliza las claves a `int`.

    Las claves JSON son strings (`"10006353"`) pero `a[]`/`b[]` traen enteros; sin normalizar,
    cualquier lookup es una bomba de tipos.
    """
    if not isinstance(payload, dict):
        return {}, "ninguna (el cuerpo no es un objeto)"
    respuesta = payload.get("response")
    candidatos: list[tuple[str, Any]] = [
        ("payload['dict']", payload.get("dict")),
        ("payload['response']['dict']", respuesta.get("dict") if isinstance(respuesta, dict) else None),
        ("payload['response']", respuesta),
        ("payload", payload),
    ]
    for ruta, candidato in candidatos:
        if not isinstance(candidato, dict):
            continue
        numericas = {
            int(clave): valor
            for clave, valor in candidato.items()
            if str(clave).lstrip("-").isdigit() and isinstance(valor, dict)
        }
        if numericas:
            return numericas, ruta
    return {}, "ninguna (no hay claves numéricas)"


def _describir_nodo(nodo: dict[str, Any]) -> str:
    clase = nodo.get("class")
    etiqueta = _CLASES_ETIQUETA.get(clase, f"clase {clase}")
    nombre = nodo.get("name") or atributo(nodo, 75) or "-"
    return f"{etiqueta} · {nombre}"


async def _sondear_camino_optico(cliente: CromoClient, pelo_id: int) -> tuple[SeccionSonda, dict[str, Any]]:
    """Contesta las incógnitas empíricas de `/network/fo/{id}/path` con UNA llamada real.

    Sólo lectura: un GET, sin escribir en Cromo ni en la base local.
    """
    seccion = SeccionSonda(f"1. Camino óptico de `/network/fo/{pelo_id}/path`")

    inicio = time.monotonic()
    payload = await cliente.get_camino_optico(pelo_id)
    duracion = time.monotonic() - inicio

    dic, ruta_envoltura = _desenvolver_dict_sonda(payload)
    seccion.agregar(f"- **Latencia real:** {duracion:.2f} s")
    seccion.agregar(f"- **Claves de nivel superior:** `{sorted(payload)[:12] if isinstance(payload, dict) else type(payload).__name__}`")
    seccion.agregar(f"- **Envoltura que resolvió el dict:** `{ruta_envoltura}`")
    seccion.agregar(f"- **Nodos en el dict:** {len(dic)}")

    if not dic:
        seccion.marcar_error(
            "La respuesta no trajo ningún nodo indexado por id numérico — revisar la envoltura "
            "contra el payload crudo volcado abajo."
        )
        return seccion, payload

    # ── Incógnita 1: ¿el endpoint habla en n_id de linaje o en id de versión? ──
    con_ambos_lados = [oid for oid, nodo in dic.items() if nodo.get("a") is not None and nodo.get("b") is not None]
    seccion.agregar("")
    seccion.agregar("### Identidad del pelo consultado (n_id de linaje vs. id de versión)")
    seccion.agregar(f"- ¿`{pelo_id}` es clave del dict?: **{'SÍ' if pelo_id in dic else 'NO'}**")
    seccion.agregar(f"- Nodos con `a[]` y `b[]` a la vez (deberían ser sólo el pelo raíz): `{con_ambos_lados}`")
    if pelo_id in dic:
        seccion.agregar("- **Veredicto:** `/path` aceptó el `n_id` estable que tenemos en la base local.")
    elif len(con_ambos_lados) == 1:
        seccion.agregar(
            f"- **Veredicto:** `/path` devolvió la raíz bajo otro id (`{con_ambos_lados[0]}`) — "
            "es un id de VERSIÓN y hace falta traducir linaje↔versión."
        )
    else:
        seccion.agregar("- **Veredicto:** indeterminado, no hay una raíz única identificable.")

    raiz_id = pelo_id if pelo_id in dic else (con_ambos_lados[0] if len(con_ambos_lados) == 1 else None)
    raiz = dic.get(raiz_id) if raiz_id is not None else None

    # ── Incógnita 4/5: ¿dónde termina cada lado? ¿aparecen ODFs (69) y tubos (129)? ──
    if raiz is not None:
        lado_a = [int(x) for x in (raiz.get("a") or [])]
        lado_b = [int(x) for x in (raiz.get("b") or [])]
        seccion.agregar("")
        seccion.agregar("### Recorrido")
        seccion.agregar(f"- `father` (tubo): `{raiz.get('father')}` · `gfather` (cable): `{raiz.get('gfather')}`")
        for etiqueta, lado in (("a[]", lado_a), ("b[]", lado_b)):
            no_resueltos = [oid for oid in lado if oid not in dic]
            ultimo = dic.get(lado[-1]) if lado and lado[-1] in dic else None
            seccion.agregar(
                f"- **{etiqueta}**: {len(lado)} elementos · "
                f"último: {_describir_nodo(ultimo) if ultimo else 'no resuelto'} · "
                f"ids ausentes del dict: {len(no_resueltos)}"
            )
        clases_por_lado = {
            etiqueta: sorted({dic[oid].get("class") for oid in lado if oid in dic})
            for etiqueta, lado in (("a[]", lado_a), ("b[]", lado_b))
        }
        seccion.agregar(f"- Clases presentes por lado: `{clases_por_lado}`")

    histograma = Counter(nodo.get("class") for nodo in dic.values())
    seccion.agregar("")
    seccion.agregar("### Clases en el camino")
    for clase, cantidad in histograma.most_common():
        seccion.agregar(f"- `{clase}` ({_CLASES_ETIQUETA.get(clase, 'desconocida')}): {cantidad}")
    seccion.agregar(f"- ¿Aparece la clase 69 (ODF)?: **{'SÍ' if 69 in histograma else 'NO'}** "
                    "— de esto depende poder proponer una ODF desde el camino.")
    seccion.agregar(f"- ¿Aparece la clase 129 (tubo)?: **{'SÍ' if 129 in histograma else 'NO'}**")

    # ── Incógnita 3 + discrepancia de atributos del pelo ──
    if raiz is not None:
        seccion.agregar("")
        seccion.agregar("### Atributos del pelo raíz (todos, crudos)")
        for atr in raiz.get("at") or []:
            etiqueta = atr.get("name") or ATRIBUTOS_CONOCIDOS.get(atr.get("id"), "?")
            seccion.agregar(f"- `at.{atr.get('id')}` ({etiqueta}) = `{atr.get('value')}`")
        seccion.agregar(f"- **¿Viene `at.62` (servicio limpio)?**: **{'SÍ' if atributo(raiz, 62) else 'NO'}**")

    # Inventario de atributos por clase: alimenta ATRIBUTOS_CONOCIDOS y busca atenuación.
    inventario: dict[int, dict[int, tuple[str, str]]] = {}
    for nodo in dic.values():
        clase = nodo.get("class")
        for atr in nodo.get("at") or []:
            inventario.setdefault(clase, {}).setdefault(
                atr.get("id"), (str(atr.get("name") or ""), str(atr.get("value"))[:40])
            )
    seccion.agregar("")
    seccion.agregar("### Inventario de atributos por clase (id · name de Cromo · valor de muestra)")
    for clase in sorted(inventario, key=lambda c: (c is None, c)):
        seccion.agregar(f"- **clase {clase}** ({_CLASES_ETIQUETA.get(clase, 'desconocida')}):")
        for atr_id in sorted(inventario[clase], key=lambda a: (a is None, a)):
            nombre, muestra = inventario[clase][atr_id]
            conocido = "" if atr_id in ATRIBUTOS_CONOCIDOS else "  ⟵ no está en ATRIBUTOS_CONOCIDOS"
            seccion.agregar(f"  - `at.{atr_id}` `{nombre}` = `{muestra}`{conocido}")

    sospechosos_db = [
        (clase, atr_id, nombre, muestra)
        for clase, atrs in inventario.items()
        for atr_id, (nombre, muestra) in atrs.items()
        if re.search(r"db|aten|loss|perdida|pérdida", f"{nombre} {atr_id}", re.IGNORECASE)
    ]
    seccion.agregar("")
    seccion.agregar("### ¿Publica Cromo la atenuación (dB)?")
    if sospechosos_db:
        for clase, atr_id, nombre, muestra in sospechosos_db:
            seccion.agregar(f"- Candidato: clase `{clase}` `at.{atr_id}` `{nombre}` = `{muestra}`")
    else:
        seccion.agregar(
            "- **NO** hay ningún atributo cuyo nombre sugiera atenuación/pérdida en todo el camino. "
            "Decisión de producto pendiente: calcularla declarando procedencia, u omitirla."
        )

    # ── Incógnita 5: ¿alcanza tp[] de la fusión para armar el par fusionado? ──
    fusiones = [(oid, nodo) for oid, nodo in dic.items() if nodo.get("class") == 132]
    seccion.agregar("")
    seccion.agregar("### Fusiones")
    if fusiones:
        oid, nodo = fusiones[0]
        seccion.agregar(f"- Muestra `{oid}`: `name`=`{nodo.get('name')}` · `tp`=`{nodo.get('tp')}`")
        seccion.agregar(f"- Total de fusiones en el camino: {len(fusiones)}")
    else:
        seccion.agregar("- No apareció ninguna fusión (clase 132) en este camino.")

    return seccion, payload


async def ejecutar_sonda_camino_optico(pelo_id: int) -> tuple[str, dict[str, Any]]:
    """Modo acotado de la sonda: sólo el camino óptico de un pelo, con su payload crudo."""
    inicio_ejecucion = datetime.now(timezone.utc).isoformat()
    try:
        config = get_cromo_config()
    except CromoConfigError as exc:
        return f"# Sonda de camino óptico\n\n**No se pudo iniciar:** {exc}\n", {}

    logger.info(
        "action=cromo_sonda_camino evento=inicio pelo_id=%s url_servidor=%s", pelo_id, config.url_servidor
    )
    async with CromoClient(config=config) as cliente:
        try:
            seccion, payload = await _sondear_camino_optico(cliente, pelo_id)
        except (CromoClientError, httpx.HTTPError) as exc:
            seccion = SeccionSonda(f"1. Camino óptico de `/network/fo/{pelo_id}/path`")
            seccion.marcar_error(str(exc))
            payload = {}

    encabezado = [
        "# Sonda de camino óptico — Cromo Red",
        "",
        f"- Inicio: {inicio_ejecucion}",
        f"- Fin: {datetime.now(timezone.utc).isoformat()}",
        f"- Servidor consultado: {config.base_url}",
        f"- Pelo consultado: {pelo_id}",
        "",
        "Script de sólo lectura (un GET). No escribe en Cromo ni en la base local.",
        "",
    ]
    return "\n".join(encabezado) + "\n" + seccion.a_markdown(), payload


async def ejecutar_sonda() -> str:
    inicio_ejecucion = datetime.now(timezone.utc).isoformat()
    try:
        config = get_cromo_config()
    except CromoConfigError as exc:
        return f"# Sonda de descubrimiento Cromo\n\n**No se pudo iniciar:** {exc}\n"

    logger.info("action=cromo_sonda evento=inicio url_servidor=%s", config.url_servidor)
    secciones: list[SeccionSonda] = []

    async with CromoClient(config=config) as cliente:
        for titulo, corutina, args in (
            ("1. Identificación de la clase 69", _sondear_clase_69, (cliente,)),
            ("2. Peso de la página del barrido de botellas", _medir_peso_pagina_botellas, (cliente,)),
            ("4. Counts actuales por clase", _contar_clases, (cliente,)),
        ):
            try:
                secciones.append(await corutina(*args))
            except (CromoClientError, httpx.HTTPError) as exc:
                seccion = SeccionSonda(titulo)
                seccion.marcar_error(str(exc))
                secciones.append(seccion)

        botellas: list[dict[str, Any]] = []
        cables: list[dict[str, Any]] = []
        try:
            seccion_atributos, botellas, cables = await _inventariar_atributos(cliente)
            secciones.append(seccion_atributos)
        except (CromoClientError, httpx.HTTPError) as exc:
            seccion = SeccionSonda("5. Inventario de atributos (10 botellas · 10 cables)")
            seccion.marcar_error(str(exc))
            secciones.append(seccion)

        try:
            n_id_cable = _extraer_primer_n_id_cable(botellas)
            secciones.append(await _sondear_inner_de_cable(cliente, n_id_cable))
        except (CromoClientError, httpx.HTTPError) as exc:
            seccion = SeccionSonda("3. ¿/db/objects/{id_cable}/inner expande tubos y pelos?")
            seccion.marcar_error(str(exc))
            secciones.append(seccion)

        try:
            secciones.append(await _controlar_capacidad(cliente, cables))
        except (CromoClientError, httpx.HTTPError) as exc:
            seccion = SeccionSonda("6. Control de capacidad declarada vs. pelos recibidos")
            seccion.marcar_error(str(exc))
            secciones.append(seccion)

    def _orden(seccion: SeccionSonda) -> int:
        coincidencia = re.match(r"^(\d+)\.", seccion.titulo)
        return int(coincidencia.group(1)) if coincidencia else 99

    secciones.sort(key=_orden)

    fin_ejecucion = datetime.now(timezone.utc).isoformat()
    encabezado = [
        "# Sonda de descubrimiento — Cromo Red",
        "",
        f"- Inicio: {inicio_ejecucion}",
        f"- Fin: {fin_ejecucion}",
        f"- Servidor consultado: {config.base_url}",
        "",
        "Script de sólo lectura. No escribe en Cromo ni en la base local.",
        "",
    ]
    cuerpo = "\n".join(seccion.a_markdown() for seccion in secciones)
    return "\n".join(encabezado) + "\n" + cuerpo


def main() -> None:
    parser_cli = argparse.ArgumentParser(
        description="Sonda de descubrimiento de sólo lectura contra Cromo Red."
    )
    parser_cli.add_argument(
        "--camino-optico",
        type=int,
        metavar="PELO_ID",
        help=(
            "Modo acotado: sondea sólo `GET /network/fo/PELO_ID/path` (camino óptico) y vuelca "
            "además el payload crudo como fixture. Sin este flag corre la sonda completa."
        ),
    )
    args = parser_cli.parse_args()

    salida_dir = ROOT_DIR / "devs" / "output"
    salida_dir.mkdir(parents=True, exist_ok=True)
    marca = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if args.camino_optico is not None:
        reporte, payload = asyncio.run(ejecutar_sonda_camino_optico(args.camino_optico))
        salida_path = salida_dir / f"cromo_sonda_camino_{args.camino_optico}_{marca}.md"
        salida_path.write_text(reporte, encoding="utf-8")
        if payload:
            payload_path = salida_dir / f"cromo_path_{args.camino_optico}_{marca}.json"
            payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[OK] Payload crudo volcado en {payload_path}")
        print(f"[OK] Reporte de sonda escrito en {salida_path}")
        return

    reporte = asyncio.run(ejecutar_sonda())
    salida_path = salida_dir / f"cromo_sonda_{marca}.md"
    salida_path.write_text(reporte, encoding="utf-8")

    print(f"[OK] Reporte de sonda escrito en {salida_path}")


if __name__ == "__main__":
    main()
