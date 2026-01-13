# Nombre de archivo: protection_service.py
# Ubicación de archivo: core/services/protection_service.py
# Descripción: Servicio de Protocolo de Protección - Baneo y desbaneo de cámaras de fibra óptica

"""Servicio de Protocolo de Protección (Baneo de Cámaras).

Implementa la lógica de bloqueo de acceso físico a cámaras que contienen
fibra óptica de respaldo cuando la fibra principal está cortada.

Características:
- Redundancia cruzada: Servicio afectado != Servicio protegido
- Baneo a nivel de entidad Camara (no solo asociación)
- Restauración inteligente del estado al desbanear
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from db.models.infra import (
    Camara,
    CamaraEstado,
    Empalme,
    IncidenteBaneo,
    Ingreso,
    RutaServicio,
    Servicio,
    ruta_empalme_association,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATACLASSES
# =============================================================================


@dataclass
class BanResult:
    """Resultado de una operación de baneo."""

    success: bool
    incidente_id: Optional[int] = None
    camaras_baneadas: int = 0
    camaras_ya_baneadas: int = 0
    message: str = ""
    error: Optional[str] = None
    camaras_afectadas: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "incidente_id": self.incidente_id,
            "camaras_baneadas": self.camaras_baneadas,
            "camaras_ya_baneadas": self.camaras_ya_baneadas,
            "message": self.message,
            "error": self.error,
            "camaras_afectadas": self.camaras_afectadas,
        }


@dataclass
class LiftResult:
    """Resultado de una operación de desbaneo."""

    success: bool
    incidente_id: Optional[int] = None
    camaras_restauradas: int = 0
    camaras_mantenidas_baneadas: int = 0  # Por otro incidente activo
    message: str = ""
    error: Optional[str] = None
    camaras_afectadas: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "incidente_id": self.incidente_id,
            "camaras_restauradas": self.camaras_restauradas,
            "camaras_mantenidas_baneadas": self.camaras_mantenidas_baneadas,
            "message": self.message,
            "error": self.error,
            "camaras_afectadas": self.camaras_afectadas,
        }


# =============================================================================
# SERVICIO PRINCIPAL
# =============================================================================


class ProtectionService:
    """Servicio de Protocolo de Protección para baneo de cámaras.
    
    Gestiona el ciclo de vida de baneos:
    - Crear baneo: Marca cámaras como BANEADAS
    - Levantar baneo: Restaura estado de cámaras (LIBRE u OCUPADA según ingresos)
    - Consultar: Obtiene incidentes activos y cámaras afectadas
    """

    def __init__(self, session: Session):
        """Inicializa el servicio con una sesión de SQLAlchemy.
        
        Args:
            session: Sesión activa de SQLAlchemy (el caller maneja el ciclo de vida)
        """
        self.session = session

    # -------------------------------------------------------------------------
    # CONSULTAS
    # -------------------------------------------------------------------------

    def get_camaras_for_servicio(
        self,
        servicio_id: str,
        ruta_id: Optional[int] = None,
    ) -> List[Camara]:
        """Obtiene las cámaras asociadas a un servicio (opcionalmente filtrado por ruta).
        
        Args:
            servicio_id: ID del servicio (texto, ej: "52547")
            ruta_id: ID de ruta específica (opcional)
            
        Returns:
            Lista de cámaras únicas asociadas al servicio/ruta
        """
        # Buscar el servicio
        servicio = self.session.query(Servicio).filter(
            Servicio.servicio_id == servicio_id
        ).first()
        
        if not servicio:
            return []
        
        camaras_set: dict[int, Camara] = {}
        
        if ruta_id:
            # Filtrar por ruta específica
            ruta = self.session.query(RutaServicio).filter(
                RutaServicio.id == ruta_id,
                RutaServicio.servicio_id == servicio.id,
            ).first()
            
            if ruta:
                for empalme in ruta.empalmes:
                    if empalme.camara and empalme.camara.id not in camaras_set:
                        camaras_set[empalme.camara.id] = empalme.camara
        else:
            # Todas las rutas activas del servicio
            for ruta in servicio.rutas_activas:
                for empalme in ruta.empalmes:
                    if empalme.camara and empalme.camara.id not in camaras_set:
                        camaras_set[empalme.camara.id] = empalme.camara
        
        return list(camaras_set.values())

    def get_incidentes_activos(self) -> List[IncidenteBaneo]:
        """Obtiene todos los incidentes de baneo activos."""
        return self.session.query(IncidenteBaneo).filter(
            IncidenteBaneo.activo == True
        ).order_by(IncidenteBaneo.fecha_inicio.desc()).all()

    def get_incidentes_for_servicio(self, servicio_id: str) -> List[IncidenteBaneo]:
        """Obtiene incidentes activos que afectan a un servicio (como protegido)."""
        return self.session.query(IncidenteBaneo).filter(
            IncidenteBaneo.servicio_protegido_id == servicio_id,
            IncidenteBaneo.activo == True,
        ).all()

    def is_servicio_baneado(self, servicio_id: str) -> bool:
        """Verifica si un servicio tiene un baneo activo."""
        return self.session.query(IncidenteBaneo).filter(
            IncidenteBaneo.servicio_protegido_id == servicio_id,
            IncidenteBaneo.activo == True,
        ).first() is not None

    def get_incidente_by_id(self, incidente_id: int) -> Optional[IncidenteBaneo]:
        """Obtiene un incidente por ID."""
        return self.session.query(IncidenteBaneo).filter(
            IncidenteBaneo.id == incidente_id
        ).first()

    # -------------------------------------------------------------------------
    # OPERACIONES DE BANEO
    # -------------------------------------------------------------------------

    def create_ban(
        self,
        *,
        ticket_asociado: Optional[str],
        servicio_afectado_id: str,
        servicio_protegido_id: str,
        ruta_protegida_id: Optional[int] = None,
        usuario_ejecutor: Optional[str] = None,
        motivo: Optional[str] = None,
    ) -> BanResult:
        """Crea un incidente de baneo y marca las cámaras afectadas.
        
        Args:
            ticket_asociado: ID del ticket de soporte (opcional)
            servicio_afectado_id: ID del servicio que sufrió el corte
            servicio_protegido_id: ID del servicio a proteger (banear sus cámaras)
            ruta_protegida_id: ID de ruta específica a banear (opcional)
            usuario_ejecutor: Usuario que ejecuta el baneo
            motivo: Descripción del motivo
            
        Returns:
            BanResult con detalles de la operación
        """
        try:
            # Verificar que el servicio protegido existe
            servicio = self.session.query(Servicio).filter(
                Servicio.servicio_id == servicio_protegido_id
            ).first()
            
            if not servicio:
                return BanResult(
                    success=False,
                    error=f"Servicio '{servicio_protegido_id}' no encontrado",
                    message="No se puede crear el baneo porque el servicio protegido no existe",
                )
            
            # Verificar ruta si se especificó
            if ruta_protegida_id:
                ruta = self.session.query(RutaServicio).filter(
                    RutaServicio.id == ruta_protegida_id,
                    RutaServicio.servicio_id == servicio.id,
                ).first()
                
                if not ruta:
                    return BanResult(
                        success=False,
                        error=f"Ruta {ruta_protegida_id} no pertenece al servicio {servicio_protegido_id}",
                        message="La ruta especificada no existe o no pertenece al servicio",
                    )
            
            # Crear el incidente de baneo
            incidente = IncidenteBaneo(
                ticket_asociado=ticket_asociado,
                servicio_afectado_id=servicio_afectado_id,
                servicio_protegido_id=servicio_protegido_id,
                ruta_protegida_id=ruta_protegida_id,
                usuario_ejecutor=usuario_ejecutor,
                motivo=motivo,
                fecha_inicio=datetime.now(timezone.utc),
                activo=True,
            )
            self.session.add(incidente)
            self.session.flush()  # Obtener ID del incidente
            
            # Obtener cámaras a banear
            camaras = self.get_camaras_for_servicio(servicio_protegido_id, ruta_protegida_id)
            
            if not camaras:
                logger.warning(
                    "action=create_ban warning=no_camaras servicio=%s ruta=%s",
                    servicio_protegido_id,
                    ruta_protegida_id,
                )
                return BanResult(
                    success=True,
                    incidente_id=incidente.id,
                    camaras_baneadas=0,
                    message=f"Baneo creado (ID: {incidente.id}) pero no se encontraron cámaras asociadas",
                )
            
            # Marcar cámaras como BANEADAS
            camaras_baneadas = 0
            camaras_ya_baneadas = 0
            camaras_afectadas = []
            
            for camara in camaras:
                if camara.estado == CamaraEstado.BANEADA:
                    camaras_ya_baneadas += 1
                    camaras_afectadas.append({
                        "id": camara.id,
                        "nombre": camara.nombre,
                        "estado_anterior": "BANEADA",
                        "estado_nuevo": "BANEADA",
                        "accion": "sin_cambio",
                    })
                else:
                    estado_anterior = camara.estado.value if camara.estado else "LIBRE"
                    camara.estado = CamaraEstado.BANEADA
                    camara.last_update = datetime.now(timezone.utc)
                    camaras_baneadas += 1
                    camaras_afectadas.append({
                        "id": camara.id,
                        "nombre": camara.nombre,
                        "estado_anterior": estado_anterior,
                        "estado_nuevo": "BANEADA",
                        "accion": "baneada",
                    })
            
            logger.info(
                "action=create_ban incidente_id=%d servicio_protegido=%s camaras_baneadas=%d ya_baneadas=%d",
                incidente.id,
                servicio_protegido_id,
                camaras_baneadas,
                camaras_ya_baneadas,
            )
            
            return BanResult(
                success=True,
                incidente_id=incidente.id,
                camaras_baneadas=camaras_baneadas,
                camaras_ya_baneadas=camaras_ya_baneadas,
                message=f"Baneo creado. {camaras_baneadas} cámaras baneadas, {camaras_ya_baneadas} ya estaban baneadas.",
                camaras_afectadas=camaras_afectadas,
            )
            
        except Exception as exc:
            logger.exception("action=create_ban_error error=%s", exc)
            return BanResult(
                success=False,
                error=str(exc),
                message="Error inesperado al crear el baneo",
            )

    def lift_ban(
        self,
        incidente_id: int,
        *,
        usuario_ejecutor: Optional[str] = None,
        motivo_cierre: Optional[str] = None,
    ) -> LiftResult:
        """Levanta un baneo y restaura el estado de las cámaras.
        
        La lógica de restauración es inteligente:
        - Si la cámara tiene un ingreso activo → OCUPADA
        - Si la cámara está en otro baneo activo → BANEADA (sin cambio)
        - En otro caso → LIBRE
        
        Args:
            incidente_id: ID del incidente a cerrar
            usuario_ejecutor: Usuario que levanta el baneo
            motivo_cierre: Motivo de cierre (opcional)
            
        Returns:
            LiftResult con detalles de la operación
        """
        try:
            # Obtener el incidente
            incidente = self.get_incidente_by_id(incidente_id)
            
            if not incidente:
                return LiftResult(
                    success=False,
                    error=f"Incidente {incidente_id} no encontrado",
                    message="No existe el incidente especificado",
                )
            
            if not incidente.activo:
                return LiftResult(
                    success=False,
                    incidente_id=incidente_id,
                    error="El incidente ya está cerrado",
                    message=f"El baneo fue cerrado el {incidente.fecha_fin}",
                )
            
            # Marcar incidente como cerrado
            incidente.activo = False
            incidente.fecha_fin = datetime.now(timezone.utc)
            
            # Obtener cámaras que estaban en este baneo
            camaras = self.get_camaras_for_servicio(
                incidente.servicio_protegido_id,
                incidente.ruta_protegida_id,
            )
            
            camaras_restauradas = 0
            camaras_mantenidas = 0
            camaras_afectadas = []
            
            for camara in camaras:
                if camara.estado != CamaraEstado.BANEADA:
                    # Ya no está baneada, no hacer nada
                    continue
                
                # Verificar si hay otro baneo activo que afecte a esta cámara
                otro_baneo = self._camara_tiene_otro_baneo_activo(
                    camara.id,
                    incidente_id,
                )
                
                if otro_baneo:
                    # Mantener baneada por otro incidente
                    camaras_mantenidas += 1
                    camaras_afectadas.append({
                        "id": camara.id,
                        "nombre": camara.nombre,
                        "estado_anterior": "BANEADA",
                        "estado_nuevo": "BANEADA",
                        "accion": "mantenida_otro_baneo",
                        "otro_incidente_id": otro_baneo.id,
                    })
                    continue
                
                # Determinar nuevo estado
                nuevo_estado = self._determinar_estado_restauracion(camara)
                
                camara.estado = nuevo_estado
                camara.last_update = datetime.now(timezone.utc)
                camaras_restauradas += 1
                camaras_afectadas.append({
                    "id": camara.id,
                    "nombre": camara.nombre,
                    "estado_anterior": "BANEADA",
                    "estado_nuevo": nuevo_estado.value,
                    "accion": "restaurada",
                })
            
            logger.info(
                "action=lift_ban incidente_id=%d restauradas=%d mantenidas=%d",
                incidente_id,
                camaras_restauradas,
                camaras_mantenidas,
            )
            
            return LiftResult(
                success=True,
                incidente_id=incidente_id,
                camaras_restauradas=camaras_restauradas,
                camaras_mantenidas_baneadas=camaras_mantenidas,
                message=f"Baneo levantado. {camaras_restauradas} cámaras restauradas, {camaras_mantenidas} mantenidas baneadas por otros incidentes.",
                camaras_afectadas=camaras_afectadas,
            )
            
        except Exception as exc:
            logger.exception("action=lift_ban_error incidente_id=%d error=%s", incidente_id, exc)
            return LiftResult(
                success=False,
                incidente_id=incidente_id,
                error=str(exc),
                message="Error inesperado al levantar el baneo",
            )

    # -------------------------------------------------------------------------
    # MÉTODOS AUXILIARES INTERNOS
    # -------------------------------------------------------------------------

    def _camara_tiene_otro_baneo_activo(
        self,
        camara_id: int,
        excluir_incidente_id: int,
    ) -> Optional[IncidenteBaneo]:
        """Verifica si una cámara está afectada por otro baneo activo.
        
        Args:
            camara_id: ID de la cámara a verificar
            excluir_incidente_id: ID del incidente a excluir de la búsqueda
            
        Returns:
            El primer incidente activo que afecta la cámara, o None
        """
        # Obtener la cámara y sus empalmes
        camara = self.session.query(Camara).filter(Camara.id == camara_id).first()
        if not camara:
            return None
        
        # Obtener servicios que pasan por esta cámara
        servicios_ids = set()
        for empalme in camara.empalmes:
            for ruta in empalme.rutas:
                if ruta.servicio and ruta.servicio.servicio_id:
                    servicios_ids.add(ruta.servicio.servicio_id)
        
        if not servicios_ids:
            return None
        
        # Buscar otros incidentes activos que afecten estos servicios
        otro_incidente = self.session.query(IncidenteBaneo).filter(
            IncidenteBaneo.id != excluir_incidente_id,
            IncidenteBaneo.activo == True,
            IncidenteBaneo.servicio_protegido_id.in_(servicios_ids),
        ).first()
        
        return otro_incidente

    def _determinar_estado_restauracion(self, camara: Camara) -> CamaraEstado:
        """Determina el estado al que debe volver una cámara al desbanear.
        
        Lógica:
        - Si tiene ingreso activo (sin fecha_fin) → OCUPADA
        - En otro caso → LIBRE
        
        Args:
            camara: Cámara a evaluar
            
        Returns:
            Estado de restauración (LIBRE u OCUPADA)
        """
        # Verificar si hay un ingreso activo
        ingreso_activo = self.session.query(Ingreso).filter(
            Ingreso.camara_id == camara.id,
            Ingreso.fecha_fin == None,  # noqa: E711
        ).first()
        
        if ingreso_activo:
            return CamaraEstado.OCUPADA
        
        return CamaraEstado.LIBRE


# =============================================================================
# FUNCIONES DE ALTO NIVEL (PARA USO EN ENDPOINTS)
# =============================================================================


def create_ban(
    session: Session,
    *,
    ticket_asociado: Optional[str],
    servicio_afectado_id: str,
    servicio_protegido_id: str,
    ruta_protegida_id: Optional[int] = None,
    usuario_ejecutor: Optional[str] = None,
    motivo: Optional[str] = None,
) -> BanResult:
    """Wrapper para crear un baneo."""
    service = ProtectionService(session)
    return service.create_ban(
        ticket_asociado=ticket_asociado,
        servicio_afectado_id=servicio_afectado_id,
        servicio_protegido_id=servicio_protegido_id,
        ruta_protegida_id=ruta_protegida_id,
        usuario_ejecutor=usuario_ejecutor,
        motivo=motivo,
    )


def lift_ban(
    session: Session,
    incidente_id: int,
    *,
    usuario_ejecutor: Optional[str] = None,
    motivo_cierre: Optional[str] = None,
) -> LiftResult:
    """Wrapper para levantar un baneo."""
    service = ProtectionService(session)
    return service.lift_ban(
        incidente_id,
        usuario_ejecutor=usuario_ejecutor,
        motivo_cierre=motivo_cierre,
    )


def get_incidentes_activos(session: Session) -> List[IncidenteBaneo]:
    """Wrapper para obtener incidentes activos."""
    service = ProtectionService(session)
    return service.get_incidentes_activos()


def is_servicio_baneado(session: Session, servicio_id: str) -> bool:
    """Wrapper para verificar si un servicio está baneado."""
    service = ProtectionService(session)
    return service.is_servicio_baneado(servicio_id)
