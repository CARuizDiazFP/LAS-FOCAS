# Nombre de archivo: test_web_cromo_servicios_sin_odf.py
# Ubicación de archivo: tests/test_web_cromo_servicios_sin_odf.py
# Descripción: Pruebas de wiring (auth/admin/CSRF/serialización) de los 3 endpoints del gestor "Servicios sin ODF" — sin DB real

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

from fastapi.testclient import TestClient  # type: ignore

from core.password import hash_password
from web.app.main import app


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


def _connect_user_ok(password: str = "userpass"):
    return _connect_ok(password, "user")


def _connect_admin_ok(password: str = "adminpass"):
    return _connect_ok(password, "admin")


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["csrf"]


def _fake_async_session_local():
    """Contexto `async with AsyncSessionLocal() as sesion:` fake — mismo patrón de
    test_web_cromo_repoblar_cables.py/test_web_botellas_admin.py. La sesión en sí nunca se toca de
    verdad: todo lo que la usa (`_obtener_servicio_categorizado`, `_senal_direccion_contra_odf`, y
    las funciones de servicio de Cromo) está mockeado en cada test."""

    class _CM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *a):
            return False

    def factory():
        return _CM()

    return factory


BASE_LISTADO = "/api/admin/infra/servicios-odf/listado"


def _url_sugerencia(servicio_id: int) -> str:
    return f"/api/admin/infra/servicios-odf/{servicio_id}/sugerencia"


def _url_asociar(servicio_id: int) -> str:
    return f"/api/admin/infra/servicios-odf/{servicio_id}/asociar"


# ── GET listado ──────────────────────────────────────────────────────────


def test_listado_requiere_autenticacion():
    client = TestClient(app)
    res = client.get(BASE_LISTADO)
    assert res.status_code == 401


def test_listado_requiere_admin(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get(BASE_LISTADO)
    assert res.status_code == 403


def test_listado_400_offset_negativo(monkeypatch):
    from web.app import main as web_main
    import core.services.cromo.servicios_sin_odf as servicios_sin_odf

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local())

    async def _fake_listar(sesion, *, limit, offset, categoria, q):
        raise ValueError(f"offset no puede ser negativo: {offset}")

    monkeypatch.setattr(servicios_sin_odf, "listar_servicios_sin_odf", _fake_listar)

    client = TestClient(app)
    _login(client, "admin", "adminpass")

    res = client.get(BASE_LISTADO, params={"offset": -1})
    assert res.status_code == 400


def test_listado_400_categoria_desconocida(monkeypatch):
    from web.app import main as web_main
    import core.services.cromo.servicios_sin_odf as servicios_sin_odf

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local())

    async def _fake_listar(sesion, *, limit, offset, categoria, q):
        raise ValueError(f"categoria desconocida: {categoria!r}")

    monkeypatch.setattr(servicios_sin_odf, "listar_servicios_sin_odf", _fake_listar)

    client = TestClient(app)
    _login(client, "admin", "adminpass")

    res = client.get(BASE_LISTADO, params={"categoria": "NO_EXISTE"})
    assert res.status_code == 400


