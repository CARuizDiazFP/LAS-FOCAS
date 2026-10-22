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


# --- termino_coincide ---------------------------------------------------------------------------

def test_coincide_por_cada_campo():
    cam = _camara()
    assert cc.termino_coincide("central", cam, [], [])
    assert cc.termino_coincide("RIVADAVIA", cam, [], [])
    assert cc.termino_coincide("fon-77", cam, [], [])
    assert cc.termino_coincide("svc-9", cam, ["SVC-99"], [])
    assert cc.termino_coincide("troncal", cam, [], ["Troncal Norte"])
    assert cc.termino_coincide("libre", cam, [], [])
    assert cc.termino_coincide("tracking", cam, [], [])


def test_no_coincide_si_no_esta_en_ningun_campo():
    assert not cc.termino_coincide("zzz", _camara(), ["A1"], ["C1"])


def test_estado_y_origen_por_defecto_si_son_none():
    cam = _camara(estado=None, origen_datos=None)
    assert cc.termino_coincide("libre", cam, [], [])
    assert cc.termino_coincide("manual", cam, [], [])


def test_campos_none_no_rompen():
    cam = _camara(nombre=None, direccion=None, fontine_id=None)
    assert not cc.termino_coincide("x", cam, [], [])


# --- filtro de estado / no operativas ---------------------------------------------------------

class _QueryFalsa:
    def __init__(self, filtros, camaras):
        self.filtros = filtros
        self._camaras = camaras

    def filter(self, *criterios):
        for c in criterios:
            self.filtros.append(str(c.compile(compile_kwargs={"literal_binds": True})))
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


def test_terminos_filtran_en_python_y_paginan_despues():
    camaras = [
        _camara(nombre=f"Cam {i}", empalmes=[], cables=[], botellas=[]) for i in range(5)
    ]
    camaras[1].nombre = "Otra"
    r = _buscar(_SesionFalsa(camaras), ["  cam "], limit=2, offset=1)
    assert r.total == 4
    assert [e.camara.nombre for e in r.camaras] == ["Cam 2", "Cam 3"]
    assert r.terminos_aplicados == 1


def test_terminos_en_blanco_cuentan_cero_y_no_filtran():
    camaras = [_camara(empalmes=[], cables=[], botellas=[])]
    r = _buscar(_SesionFalsa(camaras), ["   "])
    assert r.total == 1 and r.terminos_aplicados == 0


def test_terminos_son_and():
    camaras = [
        _camara(nombre="Norte", direccion="Calle 1", empalmes=[], cables=[], botellas=[]),
        _camara(nombre="Norte", direccion="Calle 2", empalmes=[], cables=[], botellas=[]),
    ]
    r = _buscar(_SesionFalsa(camaras), ["norte", "CALLE 2"])
    assert r.total == 1


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


def test_con_terminos_helpers_se_llaman_una_vez_por_camara(monkeypatch):
    camaras = [_camara_con_servicio(f"C{i}", f"SVC-{i}", i) for i in range(4)]
    llamadas = _con_contadores(monkeypatch)
    r = _buscar(_SesionFalsa(camaras), ["c"], limit=2, offset=1)
    assert llamadas == {"rutas": 4, "servicios": 4}
    assert [e.camara.nombre for e in r.camaras] == ["C1", "C2"]
    assert r.camaras[0].servicios_ids == ["SVC-1"]
    assert r.camaras[0].rutas_info[0]["ruta_id"] == 1


def test_sin_terminos_helpers_solo_para_la_pagina(monkeypatch):
    camaras = [_camara_con_servicio(f"C{i}", f"SVC-{i}", i) for i in range(3)]
    llamadas = _con_contadores(monkeypatch)
    r = _buscar(_SesionFalsa(camaras))
    assert llamadas == {"rutas": 3, "servicios": 3}
    assert len(r.camaras) == 3


def test_match_por_servicio_y_and_con_empalme_real():
    camaras = [
        _camara_con_servicio("Norte", "SVC-10", 1),
        _camara_con_servicio("Sur", "SVC-10", 2),
        _camara_con_servicio("Norte", "SVC-20", 3),
    ]
    r = _buscar(_SesionFalsa(camaras), ["svc-10", "norte"])
    assert [e.rutas_info[0]["ruta_id"] for e in r.camaras] == [1]
    assert r.camaras[0].servicios_ids == ["SVC-10"]


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
