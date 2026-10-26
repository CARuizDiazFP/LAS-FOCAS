# Nombre de archivo: test_web_camaras_perf_real_db.py
# Ubicación de archivo: tests/test_web_camaras_perf_real_db.py
# Descripción: Cantidad de queries de los listados de Cámaras del panel: no crece con la cantidad de filas

"""Regresión del N+1 de los listados de Cámaras (`/api/infra/camaras`, smart-search): cada fila
disparaba lazy loads de empalmes/rutas/servicio y las queries propias del contexto de estado —
2071 sentencias para 500 cámaras de dev. Con la carga por lote la cantidad queda fija; sólo
`selectinload` suma una sentencia cada 500 padres de una misma relación (por eso se compara 20 contra
200 filas: con menos de 20, algunas relaciones quedan sin padres y no llegan a consultar)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from tests.soporte_postgres_real import requiere_postgres_real
from web.app.main import app

pytestmark = requiere_postgres_real


def _queries(metodo: str, ruta: str, cuerpo: dict | None = None) -> tuple[int, dict]:
    from db.session import engine

    contador = {"n": 0}

    def _contar(*_args, **_kwargs):
        contador["n"] += 1

    event.listen(engine, "before_cursor_execute", _contar)
    try:
        res = TestClient(app).request(metodo, ruta, json=cuerpo)
    finally:
        event.remove(engine, "before_cursor_execute", _contar)
    assert res.status_code == 200, res.text
    return contador["n"], res.json()


@pytest.mark.parametrize("q", ["", "&q=a"])
def test_busqueda_de_camaras_no_crece_con_el_limit(con_sesion, q):
    con_sesion("admin")
    pocas, cuerpo_pocas = _queries("GET", f"/api/infra/camaras?limit=20{q}")
    muchas, cuerpo_muchas = _queries("GET", f"/api/infra/camaras?limit=200{q}")
    assert cuerpo_pocas["total"] == 20 and cuerpo_muchas["total"] == 200
    assert pocas == muchas


def test_smart_search_sin_terminos_no_crece_con_el_limit(con_sesion):
    con_sesion("user")
    pocas, cuerpo_pocas = _queries("POST", "/api/infra/smart-search", {"terms": [], "limit": 20})
    muchas, cuerpo_muchas = _queries("POST", "/api/infra/smart-search", {"terms": [], "limit": 200})
    assert len(cuerpo_pocas["camaras"]) == 20 and len(cuerpo_muchas["camaras"]) == 200
    assert pocas == muchas