def test_listado_serializa_items_con_ambos_extremos_e_indice(monkeypatch):
    from web.app import main as web_main
    import core.services.cromo.servicios_sin_odf as servicios_sin_odf

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local())

    item = servicios_sin_odf.ServicioSinOdf(
        id=101,
        servicio_id="61943",
        numero_primer_servicio="61943",
        nombre_cliente="Banco Comafi SA",
        categoria_causa=servicios_sin_odf.CATEGORIA_OLT_PON_COMPARTIDO,
        subcategoria=None,
        nodo="OLT2_Pilar",
        equipo="OLT2_Pilar",
        extremos=[
            servicios_sin_odf.ExtremoUltimaMilla(extremo=1, nodo="SW_Frontera", equipo="SW1"),
            servicios_sin_odf.ExtremoUltimaMilla(extremo=2, nodo="OLT2_Pilar", equipo="OLT2_Pilar"),
        ],
        indice_extremo_categorizado=1,
    )
    resultado = servicios_sin_odf.ResultadoListadoSinOdf(total=1, limit=50, offset=0, items=[item])

    async def _fake_listar(sesion, *, limit, offset, categoria, q):
        return resultado

    monkeypatch.setattr(servicios_sin_odf, "listar_servicios_sin_odf", _fake_listar)

    client = TestClient(app)
    _login(client, "admin", "adminpass")

    res = client.get(BASE_LISTADO)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    fila = body["items"][0]
    assert fila["id"] == 101
    assert fila["servicio_id"] == "61943"
    assert fila["categoria_causa"] == "OLT_PON_COMPARTIDO"
    assert fila["subcategoria"] is None
    assert len(fila["extremos"]) == 2, "el listado tiene que exponer AMBOS extremos, no sólo el ganador"
    assert fila["extremos"][0] == {"extremo": 1, "nodo": "SW_Frontera", "equipo": "SW1"}
    assert fila["extremos"][1] == {"extremo": 2, "nodo": "OLT2_Pilar", "equipo": "OLT2_Pilar"}
    assert fila["indice_extremo_categorizado"] == 1


# ── GET sugerencia ───────────────────────────────────────────────────────


def test_sugerencia_requiere_autenticacion():
    client = TestClient(app)
    res = client.get(_url_sugerencia(101))
    assert res.status_code == 401


def test_sugerencia_no_requiere_admin(monkeypatch):
    """Sólo lectura/informativo: alcanza con estar autenticado, mismo criterio que
    odfs/{id}/conectores. Se prueba con un 404 (servicio inexistente) para confirmar que no se
    cortó antes por falta de rol admin (sería un 403)."""
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local())

    async def _fake_detalle(sesion, servicio_id):
        return None

    monkeypatch.setattr(web_main, "_obtener_servicio_categorizado", _fake_detalle)

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get(_url_sugerencia(999))
    assert res.status_code == 404


def test_sugerencia_404_si_no_existe(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local())

    async def _fake_detalle(sesion, servicio_id):
        return None

    monkeypatch.setattr(web_main, "_obtener_servicio_categorizado", _fake_detalle)

    client = TestClient(app)
    _login(client, "admin", "adminpass")

    res = client.get(_url_sugerencia(999))
    assert res.status_code == 404


def test_sugerencia_incluye_ambos_extremos_sugerencia_y_senal(monkeypatch):
    from web.app import main as web_main
    import core.services.cromo.servicios_sin_odf as servicios_sin_odf
    from core.services.cromo.direccion_comparacion import SenalDireccion

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local())

    servicio_fake = SimpleNamespace(
        id=101, servicio_id="61943", nombre_cliente="Banco Comafi SA", direccion="AV MITRE 2525"
    )
    extremos_fake = [
        SimpleNamespace(extremo=1, nodo="SW_Frontera", equipo="SW1"),
        SimpleNamespace(extremo=2, nodo="OLT2_Pilar", equipo="OLT2_Pilar"),
    ]

    async def _fake_detalle(sesion, servicio_id):
        assert servicio_id == 101
        return {
            "servicio": servicio_fake,
            "extremos": extremos_fake,
            "categoria_causa": servicios_sin_odf.CATEGORIA_OLT_PON_COMPARTIDO,
            "subcategoria": None,
            "indice_extremo_categorizado": 1,
        }

    monkeypatch.setattr(web_main, "_obtener_servicio_categorizado", _fake_detalle)

    async def _fake_sugerencia(sesion, servicio_id):
        return servicios_sin_odf.SugerenciaOdf(odf_n_id=555, nombre="ODF Pilar")

    monkeypatch.setattr(servicios_sin_odf, "sugerencia_odf_para_servicio", _fake_sugerencia)

    async def _fake_senal(sesion, direccion_prov, odf_n_id):
        assert direccion_prov == "AV MITRE 2525"
        assert odf_n_id == 555
        return SenalDireccion.COINCIDE

    monkeypatch.setattr(web_main, "_senal_direccion_contra_odf", _fake_senal)

    client = TestClient(app)
    _login(client, "admin", "adminpass")

    res = client.get(_url_sugerencia(101))
    assert res.status_code == 200
    body = res.json()
    assert body["categoria_causa"] == "OLT_PON_COMPARTIDO"
    assert body["direccion"] == "AV MITRE 2525"
    assert len(body["extremos"]) == 2, "el detalle tiene que exponer AMBOS extremos"
    assert body["extremos"] == [
        {"extremo": 1, "nodo": "SW_Frontera", "equipo": "SW1"},
        {"extremo": 2, "nodo": "OLT2_Pilar", "equipo": "OLT2_Pilar"},
    ]
    assert body["indice_extremo_categorizado"] == 1
    assert body["sugerencia"] == {"odf_n_id": 555, "nombre": "ODF Pilar"}
    assert body["senal_direccion"] == "coincide"


