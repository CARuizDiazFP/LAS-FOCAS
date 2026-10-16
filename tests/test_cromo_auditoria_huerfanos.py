# Nombre de archivo: test_cromo_auditoria_huerfanos.py
# Ubicación de archivo: tests/test_cromo_auditoria_huerfanos.py
# Descripción: Pruebas de la clasificación de causa de los huérfanos (función pura) con los caminos
# medidos contra Cromo real el 2026-10-16 sobre los Servicios 102452, 42351 y 93154

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.services.cromo.auditoria_huerfanos import (
    CAUSA_CABLE_DESUSO,
    CAUSA_CAMBIO_CABLE_DANO,
    CAUSA_MIGRACION_SITIO,
    CAUSA_PELO_DANADO,
    CAUSA_SIN_CLASIFICAR,
    clasificar_residual,
    es_normalizable,
)
from core.services.cromo.tracking_service import (
    ROL_RESIDUAL,
    ExtremoCamino,
    ResumenCamino,
    TrackingGenerado,
    clasificar_caminos,
)

AHORA = datetime(2026, 10, 16, tzinfo=timezone.utc)
MEDIDO = json.loads(
    (Path(__file__).parent / "fixtures" / "cromo_huerfanos_medido_2026_10_16.json").read_text()
)
CABLES_SIN_USO = frozenset(MEDIDO["cables_sin_uso"])


def _extremo(crudo):
    if not crudo:
        return None
    return ExtremoCamino(
        tipo=crudo["tipo"],
        id_cromo=crudo["id"],
        odf_id=crudo.get("odf_id"),
        odf_clase=crudo.get("odf_clase"),
    )


def _resumen(camino) -> ResumenCamino:
    return ResumenCamino(
        inicio=_extremo(camino["ini"]),
        fin=_extremo(camino["fin"]),
        odfs=tuple(camino["odfs"]),
        cables=tuple(camino["cables"]),
        botellas=tuple(camino["botellas"]),
        botella_inicio=camino["bot_ini"],
        botella_fin=camino["bot_fin"],
    )


def _clasificar_servicio(numero: str) -> dict[int, object]:
    """Separa tramos y residuales con `clasificar_caminos` y clasifica cada residual."""
    caminos = MEDIDO["servicios"][numero]["caminos"]
    trackings = [
        TrackingGenerado(
            pelo_n_id=c["semilla"],
            nombre_archivo="",
            contenido="",
            desde_cache=False,
            generado_at=AHORA,
            duracion_ms=None,
            pelos_camino=frozenset(c["semilla"] * 1000 + i for i in range(c["pelos"])),
            extremos=_resumen(c),
        )
        for c in caminos
    ]
    roles = clasificar_caminos(trackings)
    tramos = [t.extremos for t, r in zip(trackings, roles) if r != ROL_RESIDUAL]
    return {
        t.pelo_n_id: clasificar_residual(t.extremos, tramos, cables_sin_uso=CABLES_SIN_USO)
        for t, r in zip(trackings, roles)
        if r == ROL_RESIDUAL
    }


# Residuales con un extremo en ODF (69) u ODF Nodo (86): nunca candidatos a normalizar.
PROTEGIDOS = {
    "102452": {7183576, 7183577, 7246874, 7246875},
    "42351": {7968245},
    "93154": {6776439, 6776440, 7483864, 7488496, 7488499, 7717215},
}


@pytest.mark.parametrize("numero", sorted(PROTEGIDOS))
def test_residual_con_extremo_en_odf_queda_protegido(numero):
    clasificados = _clasificar_servicio(numero)
    protegidos = {semilla for semilla, c in clasificados.items() if c.protegido}
    assert protegidos == PROTEGIDOS[numero]
    assert not any(es_normalizable(c.causa, c.protegido) for s, c in clasificados.items() if s in protegidos)


def test_cable_desuso_sale_del_tendido_sin_uso_real():
    """42351: los 9 residuales cuyos cables están todos con tendido 'Sin Uso' (at.20) en Cromo."""
    clasificados = _clasificar_servicio("42351")
    desuso = {s for s, c in clasificados.items() if c.causa == CAUSA_CABLE_DESUSO}
    assert desuso == {7830664, 7830678, 7985181, 7985187, 7985188, 7999126, 7999127, 7999139, 7999140}
    assert all(not clasificados[s].protegido for s in desuso)


