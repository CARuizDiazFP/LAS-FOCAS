# Nombre de archivo: test_prov_frescura.py
# Ubicación de archivo: tests/test_prov_frescura.py
# Descripción: Tests de horas_frescura (puro, sin DB) y de la consulta batch servicios_vencidos/servicios_vencidos_sync contra Postgres real

"""Dos bloques bien separados, a propósito:

1. `horas_frescura()` es pura (sólo lee una variable de entorno) — corre siempre, sin guard, mismo
   espíritu que `tests/test_cromo_tracking_cache.py` para `ttl_horas()`.
2. `servicios_vencidos`/`servicios_vencidos_sync` son consultas reales contra
   `app.servicios_sync_prov` (migración `20260923_02`) — necesitan Postgres real para ejercitar el
   `LEFT JOIN`/`unnest(:ids ::integer[])` de verdad, así que sólo esos tests llevan
   `@requiere_postgres_real` (no `pytestmark` de archivo: no tiene sentido saltear los tests puros
   de arriba sólo porque no hay Postgres a mano).

Namespace de IDs sintéticos reservado: `"900201"`-`"900206"` (números de servicio de 6 dígitos,
mismo largo/criterio que `tests/test_servicios_prov_routes.py`, que ya reserva `"9001xx"` — confirmado
el 2026-09-24 contra `lasfocasdev-postgres` que no existe ninguna fila `"9002xx"` de 6 dígitos; la
única `"9002%"` real es `"90020"`, de 5).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.prov import frescura
from db.session import SessionLocal, async_engine
from tests.soporte_postgres_real import requiere_postgres_real

AHORA = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


# ── Parte 1: horas_frescura() — pura, sin DB ─────────────────────────────────


def test_horas_frescura_default_es_48(monkeypatch):
    monkeypatch.delenv("PROV_FRESCURA_HORAS", raising=False)
    assert frescura.horas_frescura() == pytest.approx(48.0)


def test_horas_frescura_ajustable_por_entorno(monkeypatch):
    monkeypatch.setenv("PROV_FRESCURA_HORAS", "12")
    assert frescura.horas_frescura() == pytest.approx(12.0)


@pytest.mark.parametrize("valor", ["", "   "])
def test_horas_frescura_vacio_cae_al_default(monkeypatch, valor):
    monkeypatch.setenv("PROV_FRESCURA_HORAS", valor)
    assert frescura.horas_frescura() == pytest.approx(48.0)


@pytest.mark.parametrize("valor", ["mucho", "0", "-5"])
def test_horas_frescura_invalido_no_rompe_y_cae_al_default(monkeypatch, valor):
    """Una variable de entorno mal puesta nunca debe tumbar el comando de Slack (Task 8)."""
    monkeypatch.setenv("PROV_FRESCURA_HORAS", valor)
    assert frescura.horas_frescura() == pytest.approx(48.0)


def test_ids_vacio_no_toca_la_db():
    """`_normalizar_ids` es lo único que corre con un conjunto vacío — ni `servicios_vencidos` ni su
    gemela ejecutan ninguna query en ese caso (ver el `if not ids: return set()` de ambas)."""
    assert frescura._normalizar_ids([]) == []


# ── Parte 2: servicios_vencidos / servicios_vencidos_sync — Postgres real ────

_NUMEROS_DE_TEST = ("900201", "900202", "900203", "900204", "900205", "900206")

# Motivo por el que este archivo no usa NullPool + engine propio como los `*_real_db.py` de Cromo:
# acá no hace falta abrir un TestClient/engine async de larga vida por archivo — cada test abre y
# cierra su propia sesión (sync vía `SessionLocal`, async vía este engine dedicado con `NullPool`,
# mismo motivo que esos archivos: evita reusar una conexión pooleada entre event loops distintos de
# tests async consecutivos).
_engine_test = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
AsyncSessionLocal = async_sessionmaker(_engine_test, expire_on_commit=False)


@pytest.fixture
def _limpiar_servicios_de_test():
    yield
    with SessionLocal() as session:
        # El `ON DELETE CASCADE` de `servicios_sync_prov.servicio_id` se encarga de esa tabla solo.
        session.execute(
            text("DELETE FROM app.servicios WHERE numero_primer_servicio = ANY(:numeros ::varchar[])"),
            {"numeros": list(_NUMEROS_DE_TEST)},
        )
        session.commit()


def _crear_servicio(numero: str) -> int:
    """Crea un Servicio de test mínimo y devuelve su PK entero (`app.servicios.id`) — la consulta de
    frescura trabaja sobre ese PK, no sobre el `servicio_id` string externo."""
    with SessionLocal() as session:
        pk = session.execute(
            text(
                "INSERT INTO app.servicios "
                "(servicio_id, numero_primer_servicio, numero_linea, estado_servicio, tipo_servicio, origen_datos) "
                "VALUES (:numero, :numero, :numero, 'DESCONOCIDO', 'EWS', 'MANUAL'::app.servicio_origen_datos) "
                "RETURNING id"
            ),
            {"numero": numero},
        ).scalar_one()
        session.commit()
        return int(pk)


def _insertar_sync_prov(servicio_pk: int, *, ultima_sincronizacion_ok: datetime) -> None:
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.servicios_sync_prov "
                "(servicio_id, ultima_sincronizacion_ok, ultimo_intento, nro_servicio_consultado, created_at, updated_at) "
                "VALUES (:servicio_id, :ok, :ok, 'test', :ok, :ok)"
            ),
            {"servicio_id": servicio_pk, "ok": ultima_sincronizacion_ok},
        )
        session.commit()


@requiere_postgres_real
@pytest.mark.asyncio
async def test_servicio_sin_fila_de_sync_esta_vencido(_limpiar_servicios_de_test):
    """El 92,5% real (servicios que nunca pasaron por PROV) cae acá: sin fila en
    `servicios_sync_prov`, el `LEFT JOIN` deja `ultima_sincronizacion_ok` en NULL -> vencido."""
    pk = _crear_servicio("900201")

    async with AsyncSessionLocal() as sesion:
        vencidos = await frescura.servicios_vencidos(sesion, [pk], ahora=AHORA)

    assert vencidos == {pk}


@requiere_postgres_real
@pytest.mark.asyncio
async def test_servicio_con_sincronizacion_reciente_no_esta_vencido(_limpiar_servicios_de_test):
    pk = _crear_servicio("900202")
    _insertar_sync_prov(pk, ultima_sincronizacion_ok=AHORA - timedelta(hours=1))

    async with AsyncSessionLocal() as sesion:
        vencidos = await frescura.servicios_vencidos(sesion, [pk], horas=48, ahora=AHORA)

    assert vencidos == set()


@requiere_postgres_real
@pytest.mark.asyncio
async def test_servicio_con_sincronizacion_vieja_esta_vencido(_limpiar_servicios_de_test):
    pk = _crear_servicio("900203")
    _insertar_sync_prov(pk, ultima_sincronizacion_ok=AHORA - timedelta(hours=100))

    async with AsyncSessionLocal() as sesion:
        vencidos = await frescura.servicios_vencidos(sesion, [pk], horas=48, ahora=AHORA)

    assert vencidos == {pk}


@requiere_postgres_real
@pytest.mark.asyncio
async def test_umbral_personalizado_horas_corre_el_corte(_limpiar_servicios_de_test):
    """Misma fila (sincronizada hace 2 h): con el umbral por defecto (48 h) está fresca, con un
    umbral de 1 h ya está vencida — el `horas=` explícito tiene que ganarle al default."""
    pk = _crear_servicio("900204")
    _insertar_sync_prov(pk, ultima_sincronizacion_ok=AHORA - timedelta(hours=2))

    async with AsyncSessionLocal() as sesion:
        con_default = await frescura.servicios_vencidos(sesion, [pk], horas=48, ahora=AHORA)
        con_umbral_corto = await frescura.servicios_vencidos(sesion, [pk], horas=1, ahora=AHORA)

    assert con_default == set()
    assert con_umbral_corto == {pk}


@requiere_postgres_real
@pytest.mark.asyncio
async def test_batch_devuelve_solo_el_subconjunto_pasado(_limpiar_servicios_de_test):
    """Un servicio vencido que NO está en la lista de ids consultados no debe aparecer en el
    resultado — la consulta nunca "sale a buscar" vencidos por su cuenta, sólo responde sobre el
    conjunto de entrada (ver el `unnest(:ids ::integer[])` del docstring de `frescura.py`)."""
    pk_vencido_incluido = _crear_servicio("900205")
    pk_vencido_no_incluido = _crear_servicio("900206")
    # Ninguno de los dos tiene fila en servicios_sync_prov -> ambos "vencidos" en términos
    # absolutos, pero sólo el primero está en la lista que se consulta.

    async with AsyncSessionLocal() as sesion:
        vencidos = await frescura.servicios_vencidos(sesion, [pk_vencido_incluido], ahora=AHORA)

    assert vencidos == {pk_vencido_incluido}
    assert pk_vencido_no_incluido not in vencidos


@requiere_postgres_real
@pytest.mark.asyncio
async def test_gemela_sync_devuelve_lo_mismo_que_la_async(_limpiar_servicios_de_test):
    """`servicios_vencidos_sync` es la gemela usada por el listener de Slack (Task 8), que corre en
    un callback síncrono de Slack Bolt — mismo resultado que la versión async para el mismo dato."""
    pk_fresco = _crear_servicio("900201")
    pk_vencido = _crear_servicio("900203")
    _insertar_sync_prov(pk_fresco, ultima_sincronizacion_ok=AHORA - timedelta(hours=1))
    _insertar_sync_prov(pk_vencido, ultima_sincronizacion_ok=AHORA - timedelta(hours=100))

    async with AsyncSessionLocal() as sesion:
        vencidos_async = await frescura.servicios_vencidos(sesion, [pk_fresco, pk_vencido], ahora=AHORA)

    with SessionLocal() as session:
        vencidos_sync = frescura.servicios_vencidos_sync(session, [pk_fresco, pk_vencido], ahora=AHORA)

    assert vencidos_async == vencidos_sync == {pk_vencido}
