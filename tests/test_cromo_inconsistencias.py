# Nombre de archivo: test_cromo_inconsistencias.py
# Ubicación de archivo: tests/test_cromo_inconsistencias.py
# Descripción: Pruebas unitarias del detector de inconsistencias de Cromo — reglas AUTO/MANUAL,
# falla cerrada de la confirmación en vivo, transiciones de estado, corrida sintética y post-ingesta

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from core.services.cromo import inconsistencias_cromo as inc
from core.services.cromo.client import CromoClientError

AHORA = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
BOTELLA = 10234797


def _cable(n_id: int, *, a: Optional[int] = BOTELLA, b: Optional[int] = None, **kw) -> inc.CableLocal:
    datos = dict(
        n_id=n_id,
        nombre=f"F-{n_id}",
        clase=51,
        version_id=n_id + 1,
        extremo_a_n_id=a,
        extremo_a_clase=68 if a is not None else None,
        extremo_b_n_id=b,
        extremo_b_clase=68 if b is not None else None,
    )
    datos.update(kw)
    return inc.CableLocal(**datos)


def _isla(**kw) -> inc.FilaIslaFusion:
    """La isla pura del caso testigo (cámara 10238011): fusión dentro de una botella 68, cada cable
    llega a la botella por un extremo y el otro es NULL."""
    datos = dict(
        fusion_n_id=900,
        nombre_par="1-1",
        contenedor_n_id=BOTELLA,
        contenedor_clase=68,
        contenedor_nombre="Cra Av 12 de octubre",
        contenedor_es_odf=False,
        localidad="Lomas de Zamora",
        pelo_a_n_id=1,
        pelo_b_n_id=2,
        uso_a=True,
        uso_b=False,
        cable_a=_cable(10237317, a=None, b=BOTELLA),
        cable_b=_cable(10236997),
        servicios=("102452",),
    )
    datos.update(kw)
    return inc.FilaIslaFusion(**datos)


def _conf(n_id: int, extremos: int = 1, *, borrado: bool = False, version: Optional[int] = None,
          cuando: datetime = AHORA, vigente: Optional[int] = None,
          ids: Optional[tuple[int, ...]] = None) -> inc.ConfirmacionVivo:
    """Por defecto: Cromo confirma la versión local (n_id + 1) y su(s) extremo(s) arrancan por la
    botella contenedora."""
    return inc.ConfirmacionVivo(
        cable_n_id=n_id,
        version_local=version if version is not None else n_id + 1,
        version_vigente=vigente if vigente is not None else n_id + 1,
        extremos=extremos,
        ids_extremos=ids if ids is not None else (BOTELLA, 555, 556)[:extremos],
        borrado=borrado,
        confirmado_at=cuando.isoformat(),
    )


def _confs_isla(fila: inc.FilaIslaFusion) -> dict[int, inc.ConfirmacionVivo]:
    return {c.n_id: _conf(c.n_id) for c in fila.cables()}


# ── Clasificación AUTO / MANUAL ──────────────────────────────────────────────


def test_estado_inicial_auto_cuarentena_manual_pendiente():
    assert inc.estado_inicial("AUTO") == "CUARENTENA"
    assert inc.estado_inicial("MANUAL") == "PENDIENTE"


def test_isla_pura_confirmada_es_auto():
    fila = _isla()
    assert inc.motivo_no_candidato_auto(fila) is None
    assert inc.clasificar_isla_fusion(fila, _confs_isla(fila)) == ("AUTO", "isla_pura_confirmada")


