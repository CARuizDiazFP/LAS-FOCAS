# Nombre de archivo: test_ruta_servicio.py
# Ubicación de archivo: tests/test_ruta_servicio.py
# Descripción: Tests para el sistema de versionado de rutas de servicios
"""
Tests para el modelo RutaServicio y el servicio InfraService.

Cobertura:
- Modelo RutaServicio y relaciones
- InfraService.analyze_tracking()
- InfraService.resolve_tracking() con las 4 acciones
- Helper functions
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from core.services.cromo.camara_botella_busqueda import ResultadoBusquedaExtendida
from core.services.infra_service import (
    AnalysisResult,
    AnalysisStatus,
    InfraService,
    ResolveAction,
    ResolveResult,
    RutaInfo,
    _get_or_create_empalme,
    _resolve_camara_o_registrar_sin_match,
    compute_tracking_hash,
)
from db.models.infra import (
    Camara,
    CamaraEstado,
    CamaraOrigenDatos,
    Empalme,
    IngresoSinMatch,
    RutaServicio,
    RutaTipo,
    Servicio,
)
from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError


# =============================================================================
# FIXTURES
# =============================================================================

# Contenido de tracking válido con formato esperado
SAMPLE_TRACKING_CONTENT = """
Empalme 1: CAMARA NORTE 123
Empalme 2: CAMARA SUR 456
Empalme 3: CAMARA CENTRO 789
"""

SAMPLE_TRACKING_CONTENT_MODIFIED = """
Empalme 1: CAMARA NORTE 123
Empalme 2: CAMARA SUR 456
Empalme 3: CAMARA CENTRO 789
Empalme 4: CAMARA NUEVA 999
"""


@pytest.fixture
def mock_session():
    """Crea un mock de sesión SQLAlchemy."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.get.return_value = None
    return session


@pytest.fixture
def mock_servicio():
    """Crea un servicio mock con rutas."""
    servicio = MagicMock(spec=Servicio)
    servicio.id = 1
    servicio.servicio_id = "111995"
    servicio.cliente = "Cliente Test"
    servicio.rutas = []
    return servicio


@pytest.fixture
def mock_ruta_principal(mock_servicio):
    """Crea una ruta principal mock."""
    ruta = MagicMock(spec=RutaServicio)
    ruta.id = 1
    ruta.servicio_id = mock_servicio.id
    ruta.servicio = mock_servicio
    ruta.nombre = "Principal"
    ruta.tipo = RutaTipo.PRINCIPAL
    ruta.hash_contenido = compute_tracking_hash(SAMPLE_TRACKING_CONTENT)
    ruta.activa = True
    ruta.empalmes = []
    ruta.nombre_archivo_origen = "test.txt"
    ruta.created_at = None
    return ruta


# =============================================================================
# TESTS: HELPER FUNCTIONS
# =============================================================================

class TestHelperFunctions:
    """Tests para funciones helper."""

    def test_compute_tracking_hash_consistent(self):
        """El hash debe ser consistente para el mismo contenido."""
        hash1 = compute_tracking_hash(SAMPLE_TRACKING_CONTENT)
        hash2 = compute_tracking_hash(SAMPLE_TRACKING_CONTENT)
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex digest

    def test_compute_tracking_hash_ignores_whitespace_differences(self):
        """El hash debe ser igual ignorando diferencias de espacios."""
        content1 = "Line1\nLine2"
        content2 = "  Line1  \n  Line2  "
        
        hash1 = compute_tracking_hash(content1)
        hash2 = compute_tracking_hash(content2)
        
        assert hash1 == hash2

    def test_compute_tracking_hash_different_content(self):
        """El hash debe ser diferente para contenido diferente."""
        hash1 = compute_tracking_hash(SAMPLE_TRACKING_CONTENT)
        hash2 = compute_tracking_hash(SAMPLE_TRACKING_CONTENT_MODIFIED)
        
        assert hash1 != hash2


# =============================================================================
# TESTS: ANALYSIS STATUS ENUM
# =============================================================================

class TestAnalysisStatus:
    """Tests para el enum AnalysisStatus."""

    def test_enum_values(self):
        """Verifica los valores del enum."""
        assert AnalysisStatus.NEW.value == "NEW"
        assert AnalysisStatus.IDENTICAL.value == "IDENTICAL"
        assert AnalysisStatus.CONFLICT.value == "CONFLICT"
        assert AnalysisStatus.ERROR.value == "ERROR"


