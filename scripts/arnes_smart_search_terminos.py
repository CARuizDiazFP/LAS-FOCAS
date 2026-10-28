# Nombre de archivo: arnes_smart_search_terminos.py
# Ubicación de archivo: scripts/arnes_smart_search_terminos.py
# Descripción: Compara el resultado de la smart search de Cámaras entre una revisión anterior y el código actual
"""Arnés viejo-vs-nuevo del matching de la smart search de Cámaras (`buscar_camaras_por_terminos`).

Carga `core/services/camaras_consulta.py` de una revisión de git (`--base`, por defecto `origin/dev`)
como módulo aparte y compara, para cada lista de términos, el TOTAL y la lista ORDENADA de ids que
devuelve contra el código del árbol de trabajo. Las dos corren en la misma sesión y uno después del
otro, así que la deriva de la base de dev (los workers escriben) es mínima.

La versión anterior carga todas las raíces una vez por combinación de filtros y matchea en Python (la
misma función que usaba el endpoint); la nueva se pagina de a `LIMITE_MAXIMO`.

Sólo lecturas (SELECT). Variables de entorno de la base de DEV como en `linea_base_busqueda_camaras.py`;
aborta con exit 2 si no es host local, puerto 5433 y base focas_dev.

Uso:

    python scripts/arnes_smart_search_terminos.py [--base REV] [--terminos-extra "a b" ...]

Exit 0 si no hay diferencias, 1 si las hay (se imprimen los ids sólo-viejo / sólo-nuevo).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.linea_base_busqueda_camaras import _verificar_base_dev  # noqa: E402

# Términos reales de dev y bordes del matching: acentos, puntos ("C.F."), números, 1-2 letras,
# metacaracteres de LIKE, valores de estado/origen y servicios. Se combinan también de a dos (AND).
TERMINOS = [
    "Mitre", "mitre", "MITRE", "301", "Rivadavia", "rivadavia 1", "Av.", "av", "Avenida",
    "San Martín", "san martin", "Martín", "martin", "Peña", "pena", "ñ", "á", "é", "Córdoba", "cordoba",
    "C.F.", "c.f", "cf", "C.F", "Bot", "Bot-1", "BOT 1", "cámara", "camara", "Cam",
    "a", "e", "1", "0", "12", "ab", "de", "B°", "N°", "º", "-", ".", " ", "/", "%", "_", "\\", "'",
    "libre", "LIBRE", "ocupada", "baneada", "detectada", "pendiente", "operativa", "no_operativa",
    "manual", "tracking", "sheet", "inferido", "inferido_cromo", "cromo", "_cromo",
    "O-", "100", "1000", "2000", "999999", "zzzz-no-existe",
]
PARES = [
    ["Mitre", "301"], ["Rivadavia", "1"], ["libre", "Mitre"], ["a", "e"], ["C.F.", "1"],
    ["Peña", "a"], ["manual", "100"], ["Av.", "San Martín"], ["Mitre", "Mitre"], ["cf", "libre"],
]
FILTROS = [
    {"estado": None, "incluir_no_operativas": False},
    {"estado": None, "incluir_no_operativas": True},
    {"estado": "LIBRE", "incluir_no_operativas": False},
]


def _modulo_de_revision(revision: str) -> types.ModuleType:
    fuente = subprocess.run(
        ["git", "-C", str(RAIZ), "show", f"{revision}:core/services/camaras_consulta.py"],
        check=True, capture_output=True, text=True,
    ).stdout
    modulo = types.ModuleType("camaras_consulta_base")
    modulo.__file__ = f"<{revision}>"
    sys.modules[modulo.__name__] = modulo  # las dataclasses resuelven anotaciones por sys.modules
    exec(compile(fuente, modulo.__file__, "exec"), modulo.__dict__)
    return modulo


def _terminos_reales(sesion, cantidad: int = 15) -> list[str]:
    """Servicios, fontine_id y palabras de nombres de cámaras reales de dev (sólo SELECT)."""
    from sqlalchemy import text

    consultas = [
        "SELECT servicio_id FROM app.servicios s WHERE EXISTS (SELECT 1 FROM app.rutas_servicio r "
        "WHERE r.servicio_id = s.id) ORDER BY s.id LIMIT :n",
        "SELECT fontine_id FROM app.camaras WHERE fontine_id IS NOT NULL ORDER BY id LIMIT :n",
        "SELECT split_part(nombre, ' ', 2) FROM app.camaras WHERE camara_padre_id IS NULL "
        "AND split_part(nombre, ' ', 2) <> '' ORDER BY md5(nombre) LIMIT :n",
    ]
    terminos: list[str] = []
    for sql in consultas:
        terminos += [fila[0] for fila in sesion.execute(text(sql), {"n": cantidad // 3})]
    return terminos


def _viejo(base, sesion, cache: dict, filtros: dict, terminos: list[str]) -> list[int]:
    clave = (filtros["estado"], filtros["incluir_no_operativas"])
    if clave not in cache:
        query, _ = base._consulta_base(sesion, filtros["estado"], filtros["incluir_no_operativas"])
        cache[clave] = query.order_by(base.Camara.nombre).all()
    limpios = base.normalizar_terminos(terminos)
    return [c.id for c in cache[clave] if base._coincide_con_todos(c, limpios) is not None]


def _nuevo(actual, sesion, filtros: dict, terminos: list[str]) -> tuple[int, list[int]]:
    ids: list[int] = []
    offset = 0
    while True:
        r = actual.buscar_camaras_por_terminos(sesion, terminos, limit=actual.LIMITE_MAXIMO, offset=offset, **filtros)
        ids += [e.camara.id for e in r.camaras]
        offset += actual.LIMITE_MAXIMO
        if offset >= r.total:
            return r.total, ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/dev", help="revisión de git con la implementación anterior")
    parser.add_argument("--terminos-extra", nargs="*", default=[], help="términos sueltos adicionales")
    args = parser.parse_args()
    _verificar_base_dev()

    from core.services import camaras_consulta as actual
    from db.session import SessionLocal

    base = _modulo_de_revision(args.base)
    diferencias = casos = 0
    t_viejo = t_nuevo = 0.0
    with SessionLocal() as sesion:
        listas = [[t] for t in TERMINOS + _terminos_reales(sesion) + args.terminos_extra] + PARES
        cache: dict = {}
        for filtros in FILTROS:
            for terminos in listas:
                casos += 1
                t0 = time.perf_counter()
                viejo = _viejo(base, sesion, cache, filtros, terminos)
                t1 = time.perf_counter()
                total, nuevo = _nuevo(actual, sesion, filtros, terminos)
                t2 = time.perf_counter()
                t_viejo += t1 - t0
                t_nuevo += t2 - t1
                if viejo == nuevo and total == len(viejo):
                    continue
                diferencias += 1
                solo_viejo = sorted(set(viejo) - set(nuevo))
                solo_nuevo = sorted(set(nuevo) - set(viejo))
                print(
                    f"DIFERENCIA {terminos!r} {filtros}: viejo={len(viejo)} nuevo={len(nuevo)} total_nuevo={total} "
                    f"solo_viejo={solo_viejo[:20]} solo_nuevo={solo_nuevo[:20]}"
                    + (" (mismo conjunto, otro orden)" if not solo_viejo and not solo_nuevo else "")
                )
    print(f"{casos} casos, {diferencias} con diferencias; matching viejo {t_viejo:.1f}s (una sola carga de raíces por filtro), "
          f"nuevo {t_nuevo:.1f}s")
    return 1 if diferencias else 0


if __name__ == "__main__":
    sys.exit(main())
