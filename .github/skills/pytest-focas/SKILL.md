# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/pytest-focas/SKILL.md
# Descripción: Habilidad para ejecutar tests con pytest en LAS-FOCAS

---
name: pytest-focas
description: "Usar cuando haya que ejecutar pytest, escribir tests, preparar fixtures o revisar cobertura en LAS-FOCAS"
argument-hint: "Describe suite o módulo, por ejemplo: correr tests de SLA y revisar mocks de OpenAI"
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

## Diagnóstico de Fallas: Heurísticas (lecciones 2026-07-30)

Antes de "arreglar" un test que falla, distinguir estos 4 casos — confundirlos hace perder tiempo o esconde bugs reales:

1. **Refactor intencional sin actualizar el test**: si el assert choca con el código, correr `git log -L <líneas>:<archivo>` antes de asumir que el código está mal. Puede haber un commit documentado que cambió la regla de negocio a propósito (ej.: cambio de columna de cálculo en un Excel) y el test simplemente no se actualizó.
2. **Test obsoleto por cambio de arquitectura**: si el test verifica un comportamiento que migró de dominio (server-side → client-side, HTML embebido → API JSON), no alcanza con cambiar la URL/aserción — hay que confirmar dónde vive ahora la responsabilidad (ej.: `window.USER_ROLE` inyectado en HTML → migrado a `GET /api/auth/session`) antes de escribir el reemplazo.
3. **Gap de entorno, no de código**: un `ModuleNotFoundError` en un test puede ser una dependencia que vive en el `requirements.txt` de un servicio con su propio Dockerfile (worker dedicado), nunca instalada en el `.venv` compartido. Revisar si el módulo tiene su propio `requirements.txt`/contenedor antes de asumir que falta declarar la dependencia.
4. **Gap de cobertura real (mocks insuficientes)**: `MagicMock()` no puede validar comportamiento a nivel SQL — `order_by` sobre tablas de asociación con columnas extra, constraints de FK/unicidad, inserts crudos vía `Table.insert()`. Si un modelo depende de eso, un test mockeado da falsa confianza; hace falta el patrón `ENABLE_DB_TESTS=1` contra una DB real (con rollback transaccional por test). **Caso real 2026-08-10**: un `Column(SQLEnum(...))` sin `schema="app"` pasó 500+ tests con sesión fake y sólo rompió contra la DB real, al insertar 2+ filas en el mismo `flush()` (dispara el batching "insertmanyvalues" de SQLAlchemy 2.0, que ningún mock reproduce) — ver `.github/agents/db.agent.md` sección "Gotchas reales".

Los tests `SKIPPED` casi siempre son intencionales y están documentados en `docs/PR/*.md` (buscar la fecha del commit que los introdujo) — no tratarlos como deuda silenciosa sin antes revisar el motivo. Un placeholder con `pass  # TODO` dentro de un test SÍ es deuda real, a diferencia de un `skipif`/`importorskip` bien razonado.

## Verificación real de cascadas de estado (lecciones 2026-08-10)

Para features que mutan estado en cascada (ej. baneo/desbaneo propagado a un grupo), los tests con
mocks/fakes NO pueden validar el "blast radius" real de una prueba contra datos reales — ver la skill
dedicada `.github/skills/baneo-qa-real/SKILL.md` antes de correr cualquier prueba de este tipo contra
`lasfocasdev-*`.

## Mocks compartidos rotos al extender una función con una consulta nueva (lección 2026-08-12)

`session = MagicMock()` con un chain plano (`session.query.return_value.filter.return_value.all.return_value = [...]`) asume que la función bajo test hace **una sola** consulta reconocible. Si esa función se extiende para hacer una consulta ADICIONAL (mismo modelo u otro), la nueva consulta cae en el MISMO chain mockeado — la lista pensada para la primera consulta se reusa para la segunda, y si el código intenta desempaquetarla de otra forma (ej. tuplas `(id,)` en vez de objetos ORM), rompe con un error confuso que no señala la causa real:

