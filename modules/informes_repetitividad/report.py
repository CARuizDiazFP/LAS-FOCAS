# Nombre de archivo: report.py
# Ubicación de archivo: modules/informes_repetitividad/report.py
# Descripción: Generación de archivos DOCX y PDF para el informe de repetitividad

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from modules.common.libreoffice_export import convert_to_pdf
from .config import MESES_ES, REP_TEMPLATE_PATH
from .schemas import Params, ResultadoRepetitividad

logger = logging.getLogger(__name__)


def _header_cell(cell, text: str) -> None:
    cell.text = text
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), "D9D9D9")
    cell._tc.get_or_add_tcPr().append(shading)


def _load_template() -> Document:
    """Carga la plantilla oficial o crea un documento vacío como fallback."""

    if REP_TEMPLATE_PATH.exists():
        try:
            return Document(str(REP_TEMPLATE_PATH))
        except Exception:  # pragma: no cover - logging
            logger.exception("action=load_template error path=%s", REP_TEMPLATE_PATH)
    else:
        logger.warning("Plantilla de repetitividad no encontrada en %s", REP_TEMPLATE_PATH)
    return Document()


def export_docx(
    data: ResultadoRepetitividad,
    periodo: Params,
    out_dir: str,
    df_raw: Optional[pd.DataFrame] = None,
) -> str:
    """Genera el archivo DOCX con el detalle completo de repetitividad.
    
    Args:
        data: Resultado calculado con servicios repetitivos
        periodo: Período del informe (mes/año)
        out_dir: Directorio de salida
        df_raw: DataFrame normalizado con todos los datos (opcional, para detalle enriquecido)
    """

    mes_nombre = MESES_ES[periodo.periodo_mes - 1].capitalize()
    doc = _load_template()

    # Título principal
    doc.add_heading(
        f"Informe de Repetitividad — {mes_nombre} {periodo.periodo_anio}",
        level=1,
    )

    # Resumen ejecutivo
    doc.add_paragraph(
        f"Servicios analizados: {data.total_servicios} | "
        f"Servicios con repetitividad: {data.total_repetitivos} "
        f"({100 * data.total_repetitivos / max(data.total_servicios, 1):.1f}%)"
    )

    # Si no tenemos el DataFrame raw, generamos una tabla simple (modo legacy)
    if df_raw is None or df_raw.empty:
        _export_simple_table(doc, data)
    else:
        _export_detailed_report(doc, data, df_raw)

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    docx_path = out_dir_path / f"repetitividad_{periodo.periodo_anio}{periodo.periodo_mes:02d}.docx"
    doc.save(docx_path)
    logger.info("action=export_docx path=%s items=%s", docx_path, len(data.items))
    return str(docx_path)


def _export_simple_table(doc: Document, data: ResultadoRepetitividad) -> None:
    """Genera una tabla simple con el resumen de repetitividad (fallback)."""
    
    table = doc.add_table(rows=1, cols=3)
    table.style = 'Table Grid'
    
    hdr_cells = table.rows[0].cells
    _header_cell(hdr_cells[0], "Servicio")
    _header_cell(hdr_cells[1], "Casos Repetidos")
    _header_cell(hdr_cells[2], "Detalles/IDs")

    for item in data.items:
        row = table.add_row().cells
        row[0].text = item.servicio
        row[1].text = str(item.casos)
        row[2].text = ", ".join(item.detalles[:10])  # Limitar a 10 IDs
        if item.casos >= 4:
            row[1].paragraphs[0].runs[0].bold = True

    for row in table.rows:
        for cell in row.cells:
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT


