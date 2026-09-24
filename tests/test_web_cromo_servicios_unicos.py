# Nombre de archivo: test_web_cromo_servicios_unicos.py
# Ubicación de archivo: tests/test_web_cromo_servicios_unicos.py
# Descripción: Tests de las 4 rutas REST de servicios únicos por cable/buffer, resolución de cable y refresco PROV on-demand (Task 10)

"""Task 10 del plan "Corrección ingresos + Servicios" (2026-09-23).

Mismo patrón que `tests/test_web_cromo_verificador.py` (`_Cur`/`_Conn`/`_connect_user_ok`/`_login`/
`_SesionFake`/`_fake_async_session_local`) — copiado, no factorizado (~18 copias de ese patrón en
el repo, factorizarlo está fuera de alcance de esta tarea).

Dos gotchas de matching por substring propios de este archivo (ninguno de los otros archivos de
test de Cromo los pisa, porque ninguno ejercita las dos consultas nuevas a la vez):

1. `servicios_unicos_por_cable`/`_por_tubo` (Task 1) devuelven una fila por SERVICIO (agregada con
   `GROUP BY s.id`), a diferencia de `servicios_por_cable`/`_por_tubo` (una fila por PELO) — la
   consulta real tiene `WHERE p.cable_n_id = :cable_n_id\\n    GROUP BY s.id` (con el salto de línea
   y la indentación exactos del `text()` multilínea de `verificador.py`), así que ese es el
   substring que hay que matchear para no confundirla con la versión por-pelo del otro archivo.
2. Esta ruta consulta `app.servicios_sync_prov` DOS veces con formas distintas: la propia
   (`_frescura_por_servicio`, en `web/app/main.py`) pide `servicio_id, ultima_sincronizacion_ok` por
   `ANY(:ids)` — usa el substring `"ultima_sincronizacion_ok FROM app.servicios_sync_prov"` — y la
   de Task 7 (`servicios_vencidos`, `core/services/prov/frescura.py`) hace un `unnest(:ids
   ::integer[])` + `LEFT JOIN` para devolver sólo el subconjunto vencido — usa el substring
   `"FROM unnest(:ids ::integer[])"`. Ambas tocan la misma tabla (`app.servicios_sync_prov`
   aparece en las dos), así que un substring genérico tipo `"servicios_sync_prov"` a secas
   matchearía las dos consultas con la MISMA respuesta enlatada — confirmado con `repr(str(...))`
   de las dos antes de escribir estos tests.

El POST `/refrescar-prov` NO ejercita `_ejecutar_refresco_prov_lote` de verdad (esa función reusa
`_priorizar_por_antiguedad`/`_refrescar_un_servicio` de
`modules/slack_baneo_notifier/refresco_prov.py`, que abren sus propias sesiones reales y llaman a
PROV — ya cubiertas por `tests/test_slack_refresco_prov.py` contra Postgres real): se monkeypatchea
`web.app.main._ejecutar_refresco_prov_lote` directamente, mismo criterio que
`_cliente_cromo_fake` en `test_web_cromo_verificador.py` (mockear en el límite del servicio, no
pelear con el protocolo real de PROV/Slack en un test de ruta HTTP).
"""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient  # type: ignore

from core.password import hash_password
from web.app import main as web_main
from web.app.main import _ResultadoRefrescoLote, app


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


def _connect_user_ok(password: str = "userpass"):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):
        return _Conn((pwd_hash, "user"))

    return _connect


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["csrf"]


class _ResultadoFilas:
    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None

    def scalar_one(self):
        # `count(*)` real siempre devuelve exactamente una fila — el fallback a 0 acá es sólo una
        # comodidad de test (evita tener que enlatar la respuesta en every test que toca
        # `_resolver_buffer_por_numero` pero no le importa el conteo).
        return self._filas[0][0] if self._filas else 0


class _SesionFake:
    """Matchea por substring de la consulta compilada, igual que en test_web_cromo_verificador.py."""

    def __init__(
        self,
        respuestas: Optional[dict[str, list[tuple]]] = None,
        existentes: Optional[dict[tuple[type, Any], Any]] = None,
    ) -> None:
        self._respuestas = respuestas or {}
        self._existentes = existentes or {}

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            texto = str(stmt)
        for clave, filas in self._respuestas.items():
            if clave in texto:
                return _ResultadoFilas(filas)
        return _ResultadoFilas([])

    async def get(self, modelo_cls: type, pk: Any) -> Any:
        return self._existentes.get((modelo_cls, pk))


