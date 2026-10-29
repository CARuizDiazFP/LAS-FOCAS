# Nombre de archivo: test_tracking_operaciones.py
# Ubicación de archivo: tests/test_tracking_operaciones.py
# Descripción: Tests de core/services/tracking_operaciones (upload, análisis y descarga de tracking, P12 Task 10)

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.services import tracking_operaciones as ops
from core.services.infra_service import AnalysisResult, AnalysisStatus, ResolveAction, ResolveResult, UpgradeInfo


class SesionDoble:
    """Sesión mínima: registra commit/rollback y devuelve `primero` en `query().filter().first()`."""

    def __init__(self, primero=None):
        self.primero = primero
        self.llamadas: list[str] = []

    def query(self, *_):
        return self

    def filter(self, *_):
        return self

    def options(self, *_):
        return self

    def order_by(self, *criterios):
        self.orden = criterios
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


def _parse_valido(monkeypatch):
    monkeypatch.setattr(ops, "parse_tracking", lambda raw, nombre: SimpleNamespace(
        servicio_id="111995", get_topologia=lambda: [("1", "Cam A"), ("2", "Cam B")],
    ))


def _analisis(monkeypatch, estado):
    monkeypatch.setattr(ops, "analyze_tracking_file", lambda *_: AnalysisResult(status=estado, servicio_id="111995"))


def test_procesar_nuevo_crea_la_ruta_principal_con_create_new(monkeypatch):
    """P22: el upload directo termina en una ruta (antes asociaba sólo por la tabla legada)."""
    _parse_valido(monkeypatch)
    _analisis(monkeypatch, AnalysisStatus.NEW)
    pedidos = []

    def _resolver(session, accion, raw, nombre):
        pedidos.append(accion)
        return ResolveResult(
            success=True, action=accion, servicio_id="111995", ruta_id=7,
            camaras_existentes=1, ubicaciones_sin_match=1, empalmes_creados=2,
        )

    monkeypatch.setattr(ops, "resolve_tracking_file", _resolver)
    res = ops.procesar_tracking_legacy(SesionDoble(), "x", "FO 111995.txt")
    assert pedidos == [ResolveAction.CREATE_NEW]
    assert (res.servicio_id, res.camaras_existentes, res.ubicaciones_sin_match, res.empalmes_registrados) == (
        "111995", 1, 1, 2,
    )


def test_procesar_identico_no_escribe(monkeypatch):
    _parse_valido(monkeypatch)
    _analisis(monkeypatch, AnalysisStatus.IDENTICAL)
    monkeypatch.setattr(ops, "resolve_tracking_file", lambda *_: pytest.fail("no debe resolver"))
    res = ops.procesar_tracking_legacy(SesionDoble(), "x", "FO 111995.txt")
    assert (res.servicio_id, res.camaras_existentes, res.ubicaciones_sin_match, res.empalmes_registrados) == (
        "111995", 0, 0, 0,
    )


@pytest.mark.parametrize(
    "estado", [AnalysisStatus.CONFLICT, AnalysisStatus.POTENTIAL_UPGRADE, AnalysisStatus.NEW_STRAND]
)
def test_procesar_con_rutas_distintas_pide_resolucion_sin_escribir(monkeypatch, estado):
    _parse_valido(monkeypatch)
    _analisis(monkeypatch, estado)
    monkeypatch.setattr(ops, "resolve_tracking_file", lambda *_: pytest.fail("no debe resolver"))
    with pytest.raises(ops.TrackingRequiereResolucion) as err:
        ops.procesar_tracking_legacy(SesionDoble(), "x", "FO 111995.txt")
    assert (err.value.servicio_id, err.value.estado) == ("111995", estado.value)


def test_procesar_falla_de_resolve_levanta(monkeypatch):
    _parse_valido(monkeypatch)
    _analisis(monkeypatch, AnalysisStatus.NEW)
    monkeypatch.setattr(ops, "resolve_tracking_file", lambda session, accion, *_: ResolveResult(
        success=False, action=accion, error="Error interno (ref abcd)",
    ))
    with pytest.raises(RuntimeError, match="ref abcd"):
        ops.procesar_tracking_legacy(SesionDoble(), "x", "FO 111995.txt")


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


