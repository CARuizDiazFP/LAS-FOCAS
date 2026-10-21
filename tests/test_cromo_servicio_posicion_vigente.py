# Nombre de archivo: test_cromo_servicio_posicion_vigente.py
# Ubicación de archivo: tests/test_cromo_servicio_posicion_vigente.py
# Descripción: Pruebas puras de la posición vigente por conector (modelo, posiciones posibles, declarar/retirar, validación y retiro) con una sesión fake que registra el SQL

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.services.cromo import servicio_posicion_vigente as pv
from core.services.cromo.tracking_service import ResumenCamino, TrackingGenerado

AHORA = datetime(2026, 10, 21, tzinfo=timezone.utc)


def test_modelo_usa_los_nombres_de_indice_de_la_migracion():
    """Sin nombres explícitos, autogenerate ve drift contra 20261021_01 (mismo caso que M4)."""
    from sqlalchemy import BigInteger
    from sqlalchemy.dialects.postgresql import ARRAY

    from db.models.cromo import ServicioPosicionVigente

    tabla = ServicioPosicionVigente.__table__
    assert tabla.schema == "app" and tabla.name == "servicio_posicion_vigente"
    indices = {i.name: i for i in tabla.indexes}
    assert set(indices) == {"ux_servicio_posicion_vigente_vigente", "ix_servicio_posicion_vigente_servicio"}
    unico = indices["ux_servicio_posicion_vigente_vigente"]
    assert unico.unique and [c.name for c in unico.columns] == ["servicio_id", "conector_n_id"]
    assert str(unico.dialect_options["postgresql"]["where"]) == "vigente"
    fk = next(iter(tabla.c.servicio_id.foreign_keys))
    assert fk.target_fullname == "app.servicios.id" and fk.ondelete == "CASCADE"

    tipo = tabla.c.pelos_candidatos.type
    assert isinstance(tipo, ARRAY) and isinstance(tipo.item_type, BigInteger)
    assert tabla.c.detalle_retiro.type.none_as_null is True


# ── Posiciones posibles, declarar y retirar (Task 2) ─────────────────────────────────────────


class _Resultado:
    def __init__(self, filas=(), rowcount=0, escalar=None):
        self._filas, self.rowcount, self._escalar = list(filas), rowcount, escalar

    def first(self):
        return self._filas[0] if self._filas else None

    def all(self):
        return self._filas

    def scalar(self):
        return self._escalar

    def scalar_one(self):
        return self._escalar


class _Sesion:
    """Responde por fragmento del SQL y anota cada ejecución, commits y rollbacks."""

    def __init__(self, *, posibles=(), declaradas=(), estados=(), cables=(), rowcount=1, escalar=None):
        self.posibles = list(posibles)
        self.declaradas = list(declaradas)
        self.estados = list(estados)
        self.cables = list(cables)
        self.rowcount = rowcount
        self.escalar = escalar
        self.ejecuciones: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.ejecuciones.append((sql, dict(params or {})))
        if "pg_advisory_xact_lock" in sql:
            return _Resultado()
        if sql.lstrip().startswith(("INSERT", "UPDATE")):
            return _Resultado(rowcount=self.rowcount)
        if "AS conector_n_id" in sql:
            return _Resultado(self.posibles)
        if "AS pelo_declarado" in sql:
            return _Resultado(self.declaradas)
        if "FROM app.cromo_pelos" in sql:
            return _Resultado(self.estados)
        if "FROM app.cromo_cables" in sql:
            return _Resultado(self.cables)
        return _Resultado(escalar=self.escalar, filas=[(self.escalar,)] if self.escalar else [])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    def escrituras(self):
        return [e for e in self.ejecuciones if e[0].lstrip().startswith(("INSERT", "UPDATE"))]


