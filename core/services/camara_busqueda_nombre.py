# Nombre de archivo: camara_busqueda_nombre.py
# Ubicación de archivo: core/services/camara_busqueda_nombre.py
# Descripción: Cascada de búsqueda de cámaras por nombre (con DB) sobre la normalización de core/text

"""Búsqueda tolerante de cámaras a partir de texto libre escrito por técnicos.

El nombre recibido puede tener abreviaturas, acentos alternos, ausencia de
números, etc.  La estrategia en cascada garantiza que se intenten varios
niveles de coincidencia antes de rendirse.

La capa pura de texto (normalización, abreviaturas, sinónimos) vive en `core/text/normalizacion.py`;
este módulo sólo contiene la cascada que consulta la DB. `modules/slack_baneo_notifier/camara_search.py`
es un shim que re-exporta estos nombres para los callers históricos.

`filtrar_bots_secundarios` sólo toca `.nombre` vía regex — nada específico de `Camara` — así que
también se reusa contra candidatas `CromoBotella` (`core/services/cromo/camara_botella_busqueda.py`)
para evitar que "Cra Mitre 440" (sin mención de "bot"/"botella") empareje incorrectamente "Bot 2 Cra
Mitre 440".
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.text.normalizacion import (
    RE_BOT_SUFIJO,
    RE_NUMERO_BOTELLA,
    aplicar_sinonimos,
    expandir_abreviaturas,
    limpiar_puntuacion,
    normalizar,
    normalizar_candidato,
    preparar_nombre_busqueda,
    separar_prefijo_empalme,
    tokens_significativos,
)

if TYPE_CHECKING:
    from db.models.cromo import CromoBotella
    from db.models.infra import Camara


def botella_cromo_por_n_id(n_id: int, session: Session) -> "CromoBotella | None":
    """`CromoBotella` por `n_id`, sólo si es vigente y está vinculada a una Cámara. Compartida con la
    búsqueda por ID explícito de `core/services/cromo/camara_botella_busqueda.py`."""
    from db.models.cromo import CromoBotella

    botella = session.get(CromoBotella, n_id)
    if botella is None or botella.camara_id is None or not botella.vigente:
        return None
    return botella


# Umbral de `SequenceMatcher` entre el resto del texto y el nombre de la Botella. Medido en la
# revisión (2026-10-23) contra todos los `n_id` de dev con un dígito mal tipeado o dos transpuestos
# que existen y son de OTRA cámara: con sólo "comparte una palabra o un número" el 4,6% de esos
# typos resolvía a la cámara equivocada; con números contenidos + ratio ≥ 0,8, el 0,09%. Los 6
# prefijos reales de prod dan ratio 1,0.
_UMBRAL_CORROBORACION = 0.8


def _para_corroborar(texto: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", normalizar_candidato(texto))).strip()


def resto_corrobora_botella(botella: "CromoBotella", resto: str) -> bool:
    """El texto que acompaña a un ID explícito describe a ESA Botella: vacío, o todos sus números
    de 2+ dígitos están en el nombre y el parecido (`SequenceMatcher`) es ≥ 0,8. Un ID mal tipeado
    que exista no puede resolver a una cámara que el resto del texto no describe (revisiones del
    2026-09-28 y 2026-10-23)."""
    resto_norm = _para_corroborar(resto or "")
    if not resto_norm:
        return True
    nombre_norm = _para_corroborar(botella.nombre or "")
    if not set(re.findall(r"\d{2,}", resto_norm)) <= set(re.findall(r"\d{2,}", nombre_norm)):
        return False
    return SequenceMatcher(None, resto_norm, nombre_norm).ratio() >= _UMBRAL_CORROBORACION


def camara_por_prefijo_empalme(texto: str, session: Session) -> tuple["CromoBotella | None", str]:
    """Resuelve el prefijo "Empalme <n_id>" por `n_id` de Cromo. Devuelve ``(botella, resto)``: la
    Botella si el `n_id` existe, es vigente, tiene Cámara y el resto del texto la corrobora; si no,
    ``(None, resto)`` — el texto SIN el prefijo, para seguir la búsqueda por nombre sin exigir ese
    número. Sin prefijo, ``(None, texto)``."""
    n_id, resto = separar_prefijo_empalme(texto)
    if n_id is None:
        return None, texto
    botella = botella_cromo_por_n_id(n_id, session)
    if botella is not None and resto_corrobora_botella(botella, resto):
        return botella, resto
    return None, resto


class AmbiguousSearchError(Exception):
    """Se lanza cuando la búsqueda de cámara no puede identificar una entidad unívoca.

    Cubre dos casos:

    * **Nombre insuficiente** (``cantidad == 0``): el string tiene menos de 2
      tokens significativos y ningún número; es imposible hacer una búsqueda
      precisa sin consultar la DB.
    * **Múltiples candidatos** (``cantidad > 1``): la cascada de búsqueda nunca
      redujo los resultados a exactamente una cámara.

    Attributes:
        nombre_raw:  Nombre original ingresado por el técnico.
        cantidad:    Número de candidatos encontrados (0 si el nombre es insuficiente).
        candidatos:  Lista de nombres de cámaras candidatas (hasta 3 — decisión de producto
                     2026-08-23: máximo 3 sugerencias en cualquier mensaje que use esta excepción).
    """

    def __init__(self, nombre_raw: str, cantidad: int, candidatos: list[str]) -> None:
        self.nombre_raw = nombre_raw
        self.cantidad = cantidad
        self.candidatos = candidatos[:3]
        super().__init__(
            f"Búsqueda ambigua: '{nombre_raw}' devuelve {cantidad} candidatos"
        )


class NumeroNoCoincideError(AmbiguousSearchError):
    """El texto trae números y ninguna cámara los tiene, pero sin esos números sí hay parecidas.

    Caso típico: el técnico escribió mal la altura ("Cra Mitre 404" para "Cra Mitre 440"). Las
    candidatas son SÓLO sugerencias — nunca se asigna automáticamente una cámara parecida (decisión
    del usuario 2026-10-23: "son pocos casos pero hay"). Es subclase de `AmbiguousSearchError` a
    propósito: todo caller que hoy trata la ambigüedad como "no se puede resolver" (revalidación,
    corrección, reproceso, baneo masivo) la sigue tratando igual sin cambios; sólo el listener la
    captura antes para responder "No encontré X con ese número. ¿Quisiste decir…?".

    ``cantidad`` es la cantidad de parecidas encontradas; ``candidatos`` las hasta 3 más similares.
    """


def buscar_camara(
    nombre_raw: str, session: Session, *, desempatar: bool = True
) -> tuple["Camara | None", str]:
    """Busca una cámara, intentando primero sólo con el texto antes del primer guión.

    Cuando el técnico pega en el Workflow el título completo que muestra Cromo para una Cámara/
    Botella (``<Nombre> - <Calle> <Altura> - <Localidad> - <Provincia>``, ver
    `docs/decisiones.md` entrada 2026-09-07, caso real "Cra Curupayti 2951 CF - CURUPAYTI 2964 -
    Capital Federal - Capital Federal"), todo lo posterior al primer guión son atributos de Cromo,
    no parte del nombre real. Por eso el primer intento usa sólo el prefijo antes del guión; si eso
    no resuelve a una única cámara (ni matchea, ni es ambiguo), se reintenta con el string completo
    — esto preserva casos donde el sufijo SÍ es parte legítima del nombre real y necesaria para
    desambiguar (ej. "Poste Lavalle - Campana", ver `TestLimpiarRuidoOperativo
    .test_localidad_con_guion_se_preserva`).

    Antes que nada (2026-10-23), el prefijo "Empalme <n_id de 8 dígitos>:" se resuelve por `n_id`
    de Cromo (`camara_por_prefijo_empalme`): si la Botella existe y tiene Cámara, es match directo;
    si no, se quita el prefijo y su número no cuenta como requerido.
    """
    botella, nombre_raw = camara_por_prefijo_empalme(nombre_raw, session)
    if botella is not None:
        return botella.camara, aplicar_sinonimos(
            normalizar(expandir_abreviaturas(limpiar_puntuacion(nombre_raw)))
        )
    nombre_raw = preparar_nombre_busqueda(nombre_raw)
    if "-" in nombre_raw:
        prefijo = nombre_raw.split("-", 1)[0].strip()
        if prefijo and prefijo != nombre_raw.strip() and not recorte_pierde_la_botella(prefijo, nombre_raw):
            try:
                # Sin desempate por coincidencia exacta: el prefijo es un RECORTE, y que una
                # candidata coincida exacto con el recorte no prueba nada ("terraza Viamonte 898-
                # Piso 4 C.F." terminaba en "terraza Viamonte 898" — medido 2026-09-28).
                camara, nombre_norm = _buscar_camara_intento(prefijo, session, desempate_exacto=False)
            except AmbiguousSearchError:
                pass  # el prefijo solo no alcanza — cae al intento con el string completo
            else:
                if camara is not None:
                    return camara, nombre_norm
    return _buscar_camara_intento(nombre_raw, session, desempate_exacto=desempatar)


class _CascadaBusqueda:
    """Estado de una corrida de `_buscar_camara_intento`: restricciones del input y grupo ambiguo.

    Conserva el grupo más acotado (menos candidatos) que ningún intento pudo reducir a una sola.
    """

    def __init__(
        self, nombre_raw: str, session: Session, nombre_norm: str, desempate_exacto: bool
    ) -> None:
        self.nombre_raw = nombre_raw
        self.session = session
        self.nombre_norm = nombre_norm
        self.desempate_exacto = desempate_exacto
        # Números requeridos: si el input tiene "440", solo aceptamos cámaras con "440"
        self.numeros_requeridos: set[str] = set(re.findall(r"\d+", nombre_norm))
        # Bot/Botella: si el técnico lo menciona explícitamente, permitimos bots secundarios
        self.tiene_bot: bool = bool(re.search(r"\bbot(ella)?\b", nombre_raw, re.IGNORECASE))
        self.ambiguos: list["Camara"] = []

    def _filtrar(self, candidatos: list["Camara"]) -> list["Camara"]:
        candidatos = filtrar_por_numeros(candidatos, self.numeros_requeridos)
        candidatos = filtrar_bots_secundarios(candidatos, self.tiene_bot)
        return filtrar_numero_de_botella(candidatos, self.nombre_raw)

    def candidatos_ilike(self, patron: str) -> list["Camara"]:
        return self._filtrar(_buscar_ilike_lista(patron, self.session))

    def candidatos_tokens(self, tokens: list[str]) -> list["Camara"]:
        return self._filtrar(_buscar_tokens_lista(tokens, self.session))

    def _desempatar_por_exacta(self, candidatos: list["Camara"]) -> "Camara | None":
        # Desempate (2026-09-28): si exactamente UNA candidata coincide por igualdad con la
        # entrada normalizada, es ésa — "Cra Libertad 991 CF" contra "BOTELLA CRITICA Cra
        # Libertad 991 CF". Dos o más exactas (duplicados reales del inventario, "X C.F." y
        # "X CF") siguen siendo ambiguas: nunca se elige entre dos Cámaras distintas.
        if not self.desempate_exacto or tiene_gemela_critica(candidatos):
            return None
        exactas = [c for c in candidatos if normalizar_candidato(c.nombre) == self.nombre_norm]
        return exactas[0] if len(exactas) == 1 else None

    def evaluar(self, candidatos: list["Camara"]) -> "Camara | None":
        if len(candidatos) == 1:
            return candidatos[0]
        if len(candidatos) > 1:
            elegida = self._desempatar_por_exacta(candidatos)
            if elegida is not None:
                return elegida
            if not self.ambiguos or len(candidatos) < len(self.ambiguos):
                self.ambiguos = candidatos
        return None

    def probar(self, patron: str) -> "Camara | None":
        """ILIKE con `patron` y, si hay 2+ tokens significativos, todos los tokens (AND)."""
        resultado = self.evaluar(self.candidatos_ilike(patron))
        if resultado:
            return resultado
        tokens = tokens_significativos(patron)
        if len(tokens) >= 2:
            return self.evaluar(self.candidatos_tokens(tokens)) or None
        return None


# Tipo de elemento y descriptores que, solos, no identifican una calle: si al quitar los números
# del texto sólo quedan éstos ("Cra 440" → "cra"), no se buscan parecidas — serían miles.
_TOKENS_GENERICOS = frozenset({"cra", "bot", "poste", "tza", "calle", "avenida", "pasaje", "esq"})


def _parecidas_sin_numeros(cascada: _CascadaBusqueda) -> list["Camara"]:
    """Cámaras que coinciden con el texto SIN sus números (reemplaza al viejo Intento 3, que era
    inalcanzable: sólo corría cuando el texto no tenía números, y entonces no había nada que quitar).

    Sólo para un texto CON números al que los intentos 1, 2 y 4 no le encontraron nada. Se busca por
    tokens (AND ILIKE) sobre la forma expandida y la literal, con los mismos filtros de bot y de
    número de botella que la cascada — pero sin el de números, que es justamente el que no coincide.
    Si sin los números quedan menos de 2 tokens significativos, o sólo tokens genéricos ("cra",
    "calle"), no se busca nada. Devuelve las candidatas ordenadas de más a menos parecidas al texto;
    NUNCA se usan como match (ver `NumeroNoCoincideError`)."""
    literal = aplicar_sinonimos(normalizar(limpiar_puntuacion(cascada.nombre_raw)))
    vistas: dict[int, "Camara"] = {}
    for texto in dict.fromkeys((cascada.nombre_norm, literal)):
        sin_numeros = re.sub(r"\s+", " ", re.sub(r"\d+", " ", texto)).strip()
        tokens = tokens_significativos(sin_numeros)
        if len(tokens) < 2 or set(tokens) <= _TOKENS_GENERICOS:
            continue
        candidatas = _buscar_tokens_lista(tokens, cascada.session)
        candidatas = filtrar_bots_secundarios(candidatas, cascada.tiene_bot)
        for camara in filtrar_numero_de_botella(candidatas, cascada.nombre_raw):
            vistas.setdefault(camara.id, camara)

    def _similitud(camara: "Camara") -> float:
        return SequenceMatcher(None, cascada.nombre_norm, normalizar_candidato(camara.nombre)).ratio()

    return sorted(vistas.values(), key=lambda c: (-_similitud(c), len(c.nombre or ""), c.id))


def _intento_sin_expansion(cascada: _CascadaBusqueda) -> tuple["Camara | None", str]:
    """Intento 4: nombre raw normalizado SIN expansión de abreviaturas.

    Cubre el caso en que la DB almacena el nombre con abreviaturas literales.
    """
    nombre_raw_norm = aplicar_sinonimos(normalizar(limpiar_puntuacion(cascada.nombre_raw)))
    if nombre_raw_norm != cascada.nombre_norm:
        return cascada.probar(nombre_raw_norm), nombre_raw_norm
    return None, nombre_raw_norm


def _buscar_camara_intento(
    nombre_raw: str, session: Session, *, desempate_exacto: bool = True
) -> tuple["Camara | None", str]:
    """Busca una cámara en DB tolerando abreviaturas, sinónimos y variaciones ortográficas.

    Preprocesamiento:
      - Limpieza de puntuación (comas, puntos, guiones separadores)
      - Expansión de abreviaturas viales (av→avenida, clle→calle, etc.)
      - Normalización (unidecode + lowercase)
      - Aplicación de sinónimos (botella→bot, camara→cra)

    Regla de numeración:
      Si el input contiene números, solo se aceptan cámaras cuyo nombre los
      contenga exactamente (como palabras completas). Una cámara con otro número
      nunca es match (ej: 440 ≠ 399): a lo sumo es una sugerencia (Intento 3).

    Regla de Botella/Bot:
      Si el input NO menciona explícitamente "bot" o "botella", se excluyen
      resultados de cámaras secundarias tipo "Bot 2", "Bot 3", etc.

    Estrategia en cascada:
      1. ILIKE '%nombre_norm%' en Camara.nombre y CamaraAlias.alias_nombre
      2. Todos los tokens (≥3 chars) presentes — AND ILIKE
      4. Fallback con nombre raw normalizado SIN expansión (para abreviaturas
         almacenadas literalmente en DB, p.ej. "Cra")
      3. Se evalúa al final, después del 4 (desde 2026-10-23): si el input
         TIENE números y ningún intento encontró nada —ni siquiera un grupo
         ambiguo—, se buscan parecidas sin esos números
         (`_parecidas_sin_numeros`). Si hay, se lanza ``NumeroNoCoincideError``
         con hasta 3 sugerencias; nunca se asigna una.

    Filtro de ambigüedad:
      - Heurística previa: si hay < 2 tokens significativos (≥3 chars) y ningún
        número, se lanza ``AmbiguousSearchError(cantidad=0)`` sin consultar la DB.
      - Si algún intento de la cascada devuelve múltiples candidatos (tras los
        filtros de números y bots) y ningún intento posterior los reduce a 1,
        se lanza ``AmbiguousSearchError`` con el grupo más acotado encontrado.

    Args:
        nombre_raw: Nombre extraído del mensaje (sin normalizar).
        session:    Sesión SQLAlchemy activa.

    Returns:
        Tupla ``(camara, nombre_normalizado_usado)`` cuando se identifica
        exactamente una cámara, o ``(None, nombre_norm)`` cuando no se encontró
        ninguna (flujo de auto-registro).

    Raises:
        AmbiguousSearchError: Cuando el nombre es ambiguo o insuficientemente
            específico para identificar una cámara de forma unívoca.
        NumeroNoCoincideError: (subclase) Cuando el número del input no coincide
            con ninguna cámara pero sin él hay parecidas (sólo sugerencias).
    """
    # ── Pre-proceso ──────────────────────────────────────────────────────
    nombre_limpio = limpiar_puntuacion(nombre_raw)
    nombre_expandido = expandir_abreviaturas(nombre_limpio)
    nombre_norm = aplicar_sinonimos(normalizar(nombre_expandido))
    cascada = _CascadaBusqueda(nombre_raw, session, nombre_norm, desempate_exacto)

    # ── Heurística pre-búsqueda: nombre insuficientemente específico ──────
    if len(tokens_significativos(nombre_norm)) < 2 and not cascada.numeros_requeridos:
        raise AmbiguousSearchError(nombre_raw, 0, [])

    # ── Intentos 1 y 2: nombre normalizado completo y todos sus tokens ───
    resultado = cascada.probar(nombre_norm)
    if resultado:
        return resultado, nombre_norm
    # ── Intento 4 (sin expansión) ────────────────────────────────────────
    resultado, nombre_usado = _intento_sin_expansion(cascada)
    if resultado:
        return resultado, nombre_usado

    # ── Resolución final: múltiples candidatos sin reducir a 1 → ambiguo ─
    if cascada.ambiguos:
        nombres_candidatos = [c.nombre for c in cascada.ambiguos[:3]]
        raise AmbiguousSearchError(nombre_raw, len(cascada.ambiguos), nombres_candidatos)

    # ── Intento 3: el número no coincide con ninguna → sólo sugerencias ──
    if cascada.numeros_requeridos:
        parecidas = _parecidas_sin_numeros(cascada)
        if parecidas:
            raise NumeroNoCoincideError(nombre_raw, len(parecidas), [c.nombre for c in parecidas[:3]])
    return None, nombre_norm


def filtrar_por_numeros(
    candidatos: list["Camara"], numeros_requeridos: set[str]
) -> list["Camara"]:
    """Descarta candidatos cuyo nombre no contenga todos los números requeridos.

    Usa coincidencia de número completo (``(?<!\\d)<n>(?!\\d)``) sobre el nombre
    normalizado.  Si ``numeros_requeridos`` está vacío, retorna la lista sin
    cambios.
    """
    if not numeros_requeridos:
        return candidatos
    resultado: list["Camara"] = []
    for cam in candidatos:
        nombre_norm = normalizar(cam.nombre or "")
        if all(_contiene_numero(nombre_norm, n) for n in numeros_requeridos):
            resultado.append(cam)
    return resultado


def _contiene_numero(nombre_norm: str, numero: str) -> bool:
    """`numero` aparece en `nombre_norm` como número completo.

    Desde 2026-09-28, sin `\b` a la izquierda para números de 3+ dígitos: con `\b`, "197" nunca
    matcheaba "(R197)" ni "99" matcheaba "99B", y el nombre EXACTO del inventario se descartaba a sí
    mismo. Un número corto (1-2 dígitos) sí exige que no lo preceda una letra —salvo "bot"— porque ahí
    la letra delante casi siempre es otro dato: el "2" de "Bot 2" no puede satisfacerse con el "P2"
    (piso) de otra cámara (hallazgo de la revisión de la rama, caso real "Bot 2 Interiror Parana 3745
    P2 - Unicenter"). Nunca acepta "440" dentro de "4400"."""
    for m in re.finditer(rf"(?<!\d){re.escape(numero)}(?!\d)", nombre_norm):
        if len(numero) >= 3:
            return True
        previo = nombre_norm[: m.start()]
        if not previo or not previo[-1].isalpha() or re.search(r"bot\.?$", previo):
            return True
    return False



def filtrar_numero_de_botella(candidatos: list["Camara"], nombre_raw: str) -> list["Camara"]:
    """Si el texto nombra una botella secundaria concreta ("Bot 2"), la candidata tiene que tener
    ESA botella — no alcanza con que el número aparezca en otra parte del nombre ("Ed 2", "Piso 2").

    Hallazgo de la revisión de la rama (2026-09-28): "Avalos 2829 Bot2 - Sala telefonia Ed 2 Subs"
    resolvía a "Bot. Avalos 2829 - Sala telefonia Ed 2 Subs VICE" (una botella sin número, de otra
    cámara) porque el "2" requerido lo aportaba "Ed 2". "Bot 1" no restringe: es la Cámara principal,
    cuyo nombre no lo lleva."""
    pedidos = {n for n in RE_NUMERO_BOTELLA.findall(nombre_raw or "") if n != "1"}
    if not pedidos:
        return candidatos
    return [c for c in candidatos if pedidos <= set(RE_NUMERO_BOTELLA.findall(c.nombre or ""))]


_RE_CRITICA = re.compile(r"(?i)cr[ií]tic")


def recorte_pierde_la_botella(prefijo: str, nombre_completo: str) -> bool:
    """True si el texto completo nombra una botella secundaria ("… - Bot 2") que el recorte antes
    del guion ya no incluye. Ese recorte describe OTRA cosa (la cámara, no la botella pedida) y no
    se prueba: en la revisión de la rama, "Cra Av Peron 7964 esq. Jose Maria Paz - Bot 2" resolvía
    por el recorte a otra cámara."""
    pedidos = {n for n in RE_NUMERO_BOTELLA.findall(nombre_completo or "") if n != "1"}
    return bool(pedidos) and not pedidos <= set(RE_NUMERO_BOTELLA.findall(prefijo or ""))


def tiene_gemela_critica(candidatos: list) -> bool:
    """True si alguna candidata es una variante "CRITICA" ("X - CRITICA", "BOTELLA CRITICA X").

    El listener quita el sufijo " - CRITICA" del texto ANTES de buscar (`limpiar_ruido_operativo`),
    así que la búsqueda no puede saber si el técnico pidió la crítica o la común: con una gemela
    crítica entre las candidatas, ningún desempate elige (hallazgo de la revisión de la rama: "Cra
    Diag Norte 902 Esq Suipacha - CRITICA" terminaba en la común, que además estaba BANEADA)."""
    return any(_RE_CRITICA.search(getattr(c, "nombre", None) or "") for c in candidatos)


def filtrar_bots_secundarios(
    candidatos: list["Camara"], tiene_bot: bool
) -> list["Camara"]:
    """Si el usuario NO mencionó 'bot'/'botella', excluye cámaras tipo 'Bot 2', 'Bot 3', etc.

    Esto evita que "Cra Mitre 440" empareje "Bot 2 Cra Mitre 440" cuando el
    técnico claramente se refiere a la cámara principal.
    """
    if tiene_bot:
        return candidatos
    return [c for c in candidatos if not RE_BOT_SUFIJO.search(c.nombre or "")]


def _buscar_ilike_lista(patron: str, session: Session) -> list["Camara"]:
    """Query ILIKE '%patron%' sobre Camara.nombre y CamaraAlias.alias_nombre.

    Retorna lista de candidatos sin filtrar, deduplicada por id.
    """
    from db.models.infra import Camara, CamaraAlias

    # Búsqueda en nombre directo
    por_nombre = (
        session.query(Camara)
        .filter(func.unaccent(func.lower(Camara.nombre)).ilike(f"%{patron}%"))
        .all()
    )
    # Búsqueda en aliases (JOIN)
    por_alias = (
        session.query(Camara)
        .join(CamaraAlias, CamaraAlias.camara_id == Camara.id)
        .filter(func.unaccent(func.lower(CamaraAlias.alias_nombre)).ilike(f"%{patron}%"))
        .all()
    )
    # Deduplicar preservando orden
    seen: set[int] = set()
    result: list["Camara"] = []
    for c in por_nombre + por_alias:
        if c.id not in seen:
            seen.add(c.id)
            result.append(c)
    return result


def _buscar_tokens_lista(tokens: list[str], session: Session) -> list["Camara"]:
    """Busca cámaras cuyo nombre o algún alias contenga TODOS los tokens.

    Retorna lista de candidatos sin filtrar, deduplicada por id.
    """
    from db.models.infra import Camara, CamaraAlias
    from sqlalchemy import and_

    # En nombre directo
    condiciones_nombre = [
        func.unaccent(func.lower(Camara.nombre)).ilike(f"%{token}%")
        for token in tokens
    ]
    por_nombre = session.query(Camara).filter(and_(*condiciones_nombre)).all()

    # En aliases
    condiciones_alias = [
        func.unaccent(func.lower(CamaraAlias.alias_nombre)).ilike(f"%{token}%")
        for token in tokens
    ]
    por_alias = (
        session.query(Camara)
        .join(CamaraAlias, CamaraAlias.camara_id == Camara.id)
        .filter(and_(*condiciones_alias))
        .all()
    )
    # Deduplicar preservando orden
    seen: set[int] = set()
    result: list["Camara"] = []
    for c in por_nombre + por_alias:
        if c.id not in seen:
            seen.add(c.id)
            result.append(c)
    return result


def _buscar_ilike(patron: str, session: Session) -> "Camara | None":
    """Wrapper de _buscar_ilike_lista que aplica _mejor_candidato.

    Mantenido para compatibilidad con tests que parchean esta función.
    """
    return _mejor_candidato(_buscar_ilike_lista(patron, session))


def _buscar_tokens(tokens: list[str], session: Session) -> "Camara | None":
    """Wrapper de _buscar_tokens_lista que aplica _mejor_candidato.

    Mantenido para compatibilidad con tests que parchean esta función.
    """
    return _mejor_candidato(_buscar_tokens_lista(tokens, session))


def _mejor_candidato(candidatos: list["Camara"]) -> "Camara | None":
    """De una lista de candidatos retorna el de nombre más corto (mejor match)."""
    if not candidatos:
        return None
    return min(candidatos, key=lambda c: len(c.nombre))
