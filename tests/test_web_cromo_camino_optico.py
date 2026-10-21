# Nombre de archivo: test_web_cromo_camino_optico.py
# Ubicación de archivo: tests/test_web_cromo_camino_optico.py
# Descripción: Pruebas de wiring (auth/admin/códigos/serialización) de los 3 endpoints del camino óptico de Cromo — sin DB real ni red

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from fastapi.testclient import TestClient  # type: ignore

from core.password import hash_password
from core.services.cromo.camino_optico_service import (
    ESTADO_OK,
    ESTADO_SIN_SEMILLA,
    CaminoOptico,
    ConsistenciaCamino,
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

    monkeypatch.setattr(web_main.cromo, "_servicio_existe", _existe)
    # El nombre vive en comun y lo leen el router cromo (camino-optico de Cromo) y el router servicios (camino-optico admin)
    monkeypatch.setattr(web_main.servicios, "_servicio_existe", _existe)

    async def _n_ids(_sesion, ids):
        return {}

    # La sesión es un `object()`: sin DB, los ids de ODF quedan como vienen.
    monkeypatch.setattr("core.services.cromo.servicio_odf_confirmacion.n_ids_de_odfs", _n_ids)

    async def _datos(_sesion, n_ids):
        return {}

    monkeypatch.setattr("core.services.cromo.servicio_odf_confirmacion.datos_de_odfs", _datos)


def _fake_cromo_client(monkeypatch):
    """`CromoClient` fake: nunca sale a la red. Los tests mockean el servicio, no el cliente."""

    class _Cliente:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("core.services.cromo.client.CromoClient", lambda config=None: _Cliente())
    monkeypatch.setattr("core.services.cromo.config.get_cromo_config", lambda: object())


def _fake_frescura(monkeypatch, frescos: Optional[dict] = None):
    """Neutraliza la consulta de frescura del caché: estos tests mockean el servicio, no la base."""

    async def _frescura(_sesion, _pelos, **_k):
        return frescos or {}

    monkeypatch.setattr("core.services.cromo.tracking_cache.frescura", _frescura)


def _fake_semillas(monkeypatch, semillas, *, total_matcheados=None, esperados=1, excluidos=None):
    """Stubea la lista de semillas y su conteo sin tope.

    `total_matcheados` por defecto iguala al largo de la lista; pasarlo distinto simula el caso
    real de un Servicio con cientos de pelos matcheados y sólo unos pocos listados.
    """
    async def _listar(*a, **k):
        return list(semillas)

    async def _contar(_sesion, _servicio_id):
        total = len(semillas) if total_matcheados is None else total_matcheados
        return total, sum(1 for s in semillas if s.tiene_conector_odf)

    async def _pertenece(_sesion, _servicio_id, pelo_n_id):
        # La pertenencia real NO depende de la lista truncada; acá el stub la resuelve contra el
        # conjunto completo que el test declara, que es lo que hace la consulta directa.
        return any(s.pelo_n_id == pelo_n_id for s in semillas)

    monkeypatch.setattr(
        "core.services.cromo.camino_optico_service.listar_pelos_semilla", _listar
    )
    monkeypatch.setattr("core.services.cromo.camino_optico_service.contar_semillas", _contar)
    monkeypatch.setattr(
        "core.services.cromo.camino_optico_service.pelo_pertenece_al_servicio", _pertenece
    )

    async def _esperados(_sesion, _servicio_id):
        return esperados

    async def _excluidos(_sesion, _servicio_id):
        return list(excluidos or [])

    monkeypatch.setattr("core.services.cromo.camino_optico_service.caminos_esperados", _esperados)
    monkeypatch.setattr("core.services.cromo.pelos_excluidos.listar_excluidos", _excluidos)
    # Por defecto el Servicio no tiene posiciones: la sesión es un `object()` y no hay DB.
    _fake_posiciones(monkeypatch)


def _fake_posiciones(monkeypatch, *, posibles=(), declaradas=()):
    """Stubea las posiciones del Servicio (`servicio_posicion_vigente`) sin DB.

    `posibles` son pelos de posiciones posibles (en orden) y `declaradas` pelos de posiciones
    declaradas vigentes; `pelo_es_de_posicion` y `tiene_posiciones` se resuelven contra los dos.
    """
    from types import SimpleNamespace

    from core.services.cromo import servicio_posicion_vigente as pv

    async def _posibles(_sesion, _servicio_id):
        return [SimpleNamespace(pelo_n_id=p) for p in posibles]

    async def _declaradas(_sesion, _servicio_id):
        return [SimpleNamespace(pelo_declarado=p) for p in declaradas]

    async def _es_de_posicion(_sesion, _servicio_id, pelo_n_id):
        return pelo_n_id in {*posibles, *declaradas}

    async def _tiene(_sesion, _servicio_id):
        return bool(posibles or declaradas)

    monkeypatch.setattr(pv, "posiciones_posibles", _posibles)
    monkeypatch.setattr(pv, "listar_declaradas", _declaradas)
    monkeypatch.setattr(pv, "pelo_es_de_posicion", _es_de_posicion)
    monkeypatch.setattr(pv, "tiene_posiciones", _tiene)


def _fake_tracking(monkeypatch, *, contenido: str = "GENERADO desde Cromo\r\n", nombre: str = "93154 CROMO.txt"):
    from datetime import datetime, timezone

    from core.services.cromo.tracking_service import TrackingGenerado

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return TrackingGenerado(
            pelo_n_id=pelo_n_id,
            nombre_archivo=nombre,
            contenido=contenido,
            desde_cache=False,
            generado_at=datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc),
            duracion_ms=10350,
        )

    monkeypatch.setattr("core.services.cromo.tracking_service.obtener_tracking", _obtener)


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
    _fake_frescura(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla()])
    client = _cliente_user(monkeypatch)

    res = client.get(_url_pelos())

    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["total"] == 1
    assert cuerpo["pelos"][0]["pelo_n_id"] == 10006353
    assert cuerpo["pelos"][0]["tiene_conector_odf"] is False
    assert cuerpo["pelos"][0]["tracking_en_cache"] is None


