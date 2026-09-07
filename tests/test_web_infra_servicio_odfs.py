# Nombre de archivo: test_web_infra_servicio_odfs.py
# Ubicación de archivo: tests/test_web_infra_servicio_odfs.py
# Descripción: Tests del endpoint GET /api/infra/servicios/{servicio_id}/odfs (Task 7):
# ODFs/empalmes del archivo de tracking de ruta de un servicio, para la vista de
# Detalle de Servicio. Sistema independiente del submódulo Cromo Red — la fuente es
# `RutaServicio.raw_file_content` parseado en vivo con `core.parsers.tracking_parser`,
# nunca la columna persistida `Empalme.es_transito` (no confiable, ver docstring del
# endpoint en web/app/main.py).

from types import SimpleNamespace
from typing import Any, Optional

from fastapi.testclient import TestClient

from core.password import hash_password
from db.models.infra import RutaTipo


from web.app.main import app  # type: ignore  # noqa: E402


# Fixture de tracking: una línea de terminal ODF al inicio y al final (para poblar
# terminal_a/terminal_b), un empalme de tránsito ("ODF ..."), un tramo con dB, un
# empalme simple ("CAMARA ...") y otro tramo con dB.
RAW_TRACKING_FIXTURE = "\n".join(
    [
        "O-1000-1: 5",
        "Empalme 10: ODF Retiro Bandeja 1",
        "F-CABLE-A: enlace 5.2 dB",
        "Empalme 20: CAMARA Belgrano",
        "F-CABLE-B: enlace 3.1 dB",
        "O-2000-2: 8",
    ]
)


def _connect_ok(role: str, password: str):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):  # type: ignore
        class _Cur:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=None):
                pass

            def fetchone(self):
                return (pwd_hash, role)

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return _Cur()

            def commit(self):
                pass

        return _Conn()

    return _connect