@pytest.mark.parametrize(
    ("cambios", "motivo"),
    [
        ({"contenedor_es_odf": True, "contenedor_clase": 69}, "contenedor_odf"),
        ({"contenedor_clase": 86}, "contenedor_odf"),
        ({"contenedor_clase": None}, "contenedor_no_botella"),
        ({"cable_b": None}, "cable_inexistente"),
        ({"cable_b": _cable(10236997, b=6645267, extremo_b_clase=69)}, "cable_con_extremo_odf"),
        ({"cable_b": _cable(10236997, b=777, extremo_b_es_odf=True)}, "cable_con_extremo_odf"),
        ({"cable_b": _cable(10236997, a=555, b=None)}, "cable_no_llega_al_contenedor"),
        ({"cable_b": _cable(10236997, b=555)}, "cable_con_otro_extremo"),
        ({"cable_b": _cable(10236997, b=BOTELLA)}, "cable_con_otro_extremo"),  # lazo
    ],
)
def test_todo_lo_que_no_es_isla_pura_queda_manual(cambios, motivo):
    fila = _isla(**cambios)
    # Aun con confirmaciones "perfectas" en vivo, la regla local manda: MANUAL.
    confs = {n: _conf(n) for n in (10237317, 10236997)}
    assert inc.clasificar_isla_fusion(fila, confs) == ("MANUAL", motivo)


def test_el_extremo_vivo_puede_venir_con_el_id_de_version_del_contenedor():
    """Cromo publica `tp[].id_to` = 10238011 (versión) para la botella de linaje 10234797."""
    fila = _isla(contenedor_version_id=10238011)
    confs = {c.n_id: _conf(c.n_id, ids=(10238011,)) for c in fila.cables()}
    assert inc.clasificar_isla_fusion(fila, confs) == ("AUTO", "isla_pura_confirmada")
    sin_version = _isla()
    assert inc.clasificar_isla_fusion(sin_version, confs) == ("MANUAL", "extremo_vivo_distinto")


def test_dos_pelos_del_mismo_cable_cuentan_un_solo_cable():
    cable = _cable(10236997)
    fila = _isla(cable_a=cable, cable_b=cable)
    assert fila.cables() == [cable]
    assert inc.clasificar_isla_fusion(fila, {cable.n_id: _conf(cable.n_id)})[0] == "AUTO"


@pytest.mark.parametrize(
    ("confs", "motivo"),
    [
        ({}, "sin_confirmacion_en_vivo"),
        ({10237317: _conf(10237317)}, "sin_confirmacion_en_vivo"),
        ({10237317: _conf(10237317), 10236997: _conf(10236997, 2)}, "cromo_vivo_con_otro_extremo"),
        ({10237317: _conf(10237317), 10236997: _conf(10236997, 0)}, "cromo_vivo_con_otro_extremo"),
        ({10237317: _conf(10237317), 10236997: _conf(10236997, 1, borrado=True)}, "cable_borrado_en_cromo"),
        # La versión vigente en Cromo no es la local: la regla local se evaluó sobre datos viejos.
        ({10237317: _conf(10237317), 10236997: _conf(10236997, vigente=1)}, "version_local_desactualizada"),
        # Un solo extremo vivo, pero ya no es la botella: hoy es un ODF.
        ({10237317: _conf(10237317), 10236997: _conf(10236997, ids=(6645267,))}, "extremo_vivo_distinto"),
    ],
)
def test_falla_cerrada_sin_confirmacion_en_vivo_completa(confs, motivo):
    assert inc.clasificar_isla_fusion(_isla(), confs) == ("MANUAL", motivo)


def test_caso_isla_guarda_evidencia_y_solo_pelos_en_uso():
    fila = _isla()
    caso = inc.caso_isla_fusion(fila, _confs_isla(fila), corrida_id=55)
    assert caso.tipo == "ISLA_FUSION" and caso.objeto_n_id == 900 and caso.objeto_clase == 132
    assert caso.revision == "AUTO"
    assert caso.pelos == (1,)
    assert caso.nombre == "Cra Av 12 de octubre — 1-1"
    assert caso.evidencia["corrida_id"] == 55
    assert {c["cable_n_id"] for c in caso.evidencia["confirmaciones"]} == {10237317, 10236997}
    json.dumps(caso.evidencia)  # serializable tal cual para el JSONB


# ── Interpretación de la respuesta de Cromo ──────────────────────────────────

