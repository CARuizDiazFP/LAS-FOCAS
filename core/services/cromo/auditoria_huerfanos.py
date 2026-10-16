# Nombre de archivo: auditoria_huerfanos.py
# Ubicación de archivo: core/services/cromo/auditoria_huerfanos.py
# Descripción: Auditoría de huérfanos de un Servicio — pelos de sus caminos RESIDUALES con causa
# sugerida — y normalización asistida (exclusión del pelo) desde el Viewer admin

"""Huérfanos: pelos que Cromo etiqueta con el Servicio pero que están en caminos que no son tramos.

`tracking_service.trackings_del_servicio` separa los caminos en TRAMO y RESIDUAL. Cada vez que lo
hace (Slack `@bot track`, el portal o la corrida global) llama a `auditar_servicio` con ese mismo
resultado, sin volver a Cromo, y acá se registra cada pelo residual en
`app.cromo_auditoria_huerfanos` con una causa sugerida.

**Clasificación de causa** (`clasificar_residual`, pura). Medido real el 2026-10-16 sobre 102452,
42351 y 93154 (65 residuales; ver `tests/fixtures/cromo_huerfanos_medido_2026_10_16.json`):

- `CABLE_DESUSO`: todos los cables del residual tienen tendido "Sin Uso" en Cromo
  (`cromo_cables.tendido`, at.20) y ninguno lo recorre un tramo. Es el único campo real que lo
  indica: los residuales no tienen pelos "Cortado"/"Dañado" en `cromo_pelos.estado_cromo` (0 de
  248), `cromo_pelos.status` está vacío en toda la tabla, todos sus cables están `vigente`, el
  `stp` del payload aparece igual en cables de tramos, y "el cable no lleva pelos de ningún
  servicio activo" no se cumple en ningún residual no protegido (los cables "Sin Uso" siguen con
  etiquetas de 5-6 servicios Activos). Da 9 residuales, todos en 42351.
- `PELO_DANADO`: el residual comparte cable con un tramo del mismo Servicio (en otro pelo).
- `CAMBIO_CABLE_DANO`: sus botellas extremas son botellas de un mismo tramo y no comparte ningún
  cable con él (va en paralelo por otro cable).
- `MIGRACION_SITIO`: termina en una botella que no recorre ningún tramo, o en una ODF que no es de
  los tramos ni confirmada.
- `SIN_CLASIFICAR`: el resto.

**Seguridad**: un residual con extremo en una ODF (69) u ODF Nodo (86) —o en un conector con ODF de
clase desconocida— o que toca una ODF confirmada queda `protegido` en la evidencia y nunca se
puede normalizar, tenga la causa que tenga.

**Normalizar** nunca es automático: un admin elige filas en el Viewer y se excluyen con
`pelos_excluidos.excluir_pelos(origen=AUDITORIA)`. Por ahora sólo `CABLE_DESUSO` (el resto se
revisa hasta validarlo), y eso se controla acá, no sólo en la UI.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.tracking_service import (
    CLASES_ODF_EXTREMO,
    ResumenCamino,
    TrackingGenerado,
)

logger = logging.getLogger(__name__)

CAUSA_PELO_DANADO = "PELO_DANADO"
CAUSA_CAMBIO_CABLE_DANO = "CAMBIO_CABLE_DANO"
CAUSA_CABLE_DESUSO = "CABLE_DESUSO"
CAUSA_MIGRACION_SITIO = "MIGRACION_SITIO"
CAUSA_SIN_CLASIFICAR = "SIN_CLASIFICAR"
CAUSAS = (
    CAUSA_CABLE_DESUSO,
    CAUSA_PELO_DANADO,
    CAUSA_CAMBIO_CABLE_DANO,
    CAUSA_MIGRACION_SITIO,
    CAUSA_SIN_CLASIFICAR,
)

ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_NORMALIZADO = "NORMALIZADO"
ESTADO_DESCARTADO = "DESCARTADO"
ESTADOS = (ESTADO_PENDIENTE, ESTADO_NORMALIZADO, ESTADO_DESCARTADO)

ORIGEN_AUDITORIA = "AUDITORIA"

# Primer lote habilitado (pedido del usuario). Las demás causas quedan para revisar.
CAUSAS_NORMALIZABLES = frozenset({CAUSA_CABLE_DESUSO})

# Valor de `cromo_cables.tendido` (at.20 de Cromo) que marca un cable fuera de uso.
TENDIDO_SIN_USO = "sin uso"


def es_normalizable(causa: Optional[str], protegido: bool) -> bool:
    """Si una fila con esta causa puede pasar a NORMALIZADO. Un protegido nunca."""
    return not protegido and causa in CAUSAS_NORMALIZABLES


# ── Clasificación (pura) ──────────────────────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class ClasificacionHuerfano:
    causa: str
    protegido: bool
    motivo_proteccion: Optional[str]
    senales: dict[str, Any] = field(default_factory=dict)

    def evidencia(self) -> dict[str, Any]:
        return {
            "protegido": self.protegido,
            "motivo_proteccion": self.motivo_proteccion,
            "senales": dict(self.senales),
        }


def _extremo_en_odf(resumen: ResumenCamino) -> bool:
    # Mismo criterio que `tracking_service._termina_en_odf`: clase desconocida cuenta como ODF.
    return any(
        e.es_conector_odf and (e.odf_clase is None or e.odf_clase in CLASES_ODF_EXTREMO)
        for e in resumen.extremos
    )


def clasificar_residual(
    residual: ResumenCamino,
    tramos: Sequence[ResumenCamino],
    *,
    odfs_confirmadas: frozenset[int] = frozenset(),
    cables_sin_uso: frozenset[int] = frozenset(),
    cables_protegidos: frozenset[int] = frozenset(),
) -> ClasificacionHuerfano:
    """Causa sugerida de un camino RESIDUAL a partir de los tramos del mismo Servicio. Pura.

    Precedencia: `CABLE_DESUSO` > `PELO_DANADO` > `CAMBIO_CABLE_DANO` > `MIGRACION_SITIO` >
    `SIN_CLASIFICAR`. La protección es independiente de la causa (ver docstring del módulo).

    `cables_protegidos` son los cables de los residuales protegidos del mismo Servicio: un cable
    que recorre un camino que termina en ODF no se da por "en desuso", así que un residual que lo
    comparte nunca sale `CABLE_DESUSO`.
    """
    cables = set(residual.cables)
    cables_tramos = {c for t in tramos for c in t.cables}
    botellas_tramos = {b for t in tramos for b in t.botellas}
    odfs_tramos = {o for t in tramos for o in t.odfs}

    compartidos = cables & cables_tramos
    sin_uso = cables & cables_sin_uso
    en_protegidos = cables & cables_protegidos
    desuso = bool(cables) and sin_uso == cables and not compartidos and not en_protegidos

    extremas = [b for b in (residual.botella_inicio, residual.botella_fin) if b is not None]
    paralelo = (
        len(extremas) == 2
        and not compartidos
        and any(
            residual.botella_inicio in t.botellas
            and residual.botella_fin in t.botellas
            and not (cables & set(t.cables))
            for t in tramos
        )
    )
    odfs_extremas = [e.odf_id for e in residual.extremos if e.es_conector_odf]
    migracion = bool(tramos) and (
        any(b not in botellas_tramos for b in extremas)
        or any(o not in odfs_tramos and o not in odfs_confirmadas for o in odfs_extremas)
    )

    if desuso:
        causa = CAUSA_CABLE_DESUSO
    elif compartidos:
        causa = CAUSA_PELO_DANADO
    elif paralelo:
        causa = CAUSA_CAMBIO_CABLE_DANO
    elif migracion:
        causa = CAUSA_MIGRACION_SITIO
    else:
        causa = CAUSA_SIN_CLASIFICAR

    motivo: Optional[str] = None
    if _extremo_en_odf(residual):
        motivo = "extremo en ODF u ODF Nodo"
    elif odfs_confirmadas and set(residual.odfs) & odfs_confirmadas:
        motivo = "toca una ODF confirmada"

    senales = {
        "cables": len(cables),
        "cables_sin_uso": len(sin_uso),
        "cables_compartidos_con_tramos": len(compartidos),
        "cables_en_residual_protegido": len(en_protegidos),
        "paralelo_a_tramo": paralelo,
        "botellas_extremas": extremas,
        "botellas_fuera_de_tramos": [b for b in extremas if b not in botellas_tramos],
        "odfs_extremas": odfs_extremas,
        "tramos": len(tramos),
    }
    return ClasificacionHuerfano(
        causa=causa, protegido=motivo is not None, motivo_proteccion=motivo, senales=senales
    )


# ── Auditoría por servicio (persistencia) ─────────────────────────────────────────────────────


@dataclass(slots=True)
class ResumenAuditoria:
    """`nuevos`/`actualizados` son filas PENDIENTE escritas; `retirados`, PENDIENTE borradas
    porque su pelo hoy está en un tramo."""

    nuevos: int = 0
    actualizados: int = 0
    retirados: int = 0
    por_causa: dict[str, int] = field(default_factory=dict)


_SQL_CABLES_SIN_USO = text(
    """
    SELECT n_id, version_id FROM app.cromo_cables
    WHERE (n_id = ANY(:ids) OR version_id = ANY(:ids))
      AND lower(btrim(tendido)) = :sin_uso
    """
)

# Una sola ida a la base para todos los pelos residuales. Re-auditar es idempotente y sólo pisa
# filas PENDIENTE: una NORMALIZADO o DESCARTADO ya la decidió un admin.
_SQL_UPSERT = text(
    """
    INSERT INTO app.cromo_auditoria_huerfanos
        (corrida_id, servicio_id, pelo_n_id, camino_semilla, causa, evidencia, estado)
    SELECT :corrida_id, :servicio_id, x.pelo, x.semilla, x.causa, x.evidencia::jsonb, 'PENDIENTE'
    FROM unnest(
        CAST(:pelos AS bigint[]), CAST(:semillas AS bigint[]),
        CAST(:causas AS text[]), CAST(:evidencias AS text[])
    ) AS x(pelo, semilla, causa, evidencia)
    ON CONFLICT (servicio_id, pelo_n_id) DO UPDATE
       SET corrida_id = COALESCE(EXCLUDED.corrida_id, app.cromo_auditoria_huerfanos.corrida_id),
           camino_semilla = EXCLUDED.camino_semilla,
           causa = EXCLUDED.causa,
           evidencia = EXCLUDED.evidencia,
           actualizado_at = CURRENT_TIMESTAMP
     WHERE app.cromo_auditoria_huerfanos.estado = 'PENDIENTE'
    RETURNING (xmax = 0) AS nuevo
    """
)

_SQL_RETIRAR_EN_TRAMOS = text(
    """
    DELETE FROM app.cromo_auditoria_huerfanos
    WHERE servicio_id = :servicio_id AND estado = 'PENDIENTE' AND pelo_n_id = ANY(:pelos)
    """
)


def _causa_consolidada(causas: set[str]) -> str:
    """Una causa por pelo cuando sus caminos residuales difieren: la menos normalizable."""
    if len(causas) == 1:
        return next(iter(causas))
    no_normalizables = causas - CAUSAS_NORMALIZABLES
    if len(no_normalizables) == 1:
        return next(iter(no_normalizables))
    return CAUSA_SIN_CLASIFICAR


def consolidar_por_pelo(
    residuales: Sequence[TrackingGenerado],
    tramos: Sequence[ResumenCamino],
    *,
    semillas: frozenset[int],
    pelos_en_tramos: frozenset[int] = frozenset(),
    odfs_confirmadas: frozenset[int] = frozenset(),
    cables_sin_uso: frozenset[int] = frozenset(),
) -> dict[int, tuple[int, str, dict[str, Any]]]:
    """`{pelo: (camino semilla, causa, evidencia)}` de los pelos del Servicio en residuales. Pura.

    Un mismo pelo puede estar en varios caminos residuales. Se consolida sin depender del orden:
    - `protegido` es el OR de todos sus caminos (basta uno que termine en ODF);
    - si las causas difieren, gana la menos normalizable (o `SIN_CLASIFICAR`);
    - `odfs` es la unión de las ODFs de todos sus caminos, para que `normalizar` pueda volver a
      chequear contra las ODF confirmadas vigentes al momento de normalizar.
    Además, un cable de un residual protegido nunca habilita `CABLE_DESUSO` en otro residual.
    """
    resumenes = [r.extremos or ResumenCamino() for r in residuales]
    previas = [
        clasificar_residual(
            res, tramos, odfs_confirmadas=odfs_confirmadas, cables_sin_uso=cables_sin_uso
        )
        for res in resumenes
    ]
    cables_protegidos = frozenset(
        c for res, cl in zip(resumenes, previas) if cl.protegido for c in res.cables
    )
    # Un residual protegido ya no es normalizable: su causa se calcula sin el veto (si no, sus
    # propios cables lo sacarían de CABLE_DESUSO y la evidencia perdería información).
    clasificaciones = [
        previa
        if previa.protegido
        else clasificar_residual(
            res,
            tramos,
            odfs_confirmadas=odfs_confirmadas,
            cables_sin_uso=cables_sin_uso,
            cables_protegidos=cables_protegidos,
        )
        for res, previa in zip(resumenes, previas)
    ]

    por_pelo: dict[int, list[int]] = {}
    for i, residual in enumerate(residuales):
        for pelo in sorted((residual.pelos_camino | {residual.pelo_n_id}) & semillas):
            if pelo not in pelos_en_tramos:
                por_pelo.setdefault(pelo, []).append(i)

    filas: dict[int, tuple[int, str, dict[str, Any]]] = {}
    for pelo, indices in por_pelo.items():
        causa = _causa_consolidada({clasificaciones[i].causa for i in indices})
        protegidos = [i for i in indices if clasificaciones[i].protegido]
        base = next((i for i in indices if clasificaciones[i].causa == causa), indices[0])
        evidencia = clasificaciones[base].evidencia()
        evidencia["protegido"] = bool(protegidos)
        evidencia["motivo_proteccion"] = (
            clasificaciones[protegidos[0]].motivo_proteccion if protegidos else None
        )
        evidencia["camino"] = {
            "semilla": residuales[base].pelo_n_id,
            "pelos": len(residuales[base].pelos_camino),
            "cables": list(resumenes[base].cables)[:20],
        }
        evidencia["odfs"] = sorted({o for i in indices for o in resumenes[i].odfs})
        if len(indices) > 1:
            evidencia["caminos"] = [
                {
                    "semilla": residuales[i].pelo_n_id,
                    "causa": clasificaciones[i].causa,
                    "protegido": clasificaciones[i].protegido,
                }
                for i in indices
            ]
        filas[pelo] = (residuales[base].pelo_n_id, causa, evidencia)
    return filas


async def cables_sin_uso(sesion: AsyncSession, cable_ids: Iterable[int]) -> frozenset[int]:
    """Ids (n_id o version_id, los dos) de los cables con tendido "Sin Uso". Los caminos de Cromo
    pueden traer el id de versión del cable, así que se devuelven ambos."""
    ids = sorted(set(cable_ids))
    if not ids:
        return frozenset()
    filas = (
        await sesion.execute(_SQL_CABLES_SIN_USO, {"ids": ids, "sin_uso": TENDIDO_SIN_USO})
    ).all()
    return frozenset(i for fila in filas for i in fila if i is not None)


async def auditar_servicio(
    sesion: AsyncSession,
    servicio_id: int,
    *,
    tramos: Sequence[TrackingGenerado],
    residuales: Sequence[TrackingGenerado],
    semillas: frozenset[int],
    odfs_confirmadas: frozenset[int] = frozenset(),
    corrida_id: Optional[int] = None,
) -> ResumenAuditoria:
    """Registra como PENDIENTE cada pelo del Servicio que está en un camino residual. No commitea.

    Sólo cuentan los pelos que hoy son del Servicio (`semillas`): un camino residual también
    recorre pelos de otros servicios, y excluirlos no significaría nada. Un pelo que aparece en un
    tramo nunca es huérfano, aunque otro camino residual lo recorra; y si tenía una fila PENDIENTE
    de una auditoría anterior, se borra.
    """
    resumen = ResumenAuditoria()
    resumenes_tramos = [t.extremos or ResumenCamino() for t in tramos]
    pelos_en_tramos = {p for t in tramos for p in t.pelos_camino}

    todos_los_cables = {c for t in residuales for c in (t.extremos or ResumenCamino()).cables}
    sin_uso = await cables_sin_uso(sesion, todos_los_cables)

    filas = consolidar_por_pelo(
        residuales,
        resumenes_tramos,
        semillas=semillas,
        pelos_en_tramos=frozenset(pelos_en_tramos),
        odfs_confirmadas=odfs_confirmadas,
        cables_sin_uso=sin_uso,
    )

    if pelos_en_tramos:
        borrado = await sesion.execute(
            _SQL_RETIRAR_EN_TRAMOS,
            {"servicio_id": servicio_id, "pelos": sorted(pelos_en_tramos)},
        )
        resumen.retirados = borrado.rowcount or 0

    if filas:
        pelos = sorted(filas)
        resultado = await sesion.execute(
            _SQL_UPSERT,
            {
                "corrida_id": corrida_id,
                "servicio_id": servicio_id,
                "pelos": pelos,
                "semillas": [filas[p][0] for p in pelos],
                "causas": [filas[p][1] for p in pelos],
                "evidencias": [json.dumps(filas[p][2]) for p in pelos],
            },
        )
        for (nuevo,) in resultado.all():
            if nuevo:
                resumen.nuevos += 1
            else:
                resumen.actualizados += 1
        for _semilla, causa, _evidencia in filas.values():
            resumen.por_causa[causa] = resumen.por_causa.get(causa, 0) + 1

    logger.info(
        "action=cromo_auditoria_huerfanos servicio_id=%s corrida_id=%s nuevos=%s actualizados=%s "
        "retirados=%s por_causa=%s",
        servicio_id,
        corrida_id,
        resumen.nuevos,
        resumen.actualizados,
        resumen.retirados,
        resumen.por_causa,
    )
    return resumen


async def auditar_sin_romper(
    sesion: AsyncSession,
    servicio_id: int,
    *,
    tramos: Sequence[TrackingGenerado],
    residuales: Sequence[TrackingGenerado],
    semillas: frozenset[int],
    odfs_confirmadas: frozenset[int] = frozenset(),
    corrida_id: Optional[int] = None,
) -> Optional[ResumenAuditoria]:
    """`auditar_servicio` en su propio savepoint + commit. Nunca levanta: una falla de la auditoría
    no puede tumbar la descarga de trackings (Slack o portal). Devuelve `None` si falló."""
    try:
        async with sesion.begin_nested():
            resumen = await auditar_servicio(
                sesion,
                servicio_id,
                tramos=tramos,
                residuales=residuales,
                semillas=semillas,
                odfs_confirmadas=odfs_confirmadas,
                corrida_id=corrida_id,
            )
        await sesion.commit()
        return resumen
    except Exception:  # noqa: BLE001 - la auditoría es accesoria a la descarga
        logger.exception(
            "action=cromo_auditoria_huerfanos evento=error servicio_id=%s corrida_id=%s",
            servicio_id,
            corrida_id,
        )
        try:
            await sesion.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("action=cromo_auditoria_huerfanos evento=rollback_fallido")
        return None


# ── Revisión: normalizar / descartar ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class ResultadoRevision:
    aplicados: list[int] = field(default_factory=list)
    rechazados: list[dict[str, Any]] = field(default_factory=list)

    def rechazar(self, auditoria_id: int, motivo: str) -> None:
        self.rechazados.append({"id": auditoria_id, "motivo": motivo})


_SQL_FILAS_POR_ID = text(
    """
    SELECT id, servicio_id, pelo_n_id, causa, estado,
           COALESCE((evidencia ->> 'protegido')::boolean, true) AS protegido,
           evidencia -> 'odfs' AS odfs
    FROM app.cromo_auditoria_huerfanos
    WHERE id = ANY(:ids)
    ORDER BY id
    FOR UPDATE
    """
)

_SQL_MARCAR = text(
    """
    UPDATE app.cromo_auditoria_huerfanos
       SET estado = :estado, revisado_por = :usuario, actualizado_at = CURRENT_TIMESTAMP
     WHERE id = ANY(:ids) AND estado = 'PENDIENTE'
    RETURNING id
    """
)


async def normalizar(
    sesion: AsyncSession, ids: Iterable[int], *, usuario: Optional[str]
) -> ResultadoRevision:
    """Excluye del Servicio los pelos de las filas elegidas y las deja NORMALIZADO. Commitea.

    Lo que se puede normalizar lo decide el servidor con la fila guardada, no el navegador: sólo
    filas PENDIENTE, no protegidas y con causa en `CAUSAS_NORMALIZABLES`. La exclusión queda con
    `origen=AUDITORIA`, `auditoria_id` y la causa como motivo. Un pelo que ya no es del Servicio
    (o que ya estaba excluido a mano) se rechaza y su fila queda PENDIENTE.

    Falla cerrado: sin evidencia, sin `protegido` o sin la lista `odfs` la fila no se normaliza. Y
    la protección por ODF confirmada se vuelve a chequear acá, en la misma transacción, contra las
    confirmadas vigentes hoy (n_id y version_id): una ODF confirmada después de la auditoría
    también bloquea.
    """
    from core.services.cromo.pelos_excluidos import PeloNoPerteneceAlServicio, excluir_pelos
    from core.services.cromo.servicio_odf_confirmacion import declaraciones_del_servicio

    resultado = ResultadoRevision()
    pedidos = sorted(set(int(i) for i in ids))
    filas = (await sesion.execute(_SQL_FILAS_POR_ID, {"ids": pedidos})).mappings().all()
    encontrados = {f["id"] for f in filas}
    for faltante in (i for i in pedidos if i not in encontrados):
        resultado.rechazar(faltante, "No existe.")

    grupos: dict[tuple[int, str], dict[int, int]] = {}
    confirmadas_por_servicio: dict[int, frozenset[int]] = {}
    for fila in filas:
        odfs = fila["odfs"]
        if fila["estado"] != ESTADO_PENDIENTE:
            resultado.rechazar(fila["id"], f"Ya está {fila['estado']}.")
        elif fila["protegido"]:
            resultado.rechazar(fila["id"], "Protegido: el camino termina en una ODF o toca una ODF confirmada.")
        elif not es_normalizable(fila["causa"], False):
            resultado.rechazar(fila["id"], f"La causa {fila['causa']} todavía es sólo para revisar.")
        elif not isinstance(odfs, list):
            resultado.rechazar(fila["id"], "Sin evidencia de ODFs del camino: hay que re-auditar el Servicio.")
        else:
            servicio_id = fila["servicio_id"]
            if servicio_id not in confirmadas_por_servicio:
                declaradas = await declaraciones_del_servicio(sesion, servicio_id)
                confirmadas_por_servicio[servicio_id] = declaradas.odf_ids
            if {int(o) for o in odfs} & confirmadas_por_servicio[servicio_id]:
                resultado.rechazar(fila["id"], "Protegido: el camino toca una ODF confirmada del Servicio.")
                continue
            grupos.setdefault((fila["servicio_id"], fila["causa"]), {})[fila["pelo_n_id"]] = fila["id"]

    for (servicio_id, causa), por_pelo in sorted(grupos.items()):
        try:
            excluidos, ajenos = await excluir_pelos(
                sesion,
                servicio_id,
                list(por_pelo),
                usuario=usuario,
                motivo=causa,
                origen=ORIGEN_AUDITORIA,
                auditoria_ids=por_pelo,
                confirmar=False,
            )
        except PeloNoPerteneceAlServicio:
            excluidos, ajenos = [], list(por_pelo)
        for pelo in ajenos:
            resultado.rechazar(por_pelo[pelo], "El pelo ya no es del Servicio o ya estaba excluido.")
        if excluidos:
            marcados = await sesion.execute(
                _SQL_MARCAR,
                {
                    "estado": ESTADO_NORMALIZADO,
                    "usuario": usuario,
                    "ids": [por_pelo[p] for p in excluidos],
                },
            )
            resultado.aplicados.extend(int(i) for (i,) in marcados.all())

    await sesion.commit()
    logger.info(
        "action=cromo_huerfanos_normalizar user=%s aplicados=%s rechazados=%s",
        usuario,
        resultado.aplicados,
        len(resultado.rechazados),
    )
    return resultado


async def descartar(
    sesion: AsyncSession, ids: Iterable[int], *, usuario: Optional[str]
) -> ResultadoRevision:
    """Marca DESCARTADO las filas PENDIENTE elegidas (el admin revisó y no es huérfano). Commitea."""
    resultado = ResultadoRevision()
    pedidos = sorted(set(int(i) for i in ids))
    marcados = await sesion.execute(
        _SQL_MARCAR, {"estado": ESTADO_DESCARTADO, "usuario": usuario, "ids": pedidos}
    )
    resultado.aplicados = sorted(int(i) for (i,) in marcados.all())
    for i in pedidos:
        if i not in resultado.aplicados:
            resultado.rechazar(i, "No existe o no está PENDIENTE.")
    await sesion.commit()
    logger.info(
        "action=cromo_huerfanos_descartar user=%s aplicados=%s rechazados=%s",
        usuario,
        resultado.aplicados,
        len(resultado.rechazados),
    )
    return resultado


# ── Listado para el Viewer ────────────────────────────────────────────────────────────────────

_FILTROS_SQL = """
    WHERE (CAST(:servicio_id AS integer) IS NULL OR a.servicio_id = :servicio_id)
      AND (CAST(:estado AS text) IS NULL OR a.estado = :estado)
