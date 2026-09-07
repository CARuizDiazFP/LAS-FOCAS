# Nombre de archivo: servicios_categoria_service.py
# Ubicación de archivo: core/services/servicios_categoria_service.py
# Descripción: Cambio de categoría (individual y masivo) sobre Servicio — validación de rango 0-6 y reporte de ids inexistentes

"""Cambia la `categoria` (0-6) de uno o varios `Servicio`. Más simple que
`core/services/botellas_estado_masivo_service.py` (patrón de referencia): `Servicio.id` es un único
espacio de ID (sin distinción de origen legado/Cromo como Botellas), así que no hace falta clave
compuesta ni cascada de grupo — es un `UPDATE` directo por `id`.

Sin tabla de auditoría dedicada (a diferencia de `Camara.estado`/`camaras_estado_auditoria`):
`categoria` es una clasificación de prioridad de reporting, no un estado operativo de seguridad de
campo — no se justifica la misma infraestructura de auditoría en este pase (fuera del alcance
pedido, ver docs/decisiones.md 2026-08-14)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from db.models.infra import Servicio

CATEGORIA_MINIMA = 0
CATEGORIA_MAXIMA = 6


class CategoriaInvalidaError(Exception):
    """Error de validación al cambiar la categoría — el llamador (endpoint) lo traduce a un 400,
    no a un 500."""


def validar_categoria(categoria: int) -> None:
    if not (CATEGORIA_MINIMA <= categoria <= CATEGORIA_MAXIMA):
        raise CategoriaInvalidaError(f"categoria debe estar entre {CATEGORIA_MINIMA} y {CATEGORIA_MAXIMA}")


@dataclass(slots=True)
class ResultadoCategoriaMasiva:
    categoria_nueva: int
    actualizados: int
    no_encontrados: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "categoria_nueva": self.categoria_nueva,
            "actualizados": self.actualizados,
            "no_encontrados": list(self.no_encontrados),
        }


def actualizar_categoria_masiva(
    session: Session,
    servicio_ids: list[int],
    categoria: int,
) -> ResultadoCategoriaMasiva:
    if not servicio_ids:
        raise CategoriaInvalidaError("No se especificaron servicios a actualizar")
    validar_categoria(categoria)

    ids_solicitados = set(servicio_ids)
    encontrados = {
        id_ for (id_,) in session.query(Servicio.id).filter(Servicio.id.in_(ids_solicitados)).all()
    }
    no_encontrados = sorted(ids_solicitados - encontrados)

    actualizados = 0
    if encontrados:
        actualizados = (
            session.query(Servicio)
            .filter(Servicio.id.in_(encontrados))
            .update({Servicio.categoria: categoria}, synchronize_session=False)
        )

    session.flush()

    return ResultadoCategoriaMasiva(
        categoria_nueva=categoria,
        actualizados=actualizados,
        no_encontrados=no_encontrados,
    )


__all__ = [
    "CATEGORIA_MAXIMA",
    "CATEGORIA_MINIMA",
    "CategoriaInvalidaError",
    "ResultadoCategoriaMasiva",
    "actualizar_categoria_masiva",
    "validar_categoria",
]