def test_cable_desuso_exige_todos_los_cables_sin_uso():
    """102452 7246874/75: 1 de sus 2 cables es 'Sin Uso' — no alcanza (y además es protegido)."""
    clasificados = _clasificar_servicio("102452")
    assert clasificados[7246874].causa != CAUSA_CABLE_DESUSO
    assert clasificados[7246874].evidencia()["senales"]["cables_sin_uso"] == 1


def test_distribucion_medida_por_servicio():
    """Las causas que da la regla sobre los 65 residuales medidos (21 + 18 + 26)."""
    esperado = {
        "102452": {
            CAUSA_PELO_DANADO: 3,
            CAUSA_MIGRACION_SITIO: 6,
            CAUSA_SIN_CLASIFICAR: 12,
        },
        "42351": {
            CAUSA_CABLE_DESUSO: 9,
            CAUSA_PELO_DANADO: 1,
            CAUSA_MIGRACION_SITIO: 6,
            CAUSA_SIN_CLASIFICAR: 2,
        },
        "93154": {
            CAUSA_PELO_DANADO: 11,
            CAUSA_CAMBIO_CABLE_DANO: 1,
            CAUSA_MIGRACION_SITIO: 11,
            CAUSA_SIN_CLASIFICAR: 3,
        },
    }
    for numero, causas in esperado.items():
        clasificados = _clasificar_servicio(numero)
        assert Counter(c.causa for c in clasificados.values()) == causas, numero


def test_pelo_danado_comparte_cable_con_un_tramo():
    clasificados = _clasificar_servicio("102452")
    danados = {s for s, c in clasificados.items() if c.causa == CAUSA_PELO_DANADO}
    assert danados == {7832494, 9358533, 10196042}
    assert clasificados[9358533].evidencia()["senales"]["cables_compartidos_con_tramos"] == 7


def _pelo(i: int) -> ExtremoCamino:
    return ExtremoCamino(tipo="PELO", id_cromo=i, clase=130)


def _odf(odf_id: int, clase: int | None) -> ExtremoCamino:
    return ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=odf_id + 1, odf_id=odf_id, odf_clase=clase)


TRAMO = ResumenCamino(
    inicio=_odf(500, 69),
    fin=_odf(600, 69),
    odfs=(500, 600),
    cables=(1, 2, 3),
    botellas=(10, 20, 30),
    botella_inicio=10,
    botella_fin=30,
)


def test_cambio_de_cable_en_paralelo_entre_las_mismas_botellas():
    residual = ResumenCamino(
        inicio=_pelo(1), fin=_pelo(2), cables=(7, 8), botellas=(10, 30), botella_inicio=10, botella_fin=30
    )
    c = clasificar_residual(residual, [TRAMO])
    assert c.causa == CAUSA_CAMBIO_CABLE_DANO
    assert not c.protegido


def test_migracion_de_sitio_termina_en_botella_ajena_a_los_tramos():
    residual = ResumenCamino(
        inicio=_pelo(1), fin=_pelo(2), cables=(7,), botellas=(10, 99), botella_inicio=10, botella_fin=99
    )
    assert clasificar_residual(residual, [TRAMO]).causa == CAUSA_MIGRACION_SITIO


def test_sin_tramos_no_hay_migracion_ni_paralelo():
    residual = ResumenCamino(
        inicio=_pelo(1), fin=_pelo(2), cables=(7,), botellas=(10, 99), botella_inicio=10, botella_fin=99
    )
    assert clasificar_residual(residual, []).causa == CAUSA_SIN_CLASIFICAR


def test_desuso_no_aplica_si_el_cable_lo_usa_un_tramo():
    """Un cable 'Sin Uso' que recorre un tramo está en uso: el dato de Cromo está mal, no el pelo."""
    residual = ResumenCamino(inicio=_pelo(1), fin=_pelo(2), cables=(1,))
    c = clasificar_residual(residual, [TRAMO], cables_sin_uso=frozenset({1}))
    assert c.causa == CAUSA_PELO_DANADO


def test_desuso_sin_cables_resueltos_no_aplica():
    residual = ResumenCamino(inicio=_pelo(1), fin=_pelo(2), cables=())
    assert clasificar_residual(residual, [TRAMO], cables_sin_uso=frozenset({1})).causa == CAUSA_SIN_CLASIFICAR


