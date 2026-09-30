# Nombre de archivo: test_servicios_fusion_prov_real_db.py
# Ubicación de archivo: tests/test_servicios_fusion_prov_real_db.py
# Descripción: Integración contra Postgres real de la fusión por cadena PROV y de la regla del ID operativo en ingerir_contexto_prov

"""Filas sintéticas (números 9999 7xx, fuera de lo que SLA/PROV asigna) que reproducen el par mutuo
real del backfill del 2026-09-30. Todo se borra al terminar; nunca toca datos reales de dev.

Cubre lo que los tests puros no pueden: FKs reales (pelos, sync, historial, tracking), la liberación
de `servicio_id`/`numero_primer_servicio` UNIQUE al borrar el perdedor, y el resolver de la API v1
contra el resultado.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.prov.ingesta import ingerir_contexto_prov
from core.services.servicio_traza import resolver_servicio_por_identificador
from core.services.servicios_fusion_prov import aplicar_plan, cargar_filas, planificar
from db.models.infra import Servicio
from db.session import SessionLocal, async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

_engine_test = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
_AsyncSessionLocalTest = async_sessionmaker(_engine_test, expire_on_commit=False)

VIEJO, NUEVO, ORIGINAL, BAJA = "9999701", "9999702", "9999700", "9999703"
_NUMEROS = [VIEJO, NUEVO, ORIGINAL, BAJA]
_PELO_FALSO_TRACKING = 999_999_701  # cromo_tracking_cache.pelo_n_id no tiene FK dura


def _borrar():
    with SessionLocal() as s:
        s.execute(text("DELETE FROM app.cromo_tracking_cache WHERE pelo_n_id = :p"), {"p": _PELO_FALSO_TRACKING})
        s.execute(text("DELETE FROM app.cromo_servicio_match WHERE servicio_numero = ANY(:n ::text[])"), {"n": _NUMEROS})
        s.execute(
            text(
                "DELETE FROM app.servicios WHERE servicio_id = ANY(:n ::varchar[]) "
                "OR numero_primer_servicio = ANY(:n ::varchar[])"
            ),
            {"n": _NUMEROS},
        )
        s.commit()


def _insertar_servicio(s, sid, primer, alias, cliente) -> int:
    return int(
        s.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, alias_ids, nombre_cliente, "
                "categoria, origen_datos, estado_servicio) "
                "VALUES (:sid, :primer, CAST(:alias AS varchar[]), :cliente, 0, 'MANUAL', 'Activo') RETURNING id"
            ),
            {"sid": sid, "primer": primer, "alias": alias, "cliente": cliente},
        ).scalar_one()
    )


def _cadena(s, pk):
    for orden, (numero, estado, vigente) in enumerate(
        [(NUEVO, "INSTALADO", True), (VIEJO, "DADO BAJA", False), (ORIGINAL, "DADO BAJA", False)]
    ):
        s.execute(
            text(
                "INSERT INTO app.servicios_historial_id (servicio_id, numero_id, orden, estado_comercial, es_vigente) "
                "VALUES (:pk, :n, :o, :e, :v)"
            ),
            {"pk": pk, "n": numero, "o": orden, "e": estado, "v": vigente},
        )


@pytest.fixture
def par_mutuo():
    """Fila vieja (con cliente, 2 pelos, sync) + fila nueva (placeholder sin cliente, 1 pelo, tracking)."""

    _borrar()
    with SessionLocal() as s:
        pelos = list(s.execute(text("SELECT n_id FROM app.cromo_pelos ORDER BY n_id LIMIT 3")).scalars())
        if len(pelos) < 3:
            pytest.skip("La base no tiene cromo_pelos")
        vieja = _insertar_servicio(s, VIEJO, ORIGINAL, [NUEVO], "CLIENTE FUSION TEST")
        nueva = _insertar_servicio(s, NUEVO, NUEVO, [VIEJO], None)
        _cadena(s, vieja)
        _cadena(s, nueva)
        for pelo, pk, numero in ((pelos[0], vieja, VIEJO), (pelos[1], vieja, ORIGINAL), (pelos[2], nueva, NUEVO)):
            s.execute(
                text(
                    "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo) "
                    "VALUES (:p, :n, :s, 'test')"
                ),
                {"p": pelo, "n": numero, "s": pk},
            )
        s.execute(text("INSERT INTO app.servicios_sync_prov (servicio_id, ultima_sincronizacion_ok) VALUES (:s, now())"), {"s": vieja})
        s.execute(
            text(
                "INSERT INTO app.cromo_tracking_cache (pelo_n_id, servicio_id, nombre_archivo, contenido) "
                "VALUES (:p, :s, 'x.txt', 'Empalme 1: X')"
            ),
            {"p": _PELO_FALSO_TRACKING, "s": nueva},
        )
        s.commit()
    try:
        yield vieja, nueva
    finally:
        _borrar()


def _resolver(ident: str):
    async def _run():
        async with _AsyncSessionLocalTest() as s:
            return await resolver_servicio_por_identificador(s, ident)

    return asyncio.run(_run())


def test_antes_de_fusionar_el_par_mutuo_no_da_404_en_la_api(par_mutuo) -> None:
    """Bug real (2026-09-30): la regla anti-ambigüedad descartaba las dos filas de un par mutuo y el
    servicio daba 404. Ahora cada ID resuelve a la fila que lo tiene como `servicio_id`."""

    vieja, nueva = par_mutuo
    assert _resolver(NUEVO).servicio.id == nueva
    assert _resolver(VIEJO).servicio.id == vieja


def test_fusion_deja_una_fila_con_el_id_instalado_y_todos_los_pelos(par_mutuo) -> None:
    vieja, nueva = par_mutuo
    with SessionLocal() as s:
        plan = planificar(list(cargar_filas(s, [vieja, nueva]).values()))
        assert plan.motivo_salteo is None
        assert plan.sobreviviente.id == vieja
        movidos = aplicar_plan(s, plan)
        s.commit()

        fila = s.execute(
            text("SELECT servicio_id, numero_linea, numero_primer_servicio, alias_ids, nombre_cliente FROM app.servicios WHERE id = :id"),
            {"id": vieja},
        ).one()
        assert fila.servicio_id == NUEVO
        assert fila.numero_linea == NUEVO
        assert fila.numero_primer_servicio == ORIGINAL
        assert set(fila.alias_ids) == {VIEJO, ORIGINAL}
        assert fila.nombre_cliente == "CLIENTE FUSION TEST"
        assert s.execute(text("SELECT count(*) FROM app.servicios WHERE id = :id"), {"id": nueva}).scalar_one() == 0
        assert movidos["matches"] == 1
        assert s.execute(text("SELECT count(*) FROM app.cromo_servicio_match WHERE servicio_id = :id"), {"id": vieja}).scalar_one() == 3
        assert s.execute(text("SELECT servicio_id FROM app.cromo_tracking_cache WHERE pelo_n_id = :p"), {"p": _PELO_FALSO_TRACKING}).scalar_one() == vieja
        assert s.execute(text("SELECT count(*) FROM app.servicios_sync_prov WHERE servicio_id = :id"), {"id": vieja}).scalar_one() == 1
        assert s.execute(text("SELECT count(*) FROM app.servicios_historial_id WHERE servicio_id = :id"), {"id": vieja}).scalar_one() == 3

    for ident in (NUEVO, VIEJO, ORIGINAL):
        r = _resolver(ident)
        assert r is not None and r.servicio.id == vieja, ident
        assert r.es_id_vigente is (ident == NUEVO)


def test_ingesta_prov_usa_el_instalado_aunque_el_vigente_sea_pendiente() -> None:
    """Regla nueva en ingerir_contexto_prov: un upgrade PENDIENTE CPS no desplaza al INSTALADO."""

    _borrar()
    with SessionLocal() as s:
        pk = _insertar_servicio(s, ORIGINAL, ORIGINAL, [], "CLIENTE PENDIENTE TEST")
        s.commit()
    contexto = {
        "id_servicio": "EWS",
        "nro_servicio": BAJA,  # el número más alto: el upgrade pendiente
        "nro_servicio_original": ORIGINAL,
        "estado_comercial": "PENDIENTE CPS",
        "Descripcion": "CLIENTE PENDIENTE TEST",
        "cadena_upgrade": [
            {"nro_servicio": BAJA, "estado_comercial": "PENDIENTE CPS", "es_vigente": True},
            {"nro_servicio": VIEJO, "estado_comercial": "INSTALADO", "es_vigente": False},
            {"nro_servicio": ORIGINAL, "estado_comercial": "DADO BAJA", "es_vigente": False},
        ],
    }
    try:

        async def _run():
            async with _AsyncSessionLocalTest() as s:
                servicio = (await s.execute(select(Servicio).where(Servicio.id == pk))).scalars().one()
                await ingerir_contexto_prov(s, servicio, contexto)
                await s.commit()

        asyncio.run(_run())
        with SessionLocal() as s:
            fila = s.execute(text("SELECT servicio_id, numero_linea, alias_ids FROM app.servicios WHERE id = :id"), {"id": pk}).one()
        assert fila.servicio_id == VIEJO
        assert fila.numero_linea == VIEJO
        assert {BAJA, ORIGINAL} <= set(fila.alias_ids)
        assert VIEJO not in fila.alias_ids
    finally:
        _borrar()


def test_match_de_la_ingesta_cromo_resuelve_el_par_mutuo(par_mutuo) -> None:
    """`_SQL_BUSCAR_SERVICIO` tenía la misma regla: en un par mutuo no encontraba ninguna fila, y
    los pelos nuevos de ese servicio quedaban sin matchear en la próxima ingesta."""

    from core.services.cromo.ingesta import _SQL_BUSCAR_SERVICIO

    vieja, nueva = par_mutuo
    with SessionLocal() as s:
        assert s.execute(_SQL_BUSCAR_SERVICIO, {"numero": NUEVO}).scalar() == nueva
        assert s.execute(_SQL_BUSCAR_SERVICIO, {"numero": VIEJO}).scalar() == vieja


def test_realinea_una_fila_suelta_que_quedo_con_el_pendiente() -> None:
    """Caso real (fila 737 de dev): 120393 PENDIENTE CPS quedó como ID; el INSTALADO es 112763."""

    from core.services.servicios_fusion_prov import cargar_desalineadas, realinear

    _borrar()
    with SessionLocal() as s:
        pk = _insertar_servicio(s, BAJA, ORIGINAL, [VIEJO], "CLIENTE REALINEAR TEST")
        for orden, (numero, estado, vigente) in enumerate(
            [(BAJA, "PENDIENTE CPS", True), (VIEJO, "INSTALADO", False), (ORIGINAL, "DADO BAJA", False)]
        ):
            s.execute(
                text(
                    "INSERT INTO app.servicios_historial_id (servicio_id, numero_id, orden, estado_comercial, es_vigente) "
                    "VALUES (:pk, :n, :o, :e, :v)"
                ),
                {"pk": pk, "n": numero, "o": orden, "e": estado, "v": vigente},
            )
        s.commit()
    try:
        with SessionLocal() as s:
            candidatas = [r for r in cargar_desalineadas(s) if r.id == pk]
            assert [(r.servicio_id_antes, r.operativo) for r in candidatas] == [(BAJA, VIEJO)]
            realinear(s, candidatas[0])
            s.commit()
            fila = s.execute(text("SELECT servicio_id, numero_linea, alias_ids FROM app.servicios WHERE id = :id"), {"id": pk}).one()
            assert (fila.servicio_id, fila.numero_linea) == (VIEJO, VIEJO)
            assert set(fila.alias_ids) == {BAJA}
            assert not [r for r in cargar_desalineadas(s) if r.id == pk], "una segunda pasada no vuelve a tocarla"
        r = _resolver(BAJA)
        assert r.servicio.id == pk and r.servicio.servicio_id == VIEJO and r.es_id_vigente is False
    finally:
        _borrar()