def _fila_posible(conector, numero, pelo, *, bandeja=8604881, bandeja_nombre="O-1252871-1",
                  cable=6600854, etiqueta="44649", por_resuelto=True, por_pelo=False, candidatos=None):
    return SimpleNamespace(
        conector_n_id=conector, odf_n_id=6644560, odf_nombre="ODF San Martin 137 P5 D", odf_clase=69,
        bandeja_n_id=bandeja, bandeja_nombre=bandeja_nombre, numero_conector=numero,
        pelo_n_id=pelo, numero_pelo="1", cable_n_id=cable, cable_nombre="F-PC-CC",
        etiqueta_pelo=etiqueta, estado_pelo="Utilizado", servicio_resuelto="93150",
        servicio_id_historico="44649", por_resuelto=por_resuelto, por_pelo=por_pelo,
        s_id="93150", s_primero="93150", s_alias=[], servicio_activo_ajeno=None,
        pelos_candidatos=candidatos if candidatos is not None else ([pelo] if pelo else []),
        patch_conector_n_id=None,
    )


def _posible(conector, numero, pelo, **kw) -> pv.PosicionPosible:
    return pv._posible_de_fila(_fila_posible(conector, numero, pelo, **kw))


def _fila_declarada(id_=1, conector=8604882, pelo=7028862, *, actual=7028862, existe=True, candidatos=None):
    return SimpleNamespace(
        id=id_, conector_n_id=conector, odf_n_id=6644560, odf_nombre="ODF San Martin 137 P5 D",
        bandeja_n_id=8604881, bandeja_nombre="O-1252871-1", numero_conector="1",
        pelo_declarado=pelo, pelos_candidatos=candidatos if candidatos is not None else [pelo],
        declarado_por="admin", declarado_en=AHORA, conector_existe=existe, pelo_actual=actual,
    )


def _declarada(**kw) -> pv.PosicionDeclarada:
    return pv._declarada_de_fila(_fila_declarada(**kw))


@pytest.mark.asyncio
async def test_posiciones_posibles_mapea_filas_y_marca_etiqueta_ajena():
    sesion = _Sesion(posibles=[
        _fila_posible(8604882, "1", 7028862),
        _fila_posible(8546314, "1", 6799280, etiqueta="93150", bandeja_nombre="O-1239922-1", por_pelo=True),
        _fila_posible(8546399, "7", None, etiqueta=None),
    ])

    posibles = await pv.posiciones_posibles(sesion, 4)

    assert [p.conector_n_id for p in posibles] == [8604882, 8546314, 8546399]
    viejo, nuevo, sin_pelo = posibles
    assert viejo.etiqueta_ajena is True and viejo.por_resuelto and not viejo.por_pelo
    assert viejo.posicion == "O-1252871-1:1"
    assert nuevo.etiqueta_ajena is False
    assert sin_pelo.pelo_n_id is None and sin_pelo.etiqueta_ajena is False
    sql, params = sesion.ejecuciones[0]
    assert params == {"servicio_id": 4}
    # Filtros compartidos: pelos excluidos a mano y pelos de otro servicio Activo.
    assert "app.cromo_servicio_pelo_excluido" in sql
    assert "ILIKE 'activo'" in sql
    assert "c.vigente" in sql


def test_listado_une_pelo_cable_y_odf_antes_del_where():
    """Regresión: el listado leía `p`, `cab` y `o` sin unirlos ("missing FROM-clause entry for table
    o" contra la DB real). Las guardas EXISTS no los necesitan y no los llevan."""
    sql = str(pv._SQL_POSICIONES_POSIBLES)
    where = sql.index("WHERE c.vigente")
    for join in (
        "LEFT JOIN app.cromo_pelos p ON",
        "LEFT JOIN app.cromo_cables cab ON",
        "LEFT JOIN app.cromo_odfs o ON",
    ):
        assert -1 < sql.find(join) < where, join
    assert "LEFT JOIN" not in str(pv._SQL_PELO_ES_DE_POSICION)
    assert "LEFT JOIN" not in str(pv._SQL_TIENE_POSICIONES)


def test_fragmento_de_otro_activo_es_reutilizable_con_otra_columna():
    fragmento = pv.SIN_PELO_DE_OTRO_SERVICIO_ACTIVO_SQL.format(pelo=":pelo_n_id")
    assert fragmento.lstrip().startswith("AND NOT")
    assert "mo.pelo_n_id = :pelo_n_id" in fragmento
    assert "{pelo}" not in fragmento


