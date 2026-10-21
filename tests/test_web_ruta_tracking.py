# Nombre de archivo: test_web_ruta_tracking.py
# Ubicación de archivo: tests/test_web_ruta_tracking.py
# Descripción: Caracterización de GET /api/infra/rutas/{ruta_id}/tracking: datos reales de dev y ramas con sesión simulada

"""Red de seguridad del refactor de `get_ruta_tracking`.

Dos grupos:
- Contra Postgres real (dev): los ids se eligen en tiempo de ejecución con un SELECT, porque los
  datos de dev cambian; las aserciones son de estructura y de coherencia con la base.
- Con sesión simulada (sin base): fijan cada rama del original (puntas, fallback por regex del ODF,
  JSON guardado, empalmes de la base, 500) con parches donde el nombre se LEE en tiempo de llamada
  (`db.session.SessionLocal` y `core.parsers.tracking_parser.parse_tracking`, ambos importados
  dentro de la función).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.soporte_postgres_real import requiere_postgres_real
from web.app.main import app

CLAVES = {"status", "ruta_id", "servicio_id", "ruta_nombre", "ruta_tipo", "tracking", "punta_a", "punta_b", "transitos_count"}
CLAVES_PUNTA = {"sitio", "identificador", "conector"}


@pytest.fixture
def cliente():
    with patch("web.app.routers.servicios._require_auth", return_value=("tester", "admin")):
        yield TestClient(app)


# --------------------------------------------------------------------------- datos reales de dev


def _ids_reales() -> dict[str, int | None]:
    from sqlalchemy import text

    from db.session import SessionLocal

    consultas = {
        "con_raw": "SELECT id FROM app.rutas_servicio WHERE coalesce(raw_file_content, '') <> '' ORDER BY id LIMIT 1",
        "solo_json": (
            "SELECT id FROM app.rutas_servicio WHERE coalesce(raw_file_content, '') = '' "
            "AND coalesce(contenido_original, '') <> '' ORDER BY id LIMIT 1"
        ),
        "solo_empalmes": (
            "SELECT r.id FROM app.rutas_servicio r WHERE coalesce(r.raw_file_content, '') = '' "
            "AND coalesce(r.contenido_original, '') = '' AND EXISTS "
            "(SELECT 1 FROM app.ruta_empalme_association a WHERE a.ruta_id = r.id) ORDER BY r.id LIMIT 1"
        ),
        "sin_empalmes": (
            "SELECT r.id FROM app.rutas_servicio r WHERE NOT EXISTS "
            "(SELECT 1 FROM app.ruta_empalme_association a WHERE a.ruta_id = r.id) ORDER BY r.id LIMIT 1"
        ),
        "inexistente": "SELECT coalesce(max(id), 0) + 1000 FROM app.rutas_servicio",
    }
    with SessionLocal() as sesion:
        return {k: sesion.execute(text(q)).scalar() for k, q in consultas.items()}


def _verificar_estructura(cuerpo: dict) -> None:
    assert set(cuerpo) == CLAVES
    assert cuerpo["status"] == "ok"
    assert isinstance(cuerpo["tracking"], list)
    for item in cuerpo["tracking"]:
        assert item["tipo"] in {"camara", "cable"}
        esperadas = {"tipo", "descripcion", "empalme_id"} if item["tipo"] == "camara" else {"tipo", "nombre", "atenuacion_db"}
        assert set(item) == esperadas
    for punta in (cuerpo["punta_a"], cuerpo["punta_b"]):
        assert punta is None or set(punta) == CLAVES_PUNTA


def _cantidad_empalmes_en_base(ruta_id: int) -> int:
    from sqlalchemy import text

    from db.session import SessionLocal

    with SessionLocal() as sesion:
        return sesion.execute(
            text("SELECT count(*) FROM app.ruta_empalme_association WHERE ruta_id = :r"), {"r": ruta_id}
        ).scalar()


@requiere_postgres_real
@pytest.mark.parametrize("categoria", ["con_raw", "solo_json", "solo_empalmes"])
def test_ruta_real_estructura_y_coherencia(cliente, categoria):
    ruta_id = _ids_reales()[categoria]
    if ruta_id is None:
        pytest.skip(f"dev no tiene una ruta de la categoría {categoria}")
    resp = cliente.get(f"/api/infra/rutas/{ruta_id}/tracking")
    assert resp.status_code == 200
    cuerpo = resp.json()
    _verificar_estructura(cuerpo)
    assert cuerpo["ruta_id"] == ruta_id
    assert cuerpo["ruta_tipo"] in {"PRINCIPAL", "BACKUP", "ALTERNATIVA"}
    if categoria == "con_raw":
        assert cuerpo["transitos_count"] is not None
        assert cuerpo["tracking"]
    else:
        assert cuerpo["transitos_count"] is None
    if categoria == "solo_empalmes":
        assert len(cuerpo["tracking"]) == _cantidad_empalmes_en_base(ruta_id)
        assert all(i["tipo"] == "camara" for i in cuerpo["tracking"])
        assert cuerpo["punta_a"] is None and cuerpo["punta_b"] is None


@requiere_postgres_real
def test_ruta_real_inexistente_da_404(cliente):
    ruta_id = _ids_reales()["inexistente"]
    resp = cliente.get(f"/api/infra/rutas/{ruta_id}/tracking")
    assert resp.status_code == 404
    assert resp.json() == {"error": "Ruta no encontrada"}


def test_sin_sesion_da_401():
    resp = TestClient(app).get("/api/infra/rutas/1/tracking")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- ramas con sesión simulada


def _ruta(**campos) -> SimpleNamespace:
    base = {
        "id": 7,
        "nombre": "Ruta 7",
        "tipo": SimpleNamespace(value="PRINCIPAL"),
        "servicio": SimpleNamespace(servicio_id="SRV-1"),
        "raw_file_content": None,
        "nombre_archivo_origen": None,
        "contenido_original": None,
        "empalmes": [],
    }
    base.update(campos)
    return SimpleNamespace(**base)


class _Sesion:
    def __init__(self, ruta):
        self._ruta = ruta

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, *_a):
        return self

    def filter(self, *_a):
        return self

    def first(self):
        return self._ruta


@contextmanager
def _con_ruta(ruta, parsed=None):
    with patch("db.session.SessionLocal", lambda: _Sesion(ruta)):
        if parsed is None:
            yield
        else:
            with patch("core.parsers.tracking_parser.parse_tracking", return_value=parsed):
                yield


def _punta(sitio="S", ident="I", conector="C"):
    return SimpleNamespace(sitio_descripcion=sitio, identificador_fisico=ident, pelo_conector=conector)


def _entrada(tipo, raw_line="", **campos):
    base = {"tipo": tipo, "raw_line": raw_line, "empalme_descripcion": None, "empalme_id": None,
            "cable_nombre": None, "atenuacion_db": None}
    base.update(campos)
    return SimpleNamespace(**base)


def _parsed(entries, punta_a=None, punta_b=None, transitos=3):
    return SimpleNamespace(entries=entries, punta_a=punta_a, punta_b=punta_b, transitos_count=transitos)


def _get(cliente, ruta, parsed=None):
    with _con_ruta(ruta, parsed):
        return cliente.get("/api/infra/rutas/7/tracking")


def test_raw_con_puntas_y_entradas_mixtas(cliente):
    parsed = _parsed(
        [
            _entrada("empalme", empalme_descripcion=None, empalme_id=11),
            _entrada("tramo", cable_nombre=None, atenuacion_db=0.5),
            _entrada("otro"),
            _entrada("empalme", empalme_descripcion="Cámara X", empalme_id=12),
            _entrada("tramo", cable_nombre="CBL-1", atenuacion_db=None),
        ],
        punta_a=_punta("A", None, "1"),
        punta_b=_punta(None, "ID-B", None),
        transitos=5,
    )
    resp = _get(cliente, _ruta(raw_file_content="x", nombre_archivo_origen=None), parsed)
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "ruta_id": 7,
        "servicio_id": "SRV-1",
        "ruta_nombre": "Ruta 7",
        "ruta_tipo": "PRINCIPAL",
        "tracking": [
            {"tipo": "camara", "descripcion": "", "empalme_id": 11},
            {"tipo": "cable", "nombre": "", "atenuacion_db": 0.5},
            {"tipo": "camara", "descripcion": "Cámara X", "empalme_id": 12},
            {"tipo": "cable", "nombre": "CBL-1", "atenuacion_db": None},
        ],
        "punta_a": {"sitio": "A", "identificador": "", "conector": "1"},
        "punta_b": {"sitio": "", "identificador": "ID-B", "conector": ""},
        "transitos_count": 5,
    }


def test_raw_pasa_nombre_de_archivo_vacio_si_es_none(cliente):
    parsed = _parsed([])
    with patch("db.session.SessionLocal", lambda: _Sesion(_ruta(raw_file_content="txt"))):
        with patch("core.parsers.tracking_parser.parse_tracking", return_value=parsed) as pt:
            cliente.get("/api/infra/rutas/7/tracking")
    pt.assert_called_once_with("txt", "")


def test_raw_puntas_por_regex_del_odf_primero_y_ultimo(cliente):
    parsed = _parsed(
        [
            _entrada("tramo", raw_line="sin odf", cable_nombre=None),
            _entrada("tramo", raw_line="x O-AB-12: 34 y", cable_nombre="C1"),
            _entrada("empalme", empalme_descripcion="E"),
            _entrada("tramo", raw_line="z O-ZZ-9: 7", cable_nombre="C2"),
        ]
    )
    cuerpo = _get(cliente, _ruta(raw_file_content="x"), parsed).json()
    assert cuerpo["punta_a"] == {"sitio": "O-AB-12", "identificador": "", "conector": "34"}
    assert cuerpo["punta_b"] == {"sitio": "O-ZZ-9", "identificador": "", "conector": "7"}


def test_raw_regex_corta_en_el_primer_tramo_con_cable_aunque_no_matchee(cliente):
    parsed = _parsed(
        [
            _entrada("tramo", raw_line="sin match", cable_nombre="C1"),
            _entrada("tramo", raw_line="O-AB-12: 34", cable_nombre="C2"),
        ],
        punta_b=_punta(),
    )
    cuerpo = _get(cliente, _ruta(raw_file_content="x"), parsed).json()
    assert cuerpo["punta_a"] is None
    assert cuerpo["punta_b"] == {"sitio": "S", "identificador": "I", "conector": "C"}


def test_raw_sin_entradas_cae_a_empalmes_de_la_base(cliente):
    empalmes = [
        SimpleNamespace(camara=SimpleNamespace(nombre="Cam1"), tracking_empalme_id=5),
        SimpleNamespace(camara=None, tracking_empalme_id=None),
    ]
    cuerpo = _get(cliente, _ruta(raw_file_content="x", empalmes=empalmes), _parsed([], transitos=2)).json()
    assert cuerpo["tracking"] == [
        {"tipo": "camara", "descripcion": "Cam1", "empalme_id": 5},
        {"tipo": "camara", "descripcion": "Sin cámara", "empalme_id": None},
    ]
    assert cuerpo["transitos_count"] == 2
    assert cuerpo["punta_a"] is None and cuerpo["punta_b"] is None


def test_json_guardado_con_puntas_y_entradas(cliente):
    contenido = json.dumps(
        {
            "punta_a": {"sitio_descripcion": "A"},
            "punta_b": {"identificador_fisico": "B", "pelo_conector": "9"},
            "entries": [
                {"tipo": "empalme", "empalme_id": 1},
                {"tipo": "tramo", "cable_nombre": "K", "atenuacion_db": 1.5},
                {"tipo": "tramo"},
                {"tipo": "otro"},
                {"tipo": "empalme", "empalme_descripcion": "D", "empalme_id": 2},
            ],
        }
    )
    cuerpo = _get(cliente, _ruta(contenido_original=contenido)).json()
    assert cuerpo["tracking"] == [
        {"tipo": "camara", "descripcion": "", "empalme_id": 1},
        {"tipo": "cable", "nombre": "K", "atenuacion_db": 1.5},
        {"tipo": "cable", "nombre": "", "atenuacion_db": None},
        {"tipo": "camara", "descripcion": "D", "empalme_id": 2},
    ]
    assert cuerpo["punta_a"] == {"sitio": "A", "identificador": "", "conector": ""}
    assert cuerpo["punta_b"] == {"sitio": "", "identificador": "B", "conector": "9"}
    assert cuerpo["transitos_count"] is None


def test_json_sin_puntas_ni_entradas_cae_a_empalmes(cliente):
    empalmes = [SimpleNamespace(camara=SimpleNamespace(nombre="C"), tracking_empalme_id=1)]
    cuerpo = _get(cliente, _ruta(contenido_original="{}", empalmes=empalmes)).json()
    assert cuerpo["tracking"] == [{"tipo": "camara", "descripcion": "C", "empalme_id": 1}]
    assert cuerpo["punta_a"] is None


def test_json_invalido_se_ignora_y_cae_a_empalmes(cliente):
    empalmes = [SimpleNamespace(camara=None, tracking_empalme_id=3)]
    resp = _get(cliente, _ruta(contenido_original="no es json", empalmes=empalmes))
    assert resp.status_code == 200
    assert resp.json()["tracking"] == [{"tipo": "camara", "descripcion": "Sin cámara", "empalme_id": 3}]


def test_raw_tiene_prioridad_sobre_json(cliente):
    parsed = _parsed([_entrada("empalme", empalme_descripcion="RAW")])
    ruta = _ruta(raw_file_content="x", contenido_original=json.dumps({"entries": [{"tipo": "empalme"}]}))
    assert _get(cliente, ruta, parsed).json()["tracking"][0]["descripcion"] == "RAW"


def test_sin_nada_devuelve_tracking_vacio(cliente):
    cuerpo = _get(cliente, _ruta()).json()
    assert cuerpo["tracking"] == []
    assert cuerpo["punta_a"] is None and cuerpo["punta_b"] is None and cuerpo["transitos_count"] is None


def test_ruta_inexistente_simulada_da_404(cliente):
    resp = _get(cliente, None)
    assert resp.status_code == 404
    assert resp.json() == {"error": "Ruta no encontrada"}


def test_error_inesperado_da_500_con_texto(cliente):
    resp = _get(cliente, _ruta(servicio=None))
    assert resp.status_code == 500
    assert resp.json()["error"].startswith("Error obteniendo tracking: ")
