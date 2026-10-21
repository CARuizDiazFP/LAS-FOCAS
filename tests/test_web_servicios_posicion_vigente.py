# Nombre de archivo: test_web_servicios_posicion_vigente.py
# Ubicación de archivo: tests/test_web_servicios_posicion_vigente.py
# Descripción: Pruebas de los endpoints de la posición vigente por conector (admin, CSRF, códigos, serialización) y de la guarda del .txt contra Postgres real (42352 ↔ 42351)

"""Los endpoints viven en `web/app/routers/servicios.py`, junto a las ODF confirmadas, con el mismo
patrón: `_require_admin` → `_validar_csrf` → `_servicio_existe` → core → `JSONResponse`.

Los tests de wiring mockean el core (`servicio_posicion_vigente`). Los marcados con
`requiere_postgres_real` pegan contra la DB de dev sólo para LEER: el GET del 93150 y el 400 del
`.txt` para un pelo del 42351 pedido desde el 42352. Ninguno declara ni retira contra la DB real
(eso lo cubren los tests del core, en transacción revertida).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from core.services.cromo import servicio_posicion_vigente as pv
from core.services.cromo.servicio_posicion_vigente import (
    PosicionDeclarada,
    PosicionNoValida,
    PosicionPosible,
)
from tests.soporte_postgres_real import requiere_postgres_real
from tests.test_web_cromo_camino_optico import _cliente_admin, _cliente_user, _fake_session

SERVICIO = 557
URL = f"/api/admin/infra/servicios-odf/{SERVICIO}/posicion-vigente"


@pytest.fixture
def _testing(monkeypatch):
    """`_validar_csrf` se saltea con TESTING=true; sin esto estos tests dependen del orden."""
    monkeypatch.setenv("TESTING", "true")


@pytest.fixture
def sin_testing(monkeypatch):
    """CSRF real: `_validar_csrf` se saltea con TESTING=true."""
    monkeypatch.delenv("TESTING", raising=False)


def _posible(conector: int, numero: str, pelo: int | None, **otros) -> PosicionPosible:
    base = dict(
        conector_n_id=conector,
        odf_n_id=6644560,
        odf_nombre="ODF San Martin 137 P5 D",
        odf_clase=69,
        bandeja_n_id=8604881,
        bandeja_nombre="O-1252871-1",
        numero_conector=numero,
        pelo_n_id=pelo,
        numero_pelo=numero,
        cable_n_id=6600854,
        cable_nombre="F-PC-CC",
        etiqueta_pelo="44649",
        etiqueta_ajena=True,
        estado_pelo="Utilizado",
        servicio_resuelto="93150",
        servicio_id_historico="44649",
        patch_conector_n_id=None,
        por_resuelto=True,
        por_pelo=False,
        pelos_candidatos=(pelo,) if pelo else (),
    )
    base.update(otros)
    return PosicionPosible(**base)


def _declarada(conector: int, numero: str, pelo: int, *, actual: int | None = None, existe: bool = True):
    return PosicionDeclarada(
        id=conector - 8600000,
        conector_n_id=conector,
        odf_n_id=6644560,
        odf_nombre="ODF San Martin 137 P5 D",
        bandeja_n_id=8604881,
        bandeja_nombre="O-1252871-1",
        numero_conector=numero,
        pelo_declarado=pelo,
        pelos_candidatos=(pelo,),
        pelo_actual=pelo if actual is None else actual,
        conector_existe=existe,
        declarado_por="admin",
        declarado_en=datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc),
    )


def _fake_core(monkeypatch, *, posibles=(), declaradas=()):
    """El GET sólo lee: si llegara a retirar algo, el test explota."""

    async def _posibles(_sesion, _servicio_id):
        return list(posibles)

    async def _declaradas(_sesion, _servicio_id):
        return list(declaradas)

    async def _no_retira(*a, **k):
        raise AssertionError("el GET de la posición vigente no retira nada")

    monkeypatch.setattr(pv, "posiciones_posibles", _posibles)
    monkeypatch.setattr(pv, "listar_declaradas", _declaradas)
    monkeypatch.setattr(pv, "retirar", _no_retira)
    monkeypatch.setattr(pv, "aplicar_retiros", _no_retira)


# ── Auth, CSRF y 404 ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "metodo, url, cuerpo",
    [
        ("get", URL, None),
        ("post", URL, {"conectores_n_id": [8604882]}),
        ("post", f"{URL}/retirar", {"conector_n_id": 8604882}),
    ],
)
def test_posicion_vigente_exige_admin(monkeypatch, _testing, metodo, url, cuerpo):
    _fake_session(monkeypatch)
    _fake_core(monkeypatch)
    client = _cliente_user(monkeypatch)

    res = client.get(url) if metodo == "get" else client.post(url, json=cuerpo)

    assert res.status_code == 403


@pytest.mark.parametrize(
    "url, cuerpo",
    [(URL, {"conectores_n_id": [8604882]}), (f"{URL}/retirar", {"conector_n_id": 8604882})],
)
def test_posicion_vigente_exige_csrf(monkeypatch, sin_testing, url, cuerpo):
    _fake_session(monkeypatch)
    client = _cliente_admin(monkeypatch)

    res = client.post(url, json=cuerpo)

    assert res.status_code == 403
    assert res.json()["error"] == "CSRF inválido"


@pytest.mark.parametrize(
    "metodo, url, cuerpo",
    [
        ("get", URL, None),
        ("post", URL, {"conectores_n_id": [8604882]}),
        ("post", f"{URL}/retirar", {"conector_n_id": 8604882}),
    ],
)
def test_posicion_vigente_servicio_inexistente_404(monkeypatch, _testing, metodo, url, cuerpo):
    _fake_session(monkeypatch, existe=False)
    _fake_core(monkeypatch)
    client = _cliente_admin(monkeypatch)

    res = client.get(url) if metodo == "get" else client.post(url, json=cuerpo)

    assert res.status_code == 404
    assert res.json()["error"] == "Servicio no encontrado"


# ── GET: declaradas y posibles ───────────────────────────────────────────────────────────────


def test_get_serializa_posibles_con_posicion_par_sugerido_y_declarada(monkeypatch, _testing):
    _fake_session(monkeypatch)
    posibles = [
        _posible(8604882, "1", 7028862),
        _posible(8604883, "2", 7028863),
        _posible(8604886, "5", None),
        _posible(
            8546318, "5", 6799284, bandeja_n_id=8546300, bandeja_nombre="O-1239922-1",
            etiqueta_pelo="93150", etiqueta_ajena=False, servicio_activo_ajeno="42351",
        ),
    ]
    _fake_core(monkeypatch, posibles=posibles, declaradas=[_declarada(8604882, "1", 7028862)])

    cuerpo = _cliente_admin(monkeypatch).get(URL).json()

    por_id = {p["conector_n_id"]: p for p in cuerpo["posibles"]}
    assert list(por_id) == [8604882, 8604883, 8604886, 8546318]
    uno = por_id[8604882]
    assert uno["posicion"] == "O-1252871-1:1"
    assert uno["par_sugerido_n_id"] == 8604883 and por_id[8604883]["par_sugerido_n_id"] == 8604882
    assert uno["declarada"] is True and por_id[8604883]["declarada"] is False
    assert uno["etiqueta_pelo"] == "44649" and uno["etiqueta_ajena"] is True
    assert uno["pelo_n_id"] == 7028862 and uno["pelos_candidatos"] == [7028862]
    assert uno["servicio_activo_ajeno"] is None
    # Un conector sin pelo se lista (el selector lo muestra deshabilitado) y no tiene par.
    assert por_id[8604886]["pelo_n_id"] is None and por_id[8604886]["par_sugerido_n_id"] is None
    # El pelo que también matchea a otro servicio Activo lo dice.
    assert por_id[8546318]["servicio_activo_ajeno"] == "42351"
    assert set(uno) == {
        "conector_n_id", "posicion", "odf_n_id", "odf_nombre", "odf_clase", "bandeja_n_id",
        "bandeja_nombre", "numero_conector", "pelo_n_id", "numero_pelo", "pelos_candidatos",
        "cable_n_id", "cable_nombre", "etiqueta_pelo", "etiqueta_ajena", "estado_pelo",
        "servicio_resuelto", "servicio_id_historico", "patch_conector_n_id", "por_resuelto",
        "por_pelo", "servicio_activo_ajeno", "par_sugerido_n_id", "declarada",
    }

    (declarada,) = cuerpo["declaradas"]
    assert declarada == {
        "id": 4882,
        "conector_n_id": 8604882,
        "posicion": "O-1252871-1:1",
        "odf_n_id": 6644560,
        "odf_nombre": "ODF San Martin 137 P5 D",
        "bandeja_n_id": 8604881,
        "bandeja_nombre": "O-1252871-1",
        "numero_conector": "1",
        "pelo_n_id_declarado": 7028862,
        "pelo_n_id_actual": 7028862,
        "pelos_candidatos": [7028862],
        "declarado_por": "admin",
        "declarado_en": "2026-10-21T12:00:00+00:00",
        "valida": True,
        "aviso": None,
        "codigo_aviso": None,
    }


def test_get_informa_la_declarada_que_el_inventario_ya_no_sostiene_sin_retirarla(monkeypatch, _testing):
    """El GET sólo informa: retirar es efecto de la corrida (`trackings_del_servicio`)."""
    _fake_session(monkeypatch)
    declaradas = [
        replace(_declarada(8604882, "1", 7028862), pelo_actual=None),
        _declarada(8604883, "2", 7028863, actual=1),
        _declarada(8604884, "3", 7028864, existe=False),
    ]
    _fake_core(monkeypatch, declaradas=declaradas)

    cuerpo = _cliente_admin(monkeypatch).get(URL).json()

    por_id = {d["conector_n_id"]: d for d in cuerpo["declaradas"]}
    assert [d["valida"] for d in por_id.values()] == [False, False, False]
    assert por_id[8604882]["codigo_aviso"] == "SIN_PELO"
    assert "ya no tiene pelo" in por_id[8604882]["aviso"]
    assert por_id[8604883]["codigo_aviso"] == "PELO_CAMBIO"
    assert "declarado 7028863, ahora 1" in por_id[8604883]["aviso"]
    assert por_id[8604884]["codigo_aviso"] == "CONECTOR_INEXISTENTE"
    assert cuerpo["posibles"] == []


# ── POST: declarar y retirar ─────────────────────────────────────────────────────────────────


def test_declarar_posicion_vigente_ok_409_y_validacion(monkeypatch, _testing):
    _fake_session(monkeypatch)
    llamadas: list[tuple] = []

    async def _declarar(_sesion, servicio_id, conectores_n_id, *, usuario):
        if 1 in conectores_n_id:
            raise PosicionNoValida(f"El conector 1 no es una posición posible del Servicio {servicio_id}.")
        llamadas.append((servicio_id, list(conectores_n_id), usuario))
        return [_declarada(c, str(c - 8604881), c - 1575020) for c in conectores_n_id]

    monkeypatch.setattr(pv, "declarar", _declarar)
    client = _cliente_admin(monkeypatch)

    ok = client.post(URL, json={"conectores_n_id": [8604882, 8604883]})
    ajeno = client.post(URL, json={"conectores_n_id": [1]})
    vacio = client.post(URL, json={"conectores_n_id": []})
    demasiados = client.post(URL, json={"conectores_n_id": list(range(1, 10))})

    assert ok.status_code == 200
    assert ok.json()["ok"] is True
    assert [d["posicion"] for d in ok.json()["declaradas"]] == ["O-1252871-1:1", "O-1252871-1:2"]
    assert llamadas == [(SERVICIO, [8604882, 8604883], "admin")]
    assert ajeno.status_code == 409
    assert ajeno.json() == {"error": f"El conector 1 no es una posición posible del Servicio {SERVICIO}."}
    assert vacio.status_code == 422 and demasiados.status_code == 422


def test_retirar_posicion_vigente_manual_y_404_si_no_vigente(monkeypatch, _testing):
    _fake_session(monkeypatch)
    retiros: list[tuple] = []

    async def _retirar_manual(_sesion, servicio_id, conector_n_id, *, usuario):
        retiros.append((servicio_id, conector_n_id, usuario))
        return conector_n_id == 8604882

    async def _declaradas(_sesion, _servicio_id):
        return [_declarada(8604883, "2", 7028863)]

    monkeypatch.setattr(pv, "retirar_manual", _retirar_manual)
    monkeypatch.setattr(pv, "listar_declaradas", _declaradas)
    client = _cliente_admin(monkeypatch)

    ok = client.post(f"{URL}/retirar", json={"conector_n_id": 8604882})
    no_vigente = client.post(f"{URL}/retirar", json={"conector_n_id": 8604999})

    assert ok.status_code == 200
    assert ok.json()["ok"] is True
    assert [d["conector_n_id"] for d in ok.json()["declaradas"]] == [8604883]
    assert retiros == [(SERVICIO, 8604882, "admin"), (SERVICIO, 8604999, "admin")]
    assert no_vigente.status_code == 404
    assert "8604999" in no_vigente.json()["error"]


# ── Postgres real (sólo lectura) ─────────────────────────────────────────────────────────────


@pytest.fixture
def db_real(monkeypatch):
    """`AsyncSessionLocal` con NullPool: TestClient corre cada request en su propio event loop y el
    pool global no sirve entre loops."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from db.session import async_engine

    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    monkeypatch.setattr(
        "db.session.AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False)
    )
    yield


