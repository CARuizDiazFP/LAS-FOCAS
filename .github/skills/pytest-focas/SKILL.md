# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/pytest-focas/SKILL.md
# Descripción: Habilidad para ejecutar tests con pytest en LAS-FOCAS

---
name: Pytest FOCAS
description: Habilidad para ejecutar y escribir tests con pytest en LAS-FOCAS
---

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

## Checklist Pre-Commit

- [ ] `pytest` pasa sin errores
- [ ] Tests nuevos para código nuevo
- [ ] Mocks para servicios externos
- [ ] Sin tests que dependan de red/DB real
