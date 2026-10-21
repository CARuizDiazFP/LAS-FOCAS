# Nombre de archivo: linea_base_busqueda_camaras.py
# Ubicación de archivo: scripts/linea_base_busqueda_camaras.py
# Descripción: Graba y compara la línea base de smart search y exportación de Cámaras contra la base de dev
"""Línea base de la smart search y la exportación de Cámaras.

Sirve para verificar que un refactor de la smart search (`POST /api/infra/smart-search`)
o de la exportación (`GET /api/infra/export/cameras`) de Cámaras no cambia las respuestas.

Sólo lecturas (SELECT). Variables de entorno para la base de DEV:

    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_DB=focas_dev \
    POSTGRES_USER=FOCALBOT POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)"

Aborta con exit 2 si no es host local, puerto 5433 y base focas_dev (nunca producción, 5432).

Uso:

    python scripts/linea_base_busqueda_camaras.py grabar --salida DIR [--solo smart|export]
    python scripts/linea_base_busqueda_camaras.py comparar --salida DIR [--solo smart|export]

Tiempos aproximados: smart unos 20 min, export unos 1,5 min.

Advertencia de deriva: la base de dev cambia (los workers escriben), así que la línea base
se graba FRESCA con el código anterior justo antes de comparar. Pasos:

    1. git worktree add --detach <scratch>/base <commit-anterior>
    2. Enlazar `.venv` y `.secrets` dentro de ese worktree.
    3. `grabar` en <scratch>/base.
    4. `comparar` en el worktree con el cambio.
    5. Si difiere, repetir una vez para descartar deriva.
    6. Al final, `git worktree remove <scratch>/base` sin `--force`.
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
BASE_DEV = "focas_dev"
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
    if str(url.port) != PUERTO_DEV or url.host not in HOSTS_LOCALES or url.database != BASE_DEV:
        _abortar(
            f"la URL efectiva apunta a {url.host}:{url.port}/{url.database}; "
            f"sólo se permite {BASE_DEV} local en {PUERTO_DEV}"
        )


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


def _xlsx_crudo(contenido: bytes) -> str:
    """Lee el XLSX con openpyxl (celdas crudas, sin inferencia de tipos): encabezado + filas."""
    from openpyxl import load_workbook

    libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    hojas = {}
    for hoja in libro.worksheets:
        filas = [list(fila) for fila in hoja.iter_rows(values_only=True)]
        hojas[hoja.title] = {"columnas": filas[0] if filas else [], "filas": filas[1:]}
    libro.close()
    return json.dumps(hojas, ensure_ascii=False, indent=1, default=repr)


def _correr_smart(cliente, resultados: dict[str, str]) -> None:
    for nombre, cuerpo in _combinaciones_smart():
        r = cliente.post("/api/infra/smart-search", json=cuerpo)
        resultados[nombre] = json.dumps({"status": r.status_code, "cuerpo": r.json()}, ensure_ascii=False, indent=1)


def _correr_export(cliente, resultados: dict[str, str]) -> None:
    servicio_id = _servicio_con_camaras()
    resultados["_servicio_id"] = servicio_id
    for estado in ("ALL", "LIBRE", "BANEADA"):
        for formato in ("csv", "xlsx"):
            base = {"filter_status": estado, "format": formato}
            for variante, p in (("", base), ("_srv", {**base, "servicio_id": servicio_id})):
                r = cliente.get("/api/infra/export/cameras", params=p)
                disp = _normalizar_ts(r.headers.get("content-disposition", ""))
                cuerpo = _xlsx_crudo(r.content) if formato == "xlsx" and "xlsx" in disp else r.content.decode("utf-8")
                resultados[f"export_{estado}_{formato}{variante}"] = (
                    f"status={r.status_code}\ncontent-type={r.headers.get('content-type')}\n"
                    f"content-disposition={disp}\n---\n{cuerpo}"
                )


def _correr(solo: str | None) -> dict[str, str]:
    """Devuelve {nombre: contenido_texto}; `solo` limita a 'smart' o 'export'."""
    from fastapi.testclient import TestClient

    from web.app.main import app

    resultados: dict[str, str] = {}
    with patch("web.app.routers.camaras._require_auth", return_value=("linea-base", "admin")):
        cliente = TestClient(app)
        if solo in (None, "smart"):
            _correr_smart(cliente, resultados)
        if solo in (None, "export"):
            _correr_export(cliente, resultados)
    return resultados


def _grabar(salida: Path, solo: str | None) -> int:
    salida.mkdir(parents=True, exist_ok=True)
    resultados = _correr(solo)
    for nombre, contenido in resultados.items():
        with open(salida / f"{nombre}.json", "w", encoding="utf-8", newline="") as f:
            f.write(contenido)
    print(f"Grabadas {len([n for n in resultados if n[0] != '_'])} consultas en {salida}")
    return 0


def _comparar(salida: Path, solo: str | None) -> int:
    if not salida.is_dir():
        _abortar(f"no existe el directorio de línea base {salida}")
    resultados = _correr(solo)
    prefijos = (f"{solo}_",) if solo else ("smart_", "export_")
    grabados = {p.stem for p in salida.glob("*.json") if p.stem.startswith(prefijos)}
    actuales = {n for n in resultados if n.startswith(prefijos)}
    diferencias = 0
    for nombre in sorted(grabados | actuales):
        if nombre not in actuales or nombre not in grabados:
            print(f"DIFERENCIA {nombre}: presente sólo en {'línea base' if nombre in grabados else 'corrida actual'}")
            diferencias += 1
            continue
        with open(salida / f"{nombre}.json", encoding="utf-8", newline="") as f:
            antes = f.read()
        if antes != resultados[nombre]:
            diferencias += 1
            diff = difflib.unified_diff(
                antes.splitlines(keepends=True),
                resultados[nombre].splitlines(keepends=True),
                "linea_base",
                "actual",
                lineterm="",
                n=2,
            )
            print(f"DIFERENCIA {nombre}:")
            print("".join(repr(linea) + "\n" for linea in list(diff)[:60]))
    if diferencias:
        print(f"FALLA: {diferencias} diferencias", file=sys.stderr)
        return 1
    print(f"OK: {len(actuales)} consultas idénticas a la línea base")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=["grabar", "comparar"])
    parser.add_argument("--salida", required=True, type=Path)
    parser.add_argument("--solo", choices=["smart", "export"], default=None, help="limita a un grupo de consultas")
    args = parser.parse_args()
    _verificar_base_dev()
    return _grabar(args.salida, args.solo) if args.accion == "grabar" else _comparar(args.salida, args.solo)


if __name__ == "__main__":
    sys.exit(main())
