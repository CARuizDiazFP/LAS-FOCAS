# Nombre de archivo: test_cromo_tracking_clasificacion.py
# Ubicación de archivo: tests/test_cromo_tracking_clasificacion.py
# Descripción: Pruebas de `clasificar_caminos` (TRAMO / RESIDUAL) con los caminos medidos contra Cromo
# real el 2026-10-16 sobre los Servicios 102452, 42351, 93154 y 94673, y de `clasificar_con_posiciones`
# (VIGENTE / ADICIONAL) con el caso 93150 medido el 2026-10-21

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.services.cromo.tracking_service import (
    ORIGEN_DECLARADO,
    ORIGEN_ETIQUETADO,
    ORIGEN_POSICION,
    ROL_ADICIONAL,
    ROL_RESIDUAL,
    ROL_TRAMO,
    ROL_VIGENTE,
    ExtremoCamino,
    ResumenCamino,
    TrackingGenerado,
    clasificar_caminos,
    clasificar_con_posiciones,
    es_camino_completo,
    origen_del_camino,
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


def test_una_odf_confirmada_rescata_al_camino_que_termina_en_ella():
    """Tarea 4 confirma ODFs del Servicio: un camino que TERMINA en una es tramo aunque no tenga
    par (93154: 7483864, 36 pelos, termina en la ODF 6641630)."""
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


def test_extremo_conector_odf_sin_odf_id_es_candidato_a_tramo():
    """M1: un camino que termina en un conector de ODF sin `gfather` resuelto termina en ODF: no
    puede perder contra un camino sin ODF por un dato faltante."""
    sin_gfather = ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=3, clase=136)
    pelo = ExtremoCamino(tipo="PELO", id_cromo=1, clase=130)
    caminos = [
        TrackingGenerado(
            pelo_n_id=1, nombre_archivo="x.txt", contenido="", desde_cache=True, generado_at=AHORA,
            duracion_ms=None, pelos_camino=frozenset(range(1, 40)),
            extremos=ResumenCamino(inicio=sin_gfather, fin=pelo, cables=tuple(range(40))),
        ),
        _camino(1000, 100, cables=range(1000, 1100)),
    ]
    assert clasificar_caminos(caminos) == [ROL_TRAMO, ROL_RESIDUAL]


def test_contar_segmentos_agrupa_los_tramos_que_comparten_cables():
    """I4: mismo corte que el par de `clasificar_caminos` (Jaccard >= 0,8)."""
    from core.services.cromo.tracking_service import contar_segmentos

    par_42351 = [_camino(1, 50, cables=range(155)), _camino(100, 50, cables=range(10, 165))]
    assert contar_segmentos(par_42351) == 1

    tres_pares = [
        _camino(i * 1000 + j, 20, cables=range(i * 100, i * 100 + 30))
        for i in range(3)
        for j in range(2)
    ]
    assert contar_segmentos(tres_pares) == 3
    assert contar_segmentos([_camino(1, 5, cables=(1,))]) == 1
    assert contar_segmentos([]) == 0


def test_odf_confirmada_no_rescata_al_camino_que_solo_la_toca_en_el_medio():
    """Medido en dev (2026-10-18, 102452): confirmar KORN y los racks de Dixon volvía tramos a
    caminos de 2 pelos que sólo pasaban por esas ODF, sin terminar en ellas (6 → 12 trackings)."""
    largo_a = _camino(1, 40, ini=86, fin=86, odfs=(500, 600), cables=(1, 2))
    largo_b = _camino(100, 40, ini=86, fin=86, odfs=(500, 600), cables=(1, 2))
    medio = _camino(200, 2, odfs=(600,), cables=(9,))
    roles = clasificar_caminos([largo_a, largo_b, medio], odfs_confirmadas=frozenset({600}))
    assert roles == [ROL_TRAMO, ROL_TRAMO, ROL_RESIDUAL]


