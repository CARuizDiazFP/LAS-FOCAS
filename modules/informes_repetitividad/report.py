# Nombre de archivo: report.py
# Ubicación de archivo: modules/informes_repetitividad/report.py
# Descripción: Generación de archivos DOCX y PDF para el informe de repetitividad

import logging
from pathlib import Path
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

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


def export_docx(data: ResultadoRepetitividad, periodo: Params, out_dir: str) -> str:
    """Genera el archivo DOCX con la tabla de repetitividad."""

    mes_nombre = MESES_ES[periodo.periodo_mes - 1].capitalize()
    doc = _load_template()

    doc.add_heading(
        f"Informe de Repetitividad — {mes_nombre} {periodo.periodo_anio}",
        level=1,
    )

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