def test_pelos_preselecciona_las_posiciones_de_odf(monkeypatch):
    """Lo que pidió operaciones: vienen tildadas las posiciones de la ODF, que pueden ser varias."""
    _fake_session(monkeypatch)
    _fake_frescura(monkeypatch)
    _fake_semillas(
        monkeypatch,
        [
            _semilla(1),
            _semilla_con_conector(2),
            _semilla_con_conector(3),
        ],
    )
    client = _cliente_user(monkeypatch)

    cuerpo = client.get(_url_pelos()).json()

    assert cuerpo["preseleccionados"] == [2, 3]
    assert cuerpo["odf_relevada"] is True


def test_pelos_avisa_cuando_la_odf_no_esta_relevada(monkeypatch):
    """Caso real del servicio 122347: 6 pelos y ningún conector de ODF ingerido todavía."""
    _fake_session(monkeypatch)
    _fake_frescura(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla(7554378), _semilla(6967355)])
    client = _cliente_user(monkeypatch)

    cuerpo = client.get(_url_pelos()).json()

    assert cuerpo["odf_relevada"] is False
    assert cuerpo["preseleccionados"] == [7554378], "cae al comportamiento histórico"


def test_pelos_informa_que_el_tracking_ya_esta_en_cache(monkeypatch):
    """La UI necesita saber si la descarga es instantánea o va a tardar varios segundos."""
    from datetime import datetime, timezone

    _fake_session(monkeypatch)
    _fake_frescura(
        monkeypatch, {10006353: datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)}
    )
    _fake_semillas(monkeypatch, [_semilla()])
    client = _cliente_user(monkeypatch)

    cuerpo = client.get(_url_pelos()).json()

    assert cuerpo["pelos"][0]["tracking_en_cache"] == "2026-09-17T09:00:00+00:00"


def _semilla_con_conector(pelo_n_id: int) -> PeloSemilla:
    """Semilla que ya es posición de patchera de una ODF ingerida."""
    base = _semilla(pelo_n_id)
    base.tiene_conector_odf = True
    return base


async def _semillas_async():
    return [_semilla()]


def test_pelos_404_si_el_servicio_no_existe(monkeypatch):
    _fake_session(monkeypatch, existe=False)
    client = _cliente_user(monkeypatch)

    assert client.get(_url_pelos(999999)).status_code == 404


def test_pelos_devuelve_lista_vacia_sin_semillas(monkeypatch):
    # Es el 77% de los Servicios del gestor: no es un error, es la respuesta correcta.
    _fake_session(monkeypatch)
    _fake_frescura(monkeypatch)
    _fake_semillas(monkeypatch, [], esperados=0)
    client = _cliente_user(monkeypatch)

    res = client.get(_url_pelos())

    assert res.status_code == 200
    assert res.json() == {
        "servicio_id": SERVICIO,
        "total": 0,
        "pelos": [],
        "preseleccionados": [],
        "odf_relevada": False,
        "total_matcheados": 0,
        "total_con_posicion_odf": 0,
        "caminos_esperados": 0,
        "excluidos": [],
    }


def test_pelos_distingue_el_universo_matcheado_de_lo_listado(monkeypatch):
    """Caso real del Servicio 93154: 227 pelos matcheados y sólo 2 que son posición de ODF.

    El número de servicio viaja en el `at.61` de TODOS los pelos del recorrido, no sólo de los
    extremos, así que el total es grande por diseño. Sin estos dos contadores la UI no puede
    distinguir "este Servicio tiene 20 pelos" de "tiene 227 y te muestro 20", y el operador que
    sabe que su Servicio tiene 2 fibras cree que el sistema está mal.
    """
    _fake_session(monkeypatch)
    _fake_frescura(monkeypatch)
    _fake_semillas(
        monkeypatch,
        [_semilla_con_conector(1), _semilla_con_conector(2), _semilla(3)],
        total_matcheados=227,
    )
    client = _cliente_user(monkeypatch)

    cuerpo = client.get(_url_pelos()).json()

    assert cuerpo["total"] == 3, "lo que se lista"
    assert cuerpo["total_matcheados"] == 227, "el universo real, sin el tope"
    assert cuerpo["total_con_posicion_odf"] == 2, "los pelos del Servicio propiamente dichos"
    assert cuerpo["preseleccionados"] == [1, 2]


# ── GET .../camino-optico/tracking.txt ──────────────────────────────────────


def test_tracking_txt_requiere_autenticacion():
    assert TestClient(app).get(_url_txt()).status_code == 401


def test_tracking_txt_devuelve_el_archivo_con_content_disposition(monkeypatch):
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla()])
    _fake_tracking(monkeypatch)
    client = _cliente_user(monkeypatch)

    res = client.get(_url_txt())

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert 'filename="93154 CROMO.txt"' in res.headers["content-disposition"]
    assert "GENERADO desde Cromo" in res.text


def _preparar_txt(monkeypatch, *, desde_cache: bool):
    from core.services.cromo.tracking_service import TrackingGenerado

    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla()])

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return TrackingGenerado(
            pelo_n_id=pelo_n_id,
            nombre_archivo="93154 CROMO.txt",
            contenido="GENERADO desde Cromo\r\n",
            desde_cache=desde_cache,
            generado_at=datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc),
            duracion_ms=10,
        )

    monkeypatch.setattr("core.services.cromo.tracking_service.obtener_tracking", _obtener)


def test_tracking_txt_registra_evidencia_y_su_falla_no_cambia_la_respuesta(monkeypatch):
    _preparar_txt(monkeypatch, desde_cache=False)
    client = _cliente_user(monkeypatch)
    base = client.get(_url_txt())

    llamadas = []

    async def _boom(*args, **kwargs):
        llamadas.append(kwargs.get("fuente"))
        raise RuntimeError("evidencia rota")

    monkeypatch.setattr("core.services.cromo.arbitro.evidencia.registrar_y_encolar", _boom)
    res = client.get(_url_txt())

    assert llamadas == ["WEB"]
    assert res.status_code == base.status_code == 200
    assert res.content == base.content
    assert res.headers["content-disposition"] == base.headers["content-disposition"]


