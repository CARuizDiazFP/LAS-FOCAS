# Nombre de archivo: legacy_report.py
# Ubicación de archivo: core/sla/legacy_report.py
# Descripción: Render del informe SLA mensual (plantilla heredada) a partir de core/sla/informe.py, sin cálculo propio
"""Render del informe SLA sobre la plantilla heredada (Sandy).

Desde P25 no lee Excel ni calcula: recibe un ``InformeSla`` (``core/sla/informe.py``), cuyas horas y SLA
salen del motor de SLA consumido (columna P). Sirve al modo Excel y al modo base del panel, a
``/api/flows/sla`` y a ``POST /reports/sla``. ``identificar_excel`` sigue acá: clasifica los archivos
subidos (Servicios vs Reclamos) en el panel.
"""

from __future__ import annotations

import copy
import io
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Sequence

import pandas as pd
from docx import Document
from docx.oxml.shared import OxmlElement
from docx.table import Table
from docx.text.paragraph import Paragraph

from core.docx_utils.text_replace import replace_text_everywhere
from core.services.office_client import intentar_pdf
from core.sla.config import MESES_ES, REPORTS_DIR, SLA_TEMPLATE_PATH
from core.sla.informe import InformeSla, ServicioInforme
from core.sla_consumo.parser import _normalize

logger = logging.getLogger(__name__)


@dataclass
class DocumentoSLA:
    """Rutas de salida del informe."""

    docx: Path
    pdf: Optional[Path]
    pdf_error: Optional[str] = None  # motivo si se pidió PDF y no se generó


def _copy_cell_borders(source_cell, target_cell) -> None:
    """Copia los bordes de una celda a otra preservando el formato."""
    try:
        source_tc = source_cell._element
        target_tc = target_cell._element
        
        # Obtener tcPr (table cell properties) de la celda origen
        source_tcPr = source_tc.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tcPr')
        if source_tcPr is None:
            return
        
        # Buscar tcBorders en la celda origen
        source_borders = source_tcPr.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tcBorders')
        if source_borders is None:
            return
        
        # Obtener o crear tcPr en la celda destino
        target_tcPr = target_tc.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tcPr')
        if target_tcPr is None:
            target_tcPr = OxmlElement('w:tcPr')
            target_tc.insert(0, target_tcPr)
        
        # Eliminar bordes existentes en destino
        existing_borders = target_tcPr.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tcBorders')
        if existing_borders is not None:
            target_tcPr.remove(existing_borders)
        
        # Copiar los bordes
        target_tcPr.append(copy.deepcopy(source_borders))
    except Exception as exc:  # noqa: BLE001
        logger.debug("action=copy_cell_borders error=%s", exc)


def _set_cell_text(cell, new_text: str) -> None:
    """Reemplaza el texto de una celda preservando su formato original."""
    if not cell.paragraphs:
        cell.text = new_text
        return
    
    # Preservar formato del primer párrafo y su primer run
    paragraph = cell.paragraphs[0]
    if not paragraph.runs:
        cell.text = new_text
        return
    
    # Mantener formato del primer run
    first_run = paragraph.runs[0]
    run_format = {
        'bold': first_run.bold,
        'italic': first_run.italic,
        'underline': first_run.underline,
        'font_name': first_run.font.name if first_run.font else None,
        'font_size': first_run.font.size if first_run.font else None,
        'font_color': first_run.font.color.rgb if first_run.font and first_run.font.color else None,
    }
    
    # Limpiar todos los runs del párrafo
    for run in paragraph.runs:
        run.text = ""
    
    # Limpiar párrafos adicionales
    for i in range(len(cell.paragraphs) - 1, 0, -1):
        p = cell.paragraphs[i]
        p._element.getparent().remove(p._element)
    
    # Crear nuevo run con el texto y formato preservado
    run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
    run.text = new_text
    if run_format['bold'] is not None:
        run.bold = run_format['bold']
    if run_format['italic'] is not None:
        run.italic = run_format['italic']
    if run_format['underline'] is not None:
        run.underline = run_format['underline']
    if run.font and run_format['font_name']:
        run.font.name = run_format['font_name']
    if run.font and run_format['font_size']:
        run.font.size = run_format['font_size']
    if run.font and run_format['font_color']:
        run.font.color.rgb = run_format['font_color']