# Forma real (2026-10-17) de GET /db/objects/10238010: versión vigente de F-GTTttttt-003-B.
_VIGENTE = {
    "id": 10238010,
    "n_id": 10237317,
    "class": 51,
    "tp": [{"type": 0, "nfrom": 1, "id_to": 10238011, "nto": 1, "class": 68}],
    "hist": [
        {"id": 10237317, "next_id": 10237630, "to": 1783413343},
        {"id": 10238010, "next_id": 0, "to": 0},
    ],
}


def test_interpretar_cable_vivo_version_vigente_un_extremo():
    assert inc.interpretar_cable_vivo(_VIGENTE) == (False, 10238010, (10238011,))


def test_interpretar_cable_vivo_version_vieja_sin_tp_apunta_a_la_vigente():
    vieja = {"id": 10237317, "to": 1783413343, "tp": None, "hist": _VIGENTE["hist"]}
    assert inc.interpretar_cable_vivo(vieja) == (False, 10238010, ())


def test_interpretar_cable_vivo_borrado_y_dos_extremos():
    borrado = {"id": 5, "hist": [{"id": 5, "next_id": 0, "to": 123}], "tp": []}
    assert inc.interpretar_cable_vivo(borrado)[0] is True
    dos = {"id": 5, "tp": [{"nfrom": 0, "id_to": 1}, {"nfrom": 1, "id_to": 2}, {"nfrom": 1, "id_to": 3}]}
    assert inc.interpretar_cable_vivo(dos) == (False, 5, (1, 2))


class _ClienteFake:
    def __init__(self, respuestas: dict[int, Any]) -> None:
        self.respuestas = respuestas
        self.pedidos: list[int] = []

    async def get_objeto(self, n_id: int) -> dict[str, Any]:
        self.pedidos.append(n_id)
        valor = self.respuestas.get(n_id)
        if isinstance(valor, Exception):
            raise valor
        if valor is None:
            raise CromoClientError(f"sin respuesta para {n_id}")
        return {"response": valor}


@pytest.mark.asyncio
async def test_confirmar_cable_una_llamada_si_la_version_local_es_la_vigente():
    cliente = _ClienteFake({10238010: _VIGENTE})
    cable = _cable(10237317, version_id=10238010)
    conf = await inc.confirmar_cable_en_vivo(cliente, cable, ahora=AHORA)
    assert cliente.pedidos == [10238010]
    assert conf.un_solo_extremo and conf.llamadas == 1 and conf.ids_extremos == (10238011,)


@pytest.mark.asyncio
async def test_version_local_vieja_sigue_a_la_vigente_pero_queda_manual():
    """Con la versión local vieja se pide la vigente sólo como evidencia: aunque hoy tenga un solo
    extremo y sea la botella, la regla local se evaluó sobre datos viejos → MANUAL."""
    vieja = {"id": 10237317, "to": 1783413343, "hist": _VIGENTE["hist"]}
    cliente = _ClienteFake({10237317: vieja, 10238010: _VIGENTE})
    cable = _cable(10237317, a=None, b=BOTELLA, version_id=10237317)
    conf = await inc.confirmar_cable_en_vivo(cliente, cable, ahora=AHORA)
    assert cliente.pedidos == [10237317, 10238010]
    assert conf.llamadas == 2 and conf.version_vigente == 10238010 and conf.extremos == 1
    fila = _isla(contenedor_version_id=10238011, cable_a=cable, cable_b=cable)
    assert inc.clasificar_isla_fusion(fila, {cable.n_id: conf}) == (
        "MANUAL", "version_local_desactualizada"
    )


@pytest.mark.asyncio
async def test_un_solo_extremo_vivo_que_es_un_odf_queda_manual():
    """La versión local es la vigente, pero su único extremo en Cromo es un ODF (no la botella)."""
    vigente_odf = {**_VIGENTE, "tp": [{"nfrom": 1, "id_to": 6645267, "class": 69}]}
    cliente = _ClienteFake({10238010: vigente_odf})
    cable = _cable(10237317, a=None, b=BOTELLA, version_id=10238010)
    conf = await inc.confirmar_cable_en_vivo(cliente, cable, ahora=AHORA)
    fila = _isla(contenedor_version_id=10238011, cable_a=cable, cable_b=cable)
    assert inc.clasificar_isla_fusion(fila, {cable.n_id: conf}) == ("MANUAL", "extremo_vivo_distinto")


