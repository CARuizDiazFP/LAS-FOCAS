# Nombre de archivo: camara_hierarchy_service.py
# Ubicación de archivo: core/services/camara_hierarchy_service.py
# Descripción: Jerarquía Cámara/Botella — detecta el sufijo "Bot N" y resuelve/crea la cámara padre

"""Resuelve la jerarquía Cámara/Botella (`Camara.camara_padre_id`, self-FK) sobre nombres de cámara ya
existentes o recién dados de alta. "Botella" acá es un concepto de este módulo de Infraestructura,
homónimo de `CromoBotella` (`app.cromo_botellas`, módulo de ingesta Cromo Red, esquema separado).

No reinventa la detección de "Bot N": reusa `RE_BOT_SUFIJO`
(`modules/slack_baneo_notifier/camara_search.py`), la misma regex de negocio ya probada contra datos
reales del listener de ingresos Slack — clase de un solo dígito a propósito, evita el falso positivo
real "Bot 30 de Septiembre y J.M.Estrada" (no es la botella 30, es una calle que empieza con "30").

`resolver_o_crear_padre_desde_base()` es el núcleo reutilizable (parametrizado en
estado/origen_datos) del que también depende `core/services/cromo/camara_padre_service.py` para
vincular Botellas Cromo a una Cámara padre — mismo mecanismo de resolución, sin duplicar código,
para dos backfills con políticas de estado por defecto distintas (ver ese módulo).
"""

from __future__ import annotations

import logging
import re
import zlib
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos
from modules.slack_baneo_notifier.camara_search import RE_BOT_SUFIJO, _limpiar_puntuacion, _normalizar

logger = logging.getLogger(__name__)

# Orden de severidad para computar el estado más restrictivo de un grupo Cámara+Botellas — mismo
# criterio que usa `aplicar_estado_a_grupo` (core/services/camara_estado_service.py) al propagar.
#
# `PENDIENTE_REVISION` NO participa a propósito (bug real encontrado corriendo el backfill contra
# datos reales, no en tests unitarios): no es un nivel de severidad de seguridad física — es un estado
# administrativo temporal ("esta fila la auto-registró el listener de Slack, un admin todavía no la
# revisó"). Incluirlo en esta escala hacía que una botella LIBRE con una hermana PENDIENTE_REVISION
# "escalara" a PENDIENTE_REVISION — corrompiendo silenciosamente cámaras que nunca deberían pasar por
# el flujo de triage admin. `estado_mas_restrictivo()` filtra estos casos antes de calcular.
#
# `NO_OPERATIVA` (2026-08-11, backfill de Botellas Cromo) sí participa, con peso intermedio entre
# LIBRE y OCUPADA: es más conservador que LIBRE (no hay ninguna señal real detrás) pero no debe
# ocultar un uso/baneo confirmado del resto del grupo.
#
# `DETECTADA` fue retirado del sistema (2026-08-11, mismo pase) — el estado operable de
# Cámara/Botella se redujo a LIBRE/OCUPADA/BANEADA/NO_OPERATIVA (ver
# `scripts/retirar_estado_detectada.py`). Ya no tiene entrada propia acá; si alguna fila legado
# quedara sin backfillear, cae al fallback `.get(e, 0)` — mismo peso que LIBRE, nunca bloquea el
# cálculo.
_ORDEN_SEVERIDAD_ESTADO: dict[CamaraEstado, int] = {
    CamaraEstado.LIBRE: 0,
    CamaraEstado.NO_OPERATIVA: 1,
    CamaraEstado.OCUPADA: 2,
    CamaraEstado.BANEADA: 3,
}


def extraer_base(nombre: Optional[str]) -> Optional[str]:
    """Si `nombre` matchea el sufijo "Bot N", devuelve el nombre sin ESE token (preservando todo lo
    que viene antes y después) — no `None` si no matchea.

    Importante: remueve sólo el token "Bot N", no todo lo que sigue. Un `regexp_replace` con `.*$`
    (probado y descartado durante la investigación) se comía sufijos reales como "CF"/"C.F." al final
    del nombre, rompiendo el join con la forma pelada ("Cra 14 de Julio 240 Bot 2 CF" tendría que dar
    "Cra 14 de Julio 240 CF", no "Cra 14 de Julio 240").
    """
    if not nombre:
        return None
    match = RE_BOT_SUFIJO.search(nombre)
    if not match:
        return None
    base = f"{nombre[: match.start()]} {nombre[match.end() :]}"
    base = re.sub(r"\s+", " ", base).strip()
    return base or None


