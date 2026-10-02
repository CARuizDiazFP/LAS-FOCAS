# Nombre de archivo: cable_info.py
# Ubicación de archivo: modules/slack_baneo_notifier/cable_info.py
# Descripción: Parser y consulta de los comandos "Info cable"/"Verificar cable"/"Servicios" (con o sin buffer) para el handler app_mention del listener de Slack

"""Comandos de la app de Slack de verificación de Cables (docs/slack_app_cables.md):
- `@bot Info cable <nombre>` — información básica del Cable (capacidad, propietario, jerarquía,
  Botellas de sus extremos).
- `@bot Verificar cable <nombre> B<N>` — servicios matcheados en un buffer puntual del cable, **por
  pelo** (una línea por pelo — varios pelos por servicio es normal, es el dato físico correcto).
- `@bot Info cable <nombre> B<N>` — listado completo de pelos de ese buffer (matcheados o no, con
  la descripción cruda si el pelo no está libre pero tampoco se identificó cliente/cable). Desde la
  Task 8 (plan "Corrección ingresos + Servicios", 2026-09-23) marca con `🕒` los pelos cuyo servicio
  matcheado tiene la sincronización PROV vencida (`core/services/prov/frescura.py`).
- `@bot Servicios [C<N>] <cable> [VER|NOVER]` / `@bot Servicios [C<N>] <cable> B<N> [VER|NOVER]`
  (Task 8 del mismo plan; filtros opcionales por categoría C1-C6 y por verificable desde 2026-09-28) — IDs de servicio
  **únicos** (agregados por `s.id`, no uno por pelo) agrupados por buffer, con marca de frescura
  PROV. Complementa a "Verificar cable X BN", no lo reemplaza: el 18,9% de los pares (pelo, servicio)
  medido real contra `lasfocasdev-postgres` tiene un número distinto escrito en la descripción del
  pelo vs. el `servicio_id` vigente — este comando lo señala explícitamente en vez de dejar que el
  técnico confíe en la etiqueta física.

El "código de cable" que el técnico escribe (ej. real "F-VFL-IND") es directamente
`cromo_cables.nombre` — verificado 2026-08-13 contra `lasfocasdev-postgres` (no un código externo en
otro sistema, no `id_legacy`). `nombre` es casi siempre único, pero NO es una lista cerrada de un solo
caso: hay al menos 2 pares duplicados reales conocidos ("F-ALV-2335", visto 2026-08-13; "F-LEM-11-A",
visto 2026-08-25) sobre ~32.782 cables — se resuelve con match exacto case-insensitive; ante 0 o 2+
resultados se responde pidiendo precisión en vez de adivinar (`buscar_cable_por_n_id_o_nombre`
también acepta el n_id sugerido en esa respuesta, ver más abajo).

El "B<N>" de buffer (confirmado con el usuario 2026-08-13, no inferido): el técnico cuenta los
buffers desde 1 ("B1" es el primer buffer físico) — mapea a `cromo_tubos.orden = N - 1` (la columna
arranca en 0 en los datos reales). Los buffers en Cromo se identifican también por color
(`cromo_tubos.nombre_color`, ej. "AZ"/"NR"/"VR") pero el técnico referencia por número, no por color.

Consulta síncrona (`Session`, no `AsyncSession`): el listener corre dentro de un handler de Slack
Bolt síncrono (mismo patrón que el resto de `modules/slack_baneo_notifier/`), y los modelos ORM de
Cromo son comunes a cualquiera de las dos sesiones — no hace falta puentear a asyncio para esto. Los
servicios `core/services/cromo/verificador.py`/`detalle.py` (pensados para `AsyncSession`) exponen
gemelas síncronas (`servicios_por_tubo_sync`, `pelos_de_tubo_sync`) reusando exactamente las mismas
queries SQL, en vez de duplicar lógica de negocio acá.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from core.services.cromo.detalle import PeloDetalle, pelos_de_tubo_sync
from core.services.cromo.parser import extraer_tipo_servicio_display
from core.services.cromo.verificador import (
    ResultadoServiciosUnicos,
    ResultadoTubo,
    ServicioUnico,
    servicios_por_tubo_sync,
)
from db.models.cromo import CromoBotella, CromoCable, CromoTubo

# "Info cable <nombre>", case-insensitive, tolera "Info Cable"/"info cable". El resto de la línea
# (recortado) es el nombre del cable. `_RE_CABLE_BUFFER` (más abajo) se intenta SIEMPRE primero en el
# listener — este regex es deliberadamente "goloso" (`.+` hasta el final) y matchearía de más si un
# mensaje con sufijo "B<N>" llegara acá primero (lo tomaría como parte del nombre del cable).
_RE_INFO_CABLE = re.compile(r"(?i)\binfo\s+cable\s+(.+)$")

# "Verificar cable <nombre> B<N>" / "Info cable <nombre> B<N>" — `.+?` no-goloso para que el nombre
# del cable no se coma el sufijo "B<N>"/"Buffer <N>" del final. Tolera "B1", "B 1", "Buffer 1".
_RE_CABLE_BUFFER = re.compile(r"(?i)^(verificar|info)\s+cable\s+(.+?)\s+(?:b|buffer)\s*(\d+)$")

# Slack no renderiza mrkdwn antes de mandarnos el evento — negrita/cursiva/código/tachado
# (*texto*, _texto_, `texto`, ~texto~) llegan con los caracteres literales en `event["text"]`. Bug
# real 2026-08-25 (reproducido con el payload crudo real del canal #baneo-de-camaras-prueba): un
# técnico que resalta el código en negrita (uso normal de Slack, ej. "info cable *F-VDP-JUR*") hacía
# que el match exacto contra `cromo_cables.nombre` fallara siempre (buscaba "*F-VDP-JUR*" literal) y
# además rompía `_RE_CABLE_BUFFER` (el "*" final no encaja en el ancla `$`, caía a este regex goloso
# y se comía "B1*"/"*" como si fueran parte del nombre). Se quitan globalmente antes de matchear
# cualquiera de los dos regex — ningún código de cable real usa estos 4 caracteres.
#
# Público (promovido 2026-09-23, Task 4 del plan de corrección de ingresos/servicios): el mismo bug
# aplica igual a "Forzar ingreso"/"Forzar egreso" (`modules/slack_baneo_notifier/correccion_ingreso.py`)
# — un técnico escribe "Forzar egreso *Cra Balcarce 302*" igual que escribía "info cable *F-VDP-JUR*".
# Verificado (grep) que no tenía otros usos antes de renombrar: sólo los dos call-sites de este mismo
# archivo.
_RE_FORMATO_SLACK = re.compile(r"[*_`~]")


def quitar_formato_slack(texto: str) -> str:
    return _RE_FORMATO_SLACK.sub("", texto)


def extraer_comando_info_cable(texto: str) -> Optional[str]:
    """Extrae el nombre de cable de un texto tipo "Info cable F-VFL-IND". Devuelve `None` si el
    texto no matchea el comando (no es un error — puede ser una mención sin relación a este comando)."""
    texto_normalizado = quitar_formato_slack(re.sub(r"\s+", " ", texto).strip())
    match = _RE_INFO_CABLE.search(texto_normalizado)
    if not match:
        return None
    nombre = match.group(1).strip().strip(".,;:!?")
    return nombre or None


def buscar_cable_por_nombre(session: Session, nombre: str) -> list[CromoCable]:
    """Match exacto case-insensitive contra `cromo_cables.nombre` (vigentes) — no `ILIKE` parcial:
    es un código puntual que el técnico copia de una etiqueta física, no un término de búsqueda
    libre. Devuelve una lista para que el caller distinga 0 (no encontrado) de 2+ (el único
    duplicado real conocido, "F-ALV-2335")."""
    return (
        session.query(CromoCable)
        .filter(CromoCable.vigente.is_(True), func.lower(CromoCable.nombre) == nombre.lower())
        .all()
    )


def buscar_cable_por_n_id_o_nombre(session: Session, texto: str) -> list[CromoCable]:
    """Resuelve un cable por n_id si `texto` es puramente numérico; si no, cae a
    `buscar_cable_por_nombre`. Bug real (2026-08-25): `construir_respuesta_ambiguo` le pide al
    técnico "especificá por n_id", pero `buscar_cable_por_nombre` sólo busca por `nombre` — un
    reintento con el n_id sugerido (ej. "info cable 10260935 B6") no matcheaba ningún cable (ninguno
    se llama literalmente "10260935") y el bot respondía "no encontré el cable" aunque sí existe.
    Verificado contra `lasfocasdev-postgres`: "F-LEM-11-A" tiene 2 cables vigentes reales (n_id
    10260935 y 9498169). Único punto de cambio: `listener._resolver_cable_o_responder` llama a esta
    función en vez de `buscar_cable_por_nombre` directamente, así que arregla los 3 comandos que la
    comparten ("Info cable", "Verificar cable X BN", "Info cable X BN")."""
    texto_limpio = texto.strip()
    if texto_limpio.isdigit():
        cable = (
            session.query(CromoCable)
            .filter(CromoCable.vigente.is_(True), CromoCable.n_id == int(texto_limpio))
            .first()
        )
        return [cable] if cable else []
    return buscar_cable_por_nombre(session, texto)


def _resolver_nombre_extremo(session: Session, n_id: Optional[int], nombre_crudo: Optional[str]) -> Optional[str]:
    """Nombre real de la Botella en un extremo del cable. `cromo_cables.extremo_a_nombre`/
    `extremo_b_nombre` son crudos y no confiables (`at.37` nunca llega desde Cromo — a veces vienen
    concatenados con el extremo A, a veces vacíos, ver Etapa 9c en docs/modulo_ingesta_cromo.md) —
    se resuelve el nombre real vía `cromo_botellas.nombre` por `n_id`, con el crudo como único
    fallback si la Botella todavía no bajó a la tabla."""
    if n_id is not None:
        real = session.query(CromoBotella.nombre).filter(CromoBotella.n_id == n_id).scalar()
        if real:
            return real
    return nombre_crudo or None


def construir_respuesta_info_cable(cable: CromoCable, session: Session) -> str:
    """Arma el texto de respuesta con la info básica del cable — capacidad, propietario, jerarquía
    y el nombre real de la Botella en cada extremo."""
    extremo_a = _resolver_nombre_extremo(session, cable.extremo_a_n_id, cable.extremo_a_nombre)
    extremo_b = _resolver_nombre_extremo(session, cable.extremo_b_n_id, cable.extremo_b_nombre)

    lineas = [
        f"📡 Cable *{cable.nombre}* (n_id {cable.n_id})",
        f"• Capacidad: {cable.capacidad or '—'}",
        f"• Propietario: {cable.propietario or '—'}",
        f"• Jerarquía: {cable.jerarquia or '—'}",
        f"• Extremo A: {extremo_a or '—'}",
        f"• Extremo B: {extremo_b or '—'}",
    ]
    return "\n".join(lineas)


def construir_respuesta_no_encontrado(nombre: str) -> str:
    return f":warning: No encontré ningún cable vigente con el código *{nombre}*."


def construir_respuesta_ambiguo(nombre: str, cables: list[CromoCable]) -> str:
    n_ids = ", ".join(str(c.n_id) for c in cables)
    return (
        f":warning: Encontré *{len(cables)}* cables con el código *{nombre}* — "
        f"especificá por n_id: {n_ids}."
    )


# ── "Verificar cable <nombre> B<N>" / "Info cable <nombre> B<N>" ────────────────────────────────


def extraer_comando_cable_buffer(texto: str) -> Optional[tuple[str, str, int]]:
    """Extrae (verbo, nombre_cable, numero_buffer) de "Verificar cable F-VFL-IND B1" o
    "Info cable F-VFL-IND B1". `verbo` normalizado a minúsculas ("verificar"|"info"). Devuelve
    `None` si el texto no matchea (no es un error — puede ser una mención sin relación)."""
    texto_normalizado = quitar_formato_slack(re.sub(r"\s+", " ", texto).strip())
    match = _RE_CABLE_BUFFER.match(texto_normalizado)
    if not match:
        return None
    verbo, nombre, numero = match.group(1).lower(), match.group(2).strip(), match.group(3)
    if not nombre:
        return None
    return verbo, nombre, int(numero)


# ── "Servicios <cable>" / "Servicios <cable> B<N>" (Task 8) ─────────────────────────────────────

# El de buffer se intenta SIEMPRE primero en el listener — misma precedencia y misma razón que
# `_RE_CABLE_BUFFER` vs. `_RE_INFO_CABLE`: `_RE_SERVICIOS_CABLE` es "goloso" (`.+` hasta el final) y
# se comería el sufijo "B<N>" como si fuera parte del nombre si se probara antes. Verbo "servicios"
# libre: ni `_RE_INFO_CABLE` (exige "info cable") ni `_RE_CABLE_BUFFER` (exige "(verificar|info)
# cable") matchean un texto que empieza con "servicios".
_RE_SERVICIOS_BUFFER = re.compile(r"(?i)^servicios\s+(?:cable\s+)?(.+?)\s+(?:b|buffer)\s*(\d+)$")
_RE_SERVICIOS_CABLE = re.compile(r"(?i)^servicios\s+(?:cable\s+)?(.+)$")

# Filtros opcionales (2026-09-28): "Servicios [C<N>] <cable> [B<N>] [VER|NOVER]". Cada token se
# separa ANTES de los dos parsers de arriba (`extraer_filtro_categoria`/`extraer_filtro_verificable`),
# así éstos siguen viendo la forma sin filtro y no cambian de contrato.
# - Categoría: pegada al verbo. Exige algo después para que "Servicios C1" a secas siga siendo un
#   cable llamado "C1".
# - Verificable: al final, después del buffer. Exige algo entre el verbo y el token para que
#   "Servicios VER" a secas siga siendo un cable llamado "VER". Tolera "NO VER"/"NO-VER".
_RE_FILTRO_CATEGORIA = re.compile(r"(?i)^(servicios)\s+c(\d+)\s+(.+)$")
_RE_FILTRO_VERIFICABLE = re.compile(r"(?i)^(servicios\s+.+?)\s+(ver|no\s*-?\s*ver)$")
CATEGORIAS_FILTRABLES = range(1, 7)  # C1-C6; C0 es el placeholder sintetizado por Cromo, no se filtra


def extraer_filtro_categoria(texto: str) -> tuple[Optional[int], str]:
    """Separa el filtro "C<N>" de "Servicios C<N> <cable>[ B<N>]". Devuelve (categoria, resto) con
    `resto` = "Servicios <cable>[ B<N>]", listo para `extraer_comando_servicios_buffer`/`_cable`.
    Sin filtro devuelve `(None, texto)` intacto. Una categoría fuera de `CATEGORIAS_FILTRABLES` se
    devuelve igual — el caller decide avisar en vez de buscar un cable llamado "C7 <cable>"."""
    texto_normalizado = quitar_formato_slack(re.sub(r"\s+", " ", texto).strip())
    match = _RE_FILTRO_CATEGORIA.match(texto_normalizado)
    if not match:
        return None, texto
    return int(match.group(2)), f"{match.group(1)} {match.group(3)}"


def extraer_filtro_verificable(texto: str) -> tuple[Optional[bool], str]:
    """Separa el sufijo "VER"/"NOVER" de "Servicios ... VER|NOVER". Devuelve (verificable, resto):
    `True` = sólo verificables, `False` = sólo no verificables. Sin filtro devuelve `(None, texto)`
    intacto. Se aplica después de `extraer_filtro_categoria` (el orden entre los dos no importa:
    uno mira el comienzo y el otro el final)."""
    texto_normalizado = quitar_formato_slack(re.sub(r"\s+", " ", texto).strip())
    match = _RE_FILTRO_VERIFICABLE.match(texto_normalizado)
    if not match:
        return None, texto
    return match.group(2).lower() == "ver", match.group(1)


def filtrar_servicios(
    resultado: ResultadoServiciosUnicos,
    *,
    categoria: Optional[int] = None,
    verificable: Optional[bool] = None,
) -> ResultadoServiciosUnicos:
    """Filtro en memoria sobre la misma consulta de siempre — un cable real trae decenas de
    servicios (118 el más grande medido), no justifica una variante SQL por filtro. `None` en un
    criterio = no filtra por él."""
    if categoria is None and verificable is None:
        return resultado
    return replace(
        resultado,
        servicios=[
            s
            for s in resultado.servicios
            if (categoria is None or s.categoria == categoria)
            and (verificable is None or s.es_verificable is verificable)
        ],
    )


def construir_respuesta_categoria_invalida(categoria: int) -> str:
    return f":warning: Categoría *C{categoria}* inválida — el filtro acepta C1 a C6 (ej. `Servicios C6 F-GRN-598`)."


def extraer_comando_servicios_buffer(texto: str) -> Optional[tuple[str, int]]:
    """Extrae (nombre_cable, numero_buffer) de "Servicios F-VFL-IND B1" / "Servicios cable
    F-VFL-IND Buffer 1". Devuelve `None` si el texto no matchea (no es un error — puede ser una
    mención sin relación a este comando)."""
    texto_normalizado = quitar_formato_slack(re.sub(r"\s+", " ", texto).strip())
    match = _RE_SERVICIOS_BUFFER.match(texto_normalizado)
    if not match:
        return None
    nombre, numero = match.group(1).strip(), match.group(2)
    if not nombre:
        return None
    return nombre, int(numero)


def extraer_comando_servicios_cable(texto: str) -> Optional[str]:
    """Extrae el nombre de cable de "Servicios F-VFL-IND" / "Servicios cable F-VFL-IND" (sin
    sufijo de buffer). El listener prueba `extraer_comando_servicios_buffer` primero — este parser
    es deliberadamente goloso, igual que `extraer_comando_info_cable`."""
    texto_normalizado = quitar_formato_slack(re.sub(r"\s+", " ", texto).strip())
    match = _RE_SERVICIOS_CABLE.match(texto_normalizado)
    if not match:
        return None
    nombre = match.group(1).strip().strip(".,;:!?")
    return nombre or None


def resolver_tubo_por_numero(session: Session, cable_n_id: int, numero_buffer: int) -> Optional[CromoTubo]:
    """`numero_buffer` es 1-indexado (como lo cuenta el técnico) — `cromo_tubos.orden` arranca en 0
    en los datos reales, de ahí el `- 1`."""
    return (
        session.query(CromoTubo)
        .filter(CromoTubo.cable_n_id == cable_n_id, CromoTubo.vigente.is_(True), CromoTubo.orden == numero_buffer - 1)
        .first()
    )


def contar_buffers_cable(session: Session, cable_n_id: int) -> int:
    return (
        session.query(func.count(CromoTubo.n_id))
        .filter(CromoTubo.cable_n_id == cable_n_id, CromoTubo.vigente.is_(True))
        .scalar()
        or 0
    )


def construir_respuesta_buffer_no_encontrado(nombre_cable: str, numero_buffer: int, total_buffers: int) -> str:
    if total_buffers == 0:
        return f":warning: El cable *{nombre_cable}* no tiene buffers registrados en el inventario."
    return (
        f":warning: El cable *{nombre_cable}* no tiene un buffer B{numero_buffer} — "
        f"tiene {total_buffers} buffer(es) registrados (B1 a B{total_buffers})."
    )


def construir_respuesta_verificar_buffer(cable: CromoCable, tubo: CromoTubo, resultado: ResultadoTubo) -> str:
    """"Verificar cable X BN" — sólo los servicios matcheados, sin el listado completo de pelos
    (ese es "Info cable X BN", ver `construir_respuesta_info_buffer`)."""
    color = f" ({tubo.nombre_color})" if tubo.nombre_color else ""
    encabezado = f"🔍 Cable *{cable.nombre}* / Buffer *B{tubo.orden + 1}*{color}"
    if not resultado.servicios:
        return f"{encabezado}\nSin servicios matcheados en este buffer."

    lineas = [encabezado, f"{len(resultado.servicios)} servicio(s) encontrado(s):"]
    for s in resultado.servicios:
        cliente = s.nombre_cliente or s.cliente or "—"
        lineas.append(f"• {s.servicio_id_externo} — {cliente} ({s.estado_servicio or '—'})")
    return "\n".join(lineas)


# ── "Servicios <cable>" / "Servicios <cable> B<N>" — IDs únicos, no detalle de pelo (Task 8) ────

# Resuelve a qué buffer pertenece cada `ServicioUnico` de un cable ENTERO sin una query por
# servicio (un cable real llega a 118, ver `servicios_unicos_por_cable_sync`): dos consultas batch,
# una por todos los pelos del cable (pelo_n_id -> tubo_n_id) y otra por todos sus tubos vigentes
# (tubo_n_id -> orden/color) alcanzan para agrupar los N servicios en memoria.
_SQL_PELOS_TUBO_DE_CABLE = text(
    "SELECT n_id, tubo_n_id FROM app.cromo_pelos WHERE cable_n_id = :cable_n_id AND vigente"
)
_SQL_TUBOS_VIGENTES_DE_CABLE = text(
    "SELECT n_id, orden, nombre_color FROM app.cromo_tubos WHERE cable_n_id = :cable_n_id AND vigente = true"
)


def _agrupar_servicios_por_buffer(
    session: Session, cable_n_id: int, servicios: list[ServicioUnico]
) -> list[tuple[Optional[int], Optional[str], list[ServicioUnico]]]:
    """Agrupa `servicios` (de `servicios_unicos_por_cable_sync`) por buffer del cable. El pelo
    representativo de cada servicio es `pelos_n_ids[0]` — ya viene ordenado ascendente
    (`array_agg(... ORDER BY p.n_id)` en `verificador.py`), mismo criterio de "primero como
    representativo" que ya usa `_describir_pelo` con `pelo.servicios[0]`. Un servicio cuyo pelo
    representativo no resuelve a un tubo vigente (referencia colgada) cae en un grupo aparte
    (`orden=None`) en vez de perderse. Devuelve los grupos ordenados por `orden` ascendente, con el
    grupo sin buffer identificado al final."""
    pelo_a_tubo = {
        fila[0]: fila[1]
        for fila in session.execute(_SQL_PELOS_TUBO_DE_CABLE, {"cable_n_id": cable_n_id}).all()
    }
    tubos = {
        fila[0]: (fila[1], fila[2])
        for fila in session.execute(_SQL_TUBOS_VIGENTES_DE_CABLE, {"cable_n_id": cable_n_id}).all()
    }

    grupos: dict[Optional[int], list[ServicioUnico]] = {}
    for s in servicios:
        pelo_representativo = s.pelos_n_ids[0] if s.pelos_n_ids else None
        tubo_n_id = pelo_a_tubo.get(pelo_representativo) if pelo_representativo is not None else None
        if tubo_n_id is not None and tubo_n_id not in tubos:
            tubo_n_id = None  # referencia colgada: el tubo dejó de ser vigente o no se ingirió
        grupos.setdefault(tubo_n_id, []).append(s)

    con_buffer = sorted((t for t in grupos if t is not None), key=lambda t: tubos[t][0])
    resultado = [(tubos[t][0], tubos[t][1], grupos[t]) for t in con_buffer]
    if None in grupos:
        resultado.append((None, None, grupos[None]))
    return resultado


def _lineas_grupos_por_buffer(grupos: list[tuple[Optional[int], Optional[str], list[ServicioUnico]]]) -> list[str]:
    lineas = []
    for orden, color, servicios in grupos:
        ids = ", ".join(s.servicio_id_externo for s in servicios)
        if orden is None:
            lineas.append(f"Sin buffer identificado: {ids}")
        else:
            color_txt = f" ({color})" if color else ""
            lineas.append(f"B{orden + 1}{color_txt}: {ids}")
    return lineas


def _lineas_discrepancias_numero_pelo(servicios: list[ServicioUnico]) -> list[str]:
    """"En el pelo figura otro número" — compara `servicio_id_externo` (el ID vigente) contra
    `numeros_en_pelo` (los `servicio_numero` distintos escritos en la descripción de sus pelos). Es
    el 18,9% medido real (25.203 de 133.173 pares pelo↔servicio, `docs/decisiones.md`): el técnico
    lee en la etiqueta física un número que ya no es el vigente."""
    lineas = []
    for s in servicios:
        otros = sorted({n for n in s.numeros_en_pelo if n and n != s.servicio_id_externo})
        if otros:
            lineas.append(
                f"⚠️ En el pelo figura otro número: {s.servicio_id_externo} "
                f"(el pelo dice {', '.join(otros)})"
            )
    return lineas


def _linea_frescura_prov(
    servicios: list[ServicioUnico], vencidos: set[int], *, refrescando: bool = False
) -> Optional[str]:
    """El conteo de vencidos, con un sufijo de refresco opcional. La Task 8 la dejó
    deliberadamente sin sufijo ("el refresco real todavía no existe (Task 9) y prometerlo acá le
    mentiría al técnico") — desde la Task 9 el refresco sí existe
    (`modules/slack_baneo_notifier/refresco_prov.py`), así que el caller (el listener) puede pasar
    `refrescando=True` cuando efectivamente encoló el refresco asíncrono para este lote. Default
    `False` a propósito: no cambia el contrato para ningún caller que no sabe de esto (mismo
    criterio que `vencidos` en `construir_respuesta_info_buffer`). `None` si no hay ninguno vencido
    — no hace falta la línea para decir "0"."""
    cantidad = sum(1 for s in servicios if s.servicio_id in vencidos)
    if cantidad == 0:
        return None
    sufijo = " — refrescando…" if refrescando else ""
    return f"🕒 {cantidad} con validación PROV vencida{sufijo}"


def _sufijo_filtros(categoria: Optional[int], verificable: Optional[bool]) -> str:
    partes = []
    if categoria is not None:
        partes.append(f"Categoría *C{categoria}*")
    if verificable is not None:
        partes.append("Verificables" if verificable else "No verificables")
    return "".join(f" · {p}" for p in partes)


def _texto_sin_servicios(ambito: str, categoria: Optional[int], verificable: Optional[bool]) -> str:
    if categoria is None and verificable is None:
        return f"Sin servicios matcheados en este {ambito}."
    descripcion = "servicios"
    if categoria is not None:
        descripcion += f" de categoría C{categoria}"
    if verificable is not None:
        descripcion += " verificables" if verificable else " no verificables"
    return f"Sin {descripcion} en este {ambito}."


def construir_respuesta_servicios_cable(
    cable: CromoCable,
    session: Session,
    resultado: ResultadoServiciosUnicos,
    vencidos: set[int],
    *,
    refrescando: bool = False,
    categoria: Optional[int] = None,
    verificable: Optional[bool] = None,
) -> str:
    """"Servicios <cable>" — un ID por servicio (no uno por pelo, eso es "Verificar cable X BN"),
    agrupados por buffer, con marca de frescura PROV. Con la salida acotada a IDs, un cable entero
    (118 servicios reales, `FO-FL-1003` n_id 6610203) entra cómodo en un solo mensaje (~950
    caracteres) — no hace falta truncar.

    `refrescando` (Task 9, default `False` — no rompe ningún caller existente): ver
    `_linea_frescura_prov`. `categoria`/`verificable` (2026-09-28): sólo rotulan — el filtrado ya
    lo hizo el caller con `filtrar_servicios`."""
    servicios = resultado.servicios
    encabezado_base = f"🧾 Servicios del cable *{cable.nombre}*{_sufijo_filtros(categoria, verificable)}"
    if not servicios:
        return f"{encabezado_base}\n{_texto_sin_servicios('cable', categoria, verificable)}"

    grupos = _agrupar_servicios_por_buffer(session, cable.n_id, servicios)
    lineas = [f"{encabezado_base} — {len(servicios)} ID(s) únicos"]
    lineas.extend(_lineas_grupos_por_buffer(grupos))
    lineas.extend(_lineas_discrepancias_numero_pelo(servicios))
    linea_frescura = _linea_frescura_prov(servicios, vencidos, refrescando=refrescando)
    if linea_frescura:
        lineas.append(linea_frescura)
    return "\n".join(lineas)


def construir_respuesta_servicios_buffer(
    cable: CromoCable,
    tubo: CromoTubo,
    resultado: ResultadoServiciosUnicos,
    vencidos: set[int],
    *,
    refrescando: bool = False,
    categoria: Optional[int] = None,
    verificable: Optional[bool] = None,
) -> str:
    """"Servicios <cable> B<N>" — mismo IDs únicos que `construir_respuesta_servicios_cable`,
    acotado a un buffer puntual (mismo par cable/buffer que "Verificar cable X BN", pero por-
    servicio en vez de por-pelo).

    `refrescando` (Task 9, default `False` — no rompe ningún caller existente): ver
    `_linea_frescura_prov`. `categoria`/`verificable`: ver `construir_respuesta_servicios_cable`."""
    servicios = resultado.servicios
    color = f" ({tubo.nombre_color})" if tubo.nombre_color else ""
    encabezado = (
        f"🧾 Servicios del cable *{cable.nombre}* / Buffer *B{tubo.orden + 1}*{color}{_sufijo_filtros(categoria, verificable)}"
    )
    if not servicios:
        return f"{encabezado}\n{_texto_sin_servicios('buffer', categoria, verificable)}"

    lineas = [f"{encabezado} — {len(servicios)} ID(s) únicos", ", ".join(s.servicio_id_externo for s in servicios)]
    lineas.extend(_lineas_discrepancias_numero_pelo(servicios))
    linea_frescura = _linea_frescura_prov(servicios, vencidos, refrescando=refrescando)
    if linea_frescura:
        lineas.append(linea_frescura)
    return "\n".join(lineas)


def _describir_pelo(pelo: PeloDetalle, vencidos: Optional[set[int]] = None) -> str:
    """Formato (ticket 2026-08-25):
    - Con servicio: "Pelo N (Color): Tipo — Línea — Cliente — Descripción (Estado)".
    - Libre/sin match: "Pelo N (Color): Libre — Descripción" (sin el segundo tramo si no hay
      `servicio_raw` — antes esta rama distinguía "Libre" de "No se identifica cliente/cable", el
      ticket la unifica en una sola forma).

    `vencidos` (Task 8, plan "Corrección ingresos + Servicios"): set de `servicio_id` (PK) con la
    sincronización PROV vencida — agrega un `🕒` de sufijo al pelo cuyo servicio matcheado está ahí.
    `None`/vacío (default) no marca nada, así el caller que todavía no calculó frescura (ninguno,
    hoy) no tiene que pasar nada. Sólo marca, no dispara refresco — eso es la Task 9."""
    etiqueta = pelo.numero_pelo or f"n_id {pelo.n_id}"
    color = pelo.color or "—"
    if pelo.servicios:
        s = pelo.servicios[0]
        cliente = s.nombre_cliente or s.cliente or "—"
        tipo = extraer_tipo_servicio_display(pelo.servicio_raw)
        marcador = " 🕒" if vencidos and s.servicio_id in vencidos else ""
        return (
            f"• Pelo {etiqueta} ({color}): {tipo} — {s.servicio_id_externo} — {cliente} — "
            f"{pelo.servicio_raw or '—'} ({s.estado_servicio or '—'}){marcador}"
        )
    if pelo.servicio_raw:
        return f"• Pelo {etiqueta} ({color}): Libre — {pelo.servicio_raw}"
    return f"• Pelo {etiqueta} ({color}): Libre"


def construir_respuesta_info_buffer(
    cable: CromoCable, tubo: CromoTubo, pelos: list[PeloDetalle], vencidos: Optional[set[int]] = None
) -> str:
    """"Info cable X BN" — listado completo de pelos del buffer, matcheados o no. A diferencia de
    "Verificar cable X BN", detalla la descripción cruda (`servicio_raw`) de los pelos que no están
    libres pero tampoco se identificó cliente/cable — pedido explícito de la spec original.

    `vencidos` (Task 8): opcional y con default `None` a propósito — no cambia el contrato para el
    único otro caller además del listener (`tests/test_slack_cable_info.py`, que sigue llamando con
    3 posicionales). Sólo agrega el marcador `🕒` de `_describir_pelo`, no cambia esta función ni
    dispara ningún refresco (eso es la Task 9)."""
    color = f" ({tubo.nombre_color})" if tubo.nombre_color else ""
    encabezado = f"📋 Cable *{cable.nombre}* / Buffer *B{tubo.orden + 1}*{color}"
    if not pelos:
        return f"{encabezado}\nSin pelos registrados en este buffer."

    lineas = [f"{encabezado} — {len(pelos)} pelo(s)"]
    lineas.extend(_describir_pelo(p, vencidos) for p in pelos)
    return "\n".join(lineas)


__all__ = [
    "CATEGORIAS_FILTRABLES",
    "buscar_cable_por_n_id_o_nombre",
    "buscar_cable_por_nombre",
    "construir_respuesta_ambiguo",
    "construir_respuesta_buffer_no_encontrado",
    "construir_respuesta_categoria_invalida",
    "construir_respuesta_info_buffer",
    "construir_respuesta_info_cable",
    "construir_respuesta_no_encontrado",
    "construir_respuesta_servicios_buffer",
    "construir_respuesta_servicios_cable",
    "construir_respuesta_verificar_buffer",
    "contar_buffers_cable",
    "extraer_comando_cable_buffer",
    "extraer_comando_info_cable",
    "extraer_comando_servicios_buffer",
    "extraer_filtro_categoria",
    "extraer_filtro_verificable",
    "filtrar_servicios",
    "extraer_comando_servicios_cable",
    "quitar_formato_slack",
    "resolver_tubo_por_numero",
]