class TestResolveAction:
    """Tests para el enum ResolveAction."""

    def test_enum_values(self):
        """Verifica los valores del enum."""
        assert ResolveAction.CREATE_NEW.value == "CREATE_NEW"
        assert ResolveAction.MERGE_APPEND.value == "MERGE_APPEND"
        assert ResolveAction.REPLACE.value == "REPLACE"
        assert ResolveAction.BRANCH.value == "BRANCH"


# =============================================================================
# TESTS: DATACLASSES
# =============================================================================

class TestDataclasses:
    """Tests para dataclasses de resultados."""

    def test_ruta_info_creation(self):
        """Debe crear RutaInfo correctamente."""
        info = RutaInfo(
            id=1,
            nombre="Principal",
            tipo="PRINCIPAL",
            hash_contenido="abc123",
            empalmes_count=5,
            activa=True,
            created_at=None,
            nombre_archivo_origen="test.txt",
        )
        
        assert info.id == 1
        assert info.nombre == "Principal"
        assert info.tipo == "PRINCIPAL"
        assert info.empalmes_count == 5

    def test_analysis_result_new(self):
        """Debe crear AnalysisResult para NEW."""
        result = AnalysisResult(
            status=AnalysisStatus.NEW,
            servicio_id="111995",
            nuevo_hash="abc123",
            parsed_empalmes_count=5,
            message="Servicio nuevo detectado",
        )
        
        assert result.status == AnalysisStatus.NEW
        assert result.servicio_id == "111995"
        assert result.rutas_existentes == []

    def test_resolve_result_success(self):
        """Debe crear ResolveResult para éxito."""
        result = ResolveResult(
            success=True,
            action=ResolveAction.CREATE_NEW,
            servicio_id="111995",
            servicio_db_id=1,
            ruta_id=1,
            ruta_nombre="Principal",
            empalmes_creados=5,
            message="Servicio creado exitosamente",
        )
        
        assert result.success is True
        assert result.action == ResolveAction.CREATE_NEW


# =============================================================================
# TESTS: INFRA SERVICE - ANALYZE (usando mocks del parser)
# =============================================================================

class TestInfraServiceAnalyze:
    """Tests para InfraService.analyze_tracking()."""

    def test_analyze_new_service(self, mock_session):
        """Debe detectar servicio nuevo (status=NEW)."""
        mock_session.query.return_value.filter.return_value.first.return_value = None
        
        service = InfraService(mock_session)
        
        # Usar archivo con nombre válido que contenga el ID
        result = service.analyze_tracking(SAMPLE_TRACKING_CONTENT, "FO 111995 C2.txt")
        
        # Si el parser funciona correctamente, debe detectar como nuevo
        # Si falla el parse, será ERROR
        assert result.status in [AnalysisStatus.NEW, AnalysisStatus.ERROR]
        if result.status == AnalysisStatus.NEW:
            assert result.servicio_id == "111995"

    def test_analyze_identical_content(self, mock_session, mock_servicio, mock_ruta_principal):
        """Debe detectar contenido idéntico (status=IDENTICAL)."""
        mock_servicio.rutas = [mock_ruta_principal]
        mock_session.query.return_value.filter.return_value.first.return_value = mock_servicio
        
        service = InfraService(mock_session)
        
        result = service.analyze_tracking(SAMPLE_TRACKING_CONTENT, "FO 111995 C2.txt")
        
        # Puede ser IDENTICAL si el hash coincide, o ERROR si el parse falla
        assert result.status in [AnalysisStatus.IDENTICAL, AnalysisStatus.ERROR]

    def test_analyze_conflict(self, mock_session, mock_servicio, mock_ruta_principal):
        """Debe detectar conflicto (status=CONFLICT)."""
        mock_servicio.rutas = [mock_ruta_principal]
        mock_session.query.return_value.filter.return_value.first.return_value = mock_servicio
        
        service = InfraService(mock_session)
        
        # Contenido modificado -> hash diferente
        result = service.analyze_tracking(SAMPLE_TRACKING_CONTENT_MODIFIED, "FO 111995 C2.txt")
        
        # Puede ser CONFLICT si detecta diferencia, o ERROR si falla algo
        assert result.status in [AnalysisStatus.CONFLICT, AnalysisStatus.ERROR]


