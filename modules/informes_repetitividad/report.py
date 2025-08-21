# Nombre de archivo: report.py
# Ubicación de archivo: modules/informes_repetitividad/report.py
# Descripción: Generación de archivos DOCX y PDF para el informe de repetitividad

import logging
import subprocess
from pathlib import Path
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .config import MESES_ES
from .schemas import Params, ResultadoRepetitividad

logger = logging.getLogger(__name__)


def _header_cell(cell, text: str) -> None:
    cell.text = text
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), "D9D9D9")
    cell._tc.get_or_add_tcPr().append(shading)


def export_docx(data: ResultadoRepetitividad, periodo: Params, out_dir: str) -> str:
    """Genera el archivo DOCX con la tabla de repetitividad."""
    mes_nombre = MESES_ES[periodo.periodo_mes - 1].capitalize()
    doc = Document()
    doc.add_heading(f"Informe de Repetitividad — {mes_nombre} {periodo.periodo_anio}", level=1)

    doc.add_paragraph(
        f"Servicios analizados: {data.total_servicios} | Servicios con repetitividad: {data.total_repetitivos}",
    )

    table = doc.add_table(rows=1, cols=3)
    hdr_cells = table.rows[0].cells
    _header_cell(hdr_cells[0], "Servicio")
    _header_cell(hdr_cells[1], "Casos Repetidos")
    _header_cell(hdr_cells[2], "Detalles/IDs")

    for item in data.items:
        row = table.add_row().cells
        row[0].text = item.servicio
        row[1].text = str(item.casos)
        row[2].text = ", ".join(item.detalles)
        if item.casos >= 4:
            row[1].paragraphs[0].runs[0].bold = True

    for row in table.rows:
        for cell in row.cells:
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    docx_path = out_dir_path / f"repetitividad_{periodo.periodo_anio}{periodo.periodo_mes:02d}.docx"
    doc.save(docx_path)
    logger.info("action=export_docx path=%s", docx_path)
    return str(docx_path)


def maybe_export_pdf(docx_path: str, out_dir: str, soffice_bin: Optional[str]) -> Optional[str]:
    """Convierte el DOCX a PDF si LibreOffice está disponible."""
    if not soffice_bin:
        return None

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                soffice_bin,
                "--headless",
                "--convert-to",
                "pdf",
                docx_path,
                "--outdir",
                str(out_dir_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as exc:  # pragma: no cover - logging
        logger.exception("action=maybe_export_pdf error=%s", exc)
        return None

    pdf_path = Path(out_dir) / (Path(docx_path).stem + ".pdf")
    if pdf_path.exists():
        logger.info("action=maybe_export_pdf path=%s", pdf_path)
        return str(pdf_path)
    return None
