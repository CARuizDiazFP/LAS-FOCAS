# Nombre de archivo: test_cromo_direccion_comparacion.py
# Ubicación de archivo: tests/test_cromo_direccion_comparacion.py
# Descripción: Tests unitarios para la señal de comparación dirección PROV vs. ODF Cromo (sin DB)

"""Tests para core.services.cromo.direccion_comparacion.comparar_direccion_prov_vs_odf().

Los 7 casos son los exactos del brief de la Task 2 (plan
`tambiem-validemos-domicilios-extraidos-robust-swing`): cubren coincidencia exacta, altura
distinta con misma calle, inversión apellido/nombre (intersección de tokens, no substring),
inputs faltantes de cada lado, cero tokens en común con altura también distinta, y altura con
ceros a la izquierda.
"""

from __future__ import annotations

from core.services.cromo.direccion_comparacion import (
    SenalDireccion,
    comparar_direccion_prov_vs_odf,
)


def test_altura_distinta_misma_calle_no_coincide() -> None:
    resultado = comparar_direccion_prov_vs_odf(
        "AV. Bartolome Mitre 900 P.19", "AVENIDA BARTOLOME MITRE", "2525"
    )
    assert resultado == SenalDireccion.NO_COINCIDE


def test_calle_y_altura_coinciden() -> None:
    resultado = comparar_direccion_prov_vs_odf(
        "AV. Bartolome Mitre 2525 P.19", "AVENIDA BARTOLOME MITRE", "2525"
    )
    assert resultado == SenalDireccion.COINCIDE


def test_apellido_nombre_invertido_coincide_por_interseccion_de_tokens() -> None:
    resultado = comparar_direccion_prov_vs_odf(
        "PERON, JUAN DOMINGO, TTE. GENERAL 650 P.5", "TTE GRAL JUAN D PERON", "650"
    )
    assert resultado == SenalDireccion.COINCIDE


def test_direccion_prov_none_no_se_pudo_comparar() -> None:
    resultado = comparar_direccion_prov_vs_odf(None, "AVENIDA BARTOLOME MITRE", "2525")
    assert resultado == SenalDireccion.NO_SE_PUDO_COMPARAR


def test_odf_sin_calle_ni_altura_no_se_pudo_comparar() -> None:
    resultado = comparar_direccion_prov_vs_odf("Bartolome Mitre 900", None, None)
    assert resultado == SenalDireccion.NO_SE_PUDO_COMPARAR


def test_cero_tokens_en_comun_y_altura_distinta_no_coincide() -> None:
    resultado = comparar_direccion_prov_vs_odf(
        "Calle Falsa 123", "AVENIDA BARTOLOME MITRE", "2525"
    )
    assert resultado == SenalDireccion.NO_COINCIDE


def test_altura_con_ceros_a_la_izquierda_coincide() -> None:
    resultado = comparar_direccion_prov_vs_odf(
        "Bartolome Mitre 0650", "BARTOLOME MITRE", "650"
    )
    assert resultado == SenalDireccion.COINCIDE