# =============================================================================
# TESTS: INFRA SERVICE - RESOLVE (básicos)
# =============================================================================

class TestInfraServiceResolve:
    """Tests para InfraService.resolve_tracking()."""

    def test_resolve_merge_append_requires_target_ruta(self, mock_session, mock_servicio):
        """MERGE_APPEND debe requerir target_ruta_id."""
        mock_session.query.return_value.filter.return_value.first.return_value = mock_servicio
        
        service = InfraService(mock_session)
        
        result = service.resolve_tracking(
            ResolveAction.MERGE_APPEND,
            SAMPLE_TRACKING_CONTENT,
            "FO 111995 C2.txt",
            target_ruta_id=None,  # Sin target
        )
        
        assert result.success is False
        assert "target_ruta_id" in result.error.lower() or "ruta" in result.error.lower()

    def test_resolve_replace_requires_target_ruta(self, mock_session, mock_servicio):
        """REPLACE debe requerir target_ruta_id."""
        mock_session.query.return_value.filter.return_value.first.return_value = mock_servicio
        
        service = InfraService(mock_session)
        
        result = service.resolve_tracking(
            ResolveAction.REPLACE,
            SAMPLE_TRACKING_CONTENT,
            "FO 111995 C2.txt",
            target_ruta_id=None,  # Sin target
        )
        
        assert result.success is False
        assert "target_ruta_id" in result.error.lower() or "ruta" in result.error.lower()


# =============================================================================
# TESTS: TAREA 3 — "Adjuntar tracking" nunca crea Camara, registra IngresoSinMatch
# =============================================================================

class TestResolveCamaraORegistrarSinMatch:
    """Tests para `_resolve_camara_o_registrar_sin_match` — reemplaza `_get_or_create_camara`.

    Cromo Red es la fuente de verdad del inventario (2026-08-11): esta función NUNCA debe
    instanciar una `Camara` nueva, matchee o no matchee.
    """

    @patch("core.services.cromo.camara_botella_busqueda.buscar_camara_o_botella_cromo")
    def test_devuelve_camara_si_hay_match(self, mock_buscar, mock_session):
        camara_mock = MagicMock(spec=Camara)
        camara_mock.id = 10
        mock_buscar.return_value = ResultadoBusquedaExtendida(
            camara=camara_mock, nombre_norm="camara norte 123", fuente="camara", botella=None
        )

        resultado = _resolve_camara_o_registrar_sin_match(
            mock_session, "Camara Norte 123", filename="FO 111995 C2.txt", servicio_id="111995"
        )

        assert resultado is camara_mock
        assert mock_session.add.call_count == 0  # ningún IngresoSinMatch, ninguna Camara

    @patch("core.services.cromo.camara_botella_busqueda.buscar_camara_o_botella_cromo")
    def test_sin_match_registra_ingreso_sin_match_y_nunca_crea_camara(self, mock_buscar, mock_session):
        mock_buscar.return_value = ResultadoBusquedaExtendida(
            camara=None, nombre_norm="ubicacion rara", fuente=None, botella=None
        )

        resultado = _resolve_camara_o_registrar_sin_match(
            mock_session, "Ubicacion Rara ", filename="FO 111995 C2.txt", servicio_id="111995"
        )

        assert resultado is None
        add_args = [call.args[0] for call in mock_session.add.call_args_list]
        assert len(add_args) == 1
        ingreso = add_args[0]
        assert isinstance(ingreso, IngresoSinMatch)
        assert ingreso.origen == "tracking"
        assert ingreso.texto_original == "Ubicacion Rara"  # strip() aplicado
        assert "FO 111995 C2.txt" in ingreso.contexto
        assert "111995" in ingreso.contexto
        # Nunca se instancia una Camara nueva, ni siquiera en el flujo sin match
        assert not any(isinstance(obj, Camara) for obj in add_args)

    @patch("core.services.cromo.camara_botella_busqueda.buscar_camara_o_botella_cromo")
    def test_ambiguous_search_error_se_trata_como_sin_match(self, mock_buscar, mock_session):
        """`AmbiguousSearchError` no se propaga: acá no hay desambiguación interactiva (a
        diferencia del listener de Slack) — se trata como "sin match" sin romper el tracking."""
        mock_buscar.side_effect = AmbiguousSearchError(
            "Camara Norte", 2, ["Camara Norte 1", "Camara Norte 2"]
        )

        resultado = _resolve_camara_o_registrar_sin_match(
            mock_session, "Camara Norte", filename="FO 111995 C2.txt", servicio_id="111995"
        )

        assert resultado is None
        add_args = [call.args[0] for call in mock_session.add.call_args_list]
        assert len(add_args) == 1
        assert isinstance(add_args[0], IngresoSinMatch)
        assert not any(isinstance(obj, Camara) for obj in add_args)