def test_sugerencia_sin_olt_no_ofrece_sugerencia(monkeypatch):
    """Categoría distinta de OLT_PON_COMPARTIDO: nunca llama a sugerencia_odf_para_servicio (no
    aplica), y la respuesta trae sugerencia/senal_direccion en None."""
    from web.app import main as web_main
    import core.services.cromo.servicios_sin_odf as servicios_sin_odf

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local())

    servicio_fake = SimpleNamespace(id=202, servicio_id="70000", nombre_cliente="Cliente X", direccion=None)

    async def _fake_detalle(sesion, servicio_id):
        return {
            "servicio": servicio_fake,
            "extremos": [SimpleNamespace(extremo=1, nodo="CLI_Casa", equipo="ONT1")],
            "categoria_causa": servicios_sin_odf.CATEGORIA_EQUIPO_DOMICILIO_CLIENTE,
            "subcategoria": None,
            "indice_extremo_categorizado": 0,
        }

    monkeypatch.setattr(web_main, "_obtener_servicio_categorizado", _fake_detalle)

    llamado = {"sugerencia": False}

    async def _fake_sugerencia(sesion, servicio_id):
        llamado["sugerencia"] = True
        return None

    monkeypatch.setattr(servicios_sin_odf, "sugerencia_odf_para_servicio", _fake_sugerencia)

    client = TestClient(app)
    _login(client, "admin", "adminpass")

    res = client.get(_url_sugerencia(202))
    assert res.status_code == 200
    body = res.json()
    assert body["sugerencia"] is None
    assert body["senal_direccion"] is None
    assert llamado["sugerencia"] is False, "no debe pedir sugerencia fuera de OLT_PON_COMPARTIDO"


# ── POST asociar ─────────────────────────────────────────────────────────


def test_asociar_requiere_autenticacion():
    client = TestClient(app)
    res = client.post(_url_asociar(101), json={"odf_n_id": 555})
    assert res.status_code == 401


