# Nombre de archivo: test_ingreso_reproceso.py
# Ubicación de archivo: tests/test_ingreso_reproceso.py
# Descripción: Pruebas del reproceso por lote de ingresos sin match (servicio, egreso histórico acotado, multi-bot con "Bot" genérico)

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.services import ingreso_reproceso_service as rs
from core.services.cromo.camara_botella_busqueda import ResultadoBusquedaExtendida
from core.services.ingreso_service import registrar_egreso_historico
from db.models.cromo import CromoBotella
from db.models.infra import Camara, Ingreso, IngresoSinMatch, IngresoTipo
from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError, detectar_multi_bot

MOMENTO = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
CAMARA = Camara(id=7, nombre="Cra Monteagudo 202 CF")


def _mensaje(tipo: str, nombre: str) -> str:
    return (
        "*Cual es el numero de Ticket MKT? o Numero de Linea*\n1308683\n"
        f"*Nombre: Nodo/Camara/botella*\n{nombre}\n*Ingreso o Egreso*\n{tipo}\n"
        "Persona que solicito La Autorizacion\n<@U06MWM95DTP>"
    )


def _caso(id_: int, tipo: str, nombre: str, *, texto_original: str | None = None) -> IngresoSinMatch:
    return IngresoSinMatch(
        id=id_, texto_original=texto_original or nombre, origen="slack", contexto="C1",
        thread_ts=f"17000000{id_}.0001", texto_mensaje=_mensaje(tipo, nombre), created_at=MOMENTO,
        revisado=False, resuelto_via_empalme=False, resuelto_via_revalidacion=False,
    )


def _resultado(camara=CAMARA, botella=None) -> ResultadoBusquedaExtendida:
    return ResultadoBusquedaExtendida(camara=camara, nombre_norm="x", fuente="camara", botella=botella)


@pytest.fixture
def sin_nodos():
    with patch.object(rs, "corresponde_a_nodo", return_value=False):
        yield


def _session_sin_existentes() -> MagicMock:
    session = MagicMock()
    session.query.return_value.filter.return_value.filter.return_value.first.return_value = None
    return session


# ── Multi-bot con "Bot" genérico al principio (bug real hallado en el ensayo) ───────────────────


def test_multi_bot_descarta_bot_generico_al_principio():
    assert detectar_multi_bot("Bot monteagudo 202 bot1 y bot2") == ["monteagudo 202", "Bot 2 monteagudo 202"]
    assert detectar_multi_bot("Bot 2 y 3 Cra X") == ["Bot 2 Cra X", "Bot 3 Cra X"]


def test_nombres_del_caso_ya_separado_por_el_listener_viejo_usa_solo_su_parte():
    caso = _caso(1, "Ingreso", "Bartolomé Mitre 301. Botella 1 y 2. CF", texto_original="Bot 2 Bartolomé Mitre 301 CF")
    assert rs._nombres_del_caso(caso, "Bartolomé Mitre 301. Botella 1 y 2. CF") == ["Bot 2 Bartolomé Mitre 301 CF"]


def test_nombres_del_caso_no_separado_antes_usa_todas_las_partes():
    caso = _caso(1, "Ingreso", "Cra monteagudo 202 bot1 y bot2")
    assert rs._nombres_del_caso(caso, "Cra monteagudo 202 bot1 y bot2") == [
        "Cra monteagudo 202",
        "Bot 2 Cra monteagudo 202",
    ]


# ── Servicio ───────────────────────────────────────────────────────────────────────────────────


def test_ingreso_resuelto_se_registra_con_el_horario_original_y_como_ingreso_real(sin_nodos):
    caso = _caso(5, "Ingreso", "Cra huergo701")
    session = _session_sin_existentes()
    fila = Ingreso(id=99, camara_id=7, tipo=IngresoTipo.INGRESO)
    with patch.object(rs, "buscar_camara_o_botella_cromo", return_value=_resultado()), patch.object(
        rs, "registrar_movimiento_ingreso", return_value=fila
    ) as registrar:
        item = rs._procesar_caso(session, caso, client=None)
    assert item.estado == rs.REGISTRADO
    kwargs = registrar.call_args.kwargs
    assert kwargs["momento"] == MOMENTO and kwargs["tipo_movimiento"] == "Ingreso"
    assert kwargs["thread_ts"] == caso.thread_ts and kwargs["tecnico_nombre"] == "U06MWM95DTP"
    assert caso.ingreso_id == 99 and caso.resuelto_via_revalidacion is True


def test_egreso_usa_el_egreso_historico_acotado(sin_nodos):
    caso = _caso(6, "Egreso", "Cra huergo701")
    fila = Ingreso(id=42, camara_id=7, tipo=IngresoTipo.INGRESO)
    with patch.object(rs, "buscar_camara_o_botella_cromo", return_value=_resultado()), patch.object(
        rs, "registrar_egreso_historico", return_value=(fila, True)
    ) as egreso, patch.object(rs, "registrar_movimiento_ingreso") as en_vivo:
        item = rs._procesar_caso(_session_sin_existentes(), caso, client=None)
    en_vivo.assert_not_called()
    assert egreso.call_args.kwargs["momento"] == MOMENTO
    assert item.movimientos[0].accion == "egreso_cerro_existente"


