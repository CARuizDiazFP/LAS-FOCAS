# Nombre de archivo: charts.py
# Ubicación de archivo: core/sla_consumo/charts.py
# Descripción: Gráficos PNG del informe SLA consumido — torta global de causas y magnitud de eventos (matplotlib Agg)

from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from core.sla_consumo import metricas as m  # noqa: E402
from core.sla_consumo.presentacion import COLORES_CAUSA, fmt_horas, fmt_pct  # noqa: E402


def _servicios_txt(n: int) -> str:
    return f"{n} servicio" if n == 1 else f"{n} servicios"


def _guardar(fig, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return destino


def torta_causas(res, destino: Path) -> Path | None:
    comp = res.composicion
    total = float(comp["horas"].sum())
    if total <= m.EPS_HORAS:
        return None
    datos = comp[comp["horas"] > m.EPS_HORAS]
    fig, ax = plt.subplots(figsize=(9, 6))
    cuñas, _ = ax.pie(datos["horas"], colors=[f"#{COLORES_CAUSA[c]}" for c in datos["causa"]], startangle=90,
                      counterclock=False, wedgeprops={"edgecolor": "white", "linewidth": 1.5})
    for cuña, (_, fila) in zip(cuñas, datos.iterrows()):
        if fila["pct"] >= 5:
            ang = (cuña.theta1 + cuña.theta2) / 2
            x, y = matplotlib.transforms.Affine2D().rotate_deg(ang).transform((0.62, 0))
            ax.text(x, y, f"{fmt_horas(fila['horas'])} h\n{fmt_pct(fila['pct'])}", ha="center", va="center",
                    color="white", fontsize=10, fontweight="bold")
    ax.legend(cuñas, [f"{f['causa']}: {fmt_horas(f['horas'])} h ({fmt_pct(f['pct'])})" for _, f in datos.iterrows()],
              title="Causa", loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=10)
    ax.set_title("Composición de las horas computables por causa", fontsize=13)
    t = res.totales
    fig.text(0.5, 0.02,
             f"Total computable: {fmt_horas(total)} h (reclamos vinculados). Excluidas por cierre Cliente: "
             f"{fmt_horas(t.get('horas_excluidas'))} h. Reclamos no vinculados (fuera del universo): "
             f"{fmt_horas(t.get('horas_no_vinculadas'))} h, no incluidas.",
             ha="center", va="top", fontsize=8, color="#444444", wrap=True)
    return _guardar(fig, destino)


def magnitud_eventos(res, destino: Path, top: int = 15) -> Path | None:
    ev = res.eventos
    if ev.empty:
        return None
    datos = ev.assign(_h=pd.to_numeric(ev["horas_servicio"], errors="coerce").fillna(0.0)) \
              .sort_values("_h", ascending=False, kind="mergesort").head(top)[::-1]
    fig, ax = plt.subplots(figsize=(11, max(3.5, 0.5 * len(datos) + 1.5)))
    base = pd.Series(0.0, index=datos.index)
    for causa, col in m.COLUMNA_HORAS_POR_CAUSA.items():
        valores = pd.to_numeric(datos[col], errors="coerce").fillna(0.0)
        ax.barh(range(len(datos)), valores, left=base, color=f"#{COLORES_CAUSA[causa]}", label=causa)
        base = base + valores
    maximo = float(datos["_h"].max()) or 1.0
    for i, (_, f) in enumerate(datos.iterrows()):
        ax.text(f["_h"] + maximo * 0.01, i,
                f"{_servicios_txt(int(f['servicios_afectados']))} · suficiente {int(f['n_suficiente_solo'])} · "
                f"cruza {int(f['n_cruza_umbral'])} · determinante {int(f['n_determinante'])}",
                va="center", fontsize=8)
    ax.set_yticks(range(len(datos)), [f"{e} ({fmt_horas(h)} h)" for e, h in zip(datos["numero_evento"], datos["_h"])])
    ax.set_xlim(0, maximo * 1.75)
    ax.set_xlabel("Horas-servicio (suma de horas de cada reclamo en cada servicio afectado)")
    ax.set_title(f"Magnitud de los {len(datos)} mayores eventos", fontsize=13)
    ax.legend(loc="lower right", fontsize=8, title="Causa")
    return _guardar(fig, destino)
