# Nombre de archivo: test_web_cromo_camino_optico.py
# Ubicación de archivo: tests/test_web_cromo_camino_optico.py
# Descripción: Pruebas de wiring (auth/admin/códigos/serialización) de los 3 endpoints del camino óptico de Cromo — sin DB real ni red

from __future__ import annotations

from typing import Optional

from fastapi.testclient import TestClient  # type: ignore

from core.password import hash_password
from core.services.cromo.camino_optico_service import (
    ESTADO_OK,
    ESTADO_SIN_SEMILLA,
    CaminoOptico,
    ConsistenciaCamino,
    PeloAjenoAlServicio,
    PeloSemilla,
    ResultadoRegla,
)
from web.app.main import app

SERVICIO = 557


class _Cur:
    def __init__(self, row: Optional[tuple] = None) -> None:
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None) -> None:
        return None

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row: tuple) -> None:
        self.cur = _Cur(row)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cur

    def commit(self) -> None:
        return None


def _connect_ok(password: str, role: str):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):
        return _Conn((pwd_hash, role))

    return _connect


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["csrf"]


def _cliente_admin(monkeypatch) -> TestClient:
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_ok("adminpass", "admin"))
    client = TestClient(app)
    _login(client, "admin", "adminpass")
    return client


def _cliente_user(monkeypatch) -> TestClient:
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_ok("userpass", "user"))
    client = TestClient(app)
    _login(client, "user", "userpass")
    return client


def _fake_session(monkeypatch, *, existe: bool = True):
    """Sesión async fake: sólo tiene que responder al chequeo de existencia del Servicio."""
    from web.app import main as web_main

    class _CM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("db.session.AsyncSessionLocal", lambda: _CM())

    async def _existe(_sesion, _servicio_id):
        return existe

    monkeypatch.setattr(web_main, "_servicio_existe", _existe)


def _fake_cromo_client(monkeypatch):
    """`CromoClient` fake: nunca sale a la red. Los tests mockean el servicio, no el cliente."""

    class _Cliente:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("core.services.cromo.client.CromoClient", lambda config=None: _Cliente())
    monkeypatch.setattr("core.services.cromo.config.get_cromo_config", lambda: object())


def _semilla(pelo_n_id: int = 10006353) -> PeloSemilla:
    return PeloSemilla(
        pelo_n_id=pelo_n_id,
        servicio_numero="93154",
        metodo="REGEX_EXACTO",
        confianza=100,
        numero_pelo="4",
        color="MR",
        cable_n_id=10006296,
        cable_nombre="FD-980-B",
        tiene_conector_odf=False,
        servicio_raw="FO 93154 - ODF Guanahani 580",
    )


def _camino_ok() -> CaminoOptico:
    consistencia = ConsistenciaCamino(
        reglas=[
            ResultadoRegla(
                regla="PELO_CABLE",
                descripcion="Cable declarado para cada pelo del camino",
                total=98,
                coincide=94,
                discrepa=0,
                no_ingerido=4,
            )
        ]
    )
    return CaminoOptico(
        estado=ESTADO_OK,
        pelo_n_id=10006353,
        id_pedido=10006353,
        id_raiz=10006353,
        raiz_es_mismo_id=True,
        servicio_at62="93154",
        servicio_at61="FO 93154 - ODF Guanahani 580",
        numero_pelo="4",
        cable_nombre="FD-980-B",
        consistencia=consistencia,
        duracion_ms=10350,
    )


def _url_pelos(servicio_id: int = SERVICIO) -> str:
    return f"/api/infra/cromo/servicios/{servicio_id}/camino-optico/pelos"


def _url_txt(servicio_id: int = SERVICIO) -> str:
    return f"/api/infra/cromo/servicios/{servicio_id}/camino-optico/tracking.txt"


def _url_camino(servicio_id: int = SERVICIO) -> str:
    return f"/api/admin/infra/servicios-odf/{servicio_id}/camino-optico"


# ── GET .../camino-optico/pelos (semillas, sin tocar Cromo) ──────────────────


def test_pelos_requiere_autenticacion():
    assert TestClient(app).get(_url_pelos()).status_code == 401


def test_pelos_devuelve_las_semillas_serializadas(monkeypatch):
    _fake_session(monkeypatch)
    monkeypatch.setattr(
        "core.services.cromo.camino_optico_service.listar_pelos_semilla",
        lambda *a, **k: _semillas_async(),
    )
    client = _cliente_user(monkeypatch)

    res = client.get(_url_pelos())

    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["total"] == 1
    assert cuerpo["pelos"][0]["pelo_n_id"] == 10006353
    assert cuerpo["pelos"][0]["tiene_conector_odf"] is False


async def _semillas_async():
    return [_semilla()]


def test_pelos_404_si_el_servicio_no_existe(monkeypatch):
    _fake_session(monkeypatch, existe=False)
    client = _cliente_user(monkeypatch)

    assert client.get(_url_pelos(999999)).status_code == 404


def test_pelos_devuelve_lista_vacia_sin_semillas(monkeypatch):
    # Es el 77% de los Servicios del gestor: no es un error, es la respuesta correcta.
    _fake_session(monkeypatch)

    async def _vacio(*a, **k):
        return []

    monkeypatch.setattr(
        "core.services.cromo.camino_optico_service.listar_pelos_semilla", _vacio
    )
    client = _cliente_user(monkeypatch)

    res = client.get(_url_pelos())

    assert res.status_code == 200
    assert res.json() == {"servicio_id": SERVICIO, "total": 0, "pelos": []}