def test_tracking_txt_desde_cache_no_registra_evidencia(monkeypatch):
    _preparar_txt(monkeypatch, desde_cache=True)
    llamadas = []

    async def _registrar(*args, **kwargs):
        llamadas.append(1)

    monkeypatch.setattr("core.services.cromo.arbitro.evidencia.registrar_y_encolar", _registrar)
    res = _cliente_user(monkeypatch).get(_url_txt())

    assert res.status_code == 200
    assert llamadas == []


def test_tracking_txt_con_un_solo_pelo_conserva_el_nombre_historico(monkeypatch):
    """Caso PON. Nada de lo que consume ese `.txt` aguas abajo se entera del cambio."""
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla(10006353)], total_matcheados=1)
    _fake_tracking(monkeypatch)
    client = _cliente_user(monkeypatch)

    res = client.get(_url_txt(), params={"pelo_n_id": 10006353})

    assert 'filename="93154 CROMO.txt"' in res.headers["content-disposition"]


def test_tracking_txt_con_varios_pelos_identifica_a_cual_corresponde(monkeypatch):
    """El hueco que no cubría ningún test: un Servicio con más de una semilla.

    Sin esto los N archivos del mismo Servicio se llamarían igual y se pisarían al descargarlos.
    """
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla(10006353), _semilla(10006354)])
    _fake_tracking(monkeypatch)
    client = _cliente_user(monkeypatch)

    uno = client.get(_url_txt(), params={"pelo_n_id": 10006353})
    otro = client.get(_url_txt(), params={"pelo_n_id": 10006354})

    assert 'filename="93154 CROMO pelo 10006353.txt"' in uno.headers["content-disposition"]
    assert 'filename="93154 CROMO pelo 10006354.txt"' in otro.headers["content-disposition"]


def test_tracking_txt_con_tramo_usa_el_nombre_de_tramo(monkeypatch):
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla(10006353), _semilla(10006354)])
    _fake_tracking(monkeypatch)
    client = _cliente_user(monkeypatch)

    from core.services.cromo import tracking_service

    async def _numero(_sesion, _servicio_id):
        return "93154"

    monkeypatch.setattr(tracking_service, "numero_del_servicio", _numero)

    res = client.get(_url_txt(), params={"pelo_n_id": 10006354, "tramo": 2})

    assert 'filename="93154 CROMO T2 pelo 10006354.txt"' in res.headers["content-disposition"]


def test_tracking_txt_con_tramo_usa_el_numero_del_servicio_y_no_el_at62(monkeypatch):
    """El at.62 del pelo puede venir mal cargado en Cromo (medido: "83254" en un hilo del 93154).
    El nombre del tramo sale del número del Servicio en LAS-FOCAS."""
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla(10006353), _semilla(10006354)])
    _fake_tracking(monkeypatch)
    client = _cliente_user(monkeypatch)
    from core.services.cromo import tracking_service

    async def _numero(_sesion, _servicio_id):
        return "77777"

    monkeypatch.setattr(tracking_service, "numero_del_servicio", _numero)

    res = client.get(_url_txt(), params={"pelo_n_id": 10006354, "tramo": 2})

    assert 'filename="77777 CROMO T2 pelo 10006354.txt"' in res.headers["content-disposition"]


def test_tracking_txt_sin_pelo_explicito_usa_la_posicion_de_odf(monkeypatch):
    """Sin `pelo_n_id`, el default es la posición de ODF del Servicio, no el primero del ranking."""
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla(111), _semilla_con_conector(222)])
    elegidos = []

    from datetime import datetime, timezone

    from core.services.cromo.tracking_service import TrackingGenerado

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        elegidos.append(pelo_n_id)
        return TrackingGenerado(
            pelo_n_id=pelo_n_id,
            nombre_archivo="93154 CROMO.txt",
            contenido="GENERADO desde Cromo",
            desde_cache=False,
            generado_at=datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc),
            duracion_ms=1,
        )

    monkeypatch.setattr("core.services.cromo.tracking_service.obtener_tracking", _obtener)
    client = _cliente_user(monkeypatch)

    assert client.get(_url_txt()).status_code == 200
    assert elegidos == [222]


def test_tracking_txt_409_sin_semilla_en_vez_de_un_archivo_vacio(monkeypatch):
    """Un `.txt` que dice "no hay datos" es basura en la carpeta de Descargas de alguien."""
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [])
    client = _cliente_user(monkeypatch)

    res = client.get(_url_txt())

    assert res.status_code == 409
    assert res.json()["estado"] == ESTADO_SIN_SEMILLA


def test_tracking_txt_400_si_el_pelo_no_es_del_servicio(monkeypatch):
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla()])
    client = _cliente_user(monkeypatch)

    res = client.get(_url_txt(), params={"pelo_n_id": 1})

    assert res.status_code == 400
    assert "no pertenece" in res.json()["error"]


def test_tracking_txt_acepta_un_pelo_real_aunque_quede_fuera_del_tope(monkeypatch):
    """Regresión del bug real del Servicio 93154.

    La pertenencia se resolvía contra la lista de semillas, que viene **truncada** en 20 sobre 227
    pelos matcheados: un pelo legítimo que el propio selector acababa de ofrecer se rechazaba con
    "no pertenece al Servicio". Ahora se consulta directo, sin ventana.
    """
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    # La lista que ve el endpoint NO contiene al pelo pedido; el conjunto real sí.
    semillas = [_semilla(6822061), _semilla(6822062)]
    _fake_semillas(monkeypatch, semillas, total_matcheados=227)

    async def _listar_truncado(*a, **k):
        return [_semilla(999999)]

    monkeypatch.setattr(
        "core.services.cromo.camino_optico_service.listar_pelos_semilla", _listar_truncado
    )
    _fake_tracking(monkeypatch)
    client = _cliente_user(monkeypatch)

    res = client.get(_url_txt(), params={"pelo_n_id": 6822061})

    assert res.status_code == 200
    assert 'filename="93154 CROMO pelo 6822061.txt"' in res.headers["content-disposition"]


