# Nombre de archivo: ingresos_reprocesar_sin_match.py
# Ubicación de archivo: scripts/ingresos_reprocesar_sin_match.py
# Descripción: Reproceso por lote de app.ingresos_sin_match (Slack) con la búsqueda actual; dry-run exacto por defecto

"""Reprocesa los casos pendientes de `app.ingresos_sin_match` con la búsqueda de cámaras ACTUAL y
registra los movimientos que ahora resuelven, con su horario original. Lógica en
`core/services/ingreso_reproceso_service.py` (ver su docstring para las reglas).

**Dry-run exacto por defecto**: corre TODO el reproceso —mismas consultas, mismas escrituras— dentro de
una transacción externa que al final se revierte (`join_transaction_mode="create_savepoint"`: los
`commit()` de los servicios sólo liberan savepoints). El reporte del dry-run es lo que haría `--apply`,
no una estimación.

Correr DENTRO del contenedor del worker de Slack del entorno, con el código y la `DATABASE_URL`
desplegados (nunca desde el host contra prod). El contenedor no tiene `scripts/` ni `/tmp`: el script
entra por stdin y el reporte sale por stdout (`--reporte -`):

    docker exec -i -w /app -e PYTHONPATH=/app <prefijo>-slack-baneo-worker \\
        python - --slack --reporte - < scripts/ingresos_reprocesar_sin_match.py > reproceso_dry.json
    # revisar el reporte; si está bien, la misma línea con --apply

`--slack` resuelve el nombre del técnico con la Slack Web API (`users.info`), igual que en vivo. Sin él
se guarda el ID crudo de Slack. `--ids 12,15` limita a esos casos. No postea nada en Slack.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

if "__file__" in globals() and not __file__.startswith("<"):  # por stdin no hay archivo: usa PYTHONPATH
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.orm import Session

from core.logging import setup_logging
from core.services.ingreso_reproceso_service import reporte_como_dicts, reprocesar_ingresos_sin_match
from db.session import engine

logger = setup_logging("ingresos_reprocesar_sin_match")


def _cliente_slack():
    from slack_sdk import WebClient

    from core.config import get_settings

    token = get_settings().slack.bot_token
    if not token:
        raise SystemExit("--slack pedido pero no hay SLACK_BOT_TOKEN configurado")
    return WebClient(token=token)


def ejecutar(connection, *, aplicar: bool, client=None, ids: list[int] | None = None) -> list[dict]:
    """Corre el reproceso sobre `connection`. Con `aplicar=False` revierte todo al final."""
    transaccion = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", autoflush=False)
    try:
        reporte = reporte_como_dicts(reprocesar_ingresos_sin_match(session, client=client, ids=ids))
    except BaseException:
        session.close()
        transaccion.rollback()
        raise
    session.close()
    if aplicar:
        transaccion.commit()
    else:
        transaccion.rollback()
    return reporte


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="escribe los cambios (sin esto: dry-run exacto)")
    parser.add_argument("--slack", action="store_true", help="resolver nombres de técnico vía Slack")
    parser.add_argument("--ids", default="", help="ids de caso separados por coma")
    parser.add_argument("--reporte", default="", help="ruta del reporte JSON por caso ('-' = stdout)")
    args = parser.parse_args()

    ids = [int(x) for x in args.ids.split(",") if x.strip()] or None
    client = _cliente_slack() if args.slack else None
    inicio = time.perf_counter()
    with engine.connect() as connection:
        reporte = ejecutar(connection, aplicar=args.apply, client=client, ids=ids)

    conteo = collections.Counter(item["estado"] for item in reporte)
    acciones = collections.Counter(m["accion"] for item in reporte for m in item["movimientos"])
    logger.info(
        "action=reproceso_ingresos_sin_match modo=%s casos=%d estados=%s acciones=%s duracion_s=%.1f",
        "apply" if args.apply else "dry-run",
        len(reporte),
        dict(conteo),
        dict(acciones),
        time.perf_counter() - inicio,
    )
    resumen = json.dumps({"modo": "apply" if args.apply else "dry-run", "casos": len(reporte),
                          "estados": dict(conteo), "acciones": dict(acciones)}, ensure_ascii=False)
    if args.reporte == "-":
        print(json.dumps(reporte, ensure_ascii=False, indent=1))
        print(resumen, file=sys.stderr)
        return
    if args.reporte:
        Path(args.reporte).write_text(json.dumps(reporte, ensure_ascii=False, indent=1))
    print(resumen)


if __name__ == "__main__":
    main()