def normalizar_para_agrupar(nombre: Optional[str]) -> str:
    """Normaliza un nombre de cámara para comparar/agrupar — reusa la misma limpieza de puntuación +
    normalización (unaccent + lowercase + colapso de espacios) que ya usa `camara_search.buscar_camara`,
    sin la expansión de abreviaturas ni los sinónimos (esos son específicos de la búsqueda difusa de
    texto libre de técnicos, no aplican a comparar dos nombres ya estructurados de la DB)."""
    return _normalizar(_limpiar_puntuacion(nombre or ""))


def estado_mas_restrictivo(estados: Iterable[CamaraEstado]) -> CamaraEstado:
    """Devuelve el estado más restrictivo de un grupo: BANEADA > OCUPADA/DETECTADA > LIBRE.

    Ignora deliberadamente cualquier `PENDIENTE_REVISION` en la lista — no es un nivel de severidad
    física, es un estado administrativo temporal que nunca debe "ganarle" a, ni ser sobreescrito por,
    el resto del grupo (ver comentario en `_ORDEN_SEVERIDAD_ESTADO`). Si TODOS los estados son
    `PENDIENTE_REVISION` (o la lista está vacía), devuelve `LIBRE` — quien llama debe evitar aplicar
    ese resultado si en realidad quería decir "no toco nada", no asumirlo como respuesta válida."""
    candidatos = [e for e in estados if e != CamaraEstado.PENDIENTE_REVISION]
    if not candidatos:
        return CamaraEstado.LIBRE
    return max(candidatos, key=lambda e: _ORDEN_SEVERIDAD_ESTADO.get(e, 0))


def ids_camaras_con_cromo_hijos(session: Session) -> set[int]:
    """IDs de `Camara` raíz que ya tienen al menos una `CromoBotella` propia (`camara_id`).

    Bug real encontrado corriendo `scripts/cromo_backfill_camara_padre.py` una segunda vez
    (2026-08-12, detectado en `--dry-run` antes de aplicar — nunca llegó a tocar datos reales): una
    Cámara padre creada por el backfill de Cromo tiene CERO Botellas legado (`.botellas`, el self-FK
    que sí chequean el paso 1 y la absorción de "peladas" de `resolver_o_crear_padre_desde_base`),
    así que cualquier caller de esa función — este mismo backfill en una corrida posterior, el
    listener de Slack, `camara_backfill_padre_botella.py` — la veía como una fila "pelada" sin
    hijos y la absorbía como Botella de una Cámara padre nueva, duplicando el padre y dejando su
    `camara_id` de Cromo apuntando a una fila que dejó de ser raíz (invariante roto, ver
    `_detectar_camara_id_invalido` en el backfill). Este set protege esas filas en ambos chequeos."""
    return {
        camara_id
        for (camara_id,) in session.query(CromoBotella.camara_id).filter(CromoBotella.camara_id.isnot(None)).all()
    }


