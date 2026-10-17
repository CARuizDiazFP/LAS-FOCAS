# Nombre de archivo: test_fo_monitor_semaforo.py
# Ubicación de archivo: tests/test_fo_monitor_semaforo.py
# Descripción: Tests del semáforo puro de FO Monitor (orden gris→rojo→amarillo→verde→naranja)

from core.services.fo_monitor.semaforo import (
    AMARILLO, ADMIN_DOWN, DESCONOCIDO, DOWN, GRIS, NARANJA, NO_SOPORTADO, ROJO, UP, VERDE, calcular_semaforo,
)


def _todos(estado, n):
    return {i: estado for i in range(n)}


def test_sin_servicios_es_gris():
    r = calcular_semaforo([], {})
    assert (r.color, r.motivo) == (GRIS, "sin_verificables")


def test_todos_no_soportados_o_admin_down_es_gris():
    r = calcular_semaforo([1, 2], {1: NO_SOPORTADO, 2: ADMIN_DOWN})
    assert (r.color, r.motivo) == (GRIS, "sin_verificables")


def test_cobertura_menor_50_es_gris_desconocido():
    pre = {0: UP, 1: DESCONOCIDO, 2: DESCONOCIDO}
    r = calcular_semaforo([0, 1, 2], pre)
    assert (r.color, r.motivo) == (GRIS, "desconocido")


def test_todo_conocido_down_es_rojo_aunque_haya_caidas_nuevas():
    r = calcular_semaforo([0, 1], _todos(UP, 2), _todos(DOWN, 2))
    assert r.color == ROJO
    assert r.caidas_nuevas == [0, 1]


def test_una_caida_nueva_con_95_por_ciento_up_es_amarillo():
    pre = _todos(UP, 20)
    post = dict(pre)
    post[7] = DOWN
    r = calcular_semaforo(list(range(20)), pre, post)
    assert r.color == AMARILLO
    assert r.caidas_nuevas == [7]


def test_caida_reconocida_como_ajena_no_es_amarilla():
    pre = _todos(UP, 20)
    post = dict(pre)
    post[7] = DOWN
    r = calcular_semaforo(list(range(20)), pre, post, reconocidos={7})
    assert r.color == VERDE


def test_sin_linea_base_no_puede_ser_amarillo():
    pre = {i: DESCONOCIDO for i in range(5)}
    post = {0: DOWN, 1: UP, 2: UP, 3: UP, 4: UP}
    r = calcular_semaforo(list(range(5)), pre, post, sin_linea_base=True)
    assert r.color == VERDE
    assert r.sin_linea_base


def test_umbral_80_verde_y_naranja():
    assert calcular_semaforo(list(range(5)), {0: DOWN, 1: UP, 2: UP, 3: UP, 4: UP}).color == VERDE
    assert calcular_semaforo(list(range(5)), {0: DOWN, 1: DOWN, 2: UP, 3: UP, 4: UP}).color == NARANJA
    assert calcular_semaforo(list(range(10)), {**_todos(DOWN, 9), 9: UP}).color == NARANJA


def test_recuperacion_se_informa_sin_cambiar_color():
    pre = {0: DOWN, 1: UP, 2: UP, 3: UP, 4: UP}
    post = _todos(UP, 5)
    r = calcular_semaforo(list(range(5)), pre, post)
    assert r.color == VERDE
    assert r.recuperaciones == [0]


def test_admin_down_no_cuenta_en_porcentaje():
    r = calcular_semaforo([0, 1, 2], {0: ADMIN_DOWN, 1: UP, 2: UP})
    assert (r.color, r.evaluables, r.cobertura) == (VERDE, 2, 1.0)


def test_en_curso_usa_pre_y_no_tiene_caidas():
    r = calcular_semaforo([0, 1], {0: UP, 1: DOWN})
    assert r.fase == "PRE"
    assert r.caidas_nuevas == []
    assert r.color == NARANJA
