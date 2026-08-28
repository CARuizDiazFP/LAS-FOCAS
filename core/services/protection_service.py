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
    CamaraEstadoAuditoria,
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

        Resuelve por DOS caminos independientes cuando no se pasa `ruta_id` (bloque `else`):
        - Legacy: `Servicio→RutaServicio→Empalme.camara_id→Camara` (trackings cargados a mano).
        - Cromo (Etapa Refactor baneos, 2026-08-23): `Servicio→CromoServicioMatch→CromoPelo→
          CromoCable→CromoBotella.camara_id→Camara`, vía `camara_ids_por_servicio_sync`
          (`core/services/cromo/verificador.py`, mismo estilo `text()` para no acoplar este archivo a
          las tablas `cromo_*` vía ORM) — cierra el gap real de servicios cuya infraestructura sólo se
          conoce por la ingesta de Cromo Red, que antes devolvían `[]` (no baneables) por depender
          únicamente del camino legacy.

        El camino Cromo SÓLO corre en el bloque `else` (sin `ruta_id`). Cuando se pasa `ruta_id`
        explícito (bloque `if ruta_id:`), es un filtro de precisión sobre una `RutaServicio` puntual —
        concepto que Cromo no modela (no tiene noción de "ruta") — así que ese camino se ignora
        completamente ahí.

        Dedup por `Camara.id` (mismo `camaras_set` para ambos caminos): si el mismo `camara_id`
        aparece por legacy Y por Cromo, sólo se consulta/agrega una vez — el objeto ya resuelto por
        legacy gana, no se vuelve a pedir a la DB.

        Args:
            servicio_id: ID del servicio (texto, ej: "52547")
            ruta_id: ID de ruta específica (opcional) — si se pasa, ignora el camino Cromo

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
            # Todas las rutas activas del servicio (camino legacy)
            for ruta in servicio.rutas_activas:
                for empalme in ruta.empalmes:
                    if empalme.camara and empalme.camara.id not in camaras_set:
                        camaras_set[empalme.camara.id] = empalme.camara

            # Camino Cromo: resuelve camara_id que el legacy no vio (servicio sin trackings cargados,
            # o con trackings parciales que no cubren toda su infraestructura real).
            from core.services.cromo.verificador import camara_ids_por_servicio_sync

            camara_ids_cromo = camara_ids_por_servicio_sync(self.session, servicio.id)
            camara_ids_faltantes = camara_ids_cromo - camaras_set.keys()
            if camara_ids_faltantes:
                camaras_cromo = self.session.query(Camara).filter(
                    Camara.id.in_(camara_ids_faltantes)
                ).all()
                for camara in camaras_cromo:
                    camaras_set[camara.id] = camara

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
            
            # Marcar cámaras como BANEADAS — cascada completa (Etapa Cámara/Botella): banear una
            # botella banea también a su cámara padre y a todas sus botellas hermanas, no sólo a la
            # que resolvió el empalme de esta ruta. `aplicar_estado_a_grupo` resuelve el grupo completo
            # de cada `camara` y es EL ÚNICO lugar que escribe `Camara.estado` — evita el hueco de
            # seguridad real donde una botella baneada dejaba a su cámara padre mostrándose libre.
            from core.services.camara_estado_service import aplicar_estado_a_grupo, miembros_del_grupo

            motivo_estado = motivo or f"Baneo por incidente #{incidente.id} (servicio protegido {servicio_protegido_id})"
            camaras_baneadas = 0
            camaras_ya_baneadas = 0
            camaras_afectadas = []
            procesadas: set[int] = set()

            for camara in camaras:
                if camara.id in procesadas:
                    continue
                auditorias = aplicar_estado_a_grupo(
                    self.session,
                    camara,
                    CamaraEstado.BANEADA,
                    usuario=usuario_ejecutor or "sistema",
                    motivo=motivo_estado,
                )
                estados_anteriores = {a.camara_id: a.estado_anterior for a in auditorias}
                for miembro in miembros_del_grupo(camara):
                    if miembro.id in procesadas:
                        continue
                    procesadas.add(miembro.id)
                    if miembro.id in estados_anteriores:
                        camaras_baneadas += 1
                        camaras_afectadas.append({
                            "id": miembro.id,
                            "nombre": miembro.nombre,
                            "estado_anterior": estados_anteriores[miembro.id].value,
                            "estado_nuevo": "BANEADA",
                            "accion": "baneada",
                        })
                    else:
                        camaras_ya_baneadas += 1
                        camaras_afectadas.append({
                            "id": miembro.id,
                            "nombre": miembro.nombre,
                            "estado_anterior": "BANEADA",
                            "estado_nuevo": "BANEADA",
                            "accion": "sin_cambio",
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

            # Cascada Cámara/Botella (Etapa Infra): iterar el grupo completo de cada cámara resuelta
            # (padre + botellas hermanas), no sólo la fila que resolvió el empalme — `create_ban`
            # baneó al grupo entero, así que `lift_ban` tiene que evaluar la restauración de cada
            # miembro por separado (a diferencia del baneo, la restauración NO es uniforme: cada
            # miembro puede tener su propio ingreso activo o su propio otro-baneo, y termina en un
            # estado distinto — LIBRE u OCUPADA — según su situación puntual).
            from core.services.camara_estado_service import miembros_del_grupo

            motivo_estado = motivo_cierre or f"Restauración por cierre de incidente #{incidente_id}"
            camaras_restauradas = 0
            camaras_mantenidas = 0
            camaras_afectadas = []
            procesadas: set[int] = set()

            for camara in camaras:
                for miembro in miembros_del_grupo(camara):
                    if miembro.id in procesadas:
                        continue
                    procesadas.add(miembro.id)

                    if miembro.estado != CamaraEstado.BANEADA:
                        # Ya no está baneada, no hacer nada
                        continue

                    # Verificar si hay otro baneo activo que afecte al GRUPO de esta cámara (no sólo
                    # a `miembro` directamente — ver `_camara_tiene_otro_baneo_activo`)
                    otro_baneo = self._camara_tiene_otro_baneo_activo(
                        miembro.id,
                        incidente_id,
                    )

                    if otro_baneo:
                        # Mantener baneada por otro incidente
                        camaras_mantenidas += 1
                        camaras_afectadas.append({
                            "id": miembro.id,
                            "nombre": miembro.nombre,
                            "estado_anterior": "BANEADA",
                            "estado_nuevo": "BANEADA",
                            "accion": "mantenida_otro_baneo",
                            "otro_incidente_id": otro_baneo.id,
                        })
                        continue

                    # Determinar nuevo estado (por miembro — no uniforme, ver docstring arriba)
                    nuevo_estado = self._determinar_estado_restauracion(miembro, incidente)
                    if nuevo_estado == CamaraEstado.BANEADA:
                        # Baneo independiente anterior a este incidente (sin IncidenteBaneo que lo
                        # respalde) — no se toca, ver docstring de _determinar_estado_restauracion.
                        camaras_mantenidas += 1
                        camaras_afectadas.append({
                            "id": miembro.id,
                            "nombre": miembro.nombre,
                            "estado_anterior": "BANEADA",
                            "estado_nuevo": "BANEADA",
                            "accion": "mantenida_baneo_independiente",
                        })
                        continue

                    self.session.add(
                        CamaraEstadoAuditoria(
                            camara_id=miembro.id,
                            usuario=usuario_ejecutor or "sistema",
                            motivo=motivo_estado,
                            estado_anterior=miembro.estado,
                            estado_nuevo=nuevo_estado,
                        )
                    )
                    miembro.estado = nuevo_estado
                    miembro.last_update = datetime.now(timezone.utc)
                    camaras_restauradas += 1
                    camaras_afectadas.append({
                        "id": miembro.id,
                        "nombre": miembro.nombre,
                        "estado_anterior": "BANEADA",
                        "estado_nuevo": nuevo_estado.value,
                        "accion": "restaurada",
                    })

            # Reconciliación de incidentes hermanos (hallazgo real, 2026-08-28): cámaras que un
            # hermano ya cerrado no pudo liberar porque ESTE incidente todavía estaba activo en ese
            # momento — ver docstring de `_reconciliar_hermanos_cerrados`.
            camaras_afectadas_hermanos = self._reconciliar_hermanos_cerrados(
                incidente.servicio_protegido_id,
                incidente_id,
                usuario_ejecutor=usuario_ejecutor,
            )
            camaras_restauradas += len(camaras_afectadas_hermanos)
            camaras_afectadas.extend(camaras_afectadas_hermanos)

            logger.info(
                "action=lift_ban incidente_id=%d restauradas=%d mantenidas=%d restauradas_hermanos=%d",
                incidente_id,
                camaras_restauradas,
                camaras_mantenidas,
                len(camaras_afectadas_hermanos),
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

    def _reconciliar_hermanos_cerrados(
        self,
        servicio_protegido_id: str,
        incidente_excluido_id: int,
        *,
        usuario_ejecutor: Optional[str] = None,
    ) -> List[dict]:
        """Tras cerrar un incidente, reintenta la restauración de cualquier incidente HERMANO —
        mismo `servicio_protegido_id`, ya cerrado — cuyas cámaras hayan quedado `BANEADA` porque, en
        el momento de SU PROPIO cierre, otro incidente hermano (éste u otro) todavía estaba activo y
        bloqueó `_camara_tiene_otro_baneo_activo`.

        Hallazgo real, 2026-08-28: dos incidentes que protegían el mismo servicio por rutas
        redundantes (Principal/Backup) se cerraron con 4 segundos de diferencia. El que cerró primero
        dejó todas sus cámaras `mantenida_otro_baneo` (correctamente — el hermano todavía estaba
        activo en ese instante). El hermano cerró segundos después, pero `lift_ban` sólo reevalúa las
        cámaras de SU PROPIA ruta — nunca vuelve a mirar las del incidente que ya se dio por cerrado.
        Resultado real: 74 cámaras/botellas quedaron `BANEADA` para siempre, sin ningún incidente
        activo detrás (ver `docs/decisiones.md`, entrada 2026-08-28).

        Corre incondicionalmente al final de `lift_ban` — el costo es acotado (sólo mira incidentes ya
        CERRADOS del mismo servicio, nunca un escaneo global de `Camara`), y así, sea cual sea el
        orden en que cierren dos incidentes hermanos, el último en cerrar termina de liberar también
        lo que el primero no pudo.

        Returns:
            Lista de dicts `camaras_afectadas` (mismo formato que `lift_ban`) de las cámaras que esta
            reconciliación efectivamente restauró — vacía si no había nada pendiente.
        """
        from core.services.camara_estado_service import miembros_del_grupo

        hermanos_cerrados = self.session.query(IncidenteBaneo).filter(
            IncidenteBaneo.servicio_protegido_id == servicio_protegido_id,
            IncidenteBaneo.id != incidente_excluido_id,
            IncidenteBaneo.activo == False,  # noqa: E712
        ).all()

        camaras_afectadas: List[dict] = []
        procesadas: set[int] = set()

        for hermano in hermanos_cerrados:
            camaras = self.get_camaras_for_servicio(hermano.servicio_protegido_id, hermano.ruta_protegida_id)
            for camara in camaras:
                for miembro in miembros_del_grupo(camara):
                    if miembro.id in procesadas or miembro.estado != CamaraEstado.BANEADA:
                        continue
                    procesadas.add(miembro.id)

                    if self._camara_tiene_otro_baneo_activo(miembro.id, hermano.id):
                        continue  # todavía hay OTRO incidente activo protegiéndola

                    nuevo_estado = self._determinar_estado_restauracion(miembro, hermano)
                    if nuevo_estado == CamaraEstado.BANEADA:
                        continue  # baneo independiente real (anterior al hermano) — no tocar

                    self.session.add(
                        CamaraEstadoAuditoria(
                            camara_id=miembro.id,
                            usuario=usuario_ejecutor or "sistema",
                            motivo=(
                                f"Restauración diferida: el incidente hermano #{hermano.id} había "
                                f"quedado pendiente al cerrarse (bloqueado por el incidente activo "
                                f"#{incidente_excluido_id} en ese momento)"
                            ),
                            estado_anterior=miembro.estado,
                            estado_nuevo=nuevo_estado,
                        )
                    )
                    miembro.estado = nuevo_estado
                    miembro.last_update = datetime.now(timezone.utc)
                    camaras_afectadas.append({
                        "id": miembro.id,
                        "nombre": miembro.nombre,
                        "estado_anterior": "BANEADA",
                        "estado_nuevo": nuevo_estado.value,
                        "accion": "restaurada_hermano",
                        "incidente_hermano_id": hermano.id,
                    })

        return camaras_afectadas

    def _camara_tiene_otro_baneo_activo(
        self,
        camara_id: int,
        excluir_incidente_id: int,
    ) -> Optional[IncidenteBaneo]:
        """Verifica si el GRUPO de una cámara (ella + su cámara padre + botellas hermanas) está
        afectado por otro baneo activo.

        Etapa Cámara/Botella: mira los empalmes de TODO el grupo, no sólo los de `camara_id`
        directamente — si los empalmes reales viven en una botella hermana (o en la cámara padre) y
        sólo se mirara `camara_id`, este chequeo no vería el otro incidente y `lift_ban` podría
        restaurar de más una cámara que en realidad sigue protegida por otro baneo vía su hermana.

        Etapa Refactor baneos (2026-08-23): el cálculo de `servicios_ids` también une el camino Cromo
        (`servicio_ids_por_camaras_sync`) — mismo gap que `get_camaras_for_servicio`: si el otro
        incidente activo protege un servicio cuya infraestructura sólo se conoce por Cromo Red (sin
        empalme/ruta legacy que lo conecte a este grupo), el camino legacy en solitario no lo detecta.

        Args:
            camara_id: ID de la cámara/botella a verificar
            excluir_incidente_id: ID del incidente a excluir de la búsqueda

        Returns:
            El primer incidente activo que afecta al grupo, o None
        """
        from core.services.camara_estado_service import miembros_del_grupo
        from core.services.cromo.verificador import servicio_ids_por_camaras_sync

        camara = self.session.query(Camara).filter(Camara.id == camara_id).first()
        if not camara:
            return None

        miembros = miembros_del_grupo(camara)

        # Servicios que pasan por CUALQUIER empalme del grupo (cámara padre + todas las botellas) —
        # camino legacy
        servicios_ids: set[str] = set()
        for miembro in miembros:
            for empalme in miembro.empalmes:
                for ruta in empalme.rutas:
                    if ruta.servicio and ruta.servicio.servicio_id:
                        servicios_ids.add(ruta.servicio.servicio_id)

        # Camino Cromo: une servicios que tocan el grupo sólo vía infraestructura Cromo (sin empalme
        # legacy) — cierra el mismo hueco que `get_camaras_for_servicio`.
        servicios_ids |= servicio_ids_por_camaras_sync(self.session, [m.id for m in miembros])

        if not servicios_ids:
            return None
        
        # Buscar otros incidentes activos que afecten estos servicios
        otro_incidente = self.session.query(IncidenteBaneo).filter(
            IncidenteBaneo.id != excluir_incidente_id,
            IncidenteBaneo.activo == True,
            IncidenteBaneo.servicio_protegido_id.in_(servicios_ids),
        ).first()
        
        return otro_incidente

    def _determinar_estado_restauracion(self, camara: Camara, incidente: IncidenteBaneo) -> CamaraEstado:
        """Determina el estado al que debe volver una cámara al desbanear.

        Antes de aplicar la lógica LIBRE/OCUPADA por defecto, consulta la auditoría para dos casos que
        esa lógica no puede ver (hallazgo real de QA, 2026-08-10 — ver
        `camara_estado_service.obtener_ultima_transicion_a_baneada`):

        - Si la última transición a BANEADA de esta cámara es ANTERIOR al inicio de este incidente,
          significa que quedó baneada por otro motivo independiente de este incidente (override manual,
          herencia del backfill de jerarquía Cámara/Botella, etc. — sin `IncidenteBaneo` que lo
          respalde, por lo que `_camara_tiene_otro_baneo_activo` no lo detecta) → se mantiene BANEADA,
          no se toca.
        - Si el estado previo a esa transición era DETECTADA, se preserva DETECTADA en vez de
          colapsarla a LIBRE — DETECTADA es un estado administrativo/de triage, no de ocupación, y
          perderlo haría ver "libre" una cámara que en realidad no fue verificada.

        Lógica por defecto (sin historial aplicable):
        - Si tiene ingreso activo (sin fecha_fin) → OCUPADA
        - En otro caso → LIBRE

        Args:
            camara: Cámara a evaluar
            incidente: Incidente que se está levantando (para comparar contra su fecha_inicio)

        Returns:
            Estado de restauración (BANEADA si se mantiene por un motivo independiente, DETECTADA,
            LIBRE u OCUPADA)
        """
        from core.services.camara_estado_service import obtener_ultima_transicion_a_baneada

        ultima_transicion = obtener_ultima_transicion_a_baneada(self.session, camara.id)
        if ultima_transicion is not None:
            if (
                ultima_transicion.created_at is not None
                and incidente.fecha_inicio is not None
                and ultima_transicion.created_at < incidente.fecha_inicio
            ):
                return CamaraEstado.BANEADA
            if ultima_transicion.estado_anterior == CamaraEstado.DETECTADA:
                return CamaraEstado.DETECTADA

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