# Encabezados mínimos para reconocer cada Excel subido (el parseo real es core/sla_consumo/parser.py).
SERVICIOS_REQUIRED: Dict[str, Sequence[str]] = {
    "tipo_servicio": ("tipo servicio",),
    "numero_linea": ("numero linea", "numero servicio", "numero primer servicio"),
    "nombre_cliente": ("nombre cliente", "cliente"),
    "horas_total": ("horas reclamos todos", "horas reclamos"),
    "sla": ("sla", "sla entregado", "% sla", "disponibilidad", "% disponibilidad"),
}

RECLAMOS_REQUIRED: Dict[str, Sequence[str]] = {
    "numero_linea": ("numero linea", "numero de linea", "numero linea reclamo", "numero primer servicio"),
    "ticket": ("numero reclamo", "n° reclamo", "n° de ticket", "numero ticket", "ticket"),
    # IMPORTANTE: Usar "Horas Netas Cierre Problema Reclamo" (columna P)
    "horas": ("horas netas cierre problema reclamo",),
    "tipo_solucion": ("tipo solucion reclamo", "tipo solución reclamo", "tipo solucion", "causa", "tipo"),
    "fecha_inicio": ("fecha inicio reclamo", "fecha inicio problema reclamo", "inicio"),
}


def _read_excel(content: bytes) -> pd.DataFrame:
    dataframe = pd.read_excel(io.BytesIO(content))
    dataframe.columns = dataframe.columns.astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    return dataframe


def identificar_excel(content: bytes) -> str:
    df = _read_excel(content)
    normalized = {_normalize(col) for col in df.columns}
    is_servicios = all(any(candidate in normalized for candidate in group) for group in SERVICIOS_REQUIRED.values())
    is_reclamos = all(any(candidate in normalized for candidate in group) for group in RECLAMOS_REQUIRED.values())
    if is_servicios and not is_reclamos:
        return "servicios"
    if is_reclamos and not is_servicios:
        return "reclamos"
    if is_servicios and is_reclamos:
        # Prefer reclamos si contiene más columnas informativas propias de tickets
        reclamo_specific = set(RECLAMOS_REQUIRED["ticket"]) | set(RECLAMOS_REQUIRED["tipo_solucion"])
        if any(candidate in normalized for candidate in reclamo_specific):
            return "reclamos"
        return "servicios"
    raise ValueError("No se pudo identificar el Excel (servicios vs reclamos)")


