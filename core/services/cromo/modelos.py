# Nombre de archivo: modelos.py
# Ubicación de archivo: core/services/cromo/modelos.py
# Descripción: Dataclasses del dominio de inventario de fibra óptica de Cromo Red (botella,
# cable, tubo, pelo, fusión, splitter y puerto de splitter)

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
class ConectorOdf:
    """Conector/posición de patchera de una ODF (class 136, "Posición Patchera"). Viaja embebido
    en `inner[]` del propio objeto ODF (class 69, requiere `show=ALL`), nunca en un barrido propio.

    `pelo_n_id` es el mismo `n_id` de `app.cromo_pelos` (confirmado real: acá `tp[].id_to` SÍ es
    directamente el n_id estable, a diferencia del "ID dual" de extremos de cable).
    `servicio_numero_atributo` es el atributo id=62 de Cromo (crudo, sólo si el conector está en
    uso); `servicio_resuelto`/`servicio_id_historico` los completa `ingesta.py` después de
    parsear (necesitan consultar `cromo_pelos.servicio_numero`, esto es un parser puro sin I/O)."""

    n_id: int
    odf_n_id: Optional[int]
    bandeja_n_id: Optional[int]
    bandeja_nombre: Optional[str]
    bandeja_modelo: Optional[str]
    numero_conector: Optional[str]
    pelo_n_id: Optional[int]
    servicio_numero_atributo: Optional[str]
    servicio_resuelto: Optional[str] = None
    servicio_id_historico: Optional[str] = None
    payload_raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(slots=True)
class Splitter:
    """Splitter óptico (class 133). Cuelga de `botella.inner[]`, igual que las fusiones.

    **Cromo publica el ratio** en `at.83` ("1x8", "1x4", "1x2"): es dato, no una inferencia. Hasta
    2026-09-17 el sistema lo deducía por fan-out de fusiones en `empalmes.py`, y medido contra 30
    botellas reales esa heurística acertaba en 18 y fallaba en 12 — incluyendo inventar splitters
    donde no hay ninguno y no devolver NUNCA un ratio cuando el splitter existía de verdad.

    `salidas` es el `N` de "1xN" ya parseado, para poder comparar y ordenar sin volver a romper el
    string; `ratio` conserva el texto crudo porque es lo que el operador reconoce.
    """

    n_id: int
    botella_n_id: Optional[int]
    nombre: Optional[str]
    ratio: Optional[str]
    salidas: Optional[int]
    # De qué objeto cuelga realmente. Medido sobre 800 splitters reales (2026-09-19): sólo el 12%
    # cuelga de una Botella; el resto cuelga de una caja PON (137, 139, 138, 84, 140, 126, 127).
    # `botella_n_id` se conserva porque `empalmes.py` consulta por esa columna, pero queda en None
    # cuando el contenedor no es una Botella — antes se le metía el dict crudo de `parent`.
    contenedor_n_id: Optional[int] = None
    contenedor_clase: Optional[int] = None


@dataclass(slots=True)
class PuertoSplitter:
    """Puerto de un splitter (class 134). `parent` apunta al `n_id` del splitter.

    `sentido` es `at.82` ("ENTRADA"/"SALIDA") y `nombre` es `at.80` ("E1", "S1"…). El atributo de
    servicio (`at.62`) **no viaja en el barrido de colección**, sólo en la respuesta de
    `/db/objects/{id}/inner` — misma asimetría ya documentada para los conectores de ODF. Por eso
    `servicios_atributo` queda en `None` cuando el objeto vino del barrido: `None` significa "no se
    preguntó", y `[]` significa "se preguntó y el puerto está libre".
    """

    n_id: int
    splitter_n_id: Optional[int]
    botella_n_id: Optional[int]
    nombre: Optional[str]
    sentido: Optional[str]
    servicios_atributo: Optional[list[str]] = None


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


__all__ = [
    "Botella",
    "Cable",
    "Odf",
    "ConectorOdf",
    "Tubo",
    "Pelo",
    "Fusion",
    "Splitter",
    "PuertoSplitter",
]