# --- Rutas de un servicio y limpieza de empalmes (Task 12) -----------------------------------------------

def test_buscar_servicio_por_numero_linea():
    """El criterio del panel (servicio_id OR numero_primer_servicio OR numero_linea) está en el filtro."""
    from sqlalchemy.dialects import postgresql

    capturado = []

    class Sesion(SesionDoble):
        def filter(self, *criterios):
            capturado.extend(criterios)
            return self

    servicio = SimpleNamespace(id=1)
    assert ops.buscar_servicio_por_identificador(Sesion(servicio), "LIN-9") is servicio
    sql = str(capturado[0].compile(dialect=postgresql.dialect()))
    assert "numero_linea" in sql and "numero_primer_servicio" in sql and "servicio_id" in sql


def test_buscar_servicio_orden_determinista():
    """Con dos candidatos se ordena por `Servicio.id` antes del `.first()` (gana el de menor id)."""
    sesion = SesionDoble(SimpleNamespace(id=1))
    ops.buscar_servicio_por_identificador(sesion, "X")
    assert [str(c) for c in sesion.orden] == ["Servicio.id"]


def test_rutas_de_servicio_inexistente_devuelve_none():
    assert ops.obtener_rutas_de_servicio(SesionDoble(None), "X") is None


def test_rutas_de_servicio_forma():
    from datetime import datetime

    from db.models.infra import RutaTipo

    ruta = SimpleNamespace(
        id=7, nombre="R1", tipo=RutaTipo.BACKUP, hash_contenido="h", empalmes=[1, 2], activa=1,
        created_at=datetime(2026, 1, 2, 3, 4, 5), nombre_archivo_origen="a.txt",
    )
    sin_tipo = SimpleNamespace(
        id=8, nombre="R2", tipo=None, hash_contenido=None, empalmes=[], activa=0,
        created_at=None, nombre_archivo_origen=None,
    )
    servicio = SimpleNamespace(servicio_id="111", id=5, cliente="ACME", rutas=[ruta, sin_tipo])
    datos = ops.obtener_rutas_de_servicio(SesionDoble(servicio), "111")
    assert set(datos) == {"status", "servicio_id", "servicio_db_id", "cliente", "rutas", "total_rutas"}
    assert datos["total_rutas"] == 2 and datos["servicio_db_id"] == 5
    assert datos["rutas"][0] == {
        "id": 7, "nombre": "R1", "tipo": "BACKUP", "hash_contenido": "h", "empalmes_count": 2,
        "activa": True, "created_at": "2026-01-02T03:04:05", "nombre_archivo_origen": "a.txt",
    }
    assert datos["rutas"][1]["tipo"] == "PRINCIPAL" and datos["rutas"][1]["activa"] is False


def test_limpiar_empalmes_inexistente_no_commitea():
    sesion = SesionDoble(None)
    assert ops.limpiar_empalmes_de_servicio(sesion, "X") is None
    assert "commit" not in sesion.llamadas


def test_limpiar_empalmes_cuenta_borra_y_commitea():
    borradas = []

    class Sesion(SesionDoble):
        def delete(self, obj):
            borradas.append(obj)

    r1, r2 = SimpleNamespace(empalmes=[1, 2]), SimpleNamespace(empalmes=[3])
    servicio = SimpleNamespace(servicio_id="52547", rutas=[r1, r2])
    sesion = Sesion(servicio)
    datos = ops.limpiar_empalmes_de_servicio(sesion, "52547")
    assert datos == {
        "status": "ok", "servicio_id": "52547",
        "message": "Eliminadas 3 asociaciones y 2 rutas",
        "rutas_eliminadas": 2, "empalmes_rutas_eliminados": 3,
    }
    assert borradas == [r1, r2] and sesion.llamadas == ["commit"]