def test_tracking_txt_502_si_cromo_no_responde(monkeypatch):
    from core.services.cromo.client import CromoClientError

    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla()])

    async def _obtener(*a, **k):
        raise CromoClientError("timeout")

    monkeypatch.setattr("core.services.cromo.tracking_service.obtener_tracking", _obtener)
    client = _cliente_user(monkeypatch)

    res = client.get(_url_txt())

    assert res.status_code == 502
    assert "Cromo no respondió" in res.json()["error"]


# ── .txt de posiciones (posición vigente / caminos adicionales) ──────────────────────────────


def _txt_con_registro(monkeypatch, *, nombre: str = "4649 CROMO.txt", numero: Optional[str] = "93150"):
    """`obtener_tracking` fake que anota con qué `servicio_id` y pelo se pidió. El nombre base
    simula el at.62 mal cargado de los pelos viejos del 93150 (`4649`)."""
    from core.services.cromo import tracking_service
    from core.services.cromo.tracking_service import TrackingGenerado

    pedidos: list[tuple] = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append((servicio_id, pelo_n_id))
        return TrackingGenerado(
            pelo_n_id=pelo_n_id,
            nombre_archivo=nombre,
            contenido="GENERADO desde Cromo",
            desde_cache=True,
            generado_at=datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc),
            duracion_ms=1,
        )

    async def _numero(_sesion, _servicio_id):
        return numero

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)
    monkeypatch.setattr(tracking_service, "numero_del_servicio", _numero)
    return pedidos


def _nombre(res) -> str:
    return res.headers["content-disposition"].split('filename="', 1)[1].rstrip('"')


def test_tracking_txt_acepta_pelo_de_posicion_aunque_tenga_otra_etiqueta(monkeypatch):
    """93150: el pelo 7028862 de O-1252871-1:1 lleva la etiqueta 44649 (no es semilla etiquetada)
    pero es posición posible. Se baja, sin servicio en el caché (no está declarado) y con el número
    del Servicio en el nombre, nunca con el at.62 `4649`."""
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla(6799280)])
    _fake_posiciones(monkeypatch, posibles=[7028862])
    pedidos = _txt_con_registro(monkeypatch)

    res = _cliente_user(monkeypatch).get(_url_txt(), params={"pelo_n_id": 7028862})

    assert res.status_code == 200
    assert _nombre(res) == "93150 CROMO pelo 7028862.txt"
    assert "4649" not in _nombre(res).replace("7028862", "")
    assert pedidos == [(None, 7028862)]


def test_tracking_txt_pelo_declarado_se_cachea_con_el_servicio(monkeypatch):
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla(6799280)])
    _fake_posiciones(monkeypatch, posibles=[7028862], declaradas=[7028862])
    pedidos = _txt_con_registro(monkeypatch)

    res = _cliente_user(monkeypatch).get(_url_txt(), params={"pelo_n_id": 7028862, "tramo": 1})

    assert res.status_code == 200
    assert _nombre(res) == "93150 CROMO T1 pelo 7028862.txt"
    assert pedidos == [(SERVICIO, 7028862)]


def test_tracking_txt_adicional_se_nombra_con_numero_del_servicio(monkeypatch):
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla(6799280)])
    _fake_posiciones(monkeypatch, posibles=[7028862])
    _txt_con_registro(monkeypatch)
    client = _cliente_user(monkeypatch)

    adicional = client.get(_url_txt(), params={"pelo_n_id": 7028862, "adicional": 2})
    # También un adicional etiquetado (un TRAMO que pasó a ADICIONAL por la declaración).
    etiquetado = client.get(_url_txt(), params={"pelo_n_id": 6799280, "adicional": 1})

    assert _nombre(adicional) == "93150 CROMO A2 pelo 7028862.txt"
    assert _nombre(etiquetado) == "93150 CROMO A1 pelo 6799280.txt"


def test_tracking_txt_tramo_de_pelo_de_posicion_no_cae_al_at62(monkeypatch):
    """Sin número del Servicio el respaldo del tramo es el at.62 del pelo; para un pelo que sólo es
    de posición ese at.62 es justamente el que está mal (`4649`)."""
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla(6799280)])
    _fake_posiciones(monkeypatch, posibles=[7028862])
    _txt_con_registro(monkeypatch, numero=None)
    client = _cliente_user(monkeypatch)

    tramo = client.get(_url_txt(), params={"pelo_n_id": 7028862, "tramo": 1})
    suelto = client.get(_url_txt(), params={"pelo_n_id": 7028862})

    assert _nombre(tramo) == "tracking_cromo T1 pelo 7028862.txt"
    assert _nombre(suelto) == "tracking_cromo_pelo_7028862.txt"


def test_tracking_txt_tramo_y_adicional_juntos_400(monkeypatch):
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [_semilla(6799280)])
    _txt_con_registro(monkeypatch)

    res = _cliente_user(monkeypatch).get(
        _url_txt(), params={"pelo_n_id": 6799280, "tramo": 1, "adicional": 1}
    )

    assert res.status_code == 400
    assert "tramo o un adicional" in res.json()["error"]


def test_tracking_txt_sin_semillas_con_posiciones_no_da_409(monkeypatch):
    """Sin semillas etiquetadas (9 servicios reales, con el filtro aplicado) el default es la
    posición declarada o, si no hay, la primera posible."""
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [])
    _fake_posiciones(monkeypatch, posibles=[7028862, 7028863])
    pedidos = _txt_con_registro(monkeypatch)
    client = _cliente_user(monkeypatch)

    res = client.get(_url_txt())

    assert res.status_code == 200
    assert _nombre(res) == "93150 CROMO pelo 7028862.txt"
    assert pedidos == [(None, 7028862)]

    _fake_posiciones(monkeypatch, posibles=[7028862, 7028863], declaradas=[7028863])
    declarada = client.get(_url_txt())

    assert declarada.status_code == 200
    assert pedidos[-1] == (SERVICIO, 7028863)