def test_pelos_de_posiciones_sin_nulos_ni_repetidos_en_orden():
    posibles = [
        _posible(1, "5", 7028862), _posible(2, "1", 7028862), _posible(3, "2", 7028863),
        _posible(4, "3", None),
    ]
    assert pv.pelos_de_posiciones(posibles) == [7028862, 7028863]


@pytest.mark.parametrize(
    ("elegido", "esperado"),
    [(8604882, 8604883), (8604883, 8604882), (8604886, None)],
    ids=["impar_va_al_siguiente", "par_va_al_anterior", "sin_par_en_las_posibles"],
)
def test_par_sugerido_hilo_contiguo_de_la_misma_bandeja(elegido, esperado):
    posibles = [
        _posible(8604882, "1", 7028862), _posible(8604883, "2", 7028863),
        _posible(8604886, "5", 7028870),
        _posible(9000001, "6", 1, bandeja=1, bandeja_nombre="OTRA"),  # mismo número, otra bandeja
    ]
    p = next(x for x in posibles if x.conector_n_id == elegido)
    assert pv.par_sugerido(p, posibles) == esperado


def test_par_sugerido_prefiere_el_mismo_cable():
    posibles = [
        _posible(10, "3", 100, cable=1), _posible(11, "4", 101, cable=2),  # par natural, otro cable
        _posible(12, "2", 102, cable=1),
    ]
    assert pv.par_sugerido(posibles[0], posibles) == 12
    # Sin vecino del mismo cable, queda el par natural.
    assert pv.par_sugerido(posibles[0], posibles[:2]) == 11


def test_par_sugerido_ignora_conectores_sin_pelo_y_numeros_no_numericos():
    posibles = [_posible(10, "1", 100), _posible(11, "2", None), _posible(12, "A", 102)]
    assert pv.par_sugerido(posibles[0], posibles) is None
    assert pv.par_sugerido(posibles[2], posibles) is None


def test_etiqueta_posiciones():
    assert pv.etiqueta_posiciones([("O-1252871-1", "1"), ("O-1252871-1", "2")]) == "O-1252871-1:1,2"
    assert (
        pv.etiqueta_posiciones([("B", "10"), ("A", "3"), ("B", "2"), ("B", "2")])
        == "B:2,10 y A:3"
    )
    assert pv.etiqueta_posiciones([]) == ""


@pytest.mark.asyncio
async def test_listar_declaradas_trae_foto_y_estado_actual_del_conector():
    sesion = _Sesion(declaradas=[_fila_declarada(candidatos=[7028862, 6799284])])

    (d,) = await pv.listar_declaradas(sesion, 4)

    assert d.posicion == "O-1252871-1:1" and d.pelo_declarado == 7028862
    assert d.pelos_candidatos == (7028862, 6799284)
    assert d.conector_existe is True and d.pelo_actual == 7028862
    sql, params = sesion.ejecuciones[0]
    assert "d.vigente" in sql and params == {"servicio_id": 4}


@pytest.mark.asyncio
async def test_declarar_toma_el_lock_hace_upsert_con_candidatos_y_commitea():
    sesion = _Sesion(
        posibles=[
            _fila_posible(8604882, "1", 7028862, candidatos=[7028862, 6799284]),
            _fila_posible(8604883, "2", 7028863),
        ],
        declaradas=[_fila_declarada(), _fila_declarada(2, 8604883, 7028863, actual=7028863)],
    )

    declaradas = await pv.declarar(sesion, 4, [8604882, 8604883, 8604882], usuario="admin")

    primero = sesion.ejecuciones[0]
    assert "pg_advisory_xact_lock" in primero[0] and primero[1]["servicio_id"] == 4
    escritas = sesion.escrituras()
    assert len(escritas) == 2  # el repetido no se escribe dos veces
    assert all("ON CONFLICT (servicio_id, conector_n_id) WHERE vigente" in sql for sql, _ in escritas)
    assert escritas[0][1] == {
        "servicio_id": 4, "conector_n_id": 8604882, "odf_n_id": 6644560, "bandeja_n_id": 8604881,
        "bandeja_nombre": "O-1252871-1", "numero_conector": "1", "pelo_n_id": 7028862,
        "pelos_candidatos": [7028862, 6799284], "usuario": "admin",
    }
    assert sesion.commits == 1 and sesion.rollbacks == 0
    assert [d.conector_n_id for d in declaradas] == [8604882, 8604883]


