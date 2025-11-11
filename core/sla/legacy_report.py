# Nombre de archivo: legacy_report.py
# Ubicación de archivo: core/sla/legacy_report.py
# Descripción: Generación del informe SLA replicando el comportamiento heredado
"""Render del informe SLA siguiendo el flujo legacy (Sandy)."""

from __future__ import annotations

import copy
import io
import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

import pandas as pd
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from core.docx_utils.text_replace import replace_title_everywhere
from core.sla.config import REPORTS_DIR, SLA_TEMPLATE_PATH, SOFFICE_BIN
from core.sla.report import DocumentoSLA
from modules.common.libreoffice_export import convert_to_pdf

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    cleaned = unicodedata.normalize("NFKD", str(text)).encode("ASCII", "ignore").decode()
    cleaned = cleaned.replace("/", " ").replace("_", " ")
    return " ".join(cleaned.lower().strip().split())


SERVICIOS_REQUIRED: Dict[str, set[str]] = {
    "tipo_servicio": {"tipo servicio"},
    "numero_linea": {"numero linea", "numero primer servicio", "numero servicio"},
    "nombre_cliente": {"nombre cliente", "cliente"},
    "horas_total": {"horas reclamos todos", "horas reclamos"},
    "sla": {"sla", "sla entregado", "% sla", "disponibilidad", "% disponibilidad"},
}

SERVICIOS_OPTIONAL: Dict[str, set[str]] = {
    "domicilio": {"direccion servicio", "domicilio", "direccion"},
}

RECLAMOS_REQUIRED: Dict[str, set[str]] = {
    "numero_linea": {"numero linea", "numero primer servicio", "numero de linea"},
    "ticket": {"numero reclamo", "n° reclamo", "n° de ticket", "numero ticket", "ticket"},
    "horas": {"horas netas reclamo", "horas netas problema reclamo", "horas netas", "duracion"},
    "tipo_solucion": {"tipo solucion reclamo", "tipo solución reclamo", "tipo solucion", "causa", "tipo"},
    "fecha_inicio": {"fecha inicio reclamo", "fecha inicio problema reclamo", "inicio"},
}

RECLAMOS_OPTIONAL: Dict[str, set[str]] = {
    "fecha_cierre": {"fecha cierre reclamo", "fecha cierre problema reclamo", "cierre"},
    "descripcion": {"descripcion", "descripcion solucion reclamo", "descripción solución reclamo"},
}


@dataclass(slots=True)
class _ExcelDataset:
    dataframe: pd.DataFrame
    columns: Dict[str, str]
    optional: Dict[str, Optional[str]]


def _match_headers(
    columns: Iterable[str],
    required: Dict[str, set[str]],
    optional: Dict[str, set[str]] | None = None,
) -> tuple[Dict[str, str], Dict[str, Optional[str]]]:
    normalized = {_normalize(col): col for col in columns}
    resolved: Dict[str, str] = {}
    for key, synonyms in required.items():
        found = next((normalized[label] for label in normalized if label in synonyms), None)
        if not found:
            raise ValueError(key)
        resolved[key] = found

    resolved_optional: Dict[str, Optional[str]] = {}
    if optional:
        for key, synonyms in optional.items():
            found = next((normalized[label] for label in normalized if label in synonyms), None)
            resolved_optional[key] = found
    return resolved, resolved_optional


def _read_excel(content: bytes) -> pd.DataFrame:
    dataframe = pd.read_excel(io.BytesIO(content))
    dataframe.columns = dataframe.columns.astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    return dataframe


