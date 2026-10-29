# Nombre de archivo: comun.py
# Ubicación de archivo: web/app/comun.py
# Descripción: Helpers compartidos de la app web (auth, CSRF, configuración, rutas de datos, historial de informes)

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, UploadFile, status

from core.config import PROJECT_ROOT, get_secret, reports_dir, uploads_dir
from core.services.report_history import ReportHistoryBackend, ReportHistoryService

from .errores import ErrorDeDominio

# Mismo logger "web" que configura main.py con setup_logging("web", ...)
logger = logging.getLogger("web")

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")

# Config DB (usa las variables del .env del stack)
DB_HOST = os.getenv("POSTGRES_HOST", "postgres")
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME = os.getenv("POSTGRES_DB", "lasfocas")
DB_USER = os.getenv("POSTGRES_USER", "lasfocas")
DB_PASS = get_secret("db_password_v1", "POSTGRES_PASSWORD")
DB_DSN = f"dbname={DB_NAME} user={DB_USER} password={DB_PASS} host={DB_HOST} port={DB_PORT}"

# Raíz de la app web (web/ en el repo, /app en la imagen): sólo para frontend/dist.
BASE_DIR = Path(__file__).resolve().parents[1]
# Rutas de datos: las de core/config (env UPLOADS_DIR/REPORTS_DIR o <raíz>/data/...). En el contenedor dan
# lo mismo que antes (/app/data/...); fuera de él ya no apuntan a web/data/, sino a las del resto del repo.
DATA_DIR = PROJECT_ROOT / "data"
UPLOADS_DIR = uploads_dir()
REPORTS_DIR = reports_dir()
DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

REPORT_HISTORY: ReportHistoryBackend = ReportHistoryService(DB_DSN)


def _detect_build_version() -> str:
    for candidate in (
        os.getenv("WEB_BUILD_VERSION"),
        os.getenv("BUILD_HASH"),
        os.getenv("GIT_SHA"),
    ):
        if candidate:
            return candidate.strip()
    return str(int(time.time()))


BUILD_VERSION = _detect_build_version()


def _internal_api_auth_headers() -> dict[str, str]:
    api_key = get_secret("api_key_v1", "LAS_FOCAS_API_KEY").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="API interna sin credenciales")
    return {
        "Authorization": f"Bearer {api_key}",
    }


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("action=config_invalid_int name=%s default=%s", name, default)
        return default


# Tope de los uploads del panel (Excel de informes e ingestas). Los que tienen un límite propio lo pasan
# en `max_mb` (CSV de alarmas 10 MB, trackings 5 MB); chat y lista de clientes ya leían con tope.
MAX_UPLOAD_MB = _env_int("MAX_UPLOAD_MB", 20)
_CHUNK_UPLOAD = 1024 * 1024


class UploadDemasiadoGrande(ErrorDeDominio):
    status_code = 413


def _tope_upload(archivo: UploadFile, max_mb: int | None) -> tuple[int, str]:
    mb = MAX_UPLOAD_MB if max_mb is None else max_mb
    nombre = Path(archivo.filename or "El archivo").name
    return mb * 1024 * 1024, f"{nombre} supera el límite de {mb} MB"


async def leer_upload(archivo: UploadFile, *, max_mb: int | None = None) -> bytes:
    """Lee el upload por chunks y corta con 413 apenas pasa el tope, sin cargarlo entero a memoria."""
    limite, mensaje = _tope_upload(archivo, max_mb)
    partes: list[bytes] = []
    total = 0
    while chunk := await archivo.read(_CHUNK_UPLOAD):
        total += len(chunk)
        if total > limite:
            logger.warning("action=upload_rechazado reason=tamano archivo=%s limite=%s", archivo.filename, limite)
            raise UploadDemasiadoGrande(mensaje)
        partes.append(chunk)
    return b"".join(partes)


