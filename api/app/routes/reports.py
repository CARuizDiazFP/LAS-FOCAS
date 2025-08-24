# Nombre de archivo: reports.py
# Ubicación de archivo: api/app/routes/reports.py
# Descripción: Endpoints para encolar generación de informes
"""Rutas que delegan la generación de informes al worker."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from rq.job import Job

from modules.informes_repetitividad.config import SOFFICE_BIN
from modules.informes_repetitividad.runner import run as run_repetitividad
from modules.worker import enqueue_informe, redis_conn

router = APIRouter(prefix="/informes", tags=["informes"])


class RepetitividadRequest(BaseModel):
    """Parámetros necesarios para el informe de repetitividad."""
    archivo: str
    mes: int
    anio: int


@router.post("/repetitividad")
def generar_repetitividad(req: RepetitividadRequest) -> dict[str, str]:
    """Encola la generación del informe de repetitividad."""
    job = enqueue_informe(run_repetitividad, req.archivo, req.mes, req.anio, SOFFICE_BIN)
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
def estado_job(job_id: str) -> dict[str, str]:
    """Devuelve el estado de un job encolado."""
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception as exc:  # pragma: no cover - validación
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": job.get_status()}
