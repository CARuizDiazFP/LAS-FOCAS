# Nombre de archivo: test_cromo_empalme_resolucion.py
# Ubicación de archivo: tests/test_cromo_empalme_resolucion.py
# Descripción: Pruebas de la resolución inversa "ID de empalme -> Botella dueña", sin DB real

from __future__ import annotations

from typing import Any, Optional

from core.services.cromo import empalme_resolucion


class _ResultadoFilas:
    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionSyncFake:
    """Reemplaza sólo `execute` (sync — `resolver_botella_por_fusion_sync` usa `Session`, no
    `AsyncSession`, mismo motivo que `servicios_por_tubo_sync`): matchea por substring de la
    consulta compilada, mismo patrón que `test_cromo_empalmes.py`/`test_cromo_verificador.py`.

    Cada test de este módulo hace a lo sumo UNA llamada relevante por clave de query (fusión,
    extremos por pelos, botellas por n_ids) — el matching por substring (sin inspeccionar params)
    alcanza porque `resolver_botella_por_fusion_sync` resuelve ambos pelos en una sola query
    batcheada (`_SQL_EXTREMOS_DE_PELOS`) y ambos candidatos en una sola query batcheada
    (`_SQL_BOTELLAS_POR_N_IDS`) — nunca hace dos llamadas a la misma query esperando respuestas
    distintas dentro del mismo test.
    """

    def __init__(self, respuestas: Optional[dict[str, list[tuple]]] = None) -> None:
        self._respuestas = respuestas or {}

    def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        texto = str(stmt)
        for clave, filas in self._respuestas.items():
            if clave in texto:
                return _ResultadoFilas(filas)
        return _ResultadoFilas([])


def test_fusion_inexistente_retorna_none():
    """Si no hay fila en cromo_fusiones para ese n_id, no hay nada que resolver."""
    sesion = _SesionSyncFake()
    resultado = empalme_resolucion.resolver_botella_por_fusion_sync(sesion, 999)
    assert resultado is None


def test_prioridad_1_botella_n_id_directo_poblado():
    """Cuando `CromoFusion.botella_n_id` está poblado y esa Botella existe, se usa directo —
    ni siquiera hace falta resolver los pelos."""
    sesion = _SesionSyncFake(
        respuestas={
            "FROM app.cromo_fusiones": [(555, None, None)],  # botella_n_id=555, pelos irrelevantes
            "FROM app.cromo_botellas": [(555, "Botella Directa", 42)],
        }
    )
    resultado = empalme_resolucion.resolver_botella_por_fusion_sync(sesion, 1)

    assert resultado is not None
    assert resultado.n_id == 555
    assert resultado.nombre == "Botella Directa"
    assert resultado.camara_id == 42


def test_botella_n_id_directo_puntero_obsoleto_cae_a_prioridad_2():
    """`botella_n_id` está poblado pero esa fila ya no existe en cromo_botellas (puntero obsoleto)
    — no se fabrica una BotellaDeFusion con datos inexistentes; cae a la resolución por extremo
    compartido (Prioridad 2), igual que si `botella_n_id` nunca hubiera estado poblado."""
    sesion = _SesionSyncFake(
        respuestas={
            # botella_n_id=999 (no existe), pelo_a=10, pelo_b=20
            "FROM app.cromo_fusiones": [(999, 10, 20)],
            "JOIN app.cromo_cables": [
                (10, 700, 701),  # pelo 10 -> cable con extremos 700/701
                (20, 701, 702),  # pelo 20 -> cable con extremos 701/702
            ],
            # 999 no aparece: puntero obsoleto. 701 (compartido) sí existe.
            "FROM app.cromo_botellas": [(701, "Botella Compartida", 7)],
        }
    )
    resultado = empalme_resolucion.resolver_botella_por_fusion_sync(sesion, 1)

    assert resultado is not None
    assert resultado.n_id == 701
    assert resultado.camara_id == 7