def test_odf_confirmada_no_rescata_ruido_chico_que_termina_en_ella():
    """Un camino de 2-3 pelos que termina en una ODF confirmada sigue siendo ruido: la
    confirmación saltea la exigencia de par, no el filtro de proporción (102452: 7801857/58 y
    7246874/75 terminaban en ODF confirmadas y duplicaban los trackings)."""
    largo_a = _camino(1, 40, ini=86, fin=86, odfs=(500, 600), cables=(1, 2))
    largo_b = _camino(100, 40, ini=86, fin=86, odfs=(500, 600), cables=(1, 2))
    stub = _camino(200, 3, fin=86, odfs=(600,), cables=(9,))
    roles = clasificar_caminos([largo_a, largo_b, stub], odfs_confirmadas=frozenset({600}))
    assert roles == [ROL_TRAMO, ROL_TRAMO, ROL_RESIDUAL]


# ── Clasificación con posiciones (VIGENTE / ADICIONAL) ─────────────────────────────────────────
#
# Caso 93150, medido en dev el 2026-10-21 (`resolver_camino_de_pelo` sin caché, dentro de
# lasfocasdev-web). El camino nuevo (6799280/81, etiquetado 93150) va de Guanahani Sala Servidores
# O-1239921-1:19/20 a San Martín O-1239922-1:1/2, 40 pelos. El viejo (7028862/63) sale de las
# posiciones —sus pelos dicen 44649— y va de O-1252871-1:1/2 (ODF 6644560, clase 69) a
# O-1252734-1:11/12 (ODF 6644536, clase 69), 49 pelos y 48 cables; incluye 6799284 (cruza
# O-1239922-1:5). 7469850 (etiquetado) va de un PELO a Ramos Mejía O-1234347-1:4, 19 pelos. Los
# caminos viejo y nuevo no comparten pelos. Los ids de ODF de Guanahani Sala Servidores y de Ramos
# Mejía no se midieron: se usan ids de fantasía.
_ODF_SAN_MARTIN_P5 = 6644560
_ODF_GUANAHANI_RACK = 6644536
_ODF_SAN_MARTIN = 6642346
_ODF_GUANAHANI_SALA = 900_001
_ODF_RAMOS_MEJIA = 900_002


def _conector(odf_id, patchera, conector, clase=69):
    return ExtremoCamino(
        tipo="CONECTOR_ODF", id_cromo=2, clase=136, odf_id=odf_id, odf_clase=clase,
        patchera_nombre=patchera, conector_numero=conector,
    )


def _camino_real(semilla, pelos, *, ini, fin, cables):
    odfs = tuple(e.odf_id for e in (ini, fin) if e.odf_id is not None)
    return TrackingGenerado(
        pelo_n_id=semilla, nombre_archivo="x.txt", contenido="", desde_cache=True,
        generado_at=AHORA, duracion_ms=None, pelos_camino=frozenset(pelos),
        extremos=ResumenCamino(inicio=ini, fin=fin, odfs=odfs, cables=tuple(cables)),
    )


_PELO = ExtremoCamino(tipo="PELO", id_cromo=1, clase=130)


def _caminos_93150():
    viejo = [
        _camino_real(
            semilla,
            {semilla, 6799284 + i, *range(8_000_000 + i * 100, 8_000_000 + i * 100 + 47)},
            ini=_conector(_ODF_SAN_MARTIN_P5, "O-1252871-1", str(i + 1)),
            fin=_conector(_ODF_GUANAHANI_RACK, "O-1252734-1", str(i + 11)),
            cables=range(500, 548),
        )
        for i, semilla in enumerate((7028862, 7028863))
    ]
    nuevo = [
        _camino_real(
            semilla,
            {semilla, *range(9_000_000 + i * 100, 9_000_000 + i * 100 + 39)},
            ini=_conector(_ODF_GUANAHANI_SALA, "O-1239921-1", str(i + 19)),
            fin=_conector(_ODF_SAN_MARTIN, "O-1239922-1", str(i + 1)),
            cables=range(600, 640),
        )
        for i, semilla in enumerate((6799280, 6799281))
    ]
    residual = _camino_real(
        7469850, {7469850, *range(9_500_000, 9_500_018)},
        ini=_PELO, fin=_conector(_ODF_RAMOS_MEJIA, "O-1234347-1", "4"), cables=range(700, 719),
    )
    return [*viejo, *nuevo, residual]