@pytest.mark.asyncio
async def test_no_reutiliza_una_previa_que_no_era_la_version_vigente():
    fila = _isla()
    previas = {c.n_id: _conf(c.n_id, vigente=1) for c in fila.cables()}
    cliente = _ClienteFake({})
    _confs, resumen = await inc.confirmar_candidatos(cliente, [fila], previas=previas, tope=300, ahora=AHORA)
    assert resumen.reutilizados == 0 and len(cliente.pedidos) == 2


# ── Confirmación de candidatos: tope, reutilización y falla cerrada ─────────


def _respuesta_un_extremo(version: int) -> dict[str, Any]:
    return {"id": version, "tp": [{"nfrom": 0, "id_to": BOTELLA}]}


@pytest.mark.asyncio
async def test_sin_cliente_no_confirma_nada():
    confs, resumen = await inc.confirmar_candidatos(None, [_isla()], previas={}, tope=300, ahora=AHORA)
    assert confs == {} and resumen.sin_cliente == 2 and resumen.candidatos == 2


@pytest.mark.asyncio
async def test_solo_se_confirman_cables_de_candidatos_y_respeta_el_tope():
    candidata = _isla()
    no_candidata = _isla(fusion_n_id=901, contenedor_clase=69, contenedor_es_odf=True,
                         cable_a=_cable(1), cable_b=_cable(2))
    cliente = _ClienteFake({10236998: _respuesta_un_extremo(10236998), 10237318: _respuesta_un_extremo(10237318)})
    confs, resumen = await inc.confirmar_candidatos(
        cliente, [candidata, no_candidata], previas={}, tope=1, ahora=AHORA
    )
    assert len(cliente.pedidos) == 1  # tope de 1, y nunca los cables de la no candidata
    assert resumen.omitidos_por_tope == 1 and resumen.confirmados == 1
    assert inc.clasificar_isla_fusion(candidata, confs)[0] == "MANUAL"


@pytest.mark.asyncio
async def test_cromo_caido_deja_todo_manual_y_corta_tras_fallos_seguidos():
    filas = [
        _isla(fusion_n_id=900 + i, cable_a=_cable(100 + 2 * i), cable_b=_cable(101 + 2 * i))
        for i in range(10)
    ]
    cliente = _ClienteFake({})  # todo falla
    confs, resumen = await inc.confirmar_candidatos(cliente, filas, previas={}, tope=300, ahora=AHORA)
    assert confs == {}
    assert resumen.errores == 20
    assert len(cliente.pedidos) < 20  # dejó de pedir tras los fallos seguidos
    assert all(inc.clasificar_isla_fusion(f, confs)[0] == "MANUAL" for f in filas)


@pytest.mark.asyncio
async def test_reutiliza_confirmacion_previa_si_la_version_local_no_cambio():
    fila = _isla()
    previas = {c.n_id: replace(_conf(c.n_id), reutilizada=True) for c in fila.cables()}
    cliente = _ClienteFake({})
    confs, resumen = await inc.confirmar_candidatos(cliente, [fila], previas=previas, tope=300, ahora=AHORA)
    assert cliente.pedidos == [] and resumen.reutilizados == 2
    assert inc.clasificar_isla_fusion(fila, confs)[0] == "AUTO"


@pytest.mark.asyncio
async def test_no_reutiliza_si_cambio_la_version_o_vencio():
    fila = _isla()
    cable_a, cable_b = fila.cables()
    previas = {
        cable_a.n_id: _conf(cable_a.n_id, version=1),  # versión local distinta
        cable_b.n_id: _conf(cable_b.n_id, cuando=AHORA - timedelta(days=8)),  # vencida
    }
    cliente = _ClienteFake({})
    _confs, resumen = await inc.confirmar_candidatos(cliente, [fila], previas=previas, tope=300, ahora=AHORA)
    assert resumen.reutilizados == 0 and len(cliente.pedidos) == 2


