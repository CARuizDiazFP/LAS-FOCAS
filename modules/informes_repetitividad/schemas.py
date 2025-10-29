# Nombre de archivo: schemas.py
# Ubicación de archivo: modules/informes_repetitividad/schemas.py
# Descripción: Modelos de datos para el informe de repetitividad

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


class Params(BaseModel):
    """Parámetros de período para generar el informe."""

    periodo_mes: int
    periodo_anio: int


class ReclamoDetalle(BaseModel):
    """Detalle de un reclamo individual asociado a un servicio repetitivo."""

    numero_reclamo: str
    numero_evento: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_cierre: Optional[str] = None
    tipo_solucion: Optional[str] = None
    horas_netas: Optional[float] = None
    descripcion_solucion: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None


class ServicioDetalle(BaseModel):
    """Información consolidada de un servicio repetitivo."""

    servicio: str
    nombre_cliente: Optional[str] = None
    tipo_servicio: Optional[str] = None
    casos: int
    reclamos: List[ReclamoDetalle]
    map_path: Optional[str] = None
    map_image_path: Optional[str] = None

    def has_geo(self) -> bool:
        return any(r.latitud is not None and r.longitud is not None for r in self.reclamos)


class ResultadoRepetitividad(BaseModel):
    """Resultado completo del cálculo de repetitividad."""

    servicios: List[ServicioDetalle]
    total_servicios: int
    total_repetitivos: int
    periodos: List[str]
    with_geo: bool = False
    source: str = "excel"