# ── GET .../camino-optico/tracking.txt ──────────────────────────────────────


def test_tracking_txt_requiere_autenticacion():
    assert TestClient(app).get(_url_txt()).status_code == 401


def test_tracking_txt_devuelve_el_archivo_con_content_disposition(monkeypatch):
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)

    async def _resolver(*a, **k):
        return _camino_ok(), [_semilla()]

    monkeypatch.setattr(
        "core.services.cromo.camino_optico_service.resolver_camino_de_servicio", _resolver
    )
    client = _cliente_user(monkeypatch)

    res = client.get(_url_txt())

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert 'filename="93154 CROMO.txt"' in res.headers["content-disposition"]
    assert "GENERADO desde Cromo" in res.text


def test_tracking_txt_409_sin_semilla_en_vez_de_un_archivo_vacio(monkeypatch):
    """Un `.txt` que dice "no hay datos" es basura en la carpeta de Descargas de alguien."""
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)

    async def _resolver(*a, **k):
        return CaminoOptico(estado=ESTADO_SIN_SEMILLA, motivo="sin pelos"), []

    monkeypatch.setattr(
        "core.services.cromo.camino_optico_service.resolver_camino_de_servicio", _resolver
    )
    client = _cliente_user(monkeypatch)

    res = client.get(_url_txt())

    assert res.status_code == 409
    assert res.json()["estado"] == ESTADO_SIN_SEMILLA


def test_tracking_txt_400_si_el_pelo_no_es_del_servicio(monkeypatch):
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)

    async def _resolver(*a, **k):
        raise PeloAjenoAlServicio("El pelo 1 no pertenece al Servicio 557.")

    monkeypatch.setattr(
        "core.services.cromo.camino_optico_service.resolver_camino_de_servicio", _resolver
    )
    client = _cliente_user(monkeypatch)

    res = client.get(_url_txt(), params={"pelo_n_id": 1})

    assert res.status_code == 400
    assert "no pertenece" in res.json()["error"]


def test_tracking_txt_502_si_cromo_no_responde(monkeypatch):
    from core.services.cromo.client import CromoClientError

    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)

    async def _resolver(*a, **k):
        raise CromoClientError("timeout")

    monkeypatch.setattr(
        "core.services.cromo.camino_optico_service.resolver_camino_de_servicio", _resolver
    )
    client = _cliente_user(monkeypatch)

    res = client.get(_url_txt())

    assert res.status_code == 502
    assert "Cromo no respondió" in res.json()["error"]


# ── GET .../servicios-odf/{id}/camino-optico (JSON + auditoría) ──────────────


def test_camino_requiere_autenticacion():
    assert TestClient(app).get(_url_camino()).status_code == 401


def test_camino_requiere_admin(monkeypatch):
    # Devuelve el recorrido entero (topología cable por cable) y gasta recursos del proveedor por
    # request: el mismo criterio ya escrito para `/sugerencia`.
    client = _cliente_user(monkeypatch)

    assert client.get(_url_camino()).status_code == 403


def test_camino_serializa_estado_estadisticas_y_consistencia(monkeypatch):
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)

    async def _resolver(*a, **k):
        return _camino_ok(), [_semilla()]

    monkeypatch.setattr(
        "core.services.cromo.camino_optico_service.resolver_camino_de_servicio", _resolver
    )
    client = _cliente_admin(monkeypatch)

    res = client.get(_url_camino())

    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["estado"] == ESTADO_OK
    assert cuerpo["identidad_cromo"]["raiz_es_mismo_id"] is True
    assert cuerpo["servicio_at62"] == "93154"
    assert cuerpo["semillas_disponibles"] == 1
    assert cuerpo["consistencia"]["reglas"][0]["regla"] == "PELO_CABLE"
    assert cuerpo["consistencia"]["total_no_ingerido"] == 4
    assert cuerpo["payload_raw"] is None  # sólo con ?raw=true


def test_camino_sin_semilla_responde_200_con_estado(monkeypatch):
    """`SIN_SEMILLA` es el caso del 77% de los Servicios del gestor: usar un código de error para
    el caso mayoritario y legítimo llena los logs de falsos incidentes."""
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)

    async def _resolver(*a, **k):
        return (
            CaminoOptico(estado=ESTADO_SIN_SEMILLA, motivo="El Servicio no tiene ningún pelo."),
            [],
        )

    monkeypatch.setattr(
        "core.services.cromo.camino_optico_service.resolver_camino_de_servicio", _resolver
    )
    client = _cliente_admin(monkeypatch)

    res = client.get(_url_camino())

    assert res.status_code == 200
    assert res.json()["estado"] == ESTADO_SIN_SEMILLA
    assert "no tiene ningún pelo" in res.json()["motivo"]


def test_camino_404_si_el_servicio_no_existe(monkeypatch):
    _fake_session(monkeypatch, existe=False)
    _fake_cromo_client(monkeypatch)
    client = _cliente_admin(monkeypatch)

    assert client.get(_url_camino(999999)).status_code == 404
