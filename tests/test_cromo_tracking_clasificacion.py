# Nombre de archivo: test_cromo_tracking_clasificacion.py
# Ubicación de archivo: tests/test_cromo_tracking_clasificacion.py
# Descripción: Pruebas de `clasificar_caminos` (TRAMO / RESIDUAL) con los caminos medidos contra Cromo
# real el 2026-10-16 sobre los Servicios 102452, 42351, 93154 y 94673

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.services.cromo.tracking_service import (
    ROL_RESIDUAL,
    ROL_TRAMO,
    ExtremoCamino,
    ResumenCamino,
    TrackingGenerado,
    clasificar_caminos,
)

AHORA = datetime(2026, 10, 16, tzinfo=timezone.utc)

# Medido real (read-only, dentro de lasfocasdev-cromo-worker): un `/path` por semilla no cubierta,
# sin corte en esperados. Por camino: (semilla, pelos, clase de la ODF del extremo inicial, ídem
# final, ODFs que toca, grupo de cables, cantidad de cables). Dos caminos del mismo grupo
# recorren exactamente los mismos cables; los grupos distintos se modelan disjuntos (el mayor
# Jaccard medido entre caminos que no son par fue 0,33). Excepción: los dos hilos de 42351
# (grupos 0 y 1) comparten 145 cables de 155/165 — Jaccard real 0,86.
MEDIDO = {
    "102452": [
        (6799794, 27, None, 86, (9585104,), 0, 27),
        (6799795, 27, None, 86, (9585104,), 0, 27),
        (7183576, 3, None, 86, (6646692,), 1, 3),
        (7183577, 3, 86, None, (6646692,), 1, 3),
        (7246874, 2, None, 86, (6646671, 9585104), 2, 2),
        (7246875, 2, None, 86, (6646671, 9585104), 2, 2),
        (7655082, 47, 86, 86, (6646686, 9585104), 3, 47),
        (7655083, 47, 86, 86, (6646686, 9585104), 3, 47),
        (7722344, 24, 86, 86, (6646686, 6646692), 4, 24),
        (7722345, 24, 86, 86, (6646686, 6646692), 4, 24),
        (7743423, 1, None, None, (), 5, 0),
        (7743424, 1, None, None, (), 5, 0),
        (7832494, 1, None, None, (), 6, 1),
        (9358135, 2, None, None, (), 7, 2),
        (9358254, 2, None, None, (), 7, 2),
        (9358533, 7, None, None, (), 8, 7),
        (9996750, 1, None, None, (), 9, 1),
        (9996751, 1, None, None, (), 9, 1),
        (10189973, 1, None, None, (), 10, 1),
        (10189982, 1, None, None, (), 10, 1),
        (10196042, 8, None, None, (), 11, 8),
        (10236889, 1, None, None, (), 12, 1),
        (10236897, 1, None, None, (), 12, 1),
        (10237047, 2, None, None, (), 13, 2),
        (10237055, 2, None, None, (), 13, 2),
        (10237203, 1, None, None, (), 14, 1),
        (10237211, 1, None, None, (), 14, 1),
    ],
    "42351": [
        (6976963, 155, 69, 69, (6644198, 6644360, 6644397, 6646665), 0, 155),
        (6976965, 165, 69, 69, (6644198, 6644360, 6644397, 6646665), 1, 165),
        (7968245, 2, None, 69, (6644384,), 2, 2),
        (7501301, 9, None, None, (), 3, 9),
        (7630621, 1, None, None, (), 4, 1),
        (7630623, 1, None, None, (), 4, 1),
        (7830664, 2, None, None, (), 5, 2),
        (7830678, 2, None, None, (), 5, 2),
        (7985181, 1, None, None, (), 6, 1),
        (7985187, 1, None, None, (), 6, 1),
        (7985188, 1, None, None, (), 6, 1),
        (7999126, 1, None, None, (), 7, 1),
        (7999127, 1, None, None, (), 7, 1),
        (7999139, 1, None, None, (), 7, 1),
        (7999140, 1, None, None, (), 7, 1),
        (9901379, 3, None, None, (), 8, 3),
        (9901380, 3, None, None, (), 8, 3),
        (9965968, 2, None, None, (), 9, 2),
        (9965980, 2, None, None, (), 9, 2),
        (9965982, 2, None, None, (), 9, 2),
    ],
    "93154": [
        (6822061, 99, 69, 69, (6642345, 6644124, 10126973, 10126974), 0, 99),
        (6822062, 99, 69, 69, (6642345, 6644124, 10126973, 10126974), 0, 99),
        (6776439, 1, None, 69, (6642072,), 1, 1),
        (6776440, 1, None, 69, (6642072,), 1, 1),
        (6973706, 3, None, None, (), 2, 3),
        (7403010, 2, None, None, (), 3, 2),
        (7483864, 36, None, 69, (6641630,), 4, 36),
        (7483865, 10, None, None, (), 5, 10),
        (7483942, 3, None, None, (), 6, 3),
        (7485661, 1, None, None, (), 7, 1),
        (7488496, 8, None, 86, (6646660,), 8, 8),
        (7488499, 8, None, 86, (6646660,), 8, 8),
        (7585231, 3, None, None, (), 9, 3),
        (7585232, 3, None, None, (), 9, 3),
        (7630629, 1, None, None, (), 10, 1),
        (7630640, 1, None, None, (), 10, 1),
        (7670697, 2, None, None, (), 11, 2),
        (7672397, 2, None, None, (), 12, 2),
        (7717215, 65, 69, 69, (6641368, 6642591, 6644320, 6644537, 6644557), 13, 65),
        (7717217, 4, None, None, (), 14, 4),
        (9233135, 3, None, None, (), 15, 3),
        (9233136, 3, None, None, (), 15, 3),
        (9522001, 2, None, None, (), 16, 2),
        (9522007, 2, None, None, (), 16, 2),
        (9786615, 2, None, None, (), 17, 2),
        (9786619, 2, None, None, (), 17, 2),
        (9901398, 3, None, None, (), 18, 3),
        (9901435, 3, None, None, (), 18, 3),
    ],
    "94673": [
        (6799772, 27, None, None, (), 0, 27),
        (6799773, 27, None, None, (), 0, 27),
    ],
}