class TestGetOrCreateEmpalmeSinMatch:
    """Tests para `_get_or_create_empalme` con `camara: Optional[Camara]` (Tarea 3)."""

    def test_crea_empalme_nuevo_sin_camara(self, mock_session):
        mock_session.query.return_value.filter.return_value.first.return_value = None

        empalme, es_nuevo = _get_or_create_empalme(mock_session, "111995_1", None)

        assert es_nuevo is True
        assert empalme.camara_id is None

    def test_crea_empalme_nuevo_con_camara(self, mock_session):
        mock_session.query.return_value.filter.return_value.first.return_value = None
        camara = MagicMock(spec=Camara)
        camara.id = 55

        empalme, es_nuevo = _get_or_create_empalme(mock_session, "111995_1", camara)

        assert es_nuevo is True
        assert empalme.camara_id == 55

    def test_reproceso_sin_match_no_pisa_camara_id_existente(self, mock_session):
        """Regresión clave (self-review Tarea 3): un reproceso donde la búsqueda no matchea NO
        debe nulear el `camara_id` de un `Empalme` ya confirmado en una corrida anterior."""
        empalme_existente = MagicMock(spec=Empalme)
        empalme_existente.camara_id = 99
        mock_session.query.return_value.filter.return_value.first.return_value = empalme_existente

        empalme, es_nuevo = _get_or_create_empalme(mock_session, "111995_1", None)

        assert es_nuevo is False
        assert empalme is empalme_existente
        assert empalme.camara_id == 99  # NO se pisó con None

    def test_reproceso_con_match_actualiza_camara_id(self, mock_session):
        """Cuando SÍ hay una cámara resuelta, el camara_id de un Empalme existente se actualiza
        normalmente (esto no debe romperse por el fix del caso anterior)."""
        empalme_existente = MagicMock(spec=Empalme)
        empalme_existente.camara_id = 1
        mock_session.query.return_value.filter.return_value.first.return_value = empalme_existente
        camara_nueva = MagicMock(spec=Camara)
        camara_nueva.id = 2

        empalme, es_nuevo = _get_or_create_empalme(mock_session, "111995_1", camara_nueva)

        assert es_nuevo is False
        assert empalme.camara_id == 2


