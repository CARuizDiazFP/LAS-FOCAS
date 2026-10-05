# Nombre de archivo: charts.py
# Ubicación de archivo: core/sla_consumo/charts.py
# Descripción: Gráficos PNG de mayores repercutores de SLA (matplotlib Agg)

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from core.sla_consumo.clasificador import GRUPOS_ORDEN  # noqa: E402

# Paleta fija por grupo: el mismo grupo tiene el mismo color en todos los gráficos.
COLORES = dict(zip(GRUPOS_ORDEN, ("#2a6fdb", "#e0892b", "#7a5bd6", "#8a8f98", "#3aa57a")))


def _guardar(fig, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(destino, dpi=150)
    plt.close(fig)
    return destino


def _finitos(serie: pd.Series) -> pd.Series:
    """Máscara de valores numéricos finitos (excluye NaN e inf)."""
    return np.isfinite(pd.to_numeric(serie, errors="coerce"))


def pareto_eventos(res, destino: Path, top: int = 15) -> Path:
    datos = res.eventos.head(top)
    total = res.eventos["horas_sla"].sum() or 1.0
    fig, ax = plt.subplots(figsize=(10, 5))
    etiquetas = [str(e) for e in datos["evento_clave"]]
    ax.bar(etiquetas, datos["horas_sla"], color=[COLORES.get(g, "#8a8f98") for g in datos["grupo_predominante"]])
    ax.set_ylabel("Horas que consumen SLA")
    ax.set_title(f"Top {len(datos)} eventos por horas de SLA consumidas")
    ax.tick_params(axis="x", rotation=60, labelsize=8)
    ax2 = ax.twinx()
    ax2.plot(etiquetas, datos["horas_sla"].cumsum() / total * 100, color="#222", marker="o", linewidth=1)
    ax2.set_ylabel("% acumulado del total")
    ax2.set_ylim(0, 100)
    return _guardar(fig, destino)


def top_servicios(res, destino: Path, top: int = 20) -> Path:
    datos = res.servicios[_finitos(res.servicios["pct_presupuesto"])].head(top)[::-1]
    fig, ax = plt.subplots(figsize=(10, max(4, len(datos) * 0.35)))
    ax.barh([f"{l} · {str(c)[:28]}" for l, c in zip(datos["numero_linea"], datos["nombre_cliente"])],
            datos["pct_presupuesto"], color="#2a6fdb")
    ax.axvline(100, color="#c0392b", linestyle="--", linewidth=1)
    ax.set_xlabel("% del presupuesto anual de SLA consumido")
    ax.set_title(f"Top {len(datos)} servicios por SLA consumido")
    return _guardar(fig, destino)


def horas_por_grupo(res, destino: Path) -> Path:
    datos = res.codigo_cierre
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(datos["grupo"], datos["horas"], color=[COLORES[g] for g in datos["grupo"]])
    ax.set_ylabel("Horas netas")
    ax.set_title("Horas por código de cierre")
    ax.tick_params(axis="x", rotation=20, labelsize=8)
    return _guardar(fig, destino)


def servicio(res, numero_linea: str, destino: Path) -> Path:
    datos = res.servicio_reclamo[res.servicio_reclamo["numero_linea"] == numero_linea]
    presupuesto = datos["presupuesto_h"].iloc[0] if len(datos) else None
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.bar(datos["numero_reclamo"].astype(str), datos["horas_sla"],
           color=[COLORES.get(g, "#8a8f98") for g in datos["grupo_cierre"]])
    ax.plot(datos["numero_reclamo"].astype(str), datos["horas_sla"].cumsum(), color="#222", marker="o", linewidth=1,
            label="Acumulado")
    if presupuesto:
        ax.axhline(presupuesto, color="#c0392b", linestyle="--", linewidth=1, label="Presupuesto anual")
    ax.set_ylabel("Horas")
    ax.set_title(f"Servicio {numero_linea}: reclamos y SLA acumulado")
    ax.tick_params(axis="x", rotation=60, labelsize=8)
    ax.legend(fontsize=8)
    return _guardar(fig, destino)