def _fake_async_session_local(sesion: _SesionFake):
    class _CM:
        async def __aenter__(self):
            return sesion

        async def __aexit__(self, *a):
            return False

    def factory():
        return _CM()

    return factory


def _fake_async_session_local_secuencia(sesiones: list[_SesionFake]):
    """Igual que `_fake_async_session_local`, pero devuelve una `_SesionFake` DISTINTA en cada
    `async with AsyncSessionLocal()` sucesivo — el POST `/refrescar-prov` abre dos sesiones
    (lectura inicial + vencidos, después re-lectura tras el refresco) y necesita poder simular un
    estado "antes"/"después" distinto en cada una."""

    iterador = iter(sesiones)

    class _CM:
        def __init__(self, sesion: _SesionFake) -> None:
            self._sesion = sesion

        async def __aenter__(self):
            return self._sesion

        async def __aexit__(self, *a):
            return False

    def factory():
        return _CM(next(iterador))

    return factory


# Fila de `_COLUMNAS_SERVICIO_UNICO` (`core/services/cromo/verificador.py`): s.id, s.servicio_id,
# s.numero_primer_servicio, s.nombre_cliente, s.cliente, s.estado_servicio, s.tipo_servicio,
# pelos_n_ids, cantidad_pelos, numeros_en_pelo, metodos.
_FILA_SERVICIO_UNICO = (
    501,
    "SRV-001",
    "SRV-001",
    "Cliente Uno",
    "Cliente Uno SA",
    "ACTIVO",
    "CORPORATIVO",
    [9001],
    1,
    ["1234"],
    ["REGEX_EXACTO"],
)

_SQL_UNICOS_POR_CABLE = "WHERE p.cable_n_id = :cable_n_id\n    GROUP BY s.id"
_SQL_UNICOS_POR_TUBO = "WHERE p.tubo_n_id = :tubo_n_id\n    GROUP BY s.id"
_SQL_FRESCURA_BATCH = "ultima_sincronizacion_ok FROM app.servicios_sync_prov"
_SQL_VENCIDOS_BATCH = "FROM unnest(:ids ::integer[])"
_SQL_TUBO_POR_ORDEN = "cromo_tubos WHERE cable_n_id = :cable_n_id AND vigente = true AND orden"
_SQL_CONTAR_BUFFERS = "count(*) FROM app.cromo_tubos WHERE cable_n_id"
_SQL_CABLE_POR_N_ID = "AND n_id = :n_id"
_SQL_CABLE_POR_NOMBRE = "lower(nombre) = lower(:nombre)"


# ── 401 sin sesión — confirma que las 4 rutas quedaron realmente cableadas ───────────────────────


def test_por_cable_requiere_autenticacion():
    client = TestClient(app)
    res = client.get("/api/infra/cromo/cables/51/servicios-unicos")
    assert res.status_code == 401


def test_por_buffer_requiere_autenticacion():
    client = TestClient(app)
    res = client.get("/api/infra/cromo/cables/51/buffers/1/servicios-unicos")
    assert res.status_code == 401


def test_resolver_requiere_autenticacion():
    client = TestClient(app)
    res = client.get("/api/infra/cromo/cables/resolver", params={"q": "F-VFL-IND"})
    assert res.status_code == 401


def test_refrescar_prov_requiere_autenticacion():
    client = TestClient(app)
    res = client.post("/api/infra/cromo/cables/51/servicios-unicos/refrescar-prov", json={})
    assert res.status_code == 401


# ── GET /api/infra/cromo/cables/{n_id}/servicios-unicos ──────────────────────────────────────────


def test_por_cable_404_si_no_existe(monkeypatch):
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake()))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/999/servicios-unicos")
    assert res.status_code == 404
    assert res.json()["codigo"] == "NO_ENCONTRADO"


