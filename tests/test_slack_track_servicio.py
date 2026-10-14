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
        esperados=2,
        completo=False,
    )
    with patch.object(ts_mod, "resolver_servicio", return_value=servicio), patch.object(
        ts_mod, "generar_trackings", return_value=resultado
    ):
        listener._handle_track("111", client, "C123", "1.1")

    assert client.files_upload_v2.call_count == 1
    assert "Pelo 42" in client.chat_postMessage.call_args_list[-1][1]["text"]


def test_huerfanos_se_listan_y_no_suben_un_txt_de_mas():
    """94673 con un pelo movido: 2 `.txt` (sus 2 hilos) y el huérfano sólo se avisa."""
    listener = _listener()
    client = MagicMock()
    servicio = SimpleNamespace(id=1066, servicio_id="94673", nombre_cliente="X")
    resultado = ts_mod.ResultadoTrack(
        estado=ts_mod.ESTADO_OK,
        archivos=[
            ts_mod.TrackingArchivo("94673 CROMO pelo 6799772.txt", "a", False, 1),
            ts_mod.TrackingArchivo("94673 CROMO pelo 6799773.txt", "b", False, 1),
        ],
        esperados=2,
        huerfanos=["pelo 9999999 · F-VIN-TEC · 23 BL"],
    )
    with patch.object(ts_mod, "resolver_servicio", return_value=servicio), patch.object(
        ts_mod, "generar_trackings", return_value=resultado
    ):
        listener._handle_track("94673", client, "C123", "1.1")

    assert client.files_upload_v2.call_count == 2
    aviso = client.chat_postMessage.call_args_list[-1][1]["text"]
    assert "pelo 9999999" in aviso and "huérfanos" in aviso and "portal" in aviso


def test_completo_y_sin_huerfanos_no_avisa_nada():
    resultado = ts_mod.ResultadoTrack(
        estado=ts_mod.ESTADO_OK,
        archivos=[ts_mod.TrackingArchivo("a.txt", "a", False, 1)],
        esperados=1,
    )
    assert ts_mod.mensaje_resumen(resultado) is None


def test_describir_pelo_arma_la_linea_para_ubicarlo_en_cromo():
    semilla = SimpleNamespace(
        pelo_n_id=6799772, cable_nombre="F-VIN-TEC", numero_pelo="21", color="AM"
    )
    assert ts_mod._describir_pelo(semilla) == "pelo 6799772 · F-VIN-TEC · 21 AM"


def test_muchos_huerfanos_se_acotan_en_el_hilo():
    resultado = ts_mod.ResultadoTrack(
        estado=ts_mod.ESTADO_OK,
        archivos=[ts_mod.TrackingArchivo("a.txt", "a", False, 1)],
        esperados=1,
        huerfanos=[f"pelo {i}" for i in range(40)],
    )
    aviso = ts_mod.mensaje_resumen(resultado)
    assert "pelo 14" in aviso and "pelo 15\n" not in aviso
    assert "… y 25 más." in aviso
