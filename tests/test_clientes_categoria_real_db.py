# Nombre de archivo: test_clientes_categoria_real_db.py
# Ubicación de archivo: tests/test_clientes_categoria_real_db.py
# Descripción: Sincronización y operaciones de clientes por categoría contra el Postgres real de dev

"""Corre `core/services/clientes_categoria_service.py` contra el Postgres de dev con datos
sintéticos: servicios `99996xx` y clientes con nombre `ZZTEST …` (no chocan con datos reales).

Cada test hace `commit` (prueba también el ciclo de vida de la tabla temporal `ON COMMIT DROP`) y
el fixture borra todo lo sintético al final. La sincronización se llama siempre con `claves=` de
las claves sintéticas: nunca se corre un sync global contra dev desde los tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from core.services.clientes_categoria_service import (
    ClienteCategoriaError,
    agregar_alias,
    aplicar_lista,
    cambiar_categoria,
    claves_de_nombres,
    fusionar_clientes,
    listar_clientes_por_categoria,
    normalizar_clave_cliente,
    previsualizar_lista,
    quitar_alias,
    resolver_cliente,
    sincronizar_categorias,
)
from core.services.servicios_categoria_service import CategoriaInvalidaError
from db.models.infra import Cliente
from db.session import SessionLocal
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

PREFIJO_SERVICIO = "99996"


def _limpiar() -> None:
    with SessionLocal() as s:
        s.execute(text("DELETE FROM app.servicios WHERE servicio_id LIKE :p"), {"p": f"{PREFIJO_SERVICIO}%"})
        s.execute(
            text(
                "DELETE FROM app.clientes WHERE nombre LIKE 'ZZTEST %' OR nombre LIKE 'Zztest %' "
                "OR id IN (SELECT cliente_id FROM app.clientes_alias WHERE clave LIKE 'ZZTEST %')"
            )
        )
        s.commit()


@pytest.fixture
def sesion():
    _limpiar()
    s = SessionLocal()
    contador = iter(range(1, 100))

    def crear_servicio(
        nombre: str,
        *,
        sla: int | None = None,
        categoria: int | None = None,
        excepcion: bool = False,
    ) -> int:
        numero = f"{PREFIJO_SERVICIO}{next(contador):02d}"
        return s.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, nombre_cliente, categoria, categoria_sla, "
                "categoria_excepcion, estado_servicio) VALUES (:sid, :n, :c, :sla, :e, 'ACTIVO') RETURNING id"
            ),
            {"sid": numero, "n": nombre, "c": categoria, "sla": sla, "e": excepcion},
        ).scalar_one()

    s.crear_servicio = crear_servicio  # type: ignore[attr-defined]
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        _limpiar()


def _categoria_servicio(s, servicio_pk: int) -> int | None:
    return s.execute(text("SELECT categoria FROM app.servicios WHERE id = :i"), {"i": servicio_pk}).scalar_one()


def _cliente(s, nombre: str) -> Cliente:
    cliente = resolver_cliente(s, nombre)
    assert cliente is not None, nombre
    return cliente


def test_sync_registra_variantes_moda_sla_y_respeta_excepcion(sesion) -> None:
    s = sesion
    a1 = s.crear_servicio("ZZTEST BANCO UNO SA", sla=3, categoria=6)
    a2 = s.crear_servicio("ZZTEST BANCO UNO SA", sla=3, categoria=6)
    b = s.crear_servicio("ZZTEST BANCO UNO S A U", sla=5, categoria=6)
    c = s.crear_servicio("Zztest Banco Uno SA", categoria=0)
    excepcion = s.crear_servicio("ZZTEST BANCO UNO SA", sla=3, categoria=1, excepcion=True)
    s.commit()

    claves = claves_de_nombres(["ZZTEST BANCO UNO SA", "Zztest Banco Uno SA", "ZZTEST BANCO UNO S A U"])
    assert claves == {"ZZTEST BANCO UNO"}
    resumen = sincronizar_categorias(s, claves)
    s.commit()

    assert resumen.clientes_creados == 1
    assert resumen.clientes_recalculados == 1
    assert resumen.servicios_actualizados == 4
    cliente = _cliente(s, "zztest banco uno s.a.")
    assert cliente.nombre == "ZZTEST BANCO UNO SA"  # la grafía más frecuente
    assert cliente.clave == "ZZTEST BANCO UNO"
    assert cliente.categoria == 3  # moda 3 (3 votos con la excepción) sobre 5 (1 voto)
    assert cliente.origen_categoria.value == "SLA"
    assert cliente.a_revisar is True
    assert [_categoria_servicio(s, x) for x in (a1, a2, b, c)] == [3, 3, 3, 3]
    assert _categoria_servicio(s, excepcion) == 1

    # Idempotente: un segundo sync (otra transacción) no crea ni actualiza nada.
    resumen2 = sincronizar_categorias(s, claves)
    s.commit()
    assert resumen2.to_dict() == {"clientes_creados": 0, "clientes_recalculados": 0, "servicios_actualizados": 0}


def test_empate_toma_la_mas_alta_y_sin_sla_con_servicios_queda_cero(sesion) -> None:
    s = sesion
    s.crear_servicio("ZZTEST EMPATE SRL", sla=2)
    s.crear_servicio("ZZTEST EMPATE SRL", sla=4)
    placeholder = s.crear_servicio("ZZTEST PLACEHOLDER", categoria=0)
    sin_datos = s.crear_servicio("ZZTEST SIN DATOS", categoria=None)
    s.commit()

    sincronizar_categorias(s, {"ZZTEST EMPATE", "ZZTEST PLACEHOLDER", "ZZTEST SIN DATOS"})
    s.commit()

    empate = _cliente(s, "ZZTEST EMPATE SRL")
    assert (empate.categoria, empate.origen_categoria.value, empate.a_revisar) == (4, "SLA", True)
    for nombre, servicio in (("ZZTEST PLACEHOLDER", placeholder), ("ZZTEST SIN DATOS", sin_datos)):
        cliente = _cliente(s, nombre)
        assert (cliente.categoria, cliente.origen_categoria.value) == (0, "AUTO"), nombre
        assert _categoria_servicio(s, servicio) == 0

    # Ida y vuelta: AUTO 0 → MANUAL 3 → AUTO vuelve a 0 (no depende de servicios.categoria = 0).
    cliente_id = _cliente(s, "ZZTEST SIN DATOS").id
    cambiar_categoria(s, [cliente_id], 3, "admin-test")
    s.commit()
    assert _categoria_servicio(s, sin_datos) == 3
    cambiar_categoria(s, [cliente_id], None, "admin-test", automatico=True)
    s.commit()
    cliente = s.get(Cliente, cliente_id)
    assert (cliente.categoria, cliente.origen_categoria.value) == (0, "AUTO")
    assert _categoria_servicio(s, sin_datos) == 0


def test_cliente_sin_servicios_vuelto_a_auto_queda_null(sesion) -> None:
    s = sesion
    aplicar_lista(s, ["ZZTEST SOLO EN LISTA"], 5, "agregar", "admin-test")
    s.commit()
    cliente = _cliente(s, "ZZTEST SOLO EN LISTA")
    assert (cliente.categoria, cliente.origen_categoria.value) == (5, "LISTA")

    aplicar_lista(s, ["ZZTEST OTRO DE LA LISTA"], 5, "reemplazar", "admin-test")
    s.commit()
    cliente = _cliente(s, "ZZTEST SOLO EN LISTA")
    assert (cliente.categoria, cliente.origen_categoria.value) == (None, "AUTO")


def test_cambiar_categoria_manual_y_volver_a_automatico(sesion) -> None:
    s = sesion
    svc = s.crear_servicio("ZZTEST MANUAL SA", sla=5)
    s.commit()
    sincronizar_categorias(s, {"ZZTEST MANUAL"})
    s.commit()
    cliente_id = _cliente(s, "ZZTEST MANUAL").id

    resultado = cambiar_categoria(s, [cliente_id, 987654321], 2, "admin-test")
    s.commit()
    assert resultado["actualizados"] == 1
    assert resultado["no_encontrados"] == [987654321]
    cliente = s.get(Cliente, cliente_id)
    assert (cliente.categoria, cliente.origen_categoria.value, cliente.actualizado_por) == (2, "MANUAL", "admin-test")
    assert _categoria_servicio(s, svc) == 2

    # Un sync posterior no pisa una categoría MANUAL.
    assert sincronizar_categorias(s, {"ZZTEST MANUAL"}).clientes_recalculados == 0
    s.commit()
    assert s.get(Cliente, cliente_id).categoria == 2

    # "Sin categorizar" manual.
    cambiar_categoria(s, [cliente_id], None, "admin-test")
    s.commit()
    assert s.get(Cliente, cliente_id).categoria is None
    assert _categoria_servicio(s, svc) is None

    cambiar_categoria(s, [cliente_id], None, "admin-test", automatico=True)
    s.commit()
    cliente = s.get(Cliente, cliente_id)
    assert (cliente.categoria, cliente.origen_categoria.value) == (5, "SLA")
    assert _categoria_servicio(s, svc) == 5

    with pytest.raises(CategoriaInvalidaError):
        cambiar_categoria(s, [cliente_id], 7, "admin-test")


def test_lista_previsualiza_sin_escribir_y_aplica_agregar(sesion) -> None:
    s = sesion
    sube = s.crear_servicio("ZZTEST LISTA SUBE SA", sla=2)
    baja = s.crear_servicio("ZZTEST LISTA BAJA SA", sla=6)
    igual = s.crear_servicio("ZZTEST LISTA IGUAL SA", sla=4)
    s.commit()
    sincronizar_categorias(s, {"ZZTEST LISTA SUBE", "ZZTEST LISTA BAJA", "ZZTEST LISTA IGUAL"})
    s.commit()

    nombres = [
        "ZZTEST LISTA SUBE S.A.",
        "zztest lista sube",  # duplicado por clave
        "  ",
        "ZZTEST LISTA BAJA",
        "ZZTEST LISTA IGUAL SRL",
        "ZZTEST LISTA SUBEE",  # sin match, parecido a SUBE
    ]
    previa = previsualizar_lista(s, nombres, 4, "agregar", "admin-test")
    s.commit()
    assert [x["nombre"] for x in previa.sube] == ["ZZTEST LISTA SUBE SA"]
    assert [x["nombre"] for x in previa.baja] == ["ZZTEST LISTA BAJA SA"]
    assert [x["nombre"] for x in previa.sin_cambio] == ["ZZTEST LISTA IGUAL SA"]
    assert previa.nuevos == ["ZZTEST LISTA SUBEE"]
    assert [c["nombre"] for c in previa.sugerencias["ZZTEST LISTA SUBEE"]][0] == "ZZTEST LISTA SUBE SA"
    assert previa.quitados == []
    # No escribió nada.
    assert _cliente(s, "ZZTEST LISTA SUBE").categoria == 2
    assert resolver_cliente(s, "ZZTEST LISTA SUBEE") is None

    resultado = aplicar_lista(s, nombres, 4, "agregar", "admin-test")
    s.commit()
    assert resultado["creados"] == 1
    for nombre in ("ZZTEST LISTA SUBE", "ZZTEST LISTA BAJA", "ZZTEST LISTA IGUAL", "ZZTEST LISTA SUBEE"):
        cliente = _cliente(s, nombre)
        assert (cliente.categoria, cliente.origen_categoria.value) == (4, "LISTA"), nombre
    assert [_categoria_servicio(s, x) for x in (sube, baja, igual)] == [4, 4, 4]


def test_lista_reemplazar_devuelve_a_auto_los_que_no_vienen(sesion) -> None:
    s = sesion
    queda = s.crear_servicio("ZZTEST REEMPLAZO QUEDA", sla=1)
    sale = s.crear_servicio("ZZTEST REEMPLAZO SALE", sla=2)
    s.commit()
    aplicar_lista(s, ["ZZTEST REEMPLAZO QUEDA", "ZZTEST REEMPLAZO SALE"], 5, "agregar", "admin-test")
    s.commit()
    assert _categoria_servicio(s, sale) == 5

    previa = previsualizar_lista(s, ["ZZTEST REEMPLAZO QUEDA"], 5, "reemplazar")
    assert [q["nombre"] for q in previa.quitados] == ["ZZTEST REEMPLAZO SALE"]

    aplicar_lista(s, ["ZZTEST REEMPLAZO QUEDA"], 5, "reemplazar", "admin-test")
    s.commit()
    saliente = _cliente(s, "ZZTEST REEMPLAZO SALE")
    assert (saliente.categoria, saliente.origen_categoria.value) == (2, "SLA")
    assert _categoria_servicio(s, sale) == 2
    assert _categoria_servicio(s, queda) == 5


def test_fusionar_clientes_y_alias(sesion) -> None:
    s = sesion
    corto = s.crear_servicio("ZZTEST EMPRESA SATELITAL (ZZSAT)", sla=3)
    largo = s.crear_servicio("ZZTEST EMPRESA SATELITAL SOCIEDAD ANONIMA ZZSAT", sla=6)
    largo2 = s.crear_servicio("ZZTEST EMPRESA SATELITAL SOCIEDAD ANONIMA ZZSAT", sla=6)
    s.commit()
    claves = claves_de_nombres(
        ["ZZTEST EMPRESA SATELITAL (ZZSAT)", "ZZTEST EMPRESA SATELITAL SOCIEDAD ANONIMA ZZSAT"]
    )
    assert len(claves) == 2  # no colapsan solos
    sincronizar_categorias(s, claves)
    s.commit()
    destino = _cliente(s, "ZZTEST EMPRESA SATELITAL (ZZSAT)")
    origen = _cliente(s, "ZZTEST EMPRESA SATELITAL SOCIEDAD ANONIMA ZZSAT")
    assert destino.id != origen.id

    resultado = fusionar_clientes(s, destino.id, [origen.id])
    s.commit()
    assert resultado["alias_movidos"] == 1
    assert s.get(Cliente, origen.id) is None
    fusionado = s.get(Cliente, destino.id)
    assert fusionado.categoria == 6  # recalculado con los servicios sumados (6 x2 sobre 3)
    assert [_categoria_servicio(s, x) for x in (corto, largo, largo2)] == [6, 6, 6]

    with pytest.raises(ClienteCategoriaError):
        fusionar_clientes(s, destino.id, [destino.id])


def test_agregar_alias_absorbe_cliente_autocreado_y_quitar_alias(sesion) -> None:
    s = sesion
    s.crear_servicio("ZZTEST CANONICO", sla=4)
    variante = s.crear_servicio("ZZTEST VARIANTE RARA", sla=1)
    s.commit()
    sincronizar_categorias(s, {"ZZTEST CANONICO", "ZZTEST VARIANTE RARA"})
    s.commit()
    canonico = _cliente(s, "ZZTEST CANONICO")
    autocreado_id = _cliente(s, "ZZTEST VARIANTE RARA").id
    cambiar_categoria(s, [canonico.id], 3, "admin-test")
    s.commit()

    alias = agregar_alias(s, canonico.id, "ZZTEST VARIANTE RARA")
    s.commit()
    assert alias.cliente_id == canonico.id
    assert alias.origen == "MANUAL"
    assert s.get(Cliente, autocreado_id) is None
    assert _categoria_servicio(s, variante) == 3

    # El único alias de un cliente LISTA/MANUAL no se mueve: hay que fusionar.
    s.crear_servicio("ZZTEST FIJADO A MANO", sla=2)
    s.commit()
    sincronizar_categorias(s, {"ZZTEST FIJADO A MANO"})
    s.commit()
    fijado_id = _cliente(s, "ZZTEST FIJADO A MANO").id
    cambiar_categoria(s, [fijado_id], 6, "admin-test")
    s.commit()
    with pytest.raises(ClienteCategoriaError, match="fusionar"):
        agregar_alias(s, canonico.id, "ZZTEST FIJADO A MANO")
    s.rollback()
    assert s.get(Cliente, fijado_id) is not None
    assert _cliente(s, "ZZTEST FIJADO A MANO").id == fijado_id

    # El alias canónico no se puede quitar.
    canonico_alias = [a for a in s.get(Cliente, canonico.id).alias if a.clave == "ZZTEST CANONICO"][0]
    with pytest.raises(ClienteCategoriaError, match="canónico"):
        quitar_alias(s, canonico_alias.id)

    # Quitar la variante la deja como un cliente propio (AUTO/SLA) en el sync.
    quitar_alias(s, alias.id)
    s.commit()
    nuevo = _cliente(s, "ZZTEST VARIANTE RARA")
    assert nuevo.id != canonico.id
    assert (nuevo.categoria, nuevo.origen_categoria.value) == (1, "SLA")
    assert _categoria_servicio(s, variante) == 1


def test_listar_clientes_por_categoria(sesion) -> None:
    s = sesion
    s.crear_servicio("ZZTEST Álamo SA", sla=6)
    s.crear_servicio("ZZTEST alamo bis", sla=6, categoria=2, excepcion=True)
    s.crear_servicio("ZZTEST BETA", categoria=None)
    s.commit()
    sincronizar_categorias(s, claves_de_nombres(["ZZTEST Álamo SA", "ZZTEST alamo bis", "ZZTEST BETA"]))
    s.commit()
    aplicar_lista(s, ["ZZTEST GAMMA SIN SERVICIOS"], None, "agregar", "admin-test")  # "sin categorizar"
    s.commit()

    grupos = listar_clientes_por_categoria(s)
    s.commit()
    assert list(grupos) == ["6", "5", "4", "3", "2", "1", "0", "sin"]
    seis = [c for c in grupos["6"] if c["nombre"].startswith("ZZTEST")]
    assert [c["nombre"] for c in seis] == ["ZZTEST alamo bis", "ZZTEST Álamo SA"]
    alamo = seis[1]
    assert alamo["servicios"] == 1
    assert alamo["excepciones"] == 0
    assert alamo["alias"] == [
        {"id": alamo["alias"][0]["id"], "nombre_original": "ZZTEST Álamo SA", "origen": "AUTO", "canonico": True}
    ]
    bis = seis[0]
    assert (bis["servicios"], bis["excepciones"]) == (1, 1)
    cero = [c for c in grupos["0"] if c["nombre"].startswith("ZZTEST")]
    assert [c["nombre"] for c in cero] == ["ZZTEST BETA"]  # tiene servicios sin dato SLA
    sin = [c for c in grupos["sin"] if c["nombre"].startswith("ZZTEST")]
    assert [(c["nombre"], c["servicios"]) for c in sin] == [("ZZTEST GAMMA SIN SERVICIOS", 0)]
    assert normalizar_clave_cliente("ZZTEST Álamo SA") == "ZZTEST ALAMO"

    # `canonico` distingue el alias que no se puede quitar (clave == Cliente.clave) del resto.
    agregar_alias(s, alamo["id"], "ZZTEST Álamo Variante")
    s.commit()
    alamo = next(c for c in listar_clientes_por_categoria(s)["6"] if c["id"] == alamo["id"])
    s.commit()
    assert {a["nombre_original"]: a["canonico"] for a in alamo["alias"]} == {
        "ZZTEST Álamo SA": True,
        "ZZTEST Álamo Variante": False,
    }


def test_endpoint_heredar_quita_excepcion_y_vuelve_a_la_del_cliente(sesion) -> None:
    from fastapi.testclient import TestClient

    from api.app.main import app

    s = sesion
    s.crear_servicio("ZZTEST HEREDAR SA", sla=4)
    excepcion = s.crear_servicio("ZZTEST HEREDAR SA", sla=4, categoria=1, excepcion=True)
    s.commit()
    sincronizar_categorias(s, {"ZZTEST HEREDAR"})
    s.commit()
    assert _categoria_servicio(s, excepcion) == 1

    respuesta = TestClient(app).patch(
        f"/servicios/{excepcion}/categoria/heredar", headers={"Authorization": "Bearer test-api-key"}
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["categoria"] == 4
    s.expire_all()
    fila = s.execute(
        text("SELECT categoria, categoria_excepcion FROM app.servicios WHERE id = :i"), {"i": excepcion}
    ).one()
    assert tuple(fila) == (4, False)


def test_endpoints_lista_por_http_previsualiza_archivo_y_aplica_json(sesion) -> None:
    import io

    import pandas as pd
    from fastapi.testclient import TestClient

    from api.app.main import app

    s = sesion
    sube = s.crear_servicio("ZZTEST HTTP SUBE SA", sla=2)
    s.commit()
    sincronizar_categorias(s, {"ZZTEST HTTP SUBE"})
    s.commit()

    buffer = io.BytesIO()
    pd.DataFrame({"Id": ["1", "2"], "Nombre Cliente": ["ZZTEST HTTP SUBE S.A.", "ZZTEST HTTP NUEVO"]}).to_excel(
        buffer, index=False, engine="openpyxl"
    )
    http = TestClient(app)
    headers = {"Authorization": "Bearer test-api-key", "X-Usuario": "admin-http-test"}

    previa = http.post(
        "/clientes/lista/previsualizar",
        files={"file": ("lista.xlsx", buffer.getvalue(), "application/octet-stream")},
        data={"categoria": "5", "modo": "agregar"},
        headers=headers,
    )

    assert previa.status_code == 200, previa.text
    cuerpo = previa.json()
    assert [x["nombre"] for x in cuerpo["sube"]] == ["ZZTEST HTTP SUBE SA"]
    assert cuerpo["nuevos"] == ["ZZTEST HTTP NUEVO"]
    s.expire_all()
    assert _cliente(s, "ZZTEST HTTP SUBE").categoria == 2  # previsualizar no escribe
    assert resolver_cliente(s, "ZZTEST HTTP NUEVO") is None

    aplicado = http.post(
        "/clientes/lista/aplicar",
        json={"nombres": ["ZZTEST HTTP SUBE S.A.", "ZZTEST HTTP NUEVO"], "categoria": 5},
        headers=headers,
    )

    assert aplicado.status_code == 200, aplicado.text
    assert aplicado.json()["creados"] == 1
    s.expire_all()
    cliente = _cliente(s, "ZZTEST HTTP SUBE")
    assert (cliente.categoria, cliente.origen_categoria.value, cliente.actualizado_por) == (
        5,
        "LISTA",
        "admin-http-test",
    )
    assert _categoria_servicio(s, sube) == 5


def test_search_servicios_token_sin_filtra_sin_categorizar(sesion) -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from api.app.main import app
    from db.session import async_engine, get_async_db

    s = sesion
    sin = s.crear_servicio("ZZTEST SEARCH SIN SA")
    con = s.crear_servicio("ZZTEST SEARCH SIN SA", categoria=3)
    s.crear_servicio("ZZTEST SEARCH SIN SA", categoria=5)
    s.commit()

    # NullPool: TestClient corre cada request en su propio event loop; el pool global no sirve entre loops.
    engine = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_async_db] = _override
    http = TestClient(app)
    headers = {"Authorization": "Bearer test-api-key"}

    def _ids(categoria: str) -> set[int]:
        r = http.get(
            "/servicios/search", params={"cliente": "ZZTEST SEARCH SIN", "categoria": categoria}, headers=headers
        )
        assert r.status_code == 200, r.text
        return {item["id"] for item in r.json()["servicios"]}

    try:
        assert _ids("sin") == {sin}
        assert _ids("sin,3") == {sin, con}
    finally:
        app.dependency_overrides.pop(get_async_db, None)
