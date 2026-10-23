# Nombre de archivo: camara_botella_busqueda.py
# Ubicación de archivo: core/services/cromo/camara_botella_busqueda.py
# Descripción: Búsqueda extendida por nombre libre que cierra el gap Camara-only, agregando CromoBotella como segunda fuente

"""Componente compartido de búsqueda: resuelve texto libre de técnicos/operadores a una raíz
`Camara`, buscando primero en `app.camaras` (fuente canónica, vía `buscar_camara()` del listener de
Slack de ingreso) y, si no hay match ahí, en `app.cromo_botellas` — el inventario real de Cromo Red
tiene botellas que nunca tuvieron fila propia en `Camara` (ej. "Bot 2 Cra Mitre 440"), y hoy esa
búsqueda las ignora por completo.

Pensado para ser consumido por dos flujos que hoy NO se tocan en esta tarea (quedan para tareas
futuras del mismo plan): el listener de Slack de ingreso de técnicos
(`modules/slack_baneo_notifier/listener.py`) y el flujo "adjuntar tracking" del portal Infra
(`core/services/infra_service.py`).

Riesgo conocido, sin acción en esta tarea: la cascada ILIKE/tokens de este módulo hace table scan
sobre `app.cromo_botellas` en cada llamada porque el patrón real (`ILIKE '%patron%'` sobre
`unaccent(lower(nombre))`) no se beneficia del índice btree simple sobre `nombre` ni del GIN de
full-text ya existente. La corrección real de rendimiento exige decidir un índice funcional o una
extensión como `pg_trgm` y queda fuera del alcance de este fix mecánico; no se toca
`db/models/cromo.py` acá.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from modules.slack_baneo_notifier.camara_search import (
    AmbiguousSearchError,
    NumeroNoCoincideError,
    _aplicar_sinonimos,
    _expandir_abreviaturas,
    _filtrar_bots_secundarios,
    _filtrar_numero_de_botella,
    _filtrar_por_numeros,
    _limpiar_puntuacion,
    _normalizar,
    botella_cromo_por_n_id,
    buscar_camara,
    camara_por_prefijo_empalme,
    normalizar_candidato,
    preparar_nombre_busqueda,
    quitar_botella_uno,
    recorte_pierde_la_botella,
    resto_corrobora_botella,
    tiene_gemela_critica,
)

if TYPE_CHECKING:
    from db.models.infra import Camara
    from db.models.cromo import CromoBotella


@dataclass(slots=True)
class ResultadoBusquedaExtendida:
    """Resultado de `buscar_camara_o_botella_cromo()`.

    Attributes:
        camara:       Cámara raíz a evaluar — propia (``fuente="camara"``) o resuelta desde la
                      ``CromoBotella`` matcheada (``fuente="cromo_botella"``, vía
                      ``CromoBotella.camara``). ``None`` si no hubo match en ninguna fuente.
        nombre_norm:  Nombre normalizado usado para la búsqueda (mismo criterio de
                      normalización que ``buscar_camara()``).
        fuente:       ``"camara"`` | ``"cromo_botella"`` | ``None`` (sin match).
        botella:      La ``CromoBotella`` matcheada, sólo si ``fuente == "cromo_botella"``.
    """

    camara: "Camara | None"
    nombre_norm: str
    fuente: Literal["camara", "cromo_botella"] | None
    botella: "CromoBotella | None"


def _normalizar_pipeline(nombre_raw: str) -> str:
    """Reproduce, sin duplicarlo, el mismo pipeline de preprocesamiento que usa `buscar_camara()`
    internamente: limpiar puntuación → expandir abreviaturas → normalizar → sinónimos. Necesario
    para poder correr una cascada "equivalente" contra `CromoBotella.nombre` con el mismo criterio
    de normalización que ya usa la búsqueda canónica de `Camara`."""
    nombre_limpio = _limpiar_puntuacion(nombre_raw)
    nombre_expandido = _expandir_abreviaturas(nombre_limpio)
    nombre_norm_base = _normalizar(nombre_expandido)
    return _aplicar_sinonimos(nombre_norm_base)


def _buscar_botella_ilike_lista(patron: str, session: Session) -> list["CromoBotella"]:
    """Query ILIKE '%patron%' sobre CromoBotella.nombre. Sin JOIN de alias: a diferencia de
    Camara/CamaraAlias, CromoBotella no tiene una tabla de alias de nombre equivalente."""
    from db.models.cromo import CromoBotella

    return (
        session.query(CromoBotella)
        .filter(func.unaccent(func.lower(CromoBotella.nombre)).ilike(f"%{patron}%"))
        .all()
    )


def _buscar_botella_tokens_lista(tokens: list[str], session: Session) -> list["CromoBotella"]:
    """Busca CromoBotella cuyo nombre contenga TODOS los tokens dados (AND ILIKE)."""
    from db.models.cromo import CromoBotella

    condiciones = [
        func.unaccent(func.lower(CromoBotella.nombre)).ilike(f"%{token}%")
        for token in tokens
    ]
    return session.query(CromoBotella).filter(and_(*condiciones)).all()


# Mismo patrón que el `tiene_bot` inline de `buscar_camara()` (camara_search.py): se evalúa sobre
# el nombre_raw ORIGINAL, antes de normalizar/sinonimizar (donde "botella" ya habría mutado a
# "bot"). No se exporta desde camara_search.py porque ahí tampoco es una constante nombrada — es
# una expresión inline dentro de buscar_camara() — así que este regex se duplica deliberadamente
# aquí como la contraparte mínima, igual que ya se recalculan `numeros_requeridos` de forma
# independiente en este módulo en vez de recibirlos por parámetro.
_RE_TIENE_BOT = re.compile(r"\bbot(ella)?\b", re.IGNORECASE)


def _cascada_botella(nombre_raw: str, session: Session, *, desempatar: bool = True) -> list["CromoBotella"]:
    """Intenta primero sólo con el texto antes del primer guión (mismo criterio que
    `buscar_camara()` — ver su docstring: cubre el caso real del técnico pegando el título
    completo de Cromo, "Nombre - Calle Altura - Localidad - Provincia"). Si el prefijo no resuelve
    a exactamente una `CromoBotella`, cae a `_cascada_botella_intento()` con el string completo —
    preserva casos donde el sufijo es parte legítima del nombre (ej. "Poste Lavalle - Campana")."""
    if "-" in nombre_raw:
        prefijo = nombre_raw.split("-", 1)[0].strip()
        if prefijo and prefijo != nombre_raw.strip() and not recorte_pierde_la_botella(prefijo, nombre_raw):
            # Sobre el recorte, sólo la cascada original (sin desempates ni intento literal) —
            # mismo criterio que `buscar_camara()`: un recorte que resuelve "de más" no prueba nada.
            candidatos_prefijo = _cascada_botella_intento(prefijo, session, extendida=False)
            if len(candidatos_prefijo) == 1:
                return candidatos_prefijo
    return _cascada_botella_intento(nombre_raw, session, extendida=True, desempatar=desempatar)


def _cascada_botella_intento(
    nombre_raw: str, session: Session, *, extendida: bool = True, desempatar: bool = True
) -> list["CromoBotella"]:
    """Cascada equivalente a los Intentos 1-2 de `buscar_camara()`, pero contra
    `CromoBotella.nombre`: ILIKE con el nombre normalizado completo, y si no reduce a 1 candidato,
    AND-ILIKE por tokens significativos (≥3 chars). En ambos pasos se filtra por números requeridos
    con `_filtrar_por_numeros` y por bots secundarios con `_filtrar_bots_secundarios` (reusados, no
    reimplementados) — si el input no menciona "bot"/"botella" explícitamente, se excluyen
    candidatas tipo "Bot 2 Cra Mitre 440" para evitar que "Cra Mitre 440" empareje una botella
    secundaria cuando el técnico se refiere a la cámara principal.

    Guardia de input degenerado (mismo criterio que la heurística pre-búsqueda de `buscar_camara()`,
    ver camara_search.py:330-332): si hay menos de 2 tokens significativos (≥3 chars) y ningún
    número, se retorna `[]` sin consultar la DB — evita un table scan `ILIKE '%%'` que matchearía
    cada fila de `cromo_botellas`. Alcanzable en la práctica desde el camino de `buscar_camara()`
    ambiguo por input insuficiente (`AmbiguousSearchError(cantidad=0)`): ese camino re-ejecuta esta
    cascada contra `CromoBotella` con el mismo `nombre_raw` degenerado.

    Fuera de alcance deliberado (no pedido por la tarea): join de alias (no existe tabla de alias
    para CromoBotella).

    Returns:
        Lista vacía (sin match, o input degenerado), lista de 1 elemento (match único), o lista de
        2+ elementos (ambiguo — el grupo más acotado encontrado en la cascada).
    """
    nombre_norm = _normalizar_pipeline(nombre_raw)
    numeros_requeridos: set[str] = set(re.findall(r"\d+", nombre_norm))
    tiene_bot: bool = bool(_RE_TIENE_BOT.search(nombre_raw))

    tokens_sig = [t for t in nombre_norm.split() if len(t) >= 3]
    if len(tokens_sig) < 2 and not numeros_requeridos:
        return []

    def _filtrada(candidatos: list["CromoBotella"]) -> list["CromoBotella"]:
        candidatos = _filtrar_por_numeros(candidatos, numeros_requeridos)
        candidatos = _filtrar_bots_secundarios(candidatos, tiene_bot)
        return _filtrar_numero_de_botella(candidatos, nombre_raw)

    desempatar = desempatar and extendida
    mejor_ambiguo: list["CromoBotella"] = []

    def _evaluar(candidatos: list["CromoBotella"]) -> list["CromoBotella"] | None:
        nonlocal mejor_ambiguo
        if len(candidatos) == 1:
            return candidatos
        if len(candidatos) > 1:
            desempate = _desempatar_botellas(candidatos, nombre_norm) if desempatar else None
            if desempate is not None:
                return [desempate]
            if not mejor_ambiguo or len(candidatos) < len(mejor_ambiguo):
                mejor_ambiguo = candidatos
        return None

    # ── Intento 1: ILIKE con el nombre normalizado completo ──────────────
    resuelto = _evaluar(_filtrada(_buscar_botella_ilike_lista(nombre_norm, session)))
    if resuelto:
        return resuelto

    # ── Intento 2: todos los tokens (≥3 chars) presentes ─────────────────
    if len(tokens_sig) >= 2:
        resuelto = _evaluar(_filtrada(_buscar_botella_tokens_lista(tokens_sig, session)))
        if resuelto:
            return resuelto

    # ── Intento 3: sin expansión de abreviaturas (2026-09-28) ────────────
    # Paridad con el Intento 4 de `buscar_camara()`: Cromo guarda "Av"/"Dr" literales, y la entrada
    # expandida ("avenida"/"doctor") no los encuentra. Caso real: "Cra Av Santa Fe 4276 Bot 2 CF"
    # existe EXACTO en `cromo_botellas` y quedaba sin match (8 filas de `ingresos_sin_match` de prod).
    nombre_literal = _aplicar_sinonimos(_normalizar(_limpiar_puntuacion(nombre_raw)))
    if extendida and nombre_literal != nombre_norm:
        resuelto = _evaluar(_filtrada(_buscar_botella_ilike_lista(nombre_literal, session)))
        if resuelto:
            return resuelto
        tokens_literal = [t for t in nombre_literal.split() if len(t) >= 3]
        if len(tokens_literal) >= 2:
            resuelto = _evaluar(_filtrada(_buscar_botella_tokens_lista(tokens_literal, session)))
            if resuelto:
                return resuelto

    return mejor_ambiguo


def _desempatar_botellas(candidatos: list["CromoBotella"], nombre_norm: str) -> "CromoBotella | None":
    """Reduce 2+ `CromoBotella` candidatas a una cuando la elección no cambia el resultado real:

    1. Exactamente una coincide por igualdad con la entrada normalizada → ésa.
    2. Dos o más coinciden exacto y TODAS cuelgan de la misma Cámara padre (mismo `camara_id` no
       nulo): son la misma botella cargada dos veces — caso real "Cra A. Frondizi 1413 BOT 2 PILAR" y
       "… Bot 2 …", que sólo difieren en mayúsculas. Se toma la de menor `n_id` (determinista).

    Nunca entre botellas que NO coinciden exacto, aunque compartan padre: pueden ser botellas físicas
    distintas (Bot 2 y Bot 3), y `registrar_movimiento_ingreso` cierra el Egreso por
    `cromo_botella_id` exacto — elegir mal deja el ingreso abierto (hallazgo de la revisión de la
    rama, "Gorriti 386 Lomas botella"). Nunca si hay una gemela "CRITICA" (`tiene_gemela_critica`).
    Compara por id: dos botellas de nombre igual en Cámaras distintas siguen siendo ambiguas."""
    if tiene_gemela_critica(candidatos):
        return None
    exactas = [b for b in candidatos if normalizar_candidato(b.nombre) == nombre_norm]
    if len(exactas) == 1:
        return exactas[0]
    padres = {b.camara_id for b in exactas}
    if len(exactas) >= 2 and len(padres) == 1 and None not in padres:
        return min(exactas, key=lambda b: b.n_id)
    return None


def _fusionar_nombres_dedup(*grupos: list[str]) -> list[str]:
    """Concatena listas de nombres (en el orden dado — la primera es la fuente canónica) y
    deduplica por nombre normalizado, no por identidad ni por id (Camara y CromoBotella son tipos
    de entidad distintos, sin id compartido)."""
    vistos: set[str] = set()
    resultado: list[str] = []
    for nombre in (n for grupo in grupos for n in grupo):
        if not nombre:
            continue
        clave = _normalizar_pipeline(nombre)
        if clave in vistos:
            continue
        vistos.add(clave)
        resultado.append(nombre)
    return resultado


# "ID DE BOTELLA : 6631457 ( TZA. FLORIDA 142)" — el técnico copió el `n_id` de Cromo. 6-9 dígitos
# (rango real de `cromo_botellas.n_id`) a no más de 20 caracteres no numéricos de la palabra "ID".
_RE_ID_CROMO = re.compile(r"(?i)\bid\b\D{0,20}?(\d{6,9})(?!\d)")


def _buscar_por_id_cromo(nombre_raw: str, session: Session) -> "CromoBotella | None":
    """Botella por `n_id` explícito, sólo si es vigente, tiene Cámara padre y —cuando el texto trae
    algo más que el ID— ese resto la corrobora (comparte un número o una palabra de 4+ letras con el
    nombre). Un ID mal tipeado que exista no puede resolver a una cámara que el resto del texto
    contradice (hallazgo de la revisión de la rama)."""
    match = _RE_ID_CROMO.search(nombre_raw)
    if not match:
        return None
    botella = botella_cromo_por_n_id(int(match.group(1)), session)
    if botella is None:
        return None
    resto = nombre_raw[: match.start()] + " " + nombre_raw[match.end():]
    return botella if resto_corrobora_botella(botella, resto) else None


def buscar_por_id_legacy(id_legacy: str, session: Session) -> ResultadoBusquedaExtendida | None:
    """Cámara por "Fontaine ID" (`app.cromo_botellas.id_legacy`, el ID del sistema anterior que
    Cromo conserva; ej. real "ingreso ok, id: 1228619" → Botella 10245762 → Cámara 33978).

    Misma forma de resultado que `buscar_camara_o_botella_cromo` (``fuente="cromo_botella"``).
    Devuelve ``None`` si ninguna Botella tiene ese `id_legacy` o si la que lo tiene no está
    vinculada a una Cámara. Se consideran también las Botellas no vigentes: el `id_legacy` sigue
    identificando el lugar físico aunque Cromo haya reemplazado la versión. Si el `id_legacy` está
    en más de una Botella (hay 1 caso en dev y prod), lanza `AmbiguousSearchError` y nunca elige.
    No es `app.camaras.fontine_id` (vacía en dev y prod)."""
    from db.models.cromo import CromoBotella

    valor = (id_legacy or "").strip()
    if not valor:
        return None
    botellas = (
        session.query(CromoBotella).filter(CromoBotella.id_legacy == valor).order_by(CromoBotella.n_id).all()
    )
    if not botellas:
        return None
    if len(botellas) > 1:
        raise AmbiguousSearchError(valor, len(botellas), [b.nombre for b in botellas])
    botella = botellas[0]
    if botella.camara_id is None or botella.camara is None:
        return None
    return ResultadoBusquedaExtendida(
        camara=botella.camara,
        nombre_norm=_normalizar_pipeline(botella.nombre or ""),
        fuente="cromo_botella",
        botella=botella,
    )


def buscar_camara_o_botella_cromo(
    nombre_raw: str, session: Session, *, desempatar: bool = True, tolerante: bool = True
) -> ResultadoBusquedaExtendida:
    """Punto de entrada de la búsqueda extendida (ver `_buscar_extendida` para la cascada).

    Agregado el 2026-09-28 (`docs/relevamiento_ingresos_sin_match_2026-09-28.md`), en este orden:

    1. **ID de Cromo explícito** ("ID DE BOTELLA : 6631457 …", y desde 2026-10-23 el prefijo
       "Empalme 10245762: …"): lookup directo por `n_id`.
    2. `preparar_nombre_busqueda`: "bot2" → "Bot 2", "huergo701" → "huergo 701".
    3. La cascada, y si no resolvió a una cámara y el texto menciona "Bot 1"/"Botella 1", un
       segundo intento sin esa mención (= la Cámara principal). Si el segundo intento tampoco
       resuelve, se devuelve el resultado —o se relanza la ambigüedad— del PRIMERO: la variante
       sólo puede ganar con un match único, nunca empeorar la respuesta original.

    `desempatar=False` apaga los desempates entre candidatas (coincidencia exacta, misma botella
    cargada dos veces): para callers que nunca deben elegir a ciegas, como el baneo masivo desde
    Excel (`camara_ingest_service`). El resto de las mejoras sigue activo — resuelven matches
    únicos, no eligen entre varios.

    4. (2026-09-29) Si sigue sin match, `_resultado_tolerante`: sin la localidad final y/o sin el
       tipo inicial ("Cra" escrito para un "Poste"). `tolerante=False` lo apaga: el baneo masivo
       desde Excel busca nombres del inventario y banear una cámara por un texto "parecido" es peor
       que dejarlo sin match.
    """
    # "Empalme <n_id>: <nombre>" (2026-10-23): resuelto por `n_id` antes que nada, devolviendo la
    # Botella (no sólo la Cámara, como haría `buscar_camara`). Si no resuelve, sigue sin el prefijo.
    botella_id, nombre_raw = camara_por_prefijo_empalme(nombre_raw, session)
    if botella_id is None:
        botella_id = _buscar_por_id_cromo(nombre_raw, session)
    if botella_id is not None:
        return ResultadoBusquedaExtendida(
            camara=botella_id.camara,
            nombre_norm=_normalizar_pipeline(nombre_raw),
            fuente="cromo_botella",
            botella=botella_id,
        )

    nombre = preparar_nombre_busqueda(nombre_raw)
    variante = quitar_botella_uno(nombre)
    try:
        resultado = _buscar_extendida(nombre, session, desempatar=desempatar)
    except NumeroNoCoincideError:
        # Para la cascada es un "sin match" (sólo trae sugerencias): pasa por los mismos reintentos
        # que un sin match y, si ninguno resuelve, se relanza con sus sugerencias.
        alternativo = _reintentos_sin_match(nombre, variante, session, desempatar, tolerante)
        if alternativo is not None:
            return alternativo
        raise
    except AmbiguousSearchError:
        if variante == nombre:
            raise
        alternativo = _resultado_variante(variante, session, desempatar)
        if alternativo is not None:
            return alternativo
        raise
    if resultado.camara is None:
        alternativo = _reintentos_sin_match(nombre, variante, session, desempatar, tolerante)
        if alternativo is not None:
            return alternativo
    return resultado


def _reintentos_sin_match(
    nombre: str, variante: str, session: Session, desempatar: bool, tolerante: bool
) -> ResultadoBusquedaExtendida | None:
    """Reintentos de un texto sin match, en orden: sin "Bot 1" y, si `tolerante`, sin localidad/
    tipo. Sólo cuentan con un match único."""
    if variante != nombre:
        alternativo = _resultado_variante(variante, session, desempatar)
        if alternativo is not None:
            return alternativo
    if tolerante:
        return _resultado_tolerante(nombre, session, desempatar)
    return None


# Tipo de elemento al inicio del texto que el técnico a veces escribe distinto del inventario: "Cra
# colectora oeste panamericana 31.500" para el "Poste Colectora Oeste Panamericana Km. 31.500".
# Sólo tipos de Cámara — nunca "Bot"/"Tza": una botella no es intercambiable con su cámara.
_RE_TIPO_CAMARA = re.compile(r"(?i)^\s*(?:cra|c[aá]mara|poste)\b\.?\s*")


def _resultado_tolerante(
    nombre: str, session: Session, desempatar: bool
) -> ResultadoBusquedaExtendida | None:
    """Reintentos para un texto SIN MATCH (nunca para uno ambiguo), en este orden (2026-09-29, casos
    #204/#205 de prod):

    1. Sin la localidad final ("… 31.500 EL TALAR" → "… 31.500", ver `localidades_catalogo`).
    2. Sin el tipo inicial ("Cra"/"Cámara"/"Poste"), con y sin localidad. Sólo si queda un número
       (altura/km) y la cámara encontrada es también de tipo Cámara ("Cra …"/"Poste …"/"Cámara …"),
       resuelta por su nombre y no por una Botella de Cromo: el tipo sólo es intercambiable entre
       cámaras.

    Cada reintento cuenta sólo con un match único (`_resultado_variante`) cuyos números sean
    exactamente los del texto (`_numeros_coinciden`); si ninguno resuelve, el caller devuelve el
    resultado original.
    """
    from core.services.localidades_catalogo import localidades, quitar_localidad_final

    sin_localidad = quitar_localidad_final(nombre, localidades(session))
    if sin_localidad != nombre:
        alternativo = _resultado_variante(sin_localidad, session, desempatar)
        if alternativo is not None and _numeros_coinciden(sin_localidad, alternativo):
            return alternativo

    if not _RE_TIPO_CAMARA.match(nombre):
        return None
    for texto in dict.fromkeys((nombre, sin_localidad)):
        sin_tipo = _RE_TIPO_CAMARA.sub("", texto, count=1).strip()
        if not re.search(r"\d", sin_tipo):
            continue
        alternativo = _resultado_variante(sin_tipo, session, desempatar)
        if (
            alternativo is not None
            and alternativo.fuente == "camara"
            and _RE_TIPO_CAMARA.match(alternativo.camara.nombre or "")
            and _numeros_coinciden(sin_tipo, alternativo)
        ):
            return alternativo
    return None


_RE_NUMERO_COMPLETO = re.compile(r"\d+(?:[.,]\d+)*")


def _numeros_coinciden(texto: str, resultado: ResultadoBusquedaExtendida) -> bool:
    """Cada número del texto, ENTERO y con sus decimales, está en el nombre encontrado.

    El filtro de números de la cascada acepta "63" dentro de "63.9" y "9" como el decimal de "63.9"
    — suficiente cuando el texto es el nombre completo, pero no para un reintento que ya le sacó
    palabras al texto: el arnés de transiciones (2026-09-29) encontró "Poste Ruta 9 Km 63 CAMPANA"
    resolviendo, sin la localidad, a "Poste Ruta 8 Km 63.9 y Cosme FATIMA"."""
    nombre = resultado.botella.nombre if resultado.botella is not None else resultado.camara.nombre
    del_nombre = set(_RE_NUMERO_COMPLETO.findall(nombre or ""))
    return set(_RE_NUMERO_COMPLETO.findall(texto)) <= del_nombre


def _resultado_variante(
    nombre: str, session: Session, desempatar: bool
) -> ResultadoBusquedaExtendida | None:
    """Intento con la variante sin "Bot 1": sólo cuenta si resuelve a una cámara."""
    try:
        resultado = _buscar_extendida(nombre, session, desempatar=desempatar)
    except AmbiguousSearchError:
        return None
    return resultado if resultado.camara is not None else None


def _buscar_extendida(
    nombre_raw: str, session: Session, *, desempatar: bool = True
) -> ResultadoBusquedaExtendida:
    """Busca una Cámara por nombre libre, ampliando la búsqueda a `CromoBotella` cuando la cascada
    canónica de `buscar_camara()` no encuentra nada en `Camara`.

    Cascada:
      1. `buscar_camara(nombre_raw, session)` sin modificar — si matchea, listo (no se consulta
         `CromoBotella`, no hay ambigüedad posible entre fuentes cuando ya hay match único).
      2. Si `Camara` no matcheó nada: cascada equivalente contra `CromoBotella.nombre`.
         - Match único con `camara_id` poblado → resuelve la Cámara raíz vía `CromoBotella.camara`.
         - Match único con `camara_id is None` (backfill de cámara padre pendiente) → tratado como
           no-match completo, igual que si no hubiera matcheado nada.
         - Sin match en ninguna de las dos fuentes → resultado vacío.
         - Ambiguo (2+ candidatos que nunca se redujeron a 1) → `AmbiguousSearchError` con las
           `CromoBotella` candidatas (Camara no aportó candidatos porque no matcheó nada).
      3. Si `buscar_camara()` lanza `AmbiguousSearchError` (0 tokens significativos o múltiples
         `Camara` candidatas): se repite la misma cascada contra `CromoBotella.nombre` y se
         fusionan los candidatos de ambas fuentes (Camara primero, fuente canónica; CromoBotella
         completa el resto), deduplicados por nombre normalizado. Se relanza la misma
         `AmbiguousSearchError` con la lista fusionada — el cap a 3 lo aplica el propio
         `__init__` de la excepción.
      4. Si `buscar_camara()` lanza `NumeroNoCoincideError` (ninguna `Camara` con ese número, sólo
         parecidas): se trata como el paso 2 — si `CromoBotella` resuelve, es match; si es ambigua,
         `AmbiguousSearchError` con las botellas; si no, se relanza con las sugerencias.

    Args:
        nombre_raw: Nombre extraído del mensaje/formulario, sin normalizar.
        session:    Sesión SQLAlchemy activa (síncrona, ORM).

    Returns:
        `ResultadoBusquedaExtendida` — nunca lanza para el caso "sin match" (eso es un resultado
        válido con `camara=None`, `fuente=None`); sólo lanza `AmbiguousSearchError` cuando el
        nombre es ambiguo.

    Raises:
        AmbiguousSearchError: nombre insuficientemente específico, o múltiples candidatas sin
            reducirse a una sola entre `Camara` y `CromoBotella`.
        NumeroNoCoincideError: (subclase) ninguna con ese número en ninguna fuente, pero hay
            `Camara` parecidas sin él (sólo sugerencias, ver paso 4).
    """
    try:
        camara, nombre_norm = buscar_camara(nombre_raw, session, desempatar=desempatar)
    except NumeroNoCoincideError:
        # `Camara` no tiene ninguna con ese número (sólo parecidas): igual que un sin match, se
        # prueba `CromoBotella`. Si tampoco resuelve, se relanza con las sugerencias de `Camara`.
        resultado = _resultado_botella(nombre_raw, _normalizar_pipeline(nombre_raw), session, desempatar)
        if resultado.camara is not None:
            return resultado
        raise
    except AmbiguousSearchError as exc:
        candidatos_botella = _cascada_botella(nombre_raw, session, desempatar=desempatar)
        nombres_botella = [b.nombre for b in candidatos_botella]
        fusionados = _fusionar_nombres_dedup(exc.candidatos, nombres_botella)
        # exc.candidatos ya viene recortado a 3 por AmbiguousSearchError.__init__ — NO es el conteo
        # real de ambigüedad de Camara. exc.cantidad sí lo es (ver buscar_camara():
        # `raise AmbiguousSearchError(nombre_raw, len(_ambiguos), nombres_candidatos)`, cantidad se
        # pasa sin recortar). cantidad nunca debe reportar menos de lo que Camara sola ya encontró
        # — ese número llega tal cual a un mensaje de Slack (modules/slack_baneo_notifier/listener.py).
        cantidad = max(exc.cantidad, len(fusionados))
        raise AmbiguousSearchError(nombre_raw, cantidad, fusionados) from exc

    if camara is not None:
        return ResultadoBusquedaExtendida(
            camara=camara, nombre_norm=nombre_norm, fuente="camara", botella=None
        )
    return _resultado_botella(nombre_raw, nombre_norm, session, desempatar)


def _resultado_botella(
    nombre_raw: str, nombre_norm: str, session: Session, desempatar: bool
) -> ResultadoBusquedaExtendida:
    """Paso 2 de `_buscar_extendida`: `Camara` no matcheó nada, se prueba `CromoBotella`."""
    candidatos_botella = _cascada_botella(nombre_raw, session, desempatar=desempatar)

    if len(candidatos_botella) == 1:
        botella = candidatos_botella[0]
        if botella.camara_id is None:
            return ResultadoBusquedaExtendida(
                camara=None, nombre_norm=nombre_norm, fuente=None, botella=None
            )
        return ResultadoBusquedaExtendida(
            camara=botella.camara, nombre_norm=nombre_norm, fuente="cromo_botella", botella=botella
        )

    if len(candidatos_botella) > 1:
        nombres_botella = _fusionar_nombres_dedup([b.nombre for b in candidatos_botella])
        # Cuenta real de candidatas, no la de nombres deduplicados: dos botellas de nombre idéntico
        # en Cámaras distintas son dos candidatas (antes se informaba "1 candidato", caso Frondizi).
        raise AmbiguousSearchError(nombre_raw, len(candidatos_botella), nombres_botella)

    return ResultadoBusquedaExtendida(camara=None, nombre_norm=nombre_norm, fuente=None, botella=None)
