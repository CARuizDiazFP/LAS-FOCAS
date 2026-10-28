# Nombre de archivo: camaras_busqueda_avanzada.py
# Ubicación de archivo: core/services/camaras_busqueda_avanzada.py
# Descripción: Búsqueda avanzada de Cámaras por filtros AND (modelos del request y matching), común a la API y al panel

"""Búsqueda avanzada (`POST /api/infra/search`) movida desde `api/app/routes/infra.py` y
`web/app/routers/camaras.py`, donde estaba copiada.

Conserva su semántica: el matching corre en Python sobre todas las cámaras (Botellas y NO_OPERATIVA
incluidas), ordenadas por nombre (con `id` de desempate), y la paginación se aplica después de filtrar.
Los servicios de cada cámara salen de sus rutas (con caída a la asociación legacy si no tiene), igual
que en el resto de la consulta de Cámaras. Los modelos Pydantic son los de la API y los usan ambos routers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.services.camaras_consulta import (
    _CARGA_POR_LOTE,
    CamaraEncontrada,
    _collect_camara_rutas_info,
    _collect_camara_servicios_ids,
)
from db.models.infra import Camara, CamaraEstado


class FilterField(str, Enum):
    """Campos disponibles para filtrar en búsqueda avanzada."""

    SERVICE_ID = "service_id"  # Busca cámaras asociadas a un servicio
    ADDRESS = "address"  # Busca por nombre/dirección de cámara
    STATUS = "status"  # Busca por estado (LIBRE, OCUPADA, BANEADA, DETECTADA)
    CABLE = "cable"  # Busca cámaras asociadas a un cable
    ORIGEN = "origen"  # Busca por origen de datos (MANUAL, TRACKING, SHEET)


class FilterOperator(str, Enum):
    """Operadores de comparación para filtros."""

    EQ = "eq"  # Igual exacto
    CONTAINS = "contains"  # Contiene (case-insensitive)
    STARTS_WITH = "starts_with"  # Empieza con
    ENDS_WITH = "ends_with"  # Termina con
    IN = "in"  # Valor en lista


class SearchFilter(BaseModel):
    """Filtro individual para búsqueda avanzada."""

    field: FilterField
    operator: FilterOperator = FilterOperator.CONTAINS
    value: str | list[str]

    model_config = {"json_schema_extra": {"examples": [{"field": "address", "operator": "contains", "value": "rivadavia"}]}}


class SearchRequest(BaseModel):
    """Request para búsqueda avanzada de cámaras con filtros AND."""

    filters: list[SearchFilter] = Field(default_factory=list, min_length=0, max_length=10)
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "filters": [
                        {"field": "service_id", "operator": "eq", "value": "SVC-12345"},
                        {"field": "address", "operator": "contains", "value": "rivadavia"},
                    ],
                    "limit": 50,
                    "offset": 0,
                }
            ]
        }
    }


@dataclass(frozen=True)
class ResultadoBusqueda:
    """Total de cámaras que cumplen todos los filtros y la página pedida."""

    total: int
    camaras: list[CamaraEncontrada]


def filtro_texto_coincide(value: str | list[str], operator: FilterOperator, db_value: Optional[str]) -> bool:
    """Aplica un filtro de texto (case-insensitive) a un valor de la base; `None` nunca coincide."""

    if db_value is None:
        return False

    db_lower = db_value.lower()
    val_lower = value.lower() if isinstance(value, str) else value

    if operator == FilterOperator.EQ:
        return db_lower == val_lower
    if operator == FilterOperator.CONTAINS:
        return val_lower in db_lower
    if operator == FilterOperator.STARTS_WITH:
        return db_lower.startswith(val_lower)
    if operator == FilterOperator.ENDS_WITH:
        return db_lower.endswith(val_lower)
    if operator == FilterOperator.IN:
        if isinstance(value, list):
            return db_lower in [v.lower() for v in value]
        return db_lower == val_lower
    return False


def _valor_escalar(valor: str | list[str]) -> str:
    """Primer elemento si el valor es una lista (vacía: cadena vacía)."""

    return valor if isinstance(valor, str) else valor[0] if valor else ""


def _coincide_enum(actual: str, flt: SearchFilter) -> bool:
    """Compara un valor de enum (estado, origen) con el filtro: `in` con lista o igualdad."""

    if flt.operator == FilterOperator.IN and isinstance(flt.value, list):
        return actual.upper() in [v.upper() for v in flt.value]
    return actual.upper() == _valor_escalar(flt.value).upper()


def camara_coincide_filtro(
    camara: Camara,
    flt: SearchFilter,
    servicios_ids: list[str],
    cables_nombres: list[str],
) -> bool:
    """Evalúa si una cámara cumple un filtro, dados sus servicios y los nombres de sus cables."""

    value = _valor_escalar(flt.value)

    if flt.field == FilterField.SERVICE_ID:
        return any(filtro_texto_coincide(value, flt.operator, svc_id) for svc_id in servicios_ids)
    if flt.field == FilterField.ADDRESS:
        return filtro_texto_coincide(value, flt.operator, camara.nombre) or filtro_texto_coincide(
            value, flt.operator, camara.direccion
        )
    if flt.field == FilterField.STATUS:
        return _coincide_enum(camara.estado.value if camara.estado else "LIBRE", flt)
    if flt.field == FilterField.CABLE:
        return any(filtro_texto_coincide(value, flt.operator, nombre) for nombre in cables_nombres)
    if flt.field == FilterField.ORIGEN:
        return _coincide_enum(camara.origen_datos.value if camara.origen_datos else "MANUAL", flt)
    return False


def _cables_nombres_unicos(camara: Camara) -> list[str]:
    """Nombres de los cables de la cámara (origen y destino), sin repetidos y en orden."""

    nombres: list[str] = []
    for cable in camara.cables:
        if cable.nombre and cable.nombre not in nombres:
            nombres.append(cable.nombre)
    return nombres


def _prefiltro_estados(filtros: list[SearchFilter]) -> list[CamaraEstado] | None:
    """Estados a pedir a la base cuando el único filtro es `status` con `eq`/`in`; `None` si no aplica.

    Es sólo una optimización: el matching en Python vuelve a evaluar el filtro. Un valor vacío o
    inválido no restringe la consulta (el matching lo resuelve y devuelve 0 resultados)."""

    if len(filtros) != 1 or filtros[0].field != FilterField.STATUS:
        return None
    flt = filtros[0]
    validos = {e.value for e in CamaraEstado}
    if flt.operator == FilterOperator.EQ:
        valor = _valor_escalar(flt.value).upper()
        return [CamaraEstado(valor)] if valor in validos else None
    if flt.operator == FilterOperator.IN and isinstance(flt.value, list):
        estados = [CamaraEstado(v.upper()) for v in flt.value if v.upper() in validos]
        return estados or None
    return None


def buscar_camaras_avanzada(
    session: Session,
    filtros: list[SearchFilter],
    *,
    limit: int,
    offset: int,
) -> ResultadoBusqueda:
    """Cámaras que cumplen TODOS los filtros (AND), ordenadas por nombre y paginadas tras filtrar."""

    stmt = select(Camara).options(*_CARGA_POR_LOTE).order_by(Camara.nombre, Camara.id)
    estados = _prefiltro_estados(filtros)
    if estados:
        stmt = stmt.where(Camara.estado.in_(estados))

    coincidentes: list[CamaraEncontrada] = []
    for camara in session.scalars(stmt).all():
        rutas_info = _collect_camara_rutas_info(camara)
        servicios_ids = _collect_camara_servicios_ids(camara, rutas_info)
        if filtros:
            cables = _cables_nombres_unicos(camara)
            if not all(camara_coincide_filtro(camara, flt, servicios_ids, cables) for flt in filtros):
                continue
        coincidentes.append(CamaraEncontrada(camara=camara, rutas_info=rutas_info, servicios_ids=servicios_ids))

    return ResultadoBusqueda(total=len(coincidentes), camaras=coincidentes[offset : offset + limit])
