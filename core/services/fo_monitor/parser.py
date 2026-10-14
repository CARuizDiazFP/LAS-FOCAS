# Nombre de archivo: parser.py
# Ubicación de archivo: core/services/fo_monitor/parser.py
# Descripción: Extrae el bloque FOMON (estado por servicio) y la marca de fin de las respuestas de burritoIA en Slack

"""Parser de respuestas de burritoIA para FO Monitor.

burritoIA contesta en el hilo de la mención, en Slack mrkdwn y a veces partido en 2+ mensajes;
cada respuesta termina con `_(ref: #xxxx)_`. Este módulo es puro (sin Slack ni DB): recibe los
textos de los mensajes del bot, en orden, y devuelve un estado normalizado por servicio pedido.

Regla de oro: lo que no se puede leer con certeza es DESCONOCIDO, nunca UP. Un servicio pedido
sin línea FOMON válida queda DESCONOCIDO con motivo `sin_linea`.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from core.services.fo_monitor.prompt import ESTADOS_VALIDOS

_RE_LINEA = re.compile(
    r"FOMON\s*\|\s*(?P<id>[A-Za-z0-9][A-Za-z0-9-]*)\s*\|\s*(?P<estado>[A-Za-z_]+)\s*\|"
    r"\s*(?P<extremo>[^|\n]*?)\s*\|\s*(?P<motivo>[^\n]*)$",
    re.IGNORECASE,
)
_RE_REF = re.compile(r"\(ref:\s*#([0-9A-Za-z]+)\)")
_DECORACION = "`*_~> \t"


@dataclass(frozen=True)
class ResultadoServicio:
    servicio_id: str
    estado: str
    extremo: str | None
    motivo: str
    parseado: bool


@dataclass
class RespuestaParseada:
    resultados: dict[str, ResultadoServicio]
    ref: str | None
    lineas_invalidas: list[str] = field(default_factory=list)
    completa: bool = False

    @property
    def ids_con_linea(self) -> set[str]:
        return {k for k, v in self.resultados.items() if v.parseado}


def _limpiar_linea(linea: str) -> str:
    return linea.strip().strip(_DECORACION).strip()


def _normalizar_id(valor: str) -> str:
    valor = valor.strip()
    return str(int(valor)) if valor.isdigit() else valor.upper()


def parsear_respuesta(textos: Iterable[str], ids_solicitados: Sequence[str]) -> RespuestaParseada:
    """Parsea los mensajes de burritoIA de un hilo.

    `completa` es True cuando todos los IDs pedidos tienen una línea válida. La marca `ref` sola
    no alcanza (burritoIA puede cerrar sin el bloque); el worker decide con `ref` + silencio.
    """
    pedidos = {_normalizar_id(i): str(i) for i in ids_solicitados}
    encontrados: dict[str, ResultadoServicio] = {}
    invalidas: list[str] = []
    ref: str | None = None

    for texto in textos:
        texto = html.unescape(texto or "")
        m_ref = _RE_REF.search(texto)
        if m_ref:
            ref = m_ref.group(1)
        for linea_cruda in texto.splitlines():
            linea = _limpiar_linea(linea_cruda)
            if "FOMON|" not in linea.upper().replace(" ", ""):
                continue
            if "<ESTADO>" in linea.upper() or "<ID>" in linea.upper():
                continue  # eco de la plantilla del prompt
            m = _RE_LINEA.search(linea)
            if not m:
                invalidas.append(linea)
                continue
            sid = _normalizar_id(m.group("id"))
            if sid.startswith("FOMON-Q") and len(pedidos) == 1:
                # burritoIA a veces pone el token de la consulta en lugar del id (PoC, ref #ec8a);
                # con un único servicio pedido no hay ambigüedad.
                sid = next(iter(pedidos))
            estado = m.group("estado").upper()
            if sid not in pedidos or estado not in ESTADOS_VALIDOS:
                invalidas.append(linea)
                continue
            extremo = m.group("extremo").strip().strip(_DECORACION) or None
            if extremo in ("-", "—", "−", "–"):
                extremo = None
            encontrados[sid] = ResultadoServicio(
                servicio_id=pedidos[sid],
                estado=estado,
                extremo=extremo,
                motivo=m.group("motivo").strip().strip(_DECORACION)[:200],
                parseado=True,
            )

    resultados: dict[str, ResultadoServicio] = {}
    for sid_norm, sid_original in pedidos.items():
        resultados[sid_original] = encontrados.get(sid_norm) or ResultadoServicio(
            servicio_id=sid_original, estado="DESCONOCIDO", extremo=None, motivo="sin_linea", parseado=False
        )
    return RespuestaParseada(
        resultados=resultados,
        ref=ref,
        lineas_invalidas=invalidas,
        completa=len(encontrados) == len(pedidos),
    )