def test_tracking_txt_400_pelo_ajeno_aunque_el_servicio_no_tenga_semillas(monkeypatch):
    """Pedido explícito de un pelo que no es del Servicio: 400, aunque no haya semillas (42352)."""
    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_semillas(monkeypatch, [])

    res = _cliente_user(monkeypatch).get(_url_txt(), params={"pelo_n_id": 6976963})

    assert res.status_code == 400
    assert "no pertenece" in res.json()["error"]


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



# ── Caminos del Servicio y exclusión de huérfanos (Servicio 94673, 2026-10-05) ──────────────


def test_pelos_informa_caminos_esperados_y_excluidos(monkeypatch):
    from datetime import datetime, timezone

    from core.services.cromo.pelos_excluidos import PeloExcluido

    _fake_session(monkeypatch)
    _fake_frescura(monkeypatch)
    excluido = PeloExcluido(
        pelo_n_id=9999999,
        numero_pelo="23",
        color="BL",
        cable_nombre="F-VIN-TEC",
        motivo="Huérfano",
        excluido_por="admin",
        created_at=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
    )
    _fake_semillas(
        monkeypatch, [_semilla(6799772), _semilla(6799773)], esperados=2, excluidos=[excluido]
    )
    client = _cliente_user(monkeypatch)

    cuerpo = client.get(_url_pelos()).json()

    assert cuerpo["caminos_esperados"] == 2
    assert cuerpo["excluidos"][0]["pelo_n_id"] == 9999999
    assert cuerpo["excluidos"][0]["excluido_por"] == "admin"


def _fake_trackings_del_servicio(monkeypatch, resultado):
    async def _del_servicio(_cliente, _sesion, _servicio_id):
        return resultado

    monkeypatch.setattr(
        "core.services.cromo.tracking_service.trackings_del_servicio", _del_servicio
    )


def test_caminos_devuelve_los_tramos_y_los_residuales(monkeypatch):
    from datetime import datetime, timezone

    from core.services.cromo.tracking_service import (
        ExtremoCamino,
        ResumenCamino,
        TrackingGenerado,
        TrackingsDelServicio,
    )

    resumen = ResumenCamino(
        inicio=ExtremoCamino(
            tipo="CONECTOR_ODF",
            id_cromo=1,
            odf_id=10,
            odf_clase=69,
            odf_nombre="ODF X",
            patchera_nombre="P1",
            conector_numero="39",
        ),
        fin=ExtremoCamino(tipo="pelo", id_cromo=77, clase=130),
    )

    def _t(pelo: int, nombre: str, rol: str) -> TrackingGenerado:
        return TrackingGenerado(
            pelo_n_id=pelo,
            nombre_archivo=nombre,
            contenido="x",
            desde_cache=True,
            generado_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
            duracion_ms=1,
            pelos_camino=frozenset({pelo, pelo + 1000}),
            extremos=resumen,
            rol=rol,
        )

    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    _fake_trackings_del_servicio(
        monkeypatch,
        TrackingsDelServicio(
            tramos=[
                _t(6799772, "94673 CROMO T1 pelo 6799772.txt", "TRAMO"),
                _t(6799773, "94673 CROMO T2 pelo 6799773.txt", "TRAMO"),
            ],
            residuales=[_t(9999999, "94673 CROMO.txt", "RESIDUAL")],
            errores=[],
            completo=True,
            esperados_declarados=3,
        ),
    )
    client = _cliente_user(monkeypatch)

    res = client.get(f"/api/infra/cromo/servicios/{SERVICIO}/camino-optico/caminos")

    assert res.status_code == 200
    cuerpo = res.json()
    assert set(cuerpo) == {
        "tramos", "residuales", "esperados_declarados", "odf_confirmadas", "completo", "errores",
        "no_cubiertos", "tope_llamadas", "segmentos", "inconsistencias",
        "adicionales", "caminos_resueltos", "posicion_vigente",
    }
    assert cuerpo["adicionales"] == [] and cuerpo["caminos_resueltos"] == 2
    assert cuerpo["posicion_vigente"] == {
        "declarada": False, "aplicada": False, "posiciones": "", "avisos": [],
    }
    assert cuerpo["tramos"][0]["rol"] == "TRAMO" and cuerpo["tramos"][0]["completo"] is False
    assert cuerpo["esperados_declarados"] == 3 and cuerpo["completo"] is True
    assert [c["n"] for c in cuerpo["tramos"]] == [1, 2]
    assert [c["pelo_n_id"] for c in cuerpo["tramos"]] == [6799772, 6799773]
    assert cuerpo["tramos"][0]["pelos_en_camino"] == 2
    assert cuerpo["tramos"][0]["desde_cache"] is True
    assert cuerpo["tramos"][0]["nombre_archivo"] == "94673 CROMO T1 pelo 6799772.txt"
    assert cuerpo["tramos"][0]["extremos"]["a"] == {
        "tipo": "CONECTOR_ODF",
        "odf_n_id": 10,
        "odf_nombre": "ODF X",
        "odf_clase": 69,
        "patchera_nombre": "P1",
        "conector": "39",
        "id_cromo": 1,
    }
    assert cuerpo["tramos"][0]["extremos"]["b"]["tipo"] == "pelo"
    assert [r["pelo_n_id"] for r in cuerpo["residuales"]] == [9999999]
    assert "n" not in cuerpo["residuales"][0] and "desde_cache" not in cuerpo["residuales"][0]
    assert "extremos" in cuerpo["residuales"][0]


def test_caminos_con_cromo_caido_responde_502(monkeypatch):
    from core.services.cromo.client import CromoClientError

    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)

    async def _falla(_cliente, _sesion, _servicio_id):
        raise CromoClientError("timeout")

    monkeypatch.setattr("core.services.cromo.tracking_service.trackings_del_servicio", _falla)
    client = _cliente_user(monkeypatch)

    res = client.get(f"/api/infra/cromo/servicios/{SERVICIO}/camino-optico/caminos")

    assert res.status_code == 502


def _url_excluir(restaurar: bool = False) -> str:
    sufijo = "/restaurar" if restaurar else ""
    return f"/api/admin/infra/servicios-odf/{SERVICIO}/pelos-excluidos{sufijo}"


