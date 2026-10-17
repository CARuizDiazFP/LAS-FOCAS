# Nombre de archivo: test_fo_monitor_parser.py
# Ubicación de archivo: tests/test_fo_monitor_parser.py
# Descripción: Tests del prompt y del parser de respuestas de burritoIA (bloque FOMON) de FO Monitor

import json
from pathlib import Path

import pytest

from core.services.fo_monitor.parser import parsear_respuesta
from core.services.fo_monitor.prompt import construir_prompt, token_consulta


def test_prompt_incluye_mencion_token_e_ids():
    texto = construir_prompt("U0A2HE3K950", 42, ["117995", "113705"])
    assert texto.startswith("<@U0A2HE3K950> verificar servicios 117995, 113705")
    assert token_consulta(42) in texto
    assert "117995, 113705" in texto
    assert "FOMON|<número de servicio>|<ESTADO>|<extremo>|<motivo>" in texto


def test_prompt_sin_ids_falla():
    with pytest.raises(ValueError):
        construir_prompt("U0A2HE3K950", 1, [])


def test_bloque_en_code_fence_partido_en_dos_mensajes():
    msg1 = "*Servicio 117995* — análisis...\n```\nFOMON|117995|UP|-|Acceso UP/UP\n"
    msg2 = "FOMON|113705|DOWN|2|ONT down dying gasp\n```\n_(ref: #ae2b)_"
    r = parsear_respuesta([msg1, msg2], ["117995", "113705"])
    assert r.completa
    assert r.ref == "ae2b"
    assert r.resultados["117995"].estado == "UP"
    assert r.resultados["117995"].extremo is None
    assert r.resultados["113705"].estado == "DOWN"
    assert r.resultados["113705"].extremo == "2"


def test_id_faltante_queda_desconocido_y_no_completa():
    r = parsear_respuesta(["FOMON|117995|UP|-|ok"], ["117995", "113705"])
    assert not r.completa
    assert r.resultados["113705"].estado == "DESCONOCIDO"
    assert r.resultados["113705"].motivo == "sin_linea"
    assert not r.resultados["113705"].parseado


def test_estado_invalido_e_id_no_pedido_van_a_invalidas():
    r = parsear_respuesta(["FOMON|117995|CAIDO|-|x\nFOMON|999|UP|-|x"], ["117995"])
    assert r.resultados["117995"].estado == "DESCONOCIDO"
    assert len(r.lineas_invalidas) == 2


def test_eco_de_plantilla_se_ignora_y_entidades_html_se_desescapan():
    texto = "FOMON|<id>|<ESTADO>|<extremo>|<motivo>\n`FOMON|117995|admin_down|1|apagado &amp; sin uso`"
    r = parsear_respuesta([texto], ["117995"])
    assert r.lineas_invalidas == []
    assert r.resultados["117995"].estado == "ADMIN_DOWN"
    assert r.resultados["117995"].motivo == "apagado & sin uso"


def test_ids_con_ceros_y_espacios_se_normalizan():
    r = parsear_respuesta(["  FOMON | 0117995 | up | - | ok  "], ["117995"])
    assert r.resultados["117995"].estado == "UP"


# --- Respuestas reales de burritoIA (PoC 2026-10-14, sólo bloque final + ref) ----------------------

_FIX = json.loads(
    (Path(__file__).parent / "fixtures" / "fo_monitor" / "respuestas_burrito_poc_2026-10-14.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("clave", ["S4_v3_3960", "S7_v3_4ca7", "S1_v3_eb2f"])
def test_respuestas_reales_v3_parsean_completas(clave):
    caso = _FIX[clave]
    r = parsear_respuesta(caso["textos"], caso["ids"])
    assert r.completa
    assert r.lineas_invalidas == []
    assert r.ref


def test_real_lote_mixto_reporta_no_soportado_por_linea():
    caso = _FIX["S7_v3_4ca7"]
    r = parsear_respuesta(caso["textos"], caso["ids"])
    assert r.resultados["112731"].estado == "NO_SOPORTADO"
    assert r.resultados["117995"].estado == "UP"


def test_real_respuesta_sin_bloque_deja_todo_desconocido_con_ref():
    caso = _FIX["S5_v3_18ee"]
    r = parsear_respuesta(caso["textos"], caso["ids"])
    assert not r.completa
    assert r.ref == "18ee"
    assert {v.estado for v in r.resultados.values()} == {"DESCONOCIDO"}


def test_real_v2_token_en_lugar_de_id_con_un_solo_servicio():
    caso = _FIX["S1_v2_ec8a"]
    r = parsear_respuesta(caso["textos"], caso["ids"])
    assert r.completa
    assert r.resultados["117995"].estado == "UP"


def test_linea_sin_campo_extremo_real_v4():
    linea = "```\nFOMON|121830|UP|inferido por troncal: TwentyFiveGigE1/0/43 up/up (SW_4_Chacabuco271_P1)\n```\n_(ref: #fe81)_"
    r = parsear_respuesta([linea], ["121830"])
    assert r.completa
    assert r.resultados["121830"].estado == "UP"
    assert r.resultados["121830"].extremo is None
    assert r.resultados["121830"].motivo.startswith("inferido por troncal")


def test_prompt_v4_pide_troncal_si_acceso_sin_gestion():
    texto = construir_prompt("U0A2HE3K950", 7, ["121830"], version="v4")
    assert texto.startswith("<@U0A2HE3K950> verificar servicio 121830")
    assert "troncal" in texto and "FOMON-Q7" in texto
