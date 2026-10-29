# Nombre de archivo: servicios_ingesta_service.py
# Ubicación de archivo: core/services/servicios_ingesta_service.py
# Descripción: Ingesta sync de la planilla de servicios SLA: parseo, consolidación de identidad, upsert y fusión de placeholders

"""Ingesta de la planilla de servicios SLA (`POST /servicios/ingest` de la API interna).

Todo es síncrono (pandas/openpyxl y los loops de consolidación son CPU puro): la ruta lo corre con
`asyncio.to_thread` y una `SessionLocal()` propia, así no bloquea el event loop (B11 de P12). El
SQL y el orden del DML son los mismos que tenía el handler async; la sync de categorías de los
clientes tocados queda en la ruta, después del commit (`sincronizar_clientes_post_ingesta`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import and_, case, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.parsers.archivo_tabular import FormatoNoSoportadoError, leer_tabla
from core.parsers.servicios_excel import parse_servicios_df
from core.services.servicios_categoria_service import CategoriaInvalidaError, validar_categoria
from core.services.servicios_consolidacion_service import (
    consolidar_identidad_servicio,
    es_verificable_por_tipo_y_estado,
    resolver_estado_servicio,
)
from db.models.infra import Servicio, ServicioOrigenDatos

logger = logging.getLogger(__name__)


class FormatoNoSoportado(ValueError):
    """Extensión distinta de .xlsx/.xlsm/.csv — la ruta lo traduce a 415."""


class ArchivoIlegible(ValueError):
    """pandas/openpyxl no pudo leer el archivo — la ruta lo traduce a 400."""


@dataclass(frozen=True)
class ResultadoIngesta:
    """Contadores de `IngestServiciosResponse` más los nombres de cliente que la ruta le pasa a
    `sincronizar_clientes_post_ingesta` (vacío = no se ingirió ninguna fila, no hay sync)."""

    rows_ok: int
    rows_bad: int
    inserted: int
    updated: int
    unchanged: int
    nombres_tocados: list[str | None] = field(default_factory=list)


@dataclass
class PlanFusiones:
    """Placeholders Cromo puros a fusionar después del upsert."""

    # numero_primer_servicio -> id del placeholder a fusionar
    fusiones_pendientes: dict[str, int] = field(default_factory=dict)
    # numero_primer_servicio -> servicio_id final real
    id_final_pendiente_por_numero: dict[str, str] = field(default_factory=dict)


def _chunked(items: list[dict[str, Any]], size: int = 500) -> list[list[dict[str, Any]]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        clean = value.strip()
        return clean or None
    # Soporte para pandas.NA y similares
    try:
        if pd.isna(value):
            return None
    except Exception:  # noqa: BLE001
        return value
    return value


def leer_y_parsear(filename: str, content: bytes) -> tuple[pd.DataFrame, Any]:
    """Lee el archivo y lo normaliza con `parse_servicios_df`: devuelve `(df_ok, summary)`."""
    try:
        df = leer_tabla(filename, content)
    except FormatoNoSoportadoError as exc:
        raise FormatoNoSoportado(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=servicios_ingest_read_error error=%s", exc)
        raise ArchivoIlegible(str(exc)) from exc
    return parse_servicios_df(df)


def armar_filas(df_ok: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Filas del DataFrame normalizadas, indexadas por `numero_primer_servicio` (la última gana)."""
    rows_by_id: dict[str, dict[str, Any]] = {}
    for row in df_ok.to_dict("records"):
        numero_primer_servicio = str(_normalize_value(row.get("numero_primer_servicio")) or "").strip()
        if not numero_primer_servicio:
            continue
        rows_by_id[numero_primer_servicio] = {
            "numero_primer_servicio": numero_primer_servicio,
            "nombre_cliente": _normalize_value(row.get("nombre_cliente")),
            "numero_linea": _normalize_value(row.get("numero_linea")),
            "tipo_servicio": _normalize_value(row.get("tipo_servicio")),
            "sla_prometido": _normalize_value(row.get("sla_prometido")),
            "direccion": _normalize_value(row.get("direccion")),
            "localidad": _normalize_value(row.get("localidad")),
            "provincia": _normalize_value(row.get("provincia")),
            "direccion_2": _normalize_value(row.get("direccion_2")),
            "estado_servicio": _normalize_value(row.get("estado_servicio")) or "DESCONOCIDO",
            "categoria": _normalize_value(row.get("categoria")),
            "linea_upgrade_de": _normalize_value(row.get("linea_upgrade_de")),
            "linea_upgrade_a": _normalize_value(row.get("linea_upgrade_a")),
            # 2026-08-14: re-etiqueta también un placeholder Cromo (origen_datos=INFERIDO_CROMO)
            # preexistente cuando el ingest real lo enriquece por el mismo numero_primer_servicio —
            # sin esto quedaría marcado INFERIDO_CROMO para siempre pese a tener datos reales, ver
            # docs/decisiones.md.
            "origen_datos": ServicioOrigenDatos.INGEST_EXCEL.value,
        }
    return rows_by_id