def _export_detailed_report(doc: Document, data: ResultadoRepetitividad, df: pd.DataFrame) -> None:
    """Genera un informe detallado al estilo del legacy, con tablas por servicio."""
    
    # Agrupar por servicio y generar una sección para cada uno
    for item in data.items:
        servicio_id = item.servicio
        
        # Filtrar los casos de este servicio
        df_servicio = df[df["SERVICIO"] == servicio_id].copy()
        
        if df_servicio.empty:
            continue
        
        # Obtener información del servicio
        primer_caso = df_servicio.iloc[0]
        cliente = primer_caso.get("CLIENTE", "N/A")
        tipo_servicio = primer_caso.get("TIPO_SERVICIO", "Servicio")
        
        # Encabezado del servicio
        doc.add_heading(
            f"{tipo_servicio}: {servicio_id} - {cliente}",
            level=2,
        )
        
        # Crear tabla de detalle
        # Columnas: Reclamo, Tipo Solución, Fecha Inicio, Fecha Cierre, Horas, Descripción
        num_cols = 6
        table = doc.add_table(rows=1, cols=num_cols)
        table.style = 'Table Grid'
        
        # Encabezados
        hdr_cells = table.rows[0].cells
        headers = [
            "Reclamo",
            "Tipo Solución",
            "Fecha Inicio",
            "Fecha Cierre",
            "Horas Netas",
            "Descripción Solución",
        ]
        for idx, header in enumerate(headers):
            _header_cell(hdr_cells[idx], header)
        
        # Llenar filas con datos
        for _, fila in df_servicio.iterrows():
            row_cells = table.add_row().cells
            
            # Número de reclamo/ID
            id_caso = fila.get("ID_SERVICIO", fila.name)
            row_cells[0].text = str(id_caso)
            
            # Tipo de solución
            tipo_solucion = fila.get("Tipo Solución Reclamo", "-")
            row_cells[1].text = str(tipo_solucion) if pd.notna(tipo_solucion) else "-"
            
            # Fecha de inicio
            fecha_inicio = fila.get("FECHA_INICIO") or fila.get("FECHA")
            if pd.notna(fecha_inicio):
                try:
                    row_cells[2].text = pd.to_datetime(fecha_inicio).strftime("%d/%m/%Y %H:%M")
                except Exception:
                    row_cells[2].text = str(fecha_inicio)
            else:
                row_cells[2].text = "-"
            
            # Fecha de cierre
            fecha_cierre = fila.get("FECHA")
            if pd.notna(fecha_cierre):
                try:
                    row_cells[3].text = pd.to_datetime(fecha_cierre).strftime("%d/%m/%Y %H:%M")
                except Exception:
                    row_cells[3].text = str(fecha_cierre)
            else:
                row_cells[3].text = "-"
            
            # Horas netas
            horas = fila.get("Horas Netas Problema Reclamo") or fila.get("Horas Netas Reclamo")
            if pd.notna(horas):
                if isinstance(horas, pd.Timedelta):
                    total_min = int(horas.total_seconds() // 60)
                    h = total_min // 60
                    m = total_min % 60
                    row_cells[4].text = f"{h:02d}:{m:02d}"
                else:
                    row_cells[4].text = str(horas)
            else:
                row_cells[4].text = "-"
            
            # Descripción de solución
            desc = fila.get("Descripción Solución Reclamo", "-")
            if pd.notna(desc):
                # Limitar a 200 caracteres para no romper el layout
                desc_text = str(desc)[:200]
                row_cells[5].text = desc_text
            else:
                row_cells[5].text = "-"
        
        # Ajustar tamaño de fuente de la tabla (opcional, para mejor lectura)
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(9)
        
        # Espacio antes de la siguiente sección
        doc.add_paragraph()


def maybe_export_pdf(docx_path: str, soffice_bin: Optional[str]) -> Optional[str]:
    """Convierte el DOCX a PDF si LibreOffice está disponible."""

    if not soffice_bin:
        logger.debug("action=maybe_export_pdf reason=missing_binary")
        return None

    binary_path = Path(soffice_bin)
    if not binary_path.exists():
        logger.info(
            "action=maybe_export_pdf reason=binary_not_found soffice_bin=%s",
            soffice_bin,
        )
        return None

    try:
        return convert_to_pdf(docx_path, soffice_bin)
    except Exception:  # pragma: no cover - logging
        logger.exception("action=maybe_export_pdf error")
        return None