def test_max_confirmaciones_configurado(monkeypatch):
    monkeypatch.delenv("CROMO_INCONSISTENCIAS_MAX_CONFIRMACIONES", raising=False)
    assert inc.max_confirmaciones_configurado() == 300
    monkeypatch.setenv("CROMO_INCONSISTENCIAS_MAX_CONFIRMACIONES", "25")
    assert inc.max_confirmaciones_configurado() == 25
    monkeypatch.setenv("CROMO_INCONSISTENCIAS_MAX_CONFIRMACIONES", "0")
    assert inc.max_confirmaciones_configurado() == 0
    monkeypatch.setenv("CROMO_INCONSISTENCIAS_MAX_CONFIRMACIONES", "abc")
    assert inc.max_confirmaciones_configurado() == 300


# ── Estados: upsert, cierre, reapertura y cambio manual ─────────────────────


def _existente(estado: str, revision: str = "MANUAL", por: Optional[str] = inc.USUARIO_DETECTOR):
    return inc.EstadoExistente(id=1, estado=estado, revision=revision, actualizado_por=por)


@pytest.mark.parametrize(
    ("existente", "revision", "esperado"),
    [
        (None, "AUTO", ("CUARENTENA", False)),
        (None, "MANUAL", ("PENDIENTE", False)),
        (_existente("ACEPTADA"), "AUTO", ("ACEPTADA", False)),
        (_existente("REPORTADA", "AUTO"), "MANUAL", ("REPORTADA", False)),
        (_existente("CORREGIDA", "AUTO"), "AUTO", ("CUARENTENA", True)),
        (_existente("CORREGIDA"), "MANUAL", ("PENDIENTE", True)),
        (_existente("CUARENTENA", "AUTO"), "AUTO", ("CUARENTENA", False)),
        (_existente("CUARENTENA", "AUTO"), "MANUAL", ("PENDIENTE", False)),  # deja de ser pura
        (_existente("PENDIENTE"), "AUTO", ("CUARENTENA", False)),  # el detector lo promueve
        (_existente("PENDIENTE", por="ana@metrotel"), "AUTO", ("PENDIENTE", False)),  # humano manda
        (_existente("PENDIENTE", "AUTO", por="ana@metrotel"), "AUTO", ("PENDIENTE", False)),
        (_existente("CUARENTENA", "MANUAL", por="ana@metrotel"), "MANUAL", ("CUARENTENA", False)),
        (_existente("CUARENTENA", "AUTO", por="ana@metrotel"), "MANUAL", ("CUARENTENA", False)),
    ],
)
def test_decidir_estado(existente, revision, esperado):
    assert inc.decidir_estado(existente, revision) == esperado


@pytest.mark.parametrize(
    ("actual", "destino", "rechazado"),
    [
        ("PENDIENTE", "CUARENTENA", False),
        ("CUARENTENA", "PENDIENTE", False),
        ("CUARENTENA", "ACEPTADA", False),
        ("PENDIENTE", "REPORTADA", False),
        ("ACEPTADA", "PENDIENTE", False),
        ("PENDIENTE", "CORREGIDA", True),  # sólo el detector cierra
        ("CORREGIDA", "CUARENTENA", True),
        ("ACEPTADA", "ACEPTADA", True),
        ("PENDIENTE", "INVENTADO", True),
    ],
)
def test_motivo_rechazo_transicion(actual, destino, rechazado):
    assert (inc.motivo_rechazo_transicion(actual, destino) is not None) is rechazado


# ── Corrida sintética ────────────────────────────────────────────────────────


@dataclass
class _Corrida:
    id: int
    estado: str = "EN_CURSO"
    total_objetivo: Optional[int] = None
    leidas: int = 0
    creadas: int = 0
    actualizadas: int = 0
    errores: int = 0
    finalizada_at: Any = None


