# Nombre de archivo: separacion_service.py
# Ubicación de archivo: core/services/cromo/separacion_service.py
# Descripción: Separación manual de una Botella Cromo de su Cámara padre actual (agrupamiento erróneo por nombre) hacia una Cámara nueva e independiente

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from core.services.camara_hierarchy_service import normalizar_para_agrupar_extendido
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado, CamaraEstadoAuditoria, CamaraOrigenDatos


class BotellaNoEncontradaError(Exception):
    """El n_id no existe en app.cromo_botellas — el endpoint la mapea a 404."""


class SeparacionBotellaError(Exception):
    """Validación de dominio (nombre vacío, colisión de nombre) — el endpoint la mapea a 400."""


@dataclass(slots=True, frozen=True)
class ResultadoSeparacion:
    botella_n_id: int
    camara_anterior_id: Optional[int]
    camara_nueva_id: int
    camara_nueva_nombre: str


def _existe_camara_raiz_con_nombre(session: Session, nombre: str) -> Optional[Camara]:
    """Mismo patrón que `camara_duplicados_service.detectar_grupos_duplicados`: trae TODAS las
    Cámaras raíz (~10.212 filas, sub-segundo) y compara por `normalizar_para_agrupar_extendido` —
    no hay hoy una query SQL barata para esto (sin índice/columna funcional)."""
    clave = normalizar_para_agrupar_extendido(nombre)
    raices = session.query(Camara).filter(Camara.camara_padre_id.is_(None)).all()
    for candidata in raices:
        if normalizar_para_agrupar_extendido(candidata.nombre) == clave:
            return candidata
    return None


def separar_botella_de_padre(
    session: Session, *, botella_n_id: int, nombre: str, motivo: str, usuario: str
) -> ResultadoSeparacion:
    """Separa una CromoBotella de su Cámara padre actual, creándole una Cámara nueva e
    independiente. No hace `commit`/`rollback` — lo controla el endpoint (mismo patrón que
    `orfanas_service.asociar_huerfanas`/`botella_merge_service.apropiar_legado_a_cromo`).

    Deliberadamente NO toca la Cámara padre anterior (no la elimina ni la audita) aunque quede sin
    esta Botella — es un flujo separado ("Eliminar Cámara") con sus propias validaciones de bloqueo.
    """
    botella = session.get(CromoBotella, botella_n_id)
    if botella is None:
        raise BotellaNoEncontradaError(f"No existe una Botella Cromo con n_id={botella_n_id}.")

    if botella.camara_id is None:
        raise SeparacionBotellaError(
            f"La Botella n_id={botella_n_id} no tiene Cámara padre — usá 'Asociar huérfana' en vez de separar."
        )

    nombre_final = nombre.strip()
    if not nombre_final:
        raise SeparacionBotellaError("El nombre no puede quedar vacío.")

    colision = _existe_camara_raiz_con_nombre(session, nombre_final)
    if colision is not None:
        raise SeparacionBotellaError(
            f'El nombre "{nombre_final}" ya lo usa la Cámara "{colision.nombre}" (ID {colision.id}) '
            "una vez normalizado — elegí un nombre distintivo para evitar que se agrupen de nuevo."
        )

    camara_anterior_id = botella.camara_id

    nueva_camara = Camara(
        nombre=nombre_final,
        estado=botella.estado,
        origen_datos=CamaraOrigenDatos.MANUAL,
        last_update=datetime.now(timezone.utc),
    )
    session.add(nueva_camara)
    session.flush()  # necesito nueva_camara.id antes de asignarlo a la Botella

    session.add(
        CamaraEstadoAuditoria(
            camara_id=nueva_camara.id,
            usuario=usuario,
            motivo=(
                f"Cámara creada al separar la Botella Cromo n_id={botella.n_id} de su Cámara padre "
                f"anterior (id={camara_anterior_id}) — hereda el estado real de la Botella."
            ),
            estado_anterior=CamaraEstado.LIBRE,
            estado_nuevo=nueva_camara.estado,
        )
    )

    ahora = datetime.now(timezone.utc)
    botella.nombre = nombre_final
    botella.nombre_editado_manual = True
    botella.camara_id = nueva_camara.id
    botella.separada_manualmente = True
    botella.separada_motivo = motivo.strip() or None
    botella.separada_por = usuario
    botella.separada_at = ahora

    return ResultadoSeparacion(
        botella_n_id=botella.n_id,
        camara_anterior_id=camara_anterior_id,
        camara_nueva_id=nueva_camara.id,
        camara_nueva_nombre=nueva_camara.nombre,
    )


__all__ = [
    "BotellaNoEncontradaError",
    "SeparacionBotellaError",
    "ResultadoSeparacion",
    "separar_botella_de_padre",
]