_ETIQUETADOS_93150 = frozenset({6799280, 6799281, 7469850})
_DECLARADOS_93150 = frozenset({7028862, 7028863})


def _roles_por_pelo(caminos, roles):
    return dict(zip((c.pelo_n_id for c in caminos), roles))


class TestEsCaminoCompleto:
    def test_odf_en_ambos_extremos_es_completo(self):
        viejo = _caminos_93150()[0]
        assert es_camino_completo(viejo)

    def test_un_extremo_en_pelo_no_es_completo(self):
        assert not es_camino_completo(_caminos_93150()[-1])

    def test_odf_de_clase_desconocida_cuenta_como_odf(self):
        """Igual que `_termina_en_odf`: no se pierde un camino por un `gfather` sin `class`."""
        sin_clase = _conector(77, "O-1", "1", clase=None)
        camino = _camino_real(1, {1}, ini=sin_clase, fin=sin_clase, cables=(1,))
        assert es_camino_completo(camino)

    def test_conector_en_algo_que_no_es_odf_no_es_completo(self):
        otro = _conector(77, "O-1", "1", clase=70)
        camino = _camino_real(1, {1}, ini=otro, fin=_conector(78, "O-2", "1"), cables=(1,))
        assert not es_camino_completo(camino)

    def test_sin_resumen_no_es_completo(self):
        camino = TrackingGenerado(
            pelo_n_id=1, nombre_archivo="x.txt", contenido="", desde_cache=False, generado_at=AHORA,
            duracion_ms=None, pelos_camino=frozenset({1}),
        )
        assert not es_camino_completo(camino)


class TestOrigenDelCamino:
    def test_declarado_gana_aunque_el_camino_toque_un_etiquetado(self):
        camino = _camino_real(10, {10, 11}, ini=_PELO, fin=_PELO, cables=())
        assert (
            origen_del_camino(camino, etiquetados=frozenset({11}), declarados=frozenset({10}))
            == ORIGEN_DECLARADO
        )

    def test_es_por_interseccion_de_pelos_y_no_por_la_semilla(self):
        """El camino nuevo del 93150 también sale de una posición (O-1239922-1:1): si lo resolvió esa
        semilla y no la etiquetada, sigue siendo ETIQUETADO porque sus pelos la incluyen."""
        camino = _camino_real(55, {55, 6799280}, ini=_PELO, fin=_PELO, cables=())
        assert (
            origen_del_camino(camino, etiquetados=_ETIQUETADOS_93150, declarados=frozenset())
            == ORIGEN_ETIQUETADO
        )
        camino_decl = _camino_real(55, {55, 7028863}, ini=_PELO, fin=_PELO, cables=())
        assert (
            origen_del_camino(camino_decl, etiquetados=frozenset(), declarados=_DECLARADOS_93150)
            == ORIGEN_DECLARADO
        )

    def test_sin_interseccion_es_posicion(self):
        viejo = _caminos_93150()[0]
        assert (
            origen_del_camino(viejo, etiquetados=_ETIQUETADOS_93150, declarados=frozenset())
            == ORIGEN_POSICION
        )


@pytest.mark.parametrize("servicio", sorted(MEDIDO))
@pytest.mark.parametrize("confirmadas", [frozenset(), frozenset({6641630})])
def test_sin_declarados_ni_posiciones_es_identico_a_clasificar_caminos(servicio, confirmadas):
    """Regresión: con todas las semillas etiquetadas y sin declaración nada cambia (77 caminos)."""
    caminos = _caminos(servicio)
    etiquetados = frozenset(c.pelo_n_id for c in caminos)
    assert clasificar_con_posiciones(
        caminos, etiquetados=etiquetados, declarados=frozenset(), odfs_confirmadas=confirmadas
    ) == clasificar_caminos(caminos, odfs_confirmadas=confirmadas)