@pytest.mark.asyncio
async def test_declarar_conector_que_no_es_posicion_posible_no_escribe_nada():
    sesion = _Sesion(posibles=[_fila_posible(8604882, "1", 7028862)])

    with pytest.raises(pv.PosicionNoValida):
        await pv.declarar(sesion, 4, [8604882, 8595049], usuario="admin")

    assert sesion.escrituras() == [] and sesion.commits == 0 and sesion.rollbacks == 1


@pytest.mark.asyncio
async def test_declarar_conector_sin_pelo_no_escribe_nada():
    sesion = _Sesion(posibles=[_fila_posible(8604882, "1", 7028862), _fila_posible(8604886, "5", None)])

    with pytest.raises(pv.PosicionNoValida):
        await pv.declarar(sesion, 4, [8604882, 8604886], usuario="admin")

    assert sesion.escrituras() == [] and sesion.commits == 0


@pytest.mark.asyncio
async def test_declarar_lista_vacia_es_invalida_sin_consultar():
    sesion = _Sesion()
    with pytest.raises(pv.PosicionNoValida):
        await pv.declarar(sesion, 4, [], usuario="admin")
    assert sesion.ejecuciones == []


@pytest.mark.asyncio
async def test_retirar_condiciona_por_id_y_pelo_leido_y_commitea():
    sesion = _Sesion(rowcount=1)

    ok = await pv.retirar(
        sesion, 7, pelo_leido=7028862, motivo="PELO_CAMBIO", detalle={"declarado": 7028862, "actual": 1}
    )

    assert ok is True and sesion.commits == 1
    sql, params = sesion.escrituras()[0]
    assert "WHERE id = :id AND vigente AND pelo_n_id = :pelo_leido" in sql
    assert params["id"] == 7 and params["pelo_leido"] == 7028862
    assert params["motivo"] == "PELO_CAMBIO" and params["usuario"] == "auto"
    assert params["detalle"] == '{"declarado": 7028862, "actual": 1}'


@pytest.mark.asyncio
async def test_retirar_sin_fila_que_coincida_devuelve_false():
    sesion = _Sesion(rowcount=0)
    assert await pv.retirar(sesion, 7, pelo_leido=1, motivo="MANUAL", usuario="ana") is False
    assert sesion.escrituras()[0][1]["detalle"] is None


@pytest.mark.asyncio
async def test_retirar_motivo_invalido_no_consulta():
    sesion = _Sesion()
    with pytest.raises(ValueError):
        await pv.retirar(sesion, 7, pelo_leido=1, motivo="OTRO")
    assert sesion.ejecuciones == []


@pytest.mark.asyncio
async def test_retirar_manual_busca_la_declarada_vigente_del_conector():
    sesion = _Sesion(declaradas=[_fila_declarada(5, 8604882, 7028862)], rowcount=1)

    assert await pv.retirar_manual(sesion, 4, 8604882, usuario="ana") is True
    assert await pv.retirar_manual(sesion, 4, 999, usuario="ana") is False

    (sql, params), = sesion.escrituras()
    assert params["id"] == 5 and params["motivo"] == "MANUAL" and params["usuario"] == "ana"


@pytest.mark.asyncio
async def test_pelo_es_de_posicion_incluye_posibles_y_declaradas():
    sesion = _Sesion(escalar=True)
    assert await pv.pelo_es_de_posicion(sesion, 4, 7028862) is True
    sql, params = sesion.ejecuciones[0]
    assert params == {"servicio_id": 4, "pelo_n_id": 7028862}
    assert "app.servicio_posicion_vigente" in sql and "app.cromo_servicio_pelo_excluido" in sql
    assert "ILIKE 'activo'" in sql
    assert await pv.pelo_es_de_posicion(_Sesion(escalar=None), 4, 1) is False