TRAMOS_ESPERADOS = {
    "102452": {6799794, 6799795, 7655082, 7655083, 7722344, 7722345},
    "42351": {6976963, 6976965},
    "93154": {6822061, 6822062},
    "94673": {6799772, 6799773},
}


def _extremo(clase_odf, odf_id):
    if clase_odf is None:
        return ExtremoCamino(tipo="PELO", id_cromo=1, clase=130)
    return ExtremoCamino(
        tipo="CONECTOR_ODF", id_cromo=2, clase=136, odf_id=odf_id, odf_clase=clase_odf,
        patchera_nombre="O-1", conector_numero="1",
    )


def _cables(servicio, grupo, cantidad):
    if servicio == "42351" and grupo == 1:
        return tuple(range(0, 145)) + tuple(range(100_000, 100_020))
    return tuple(range(grupo * 1000, grupo * 1000 + cantidad))


def _caminos(servicio):
    caminos = []
    for semilla, pelos, ini, fin, odfs, grupo, cantidad in MEDIDO[servicio]:
        odf = odfs[0] if odfs else None
        caminos.append(
            TrackingGenerado(
                pelo_n_id=semilla,
                nombre_archivo="x.txt",
                contenido="",
                desde_cache=True,
                generado_at=AHORA,
                duracion_ms=None,
                pelos_camino=frozenset(range(semilla, semilla + pelos)),
                extremos=ResumenCamino(
                    inicio=_extremo(ini, odf),
                    fin=_extremo(fin, odfs[-1] if odfs else None),
                    odfs=odfs,
                    cables=_cables(servicio, grupo, cantidad),
                    servicio_at62=servicio,
                ),
            )
        )
    return caminos


def _tramos(caminos, roles):
    return {c.pelo_n_id for c, r in zip(caminos, roles) if r == ROL_TRAMO}


@pytest.mark.parametrize("servicio", sorted(MEDIDO))
def test_los_servicios_medidos_dan_los_tramos_esperados(servicio):
    """102452: 3 pares (6 tramos) y 21 residuales; 42351, 93154 y 94673: 2 tramos cada uno."""
    caminos = _caminos(servicio)
    roles = clasificar_caminos(caminos)
    assert _tramos(caminos, roles) == TRAMOS_ESPERADOS[servicio]
    assert set(roles) <= {ROL_TRAMO, ROL_RESIDUAL}
    assert len(roles) == len(caminos)


