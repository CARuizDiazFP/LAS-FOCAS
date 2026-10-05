# Nombre de archivo: xlsx_builder.py
# Ubicación de archivo: core/sla_consumo/xlsx_builder.py
# Descripción: XLSX del informe SLA consumido, una hoja por vista

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HOJAS = ("Resumen", "Eventos", "Servicios", "Servicio x Reclamo", "Código de cierre",
         "Detalle tipo solución", "Carrier x Cliente")


def _limpiar(df: pd.DataFrame) -> pd.DataFrame:
    """Quita tz (openpyxl no escribe datetimes tz-aware) y reemplaza ±inf por vacío."""
    df = df.copy()
    for col in df.columns:
        if isinstance(df[col].dtype, pd.DatetimeTZDtype):
            df[col] = df[col].dt.tz_localize(None)
        elif pd.api.types.is_float_dtype(df[col].dtype):
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)
    return df


def construir_xlsx(res, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    resumen = pd.DataFrame([{"fecha_corte": res.fecha_corte.isoformat(), **res.totales}]).T.reset_index()
    resumen.columns = ["indicador", "valor"]
    vistas = (resumen, res.eventos, res.servicios, res.servicio_reclamo, res.codigo_cierre,
              res.codigo_cierre_detalle, res.carrier_cliente)
    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        for nombre, df in zip(HOJAS, vistas):
            _limpiar(df).to_excel(writer, sheet_name=nombre, index=False)
            hoja = writer.sheets[nombre]
            hoja.freeze_panes = "A2"
            for columna in hoja.columns:
                ancho = max(len(str(c.value or "")) for c in columna[:200])
                hoja.column_dimensions[columna[0].column_letter].width = min(max(10, ancho + 2), 50)
    return destino