@requiere_postgres_real
def test_get_posicion_vigente_del_93150_real(monkeypatch, _testing, db_real):
    """93150 (`servicios.id=4`): 14 posiciones; O-1252871-1:1 (8604882) lleva la etiqueta 44649 de
    un servicio de Baja y sugiere su par :2 (medido en dev, 2026-10-21)."""
    res = _cliente_admin(monkeypatch).get("/api/admin/infra/servicios-odf/4/posicion-vigente")

    assert res.status_code == 200
    cuerpo = res.json()
    por_id = {p["conector_n_id"]: p for p in cuerpo["posibles"]}
    assert len(por_id) == 14
    uno = por_id[8604882]
    assert uno["posicion"] == "O-1252871-1:1"
    assert uno["pelo_n_id"] == 7028862
    assert uno["etiqueta_pelo"] == "44649" and uno["etiqueta_ajena"] is True
    assert uno["par_sugerido_n_id"] == 8604883
    assert uno["declarada"] is any(d["conector_n_id"] == 8604882 for d in cuerpo["declaradas"])


@requiere_postgres_real
def test_tracking_txt_400_para_un_pelo_del_42351_pedido_desde_el_42352_real(monkeypatch, db_real):
    """El 42352 (id 568) tiene conectores resueltos a 42352 cuyos pelos son del 42351 (id 567,
    Activo): ese pelo no es suyo, ni etiquetado ni como posición. 400 antes de ir a Cromo."""

    def _sin_cromo(*a, **k):
        raise AssertionError("no tiene que ir a Cromo")

    monkeypatch.setattr("core.services.cromo.client.CromoClient", _sin_cromo)
    res = _cliente_user(monkeypatch).get(
        "/api/infra/cromo/servicios/568/camino-optico/tracking.txt", params={"pelo_n_id": 6976963}
    )

    assert res.status_code == 400
    assert res.json()["error"] == "El pelo 6976963 no pertenece al Servicio 568."


