# Nombre de archivo: libreoffice_export.py
# Ubicación de archivo: modules/common/libreoffice_export.py
# Descripción: Conversión de archivos DOCX a PDF usando LibreOffice en modo headless

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def convert_to_pdf(docx_path: str, soffice_bin: str) -> str:
    """Convierte un DOCX a PDF utilizando LibreOffice.

    Parameters
    ----------
    docx_path: str
        Ruta del archivo DOCX de origen.
    soffice_bin: str
        Ruta al ejecutable de LibreOffice (`soffice`).

    Returns
    -------
    str
        Ruta absoluta del PDF generado.

    Raises
    ------
    Exception
        Propaga cualquier error ocurrido durante la conversión.
    """
    out_dir = Path(docx_path).parent
    if not shutil.which(soffice_bin):
        logger.error(
            "action=convert_to_pdf error=soffice_no_encontrado path=%s", soffice_bin
        )
        raise FileNotFoundError(soffice_bin)
    try:
        subprocess.run(
            [
                soffice_bin,
                "--headless",
                "--convert-to",
                "pdf",
                docx_path,
                "--outdir",
                str(out_dir),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:  # pragma: no cover - logging
        logger.exception(
            "action=convert_to_pdf error=soffice_no_encontrado path=%s", soffice_bin
        )
        raise
    except subprocess.CalledProcessError as exc:  # pragma: no cover - logging
        logger.exception(
            "action=convert_to_pdf error=conversion_fallida code=%s stderr=%s",
            exc.returncode,
            exc.stderr.decode(errors="ignore") if exc.stderr else "",
        )
        raise
    except Exception as exc:  # pragma: no cover - logging
        logger.exception("action=convert_to_pdf error_desconocido=%s", exc)
        raise

    pdf_path = out_dir / (Path(docx_path).stem + ".pdf")
    if not pdf_path.exists():  # pragma: no cover - sanity check
        raise FileNotFoundError(f"No se generó el PDF en {pdf_path}")
    logger.info("action=convert_to_pdf path=%s", pdf_path)
    return str(pdf_path)

