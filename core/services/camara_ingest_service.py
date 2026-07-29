# Nombre de archivo: camara_ingest_service.py
# Ubicación de archivo: core/services/camara_ingest_service.py
# Descripción: Servicio síncrono para ingesta masiva de cámaras desde Excel y baneo administrativo

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from db.models.infra import Camara, CamaraAlias, CamaraEstado, CamaraOrigenDatos
from db.session import SessionLocal
from core.services.camara_estado_service import override_camara_estado_manual

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CamaraIngestaResultado:
    """Resultado del procesamiento de ingesta masiva de cámaras."""

    creadas: int = 0
    preexistentes: int = 0
    baneadas: int = 0
    errores: list[str] = field(default_factory=list)


def _buscar_camara(session: Session, alias: str) -> Camara | None:
    """Busca una cámara por alias exacto o por nombre. Retorna None si no existe."""
    # 1. Buscar por alias registrado
    camara_alias = (
        session.query(CamaraAlias)
        .filter(CamaraAlias.alias_nombre == alias)
        .first()
    )
    if camara_alias is not None:
        return camara_alias.camara

    # 2. Fallback: buscar por nombre directo
    return session.query(Camara).filter(Camara.nombre == alias).first()


def procesar_ingesta_camaras(
    aliases: list[str],
    motivo_baneo: str,
    usuario: str,
) -> CamaraIngestaResultado:
    """Procesa una lista de aliases de cámaras: da de alta las que no existen
    y aplica baneo administrativo (BANEADA) a todas.

    Args:
        aliases: Lista deduplicada de identificadores/aliases de cámaras.
        motivo_baneo: Texto obligatorio que describe el motivo del baneo masivo.
        usuario: Nombre del usuario admin que ejecuta la operación.

    Returns:
        CamaraIngestaResultado con conteos de operaciones realizadas.
    """
    resultado = CamaraIngestaResultado()
    session: Session = SessionLocal()

    try:
        for alias in aliases:
            try:
                camara = _buscar_camara(session, alias)

                if camara is None:
                    # Alta de nueva cámara
                    camara = Camara(
                        nombre=alias,
                        estado=CamaraEstado.LIBRE,
                        origen_datos=CamaraOrigenDatos.SHEET,
                    )
                    session.add(camara)
                    session.flush()  # obtener el id generado
                    resultado.creadas += 1
                    logger.info(
                        "action=camara_ingest_alta alias=%s camara_id=%d usuario=%s",
                        alias,
                        camara.id,
                        usuario,
                    )
                else:
                    resultado.preexistentes += 1

                # Baneo administrativo (manual, sin IncidenteBaneo)
                ban_result = override_camara_estado_manual(
                    session,
                    camara.id,
                    CamaraEstado.BANEADA,
                    usuario=usuario,
                    motivo=motivo_baneo,
                )
                if ban_result.success:
                    resultado.baneadas += 1
                    logger.info(
                        "action=camara_ingest_baneo alias=%s camara_id=%d changed=%s usuario=%s",
                        alias,
                        camara.id,
                        ban_result.changed,
                        usuario,
                    )
                else:
                    error_msg = f"{alias}: {ban_result.error or 'baneo fallido'}"
                    resultado.errores.append(error_msg)
                    logger.warning(
                        "action=camara_ingest_baneo_error alias=%s camara_id=%d error=%s",
                        alias,
                        camara.id,
                        ban_result.error,
                    )

            except Exception as exc:  # noqa: BLE001
                resultado.errores.append(f"{alias}: {exc!s}")
                logger.exception(
                    "action=camara_ingest_alias_error alias=%s usuario=%s error=%s",
                    alias,
                    usuario,
                    exc,
                )

        session.commit()
        logger.info(
            "action=camara_ingest_commit usuario=%s creadas=%d preexistentes=%d baneadas=%d errores=%d",
            usuario,
            resultado.creadas,
            resultado.preexistentes,
            resultado.baneadas,
            len(resultado.errores),
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return resultado


__all__ = [
    "CamaraIngestaResultado",
    "procesar_ingesta_camaras",
]