def _login(client: TestClient, monkeypatch, *, role: str = "user", password: str = "secret") -> str:
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_ok(role, password))
    response = client.post(
        "/api/auth/login",
        json={"username": role, "password": password},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    return data["csrf"]


class _SessionScope:
    """Replica el patrón `with SessionLocal() as session:` usado en web/app/main.py."""

    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeQueryChain:
    """Query fake encadenable: soporta .filter()/.options()/.first()/.all()."""

    def __init__(self, *, one: Any = None, many: Optional[list[Any]] = None):
        self._one = one
        self._many = many if many is not None else []

    def filter(self, *args, **kwargs):
        return self

    def options(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._one

    def all(self):
        return list(self._many)


class _ServicioOdfsSession:
    """Sesión fake que distingue explícitamente entre la query de `Servicio` y la de
    `Empalme` (el endpoint hace dos queries distintas) — nunca deja que un solo mock
    de `session.query(...).filter(...)` sirva para ambas sin quererlo: dispatch por
    nombre de entidad, igual que `_InfraDetailSession` en test_web_infra_camera_state.py.
    """

    def __init__(self, servicio: Any, empalmes_db: Optional[list[Any]] = None):
        self._servicio = servicio
        self._empalmes_db = empalmes_db or []
        self.empalme_query_called = False

    def query(self, *entities):
        entity = entities[0]
        entity_name = getattr(entity, "__name__", "")
        if entity_name == "Servicio":
            return _FakeQueryChain(one=self._servicio)
        if entity_name == "Empalme":
            self.empalme_query_called = True
            return _FakeQueryChain(many=self._empalmes_db)
        raise AssertionError(f"Query inesperada para entidad {entity_name!r}")

    def commit(self):
        pass

    def rollback(self):
        pass


def _build_ruta(
    *,
    ruta_id: int = 1,
    nombre: str = "Principal",
    tipo: RutaTipo = RutaTipo.PRINCIPAL,
    activa: bool = True,
    raw_file_content: Optional[str] = RAW_TRACKING_FIXTURE,
    nombre_archivo_origen: Optional[str] = "FO SRV-1.txt",
) -> Any:
    return SimpleNamespace(
        id=ruta_id,
        nombre=nombre,
        tipo=tipo,
        activa=activa,
        raw_file_content=raw_file_content,
        nombre_archivo_origen=nombre_archivo_origen,
    )


def _build_servicio(servicio_id: str, rutas: list[Any]) -> Any:
    return SimpleNamespace(servicio_id=servicio_id, rutas=rutas)


def _build_empalme_db(tracking_empalme_id: str, *, camara_id: int, camara_nombre: str, estado: str) -> Any:
    camara = SimpleNamespace(id=camara_id, nombre=camara_nombre, estado=SimpleNamespace(value=estado))
    return SimpleNamespace(tracking_empalme_id=tracking_empalme_id, camara=camara)


def _patch_session(monkeypatch, session):
    from db import session as db_session

    monkeypatch.setattr(db_session, "SessionLocal", _SessionScope(session))


def test_get_servicio_odfs_404_si_no_existe(monkeypatch):
    client = TestClient(app)
    _login(client, monkeypatch)

    fake_session = _ServicioOdfsSession(servicio=None)
    _patch_session(monkeypatch, fake_session)

    response = client.get("/api/infra/servicios/NO-EXISTE/odfs")

    assert response.status_code == 404
    assert response.json() == {"error": "Servicio NO-EXISTE no encontrado"}


def test_get_servicio_odfs_happy_path_transito_simple_y_enriquecimiento_camara(monkeypatch):
    client = TestClient(app)
    _login(client, monkeypatch)

    ruta = _build_ruta()
    servicio = _build_servicio("SRV-1", [ruta])
    empalme_db = _build_empalme_db("SRV-1_10", camara_id=4, camara_nombre="Camara Retiro", estado="LIBRE")

    fake_session = _ServicioOdfsSession(servicio=servicio, empalmes_db=[empalme_db])
    _patch_session(monkeypatch, fake_session)

    response = client.get("/api/infra/servicios/SRV-1/odfs")

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["servicio_id"] == "SRV-1"
    assert payload["total_odfs"] == 1
    assert payload["total_empalmes"] == 2
    assert len(payload["rutas"]) == 1

    ruta_payload = payload["rutas"][0]
    assert ruta_payload["ruta_id"] == 1
    assert ruta_payload["ruta_nombre"] == "Principal"
    assert ruta_payload["ruta_tipo"] == "PRINCIPAL"
    assert ruta_payload["activa"] is True
    assert ruta_payload["sin_tracking"] is False
    assert ruta_payload["terminal_a"] == {"odf_id": "O-1000-1", "conector": "5"}
    assert ruta_payload["terminal_b"] == {"odf_id": "O-2000-2", "conector": "8"}
    assert ruta_payload["transitos_count"] == 1
    assert ruta_payload["empalmes_count"] == 2

    empalmes = ruta_payload["empalmes"]
    assert len(empalmes) == 2

    transito, simple = empalmes
    assert transito["empalme_id"] == "10"
    assert transito["descripcion"] == "ODF Retiro Bandeja 1"
    assert transito["es_transito"] is True
    assert transito["camara_id"] == 4
    assert transito["camara_nombre"] == "Camara Retiro"
    assert transito["camara_estado"] == "LIBRE"

    assert simple["empalme_id"] == "20"
    assert simple["descripcion"] == "CAMARA Belgrano"
    assert simple["es_transito"] is False
    assert simple["camara_id"] is None
    assert simple["camara_nombre"] is None
    assert simple["camara_estado"] is None

    assert fake_session.empalme_query_called is True


def test_get_servicio_odfs_ruta_sin_tracking_no_lanza_excepcion(monkeypatch):
    client = TestClient(app)
    _login(client, monkeypatch)

    ruta = _build_ruta(raw_file_content=None, nombre_archivo_origen=None)
    servicio = _build_servicio("SRV-2", [ruta])

    fake_session = _ServicioOdfsSession(servicio=servicio, empalmes_db=[])
    _patch_session(monkeypatch, fake_session)

    response = client.get("/api/infra/servicios/SRV-2/odfs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_odfs"] == 0
    assert payload["total_empalmes"] == 0

    ruta_payload = payload["rutas"][0]
    assert ruta_payload["sin_tracking"] is True
    assert ruta_payload["empalmes"] == []
    # Sin raw_file_content no hay nada que parsear -> no se dispara la query batched
    # de Empalme (tracking_ids queda vacío).
    assert fake_session.empalme_query_called is False


def test_get_servicio_odfs_multiples_rutas_suman_totales(monkeypatch):
    client = TestClient(app)
    _login(client, monkeypatch)

    ruta_1 = _build_ruta(ruta_id=1, nombre="Principal", raw_file_content=RAW_TRACKING_FIXTURE)
    raw_ruta_2 = "\n".join(
        [
            "Empalme 30: ODF Backup Bandeja 2",
            "F-CABLE-C: enlace 2.0 dB",
        ]
    )
    ruta_2 = _build_ruta(
        ruta_id=2,
        nombre="Backup",
        tipo=RutaTipo.BACKUP,
        raw_file_content=raw_ruta_2,
        nombre_archivo_origen="FO SRV-3 backup.txt",
    )
    servicio = _build_servicio("SRV-3", [ruta_1, ruta_2])

    fake_session = _ServicioOdfsSession(servicio=servicio, empalmes_db=[])
    _patch_session(monkeypatch, fake_session)

    response = client.get("/api/infra/servicios/SRV-3/odfs")

    assert response.status_code == 200
    payload = response.json()

    # ruta_1: transitos_count=1, empalmes_count=2 | ruta_2: transitos_count=1, empalmes_count=1
    assert payload["total_odfs"] == 2
    assert payload["total_empalmes"] == 3
    assert len(payload["rutas"]) == 2

    nombres = {r["ruta_nombre"] for r in payload["rutas"]}
    assert nombres == {"Principal", "Backup"}

    ruta_2_payload = next(r for r in payload["rutas"] if r["ruta_nombre"] == "Backup")
    assert ruta_2_payload["ruta_tipo"] == "BACKUP"
    assert ruta_2_payload["empalmes_count"] == 1
    assert ruta_2_payload["transitos_count"] == 1
    assert ruta_2_payload["empalmes"][0]["camara_id"] is None


def test_get_servicio_odfs_no_duplica_odf_compartida_entre_rutas(monkeypatch):
    """Bug real (2026-08-31, ticket duplicidad Buscador/ODFs): dos rutas del mismo servicio
    ("Principal" y "Principal - Pelo 2", dos pelos del MISMO cable físico) suelen atravesar los
    MISMOS empalmes — antes de este fix, `total_odfs`/`total_empalmes` sumaban por-ruta y mostraban
    "4 ODF(s)" para sólo 2 ODFs físicas repetidas en ambas rutas (detectado por el usuario en
    pantalla). `empalme_id` es la identidad estable entre rutas del mismo servicio; los totales deben
    contar distintos, no ocurrencias."""

    client = TestClient(app)
    _login(client, monkeypatch)

    raw_pelo_1 = "\n".join(
        [
            "O-1234166-1: 18",
            "Empalme 6641368: Nodo Rack 30",
            "F-CABLE-A: enlace 5.2 dB",
            "Empalme 6642085: ODF Rack Netizen",
            "O-1238223-1: 15",
        ]
    )
    raw_pelo_2 = "\n".join(
        [
            "O-1234166-1: 2",
            "Empalme 6641368: Nodo Rack 30",
            "F-CABLE-A: enlace 5.2 dB",
            "Empalme 6642085: ODF Rack Netizen",
            "O-1238223-1: 16",
        ]
    )
    ruta_1 = _build_ruta(ruta_id=1, nombre="Principal", raw_file_content=raw_pelo_1)
    ruta_2 = _build_ruta(
        ruta_id=2,
        nombre="Principal - Pelo 2 (C2)",
        raw_file_content=raw_pelo_2,
        nombre_archivo_origen="FO SRV-5 C2.txt",
    )
    servicio = _build_servicio("SRV-5", [ruta_1, ruta_2])

    fake_session = _ServicioOdfsSession(servicio=servicio, empalmes_db=[])
    _patch_session(monkeypatch, fake_session)

    response = client.get("/api/infra/servicios/SRV-5/odfs")

    assert response.status_code == 200
    payload = response.json()

    # 2 empalmes físicos distintos (6641368, 6642085), ambos de tránsito (ODF) — repetidos en las 2
    # rutas porque es el mismo cable físico, no 4 entidades distintas.
    assert payload["total_odfs"] == 2
    assert payload["total_empalmes"] == 2
    assert len(payload["rutas"]) == 2
    for ruta_payload in payload["rutas"]:
        assert {e["empalme_id"] for e in ruta_payload["empalmes"]} == {"6641368", "6642085"}


def test_get_servicio_odfs_resuelve_por_numero_linea(monkeypatch):
    """El helper _find_servicio_por_identificador_web se reusa acá igual que en
    get_servicio_rutas_web: cualquier identificador flexible debería resolver, y como
    la sesión es fake (siempre devuelve el mismo `servicio` para la entidad Servicio
    sin importar el filtro real de SQLAlchemy), esto sólo confirma que el endpoint
    nuevo invoca el mismo camino de resolución sin romperse con un id no-numérico."""

    client = TestClient(app)
    _login(client, monkeypatch)

    ruta = _build_ruta(raw_file_content=None)
    servicio = _build_servicio("SRV-4", [ruta])

    fake_session = _ServicioOdfsSession(servicio=servicio, empalmes_db=[])
    _patch_session(monkeypatch, fake_session)

    response = client.get("/api/infra/servicios/numero-linea-cualquiera/odfs")

    assert response.status_code == 200
    assert response.json()["servicio_id"] == "SRV-4"
