# Nombre de archivo: cromo_sonda.py
# Ubicación de archivo: scripts/cromo_sonda.py
# Descripción: Script de descubrimiento de sólo lectura contra Cromo Red para cerrar puntos abiertos de docs/ingesta_cromo.md

from __future__ import annotations

import asyncio
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
from core.services.cromo.parser import atributo

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
    reporte = asyncio.run(ejecutar_sonda())

    salida_dir = ROOT_DIR / "devs" / "output"
    salida_dir.mkdir(parents=True, exist_ok=True)
    marca = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    salida_path = salida_dir / f"cromo_sonda_{marca}.md"
    salida_path.write_text(reporte, encoding="utf-8")

    print(f"[OK] Reporte de sonda escrito en {salida_path}")


if __name__ == "__main__":
    main()