def leer_upload_sync(archivo: UploadFile, *, max_mb: int | None = None) -> bytes:
    """Variante para endpoints `def` (threadpool): lee `archivo.file` con el mismo tope que `leer_upload`."""
    limite, mensaje = _tope_upload(archivo, max_mb)
    partes: list[bytes] = []
    total = 0
    while chunk := archivo.file.read(_CHUNK_UPLOAD):
        total += len(chunk)
        if total > limite:
            logger.warning("action=upload_rechazado reason=tamano archivo=%s limite=%s", archivo.filename, limite)
            raise UploadDemasiadoGrande(mensaje)
        partes.append(chunk)
    return b"".join(partes)


def _require_auth(request: Request) -> tuple[str, str]:
    username = request.session.get("username")
    role = request.session.get("role", "user")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return username, role


def _require_admin(request: Request) -> str:
    username, role = _require_auth(request)
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permisos insuficientes")
    return username


def _es_destino_slack_valido(destino: str) -> bool:
    """Valida nombres de canal o IDs de destino de Slack."""
    if not destino:
        return False
    valor = destino.strip()
    if not valor:
        return False
    if re.fullmatch(r"#[a-z0-9._-]+", valor):
        return True
    if re.fullmatch(r"[CGD][A-Z0-9]{8,}", valor):
        return True
    return False


# Etapa 7: la ingesta corre en su propio worker Docker (modules/cromo_worker/), no en este proceso.
_CROMO_WORKER_BASE_URL = os.getenv("CROMO_WORKER_BASE_URL", "http://cromo_worker:8096")
_CROMO_WORKER_RUN_URL = f"{_CROMO_WORKER_BASE_URL}/run"


async def _marcar_corrida_fallida(corrida_id: int, motivo: str) -> None:
    """La corrida ya se creó como EN_CURSO — si no se pudo delegar al worker, no debe quedar huérfana."""
    from datetime import datetime, timezone

    from db.models.cromo import CromoIngestaCorrida, CromoIngestaEvento
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
        if corrida is None:
            return
        corrida.estado = "FALLIDA"
        corrida.finalizada_at = datetime.now(timezone.utc)
        sesion.add(CromoIngestaEvento(corrida_id=corrida_id, accion="ERROR", detalle=motivo))
        await sesion.commit()


def _serializar_cromo_corrida(corrida: Any) -> dict[str, Any]:
    return {
        "id": corrida.id,
        "usuario": corrida.usuario,
        "estado": corrida.estado,
        "params": corrida.params,
        "total_objetivo": corrida.total_objetivo,
        "leidas": corrida.leidas,
        "creadas": corrida.creadas,
        "actualizadas": corrida.actualizadas,
        "sin_cambios": corrida.sin_cambios,
        "errores": corrida.errores,
        "refs_colgadas": corrida.refs_colgadas,
        "iniciada_at": corrida.iniciada_at.isoformat() if corrida.iniciada_at else None,
        "finalizada_at": corrida.finalizada_at.isoformat() if corrida.finalizada_at else None,
    }