def _advisory_lock_para(session: Session, clave: str) -> None:
    """Toma un advisory lock de Postgres (`pg_advisory_xact_lock`) para la duración de la transacción
    actual, keyed por un hash estable de `clave`. No requiere ningún constraint de unicidad en la
    tabla (que hoy chocaría con los duplicados de nombre preexistentes, fuera de alcance de esta
    migración) — serializa únicamente el check-then-create de `resolver_o_crear_padre` entre sesiones
    concurrentes que resuelven la MISMA base de nombre, sin bloquear nada más."""
    clave_hash = zlib.crc32(clave.encode("utf-8"))
    session.execute(text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": clave_hash})


def resolver_o_crear_padre_desde_base(
    session: Session,
    base: str,
    *,
    usuario: str = "sistema",
    estado_si_nuevo: CamaraEstado = CamaraEstado.LIBRE,
    origen_si_nuevo: CamaraOrigenDatos = CamaraOrigenDatos.INFERIDO,
) -> Camara:
    """Resuelve (o crea) la cámara padre para una `base` ya extraída (sin el token "Bot N"/prefijo).

    Núcleo reutilizable de `resolver_o_crear_padre` — parametrizado en `estado_si_nuevo`/
    `origen_si_nuevo` para que otros backfills (ej. `core/services/cromo/camara_padre_service.py`,
    Botellas Cromo) puedan reusar exactamente esta lógica (advisory lock, no-promoción de filas
    existentes, absorción de "peladas") sin duplicarla, sólo cambiando con qué estado/origen nace
    la fila si hay que crearla.

    Nunca promueve una fila existente a "padre": si ya existe una fila raíz (`camara_padre_id IS
    NULL`) cuyo nombre normalizado coincide con la base extraída, esa fila se re-vincula como botella
    del padre (mismo criterio que aplica `scripts/camara_backfill_padre_botella.py`) en vez de
    convertirse ella misma en el padre — mantiene consistencia con cómo el backfill trató el caso real
    "Cra 14 de Julio 240 CF" / "Cra 14 de Julio 240 Bot 2 CF" (ninguna de las dos filas existentes se
    promueve; se crea una tercera fila como padre y ambas quedan como sus botellas).
    """
    base_norm = normalizar_para_agrupar(base)
    _advisory_lock_para(session, base_norm)

    # O(n) sobre las filas raíz — mismo orden de magnitud que ya usa `_get_or_create_camara`
    # (`core/services/infra_service.py`) para su propio dedup; el dataset es chico (~1800 filas).
    raices = session.query(Camara).filter(Camara.camara_padre_id.is_(None)).all()
    ids_con_cromo_hijos = ids_camaras_con_cromo_hijos(session)

    def _tiene_hijos(candidata: Camara) -> bool:
        # Botella legado (self-FK) O Botella Cromo propia — ver `ids_camaras_con_cromo_hijos`.
        return bool(candidata.botellas) or candidata.id in ids_con_cromo_hijos

    # 1. ¿Ya existe un padre para esta base? Sólo cuentan como "padre" las filas que YA tienen al
    #    menos una botella — una fila raíz sin botellas es una cámara normal, no un padre, aunque su
    #    nombre coincida (evita promover una fila ajena por casualidad de nombre).
    for candidata in raices:
        if _tiene_hijos(candidata) and normalizar_para_agrupar(candidata.nombre) == base_norm:
            return candidata

    # 2. No existe ningún padre todavía — crear uno nuevo. Antes de devolverlo, absorber como
    #    botella cualquier fila raíz "pelada" preexistente cuyo nombre normalizado coincida
    #    exactamente con la base (ej. "Cra 14 de Julio 240 CF" ya existía como fila independiente) —
    #    nunca se promueve esa fila a padre, siempre queda como botella más del padre nuevo.
    nuevo_padre = Camara(
        nombre=base,
        estado=estado_si_nuevo,
        origen_datos=origen_si_nuevo,
    )
    session.add(nuevo_padre)
    session.flush()

    hermanas_absorbidas = []
    for candidata in raices:
        if normalizar_para_agrupar(candidata.nombre) != base_norm:
            continue
        if _tiene_hijos(candidata):
            # No debería llegar acá (el paso 1 ya habría devuelto esta fila) — defensivo: nunca
            # absorber una raíz con Botellas propias, rompería el invariante "camara_id siempre
            # apunta a una raíz" (ver `ids_camaras_con_cromo_hijos`).
            continue
        candidata.camara_padre_id = nuevo_padre.id
        hermanas_absorbidas.append(candidata.id)

    logger.info(
        "action=camara_hierarchy evento=padre_creado padre_id=%s nombre='%s' estado=%s "
        "origen_datos=%s hermanas_absorbidas=%s usuario=%s",
        nuevo_padre.id,
        base,
        estado_si_nuevo.value,
        origen_si_nuevo.value,
        hermanas_absorbidas,
        usuario,
    )
    return nuevo_padre


def resolver_o_crear_padre(session: Session, nombre_hijo: str, *, usuario: str = "sistema") -> Optional[Camara]:
    """Resuelve (o crea) la cámara padre para `nombre_hijo`, si el nombre matchea el sufijo "Bot N".

    Devuelve `None` si `nombre_hijo` no matchea el patrón — el llamador no debe tocar
    `camara_padre_id` en ese caso (la fila sigue siendo una cámara raíz normal).
    """
    base = extraer_base(nombre_hijo)
    if base is None:
        return None
    return resolver_o_crear_padre_desde_base(session, base, usuario=usuario)


__all__ = [
    "ids_camaras_con_cromo_hijos",
    "extraer_base",
    "normalizar_para_agrupar",
    "estado_mas_restrictivo",
    "resolver_o_crear_padre_desde_base",
    "resolver_o_crear_padre",
]
