# Nombre de archivo: infra_sync.py
# Ubicación de archivo: core/services/infra_sync.py
# Descripción: Sincronización de cámaras desde Google Sheets hacia PostgreSQL
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from os import getenv
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import gspread
from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound
from sqlalchemy.orm import Session

from core.config import get_settings
from db.models.infra import Camara, CamaraEstado
from db.session import SessionLocal


logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"Fontine_ID", "Nombre", "Lat", "Lon", "Estado"}


@dataclass(slots=True)
class InfraSyncResult:
    processed: int
    updated: int
    created: int
    skipped: int

    def to_response(self) -> dict[str, int | str]:
        return {
            "status": "ok",
            "processed": self.processed,
            "updated": self.updated,
            "created": self.created,
        }


def _build_gspread_client() -> gspread.Client:
    raw_credentials = getenv("GOOGLE_CREDENTIALS_JSON")
    if raw_credentials:
        try:
            payload = json.loads(raw_credentials)
        except json.JSONDecodeError as exc:  # noqa: BLE001
            raise ValueError("GOOGLE_CREDENTIALS_JSON no contiene JSON válido") from exc
        return gspread.service_account_from_dict(payload)

    credentials_path = Path(__file__).resolve().parents[2] / "Keys" / "credentials.json"
    if credentials_path.exists():
        return gspread.service_account(filename=str(credentials_path))

    fallback_path = Path(__file__).resolve().parents[2] / "credentials.json"
    if fallback_path.exists():
        return gspread.service_account(filename=str(fallback_path))

    raise RuntimeError("No se encontró credentials.json en /Keys ni la variable GOOGLE_CREDENTIALS_JSON")


def _fetch_rows(client: gspread.Client, sheet_id: str, worksheet_name: str) -> Sequence[Mapping[str, Any]]:
    try:
        worksheet = client.open_by_key(sheet_id).worksheet(worksheet_name)
    except SpreadsheetNotFound as exc:
        raise ValueError(f"No se encontró el Sheet con ID {sheet_id}") from exc
    except WorksheetNotFound as exc:
        raise ValueError(f"No se encontró la hoja {worksheet_name} en el Sheet {sheet_id}") from exc

    records = worksheet.get_all_records()
    if not records:
        logger.info("action=infra_sync empty_sheet sheet=%s worksheet=%s", sheet_id, worksheet_name)
        return []

    missing = [col for col in REQUIRED_COLUMNS if col not in records[0]]
    if missing:
        raise ValueError(f"Faltan columnas requeridas en la hoja: {', '.join(missing)}")

    logger.info(
        "action=infra_sync fetched_rows=%d sheet=%s worksheet=%s",
        len(records),
        sheet_id,
        worksheet_name,
    )
    return records


def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        logger.warning("action=infra_sync invalid_float value=%s", value)
        return None


def _parse_estado(value: Any) -> CamaraEstado:
    if value is None:
        return CamaraEstado.LIBRE
    text = str(value).strip().upper()
    try:
        return CamaraEstado(text)
    except ValueError:
        logger.warning("action=infra_sync invalid_estado value=%s fallback=%s", value, CamaraEstado.LIBRE.value)
        return CamaraEstado.LIBRE


def _ensure_session(session: Optional[Session]) -> tuple[Session, bool]:
    if session is not None:
        return session, False
    return SessionLocal(), True


def _sync_rows(rows: Sequence[Mapping[str, Any]], session: Session) -> InfraSyncResult:
    processed = 0
    updated = 0
    created = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    for index, row in enumerate(rows, start=1):
        fontine_raw = row.get("Fontine_ID")
        if not fontine_raw:
            skipped += 1
            logger.warning("action=infra_sync skip_row reason=missing_fontine_id row=%d", index)
            continue

        fontine_id = str(fontine_raw).strip()
        if not fontine_id:
            skipped += 1
            logger.warning("action=infra_sync skip_row reason=blank_fontine_id row=%d", index)
            continue

        processed += 1
        nombre_raw = row.get("Nombre")
        nombre = None if nombre_raw is None else str(nombre_raw).strip() or None
        latitud = _parse_float(row.get("Lat"))
        longitud = _parse_float(row.get("Lon"))
        estado = _parse_estado(row.get("Estado"))

        camara: Camara | None = session.query(Camara).filter_by(fontine_id=fontine_id).first()

        if camara is None:
            camara = Camara(
                fontine_id=fontine_id,
                nombre=nombre,
                latitud=latitud,
                longitud=longitud,
                estado=estado,
                last_update=now,
            )
            session.add(camara)
            created += 1
            logger.info("action=infra_sync created fontine_id=%s estado=%s", fontine_id, estado.value)
            continue

        changed = False
        if nombre is not None and nombre != camara.nombre:
            camara.nombre = nombre
            changed = True
        if latitud is not None and latitud != camara.latitud:
            camara.latitud = latitud
            changed = True
        if longitud is not None and longitud != camara.longitud:
            camara.longitud = longitud
            changed = True
        if estado != camara.estado:
            camara.estado = estado
            changed = True

        if changed:
            camara.last_update = now
            updated += 1
            logger.info("action=infra_sync updated fontine_id=%s estado=%s", fontine_id, estado.value)
        else:
            skipped += 1

    return InfraSyncResult(processed=processed, updated=updated, created=created, skipped=skipped)


def sync_camaras_from_sheet(
    *,
    sheet_id: Optional[str] = None,
    worksheet_name: Optional[str] = None,
    client: Optional[gspread.Client] = None,
    session: Optional[Session] = None,
) -> InfraSyncResult:
    settings = get_settings()
    target_sheet_id = sheet_id or settings.infra.sheet_id
    if not target_sheet_id:
        raise ValueError("Configurar INFRA_SHEET_ID o pasar sheet_id explícito")

    target_sheet_name = worksheet_name or settings.infra.sheet_name
    gs_client = client or _build_gspread_client()
    rows = _fetch_rows(gs_client, target_sheet_id, target_sheet_name)

    db_session, should_close = _ensure_session(session)
    try:
        result = _sync_rows(rows, db_session)
        db_session.commit()
    except Exception:  # noqa: BLE001
        db_session.rollback()
        raise
    finally:
        if should_close:
            db_session.close()

    logger.info(
        "action=infra_sync summary processed=%d updated=%d created=%d skipped=%d",
        result.processed,
        result.updated,
        result.created,
        result.skipped,
    )
    return result