def test_asociar_requiere_admin(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.post(_url_asociar(101), json={"odf_n_id": 555})
    assert res.status_code == 403


def test_asociar_csrf_invalido_403(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setenv("TESTING", "false")  # ver nota en test_web_botellas_admin.py
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    client = TestClient(app)
    _login(client, "admin", "adminpass")

    res = client.post(_url_asociar(101), json={"odf_n_id": 555, "csrf_token": "invalido"})
    assert res.status_code == 403


def test_asociar_404_si_servicio_no_existe(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local())

    async def _fake_detalle(sesion, servicio_id):
        return None

    monkeypatch.setattr(web_main, "_obtener_servicio_categorizado", _fake_detalle)

    client = TestClient(app)
    csrf = _login(client, "admin", "adminpass")

    res = client.post(_url_asociar(999), json={"odf_n_id": 555, "csrf_token": csrf})
    assert res.status_code == 404


def test_asociar_404_si_odf_no_existe(monkeypatch):
    """crear_override levanta ObjetoNoEncontrado si la ODF no tiene fila propia en cromo_odfs —
    tiene que mapear a 404, nunca explotar a 500."""
    from web.app import main as web_main
    import core.services.cromo.servicios_sin_odf as servicios_sin_odf
    import core.services.cromo.servicio_odf_override_service as override_service
    from core.services.cromo.direccion_comparacion import SenalDireccion

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local())

    servicio_fake = SimpleNamespace(id=101, servicio_id="61943", nombre_cliente="X", direccion="X 1")

    async def _fake_detalle(sesion, servicio_id):
        return {
            "servicio": servicio_fake,
            "extremos": [],
            "categoria_causa": servicios_sin_odf.CATEGORIA_OLT_PON_COMPARTIDO,
            "subcategoria": None,
            "indice_extremo_categorizado": None,
        }

    monkeypatch.setattr(web_main, "_obtener_servicio_categorizado", _fake_detalle)

    async def _fake_senal(sesion, direccion_prov, odf_n_id):
        return SenalDireccion.NO_SE_PUDO_COMPARAR

    monkeypatch.setattr(web_main, "_senal_direccion_contra_odf", _fake_senal)

    async def _fake_crear_override(sesion, **kwargs):
        raise override_service.ObjetoNoEncontrado("No existe un ODF con n_id=999999.")

    monkeypatch.setattr(override_service, "crear_override", _fake_crear_override)

    client = TestClient(app)
    csrf = _login(client, "admin", "adminpass")

    res = client.post(_url_asociar(101), json={"odf_n_id": 999999, "csrf_token": csrf})
    assert res.status_code == 404


def test_asociar_ok_recalcula_senal_contra_odf_del_body(monkeypatch):
    """El backend recalcula senal_direccion contra la ODF REALMENTE elegida en el body, no confía
    en lo que mandó el frontend (que puede haber elegido otra distinta a la sugerida) — y un
    no_coincide no bloquea la asociación."""
    from web.app import main as web_main
    import core.services.cromo.servicios_sin_odf as servicios_sin_odf
    import core.services.cromo.servicio_odf_override_service as override_service
    from core.services.cromo.direccion_comparacion import SenalDireccion

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local())

    servicio_fake = SimpleNamespace(id=101, servicio_id="61943", nombre_cliente="X", direccion="AV MITRE 2525")

    async def _fake_detalle(sesion, servicio_id):
        return {
            "servicio": servicio_fake,
            "extremos": [],
            "categoria_causa": servicios_sin_odf.CATEGORIA_OLT_PON_COMPARTIDO,
            "subcategoria": None,
            "indice_extremo_categorizado": None,
        }

    monkeypatch.setattr(web_main, "_obtener_servicio_categorizado", _fake_detalle)

    llamada_senal = {}

    async def _fake_senal(sesion, direccion_prov, odf_n_id):
        llamada_senal["direccion_prov"] = direccion_prov
        llamada_senal["odf_n_id"] = odf_n_id
        return SenalDireccion.NO_COINCIDE

    monkeypatch.setattr(web_main, "_senal_direccion_contra_odf", _fake_senal)

    llamada_override = {}

    async def _fake_crear_override(sesion, **kwargs):
        llamada_override.update(kwargs)
        return SimpleNamespace(id=1, **kwargs)

    monkeypatch.setattr(override_service, "crear_override", _fake_crear_override)

    client = TestClient(app)
    csrf = _login(client, "admin", "adminpass")

    res = client.post(
        _url_asociar(101),
        json={"odf_n_id": 777, "pelo_n_id": 42, "notas": "confirmado a mano", "csrf_token": csrf},
    )
    assert res.status_code == 200
    body = res.json()
    assert body == {"ok": True, "categoria_causa": "OLT_PON_COMPARTIDO", "senal_direccion": "no_coincide"}
    assert llamada_senal == {"direccion_prov": "AV MITRE 2525", "odf_n_id": 777}
    assert llamada_override["servicio_id"] == 101
    assert llamada_override["odf_n_id"] == 777
    assert llamada_override["pelo_n_id"] == 42
    assert llamada_override["notas"] == "confirmado a mano"
    assert llamada_override["usuario"] == "admin"
    assert llamada_override["senal_direccion"] == SenalDireccion.NO_COINCIDE