def test_excluir_pelo_exige_admin(monkeypatch):
    _fake_session(monkeypatch)
    client = _cliente_user(monkeypatch)

    res = client.post(_url_excluir(), json={"pelos_n_id": [9999999]})

    assert res.status_code == 403


def test_excluir_pelos_en_lote_y_todos_ajenos_409(monkeypatch):
    from core.services.cromo import pelos_excluidos

    _fake_session(monkeypatch)
    llamadas: list[tuple] = []

    async def _excluir(_sesion, servicio_id, pelos_n_id, *, usuario, motivo=None):
        if pelos_n_id == [1]:
            raise pelos_excluidos.PeloNoPerteneceAlServicio("ajeno")
        llamadas.append((servicio_id, pelos_n_id, usuario, motivo))
        return [p for p in pelos_n_id if p != 5], [5]

    monkeypatch.setattr(pelos_excluidos, "excluir_pelos", _excluir)
    client = _cliente_admin(monkeypatch)

    ok = client.post(_url_excluir(), json={"pelos_n_id": [9999999, 9999998, 5], "motivo": "Huérfano"})
    ajeno = client.post(_url_excluir(), json={"pelos_n_id": [1]})
    vacio = client.post(_url_excluir(), json={"pelos_n_id": []})

    assert ok.status_code == 200
    assert ok.json()["excluidos"] == [9999999, 9999998] and ok.json()["ajenos"] == [5]
    assert llamadas == [(SERVICIO, [9999999, 9999998, 5], "admin", "Huérfano")]
    assert ajeno.status_code == 409
    assert vacio.status_code == 422


def test_restaurar_pelo_no_excluido_404(monkeypatch):
    from core.services.cromo import pelos_excluidos

    _fake_session(monkeypatch)

    async def _restaurar(_sesion, _servicio_id, pelo_n_id, *, usuario):
        return pelo_n_id == 9999999

    monkeypatch.setattr(pelos_excluidos, "restaurar_pelo", _restaurar)
    client = _cliente_admin(monkeypatch)

    assert client.post(_url_excluir(True), json={"pelo_n_id": 9999999}).status_code == 200
    assert client.post(_url_excluir(True), json={"pelo_n_id": 5}).status_code == 404


# ── ODF confirmadas y trackings esperados (Tarea 4) ─────────────────────────────────────────


@pytest.fixture(autouse=False)
def _testing(monkeypatch):
    """`_validar_csrf` se saltea con TESTING=true; sin esto estos tests dependen del orden."""
    monkeypatch.setenv("TESTING", "true")


def _url_odf(sufijo: str = "") -> str:
    return f"/api/admin/infra/servicios-odf/{SERVICIO}/odf-confirmadas{sufijo}"


def test_confirmar_odf_exige_admin(monkeypatch, _testing):
    _fake_session(monkeypatch)
    client = _cliente_user(monkeypatch)

    res = client.post(_url_odf(), json={"odfs": [{"odf_n_id": 1, "rol": "EXTREMO"}]})

    assert res.status_code == 403


def test_confirmar_odf_en_lote_valida_rol_y_mapea_inexistente_a_404(monkeypatch, _testing):
    from core.services.cromo import servicio_odf_confirmacion as svc
    from core.services.cromo.verificador import ObjetoNoEncontrado

    _fake_session(monkeypatch)
    llamadas: list[tuple] = []

    async def _confirmar(_sesion, servicio_id, odfs, *, usuario):
        if any(n == 99 for n, _ in odfs):
            raise ObjetoNoEncontrado("no existe")
        llamadas.append((servicio_id, odfs, usuario))
        return [{"odf_n_id": n, "rol": r} for n, r in odfs]

    monkeypatch.setattr(svc, "confirmar", _confirmar)
    client = _cliente_admin(monkeypatch)

    ok = client.post(
        _url_odf(),
        json={"odfs": [{"odf_n_id": 1, "rol": "EXTREMO"}, {"odf_n_id": 2, "rol": "TRANSITO"}]},
    )
    inexistente = client.post(_url_odf(), json={"odfs": [{"odf_n_id": 99, "rol": "EXTREMO"}]})
    rol_malo = client.post(_url_odf(), json={"odfs": [{"odf_n_id": 1, "rol": "OTRO"}]})
    vacio = client.post(_url_odf(), json={"odfs": []})

    assert ok.status_code == 200
    assert ok.json()["odf_confirmadas"] == [
        {"odf_n_id": 1, "rol": "EXTREMO"},
        {"odf_n_id": 2, "rol": "TRANSITO"},
    ]
    assert llamadas == [(SERVICIO, [(1, "EXTREMO"), (2, "TRANSITO")], "admin")]
    assert inexistente.status_code == 404
    assert rol_malo.status_code == 422 and vacio.status_code == 422


def test_confirmar_odf_servicio_inexistente_404(monkeypatch, _testing):
    _fake_session(monkeypatch, existe=False)
    client = _cliente_admin(monkeypatch)

    res = client.post(_url_odf(), json={"odfs": [{"odf_n_id": 1, "rol": "EXTREMO"}]})

    assert res.status_code == 404


def test_desconfirmar_odf_404_si_no_estaba_vigente(monkeypatch, _testing):
    from core.services.cromo import servicio_odf_confirmacion as svc

    _fake_session(monkeypatch)

    async def _desconfirmar(_sesion, _servicio_id, odf_n_id):
        return odf_n_id == 1

    async def _listar(_sesion, _servicio_id):
        return []

    monkeypatch.setattr(svc, "desconfirmar", _desconfirmar)
    monkeypatch.setattr(svc, "listar", _listar)
    client = _cliente_admin(monkeypatch)

    assert client.post(_url_odf("/desconfirmar"), json={"odf_n_id": 1}).status_code == 200
    assert client.post(_url_odf("/desconfirmar"), json={"odf_n_id": 2}).status_code == 404
    assert _cliente_user(monkeypatch).post(
        _url_odf("/desconfirmar"), json={"odf_n_id": 1}
    ).status_code == 403


