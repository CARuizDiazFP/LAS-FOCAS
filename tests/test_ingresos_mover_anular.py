# Nombre de archivo: test_ingresos_mover_anular.py
# Ubicación de archivo: tests/test_ingresos_mover_anular.py
# Descripción: Pruebas unitarias de mover_ingreso_web/anular_ingreso_web (validaciones, auditoría y FO Monitor)

"""Servicio de corrección de ingresos desde el portal (plan 2026-10-23, Task 2), sin DB: la sesión es
un `MagicMock` y las dos consultas de FO Monitor se parchean en el módulo donde se leen. El SQL real
(filtro de estados abiertos, otros vinculados vigentes) lo cubre `test_ingresos_mover_anular_real_db.py`."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from core.services import ingreso_correccion_service as ics
from core.services.fo_monitor.alcance import AlcanceIntervencion, CableAlcance
from core.services.ingreso_correccion_service import (
    COMANDO_ANULAR_INGRESO,
    COMANDO_MOVER_INGRESO,
    OMISION_CONSULTAS_YA_ENVIADAS,
    OMISION_OTROS_INGRESOS_VIGENTES,
    ORIGEN_WEB,
    RESULTADO_BOTELLA_INVALIDA,
    RESULTADO_CAMARA_NO_ENCONTRADA,
    RESULTADO_DESTINO_NO_RAIZ,
    RESULTADO_INGRESO_ANULADO,
    RESULTADO_INGRESO_NO_ENCONTRADO,
    RESULTADO_MISMO_DESTINO,
    RESULTADO_MOTIVO_INVALIDO,
    RESULTADO_OK_INGRESO_ANULADO,
    RESULTADO_OK_INGRESO_MOVIDO,
    IntervencionFomonOmitida,
    ResultadoCorreccion,
    anular_ingreso_web,
    mover_ingreso_web,
)
from db.models.cromo import CromoBotella
from db.models.fo_monitor import FomonConsulta, FomonIntervencion, FomonIntervencionServicio
from db.models.infra import Camara, CamaraEstado, Ingreso, IngresoCorreccion, IngresoTipo

AHORA = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)
INICIO = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
ORIGEN = 7
DESTINO = 9
BOTELLA_ORIGEN = 5001
BOTELLA_DESTINO = 6001


def _ingreso(*, camara_id: int = ORIGEN, botella: int | None = BOTELLA_ORIGEN, tipo=IngresoTipo.INGRESO) -> Ingreso:
    ingreso = Ingreso(
        id=42,
        camara_id=camara_id,
        cromo_botella_id=botella,
        tecnico_id="rider.fernandez",
        tipo=tipo,
        fecha_inicio=INICIO,
        fecha_fin=None,
    )
    ingreso.camara = Camara(id=camara_id, nombre="Cra Origen", estado=CamaraEstado.LIBRE)
    return ingreso


def _botella(n_id: int = BOTELLA_DESTINO, *, camara_id: int | None = DESTINO, vigente: bool = True) -> CromoBotella:
    return CromoBotella(n_id=n_id, camara_id=camara_id, vigente=vigente, nombre=f"BOT {n_id}")


def _session(objetivo: Ingreso | None, *, destino: Camara | None = None, botellas=(), consultas=()) -> MagicMock:
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = objetivo
    session.query.return_value.filter.return_value.all.return_value = list(consultas)
    por_modelo = {Camara: {} if destino is None else {destino.id: destino}, CromoBotella: {b.n_id: b for b in botellas}}
    session.get.side_effect = lambda modelo, pk: por_modelo.get(modelo, {}).get(pk)
    return session


def _destino() -> Camara:
    return Camara(id=DESTINO, nombre="Cra Destino", estado=CamaraEstado.LIBRE)


def _auditoria(session: MagicMock) -> IngresoCorreccion:
    filas = [c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], IngresoCorreccion)]
    assert len(filas) == 1, "cada invocación escribe exactamente una fila de auditoría"
    return filas[0]


def _alcance(camara_id: int, botella_n_id: int | None, *, con_servicios: bool = True) -> AlcanceIntervencion:
    """Alcance falso de la cámara destino: un cable con un servicio (o sin, si `con_servicios=False`)
    y otro sin servicios."""
    servicio = MagicMock(servicio_id=77, servicio_id_externo="SRV-77", tipo_servicio="L2", categoria=1,
                         nombre_cliente="Cliente", cliente=None)
    return AlcanceIntervencion(
        camara_id=camara_id,
        botella_objetivo_n_id=botella_n_id if botella_n_id is not None else 6999,
        botella_1_inferida=botella_n_id is None,
        botellas={},
        cables=[
            CableAlcance(n_id=801, nombre="CABLE NUEVO", clase=51, botella_n_id=6999, es_objetivo=True,
                         servicios=[servicio] if con_servicios else []),
            CableAlcance(n_id=802, nombre="CABLE SIN SERV", clase=51, botella_n_id=6999, es_objetivo=False),
        ],
    )


@pytest.fixture
def fomon(monkeypatch):
    """Parchea las consultas de FO Monitor del módulo y `resolver_alcance` (donde se leen). `abiertas`,
    `otros` y `enviadas` (por intervención) y `otras_en_destino` se cargan desde cada test."""
    estado = {"abiertas": [], "otros": {}, "enviadas": set(), "otras_en_destino": [], "con_servicios": True}
    abiertas = MagicMock(side_effect=lambda session, ingreso_id: list(estado["abiertas"]))
    otros = MagicMock(side_effect=lambda session, intervencion_id, ingreso_id: list(estado["otros"].get(intervencion_id, [])))
    resolver = MagicMock(
        side_effect=lambda session, camara_id, botella_n_id: _alcance(
            camara_id, botella_n_id, con_servicios=estado["con_servicios"]
        )
    )
    monkeypatch.setattr(ics, "_intervenciones_abiertas_vinculadas", abiertas)
    monkeypatch.setattr(ics, "_otros_vinculados_vigentes", otros)
    monkeypatch.setattr(ics, "_consultas_ya_enviadas", lambda session, intervencion_id: intervencion_id in estado["enviadas"])
    monkeypatch.setattr(ics, "_otras_abiertas_en_camara", lambda session, camara_id, intervencion_id: list(estado["otras_en_destino"]))
    monkeypatch.setattr(ics, "resolver_alcance", resolver)
    estado["mock_abiertas"] = abiertas
    estado["mock_resolver"] = resolver
    return estado


def _servicios_congelados(session: MagicMock) -> list[FomonIntervencionServicio]:
    return [c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], FomonIntervencionServicio)]


def _mover(session: MagicMock, *, botella: int | None = None, motivo: str = "  Fontaine mal tipeado  ", destino: int = DESTINO) -> ResultadoCorreccion:
    return mover_ingreso_web(
        session, ingreso_id=42, camara_destino_id=destino, cromo_botella_destino_n_id=botella,
        motivo=motivo, usuario="admin2", ahora=AHORA,
    )


def _anular(session: MagicMock, *, motivo: str = "  nunca ocurrió  ", usuario: str = "admin2") -> ResultadoCorreccion:
    return anular_ingreso_web(session, ingreso_id=42, motivo=motivo, usuario=usuario, ahora=AHORA)


def _interv(id_: int, estado: str = "EN_CURSO") -> FomonIntervencion:
    return FomonIntervencion(
        id=id_, origen="INGRESO", camara_id=ORIGEN, botella_objetivo_n_id=BOTELLA_ORIGEN,
        botella_1_inferida=True, estado=estado, proximo_evento_en=None, aviso_ts="111.222",
        aviso_canal="CFOMON", atribucion_compartida=False, sin_linea_base=False,
    )


# ── Mover: caminos felices ─────────────────────────────────────────────────────────────────────


def test_mover_sin_botella_cambia_camara_deja_botella_null_y_audita(fomon):
    objetivo = _ingreso()
    session = _session(objetivo, destino=_destino())

    resultado = _mover(session)

    assert resultado.resultado == RESULTADO_OK_INGRESO_MOVIDO
    assert resultado.ingreso is objetivo
    assert objetivo.camara_id == DESTINO
    assert objetivo.cromo_botella_id is None
    assert objetivo.fecha_fin is None, "un ingreso abierto se mueve abierto"
    assert objetivo.fecha_inicio == INICIO
    fila = _auditoria(session)
    assert fila.comando == COMANDO_MOVER_INGRESO
    assert fila.origen == ORIGEN_WEB and fila.actor_web_usuario == "admin2"
    assert fila.actor_slack_user_id is None and fila.canal_id is None
    assert fila.resultado == RESULTADO_OK_INGRESO_MOVIDO
    assert fila.ingreso_id == 42
    assert fila.camara_id_resuelta == DESTINO and fila.cromo_botella_id_resuelta is None
    assert fila.camara_id_anterior == ORIGEN and fila.cromo_botella_id_anterior == BOTELLA_ORIGEN
    assert fila.motivo == "Fontaine mal tipeado"
    session.commit.assert_called_once()  # el cambio y la auditoría, en un solo commit


def test_mover_con_botella_vigente_del_destino(fomon):
    objetivo = _ingreso()
    session = _session(objetivo, destino=_destino(), botellas=[_botella()])

    resultado = _mover(session, botella=BOTELLA_DESTINO)

    assert resultado.resultado == RESULTADO_OK_INGRESO_MOVIDO
    assert objetivo.camara_id == DESTINO and objetivo.cromo_botella_id == BOTELLA_DESTINO
    fila = _auditoria(session)
    assert fila.cromo_botella_id_resuelta == BOTELLA_DESTINO
    assert fila.cromo_botella_id_anterior == BOTELLA_ORIGEN


@pytest.mark.parametrize(
    ("botella_actual", "botella_pedida"),
    [(BOTELLA_ORIGEN, None), (None, BOTELLA_DESTINO), (BOTELLA_ORIGEN, BOTELLA_DESTINO)],
)
def test_mover_misma_camara_con_otra_botella_es_valido(fomon, botella_actual, botella_pedida):
    objetivo = _ingreso(camara_id=DESTINO, botella=botella_actual)
    session = _session(objetivo, destino=_destino(), botellas=[_botella()])

    resultado = _mover(session, botella=botella_pedida)

    assert resultado.resultado == RESULTADO_OK_INGRESO_MOVIDO
    assert objetivo.camara_id == DESTINO and objetivo.cromo_botella_id == botella_pedida


def test_mover_no_toca_el_estado_persistido_de_las_camaras(fomon):
    objetivo = _ingreso()
    origen = objetivo.camara
    destino = _destino()
    session = _session(objetivo, destino=destino)

    _mover(session)

    assert origen.estado == CamaraEstado.LIBRE and destino.estado == CamaraEstado.LIBRE


# ── Mover: validaciones ────────────────────────────────────────────────────────────────────────


def test_mover_ingreso_inexistente(fomon):
    session = _session(None, destino=_destino())

    resultado = _mover(session)

    assert resultado.resultado == RESULTADO_INGRESO_NO_ENCONTRADO
    fila = _auditoria(session)
    assert fila.resultado == RESULTADO_INGRESO_NO_ENCONTRADO and fila.ingreso_id is None
    assert fila.comando == COMANDO_MOVER_INGRESO and fila.origen == ORIGEN_WEB
    session.commit.assert_called_once()
    fomon["mock_abiertas"].assert_not_called()


def test_mover_ingreso_anulado(fomon):
    objetivo = _ingreso()
    objetivo.anulado_at, objetivo.anulado_por, objetivo.anulado_motivo = AHORA, "admin1", "nunca ocurrió"
    session = _session(objetivo, destino=_destino())

    resultado = _mover(session)

    assert resultado.resultado == RESULTADO_INGRESO_ANULADO
    assert objetivo.camara_id == ORIGEN and objetivo.cromo_botella_id == BOTELLA_ORIGEN
    fila = _auditoria(session)
    assert fila.resultado == RESULTADO_INGRESO_ANULADO and fila.ingreso_id == 42
    assert fila.camara_id_anterior == ORIGEN
    session.commit.assert_called_once()
    fomon["mock_abiertas"].assert_not_called()


@pytest.mark.parametrize("motivo", ["", "   ", "ab", "  ab  ", "x" * 501])
def test_mover_motivo_invalido(fomon, motivo):
    objetivo = _ingreso()
    session = _session(objetivo, destino=_destino())

    resultado = _mover(session, motivo=motivo)

    assert resultado.resultado == RESULTADO_MOTIVO_INVALIDO
    assert objetivo.camara_id == ORIGEN
    assert _auditoria(session).resultado == RESULTADO_MOTIVO_INVALIDO
    session.commit.assert_called_once()


@pytest.mark.parametrize("motivo", ["abc", "x" * 500])
def test_mover_motivo_en_los_bordes_es_valido(fomon, motivo):
    session = _session(_ingreso(), destino=_destino())

    assert _mover(session, motivo=motivo).resultado == RESULTADO_OK_INGRESO_MOVIDO


def test_mover_destino_inexistente(fomon):
    objetivo = _ingreso()
    session = _session(objetivo, destino=None)

    resultado = _mover(session)

    assert resultado.resultado == RESULTADO_CAMARA_NO_ENCONTRADA
    assert objetivo.camara_id == ORIGEN
    fila = _auditoria(session)
    assert fila.resultado == RESULTADO_CAMARA_NO_ENCONTRADA and fila.camara_id_resuelta is None
    assert fila.camara_texto_solicitado == f"camara_id={DESTINO}"
    fomon["mock_abiertas"].assert_not_called()


@pytest.mark.parametrize(
    "botellas",
    [
        [],  # inexistente
        [_botella(vigente=False)],
        [_botella(camara_id=ORIGEN)],
        [_botella(camara_id=None)],
    ],
    ids=["inexistente", "no_vigente", "de_otra_camara", "sin_camara"],
)
def test_mover_botella_invalida(fomon, botellas):
    objetivo = _ingreso()
    session = _session(objetivo, destino=_destino(), botellas=botellas)

    resultado = _mover(session, botella=BOTELLA_DESTINO)

    assert resultado.resultado == RESULTADO_BOTELLA_INVALIDA
    assert objetivo.camara_id == ORIGEN and objetivo.cromo_botella_id == BOTELLA_ORIGEN
    fila = _auditoria(session)
    assert fila.resultado == RESULTADO_BOTELLA_INVALIDA and fila.error_detalle
    session.commit.assert_called_once()
    fomon["mock_abiertas"].assert_not_called()


@pytest.mark.parametrize("botella", [None, BOTELLA_DESTINO])
def test_mover_misma_camara_y_misma_botella(fomon, botella):
    objetivo = _ingreso(camara_id=DESTINO, botella=botella)
    session = _session(objetivo, destino=_destino(), botellas=[_botella()])

    resultado = _mover(session, botella=botella)

    assert resultado.resultado == RESULTADO_MISMO_DESTINO
    assert _auditoria(session).resultado == RESULTADO_MISMO_DESTINO
    session.commit.assert_called_once()
    fomon["mock_abiertas"].assert_not_called()


# ── Mover: FO Monitor ──────────────────────────────────────────────────────────────────────────


def test_mover_recalcula_el_alcance_de_la_intervencion_para_el_destino(fomon):
    interv = _interv(301)
    fomon["abiertas"] = [interv]
    session = _session(_ingreso(), destino=_destino(), botellas=[_botella()])

    resultado = _mover(session, botella=BOTELLA_DESTINO)

    fomon["mock_resolver"].assert_called_once_with(session, DESTINO, BOTELLA_DESTINO)
    assert interv.camara_id == DESTINO and interv.botella_objetivo_n_id == BOTELLA_DESTINO
    assert interv.botella_1_inferida is False
    # La lista congelada vieja se borra y se escribe la del destino.
    modelos = [c.args[0] for c in session.query.call_args_list]
    assert FomonIntervencionServicio in modelos
    session.query.return_value.filter.return_value.delete.assert_called_once_with(synchronize_session=False)
    congelados = _servicios_congelados(session)
    assert {(f.cable_n_id, f.servicio_pk) for f in congelados} == {(801, 77), (802, None)}
    assert all(f.intervencion_id == 301 for f in congelados)
    assert interv.estado == "EN_CURSO", "sin consultas en vuelo, el estado no cambia"
    assert resultado.intervenciones_fomon == [301] and resultado.intervenciones_fomon_omitidas == []


def test_mover_sin_botella_toma_la_botella_1_del_destino(fomon):
    interv = _interv(301)
    fomon["abiertas"] = [interv]
    session = _session(_ingreso(), destino=_destino())

    _mover(session)

    fomon["mock_resolver"].assert_called_once_with(session, DESTINO, None)
    assert interv.camara_id == DESTINO
    assert interv.botella_objetivo_n_id == 6999 and interv.botella_1_inferida is True


@pytest.mark.parametrize(
    ("estado", "estado_final"),
    [("PRE_EN_CURSO", "PRE_PENDIENTE"), ("POST_EN_CURSO", "POST_PENDIENTE")],
)
def test_mover_cancela_consultas_pendientes_y_vuelve_a_planificar(fomon, estado, estado_final):
    """Las PENDIENTE se armaron con el alcance viejo: se cancelan, y la intervención vuelve a la fase
    pendiente para que `planificar_consultas` cree las del alcance nuevo en el próximo tick."""
    interv = _interv(301, estado=estado)
    fomon["abiertas"] = [interv]
    pendiente = FomonConsulta(id=1, intervencion_id=301, fase="PRE", estado="PENDIENTE")
    session = _session(_ingreso(), destino=_destino(), consultas=[pendiente])

    resultado = _mover(session)

    assert pendiente.estado == "CANCELADA" and pendiente.error == "alcance_recalculado"
    assert interv.estado == estado_final and interv.proximo_evento_en == AHORA
    assert interv.aviso_ts is None and interv.aviso_canal is None
    assert resultado.intervenciones_fomon == [301]


def test_mover_omite_la_intervencion_que_ya_consulto_a_burrito(fomon):
    interv = _interv(301, estado="EN_CURSO")
    fomon["abiertas"] = [interv]
    fomon["enviadas"] = {301}
    pendiente = FomonConsulta(id=1, intervencion_id=301, fase="POST", estado="PENDIENTE")
    session = _session(_ingreso(), destino=_destino(), consultas=[pendiente])

    resultado = _mover(session)

    assert resultado.resultado == RESULTADO_OK_INGRESO_MOVIDO
    assert resultado.intervenciones_fomon == []
    assert resultado.intervenciones_fomon_omitidas == [IntervencionFomonOmitida(301, OMISION_CONSULTAS_YA_ENVIADAS)]
    assert (interv.camara_id, interv.botella_objetivo_n_id, interv.estado) == (ORIGEN, BOTELLA_ORIGEN, "EN_CURSO")
    assert pendiente.estado == "PENDIENTE"
    fomon["mock_resolver"].assert_not_called()
    assert _servicios_congelados(session) == []


def test_mover_omite_intervencion_con_otro_ingreso_vigente_en_otra_camara(fomon):
    """"Botella 1 y 2" en el mismo hilo: mover una sola de las filas no se lleva la intervención,
    que sigue verificando la que quedó en la cámara original."""
    interv = _interv(301)
    fomon["abiertas"] = [interv]
    fomon["otros"] = {301: [_ingreso(camara_id=ORIGEN)]}
    session = _session(_ingreso(), destino=_destino())

    resultado = _mover(session)

    assert interv.camara_id == ORIGEN and interv.botella_objetivo_n_id == BOTELLA_ORIGEN
    assert resultado.intervenciones_fomon == []
    assert resultado.intervenciones_fomon_omitidas == [IntervencionFomonOmitida(301, OMISION_OTROS_INGRESOS_VIGENTES)]
    assert resultado.resultado == RESULTADO_OK_INGRESO_MOVIDO
    fomon["mock_resolver"].assert_not_called()


def test_mover_actualiza_si_los_otros_ingresos_ya_estan_en_el_destino(fomon):
    interv = _interv(301)
    fomon["abiertas"] = [interv]
    fomon["otros"] = {301: [_ingreso(camara_id=DESTINO)]}
    session = _session(_ingreso(), destino=_destino())

    resultado = _mover(session)

    assert interv.camara_id == DESTINO
    assert resultado.intervenciones_fomon == [301]


def test_mover_marca_atribucion_compartida_si_el_destino_tiene_otra_abierta(fomon):
    interv = _interv(301)
    otra = _interv(302)
    otra.camara_id = DESTINO
    fomon["abiertas"] = [interv]
    fomon["otras_en_destino"] = [otra]
    session = _session(_ingreso(), destino=_destino())

    _mover(session)

    assert interv.atribucion_compartida is True and otra.atribucion_compartida is True


# ── Anular: camino feliz ───────────────────────────────────────────────────────────────────────


def test_anular_setea_la_baja_logica_y_audita(fomon):
    objetivo = _ingreso()
    camara = objetivo.camara
    session = _session(objetivo)

    resultado = _anular(session)

    assert resultado.resultado == RESULTADO_OK_INGRESO_ANULADO
    assert objetivo.anulado_at == AHORA and objetivo.anulado_at.tzinfo is not None
    assert objetivo.anulado_por == "admin2"
    assert objetivo.anulado_motivo == "nunca ocurrió"
    assert objetivo.fecha_fin is None and objetivo.camara_id == ORIGEN
    assert camara.estado == CamaraEstado.LIBRE, "Camara.estado persistido no se toca"
    fila = _auditoria(session)
    assert fila.comando == COMANDO_ANULAR_INGRESO
    assert fila.origen == ORIGEN_WEB and fila.actor_web_usuario == "admin2"
    assert fila.resultado == RESULTADO_OK_INGRESO_ANULADO
    assert fila.ingreso_id == 42 and fila.camara_id_resuelta == ORIGEN
    assert fila.motivo == "nunca ocurrió"
    assert fila.momento_efectivo == AHORA
    assert fila.camara_id_anterior is None and fila.cromo_botella_id_anterior is None
    session.commit.assert_called_once()  # la baja lógica y la auditoría, en un solo commit


def test_anular_no_reabre_ni_consulta_el_caso_sin_match(fomon):
    """Decisión 4: el `IngresoSinMatch` que había resuelto el ingreso queda como está."""
    from db.models.infra import IngresoSinMatch

    session = _session(_ingreso())

    _anular(session)

    modelos = [c.args[0] for c in session.query.call_args_list]
    assert IngresoSinMatch not in modelos


def test_anular_trunca_el_autor_al_largo_de_la_columna(fomon):
    objetivo = _ingreso()
    session = _session(objetivo)

    _anular(session, usuario="u" * 200)

    assert len(objetivo.anulado_por) == 128
    assert len(_auditoria(session).actor_web_usuario) == 64


@pytest.mark.parametrize("tipo", [IngresoTipo.EGRESO, IngresoTipo.INTENTO_BLOQUEADO])
def test_anular_acepta_cualquier_tipo_de_fila(fomon, tipo):
    objetivo = _ingreso(tipo=tipo)
    session = _session(objetivo)

    assert _anular(session).resultado == RESULTADO_OK_INGRESO_ANULADO
    assert objetivo.anulado_at == AHORA


# ── Anular: validaciones ───────────────────────────────────────────────────────────────────────


def test_anular_ingreso_inexistente(fomon):
    session = _session(None)

    resultado = _anular(session)

    assert resultado.resultado == RESULTADO_INGRESO_NO_ENCONTRADO
    fila = _auditoria(session)
    assert fila.comando == COMANDO_ANULAR_INGRESO and fila.ingreso_id is None
    session.commit.assert_called_once()
    fomon["mock_abiertas"].assert_not_called()


def test_anular_ya_anulado_no_pisa_la_anulacion_previa(fomon):
    previo = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
    objetivo = _ingreso()
    objetivo.anulado_at, objetivo.anulado_por, objetivo.anulado_motivo = previo, "admin1", "primera vez"
    session = _session(objetivo)

    resultado = _anular(session)

    assert resultado.resultado == RESULTADO_INGRESO_ANULADO
    assert resultado.respuesta == "El ingreso #42 ya está anulado."
    assert (objetivo.anulado_at, objetivo.anulado_por, objetivo.anulado_motivo) == (previo, "admin1", "primera vez")
    assert _auditoria(session).resultado == RESULTADO_INGRESO_ANULADO
    session.commit.assert_called_once()
    fomon["mock_abiertas"].assert_not_called()


@pytest.mark.parametrize("motivo", ["", "  ", "no", "x" * 501])
def test_anular_motivo_invalido(fomon, motivo):
    objetivo = _ingreso()
    session = _session(objetivo)

    resultado = _anular(session, motivo=motivo)

    assert resultado.resultado == RESULTADO_MOTIVO_INVALIDO
    assert objetivo.anulado_at is None
    assert _auditoria(session).resultado == RESULTADO_MOTIVO_INVALIDO
    session.commit.assert_called_once()
    fomon["mock_abiertas"].assert_not_called()


# ── Anular: FO Monitor ─────────────────────────────────────────────────────────────────────────


def test_anular_cancela_la_intervencion_abierta_y_sus_consultas_pendientes(fomon):
    interv = _interv(301, estado="PRE_EN_CURSO")
    interv.proximo_evento_en = AHORA
    fomon["abiertas"] = [interv]
    pendiente = FomonConsulta(id=1, intervencion_id=301, fase="PRE", estado="PENDIENTE")
    session = _session(_ingreso(), consultas=[pendiente])

    resultado = _anular(session)

    assert interv.estado == "CANCELADA"
    assert interv.cerrada_at == AHORA
    assert interv.proximo_evento_en is None
    assert pendiente.estado == "CANCELADA" and pendiente.error == "ingreso_anulado"
    assert resultado.intervenciones_fomon == [301] and resultado.intervenciones_fomon_omitidas == []


def test_anular_no_cancela_la_intervencion_si_le_quedan_otros_ingresos_vigentes(fomon):
    interv = _interv(301)
    fomon["abiertas"] = [interv]
    fomon["otros"] = {301: [_ingreso()]}
    session = _session(_ingreso())

    resultado = _anular(session)

    assert interv.estado == "EN_CURSO" and interv.cerrada_at is None
    assert resultado.intervenciones_fomon == []
    assert resultado.intervenciones_fomon_omitidas == [IntervencionFomonOmitida(301, OMISION_OTROS_INGRESOS_VIGENTES)]
    assert resultado.resultado == RESULTADO_OK_INGRESO_ANULADO


# ── Ronda de revisión: atomicidad, destino no raíz, FO Monitor después de la PRE ───────────────


@pytest.mark.parametrize("operacion", ["mover", "anular"])
def test_si_falla_el_commit_unico_hace_rollback_y_propaga(fomon, operacion):
    """El cambio y la auditoría van en un solo commit: si falla, no se devuelve un OK sin rastro."""
    session = _session(_ingreso(), destino=_destino())
    session.commit.side_effect = RuntimeError("INSERT de auditoría rechazado")

    with pytest.raises(RuntimeError):
        _mover(session) if operacion == "mover" else _anular(session)

    session.commit.assert_called_once()
    session.rollback.assert_called_once()


def test_un_rechazo_con_fallo_de_auditoria_sigue_sin_propagar(fomon):
    """Los rechazos no cambian nada: conservan el comportamiento anterior (se loguea y se responde)."""
    session = _session(None)
    session.commit.side_effect = RuntimeError("caída")

    resultado = _mover(session)

    assert resultado.resultado == RESULTADO_INGRESO_NO_ENCONTRADO and resultado.auditoria is None


def test_mover_rechaza_destino_que_no_es_camara_raiz(fomon):
    objetivo = _ingreso()
    destino = _destino()
    destino.camara_padre_id = 3
    session = _session(objetivo, destino=destino)

    resultado = _mover(session)

    assert resultado.resultado == RESULTADO_DESTINO_NO_RAIZ
    assert "cámara raíz" in resultado.respuesta and "administrador" not in resultado.respuesta
    assert objetivo.camara_id == ORIGEN
    fila = _auditoria(session)
    assert fila.resultado == RESULTADO_DESTINO_NO_RAIZ and fila.camara_id_resuelta == DESTINO
    session.commit.assert_called_once()
    fomon["mock_abiertas"].assert_not_called()


def test_mover_permite_destino_pendiente_de_revision(fomon):
    destino = _destino()
    destino.estado = CamaraEstado.PENDIENTE_REVISION
    session = _session(_ingreso(), destino=destino)

    assert _mover(session).resultado == RESULTADO_OK_INGRESO_MOVIDO


@pytest.mark.parametrize("estado", ["EN_CURSO", "SIN_EGRESO", "POST_PENDIENTE", "POST_EN_CURSO"])
def test_mover_despues_de_la_pre_marca_sin_linea_base_y_limpia_el_aviso(fomon, estado):
    interv = _interv(301, estado=estado)
    fomon["abiertas"] = [interv]
    session = _session(_ingreso(), destino=_destino())

    _mover(session)

    assert interv.sin_linea_base is True
    assert interv.aviso_ts is None and interv.aviso_canal is None


def test_mover_despues_de_la_pre_sin_servicios_no_marca_sin_linea_base(fomon):
    interv = _interv(301, estado="EN_CURSO")
    fomon["abiertas"] = [interv]
    fomon["con_servicios"] = False
    session = _session(_ingreso(), destino=_destino())

    _mover(session)

    assert interv.sin_linea_base is False
    assert interv.aviso_ts is None


@pytest.mark.parametrize("estado", ["PRE_PENDIENTE", "PRE_EN_CURSO"])
def test_mover_antes_de_la_pre_no_marca_sin_linea_base(fomon, estado):
    """La PRE todavía se mide, con el alcance nuevo."""
    interv = _interv(301, estado=estado)
    fomon["abiertas"] = [interv]
    session = _session(_ingreso(), destino=_destino())

    _mover(session)

    assert interv.sin_linea_base is False
