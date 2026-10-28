# Nombre de archivo: test_camaras_consulta.py
# Ubicación de archivo: tests/test_camaras_consulta.py
# Descripción: Tests de la smart search de Cámaras (core/services/camaras_consulta.py)

from __future__ import annotations

from types import SimpleNamespace

from core.services import camaras_consulta as cc
from db.models.infra import CamaraEstado, CamaraOrigenDatos


def _camara(**kw):
    base = dict(
        nombre="Cámara Central", direccion="Av. Rivadavia 100", fontine_id="FON-77",
        estado=CamaraEstado.LIBRE, origen_datos=CamaraOrigenDatos.TRACKING,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# --- normalizar_terminos -----------------------------------------------------------------------

def test_normalizar_strip_y_descarta_vacios():
    assert cc.normalizar_terminos(["  ruta 5 ", "", "   ", "x"]) == ["ruta 5", "x"]


def test_normalizar_conserva_repetidos_y_mayusculas():
    assert cc.normalizar_terminos(["A", "a"]) == ["A", "a"]


def test_normalizar_lista_vacia():
    assert cc.normalizar_terminos([]) == []


# --- condicion_termino (SQL) -------------------------------------------------------------------

def _sql(termino: str) -> str:
    from sqlalchemy.dialects import postgresql

    return str(cc.condicion_termino(termino).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))


def test_condicion_busca_en_cada_campo():
    sql = _sql("central")
    for columna in ("camaras.nombre", "camaras.direccion", "camaras.fontine_id", "servicios.servicio_id", "cables.nombre"):
        assert f"{columna} ILIKE" in sql, columna
    assert "ruta_empalme_association" in sql and "servicio_empalme_association" in sql


def test_condicion_servicios_de_botellas_y_legacy_solo_sin_rutas():
    sql = _sql("svc")
    # raíz del grupo: la propia cámara o la padre de la Botella
    assert "coalesce(camaras_1.camara_padre_id, camaras_1.id)" in sql
    assert "NOT IN" in sql


def test_condicion_escapa_metacaracteres_de_like():
    assert "'%%' || '/%%/_' || '%%' ESCAPE '/'" in _sql("%_")


def test_condicion_estado_y_origen_por_valor_del_enum():
    assert "camaras.estado IN ('LIBRE')" in _sql("libre")
    assert "camaras.estado IN ('OPERATIVA'" not in _sql("operativa")
    assert "camaras.estado IN ('NO_OPERATIVA')" in _sql("operativa")
    assert "camaras.origen_datos IN ('MANUAL')" in _sql("MANUAL")
    assert "camaras.origen_datos IN ('INFERIDO', 'INFERIDO_CROMO')" in _sql("inferido")


def test_condicion_sin_estado_ni_origen_si_el_termino_no_aparece():
    sql = _sql("zzz")
    assert "camaras.estado IN" not in sql and "camaras.origen_datos IN" not in sql


# --- filtro de estado / no operativas ---------------------------------------------------------

class _QueryFalsa:
    def __init__(self, filtros, camaras):
        self.filtros = filtros
        self._camaras = camaras

    def filter(self, *criterios):
        from sqlalchemy.dialects import postgresql

        for c in criterios:
            self.filtros.append(str(c.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})))
        return self

    def options(self, *_):
        return self

    def order_by(self, *_):
        return self

    def offset(self, *_):
        return self

    def limit(self, *_):
        return self

    def count(self):
        return len(self._camaras)

    def all(self):
        return list(self._camaras)


class _SesionFalsa:
    def __init__(self, camaras=()):
        self.filtros: list[str] = []
        self._camaras = camaras

    def query(self, *_):
        return _QueryFalsa(self.filtros, self._camaras)


def _buscar(sesion, terminos=(), **kw):
    args = dict(estado=None, incluir_no_operativas=False, limit=100, offset=0)
    args.update(kw)
    return cc.buscar_camaras_por_terminos(sesion, list(terminos), **args)


def _excluye_no_operativas(sesion) -> bool:
    return any("!=" in f and "NO_OPERATIVA" in f for f in sesion.filtros)


def test_por_defecto_excluye_no_operativas():
    s = _SesionFalsa()
    r = _buscar(s)
    assert _excluye_no_operativas(s)
    assert r.estado_filter is None


def test_toggle_incluir_no_operativas_no_filtra():
    s = _SesionFalsa()
    _buscar(s, incluir_no_operativas=True)
    assert not _excluye_no_operativas(s)