def consolidar_filas(session: Session, rows_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Completa cada fila (en el lugar) con identidad, estado, categoría y verificable contra lo que
    ya existe en la DB, y devuelve las filas existentes por `numero_primer_servicio`.

    El SELECT de existentes va ANTES del loop: la ingesta decide con lo leído acá y el upsert no
    pisa lo que cambie después (ver `test_ingest_no_pisa_una_excepcion_fijada_mientras_corria`)."""
    # Consolidación de identidad (Task 3/4): calcula el servicio_id/numero_linea/alias_ids finales
    # de cada fila contra lo que ya existe en la DB para ese numero_primer_servicio — reemplaza el
    # upsert ciego anterior, que pisaba servicio_id = numero_primer_servicio en cada corrida (bug
    # real que motiva este plan, ver docs del plan de trazabilidad de IDs).
    numeros = list(rows_by_id.keys())
    existentes_por_id: dict[str, Any] = {}
    if numeros:
        existentes_stmt = select(
            Servicio.numero_primer_servicio,
            Servicio.servicio_id,
            Servicio.numero_linea,
            Servicio.alias_ids,
            Servicio.categoria,
            Servicio.categoria_sla,
            Servicio.categoria_excepcion,
            Servicio.nombre_cliente,
            Servicio.es_verificable_override,
            Servicio.estado_servicio,
        ).where(Servicio.numero_primer_servicio.in_(numeros))
        for fila in session.execute(existentes_stmt).all():
            existentes_por_id[fila.numero_primer_servicio] = fila

    ids_reclamados: dict[str, str] = {}
    for numero, row in rows_by_id.items():
        existente = existentes_por_id.get(numero)
        linea_upgrade_de = row.pop("linea_upgrade_de", None)
        linea_upgrade_a = row.pop("linea_upgrade_a", None)

        identidad = consolidar_identidad_servicio(
            numero_primer_servicio=numero,
            numero_linea_excel=row.get("numero_linea"),
            linea_upgrade_de=linea_upgrade_de,
            linea_upgrade_a=linea_upgrade_a,
            servicio_id_actual=existente.servicio_id if existente else None,
            numero_linea_actual=existente.numero_linea if existente else None,
            alias_ids_actual=list(existente.alias_ids) if existente and existente.alias_ids else None,
        )
        row["servicio_id"] = identidad.servicio_id
        row["numero_linea"] = identidad.numero_linea
        row["alias_ids"] = identidad.alias_ids

        # Un Excel que no aporta el ID de línea más alto conocido (`avanza_por_excel=False`, ej.
        # un archivo viejo subido después para completar el histórico de IDs) no puede degradar un
        # servicio ya "Activo" — sólo completa/relaciona el ID vía `alias_ids` arriba. Ver
        # docs/decisiones.md.
        row["estado_servicio"] = resolver_estado_servicio(
            estado_actual=existente.estado_servicio if existente else None,
            estado_excel=row["estado_servicio"],
            avanza_identidad=identidad.avanza_por_excel,
        )

        # "Nivel Cliente" de la planilla → `categoria_sla` (insumo de la categoría `SLA` del cliente).
        # `isdigit()` sola no alcanza: "7"/"10" son dígitos pero violan el CHECK (0-6) y el
        # IntegrityError sin manejar tumbaba el archivo completo con un 500. Un valor fuera de rango
        # o una celda vacía conservan el `categoria_sla` previo (NULL en un alta): una planilla sin
        # el dato no borra lo que trajo una anterior.
        categoria_excel = row.get("categoria")
        nivel_excel: int | None = None
        if categoria_excel is not None and str(categoria_excel).isdigit():
            try:
                validar_categoria(int(categoria_excel))
                nivel_excel = int(categoria_excel)
            except CategoriaInvalidaError:
                logger.warning(
                    "action=servicios_ingest evento=categoria_invalida numero_primer_servicio=%s valor=%s",
                    numero,
                    categoria_excel,
                )
        categoria_actual = existente.categoria if existente else None
        row["categoria_sla"] = nivel_excel if nivel_excel is not None else (
            existente.categoria_sla if existente else None
        )
        # `categoria` la define el cliente (sync post-commit). Un servicio existente conserva la
        # actual —con o sin excepción—, así re-subir la misma planilla no reescribe una categoría
        # que la sync después revierte (ruling R9). El "Nivel Cliente" sólo es provisional cuando
        # la actual es NULL (incluye las altas); sin dato válido queda NULL — 6 ya no es default.
        if categoria_actual is not None or (existente is not None and existente.categoria_excepcion):
            row["categoria"] = categoria_actual
        else:
            row["categoria"] = nivel_excel

        override_actual = existente.es_verificable_override if existente else None
        row["es_verificable"] = (
            override_actual
            if override_actual is not None
            else es_verificable_por_tipo_y_estado(row.get("tipo_servicio"), row["estado_servicio"])
        )

        # Detección de fragmentación: si dos numero_primer_servicio distintos de ESTE mismo archivo
        # reclaman el mismo id (servicio_id/numero_linea/alias) es una señal de datos inconsistentes
        # en el Excel de origen — se deja loggeado para revisión manual, no bloquea la ingesta.
        for candidato in (row["servicio_id"], row["numero_linea"], *row["alias_ids"]):
            dueño_previo = ids_reclamados.get(candidato)
            if dueño_previo and dueño_previo != numero:
                logger.warning(
                    "action=servicios_ingest evento=fragmentacion_detectada id=%s "
                    "numero_primer_servicio_a=%s numero_primer_servicio_b=%s",
                    candidato,
                    dueño_previo,
                    numero,
                )
            else:
                ids_reclamados[candidato] = numero

    return existentes_por_id


def planear_fusiones(
    session: Session, rows_by_id: dict[str, dict[str, Any]], existentes_por_id: dict[str, Any]
) -> PlanFusiones:
    """Resuelve las colisiones de `servicio_id` (índice UNIQUE) antes del upsert: arma el plan de
    fusión de placeholders Cromo puros y degrada a alias el resto, ajustando las filas en el lugar."""
    # Fusión de placeholders Cromo puros que ya ocupan el servicio_id que esta familia necesita.
    # `app.servicios.servicio_id` tiene índice UNIQUE, así que sin este paso el upsert de más abajo
    # revienta con `duplicate key value violates unique constraint "ix_servicios_servicio_id"` y se
    # pierde el chunk completo de 500 filas (176 casos reales medidos en dev: 161 contra un
    # placeholder INFERIDO_CROMO y 15 contra filas MANUAL).
    # Sólo se fusiona un placeholder INFERIDO_CROMO que de verdad nunca fue tocado — cualquier otra
    # colisión (MANUAL/INGEST_EXCEL, un placeholder divergido, uno con tracking físico encima, o una
    # fila que pertenece a otra familia de ESTE mismo archivo) se degrada sin pisar servicio_id,
    # agregando igual el id a alias_ids, con un warning explícito: fusionar dos registros reales sin
    # confirmación humana está fuera de alcance a propósito.
    candidatos_servicio_id = {row["servicio_id"] for row in rows_by_id.values()}
    colisiones_stmt = select(
        Servicio.id,
        Servicio.servicio_id,
        Servicio.numero_primer_servicio,
        Servicio.origen_datos,
    ).where(Servicio.servicio_id.in_(candidatos_servicio_id))
    colision_por_servicio_id: dict[str, Any] = {}
    for fila in session.execute(colisiones_stmt).all():
        colision_por_servicio_id[fila.servicio_id] = fila

    # Placeholders candidatos a fusión: sólo los que NUNCA fueron tocados por tracking físico (sin
    # filas en rutas_servicio) — el flag origen_datos=INFERIDO_CROMO por sí solo NO lo garantiza,
    # porque core/services/infra_service.py::create_new reusa un Servicio ya existente (`if existing:
    # servicio = existing`, puede ser un placeholder Cromo) y le cuelga una RutaServicio, todo SIN
    # cambiarle origen_datos. Un hard delete no puede apoyarse en una medición puntual ("hoy son 0 en
    # dev"), tiene que chequear el hecho. La tabla legada servicio_empalme_association ya no cuenta
    # (retirada en P22: las rutas son la única fuente; en dev y prod ningún servicio la tenía sin rutas).
    ids_placeholder_candidatos = [
        fila.id
        for fila in colision_por_servicio_id.values()
        if fila.origen_datos == ServicioOrigenDatos.INFERIDO_CROMO
        and fila.numero_primer_servicio == fila.servicio_id
    ]
    ids_con_rutas_o_empalmes: set[int] = set()
    if ids_placeholder_candidatos:
        tocados_stmt = text(
            """
            SELECT DISTINCT servicio_id FROM app.rutas_servicio WHERE servicio_id = ANY(:ids)
            """
        )
        ids_con_rutas_o_empalmes = {
            fila[0]
            for fila in session.execute(tocados_stmt, {"ids": ids_placeholder_candidatos}).all()
        }

    plan = PlanFusiones()
    for numero, row in rows_by_id.items():
        colision = colision_por_servicio_id.get(row["servicio_id"])
        if colision is None or colision.numero_primer_servicio == numero:
            continue  # sin colisión real, o es la propia fila de esta misma familia

        # Si la fila en colisión es de OTRA familia de este mismo archivo, fusionarla sería borrar una
        # fila que el upsert de más abajo está por escribir. Se degrada (no se fusiona) aunque cumpla
        # el resto del predicado de "placeholder puro".
        colisiona_con_otra_familia_del_batch = colision.numero_primer_servicio in rows_by_id
        es_placeholder_puro = (
            not colisiona_con_otra_familia_del_batch
            and colision.origen_datos == ServicioOrigenDatos.INFERIDO_CROMO
            and colision.numero_primer_servicio == colision.servicio_id
            and colision.id not in ids_con_rutas_o_empalmes
        )

        existente = existentes_por_id.get(numero)
        valor_seguro = existente.servicio_id if existente else numero
        if es_placeholder_puro:
            plan.id_final_pendiente_por_numero[numero] = row["servicio_id"]
            plan.fusiones_pendientes[numero] = colision.id
            row["servicio_id"] = valor_seguro
        else:
            logger.warning(
                "action=servicios_ingest evento=servicio_id_colision_no_fusionable "
                "numero_primer_servicio=%s servicio_id_deseado=%s colision_con_id=%s colision_origen=%s "
                "colision_del_mismo_batch=%s",
                numero,
                row["servicio_id"],
                colision.id,
                colision.origen_datos.value if hasattr(colision.origen_datos, "value") else str(colision.origen_datos),
                colisiona_con_otra_familia_del_batch,
            )
            id_final_no_fusionable = row["servicio_id"]
            row["servicio_id"] = valor_seguro
            # `consolidar_identidad_servicio` había excluido `id_final` de los alias y dejado
            # `valor_seguro` adentro, asumiendo que el servicio_id final iba a ser `id_final`. Al
            # degradar se invierte: `valor_seguro` pasa a ser el servicio_id (no tiene sentido que
            # además figure como su propio alias) y `id_final` baja a alias.
            if valor_seguro in row["alias_ids"]:
                row["alias_ids"].remove(valor_seguro)
            if id_final_no_fusionable != valor_seguro and id_final_no_fusionable not in row["alias_ids"]:
                row["alias_ids"].append(id_final_no_fusionable)
    return plan


def upsert_servicios(session: Session, rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Upsert por chunks de 500 sobre `numero_primer_servicio`; sólo actualiza filas que cambiaron.
    Devuelve `(inserted, updated)`."""
    inserted = 0
    updated = 0

    for chunk in _chunked(rows, size=500):
        stmt = pg_insert(Servicio).values(chunk)
        excluded = stmt.excluded

        set_map = {
            "servicio_id": excluded.servicio_id,
            "nombre_cliente": excluded.nombre_cliente,
            "numero_linea": excluded.numero_linea,
            "tipo_servicio": excluded.tipo_servicio,
            "sla_prometido": excluded.sla_prometido,
            "direccion": excluded.direccion,
            "localidad": excluded.localidad,
            "provincia": excluded.provincia,
            "direccion_2": excluded.direccion_2,
            "estado_servicio": excluded.estado_servicio,
            "origen_datos": excluded.origen_datos,
            # Una excepción fijada a mano (`PATCH /{id}/categoria`) mientras corría la ingesta no se
            # pisa con la categoría de la planilla.
            "categoria": case(
                (Servicio.categoria_excepcion, Servicio.categoria), else_=excluded.categoria
            ),
            "categoria_sla": excluded.categoria_sla,
            "es_verificable": excluded.es_verificable,
            "alias_ids": excluded.alias_ids,
        }

        changed_where = or_(
            Servicio.nombre_cliente.is_distinct_from(excluded.nombre_cliente),
            Servicio.numero_linea.is_distinct_from(excluded.numero_linea),
            Servicio.tipo_servicio.is_distinct_from(excluded.tipo_servicio),
            Servicio.sla_prometido.is_distinct_from(excluded.sla_prometido),
            Servicio.direccion.is_distinct_from(excluded.direccion),
            Servicio.localidad.is_distinct_from(excluded.localidad),
            Servicio.provincia.is_distinct_from(excluded.provincia),
            Servicio.direccion_2.is_distinct_from(excluded.direccion_2),
            Servicio.estado_servicio.is_distinct_from(excluded.estado_servicio),
            Servicio.servicio_id.is_distinct_from(excluded.servicio_id),
            Servicio.origen_datos.is_distinct_from(excluded.origen_datos),
            and_(
                Servicio.categoria.is_distinct_from(excluded.categoria),
                Servicio.categoria_excepcion.is_(False),
            ),
            Servicio.categoria_sla.is_distinct_from(excluded.categoria_sla),
            Servicio.es_verificable.is_distinct_from(excluded.es_verificable),
            Servicio.alias_ids.is_distinct_from(excluded.alias_ids),
        )

        stmt = stmt.on_conflict_do_update(
            index_elements=[Servicio.numero_primer_servicio],
            set_=set_map,
            where=changed_where,
        ).returning(text("xmax = 0 AS inserted"))

        result = session.execute(stmt)
        flags = result.all()
        inserted += sum(1 for (flag,) in flags if bool(flag))
        updated += sum(1 for (flag,) in flags if not bool(flag))

    return inserted, updated


def aplicar_fusiones(session: Session, plan: PlanFusiones) -> None:
    """Segunda fase de la fusión: reasigna lo que apuntaba a cada placeholder, lo borra y le da su
    `servicio_id` a la familia real."""
    # Recién acá existe con certeza la fila de la familia real (el upsert la insertó o actualizó),
    # así que ya se le puede reasignar lo que apuntaba al placeholder y liberar el servicio_id.
    #
    # El ORDEN es obligatorio, no cosmético: `app.cromo_servicio_match.servicio_id` referencia
    # `app.servicios.id` SIN `ON DELETE CASCADE` (verificado real con `\d app.cromo_servicio_match`),
    # así que si se borrara el placeholder antes de reasignar, el DELETE fallaría por violación de FK
    # y se caería la ingesta entera. `app.rutas_servicio.servicio_id` sí es `ON DELETE CASCADE`: se
    # reasigna igual porque dejar que la cascada BORRE rutas de un servicio real sería pérdida de
    # datos (en la práctica un placeholder puro nunca tiene rutas — sólo el módulo de tracking
    # físico las crea —, verificado 0 de 9054 en dev, pero reasignar es lo correcto igual).
    fusiones_pendientes = plan.fusiones_pendientes
    id_final_pendiente_por_numero = plan.id_final_pendiente_por_numero
    if not fusiones_pendientes:
        return

    ids_stmt = select(Servicio.id, Servicio.numero_primer_servicio).where(
        Servicio.numero_primer_servicio.in_(list(fusiones_pendientes.keys()))
    )
    id_por_numero = {fila.numero_primer_servicio: fila.id for fila in session.execute(ids_stmt).all()}

    for numero, placeholder_id in fusiones_pendientes.items():
        familia_id = id_por_numero.get(numero)
        if familia_id is None or familia_id == placeholder_id:
            logger.warning(
                "action=servicios_ingest evento=fusion_no_aplicada numero_primer_servicio=%s "
                "placeholder_id=%s familia_id=%s",
                numero,
                placeholder_id,
                familia_id,
            )
            continue
        session.execute(
            text("UPDATE app.cromo_servicio_match SET servicio_id = :familia_id WHERE servicio_id = :placeholder_id"),
            {"familia_id": familia_id, "placeholder_id": placeholder_id},
        )
        session.execute(
            text("UPDATE app.rutas_servicio SET servicio_id = :familia_id WHERE servicio_id = :placeholder_id"),
            {"familia_id": familia_id, "placeholder_id": placeholder_id},
        )
        # `servicio_empalme_association` (retirada, P22) no se toca: su FK es ON DELETE CASCADE.
        session.execute(
            text("DELETE FROM app.servicios WHERE id = :placeholder_id"),
            {"placeholder_id": placeholder_id},
        )
        session.execute(
            text("UPDATE app.servicios SET servicio_id = :id_final WHERE id = :familia_id"),
            {"id_final": id_final_pendiente_por_numero[numero], "familia_id": familia_id},
        )
        logger.warning(
            "action=servicios_ingest evento=placeholder_fusionado numero_primer_servicio=%s "
            "placeholder_id=%s servicio_id_liberado=%s familia_id=%s",
            numero,
            placeholder_id,
            id_final_pendiente_por_numero[numero],
            familia_id,
        )


def ingerir_servicios(session: Session, filename: str, content: bytes) -> ResultadoIngesta:
    """Ingesta completa en una transacción: commit único al final, rollback ante cualquier error.

    Levanta `FormatoNoSoportado` / `ArchivoIlegible` si el archivo no se puede leer. No sincroniza
    las categorías de los clientes: eso lo hace la ruta después del commit con `nombres_tocados`."""
    df_ok, summary = leer_y_parsear(filename, content)
    if df_ok.empty:
        return ResultadoIngesta(
            rows_ok=summary.rows_ok,
            rows_bad=summary.rows_bad,
            inserted=0,
            updated=0,
            unchanged=0,
        )

    try:
        rows_by_id = armar_filas(df_ok)
        existentes_por_id = consolidar_filas(session, rows_by_id)
        plan = planear_fusiones(session, rows_by_id, existentes_por_id)
        rows = list(rows_by_id.values())
        inserted, updated = upsert_servicios(session, rows)
        aplicar_fusiones(session, plan)
        session.commit()
    except Exception:
        session.rollback()
        raise

    # Categoría por cliente: sólo los clientes de este archivo (nombre nuevo y, si la planilla
    # renombró un servicio, también el anterior).
    nombres_tocados = [row.get("nombre_cliente") for row in rows]
    nombres_tocados += [fila.nombre_cliente for fila in existentes_por_id.values()]

    return ResultadoIngesta(
        rows_ok=summary.rows_ok,
        rows_bad=summary.rows_bad,
        inserted=inserted,
        updated=updated,
        unchanged=max(len(rows) - inserted - updated, 0),
        nombres_tocados=nombres_tocados,
    )


__all__ = [
    "ArchivoIlegible",
    "FormatoNoSoportado",
    "PlanFusiones",
    "ResultadoIngesta",
    "aplicar_fusiones",
    "armar_filas",
    "consolidar_filas",
    "ingerir_servicios",
    "leer_y_parsear",
    "planear_fusiones",
    "upsert_servicios",
]
