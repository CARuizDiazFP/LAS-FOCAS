# Nombre de archivo: test_cromo_tracking_cache.py
# Ubicación de archivo: tests/test_cromo_tracking_cache.py
# Descripción: Pruebas de la lógica de frescura del caché de trackings y del upsert que no borra la atribución al Servicio — parte pura, sin base ni red

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.services.cromo import tracking_cache

AHORA = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


def test_entrada_recien_generada_esta_fresca():
    assert tracking_cache.esta_vencido(AHORA - timedelta(minutes=1), AHORA, 24) is False


def test_entrada_de_hace_23_horas_sigue_fresca():
    assert tracking_cache.esta_vencido(AHORA - timedelta(hours=23), AHORA, 24) is False


def test_entrada_de_hace_25_horas_esta_vencida():
    assert tracking_cache.esta_vencido(AHORA - timedelta(hours=25), AHORA, 24) is True


def test_el_borde_exacto_del_ttl_cuenta_como_vencido():
    """A las 24 h justas la entrada ya no se sirve.

    El criterio es `>=` y no `>` a propósito: ante la duda, regenerar contra Cromo es correcto y
    sólo cuesta tiempo, mientras que servir un tracking vencido entrega información equivocada.
    """
    assert tracking_cache.esta_vencido(AHORA - timedelta(hours=24), AHORA, 24) is True


def test_entrada_sin_fecha_se_trata_como_vencida():
    assert tracking_cache.esta_vencido(None, AHORA, 24) is True


def test_fecha_ingenua_se_interpreta_como_utc_y_no_revienta():
    """Una fecha sin tzinfo no puede tumbar la descarga con un TypeError.

    Postgres devuelve `timestamptz`, pero un objeto armado a mano (test, backfill, fixture) puede
    venir ingenuo; compararlo crudo contra un `ahora` con tz explota.
    """
    ingenua = (AHORA - timedelta(hours=1)).replace(tzinfo=None)
    assert tracking_cache.esta_vencido(ingenua, AHORA, 24) is False


def test_ttl_por_defecto_es_24_horas(monkeypatch):
    monkeypatch.delenv("CROMO_TRACKING_CACHE_TTL_HORAS", raising=False)
    assert tracking_cache.ttl_horas() == pytest.approx(24.0)


def test_ttl_se_puede_ajustar_por_entorno(monkeypatch):
    monkeypatch.setenv("CROMO_TRACKING_CACHE_TTL_HORAS", "0.5")
    assert tracking_cache.ttl_horas() == pytest.approx(0.5)


@pytest.mark.parametrize("valor", ["", "   "])
def test_ttl_vacio_cae_al_default(monkeypatch, valor):
    monkeypatch.setenv("CROMO_TRACKING_CACHE_TTL_HORAS", valor)
    assert tracking_cache.ttl_horas() == pytest.approx(24.0)


@pytest.mark.parametrize("valor", ["veinticuatro", "0", "-3"])
def test_ttl_invalido_no_rompe_la_descarga_y_cae_al_default(monkeypatch, valor):
    """Un caché mal configurado nunca debe impedir bajar el tracking."""
    monkeypatch.setenv("CROMO_TRACKING_CACHE_TTL_HORAS", valor)
    assert tracking_cache.ttl_horas() == pytest.approx(24.0)


class _SesionQueCompila:
    """Guarda el SQL que recibe, compilado para Postgres, sin ejecutar nada."""

    def __init__(self) -> None:
        self.sql: list[str] = []

    async def execute(self, sentencia, *_a, **_k):
        from sqlalchemy.dialects import postgresql

        self.sql.append(str(sentencia.compile(dialect=postgresql.dialect())))


@pytest.mark.asyncio
async def test_guardar_sin_servicio_no_borra_la_atribucion_de_la_fila():
    """Un pelo de una posición no declarada se cachea con `servicio_id=None`: el upsert conserva el
    servicio que ya tenía la fila (la traza del Servicio y la API v1 leen esa columna)."""
    sesion = _SesionQueCompila()

    await tracking_cache.guardar(
        sesion, pelo_n_id=7028863, servicio_id=None, nombre_archivo="x.txt", contenido="", ahora=AHORA
    )

    upsert = sesion.sql[0].lower()
    assert "on conflict (pelo_n_id) do update" in upsert
    assert "servicio_id = coalesce(excluded.servicio_id, app.cromo_tracking_cache.servicio_id)" in upsert


@pytest.mark.asyncio
async def test_obtener_tracking_pasa_servicio_none_al_cache(monkeypatch):
    from core.services.cromo import tracking_service
    from core.services.cromo.camino_optico_service import ESTADO_OK, CaminoOptico

    guardados: list = []

    async def _leer(_sesion, _pelo):
        return None

    async def _guardar(_sesion, **kw):
        guardados.append(kw["servicio_id"])

    async def _resolver(_cliente, _sesion, pelo_n_id):
        return CaminoOptico(estado=ESTADO_OK, pelo_n_id=pelo_n_id, servicio_at62="4649")

    class _Sesion:
        async def commit(self):
            return None

    monkeypatch.setattr(tracking_cache, "leer", _leer)
    monkeypatch.setattr(tracking_cache, "guardar", _guardar)
    monkeypatch.setattr(tracking_service, "resolver_camino_de_pelo", _resolver)

    tracking = await tracking_service.obtener_tracking(object(), _Sesion(), servicio_id=None, pelo_n_id=7028862)

    assert guardados == [None]
    assert tracking.pelo_n_id == 7028862
