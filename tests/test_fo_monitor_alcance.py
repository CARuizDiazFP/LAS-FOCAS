# Nombre de archivo: test_fo_monitor_alcance.py
# Ubicación de archivo: tests/test_fo_monitor_alcance.py
# Descripción: Tests del alcance de una intervención FO Monitor (selector de Botella 1 y deduplicado de servicios)

from core.services.cromo.verificador import ServicioUnico
from core.services.fo_monitor.alcance import AlcanceIntervencion, CableAlcance, elegir_botella_1


def _s(pk: int) -> ServicioUnico:
    return ServicioUnico(
        servicio_id=pk, servicio_id_externo=str(pk), numero_primer_servicio=None, nombre_cliente=None,
        cliente=None, estado_servicio="Activo", tipo_servicio="TLS", pelos_n_ids=[], cantidad_pelos=1,
        numeros_en_pelo=[], metodos=[], categoria=6, es_verificable=True,
    )


def test_botella_1_es_la_sin_sufijo_aunque_no_sea_la_primera():
    botellas = [(6632152, "Cra 25 de Mayo 399 Bot 2 CF"), (9932623, "Cra 25 de Mayo 399 Bot 3 CF"), (6632003, "Cra 25 de Mayo 399 CF")]
    assert elegir_botella_1(botellas) == (6632003, False)


def test_botella_1_literal_bot_1():
    botellas = [(6632782, "Cra L de la Torre 901 BERAZATEGUI Bot 2"), (6632084, "Cra L de la Torre 901 BERAZATEGUI Bot 1")]
    assert elegir_botella_1(botellas) == (6632084, False)


def test_botella_1_inferida_si_no_hay_ni_sufijo_ni_bot_1():
    botellas = [(3, "Cra X Bot 3"), (2, "Cra X Bot 2")]
    assert elegir_botella_1(botellas) == (2, True)


def test_bot_30_de_septiembre_no_es_sufijo():
    botellas = [(5, "Cra Bot 30 de Septiembre y Estrada"), (6, "Cra Bot 30 de Septiembre y Estrada Bot 2")]
    assert elegir_botella_1(botellas) == (5, False)


def test_sin_botellas():
    assert elegir_botella_1([]) == (None, False)


def test_servicios_unicos_deduplica_y_prioriza_objetivo():
    alcance = AlcanceIntervencion(
        camara_id=1, botella_objetivo_n_id=10, botella_1_inferida=False, botellas={10: "a", 20: "b"},
        cables=[
            CableAlcance(n_id=1, nombre="F-A", clase=51, botella_n_id=10, es_objetivo=True, servicios=[_s(30), _s(10)]),
            CableAlcance(n_id=2, nombre="F-B", clase=51, botella_n_id=20, es_objetivo=False, servicios=[_s(5), _s(10)]),
        ],
    )
    assert [s.servicio_id for s in alcance.servicios_unicos()] == [10, 30, 5]