@pytest.mark.parametrize("invertir", [False, True])
def test_93150_sin_declaracion_el_nuevo_es_tramo_y_el_viejo_adicional(invertir):
    """Sin declaración el camino nuevo sigue siendo el tramo (como hoy) y el viejo, que sale sólo de
    posiciones y termina en ODF en los dos extremos, es ADICIONAL. No depende del orden."""
    caminos = _caminos_93150()
    if invertir:
        caminos = list(reversed(caminos))
    roles = _roles_por_pelo(
        caminos,
        clasificar_con_posiciones(caminos, etiquetados=_ETIQUETADOS_93150, declarados=frozenset()),
    )
    assert roles == {
        6799280: ROL_TRAMO, 6799281: ROL_TRAMO,
        7028862: ROL_ADICIONAL, 7028863: ROL_ADICIONAL,
        7469850: ROL_RESIDUAL,
    }


def test_93150_con_declaracion_el_viejo_es_vigente_y_el_nuevo_adicional():
    caminos = _caminos_93150()
    roles = _roles_por_pelo(
        caminos,
        clasificar_con_posiciones(
            caminos, etiquetados=_ETIQUETADOS_93150, declarados=_DECLARADOS_93150
        ),
    )
    assert roles == {
        7028862: ROL_VIGENTE, 7028863: ROL_VIGENTE,
        6799280: ROL_ADICIONAL, 6799281: ROL_ADICIONAL,
        7469850: ROL_RESIDUAL,
    }


def test_declaracion_sin_camino_resuelto_no_degrada_los_tramos():
    """Si el camino declarado no está entre los resueltos no hay VIGENTE que lo reemplace: los
    tramos siguen siendo tramos."""
    caminos = _caminos_93150()[2:]
    roles = clasificar_con_posiciones(
        caminos, etiquetados=_ETIQUETADOS_93150, declarados=_DECLARADOS_93150
    )
    assert roles == [ROL_TRAMO, ROL_TRAMO, ROL_RESIDUAL]


def test_camino_de_posicion_incompleto_es_residual():
    """Un camino que sale sólo de posiciones y no termina en ODF en los dos extremos es ruido."""
    caminos = _caminos_93150()
    stub = _camino_real(
        1, set(range(1, 30)), ini=_PELO, fin=_conector(_ODF_SAN_MARTIN, "O-1239922-1", "7"),
        cables=range(800, 830),
    )
    roles = clasificar_con_posiciones(
        [*caminos, stub], etiquetados=_ETIQUETADOS_93150, declarados=frozenset()
    )
    assert roles[-1] == ROL_RESIDUAL


def test_caminos_de_posiciones_no_mueven_el_umbral_de_proporcion():
    """Si un camino de posición de 200 pelos entrara a `clasificar_caminos`, el 25 % pasaría a 50 y
    el par etiquetado de 40 pelos quedaría RESIDUAL."""
    par = _caminos_93150()[2:4]
    largo = _camino_real(
        1, set(range(1, 201)), ini=_conector(10, "O-10", "1"), fin=_conector(11, "O-11", "1"),
        cables=range(900, 1100),
    )
    assert clasificar_caminos([*par, largo]) == [ROL_RESIDUAL, ROL_RESIDUAL, ROL_TRAMO]
    roles = clasificar_con_posiciones(
        [*par, largo], etiquetados=frozenset({6799280, 6799281}), declarados=frozenset()
    )
    assert roles == [ROL_TRAMO, ROL_TRAMO, ROL_ADICIONAL]


