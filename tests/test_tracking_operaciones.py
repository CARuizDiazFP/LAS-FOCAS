# Nombre de archivo: test_tracking_operaciones.py
# Ubicación de archivo: tests/test_tracking_operaciones.py
# Descripción: Tests de core/services/tracking_operaciones (upload, análisis y descarga de tracking, P12 Task 10)

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.services import tracking_operaciones as ops
from core.services.infra_service import AnalysisResult, AnalysisStatus, UpgradeInfo


class SesionDoble:
    """Sesión mínima: registra commit/rollback y devuelve `primero` en `query().filter().first()`."""

    def __init__(self, primero=None):
        self.primero = primero
        self.llamadas: list[str] = []

    def query(self, *_):
        return self

    def filter(self, *_):
        return self

    def first(self):
        return self.primero

    def add(self, _):
        self.llamadas.append("add")

    def flush(self):
        self.llamadas.append("flush")

    def commit(self):
        self.llamadas.append("commit")

    def rollback(self):
        self.llamadas.append("rollback")


def test_decodificar_utf8_y_latin1():
    assert ops.decodificar_tracking("áé".encode("utf-8")) == "áé"
    assert ops.decodificar_tracking(b"\xe1") == "á"


def test_tope_de_tracking_es_5_mb():
    assert ops.MAX_TRACKING_MB == 5


def test_procesar_sin_servicio_id_no_escribe():
    sesion = SesionDoble()
    with pytest.raises(ops.TrackingSinServicioId):
        ops.procesar_tracking_legacy(sesion, "Empalme 1: Algun lugar", "sin_id.txt")
    assert sesion.llamadas == []


def test_procesar_sin_ubicaciones_no_escribe():
    sesion = SesionDoble()
    with pytest.raises(ops.TrackingSinUbicaciones):
        ops.procesar_tracking_legacy(sesion, "nada util", "FO 111995 C2.txt")
    assert sesion.llamadas == []


def test_procesar_cuenta_matches_y_hace_commit(monkeypatch):
    monkeypatch.setattr(ops, "parse_tracking", lambda raw, nombre: SimpleNamespace(
        servicio_id="111995",
        get_topologia=lambda: [("1", "Cam A"), ("2", "Cam B")],
        to_dict=lambda: {"ok": True},
    ))
    monkeypatch.setattr(
        ops, "_resolve_camara_o_registrar_sin_match",
        lambda session, ubicacion, **_: object() if ubicacion == "Cam A" else None,
    )
    monkeypatch.setattr(
        ops, "_get_or_create_empalme",
        lambda session, tracking_id, camara: (SimpleNamespace(servicios=[], camara_id=None), True),
    )
    sesion = SesionDoble()
    res = ops.procesar_tracking_legacy(sesion, "x", "FO 111995.txt")
    assert (res.servicio_id, res.camaras_existentes, res.ubicaciones_sin_match, res.empalmes_registrados) == (
        "111995", 1, 1, 2,
    )
    assert sesion.llamadas[-1] == "commit"


def test_procesar_hace_rollback_si_falla(monkeypatch):
    monkeypatch.setattr(ops, "parse_tracking", lambda raw, nombre: SimpleNamespace(
        servicio_id="1", get_topologia=lambda: [("1", "X")], to_dict=lambda: {},
    ))

    def _roto(*_, **__):
        raise RuntimeError("falla")

    monkeypatch.setattr(ops, "_resolve_camara_o_registrar_sin_match", _roto)
    sesion = SesionDoble()
    with pytest.raises(RuntimeError):
        ops.procesar_tracking_legacy(sesion, "x", "FO 1.txt")
    assert "rollback" in sesion.llamadas and "commit" not in sesion.llamadas


def test_serializar_analisis_une_claves_de_panel_y_api():
    upgrade = UpgradeInfo(
        old_service_id="1", old_service_db_id=2, new_service_id="3", match_reason="x",
        terminal_a_odf="O-1-15",
    )
    res = AnalysisResult(
        status=AnalysisStatus.POTENTIAL_UPGRADE, parsed_empalmes_count=4, upgrade_info=upgrade,
        cantidad_pelos=2, alias_id="9",
    )
    datos = ops.serializar_analisis(res)
    assert datos["suggested_action"] == "CONFIRM_UPGRADE"
    assert datos["hash_match"] is False and datos["empalmes_nuevos"] == 4
    assert datos["cantidad_pelos"] == 2 and datos["alias_id"] == "9"
    assert datos["upgrade_info"]["terminal_a_odf"] == "O-1-15"


@pytest.mark.parametrize(
    ("estado", "accion"),
    [("NEW", "CREATE_NEW"), ("IDENTICAL", "SKIP"), ("CONFLICT", "REPLACE"), ("ERROR", None)],
)
def test_serializar_analisis_accion_sugerida(estado, accion):
    assert ops.serializar_analisis(AnalysisResult(status=AnalysisStatus(estado)))["suggested_action"] == accion


def test_original_ruta_inexistente_devuelve_none():
    assert ops.obtener_tracking_original(SesionDoble(None), 7) is None


def test_original_sin_contenido_levanta():
    ruta = SimpleNamespace(raw_file_content=None, nombre_archivo_origen=None)
    with pytest.raises(ops.TrackingOriginalNoDisponible):
        ops.obtener_tracking_original(SesionDoble(ruta), 7)


def test_original_con_y_sin_nombre():
    ruta = SimpleNamespace(raw_file_content="abc", nombre_archivo_origen=None)
    assert ops.obtener_tracking_original(SesionDoble(ruta), 7) == ops.TrackingOriginal("tracking_ruta_7.txt", "abc")
    ruta.nombre_archivo_origen = "FO 1.txt"
    assert ops.obtener_tracking_original(SesionDoble(ruta), 7).filename == "FO 1.txt"


# --- Resolución (Task 11) ---------------------------------------------------------------------------

def test_parsear_accion_resolve():
    from core.services.infra_service import ResolveAction

    assert ops.parsear_accion_resolve("confirm_upgrade") is ResolveAction.CONFIRM_UPGRADE
    assert ops.parsear_accion_resolve("Create_New") is ResolveAction.CREATE_NEW
    assert ops.parsear_accion_resolve("skip") is None
    with pytest.raises(ops.AccionResolveInvalida):
        ops.parsear_accion_resolve("NO_EXISTE")


def test_parsear_ruta_tipo():
    from db.models.infra import RutaTipo

    assert ops.parsear_ruta_tipo(None) is RutaTipo.ALTERNATIVA
    assert ops.parsear_ruta_tipo("") is RutaTipo.ALTERNATIVA
    assert ops.parsear_ruta_tipo("backup") is RutaTipo.BACKUP
    with pytest.raises(ops.RutaTipoInvalido):
        ops.parsear_ruta_tipo("x")


def test_serializar_resolucion_claves_del_panel():
    from core.services.infra_service import ResolveAction, ResolveResult

    datos = ops.serializar_resolucion(
        ResolveResult(success=False, action=ResolveAction.REPLACE, servicio_id="1", error="e", message="m")
    )
    assert set(datos) == {
        "success", "action", "servicio_id", "servicio_db_id", "ruta_id", "ruta_nombre", "camaras_nuevas",
        "camaras_existentes", "empalmes_creados", "empalmes_asociados", "ubicaciones_sin_match", "message",
        "error",
    }
    assert datos["action"] == "REPLACE" and datos["success"] is False and datos["error"] == "e"