def test_por_cable_happy_path_con_frescura(monkeypatch):
    from db.models.cromo import CromoCable

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    ahora = datetime.now(timezone.utc)
    vieja = ahora - timedelta(hours=100)  # > 48h default -> vencida
    fresca = ahora - timedelta(hours=1)  # < 48h default -> no vencida

    fila_vencida = _FILA_SERVICIO_UNICO
    fila_fresca = (
        502,
        "SRV-002",
        "SRV-002",
        "Cliente Dos",
        "Cliente Dos SA",
        "ACTIVO",
        "RESIDENCIAL",
        [9002, 9003],
        2,
        ["5678"],
        ["REGEX_EXACTO"],
    )
    cable = CromoCable(n_id=51, nombre="Cable Troncal", capacidad="72-BRUG", vigente=True)
    sesion = _SesionFake(
        respuestas={
            _SQL_UNICOS_POR_CABLE: [fila_vencida, fila_fresca],
            _SQL_FRESCURA_BATCH: [(501, vieja), (502, fresca)],
        },
        existentes={(CromoCable, 51): cable},
    )
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/51/servicios-unicos")
    assert res.status_code == 200
    payload = res.json()
    assert payload["cable_n_id"] == 51
    assert payload["cable_nombre"] == "Cable Troncal"
    assert payload["buffer"] is None
    assert payload["refresco_prov"] == {"estado": "no_solicitado", "fallidos": []}
    assert len(payload["servicios"]) == 2

    por_id = {s["servicio_id"]: s for s in payload["servicios"]}
    assert por_id[501]["frescura"]["vencida"] is True
    assert por_id[501]["cantidad_pelos"] == 1
    assert por_id[501]["pelos_n_ids"] == [9001]
    assert por_id[502]["frescura"]["vencida"] is False
    assert por_id[502]["pelos_n_ids"] == [9002, 9003]


def test_por_cable_servicio_nunca_sincronizado_es_vencido(monkeypatch):
    """Sin fila en `servicios_sync_prov` (nunca sincronizó) -> vencida, mismo criterio que la
    consulta de frescura de Task 7 (`IS NULL OR ... < corte`)."""
    from db.models.cromo import CromoCable

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    cable = CromoCable(n_id=51, nombre="Cable Troncal", capacidad="72-BRUG", vigente=True)
    sesion = _SesionFake(
        respuestas={_SQL_UNICOS_POR_CABLE: [_FILA_SERVICIO_UNICO]},
        existentes={(CromoCable, 51): cable},
    )
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/51/servicios-unicos")
    assert res.status_code == 200
    payload = res.json()
    servicio = payload["servicios"][0]
    assert servicio["frescura"]["vencida"] is True
    assert servicio["frescura"]["ultima_sincronizacion_prov"] is None
    assert servicio["frescura"]["antiguedad_horas"] is None


# ── GET /api/infra/cromo/cables/{n_id}/buffers/{numero}/servicios-unicos ─────────────────────────


def test_por_buffer_404_buffer_inexistente_incluye_total_buffers(monkeypatch):
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(respuestas={_SQL_CONTAR_BUFFERS: [(3,)]})
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/51/buffers/9/servicios-unicos")
    assert res.status_code == 404
    payload = res.json()
    assert payload["codigo"] == "NO_ENCONTRADO"
    assert payload["total_buffers"] == 3


def test_por_buffer_happy_path(monkeypatch):
    from db.models.cromo import CromoCable

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    cable = CromoCable(n_id=51, nombre="Cable Troncal", capacidad="72-BRUG", vigente=True)
    sesion = _SesionFake(
        respuestas={
            _SQL_TUBO_POR_ORDEN: [(129001, 2, "AZUL")],
            _SQL_UNICOS_POR_TUBO: [_FILA_SERVICIO_UNICO],
        },
        existentes={(CromoCable, 51): cable},
    )
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/51/buffers/3/servicios-unicos")
    assert res.status_code == 200
    payload = res.json()
    assert payload["cable_nombre"] == "Cable Troncal"
    assert payload["buffer"] == {"numero": 3, "orden": 2, "nombre_color": "AZUL"}
    assert len(payload["servicios"]) == 1
    assert payload["servicios"][0]["servicio_id_externo"] == "SRV-001"


