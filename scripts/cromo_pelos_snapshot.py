# Nombre de archivo: cromo_pelos_snapshot.py
# Ubicación de archivo: scripts/cromo_pelos_snapshot.py
# Descripción: Copia los at.61/62/63 de pelos leídos por /inner de un entorno a otro (dev → prod) y concilia los servicios sin consultar Cromo

"""Poblar prod con el barrido `/inner` que ya corrió en dev, sin volver a pagar ~12 h de Cromo.

Dev y prod consultan el mismo Cromo (`CROMO_BASE_URL` y credencial iguales, verificado 2026-10-01) y
los tubos/pelos se identifican por el `n_id` de Cromo, igual en las dos bases: los **atributos** de
cada pelo se pueden copiar. Los **vínculos** pelo→servicio no, porque `cromo_servicio_match.servicio_id`
es el id interno de `app.servicios` de cada base (difieren entre dev y prod) y hay que respetar los
servicios, conectores de ODF y vínculos `MANUAL` del destino. Por eso son tres pasos:

1. ``exportar`` (en dev): CSV por stdout de los tubos y pelos leídos por `/inner`
   (`atributos_leidos_at` no nulo).
2. ``importar`` (en prod): upsert por `n_id` desde stdin. Pisa sólo los campos que vienen de Cromo
   (los de `PELO_CAMPOS` + at.62/63); nunca `verificable`/`status`, que se cargan a mano.
3. ``conciliar`` (en prod): `ingesta.fase_pelos_desde_inventario`, la misma regla de
   `pelo_servicios.py` que usa el barrido, con los datos ya importados.

``importar`` y ``conciliar`` son **dry-run exacto por defecto** (todo dentro de una transacción que se
revierte); ``--apply`` escribe. ``conciliar --apply`` commitea por tanda y se puede continuar con
``--reanudar <corrida>``.

Se corren dentro del contenedor `api` de cada entorno (`lasfocas-api` tiene `scripts/` en la imagen):

    # dev, cuando el barrido terminó (una sola vez)
    docker exec -i -w /app -e PYTHONPATH=/app lasfocasdev-api python - exportar --tabla tubos \\
        < scripts/cromo_pelos_snapshot.py | gzip > ~/snapshot_tubos.csv.gz
    docker exec -i -w /app -e PYTHONPATH=/app lasfocasdev-api python - exportar --tabla pelos \\
        < scripts/cromo_pelos_snapshot.py | gzip > ~/snapshot_pelos.csv.gz

    # prod: dry-run, revisar, y la misma línea con --apply
    gunzip -c ~/snapshot_tubos.csv.gz | docker exec -i lasfocas-api python scripts/cromo_pelos_snapshot.py importar --tabla tubos
    gunzip -c ~/snapshot_pelos.csv.gz | docker exec -i lasfocas-api python scripts/cromo_pelos_snapshot.py importar --tabla pelos
    docker exec lasfocas-api python scripts/cromo_pelos_snapshot.py conciliar --limite 200
    docker exec lasfocas-api python scripts/cromo_pelos_snapshot.py conciliar --apply --usuario cruizdiaz@metrotel.com.ar
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if "__file__" in globals() and not __file__.startswith("<"):  # por stdin no hay archivo: usa PYTHONPATH
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import setup_logging
from core.services.cromo import ingesta
from db.models.cromo import CromoIngestaCorrida
from db.session import async_engine, engine

logger = setup_logging("cromo_pelos_snapshot")

TIPO_CORRIDA = "MANUAL_PELOS_DESDE_SNAPSHOT"
_LIMITE_DRY_RUN = 200

COLUMNAS = {
    "tubos": ("n_id", "cable_n_id", "orden", "nombre_color"),
    "pelos": (
        "n_id", "tubo_n_id", "cable_n_id", "numero_pelo", "orden", "color", "servicio_raw",
        "servicio_numero", "tipo_asociacion", "servicio_atributo", "estado_cromo", "atributos_leidos_at",
    ),
}
_SELECT_EXPORTAR = {
    "tubos": """
        SELECT t.n_id, t.cable_n_id, t.orden, t.nombre_color FROM app.cromo_tubos t
        WHERE EXISTS (SELECT 1 FROM app.cromo_pelos p WHERE p.tubo_n_id = t.n_id AND p.atributos_leidos_at IS NOT NULL)
        ORDER BY t.n_id
    """,
    "pelos": f"""
        SELECT {", ".join(COLUMNAS["pelos"])} FROM app.cromo_pelos
        WHERE atributos_leidos_at IS NOT NULL ORDER BY n_id
    """,
}
_TIPOS_TEMP = {
    "tubos": "n_id bigint, cable_n_id bigint, orden smallint, nombre_color text",
    "pelos": (
        "n_id bigint, tubo_n_id bigint, cable_n_id bigint, numero_pelo text, orden smallint, color text, "
        "servicio_raw text, servicio_numero text, tipo_asociacion text, servicio_atributo text, "
        "estado_cromo text, atributos_leidos_at timestamptz"
    ),
}
# `(xmax = 0)` es verdadero sólo en las filas recién insertadas: cuenta creadas vs actualizadas en un
# solo paso. `vigente` vuelve a true: si Cromo trajo el pelo en `/inner`, existe.
_UPSERT = {
    "tubos": """
        INSERT INTO app.cromo_tubos (n_id, cable_n_id, orden, nombre_color, vigente, ultima_ingesta)
        SELECT n_id, cable_n_id, orden, nombre_color, true, now() FROM tmp_snapshot
        ON CONFLICT (n_id) DO UPDATE SET cable_n_id = EXCLUDED.cable_n_id, orden = EXCLUDED.orden,
            nombre_color = EXCLUDED.nombre_color, vigente = true, ultima_ingesta = now()
        RETURNING (xmax = 0)
    """,
    "pelos": """
        INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, numero_pelo, orden, color, servicio_raw,
            servicio_numero, tipo_asociacion, servicio_atributo, estado_cromo, atributos_leidos_at, vigente,
            ultima_ingesta)
        SELECT n_id, tubo_n_id, cable_n_id, numero_pelo, orden, color, servicio_raw, servicio_numero,
            CAST(tipo_asociacion AS app.cromo_tipo_asociacion_pelo), servicio_atributo, estado_cromo,
            atributos_leidos_at, true, now()
        FROM tmp_snapshot
        ON CONFLICT (n_id) DO UPDATE SET tubo_n_id = EXCLUDED.tubo_n_id, cable_n_id = EXCLUDED.cable_n_id,
            numero_pelo = EXCLUDED.numero_pelo, orden = EXCLUDED.orden, color = EXCLUDED.color,
            servicio_raw = EXCLUDED.servicio_raw, servicio_numero = EXCLUDED.servicio_numero,
            tipo_asociacion = EXCLUDED.tipo_asociacion, servicio_atributo = EXCLUDED.servicio_atributo,
            estado_cromo = EXCLUDED.estado_cromo, atributos_leidos_at = EXCLUDED.atributos_leidos_at,
            vigente = true, ultima_ingesta = now()
        RETURNING (xmax = 0)
    """,
}


def exportar(tabla: str, salida) -> int:
    """Escribe el CSV (con encabezado) en `salida` (binario). Devuelve la cantidad de filas."""
    with engine.connect() as conn:
        en_curso = conn.execute(
            text(
                "SELECT count(*) FROM app.cromo_ingesta_corridas WHERE estado = 'EN_CURSO' "
                "AND params->>'tipo' = 'MANUAL_BARRIDO_PELOS_INNER'"
            )
        ).scalar_one()
        if en_curso:
            raise SystemExit("Hay un barrido /inner EN_CURSO: exportar recién cuando termine.")
        # Un barrido lanzado con la versión anterior del script corre en UNA transacción y no se ve como
        # EN_CURSO hasta el commit final (corrida 2149, 2026-10-01): exportar en ese momento daría la
        # foto previa al barrido. Una transacción abierta hace más de 10 minutos es esa señal.
        abiertas = conn.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND pid <> pg_backend_pid() AND xact_start < now() - interval '10 minutes'"
            )
        ).scalar_one()
        if abiertas:
            raise SystemExit(
                f"Hay {abiertas} transacción(es) abierta(s) hace más de 10 min (¿un barrido en curso?): "
                "exportar recién cuando terminen."
            )
        filas = conn.execute(text(f"SELECT count(*) FROM ({_SELECT_EXPORTAR[tabla]}) x")).scalar_one()
        cursor = conn.connection.dbapi_connection.cursor()
        with cursor.copy(f"COPY ({_SELECT_EXPORTAR[tabla]}) TO STDOUT WITH (FORMAT csv, HEADER)") as copia:
            for bloque in copia:
                salida.write(bytes(bloque))
        salida.flush()
    return filas


def importar(tabla: str, entrada, *, aplicar: bool) -> dict:
    """Carga el CSV de `entrada` en una tabla temporal y hace el upsert. Dry-run exacto sin `aplicar`."""
    with engine.connect() as conn:
        transaccion = conn.begin()
        try:
            conn.execute(text(f"CREATE TEMP TABLE tmp_snapshot ({_TIPOS_TEMP[tabla]}) ON COMMIT DROP"))
            cursor = conn.connection.dbapi_connection.cursor()
            columnas = ", ".join(COLUMNAS[tabla])
            with cursor.copy(f"COPY tmp_snapshot ({columnas}) FROM STDIN WITH (FORMAT csv, HEADER)") as copia:
                while bloque := entrada.read(1 << 20):
                    copia.write(bloque)
            leidas = conn.execute(text("SELECT count(*) FROM tmp_snapshot")).scalar_one()
            duplicadas = conn.execute(
                text("SELECT count(*) FROM (SELECT n_id FROM tmp_snapshot GROUP BY n_id HAVING count(*) > 1) d")
            ).scalar_one()
            if duplicadas:
                raise SystemExit(f"El CSV trae {duplicadas} n_id repetidos: no se importa nada.")
            resultado = [r[0] for r in conn.execute(text(_UPSERT[tabla])).all()]
        except BaseException:
            transaccion.rollback()
            raise
        if aplicar:
            transaccion.commit()
        else:
            transaccion.rollback()
    return {
        "modo": "apply" if aplicar else "dry-run",
        "tabla": tabla,
        "filas_csv": leidas,
        "creadas": sum(resultado),
        "actualizadas": len(resultado) - sum(resultado),
    }


async def conciliar(args: argparse.Namespace) -> dict:
    inicio = time.perf_counter()
    async with async_engine.connect() as conn:
        externa = None if args.apply else await conn.begin()
        try:
            async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False) as s:
                if args.reanudar:
                    corrida = await s.get(CromoIngestaCorrida, args.reanudar)
                    if corrida is None or (corrida.params or {}).get("tipo") != TIPO_CORRIDA:
                        raise SystemExit(f"La corrida {args.reanudar} no es una conciliación {TIPO_CORRIDA}")
                    corrida.estado, corrida.finalizada_at = "EN_CURSO", None
                else:
                    corrida = await ingesta.iniciar_corrida(
                        s, usuario=args.usuario, psize=0, max_paginas=None, clases=(),
                        params_extra={"tipo": TIPO_CORRIDA},
                    )
                contadores = ingesta.ContadoresCorrida(
                    leidas=corrida.leidas or 0, actualizadas=corrida.actualizadas or 0, errores=corrida.errores or 0
                ) if args.reanudar else ingesta.ContadoresCorrida()
                limite = args.limite if args.limite is not None else (None if args.apply else _LIMITE_DRY_RUN)
                cables = [args.cable] if args.cable is not None else None

                def _progreso(hechos: int, total: int, resumen: ingesta.ResumenPelosInner) -> None:
                    print(
                        f"[{datetime.now():%H:%M:%S}] {hechos}/{total} cables pelos={resumen.pelos_leidos} "
                        f"creados={resumen.vinculos_creados} retirados={resumen.vinculos_retirados} "
                        f"errores={resumen.cables_error}",
                        file=sys.stderr, flush=True,
                    )

                resumen = await ingesta.fase_pelos_desde_inventario(
                    s, corrida, contadores, cables=cables, limite=limite, reanudar=bool(args.reanudar),
                    detallar=cables is not None, al_avanzar=_progreso,
                )
                corrida.estado = "OK" if resumen.cables_error == 0 else "OK_CON_ERRORES"
                corrida.finalizada_at = datetime.now(timezone.utc)
                ingesta.sincronizar_contadores(corrida, contadores)
                await s.commit()
                corrida_id = corrida.id
        except BaseException:
            if externa is not None:
                await externa.rollback()
            raise
        if externa is not None:
            await externa.rollback()
    return {
        "modo": "apply" if args.apply else "dry-run",
        "corrida_id": corrida_id if args.apply else None,
        "duracion_s": round(time.perf_counter() - inicio, 1),
        "cables_ok": resumen.cables_ok,
        "cables_error": resumen.cables_error,
        "pelos": resumen.pelos_leidos,
        "pelos_con_manual_sin_tocar": resumen.pelos_con_manual,
        "vinculos_creados": resumen.vinculos_creados,
        "vinculos_retirados": resumen.vinculos_retirados,
        "vinculos_metodo_cambiado": resumen.vinculos_metodo_cambiado,
        "numeros_sin_servicio": len(resumen.numeros_sin_servicio),
        "detalle": resumen.detalle,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)
    p_exp = sub.add_parser("exportar", help="CSV por stdout (en el entorno que corrió el barrido)")
    p_exp.add_argument("--tabla", choices=sorted(COLUMNAS), required=True)
    p_imp = sub.add_parser("importar", help="CSV por stdin, upsert por n_id (dry-run por defecto)")
    p_imp.add_argument("--tabla", choices=sorted(COLUMNAS), required=True)
    p_imp.add_argument("--apply", action="store_true")
    p_con = sub.add_parser("conciliar", help="vínculos pelo→servicio con los atributos ya importados")
    p_con.add_argument("--apply", action="store_true")
    p_con.add_argument("--usuario", default="pelos-desde-snapshot")
    p_con.add_argument("--cable", type=int, help="n_id de un cable puntual (muestra el detalle)")
    p_con.add_argument("--limite", type=int, help=f"máximo de cables (default: todos con --apply, {_LIMITE_DRY_RUN} en dry-run)")
    p_con.add_argument("--reanudar", type=int, help="id de una corrida de conciliación para continuarla")
    args = parser.parse_args()

    if args.comando == "exportar":
        filas = exportar(args.tabla, sys.stdout.buffer)
        logger.info("action=cromo_pelos_snapshot comando=exportar tabla=%s filas=%s", args.tabla, filas)
        print(json.dumps({"tabla": args.tabla, "filas": filas}), file=sys.stderr)
        return
    if args.comando == "importar":
        resultado = importar(args.tabla, sys.stdin.buffer, aplicar=args.apply)
        logger.info("action=cromo_pelos_snapshot comando=importar %s", resultado)
        print(json.dumps(resultado, ensure_ascii=False))
        return
    if args.reanudar and not args.apply:
        parser.error("--reanudar sólo tiene sentido con --apply")
    resultado = asyncio.run(conciliar(args))
    logger.info(
        "action=cromo_pelos_snapshot comando=conciliar modo=%s corrida_id=%s cables_ok=%s creados=%s retirados=%s",
        resultado["modo"], resultado["corrida_id"], resultado["cables_ok"],
        resultado["vinculos_creados"], resultado["vinculos_retirados"],
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