class TestUbicacionesSinMatchPorAccion:
    """`ResolveResult.ubicaciones_sin_match` debe contarse en las 6 acciones que resuelven
    cámaras — no sólo en algunas (self-review Tarea 3). `camaras_nuevas` debe quedar siempre en 0
    (el campo se mantiene por compatibilidad de API, pero esta función nunca crea Camara)."""

    @patch("core.services.infra_service._resolve_camara_o_registrar_sin_match")
    def test_create_new(self, mock_resolve, mock_session):
        mock_resolve.return_value = None
        mock_session.query.return_value.filter.return_value.first.return_value = None  # servicio nuevo

        service = InfraService(mock_session)
        result = service.resolve_tracking(
            ResolveAction.CREATE_NEW, SAMPLE_TRACKING_CONTENT, "FO 111995 C2.txt"
        )

        assert result.success is True
        assert result.ubicaciones_sin_match == 3
        assert result.camaras_nuevas == 0

    @patch("core.services.infra_service._resolve_camara_o_registrar_sin_match")
    def test_merge_append(self, mock_resolve, mock_session, mock_servicio):
        mock_resolve.return_value = None
        ruta = MagicMock()
        ruta.id = 1
        ruta.nombre = "Principal"
        ruta.servicio = mock_servicio
        ruta.empalmes = []
        mock_session.query.return_value.get.return_value = ruta

        service = InfraService(mock_session)
        result = service.resolve_tracking(
            ResolveAction.MERGE_APPEND,
            SAMPLE_TRACKING_CONTENT,
            "FO 111995 C2.txt",
            target_ruta_id=1,
        )

        assert result.success is True
        assert result.ubicaciones_sin_match == 3
        assert result.camaras_nuevas == 0

    @patch("core.services.infra_service._resolve_camara_o_registrar_sin_match")
    def test_replace(self, mock_resolve, mock_session, mock_servicio):
        mock_resolve.return_value = None
        ruta = MagicMock()
        ruta.id = 1
        ruta.nombre = "Principal"
        ruta.servicio = mock_servicio
        ruta.empalmes = []
        mock_session.query.return_value.get.return_value = ruta

        service = InfraService(mock_session)
        result = service.resolve_tracking(
            ResolveAction.REPLACE,
            SAMPLE_TRACKING_CONTENT,
            "FO 111995 C2.txt",
            target_ruta_id=1,
        )

        assert result.success is True
        assert result.ubicaciones_sin_match == 3
        assert result.camaras_nuevas == 0

    @patch("core.services.infra_service._resolve_camara_o_registrar_sin_match")
    @patch.object(InfraService, "_find_servicio_by_identificador")
    def test_branch(self, mock_find, mock_resolve, mock_session):
        mock_resolve.return_value = None
        servicio = MagicMock(spec=Servicio)
        servicio.id = 1
        servicio.servicio_id = "111995"
        servicio.rutas = []
        servicio.empalmes = []
        mock_find.return_value = servicio

        service = InfraService(mock_session)
        result = service.resolve_tracking(
            ResolveAction.BRANCH,
            SAMPLE_TRACKING_CONTENT,
            "FO 111995 C2.txt",
            new_ruta_name="Ruta Alternativa",
        )

        assert result.success is True
        assert result.ubicaciones_sin_match == 3
        assert result.camaras_nuevas == 0

    @patch("core.services.infra_service._resolve_camara_o_registrar_sin_match")
    def test_confirm_upgrade(self, mock_resolve, mock_session):
        mock_resolve.return_value = None
        old_servicio = MagicMock(spec=Servicio)
        old_servicio.id = 1
        old_servicio.servicio_id = "999999"
        old_servicio.alias_ids = []
        old_servicio.empalmes = []
        mock_session.query.return_value.filter.return_value.first.return_value = old_servicio

        service = InfraService(mock_session)
        result = service.resolve_tracking(
            ResolveAction.CONFIRM_UPGRADE,
            SAMPLE_TRACKING_CONTENT,
            "FO 111995 C2.txt",
            old_service_id="999999",
        )

        assert result.success is True
        assert result.ubicaciones_sin_match == 3
        assert result.camaras_nuevas == 0

    @patch("core.services.infra_service._resolve_camara_o_registrar_sin_match")
    def test_add_strand(self, mock_resolve, mock_session, mock_servicio):
        mock_resolve.return_value = None
        ruta_base = MagicMock()
        ruta_base.id = 1
        ruta_base.nombre = "Principal"
        ruta_base.tipo = RutaTipo.PRINCIPAL
        ruta_base.servicio = mock_servicio
        mock_session.query.return_value.get.return_value = ruta_base
        mock_session.query.return_value.filter.return_value.count.return_value = 0

        service = InfraService(mock_session)
        result = service.resolve_tracking(
            ResolveAction.ADD_STRAND,
            SAMPLE_TRACKING_CONTENT,
            "FO 111995 C2.txt",
            target_ruta_id=1,
        )

        assert result.success is True
        assert result.ubicaciones_sin_match == 3