@dataclass
class _Sesion:
    corrida: _Corrida
    eventos: list = field(default_factory=list)
    commits: int = 0
    rollbacks: int = 0

    async def get(self, _modelo, _pk):
        return self.corrida

    def add(self, obj) -> None:
        self.eventos.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _eventos(sesion: _Sesion, accion: str) -> list[dict]:
    return [json.loads(e.detalle) for e in sesion.eventos if e.accion == accion]


def _resumen_fake() -> inc.ResumenDeteccion:
    return inc.ResumenDeteccion(
        por_tipo_revision={"ISLA_FUSION": {"AUTO": 1, "MANUAL": 0}},
        total=1,
        confirmaciones=inc.ResumenConfirmaciones(),
        aplicado=True,
        nuevos=1,
    )


@pytest.mark.asyncio
async def test_ejecutar_corrida_emite_pagina_por_fase_y_cierra_ok(monkeypatch):
    sesion = _Sesion(_Corrida(id=9))
    recibido: dict[str, Any] = {}

    async def _detectar(sesion_arg, *, cliente, corrida_id, aplicar, al_avanzar):
        recibido.update(corrida_id=corrida_id, aplicar=aplicar, cliente=cliente)
        for fase in ("LECTURA", "CONFIRMACION", "APLICACION"):
            await al_avanzar(fase, {"x": 1})
        return _resumen_fake()

    async def _no_cancelada(_s, _id):
        return False

    monkeypatch.setattr(inc, "detectar", _detectar)
    monkeypatch.setattr(inc.ingesta, "_fue_cancelada_externamente", _no_cancelada)

    estado = await inc.ejecutar_corrida("cli", sesion, 9)

    assert estado == "OK" and sesion.corrida.estado == "OK"
    assert recibido == {"corrida_id": 9, "aplicar": True, "cliente": "cli"}
    paginas = _eventos(sesion, "PAGINA")
    assert [p["paso"] for p in paginas] == ["LECTURA", "CONFIRMACION", "APLICACION"]
    assert [p["leidas"] for p in paginas] == [1, 2, 3] and paginas[0]["total"] == 3
    resumen = _eventos(sesion, "RESUMEN")[0]
    assert resumen["estado"] == "OK" and resumen["nuevos"] == 1
    assert sesion.corrida.creadas == 1 and sesion.corrida.finalizada_at is not None


@pytest.mark.asyncio
async def test_ejecutar_corrida_cancelada_entre_fases_no_aplica(monkeypatch):
    sesion = _Sesion(_Corrida(id=9))
    fases: list[str] = []

    async def _detectar(sesion_arg, *, cliente, corrida_id, aplicar, al_avanzar):
        for fase in ("LECTURA", "CONFIRMACION", "APLICACION"):
            fases.append(fase)
            await al_avanzar(fase, {})
        return _resumen_fake()

    async def _cancelada(_s, _id):
        return True

    monkeypatch.setattr(inc, "detectar", _detectar)
    monkeypatch.setattr(inc.ingesta, "_fue_cancelada_externamente", _cancelada)

    assert await inc.ejecutar_corrida(None, sesion, 9) == "CANCELADA"
    assert fases == ["LECTURA"]
    assert sesion.corrida.estado == "CANCELADA"