def load_servicios_excel(content: bytes) -> _ExcelDataset:
    df = _read_excel(content)
    try:
        resolved, optional = _match_headers(df.columns, SERVICIOS_REQUIRED, SERVICIOS_OPTIONAL)
    except ValueError as exc:
        missing = str(exc)
        raise ValueError(f"Faltan columnas en Excel de servicios: {missing.upper()}") from exc

    df = df.copy()
    sla_col = resolved["sla"]
    df[sla_col] = df[sla_col].apply(_parse_sla_value)
    horas_col = resolved["horas_total"]
    df[horas_col] = df[horas_col].apply(_to_timedelta).apply(_fmt_td)
    df.sort_values(resolved["sla"], ascending=False, inplace=True)
    return _ExcelDataset(df.reset_index(drop=True), resolved, optional)


def load_reclamos_excel(content: bytes) -> _ExcelDataset:
    df = _read_excel(content)
    try:
        resolved, optional = _match_headers(df.columns, RECLAMOS_REQUIRED, RECLAMOS_OPTIONAL)
    except ValueError as exc:
        missing = str(exc)
        raise ValueError(f"Faltan columnas en Excel de reclamos: {missing.upper()}") from exc

    df = df.copy()
    horas_col = resolved["horas"]
    df[horas_col] = df[horas_col].apply(_horas_decimal)
    fecha_col = resolved["fecha_inicio"]
    df[fecha_col] = df[fecha_col].apply(_to_datetime)
    cierre_col = optional.get("fecha_cierre")
    if cierre_col:
        df[cierre_col] = df[cierre_col].apply(_to_datetime)
    df.sort_values([resolved["numero_linea"], fecha_col], inplace=True)
    return _ExcelDataset(df.reset_index(drop=True), resolved, optional)


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
        reclamo_specific = RECLAMOS_REQUIRED["ticket"].union(RECLAMOS_REQUIRED["tipo_solucion"])
        if any(candidate in normalized for candidate in reclamo_specific):
            return "reclamos"
        return "servicios"
    raise ValueError("No se pudo identificar el Excel (servicios vs reclamos)")


def generate_from_excel_pair(
    servicios_content: bytes,
    reclamos_content: bytes,
    *,
    mes: int,
    anio: int,
    incluir_pdf: bool = False,
    reports_dir: Path | None = None,
    soffice_bin: Optional[str] = None,
    eventos: str = "",
    conclusion: str = "",
    propuesta: str = "",
) -> DocumentoSLA:
    servicios = load_servicios_excel(servicios_content)
    reclamos = load_reclamos_excel(reclamos_content)
    return _render_document(
        servicios,
        reclamos,
        mes=mes,
        anio=anio,
        incluir_pdf=incluir_pdf,
        reports_dir=reports_dir or REPORTS_DIR,
        soffice_bin=soffice_bin or SOFFICE_BIN,
        eventos=eventos,
        conclusion=conclusion,
        propuesta=propuesta,
    )


