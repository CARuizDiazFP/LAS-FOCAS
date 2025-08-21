# Nombre de archivo: schemas.py
# Ubicación de archivo: modules/informes_sla/schemas.py
# Descripción: Modelos de datos para el informe de SLA

from typing import Dict, List
from pydantic import BaseModel


class Params(BaseModel):
    """Parámetros de período para el informe."""

    periodo_mes: int
    periodo_anio: int


class KPI(BaseModel):
    """Indicadores clave de cumplimiento de SLA."""

    total: int
    cumplidos: int
    incumplidos: int
    pct_cumplimiento: float
    ttr_promedio_h: float
    ttr_mediana_h: float


class FilaDetalle(BaseModel):
    """Detalle por ticket o caso analizado."""

    id: str
    cliente: str
    servicio: str
    ttr_h: float
    sla_objetivo_h: float
    cumplido: bool


class ResultadoSLA(BaseModel):
    """Resultado global del análisis de SLA."""

    kpi: KPI
    detalle: List[FilaDetalle]
    breakdown_por_servicio: Dict[str, KPI]
    sin_cierre: int