def test_chip_no_operativa_las_trae_aunque_el_toggle_este_apagado():
    s = _SesionFalsa()
    r = _buscar(s, estado=" no_operativa ", incluir_no_operativas=False)
    assert r.estado_filter == "NO_OPERATIVA"
    assert not _excluye_no_operativas(s)


def test_chip_otro_estado_mantiene_exclusion_de_no_operativas():
    s = _SesionFalsa()
    r = _buscar(s, estado="libre")
    assert r.estado_filter == "LIBRE"
    assert _excluye_no_operativas(s)


def test_estado_invalido_se_ignora():
    r = _buscar(_SesionFalsa(), estado="inexistente")
    assert r.estado_filter is None


def test_limit_y_offset_se_acotan():
    r = _buscar(_SesionFalsa(), limit=9999, offset=-5)
    assert (r.limit, r.offset) == (500, 0)


def test_terminos_agregan_una_condicion_sql_por_termino():
    s = _SesionFalsa()
    r = _buscar(s, ["  cam ", "norte"])
    assert sum("camaras.nombre ILIKE" in f for f in s.filtros) == 2
    assert r.terminos_aplicados == 2


def test_terminos_en_blanco_cuentan_cero_y_no_filtran():
    camaras = [_camara(empalmes=[], cables=[], botellas=[])]
    s = _SesionFalsa(camaras)
    r = _buscar(s, ["   "])
    assert r.total == 1 and r.terminos_aplicados == 0
    assert not any("ILIKE" in f for f in s.filtros)


# --- reuso de lo calculado (conteo de llamadas) -----------------------------------------------

def _con_contadores(monkeypatch):
    llamadas = {"rutas": 0, "servicios": 0}
    orig_r, orig_s = cc._collect_camara_rutas_info, cc._collect_camara_servicios_ids

    def rutas(*a, **k):
        llamadas["rutas"] += 1
        return orig_r(*a, **k)

    def servicios(*a, **k):
        llamadas["servicios"] += 1
        return orig_s(*a, **k)

    monkeypatch.setattr(cc, "_collect_camara_rutas_info", rutas)
    monkeypatch.setattr(cc, "_collect_camara_servicios_ids", servicios)
    return llamadas


def _camara_con_servicio(nombre, servicio_id, ruta_id):
    servicio = SimpleNamespace(servicio_id=servicio_id, alias_ids=None)
    ruta = SimpleNamespace(
        id=ruta_id, servicio=servicio, nombre="R", tipo=SimpleNamespace(value="PRINCIPAL"),
        empalmes=[SimpleNamespace(es_transito=True)], punta_a=None, punta_b=None,
    )
    return _camara(
        nombre=nombre, cables=[], botellas=[],
        empalmes=[SimpleNamespace(rutas=[ruta], servicios=[servicio])],
    )


def test_helpers_solo_para_la_pagina(monkeypatch):
    camaras = [_camara_con_servicio(f"C{i}", f"SVC-{i}", i) for i in range(3)]
    llamadas = _con_contadores(monkeypatch)
    r = _buscar(_SesionFalsa(camaras), ["c"])
    assert llamadas == {"rutas": 3, "servicios": 3}
    assert len(r.camaras) == 3
    assert r.camaras[0].servicios_ids == ["SVC-0"]
    assert r.camaras[0].rutas_info[0]["ruta_id"] == 0


def test_rutas_info_usa_sitio_descripcion_de_las_puntas():
    """Regresión: `PuntoTerminal` no tiene `.sitio`, tiene `sitio_descripcion`.

    Con puntos terminales cargados, la smart search y el detalle de Cámara daban 500.
    """
    camara = _camara_con_servicio("C1", "SVC-1", 7)
    ruta = camara.empalmes[0].rutas[0]
    ruta.punta_a = SimpleNamespace(sitio_descripcion="ODF MAIPU 316 1")
    ruta.punta_b = SimpleNamespace(sitio_descripcion=None)

    info = cc._collect_camara_rutas_info(camara)

    assert info[0]["punta_a_sitio"] == "ODF MAIPU 316 1"
    assert info[0]["punta_b_sitio"] is None


# --- orden explícito de las relaciones que llegan a la respuesta ---------------------------------