def test_vigente_no_participa_de_clasificar_caminos():
    """Un camino declarado largo tampoco mueve el umbral: el par etiquetado sigue pasando y, como
    hay declaración aplicada, queda ADICIONAL (no RESIDUAL)."""
    par = _caminos_93150()[2:4]
    declarado = _camino_real(
        1, set(range(1, 201)), ini=_conector(10, "O-10", "1"), fin=_conector(11, "O-11", "1"),
        cables=range(900, 1100),
    )
    roles = clasificar_con_posiciones(
        [declarado, *par], etiquetados=frozenset({6799280, 6799281}), declarados=frozenset({1})
    )
    assert roles == [ROL_VIGENTE, ROL_ADICIONAL, ROL_ADICIONAL]


def test_odf_confirmada_sigue_rescatando_solo_entre_etiquetados():
    """La ODF confirmada rescata al etiquetado sin par que termina en ella (como en
    `clasificar_caminos`), pero no vuelve tramo a un camino de posición incompleto que también
    termina en ella."""
    par = _caminos_93150()[2:4]
    confirmada = 600_000
    etiquetado_sin_par = _camino_real(
        7469850, set(range(7469850, 7469880)), ini=_PELO,
        fin=_conector(confirmada, "O-60", "1"), cables=range(1200, 1230),
    )
    de_posicion = _camino_real(
        1, set(range(1, 31)), ini=_PELO, fin=_conector(confirmada, "O-60", "2"),
        cables=range(1300, 1330),
    )
    roles = clasificar_con_posiciones(
        [*par, etiquetado_sin_par, de_posicion],
        etiquetados=frozenset({6799280, 6799281, 7469850}),
        declarados=frozenset(),
        odfs_confirmadas=frozenset({confirmada}),
    )
    assert roles == [ROL_TRAMO, ROL_TRAMO, ROL_TRAMO, ROL_RESIDUAL]


def test_clasificar_con_posiciones_sin_caminos_devuelve_lista_vacia():
    assert clasificar_con_posiciones([], etiquetados=frozenset(), declarados=frozenset()) == []


# ── Camino de posición ajeno: domina la etiqueta de otro servicio Activo ─────────────────────


def test_camino_de_posicion_ajeno_es_residual():
    """El filtro de las posiciones mira sólo el pelo semilla: un conector resuelto a este Servicio
    con un pelo sin etiqueta pasa, pero su `/path` puede ser el camino de OTRO servicio Activo
    (caso 42352 ↔ 42351). Ese camino de origen POSICION (`caminos_ajenos`, por etiqueta
    dominante), aunque termine en ODF en los dos extremos, no es ADICIONAL."""
    caminos = _caminos_93150()
    roles = _roles_por_pelo(
        caminos,
        clasificar_con_posiciones(
            caminos,
            etiquetados=_ETIQUETADOS_93150,
            declarados=frozenset(),
            caminos_ajenos=frozenset({7028862}),
        ),
    )
    assert roles == {
        6799280: ROL_TRAMO, 6799281: ROL_TRAMO,
        7028862: ROL_RESIDUAL, 7028863: ROL_ADICIONAL,
        7469850: ROL_RESIDUAL,
    }


def test_caminos_ajenos_no_degradan_al_declarado_ni_al_etiquetado():
    """El DECLARADO es una decisión explícita del admin y el ETIQUETADO lleva la etiqueta del
    Servicio: el filtro sólo aplica a los caminos de origen POSICION."""
    caminos = _caminos_93150()
    roles = _roles_por_pelo(
        caminos,
        clasificar_con_posiciones(
            caminos,
            etiquetados=_ETIQUETADOS_93150,
            declarados=_DECLARADOS_93150,
            caminos_ajenos=frozenset(c.pelo_n_id for c in caminos),
        ),
    )
    assert roles == {
        7028862: ROL_VIGENTE, 7028863: ROL_VIGENTE,
        6799280: ROL_ADICIONAL, 6799281: ROL_ADICIONAL,
        7469850: ROL_RESIDUAL,
    }