def test_nodo_se_marca_revisado_sin_registrar():
    caso = _caso(7, "Ingreso", "Barrio Norte")
    with patch.object(rs, "corresponde_a_nodo", return_value=True), patch.object(
        rs, "buscar_camara_o_botella_cromo"
    ) as buscar:
        item = rs._procesar_caso(MagicMock(), caso, client=None)
    buscar.assert_not_called()
    assert item.estado == rs.NODO and caso.revisado is True and caso.ingreso_id is None


@pytest.mark.parametrize(
    ("efecto", "estado"),
    [(AmbiguousSearchError("x", 2, ["a", "b"]), rs.AMBIGUO), (None, rs.SIN_MATCH)],
)
def test_no_resuelto_no_toca_el_caso(sin_nodos, efecto, estado):
    caso = _caso(8, "Ingreso", "Cra zepita 3101")
    buscar = {"side_effect": efecto} if efecto else {"return_value": _resultado(camara=None)}
    session = MagicMock()
    with patch.object(rs, "buscar_camara_o_botella_cromo", **buscar):
        item = rs._procesar_caso(session, caso, client=None)
    assert item.estado == estado
    assert caso.resuelto_via_revalidacion is False and caso.ingreso_id is None
    session.commit.assert_not_called()


def test_multi_bot_no_escribe_nada_si_una_parte_no_resuelve(sin_nodos):
    """Todas las búsquedas van antes de la primera escritura: un multi-bot a medias no deja una
    botella registrada y la otra no."""
    caso = _caso(9, "Ingreso", "Cra monteagudo 202 bot1 y bot2")
    with patch.object(rs, "buscar_camara_o_botella_cromo", side_effect=[_resultado(), _resultado(camara=None)]), patch.object(
        rs, "registrar_movimiento_ingreso"
    ) as registrar:
        item = rs._procesar_caso(MagicMock(), caso, client=None)
    registrar.assert_not_called()
    assert item.estado == rs.SIN_MATCH


def test_no_duplica_un_movimiento_que_el_hilo_ya_tiene(sin_nodos):
    caso = _caso(10, "Ingreso", "Cra huergo701")
    existente = Ingreso(id=5, camara_id=7, tipo=IngresoTipo.INGRESO)
    session = MagicMock()
    session.query.return_value.filter.return_value.filter.return_value.first.return_value = existente
    with patch.object(rs, "buscar_camara_o_botella_cromo", return_value=_resultado()), patch.object(
        rs, "registrar_movimiento_ingreso"
    ) as registrar:
        item = rs._procesar_caso(session, caso, client=None)
    registrar.assert_not_called()
    assert item.estado == rs.YA_EXISTIA and caso.ingreso_id == 5


def test_un_error_en_un_caso_no_frena_el_lote():
    casos = [_caso(1, "Ingreso", "a"), _caso(2, "Ingreso", "b")]
    session = MagicMock()
    ok = rs.CasoReprocesado(caso_id=2, created_at="", texto_original="b", estado=rs.SIN_MATCH)
    with patch.object(rs, "_candidatos", return_value=casos), patch.object(
        rs, "_procesar_caso", side_effect=[RuntimeError("db"), ok]
    ):
        reporte = rs.reprocesar_ingresos_sin_match(session)
    assert [r.estado for r in reporte] == [rs.ERROR, rs.SIN_MATCH]
    session.rollback.assert_called_once()


# ── Egreso histórico acotado en el tiempo ──────────────────────────────────────────────────────


def _filtros_de(session: MagicMock) -> list:
    return list(session.query.return_value.filter.call_args.args)


def test_egreso_historico_solo_cierra_ingresos_anteriores():
    session = MagicMock()
    abierto = Ingreso(id=3, camara_id=7, tipo=IngresoTipo.INGRESO, fecha_inicio=MOMENTO - timedelta(hours=2))
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = abierto
    fila, cerro = registrar_egreso_historico(
        session, camara=CAMARA, botella=None, tecnico_nombre="U06MWM95DTP", slack_user_id="U06MWM95DTP", momento=MOMENTO
    )
    assert cerro is True and fila.fecha_fin == MOMENTO
    filtro_fecha = [f for f in _filtros_de(session) if getattr(getattr(f, "left", None), "key", None) == "fecha_inicio"]
    assert filtro_fecha and filtro_fecha[0].operator.__name__ == "lt"
    assert filtro_fecha[0].right.value == MOMENTO


def test_egreso_historico_sin_ingreso_anterior_crea_huerfano():
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    botella = CromoBotella(n_id=6634108, nombre="Bot 2")
    fila, cerro = registrar_egreso_historico(
        session, camara=CAMARA, botella=botella, tecnico_nombre=None, slack_user_id=None, momento=MOMENTO, thread_ts="t"
    )
    assert cerro is False
    assert fila.tipo == IngresoTipo.EGRESO and fila.fecha_inicio is None and fila.fecha_fin == MOMENTO
    assert fila.cromo_botella_id == 6634108 and fila.thread_ts == "t"
    session.add.assert_called_once_with(fila)