def test_por_buffer_con_fila_propia_pero_sin_pelos_no_es_404(monkeypatch):
    """El tubo existe de verdad en `cromo_tubos` (se resuelve por fila propia) pero no tiene ningún
    pelo cargado todavía -- `servicios_unicos_por_tubo` levantaría `ObjetoNoEncontrado` en ese caso
    (su propio criterio de "no encontrado" es tolerante a la fila de TUBO faltante, no al revés);
    la ruta debe devolver 200 con `servicios: []`, no propagar un 404 espurio."""
    from db.models.cromo import CromoCable

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    cable = CromoCable(n_id=51, nombre="Cable Troncal", capacidad="72-BRUG", vigente=True)
    sesion = _SesionFake(
        respuestas={_SQL_TUBO_POR_ORDEN: [(129001, 2, "AZUL")]},
        existentes={(CromoCable, 51): cable},
    )
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/51/buffers/3/servicios-unicos")
    assert res.status_code == 200
    payload = res.json()
    assert payload["servicios"] == []
    assert payload["buffer"] == {"numero": 3, "orden": 2, "nombre_color": "AZUL"}


# ── GET /api/infra/cromo/cables/resolver ─────────────────────────────────────────────────────────


def test_resolver_por_n_id_happy_path(monkeypatch):
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(respuestas={_SQL_CABLE_POR_N_ID: [(10260935, "F-LEM-11-A", "48-BRUG")]})
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/resolver", params={"q": "10260935"})
    assert res.status_code == 200
    assert res.json() == {"n_id": 10260935, "nombre": "F-LEM-11-A", "capacidad": "48-BRUG"}


def test_resolver_por_nombre_no_encontrado(monkeypatch):
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake()))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/resolver", params={"q": "F-NO-EXISTE"})
    assert res.status_code == 404
    assert res.json()["codigo"] == "NO_ENCONTRADO"


def test_resolver_por_nombre_ambiguo(monkeypatch):
    """Los dos pares de nombres duplicados reales conocidos del brief ("F-ALV-2335"/"F-LEM-11-A")
    son exactamente este caso: 2+ cables vigentes con el mismo nombre."""
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(
        respuestas={
            _SQL_CABLE_POR_NOMBRE: [
                (10260935, "F-LEM-11-A", "48-BRUG"),
                (9498169, "F-LEM-11-A", "24-BRUG"),
            ]
        }
    )
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/resolver", params={"q": "F-LEM-11-A"})
    assert res.status_code == 409
    payload = res.json()
    assert payload["codigo"] == "AMBIGUO"
    assert {c["n_id"] for c in payload["candidatos"]} == {10260935, 9498169}


# ── POST /api/infra/cromo/cables/{n_id}/servicios-unicos/refrescar-prov ──────────────────────────


def test_refrescar_prov_csrf_invalido(monkeypatch):
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake()))
    monkeypatch.setenv("TESTING", "false")

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.post(
        "/api/infra/cromo/cables/51/servicios-unicos/refrescar-prov",
        json={"csrf_token": "invalido"},
    )
    assert res.status_code == 403


def test_refrescar_prov_404_si_cable_no_existe(monkeypatch):
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake()))
    monkeypatch.setenv("TESTING", "false")

    client = TestClient(app)
    csrf = _login(client, "user", "userpass")

    res = client.post(
        "/api/infra/cromo/cables/999/servicios-unicos/refrescar-prov",
        json={"csrf_token": csrf},
    )
    assert res.status_code == 404
    assert res.json()["codigo"] == "NO_ENCONTRADO"