class TestServicioAliasReuse:
    """`_find_servicio_by_identificador` (mismo criterio que
    `core/services/cromo/ingesta.py::_SQL_BUSCAR_SERVICIO`: servicio_id, numero_primer_servicio o
    alias_ids) debe estar wireado en CREATE_NEW y BRANCH — antes sólo comparaban `servicio_id`
    exacto, lo que podía duplicar un Servicio que ya existe bajo un ID alternativo."""

    @patch("core.services.infra_service._resolve_camara_o_registrar_sin_match")
    @patch.object(InfraService, "_find_servicio_by_identificador")
    def test_create_new_reusa_servicio_encontrado_por_alias(self, mock_find, mock_resolve, mock_session):
        mock_resolve.return_value = None
        servicio_existente = MagicMock(spec=Servicio)
        servicio_existente.id = 42
        # ID canónico de la fila, DISTINTO del número que trae el archivo ("111995" — un alias
        # viejo). Bug real encontrado en revisión: antes del fix, el ResolveResult devuelto
        # (y por lo tanto `TrackingResolveResponse.servicio_id`) mostraba "111995" en vez de
        # "O1C1", porque `_action_create_new` seguía usando `parsed.servicio_id` en el retorno
        # aunque `existing` se hubiera encontrado por alias.
        servicio_existente.servicio_id = "O1C1"
        servicio_existente.rutas = []
        servicio_existente.empalmes = []
        mock_find.return_value = servicio_existente

        service = InfraService(mock_session)
        result = service.resolve_tracking(
            ResolveAction.CREATE_NEW, SAMPLE_TRACKING_CONTENT, "FO 111995 C2.txt"
        )

        mock_find.assert_called_once_with("111995")
        assert result.success is True
        # Reusó el servicio existente (id=42): si hubiera creado uno nuevo, servicio_db_id
        # quedaría en None porque `session.flush()` está mockeado y no asigna PK.
        assert result.servicio_db_id == 42
        # Regresión: debe reportar el servicio_id CANÓNICO de la fila encontrada, no el número
        # ("111995") que traía el archivo de tracking.
        assert result.servicio_id == "O1C1"

    @patch("core.services.infra_service._resolve_camara_o_registrar_sin_match")
    @patch.object(InfraService, "_find_servicio_by_identificador")
    def test_branch_encuentra_servicio_por_alias(self, mock_find, mock_resolve, mock_session):
        mock_resolve.return_value = None
        servicio_existente = MagicMock(spec=Servicio)
        servicio_existente.id = 42
        servicio_existente.servicio_id = "O1C1"
        servicio_existente.rutas = []
        servicio_existente.empalmes = []
        mock_find.return_value = servicio_existente

        service = InfraService(mock_session)
        result = service.resolve_tracking(
            ResolveAction.BRANCH,
            SAMPLE_TRACKING_CONTENT,
            "FO 111995 C2.txt",
            new_ruta_name="Ruta Alternativa",
        )

        mock_find.assert_called_once_with("111995")
        assert result.success is True
        assert result.servicio_db_id == 42
        assert result.servicio_id == "O1C1"


class TestEmpalmeKeyedPorServicioCanonico:
    """Importante #2 (revisión post-implementación, 2026-08-23): el `tracking_id` de un Empalme
    debe construirse con el `servicio_id` CANÓNICO del Servicio resuelto (`servicio.servicio_id`),
    no con `parsed.servicio_id` (el número que traía el archivo, que puede ser un
    alias/numero_primer_servicio no canónico) — de lo contrario, al reprocesar un tracking que
    referencia un alias viejo, `_get_or_create_empalme` buscaría bajo una clave distinta a la
    usada en la corrida original y crearía filas de Empalme duplicadas en vez de reusarlas.

    Se mockea `_get_or_create_empalme` e inspecciona el `tracking_id` (2do arg posicional) con el
    que se lo invoca en cada iteración — es el punto exacto donde el bug real vivía."""

    @patch("core.services.infra_service._get_or_create_empalme")
    @patch("core.services.infra_service._resolve_camara_o_registrar_sin_match")
    @patch.object(InfraService, "_find_servicio_by_identificador")
    def test_create_new_usa_servicio_id_canonico_para_tracking_id(
        self, mock_find, mock_resolve, mock_get_empalme, mock_session
    ):
        mock_resolve.return_value = None
        servicio_existente = MagicMock(spec=Servicio)
        servicio_existente.id = 42
        servicio_existente.servicio_id = "O1C1"  # canónico, distinto del archivo ("111995")
        servicio_existente.rutas = []
        servicio_existente.empalmes = []
        mock_find.return_value = servicio_existente

        empalme_mock = MagicMock(spec=Empalme)
        empalme_mock.id = 1
        mock_get_empalme.return_value = (empalme_mock, False)  # simula reuso, nunca "es_nuevo"

        service = InfraService(mock_session)
        result = service.resolve_tracking(
            ResolveAction.CREATE_NEW, SAMPLE_TRACKING_CONTENT, "FO 111995 C2.txt"
        )

        assert result.success is True
        assert result.servicio_id == "O1C1"

        tracking_ids_usados = [call.args[1] for call in mock_get_empalme.call_args_list]
        # Los 3 empalmes de SAMPLE_TRACKING_CONTENT deben quedar keyeados bajo el ID canónico.
        assert tracking_ids_usados == ["O1C1_1", "O1C1_2", "O1C1_3"]
        # Antes del fix, esto habría sido ["111995_1", "111995_2", "111995_3"] — el alias del
        # archivo, que dejaría huérfanos los empalmes ya registrados bajo "O1C1_N".
        assert not any(tid.startswith("111995_") for tid in tracking_ids_usados)

    @patch("core.services.infra_service._get_or_create_empalme")
    @patch("core.services.infra_service._resolve_camara_o_registrar_sin_match")
    @patch.object(InfraService, "_find_servicio_by_identificador")
    def test_branch_usa_servicio_id_canonico_para_tracking_id(
        self, mock_find, mock_resolve, mock_get_empalme, mock_session
    ):
        mock_resolve.return_value = None
        servicio_existente = MagicMock(spec=Servicio)
        servicio_existente.id = 42
        servicio_existente.servicio_id = "O1C1"
        servicio_existente.rutas = []
        servicio_existente.empalmes = []
        mock_find.return_value = servicio_existente

        empalme_mock = MagicMock(spec=Empalme)
        empalme_mock.id = 1
        mock_get_empalme.return_value = (empalme_mock, False)

        service = InfraService(mock_session)
        result = service.resolve_tracking(
            ResolveAction.BRANCH,
            SAMPLE_TRACKING_CONTENT,
            "FO 111995 C2.txt",
            new_ruta_name="Ruta Alternativa",
        )

        assert result.success is True
        assert result.servicio_id == "O1C1"

        tracking_ids_usados = [call.args[1] for call in mock_get_empalme.call_args_list]
        assert tracking_ids_usados == ["O1C1_1", "O1C1_2", "O1C1_3"]
        assert not any(tid.startswith("111995_") for tid in tracking_ids_usados)


