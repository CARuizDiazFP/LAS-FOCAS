# Nombre de archivo: cable_info.py
# Ubicación de archivo: modules/slack_baneo_notifier/cable_info.py
# Descripción: Parser y consulta de los comandos "Info cable"/"Verificar cable" (con o sin buffer) para el handler app_mention del listener de Slack

"""Comandos de la app de Slack de verificación de Cables (docs/slack_app_cables.md):
- `@bot Info cable <nombre>` — información básica del Cable (capacidad, propietario, jerarquía,
  Botellas de sus extremos).
- `@bot Verificar cable <nombre> B<N>` — servicios matcheados en un buffer puntual del cable.
- `@bot Info cable <nombre> B<N>` — listado completo de pelos de ese buffer (matcheados o no, con
  la descripción cruda si el pelo no está libre pero tampoco se identificó cliente/cable).

El "código de cable" que el técnico escribe (ej. real "F-VFL-IND") es directamente
`cromo_cables.nombre` — verificado 2026-08-13 contra `lasfocasdev-postgres` (no un código externo en
otro sistema, no `id_legacy`). `nombre` es prácticamente único (1 solo par duplicado real,
"F-ALV-2335", sobre ~32.782 cables) — se resuelve con match exacto case-insensitive; ante 0 o 2+
resultados se responde pidiendo precisión en vez de adivinar.

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
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.services.cromo.detalle import PeloDetalle, pelos_de_tubo_sync
from core.services.cromo.verificador import ResultadoTubo, servicios_por_tubo_sync
from db.models.cromo import CromoBotella, CromoCable, CromoTubo

# "Info cable <nombre>", case-insensitive, tolera "Info Cable"/"info cable". El resto de la línea
# (recortado) es el nombre del cable. `_RE_CABLE_BUFFER` (más abajo) se intenta SIEMPRE primero en el
# listener — este regex es deliberadamente "goloso" (`.+` hasta el final) y matchearía de más si un
# mensaje con sufijo "B<N>" llegara acá primero (lo tomaría como parte del nombre del cable).
_RE_INFO_CABLE = re.compile(r"(?i)\binfo\s+cable\s+(.+)$")

# "Verificar cable <nombre> B<N>" / "Info cable <nombre> B<N>" — `.+?` no-goloso para que el nombre
# del cable no se coma el sufijo "B<N>"/"Buffer <N>" del final. Tolera "B1", "B 1", "Buffer 1".
_RE_CABLE_BUFFER = re.compile(r"(?i)^(verificar|info)\s+cable\s+(.+?)\s+(?:b|buffer)\s*(\d+)$")


def extraer_comando_info_cable(texto: str) -> Optional[str]:
    """Extrae el nombre de cable de un texto tipo "Info cable F-VFL-IND". Devuelve `None` si el
    texto no matchea el comando (no es un error — puede ser una mención sin relación a este comando)."""
    texto_normalizado = re.sub(r"\s+", " ", texto).strip()
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
    texto_normalizado = re.sub(r"\s+", " ", texto).strip()
    match = _RE_CABLE_BUFFER.match(texto_normalizado)
    if not match:
        return None
    verbo, nombre, numero = match.group(1).lower(), match.group(2).strip(), match.group(3)
    if not nombre:
        return None
    return verbo, nombre, int(numero)


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


def _describir_pelo(pelo: PeloDetalle) -> str:
    etiqueta = pelo.numero_pelo or f"n_id {pelo.n_id}"
    if pelo.servicios:
        s = pelo.servicios[0]
        cliente = s.nombre_cliente or s.cliente or "—"
        return f"• Pelo {etiqueta}: {s.servicio_id_externo} — {cliente} ({s.estado_servicio or '—'})"
    if not pelo.servicio_raw:
        return f"• Pelo {etiqueta}: Libre"
    return f'• Pelo {etiqueta}: No se identifica cliente/cable — "{pelo.servicio_raw}"'


def construir_respuesta_info_buffer(cable: CromoCable, tubo: CromoTubo, pelos: list[PeloDetalle]) -> str:
    """"Info cable X BN" — listado completo de pelos del buffer, matcheados o no. A diferencia de
    "Verificar cable X BN", detalla la descripción cruda (`servicio_raw`) de los pelos que no están
    libres pero tampoco se identificó cliente/cable — pedido explícito de la spec original."""
    color = f" ({tubo.nombre_color})" if tubo.nombre_color else ""
    encabezado = f"📋 Cable *{cable.nombre}* / Buffer *B{tubo.orden + 1}*{color}"
    if not pelos:
        return f"{encabezado}\nSin pelos registrados en este buffer."

    lineas = [f"{encabezado} — {len(pelos)} pelo(s)"]
    lineas.extend(_describir_pelo(p) for p in pelos)
    return "\n".join(lineas)


__all__ = [
    "buscar_cable_por_nombre",
    "construir_respuesta_ambiguo",
    "construir_respuesta_buffer_no_encontrado",
    "construir_respuesta_info_buffer",
    "construir_respuesta_info_cable",
    "construir_respuesta_no_encontrado",
    "construir_respuesta_verificar_buffer",
    "contar_buffers_cable",
    "extraer_comando_cable_buffer",
    "extraer_comando_info_cable",
    "resolver_tubo_por_numero",
]
