# Nombre de archivo: test_slack_track_servicio.py
# Ubicación de archivo: tests/test_slack_track_servicio.py
# Descripción: Pruebas del comando de Slack "@bot track <id>" — parser del comando y resolución del Servicio por sus tres identidades

"""El parser se prueba puro (sin DB) y la resolución del Servicio contra Postgres real.

La resolución va contra un motor real y no contra un mock a propósito: lo que se prueba es que
`alias_ids` (un `ARRAY` de Postgres) matchee con `contains`, y un mock de sesión devolvería lo que
uno le dicte sin ejercitar el operador de array.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from db.session import SessionLocal
from modules.slack_baneo_notifier.tracking_servicio import extraer_comando_track
from tests.soporte_postgres_real import requiere_postgres_real

_NUMERO_ACTUAL = "9999201"
_NUMERO_PRIMERO = "9999202"
_ALIAS = "9999203"


# ── Parser del comando ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("track 67395", "67395"),
        ("Track 67395", "67395"),
        ("TRACK 67395", "67395"),
        # Slack manda el mrkdwn con los caracteres literales: un técnico que resalta el número en
        # negrita es uso normal, y ya rompió el comando "Info cable" una vez (2026-08-25).
        ("track *67395*", "67395"),
        ("track `67395`", "67395"),
        # Espacios de más, que es lo que queda al copiar y pegar.
        ("  track   67395  ", "67395"),
        # "tracking" como sinónimo: es como se lo nombra en la UI.
        ("tracking 67395", "67395"),
    ],
)
def test_extrae_el_id_del_comando(texto, esperado):
    assert extraer_comando_track(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "track",
        "track abc",
        "track 67395 y algo mas",
        # No debe robarle el mensaje a los comandos que ya existen.
        "info cable F-VFL-IND",
        "verificar cable F-VFL-IND B1",
        "servicios F-VFL-IND",
        "",
        "hola",
        # "track" adentro de otra palabra no es el comando.
        "trackear 67395",
    ],
)
def test_ignora_lo_que_no_es_el_comando(texto):
    assert extraer_comando_track(texto) is None


# ── Resolución del Servicio por sus tres identidades ─────────────────────────


@pytest.fixture
def servicio_con_tres_identidades():
    """Un Servicio cuyo ID actual, primer servicio y alias son los tres distintos: si el resolver
    mirara una sola columna, dos de los tres casos pasarían igual y el test no probaría nada."""
    with SessionLocal() as session:
        servicio_id = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios "
                    "(servicio_id, numero_primer_servicio, alias_ids, categoria, origen_datos, estado_servicio) "
                    "VALUES (:actual, :primero, :alias ::varchar[], 0, 'INFERIDO_CROMO', 'DESCONOCIDO') "
                    "RETURNING id"
                ),
                {"actual": _NUMERO_ACTUAL, "primero": _NUMERO_PRIMERO, "alias": [_ALIAS]},
            ).scalar_one()
        )
        session.commit()
    try:
        yield servicio_id
    finally:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM app.servicios WHERE id = :s"), {"s": servicio_id})
            session.commit()


@requiere_postgres_real
@pytest.mark.parametrize(
    "identidad",
    [_NUMERO_ACTUAL, _NUMERO_PRIMERO, _ALIAS],
    ids=["por servicio_id", "por numero_primer_servicio", "por alias historico"],
)
def test_resuelve_el_servicio_por_cualquiera_de_sus_tres_identidades(
    servicio_con_tres_identidades, identidad
):
    from modules.slack_baneo_notifier.tracking_servicio import resolver_servicio

    with SessionLocal() as session:
        servicio = resolver_servicio(session, identidad)

    assert servicio is not None, f"'{identidad}' es una identidad válida del mismo Servicio"
    assert servicio.id == servicio_con_tres_identidades


@requiere_postgres_real
def test_devuelve_none_si_el_id_no_existe():
    from modules.slack_baneo_notifier.tracking_servicio import resolver_servicio

    with SessionLocal() as session:
        assert resolver_servicio(session, "9999299") is None


# ── Handler del listener ─────────────────────────────────────────────────────

from types import SimpleNamespace  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import modules.slack_baneo_notifier.tracking_servicio as ts_mod  # noqa: E402


def _listener():
    from modules.slack_baneo_notifier.listener import IngresoListener

    return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")


def _mencion(texto: str) -> dict:
    return {"text": f"<@U0BOT> {texto}", "channel": "C123", "ts": "1.1"}


def test_la_mencion_track_no_cae_en_los_parsers_de_cable():
    """El despacho prueba `track` primero. Si cayera en los parsers "golosos" de cable, un
    "track 67395" terminaría buscando un cable llamado "67395"."""
    listener = _listener()
    with patch.object(listener, "_handle_track") as handler:
        listener._handle_app_mention(_mencion("track 67395"), MagicMock())
    handler.assert_called_once()
    assert handler.call_args[0][0] == "67395"


def test_servicio_inexistente_responde_y_no_sube_nada():
    listener = _listener()
    client = MagicMock()
    with patch.object(ts_mod, "resolver_servicio", return_value=None):
        listener._handle_track("9999299", client, "C123", "1.1")

    client.files_upload_v2.assert_not_called()
    texto = client.chat_postMessage.call_args[1]["text"]
    assert "9999299" in texto and "No encontré" in texto


def test_sube_un_archivo_por_pelo_al_hilo():
    listener = _listener()
    client = MagicMock()
    servicio = SimpleNamespace(id=737, servicio_id="120393", nombre_cliente="ESPN SUR SRL")
    resultado = ts_mod.ResultadoTrack(
        estado=ts_mod.ESTADO_OK,
        archivos=[
            ts_mod.TrackingArchivo("a_7134826.txt", "contenido A", True, 10),
            ts_mod.TrackingArchivo("a_7134827.txt", "contenido B", False, 5200),
        ],
    )
    with patch.object(ts_mod, "resolver_servicio", return_value=servicio), patch.object(
        ts_mod, "generar_trackings", return_value=resultado
    ):
        listener._handle_track("67395", client, "C123", "1.1")

    assert client.files_upload_v2.call_count == 2
    for llamada in client.files_upload_v2.call_args_list:
        # Todo va al hilo de la mención, no al canal suelto.
        assert llamada[1]["thread_ts"] == "1.1"
        assert llamada[1]["channel"] == "C123"
    nombres = [c[1]["filename"] for c in client.files_upload_v2.call_args_list]
    assert nombres == ["a_7134826.txt", "a_7134827.txt"]
    # Y avisa antes de empezar: en frío esto tarda minutos y sin aviso parece que no hizo nada.
    assert "Generando" in client.chat_postMessage.call_args_list[0][1]["text"]


def test_sin_semilla_avisa_el_motivo_y_no_sube_un_txt_vacio():
    listener = _listener()
    client = MagicMock()
    servicio = SimpleNamespace(id=1, servicio_id="111", nombre_cliente="X")
    resultado = ts_mod.ResultadoTrack(estado="SIN_SEMILLA", mensaje="El Servicio no tiene ningún pelo en Cromo.")
    with patch.object(ts_mod, "resolver_servicio", return_value=servicio), patch.object(
        ts_mod, "generar_trackings", return_value=resultado
    ):
        listener._handle_track("111", client, "C123", "1.1")

    client.files_upload_v2.assert_not_called()
    assert "no tiene ningún pelo" in client.chat_postMessage.call_args[1]["text"]


def test_un_pelo_fallado_no_cancela_los_demas_pero_se_reporta():
    """Con caminos faltantes se dice cuántos se esperaban y por qué fallaron."""
    listener = _listener()
    client = MagicMock()
    servicio = SimpleNamespace(id=1, servicio_id="111", nombre_cliente="X")
    resultado = ts_mod.ResultadoTrack(
        estado=ts_mod.ESTADO_OK,
        archivos=[ts_mod.TrackingArchivo("ok.txt", "x", True, 1)],
        errores=["Pelo 42: Cromo no devolvió camino"],
        esperados_declarados=2,
        completo=False,
    )
    with patch.object(ts_mod, "resolver_servicio", return_value=servicio), patch.object(
        ts_mod, "generar_trackings", return_value=resultado
    ):
        listener._handle_track("111", client, "C123", "1.1")

    assert client.files_upload_v2.call_count == 1
    assert "Pelo 42" in client.chat_postMessage.call_args_list[-1][1]["text"]


def _ok(n: int, **kw):
    return ts_mod.ResultadoTrack(
        estado=ts_mod.ESTADO_OK,
        archivos=[
            ts_mod.TrackingArchivo(f"94673 CROMO T{i} pelo {i}.txt", "a", False, 1)
            for i in range(1, n + 1)
        ],
        **kw,
    )


def test_segmentado_sube_un_archivo_por_tramo_y_avisa_segmentos_y_trackings():
    """102452: 3 pares de hilos (6 trackings) sobre 3 segmentos físicos."""
    listener = _listener()
    client = MagicMock()
    servicio = SimpleNamespace(id=1168, servicio_id="102452", nombre_cliente="X")
    resultado = _ok(6, segmentos=3)
    with patch.object(ts_mod, "resolver_servicio", return_value=servicio), patch.object(
        ts_mod, "generar_trackings", return_value=resultado
    ):
        listener._handle_track("102452", client, "C123", "1.1")

    assert client.files_upload_v2.call_count == 6
    assert (
        "Servicio segmentado en 3 tramos (6 trackings)."
        in client.chat_postMessage.call_args_list[-1][1]["text"]
    )


def test_un_par_de_hilos_no_es_segmentacion():
    """42351: dos hilos del mismo recorrido son UN segmento: no hay nada que avisar (I4)."""
    assert ts_mod.mensaje_resumen(_ok(2, segmentos=1)) is None


def test_un_tramo_completo_no_avisa_nada():
    assert ts_mod.mensaje_resumen(_ok(1)) is None


def test_esperados_distintos_de_generados_se_avisa():
    aviso = ts_mod.mensaje_resumen(_ok(2, segmentos=1, esperados_declarados=3))
    assert "segmentado" not in aviso
    assert "Se esperaban 3 trackings y se generaron 2." in aviso


def test_esperados_iguales_a_generados_no_se_avisa():
    assert ts_mod.mensaje_resumen(_ok(1, esperados_declarados=1)) is None


def test_incompleto_por_tope_avisa_semillas_errores_y_tope():
    aviso = ts_mod.mensaje_resumen(
        _ok(1, completo=False, errores=["Pelo 42: sin camino"], no_cubiertos=5, tope_llamadas=True)
    )
    assert ":warning: Tracking incompleto: 5 semilla(s) no resolvieron." in aviso
    assert "• Pelo 42: sin camino" in aviso
    assert "Se alcanzó el tope de consultas a Cromo." in aviso


def test_semillas_fallidas_sin_tope_avisan_sin_culpar_al_tope():
    """I3: con `completo=True` y semillas fallidas (menos que el tope de fallidas) puede faltar un
    tramo entero: se avisa, y no se menciona el tope porque no se tocó."""
    aviso = ts_mod.mensaje_resumen(
        _ok(1, completo=True, errores=["Pelo 42: sin camino"], no_cubiertos=1)
    )
    assert ":warning: Tracking incompleto: 1 semilla(s) no resolvieron." in aviso
    assert "• Pelo 42: sin camino" in aviso
    assert "tope" not in aviso


def test_corte_por_fallidas_no_menciona_el_tope_de_consultas():
    errores = [f"Pelo {i}: sin camino" for i in range(10)]
    aviso = ts_mod.mensaje_resumen(_ok(1, completo=False, errores=errores, no_cubiertos=40))
    assert ":warning: Tracking incompleto: 40 semilla(s) no resolvieron." in aviso
    assert "tope" not in aviso


def test_los_residuales_no_se_mencionan_en_slack():
    assert not hasattr(ts_mod, "_describir_pelo")
    assert not hasattr(ts_mod, "_MAX_HUERFANOS_LISTADOS")
    assert "residual" not in (ts_mod.mensaje_resumen(_ok(2)) or "").lower()


# ── Posición vigente, adicionales y `track N full` (Task 7) ──────────────────

from datetime import datetime, timezone  # noqa: E402

from core.services.cromo.servicio_posicion_vigente import (  # noqa: E402
    MOTIVO_PELO_CAMBIO,
    TEXTO_CALCULO_AUTOMATICO,
    AvisoPosicion,
)
from core.services.cromo.tracking_service import (  # noqa: E402
    EstadoPosicion,
    InfoAdicional,
    TrackingGenerado,
    TrackingsDelServicio,
)

_LINEA_ADICIONALES_SIN_DECLARAR = (
    "Hay 2 camino(s) óptico(s) adicional(es) por O-1252871-1:1,2 (pelos con etiqueta 44649). "
    "Declarar la posición vigente en el Detalle de Servicio."
)


def test_resumen_avisa_adicionales_sin_declaracion():
    aviso = ts_mod.mensaje_resumen(
        _ok(
            2,
            adicionales=2,
            posiciones_adicionales="O-1252871-1:1,2",
            etiquetas_adicionales="44649",
            numero_servicio="93150",
        )
    )
    assert aviso == _LINEA_ADICIONALES_SIN_DECLARAR


def test_resumen_adicionales_sin_etiqueta_omite_el_parentesis():
    aviso = ts_mod.mensaje_resumen(
        _ok(2, adicionales=1, posiciones_adicionales="O-1252871-1:1", numero_servicio="93150")
    )
    assert aviso == (
        "Hay 1 camino(s) óptico(s) adicional(es) por O-1252871-1:1. "
        "Declarar la posición vigente en el Detalle de Servicio."
    )


def test_resumen_con_declaracion_y_adicional_invita_a_full():
    aviso = ts_mod.mensaje_resumen(
        _ok(
            2,
            adicionales=1,
            posiciones_adicionales="O-1239921-1:19,20",
            posicion_declarada="O-1252871-1:1,2",
            numero_servicio="93150",
        )
    )
    assert aviso == (
        "Posición vigente declarada: O-1252871-1:1,2. Hay 1 camino(s) óptico(s) adicional(es) "
        "por O-1239921-1:19,20. No se suben: pedí `track 93150 full` para incluirlos."
    )


def test_resumen_con_declaracion_en_full_no_invita_a_full():
    aviso = ts_mod.mensaje_resumen(
        _ok(
            3,
            adicionales=1,
            posiciones_adicionales="O-1239921-1:19,20",
            posicion_declarada="O-1252871-1:1,2",
            numero_servicio="93150",
            full=True,
            tramos=2,
        )
    )
    assert aviso == (
        "Posición vigente declarada: O-1252871-1:1,2. Hay 1 camino(s) óptico(s) adicional(es) "
        "por O-1239921-1:19,20."
    )


def test_resumen_retiro_va_primero_con_warning():
    aviso = ts_mod.mensaje_resumen(
        _ok(
            2,
            avisos_posicion=["Se retiró la posición vigente O-1252871-1:1: x.", TEXTO_CALCULO_AUTOMATICO],
            adicionales=2,
            posiciones_adicionales="O-1252871-1:1,2",
            etiquetas_adicionales="44649",
            esperados_declarados=3,
            caminos_resueltos=4,
        )
    )
    lineas = aviso.split("\n")
    assert lineas[0] == ":warning: Se retiró la posición vigente O-1252871-1:1: x."
    assert lineas[1] == f":warning: {TEXTO_CALCULO_AUTOMATICO}"
    assert lineas[2] == "Se esperaban 3 trackings y Cromo documenta 4 camino(s) óptico(s)."
    assert lineas[3] == _LINEA_ADICIONALES_SIN_DECLARAR


def test_esperados_contra_caminos_resueltos_no_contra_archivos():
    """En modo normal se suben 2 archivos pero Cromo documenta 4 caminos: lo que se compara contra
    lo declarado es lo segundo (decisión 6 del plan)."""
    assert ts_mod.mensaje_resumen(_ok(2, esperados_declarados=4, caminos_resueltos=4)) is None
    aviso = ts_mod.mensaje_resumen(_ok(4, esperados_declarados=2, caminos_resueltos=4, full=True))
    assert aviso == "Se esperaban 2 trackings y Cromo documenta 4 camino(s) óptico(s)."


def test_full_segmentacion_cuenta_tramos_no_archivos():
    aviso = ts_mod.mensaje_resumen(_ok(8, segmentos=3, tramos=6, full=True))
    assert aviso == "Servicio segmentado en 3 tramos (6 trackings)."


def test_los_residuales_no_se_mencionan_con_adicionales():
    aviso = ts_mod.mensaje_resumen(
        _ok(2, adicionales=2, posiciones_adicionales="O-1252871-1:1,2", etiquetas_adicionales="44649")
    )
    assert "residual" not in aviso.lower()


def _tracking(pelo: int, nombre: str) -> TrackingGenerado:
    return TrackingGenerado(
        pelo_n_id=pelo,
        nombre_archivo=nombre,
        contenido=f"contenido {pelo}",
        desde_cache=True,
        generado_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
        duracion_ms=1,
    )


def _del_servicio_93150(**kw) -> TrackingsDelServicio:
    """Forma del 93150 sin declaración: 2 tramos nuevos y 2 adicionales por la posición vieja."""
    tramos = [_tracking(6799280, "93150 CROMO T1 pelo 6799280.txt"), _tracking(6799281, "93150 CROMO T2 pelo 6799281.txt")]
    adicionales = [_tracking(7028862, "93150 CROMO A1 pelo 7028862.txt"), _tracking(7028863, "93150 CROMO A2 pelo 7028863.txt")]
    base = dict(
        tramos=tramos,
        residuales=[_tracking(7469850, "residual.txt")],
        errores=[],
        completo=True,
        segmentos=1,
        adicionales=adicionales,
        info_adicionales=[
            InfoAdicional(7028862, "POSICION", (("O-1252871-1", "1"),), ("44649",)),
            InfoAdicional(7028863, "POSICION", (("O-1252871-1", "2"),), ("44649",)),
        ],
        caminos_resueltos=[*tramos, *adicionales],
    )
    base.update(kw)
    return TrackingsDelServicio(**base)


def test_resultado_normal_sube_solo_tramos_y_menciona_adicionales():
    resultado = ts_mod.resultado_de_trackings(_del_servicio_93150(), full=False, numero_servicio="93150")
    assert [a.nombre for a in resultado.archivos] == [
        "93150 CROMO T1 pelo 6799280.txt",
        "93150 CROMO T2 pelo 6799281.txt",
    ]
    assert resultado.tramos == 2
    assert resultado.caminos_resueltos == 4
    assert resultado.adicionales == 2
    assert resultado.posiciones_adicionales == "O-1252871-1:1,2"
    assert resultado.etiquetas_adicionales == "44649"
    assert resultado.posicion_declarada == ""
    assert ts_mod.mensaje_resumen(resultado) == _LINEA_ADICIONALES_SIN_DECLARAR


def test_resultado_full_sube_tramos_y_adicionales_nunca_residuales():
    resultado = ts_mod.resultado_de_trackings(_del_servicio_93150(), full=True, numero_servicio="93150")
    nombres = [a.nombre for a in resultado.archivos]
    assert nombres == [
        "93150 CROMO T1 pelo 6799280.txt",
        "93150 CROMO T2 pelo 6799281.txt",
        "93150 CROMO A1 pelo 7028862.txt",
        "93150 CROMO A2 pelo 7028863.txt",
    ]
    assert "residual.txt" not in nombres
    assert resultado.full is True
    assert resultado.tramos == 2


def test_resultado_con_declaracion_aplicada_lleva_la_etiqueta_y_los_avisos():
    aviso = AvisoPosicion(
        conector_n_id=8604882,
        posicion="O-1252871-1:1",
        codigo=MOTIVO_PELO_CAMBIO,
        retirada=True,
        declaracion_id=1,
        pelo_declarado=1,
        detalle={"declarado": 1, "actual": 7028862},
    )
    del_servicio = _del_servicio_93150(
        posicion=EstadoPosicion(aplicada=True, etiqueta="O-1252871-1:1,2", avisos=[aviso]),
    )
    resultado = ts_mod.resultado_de_trackings(del_servicio, full=False, numero_servicio="93150")
    assert resultado.posicion_declarada == "O-1252871-1:1,2"
    assert resultado.avisos_posicion[0].startswith("Se retiró la posición vigente O-1252871-1:1")
    assert resultado.avisos_posicion[-1] == TEXTO_CALCULO_AUTOMATICO


def test_resultado_sin_declaracion_aplicada_no_muestra_la_etiqueta():
    """Con la declaración caída al cálculo automático, el resumen no la da por vigente."""
    del_servicio = _del_servicio_93150(posicion=EstadoPosicion(aplicada=False, etiqueta="O-1252871-1:1,2"))
    resultado = ts_mod.resultado_de_trackings(del_servicio, full=False, numero_servicio="93150")
    assert resultado.posicion_declarada == ""


def test_resultado_sin_archivos_es_error_y_conserva_los_avisos():
    aviso = AvisoPosicion(
        conector_n_id=8604882, posicion="O-1252871-1:1", codigo="SIN_PELO", retirada=True
    )
    del_servicio = _del_servicio_93150(
        tramos=[], adicionales=[], info_adicionales=[], caminos_resueltos=[],
        errores=["Pelo 42: sin camino"],
        posicion=EstadoPosicion(avisos=[aviso]),
    )
    resultado = ts_mod.resultado_de_trackings(del_servicio, full=True, numero_servicio="93150")
    assert resultado.estado == ts_mod.ESTADO_ERROR
    assert resultado.errores == ["Pelo 42: sin camino"]
    assert "Se retiró la posición vigente O-1252871-1:1" in resultado.mensaje


# ── `track N full` (Task 8) ──────────────────────────────────────────────────

from modules.slack_baneo_notifier.tracking_servicio import extraer_comando_track_full  # noqa: E402


@pytest.mark.parametrize(
    "texto",
    ["track 93150 full", "Track *93150* FULL", "tracking 93150 full", "  track  93150   full "],
)
def test_extrae_el_comando_full(texto):
    assert extraer_comando_track_full(texto) == "93150"
    assert extraer_comando_track(texto) is None


@pytest.mark.parametrize(
    "texto",
    ["track 93150 fulll", "track 93150 full ya", "track full 93150", "track 93150", "track odf O-1:1"],
)
def test_ignora_lo_que_no_es_track_full(texto):
    assert extraer_comando_track_full(texto) is None


def test_track_sin_full_sigue_igual():
    assert extraer_comando_track("track 93150") == "93150"


def test_mencion_track_full_despacha_con_full_true():
    listener = _listener()
    with patch.object(listener, "_handle_track") as handler:
        listener._handle_app_mention(_mencion("track 93150 full"), MagicMock())
    handler.assert_called_once()
    assert handler.call_args[0][0] == "93150"
    assert handler.call_args[1]["full"] is True


def test_mencion_track_normal_despacha_con_full_false():
    listener = _listener()
    with patch.object(listener, "_handle_track") as handler:
        listener._handle_app_mention(_mencion("track 93150"), MagicMock())
    assert handler.call_args[0][0] == "93150"
    assert handler.call_args[1].get("full", False) is False


def test_full_sube_los_caminos_resueltos_y_avisa_que_es_full():
    listener = _listener()
    client = MagicMock()
    servicio = SimpleNamespace(id=4, servicio_id="93150", nombre_cliente="BANCO PROVINCIA")
    with patch.object(ts_mod, "resolver_servicio", return_value=servicio), patch.object(
        ts_mod, "generar_trackings", return_value=_ok(4, full=True, tramos=2)
    ) as generar:
        listener._handle_track("93150", client, "C123", "1.1", full=True)

    generar.assert_called_once_with(4, full=True)
    assert client.files_upload_v2.call_count == 4
    espera = client.chat_postMessage.call_args_list[0][1]["text"]
    assert espera == (
        ":satellite: Generando el tracking completo (`full`) de `93150` — BANCO PROVINCIA. "
        "Si no está en caché puede tardar un rato."
    )


def test_track_normal_genera_sin_full():
    listener = _listener()
    client = MagicMock()
    servicio = SimpleNamespace(id=4, servicio_id="93150", nombre_cliente="X")
    with patch.object(ts_mod, "resolver_servicio", return_value=servicio), patch.object(
        ts_mod, "generar_trackings", return_value=_ok(2)
    ) as generar:
        listener._handle_track("93150", client, "C123", "1.1")
    generar.assert_called_once_with(4, full=False)
    assert "completo" not in client.chat_postMessage.call_args_list[0][1]["text"]


# ── `_generar_async`: salida temprana y modo full, con fakes ────────────────

import asyncio  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

import core.services.cromo.camino_optico_service as camino_mod  # noqa: E402
import core.services.cromo.client as client_mod  # noqa: E402
import core.services.cromo.servicio_posicion_vigente as posicion_mod  # noqa: E402
import core.services.cromo.tracking_service as tracking_mod  # noqa: E402


class _ClienteFake:
    def __init__(self, *a, **kw) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def generar_con_fakes(monkeypatch):
    """`_generar_async` sin DB ni Cromo: devuelve el registro de lo que se llamó."""
    llamadas: dict = {"trackings": []}
    estado = {"total_pelos": 0, "tiene_posiciones": False}

    @asynccontextmanager
    async def _sesion():
        yield object()

    async def _contar(_sesion, _pk):
        return estado["total_pelos"], 0

    async def _tiene(_sesion, _pk):
        llamadas["tiene_posiciones"] = True
        return estado["tiene_posiciones"]

    async def _trackings(_cliente, _sesion, pk, **kw):
        llamadas["trackings"].append((pk, kw))
        return _del_servicio_93150()

    async def _numero(_sesion, _pk):
        return "93150"

    monkeypatch.setattr(ts_mod, "_sesion_async", _sesion)
    monkeypatch.setattr(camino_mod, "contar_semillas", _contar)
    monkeypatch.setattr(posicion_mod, "tiene_posiciones", _tiene)
    monkeypatch.setattr(tracking_mod, "trackings_del_servicio", _trackings)
    monkeypatch.setattr(tracking_mod, "numero_del_servicio", _numero)
    monkeypatch.setattr(client_mod, "CromoClient", _ClienteFake)
    monkeypatch.setattr("core.services.cromo.config.get_cromo_config", lambda: None)
    return llamadas, estado


def test_sin_pelos_ni_posiciones_sale_temprano(generar_con_fakes):
    llamadas, _ = generar_con_fakes
    resultado = asyncio.run(ts_mod._generar_async(4))
    assert resultado.estado == "SIN_SEMILLA"
    assert llamadas["tiene_posiciones"] is True
    assert llamadas["trackings"] == []


def test_sin_pelos_etiquetados_pero_con_posiciones_genera(generar_con_fakes):
    """9 servicios sólo tienen semillas de posiciones: no deben responder "sin semilla"."""
    llamadas, estado = generar_con_fakes
    estado["tiene_posiciones"] = True
    resultado = asyncio.run(ts_mod._generar_async(4, full=True))
    assert resultado.estado == ts_mod.ESTADO_OK
    assert len(resultado.archivos) == 4
    assert llamadas["trackings"][0][0] == 4
    assert llamadas["trackings"][0][1]["fuente_evidencia"] == "SLACK"


def test_generar_normal_sube_dos_e_invita_a_declarar(generar_con_fakes):
    _, estado = generar_con_fakes
    estado["total_pelos"] = 40
    resultado = asyncio.run(ts_mod._generar_async(4))
    assert [a.nombre for a in resultado.archivos] == [
        "93150 CROMO T1 pelo 6799280.txt",
        "93150 CROMO T2 pelo 6799281.txt",
    ]
    assert resultado.numero_servicio == "93150"
    assert ts_mod.mensaje_resumen(resultado) == _LINEA_ADICIONALES_SIN_DECLARAR


# ── `track odf <patchera>:<conectores>` (Task 9) ─────────────────────────────

from core.services.cromo.odf_conectores import BandejaCandidata, ConectorDePatchera  # noqa: E402
from modules.slack_baneo_notifier.tracking_servicio import (  # noqa: E402
    MAX_CONECTORES_TRACK_ODF,
    ComandoTrackOdf,
    extraer_comando_track_odf,
)


@pytest.mark.parametrize(
    "texto, patchera, conectores",
    [
        ("track odf O-1252871-1:1", "O-1252871-1", (1,)),
        ("track odf O-1252871-1:1,2", "O-1252871-1", (1, 2)),
        ("track odf O-1252871-1:1-2", "O-1252871-1", (1, 2)),
        ("track odf O-1252871-1:1,3-4", "O-1252871-1", (1, 3, 4)),
        ("Tracking ODF O-1252871-1 : 2, 1, 2", "O-1252871-1", (2, 1)),
        # El nombre crudo se conserva: la variante 0-/O- se resuelve al buscar.
        ("track odf 0-1252871-1:1", "0-1252871-1", (1,)),
        ("track odf ODF VINCULACIÓN 2:3", "ODF VINCULACIÓN 2", (3,)),
        # Corta en el ÚLTIMO ":" (nombre real con ":" adentro).
        (
            "track odf ODF : ODF-CALLE 14 LIMA(PRACTICA) - LIMA CALLE 14:1",
            "ODF : ODF-CALLE 14 LIMA(PRACTICA) - LIMA CALLE 14",
            (1,),
        ),
        # La coma del nombre real no se confunde con la lista.
        ("track odf ODF Ruta 6 km 3,5 - 1000:2", "ODF Ruta 6 km 3,5 - 1000", (2,)),
        ("track odf `O-1252871-1:1`", "O-1252871-1", (1,)),
        ("track odf *O-1252871-1*:1", "O-1252871-1", (1,)),
        # El `_` es parte de nombres reales (13 patcheras): no se borra como formato de Slack.
        ("track odf O_X_1:1", "O_X_1", (1,)),
    ],
)
def test_extrae_el_comando_track_odf(texto, patchera, conectores):
    comando = extraer_comando_track_odf(texto)
    assert comando == ComandoTrackOdf(patchera=patchera, conectores=conectores)


@pytest.mark.parametrize(
    "texto",
    [
        "track odf",
        "track odf O-1252871-1",
        "track odf O-1252871-1:",
        "track odf :1",
        "track odf O-1:a",
        "track odfx O-1:1",
        "track 93150",
        "track 93150 full",
        "info cable F-VFL-IND",
    ],
)
def test_ignora_lo_que_no_es_track_odf(texto):
    assert extraer_comando_track_odf(texto) is None


@pytest.mark.parametrize(
    "texto, fragmento",
    [
        ("track odf O-1252871-1:2-1", "`2-1`"),
        ("track odf O-1252871-1:0", "`0`"),
        ("track odf O-1252871-1:1,,2", "lista"),
        ("track odf O-1252871-1:1-30", f"máximo es {MAX_CONECTORES_TRACK_ODF}"),
        ("track odf O-1252871-1:1-999999999", f"máximo es {MAX_CONECTORES_TRACK_ODF}"),
        ("track odf O-1252871-1:1-4,5-9", f"máximo es {MAX_CONECTORES_TRACK_ODF}"),
    ],
)
def test_track_odf_lista_invalida_devuelve_error(texto, fragmento):
    comando = extraer_comando_track_odf(texto)
    assert comando is not None and comando.conectores == ()
    assert fragmento in comando.error


def test_track_odf_tope_exacto_se_acepta():
    comando = extraer_comando_track_odf(f"track odf O-1252871-1:1-{MAX_CONECTORES_TRACK_ODF}")
    assert comando.error is None
    assert comando.conectores == tuple(range(1, MAX_CONECTORES_TRACK_ODF + 1))


def test_ningun_otro_parser_de_track_toma_track_odf():
    assert extraer_comando_track("track odf O-1252871-1:1") is None
    assert extraer_comando_track_full("track odf O-1252871-1:1") is None


# Datos reales de dev (2026-10-21): ODF San Martin 137 P5 D, patchera O-1252871-1 (bandeja 8604881).
_BANDEJA = BandejaCandidata(8604881, "O-1252871-1", 6644560, "ODF San Martin 137 P5 D")


def _conector(numero: str, **kw) -> ConectorDePatchera:
    base = dict(
        n_id=8604881 + int(numero),
        numero_conector=numero,
        pelo_n_id=None,
        patch_conector_n_id=None,
        patch_pelo_n_id=None,
        numero_pelo=None,
        cable_nombre=None,
        servicio_resuelto=None,
        servicio_pk=None,
        servicio_numero=None,
        nombre_cliente=None,
        cliente=None,
        estado_servicio=None,
        historico_numero=None,
        historico_estado=None,
        etiqueta_pelo=None,
        etiqueta_numero=None,
        etiqueta_estado=None,
    )
    base.update(kw)
    return ConectorDePatchera(**base)


def _conector_93150(numero: str, pelo: int) -> ConectorDePatchera:
    return _conector(
        numero,
        pelo_n_id=pelo,
        numero_pelo=numero,
        cable_nombre="F-PC-CC",
        servicio_resuelto="93150",
        servicio_pk=4,
        servicio_numero="93150",
        nombre_cliente="BANCO DE LA PROVINCIA DE BUENOS AIRES",
        estado_servicio="Activo",
        historico_numero="44649",
        historico_estado="Baja",
        etiqueta_pelo="44649",
        etiqueta_numero="44649",
        etiqueta_estado="Baja",
    )


def test_descripcion_de_la_posicion_del_93150():
    assert ts_mod.descripcion_posicion(_BANDEJA, _conector_93150("1", 7028862)) == (
        "`O-1252871-1:1` · ODF San Martin 137 P5 D · pelo 7028862 (F-PC-CC #1) · "
        "conector: 93150 BANCO DE LA PROVINCIA DE BUENOS AIRES (Activo) · "
        "etiqueta del pelo: 44649 (Baja)"
    )


def test_descripcion_muestra_el_historico_si_no_coincide_con_nada():
    c = replace_conector(_conector_93150("1", 7028862), historico_numero="11111", historico_estado=None)
    assert " · histórico: 11111 · etiqueta del pelo: 44649 (Baja)" in ts_mod.descripcion_posicion(_BANDEJA, c)


def test_descripcion_sin_servicio_y_por_patch():
    c = _conector("9", patch_conector_n_id=8628742, patch_pelo_n_id=10197026, cable_nombre="F-X", numero_pelo="3")
    texto = ts_mod.descripcion_posicion(_BANDEJA, c)
    assert texto == (
        "`O-1252871-1:9` · ODF San Martin 137 P5 D · pelo 10197026 (F-X #3, por patch al conector "
        "8628742) · conector: sin servicio en Cromo"
    )


def test_descripcion_etiqueta_igual_al_servicio_no_se_repite():
    c = replace_conector(
        _conector_93150("1", 7028862),
        etiqueta_pelo="93150", etiqueta_numero="93150", etiqueta_estado="Activo", historico_numero=None,
    )
    assert ts_mod.descripcion_posicion(_BANDEJA, c).endswith("(Activo)")


def replace_conector(c: ConectorDePatchera, **kw) -> ConectorDePatchera:
    from dataclasses import replace

    return replace(c, **kw)


def test_texto_candidatas_lista_hasta_diez():
    candidatas = [BandejaCandidata(i, "ODF 1", 1000 + i, f"ODF Calle {i}") for i in range(12)]
    texto = ts_mod.texto_candidatas("ODF 1", candidatas)
    lineas = texto.split("\n")
    assert lineas[0] == ":warning: La patchera `ODF 1` está en 12 bandejas distintas; no elijo una:"
    assert lineas[1] == "• ODF Calle 0 (ODF 1000) · patchera ODF 1 (bandeja 0)"
    assert len([linea for linea in lineas if linea.startswith("•")]) == 10
    assert lineas[-1] == "… y 2 más."


# Generador con fakes: `resolver_posiciones` recibe la sesión y una fábrica de cliente.


@pytest.fixture
def posiciones_con_fakes(monkeypatch):
    import core.services.cromo.odf_conectores as odf_mod

    estado: dict = {
        "bandejas": [_BANDEJA],
        "conectores": [_conector_93150("1", 7028862), _conector_93150("2", 7028863), _conector("5")],
        "fallan": {},
        "tracking_llamadas": [],
        "clientes_abiertos": 0,
        "conectores_pedidos": None,
    }

    async def _bandejas(_sesion, nombre):
        estado["nombre_buscado"] = nombre
        return estado["bandejas"]

    async def _conectores(_sesion, bandeja_n_id, numeros, *, odf_n_id=None):
        estado["conectores_pedidos"] = (bandeja_n_id, list(numeros), odf_n_id)
        return [c for c in estado["conectores"] if c.numero_conector in numeros]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        estado["tracking_llamadas"].append((servicio_id, pelo_n_id))
        if pelo_n_id in estado["fallan"]:
            raise estado["fallan"][pelo_n_id]
        return _tracking(pelo_n_id, f"cualquiera_{pelo_n_id}.txt")

    @asynccontextmanager
    async def _abrir():
        estado["clientes_abiertos"] += 1
        yield object()

    monkeypatch.setattr(odf_mod, "bandejas_por_nombre", _bandejas)
    monkeypatch.setattr(odf_mod, "conectores_de_bandeja", _conectores)
    monkeypatch.setattr(tracking_mod, "obtener_tracking", _obtener)
    estado["abrir"] = _abrir
    return estado


def _resolver(estado, patchera, conectores):
    return asyncio.run(ts_mod.resolver_posiciones(object(), estado["abrir"], patchera, conectores))


def test_resolver_posiciones_ok_sin_pelo_e_inexistente(posiciones_con_fakes):
    estado = posiciones_con_fakes
    resultado = _resolver(estado, "0-1252871-1", (1, 5, 30))

    assert resultado.estado == ts_mod.ESTADO_OK
    assert estado["nombre_buscado"] == "0-1252871-1"
    assert estado["conectores_pedidos"] == (8604881, ["1", "5", "30"], 6644560)
    assert [(p.conector, p.estado) for p in resultado.posiciones] == [
        (1, ts_mod.POSICION_OK),
        (5, ts_mod.POSICION_SIN_PELO),
        (30, ts_mod.POSICION_INEXISTENTE),
    ]
    ok = resultado.posiciones[0]
    # Nunca el at.62 del pelo (4649): el nombre sale del servicio del conector.
    assert ok.archivo.nombre == "93150 CROMO O-1252871-1_1 pelo 7028862.txt"
    assert ok.descripcion.startswith("`O-1252871-1:1` · ODF San Martin 137 P5 D · pelo 7028862")
    # Servicio Activo: la caché se atribuye al Servicio.
    assert estado["tracking_llamadas"] == [(4, 7028862)]
    assert estado["clientes_abiertos"] == 1


def test_resolver_posiciones_servicio_no_activo_cachea_sin_servicio(posiciones_con_fakes):
    estado = posiciones_con_fakes
    estado["conectores"] = [replace_conector(_conector_93150("1", 7028862), estado_servicio="Baja")]
    _resolver(estado, "O-1252871-1", (1,))
    assert estado["tracking_llamadas"] == [(None, 7028862)]


def test_resolver_posiciones_sigue_un_salto_de_patch(posiciones_con_fakes):
    estado = posiciones_con_fakes
    estado["conectores"] = [_conector("9", patch_conector_n_id=8628742, patch_pelo_n_id=10197026)]
    resultado = _resolver(estado, "O-1252871-1", (9,))
    (posicion,) = resultado.posiciones
    assert posicion.estado == ts_mod.POSICION_OK
    assert estado["tracking_llamadas"] == [(None, 10197026)]
    assert posicion.archivo.nombre == "sin_servicio CROMO O-1252871-1_9 pelo 10197026.txt"


def test_resolver_posiciones_sin_camino_no_corta_las_demas(posiciones_con_fakes):
    estado = posiciones_con_fakes
    estado["fallan"] = {7028862: tracking_mod.TrackingNoDisponible("Cromo no devolvió camino", "ERROR")}
    resultado = _resolver(estado, "O-1252871-1", (1, 2))
    assert [(p.conector, p.estado) for p in resultado.posiciones] == [
        (1, ts_mod.POSICION_SIN_CAMINO),
        (2, ts_mod.POSICION_OK),
    ]
    assert resultado.posiciones[0].motivo == "Cromo no devolvió camino"
    assert resultado.posiciones[0].pelo_n_id == 7028862


def test_resolver_posiciones_cromo_caido_es_error_y_conserva_lo_hecho(posiciones_con_fakes):
    estado = posiciones_con_fakes
    estado["fallan"] = {7028863: client_mod.CromoClientError("timeout")}
    resultado = _resolver(estado, "O-1252871-1", (1, 2))
    assert resultado.estado == ts_mod.ESTADO_ERROR
    assert resultado.mensaje == "Cromo no respondió: timeout"
    assert [p.conector for p in resultado.posiciones] == [1]


def test_resolver_posiciones_sin_pelos_no_abre_cromo(posiciones_con_fakes):
    estado = posiciones_con_fakes
    resultado = _resolver(estado, "O-1252871-1", (5,))
    assert resultado.posiciones[0].estado == ts_mod.POSICION_SIN_PELO
    assert estado["clientes_abiertos"] == 0


def test_resolver_posiciones_no_encontrada_y_ambigua(posiciones_con_fakes):
    estado = posiciones_con_fakes
    estado["bandejas"] = []
    assert _resolver(estado, "O-9", (1,)).estado == ts_mod.ESTADO_PATCHERA_NO_ENCONTRADA
    estado["bandejas"] = [
        BandejaCandidata(8592672, "O-1249273-1", 6644107, "ODF Montesquieu 1499 CF"),
        BandejaCandidata(9193166, "O-1249273-1", 9193140, "ODF Rio Negro 8100 PABLO PODESTA"),
    ]
    resultado = _resolver(estado, "O-1249273-1", (1,))
    assert resultado.estado == ts_mod.ESTADO_PATCHERA_AMBIGUA
    assert len(resultado.candidatas) == 2
    assert estado["conectores_pedidos"] is None
    assert estado["clientes_abiertos"] == 0


def test_resolver_posiciones_no_audita_ni_registra_evidencia():
    import inspect

    fuente = inspect.getsource(ts_mod.resolver_posiciones)
    assert "auditar" not in fuente and "registrar_y_encolar" not in fuente


# Handler del listener.


def _resultado_odf(**kw):
    base = dict(estado=ts_mod.ESTADO_OK, patchera="O-1252871-1", bandeja=_BANDEJA)
    base.update(kw)
    return ts_mod.ResultadoTrackOdf(**base)


def test_mencion_track_odf_despacha_al_handler_de_odf():
    listener = _listener()
    with patch.object(listener, "_handle_track_odf") as handler, patch.object(
        listener, "_handle_track"
    ) as track:
        listener._handle_app_mention(_mencion("track odf O-1252871-1:1,2"), MagicMock())
    track.assert_not_called()
    handler.assert_called_once()
    assert handler.call_args[0][0] == ComandoTrackOdf("O-1252871-1", (1, 2))


def test_track_odf_con_error_de_lista_avisa_el_uso_y_no_genera():
    listener = _listener()
    client = MagicMock()
    with patch.object(ts_mod, "generar_tracking_posiciones") as generar:
        listener._handle_track_odf(extraer_comando_track_odf("track odf O-1252871-1:1-30"), client, "C123", "1.1")
    generar.assert_not_called()
    texto = client.chat_postMessage.call_args[1]["text"]
    assert texto.startswith(":warning: ")
    assert texto.endswith(
        f"Uso: `track odf O-1252871-1:1`, `:1,2` o `:1-2` (hasta {MAX_CONECTORES_TRACK_ODF} conectores)."
    )


def test_track_odf_ok_sube_con_initial_comment_y_avisa_sin_pelo():
    listener = _listener()
    client = MagicMock()
    archivo = ts_mod.TrackingArchivo("93150 CROMO O-1252871-1_1 pelo 7028862.txt", "txt", True, 1)
    resultado = _resultado_odf(
        posiciones=[
            ts_mod.PosicionTrack(1, ts_mod.POSICION_OK, descripcion="`O-1252871-1:1` · desc", archivo=archivo, pelo_n_id=7028862),
            ts_mod.PosicionTrack(5, ts_mod.POSICION_SIN_PELO),
            ts_mod.PosicionTrack(6, ts_mod.POSICION_SIN_PELO, patch_conector_n_id=8604999),
            ts_mod.PosicionTrack(30, ts_mod.POSICION_INEXISTENTE),
            ts_mod.PosicionTrack(2, ts_mod.POSICION_SIN_CAMINO, pelo_n_id=7028863, motivo="sin camino"),
        ]
    )
    comando = ComandoTrackOdf("0-1252871-1", (1, 5, 6, 30, 2))
    with patch.object(ts_mod, "generar_tracking_posiciones", return_value=resultado) as generar:
        listener._handle_track_odf(comando, client, "C123", "1.1")

    generar.assert_called_once_with("0-1252871-1", (1, 5, 6, 30, 2))
    textos = [c[1]["text"] for c in client.chat_postMessage.call_args_list]
    assert textos[0] == (
        ":satellite: Buscando `0-1252871-1:1,5,6,30,2` en Cromo. Si no está en caché puede tardar un rato."
    )
    client.files_upload_v2.assert_called_once_with(
        channel="C123",
        thread_ts="1.1",
        content="txt",
        filename="93150 CROMO O-1252871-1_1 pelo 7028862.txt",
        title="93150 CROMO O-1252871-1_1 pelo 7028862.txt",
        initial_comment="`O-1252871-1:1` · desc",
    )
    assert textos[1:] == [
        ":information_source: `O-1252871-1:5` no tiene pelo conectado en Cromo, así que no hay tracking.",
        ":information_source: `O-1252871-1:6` no tiene pelo conectado en Cromo, así que no hay tracking "
        "(tiene patch al conector 8604999).",
        ":mag: `O-1252871-1:30` no existe en esa patchera.",
        ":warning: `O-1252871-1:2` — Cromo no resolvió el camino del pelo 7028863: sin camino.",
    ]


def test_track_odf_patchera_no_encontrada():
    listener = _listener()
    client = MagicMock()
    resultado = _resultado_odf(estado=ts_mod.ESTADO_PATCHERA_NO_ENCONTRADA, bandeja=None)
    with patch.object(ts_mod, "generar_tracking_posiciones", return_value=resultado):
        listener._handle_track_odf(ComandoTrackOdf("O-1252871-1", (1,)), client, "C123", "1.1")
    client.files_upload_v2.assert_not_called()
    assert client.chat_postMessage.call_args[1]["text"] == (
        ":mag: No encontré la patchera `O-1252871-1` en las ODF ingeridas de Cromo."
    )


def test_track_odf_patchera_ambigua_lista_candidatas():
    listener = _listener()
    client = MagicMock()
    candidatas = [
        BandejaCandidata(8592672, "O-1249273-1", 6644107, "ODF Montesquieu 1499 CF"),
        BandejaCandidata(9193166, "O-1249273-1", 9193140, "ODF Rio Negro 8100 PABLO PODESTA"),
    ]
    resultado = _resultado_odf(estado=ts_mod.ESTADO_PATCHERA_AMBIGUA, bandeja=None, candidatas=candidatas)
    with patch.object(ts_mod, "generar_tracking_posiciones", return_value=resultado):
        listener._handle_track_odf(ComandoTrackOdf("O-1249273-1", (1,)), client, "C123", "1.1")
    client.files_upload_v2.assert_not_called()
    assert client.chat_postMessage.call_args[1]["text"] == (
        ":warning: La patchera `O-1249273-1` está en 2 bandejas distintas; no elijo una:\n"
        "• ODF Montesquieu 1499 CF (ODF 6644107) · patchera O-1249273-1 (bandeja 8592672)\n"
        "• ODF Rio Negro 8100 PABLO PODESTA (ODF 9193140) · patchera O-1249273-1 (bandeja 9193166)"
    )


def test_track_odf_cromo_caido_sube_lo_hecho_y_avisa():
    listener = _listener()
    client = MagicMock()
    archivo = ts_mod.TrackingArchivo("a.txt", "txt", True, 1)
    resultado = _resultado_odf(
        estado=ts_mod.ESTADO_ERROR,
        mensaje="Cromo no respondió: timeout",
        posiciones=[ts_mod.PosicionTrack(1, ts_mod.POSICION_OK, descripcion="d", archivo=archivo)],
    )
    with patch.object(ts_mod, "generar_tracking_posiciones", return_value=resultado):
        listener._handle_track_odf(ComandoTrackOdf("O-1252871-1", (1, 2)), client, "C123", "1.1")
    assert client.files_upload_v2.call_count == 1
    assert client.chat_postMessage.call_args[1]["text"] == ":warning: Cromo no respondió: timeout"


def test_track_odf_falla_inesperada_avisa():
    listener = _listener()
    client = MagicMock()
    with patch.object(ts_mod, "generar_tracking_posiciones", side_effect=RuntimeError("boom")):
        listener._handle_track_odf(ComandoTrackOdf("O-1252871-1", (1,)), client, "C123", "1.1")
    assert client.chat_postMessage.call_args[1]["text"] == (
        ":x: No se pudo generar el tracking de `O-1252871-1:1`."
    )


def test_track_odf_falla_al_subir_avisa_el_archivo():
    listener = _listener()
    client = MagicMock()
    client.files_upload_v2.side_effect = RuntimeError("slack")
    archivo = ts_mod.TrackingArchivo("a.txt", "txt", True, 1)
    resultado = _resultado_odf(
        posiciones=[ts_mod.PosicionTrack(1, ts_mod.POSICION_OK, descripcion="d", archivo=archivo)]
    )
    with patch.object(ts_mod, "generar_tracking_posiciones", return_value=resultado):
        listener._handle_track_odf(ComandoTrackOdf("O-1252871-1", (1,)), client, "C123", "1.1")
    assert client.chat_postMessage.call_args[1]["text"] == ":x: No pude subir `a.txt`."


@requiere_postgres_real
def test_resolver_posiciones_con_datos_reales_del_93150(monkeypatch):
    """Patchera y conectores reales de dev (sólo lectura); el tracking es falso para no escribir la
    caché. El comentario es el del paso 6 de la verificación del plan."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from db.session import async_engine

    llamadas: list = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        llamadas.append((servicio_id, pelo_n_id))
        return _tracking(pelo_n_id, "x.txt")

    @asynccontextmanager
    async def _abrir():
        yield object()

    monkeypatch.setattr(tracking_mod, "obtener_tracking", _obtener)

    async def _correr():
        engine = create_async_engine(
            async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
        )
        try:
            async with async_sessionmaker(engine)() as sesion:
                return await ts_mod.resolver_posiciones(sesion, _abrir, "0-1252871-1", (1, 2, 5))
        finally:
            await engine.dispose()

    resultado = asyncio.run(_correr())

    assert resultado.estado == ts_mod.ESTADO_OK
    assert resultado.bandeja.bandeja_n_id == 8604881
    assert [(p.conector, p.estado) for p in resultado.posiciones] == [
        (1, ts_mod.POSICION_OK),
        (2, ts_mod.POSICION_OK),
        (5, ts_mod.POSICION_SIN_PELO),
    ]
    assert llamadas == [(4, 7028862), (4, 7028863)]
    uno = resultado.posiciones[0]
    assert uno.archivo.nombre == "93150 CROMO O-1252871-1_1 pelo 7028862.txt"
    assert uno.descripcion == (
        "`O-1252871-1:1` · ODF San Martin 137 P5 D · pelo 7028862 (F-PC-CC #1) · "
        "conector: 93150 BANCO DE LA PROVINCIA DE BUENOS AIRES (Activo) · "
        "etiqueta del pelo: 44649 (Baja)"
    )
