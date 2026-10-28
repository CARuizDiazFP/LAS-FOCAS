# Nombre de archivo: test_contrato_infra_web_api_real_db.py
# Ubicación de archivo: tests/test_contrato_infra_web_api_real_db.py
# Descripción: Contrato web/API de las rutas /api/infra duplicadas contra focas_dev, sólo caminos que no escriben (P12, Task 1)

"""Complemento de `test_contrato_infra_web_api.py`: los casos que consultan la base. Todos son de
sólo lectura o usan ids inexistentes (`ZZ-NO-EXISTE`, `999999999`), así que no escriben nada en
`focas_dev`. La API usa un engine async con `NullPool`: cada request del TestClient corre en su propio
event loop y el pool global quedaría atado a uno muerto."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.app.main import app as app_api
from db.session import SessionLocal, async_engine, get_async_db
from tests.soporte_postgres_real import requiere_postgres_real
from tests.test_contrato_infra_web_api import assert_forma, cliente_api, cliente_web

pytestmark = requiere_postgres_real

NONE = type(None)
INEXISTENTE = "ZZ-NO-EXISTE"
ID_INEXISTENTE = 999999999

# Cámara completa del panel (21 claves) y cámara de la API / de search del panel (9 claves).
CAMARA_BASE: dict = {
    "id": int, "nombre": str, "fontine_id": (str, NONE), "direccion": (str, NONE), "estado": str,
    "origen_datos": str, "latitud": (float, int, NONE), "longitud": (float, int, NONE), "servicios": list,
}
CAMARA_WEB_COMPLETA: dict = {
    **CAMARA_BASE,
    "rutas": list, "tiene_baneo_activo": bool, "tiene_ingreso_activo": bool, "inconsistente": bool,
    "estado_sugerido": str, "ticket_baneo": (str, NONE), "editable": bool, "incidentes_activos": list,
    "es_botella": bool, "camara_padre_id": (int, NONE), "camara_padre_nombre": (str, NONE),
    "botellas_count": int,
}
BAN_RESULTADO_CREAR: dict = {
    "success": bool, "incidente_id": (int, NONE), "camaras_baneadas": int, "camaras_ya_baneadas": int,
    "message": str, "error": (str, NONE), "camaras_afectadas": list,
}
BAN_RESULTADO_LEVANTAR: dict = {
    "success": bool, "incidente_id": (int, NONE), "camaras_restauradas": int,
    "camaras_mantenidas_baneadas": int, "message": str, "error": (str, NONE), "camaras_afectadas": list,
}
INCIDENTE_WEB: dict = {
    "id": int, "ticket_asociado": (str, NONE), "servicio_afectado_id": str, "servicio_protegido_id": str,
    "ruta_protegida_id": (int, NONE), "usuario_ejecutor": (str, NONE), "motivo": (str, NONE),
    "fecha_inicio": (str, NONE), "activo": bool, "duracion_horas": (float, int, NONE), "camaras_count": int,
    "camaras_baneadas_count": int,
}
RUTAS_SERVICIO: dict = {
    "status": str, "servicio_id": str, "servicio_db_id": int, "cliente": (str, NONE), "rutas": list,
    "total_rutas": int,
}
RUTA_ITEM: dict = {
    "id": int, "nombre": str, "tipo": str, "hash_contenido": (str, NONE), "empalmes_count": int,
    "activa": bool, "created_at": (str, NONE), "nombre_archivo_origen": (str, NONE),
}
CSV_NOMBRE = re.compile(r'attachment; filename="camaras_\d{8}_\d{6}\.csv"')


@pytest.fixture
def web(con_sesion):
    return cliente_web(con_sesion)


@pytest.fixture
def api():
    """Cliente de la API con la sesión async sobre un engine sin pool compartido entre loops."""
    engine = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
    fabrica = async_sessionmaker(engine, expire_on_commit=False)

    async def _sesion():
        async with fabrica() as session:
            yield session

    previo = app_api.dependency_overrides.get(get_async_db)
    app_api.dependency_overrides[get_async_db] = _sesion
    try:
        yield cliente_api()
    finally:
        if previo is None:
            app_api.dependency_overrides.pop(get_async_db, None)
        else:
            app_api.dependency_overrides[get_async_db] = previo


@pytest.fixture(scope="module")
def ruta_con_tracking() -> tuple[str, int]:
    """(servicio_id, ruta_id) reales de focas_dev con `raw_file_content`; salteado si no hay (SELECT puro)."""
    with SessionLocal() as session:
        fila = session.execute(text(
            "SELECT s.servicio_id, r.id FROM app.rutas_servicio r JOIN app.servicios s ON s.id = r.servicio_id "
            "WHERE r.raw_file_content IS NOT NULL AND r.raw_file_content <> '' ORDER BY r.id LIMIT 1"
        )).first()
    if fila is None:
        pytest.skip("focas_dev no tiene rutas con raw_file_content")
    return fila[0], fila[1]


def _primero(camaras: list, claves: dict) -> None:
    if camaras:
        assert_forma(camaras[0], claves)


# --- Lectura ----------------------------------------------------------------------------------------

def test_web_camaras_forma(web):
    res = web.get("/api/infra/camaras", params={"limit": 5})
    assert res.status_code == 200
    cuerpo = res.json()
    assert_forma(cuerpo, {"status": str, "total": int, "camaras": list})
    _primero(cuerpo["camaras"], CAMARA_WEB_COMPLETA)


def test_api_camaras_forma(api):
    res = api.get("/api/infra/camaras", params={"limit": 5})
    assert res.status_code == 200
    cuerpo = res.json()
    assert_forma(cuerpo, {"status": str, "total": int, "camaras": list})
    _primero(cuerpo["camaras"], CAMARA_BASE)


def test_web_search_sin_filtros_forma(web):
    res = web.post("/api/infra/search", json={"filters": [], "limit": 5})
    assert res.status_code == 200
    cuerpo = res.json()
    assert_forma(cuerpo, {
        "status": str, "total": int, "limit": int, "offset": int, "filters_applied": int, "camaras": list,
    })
    _primero(cuerpo["camaras"], CAMARA_BASE)


def test_api_search_sin_filtros_forma(api):
    res = api.post("/api/infra/search", json={"filters": [], "limit": 5})
    assert res.status_code == 200
    cuerpo = res.json()
    assert_forma(cuerpo, {
        "status": str, "total": int, "limit": int, "offset": int, "filters_applied": int, "camaras": list,
    })
    _primero(cuerpo["camaras"], CAMARA_BASE)


def test_web_smart_search_forma(web):
    res = web.post("/api/infra/smart-search", json={"terms": [], "limit": 5})
    assert res.status_code == 200
    cuerpo = res.json()
    assert_forma(cuerpo, {
        "status": str, "total": int, "limit": int, "offset": int, "filters_applied": int,
        "estado_filter": (str, NONE), "incluir_no_operativas": bool, "camaras": list,
    })
    _primero(cuerpo["camaras"], CAMARA_WEB_COMPLETA)


def test_api_smart_search_forma(api):
    res = api.post("/api/infra/smart-search", json={"terms": [], "limit": 5})
    assert res.status_code == 200
    cuerpo = res.json()
    assert_forma(cuerpo, {
        "status": str, "total": int, "limit": int, "offset": int, "filters_applied": int, "camaras": list,
    })
    _primero(cuerpo["camaras"], CAMARA_BASE)


@pytest.mark.parametrize("terminos", [["  "], [], ["", " "]])
@pytest.mark.parametrize("limit", [1, 500])
def test_api_smart_search_sin_terminos_efectivos_cuenta_todas(api, terminos, limit):
    """D3: sin términos efectivos la API matchea todo su universo (Botellas y NO_OPERATIVA incluidas)."""
    with SessionLocal() as session:
        total_db = session.execute(text("SELECT count(*) FROM app.camaras")).scalar_one()
    res = api.post("/api/infra/smart-search", json={"terms": terminos, "limit": limit})
    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["total"] == total_db
    assert cuerpo["filters_applied"] == 0
    assert len(cuerpo["camaras"]) == min(limit, total_db)


def test_api_smart_search_encuentra_botella_por_su_servicio(api):
    """Una Botella con ruta propia aparece al buscar por su servicio (criterio = lo que se le muestra)."""
    with SessionLocal() as session:
        fila = session.execute(text(
            "SELECT c.id, s.servicio_id FROM app.camaras c "
            "JOIN app.empalmes e ON e.camara_id = c.id "
            "JOIN app.ruta_empalme_association rea ON rea.empalme_id = e.id "
            "JOIN app.rutas_servicio r ON r.id = rea.ruta_id "
            "JOIN app.servicios s ON s.id = r.servicio_id "
            "WHERE c.camara_padre_id IS NOT NULL AND s.servicio_id IS NOT NULL ORDER BY c.id LIMIT 1"
        )).first()
    if fila is None:
        pytest.skip("focas_dev no tiene Botellas con ruta propia")
    camara_id, servicio_id = fila
    res = api.post("/api/infra/smart-search", json={"terms": [servicio_id], "limit": 500})
    assert res.status_code == 200
    camaras = res.json()["camaras"]
    assert camara_id in {c["id"] for c in camaras}
    botella = next(c for c in camaras if c["id"] == camara_id)
    assert servicio_id in botella["servicios"]


@pytest.mark.parametrize("termino", ["central", "libre", "1"])
def test_buscar_solo_raiz_true_no_cambia_el_total(termino):
    """El panel (`solo_raiz=True`) conserva el total de la consulta previa: raíces, sin NO_OPERATIVA."""
    from core.services.camaras_consulta import buscar_camaras_por_terminos, condicion_termino
    from db.models.infra import Camara, CamaraEstado

    with SessionLocal() as session:
        previo = (
            session.query(Camara)
            .filter(Camara.camara_padre_id.is_(None), Camara.estado != CamaraEstado.NO_OPERATIVA)
            .filter(condicion_termino(termino))
            .count()
        )
        actual = buscar_camaras_por_terminos(
            session, [termino], estado=None, incluir_no_operativas=False, limit=1, offset=0
        )
    assert actual.total == previo


def test_web_export_csv(web):
    res = web.get("/api/infra/export/cameras", params={"format": "csv"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "text/csv; charset=utf-8"
    assert CSV_NOMBRE.fullmatch(res.headers["content-disposition"])


def test_api_export_csv(api):
    res = api.get("/api/infra/export/cameras", params={"format": "csv"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "text/csv; charset=utf-8"
    assert CSV_NOMBRE.fullmatch(res.headers["content-disposition"])


def test_web_export_format_xlsx_mayuscula_200(web):
    res = web.get("/api/infra/export/cameras", params={"format": "XLSX"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert res.content[:2] == b"PK"


def test_web_ban_active_forma(web):
    res = web.get("/api/infra/ban/active")
    assert res.status_code == 200
    cuerpo = res.json()
    assert_forma(cuerpo, {"status": str, "incidentes": list, "total": int, "total_camaras_baneadas": int})
    if cuerpo["incidentes"]:
        assert_forma(cuerpo["incidentes"][0], INCIDENTE_WEB)


def test_api_ban_active_forma(api):
    res = api.get("/api/infra/ban/active")
    assert res.status_code == 200
    cuerpo = res.json()
    assert_forma(cuerpo, {"status": str, "incidentes": list, "total": int, "total_camaras_baneadas": int})
    if cuerpo["incidentes"]:
        assert_forma(cuerpo["incidentes"][0], INCIDENTE_WEB)


@pytest.mark.parametrize("cliente", ["web", "api"])
def test_email_config_forma(cliente, request):
    res = request.getfixturevalue(cliente).get("/api/infra/notify/email/config")
    assert res.status_code == 200
    assert_forma(res.json(), {"configured": bool, "from_email": (str, NONE), "from_name": (str, NONE)})


def test_web_servicio_rutas_forma(web, ruta_con_tracking):
    servicio_id, _ = ruta_con_tracking
    res = web.get(f"/api/infra/servicios/{servicio_id}/rutas")
    assert res.status_code == 200
    cuerpo = res.json()
    assert_forma(cuerpo, RUTAS_SERVICIO)
    assert cuerpo["rutas"]
    assert_forma(cuerpo["rutas"][0], RUTA_ITEM)


def test_api_servicio_rutas_forma(api, ruta_con_tracking):
    servicio_id, _ = ruta_con_tracking
    res = api.get(f"/api/infra/servicios/{servicio_id}/rutas")
    assert res.status_code == 200
    cuerpo = res.json()
    assert_forma(cuerpo, RUTAS_SERVICIO)
    assert cuerpo["rutas"]
    assert_forma(cuerpo["rutas"][0], RUTA_ITEM)


def test_servicio_rutas_por_numero_primer_servicio(web, api):
    """Ambas apps resuelven el servicio por `numero_primer_servicio` (D12) y devuelven las mismas claves."""
    with SessionLocal() as session:
        fila = session.execute(text(
            "SELECT numero_primer_servicio FROM app.servicios WHERE numero_primer_servicio IS NOT NULL "
            "AND numero_primer_servicio <> '' ORDER BY id LIMIT 1"
        )).first()
    if fila is None:
        pytest.skip("focas_dev no tiene servicios con numero_primer_servicio")
    res_web = web.get(f"/api/infra/servicios/{fila[0]}/rutas")
    res_api = api.get(f"/api/infra/servicios/{fila[0]}/rutas")
    assert res_web.status_code == res_api.status_code == 200
    assert_forma(res_web.json(), RUTAS_SERVICIO)
    assert_forma(res_api.json(), RUTAS_SERVICIO)


def test_servicio_rutas_inexistente_404(web, api):
    res_web = web.get(f"/api/infra/servicios/{INEXISTENTE}/rutas")
    res_api = api.get(f"/api/infra/servicios/{INEXISTENTE}/rutas")
    assert res_web.status_code == res_api.status_code == 404
    assert_forma(res_web.json(), {"error": str})
    assert_forma(res_api.json(), {"detail": str})


@pytest.mark.parametrize("cliente", ["web", "api"])
def test_tracking_download_ok(cliente, request, ruta_con_tracking):
    _, ruta_id = ruta_con_tracking
    res = request.getfixturevalue(cliente).get(f"/api/infra/tracking/{ruta_id}/download")
    assert res.status_code == 200
    assert res.headers["content-type"] == "text/plain; charset=utf-8"
    assert re.fullmatch(r'attachment; filename="[^"]+"', res.headers["content-disposition"])
    assert res.content


def test_tracking_download_inexistente_404(web, api):
    res_web = web.get(f"/api/infra/tracking/{ID_INEXISTENTE}/download")
    res_api = api.get(f"/api/infra/tracking/{ID_INEXISTENTE}/download")
    assert res_web.status_code == res_api.status_code == 404
    assert_forma(res_web.json(), {"error": str})
    assert_forma(res_api.json(), {"detail": str})


# --- Análisis de tracking (sólo lectura: servicio inexistente) --------------------------------------

CLAVES_ANALISIS_API = {
    "status": str, "servicio_id": (str, NONE), "servicio_db_id": (int, NONE), "nuevo_hash": (str, NONE),
    "rutas_existentes": list, "ruta_identica_id": (int, NONE), "parsed_empalmes_count": int, "message": str,
    "error": (str, NONE), "upgrade_info": (dict, NONE), "strand_info": (dict, NONE),
    "punta_a_sitio": (str, NONE), "punta_b_sitio": (str, NONE), "cantidad_pelos": (int, NONE),
    "alias_id": (str, NONE),
}
CLAVES_ANALISIS_WEB = {
    **{k: v for k, v in CLAVES_ANALISIS_API.items()},
    "empalmes_nuevos": int, "suggested_action": (str, NONE), "hash_match": bool,
}


def test_analyze_tracking_sin_ubicaciones_error_en_las_dos_apps(web, api):
    archivo = {"file": ("FO 999999991 C2.txt", b"sin empalmes", "text/plain")}
    res_web = web.post("/api/infra/trackings/analyze", files=archivo)
    res_api = api.post("/api/infra/trackings/analyze", files=archivo)
    assert res_web.status_code == res_api.status_code == 200
    assert_forma(res_web.json(), CLAVES_ANALISIS_WEB)
    assert_forma(res_api.json(), CLAVES_ANALISIS_API)
    assert res_web.json()["status"] == res_api.json()["status"] == "ERROR"


# --- Sin escritura (ids inexistentes) ---------------------------------------------------------------

def test_ban_create_servicios_inexistentes_200_success_false(web, api):
    cuerpo = {"servicio_afectado_id": INEXISTENTE, "servicio_protegido_id": INEXISTENTE}
    for cliente in (web, api):
        res = cliente.post("/api/infra/ban/create", json=cuerpo)
        assert res.status_code == 200
        assert_forma(res.json(), BAN_RESULTADO_CREAR)
        assert res.json()["success"] is False


def test_ban_lift_incidente_inexistente_200_success_false(web, api):
    for cliente in (web, api):
        res = cliente.post("/api/infra/ban/lift", json={"incidente_id": ID_INEXISTENTE})
        assert res.status_code == 200
        assert_forma(res.json(), BAN_RESULTADO_LEVANTAR)
        assert res.json()["success"] is False


def test_download_eml_incidente_inexistente_404(web, api):
    res_web = web.post(
        "/api/infra/notify/download-eml",
        json={"incident_id": ID_INEXISTENTE, "recipients": "a@b.com", "subject": "s"},
    )
    res_api = api.post("/api/infra/notify/download-eml", data={"incident_id": ID_INEXISTENTE})
    assert res_web.status_code == res_api.status_code == 404
    assert_forma(res_web.json(), {"error": str})
    assert_forma(res_api.json(), {"detail": str})


def test_delete_empalmes_servicio_inexistente_404(web, api):
    res_web = web.delete(f"/api/infra/servicios/{INEXISTENTE}/empalmes")
    res_api = api.delete(f"/api/infra/servicios/{INEXISTENTE}/empalmes")
    assert res_web.status_code == res_api.status_code == 404
    assert_forma(res_web.json(), {"error": str})
    assert_forma(res_api.json(), {"detail": str})


def test_trackings_resolve_accion_invalida_400(web, api):
    cuerpo = {"action": "NO_EXISTE", "content": "x", "filename": "x.txt"}
    res_web = web.post("/api/infra/trackings/resolve", json=cuerpo)
    res_api = api.post("/api/infra/trackings/resolve", json=cuerpo)
    assert res_web.status_code == res_api.status_code == 400
    assert_forma(res_web.json(), {"error": str})
    assert_forma(res_api.json(), {"detail": str})
