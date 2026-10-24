# Nombre de archivo: test_web_rutas_contrato.py
# Ubicación de archivo: tests/test_web_rutas_contrato.py
# Descripción: Contrato que congela qué endpoint resuelve cada ruta de la app FastAPI de la SPA (web/app/main.py)

import json
import os
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Match, Mount, WebSocketRoute

from web.app.main import app

RUTA_CONTRATO = Path(__file__).parent / "fixtures" / "web_rutas_contrato.json"

_REEMPLAZOS_CONVERTIDOR = {"int": "1", "float": "1.5", "path": "muestra/sub"}


def muestra_de_ruta(plantilla: str) -> str:
    """Reemplaza los parámetros de una plantilla por valores de muestra."""

    def _reemplazo(coincidencia: re.Match) -> str:
        convertidor = coincidencia.group(1)
        return _REEMPLAZOS_CONVERTIDOR.get(convertidor, "muestra")

    return re.sub(r"\{[^}:]+(?::([^}]+))?\}", _reemplazo, plantilla)


def resolver(app_: FastAPI, tipo: str, metodo: str, path: str) -> str | None:
    """Devuelve el nombre del endpoint que resuelve (primer Match.FULL en orden)."""
    scope = {"type": tipo, "path": path, "root_path": "", "query_string": b"", "headers": []}
    if tipo == "http":
        scope["method"] = metodo
    for ruta in app_.router.routes:
        coincidencia, _ = ruta.matches(scope)
        if coincidencia != Match.FULL:
            continue
        if isinstance(ruta, Mount):
            return f"mount:{ruta.name}"
        return ruta.endpoint.__name__
    return None


def contrato_actual(app_: FastAPI) -> list[dict]:
    """Arma el contrato: una entrada por método de cada APIRoute y por cada WebSocketRoute."""
    entradas = []
    for ruta in app_.router.routes:
        if isinstance(ruta, APIRoute):
            for metodo in sorted(ruta.methods):
                muestra = muestra_de_ruta(ruta.path)
                entradas.append(
                    {
                        "tipo": "http",
                        "metodo": metodo,
                        "plantilla": ruta.path,
                        "muestra": muestra,
                        "endpoint": resolver(app_, "http", metodo, muestra),
                    }
                )
        elif isinstance(ruta, WebSocketRoute):
            muestra = muestra_de_ruta(ruta.path)
            entradas.append(
                {
                    "tipo": "websocket",
                    "metodo": "WEBSOCKET",
                    "plantilla": ruta.path,
                    "muestra": muestra,
                    "endpoint": resolver(app_, "websocket", "", muestra),
                }
            )
    entradas.sort(key=lambda e: (e["plantilla"], e["metodo"]))
    return entradas


def _clave(entrada: dict) -> tuple:
    return (entrada["tipo"], entrada["metodo"], entrada["plantilla"])


def test_contrato_de_rutas_no_cambia():
    actual = contrato_actual(app)
    if os.environ.get("REGENERAR_CONTRATO_RUTAS") == "1":
        RUTA_CONTRATO.parent.mkdir(parents=True, exist_ok=True)
        RUTA_CONTRATO.write_text(
            json.dumps(actual, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        pytest.skip(f"Contrato regenerado con {len(actual)} entradas")

    esperado = json.loads(RUTA_CONTRATO.read_text(encoding="utf-8"))
    por_esperado = {_clave(e): e for e in esperado}
    por_actual = {_clave(e): e for e in actual}

    agregadas = [k for k in por_actual if k not in por_esperado]
    quitadas = [k for k in por_esperado if k not in por_actual]
    cambiadas = [
        (k, por_esperado[k]["endpoint"], por_actual[k]["endpoint"])
        for k in por_actual
        if k in por_esperado and por_esperado[k]["endpoint"] != por_actual[k]["endpoint"]
    ]
    # Las claves duplicadas colapsan en el dict; comparar también la lista completa.
    mensajes = [f"agregada: {k}" for k in agregadas]
    mensajes += [f"quitada: {k}" for k in quitadas]
    mensajes += [f"endpoint cambiado: {k}: {a} -> {b}" for k, a, b in cambiadas]
    if not mensajes and actual != esperado:
        mensajes.append("diferencia en muestra/orden/entradas duplicadas del contrato")
    assert not mensajes, "El contrato de rutas cambió:\n" + "\n".join(mensajes)


@pytest.mark.parametrize(
    ("plantilla", "esperado"),
    [
        ("/api/x/{nombre}", "/api/x/muestra"),
        ("/api/x/{id:int}", "/api/x/1"),
        ("/api/x/{valor:float}", "/api/x/1.5"),
        ("/{path:path}", "/muestra/sub"),
        ("/health/version", "/health/version"),
    ],
)
def test_muestra_de_ruta(plantilla, esperado):
    assert muestra_de_ruta(plantilla) == esperado


def test_resolver_detecta_sombra():
    juguete = FastAPI()

    @juguete.get("/x/{id}")
    def parametrica(id: str):
        return id

    @juguete.get("/x/export")
    def exportar():
        return "export"

    assert resolver(juguete, "http", "GET", "/x/export") == "parametrica"