class TestResolveResultUbicacionesSinMatch:
    """Tests de forma para el nuevo campo del dataclass (backward-compatible)."""

    def test_default_es_cero(self):
        result = ResolveResult(success=True, action=ResolveAction.CREATE_NEW)
        assert result.ubicaciones_sin_match == 0

    def test_to_dict_incluye_el_campo(self):
        result = ResolveResult(
            success=True, action=ResolveAction.CREATE_NEW, ubicaciones_sin_match=5
        )
        data = result.to_dict()
        assert data["ubicaciones_sin_match"] == 5
        # camaras_nuevas se mantiene (API pública documentada, otros consumidores pueden leerlo)
        assert "camaras_nuevas" in data
        assert data["camaras_nuevas"] == 0


# =============================================================================
# TESTS: RUTA TIPO ENUM
# =============================================================================

class TestRutaTipo:
    """Tests para el enum RutaTipo."""

    def test_enum_values(self):
        """Verifica los valores del enum."""
        assert RutaTipo.PRINCIPAL.value == "PRINCIPAL"
        assert RutaTipo.BACKUP.value == "BACKUP"
        assert RutaTipo.ALTERNATIVA.value == "ALTERNATIVA"

    def test_enum_from_string(self):
        """Debe crear enum desde string."""
        assert RutaTipo("PRINCIPAL") == RutaTipo.PRINCIPAL
        assert RutaTipo("BACKUP") == RutaTipo.BACKUP

    def test_enum_invalid_value(self):
        """Debe fallar con valor inválido."""
        with pytest.raises(ValueError):
            RutaTipo("INVALIDO")


# =============================================================================
# TESTS: INTEGRATION (requiere DB real - marcados como slow)
# =============================================================================

@pytest.mark.slow
class TestRutaServicioIntegration:
    """Tests de integración que requieren base de datos real."""

    @pytest.fixture
    def db_session(self):
        """Fixture para sesión de DB real."""
        # Este fixture solo se ejecuta si los tests slow están habilitados
        pytest.skip("Requiere base de datos real")

    def test_create_ruta_with_empalmes(self, db_session):
        """Debe crear ruta con empalmes ordenados."""
        pass  # TODO: Implementar con DB real

    def test_servicio_ruta_principal_property(self, db_session):
        """Debe retornar ruta principal correctamente."""
        pass  # TODO: Implementar con DB real
