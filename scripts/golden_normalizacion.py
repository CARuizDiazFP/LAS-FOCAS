# Nombre de archivo: golden_normalizacion.py
# Ubicación de archivo: scripts/golden_normalizacion.py
# Descripción: Corpus real y golden snapshot de la normalización de nombres (P11), más cascada de búsqueda contra focas_dev

"""Golden de la normalización de nombres de cámaras/botellas (P11).

Subcomandos:

* ``exportar --prod-mensajes <json>``: arma ``tests/fixtures/normalizacion/corpus.json.gz``
  (``{"nombres": [...], "mensajes": [...]}``) con nombres reales de focas_dev (SELECT vía
  ``docker exec lasfocasdev-postgres psql``), mensajes sintéticos, los textos reales anonimizados
  de prod (archivo ya exportado; este script NO consulta prod) y casos frontera.
* ``snapshot``: aplica cada función de ``FUNCIONES_GOLDEN`` (tests/test_normalizacion_golden.py) sobre
  el corpus y guarda ``golden.json`` (sha256 por bloque de 512 salidas ``repr()``).
* ``cascada --salida <json>``: ``buscar_camara`` sobre una muestra fija (semilla 11) de 2.000 nombres
  de Cámaras + variantes; sólo lectura contra la DB de dev (rollback al final). Corre DENTRO de
  ``lasfocasdev-slack-baneo-worker`` (ver el reporte de la Task 1 para el comando exacto).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import random
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FIXTURES = RAIZ / "tests" / "fixtures" / "normalizacion"
CORPUS = FIXTURES / "corpus.json.gz"
GOLDEN = FIXTURES / "golden.json"
TAM_BLOQUE = 512

FRONTERA = [
    "",
    "   ",
    "Bot 30 de Septiembre",
    "Empalme 10245762: Cra 25 de Mayo 302",
    "*negrita*",
    "Cra Mitre 440 \U0001f6a7",
    "Cámara 5º piso",
    "Cámara 5° piso",
    "Straße ß 12",
]


def _psql_json(sql: str) -> list[str]:
    """SELECT de una sola columna vía psql dentro del contenedor dev (sin imprimir credenciales)."""
    consulta = f"SELECT coalesce(json_agg(n ORDER BY n), '[]'::json) FROM ({sql}) t(n)"
    r = subprocess.run(
        ["docker", "exec", "lasfocasdev-postgres", "sh", "-c",
         'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "$0"', consulta],
        capture_output=True, text=True, check=True,
    )
    return json.loads(r.stdout)


def _mensajes_sinteticos(n: str) -> list[str]:
    return [
        f"*Nombre: Nodo/Camara/botella*\n{n}\n*Ingreso o Egreso*\nIngreso",
        f"Cámara: {n}",
        f"*Nombre: Nodo/Camara/botella*\nme:\n{n}\n*Otro*",
    ]


def exportar(prod_mensajes: Path) -> None:
    fuentes = {
        "camaras": _psql_json("SELECT DISTINCT nombre FROM app.camaras WHERE nombre IS NOT NULL"),
        "cromo_botellas": _psql_json("SELECT DISTINCT nombre FROM app.cromo_botellas WHERE nombre IS NOT NULL"),
        "camara_alias": _psql_json("SELECT DISTINCT alias_nombre FROM app.camara_alias WHERE alias_nombre IS NOT NULL"),
    }
    prod = json.loads(prod_mensajes.read_text(encoding="utf-8"))
    nombres_reales = sorted({n for lista in fuentes.values() for n in lista})
    mensajes = {m for n in nombres_reales for m in _mensajes_sinteticos(n)}
    mensajes.update(prod)
    mensajes.update(FRONTERA)
    nombres = set(nombres_reales) | set(prod) | set(FRONTERA)
    corpus = {"nombres": sorted(nombres), "mensajes": sorted(mensajes)}
    FIXTURES.mkdir(parents=True, exist_ok=True)
    datos = json.dumps(corpus, ensure_ascii=False).encode("utf-8")
    with open(CORPUS, "wb") as crudo, gzip.GzipFile(fileobj=crudo, mode="wb", mtime=0, filename="") as gz:
        gz.write(datos)
    for k, v in fuentes.items():
        print(f"{k}: {len(v)}")
    print(f"prod_mensajes: {len(prod)}")
    print(f"corpus: nombres={len(corpus['nombres'])} mensajes={len(corpus['mensajes'])}")


def cargar_corpus() -> dict[str, list[str]]:
    with gzip.open(CORPUS, "rt", encoding="utf-8") as f:
        return json.load(f)


def cargar_funciones():
    ruta = RAIZ / "tests" / "test_normalizacion_golden.py"
    sys.path.insert(0, str(RAIZ))
    spec = importlib.util.spec_from_file_location("test_normalizacion_golden", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def serializar(fn, entrada: str) -> str:
    try:
        return repr(fn(entrada))
    except Exception as e:  # noqa: BLE001 — se congela también la excepción
        return f"EXC:{type(e).__name__}:{e}"


def hashes_bloques(fn, entradas: list[str]) -> list[str]:
    salidas = [serializar(fn, e) for e in entradas]
    return [
        hashlib.sha256("\n".join(salidas[i:i + TAM_BLOQUE]).encode("utf-8")).hexdigest()
        for i in range(0, len(salidas), TAM_BLOQUE)
    ]


def snapshot() -> None:
    mod = cargar_funciones()
    corpus = cargar_corpus()
    golden = {}
    for nombre, fn in mod.FUNCIONES_GOLDEN.items():
        entradas = corpus[mod.ENTRADA_DE[nombre]]
        golden[nombre] = {"total": len(entradas), "bloques": hashes_bloques(fn, entradas)}
    GOLDEN.write_text(json.dumps(golden, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"golden.json: {len(golden)} funciones")


def _sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def cascada(salida: Path) -> None:
    from sqlalchemy import text

    from db.session import SessionLocal
    from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError, buscar_camara

    s = SessionLocal()
    s.execute(text("SET TRANSACTION READ ONLY"))
    nombres = [r[0] for r in s.execute(text("SELECT nombre FROM app.camaras WHERE nombre IS NOT NULL ORDER BY id")).all()]
    muestra = random.Random(11).sample(nombres, 2000)
    entradas: list[str] = []
    for n in muestra:
        entradas += [
            n,
            re.sub(r"\bbot\.?\s*(\d)", r"bot\1", n, flags=re.IGNORECASE) if re.search(r"\bbot\.?\s*\d", n, re.IGNORECASE) else f"{n} bot2",
            _sin_acentos(n),
            f"{n} - CUADRILLA X",
            re.sub(r"\s+", " ", re.sub(r"\d+", "", n)).strip(),
        ]
    resultado = {}
    for e in dict.fromkeys(entradas):
        try:
            camara, nombre_norm = buscar_camara(e, s)
            resultado[e] = [camara.id if camara is not None else None, nombre_norm]
        except AmbiguousSearchError as exc:
            resultado[e] = [type(exc).__name__, exc.cantidad, exc.candidatos]
        except Exception as exc:  # noqa: BLE001
            resultado[e] = [f"EXC:{type(exc).__name__}", str(exc)]
    s.rollback()
    s.close()
    salida.write_text(json.dumps(resultado, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"cascada: {len(resultado)} entradas -> {salida}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("exportar")
    e.add_argument("--prod-mensajes", type=Path, required=True)
    sub.add_parser("snapshot")
    c = sub.add_parser("cascada")
    c.add_argument("--salida", type=Path, required=True)
    a = p.parse_args()
    if a.cmd == "exportar":
        exportar(a.prod_mensajes)
    elif a.cmd == "snapshot":
        snapshot()
    else:
        cascada(a.salida)


if __name__ == "__main__":
    main()