def test_refrescar_prov_sin_vencidos_no_dispara_el_lote(monkeypatch):
    """Ningún servicio vencido -> `refresco_prov.estado == "sin_vencidos"` y
    `_ejecutar_refresco_prov_lote` ni se llama (no hay nada que refrescar)."""
    from db.models.cromo import CromoCable

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setenv("TESTING", "false")

    ahora = datetime.now(timezone.utc)
    fresca = ahora - timedelta(hours=1)
    cable = CromoCable(n_id=51, nombre="Cable Troncal", capacidad="72-BRUG", vigente=True)

    sesiones = [
        _SesionFake(
            respuestas={
                _SQL_UNICOS_POR_CABLE: [_FILA_SERVICIO_UNICO],
                _SQL_VENCIDOS_BATCH: [],  # ninguno vencido
            }
        ),
        _SesionFake(
            respuestas={
                _SQL_UNICOS_POR_CABLE: [_FILA_SERVICIO_UNICO],
                _SQL_FRESCURA_BATCH: [(501, fresca)],
            },
            existentes={(CromoCable, 51): cable},
        ),
    ]
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local_secuencia(sesiones))

    lote_fake = AsyncMock(side_effect=AssertionError("no debería llamarse: no hay vencidos"))
    monkeypatch.setattr(web_main, "_ejecutar_refresco_prov_lote", lote_fake)

    client = TestClient(app)
    csrf = _login(client, "user", "userpass")

    res = client.post(
        "/api/infra/cromo/cables/51/servicios-unicos/refrescar-prov",
        json={"csrf_token": csrf},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["refresco_prov"] == {"estado": "sin_vencidos", "fallidos": []}
    lote_fake.assert_not_awaited()


def test_refrescar_prov_con_vencidos_completado(monkeypatch):
    from db.models.cromo import CromoCable

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setenv("TESTING", "false")

    ahora = datetime.now(timezone.utc)
    nueva = ahora - timedelta(hours=1)
    cable = CromoCable(n_id=51, nombre="Cable Troncal", capacidad="72-BRUG", vigente=True)

    sesiones = [
        _SesionFake(
            respuestas={
                _SQL_UNICOS_POR_CABLE: [_FILA_SERVICIO_UNICO],
                _SQL_VENCIDOS_BATCH: [(501,)],
            }
        ),
        _SesionFake(
            respuestas={
                _SQL_UNICOS_POR_CABLE: [_FILA_SERVICIO_UNICO],
                _SQL_FRESCURA_BATCH: [(501, nueva)],
            },
            existentes={(CromoCable, 51): cable},
        ),
    ]
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local_secuencia(sesiones))

    lote_fake = AsyncMock(return_value=_ResultadoRefrescoLote(fallidos=[]))
    monkeypatch.setattr(web_main, "_ejecutar_refresco_prov_lote", lote_fake)

    client = TestClient(app)
    csrf = _login(client, "user", "userpass")

    res = client.post(
        "/api/infra/cromo/cables/51/servicios-unicos/refrescar-prov",
        json={"csrf_token": csrf},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["refresco_prov"] == {"estado": "completado", "fallidos": []}
    lote_fake.assert_awaited_once()
    (pendientes_llamados,), _kwargs = lote_fake.call_args
    assert [s.servicio_id for s in pendientes_llamados] == [501]


def test_refrescar_prov_con_fallidos_es_parcial(monkeypatch):
    from db.models.cromo import CromoCable

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setenv("TESTING", "false")

    cable = CromoCable(n_id=51, nombre="Cable Troncal", capacidad="72-BRUG", vigente=True)
    sesiones = [
        _SesionFake(
            respuestas={
                _SQL_UNICOS_POR_CABLE: [_FILA_SERVICIO_UNICO],
                _SQL_VENCIDOS_BATCH: [(501,)],
            }
        ),
        _SesionFake(
            respuestas={_SQL_UNICOS_POR_CABLE: [_FILA_SERVICIO_UNICO]},
            existentes={(CromoCable, 51): cable},
        ),
    ]
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local_secuencia(sesiones))

    fallidos = [{"servicio_id_externo": "SRV-001", "motivo": "timeout o error de comunicación con PROV"}]
    lote_fake = AsyncMock(return_value=_ResultadoRefrescoLote(fallidos=fallidos))
    monkeypatch.setattr(web_main, "_ejecutar_refresco_prov_lote", lote_fake)

    client = TestClient(app)
    csrf = _login(client, "user", "userpass")

    res = client.post(
        "/api/infra/cromo/cables/51/servicios-unicos/refrescar-prov",
        json={"csrf_token": csrf},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["refresco_prov"]["estado"] == "parcial"
    assert payload["refresco_prov"]["fallidos"] == fallidos


def test_refrescar_prov_502_si_prov_no_configurado(monkeypatch):
    from core.services.prov.config import ProvConfigError

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setenv("TESTING", "false")

    sesion = _SesionFake(
        respuestas={
            _SQL_UNICOS_POR_CABLE: [_FILA_SERVICIO_UNICO],
            _SQL_VENCIDOS_BATCH: [(501,)],
        }
    )
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    lote_fake = AsyncMock(side_effect=ProvConfigError("falta configurar PROV_BASE_URL"))
    monkeypatch.setattr(web_main, "_ejecutar_refresco_prov_lote", lote_fake)

    client = TestClient(app)
    csrf = _login(client, "user", "userpass")

    res = client.post(
        "/api/infra/cromo/cables/51/servicios-unicos/refrescar-prov",
        json={"csrf_token": csrf},
    )
    assert res.status_code == 502
