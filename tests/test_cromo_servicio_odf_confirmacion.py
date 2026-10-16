# Nombre de archivo: test_cromo_servicio_odf_confirmacion.py
# Ubicación de archivo: tests/test_cromo_servicio_odf_confirmacion.py
# Descripción: Pruebas de servicio_odf_confirmacion (confirmar/desconfirmar/listar/declarar) con una sesión fake que registra el SQL

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.services.cromo import servicio_odf_confirmacion as svc
from core.services.cromo.verificador import ObjetoNoEncontrado

AHORA = datetime(2026, 10, 16, tzinfo=timezone.utc)


class _Resultado:
    def __init__(self, filas=(), rowcount=0, escalar=None):
        self._filas, self.rowcount, self._escalar = list(filas), rowcount, escalar

    def first(self):
        return self._filas[0] if self._filas else None

    def all(self):
        return self._filas

    def scalar_one_or_none(self):
        return self._escalar


class _Sesion:
    """Responde por fragmento del SQL y anota cada ejecución y los commits."""

    def __init__(self, *, odfs_existentes=(), versiones=None, vigentes=(), rowcount=1, esperados=None):
        self.odfs_existentes = set(odfs_existentes)
        self.versiones = dict(versiones or {})  # version_id -> n_id
        self.vigentes = list(vigentes)
        self.rowcount = rowcount
        self.esperados = esperados
        self.ejecuciones: list[tuple[str, dict]] = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.ejecuciones.append((sql, params or {}))
        if "FROM app.cromo_odfs" in sql and "SELECT n_id" in sql:
            ident = params["id"]
            n_id = ident if ident in self.odfs_existentes else self.versiones.get(ident)
            return _Resultado([(n_id,)] if n_id is not None else [])
        if "FROM app.servicio_odf_confirmada" in sql:
            return _Resultado(self.vigentes)
        if "SELECT trackings_esperados" in sql:
            return _Resultado(escalar=self.esperados)
        return _Resultado(rowcount=self.rowcount)

    async def commit(self):
        self.commits += 1

    def escrituras(self):
        return [e for e in self.ejecuciones if e[0].lstrip().startswith(("INSERT", "UPDATE"))]


def _fila(odf_n_id, rol="EXTREMO", version_id=None):
    return SimpleNamespace(
        odf_n_id=odf_n_id, rol=rol, confirmado_por="admin", confirmado_en=AHORA,
        odf_nombre=f"ODF {odf_n_id}", odf_tipo="ODF", odf_version_id=version_id,
    )


@pytest.mark.asyncio
async def test_confirmar_en_lote_inserta_con_upsert_y_devuelve_la_lista_vigente():
    sesion = _Sesion(odfs_existentes={1, 2}, vigentes=[_fila(1), _fila(2, "TRANSITO")])

    lista = await svc.confirmar(sesion, 7, [(1, "EXTREMO"), (2, "TRANSITO")], usuario="admin")

    escritas = sesion.escrituras()
    assert len(escritas) == 2
    assert all("ON CONFLICT (servicio_id, odf_n_id) WHERE vigente" in sql for sql, _ in escritas)
    assert escritas[1][1] == {"servicio_id": 7, "odf_n_id": 2, "rol": "TRANSITO", "usuario": "admin"}
    assert sesion.commits == 1
    assert [f["odf_n_id"] for f in lista] == [1, 2]


@pytest.mark.asyncio
async def test_confirmar_acepta_version_id_y_guarda_el_n_id():
    sesion = _Sesion(odfs_existentes={6646686}, versiones={9295436: 6646686}, vigentes=[_fila(6646686)])

    await svc.confirmar(sesion, 7, [(9295436, "TRANSITO")], usuario="admin")

    assert sesion.escrituras()[0][1]["odf_n_id"] == 6646686


@pytest.mark.asyncio
async def test_confirmar_odf_inexistente_no_escribe_nada():
    sesion = _Sesion(odfs_existentes={1})

    with pytest.raises(ObjetoNoEncontrado):
        await svc.confirmar(sesion, 7, [(1, "EXTREMO"), (99, "EXTREMO")], usuario="admin")

    assert sesion.escrituras() == [] and sesion.commits == 0


@pytest.mark.asyncio
async def test_confirmar_rol_invalido_levanta_valueerror_sin_consultar():
    sesion = _Sesion(odfs_existentes={1})

    with pytest.raises(ValueError):
        await svc.confirmar(sesion, 7, [(1, "OTRO")], usuario="admin")

    assert sesion.ejecuciones == []


@pytest.mark.asyncio
async def test_desconfirmar_marca_no_vigente_sin_borrar_y_informa_si_habia():
    sesion = _Sesion(rowcount=1)
    assert await svc.desconfirmar(sesion, 7, 1) is True
    sql, params = sesion.escrituras()[0]
    assert "SET vigente = false" in sql and "DELETE" not in sql
    assert params == {"servicio_id": 7, "odf_n_id": 1}

    assert await svc.desconfirmar(_Sesion(rowcount=0), 7, 1) is False


@pytest.mark.asyncio
async def test_declarar_trackings_esperados_valida_y_permite_limpiar():
    sesion = _Sesion()
    assert await svc.declarar_trackings_esperados(sesion, 7, 6) is True
    assert sesion.escrituras()[0][1] == {"servicio_id": 7, "cantidad": 6}

    assert await svc.declarar_trackings_esperados(sesion, 7, None) is True
    assert sesion.escrituras()[1][1] == {"servicio_id": 7, "cantidad": None}

    with pytest.raises(ValueError):
        await svc.declarar_trackings_esperados(sesion, 7, 0)
    assert await svc.declarar_trackings_esperados(_Sesion(rowcount=0), 99, 2) is False


@pytest.mark.asyncio
async def test_declaraciones_incluyen_n_id_y_version_id_y_los_esperados():
    sesion = _Sesion(vigentes=[_fila(6646686, "TRANSITO", version_id=9295436), _fila(5)], esperados=6)

    decl = await svc.declaraciones_del_servicio(sesion, 7)

    assert decl.odf_ids == frozenset({6646686, 9295436, 5})
    assert decl.trackings_esperados == 6
    assert [c["odf_n_id"] for c in decl.confirmadas] == [6646686, 5]


@pytest.mark.asyncio
async def test_declaraciones_sin_nada_es_como_hoy():
    decl = await svc.declaraciones_del_servicio(_Sesion(), 7)

    assert decl.odf_ids == frozenset() and decl.confirmadas == [] and decl.trackings_esperados is None