def generar_documento(
    informe: InformeSla,
    *,
    incluir_pdf: bool = False,
    reports_dir: Path | None = None,
    eventos: str = "",
    conclusion: str = "",
    propuesta: str = "",
) -> DocumentoSLA:
    if not SLA_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Plantilla SLA no encontrada: {SLA_TEMPLATE_PATH}")

    doc = Document(str(SLA_TEMPLATE_PATH))
    # Placeholders del template: "XXXXX" -> "Octubre " y "2023" -> año.
    replace_text_everywhere(doc, {
        "XXXXX": f"{MESES_ES[informe.mes - 1].capitalize()} ",
        "2023": str(informe.anio),
    })

    if len(doc.tables) < 3:
        raise ValueError("La plantilla SLA debe contener al menos tres tablas base")

    cuerpo = doc._body._element
    tabla_principal = doc.tables[0]
    tabla_servicio_tpl = copy.deepcopy(doc.tables[1]._tbl)
    tabla_detalle_tpl = copy.deepcopy(doc.tables[2]._tbl)

    idx_tabla2 = cuerpo.index(doc.tables[1]._tbl)
    idx_tabla3 = cuerpo.index(doc.tables[2]._tbl)

    bloques_texto: list[tuple[str, Optional[str]]] = []
    for element in list(cuerpo[idx_tabla2 + 1 : idx_tabla3]):
        if element.tag.endswith("p"):
            parrafo = Paragraph(element, doc)
            bloques_texto.append((parrafo.text, parrafo.style.name if parrafo.style else None))
        cuerpo.remove(element)

    cuerpo.remove(doc.tables[2]._tbl)
    cuerpo.remove(doc.tables[1]._tbl)

    _rellenar_tabla_principal(tabla_principal, informe.servicios)

    for indice, servicio in enumerate(informe.servicios):
        elem_servicio = copy.deepcopy(tabla_servicio_tpl)
        cuerpo.append(elem_servicio)
        _completar_tabla_servicio(doc.tables[-1], servicio)

        insert_idx = cuerpo.index(elem_servicio)
        _insertar_bloques(doc, cuerpo, insert_idx, bloques_texto, eventos, conclusion, propuesta)

        elem_detalle = copy.deepcopy(tabla_detalle_tpl)
        cuerpo.insert(insert_idx + len(bloques_texto) + 1, elem_detalle)
        _completar_tabla_detalle(doc.tables[-1], servicio)

        if indice < len(informe.servicios) - 1:
            salto = doc.add_page_break()
            cuerpo.remove(salto._p)
            cuerpo.insert(cuerpo.index(elem_detalle) + 1, salto._p)

    destino = Path(reports_dir or REPORTS_DIR) / "sla" / f"{informe.anio:04d}{informe.mes:02d}"
    destino.mkdir(parents=True, exist_ok=True)
    docx_path = destino / f"InformeSLA_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    doc.save(docx_path)

    pdf_path: Optional[Path] = None
    pdf_error: Optional[str] = None
    if incluir_pdf:
        pdf_path, pdf_error = intentar_pdf(docx_path, contexto="sla_legacy_report")

    return DocumentoSLA(docx=docx_path, pdf=pdf_path, pdf_error=pdf_error)


def _horas_reclamos(servicio: ServicioInforme) -> list[float]:
    # Redondeo a 4 decimales por reclamo, como el informe heredado (el total en HHH:MM:SS no cambia de segundo).
    return [round(float(h), 4) for h in servicio.reclamos["horas_computables"]]


def _fila_con_bordes(tabla: Table, celdas_template) -> list:
    nueva = tabla.add_row().cells
    for i, celda in enumerate(nueva):
        if i < len(celdas_template):
            _copy_cell_borders(celdas_template[i], celda)
    return nueva


def _rellenar_tabla_principal(tabla: Table, servicios: Sequence[ServicioInforme]) -> None:
    while len(tabla.rows) > 1:
        tabla._tbl.remove(tabla.rows[1]._tr)
    template = tabla.rows[0].cells
    for servicio in servicios:
        celdas = _fila_con_bordes(tabla, template)
        _set_cell_text(celdas[0], servicio.tipo_servicio or "")
        _set_cell_text(celdas[1], servicio.linea_visible)
        _set_cell_text(celdas[2], servicio.nombre_cliente or "")
        _set_cell_text(celdas[3], _formatear_horas_totales(round(sum(_horas_reclamos(servicio)), 4)))
        _set_cell_text(celdas[4], _sla_texto(servicio.sla_entregado))