@pytest.mark.asyncio
async def test_tiene_posiciones():
    sesion = _Sesion(escalar=True)
    assert await pv.tiene_posiciones(sesion, 4) is True
    sql, params = sesion.ejecuciones[0]
    assert "c.pelo_n_id IS NOT NULL" in sql and "app.servicio_posicion_vigente" in sql
    assert params == {"servicio_id": 4}
    assert await pv.tiene_posiciones(_Sesion(escalar=False), 4) is False


# ── Validación y retiro (Task 3) ─────────────────────────────────────────────────────────────

ESTADOS_DANADOS_REALES = [
    "Cortado", "Dañado", "CORTADO", "CORTADO AL RAS", "CORTADO AL RAZ", "BUFFER 6 CORTADO AL RAS",
    "CORTADO LADO BOT", "Cortado dentro del BUFFER", "buffer cortado al ras",
    "Cortado en Cra. Ramal Pilar Km 50.400 Calle Magnolias", "Fibra Dañada", "Fibra dañana",
]


@pytest.mark.parametrize("estado", ESTADOS_DANADOS_REALES)
def test_estados_reales_de_cortado_o_danado(estado):
    assert pv.es_estado_pelo_danado(estado) is True


@pytest.mark.parametrize(
    "estado", ["Utilizado", "Libre", "Reservado", "Cedidos", "En servicio", "OCUPADO", None, "", "  "]
)
def test_estados_sanos(estado):
    assert pv.es_estado_pelo_danado(estado) is False


def test_validar_en_db_sin_cambios_no_avisa():
    assert pv.validar_en_db([_declarada()]) == []


def test_validar_en_db_conector_inexistente_sin_pelo_y_pelo_cambio():
    avisos = pv.validar_en_db([
        _declarada(id_=1, existe=False, actual=None),
        _declarada(id_=2, conector=8604883, pelo=7028863, actual=None),
        _declarada(id_=3, conector=8604884, pelo=7028864, actual=1),
    ])
    assert [(a.declaracion_id, a.codigo, a.retirada) for a in avisos] == [
        (1, "CONECTOR_INEXISTENTE", True),
        (2, "SIN_PELO", True),
        (3, "PELO_CAMBIO", True),
    ]
    assert avisos[2].detalle == {"declarado": 7028864, "actual": 1}
    assert avisos[2].pelo_declarado == 7028864 and avisos[2].posicion == "O-1252871-1:1"


def test_validar_en_db_pelo_alternativo_del_mismo_conector_no_es_cambio():
    """La ingesta prefiere el cable propio y puede cambiar `pelo_n_id` cuando entra el de un tercero:
    si el pelo actual está entre los candidatos guardados, la declaración sigue valiendo."""
    assert pv.validar_en_db([_declarada(actual=6799284, candidatos=[7028862, 6799284])]) == []


def _tracking(pelo, pelos=(), cables=()):
    return TrackingGenerado(
        pelo_n_id=pelo, nombre_archivo=f"{pelo}.txt", contenido="", desde_cache=True,
        generado_at=AHORA, duracion_ms=None, pelos_camino=frozenset({pelo, *pelos}),
        extremos=ResumenCamino(cables=tuple(cables)),
    )


@pytest.fixture
def sin_uso(monkeypatch):
    marcados: set[int] = set()

    async def _cables_sin_uso(sesion, ids):
        return frozenset(i for i in ids if i in marcados)

    from core.services.cromo import auditoria_huerfanos

    monkeypatch.setattr(auditoria_huerfanos, "cables_sin_uso", _cables_sin_uso)
    return marcados


