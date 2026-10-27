#!/usr/bin/env python3
# Nombre de archivo: check_drift_modelos.py
# Ubicación de archivo: scripts/check_drift_modelos.py
# Descripción: Chequeo (solo lectura) del drift entre los modelos SQLAlchemy y una base Postgres, con el mismo alcance que el autogenerate de Alembic

"""Drift modelo↔base, clasificado.

Corre ``alembic.autogenerate.compare_metadata`` con la configuración de
`db/models/autogenerate.py` (la misma que usa `db/alembic/env.py`) dentro de una transacción
``READ ONLY`` y agrupa cada diferencia:

- índice sólo en la base / sólo en el modelo;
- índice con nombre distinto (mismas columnas y unicidad, otro nombre);
- índice con definición distinta (mismo nombre, otras columnas o unicidad);
- constraint, tabla, columna o FK sólo en un lado;
- tipo, nulabilidad, ``server_default`` y comentario de columna.

Conexión: la misma que `db/session.py` (``ALEMBIC_URL`` > ``DATABASE_URL`` > ``POSTGRES_*`` con la
contraseña del Docker Secret o ``POSTGRES_PASSWORD``). Contra dev:

    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_DB=focas_dev POSTGRES_USER=FOCALBOT \\
      POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)" python scripts/check_drift_modelos.py

Opciones: ``--json`` (salida para máquinas) y ``--detalle`` (lista cada diferencia).
Código de salida: 0 sin drift, 1 con drift, 2 si no se pudo conectar.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

#: Orden de presentación de las categorías.
CATEGORIAS = (
    "indice_solo_base",
    "indice_solo_modelo",
    "indice_nombre_distinto",
    "indice_definicion_distinta",
    "constraint_solo_base",
    "constraint_solo_modelo",
    "tabla_solo_base",
    "tabla_solo_modelo",
    "columna_solo_base",
    "columna_solo_modelo",
    "fk_solo_base",
    "fk_solo_modelo",
    "tipo",
    "nulabilidad",
    "server_default",
    "comentario",
    "otro",
)

_SIMPLES = {
    "remove_constraint": "constraint_solo_base",
    "add_constraint": "constraint_solo_modelo",
    "remove_table": "tabla_solo_base",
    "add_table": "tabla_solo_modelo",
    "remove_column": "columna_solo_base",
    "add_column": "columna_solo_modelo",
    "remove_fk": "fk_solo_base",
    "add_fk": "fk_solo_modelo",
}

_COLUMNA = {
    "modify_type": "tipo",
    "modify_nullable": "nulabilidad",
    "modify_default": "server_default",
    "modify_comment": "comentario",
}


def _columnas_indice(indice: Any) -> tuple[str, ...]:
    return tuple(getattr(e, "name", None) or str(e) for e in indice.expressions)


def _firma_indice(indice: Any) -> tuple[str, tuple[str, ...], bool]:
    return (indice.table.name, _columnas_indice(indice), bool(indice.unique))


def _describir_indice(indice: Any) -> str:
    unico = " UNIQUE" if indice.unique else ""
    return f"{indice.table.name}.{indice.name}{unico} ({', '.join(_columnas_indice(indice))})"


def _describir_objeto(op: tuple[Any, ...]) -> str:
    obj = op[1]
    tabla = getattr(obj, "table", None)
    if tabla is not None:
        return f"{tabla.name}.{getattr(obj, 'name', obj)}"
    if len(op) > 3 and isinstance(op[2], str):  # add/remove_column: (op, schema, tabla, columna)
        return f"{op[2]}.{op[3].name}"
    return str(getattr(obj, "name", obj))


def _describir_columna(op: tuple[Any, ...]) -> str:
    # (op, schema, tabla, columna, existing_kw, valor_base, valor_modelo)
    _, _, tabla, columna, _, en_base, en_modelo = op
    return f"{tabla}.{columna}: base={_texto(en_base)} modelo={_texto(en_modelo)}"


def _texto(valor: Any) -> str:
    arg = getattr(valor, "arg", None)  # DefaultClause
    if arg is not None:
        return str(getattr(arg, "text", arg))
    return repr(valor) if isinstance(valor, str) else str(valor)


def clasificar(diferencias: list[Any]) -> dict[str, list[str]]:
    """Agrupa la salida de ``compare_metadata`` por categoría (descripciones legibles)."""
    grupos: dict[str, list[str]] = defaultdict(list)
    agregados: list[Any] = []
    quitados: list[Any] = []

    for diff in diferencias:
        ops = diff if isinstance(diff, list) else [diff]
        for op in ops:
            tipo = op[0]
            if tipo == "add_index":
                agregados.append(op[1])
            elif tipo == "remove_index":
                quitados.append(op[1])
            elif tipo in _SIMPLES:
                grupos[_SIMPLES[tipo]].append(_describir_objeto(op))
            elif tipo in _COLUMNA:
                grupos[_COLUMNA[tipo]].append(_describir_columna(op))
            else:
                grupos["otro"].append(repr(op))

    por_nombre_base = {(i.table.name, i.name): i for i in quitados}
    por_firma_base: dict[tuple[str, tuple[str, ...], bool], list[Any]] = defaultdict(list)
    for indice in quitados:
        por_firma_base[_firma_indice(indice)].append(indice)
    emparejados: set[int] = set()

    for indice in agregados:
        mismo_nombre = por_nombre_base.get((indice.table.name, indice.name))
        if mismo_nombre is not None and id(mismo_nombre) not in emparejados:
            emparejados.add(id(mismo_nombre))
            grupos["indice_definicion_distinta"].append(
                f"{_describir_indice(mismo_nombre)} → modelo {_describir_indice(indice)}"
            )
            continue
        candidatos = [i for i in por_firma_base[_firma_indice(indice)] if id(i) not in emparejados]
        if candidatos:
            emparejados.add(id(candidatos[0]))
            grupos["indice_nombre_distinto"].append(
                f"{indice.table.name}: base {candidatos[0].name} ↔ modelo {indice.name}"
            )
            continue
        grupos["indice_solo_modelo"].append(_describir_indice(indice))

    for indice in quitados:
        if id(indice) not in emparejados:
            grupos["indice_solo_base"].append(_describir_indice(indice))

    return {c: sorted(grupos[c]) for c in CATEGORIAS if grupos.get(c)}


def _conectar_y_comparar() -> tuple[str, str, list[Any]]:
    from sqlalchemy import text

    from db.models.autogenerate import comparar_modelos
    from db.session import engine

    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            base = conn.execute(text("SELECT current_database()")).scalar_one()
            revision = conn.execute(text("SELECT string_agg(version_num, ',') FROM alembic_version")).scalar()
            return base, revision or "-", comparar_modelos(conn)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="salida JSON")
    parser.add_argument("--detalle", action="store_true", help="listar cada diferencia")
    args = parser.parse_args(argv)

    try:
        base, revision, diferencias = _conectar_y_comparar()
    except Exception as exc:  # conexión, auth o esquema: no hay nada que comparar
        print(f"No se pudo comparar contra la base: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    grupos = clasificar(diferencias)
    total = sum(len(v) for v in grupos.values())

    if args.json:
        print(json.dumps({"base": base, "revision": revision, "total": total, "grupos": grupos}, ensure_ascii=False, indent=2))
    else:
        print(f"Base: {base} (revisión {revision})")
        print(f"Diferencias modelo↔base: {total}")
        for categoria, items in grupos.items():
            print(f"  {categoria}: {len(items)}")
            if args.detalle:
                for item in items:
                    print(f"    - {item}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
