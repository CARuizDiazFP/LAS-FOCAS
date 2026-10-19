# Nombre de archivo: senales.py
# Ubicación de archivo: core/services/cromo/arbitro/senales.py
# Descripción: Núcleo puro del árbitro de Cromo: señales, puntaje, alcance, evaluación y contrato de regla

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

USUARIO_ARBITRO = "arbitro-cromo"

MODOS = ("APAGADA", "SOMBRA", "AUTO")
ESTADOS_ABIERTOS = ("PROPUESTA", "EN_OBSERVACION")
ACCIONES = ("ASOCIAR_ODF", "FUSIONAR_GEMELO", "INFORMAR")
DISPAROS = ("INGESTA", "REGISTRADOR", "VIEWER", "NORMALIZADOR")

OBJETO_SERVICIO = "SERVICIO"
OBJETO_BOTELLA = "BOTELLA"
OBJETO_ODF = "ODF"

_TIPOS_ALCANCE = ("TODO", "SERVICIOS", "BOTELLAS", "ODFS")
_OBJETO_POR_ALCANCE = {
    "SERVICIOS": OBJETO_SERVICIO,
    "BOTELLAS": OBJETO_BOTELLA,
    "ODFS": OBJETO_ODF,
}


@dataclass(frozen=True, slots=True)
class Senal:
    """Una evidencia con peso; un veto anula todo el puntaje."""

    codigo: str
    peso: int
    detalle: Mapping[str, Any] = field(default_factory=dict)
    veto: bool = False


@dataclass(frozen=True, slots=True)
class Alcance:
    """Conjunto de objetos sobre el que se evalúa; TODO con ids vacío es válido."""

    tipo: str
    ids: tuple[int, ...] = ()

    def cubre(self, objeto_tipo: str, objeto_id: int) -> bool:
        if self.tipo == "TODO":
            return True
        return _OBJETO_POR_ALCANCE.get(self.tipo) == objeto_tipo and objeto_id in self.ids

    def a_dict(self) -> dict:
        return {"tipo": self.tipo, "ids": list(self.ids)}

    @classmethod
    def desde_dict(cls, d: Mapping[str, Any]) -> "Alcance":
        tipo = d.get("tipo") if isinstance(d, Mapping) else None
        if tipo not in _TIPOS_ALCANCE:
            raise ValueError(f"Tipo de alcance inválido: {tipo!r}")
        crudos = d.get("ids") or []
        if isinstance(crudos, (str, bytes)) or not isinstance(crudos, Sequence):
            raise ValueError("ids debe ser una lista de enteros")
        ids: list[int] = []
        for valor in crudos:
            if isinstance(valor, bool) or not isinstance(valor, int):
                raise ValueError(f"id de alcance no entero: {valor!r}")
            ids.append(valor)
        return cls(tipo=tipo, ids=tuple(ids))


@dataclass(frozen=True, slots=True)
class Evaluacion:
    regla: str
    objeto_tipo: str
    objeto_id: int
    accion: str
    parametros: Mapping[str, Any]
    senales: tuple[Senal, ...]
    tope: int = 100


def puntaje(senales: Sequence[Senal], tope: int = 100) -> int:
    if any(s.veto for s in senales):
        return 0
    return max(0, min(tope, 100, sum(s.peso for s in senales)))


def evidencia_hash(ev: Evaluacion) -> str:
    senales = sorted(
        ([s.codigo, s.peso, dict(s.detalle)] for s in ev.senales),
        key=lambda t: t[0],
    )
    payload = {
        "regla": ev.regla,
        "objeto_tipo": ev.objeto_tipo,
        "objeto_id": ev.objeto_id,
        "accion": ev.accion,
        "parametros": dict(ev.parametros),
        "senales": senales,
    }
    crudo = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


class Regla(Protocol):
    """Contrato de una regla del árbitro.

    `propios` son los objeto_id que esta regla tiene EN_OBSERVACION: debe volver a
    evaluarlos ignorando el efecto de su propia acción. `contexto` es un caché
    compartido entre reglas dentro de una misma evaluación.
    """

    codigo: str

    async def evaluar(
        self,
        sesion: "AsyncSession",
        alcance: Alcance,
        *,
        propios: frozenset[int],
        contexto: dict[str, Any],
    ) -> list[Evaluacion]: ...
