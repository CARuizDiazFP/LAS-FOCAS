# Nombre de archivo: validador_datos_service.py
# Ubicación de archivo: core/services/cromo/validador_datos_service.py
# Descripción: Validador de datos en vivo contra Cromo por n_id — mismo tratamiento de parseo que la ingesta (árbol completo), cero acceso a la base de datos local

"""Herramienta de diagnóstico "Validar datos DB Cromo" (Tool Kit): dado un n_id, consulta Cromo en
vivo y le aplica EXACTAMENTE el mismo parseo que usa `core/services/cromo/ingesta.py` — `parse_objeto`
(dispatch genérico por clase, el mismo que usa `parse_pagina`), `parse_arbol_botella` (árbol completo
de una botella: fusiones/cables/tubos/pelos) y `extraer_tubos_y_pelos` (tubos/pelos propios de un
cable) — sin persistir absolutamente nada. Distinto de `live_lookup_service.py` (que sólo devuelve los
atributos planos del objeto consultado, sin armar el árbol) y del todo independiente de
`VerificadorCromoView.vue`/`ModalVerificadorCromo.vue` (que consultan servicios ya matcheados contra
el inventario YA ingerido) — confirmado explícitamente con el usuario como herramienta separada.

Cero acceso a la base de datos local, ni siquiera en lectura (confirmado explícitamente): los
"servicios" de cada pelo se exponen crudos (`servicio_raw`/`servicio_numero`), nunca resueltos contra
`app.servicios`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.services.cromo import parser as cromo_parser
from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.modelos import Cable, Fusion, Pelo, Tubo
from core.services.cromo.parser import ClaseExcluidaError, ClaseNoSoportadaError, ErrorParseo
from core.services.cromo.verificador import ObjetoNoEncontrado


@dataclass(slots=True)
class ResultadoValidacionCromo:
    n_id: int
    clase: Optional[int]
    tipo_objeto: str
    nombre: Optional[str]
    notas: Optional[str]
    latitud: Optional[float]
    longitud: Optional[float]
    codigo_modelo: Optional[str]
    id_legacy: Optional[str]
    cables: list[Cable] = field(default_factory=list)
    tubos: list[Tubo] = field(default_factory=list)
    pelos: list[Pelo] = field(default_factory=list)
    fusiones: list[Fusion] = field(default_factory=list)
    errores_parseo: list[ErrorParseo] = field(default_factory=list)
    payload_raw: dict[str, Any] = field(default_factory=dict, repr=False)


async def validar_elemento_cromo(cliente: CromoClient, n_id: int) -> ResultadoValidacionCromo:
    """GET en vivo contra Cromo (`CromoClient.get_objeto`) + parseo con las mismas funciones que usa
    la ingesta — sin tocar la base de datos local en ningún momento.

    Un objeto de clase excluida o no soportada (`ClaseExcluidaError`/`ClaseNoSoportadaError`, ver
    `parser.py::parse_objeto`) no rompe la herramienta — el propósito es diagnóstico, así que se
    devuelve igual con `tipo_objeto="Desconocido"` y el motivo en `errores_parseo`, nunca un 500.
    """
    try:
        obj = await cliente.get_objeto(n_id)
    except CromoClientError as exc:
        if exc.status_code == 404:
            raise ObjetoNoEncontrado(f"No existe un elemento con n_id={n_id} en Cromo.") from exc
        raise

    clase = obj.get("class")
    tipo_objeto = "Desconocido"
    nombre: Optional[str] = None
    notas: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    codigo_modelo: Optional[str] = None
    id_legacy: Optional[str] = None
    cables: list[Cable] = []
    tubos: list[Tubo] = []
    pelos: list[Pelo] = []
    fusiones: list[Fusion] = []
    errores: list[ErrorParseo] = []

    try:
        dominio = cromo_parser.parse_objeto(obj)
    except (ClaseExcluidaError, ClaseNoSoportadaError) as exc:
        errores.append(ErrorParseo(n_id=n_id, clase=clase, motivo=str(exc)))
        dominio = None

    if dominio is not None:
        tipo_objeto = type(dominio).__name__
        if tipo_objeto == "Botella":
            arbol = cromo_parser.parse_arbol_botella(obj)
            nombre = arbol.botella.nombre
            notas = arbol.botella.notas
            codigo_modelo = arbol.botella.codigo_modelo
            id_legacy = arbol.botella.id_legacy
            latitud = arbol.botella.latitud
            longitud = arbol.botella.longitud
            cables = arbol.cables
            tubos = arbol.tubos
            pelos = arbol.pelos
            fusiones = arbol.fusiones
            errores.extend(arbol.errores)
        elif isinstance(dominio, Cable):
            nombre = dominio.nombre
            id_legacy = dominio.id_legacy
            cables = [dominio]
            tubos_propios, pelos_propios, errores_propios = cromo_parser.extraer_tubos_y_pelos(obj)
            tubos = tubos_propios
            pelos = pelos_propios
            errores.extend(errores_propios)
        elif isinstance(dominio, Fusion):
            nombre = dominio.nombre_par
            latitud = dominio.latitud
            longitud = dominio.longitud
            fusiones = [dominio]
        elif isinstance(dominio, Tubo):
            nombre = dominio.nombre_color
            tubos = [dominio]
        elif isinstance(dominio, Pelo):
            nombre = dominio.numero_pelo
            pelos = [dominio]

    return ResultadoValidacionCromo(
        n_id=n_id,
        clase=clase,
        tipo_objeto=tipo_objeto,
        nombre=nombre,
        notas=notas,
        latitud=latitud,
        longitud=longitud,
        codigo_modelo=codigo_modelo,
        id_legacy=id_legacy,
        cables=cables,
        tubos=tubos,
        pelos=pelos,
        fusiones=fusiones,
        errores_parseo=errores,
        payload_raw=obj,
    )


__all__ = ["ResultadoValidacionCromo", "validar_elemento_cromo"]