def _camino_sin_cromo(monkeypatch) -> list[int]:
    """`CromoClient` inerte y `/path` stubeado: registra qué pelo se pidió y nunca sale a la red.
    Devuelve `SIN_CAMINO` para que el endpoint no registre evidencia del árbitro en la DB real."""
    from core.services.cromo import camino_optico_service as svc

    class _Cliente:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    pedidos: list[int] = []

    async def _camino_de_pelo(_cliente, _sesion, pelo_n_id, **_k):
        pedidos.append(pelo_n_id)
        return svc.CaminoOptico(estado=svc.ESTADO_SIN_CAMINO, pelo_n_id=pelo_n_id, motivo="stub")

    monkeypatch.setattr("core.services.cromo.client.CromoClient", lambda config=None: _Cliente())
    monkeypatch.setattr("core.services.cromo.config.get_cromo_config", lambda: object())
    monkeypatch.setattr(svc, "resolver_camino_de_pelo", _camino_de_pelo)
    return pedidos


@requiere_postgres_real
def test_camino_optico_acepta_el_pelo_de_posicion_del_93150_real(monkeypatch, _testing, db_real):
    """«Detalle» de un tramo VIGENTE / adicional del 93150: el pelo 7028862 (O-1252871-1:1) lleva la
    etiqueta 44649, no es semilla etiquetada, pero es posición del Servicio. Antes daba 400."""
    pedidos = _camino_sin_cromo(monkeypatch)

    res = _cliente_admin(monkeypatch).get(
        "/api/admin/infra/servicios-odf/4/camino-optico", params={"pelo_n_id": 7028862}
    )

    assert res.status_code == 200, res.text
    assert pedidos == [7028862]


@requiere_postgres_real
def test_camino_optico_400_para_un_pelo_del_42351_pedido_desde_el_42352_real(monkeypatch, _testing, db_real):
    """El guard no se afloja: el pelo 6976963 es del 42351 (Activo), ni etiquetado ni posición del
    42352. 400 sin llegar a `/path`."""
    pedidos = _camino_sin_cromo(monkeypatch)

    res = _cliente_admin(monkeypatch).get(
        "/api/admin/infra/servicios-odf/568/camino-optico", params={"pelo_n_id": 6976963}
    )

    assert res.status_code == 400
    assert res.json()["error"] == "El pelo 6976963 no pertenece al Servicio 568."
    assert pedidos == []
