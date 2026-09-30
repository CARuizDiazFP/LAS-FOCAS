# Nombre de archivo: arnes_busqueda_camaras.py
# Ubicación de archivo: scripts/arnes_busqueda_camaras.py
# Descripción: Arneses read-only de la búsqueda de cámaras (auto-recuperación, transiciones y textos reales) para comparar el código base contra una rama

"""Arneses de regresión de la búsqueda de cámaras (`buscar_camara_o_botella_cromo`).

Criterio de aceptación de cualquier cambio a `camara_search.py`/`camara_botella_busqueda.py`
(`docs/relevamiento_ingresos_sin_match_2026-09-28.md`): **0 incorrectas nuevas** en los dos arneses,
comparando el código base contra la rama sobre el mismo inventario (dev, read-only).

Corre DENTRO de `lasfocasdev-slack-baneo-worker`, con el código de cada versión copiado a un
directorio propio y antepuesto en `PYTHONPATH` (``/tmp/arnes/base``, ``/tmp/arnes/rama``):

    W=<worktree>; C=lasfocasdev-slack-baneo-worker; mkdir -p /tmp/x/base /tmp/x/rama
    git -C $W archive HEAD core modules db | tar -x -C /tmp/x/base      # base = HEAD sin cambios
    (cd $W && tar -c core modules db) | tar -x -C /tmp/x/rama           # rama = working tree
    docker exec $C mkdir -p /tmp/arnes && docker cp /tmp/x/base $C:/tmp/arnes/ && docker cp /tmp/x/rama $C:/tmp/arnes/
    docker cp scripts/arnes_busqueda_camaras.py $C:/tmp/arnes/
    # opcional: textos reales ("id|texto" por línea) exportados read-only de prod
    docker exec -w /app -e PYTHONPATH=/tmp/arnes/base:/app $C python /tmp/arnes/arnes_busqueda_camaras.py generar /tmp/arnes [--textos /tmp/arnes/prod.tsv]
    for v in base rama; do for s in auto trans prod; do
      docker exec -w /app -e PYTHONPATH=/tmp/arnes/$v:/app $C python /tmp/arnes/arnes_busqueda_camaras.py correr /tmp/arnes $s $v &
    done; done; wait        # trans tarda ~30 min por versión (7.000+ entradas)
    docker exec $C python /tmp/arnes/arnes_busqueda_camaras.py comparar /tmp/arnes trans

**Una "INCORRECTA" nueva no es automáticamente un bug** (2026-09-29): el arnés compara por Cámara
raíz, y los pares duplicados legado/Cromo ("Cámara Rawson 2342" contra "Cra Rawson 2342 MARTINEZ")
cuentan como incorrectas. `clasificar` corre la versión actual (usar la base) sobre el nombre
ORIGINAL de cada caso y sobre el texto sin la localidad: si la base ya da la misma cámara, es
heredado, no nuevo. El caso real que sí era bug ("Ruta 9 Km 63" → "Ruta 8 Km 63.9") se distinguía
porque la base no lo resolvía así.
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

_RE_TIPO = re.compile(r"(?i)^\s*(cra|c[aá]mara|poste)\b\.?\s*")


def _sesion():
    from sqlalchemy import text

    from db.session import SessionLocal

    s = SessionLocal()
    s.execute(text("SET TRANSACTION READ ONLY"))
    return s


def generar(d: Path, textos: str | None) -> None:
    """auto: 1.500 Cámaras (seed 7) buscándose a sí mismas. trans: 2.000 Cámaras con número (seed 11)
    + localidad propia/al azar, tipo cambiado, tipo + localidad, "Cra" antepuesto."""
    from sqlalchemy import text

    s = _sesion()
    camaras = s.execute(text("SELECT id, nombre FROM app.camaras WHERE nombre IS NOT NULL ORDER BY id")).all()
    loc_por_camara = dict(s.execute(text(
        "SELECT DISTINCT ON (camara_id) camara_id, localidad FROM app.cromo_botellas "
        "WHERE vigente AND camara_id IS NOT NULL AND coalesce(localidad,'') <> '' ORDER BY camara_id, n_id")).all())
    locs = [r[0] for r in s.execute(text(
        "SELECT localidad FROM app.cromo_botellas WHERE vigente AND coalesce(localidad,'')<>'' "
        "GROUP BY 1 HAVING count(*) >= 15 ORDER BY 1")).all()]
    s.rollback()
    s.close()

    auto = [{"k": f"auto:{cid}", "texto": nom, "esperado": cid} for cid, nom in random.Random(7).sample(camaras, 1500)]
    rnd = random.Random(11)
    trans = []
    for cid, nom in rnd.sample([c for c in camaras if re.search(r"\d", c[1])], 2000):
        loc = loc_por_camara.get(cid) or rnd.choice(locs)
        trans.append({"k": f"loc:{cid}", "texto": f"{nom} {loc.upper()}", "esperado": cid})
        trans.append({"k": f"locr:{cid}", "texto": f"{nom} {rnd.choice(locs)}", "esperado": cid})
        m = _RE_TIPO.match(nom)
        if m:
            swap = ("Poste" if m.group(1).lower() != "poste" else "Cra") + " " + nom[m.end():]
            trans.append({"k": f"tipo:{cid}", "texto": swap, "esperado": cid})
            trans.append({"k": f"tipoloc:{cid}", "texto": f"{swap} {loc}", "esperado": cid})
        else:
            trans.append({"k": f"pre:{cid}", "texto": f"Cra {nom}", "esperado": cid})
    prod = []
    if textos:
        for linea in open(textos):
            i, _, t = linea.rstrip("\n").partition("|")
            if i.isdigit():
                prod.append({"k": f"prod:{i}", "texto": t, "esperado": None})
    for nombre, datos in (("auto", auto), ("trans", trans), ("prod", prod)):
        json.dump(datos, open(d / f"{nombre}.json", "w"), ensure_ascii=False)
    print(len(auto), len(trans), len(prod))


def _buscar(s, texto: str):
    from core.services.cromo.camara_botella_busqueda import buscar_camara_o_botella_cromo
    from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError, limpiar_ruido_operativo

    try:
        r = buscar_camara_o_botella_cromo(limpiar_ruido_operativo(texto), s)
        return ("M", r.camara.id, r.camara.nombre) if r.camara is not None else ("N", None, None)
    except AmbiguousSearchError as exc:
        return ("A", None, "; ".join(exc.candidatos))


def correr(d: Path, conjunto: str, version: str) -> None:
    from db.models.infra import Camara

    entradas = json.load(open(d / f"{conjunto}.json"))
    s = _sesion()
    raiz = {cid: (padre or cid) for cid, padre in s.query(Camara.id, Camara.camara_padre_id).all()}
    out, lat = {}, []
    for e in entradas:
        t0 = time.monotonic()
        res, cid, nombre = _buscar(s, e["texto"])
        lat.append(time.monotonic() - t0)
        out[e["k"]] = {"texto": e["texto"], "esperado": e.get("esperado"), "res": res, "id": cid, "nombre": nombre,
                       "raiz": raiz.get(cid) if cid else None,
                       "raiz_esperada": raiz.get(e["esperado"]) if e.get("esperado") else None}
    s.rollback()
    s.close()
    lat.sort()
    print(f"{version} {conjunto}: n={len(lat)} mediana={lat[len(lat) // 2] * 1000:.0f}ms max={lat[-1] * 1000:.0f}ms")
    json.dump(out, open(d / f"out_{version}_{conjunto}.json", "w"), ensure_ascii=False)


def _clase(x: dict) -> str:
    if x["res"] != "M":
        return {"A": "ambiguo", "N": "sin_match"}[x["res"]]
    if x["esperado"] is None:
        return "match"
    return "correcta" if x["raiz"] == x["raiz_esperada"] else "INCORRECTA"


def comparar(d: Path, conjunto: str) -> list[str]:
    b = json.load(open(d / f"out_base_{conjunto}.json"))
    r = json.load(open(d / f"out_rama_{conjunto}.json"))
    print("base:", dict(Counter(_clase(x) for x in b.values())))
    print("rama:", dict(Counter(_clase(x) for x in r.values())))
    trans, nuevas = Counter(), []
    for k in b:
        cb, cr = _clase(b[k]), _clase(r[k])
        if cb != cr or (cb == cr == "match" and b[k]["id"] != r[k]["id"]):
            trans[(cb, cr)] += 1
            if cr in ("INCORRECTA", "match"):  # los "match" de textos reales se revisan a mano
                print(f"  {cb}->{cr} {k}: {r[k]['texto']!r} => {r[k]['nombre']!r}")
            if cr == "INCORRECTA":
                nuevas.append(k)
    print("transiciones:", {f"{a}->{c}": n for (a, c), n in trans.items()})
    return nuevas


def clasificar(d: Path, conjunto: str) -> None:
    """Para cada incorrecta nueva: qué da la versión cargada (usar la BASE) con el nombre original de
    la Cámara esperada y con el texto sin localidad final."""
    from core.services.localidades_catalogo import localidades, quitar_localidad_final
    from db.models.infra import Camara

    r = json.load(open(d / f"out_rama_{conjunto}.json"))
    nuevas = comparar(d, conjunto)
    s = _sesion()
    cat = localidades(s)
    for k in nuevas:
        origen = s.get(Camara, r[k]["esperado"])
        sin_loc = quitar_localidad_final(r[k]["texto"], cat)
        print(f"{k} origen={origen.nombre!r} rama={r[k]['nombre']!r}\n"
              f"   base(origen)={_buscar(s, origen.nombre)[2]!r}\n   base({sin_loc!r})={_buscar(s, sin_loc)[2]!r}")
    s.rollback()
    s.close()


def main() -> None:
    uso = "uso: generar <dir> [--textos f] | correr <dir> <auto|trans|prod> <base|rama> | comparar|clasificar <dir> <conjunto>"
    if len(sys.argv) < 3:
        sys.exit(uso)
    cmd, d = sys.argv[1], Path(sys.argv[2])
    if cmd == "generar":
        generar(d, sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--textos" else None)
    elif cmd == "correr":
        correr(d, sys.argv[3], sys.argv[4])
    elif cmd == "comparar":
        comparar(d, sys.argv[3])
    elif cmd == "clasificar":
        clasificar(d, sys.argv[3])
    else:
        sys.exit(uso)


if __name__ == "__main__":
    main()