def test_declarar_trackings_esperados_valida_y_permite_null(monkeypatch, _testing):
    from core.services.cromo import servicio_odf_confirmacion as svc

    _fake_session(monkeypatch)
    declaradas: list = []

    async def _declarar(_sesion, servicio_id, cantidad):
        declaradas.append((servicio_id, cantidad))
        return True

    monkeypatch.setattr(svc, "declarar_trackings_esperados", _declarar)
    client = _cliente_admin(monkeypatch)
    url = f"/api/admin/infra/servicios-odf/{SERVICIO}/trackings-esperados"

    assert client.post(url, json={"cantidad": 6}).status_code == 200
    assert client.post(url, json={"cantidad": None}).status_code == 200
    assert client.post(url, json={"cantidad": 0}).status_code == 422
    assert declaradas == [(SERVICIO, 6), (SERVICIO, None)]
    assert _cliente_user(monkeypatch).post(url, json={"cantidad": 2}).status_code == 403


def test_listar_odf_confirmadas_exige_admin_y_devuelve_lo_declarado(monkeypatch, _testing):
    from core.services.cromo import servicio_odf_confirmacion as svc

    _fake_session(monkeypatch)

    async def _decl(_sesion, _servicio_id):
        return svc.Declaraciones(confirmadas=[{"odf_n_id": 1, "rol": "EXTREMO"}], trackings_esperados=4)

    monkeypatch.setattr(svc, "declaraciones_del_servicio", _decl)

    assert _cliente_user(monkeypatch).get(_url_odf()).status_code == 403
    cuerpo = _cliente_admin(monkeypatch).get(_url_odf()).json()
    assert cuerpo == {"odf_confirmadas": [{"odf_n_id": 1, "rol": "EXTREMO"}], "trackings_esperados": 4}


def test_caminos_expone_el_n_id_de_la_odf_aunque_el_camino_traiga_el_version_id(monkeypatch):
    """Un extremo con el id de versión de la ODF sale con el n_id de linaje, que es el que
    comparan las ODF confirmadas del mismo response."""
    from core.services.cromo import servicio_odf_confirmacion as svc
    from core.services.cromo.tracking_service import (
        ExtremoCamino,
        ResumenCamino,
        TrackingGenerado,
        TrackingsDelServicio,
    )

    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    extremo = ExtremoCamino(
        tipo="CONECTOR_ODF", id_cromo=5, clase=136, odf_id=9295436, odf_clase=86,
        odf_nombre="NODO KORN", patchera_nombre="O-1", conector_numero="39",
    )
    tramo = TrackingGenerado(
        pelo_n_id=10, nombre_archivo="1 CROMO T1 pelo 10.txt", contenido="", desde_cache=True,
        generado_at=datetime(2026, 10, 16, tzinfo=timezone.utc), duracion_ms=None,
        pelos_camino=frozenset({10}),
        extremos=ResumenCamino(inicio=extremo, fin=None, odfs=(9295436,)), rol="TRAMO",
    )
    _fake_trackings_del_servicio(
        monkeypatch,
        TrackingsDelServicio(
            tramos=[tramo], residuales=[], errores=[], completo=True,
            odf_confirmadas=[{"odf_n_id": 6646686, "rol": "TRANSITO"}],
        ),
    )

    async def _n_ids(_sesion, ids):
        assert list(ids) == [9295436]
        return {9295436: 6646686}

    monkeypatch.setattr(svc, "n_ids_de_odfs", _n_ids)
    cuerpo = _cliente_user(monkeypatch).get(
        f"/api/infra/cromo/servicios/{SERVICIO}/camino-optico/caminos"
    ).json()

    assert cuerpo["tramos"][0]["extremos"]["a"]["odf_n_id"] == 6646686
    assert cuerpo["odf_confirmadas"][0]["odf_n_id"] == 6646686


def test_caminos_expone_todas_las_odfs_de_tramos_y_residuales_con_nombre_y_clase(monkeypatch):
    """I2: la UI tiene que poder confirmar una ODF que sólo toca un residual o que es intermedia.
    Cada camino trae sus `odfs` normalizadas a n_id, con nombre y clase de `cromo_odfs`; las de los
    extremos conservan el nombre del payload si la ODF no está ingerida."""
    from core.services.cromo import servicio_odf_confirmacion as svc
    from core.services.cromo.tracking_service import (
        ExtremoCamino,
        ResumenCamino,
        TrackingGenerado,
        TrackingsDelServicio,
    )

    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)
    extremo = ExtremoCamino(
        tipo="CONECTOR_ODF", id_cromo=5, clase=136, odf_id=9295436, odf_clase=86,
        odf_nombre="NODO KORN",
    )

    def _t(pelo, resumen, rol):
        return TrackingGenerado(
            pelo_n_id=pelo, nombre_archivo=f"{pelo}.txt", contenido="", desde_cache=True,
            generado_at=datetime(2026, 10, 16, tzinfo=timezone.utc), duracion_ms=None,
            pelos_camino=frozenset({pelo}), extremos=resumen, rol=rol,
        )

    tramo = _t(10, ResumenCamino(inicio=extremo, fin=None, odfs=(777, 9295436)), "TRAMO")
    residual = _t(20, ResumenCamino(inicio=None, fin=None, odfs=(888,)), "RESIDUAL")
    _fake_trackings_del_servicio(
        monkeypatch,
        TrackingsDelServicio(
            tramos=[tramo], residuales=[residual], errores=["Pelo 3: sin camino"], completo=True,
            no_cubiertos=[3], tope_llamadas=False, segmentos=1,
        ),
    )

    async def _n_ids(_sesion, ids):
        assert sorted(ids) == [777, 888, 9295436]
        return {9295436: 6646686, 777: 777, 888: 888}

    async def _datos(_sesion, n_ids):
        assert sorted(n_ids) == [777, 888, 6646686]
        return {777: ("ODF INTERMEDIA", 69), 888: ("ODF DEL RESIDUAL", 69)}

    monkeypatch.setattr(svc, "n_ids_de_odfs", _n_ids)
    monkeypatch.setattr(svc, "datos_de_odfs", _datos)
    cuerpo = _cliente_user(monkeypatch).get(
        f"/api/infra/cromo/servicios/{SERVICIO}/camino-optico/caminos"
    ).json()

    assert cuerpo["tramos"][0]["odfs"] == [
        {"odf_n_id": 777, "odf_nombre": "ODF INTERMEDIA", "odf_clase": 69},
        {"odf_n_id": 6646686, "odf_nombre": "NODO KORN", "odf_clase": 86},
    ]
    assert cuerpo["residuales"][0]["odfs"] == [
        {"odf_n_id": 888, "odf_nombre": "ODF DEL RESIDUAL", "odf_clase": 69}
    ]
    assert cuerpo["no_cubiertos"] == 1
    assert cuerpo["tope_llamadas"] is False
    assert cuerpo["segmentos"] == 1


