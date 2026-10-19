# Nombre de archivo: test_cromo_servicio_odf_override_unit.py
# Ubicación de archivo: tests/test_cromo_servicio_odf_override_unit.py
# Descripción: Pruebas unitarias de crear_override con sesión fake (origen, propuesta_id y confirmar), sin Postgres

"""Complemento sin base de datos de `test_cromo_servicio_odf_override_service.py`.

Ese archivo es de integración real (`requiere_postgres_real` a nivel de módulo) y se saltea sin
Postgres. Estas pruebas cubren la rama `confirmar=False` (flush sin commit, para que el árbitro
la use dentro de su propia transacción) con una sesión fake que registra las llamadas.
"""

from __future__ import annotations

import pytest

from core.services.cromo.servicio_odf_override_service import crear_override


class _ResultadoFake:
    def __init__(self, fila):
        self._fila = fila

    def first(self):
        return self._fila


class _SesionFake:
    """Registra los métodos de transacción llamados y asigna `id` al hacer flush, como Postgres."""

    def __init__(self):
        self.llamadas: list[str] = []
        self.agregados: list = []

    async def execute(self, sql, params=None):
        self.llamadas.append("execute")
        return _ResultadoFake((1,))

    def add(self, obj):
        self.llamadas.append("add")
        self.agregados.append(obj)

    async def flush(self):
        self.llamadas.append("flush")
        for obj in self.agregados:
            if obj.id is None:
                obj.id = 100 + len(self.agregados)

    async def commit(self):
        self.llamadas.append("commit")

    async def refresh(self, obj):
        self.llamadas.append("refresh")


@pytest.mark.asyncio
async def test_crear_override_auto_sin_commit():
    sesion = _SesionFake()

    override = await crear_override(
        sesion,
        servicio_id=1,
        odf_n_id=999_950_001,
        categoria_causa="ODF_INCORRECTA",
        usuario="arbitro",
        origen="AUTO",
        propuesta_id=7,
        confirmar=False,
    )

    assert "flush" in sesion.llamadas
    assert "commit" not in sesion.llamadas
    assert "refresh" not in sesion.llamadas
    assert override.id is not None
    assert override.origen == "AUTO"
    assert override.propuesta_id == 7


@pytest.mark.asyncio
async def test_crear_override_default_manual_con_commit():
    sesion = _SesionFake()

    override = await crear_override(
        sesion,
        servicio_id=1,
        odf_n_id=999_950_001,
        categoria_causa="ODF_INCORRECTA",
        usuario="operador",
    )

    assert sesion.llamadas[-2:] == ["commit", "refresh"]
    assert "flush" not in sesion.llamadas
    assert override.origen == "MANUAL"
    assert override.propuesta_id is None
