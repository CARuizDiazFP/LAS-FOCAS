# Nombre de archivo: clientes_categoria_regularizar.py
# Ubicación de archivo: scripts/clientes_categoria_regularizar.py
# Descripción: Regularización única de categorías por cliente — sync global, alias conocidos, Lista C6 y propagación; dry-run con rollback

"""Se corre una vez por entorno, primero con `--dry-run`.

Orden de las operaciones (todas en UNA transacción; sin `--dry-run` se hace un único commit al final):

1. `sincronizar_categorias` global: crea los clientes, la categoría automática y `a_revisar`.
2. Alias `canónico | variante` del archivo. Si el canónico no tiene cliente todavía se lo crea con
   `aplicar_lista` (C6, origen `LISTA`) y recién entonces se vincula la variante. Una variante que ya
   resuelve al mismo cliente por normalización se omite (se reporta).
3. `aplicar_lista(nombres_c6, 6, "agregar")`: fija C6 con origen `LISTA` (crea sin servicios los que no
   existen, p. ej. MEPADIP) y reporta sugerencias para los nombres sin match.
4. Sync global final (la propagación retroactiva a `servicios`).

El paso 2 va antes que el 3 para que las variantes (p. ej. "BANCO CREDICOOP") se fusionen en su
canónico antes de que la lista cree clientes duplicados.

Con `--dry-run` todo corre dentro de una transacción externa que se revierte al final
(`join_transaction_mode="create_savepoint"`, patrón de `ingresos_reprocesar_sin_match.py`): el resumen
es exactamente lo que haría la corrida real.

    python scripts/clientes_categoria_regularizar.py --dry-run            # host (variables POSTGRES_* de dev)
    docker exec lasfocasdev-api python scripts/clientes_categoria_regularizar.py --dry-run

El archivo por defecto es `scripts/data/clientes_c6_inicial.txt` (la imagen `api` copia `scripts/` entero);
`--archivo PATH` usa otro.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.logging import setup_logging
from core.services.clientes_categoria_service import (
    ClienteCategoriaError,
    agregar_alias_por_nombre,
    aplicar_lista,
    listar_clientes_por_categoria,
    normalizar_clave_cliente,
    previsualizar_lista,
    resolver_cliente,
    sincronizar_categorias,
)
from db.session import engine

logger = setup_logging("clientes_categoria_regularizar")

ARCHIVO_POR_DEFECTO = ROOT_DIR / "scripts" / "data" / "clientes_c6_inicial.txt"
USUARIO = "regularizacion-2026-10-14"
CATEGORIA_LISTA = 6
MAX_A_REVISAR = 30


def parsear_archivo(contenido: str) -> tuple[list[str], list[tuple[str, str]]]:
    """`(nombres, alias)` del archivo: ignora líneas vacías y `#`; `canónico | variante` es un alias.
    Deduplica nombres y pares por clave normalizada, conservando el orden y la primera grafía."""
    nombres: list[str] = []
    alias: list[tuple[str, str]] = []
    claves_nombres: set[str] = set()
    claves_alias: set[tuple[str, str]] = set()
    for linea in contenido.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        if "|" in linea:
            canonico, _, variante = (parte.strip() for parte in linea.partition("|"))
            clave_c, clave_v = normalizar_clave_cliente(canonico), normalizar_clave_cliente(variante)
            if not clave_c or not clave_v or (clave_c, clave_v) in claves_alias:
                continue
            claves_alias.add((clave_c, clave_v))
            alias.append((canonico, variante))
            continue
        clave = normalizar_clave_cliente(linea)
        if clave and clave not in claves_nombres:
            claves_nombres.add(clave)
            nombres.append(linea)
    return nombres, alias


def _servicios_por_categoria(session: Session) -> dict[str, int]:
    filas = session.execute(text("SELECT categoria, count(*) FROM app.servicios GROUP BY categoria")).all()
    return {("NULL" if cat is None else str(cat)): int(n) for cat, n in sorted(filas, key=lambda f: (f[0] is None, f[0]))}


def _clientes_por_categoria_y_origen(session: Session) -> dict[str, dict[str, int]]:
    filas = session.execute(
        text(
            "SELECT categoria, CAST(origen_categoria AS text), count(*) FROM app.clientes "
            "GROUP BY 1, 2 ORDER BY 1 NULLS LAST, 2"
        )
    ).all()
    salida: dict[str, dict[str, int]] = {}
    for cat, origen, n in filas:
        salida.setdefault("NULL" if cat is None else str(cat), {})[origen] = int(n)
    return salida


def _cargar_alias(session: Session, alias: list[tuple[str, str]]) -> dict:
    aplicados: list[dict] = []
    omitidos: list[dict] = []
    for canonico, variante in alias:
        cliente = resolver_cliente(session, canonico)
        if cliente is None:
            aplicar_lista(session, [canonico], CATEGORIA_LISTA, "agregar", usuario=USUARIO)
            cliente = resolver_cliente(session, canonico)
        if cliente is None:
            omitidos.append({"canonico": canonico, "variante": variante, "motivo": "canónico sin cliente"})
            continue
        actual = resolver_cliente(session, variante)
        if actual is not None and actual.id == cliente.id:
            omitidos.append({"canonico": canonico, "variante": variante, "motivo": "ya resuelve al mismo cliente"})
            continue
        try:
            agregar_alias_por_nombre(session, cliente.id, variante, origen="MANUAL")
        except ClienteCategoriaError as exc:
            omitidos.append({"canonico": canonico, "variante": variante, "motivo": str(exc)})
            continue
        aplicados.append({"canonico": canonico, "variante": variante, "cliente_id": cliente.id})
    return {"aplicados": aplicados, "omitidos": omitidos}


def regularizar(session: Session, nombres: list[str], alias: list[tuple[str, str]]) -> dict:
    """Corre los 4 pasos sobre `session` (sin commit) y devuelve el resumen."""
    antes_servicios = _servicios_por_categoria(session)
    antes_clientes = _clientes_por_categoria_y_origen(session)

    sync_inicial = sincronizar_categorias(session)
    resultado_alias = _cargar_alias(session, alias)

    previa = previsualizar_lista(session, nombres, CATEGORIA_LISTA, "agregar", usuario=USUARIO)
    sin_match = list(previa.nuevos)
    sugerencias = dict(previa.sugerencias)
    lista = aplicar_lista(session, nombres, CATEGORIA_LISTA, "agregar", usuario=USUARIO)
    sync_final = sincronizar_categorias(session)

    grupos = listar_clientes_por_categoria(session)
    claves_lista = {normalizar_clave_cliente(n) for n in nombres}
    claves_lista |= {normalizar_clave_cliente(c) for c, _ in alias}
    c6_fuera_de_lista = [
        {"nombre": c["nombre"], "servicios": c["servicios"], "origen": c["origen_categoria"]}
        for c in grupos["6"]
        if c["origen_categoria"] == "SLA"
        and not ({normalizar_clave_cliente(a["nombre_original"]) for a in c["alias"]} & claves_lista)
    ]
    a_revisar = sorted(c["nombre"] for g in grupos.values() for c in g if c["a_revisar"])

    return {
        "servicios_por_categoria": {"antes": antes_servicios, "despues": _servicios_por_categoria(session)},
        "clientes_por_categoria_y_origen": {
            "antes": antes_clientes,
            "despues": _clientes_por_categoria_y_origen(session),
        },
        "lista_c6": {
            "nombres_en_archivo": len(nombres),
            "con_match": len(nombres) - len(sin_match),
            "creados_sin_servicios": sin_match,
            "sugerencias": sugerencias,
        },
        "alias": resultado_alias,
        "a_revisar": {"total": len(a_revisar), "primeros": a_revisar[:MAX_A_REVISAR]},
        "c6_por_sla_fuera_de_la_lista": c6_fuera_de_lista,
        "sync_inicial": sync_inicial.to_dict(),
        "sync_final": sync_final.to_dict(),
        "lista_resultado": {k: lista[k] for k in ("creados", "sync")},
    }


def ejecutar(connection, nombres: list[str], alias: list[tuple[str, str]], *, aplicar: bool) -> dict:
    """Corre la regularización sobre `connection`. Con `aplicar=False` revierte todo al final."""
    transaccion = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", autoflush=False)
    try:
        resumen = regularizar(session, nombres, alias)
    except BaseException:
        session.close()
        transaccion.rollback()
        raise
    session.close()
    if aplicar:
        transaccion.commit()
    else:
        transaccion.rollback()
    resumen["modo"] = "apply" if aplicar else "dry-run"
    return resumen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="corre todo y revierte al final")
    parser.add_argument("--archivo", default=str(ARCHIVO_POR_DEFECTO), help="lista C6 y alias (ver docstring)")
    args = parser.parse_args()

    ruta = Path(args.archivo)
    if not ruta.is_file():
        raise SystemExit(f"No existe el archivo {ruta} (usar --archivo)")
    nombres, alias = parsear_archivo(ruta.read_text(encoding="utf-8"))
    if not nombres:
        raise SystemExit(f"{ruta} no tiene nombres")

    with engine.connect() as connection:
        resumen = ejecutar(connection, nombres, alias, aplicar=not args.dry_run)
    logger.info("action=clientes_categoria_regularizar modo=%s nombres=%d alias=%d", resumen["modo"], len(nombres), len(alias))
    print(json.dumps(resumen, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