def test_relaciones_de_infra_ordenadas_por_id():
    """El orden de rutas/empalmes/botellas/servicios de la respuesta no depende del plan de la consulta:
    sin `order_by`, la carga por lote y la individual devolvían órdenes distintos."""
    from sqlalchemy import inspect

    from db.models.infra import Camara, Empalme, Servicio

    esperado = {
        (Camara, "empalmes"): ("empalmes", "id"),
        (Camara, "botellas"): ("camaras", "id"),
        (Empalme, "servicios"): ("servicios", "id"),
        (Empalme, "rutas"): ("rutas_servicio", "id"),
        (Servicio, "empalmes"): ("empalmes", "id"),
    }
    for (modelo, nombre), columna in esperado.items():
        orden = inspect(modelo).relationships[nombre].order_by
        assert orden, f"{modelo.__name__}.{nombre} sin order_by"
        assert [(c.table.name, c.name) for c in orden] == [columna], f"{modelo.__name__}.{nombre}: {orden!r}"


def test_carga_por_lote_incluye_rutas_de_empalmes_y_botellas():
    rutas = [o for o in cc._CARGA_POR_LOTE if "Empalme.rutas" in str(o.path)]
    assert len(rutas) == 4


# --- listar_camaras / serializar_camara_basica (P12, Task 3) -----------------------------------

class _SesionListado:
    """Doble de Session: `query(...)` devuelve una cadena que ignora filtros y entrega `camaras`."""

    def __init__(self, camaras):
        self._camaras = camaras
        self.filtros = []

    def query(self, *_a, **_k):
        sesion = self

        class _Q:
            def options(self, *_o):
                return self

            def filter(self, *c):
                sesion.filtros.extend(c)
                return self

            def order_by(self, *_o):
                return self

            def limit(self, n):
                sesion.limite = n
                return self

            def all(self):
                return list(sesion._camaras)

        return _Q()


def _ruta(rid, servicio_id):
    return SimpleNamespace(
        id=rid, nombre=f"R{rid}", tipo=SimpleNamespace(value="PRINCIPAL"),
        servicio=SimpleNamespace(servicio_id=servicio_id, alias_ids=None), empalmes=[],
        punta_a=None, punta_b=None,
    )


def test_listar_camaras_servicios_ordenados():
    emp = SimpleNamespace(rutas=[_ruta(1, "B"), _ruta(2, "A")], servicios=[])
    cam = _camara(id=1, empalmes=[emp], botellas=[])
    sesion = _SesionListado([cam])
    res = cc.listar_camaras(sesion, q=None, estado=None, limit=10)
    assert [e.servicios_ids for e in res] == [["A", "B"]]
    assert len(res[0].rutas_info) == 2


def test_listar_camaras_sin_rutas_usa_legacy():
    emp = SimpleNamespace(rutas=[], servicios=[SimpleNamespace(servicio_id="X")])
    cam = _camara(id=1, empalmes=[emp], botellas=[])
    res = cc.listar_camaras(_SesionListado([cam]), q=None, estado=None, limit=10)
    assert res[0].rutas_info == [] and res[0].servicios_ids == ["X"]


def test_listar_camaras_tope_de_limite():
    sesion = _SesionListado([])
    cc.listar_camaras(sesion, q=None, estado=None, limit=99999)
    assert sesion.limite == cc.LIMITE_MAXIMO


def test_serializar_camara_basica_claves():
    cam = _camara(id=3, latitud=1.5, longitud=2.5)
    d = cc.serializar_camara_basica(cc.CamaraEncontrada(cam, [], ["S1"]))
    assert list(d) == [
        "id", "nombre", "fontine_id", "direccion", "estado", "origen_datos", "latitud", "longitud", "servicios",
    ]
    assert d["servicios"] == ["S1"] and d["estado"] == "LIBRE" and d["origen_datos"] == "TRACKING"


def test_listar_camaras_precarga_camara_padre(monkeypatch):
    """Las Botellas que devuelve el listado serializan `camara_padre_nombre`: sin precarga, N+1."""
    sesion = _SesionListado([])
    opciones = []
    consulta = sesion.query

    def _query(*a, **k):
        q = consulta(*a, **k)
        original = q.options
        q.options = lambda *o: (opciones.extend(o), original(*o))[1]
        return q

    sesion.query = _query
    cc.listar_camaras(sesion, q=None, estado=None, limit=5)
    assert any("Camara.camara_padre" in str(o.path) for o in opciones)
    assert not any("Camara.camara_padre" in str(o.path) for o in cc._CARGA_POR_LOTE)
