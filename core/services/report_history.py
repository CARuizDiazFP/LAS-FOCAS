# Nombre de archivo: report_history.py
# Ubicación de archivo: core/services/report_history.py
# Descripción: Servicio de histórico persistente para informes generados desde el panel web

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Protocol

import psycopg

logger = logging.getLogger(__name__)

ReportMetadata = Dict[str, Any]


class ReportHistoryBackend(Protocol):
    """Contrato mínimo usado por los endpoints web."""

    def start(
        self,
        *,
        report_type: str,
        username: str,
        source: str,
        period_month: int,
        period_year: int,
        input_metadata: ReportMetadata | None = None,
    ) -> int | None:
        """Crea un registro en estado running."""

    def finish_success(
        self,
        report_id: int | None,
        *,
        output_metadata: ReportMetadata | None = None,
    ) -> None:
        """Marca un registro como exitoso."""

    def finish_error(
        self,
        report_id: int | None,
        *,
        error_code: str,
        error_message: str,
        output_metadata: ReportMetadata | None = None,
    ) -> None:
        """Marca un registro como fallido."""

    def list_records(
        self,
        *,
        report_type: str | None = None,
        status: str | None = None,
        username: str | None = None,
        month: int | None = None,
        year: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ReportMetadata]:
        """Lista registros ordenados del más reciente al más antiguo."""


def _json_payload(value: ReportMetadata | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def _decode_json(value: Any) -> ReportMetadata:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@dataclass
class ReportHistoryService:
    """Persistencia PostgreSQL del histórico de reportes.

    Los métodos son tolerantes a errores para que el histórico no bloquee la
    generación del informe cuando la migración aún no fue aplicada.
    """

    dsn: str

    def start(
        self,
        *,
        report_type: str,
        username: str,
        source: str,
        period_month: int,
        period_year: int,
        input_metadata: ReportMetadata | None = None,
    ) -> int | None:
        try:
            with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:  # type: ignore[assignment]
                cur.execute(
                    """
                    INSERT INTO app.report_history (
                        report_type, status, username, source,
                        period_month, period_year, input_metadata
                    )
                    VALUES (%s, 'running', %s, %s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        report_type,
                        username,
                        source,
                        period_month,
                        period_year,
                        _json_payload(input_metadata),
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                return int(row[0]) if row else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("action=report_history_start error=%s", exc)
            return None

    def finish_success(
        self,
        report_id: int | None,
        *,
        output_metadata: ReportMetadata | None = None,
    ) -> None:
        if report_id is None:
            return
        try:
            with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:  # type: ignore[assignment]
                cur.execute(
                    """
                    UPDATE app.report_history
                    SET status = 'success',
                        finished_at = CURRENT_TIMESTAMP,
                        duration_ms = GREATEST(
                            0,
                            (EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)) * 1000)::integer
                        ),
                        output_metadata = %s::jsonb,
                        error_code = NULL,
                        error_message = NULL
                    WHERE id = %s
                    """,
                    (_json_payload(output_metadata), report_id),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("action=report_history_success error=%s report_id=%s", exc, report_id)

    def finish_error(
        self,
        report_id: int | None,
        *,
        error_code: str,
        error_message: str,
        output_metadata: ReportMetadata | None = None,
    ) -> None:
        if report_id is None:
            return
        try:
            with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:  # type: ignore[assignment]
                cur.execute(
                    """
                    UPDATE app.report_history
                    SET status = 'error',
                        finished_at = CURRENT_TIMESTAMP,
                        duration_ms = GREATEST(
                            0,
                            (EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)) * 1000)::integer
                        ),
                        output_metadata = %s::jsonb,
                        error_code = %s,
                        error_message = %s
                    WHERE id = %s
                    """,
                    (_json_payload(output_metadata), error_code, error_message[:1000], report_id),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("action=report_history_error error=%s report_id=%s", exc, report_id)

    def list_records(
        self,
        *,
        report_type: str | None = None,
        status: str | None = None,
        username: str | None = None,
        month: int | None = None,
        year: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ReportMetadata]:
        filters: list[str] = []
        params: list[Any] = []
        if report_type:
            filters.append("report_type = %s")
            params.append(report_type)
        if status:
            filters.append("status = %s")
            params.append(status)
        if username:
            filters.append("username = %s")
            params.append(username)
        if month is not None:
            filters.append("period_month = %s")
            params.append(month)
        if year is not None:
            filters.append("period_year = %s")
            params.append(year)

        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        try:
            with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:  # type: ignore[assignment]
                cur.execute(
                    f"""
                    SELECT id, report_type, status, username, source,
                           period_month, period_year, started_at, finished_at,
                           duration_ms, input_metadata, output_metadata,
                           error_code, error_message
                    FROM app.report_history
                    {where_sql}
                    ORDER BY started_at DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    params,
                )
                rows = cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("action=report_history_list error=%s", exc)
            return []

        return [
            {
                "id": int(row[0]),
                "report_type": row[1],
                "status": row[2],
                "username": row[3],
                "source": row[4],
                "period_month": row[5],
                "period_year": row[6],
                "started_at": _iso(row[7]),
                "finished_at": _iso(row[8]),
                "duration_ms": row[9],
                "input_metadata": _decode_json(row[10]),
                "output_metadata": _decode_json(row[11]),
                "error_code": row[12],
                "error_message": row[13],
            }
            for row in rows
        ]