@pytest.mark.asyncio
async def test_validar_camino_pelo_danado(sin_uso):
    sesion = _Sesion(estados=[SimpleNamespace(n_id=7028870, estado_cromo="CORTADO AL RAS", atributos_leidos_at=AHORA)])

    aviso = await pv.validar_camino(sesion, _declarada(), _tracking(7028862, {7028870}))

    assert aviso.codigo == "PELO_DANADO" and aviso.retirada is False
    assert aviso.detalle["pelo"] == 7028870 and aviso.detalle["estado"] == "CORTADO AL RAS"
    assert aviso.declaracion_id == 1
    sql, params = sesion.ejecuciones[0]
    assert sorted(params["pelos"]) == [7028862, 7028870]


@pytest.mark.asyncio
async def test_validar_camino_ignora_estados_sanos_y_mira_cables_sin_uso(sin_uso):
    sin_uso.add(6600854)
    sesion = _Sesion(
        estados=[SimpleNamespace(n_id=7028862, estado_cromo="Utilizado", atributos_leidos_at=AHORA)],
        cables=[SimpleNamespace(n_id=6600854, nombre="F-PC-CC")],
    )

    aviso = await pv.validar_camino(sesion, _declarada(), _tracking(7028862, cables=[6600854, 1]))

    assert aviso.codigo == "CABLE_SIN_USO" and aviso.retirada is False
    assert aviso.detalle == {"cable": 6600854, "nombre": "F-PC-CC"}


@pytest.mark.asyncio
async def test_validar_camino_sano_no_avisa(sin_uso):
    assert await pv.validar_camino(_Sesion(), _declarada(), _tracking(7028862, cables=[1])) is None


def _completo(*pelos):
    marcados = set(pelos)
    return lambda t: t.pelo_n_id in marcados


@pytest.mark.asyncio
async def test_decidir_retiro_retira_si_hay_otro_camino_completo_sano(sin_uso):
    aviso = pv.AvisoPosicion(8604882, "O-1252871-1:1", "PELO_DANADO", False, 1, 7028862, {"pelo": 7})
    declarado = _tracking(7028862, {7})
    otro = _tracking(6799280, {6799290})

    final = await pv.decidir_retiro(
        _Sesion(), aviso, declarado=declarado, caminos=[declarado, otro], es_completo=_completo(6799280)
    )

    assert final.retirada is True and final.detalle["camino_alternativo"] == 6799280


@pytest.mark.asyncio
async def test_decidir_retiro_mantiene_si_el_alternativo_no_es_completo(sin_uso):
    aviso = pv.AvisoPosicion(8604882, "O-1252871-1:1", "CABLE_SIN_USO", False, 1, 7028862, {})
    final = await pv.decidir_retiro(
        _Sesion(), aviso, declarado=_tracking(7028862), caminos=[_tracking(6799280)],
        es_completo=_completo(),
    )
    assert final.retirada is False


@pytest.mark.asyncio
async def test_decidir_retiro_mantiene_si_los_dos_caminos_estan_mal(sin_uso):
    """Forma del 21070: el tramo bueno también tiene un pelo Dañado → se mantiene y se avisa."""
    aviso = pv.AvisoPosicion(8604882, "O-1252871-1:1", "PELO_DANADO", False, 1, 7028862, {})
    sesion = _Sesion(estados=[SimpleNamespace(n_id=6799290, estado_cromo="Dañado", atributos_leidos_at=None)])
    final = await pv.decidir_retiro(
        sesion, aviso, declarado=_tracking(7028862), caminos=[_tracking(6799280, {6799290})],
        es_completo=_completo(6799280),
    )
    assert final.retirada is False


@pytest.mark.asyncio
async def test_decidir_retiro_ignora_caminos_que_comparten_pelos_con_el_declarado(sin_uso):
    aviso = pv.AvisoPosicion(8604882, "O-1252871-1:1", "PELO_DANADO", False, 1, 7028862, {})
    mismo = _tracking(7028870, {7028862})  # el mismo camino sembrado desde otro pelo
    final = await pv.decidir_retiro(
        _Sesion(), aviso, declarado=_tracking(7028862), caminos=[mismo], es_completo=_completo(7028870)
    )
    assert final.retirada is False