"""

_SQL_LISTAR = text(
    f"""
    SELECT a.id, a.servicio_id, s.servicio_id AS servicio_numero, a.pelo_n_id,
           p.numero_pelo, p.color, cab.n_id AS cable_n_id, cab.nombre AS cable_nombre,
           a.camino_semilla, a.causa, a.evidencia, a.estado, a.revisado_por, a.corrida_id,
           a.detectado_at, a.actualizado_at
    FROM app.cromo_auditoria_huerfanos a
    JOIN app.servicios s ON s.id = a.servicio_id
    LEFT JOIN app.cromo_pelos p ON p.n_id = a.pelo_n_id
    LEFT JOIN app.cromo_cables cab ON cab.n_id = p.cable_n_id
    {_FILTROS_SQL}
      AND (CAST(:causa AS text) IS NULL OR a.causa = :causa)
    ORDER BY a.servicio_id, a.camino_semilla, a.pelo_n_id
    LIMIT :limit OFFSET :offset
    """
)

_SQL_CONTAR = text(
    f"""
    SELECT a.causa, COUNT(*) FROM app.cromo_auditoria_huerfanos a
    {_FILTROS_SQL}
    GROUP BY a.causa
    """
)


async def listar_huerfanos(
    sesion: AsyncSession,
    *,
    servicio_id: Optional[int] = None,
    causa: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Página del Viewer. `conteos_por_causa` se calcula con los filtros de servicio y estado pero
    antes del de causa, para que los chips muestren el número de las otras causas."""
    params = {"servicio_id": servicio_id, "estado": estado}
    conteos = {c: 0 for c in CAUSAS}
    for fila_causa, cantidad in (await sesion.execute(_SQL_CONTAR, params)).all():
        conteos[fila_causa] = int(cantidad)
    total = conteos.get(causa, 0) if causa else sum(conteos.values())
    filas = (
        await sesion.execute(
            _SQL_LISTAR, {**params, "causa": causa, "limit": limit, "offset": offset}
        )
    ).mappings().all()
    items = []
    for fila in filas:
        evidencia = fila["evidencia"] or {}
        # Falla cerrado, igual que `normalizar`: sin el dato, se trata como protegido.
        protegido = evidencia.get("protegido") is not False or not isinstance(
            evidencia.get("odfs"), list
        )
        items.append(
            {
                "id": fila["id"],
                "servicio_id": fila["servicio_id"],
                "servicio_numero": fila["servicio_numero"],
                "pelo_n_id": fila["pelo_n_id"],
                "numero_pelo": fila["numero_pelo"],
                "color": fila["color"],
                "cable_n_id": fila["cable_n_id"],
                "cable_nombre": fila["cable_nombre"],
                "camino_semilla": fila["camino_semilla"],
                "causa": fila["causa"],
                "evidencia": evidencia,
                "protegido": protegido,
                "estado": fila["estado"],
                "normalizable": fila["estado"] == ESTADO_PENDIENTE
                and es_normalizable(fila["causa"], protegido),
                "revisado_por": fila["revisado_por"],
                "corrida_id": fila["corrida_id"],
                "detectado_at": fila["detectado_at"].isoformat() if fila["detectado_at"] else None,
                "actualizado_at": (
                    fila["actualizado_at"].isoformat() if fila["actualizado_at"] else None
                ),
            }
        )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
        "conteos_por_causa": conteos,
    }


__all__ = [
    "CAUSAS",
    "CAUSAS_NORMALIZABLES",
    "ESTADOS",
    "ClasificacionHuerfano",
    "ResultadoRevision",
    "ResumenAuditoria",
    "auditar_servicio",
    "auditar_sin_romper",
    "cables_sin_uso",
    "clasificar_residual",
    "descartar",
    "es_normalizable",
    "listar_huerfanos",
    "normalizar",
]