def _render_document(
    servicios: _ExcelDataset,
    reclamos: _ExcelDataset,
    *,
    mes: int,
    anio: int,
    incluir_pdf: bool,
    reports_dir: Path,
    soffice_bin: Optional[str],
    eventos: str,
    conclusion: str,
    propuesta: str,
) -> DocumentoSLA:
    if not SLA_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Plantilla SLA no encontrada: {SLA_TEMPLATE_PATH}")

    doc = Document(str(SLA_TEMPLATE_PATH))
    replace_title_everywhere(doc, f"Informe SLA — {mes:02d}/{anio}")

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

    while len(tabla_principal.rows) > 1:
        tabla_principal._tbl.remove(tabla_principal.rows[1]._tr)

    cuerpo.remove(doc.tables[2]._tbl)
    cuerpo.remove(doc.tables[1]._tbl)

    _rellenar_tabla_principal(tabla_principal, servicios)

    num_servicios = len(servicios.dataframe)
    for idx, srv_row in servicios.dataframe.iterrows():
        elem_servicio = copy.deepcopy(tabla_servicio_tpl)
        cuerpo.append(elem_servicio)
        tabla_servicio = doc.tables[-1]
        _completar_tabla_servicio(tabla_servicio, srv_row, servicios, reclamos)

        insert_idx = cuerpo.index(elem_servicio)
        _insertar_bloques(doc, cuerpo, insert_idx, bloques_texto, eventos, conclusion, propuesta)

        elem_detalle = copy.deepcopy(tabla_detalle_tpl)
        cuerpo.insert(insert_idx + len(bloques_texto) + 1, elem_detalle)
        tabla_detalle = doc.tables[-1]
        _completar_tabla_detalle(tabla_detalle, srv_row, servicios, reclamos)

        if idx < num_servicios - 1:
            salto = doc.add_page_break()
            cuerpo.remove(salto._p)
            cuerpo.insert(cuerpo.index(elem_detalle) + 1, salto._p)

    destino = Path(reports_dir) / "sla" / f"{anio:04d}{mes:02d}"
    destino.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    docx_path = destino / f"InformeSLA_{timestamp}.docx"
    doc.save(docx_path)

    pdf_path: Optional[Path] = None
    if incluir_pdf:
        binario = soffice_bin
        if binario:
            try:
                pdf_generado = convert_to_pdf(str(docx_path), binario)
                pdf_path = Path(pdf_generado)
            except Exception as exc:  # pragma: no cover - logging
                logger.warning("action=sla_legacy_report stage=pdf error=%s", exc)
        else:
            logger.info("action=sla_legacy_report stage=pdf reason=missing_soffice")

    return DocumentoSLA(docx=docx_path, pdf=pdf_path)


def _rellenar_tabla_principal(tabla: Table, servicios: _ExcelDataset) -> None:
    tipo_col = servicios.columns["tipo_servicio"]
    linea_col = servicios.columns["numero_linea"]
    cliente_col = servicios.columns["nombre_cliente"]
    horas_col = servicios.columns["horas_total"]
    sla_col = servicios.columns["sla"]

    while len(tabla.rows) > 1:
        tabla._tbl.remove(tabla.rows[1]._tr)

    for _, fila in servicios.dataframe.iterrows():
        nueva = copy.deepcopy(tabla.rows[0]._tr)
        tabla._tbl.append(nueva)
        celdas = tabla.rows[-1].cells
        celdas[0].text = str(fila.get(tipo_col, ""))
        celdas[1].text = str(fila.get(linea_col, ""))
        celdas[2].text = str(fila.get(cliente_col, ""))
        celdas[3].text = str(fila.get(horas_col, ""))
        sla_val = fila.get(sla_col)
        if pd.isna(sla_val):
            celdas[4].text = ""
        else:
            celdas[4].text = f"{float(sla_val) * 100:.2f}%"


def _completar_tabla_servicio(
    tabla: Table,
    srv_row: pd.Series,
    servicios: _ExcelDataset,
    reclamos: _ExcelDataset,
) -> None:
    valores = {
        "servicio": f"{srv_row.get(servicios.columns['tipo_servicio'], '')} {srv_row.get(servicios.columns['numero_linea'], '')}".strip(),
        "cliente": str(srv_row.get(servicios.columns['nombre_cliente'], "")),
        "ticket": ", ".join(_tickets_por_servicio(srv_row, servicios, reclamos)),
        "sla": _sla_texto(srv_row.get(servicios.columns['sla'])),
        "domicilio": _valor_opcional(srv_row, servicios.optional.get("domicilio")),
    }

    for fila in tabla.rows:
        for idx, celda in enumerate(fila.cells):
            contenido = celda.text.lower()
            for clave, valor in valores.items():
                if clave in contenido:
                    if len(fila.cells) > idx + 1 and not fila.cells[idx + 1].text.strip():
                        fila.cells[idx + 1].text = valor
                    else:
                        base = celda.text.split(":")[0].strip(": ")
                        fila.cells[idx].text = f"{base}: {valor}" if valor else base
                    break


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


