# Nombre de archivo: test_servicios_fusion_prov.py
# Ubicación de archivo: tests/test_servicios_fusion_prov.py
# Descripción: Tests puros de core/services/servicios_fusion_prov.py (ID operativo, agrupación, sobreviviente, plan) y de la regla en la ingesta PROV

from __future__ import annotations

from core.services.prov.ingesta import parsear_contexto_prov
from core.services.servicios_fusion_prov import (
    Eslabon,
    FilaServicio,
    agrupar,
    elegir_sobreviviente,
    id_operativo,
    planificar,
)


def _e(numero: str, orden: int, estado: str, vigente: bool = False) -> Eslabon:
    return Eslabon(numero, orden, estado, vigente)


def test_id_operativo_es_el_instalado_mas_reciente_aunque_prov_marque_vigente_un_pendiente() -> None:
    cadena = [_e("123066", 0, "PENDIENTE CPS", True), _e("96800", 1, "INSTALADO"), _e("50000", 2, "DADO BAJA")]
    assert id_operativo(cadena) == "96800"


def test_id_operativo_ignora_anulado_y_sol_baja() -> None:
    assert id_operativo([_e("3", 0, "ANULADO", True), _e("2", 1, "SOL BAJA"), _e("1", 2, "INSTALADO")]) == "1"


def test_id_operativo_sin_instalado_cae_al_vigente_de_prov() -> None:
    assert id_operativo([_e("20", 0, "DADO BAJA", True), _e("10", 1, "DADO BAJA")]) == "20"


def test_id_operativo_sin_instalado_ni_vigente_es_none() -> None:
    assert id_operativo([_e("20", 0, "DADO BAJA"), _e("10", 1, "DADO BAJA")]) is None
    assert id_operativo([]) is None


def test_id_operativo_respeta_el_orden_no_la_posicion_en_la_lista() -> None:
    assert id_operativo([_e("viejo", 3, "INSTALADO"), _e("nuevo", 1, "INSTALADO")]) == "nuevo"


def test_agrupar_une_componentes_transitivos() -> None:
    assert agrupar([(5, 7), (7, 9), (1, 2), (9, 5)]) == [[1, 2], [5, 7, 9]]


def _fila(pk: int, sid: str, *, cliente: str | None = "CLIENTE", matches: int = 0, cadena=()) -> FilaServicio:
    return FilaServicio(pk, sid, sid, (), cliente, matches, tuple(cadena))


def test_sobreviviente_prefiere_con_cliente_luego_con_cadena_luego_mas_pelos() -> None:
    placeholder = _fila(1, "118169", cliente=None, matches=50, cadena=[_e("118169", 0, "INSTALADO")])
    real = _fila(2, "102514", matches=3, cadena=[_e("118169", 0, "INSTALADO")])
    assert elegir_sobreviviente([placeholder, real]).id == 2

    sin_cadena = _fila(3, "1", matches=99)
    con_cadena = _fila(4, "2", matches=1, cadena=[_e("2", 0, "INSTALADO")])
    assert elegir_sobreviviente([sin_cadena, con_cadena]).id == 4

    assert elegir_sobreviviente([_fila(9, "a", matches=1), _fila(8, "b", matches=5)]).id == 8
    assert elegir_sobreviviente([_fila(9, "a"), _fila(8, "b")]).id == 8


def test_plan_par_mutuo_real_del_backfill() -> None:
    """Caso real de prod (fila 19922): quedó con 102514 porque 118169 lo tenía otra fila."""

    cadena = [_e("118169", 0, "INSTALADO", True), _e("111818", 1, "DADO BAJA"), _e("102514", 3, "DADO BAJA")]
    vieja = FilaServicio(19922, "102514", "101260", ("118169", "111818"), "BANCO X", 12, tuple(cadena))
    nueva = FilaServicio(30001, "118169", "118169", ("102514",), None, 4, tuple(cadena))

    plan = planificar([vieja, nueva])

    assert plan.motivo_salteo is None
    assert plan.sobreviviente.id == 19922
    assert [p.id for p in plan.perdedores] == [30001]
    assert plan.id_final == "118169"
    assert "118169" not in plan.alias_final
    assert {"102514", "101260", "111818"} <= set(plan.alias_final)


def test_plan_saltea_cadenas_con_distinto_instalado() -> None:
    a = _fila(1, "39218", cadena=[_e("39218", 0, "INSTALADO")])
    b = _fila(2, "39217", cadena=[_e("39217", 0, "INSTALADO"), _e("39218", 1, "DADO BAJA")])
    assert planificar([a, b]).motivo_salteo == "cadenas_con_distinto_id_operativo"


def test_plan_saltea_clientes_distintos() -> None:
    cadena = [_e("5", 0, "INSTALADO")]
    plan = planificar([_fila(1, "5", cliente="A SA", cadena=cadena), _fila(2, "4", cliente="B SA", cadena=cadena)])
    assert plan.motivo_salteo == "clientes_distintos"


def test_plan_cliente_igual_con_distinto_formato_no_saltea() -> None:
    cadena = [_e("5", 0, "INSTALADO")]
    plan = planificar([_fila(1, "5", cliente="Banco X", cadena=cadena), _fila(2, "4", cliente=" BANCO X ", cadena=cadena)])
    assert plan.motivo_salteo is None


def test_plan_sin_id_operativo_conserva_el_id_del_sobreviviente() -> None:
    plan = planificar([_fila(1, "7", cadena=[_e("7", 0, "DADO BAJA")]), _fila(2, "6", cliente=None)])
    assert plan.id_final == "7"


def test_parseo_de_prov_conserva_estado_y_vigencia_de_cada_eslabon() -> None:
    """La regla del ID operativo depende de que el parser no pierda `estado_comercial` por eslabón."""

    parseado = parsear_contexto_prov(
        {
            "nro_servicio": "123066",
            "nro_servicio_original": "50000",
            "estado_comercial": "PENDIENTE CPS",
            "cadena_upgrade": [
                {"nro_servicio": "123066", "estado_comercial": "PENDIENTE CPS", "es_vigente": True},
                {"nro_servicio": "96800", "estado_comercial": "INSTALADO", "es_vigente": False},
            ],
        }
    )
    eslabones = [Eslabon(e.numero_id, e.orden, e.estado_comercial, e.es_vigente) for e in parseado.historial]
    assert id_operativo(eslabones) == "96800"