@pytest.mark.parametrize("clase", [69, 86, None])
def test_extremo_en_odf_protege_aunque_la_causa_sea_desuso(clase):
    residual = ResumenCamino(inicio=_pelo(1), fin=_odf(700, clase), odfs=(700,), cables=(9,))
    c = clasificar_residual(residual, [TRAMO], cables_sin_uso=frozenset({9}))
    assert c.causa == CAUSA_CABLE_DESUSO
    assert c.protegido
    assert c.evidencia()["protegido"] is True
    assert not es_normalizable(c.causa, c.protegido)


def test_toca_odf_confirmada_protege():
    residual = ResumenCamino(inicio=_pelo(1), fin=_pelo(2), odfs=(800,), cables=(9,))
    c = clasificar_residual(
        residual, [TRAMO], odfs_confirmadas=frozenset({800}), cables_sin_uso=frozenset({9})
    )
    assert c.protegido
    assert c.evidencia()["motivo_proteccion"] == "toca una ODF confirmada"


def test_solo_cable_desuso_es_normalizable():
    assert es_normalizable(CAUSA_CABLE_DESUSO, False)
    for causa in (CAUSA_PELO_DANADO, CAUSA_CAMBIO_CABLE_DANO, CAUSA_MIGRACION_SITIO, CAUSA_SIN_CLASIFICAR):
        assert not es_normalizable(causa, False)


# ── Consolidación por pelo (ronda de fixes 1) ─────────────────────────────────────────────────


def _residual(semilla: int, pelos: set[int], resumen: ResumenCamino) -> TrackingGenerado:
    return TrackingGenerado(
        pelo_n_id=semilla,
        nombre_archivo="",
        contenido="",
        desde_cache=True,
        generado_at=AHORA,
        duracion_ms=None,
        pelos_camino=frozenset(pelos),
        extremos=resumen,
    )


PROTEGIDO_A = ResumenCamino(inicio=_pelo(1), fin=_odf(700, 86), odfs=(700,), cables=(9,))
DESUSO_B = ResumenCamino(inicio=_pelo(1), fin=_pelo(2), cables=(9,))


@pytest.mark.parametrize("orden", ["protegido_primero", "desuso_primero"])
def test_pelo_en_residual_protegido_y_en_otro_queda_protegido_en_cualquier_orden(orden):
    from core.services.cromo.auditoria_huerfanos import consolidar_por_pelo

    a = _residual(100, {1, 5}, PROTEGIDO_A)
    b = _residual(200, {1, 6}, DESUSO_B)
    residuales = [a, b] if orden == "protegido_primero" else [b, a]

    filas = consolidar_por_pelo(
        residuales, [TRAMO], semillas=frozenset({1, 5, 6}), cables_sin_uso=frozenset({9})
    )

    _semilla, causa, evidencia = filas[1]
    assert evidencia["protegido"] is True
    assert not es_normalizable(causa, evidencia["protegido"])
    assert evidencia["odfs"] == [700]
    assert {c["semilla"] for c in evidencia["caminos"]} == {100, 200}
    # El cable 9 lo recorre un residual protegido: el otro tampoco sale CABLE_DESUSO.
    assert filas[6][1] != CAUSA_CABLE_DESUSO
    assert filas[6][2]["senales"]["cables_en_residual_protegido"] == 1


def test_causas_distintas_por_pelo_gana_la_menos_normalizable():
    from core.services.cromo.auditoria_huerfanos import consolidar_por_pelo

    desuso = _residual(100, {1}, ResumenCamino(inicio=_pelo(1), fin=_pelo(2), cables=(9,)))
    danado = _residual(200, {1}, ResumenCamino(inicio=_pelo(1), fin=_pelo(2), cables=(1,)))
    for residuales in ([desuso, danado], [danado, desuso]):
        filas = consolidar_por_pelo(
            residuales, [TRAMO], semillas=frozenset({1}), cables_sin_uso=frozenset({9})
        )
        assert filas[1][1] == CAUSA_PELO_DANADO
        assert filas[1][2]["protegido"] is False


def test_consolidar_solo_pelos_del_servicio_y_fuera_de_tramos():
    from core.services.cromo.auditoria_huerfanos import consolidar_por_pelo

    r = _residual(100, {1, 2, 3}, DESUSO_B)
    filas = consolidar_por_pelo(
        [r], [TRAMO], semillas=frozenset({1, 2}), pelos_en_tramos=frozenset({2}),
        cables_sin_uso=frozenset({9}),
    )
    assert set(filas) == {1}
    assert filas[1][1] == CAUSA_CABLE_DESUSO and filas[1][2]["odfs"] == []
