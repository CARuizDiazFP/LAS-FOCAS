# Nombre de archivo: cromo_backfill_camara_padre.py
# Ubicación de archivo: scripts/cromo_backfill_camara_padre.py
# Descripción: Backfill idempotente que vincula Botellas Cromo (app.cromo_botellas) a una Cámara padre propia y les asigna estado

"""Vincula retroactivamente cada `CromoBotella` vigente a una `Camara` padre (`app.camaras`) y le
asigna un `estado` operativo — mismo criterio de resolución que ya usa la jerarquía Bot-N legado
(`core/services/camara_hierarchy_service.py::resolver_o_crear_padre_desde_base`: nunca promover una
fila "pelada" existente a padre, sino absorberla; reusar un padre ya establecido por nombre
normalizado), pero con resolución en memoria en vez de reusar esa función por-fila — ver nota de
performance más abajo. Cromo como fuente de verdad: para cada nombre de Botella no vacío, resuelve
(o crea) su Cámara padre vía `core/services/cromo/camara_padre_service.py::extraer_base_cromo` —
sufijo real "Bot N", prefijo "Botella N <nombre>", o (2026-08-12) el nombre exacto de la Botella
como último recurso si ninguno de los dos patrones matchea (ej. "Av Rivadavia 6041"). Con el
fallback de nombre exacto, prácticamente ninguna Botella con `nombre` no vacío queda sin Cámara
padre — sólo las de `nombre` vacío/`NULL` siguen sin resolución automática (quedan para
`core/services/cromo/orfanas_service.py`, resolución manual).

**Nota de performance (hallazgo real, no teórico)**: la primera versión de este script reusaba
`core/services/cromo/camara_padre_service.py::resolver_o_crear_padre_cromo()` (que delega en
`resolver_o_crear_padre_desde_base`) llamándola una vez por cada Botella candidata. Esa función está
diseñada para UNA llamada aislada por evento en vivo (6 caminos de alta ya la usan así) — cada
llamada re-consulta TODAS las Cámaras raíz (`camara_padre_id IS NULL`) desde cero. A la escala del
dataset legado (~1800 filas) eso es aceptable; a la escala de Botellas Cromo con patrón (1588 filas
reales contra hasta ~2900 raíces creciendo) resultó en más de 25 minutos sin terminar y 78% de CPU
sostenido corriendo dentro de `lasfocasdev-api` (contenedor compartido con la API real) antes de ser
abortado manualmente durante la verificación de esta tarea. La función compartida NO se modificó
(sigue siendo correcta y necesaria para sus llamadores en vivo, donde O(n) por llamada aislada es
intrascendente) — este script implementa su propia resolución equivalente pero O(1) amortizado: una
única carga de raíces con `botellas` precargada (`selectinload`) + diccionarios en memoria, en vez
de una consulta completa por cada una de las 1588 filas.

**Normalización extendida (2026-08-14)**: la resolución en memoria de este script usa
`normalizar_para_agrupar_extendido` (abreviaturas + sinónimos, no sólo unaccent/lowercase/
puntuación) — mismo cambio aplicado a `resolver_o_crear_padre_desde_base` el mismo día para cerrar
el gap que permitía crear Cámaras padre duplicadas para el mismo sitio físico (ej. real "Bot Tza San
Antonio 640" vs "Bot. Tza.San Antonio 640 CF"). Sin este cambio, correr este script periódicamente
seguiría generando duplicados nuevos por este camino de código aunque el gap ya estuviera cerrado en
la función compartida.

Tres fases:
1. Vincular `CromoBotella.camara_id` resolviendo/creando la Cámara padre por nombre (resolución en
   memoria, ver nota de performance).
2. Escalar el estado del grupo completo (padre + todas sus botellas, `Camara` y `CromoBotella`
   mezcladas) al más restrictivo — mismo criterio que `camara_backfill_padre_botella.py`, saltando
   grupos con algún miembro `PENDIENTE_REVISION` (estado administrativo, no de severidad física).
3. Fijar `CromoBotella.estado` a partir del estado ya escalado del padre, pasado por
   `_MAPEO_ESTADO_CROMO` — el `CHECK` de `cromo_botellas` sólo admite LIBRE/OCUPADA/BANEADA/
   NO_OPERATIVA (Cromo no tiene equivalente de DETECTADA/PENDIENTE_REVISION, workflows exclusivos
   del dominio legado).

**Actualización 2026-08-13 (decisión explícita del usuario, revierte la política fail-closed del
2026-08-11)**: toda Cámara padre NUEVA nace en `LIBRE` — una Cámara recién creada no tiene todavía
ningún empalme/ruta propio, así que no puede existir un `IncidenteBaneo` activo real que la afecte,
no hay nada que "chequear" en el momento del alta. Si en cambio el backfill reutiliza una `Camara`
legado ya existente (nombre coincidente), hereda su estado real — no es inferencia, es un dato que
ya existe y tiene auditoría propia (`CamaraEstadoAuditoria`), y puede legítimamente estar `BANEADA`.
Ver `docs/decisiones.md`.

Idempotente vía `WHERE vigente=true AND camara_id IS NULL AND NOT separada_manualmente` — sin
columna de progreso extra. El tercer término es redundante hoy (`separada_manualmente=true`
implica `camara_id` ya seteado, ver `core/services/cromo/separacion_service.py`), pero es el
blindaje explícito pedido para que un futuro `--force` que resetee `camara_id` a NULL no vuelva a
agrupar una fila que un admin separó a mano a propósito. Re-escanear en memoria es barato a ~11k
filas. La reingesta periódica de Cromo (`ingesta.py`) nunca pisa `camara_id`/`estado`: no están en
`_BOTELLA_CAMPOS` ni en el dataclass `Botella`.

Sesión síncrona (`SessionLocal`, no `AsyncSessionLocal`): toda la lógica reutilizada
(`aplicar_estado_a_grupo`, `miembros_del_grupo`) es síncrona; mezclar dos engines en un script batch
de esta escala no aporta nada.

**Concurrencia**: a diferencia de `resolver_o_crear_padre_desde_base` (que toma un advisory lock por
nombre para altas concurrentes en vivo), la resolución en memoria de este script NO toma lock — es
correcta para una corrida de este script a la vez (uso previsto: manual/periódico, igual que
`cromo_backfill_geo.py`/`cromo_backfill_servicio_prefijos.py`), pero dos corridas simultáneas de este
mismo script SÍ podrían crear Cámaras padre duplicadas. No correr dos instancias en paralelo.

**Bug real de idempotencia corregido (2026-08-12, detectado en `--dry-run` de esta misma sesión antes
de aplicar — nunca llegó a tocar datos reales)**: la clasificación "pelada" (ver arriba) originalmente
sólo miraba `raiz.botellas` (self-FK legado) para decidir si una Cámara raíz ya era un padre
establecido. Una Cámara padre creada por una corrida ANTERIOR de este script tiene CERO Botellas
legado (sus hijas son `CromoBotella`, tabla distinta) — en una segunda corrida se la clasificaba
como "pelada" y se la absorbía como Botella de un padre nuevo duplicado, dejando su `camara_id` de
Cromo apuntando a una fila que dejó de ser raíz (invariante roto, ver `_detectar_camara_id_invalido`
más abajo, que fue justo lo que lo detectó: ~400 vinculaciones habrían quedado inválidas). Corregido
reusando `core/services/camara_hierarchy_service.py::ids_camaras_con_cromo_hijos` (mismo fix aplicado
también en `resolver_o_crear_padre_desde_base`, compartido con el listener de Slack y el backfill
legado — ver ese módulo).

No pega contra la API de Cromo — sólo lee/escribe tablas ya pobladas por la ingesta.

Uso:
    source .venv/bin/activate
    python scripts/cromo_backfill_camara_padre.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.orm import selectinload

from core.logging import setup_logging
from core.services.camara_estado_service import MAPEO_ESTADO_CROMO, aplicar_estado_a_grupo, miembros_del_grupo
from core.services.camara_hierarchy_service import (
    estado_mas_restrictivo,
    ids_camaras_con_cromo_hijos,
    normalizar_para_agrupar_extendido,
)
from core.services.cromo.camara_padre_service import extraer_base_cromo
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos
from db.session import SessionLocal

logger = setup_logging("cromo_backfill_camara_padre")

# El CHECK ck_cromo_botellas_estado_valido sólo admite estos 4 valores — un padre reutilizado
# (Camara legado real) puede estar en DETECTADA/PENDIENTE_REVISION, que no tienen equivalente en
# el vocabulario Cromo. Mapeo compartido con `aplicar_estado_a_grupo` (2026-08-12) — antes era una
# copia local acá, movida a `camara_estado_service.py` para que el mismo mapeo sirva tanto a la
# carga inicial (este script) como a la propagación en vivo (cualquier cambio de estado real
# posterior sobre la Cámara padre).
_MAPEO_ESTADO_CROMO = MAPEO_ESTADO_CROMO


def _detectar_camara_id_invalido(session) -> list[int]:
    """Auditoría de sólo lectura: `camara_id` debería apuntar siempre a una fila raíz de `camaras`
    (`camara_padre_id IS NULL`), nunca a una botella legado — invariante que no se puede expresar
    en un CHECK cross-tabla de Postgres, se garantiza por construcción (la Fase 1 sólo resuelve
    contra `raices`, filtradas por `camara_padre_id IS NULL`) y se audita acá igual. No debería
    devolver nada nunca."""
    filas = (
        session.query(CromoBotella.n_id)
        .join(Camara, CromoBotella.camara_id == Camara.id)
        .filter(Camara.camara_padre_id.isnot(None))
        .all()
    )
    return [n_id for (n_id,) in filas]


def main(dry_run: bool) -> None:
    session = SessionLocal()
    try:
        candidatas = (
            session.query(CromoBotella)
            .filter(
                CromoBotella.vigente.is_(True),
                CromoBotella.camara_id.is_(None),
                CromoBotella.separada_manualmente.is_(False),
            )
            .order_by(CromoBotella.n_id)
            .all()
        )
        logger.info("action=cromo_backfill_camara_padre candidatas=%d", len(candidatas))

        con_patron = [(cb, extraer_base_cromo(cb.nombre)) for cb in candidatas]
        con_patron = [(cb, base) for cb, base in con_patron if base is not None]
        logger.info("action=cromo_backfill_camara_padre con_patron=%d", len(con_patron))

        # Fase 1: resolver/crear padre y vincular camara_id — resolución en memoria (ver nota de
        # performance en el docstring del módulo). Una única carga de raíces con `botellas`
        # precargada, en vez de una consulta completa por cada una de las filas con patrón.
        raices = (
            session.query(Camara)
            .filter(Camara.camara_padre_id.is_(None))
            .options(selectinload(Camara.botellas))
            .all()
        )
        # Hallazgo real (2026-08-12, detectado en --dry-run antes de aplicar — nunca tocó datos
        # reales): una Cámara padre creada por una corrida ANTERIOR de este mismo script tiene CERO
        # Botellas legado (`.botellas`, self-FK) — sin este chequeo se la clasifica como "pelada" y
        # se la absorbe como Botella de un padre NUEVO duplicado en cualquier corrida posterior,
        # dejando su `camara_id` de Cromo apuntando a una fila que dejó de ser raíz (mismo invariante
        # que audita `_detectar_camara_id_invalido`, ver `ids_camaras_con_cromo_hijos`).
        ids_con_cromo_hijos = ids_camaras_con_cromo_hijos(session)
        padres_por_nombre: dict[str, Camara] = {}
        peladas_por_nombre: dict[str, list[Camara]] = {}
        for raiz in raices:
            clave = normalizar_para_agrupar_extendido(raiz.nombre)
            if raiz.botellas or raiz.id in ids_con_cromo_hijos:
                padres_por_nombre.setdefault(clave, raiz)
            else:
                peladas_por_nombre.setdefault(clave, []).append(raiz)

        vinculos: list[tuple[CromoBotella, int]] = []
        padres_tocados: set[int] = set()
        padres_por_id: dict[int, Camara] = {}
        padres_creados = 0
        padres_reusados = 0
        for botella, base in con_patron:
            clave = normalizar_para_agrupar_extendido(base)
            padre = padres_por_nombre.get(clave)
            if padre is None:
                padre = Camara(nombre=base, estado=CamaraEstado.LIBRE, origen_datos=CamaraOrigenDatos.INFERIDO_CROMO)
                session.add(padre)
                session.flush()
                padres_por_nombre[clave] = padre
                padres_creados += 1
                for pelada in peladas_por_nombre.pop(clave, []):
                    pelada.camara_padre_id = padre.id
            else:
                padres_reusados += 1
            padres_por_id[padre.id] = padre
            botella.camara_id = padre.id
            vinculos.append((botella, padre.id))
            padres_tocados.add(padre.id)

        logger.info(
            "action=cromo_backfill_camara_padre padres_resueltos=%d padres_creados=%d "
            "padres_reusados=%d filas_vinculadas=%d",
            len(padres_tocados),
            padres_creados,
            padres_reusados,
            len(vinculos),
        )

        # Fase 2: escalar estado del grupo completo (mismo criterio que camara_backfill_padre_botella.py).
        grupos_escalados = 0
        grupos_con_pendiente_revision = 0
        for padre_id in padres_tocados:
            padre = padres_por_id[padre_id]
            grupo = miembros_del_grupo(padre)
            if any(m.estado == CamaraEstado.PENDIENTE_REVISION for m in grupo):
                grupos_con_pendiente_revision += 1
                logger.warning(
                    "action=cromo_backfill_camara_padre hallazgo=grupo_con_pendiente_revision "
                    "padre_id=%s miembros=%s — no se toca el estado, requiere triage admin normal",
                    padre_id,
                    [m.id for m in grupo],
                )
                continue
            estado_grupo = estado_mas_restrictivo(m.estado for m in grupo)
            if any(m.estado != estado_grupo for m in grupo):
                aplicar_estado_a_grupo(
                    session,
                    padre,
                    estado_grupo,
                    usuario="cromo_backfill",
                    motivo="Backfill Botellas Cromo — Cámara padre/estado heredado del grupo",
                )
                grupos_escalados += 1
        logger.info(
            "action=cromo_backfill_camara_padre grupos_con_estado_escalado=%d grupos_con_pendiente_revision=%d",
            grupos_escalados,
            grupos_con_pendiente_revision,
        )

        # Fase 3: fijar CromoBotella.estado a partir del estado ya escalado del padre, mapeado al
        # vocabulario válido de Cromo.
        herencias_no_operativa = 0
        for botella, padre_id in vinculos:
            padre = padres_por_id[padre_id]
            estado_mapeado = _MAPEO_ESTADO_CROMO[padre.estado]
            if estado_mapeado != padre.estado:
                logger.info(
                    "action=cromo_backfill_camara_padre mapeo_estado n_id=%s padre_estado=%s estado_mapeado=%s",
                    botella.n_id,
                    padre.estado.value,
                    estado_mapeado.value,
                )
            if estado_mapeado == CamaraEstado.NO_OPERATIVA:
                herencias_no_operativa += 1
            else:
                # Etiqueta corregida (2026-08-12): la condición original decía "hereda_estado_no_operativa"
                # pero disparaba justo en el caso contrario (estado_mapeado != NO_OPERATIVA) — sin impacto en
                # el estado escrito (siempre fue `botella.estado = estado_mapeado`), sólo en el texto del log.
                logger.warning(
                    "action=cromo_backfill_camara_padre hallazgo=hereda_estado_restrictivo_real n_id=%s "
                    "camara_id=%s estado=%s",
                    botella.n_id,
                    padre_id,
                    estado_mapeado.value,
                )
            botella.estado = estado_mapeado

        logger.info(
            "action=cromo_backfill_camara_padre estado_no_operativa=%d estado_heredado_real=%d",
            herencias_no_operativa,
            len(vinculos) - herencias_no_operativa,
        )

        invalidas = _detectar_camara_id_invalido(session)
        if invalidas:
            logger.warning(
                "action=cromo_backfill_camara_padre hallazgo=camara_id_apunta_a_botella_legado n_ids=%s "
                "— no debería pasar nunca, revisar manualmente",
                invalidas,
            )

        if dry_run:
            logger.info("action=cromo_backfill_camara_padre modo=dry_run — no se aplican cambios, rollback")
            session.rollback()
        else:
            session.commit()
            logger.info("action=cromo_backfill_camara_padre modo=aplicado — cambios commiteados")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Sólo reporta qué se crearía/vincularía, sin aplicar cambios")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
