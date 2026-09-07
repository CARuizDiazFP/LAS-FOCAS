# Nombre de archivo: live_lookup_service.py
# Ubicación de archivo: core/services/cromo/live_lookup_service.py
# Descripción: Visor en vivo de un elemento Cromo por n_id — GET directo contra Cromo, nunca persiste nada

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import parser as cromo_parser
from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.verificador import ObjetoNoEncontrado
from db.models.cromo import CromoClase


@dataclass(slots=True)
class AtributoVivo:
    """Un `at[]` crudo de Cromo, con etiqueta legible resuelta contra `parser.ATRIBUTOS_CONOCIDOS`."""

    id: int
    etiqueta: str
    valor: Any


@dataclass(slots=True)
class ElementoVivoCromo:
    """Snapshot en vivo de un elemento Cromo — nunca se guarda, se descarta al responder el request."""

    n_id: int
    version_id: Optional[int]
    clase: Optional[int]
    clase_etiqueta: Optional[str]
    clase_entidad: Optional[str]
    nombre: Optional[str]
    notas: Optional[str]
    atributos: list[AtributoVivo] = field(default_factory=list)
    payload_raw: dict[str, Any] = field(default_factory=dict, repr=False)


async def obtener_elemento_vivo(cliente: CromoClient, sesion: AsyncSession, n_id: int) -> ElementoVivoCromo:
    """GET en vivo contra Cromo (`CromoClient.get_objeto`) — sólo lectura, nunca persiste nada.

    Si Cromo responde 404 (el `n_id` no existe), se traduce a `ObjetoNoEncontrado` — mismo contrato
    que el resto de los endpoints de sólo lectura de Cromo (`verificador.py`/`detalle.py`). Cualquier
    otra falla (`CromoClientError` con otro `status_code`, o red agotada) se deja propagar tal cual
    para que la ruta la mapee a una falla de upstream (502), no a un 404 engañoso.
    """
    try:
        obj = await cliente.get_objeto(n_id)
    except CromoClientError as exc:
        if exc.status_code == 404:
            raise ObjetoNoEncontrado(f"No existe un elemento con n_id={n_id} en Cromo.") from exc
        raise

    clase = obj.get("class")
    clase_etiqueta: Optional[str] = None
    clase_entidad: Optional[str] = None
    if clase is not None:
        fila_clase = await sesion.get(CromoClase, clase)
        if fila_clase is not None:
            clase_etiqueta = fila_clase.etiqueta
            clase_entidad = fila_clase.entidad

    atributos = [
        AtributoVivo(
            id=item.get("id"),
            etiqueta=cromo_parser.ATRIBUTOS_CONOCIDOS.get(item.get("id"), f"Atributo {item.get('id')}"),
            valor=item.get("value"),
        )
        for item in obj.get("at") or []
    ]

    return ElementoVivoCromo(
        n_id=obj.get("n_id") or obj.get("id") or n_id,
        version_id=obj.get("id"),
        clase=clase,
        clase_etiqueta=clase_etiqueta,
        clase_entidad=clase_entidad,
        nombre=obj.get("name"),
        notas=cromo_parser.atributo(obj, 35),
        atributos=atributos,
        payload_raw=obj,
    )


__all__ = ["AtributoVivo", "ElementoVivoCromo", "obtener_elemento_vivo"]
