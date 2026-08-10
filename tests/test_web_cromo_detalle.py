# Nombre de archivo: test_web_cromo_detalle.py
# Ubicación de archivo: tests/test_web_cromo_detalle.py
# Descripción: Pruebas del endpoint de detalle jerárquico de un cable Cromo (auth, 404, serialización), sin red ni DB real

from __future__ import annotations

from typing import Any, Optional

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


def _connect_user_ok(password: str = "userpass"):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):
        return _Conn((pwd_hash, "user"))

    return _connect


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["csrf"]


def test_detalle_cable_requiere_autenticacion():
    client = TestClient(app)
    res = client.get("/api/infra/cromo/cables/51/detalle")
    assert res.status_code == 401


def test_detalle_cable_no_requiere_admin(monkeypatch):
    """Consulta de sólo lectura, mismo criterio que el verificador/inventario — alcanza con estar
    autenticado, no hace falta rol admin."""
    from web.app import main as web_main
    from core.services.cromo import detalle as cromo_detalle

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())

    async def _obtener_detalle_cable_fake(sesion, n_id):
        return cromo_detalle.DetalleCable(
            n_id=n_id,
            nombre="Cable Troncal 1",
            capacidad="72-BRUG",
            capacidad_pelos=72,
            jerarquia="Troncal",
            propietario="SBASE",
            tendido="Aereo",
            distancia_geo=None,
            distancia_real=None,
            id_legacy=None,
            notas=None,
            extremo_a_n_id=68001,
            extremo_a_clase=69,
            extremo_a_legacy=None,
            extremo_a_nombre="Botella A",
            extremo_b_n_id=68002,
            extremo_b_clase=69,
            extremo_b_legacy=None,
            extremo_b_nombre="Botella B",
            vigente=True,
            tubos=[],
        )

    monkeypatch.setattr(cromo_detalle, "obtener_detalle_cable", _obtener_detalle_cable_fake)

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/51/detalle")
    assert res.status_code == 200
    body = res.json()
    assert body["n_id"] == 51
    assert body["nombre"] == "Cable Troncal 1"
    assert body["extremo_a"] == {"n_id": 68001, "clase": 69, "legacy": None, "nombre": "Botella A"}
    assert body["extremo_b"] == {"n_id": 68002, "clase": 69, "legacy": None, "nombre": "Botella B"}
    assert body["tubos"] == []


def test_detalle_cable_no_encontrado_404(monkeypatch):
    from web.app import main as web_main
    from core.services.cromo import detalle as cromo_detalle
    from core.services.cromo.verificador import ObjetoNoEncontrado

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())

    async def _obtener_detalle_cable_fake(sesion, n_id):
        raise ObjetoNoEncontrado(f"No existe un cable con n_id={n_id} en el inventario ingerido.")

    monkeypatch.setattr(cromo_detalle, "obtener_detalle_cable", _obtener_detalle_cable_fake)

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/999/detalle")
    assert res.status_code == 404


def test_detalle_cable_serializa_tubos_pelos_y_distancia(monkeypatch):
    """Cubre el caso de `Decimal` en distancia_geo/distancia_real (no serializable por JSONResponse
    sin castear a float explícito) y el anidado tubos[].pelos[].servicios[]."""
    from decimal import Decimal

    from web.app import main as web_main
    from core.services.cromo import detalle as cromo_detalle
    from core.services.cromo.verificador import ServicioEncontrado

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())

    async def _obtener_detalle_cable_fake(sesion, n_id):
        pelo = cromo_detalle.PeloDetalle(
            n_id=9001,
            tubo_n_id=129001,
            numero_pelo="1",
            orden=1,
            color="AZUL",
            tipo_asociacion="CLIENTE",
            servicio_raw="FO 1234 - CLIENTE",
            servicio_numero="1234",
            vigente=True,
            servicios=[
                ServicioEncontrado(
                    servicio_id=501,
                    servicio_id_externo="SRV-001",
                    numero_primer_servicio="SRV-001",
                    nombre_cliente="Cliente Uno",
                    cliente="Cliente Uno SA",
                    estado_servicio="ACTIVO",
                    categoria=1,
                    tipo_servicio="CORPORATIVO",
                    pelo_n_id=9001,
                    servicio_numero_match="1234",
                    metodo="REGEX_EXACTO",
                )
            ],
        )
        tubo = cromo_detalle.TuboDetalle(
            n_id=129001, orden=1, nombre_color="AZUL", vigente=True, tiene_fila_propia=True, pelos=[pelo]
        )
        return cromo_detalle.DetalleCable(
            n_id=n_id,
            nombre="Cable Troncal 1",
            capacidad="72-BRUG",
            capacidad_pelos=72,
            jerarquia="Troncal",
            propietario="SBASE",
            tendido="Aereo",
            distancia_geo=Decimal("123.45"),
            distancia_real=Decimal("130.00"),
            id_legacy=None,
            notas=None,
            extremo_a_n_id=68001,
            extremo_a_clase=69,
            extremo_a_legacy=None,
            extremo_a_nombre="Botella A",
            extremo_b_n_id=68002,
            extremo_b_clase=69,
            extremo_b_legacy=None,
            extremo_b_nombre="Botella B",
            vigente=True,
            tubos=[tubo],
        )

    monkeypatch.setattr(cromo_detalle, "obtener_detalle_cable", _obtener_detalle_cable_fake)

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/51/detalle")
    assert res.status_code == 200
    body = res.json()
    assert body["distancia_geo"] == 123.45
    assert body["distancia_real"] == 130.0
    assert len(body["tubos"]) == 1
    assert body["tubos"][0]["tiene_fila_propia"] is True
    assert len(body["tubos"][0]["pelos"]) == 1
    servicios = body["tubos"][0]["pelos"][0]["servicios"]
    assert len(servicios) == 1
    assert servicios[0]["servicio_id_externo"] == "SRV-001"