def test_extremo_compartido_entre_ambos_cables():
    """Caso normal: ambos pelos resuelven a un cable con fila propia, y el extremo 701 aparece en
    los dos — esa es la Botella donde ocurre la fusión."""
    sesion = _SesionSyncFake(
        respuestas={
            "FROM app.cromo_fusiones": [(None, 10, 20)],
            "JOIN app.cromo_cables": [
                (10, 700, 701),
                (20, 701, 702),
            ],
            "FROM app.cromo_botellas": [(701, "Botella Compartida", 7)],
        }
    )
    resultado = empalme_resolucion.resolver_botella_por_fusion_sync(sesion, 1)

    assert resultado is not None
    assert resultado.n_id == 701
    assert resultado.nombre == "Botella Compartida"
    assert resultado.camara_id == 7


def test_un_solo_pelo_resuelve_cable_referencia_colgada():
    """El otro pelo es una referencia colgada (sin fila propia en cromo_pelos, o cuyo cable no
    tiene fila propia en cromo_cables): sólo se resuelve un cable. De sus 2 extremos, sólo uno
    (800) existe como Botella real — se usa ese, sin ambigüedad."""
    sesion = _SesionSyncFake(
        respuestas={
            # pelo_b_n_id=99 no tiene fila propia en cromo_pelos -> el JOIN no la devuelve.
            "FROM app.cromo_fusiones": [(None, 10, 99)],
            "JOIN app.cromo_cables": [
                (10, 800, 801),
            ],
            # Sólo 800 existe como Botella; 801 no tiene fila propia.
            "FROM app.cromo_botellas": [(800, "Botella Única", 3)],
        }
    )
    resultado = empalme_resolucion.resolver_botella_por_fusion_sync(sesion, 1)

    assert resultado is not None
    assert resultado.n_id == 800
    assert resultado.camara_id == 3


def test_ningun_pelo_resuelve_cable_retorna_none():
    """Ambos pelos son referencia colgada — no hay de dónde partir."""
    sesion = _SesionSyncFake(
        respuestas={
            "FROM app.cromo_fusiones": [(None, 10, 20)],
            # JOIN cromo_pelos/cromo_cables no devuelve nada para ninguno de los dos.
        }
    )
    resultado = empalme_resolucion.resolver_botella_por_fusion_sync(sesion, 1)
    assert resultado is None


def test_empate_entre_dos_botellas_candidatas_retorna_none():
    """Si tras filtrar por existencia real quedan 2+ candidatas con igual peso, no se elige
    arbitrariamente — se devuelve `None`. Caso: ambos extremos del único cable resuelto existen
    como Botella (no hay forma de saber cuál es la relevante)."""
    sesion = _SesionSyncFake(
        respuestas={
            "FROM app.cromo_fusiones": [(None, 10, 99)],  # pelo 99 dangling
            "JOIN app.cromo_cables": [
                (10, 800, 801),
            ],
            # Ambos extremos existen como Botella real -> empate.
            "FROM app.cromo_botellas": [(800, "Botella A", 3), (801, "Botella B", 4)],
        }
    )
    resultado = empalme_resolucion.resolver_botella_por_fusion_sync(sesion, 1)
    assert resultado is None


def test_extremos_sin_ninguna_botella_existente_retorna_none():
    """Los candidatos se calculan (intersección o único cable) pero ninguno tiene fila propia en
    cromo_botellas -> no hay nada para devolver."""
    sesion = _SesionSyncFake(
        respuestas={
            "FROM app.cromo_fusiones": [(None, 10, 20)],
            "JOIN app.cromo_cables": [
                (10, 700, 701),
                (20, 701, 702),
            ],
            # "FROM app.cromo_botellas" no registrado -> _SesionSyncFake devuelve [] por default.
        }
    )
    resultado = empalme_resolucion.resolver_botella_por_fusion_sync(sesion, 1)
    assert resultado is None
