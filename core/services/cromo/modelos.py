# Nombre de archivo: modelos.py
# Ubicación de archivo: core/services/cromo/modelos.py
# Descripción: Dataclasses del dominio de inventario de fibra óptica de Cromo Red (botella, cable, tubo, pelo, fusión)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class Botella:
    """Botella/empalme (class 68 · 121 · 122 · 123 · 124 · 125). `n_id` es la PK de linaje."""

    n_id: int
    version_id: Optional[int]
    vmax: Optional[int]
    clase: Optional[int]
    nombre: Optional[str]
    codigo_modelo: Optional[str]
    id_legacy: Optional[str]
    notas: Optional[str]
    calle: Optional[str]
    altura: Optional[str]
    localidad: Optional[str]
    provincia: Optional[str]
    ubicacion_fisica: Optional[str]
    tendido: Optional[str]
    latitud: Optional[float]
    longitud: Optional[float]
    pts_raw: Optional[list[Any]]
    clase_no_homologada: bool
    payload_raw: dict[str, Any] = field(repr=False)


@dataclass(slots=True)
class Cable:
    """Cable de FO (class 51). Los campos de extremos vienen de `tp[]`, sin FK dura."""

    n_id: int
    version_id: Optional[int]
    vmax: Optional[int]
    nombre: Optional[str]
    capacidad: Optional[str]
    capacidad_pelos: Optional[int]
    propietario: Optional[str]
    jerarquia: Optional[str]
    tendido: Optional[str]
    distancia_geo: Optional[float]
    distancia_real: Optional[float]
    id_legacy: Optional[str]
    notas: Optional[str]
    extremo_a_n_id: Optional[int]
    extremo_a_clase: Optional[int]
    extremo_a_legacy: Optional[str]
    extremo_a_nombre: Optional[str]
    extremo_b_n_id: Optional[int]
    extremo_b_clase: Optional[int]
    extremo_b_legacy: Optional[str]
    extremo_b_nombre: Optional[str]
    pts_raw: Optional[list[Any]]
    payload_raw: dict[str, Any] = field(repr=False)


@dataclass(slots=True)
class Odf:
    """ODF / distribuidor de fibra óptica (class 69). No cuelga del árbol de Botella — tiene su
    propia fase de ingesta directa. `cables_asociados` son los `n_id` (nunca `id_to`) de los
    cables referenciados en `tp[]`; `None` si el objeto no trajo `tp[]` en absoluto, `[]` si lo
    trajo pero ninguno de sus items era un cable."""

    n_id: int
    version_id: Optional[int]
    vmax: Optional[int]
    clase: Optional[int]
    nombre: Optional[str]
    codigo_modelo: Optional[str]
    id_legacy: Optional[str]
    notas: Optional[str]
    calle: Optional[str]
    altura: Optional[str]
    localidad: Optional[str]
    provincia: Optional[str]
    ubicacion_fisica: Optional[str]
    tendido: Optional[str]
    latitud: Optional[float]
    longitud: Optional[float]
    pts_raw: Optional[list[Any]]
    propietario: Optional[str]
    tipo_elemento: str
    cables_asociados: Optional[list[int]]
    payload_raw: dict[str, Any] = field(repr=False)


@dataclass(slots=True)
class Tubo:
    """Tubo/buffer (class 129). `cable_n_id` es el `parent`, resuelto contra `n_id`, sin FK dura."""

    n_id: int
    cable_n_id: Optional[int]
    orden: Optional[int]
    nombre_color: Optional[str]


@dataclass(slots=True)
class Pelo:
    """Pelo/hilo (class 130). Pertenece al tubo, nunca directamente a la botella."""

    n_id: int
    tubo_n_id: Optional[int]
    cable_n_id: Optional[int]
    numero_pelo: Optional[str]
    orden: Optional[int]
    color: Optional[str]
    servicio_raw: Optional[str]
    servicio_numero: Optional[str]
    tipo_asociacion: str


@dataclass(slots=True)
class Fusion:
    """Fusión (class 132). Cuelga de `botella.inner[]`; `parent` apunta al `n_id` de la botella."""

    n_id: int
    botella_n_id: Optional[int]
    nombre_par: Optional[str]
    tipo: Optional[str]
    pelo_a_n_id: Optional[int]
    pelo_b_n_id: Optional[int]
    latitud: Optional[float]
    longitud: Optional[float]


__all__ = ["Botella", "Cable", "Odf", "Tubo", "Pelo", "Fusion"]