def _completar_tabla_detalle(
    tabla: Table,
    srv_row: pd.Series,
    servicios: _ExcelDataset,
    reclamos: _ExcelDataset,
) -> None:
    while len(tabla.rows) > 1:
        tabla._tbl.remove(tabla.rows[1]._tr)

    linea_col = servicios.columns["numero_linea"]
    recl_linea_col = reclamos.columns["numero_linea"]
    recl_ticket = reclamos.columns["ticket"]
    recl_horas = reclamos.columns["horas"]
    recl_tipo = reclamos.columns["tipo_solucion"]
    recl_fecha = reclamos.columns["fecha_inicio"]
    recl_desc = reclamos.optional.get("descripcion")

    service_id = srv_row.get(linea_col)
    subset = reclamos.dataframe[reclamos.dataframe[recl_linea_col] == service_id]

    total_horas = 0.0
    for _, reclamo in subset.iterrows():
        fila = tabla.add_row().cells
        fila[0].text = str(reclamo.get(recl_linea_col, ""))
        fila[1].text = str(reclamo.get(recl_ticket, ""))
        horas_val = reclamo.get(recl_horas)
        if pd.isna(horas_val):
            fila[2].text = ""
        else:
            fila[2].text = f"{horas_val:.2f}"
            total_horas += float(horas_val)
        fila[3].text = str(reclamo.get(recl_tipo, ""))
        fecha = reclamo.get(recl_fecha)
        fila[4].text = _formatear_fecha(fecha)
        if recl_desc and len(fila) > 5:
            fila[5].text = str(reclamo.get(recl_desc, ""))

    if total_horas:
        totales = tabla.add_row().cells
        totales[0].text = "Total"
        totales[2].text = f"{total_horas:.2f}"


def _tickets_por_servicio(
    srv_row: pd.Series,
    servicios: _ExcelDataset,
    reclamos: _ExcelDataset,
) -> list[str]:
    linea_col = servicios.columns["numero_linea"]
    recl_linea_col = reclamos.columns["numero_linea"]
    recl_ticket = reclamos.columns["ticket"]
    service_id = srv_row.get(linea_col)
    tickets = reclamos.dataframe[reclamos.dataframe[recl_linea_col] == service_id][recl_ticket]
    return [str(ticket) for ticket in tickets.dropna().unique()]


def _valor_opcional(row: pd.Series, column: Optional[str]) -> str:
    if not column:
        return ""
    return str(row.get(column, ""))


def _sla_texto(valor) -> str:
    if valor is None or pd.isna(valor):
        return ""
    try:
        return f"{float(valor) * 100:.2f}%"
    except Exception:  # noqa: BLE001
        return str(valor)


def _horas_decimal(valor) -> Optional[float]:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = str(valor).strip().lower().replace(",", ".")
    if not texto:
        return None
    try:
        if ":" in texto or "h" in texto:
            return float(pd.to_timedelta(texto).total_seconds() / 3600)
        return float(texto)
    except Exception:  # noqa: BLE001
        return None


def _to_datetime(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    try:
        convertido = pd.to_datetime(valor, errors="coerce")
    except Exception:  # noqa: BLE001
        return None
    if pd.isna(convertido):
        return None
    return convertido


def _to_timedelta(valor) -> pd.Timedelta:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return pd.Timedelta(0)
    texto = str(valor).strip().lower().replace(",", ".")
    if not texto:
        return pd.Timedelta(0)
    try:
        return pd.to_timedelta(texto)
    except Exception:  # noqa: BLE001
        try:
            return pd.to_timedelta(float(texto), unit="h")
        except Exception:  # noqa: BLE001
            return pd.Timedelta(0)


def _fmt_td(td: pd.Timedelta) -> str:
    total = int(td.total_seconds())
    horas, resto = divmod(total, 3600)
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


def _parse_sla_value(valor) -> Optional[float]:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = str(valor).strip().lower().replace(",", ".")
    if not texto:
        return None
    try:
        numero = float(texto)
        if numero > 1:
            numero /= 100
        return numero
    except Exception:  # noqa: BLE001
        return None
