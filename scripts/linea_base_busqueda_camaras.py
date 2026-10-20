# Nombre de archivo: linea_base_busqueda_camaras.py
# Ubicación de archivo: scripts/linea_base_busqueda_camaras.py
# Descripción: Graba y compara la línea base de smart search y exportación de Cámaras contra la base de dev
"""Uso: python scripts/linea_base_busqueda_camaras.py {grabar,comparar} --salida DIR

Sólo lecturas (SELECT). Aborta con exit 2 si la base no es la de dev local (puerto 5433).
"""

from __future__ import annotations

import argparse
import difflib
import io
import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PUERTO_DEV = "5433"
HOSTS_LOCALES = {"127.0.0.1", "localhost", "::1"}
_TS = re.compile(r"camaras_\d{8}_\d{6}")


def _abortar(mensaje: str) -> None:
    print(f"ABORTADO: {mensaje}", file=sys.stderr)
    sys.exit(2)


def _verificar_base_dev() -> None:
    """Verifica variables de entorno y la URL efectiva del engine (sin imprimir la contraseña)."""
    host = os.getenv("POSTGRES_HOST", "")
    puerto = os.getenv("POSTGRES_PORT", "")
    if host not in HOSTS_LOCALES or puerto != PUERTO_DEV:
        _abortar(f"se exige POSTGRES_HOST local y POSTGRES_PORT={PUERTO_DEV} (recibido host={host!r} puerto={puerto!r})")
    from db.session import engine

    url = engine.url
    if str(url.port) != PUERTO_DEV or url.host not in HOSTS_LOCALES:
        _abortar(f"la URL efectiva apunta a {url.host}:{url.port}; sólo se permite dev local en {PUERTO_DEV}")


def _combinaciones_smart() -> list[tuple[str, dict]]:
    terminos = {
        "vacio": [],
        "ruta": ["ruta"],
        "ruta_5_espacios": ["RUTA ", " 5"],
        "repetido": ["a", "a"],
        "cadena_vacia": [""],
    }
    estados = {"sin": None, "libre": "LIBRE", "nooper": "NO_OPERATIVA"}
    consultas = []
    for tn, t in terminos.items():
        for en, e in estados.items():
            for inc in (False, True):
                for off in (0, 50):
                    nombre = f"smart_{tn}_est-{en}_inc-{int(inc)}_off-{off}"
                    cuerpo = {"terms": t, "estado": e, "incluir_no_operativas": inc, "limit": 50, "offset": off}
                    consultas.append((nombre, cuerpo))
    return consultas


def _servicio_con_camaras() -> str:
    """Primer servicio (menor id) con alguna ruta activa cuyo empalme tenga cámara (sólo SELECT)."""
    from sqlalchemy import text

    from db.session import SessionLocal

    consulta = text(
        "SELECT s.servicio_id FROM app.servicios s "
        "JOIN app.rutas_servicio r ON r.servicio_id = s.id AND r.activa "
        "JOIN app.ruta_empalme_association a ON a.ruta_id = r.id "
        "JOIN app.empalmes e ON e.id = a.empalme_id AND e.camara_id IS NOT NULL "
        "WHERE s.servicio_id IS NOT NULL ORDER BY s.id LIMIT 1"
    )
    with SessionLocal() as sesion:
        fila = sesion.execute(consulta).first()
    if fila is None:
        _abortar("no se encontró ningún servicio con cámaras en la base de dev")
    return fila[0]


def _normalizar_ts(texto: str) -> str:
    return _TS.sub("camaras_TS", texto)


def _correr_todo() -> dict[str, str]:
    """Devuelve {nombre: contenido_texto} con todas las respuestas."""
    import pandas as pd
    from fastapi.testclient import TestClient

    from web.app.main import app

    resultados: dict[str, str] = {}
    servicio_id = _servicio_con_camaras()
    resultados["_servicio_id"] = servicio_id
    with patch("web.app.routers.camaras._require_auth", return_value=("linea-base", "admin")):
        cliente = TestClient(app)
        for nombre, cuerpo in _combinaciones_smart():
            r = cliente.post("/api/infra/smart-search", json=cuerpo)
            resultados[nombre] = json.dumps(
                {"status": r.status_code, "cuerpo": r.json()}, ensure_ascii=False, indent=1, sort_keys=False
            )
        for estado in ("ALL", "LIBRE", "BANEADA"):
            for formato in ("csv", "xlsx"):
                nombre = f"export_{estado}_{formato}"
                params = {"filter_status": estado, "servicio_id": servicio_id, "format": formato}
                for variante, p in (("", {k: v for k, v in params.items() if k != "servicio_id"}), ("_srv", params)):
                    r = cliente.get("/api/infra/export/cameras", params=p)
                    disp = _normalizar_ts(r.headers.get("content-disposition", ""))
                    if formato == "xlsx" and "xlsx" in disp:
                        filas = pd.read_excel(io.BytesIO(r.content)).fillna("").to_dict(orient="records")
                        cuerpo = json.dumps(filas, ensure_ascii=False, indent=1, default=str)
                    else:
                        cuerpo = r.content.decode("utf-8")
                    resultados[nombre + variante] = (
                        f"status={r.status_code}\ncontent-type={r.headers.get('content-type')}\n"
                        f"content-disposition={disp}\n---\n{cuerpo}"
                    )
    return resultados



def _grabar(salida: Path) -> int:
    salida.mkdir(parents=True, exist_ok=True)
    resultados = _correr_todo()
    for nombre, contenido in resultados.items():
        with open(salida / f"{nombre}.json", "w", encoding="utf-8", newline="") as f:
            f.write(contenido)
    print(f"Grabadas {len(resultados) - 1} consultas en {salida} (servicio_id={resultados['_servicio_id']})")
    return 0


def _comparar(salida: Path) -> int:
    if not salida.is_dir():
        _abortar(f"no existe el directorio de línea base {salida}")
    resultados = _correr_todo()
    grabados = {p.stem for p in salida.glob("*.json")}
    diferencias = 0
    for nombre in sorted(grabados | set(resultados)):
        if nombre not in resultados or nombre not in grabados:
            print(f"DIFERENCIA {nombre}: presente sólo en {'línea base' if nombre in grabados else 'corrida actual'}")
            diferencias += 1
            continue
        with open(salida / f"{nombre}.json", encoding="utf-8", newline="") as f:
            antes = f.read()
        if antes != resultados[nombre]:
            diferencias += 1
            diff = difflib.unified_diff(
                antes.splitlines(keepends=True), resultados[nombre].splitlines(keepends=True), "linea_base", "actual", lineterm="", n=2
            )
            print(f"DIFERENCIA {nombre}:")
            print("".join(repr(linea) + "\n" for linea in list(diff)[:60]))
    if diferencias:
        print(f"FALLA: {diferencias} diferencias", file=sys.stderr)
        return 1
    print(f"OK: {len(resultados) - 1} consultas idénticas a la línea base")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=["grabar", "comparar"])
    parser.add_argument("--salida", required=True, type=Path)
    args = parser.parse_args()
    _verificar_base_dev()
    return _grabar(args.salida) if args.accion == "grabar" else _comparar(args.salida)


if __name__ == "__main__":
    sys.exit(main())
