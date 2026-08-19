# Nombre de archivo: orfanas_service.py
# Ubicación de archivo: core/services/cromo/orfanas_service.py
# Descripción: Listado y resolución manual de Botellas Cromo huérfanas (camara_id IS NULL) — asociación a Cámara existente o alta de una nueva

"""Botellas Cromo "huérfanas" son filas de `app.cromo_botellas` vigentes cuyo nombre no matcheó
ningún patrón del backfill automático (`scripts/cromo_backfill_camara_padre.py`) — no porque el
nombre carezca de información (verificado contra datos reales: son direcciones válidas, sólo con
ruido de formato — paréntesis, sufijo de localidad, abreviaturas no cubiertas por el regex), sino
porque el matcher automático tiene gaps reales. Este módulo resuelve el caso "sin match automático,
pero un humano SÍ reconoce la dirección" — vía asociación manual a una Cámara existente o alta de
una nueva, individual o en lote.

Lectura (`buscar_huerfanas`) es async, igual que el resto de las consultas de sólo lectura sobre
`cromo_botellas` en este módulo. Escritura (`asociar_huerfanas`) es síncrona — toca `CromoBotella`
Y `Camara` en la misma sesión, mismo patrón que ya usa `scripts/cromo_backfill_camara_padre.py`
(ambos modelos son ORM normales, no hace falta mezclar engines async+sync)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from core.services.camara_estado_service import aplicar_estado_a_grupo, miembros_del_grupo
from core.services.camara_hierarchy_service import estado_mas_restrictivo
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos


@dataclass(slots=True)
class BotellaHuerfana:
    n_id: int
    nombre: Optional[str]
    calle: Optional[str]
    localidad: Optional[str]


@dataclass(slots=True)
class ResultadoHuerfanas:
    total: int
    limit: int
    offset: int
    botellas: list[BotellaHuerfana]


async def buscar_huerfanas(
    sesion: AsyncSession,
    *,
    q: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
) -> ResultadoHuerfanas:
    """Búsqueda paginada de Botellas Cromo vigentes sin `camara_id` — `q` es `ILIKE` parcial contra
    nombre/calle/localidad, igual criterio que `buscar_botellas_unificadas`."""
    filtros = [CromoBotella.vigente.is_(True), CromoBotella.camara_id.is_(None)]
    if q and q.strip():
        termino = f"%{q.strip()}%"
        filtros.append(
            (CromoBotella.nombre.ilike(termino))
            | (CromoBotella.calle.ilike(termino))
            | (CromoBotella.localidad.ilike(termino))
        )

    total = (await sesion.execute(select(func.count()).select_from(CromoBotella).where(*filtros))).scalar_one()
    filas = (
        await sesion.execute(
            select(CromoBotella.n_id, CromoBotella.nombre, CromoBotella.calle, CromoBotella.localidad)
            .where(*filtros)
            .order_by(CromoBotella.nombre)
            .limit(limit)
            .offset(offset)
        )
    ).all()

    botellas = [BotellaHuerfana(n_id=f[0], nombre=f[1], calle=f[2], localidad=f[3]) for f in filas]
    return ResultadoHuerfanas(total=total, limit=limit, offset=offset, botellas=botellas)


class AsociarHuerfanasError(Exception):
    """Error de validación al asociar Botellas huérfanas — el llamador debe traducirlo a un 400."""


@dataclass(slots=True)
class ResultadoAsociacion:
    camara_id: int
    camara_creada: bool
    botellas_vinculadas: int
    estado_asignado: str


def asociar_huerfanas(
    session: Session,
    *,
    n_ids: list[int],
    camara_id: Optional[int],
    nombre_nueva_camara: Optional[str],
    usuario: str,
) -> ResultadoAsociacion:
    """Asocia una o más Botellas Cromo huérfanas a una Cámara — existente (`camara_id`) o nueva
    (`nombre_nueva_camara`). Exactamente uno de los dos debe venir seteado.

    A diferencia del backfill automático (que sólo actúa cuando el regex matchea), esta asociación
    es una decisión humana explícita — no hace falta volver a correr ningún patrón de nombre acá.
    """
    if not n_ids:
        raise AsociarHuerfanasError("No se especificaron Botellas para asociar")
    if bool(camara_id) == bool(nombre_nueva_camara):
        raise AsociarHuerfanasError("Especificá exactamente uno: camara_id (existente) o nombre_nueva_camara (nueva)")

    if camara_id is not None:
        camara = session.query(Camara).filter(Camara.id == camara_id).first()
        if camara is None:
            raise AsociarHuerfanasError("La Cámara indicada no existe")
        if camara.camara_padre_id is not None:
            raise AsociarHuerfanasError("No se puede asociar a una Botella — elegí su Cámara padre")
        camara_creada = False
    else:
        nombre = (nombre_nueva_camara or "").strip()
        if not nombre:
            raise AsociarHuerfanasError("El nombre de la nueva Cámara no puede estar vacío")
        camara = Camara(
            nombre=nombre,
            estado=CamaraEstado.LIBRE,
            origen_datos=CamaraOrigenDatos.INFERIDO_CROMO,
            last_update=datetime.now(timezone.utc),
        )
        session.add(camara)
        session.flush()
        camara_creada = True

    botellas = session.query(CromoBotella).filter(CromoBotella.n_id.in_(n_ids)).all()
    if len(botellas) != len(set(n_ids)):
        raise AsociarHuerfanasError("Alguna de las Botellas indicadas no existe")

    for botella in botellas:
        botella.camara_id = camara.id

    # Estado final del grupo (la Cámara + sus Botellas legado, si tenía) — el más restrictivo gana,
    # mismo criterio que el backfill automático y la unificación de Cámaras.
    grupo = miembros_del_grupo(camara)
    estado_final = estado_mas_restrictivo(m.estado for m in grupo)
    if any(m.estado != estado_final for m in grupo):
        aplicar_estado_a_grupo(
            session,
            camara,
            estado_final,
            usuario=usuario,
            motivo="Asociación manual de Botellas Cromo huérfanas — estado heredado del grupo",
        )

    estado_botellas = estado_final if estado_final.value in {"LIBRE", "OCUPADA", "BANEADA", "NO_OPERATIVA"} else CamaraEstado.NO_OPERATIVA
    for botella in botellas:
        botella.estado = estado_botellas

    return ResultadoAsociacion(
        camara_id=camara.id,
        camara_creada=camara_creada,
        botellas_vinculadas=len(botellas),
        estado_asignado=estado_botellas.value,
    )


__all__ = [
    "AsociarHuerfanasError",
    "BotellaHuerfana",
    "ResultadoAsociacion",
    "ResultadoHuerfanas",
    "asociar_huerfanas",
    "buscar_huerfanas",
]