def _serialize_camara_ingreso(item: Any) -> dict[str, Any]:
    """`botella_label` (Tarea 6, 2026-09-04) resuelve el nombre legible de la Botella intervenida —
    reemplaza el fallback "Sin botella asociada" del frontend (`ModalRegistros.vue`), que mostraba el
    `n_id` crudo o ese texto sin distinguir "no se especificó botella" (= la Cámara raíz, "Botella 1"
    por convención — ver `camara_search.detectar_multi_bot`) de "se especificó una Botella legado sin
    CromoBotella asociada". `getattr` defensivo: tolera objetos de test (`SimpleNamespace`) sin
    `.camara`/`.tipo` poblados, cayendo a los defaults más comunes."""
    if item.cromo_botella_id is not None:
        cromo_botella = getattr(item, "cromo_botella", None)
        # `CromoBotella.nombre` es nullable: si la relación existe pero su `nombre` es None/vacío,
        # el `or` cae al fallback numerado — nunca basta con chequear "la relación existe" (bug real,
        # revisión final 2026-09-04: `cromo_botella.nombre if cromo_botella is not None else ...`
        # devolvía `botella_label=None` cuando `cromo_botella.nombre IS NULL`, violando la garantía
        # documentada de "nunca null" y el tipo TypeScript `botella_label: string`).
        botella_label = (cromo_botella.nombre if cromo_botella is not None else None) or f"Botella #{item.cromo_botella_id}"
    elif getattr(getattr(item, "camara", None), "camara_padre_id", None):
        botella_label = item.camara.nombre
    else:
        botella_label = "Botella 1"

    tipo = getattr(item, "tipo", None)
    # Baja lógica (2026-10-23): los listados sólo traen anulados si un admin los pide
    # (`?incluir_anulados=1`); `getattr` por los mismos fakes de test sin esas columnas.
    anulado_at = getattr(item, "anulado_at", None)
    return {
        "id": item.id,
        "fecha_inicio": item.fecha_inicio.isoformat() if item.fecha_inicio else None,
        "fecha_fin": item.fecha_fin.isoformat() if item.fecha_fin else None,
        "tecnico_id": item.tecnico_id,
        "cromo_botella_id": item.cromo_botella_id,
        "botella_label": botella_label,
        "tipo": tipo.value if tipo else "INGRESO",
        "anulado": anulado_at is not None,
        "anulado_at": anulado_at.isoformat() if anulado_at else None,
        "anulado_por": getattr(item, "anulado_por", None),
        "anulado_motivo": getattr(item, "anulado_motivo", None),
    }


def _incluye_anulados(pedido: bool, usuario: Any) -> bool:
    """`?incluir_anulados=1` sólo tiene efecto para un admin; a un usuario común se le ignora sin
    error (decisión 6 del plan de corrección de ingresos, 2026-10-23). `usuario` es el
    `UsuarioSesion` de la request."""
    return bool(pedido) and getattr(usuario, "role", None) == "admin"


async def _encolar_arbitro(tipo: str, ids: Sequence[int], motivo: str) -> None:
    """Encola una evaluación del árbitro de Cromo (disparo VIEWER) tras una acción del operador ya
    commiteada. Best-effort: import diferido y cualquier falla se traga; nunca altera la respuesta."""
    try:
        from core.services.cromo.arbitro.cola import encolar_evaluacion
        from core.services.cromo.arbitro.senales import Alcance

        await encolar_evaluacion(Alcance(tipo, tuple(dict.fromkeys(ids))), "VIEWER", motivo)
    except Exception:  # noqa: BLE001
        logger.warning("action=arbitro_encolar_viewer result=fail motivo=%s", motivo, exc_info=True)


def _serializar_pelo_semilla(semilla: Any) -> dict[str, Any]:
    return {
        "pelo_n_id": semilla.pelo_n_id,
        "servicio_numero": semilla.servicio_numero,
        "metodo": semilla.metodo,
        "confianza": semilla.confianza,
        "numero_pelo": semilla.numero_pelo,
        "color": semilla.color,
        "cable_n_id": semilla.cable_n_id,
        "cable_nombre": semilla.cable_nombre,
        "tiene_conector_odf": semilla.tiene_conector_odf,
        "servicio_raw": semilla.servicio_raw,
    }


async def _servicio_existe(sesion: Any, servicio_id: int) -> bool:
    from sqlalchemy import text as _text

    fila = await sesion.execute(
        _text("SELECT 1 FROM app.servicios WHERE id = :id"), {"id": servicio_id}
    )
    return fila.first() is not None


def _serializar_bloqueos(bloqueos: list[Any]) -> list[dict[str, Any]]:
    return [{"origen": b.origen, "id": b.id, "nombre": b.nombre, "razon": b.razon} for b in bloqueos]