def test_caminos_expone_adicionales_completos_y_posicion_vigente(monkeypatch):
    """93150 con O-1252871-1:1,2 declarada: los vigentes son el camino viejo (7028862/63) y el nuevo
    (6799280) queda como adicional descargable, con por qué posición sale y con qué etiqueta. Los
    ids de ODF de los adicionales también se normalizan a n_id."""
    from core.services.cromo import servicio_odf_confirmacion as svc
    from core.services.cromo.servicio_posicion_vigente import AvisoPosicion
    from core.services.cromo.tracking_service import (
        EstadoPosicion,
        ExtremoCamino,
        InfoAdicional,
        ResumenCamino,
        TrackingGenerado,
        TrackingsDelServicio,
    )

    _fake_session(monkeypatch)
    _fake_cromo_client(monkeypatch)

    def _odf(id_cromo, odf_id, patchera, conector):
        return ExtremoCamino(
            tipo="CONECTOR_ODF", id_cromo=id_cromo, clase=136, odf_id=odf_id, odf_clase=69,
            odf_nombre=f"ODF {odf_id}", patchera_nombre=patchera, conector_numero=conector,
        )

    def _t(pelo, nombre, rol, resumen):
        return TrackingGenerado(
            pelo_n_id=pelo, nombre_archivo=nombre, contenido="", desde_cache=True,
            generado_at=datetime(2026, 10, 21, tzinfo=timezone.utc), duracion_ms=None,
            pelos_camino=frozenset({pelo, pelo + 1}), extremos=resumen, rol=rol,
        )

    viejo = ResumenCamino(
        inicio=_odf(8604882, 6644560, "O-1252871-1", "1"), fin=_odf(1, 6644536, "O-1252734-1", "11")
    )
    nuevo = ResumenCamino(
        inicio=_odf(2, 6642000, "O-1239921-1", "19"), fin=_odf(3, 6642001, "O-1239922-1", "1"),
        odfs=(6642555,),
    )
    vigente = _t(7028862, "93150 CROMO T1 pelo 7028862.txt", "VIGENTE", viejo)
    adicional = _t(6799280, "93150 CROMO A1 pelo 6799280.txt", "ADICIONAL", nuevo)
    aviso = AvisoPosicion(
        conector_n_id=8604883, posicion="O-1252871-1:2", codigo="PELO_DANADO", retirada=False,
        declaracion_id=2, pelo_declarado=7028863, detalle={"pelo": 7028900, "estado": "Cortado"},
    )
    _fake_trackings_del_servicio(
        monkeypatch,
        TrackingsDelServicio(
            tramos=[vigente], residuales=[], errores=[], completo=True,
            adicionales=[adicional],
            info_adicionales=[
                InfoAdicional(
                    pelo_n_id=6799280, origen="ETIQUETADO",
                    posiciones=(("O-1239922-1", "1"),), etiquetas=("93150",),
                )
            ],
            caminos_resueltos=[vigente, adicional],
            posicion=EstadoPosicion(
                declaradas=[object()], aplicada=True, etiqueta="O-1252871-1:1,2", avisos=[aviso]
            ),
        ),
    )
    vistos: list[int] = []

    async def _n_ids(_sesion, ids):
        vistos.extend(ids)
        return {}

    monkeypatch.setattr(svc, "n_ids_de_odfs", _n_ids)
    cuerpo = _cliente_user(monkeypatch).get(
        f"/api/infra/cromo/servicios/{SERVICIO}/camino-optico/caminos"
    ).json()

    assert cuerpo["tramos"][0]["rol"] == "VIGENTE" and cuerpo["tramos"][0]["completo"] is True
    (a,) = cuerpo["adicionales"]
    assert set(a) == {
        "n", "pelo_n_id", "nombre_archivo", "pelos_en_camino", "extremos", "odfs", "desde_cache",
        "completo", "origen", "posiciones", "etiquetas",
    }
    assert a["n"] == 1 and a["pelo_n_id"] == 6799280
    assert a["nombre_archivo"] == "93150 CROMO A1 pelo 6799280.txt"
    assert a["pelos_en_camino"] == 2 and a["desde_cache"] is True and a["completo"] is True
    assert a["origen"] == "ETIQUETADO"
    assert a["posiciones"] == "O-1239922-1:1" and a["etiquetas"] == ["93150"]
    assert a["extremos"]["a"]["patchera_nombre"] == "O-1239921-1"
    assert [o["odf_n_id"] for o in a["odfs"]] == [6642555, 6642000, 6642001]
    assert cuerpo["caminos_resueltos"] == 2
    assert {6642000, 6642001, 6642555} <= set(vistos)
    assert cuerpo["posicion_vigente"] == {
        "declarada": True,
        "aplicada": True,
        "posiciones": "O-1252871-1:1,2",
        "avisos": [
            {
                "conector_n_id": 8604883,
                "posicion": "O-1252871-1:2",
                "codigo": "PELO_DANADO",
                "retirada": False,
                "texto": (
                    "La posición vigente O-1252871-1:2 se mantiene, pero su camino pasa por el pelo "
                    "7028900 en estado «Cortado» y no hay otro camino completo sano."
                ),
            }
        ],
    }