```python
# Código bajo test, extendido con una consulta nueva:
def resolver_o_crear_padre_desde_base(session, base, ...):
    raices = session.query(Camara).filter(...).all()            # consulta 1
    ids_con_cromo_hijos = ids_camaras_con_cromo_hijos(session)  # consulta 2 (nueva) — mismo chain mockeado

# Test existente, escrito ANTES de la extensión:
session = MagicMock()
session.query.return_value.filter.return_value.all.return_value = [padre_existente]
resolver_o_crear_padre_desde_base(session, "...")
# TypeError: cannot unpack non-iterable Camara object — la consulta 2 recibe la lista pensada
# para la consulta 1 y falla al desempaquetarla como tuplas (id,).
```

**Fix**: no intentar que el mismo `session.query` mockeado sirva para las dos consultas — aislar la consulta nueva en su propio helper (`ids_camaras_con_cromo_hijos(session)` en el ejemplo real) y mockear ESE helper directamente con una fixture `autouse`, con un default neutro que no rompe ningún test existente:

```python
@pytest.fixture(autouse=True)
def _sin_botellas_cromo(monkeypatch):
    monkeypatch.setattr(
        "core.services.camara_hierarchy_service.ids_camaras_con_cromo_hijos",
        lambda session: set(),
    )

# Los tests existentes (9 en este caso real) siguen pasando sin tocar su lógica interna. El test
# que sí quiere ejercitar la protección real sobreescribe el mismo patch dentro del test:
def test_reusa_camara_con_cromo_hijos(monkeypatch):
    monkeypatch.setattr(
        "core.services.camara_hierarchy_service.ids_camaras_con_cromo_hijos",
        lambda session: {6526},
    )
    ...
```

Caso real: `core/services/camara_hierarchy_service.py::ids_camaras_con_cromo_hijos` — ver `tests/test_camara_hierarchy_service.py` y `tests/test_cromo_camara_padre_service.py`.

## Tests HTTP de un endpoint async con DB (lección 2026-08-14)

Antes de escribir un test HTTP nuevo contra `api/app/routes/*.py`, revisar si ya hay un archivo real
que lo haga — al buscar precedente para `PATCH /servicios/{id}/categoria` (endpoint `async def` con
`AsyncSession` vía `Depends(get_async_db)`) se encontró que `tests/test_infra_search.py` sólo cubre
casos 422 (fallan en la capa Pydantic, nunca tocan la DB) y `tests/test_servicios_routes_utils.py`
sólo testea funciones puras — **ningún archivo existente ejercita un 200 real contra un endpoint async
con `select()`/ORM**. No asumir que existe un fixture de DB compartido sin comprobarlo primero.

Patrón que sí funciona, sin DB real ni fixture nueva (`tests/test_servicios_categoria_routes.py`):

```python
from db.session import get_async_db

class _FakeAsyncSession:
    def __init__(self, servicio):
        self._servicio = servicio
    async def get(self, _model, _id):
        return self._servicio
    async def commit(self): ...
    async def refresh(self, _obj): ...

def _override_con(fake_session):
    async def _dep():
        yield fake_session
    return _dep

def test_patch_categoria(...):
    app.dependency_overrides[get_async_db] = _override_con(_FakeAsyncSession(mock_servicio))
    try:
        response = client.patch("/servicios/1/categoria", json={"categoria": 3}, headers=API_HEADERS)
    finally:
        app.dependency_overrides.pop(get_async_db, None)  # limpiar siempre, incluso si el assert falla
```

Para un endpoint que en cambio reusa una capa **sync** existente vía `asyncio.to_thread` (patrón de
`api/app/routes/infra.py`, ver más abajo "Mocks compartidos rotos..."), no hace falta el override de
`get_async_db` — alcanza con `@patch("api.app.routes.<modulo>.SessionLocal")` devolviendo un
`MagicMock()` con el chain `query().filter().all()`/`.update()` ya seteado, igual que los tests de
`core/services/*_service.py` puros.

## Checklist Pre-Commit

- [ ] `pytest` pasa sin errores
- [ ] Tests nuevos para código nuevo
- [ ] Mocks para servicios externos
- [ ] Sin tests que dependan de red/DB real
