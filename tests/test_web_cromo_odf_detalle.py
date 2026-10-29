# Nombre de archivo: test_web_cromo_odf_detalle.py
# Ubicación de archivo: tests/test_web_cromo_odf_detalle.py
# Descripción: Pruebas del endpoint de detalle de un ODF Cromo (auth, 404, serialización), sin red ni DB real

from __future__ import annotations


from fastapi.testclient import TestClient  # type: ignore

from tests.soporte_login import connect_user_ok, login
from web.app.main import app


def test_detalle_odf_requiere_autenticacion():
    client = TestClient(app)
    res = client.get("/api/infra/cromo/odfs/901/detalle")
    assert res.status_code == 401


def test_detalle_odf_no_requiere_admin(monkeypatch):
    """Consulta de sólo lectura, mismo criterio que el detalle de cable — alcanza con estar
    autenticado, no hace falta rol admin."""
    from web.app import main as web_main
    from core.services.cromo import odf_detalle as cromo_odf_detalle

    monkeypatch.setattr(web_main.psycopg, "connect", connect_user_ok())

    async def _obtener_detalle_odf_fake(sesion, n_id):
        return cromo_odf_detalle.DetalleOdf(
            n_id=n_id,
            nombre="ODF Calle 9 Nro 593 PILAR",
            tipo_elemento="ODF",
            propietario="Metrotel",
            codigo_modelo=None,
            id_legacy=None,
            notas=None,
            calle="Calle 9",
            altura="593",
            localidad="PILAR",
            provincia="Buenos Aires",
            ubicacion_fisica=None,
            tendido=None,
            latitud=None,
            longitud=None,
            vigente=True,
            cables_asociados=[{"n_id": 111, "nombre": "Cable A"}],
            odfs_en_la_misma_direccion=[{"n_id": 902, "nombre": "ODF Calle 9 Nro 595 PILAR"}],
        )

    monkeypatch.setattr(cromo_odf_detalle, "obtener_detalle_odf", _obtener_detalle_odf_fake)

    client = TestClient(app)
    login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/odfs/901/detalle")
    assert res.status_code == 200
    body = res.json()
    assert body["n_id"] == 901
    assert body["nombre"] == "ODF Calle 9 Nro 593 PILAR"
    assert body["tipo_elemento"] == "ODF"
    assert body["calle"] == "Calle 9"
    assert body["cables_asociados"] == [{"n_id": 111, "nombre": "Cable A"}]
    assert body["odfs_en_la_misma_direccion"] == [{"n_id": 902, "nombre": "ODF Calle 9 Nro 595 PILAR"}]


def test_detalle_odf_no_encontrado_404(monkeypatch):
    from web.app import main as web_main
    from core.services.cromo import odf_detalle as cromo_odf_detalle
    from core.services.cromo.verificador import ObjetoNoEncontrado

    monkeypatch.setattr(web_main.psycopg, "connect", connect_user_ok())

    async def _obtener_detalle_odf_fake(sesion, n_id):
        raise ObjetoNoEncontrado(f"No existe un ODF con n_id={n_id} en el inventario ingerido.")

    monkeypatch.setattr(cromo_odf_detalle, "obtener_detalle_odf", _obtener_detalle_odf_fake)

    client = TestClient(app)
    login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/odfs/999/detalle")
    assert res.status_code == 404


def test_detalle_odf_sin_cables_ni_vecinos(monkeypatch):
    """Estado degradado esperado (no un error): ODF sin `cables_asociados` poblados y sin ningún
    vecino de dirección conocido."""
    from web.app import main as web_main
    from core.services.cromo import odf_detalle as cromo_odf_detalle

    monkeypatch.setattr(web_main.psycopg, "connect", connect_user_ok())

    async def _obtener_detalle_odf_fake(sesion, n_id):
        return cromo_odf_detalle.DetalleOdf(
            n_id=n_id,
            nombre="ODF sin dirección",
            tipo_elemento="SIN_CLASIFICAR",
            propietario=None,
            codigo_modelo=None,
            id_legacy=None,
            notas=None,
            calle=None,
            altura=None,
            localidad=None,
            provincia=None,
            ubicacion_fisica=None,
            tendido=None,
            latitud=None,
            longitud=None,
            vigente=True,
            cables_asociados=[],
            odfs_en_la_misma_direccion=[],
        )

    monkeypatch.setattr(cromo_odf_detalle, "obtener_detalle_odf", _obtener_detalle_odf_fake)

    client = TestClient(app)
    login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/odfs/903/detalle")
    assert res.status_code == 200
    body = res.json()
    assert body["cables_asociados"] == []
    assert body["odfs_en_la_misma_direccion"] == []