def _completar_tabla_servicio(tabla: Table, servicio: ServicioInforme) -> None:
    valores = {
        "servicio": f"{servicio.tipo_servicio or ''} {servicio.servicio_id}".strip(),
        "cliente": servicio.nombre_cliente or "",
        "ticket": ", ".join(dict.fromkeys(str(t) for t in servicio.reclamos["numero_reclamo"].dropna())),
        "sla": _sla_texto(servicio.sla_entregado),
        "domicilio": servicio.domicilio or "",
    }

    for fila in tabla.rows:
        for idx, celda in enumerate(fila.cells):
            contenido = celda.text.lower()
            for clave, valor in valores.items():
                if clave in contenido:
                    if len(fila.cells) > idx + 1 and not fila.cells[idx + 1].text.strip():
                        # Label en negrita en la celda actual, valor en la siguiente.
                        label_celda = fila.cells[idx]
                        label_text = label_celda.text
                        label_celda.text = ""
                        for paragraph in label_celda.paragraphs:
                            paragraph.add_run(label_text).bold = True
                        fila.cells[idx + 1].text = valor
                    else:
                        # "Label: valor" en la misma celda, label en negrita.
                        base = celda.text.split(":")[0].strip(": ")
                        celda.text = ""
                        for paragraph in celda.paragraphs:
                            paragraph.add_run(f"{base}:").bold = True
                            if valor:
                                paragraph.add_run(f" {valor}").bold = False
                    break


def _completar_tabla_detalle(tabla: Table, servicio: ServicioInforme) -> None:
    template = list(tabla.rows[0].cells) if len(tabla.rows) > 0 else []
    while len(tabla.rows) > 1:
        tabla._tbl.remove(tabla.rows[1]._tr)

    horas = _horas_reclamos(servicio)
    for reclamo, horas_reclamo in zip(servicio.reclamos.itertuples(index=False), horas):
        fila = _fila_con_bordes(tabla, template)
        _set_cell_text(fila[0], str(reclamo.numero_linea or ""))
        _set_cell_text(fila[1], str(reclamo.numero_reclamo))
        _set_cell_text(fila[2], f"{horas_reclamo:.2f}")
        _set_cell_text(fila[3], str(reclamo.tipo_solucion or ""))
        _set_cell_text(fila[4], _formatear_fecha(reclamo.fecha_inicio))
        if len(fila) > 5:
            _set_cell_text(fila[5], str(reclamo.descripcion_solucion or ""))

    total = round(sum(horas), 4)
    if total:
        totales = _fila_con_bordes(tabla, template)
        _set_cell_text(totales[0], "Total")
        _set_cell_text(totales[2], f"{total:.2f}")


def _insertar_bloques(
    doc: Document,
    cuerpo,
    idx: int,
    bloques: Sequence[tuple[str, Optional[str]]],
    eventos: str,
    conclusion: str,
    propuesta: str,
) -> None:
    if not bloques:
        bloques = [
            ("Eventos sucedidos de mayor impacto en SLA:", None),
            ("Conclusión:", None),
            ("Propuesta de mejora:", None),
        ]
    for base, estilo in bloques:
        texto = base
        llave = base.lower()
        if "evento" in llave:
            texto = base.rstrip() + (" " + eventos.strip() if eventos else "")
        elif "conclusion" in llave or "conclusión" in llave:
            texto = base.rstrip() + (" " + conclusion.strip() if conclusion else "")
        elif "propuesta" in llave:
            texto = base.rstrip() + (" " + propuesta.strip() if propuesta else "")
        parrafo = doc.add_paragraph(texto, style=estilo)
        cuerpo.remove(parrafo._p)
        cuerpo.insert(idx + 1, parrafo._p)
        idx += 1


def _sla_texto(valor) -> str:
    if valor is None or pd.isna(valor):
        return ""
    try:
        return f"{float(valor) * 100:.2f}%"
    except Exception:  # noqa: BLE001
        return str(valor)


def _formatear_horas_totales(horas_decimal: float) -> str:
    """Convierte horas decimales a formato HHH:MM:SS."""
    total_segundos = int(horas_decimal * 3600)
    horas, resto = divmod(total_segundos, 3600)
    minutos, segundos = divmod(resto, 60)
    return f"{horas:03d}:{minutos:02d}:{segundos:02d}"


def _formatear_fecha(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    try:
        fecha = pd.to_datetime(valor)
    except Exception:  # noqa: BLE001
        return str(valor)
    if pd.isna(fecha):
        return ""
    meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    return f"{fecha.day:02d}-{meses[fecha.month - 1]}-{str(fecha.year)[2:]}"
