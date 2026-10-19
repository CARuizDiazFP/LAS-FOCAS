# Nombre de archivo: test_web_arbitro_cromo.py
# Ubicación de archivo: tests/test_web_arbitro_cromo.py
# Descripción: Pruebas de wiring (admin, CSRF, validación, códigos, encolado) de los endpoints web del árbitro de Cromo — sin DB real ni Redis

from __future__ import annotations

from typing import Any

import pytest

from core.services.cromo.arbitro import cola, evaluaciones, motor
from tests.test_web_cromo_camino_optico import _cliente_admin, _cliente_user

URL = "/api/admin/infra/arbitro-cromo"


class _Sesion:
    def __init__(self, commits: list) -> None:
        self._commits = commits

    async def commit(self):
        self._commits.append(1)


@pytest.fixture
def commits(monkeypatch) -> list:
    """Sesión fake con commit contado; TESTING=true saltea el CSRF."""
    registro: list = []

    class _CM:
        async def __aenter__(self):
            return _Sesion(registro)

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("db.session.AsyncSessionLocal", lambda: _CM())
    monkeypatch.setenv("TESTING", "true")
    return registro


@pytest.fixture
def encolados(monkeypatch) -> list:
    registro: list = []

    async def _encolar(alcance, disparo, motivo="", *, evaluacion_id=None, reglas=None):
        registro.append(
            {"alcance": alcance.a_dict(), "disparo": disparo, "motivo": motivo,
             "evaluacion_id": evaluacion_id, "reglas": reglas}
        )

    monkeypatch.setattr(cola, "encolar_evaluacion", _encolar)
    return registro


@pytest.mark.parametrize(
    "metodo, url, cuerpo",
    [
        ("get", f"{URL}/propuestas", None),
        ("post", f"{URL}/propuestas/aplicar", {"ids": [1]}),
        ("post", f"{URL}/propuestas/rechazar", {"ids": [1]}),
        ("post", f"{URL}/propuestas/revertir", {"ids": [1]}),
        ("get", f"{URL}/reglas", None),
        ("post", f"{URL}/reglas", {"codigo": "X", "modo": "SOMBRA", "umbral": 90, "presupuesto_por_corrida": 5}),
        ("post", f"{URL}/normalizar", {}),
        ("get", f"{URL}/evaluaciones", None),
    ],
)
def test_solo_admin(monkeypatch, commits, metodo, url, cuerpo):
    client = _cliente_user(monkeypatch)
    res = client.get(url) if metodo == "get" else client.post(url, json=cuerpo)
    assert res.status_code == 403


def test_propuestas_requiere_admin(monkeypatch, commits):
    assert _cliente_user(monkeypatch).get(f"{URL}/propuestas").status_code == 403


def test_aplicar_sin_csrf_403(monkeypatch, commits):
    monkeypatch.delenv("TESTING", raising=False)
    client = _cliente_admin(monkeypatch)
    res = client.post(f"{URL}/propuestas/aplicar", json={"ids": [1], "csrf_token": "otro"})
    assert res.status_code == 403
    assert res.json()["error"] == "CSRF inválido"


def test_propuestas_valida_limites_y_pasa_parametros(monkeypatch, commits):
    recibido: dict[str, Any] = {}

    async def _listar(_s, **kw):
        recibido.update(kw)
        return {"items": [], "total": 0}

    monkeypatch.setattr(motor, "listar_propuestas", _listar)
    client = _cliente_admin(monkeypatch)
    assert client.get(f"{URL}/propuestas?limit=0").status_code == 422
    assert client.get(f"{URL}/propuestas?limit=201").status_code == 422
    assert client.get(f"{URL}/propuestas?offset=-1").status_code == 422
    assert client.get(f"{URL}/propuestas?regla=GEMELO_VACIO&estado=PROPUESTA&limit=200&offset=10").status_code == 200
    assert recibido == {"regla": "GEMELO_VACIO", "estado": "PROPUESTA", "limit": 200, "offset": 10}


def test_aplicar_devuelve_aplicados_y_rechazados_y_encola(monkeypatch, commits, encolados):
    async def _aplicar(_s, ids, usuario):
        assert (list(ids), usuario) == ([1, 2, 3], "admin")
        return {"aplicados": [1, 2], "rechazados": [{"id": 3, "motivo": "estado_invalido"}]}

    async def _alcances(_s, ids):
        assert list(ids) == [1, 2]
        return {"SERVICIOS": [10], "ODFS": [20, 21]}

    monkeypatch.setattr(motor, "aplicar_manual", _aplicar)
    monkeypatch.setattr(evaluaciones, "alcances_de_propuestas", _alcances)
    client = _cliente_admin(monkeypatch)
    res = client.post(f"{URL}/propuestas/aplicar", json={"ids": [1, 2, 3]})
    assert res.status_code == 200
    assert res.json() == {
        "ok": True, "aplicados": [1, 2], "rechazados": [{"id": 3, "motivo": "estado_invalido"}]
    }
    assert commits == [1]
    assert [(e["alcance"], e["disparo"]) for e in encolados] == [
        ({"tipo": "SERVICIOS", "ids": [10]}, "VIEWER"),
        ({"tipo": "ODFS", "ids": [20, 21]}, "VIEWER"),
    ]
    assert client.post(f"{URL}/propuestas/aplicar", json={"ids": []}).status_code == 422
    assert client.post(f"{URL}/propuestas/aplicar", json={"ids": list(range(501))}).status_code == 422


