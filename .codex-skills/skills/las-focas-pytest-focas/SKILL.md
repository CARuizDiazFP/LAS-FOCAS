---
name: "las-focas-pytest-focas"
description: "Usar cuando haya que ejecutar pytest, escribir tests, preparar fixtures o revisar cobertura en LAS-FOCAS"
metadata:
  short-description: "Usar cuando haya que ejecutar pytest, escribir tests, preparar fixtures o revisar cobertura en LAS-FOCAS"
  source: ".github/skills/pytest-focas/SKILL.md"
  triggers:
    - "pytest-focas"
    - "habilidad"
    - "pytest"
    - "ejecutar"
    - "escribir"
    - "tests"
    - "preparar"
    - "fixtures"
    - "cobertura"
    - "las-focas"
  globs:
    - "tests/**"
    - "pytest.ini"
  commands:
    - |
      pytest
    - |
      pytest -v
    - |
      pytest tests/test_sla_processor.py -v
      pytest tests/test_alarmas_ciena.py::test_parse_alarma_simple -v
    - |
      pytest -k "sla" -v
      pytest -k "not slow" -v
    - |
      pytest --cov=core --cov=modules --cov-report=html
      pytest --cov=. --cov-report=term-missing
    - |
      # Verificar cobertura de módulo específico
      pytest --cov=modules/informes_sla --cov-report=term-missing

      # Fallar si cobertura < 60%
      pytest --cov=core --cov-fail-under=60
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-pytest-focas/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/pytest-focas/SKILL.md

# Skill portable: pytest-focas