@dataclass
class InMemoryReportHistory(ReportHistoryBackend):
    """Backend en memoria para pruebas de endpoints."""

    records: List[ReportMetadata] = field(default_factory=list)
    _counter: int = 0

    def start(
        self,
        *,
        report_type: str,
        username: str,
        source: str,
        period_month: int,
        period_year: int,
        input_metadata: ReportMetadata | None = None,
    ) -> int | None:
        self._counter += 1
        self.records.append(
            {
                "id": self._counter,
                "report_type": report_type,
                "status": "running",
                "username": username,
                "source": source,
                "period_month": period_month,
                "period_year": period_year,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "duration_ms": None,
                "input_metadata": input_metadata or {},
                "output_metadata": {},
                "error_code": None,
                "error_message": None,
                "_started_perf": time.perf_counter(),
            }
        )
        return self._counter

    def finish_success(
        self,
        report_id: int | None,
        *,
        output_metadata: ReportMetadata | None = None,
    ) -> None:
        self._finish(report_id, "success", output_metadata or {}, None, None)

    def finish_error(
        self,
        report_id: int | None,
        *,
        error_code: str,
        error_message: str,
        output_metadata: ReportMetadata | None = None,
    ) -> None:
        self._finish(report_id, "error", output_metadata or {}, error_code, error_message)

    def list_records(
        self,
        *,
        report_type: str | None = None,
        status: str | None = None,
        username: str | None = None,
        month: int | None = None,
        year: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ReportMetadata]:
        result = []
        for record in sorted(self.records, key=lambda item: int(item["id"]), reverse=True):
            if report_type and record["report_type"] != report_type:
                continue
            if status and record["status"] != status:
                continue
            if username and record["username"] != username:
                continue
            if month is not None and record["period_month"] != month:
                continue
            if year is not None and record["period_year"] != year:
                continue
            result.append({k: v for k, v in record.items() if not k.startswith("_")})
        return result[offset: offset + limit]

    def _finish(
        self,
        report_id: int | None,
        status: str,
        output_metadata: ReportMetadata,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        if report_id is None:
            return
        for record in self.records:
            if record["id"] == report_id:
                started_perf = float(record.get("_started_perf", time.perf_counter()))
                record["status"] = status
                record["finished_at"] = datetime.now(timezone.utc).isoformat()
                record["duration_ms"] = max(0, round((time.perf_counter() - started_perf) * 1000))
                record["output_metadata"] = output_metadata
                record["error_code"] = error_code
                record["error_message"] = error_message
                return


__all__ = [
    "InMemoryReportHistory",
    "ReportHistoryBackend",
    "ReportHistoryService",
]