# ── Umbral de tamaño en los adicionales de posición (proporción del 25 %) ─────────────────────
#
# Caso 102452 (`servicios.id=1168`), E2E real contra Cromo en dev (2026-10-22): las posiciones
# daban 2 adicionales de 1 pelo cada uno (semillas 9614673/9614674), jumpers dentro del mismo Nodo
# Dixon entre 'Rack 1 Sala 2' O-9585104-6:3/4 y 'Rack 2 SAENZ PEÑA' O-1247502-3:3/4. Terminan en
# ODF Nodo en los dos extremos (camino "completo"), pero los tramos reales tienen 47/27/24 pelos.
# El id de la ODF del Rack 2 SAENZ PEÑA no se midió: se usa uno de fantasía.
_ODF_NODO_DIXON_RACK_1 = 9585104
_ODF_NODO_DIXON_RACK_2 = 900_003


def _jumpers_102452():
    return [
        _camino_real(
            semilla,
            {semilla},
            ini=_conector(_ODF_NODO_DIXON_RACK_1, "O-9585104-6", numero, clase=86),
            fin=_conector(_ODF_NODO_DIXON_RACK_2, "O-1247502-3", numero, clase=86),
            cables=(),
        )
        for semilla, numero in ((9614673, "3"), (9614674, "4"))
    ]


def test_102452_jumper_de_posicion_de_1_pelo_frente_a_tramos_de_47_es_residual():
    caminos = [*_caminos("102452"), *_jumpers_102452()]
    etiquetados = frozenset(c.pelo_n_id for c in _caminos("102452"))
    roles = _roles_por_pelo(
        caminos,
        clasificar_con_posiciones(caminos, etiquetados=etiquetados, declarados=frozenset()),
    )
    assert all(es_camino_completo(j) for j in _jumpers_102452())
    assert roles[9614673] == ROL_RESIDUAL and roles[9614674] == ROL_RESIDUAL
    # Los tramos medidos no cambian.
    assert {p for p, r in roles.items() if r == ROL_TRAMO} == TRAMOS_ESPERADOS["102452"]
    assert ROL_ADICIONAL not in roles.values()


def test_93150_adicional_de_posicion_de_49_pelos_frente_a_tramos_de_40_sigue_adicional():
    caminos = _caminos_93150()
    assert [len(c.pelos_camino) for c in caminos[:4]] == [49, 49, 40, 40]
    roles = _roles_por_pelo(
        caminos,
        clasificar_con_posiciones(caminos, etiquetados=_ETIQUETADOS_93150, declarados=frozenset()),
    )
    assert roles[7028862] == ROL_ADICIONAL and roles[7028863] == ROL_ADICIONAL


def test_la_proporcion_de_posicion_mira_el_camino_completo_mas_largo_de_cualquier_origen():
    """El máximo sale de TODOS los caminos completos (etiquetados, declarados y de posición), no
    sólo de los etiquetados: un camino de posición de 10 pelos frente a un declarado completo de
    49 (10 < 12,25) es RESIDUAL; frente a un tramo de 40 sólo (10 ≥ 10) es ADICIONAL. Un camino
    incompleto no entra al máximo."""
    viejo, _, nuevo, nuevo_2, residual = _caminos_93150()
    chico = _camino_real(
        1, set(range(1, 11)), ini=_conector(10, "O-10", "1"), fin=_conector(11, "O-11", "1"),
        cables=(1,),
    )
    roles = clasificar_con_posiciones(
        [viejo, nuevo, nuevo_2, chico],
        etiquetados=_ETIQUETADOS_93150,
        declarados=frozenset({viejo.pelo_n_id}),
    )
    assert roles == [ROL_VIGENTE, ROL_ADICIONAL, ROL_ADICIONAL, ROL_RESIDUAL]
    largo_incompleto = _camino_real(
        500, set(range(500, 800)), ini=_PELO, fin=_conector(12, "O-12", "1"), cables=(2,),
    )
    roles = clasificar_con_posiciones(
        [nuevo, nuevo_2, largo_incompleto, chico],
        etiquetados=frozenset({6799280, 6799281, 500}),
        declarados=frozenset(),
    )
    assert roles[-1] == ROL_ADICIONAL