> Fuente original: `.github/skills/pytest-focas/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

# Habilidad: Pytest FOCAS

Guía para testing en LAS-FOCAS con pytest.

## Configuración

Archivo `pytest.ini`:
```ini
[pytest]
testpaths = tests
norecursedirs = Legacy
pythonpath = .
```

## Ejecutar Tests

### Todos los tests

```bash
pytest
```

### Con verbose

```bash
pytest -v
```

### Test específico

```bash
pytest tests/test_sla_processor.py -v
pytest tests/test_alarmas_ciena.py::test_parse_alarma_simple -v
```

### Por patrón de nombre

```bash
pytest -k "sla" -v
pytest -k "not slow" -v
```

### Con cobertura

```bash
pytest --cov=core --cov=modules --cov-report=html
pytest --cov=. --cov-report=term-missing
```

## Estructura de Tests

```
tests/
├── conftest.py           # Fixtures globales
├── fixtures/             # Archivos de prueba estáticos
├── test_<modulo>.py      # Tests por módulo
```

## Patrones de Mock

### Variables de entorno

```python
def test_con_env(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
```

### Funciones/métodos

```python
def test_con_mock(monkeypatch):
    def mock_connect(*args, **kwargs):
        return MagicMock()

    monkeypatch.setattr("module.connect", mock_connect)
```

### Proveedores externos (OpenAI, SMTP)

```python
from unittest.mock import AsyncMock, patch

@pytest.fixture
def mock_openai():
    with patch("openai.ChatCompletion.acreate") as mock:
        mock.return_value = AsyncMock(
            choices=[{"message": {"content": "respuesta"}}]
        )
        yield mock

def test_con_openai(mock_openai):
    # OpenAI no será llamado realmente
    result = await mi_funcion()
    mock_openai.assert_called_once()
```

```python
@pytest.fixture
def mock_smtp():
    with patch("smtplib.SMTP") as mock:
        yield mock

def test_enviar_email(mock_smtp):
    # SMTP no será llamado realmente
    enviar_email("test@test.com", "asunto", "cuerpo")
    mock_smtp.return_value.send_message.assert_called_once()
```

### Storage in-memory

```python
from core.chatbot.storage import InMemoryChatStorage

@pytest.fixture
def storage():
    return InMemoryChatStorage()

@pytest.mark.asyncio
async def test_chat(storage):
    await storage.save_message(1, "user", "hola")
    history = await storage.get_history(1)
    assert len(history) == 1
```

## Fixtures Comunes

```python
# conftest.py
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_db_session():
    """Mock de sesión de base de datos."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    return session

@pytest.fixture
def sample_alarma():
    """Datos de ejemplo para tests de alarmas."""
    return {
        "timestamp": "2024-01-01 10:00:00",
        "equipo": "CIENA-001",
        "severidad": "CRITICAL"
    }
```

## Cobertura Mínima

> **Regla**: 60% de cobertura para módulos nuevos en MVP

```bash
# Verificar cobertura de módulo específico
pytest --cov=modules/informes_sla --cov-report=term-missing

# Fallar si cobertura < 60%
pytest --cov=core --cov-fail-under=60
```

## Tests Asíncronos

```python
import pytest

@pytest.mark.asyncio
async def test_funcion_async():
    resultado = await mi_funcion_async()
    assert resultado is not None
```

## Nombres Descriptivos

Usar formato: `test_<funcion>_<escenario>_<resultado_esperado>`

```python
def test_parse_alarma_formato_valido_retorna_objeto():
    pass

def test_parse_alarma_formato_invalido_lanza_excepcion():
    pass

def test_generar_informe_sin_datos_retorna_vacio():
    pass
```

## CI Integration

Los tests se ejecutan en GitHub Actions (`.github/workflows/ci.yml`):
- Job `tests`: pytest para API, NLP, Web
- Falla el CI si los tests no pasan

## Diagnóstico de Fallas: Heurísticas (lecciones 2026-07-30)

Antes de "arreglar" un test que falla, distinguir estos 4 casos — confundirlos hace perder tiempo o esconde bugs reales:

1. **Refactor intencional sin actualizar el test**: si el assert choca con el código, correr `git log -L <líneas>:<archivo>` antes de asumir que el código está mal. Puede haber un commit documentado que cambió la regla de negocio a propósito (ej.: cambio de columna de cálculo en un Excel) y el test simplemente no se actualizó.
2. **Test obsoleto por cambio de arquitectura**: si el test verifica un comportamiento que migró de dominio (server-side → client-side, HTML embebido → API JSON), no alcanza con cambiar la URL/aserción — hay que confirmar dónde vive ahora la responsabilidad (ej.: `window.USER_ROLE` inyectado en HTML → migrado a `GET /api/auth/session`) antes de escribir el reemplazo.
3. **Gap de entorno, no de código**: un `ModuleNotFoundError` en un test puede ser una dependencia que vive en el `requirements.txt` de un servicio con su propio Dockerfile (worker dedicado), nunca instalada en el `.venv` compartido. Revisar si el módulo tiene su propio `requirements.txt`/contenedor antes de asumir que falta declarar la dependencia.
4. **Gap de cobertura real (mocks insuficientes)**: `MagicMock()` no puede validar comportamiento a nivel SQL — `order_by` sobre tablas de asociación con columnas extra, constraints de FK/unicidad, inserts crudos vía `Table.insert()`. Si un modelo depende de eso, un test mockeado da falsa confianza; hace falta el patrón `ENABLE_DB_TESTS=1` contra una DB real (con rollback transaccional por test). **Caso real 2026-08-10**: un `Column(SQLEnum(...))` sin `schema="app"` pasó 500+ tests con sesión fake y sólo rompió contra la DB real, al insertar 2+ filas en el mismo `flush()` (dispara el batching "insertmanyvalues" de SQLAlchemy 2.0, que ningún mock reproduce) — ver `las-focas-db-mcp-postgres` / agente `db` sección "Gotchas reales".

Los tests `SKIPPED` casi siempre son intencionales y están documentados en `docs/PR/*.md` (buscar la fecha del commit que los introdujo) — no tratarlos como deuda silenciosa sin antes revisar el motivo. Un placeholder con `pass  # TODO` dentro de un test SÍ es deuda real, a diferencia de un `skipif`/`importorskip` bien razonado.

## Verificación real de cascadas de estado (lecciones 2026-08-10)

Para features que mutan estado en cascada (ej. baneo/desbaneo propagado a un grupo), los tests con
mocks/fakes NO pueden validar el "blast radius" real de una prueba contra datos reales — ver la skill
dedicada `las-focas-baneo-qa-real` antes de correr cualquier prueba de este tipo contra
`lasfocasdev-*`.

## Checklist Pre-Commit

- [ ] `pytest` pasa sin errores
- [ ] Tests nuevos para código nuevo
- [ ] Mocks para servicios externos
- [ ] Sin tests que dependan de red/DB real