def test_rechazar_no_encola(monkeypatch, commits, encolados):
    async def _rechazar(_s, ids, usuario):
        return {"rechazados": [1], "omitidos": []}

    monkeypatch.setattr(motor, "rechazar", _rechazar)
    res = _cliente_admin(monkeypatch).post(f"{URL}/propuestas/rechazar", json={"ids": [1]})
    assert res.status_code == 200
    assert res.json() == {"ok": True, "rechazados": [1], "omitidos": []}
    assert commits == [1] and encolados == []


def test_revertir_encola_y_falla_de_encolado_no_cambia_respuesta(monkeypatch, commits):
    async def _revertir(_s, ids, usuario):
        return {"revertidos": [5], "omitidos": []}

    async def _alcances(_s, ids):
        return {"BOTELLAS": [7]}

    async def _explota(*a, **k):
        raise RuntimeError("redis caído")

    monkeypatch.setattr(motor, "revertir_manual", _revertir)
    monkeypatch.setattr(evaluaciones, "alcances_de_propuestas", _alcances)
    monkeypatch.setattr(cola, "encolar_evaluacion", _explota)
    res = _cliente_admin(monkeypatch).post(f"{URL}/propuestas/revertir", json={"ids": [5]})
    assert res.status_code == 200
    assert res.json() == {"ok": True, "revertidos": [5], "omitidos": []}


def test_reglas_get(monkeypatch, commits):
    async def _precision(_s):
        return [{"codigo": "GEMELO_VACIO"}]

    monkeypatch.setattr(motor, "precision_por_regla", _precision)
    res = _cliente_admin(monkeypatch).get(f"{URL}/reglas")
    assert res.status_code == 200 and res.json() == {"reglas": [{"codigo": "GEMELO_VACIO"}]}


def test_reglas_post_valor_invalido_422(monkeypatch, commits):
    async def _actualizar(_s, codigo, **kw):
        raise ValueError("Umbral inválido: 500")

    monkeypatch.setattr(motor, "actualizar_regla", _actualizar)
    res = _cliente_admin(monkeypatch).post(
        f"{URL}/reglas",
        json={"codigo": "GEMELO_VACIO", "modo": "AUTO", "umbral": 500, "presupuesto_por_corrida": 5},
    )
    assert res.status_code == 422
    assert "Umbral" in res.json()["error"]
    assert commits == []


def test_reglas_post_ok_commit(monkeypatch, commits):
    llamado: dict[str, Any] = {}

    async def _actualizar(_s, codigo, **kw):
        llamado.update(codigo=codigo, **kw)

    monkeypatch.setattr(motor, "actualizar_regla", _actualizar)
    res = _cliente_admin(monkeypatch).post(
        f"{URL}/reglas",
        json={"codigo": "GEMELO_VACIO", "modo": "SOMBRA", "umbral": 80, "presupuesto_por_corrida": 5},
    )
    assert res.status_code == 200 and commits == [1]
    assert llamado == {
        "codigo": "GEMELO_VACIO", "modo": "SOMBRA", "umbral": 80,
        "presupuesto_por_corrida": 5, "usuario": "admin",
    }


def test_normalizar_crea_evaluacion_encola_y_202(monkeypatch, commits, encolados):
    async def _crear(_s, usuario, reglas):
        assert (usuario, reglas) == ("admin", ["GEMELO_VACIO"])
        return 42, None

    monkeypatch.setattr(evaluaciones, "crear_evaluacion_normalizador", _crear)
    res = _cliente_admin(monkeypatch).post(f"{URL}/normalizar", json={"reglas": ["GEMELO_VACIO"]})
    assert res.status_code == 202
    assert res.json() == {"evaluacion_id": 42}
    assert commits == [1]
    assert encolados == [
        {"alcance": {"tipo": "TODO", "ids": []}, "disparo": "NORMALIZADOR", "motivo": "manual:admin",
         "evaluacion_id": 42, "reglas": ["GEMELO_VACIO"]}
    ]


def test_normalizar_con_otra_en_curso_409(monkeypatch, commits, encolados):
    async def _crear(_s, usuario, reglas):
        return None, 41

    monkeypatch.setattr(evaluaciones, "crear_evaluacion_normalizador", _crear)
    res = _cliente_admin(monkeypatch).post(f"{URL}/normalizar", json={})
    assert res.status_code == 409
    assert res.json()["evaluacion_id"] == 41
    assert commits == [] and encolados == []


def test_normalizar_regla_inexistente_422(monkeypatch, commits, encolados):
    async def _crear(*a, **k):
        raise AssertionError("no debe crear")

    monkeypatch.setattr(evaluaciones, "crear_evaluacion_normalizador", _crear)
    res = _cliente_admin(monkeypatch).post(f"{URL}/normalizar", json={"reglas": ["NO_EXISTE"]})
    assert res.status_code == 422
    assert "NO_EXISTE" in res.json()["error"]
    assert encolados == []


def test_evaluaciones_devuelve_en_curso(monkeypatch, commits):
    recibido: dict[str, Any] = {}

    async def _listar(_s, limit):
        recibido["limit"] = limit
        return {"items": [{"id": 9, "estado": "EN_CURSO"}], "en_curso": 9}

    monkeypatch.setattr(evaluaciones, "listar_evaluaciones", _listar)
    client = _cliente_admin(monkeypatch)
    res = client.get(f"{URL}/evaluaciones")
    assert res.status_code == 200
    assert res.json() == {"items": [{"id": 9, "estado": "EN_CURSO"}], "en_curso": 9}
    assert recibido["limit"] == 10
    assert client.get(f"{URL}/evaluaciones?limit=51").status_code == 422
    assert client.get(f"{URL}/evaluaciones?limit=0").status_code == 422
