# Nombre de archivo: infra_service.py
# Ubicación de archivo: core/services/infra_service.py
# Descripción: Servicio de infraestructura FO con lógica de versionado y ramificación de rutas

"""Servicio de Infraestructura de Fibra Óptica.

Implementa la lógica de ingesta inteligente en 2 pasos:
1. Análisis: Parsea archivo, detecta conflictos con rutas existentes
2. Resolución: Ejecuta la acción correspondiente (CREATE_NEW, MERGE_APPEND, REPLACE, BRANCH)

Similar a un sistema de versionado (Git branches) para los recorridos de fibra.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.parsers.tracking_parser import TrackingParseResult, parse_tracking, PuntaTerminal
from db.models.infra import (
    Camara,
    CamaraEstado,
    CamaraOrigenDatos,
    Empalme,
    PuntoTerminal,
    PuntoTerminalTipo,
    RutaServicio,
    RutaTipo,
    Servicio,
    ruta_empalme_association,
)

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS Y DATACLASSES
# =============================================================================


class AnalysisStatus(str, Enum):
    """Estado del análisis de un archivo de tracking."""

    NEW = "NEW"  # Servicio no existe, se puede crear
    IDENTICAL = "IDENTICAL"  # Hash coincide con ruta existente, no hacer nada
    CONFLICT = "CONFLICT"  # Hash difiere, requiere decisión del usuario
    POTENTIAL_UPGRADE = "POTENTIAL_UPGRADE"  # Mismas puntas A/B pero diferente ID (posible upgrade)
    NEW_STRAND = "NEW_STRAND"  # Mismo ID y camino pero diferente pelo (multi-pelo)
    ERROR = "ERROR"  # Error durante el análisis


class ResolveAction(str, Enum):
    """Acciones disponibles para resolver un conflicto de tracking."""

    CREATE_NEW = "CREATE_NEW"  # Crear servicio + ruta principal
    MERGE_APPEND = "MERGE_APPEND"  # Agregar empalmes a ruta existente
    REPLACE = "REPLACE"  # Reemplazar empalmes de ruta existente
    BRANCH = "BRANCH"  # Crear nueva ruta bajo el mismo servicio
    CONFIRM_UPGRADE = "CONFIRM_UPGRADE"  # Confirmar upgrade: mover ID viejo a alias
    ADD_STRAND = "ADD_STRAND"  # Agregar nuevo pelo a ruta existente


@dataclass
class RutaInfo:
    """Información resumida de una ruta para el frontend."""

    id: int
    nombre: str
    tipo: str
    hash_contenido: Optional[str]
    empalmes_count: int
    activa: bool
    created_at: Optional[str]
    nombre_archivo_origen: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "nombre": self.nombre,
            "tipo": self.tipo,
            "hash_contenido": self.hash_contenido,
            "empalmes_count": self.empalmes_count,
            "activa": self.activa,
            "created_at": self.created_at,
            "nombre_archivo_origen": self.nombre_archivo_origen,
        }


@dataclass
class UpgradeInfo:
    """Información de un posible upgrade detectado."""

    old_service_id: str
    old_service_db_id: int
    new_service_id: str
    match_reason: str  # "Endpoints Match", "Punta A Match", etc.
    punta_a_match: Optional[str] = None
    punta_b_match: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "old_service_id": self.old_service_id,
            "old_service_db_id": self.old_service_db_id,
            "new_service_id": self.new_service_id,
            "match_reason": self.match_reason,
            "punta_a_match": self.punta_a_match,
            "punta_b_match": self.punta_b_match,
        }


@dataclass
class StrandInfo:
    """Información de un nuevo pelo detectado."""

    service_id: str
    service_db_id: int
    ruta_id: int
    current_strands: int
    new_strand_pelo: Optional[str] = None
    new_strand_conector: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service_id": self.service_id,
            "service_db_id": self.service_db_id,
            "ruta_id": self.ruta_id,
            "current_strands": self.current_strands,
            "new_strand_pelo": self.new_strand_pelo,
            "new_strand_conector": self.new_strand_conector,
        }


@dataclass
class AnalysisResult:
    """Resultado del análisis de un archivo de tracking."""

    status: AnalysisStatus
    servicio_id: Optional[str] = None
    servicio_db_id: Optional[int] = None
    nuevo_hash: Optional[str] = None
    rutas_existentes: List[RutaInfo] = field(default_factory=list)
    ruta_identica_id: Optional[int] = None
    parsed_empalmes_count: int = 0
    message: str = ""
    error: Optional[str] = None
    # Nuevos campos para upgrade y strand
    upgrade_info: Optional[UpgradeInfo] = None
    strand_info: Optional[StrandInfo] = None
    # Info de puntas parseadas
    punta_a_sitio: Optional[str] = None
    punta_b_sitio: Optional[str] = None
    cantidad_pelos: Optional[int] = None
    alias_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "servicio_id": self.servicio_id,
            "servicio_db_id": self.servicio_db_id,
            "nuevo_hash": self.nuevo_hash,
            "rutas_existentes": [r.to_dict() for r in self.rutas_existentes],
            "ruta_identica_id": self.ruta_identica_id,
            "parsed_empalmes_count": self.parsed_empalmes_count,
            "message": self.message,
            "error": self.error,
            "upgrade_info": self.upgrade_info.to_dict() if self.upgrade_info else None,
            "strand_info": self.strand_info.to_dict() if self.strand_info else None,
            "punta_a_sitio": self.punta_a_sitio,
            "punta_b_sitio": self.punta_b_sitio,
            "cantidad_pelos": self.cantidad_pelos,
            "alias_id": self.alias_id,
        }


@dataclass
class ResolveResult:
    """Resultado de la resolución de un tracking."""

    success: bool
    action: ResolveAction
    servicio_id: Optional[str] = None
    servicio_db_id: Optional[int] = None
    ruta_id: Optional[int] = None
    ruta_nombre: Optional[str] = None
    camaras_nuevas: int = 0
    camaras_existentes: int = 0
    empalmes_creados: int = 0
    empalmes_asociados: int = 0
    message: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action.value,
            "servicio_id": self.servicio_id,
            "servicio_db_id": self.servicio_db_id,
            "ruta_id": self.ruta_id,
            "ruta_nombre": self.ruta_nombre,
            "camaras_nuevas": self.camaras_nuevas,
            "camaras_existentes": self.camaras_existentes,
            "empalmes_creados": self.empalmes_creados,
            "empalmes_asociados": self.empalmes_asociados,
            "message": self.message,
            "error": self.error,
        }


# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================


def compute_tracking_hash(raw_content: str) -> str:
    """Calcula el hash SHA256 del contenido del tracking.
    
    El hash se calcula sobre el contenido normalizado (sin espacios extra,
    líneas vacías al inicio/final) para evitar falsos positivos por
    diferencias de formato.
    """
    # Normalizar: quitar líneas vacías al inicio/final, normalizar saltos de línea
    lines = [line.strip() for line in raw_content.strip().splitlines()]
    normalized = "\n".join(line for line in lines if line)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _get_or_create_camara(
    session: Session,
    nombre: str,
    *,
    crear_si_no_existe: bool = True,
    servicio_id: Optional[str] = None,
) -> Tuple[Optional[Camara], bool]:
    """Busca una cámara por nombre o la crea si no existe.
    
    Si el servicio tiene un baneo activo, la cámara nueva nacerá BANEADA.
    
    Args:
        session: Sesión de SQLAlchemy
        nombre: Nombre de la cámara
        crear_si_no_existe: Si crear la cámara si no existe
        servicio_id: ID del servicio (para verificar baneo activo)
    
    Returns:
        Tuple[Camara|None, bool]: (cámara, es_nueva)
    """
    # Normalizar nombre para búsqueda
    nombre_norm = " ".join(nombre.strip().lower().split())
    
    # Buscar por coincidencia exacta
    camara = session.query(Camara).filter(Camara.nombre == nombre).first()
    if camara:
        return camara, False
    
    # Buscar normalizado
    all_cams = session.query(Camara).all()
    for c in all_cams:
        if c.nombre and " ".join(c.nombre.strip().lower().split()) == nombre_norm:
            return c, False
    
    if not crear_si_no_existe:
        return None, False
    
    # Determinar estado inicial de la cámara
    estado_inicial = CamaraEstado.DETECTADA
    
    # Si el servicio tiene baneo activo, la cámara nace BANEADA
    if servicio_id:
        from db.models.infra import IncidenteBaneo
        baneo_activo = session.query(IncidenteBaneo).filter(
            IncidenteBaneo.servicio_protegido_id == servicio_id,
            IncidenteBaneo.activo == True,
        ).first()
        
        if baneo_activo:
            estado_inicial = CamaraEstado.BANEADA
            logger.info(
                "action=create_camara_baneada nombre=%s servicio=%s baneo_id=%d",
                nombre,
                servicio_id,
                baneo_activo.id,
            )
    
    # Crear nueva cámara
    camara = Camara(
        nombre=nombre.strip(),
        estado=estado_inicial,
        origen_datos=CamaraOrigenDatos.TRACKING,
        last_update=datetime.now(timezone.utc),
    )
    session.add(camara)
    session.flush()
    return camara, True


def _get_or_create_empalme(
    session: Session,
    tracking_empalme_id: str,
    camara: Camara,
) -> Tuple[Empalme, bool]:
    """Obtiene o crea un empalme.
    
    Returns:
        Tuple[Empalme, bool]: (empalme, es_nuevo)
    """
    empalme = session.query(Empalme).filter(
        Empalme.tracking_empalme_id == tracking_empalme_id
    ).first()
    
    if empalme:
        # Actualizar cámara si cambió
        if empalme.camara_id != camara.id:
            empalme.camara_id = camara.id
        return empalme, False
    
    empalme = Empalme(
        tracking_empalme_id=tracking_empalme_id,
        camara_id=camara.id,
    )
    session.add(empalme)
    session.flush()
    return empalme, True


# =============================================================================
# SERVICIO PRINCIPAL
# =============================================================================


class InfraService:
    """Servicio de infraestructura de fibra óptica.
    
    Implementa el patrón "Portero" para gestión de archivos de tracking:
    - Análisis: Detecta si es nuevo, idéntico o conflicto
    - Resolución: Ejecuta la acción correspondiente con transacciones atómicas
    """

    def __init__(self, session: Session):
        """Inicializa el servicio con una sesión de SQLAlchemy.
        
        Args:
            session: Sesión activa de SQLAlchemy (el caller maneja el ciclo de vida)
        """
        self.session = session

    # -------------------------------------------------------------------------
    # FASE 1: ANÁLISIS
    # -------------------------------------------------------------------------

    def analyze_tracking(
        self,
        raw_content: str,
        filename: str,
    ) -> AnalysisResult:
        """Analiza un archivo de tracking y determina el escenario.
        
        Args:
            raw_content: Contenido crudo del archivo .txt
            filename: Nombre del archivo (para extraer servicio_id)
            
        Returns:
            AnalysisResult con status NEW, IDENTICAL, CONFLICT, POTENTIAL_UPGRADE o NEW_STRAND
        """
        try:
            # Parsear el archivo
            parsed = parse_tracking(raw_content, filename)
            
            if not parsed.servicio_id:
                return AnalysisResult(
                    status=AnalysisStatus.ERROR,
                    error=f"No se pudo extraer ID de servicio desde: {filename}",
                    message="El nombre del archivo debe contener un ID de servicio (ej: 'FO 111995 C2.txt')",
                )
            
            topologia = parsed.get_topologia()
            if not topologia:
                return AnalysisResult(
                    status=AnalysisStatus.ERROR,
                    servicio_id=parsed.servicio_id,
                    error="No se encontraron empalmes/ubicaciones en el archivo",
                    message="El archivo no contiene líneas con formato 'Empalme N: Ubicación'",
                )
            
            # Calcular hash del nuevo contenido
            nuevo_hash = compute_tracking_hash(raw_content)
            
            # Extraer info de puntas del parser
            punta_a_sitio = parsed.punta_a.sitio_descripcion if parsed.punta_a else None
            punta_b_sitio = parsed.punta_b.sitio_descripcion if parsed.punta_b else None
            
            # Buscar servicio existente por ID exacto
            servicio = self.session.query(Servicio).filter(
                Servicio.servicio_id == parsed.servicio_id
            ).first()
            
            # También buscar en alias_ids
            if not servicio:
                servicio = self.session.query(Servicio).filter(
                    Servicio.alias_ids.contains([parsed.servicio_id])
                ).first()
            
            # ESCENARIO 1: Servicio no existe - buscar por huella física (puntas)
            if not servicio:
                # Buscar coincidencia por puntas A/B
                upgrade_candidate = self._find_service_by_endpoints(punta_a_sitio, punta_b_sitio)
                
                if upgrade_candidate:
                    # POTENTIAL_UPGRADE: Mismas puntas pero diferente ID
                    upgrade_info = UpgradeInfo(
                        old_service_id=upgrade_candidate.servicio_id,
                        old_service_db_id=upgrade_candidate.id,
                        new_service_id=parsed.servicio_id,
                        match_reason="Endpoints Match",
                        punta_a_match=punta_a_sitio,
                        punta_b_match=punta_b_sitio,
                    )
                    logger.info(
                        "action=analyze_tracking status=POTENTIAL_UPGRADE old_id=%s new_id=%s",
                        upgrade_candidate.servicio_id,
                        parsed.servicio_id,
                    )
                    return AnalysisResult(
                        status=AnalysisStatus.POTENTIAL_UPGRADE,
                        servicio_id=parsed.servicio_id,
                        nuevo_hash=nuevo_hash,
                        parsed_empalmes_count=len(topologia),
                        upgrade_info=upgrade_info,
                        punta_a_sitio=punta_a_sitio,
                        punta_b_sitio=punta_b_sitio,
                        cantidad_pelos=parsed.cantidad_pelos,
                        alias_id=parsed.alias_id,
                        message=f"Detectado posible upgrade: Servicio {upgrade_candidate.servicio_id} → {parsed.servicio_id}. Mismos endpoints.",
                    )
                
                # Servicio completamente nuevo
                logger.info(
                    "action=analyze_tracking status=NEW servicio_id=%s hash=%s empalmes=%d",
                    parsed.servicio_id,
                    nuevo_hash[:16],
                    len(topologia),
                )
                return AnalysisResult(
                    status=AnalysisStatus.NEW,
                    servicio_id=parsed.servicio_id,
                    nuevo_hash=nuevo_hash,
                    parsed_empalmes_count=len(topologia),
                    punta_a_sitio=punta_a_sitio,
                    punta_b_sitio=punta_b_sitio,
                    cantidad_pelos=parsed.cantidad_pelos,
                    alias_id=parsed.alias_id,
                    message=f"Servicio {parsed.servicio_id} es nuevo. Se creará con una ruta principal.",
                )
            
            # ESCENARIO 2/3/4: Servicio existe
            rutas_info = []
            ruta_identica = None
            ruta_mismo_camino: Optional[RutaServicio] = None
            
            for ruta in servicio.rutas:
                info = RutaInfo(
                    id=ruta.id,
                    nombre=ruta.nombre,
                    tipo=ruta.tipo.value if ruta.tipo else "PRINCIPAL",
                    hash_contenido=ruta.hash_contenido,
                    empalmes_count=len(ruta.empalmes),
                    activa=bool(ruta.activa),
                    created_at=ruta.created_at.isoformat() if ruta.created_at else None,
                    nombre_archivo_origen=ruta.nombre_archivo_origen,
                )
                rutas_info.append(info)
                
                # Comparar hash exacto
                if ruta.hash_contenido == nuevo_hash:
                    ruta_identica = ruta.id
                
                # Verificar si es el mismo camino (mismas puntas) para detectar nuevo pelo
                if self._routes_have_same_path(ruta, punta_a_sitio, punta_b_sitio):
                    ruta_mismo_camino = ruta
            
            # ESCENARIO 2: Hash coincide exacto
            if ruta_identica:
                logger.info(
                    "action=analyze_tracking status=IDENTICAL servicio_id=%s ruta_id=%d",
                    parsed.servicio_id,
                    ruta_identica,
                )
                return AnalysisResult(
                    status=AnalysisStatus.IDENTICAL,
                    servicio_id=parsed.servicio_id,
                    servicio_db_id=servicio.id,
                    nuevo_hash=nuevo_hash,
                    rutas_existentes=rutas_info,
                    ruta_identica_id=ruta_identica,
                    parsed_empalmes_count=len(topologia),
                    punta_a_sitio=punta_a_sitio,
                    punta_b_sitio=punta_b_sitio,
                    cantidad_pelos=parsed.cantidad_pelos,
                    alias_id=parsed.alias_id,
                    message=f"El archivo es idéntico a la ruta existente (ID: {ruta_identica}). No se requiere acción.",
                )
            
            # ESCENARIO 2.5: Servicio existe pero sin rutas
            if len(rutas_info) == 0:
                logger.info(
                    "action=analyze_tracking status=NEW servicio_id=%s hash=%s note=servicio_sin_rutas",
                    parsed.servicio_id,
                    nuevo_hash[:16],
                )
                return AnalysisResult(
                    status=AnalysisStatus.NEW,
                    servicio_id=parsed.servicio_id,
                    servicio_db_id=servicio.id,
                    nuevo_hash=nuevo_hash,
                    parsed_empalmes_count=len(topologia),
                    punta_a_sitio=punta_a_sitio,
                    punta_b_sitio=punta_b_sitio,
                    cantidad_pelos=parsed.cantidad_pelos,
                    alias_id=parsed.alias_id,
                    message=f"Servicio {parsed.servicio_id} existe pero sin rutas. Se creará una ruta principal.",
                )
            
            # NOTA: La detección automática de NEW_STRAND fue deshabilitada.
            # La opción de agregar pelo se ofrece manualmente en el modal de conflicto.
            
            # ESCENARIO 3: Conflicto genérico (incluye opción manual de agregar pelo)
            logger.info(
                "action=analyze_tracking status=CONFLICT servicio_id=%s rutas=%d hash=%s",
                parsed.servicio_id,
                len(rutas_info),
                nuevo_hash[:16],
            )
            return AnalysisResult(
                status=AnalysisStatus.CONFLICT,
                servicio_id=parsed.servicio_id,
                servicio_db_id=servicio.id,
                nuevo_hash=nuevo_hash,
                rutas_existentes=rutas_info,
                parsed_empalmes_count=len(topologia),
                punta_a_sitio=punta_a_sitio,
                punta_b_sitio=punta_b_sitio,
                cantidad_pelos=parsed.cantidad_pelos,
                alias_id=parsed.alias_id,
                message=f"El servicio {parsed.servicio_id} ya existe con {len(rutas_info)} ruta(s). Seleccioná una acción.",
            )
            
        except Exception as exc:
            logger.exception("action=analyze_tracking_error filename=%s error=%s", filename, exc)
            return AnalysisResult(
                status=AnalysisStatus.ERROR,
                error=str(exc),
                message="Error inesperado durante el análisis del archivo",
            )

    def _find_service_by_endpoints(
        self,
        punta_a_sitio: Optional[str],
        punta_b_sitio: Optional[str],
    ) -> Optional[Servicio]:
        """Busca un servicio que tenga las mismas puntas A y B.
        
        Args:
            punta_a_sitio: Descripción del sitio de la punta A
            punta_b_sitio: Descripción del sitio de la punta B
            
        Returns:
            Servicio encontrado o None
        """
        if not punta_a_sitio and not punta_b_sitio:
            return None
        
        # Buscar en puntos_terminales
        query = self.session.query(PuntoTerminal).join(
            RutaServicio, PuntoTerminal.ruta_id == RutaServicio.id
        )
        
        # Filtrar por punta A
        if punta_a_sitio:
            punta_a_norm = punta_a_sitio.strip().upper()
            matching_a = query.filter(
                PuntoTerminal.tipo == PuntoTerminalTipo.A,
                func.upper(PuntoTerminal.sitio_descripcion) == punta_a_norm,
            ).first()
            
            if matching_a:
                ruta = self.session.query(RutaServicio).get(matching_a.ruta_id)
                if ruta:
                    # Verificar también punta B si se proporcionó
                    if punta_b_sitio:
                        punta_b_norm = punta_b_sitio.strip().upper()
                        punta_b_db = self.session.query(PuntoTerminal).filter(
                            PuntoTerminal.ruta_id == ruta.id,
                            PuntoTerminal.tipo == PuntoTerminalTipo.B,
                            func.upper(PuntoTerminal.sitio_descripcion) == punta_b_norm,
                        ).first()
                        if punta_b_db:
                            return ruta.servicio
                    else:
                        return ruta.servicio
        
        return None

    def _routes_have_same_path(
        self,
        ruta: RutaServicio,
        punta_a_sitio: Optional[str],
        punta_b_sitio: Optional[str],
    ) -> bool:
        """Verifica si una ruta tiene las mismas puntas A y B.
        
        Args:
            ruta: Ruta a verificar
            punta_a_sitio: Descripción del sitio de la punta A del archivo
            punta_b_sitio: Descripción del sitio de la punta B del archivo
            
        Returns:
            True si las puntas coinciden
        """
        if not punta_a_sitio and not punta_b_sitio:
            return False
        
        # Obtener puntas de la ruta
        ruta_punta_a = ruta.punta_a
        ruta_punta_b = ruta.punta_b
        
        # Comparar punta A
        if punta_a_sitio and ruta_punta_a:
            if punta_a_sitio.strip().upper() != (ruta_punta_a.sitio_descripcion or "").strip().upper():
                return False
        elif punta_a_sitio or ruta_punta_a:
            return False  # Una tiene y la otra no
        
        # Comparar punta B
        if punta_b_sitio and ruta_punta_b:
            if punta_b_sitio.strip().upper() != (ruta_punta_b.sitio_descripcion or "").strip().upper():
                return False
        elif punta_b_sitio or ruta_punta_b:
            return False  # Una tiene y la otra no
        
        return True

    # -------------------------------------------------------------------------
    # FASE 2: RESOLUCIÓN
    # -------------------------------------------------------------------------

    def resolve_tracking(
        self,
        action: ResolveAction,
        raw_content: str,
        filename: str,
        *,
        target_ruta_id: Optional[int] = None,
        new_ruta_name: Optional[str] = None,
        new_ruta_tipo: RutaTipo = RutaTipo.ALTERNATIVA,
        old_service_id: Optional[str] = None,  # Para CONFIRM_UPGRADE
    ) -> ResolveResult:
        """Resuelve un tracking ejecutando la acción especificada.
        
        Args:
            action: Acción a ejecutar (CREATE_NEW, MERGE_APPEND, REPLACE, BRANCH, CONFIRM_UPGRADE, ADD_STRAND)
            raw_content: Contenido crudo del archivo
            filename: Nombre del archivo
            target_ruta_id: ID de la ruta destino (para MERGE_APPEND, REPLACE, ADD_STRAND)
            new_ruta_name: Nombre de la nueva ruta (para BRANCH)
            new_ruta_tipo: Tipo de la nueva ruta (para BRANCH)
            old_service_id: ID del servicio viejo (para CONFIRM_UPGRADE)
            
        Returns:
            ResolveResult con el resultado de la operación
        """
        try:
            # Parsear contenido
            parsed = parse_tracking(raw_content, filename)
            if not parsed.servicio_id:
                return ResolveResult(
                    success=False,
                    action=action,
                    error="No se pudo extraer ID de servicio",
                    message="Nombre de archivo inválido",
                )
            
            topologia = parsed.get_topologia()
            if not topologia:
                return ResolveResult(
                    success=False,
                    action=action,
                    servicio_id=parsed.servicio_id,
                    error="Sin empalmes en el archivo",
                    message="El archivo no contiene ubicaciones válidas",
                )
            
            content_hash = compute_tracking_hash(raw_content)
            
            # Ejecutar acción correspondiente
            if action == ResolveAction.CREATE_NEW:
                return self._action_create_new(parsed, topologia, content_hash, filename, raw_content)
            elif action == ResolveAction.MERGE_APPEND:
                return self._action_merge_append(parsed, topologia, content_hash, filename, raw_content, target_ruta_id)
            elif action == ResolveAction.REPLACE:
                return self._action_replace(parsed, topologia, content_hash, filename, raw_content, target_ruta_id)
            elif action == ResolveAction.BRANCH:
                return self._action_branch(parsed, topologia, content_hash, filename, raw_content, new_ruta_name, new_ruta_tipo)
            elif action == ResolveAction.CONFIRM_UPGRADE:
                return self._action_confirm_upgrade(parsed, topologia, content_hash, filename, raw_content, old_service_id)
            elif action == ResolveAction.ADD_STRAND:
                return self._action_add_strand(parsed, topologia, content_hash, filename, raw_content, target_ruta_id)
            else:
                return ResolveResult(
                    success=False,
                    action=action,
                    error=f"Acción no soportada: {action}",
                )
                
        except Exception as exc:
            logger.exception("action=resolve_tracking_error action=%s error=%s", action, exc)
            self.session.rollback()
            return ResolveResult(
                success=False,
                action=action,
                error=str(exc),
                message="Error durante la resolución. Se hizo rollback de la transacción.",
            )

    def _action_create_new(
        self,
        parsed: TrackingParseResult,
        topologia: List[Tuple[str, str]],
        content_hash: str,
        filename: str,
        raw_content: str,
    ) -> ResolveResult:
        """CREATE_NEW: Crea servicio + ruta principal.
        
        Si el servicio ya existe pero sin rutas (fue limpiado), 
        reutiliza el servicio existente y crea una nueva ruta principal.
        """
        
        # Verificar si existe
        existing = self.session.query(Servicio).filter(
            Servicio.servicio_id == parsed.servicio_id
        ).first()
        
        if existing and len(existing.rutas) > 0:
            # Ya tiene rutas, no se puede usar CREATE_NEW
            return ResolveResult(
                success=False,
                action=ResolveAction.CREATE_NEW,
                servicio_id=parsed.servicio_id,
                error="El servicio ya existe con rutas",
                message=f"Usá BRANCH o REPLACE para agregar rutas al servicio {parsed.servicio_id}",
            )
        
        # Usar servicio existente o crear nuevo
        if existing:
            servicio = existing
            logger.info(
                "action=create_new note=reutilizando_servicio servicio_id=%s db_id=%d",
                parsed.servicio_id,
                servicio.id,
            )
        else:
            servicio = Servicio(
                servicio_id=parsed.servicio_id,
                nombre_archivo_origen=filename,
            )
            self.session.add(servicio)
            self.session.flush()
        
        # Crear ruta principal
        ruta = RutaServicio(
            servicio_id=servicio.id,
            nombre="Principal",
            tipo=RutaTipo.PRINCIPAL,
            hash_contenido=content_hash,
            nombre_archivo_origen=filename,
            contenido_original=json.dumps(parsed.to_dict(), ensure_ascii=False),
            raw_file_content=raw_content,  # Guardar el archivo TXT original exacto
            activa=True,
        )
        self.session.add(ruta)
        self.session.flush()
        
        # Procesar empalmes y cámaras
        camaras_nuevas = 0
        camaras_existentes = 0
        empalmes_creados = 0
        empalmes_asociados: set[int] = set()  # Para evitar duplicados en la misma ruta
        
        for orden, (empalme_id, ubicacion) in enumerate(topologia, start=1):
            # Obtener o crear cámara (pasa servicio_id para verificar baneo)
            camara, es_nueva = _get_or_create_camara(
                self.session, ubicacion, servicio_id=parsed.servicio_id
            )
            if es_nueva:
                camaras_nuevas += 1
            else:
                camaras_existentes += 1
            
            # Obtener o crear empalme
            tracking_id = f"{parsed.servicio_id}_{empalme_id}"
            empalme, es_nuevo = _get_or_create_empalme(self.session, tracking_id, camara)
            if es_nuevo:
                empalmes_creados += 1
            
            # Asociar empalme a la ruta con orden (evitar duplicados)
            if empalme.id not in empalmes_asociados:
                stmt = ruta_empalme_association.insert().values(
                    ruta_id=ruta.id,
                    empalme_id=empalme.id,
                    orden=orden,
                )
                self.session.execute(stmt)
                empalmes_asociados.add(empalme.id)
            
            # También mantener relación legacy servicio<->empalme
            if empalme not in servicio.empalmes:
                servicio.empalmes.append(empalme)
        
        # Guardar puntos terminales (Punta A y B)
        self._update_puntos_terminales(ruta, parsed)
        
        # Actualizar alias si viene en el archivo
        if parsed.alias_id:
            current_aliases = servicio.alias_ids or []
            if parsed.alias_id not in current_aliases:
                servicio.alias_ids = current_aliases + [parsed.alias_id]
        
        # Actualizar cantidad de pelos
        if parsed.cantidad_pelos and parsed.cantidad_pelos > 1:
            ruta.cantidad_pelos = parsed.cantidad_pelos
        
        self.session.commit()
        
        logger.info(
            "action=create_new servicio_id=%s ruta_id=%d camaras_nuevas=%d empalmes=%d alias=%s",
            parsed.servicio_id,
            ruta.id,
            camaras_nuevas,
            empalmes_creados,
            parsed.alias_id,
        )
        
        return ResolveResult(
            success=True,
            action=ResolveAction.CREATE_NEW,
            servicio_id=parsed.servicio_id,
            servicio_db_id=servicio.id,
            ruta_id=ruta.id,
            ruta_nombre=ruta.nombre,
            camaras_nuevas=camaras_nuevas,
            camaras_existentes=camaras_existentes,
            empalmes_creados=empalmes_creados,
            empalmes_asociados=len(topologia),
            message=f"Servicio {parsed.servicio_id} creado con ruta 'Principal' ({len(topologia)} empalmes)",
        )

    def _action_merge_append(
        self,
        parsed: TrackingParseResult,
        topologia: List[Tuple[str, str]],
        content_hash: str,
        filename: str,
        raw_content: str,
        target_ruta_id: Optional[int],
    ) -> ResolveResult:
        """MERGE_APPEND: Agrega empalmes nuevos a una ruta existente sin borrar los actuales."""
        
        if not target_ruta_id:
            return ResolveResult(
                success=False,
                action=ResolveAction.MERGE_APPEND,
                servicio_id=parsed.servicio_id,
                error="target_ruta_id es requerido para MERGE_APPEND",
            )
        
        ruta = self.session.query(RutaServicio).get(target_ruta_id)
        if not ruta:
            return ResolveResult(
                success=False,
                action=ResolveAction.MERGE_APPEND,
                error=f"Ruta {target_ruta_id} no encontrada",
            )
        
        servicio = ruta.servicio
        
        # Obtener empalmes existentes para evitar duplicados
        empalmes_existentes_ids = {e.id for e in ruta.empalmes}
        max_orden = len(ruta.empalmes)
        
        camaras_nuevas = 0
        camaras_existentes = 0
        empalmes_creados = 0
        empalmes_agregados = 0
        
        for empalme_id, ubicacion in topologia:
            # Obtener o crear cámara (pasa servicio_id para verificar baneo)
            camara, es_nueva = _get_or_create_camara(
                self.session, ubicacion, servicio_id=parsed.servicio_id
            )
            if es_nueva:
                camaras_nuevas += 1
            else:
                camaras_existentes += 1
            
            # Obtener o crear empalme
            tracking_id = f"{parsed.servicio_id}_{empalme_id}"
            empalme, es_nuevo = _get_or_create_empalme(self.session, tracking_id, camara)
            if es_nuevo:
                empalmes_creados += 1
            
            # Solo agregar si no existe en la ruta
            if empalme.id not in empalmes_existentes_ids:
                max_orden += 1
                stmt = ruta_empalme_association.insert().values(
                    ruta_id=ruta.id,
                    empalme_id=empalme.id,
                    orden=max_orden,
                )
                self.session.execute(stmt)
                empalmes_agregados += 1
                empalmes_existentes_ids.add(empalme.id)
            
            # Mantener relación legacy
            if empalme not in servicio.empalmes:
                servicio.empalmes.append(empalme)
        
        # Actualizar metadata de la ruta
        ruta.hash_contenido = content_hash
        ruta.raw_file_content = raw_content  # Preservar archivo original
        ruta.updated_at = datetime.now(timezone.utc)
        
        self.session.commit()
        
        logger.info(
            "action=merge_append servicio_id=%s ruta_id=%d empalmes_agregados=%d",
            parsed.servicio_id,
            ruta.id,
            empalmes_agregados,
        )
        
        return ResolveResult(
            success=True,
            action=ResolveAction.MERGE_APPEND,
            servicio_id=servicio.servicio_id,
            servicio_db_id=servicio.id,
            ruta_id=ruta.id,
            ruta_nombre=ruta.nombre,
            camaras_nuevas=camaras_nuevas,
            camaras_existentes=camaras_existentes,
            empalmes_creados=empalmes_creados,
            empalmes_asociados=empalmes_agregados,
            message=f"Agregados {empalmes_agregados} empalmes a la ruta '{ruta.nombre}'",
        )

    def _action_replace(
        self,
        parsed: TrackingParseResult,
        topologia: List[Tuple[str, str]],
        content_hash: str,
        filename: str,
        raw_content: str,
        target_ruta_id: Optional[int],
    ) -> ResolveResult:
        """REPLACE: Reemplaza completamente los empalmes de una ruta."""
        
        if not target_ruta_id:
            return ResolveResult(
                success=False,
                action=ResolveAction.REPLACE,
                servicio_id=parsed.servicio_id,
                error="target_ruta_id es requerido para REPLACE",
            )
        
        ruta = self.session.query(RutaServicio).get(target_ruta_id)
        if not ruta:
            return ResolveResult(
                success=False,
                action=ResolveAction.REPLACE,
                error=f"Ruta {target_ruta_id} no encontrada",
            )
        
        servicio = ruta.servicio
        
        # Eliminar asociaciones existentes
        self.session.execute(
            ruta_empalme_association.delete().where(
                ruta_empalme_association.c.ruta_id == ruta.id
            )
        )
        
        camaras_nuevas = 0
        camaras_existentes = 0
        empalmes_creados = 0
        empalmes_asociados: set[int] = set()  # Para evitar duplicados en la misma ruta
        
        for orden, (empalme_id, ubicacion) in enumerate(topologia, start=1):
            # Obtener o crear cámara
            camara, es_nueva = _get_or_create_camara(self.session, ubicacion)
            if es_nueva:
                camaras_nuevas += 1
            else:
                camaras_existentes += 1
            
            # Obtener o crear empalme
            tracking_id = f"{parsed.servicio_id}_{empalme_id}"
            empalme, es_nuevo = _get_or_create_empalme(self.session, tracking_id, camara)
            if es_nuevo:
                empalmes_creados += 1
            
            # Asociar a la ruta (evitar duplicados)
            if empalme.id not in empalmes_asociados:
                stmt = ruta_empalme_association.insert().values(
                    ruta_id=ruta.id,
                    empalme_id=empalme.id,
                    orden=orden,
                )
                self.session.execute(stmt)
                empalmes_asociados.add(empalme.id)
            
            # Mantener relación legacy
            if empalme not in servicio.empalmes:
                servicio.empalmes.append(empalme)
        
        # Actualizar metadata
        ruta.hash_contenido = content_hash
        ruta.nombre_archivo_origen = filename
        ruta.contenido_original = json.dumps(parsed.to_dict(), ensure_ascii=False)
        ruta.raw_file_content = raw_content  # Preservar archivo original
        ruta.updated_at = datetime.now(timezone.utc)
        
        self.session.commit()
        
        logger.info(
            "action=replace servicio_id=%s ruta_id=%d empalmes=%d",
            parsed.servicio_id,
            ruta.id,
            len(topologia),
        )
        
        return ResolveResult(
            success=True,
            action=ResolveAction.REPLACE,
            servicio_id=servicio.servicio_id,
            servicio_db_id=servicio.id,
            ruta_id=ruta.id,
            ruta_nombre=ruta.nombre,
            camaras_nuevas=camaras_nuevas,
            camaras_existentes=camaras_existentes,
            empalmes_creados=empalmes_creados,
            empalmes_asociados=len(topologia),
            message=f"Ruta '{ruta.nombre}' actualizada con {len(topologia)} empalmes",
        )

    def _action_branch(
        self,
        parsed: TrackingParseResult,
        topologia: List[Tuple[str, str]],
        content_hash: str,
        filename: str,
        raw_content: str,
        new_ruta_name: Optional[str],
        new_ruta_tipo: RutaTipo,
    ) -> ResolveResult:
        """BRANCH: Crea una nueva ruta bajo el mismo servicio."""
        
        # Buscar servicio
        servicio = self.session.query(Servicio).filter(
            Servicio.servicio_id == parsed.servicio_id
        ).first()
        
        if not servicio:
            return ResolveResult(
                success=False,
                action=ResolveAction.BRANCH,
                servicio_id=parsed.servicio_id,
                error="Servicio no encontrado",
                message=f"El servicio {parsed.servicio_id} no existe. Usá CREATE_NEW primero.",
            )
        
        # Generar nombre si no se provee
        if not new_ruta_name:
            rutas_count = len(servicio.rutas)
            new_ruta_name = f"Ruta {rutas_count + 1}"
        
        # Verificar que no exista una ruta con el mismo nombre
        for ruta in servicio.rutas:
            if ruta.nombre.lower() == new_ruta_name.lower():
                return ResolveResult(
                    success=False,
                    action=ResolveAction.BRANCH,
                    servicio_id=parsed.servicio_id,
                    error=f"Ya existe una ruta con nombre '{new_ruta_name}'",
                )
        
        # Crear nueva ruta
        ruta = RutaServicio(
            servicio_id=servicio.id,
            nombre=new_ruta_name,
            tipo=new_ruta_tipo,
            hash_contenido=content_hash,
            nombre_archivo_origen=filename,
            contenido_original=json.dumps(parsed.to_dict(), ensure_ascii=False),
            raw_file_content=raw_content,  # Guardar el archivo TXT original exacto
            activa=True,
        )
        self.session.add(ruta)
        self.session.flush()
        
        camaras_nuevas = 0
        camaras_existentes = 0
        empalmes_creados = 0
        empalmes_asociados: set[int] = set()  # Para evitar duplicados en la misma ruta
        
        for orden, (empalme_id, ubicacion) in enumerate(topologia, start=1):
            # Obtener o crear cámara (pasa servicio_id para verificar baneo)
            camara, es_nueva = _get_or_create_camara(
                self.session, ubicacion, servicio_id=parsed.servicio_id
            )
            if es_nueva:
                camaras_nuevas += 1
            else:
                camaras_existentes += 1
            
            # Obtener o crear empalme
            tracking_id = f"{parsed.servicio_id}_{empalme_id}"
            empalme, es_nuevo = _get_or_create_empalme(self.session, tracking_id, camara)
            if es_nuevo:
                empalmes_creados += 1
            
            # Asociar a la ruta (evitar duplicados)
            if empalme.id not in empalmes_asociados:
                stmt = ruta_empalme_association.insert().values(
                    ruta_id=ruta.id,
                    empalme_id=empalme.id,
                    orden=orden,
                )
                self.session.execute(stmt)
                empalmes_asociados.add(empalme.id)
            
            # Mantener relación legacy
            if empalme not in servicio.empalmes:
                servicio.empalmes.append(empalme)
        
        self.session.commit()
        
        logger.info(
            "action=branch servicio_id=%s ruta_id=%d nombre=%s tipo=%s empalmes=%d",
            parsed.servicio_id,
            ruta.id,
            ruta.nombre,
            ruta.tipo.value,
            len(empalmes_asociados),
        )
        
        return ResolveResult(
            success=True,
            action=ResolveAction.BRANCH,
            servicio_id=servicio.servicio_id,
            servicio_db_id=servicio.id,
            ruta_id=ruta.id,
            ruta_nombre=ruta.nombre,
            camaras_nuevas=camaras_nuevas,
            camaras_existentes=camaras_existentes,
            empalmes_creados=empalmes_creados,
            empalmes_asociados=len(empalmes_asociados),
            message=f"Nueva ruta '{ruta.nombre}' ({ruta.tipo.value}) creada con {len(empalmes_asociados)} empalmes",
        )

    def _action_confirm_upgrade(
        self,
        parsed: TrackingParseResult,
        topologia: List[Tuple[str, str]],
        content_hash: str,
        filename: str,
        raw_content: str,
        old_service_id: Optional[str],
    ) -> ResolveResult:
        """CONFIRM_UPGRADE: Confirma un upgrade de servicio.
        
        Mueve el ID viejo a alias_ids y setea el nuevo ID como principal.
        Luego re-procesa el tracking para actualizar/validar las cámaras.
        """
        if not old_service_id:
            return ResolveResult(
                success=False,
                action=ResolveAction.CONFIRM_UPGRADE,
                servicio_id=parsed.servicio_id,
                error="old_service_id es requerido para CONFIRM_UPGRADE",
            )
        
        # Buscar el servicio viejo
        old_servicio = self.session.query(Servicio).filter(
            Servicio.servicio_id == old_service_id
        ).first()
        
        if not old_servicio:
            return ResolveResult(
                success=False,
                action=ResolveAction.CONFIRM_UPGRADE,
                servicio_id=parsed.servicio_id,
                error=f"Servicio viejo '{old_service_id}' no encontrado",
            )
        
        # Verificar que el nuevo ID no exista
        existing_new = self.session.query(Servicio).filter(
            Servicio.servicio_id == parsed.servicio_id
        ).first()
        
        if existing_new and existing_new.id != old_servicio.id:
            return ResolveResult(
                success=False,
                action=ResolveAction.CONFIRM_UPGRADE,
                servicio_id=parsed.servicio_id,
                error=f"El nuevo ID '{parsed.servicio_id}' ya existe como otro servicio",
            )
        
        # Mover el ID viejo a alias_ids
        current_aliases = old_servicio.alias_ids or []
        if old_service_id not in current_aliases:
            current_aliases.append(old_service_id)
        
        # Agregar el alias del archivo si existe
        if parsed.alias_id and parsed.alias_id not in current_aliases:
            current_aliases.append(parsed.alias_id)
        
        old_servicio.alias_ids = current_aliases
        old_servicio.servicio_id = parsed.servicio_id
        
        # Obtener la ruta principal o la primera activa
        ruta_target = old_servicio.ruta_principal
        
        if ruta_target:
            # Actualizar hash y contenido de la ruta
            ruta_target.hash_contenido = content_hash
            ruta_target.nombre_archivo_origen = filename
            ruta_target.contenido_original = json.dumps(parsed.to_dict(), ensure_ascii=False)
            ruta_target.raw_file_content = raw_content
            ruta_target.cantidad_pelos = parsed.cantidad_pelos
            
            # Actualizar/crear puntos terminales
            self._update_puntos_terminales(ruta_target, parsed)
        else:
            # Crear ruta principal si no existe
            ruta_target = RutaServicio(
                servicio_id=old_servicio.id,
                nombre="Principal",
                tipo=RutaTipo.PRINCIPAL,
                hash_contenido=content_hash,
                nombre_archivo_origen=filename,
                contenido_original=json.dumps(parsed.to_dict(), ensure_ascii=False),
                raw_file_content=raw_content,
                cantidad_pelos=parsed.cantidad_pelos,
                activa=True,
            )
            self.session.add(ruta_target)
            self.session.flush()
            
            # Crear puntos terminales
            self._update_puntos_terminales(ruta_target, parsed)
        
        # Re-procesar empalmes y cámaras
        camaras_nuevas = 0
        camaras_existentes = 0
        empalmes_creados = 0
        empalmes_asociados: set[int] = set()
        
        for orden, (empalme_id, ubicacion) in enumerate(topologia, start=1):
            camara, es_nueva = _get_or_create_camara(
                self.session, ubicacion, servicio_id=parsed.servicio_id
            )
            if es_nueva:
                camaras_nuevas += 1
            else:
                camaras_existentes += 1
            
            tracking_id = f"{parsed.servicio_id}_{empalme_id}"
            empalme, es_nuevo = _get_or_create_empalme(self.session, tracking_id, camara)
            
            # Marcar como tránsito si corresponde
            transitos = parsed.get_transitos()
            is_transito = any(t.empalme_id == empalme_id for t in transitos)
            empalme.es_transito = is_transito
            
            if es_nuevo:
                empalmes_creados += 1
            
            if empalme.id not in empalmes_asociados:
                # Verificar si ya está asociado
                existing = self.session.execute(
                    ruta_empalme_association.select().where(
                        ruta_empalme_association.c.ruta_id == ruta_target.id,
                        ruta_empalme_association.c.empalme_id == empalme.id,
                    )
                ).first()
                
                if not existing:
                    stmt = ruta_empalme_association.insert().values(
                        ruta_id=ruta_target.id,
                        empalme_id=empalme.id,
                        orden=orden,
                    )
                    self.session.execute(stmt)
                
                empalmes_asociados.add(empalme.id)
            
            if empalme not in old_servicio.empalmes:
                old_servicio.empalmes.append(empalme)
        
        self.session.commit()
        
        logger.info(
            "action=confirm_upgrade old_id=%s new_id=%s aliases=%s",
            old_service_id,
            parsed.servicio_id,
            current_aliases,
        )
        
        return ResolveResult(
            success=True,
            action=ResolveAction.CONFIRM_UPGRADE,
            servicio_id=old_servicio.servicio_id,
            servicio_db_id=old_servicio.id,
            ruta_id=ruta_target.id,
            ruta_nombre=ruta_target.nombre,
            camaras_nuevas=camaras_nuevas,
            camaras_existentes=camaras_existentes,
            empalmes_creados=empalmes_creados,
            empalmes_asociados=len(empalmes_asociados),
            message=f"Upgrade confirmado: {old_service_id} → {parsed.servicio_id}. Aliases: {current_aliases}",
        )

    def _action_add_strand(
        self,
        parsed: TrackingParseResult,
        topologia: List[Tuple[str, str]],
        content_hash: str,
        filename: str,
        raw_content: str,
        target_ruta_id: Optional[int],
    ) -> ResolveResult:
        """ADD_STRAND: Agrega un nuevo pelo a una ruta existente.
        
        Crea una nueva ruta con el mismo nombre base pero con sufijo de pelo.
        Cada pelo tiene su propio raw_content para poder descargarlo.
        """
        if not target_ruta_id:
            return ResolveResult(
                success=False,
                action=ResolveAction.ADD_STRAND,
                servicio_id=parsed.servicio_id,
                error="target_ruta_id es requerido para ADD_STRAND",
            )
        
        # Buscar la ruta base
        ruta_base = self.session.query(RutaServicio).get(target_ruta_id)
        if not ruta_base:
            return ResolveResult(
                success=False,
                action=ResolveAction.ADD_STRAND,
                servicio_id=parsed.servicio_id,
                error=f"Ruta {target_ruta_id} no encontrada",
            )
        
        servicio = ruta_base.servicio
        
        # Contar pelos existentes (rutas con el mismo nombre base)
        nombre_base = ruta_base.nombre.split(" - Pelo")[0]  # Quitar sufijo si existe
        pelos_existentes = self.session.query(RutaServicio).filter(
            RutaServicio.servicio_id == servicio.id,
            RutaServicio.nombre.like(f"{nombre_base}%"),
        ).count()
        
        # Determinar número de pelo
        nuevo_pelo_num = pelos_existentes + 1
        alias_pelo = parsed.alias_id or f"C{nuevo_pelo_num}"
        
        # Crear nueva ruta para el pelo
        nuevo_nombre = f"{nombre_base} - Pelo {nuevo_pelo_num} ({alias_pelo})"
        
        nueva_ruta = RutaServicio(
            servicio_id=servicio.id,
            nombre=nuevo_nombre,
            tipo=ruta_base.tipo,  # Mismo tipo que la ruta base
            hash_contenido=content_hash,
            nombre_archivo_origen=filename,
            contenido_original=json.dumps(parsed.to_dict(), ensure_ascii=False),
            raw_file_content=raw_content,
            activa=True,
        )
        self.session.add(nueva_ruta)
        self.session.flush()
        
        # Procesar empalmes (asociarlos a la nueva ruta)
        empalmes_asociados: set[int] = set()
        for orden, (empalme_id, ubicacion) in enumerate(topologia, start=1):
            camara, _ = _get_or_create_camara(
                self.session, ubicacion, servicio_id=parsed.servicio_id
            )
            tracking_id = f"{parsed.servicio_id}_{empalme_id}"
            empalme, _ = _get_or_create_empalme(self.session, tracking_id, camara)
            
            if empalme.id not in empalmes_asociados:
                stmt = ruta_empalme_association.insert().values(
                    ruta_id=nueva_ruta.id,
                    empalme_id=empalme.id,
                    orden=orden,
                )
                self.session.execute(stmt)
                empalmes_asociados.add(empalme.id)
        
        # Agregar alias al servicio si existe
        if parsed.alias_id:
            current_aliases = servicio.alias_ids or []
            if parsed.alias_id not in current_aliases:
                current_aliases.append(parsed.alias_id)
                servicio.alias_ids = current_aliases
        
        # Guardar puntos terminales
        self._update_puntos_terminales(nueva_ruta, parsed)
        
        self.session.commit()
        
        logger.info(
            "action=add_strand servicio_id=%s ruta_id=%d pelo=%d nombre=%s alias=%s",
            servicio.servicio_id,
            nueva_ruta.id,
            nuevo_pelo_num,
            nuevo_nombre,
            parsed.alias_id,
        )
        
        return ResolveResult(
            success=True,
            action=ResolveAction.ADD_STRAND,
            servicio_id=servicio.servicio_id,
            servicio_db_id=servicio.id,
            ruta_id=nueva_ruta.id,
            ruta_nombre=nuevo_nombre,
            message=f"Pelo {nuevo_pelo_num} agregado como '{nuevo_nombre}'",
        )

    def _update_puntos_terminales(
        self,
        ruta: RutaServicio,
        parsed: TrackingParseResult,
    ) -> None:
        """Actualiza o crea los puntos terminales de una ruta desde el parsed result."""
        
        # Actualizar/crear Punta A
        if parsed.punta_a:
            punta_a_db = self.session.query(PuntoTerminal).filter(
                PuntoTerminal.ruta_id == ruta.id,
                PuntoTerminal.tipo == PuntoTerminalTipo.A,
            ).first()
            
            if punta_a_db:
                punta_a_db.sitio_descripcion = parsed.punta_a.sitio_descripcion
                punta_a_db.identificador_fisico = parsed.punta_a.identificador_fisico
                punta_a_db.pelo_conector = parsed.punta_a.pelo_conector
            else:
                punta_a_db = PuntoTerminal(
                    ruta_id=ruta.id,
                    tipo=PuntoTerminalTipo.A,
                    sitio_descripcion=parsed.punta_a.sitio_descripcion,
                    identificador_fisico=parsed.punta_a.identificador_fisico,
                    pelo_conector=parsed.punta_a.pelo_conector,
                )
                self.session.add(punta_a_db)
        
        # Actualizar/crear Punta B
        if parsed.punta_b:
            punta_b_db = self.session.query(PuntoTerminal).filter(
                PuntoTerminal.ruta_id == ruta.id,
                PuntoTerminal.tipo == PuntoTerminalTipo.B,
            ).first()
            
            if punta_b_db:
                punta_b_db.sitio_descripcion = parsed.punta_b.sitio_descripcion
                punta_b_db.identificador_fisico = parsed.punta_b.identificador_fisico
                punta_b_db.pelo_conector = parsed.punta_b.pelo_conector
            else:
                punta_b_db = PuntoTerminal(
                    ruta_id=ruta.id,
                    tipo=PuntoTerminalTipo.B,
                    sitio_descripcion=parsed.punta_b.sitio_descripcion,
                    identificador_fisico=parsed.punta_b.identificador_fisico,
                    pelo_conector=parsed.punta_b.pelo_conector,
                )
                self.session.add(punta_b_db)
        
        self.session.flush()


# =============================================================================
# FUNCIONES HELPER (para uso desde endpoints)
# =============================================================================


def analyze_tracking_file(
    session: Session,
    raw_content: str,
    filename: str,
) -> AnalysisResult:
    """Helper para analizar un archivo de tracking.
    
    Args:
        session: Sesión de SQLAlchemy
        raw_content: Contenido del archivo
        filename: Nombre del archivo
        
    Returns:
        AnalysisResult
    """
    service = InfraService(session)
    return service.analyze_tracking(raw_content, filename)


def resolve_tracking_file(
    session: Session,
    action: ResolveAction,
    raw_content: str,
    filename: str,
    *,
    target_ruta_id: Optional[int] = None,
    new_ruta_name: Optional[str] = None,
    new_ruta_tipo: RutaTipo = RutaTipo.ALTERNATIVA,
    old_service_id: Optional[str] = None,
) -> ResolveResult:
    """Helper para resolver un archivo de tracking.
    
    Args:
        session: Sesión de SQLAlchemy
        action: Acción a ejecutar
        raw_content: Contenido del archivo
        filename: Nombre del archivo
        target_ruta_id: ID de ruta destino (para MERGE_APPEND, REPLACE, ADD_STRAND)
        new_ruta_name: Nombre de nueva ruta (para BRANCH)
        new_ruta_tipo: Tipo de nueva ruta (para BRANCH)
        old_service_id: ID del servicio viejo (para CONFIRM_UPGRADE)
        
    Returns:
        ResolveResult
    """
    service = InfraService(session)
    return service.resolve_tracking(
        action,
        raw_content,
        filename,
        target_ruta_id=target_ruta_id,
        new_ruta_name=new_ruta_name,
        new_ruta_tipo=new_ruta_tipo,
        old_service_id=old_service_id,
    )
