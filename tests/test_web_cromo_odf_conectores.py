# Nombre de archivo: test_web_cromo_odf_conectores.py
# Ubicación de archivo: tests/test_web_cromo_odf_conectores.py
# Descripción: Pruebas del endpoint de conectores de una ODF Cromo (auth, 404, serialización), sin red ni DB real

from __future__ import annotations


from fastapi.testclient import TestClient  # type: ignore

from tests.soporte_login import connect_user_ok, login
from web.app.main import app


def test_conectores_odf_requiere_autenticacion():
    client = TestClient(app)
    res = client.get("/api/infra/cromo/odfs/6642085/conectores")
    assert res.status_code == 401


def test_conectores_odf_no_requiere_admin(monkeypatch):
    """Consulta de sólo lectura, mismo criterio que el resto de endpoints Cromo — alcanza con
    estar autenticado, no hace falta rol admin."""
    from web.app import main as web_main
    from core.services.cromo import odf_conectores as cromo_odf_conectores

    monkeypatch.setattr(web_main.psycopg, "connect", connect_user_ok())

    async def _conectores_de_odf_fake(sesion, odf_n_id):
        return cromo_odf_conectores.ResultadoConectoresOdf(
            odf_n_id=odf_n_id,
            odf_nombre="ODF Rack Netizen 5 de Julio 478 C.F.",
            conectores=[
                cromo_odf_conectores.ConectorOdfResuelto(
                    n_id=8539345,
                    bandeja_n_id=8539330,
                    bandeja_nombre="O-1238223-1",
                    numero_conector="15",
                    pelo_n_id=6777271,
                    pelo_numero="1",
                    servicio_resuelto="61943",
                    servicio_id_historico="41140",
                    servicio_id_externo="61943",
                    nombre_cliente="Banco Comafi SA",
                    cliente=None,
                    estado_servicio="Activo",
                )
            ],
        )

    monkeypatch.setattr(cromo_odf_conectores, "conectores_de_odf", _conectores_de_odf_fake)

    client = TestClient(app)
    login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/odfs/6642085/conectores")
    assert res.status_code == 200
    body = res.json()
    assert body["odf_n_id"] == 6642085
    assert body["odf_nombre"] == "ODF Rack Netizen 5 de Julio 478 C.F."
    assert len(body["conectores"]) == 1
    c = body["conectores"][0]
    assert c["bandeja_nombre"] == "O-1238223-1"
    assert c["numero_conector"] == "15"
    assert c["servicio_resuelto"] == "61943"
    assert c["servicio_id_historico"] == "41140"
    assert c["servicio_id_externo"] == "61943"
    assert c["nombre_cliente"] == "Banco Comafi SA"


def test_conectores_odf_no_encontrado_404(monkeypatch):
    from web.app import main as web_main
    from core.services.cromo import odf_conectores as cromo_odf_conectores

    monkeypatch.setattr(web_main.psycopg, "connect", connect_user_ok())

    async def _conectores_de_odf_fake(sesion, odf_n_id):
        raise cromo_odf_conectores.ObjetoNoEncontrado(f"No existe una ODF con n_id={odf_n_id}.")

    monkeypatch.setattr(cromo_odf_conectores, "conectores_de_odf", _conectores_de_odf_fake)

    client = TestClient(app)
    login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/odfs/999/conectores")
    assert res.status_code == 404
