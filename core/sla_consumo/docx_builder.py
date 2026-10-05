# Nombre de archivo: docx_builder.py
# Ubicación de archivo: core/sla_consumo/docx_builder.py
# Descripción: DOCX ejecutivo (agotados/excedidos y eventos principales) y DOCX exhaustivo del informe SLA consumido

from __future__ import annotations

import os
from pathlib import Path

from core.sla_consumo import charts
from core.sla_consumo import docx_comun as dc
from core.sla_consumo import metricas as m

TOP_EVENTOS_DEFAULT = 20
_ENV_TOP_EVENTOS = "SLA_CONSUMO_TOP_EVENTOS"

_SIN_RECLAMOS = ["servicio_id", "nombre_cliente", "tipo_servicio", "sla_prometido", "presupuesto_h", "estado"]
_RECLAMOS_SIN_EVENTO = ["servicio_id", "numero_reclamo", "nombre_cliente", "horas_computables", "pct_aporte_real",
                        "consumo_total_servicio", "estado_servicio", "suficiente_solo", "cruza_umbral",
                        "determinante_al_excluir", "participa_en_agotado_o_excedido"]
_INCONSISTENCIAS = ["tipo", "numero_evento", "numero_reclamo", "servicio_id", "detalle"]
_NO_VINCULADOS = ["numero_reclamo", "numero_evento", "numero_linea", "nombre_cliente",
                  "fecha_inicio", "horas_netas", "tipo_solucion", "grupo_cierre"]


def top_eventos_config() -> int:
    """Cantidad de eventos principales del DOCX ejecutivo: env SLA_CONSUMO_TOP_EVENTOS (entero > 0) o 20."""
    try:
        valor = int(os.environ.get(_ENV_TOP_EVENTOS, "").strip())
    except ValueError:
        return TOP_EVENTOS_DEFAULT
    return valor if valor > 0 else TOP_EVENTOS_DEFAULT


def _inicio(res, destino: Path, titulo: str):
    destino.parent.mkdir(parents=True, exist_ok=True)
    graficos = destino.parent / f"{destino.stem}_graficos"
    doc = dc.nuevo_documento()
    dc.encabezado(doc, res, titulo)
    dc.resumen(doc, res)
    dc.leyendas(doc)
    dc.torta_global(doc, res, graficos)
    return doc, graficos


def _fichas(doc, res, servicios, vacio: str) -> None:
    if servicios.empty:
        dc.parrafo(doc, vacio)
        return
    fichas = dc.FichasServicio(res)
    for _, fila in servicios.iterrows():
        fichas.escribir(doc, fila)


def construir_docx_ejecutivo(res, destino: Path, top_eventos: int | None = None) -> Path:
    n = top_eventos if top_eventos and top_eventos > 0 else top_eventos_config()
    doc, graficos = _inicio(res, destino, "Informe de SLA consumido — Ejecutivo")

    dc.titulo(doc, "Eventos principales", 1)
    dc.parrafo(doc, f"Ranking por horas-servicio de impacto, descendente; se muestran los primeros {n} "
                      f"(configurable con {_ENV_TOP_EVENTOS})")
    ruta = charts.magnitud_eventos(res, graficos / "magnitud_eventos.png", top=n)
    if ruta is not None:
        dc.imagen(doc, ruta, 24)
    dc.tabla_eventos(doc, dc.eventos_ordenados(res).head(n))

    dc.titulo(doc, "Servicios agotados o excedidos", 1)
    agotados = res.servicios[res.servicios["estado"].isin(m.ESTADOS_AGOTADO_O_EXCEDIDO)]
    _fichas(doc, res, agotados, "Ningún servicio con presupuesto agotado o SLA excedido.")
    doc.save(destino)
    return destino


def construir_docx_exhaustivo(res, destino: Path) -> Path:
    doc, _ = _inicio(res, destino, "Informe de SLA consumido — Exhaustivo")

    dc.titulo(doc, "Eventos", 1)
    dc.parrafo(doc, "Todos los eventos reales, por horas-servicio de impacto descendente.")
    dc.tabla_eventos(doc, dc.eventos_ordenados(res))

    dc.titulo(doc, "Servicios con reclamos", 1)
    _fichas(doc, res, res.servicios[res.servicios["reclamos"] > 0], "Ningún servicio con reclamos vinculados.")

    dc.titulo(doc, "Servicios sin reclamos", 1)
    dc.tabla_df(doc, res.servicios[res.servicios["reclamos"] == 0], _SIN_RECLAMOS, [1.2, 3.0, 1.6, 1.0, 1.0, 1.2])

    dc.titulo(doc, "Reclamos sin evento", 1)
    dc.tabla_df(doc, res.reclamos_sin_evento, _RECLAMOS_SIN_EVENTO,
                [1.0, 1.0, 2.6, 1.0, 1.0, 1.0, 1.2, 1.0, 1.0, 1.1, 1.0])

    dc.titulo(doc, "Inconsistencias", 1)
    dc.tabla_df(doc, res.inconsistencias, _INCONSISTENCIAS, [2.0, 1.0, 1.0, 1.0, 5.0])

    dc.titulo(doc, "Reclamos no vinculados", 1)
    dc.tabla_df(doc, res.no_vinculados, _NO_VINCULADOS, [1.0, 1.0, 1.0, 2.4, 1.4, 1.0, 2.4, 1.4])
    doc.save(destino)
    return destino