def test_fo_que_sale_de_una_odf_nodo_y_no_termina_en_otra_odf_es_tramo():
    """102452: el par 6799794/95 entra por un pelo de F-VIN-TEC y termina en la ODF Nodo
    O-9585104-3. Un solo extremo en ODF Nodo alcanza."""
    caminos = _caminos("102452")
    roles = dict(zip((c.pelo_n_id for c in caminos), clasificar_caminos(caminos)))
    assert roles[6799794] == ROL_TRAMO and roles[6799795] == ROL_TRAMO


def test_un_camino_largo_sin_par_no_es_tramo_si_el_servicio_es_bifilar():
    """93154: 7717215 (65 pelos, ODF a ODF) y 7483864 (36 pelos) no tienen par; los hilos del
    servicio sí (6822061/62, 99 pelos cada uno)."""
    caminos = _caminos("93154")
    roles = dict(zip((c.pelo_n_id for c in caminos), clasificar_caminos(caminos)))
    assert roles[7717215] == ROL_RESIDUAL
    assert roles[7483864] == ROL_RESIDUAL


def test_una_odf_confirmada_hace_tramo_al_camino_que_la_toca():
    """Tarea 4 confirma ODFs del Servicio: un camino que toca una es tramo aunque sea chico."""
    caminos = _caminos("93154")
    roles = dict(
        zip(
            (c.pelo_n_id for c in caminos),
            clasificar_caminos(caminos, odfs_confirmadas=frozenset({6641630})),
        )
    )
    assert roles[7483864] == ROL_TRAMO
    assert roles[6822061] == ROL_TRAMO


def test_servicio_monofilar_no_exige_par():
    """PON o SW de módulo bifilar: un solo hilo. Sin ningún par, no se exige."""
    caminos = _caminos("42351")[:1]
    assert clasificar_caminos(caminos) == [ROL_TRAMO]


def test_sin_odf_y_sin_resumen_un_solo_camino_es_tramo():
    camino = TrackingGenerado(
        pelo_n_id=1, nombre_archivo="x.txt", contenido="", desde_cache=False, generado_at=AHORA,
        duracion_ms=None, pelos_camino=frozenset({1, 2}),
    )
    assert clasificar_caminos([camino]) == [ROL_TRAMO]


def test_sin_caminos_devuelve_lista_vacia():
    assert clasificar_caminos([]) == []


def test_odf_de_clase_desconocida_cuenta_como_odf():
    """Si el payload no trajera `class` en el `gfather`, no se pierde el tramo."""
    caminos = _caminos("94673")
    for c in caminos:
        c.extremos = ResumenCamino(
            inicio=ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=3, clase=136, odf_id=77),
            fin=c.extremos.fin, odfs=(77,), cables=c.extremos.cables,
        )
    assert clasificar_caminos(caminos) == [ROL_TRAMO, ROL_TRAMO]


def _camino(semilla, pelos, *, ini=None, fin=None, odfs=(), cables=()):
    return TrackingGenerado(
        pelo_n_id=semilla, nombre_archivo="x.txt", contenido="", desde_cache=True,
        generado_at=AHORA, duracion_ms=None, pelos_camino=frozenset(range(semilla, semilla + pelos)),
        extremos=ResumenCamino(
            inicio=_extremo(ini, odfs[0] if odfs else None),
            fin=_extremo(fin, odfs[-1] if odfs else None),
            odfs=tuple(odfs), cables=tuple(cables),
        ),
    )


def test_monofilar_con_un_par_de_ruido_no_pierde_el_hilo_real():
    """Un hilo de 100 pelos de ODF a ODF sin par, más un par de ruido de 1 pelo con extremo en
    ODF (como 93154/6776439-40): el ruido no puede volver obligatorio el par."""
    caminos = [
        _camino(1000, 100, ini=69, fin=69, odfs=(5, 6), cables=range(100)),
        _camino(1, 1, fin=69, odfs=(7,), cables=(5000,)),
        _camino(2, 1, fin=69, odfs=(7,), cables=(5000,)),
    ]
    assert clasificar_caminos(caminos) == [ROL_TRAMO, ROL_RESIDUAL, ROL_RESIDUAL]


def test_odfs_solo_intermedias_no_dejan_al_servicio_sin_tramos():
    """Si ningún camino termina en ODF, una ODF intermedia no excluye a nadie: todos son
    candidatos y el par decide."""
    caminos = [
        _camino(1, 50, odfs=(5,), cables=range(50)),
        _camino(100, 50, odfs=(5,), cables=range(50)),
    ]
    assert clasificar_caminos(caminos) == [ROL_TRAMO, ROL_TRAMO]
