# Nombre de archivo: test_baneo_operaciones.py
# Ubicación de archivo: tests/test_baneo_operaciones.py
# Descripción: Pruebas unitarias de core/services/baneo_operaciones (commit/rollback, aviso Slack y activos) con dobles

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.services import baneo_operaciones as ops
from db.models.infra import CamaraEstado


class _Sesion:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _resultado(success: bool):
    return SimpleNamespace(success=success, to_dict=lambda: {"success": success, "incidente_id": 5})


@pytest.fixture
def avisos(monkeypatch):
    llamadas: list[tuple[str, dict, str]] = []
    monkeypatch.setattr(ops, "get_settings", lambda: SimpleNamespace(slack=SimpleNamespace(bot_token="tok")))
    return llamadas


def _notificador(llamadas):
    return lambda s, tipo, datos, token: llamadas.append((tipo, datos, token))


def _crear(sesion, notificar):
    return ops.crear_baneo_y_notificar(
        sesion, ticket_asociado="T1", servicio_afectado_id="A", servicio_protegido_id="P",
        ruta_protegida_id=3, motivo="m", usuario_ejecutor="ana", notificar=notificar,
    )


def test_crear_exito_commit_y_slack(monkeypatch, avisos):
    monkeypatch.setattr(ops, "create_ban", lambda *a, **k: _resultado(True))
    sesion = _Sesion()
    assert _crear(sesion, _notificador(avisos)).success is True
    assert sesion.committed and not sesion.rolled_back
    tipo, datos, token = avisos[0]
    assert (tipo, token) == ("create", "tok")
    assert datos["servicio_afectado_id"] == "A" and datos["servicio_protegido_id"] == "P"
    assert datos["ticket_asociado"] == "T1" and datos["usuario_ejecutor"] == "ana" and datos["motivo"] == "m"


def test_crear_falla_rollback_sin_slack(monkeypatch, avisos):
    monkeypatch.setattr(ops, "create_ban", lambda *a, **k: _resultado(False))
    sesion = _Sesion()
    assert _crear(sesion, _notificador(avisos)).success is False
    assert sesion.rolled_back and not sesion.committed
    assert avisos == []


def test_crear_error_de_slack_no_cambia_respuesta(monkeypatch):
    monkeypatch.setattr(ops, "create_ban", lambda *a, **k: _resultado(True))
    monkeypatch.setattr(ops, "get_settings", lambda: SimpleNamespace(slack=SimpleNamespace(bot_token="t")))

    def _falla(*a):
        raise RuntimeError("slack caído")

    sesion = _Sesion()
    assert _crear(sesion, _falla).success is True
    assert sesion.committed


def test_levantar_exito_commit_y_slack(monkeypatch, avisos):
    monkeypatch.setattr(ops, "lift_ban", lambda *a, **k: _resultado(True))
    sesion = _Sesion()
    res = ops.levantar_baneo_y_notificar(
        sesion, 5, usuario_ejecutor="ana", motivo_cierre="ok", notificar=_notificador(avisos)
    )
    assert res.success is True and sesion.committed and not sesion.rolled_back
    tipo, datos, _ = avisos[0]
    assert tipo == "lift" and datos["usuario_ejecutor"] == "ana" and datos["motivo_cierre"] == "ok"


def test_levantar_falla_rollback_sin_slack(monkeypatch, avisos):
    monkeypatch.setattr(ops, "lift_ban", lambda *a, **k: _resultado(False))
    sesion = _Sesion()
    ops.levantar_baneo_y_notificar(
        sesion, 5, usuario_ejecutor=None, motivo_cierre=None, notificar=_notificador(avisos)
    )
    assert sesion.rolled_back and not sesion.committed and avisos == []


def test_levantar_error_de_slack_no_cambia_respuesta(monkeypatch):
    monkeypatch.setattr(ops, "lift_ban", lambda *a, **k: _resultado(True))
    monkeypatch.setattr(ops, "get_settings", lambda: (_ for _ in ()).throw(RuntimeError("sin config")))
    sesion = _Sesion()
    assert ops.levantar_baneo_y_notificar(
        sesion, 5, usuario_ejecutor=None, motivo_cierre=None, notificar=lambda *a: None
    ).success is True
    assert sesion.committed


def test_listar_activos_redondea(monkeypatch):
    inicio = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    inc = SimpleNamespace(
        id=9, ticket_asociado="T", servicio_afectado_id="A", servicio_protegido_id="P",
        ruta_protegida_id=None, usuario_ejecutor="ana", motivo="m", fecha_inicio=inicio, activo=True,
        duracion_horas=2.26,
    )
    sin_inicio = SimpleNamespace(
        id=10, ticket_asociado=None, servicio_afectado_id="A", servicio_protegido_id="Q",
        ruta_protegida_id=4, usuario_ejecutor=None, motivo=None, fecha_inicio=None, activo=True,
        duracion_horas=None,
    )
    camaras = [SimpleNamespace(estado=CamaraEstado.BANEADA), SimpleNamespace(estado=CamaraEstado.LIBRE)]

    class _Svc:
        def __init__(self, session):
            pass

        def get_camaras_for_servicio(self, servicio_id, ruta_id):
            return camaras if servicio_id == "P" else []

    class _Query:
        def filter(self, *a):
            return self

        def count(self):
            return 7

    sesion = SimpleNamespace(query=lambda *a: _Query())
    monkeypatch.setattr(ops, "get_incidentes_activos", lambda s: [inc, sin_inicio])
    monkeypatch.setattr(ops, "ProtectionService", _Svc)

    res = ops.listar_incidentes_activos(sesion)
    assert set(res) == {"status", "incidentes", "total", "total_camaras_baneadas"}
    assert (res["status"], res["total"], res["total_camaras_baneadas"]) == ("ok", 2, 7)
    primero, segundo = res["incidentes"]
    assert set(primero) == {
        "id", "ticket_asociado", "servicio_afectado_id", "servicio_protegido_id", "ruta_protegida_id",
        "usuario_ejecutor", "motivo", "fecha_inicio", "activo", "duracion_horas", "camaras_count",
        "camaras_baneadas_count",
    }
    assert primero["duracion_horas"] == 2.3
    assert primero["fecha_inicio"] == inicio.isoformat()
    assert (primero["camaras_count"], primero["camaras_baneadas_count"]) == (2, 1)
    assert segundo["duracion_horas"] is None and segundo["fecha_inicio"] is None
    assert (segundo["camaras_count"], segundo["camaras_baneadas_count"]) == (0, 0)
