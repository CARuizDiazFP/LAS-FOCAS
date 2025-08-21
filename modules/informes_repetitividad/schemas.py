# Nombre de archivo: schemas.py
# Ubicación de archivo: modules/informes_repetitividad/schemas.py
# Descripción: Modelos de datos para el informe de repetitividad

from typing import List
from pydantic import BaseModel


class Params(BaseModel):
    """Parámetros de período para generar el informe."""

    periodo_mes: int
    periodo_anio: int


class ItemSalida(BaseModel):
    """Resultado por servicio con casos repetidos."""

    servicio: str
    casos: int
    detalles: List[str]


class ResultadoRepetitividad(BaseModel):
    """Resultado completo del cálculo de repetitividad."""

    items: List[ItemSalida]
    total_servicios: int
    total_repetitivos: int