@pytest.mark.asyncio
async def test_decidir_retiro_no_toca_avisos_de_inventario(sin_uso):
    aviso = pv.AvisoPosicion(8604882, "O-1252871-1:1", "SIN_PELO", True, 1, 7028862, {})
    final = await pv.decidir_retiro(
        _Sesion(), aviso, declarado=_tracking(7028862), caminos=[], es_completo=_completo()
    )
    assert final is aviso


@pytest.mark.parametrize(
    ("codigo", "retirada", "detalle", "texto"),
    [
        ("SIN_PELO", True, {}, "Se retiró la posición vigente O-1252871-1:1: el conector ya no tiene pelo en Cromo."),
        ("CONECTOR_INEXISTENTE", True, {}, "Se retiró la posición vigente O-1252871-1:1: el conector ya no está en el inventario de Cromo."),
        ("PELO_CAMBIO", True, {"declarado": 7028862, "actual": 1}, "Se retiró la posición vigente O-1252871-1:1: el pelo del conector cambió en Cromo (declarado 7028862, ahora 1)."),
        ("PELO_DANADO", True, {"pelo": 7, "estado": "Dañado"}, "Se retiró la posición vigente O-1252871-1:1: su camino pasa por el pelo 7 en estado «Dañado»."),
        ("CABLE_SIN_USO", True, {"cable": 5, "nombre": "F-X"}, "Se retiró la posición vigente O-1252871-1:1: su camino pasa por el cable F-X con tendido «Sin Uso»."),
        ("PELO_DANADO", False, {"pelo": 7, "estado": "Dañado"}, "La posición vigente O-1252871-1:1 se mantiene, pero su camino pasa por el pelo 7 en estado «Dañado» y no hay otro camino completo sano."),
        ("CABLE_SIN_USO", False, {"cable": 5, "nombre": None}, "La posición vigente O-1252871-1:1 se mantiene, pero su camino pasa por el cable 5 con tendido «Sin Uso» y no hay otro camino completo sano."),
        ("CAMINO_NO_RESUELTO", False, {"motivo": "timeout"}, "No se pudo usar la posición vigente O-1252871-1:1: Cromo no resolvió su camino (timeout). Se usó el cálculo automático; la declaración se mantiene."),
        ("CAMINO_INCOMPLETO", False, {}, "No se pudo usar la posición vigente O-1252871-1:1: su camino no termina en ODF en ambos extremos. Se usó el cálculo automático; la declaración se mantiene."),
    ],
)
def test_texto_aviso(codigo, retirada, detalle, texto):
    aviso = pv.AvisoPosicion(8604882, "O-1252871-1:1", codigo, retirada, 1, 7028862, detalle)
    assert pv.texto_aviso(aviso) == texto


def test_textos_avisos_agrega_una_sola_vez_la_linea_del_calculo_automatico():
    retirados = [
        pv.AvisoPosicion(1, "A:1", "SIN_PELO", True),
        pv.AvisoPosicion(2, "A:2", "SIN_PELO", True),
    ]
    textos = pv.textos_avisos(retirados)
    assert len(textos) == 3
    assert textos[-1] == "Se usó el cálculo automático. Declarar la posición vigente en el Detalle de Servicio."
    assert pv.textos_avisos([pv.AvisoPosicion(1, "A:1", "CAMINO_INCOMPLETO", False)])[-1].startswith("No se pudo")
    assert pv.textos_avisos([]) == []


@pytest.mark.asyncio
async def test_aplicar_retiros_solo_los_marcados_y_con_el_pelo_leido():
    sesion = _Sesion(rowcount=1)
    avisos = [
        pv.AvisoPosicion(1, "A:1", "SIN_PELO", True, 10, 7028862, {}),
        pv.AvisoPosicion(2, "A:2", "PELO_DANADO", False, 11, 7028863, {"pelo": 1}),
    ]
    assert await pv.aplicar_retiros(sesion, avisos) == 1
    (sql, params), = sesion.escrituras()
    assert params["id"] == 10 and params["pelo_leido"] == 7028862 and params["motivo"] == "SIN_PELO"