@pytest.mark.asyncio
async def test_ejecutar_corrida_falla_cierra_fallida_sin_levantar(monkeypatch):
    sesion = _Sesion(_Corrida(id=9))

    async def _detectar(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(inc, "detectar", _detectar)

    assert await inc.ejecutar_corrida(None, sesion, 9) == "FALLIDA"
    assert sesion.corrida.estado == "FALLIDA" and sesion.rollbacks == 1
    assert "boom" in [e.detalle for e in sesion.eventos if e.accion == "ERROR"][0]


# ── Post-ingesta (best-effort) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_ingesta_no_corre_en_modos_que_no_aplican(monkeypatch):
    llamadas: list = []

    async def _no_deberia(*a, **k):
        # `detectar_post_ingesta` se traga las excepciones: se registra la llamada, no se levanta.
        llamadas.append(k)
        return None, 1

    monkeypatch.setattr(inc, "iniciar_si_no_hay_otra", _no_deberia)
    for modo in ("SOLO_ROSETAS", "SOLO_CABLES", "SOLO_CAJAS_PON"):
        assert await inc.detectar_post_ingesta(None, object(), 1, modo) is None
    assert llamadas == []


@pytest.mark.asyncio
async def test_post_ingesta_corre_la_corrida_sintetica(monkeypatch):
    llamadas: dict[str, Any] = {}

    async def _iniciar(sesion, *, usuario, origen, corrida_origen_id):
        llamadas["iniciar"] = (usuario, origen, corrida_origen_id)
        return _Corrida(id=33), None

    async def _ejecutar(cliente, sesion, corrida_id):
        llamadas["ejecutar"] = corrida_id
        return "OK"

    monkeypatch.setattr(inc, "iniciar_si_no_hay_otra", _iniciar)
    monkeypatch.setattr(inc, "ejecutar_corrida", _ejecutar)

    assert await inc.detectar_post_ingesta(None, object(), 2221, "SOLO_ODF") == "OK"
    assert llamadas == {"iniciar": (inc.USUARIO_DETECTOR, "POST_INGESTA", 2221), "ejecutar": 33}


@pytest.mark.asyncio
async def test_post_ingesta_omite_si_ya_hay_otra_en_curso(monkeypatch):
    async def _iniciar(*a, **k):
        return None, 77

    async def _no_deberia(*a, **k):
        raise AssertionError("no debería ejecutar")

    monkeypatch.setattr(inc, "iniciar_si_no_hay_otra", _iniciar)
    monkeypatch.setattr(inc, "ejecutar_corrida", _no_deberia)
    assert await inc.detectar_post_ingesta(None, object(), 1, "COMPLETA") is None


@pytest.mark.asyncio
async def test_post_ingesta_nunca_levanta(monkeypatch):
    sesion = _Sesion(_Corrida(id=1))

    async def _iniciar(*a, **k):
        raise RuntimeError("DB caída")

    monkeypatch.setattr(inc, "iniciar_si_no_hay_otra", _iniciar)
    assert await inc.detectar_post_ingesta(None, sesion, 1, "SOLO_PELOS_INNER") is None
    assert sesion.rollbacks == 1


# ── Ronda de fixes 1: robustez de la corrida y del arranque ─────────────────


class _SesionRota(_Sesion):
    """Conexión cortada: después del primer rollback, todo commit falla."""

    async def commit(self) -> None:
        if self.rollbacks:
            raise ConnectionError("conexión perdida")
        self.commits += 1


def _sesion_nueva_fake(corridas: dict[int, _Corrida], eventos: list):
    class _CM:
        async def __aenter__(self):
            sesion = _Sesion(corridas[next(iter(corridas))], eventos=eventos)
            return sesion

        async def __aexit__(self, *a):
            return False

    return lambda: _CM()


@pytest.mark.asyncio
async def test_corrida_con_conexion_rota_se_cierra_fallida_con_sesion_nueva(monkeypatch):
    """Si hasta el camino de error falla, la corrida no puede quedar EN_CURSO: bloquearía toda
    detección futura. Se cierra con una sesión nueva y `ejecutar_corrida` no levanta."""
    trabajo = _SesionRota(_Corrida(id=9))
    persistida = _Corrida(id=9)  # lo que ve una sesión nueva: sigue EN_CURSO
    eventos_nuevos: list = []

    async def _detectar(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(inc, "detectar", _detectar)
    monkeypatch.setattr(inc, "_sesion_nueva", _sesion_nueva_fake({9: persistida}, eventos_nuevos))

    assert await inc.ejecutar_corrida(None, trabajo, 9) == "FALLIDA"
    assert persistida.estado == "FALLIDA" and persistida.finalizada_at is not None
    assert [e.accion for e in eventos_nuevos] == ["ERROR"]


@pytest.mark.asyncio
async def test_cerrar_corrida_fallida_no_toca_una_ya_cerrada_y_nunca_levanta(monkeypatch):
    cerrada = _Corrida(id=9, estado="OK")
    monkeypatch.setattr(inc, "_sesion_nueva", _sesion_nueva_fake({9: cerrada}, []))
    await inc.cerrar_corrida_fallida(9, "x")
    assert cerrada.estado == "OK"

    def _rota():
        raise ConnectionError("sin DB")

    monkeypatch.setattr(inc, "_sesion_nueva", _rota)
    await inc.cerrar_corrida_fallida(9, "x")  # no levanta


@pytest.mark.asyncio
async def test_post_ingesta_cierra_su_corrida_si_la_ejecucion_levanta(monkeypatch):
    cerradas: list = []

    async def _iniciar(*a, **k):
        return _Corrida(id=44), None

    async def _ejecutar(*a, **k):
        raise RuntimeError("inesperado")

    async def _cerrar(corrida_id, motivo):
        cerradas.append(corrida_id)

    monkeypatch.setattr(inc, "iniciar_si_no_hay_otra", _iniciar)
    monkeypatch.setattr(inc, "ejecutar_corrida", _ejecutar)
    monkeypatch.setattr(inc, "cerrar_corrida_fallida", _cerrar)

    assert await inc.detectar_post_ingesta(None, _Sesion(_Corrida(id=1)), 1, "COMPLETA") is None
    assert cerradas == [44]


class _ResultadoFila:
    def __init__(self, fila):
        self._fila = fila

    def first(self):
        return self._fila


class _SesionSql:
    """Responde según el SQL: registra todo lo ejecutado."""

    def __init__(self, respuestas: dict[str, Any], falla_en: Optional[str] = None) -> None:
        self.respuestas = respuestas
        self.falla_en = falla_en
        self.ejecutado: list[str] = []
        self.rollbacks = 0
        self.agregados: list = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.ejecutado.append(sql)
        if self.falla_en and self.falla_en in sql:
            raise RuntimeError("error original del SQL")
        for clave, valor in self.respuestas.items():
            if clave in sql:
                return _ResultadoFila(valor)
        return _ResultadoFila(None)

    async def rollback(self) -> None:
        self.rollbacks += 1

    def add(self, obj) -> None:
        self.agregados.append(obj)


@pytest.mark.asyncio
async def test_leer_deteccion_propaga_el_error_original_sin_drop_posterior():
    sesion = _SesionSql({}, falla_en="WITH islas AS")
    with pytest.raises(RuntimeError, match="error original"):
        await inc.leer_deteccion(sesion)
    ultimo = sesion.ejecutado[-1]
    assert "WITH islas AS" in ultimo  # nada después del fallo (un DROP taparía el error)


@pytest.mark.asyncio
async def test_no_inicia_una_deteccion_con_una_ingesta_en_curso(monkeypatch):
    sesion = _SesionSql({"params ->> 'tipo' IS NULL": (2221,)})

    async def _no_deberia(*a, **k):
        raise AssertionError("no debería crear la corrida")

    monkeypatch.setattr(inc.ingesta, "iniciar_corrida", _no_deberia)
    corrida, en_curso = await inc.iniciar_si_no_hay_otra(sesion, usuario="ana")
    assert (corrida, en_curso) == (None, 2221) and sesion.rollbacks == 1


@pytest.mark.asyncio
async def test_inicia_si_no_hay_deteccion_ni_ingesta_en_curso(monkeypatch):
    sesion = _SesionSql({})
    creada = _Corrida(id=50)
    recibido: dict = {}

    async def _iniciar(sesion_arg, **k):
        recibido.update(k["params_extra"])
        return creada

    monkeypatch.setattr(inc.ingesta, "iniciar_corrida", _iniciar)
    corrida, en_curso = await inc.iniciar_si_no_hay_otra(
        sesion, usuario="x", origen="POST_INGESTA", corrida_origen_id=7
    )
    assert corrida is creada and en_curso is None
    assert recibido == {"tipo": inc.TIPO_CORRIDA_INCONSISTENCIAS, "origen": "POST_INGESTA", "corrida_origen_id": 7}
