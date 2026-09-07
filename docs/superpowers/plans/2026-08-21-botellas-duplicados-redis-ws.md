# Redis + worker dedicado + WebSocket para el visor de Botellas duplicadas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sacar el recálculo pesado de grupos de Botellas duplicadas del camino síncrono de 3 endpoints
de lectura, invalidándolo/recalculándolo en background vía Redis + un worker dedicado, y avisar a los
paneles admin abiertos por WebSocket para que hagan un refetch silencioso.

**Architecture:** Redis con tres roles (caché del resultado, cola de jobs, bus pub/sub). Un worker
Docker nuevo consume la cola, recalcula con la función existente sin tocarla, escribe la caché y
publica. `web` (el proceso FastAPI ya corriendo) se suscribe al canal en el arranque y reenvía por
WebSocket a los clientes conectados. Los 7 endpoints que mutan datos relevantes invalidan+encolan;
los 3 que leen el cálculo pesado intentan la caché primero y caen al cómputo síncrono si no hay hit.

**Tech Stack:** FastAPI (async), SQLAlchemy 2.0 (sync + async), `redis` (cliente async, `redis-py`
5.x), Docker Compose, Vue 3 + `<script setup>`, `fetch` nativo (sin axios).

**Spec:** `docs/superpowers/specs/2026-08-21-botellas-duplicados-redis-ws.md`

## Global Constraints

- Cache key: `cache:botellas_duplicados:v1`. TTL: `86400` segundos (red de seguridad; la
  invalidación real es explícita en cada mutación, no depende del TTL).
- Queue key (lista Redis): `admin:recompute:jobs`. Job payload: JSON
  `{"kind": "botellas_duplicados", "motivo": "<str>"}`.
- Canal pub/sub: `admin-notifications`. Mensaje: JSON
  `{"type": "botellas_duplicados_recalculado", "at": "<iso8601 UTC>"}`.
- Endpoint WebSocket nuevo: `GET /ws/admin-notifications`.
- Redis nunca es una dependencia dura: toda operación Redis (get/set/delete/rpush/publish/subscribe)
  va en `try/except Exception`, loguea con `logger.warning(..., exc_info=True)` y degrada al
  comportamiento síncrono actual — nunca propaga la excepción a quien la llama.
- Dependencia Python nueva: `redis==5.0.8`, agregada a `common-requirements.txt` (usada por `web` y
  el worker nuevo — ambos heredan de `focas-base:latest`, que instala ese archivo).
- Ningún `docker compose up`/`restart`/`down` contra `deploy/compose.yml` (prod) como parte de este
  plan — sólo se edita el YAML. Dev sí se levanta y se prueba real.
- Todo archivo nuevo Python/TS/Vue lleva el encabezado de 3 líneas ya usado en todo el repo:
  `# Nombre de archivo: ...` / `# Ubicación de archivo: ...` / `# Descripción: ...` (`//` en `.ts`,
  `<!-- -->` no aplica en `.vue` con `<script setup lang="ts">` — el encabezado va como comentario
  `//` dentro del bloque `<script setup>`).
- Todos los tests corren con el venv del proyecto activo (`source .venv/bin/activate`) y sin Redis
  real disponible — cualquier test que ejercite el cliente Redis lo hace contra un fake/mock, nunca
  contra una instancia real (mismo criterio que `pytest-focas`: "sin DB real" ya usado en
  `tests/test_web_botellas_admin.py`).

---

### Task 1: Cliente Redis + módulo de caché/cola de recálculo

**Files:**
- Create: `core/cache/__init__.py`
- Create: `core/cache/redis_client.py`
- Create: `core/services/botella_recompute_queue.py`
- Modify: `common-requirements.txt` (agregar `redis==5.0.8`)
- Test: `tests/test_botella_recompute_queue.py`

**Interfaces:**
- Produces: `core.cache.redis_client.get_redis() -> redis.asyncio.Redis` (cliente async compartido,
  lazy — construir el objeto NO abre conexión; el primer comando real sí, y puede fallar).
- Produces: `core.services.botella_recompute_queue`:
  - `CACHE_KEY = "cache:botellas_duplicados:v1"`
  - `QUEUE_KEY = "admin:recompute:jobs"`
  - `JOB_KIND_BOTELLAS_DUPLICADOS = "botellas_duplicados"`
  - `async def leer_cache_duplicados() -> list[GrupoBotellasDuplicadas] | None` (`None` = cache frío
    o Redis no disponible)
  - `async def guardar_cache_duplicados(grupos: list[GrupoBotellasDuplicadas]) -> None` (best-effort)
  - `async def encolar_recalculo_duplicados_botellas(motivo: str) -> None` (invalida + encola,
    best-effort, nunca lanza)
- Consumes: `GrupoBotellasDuplicadas`, `BotellaDuplicadaItem` de
  `core/services/botella_duplicados_service.py:34-51` (dataclasses `slots=True`, NO modificar ese
  archivo).

- [ ] **Step 1: Escribir el paquete `core/cache/`**

`core/cache/__init__.py`:
```python
# Nombre de archivo: __init__.py
# Ubicación de archivo: core/cache/__init__.py
# Descripción: Paquete de infraestructura de caché (Redis) compartida entre web y workers
```

`core/cache/redis_client.py`:
```python
# Nombre de archivo: redis_client.py
# Ubicación de archivo: core/cache/redis_client.py
# Descripción: Factory de cliente Redis async compartido — lazy, nunca lanza al construirse

from __future__ import annotations

from redis.asyncio import Redis, from_url

from core.config import get_secret

_client: Redis | None = None


def _build_redis_url() -> str:
    host = get_secret("REDIS_HOST", "REDIS_HOST", "redis")
    port = get_secret("REDIS_PORT", "REDIS_PORT", "6379")
    password = get_secret("redis_password_v1", "REDIS_PASSWORD", "")
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{host}:{port}/0"


def get_redis() -> Redis:
    """Cliente Redis compartido. Construirlo es lazy (no abre conexión) — cada comando real puede
    fallar si Redis no está disponible; cada caller decide cómo degradar, nunca se propaga acá."""
    global _client
    if _client is None:
        _client = from_url(
            _build_redis_url(),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


def reset_redis_client() -> None:
    """Sólo para tests: fuerza reconstruir el cliente en la próxima llamada a `get_redis()`."""
    global _client
    _client = None


__all__ = ["get_redis", "reset_redis_client"]
```

- [ ] **Step 2: Agregar la dependencia**

En `common-requirements.txt`, agregar en una sección nueva (buscar dónde termina el bloque de deps
de infraestructura/cache si existe alguno, o al final del archivo):
```
# Cache / cola liviana
redis==5.0.8
```

- [ ] **Step 3: Escribir el módulo de caché/cola**

`core/services/botella_recompute_queue.py`:
```python
# Nombre de archivo: botella_recompute_queue.py
# Ubicación de archivo: core/services/botella_recompute_queue.py
# Descripción: Caché + cola de recálculo en background de los grupos de Botellas duplicadas (Redis)

"""Los 7 endpoints que mutan datos que afectan `detectar_grupos_duplicados_botellas` (vigente,
camara_id/camara_padre_id, nombre) invalidan la caché y encolan un job acá — ver
`docs/superpowers/specs/2026-08-21-botellas-duplicados-redis-ws.md`. El worker
`modules/botellas_recalculo_worker` consume la cola, recalcula y vuelve a poblar la caché."""

from __future__ import annotations

import json
import logging

from core.cache.redis_client import get_redis
from core.services.botella_duplicados_service import BotellaDuplicadaItem, GrupoBotellasDuplicadas

logger = logging.getLogger(__name__)

CACHE_KEY = "cache:botellas_duplicados:v1"
CACHE_TTL_SECONDS = 86400
QUEUE_KEY = "admin:recompute:jobs"
JOB_KIND_BOTELLAS_DUPLICADOS = "botellas_duplicados"


def _grupo_to_dict(grupo: GrupoBotellasDuplicadas) -> dict:
    return {
        "camara_padre_id": grupo.camara_padre_id,
        "camara_padre_nombre": grupo.camara_padre_nombre,
        "clave_normalizada": grupo.clave_normalizada,
        "criterio": grupo.criterio,
        "estados_en_conflicto": grupo.estados_en_conflicto,
        "estado_mas_restrictivo": grupo.estado_mas_restrictivo,
        "resoluble": grupo.resoluble,
        "miembros": [
            {"origen": m.origen, "id": m.id, "nombre": m.nombre, "estado": m.estado}
            for m in grupo.miembros
        ],
    }


def _grupo_from_dict(data: dict) -> GrupoBotellasDuplicadas:
    return GrupoBotellasDuplicadas(
        camara_padre_id=data["camara_padre_id"],
        camara_padre_nombre=data["camara_padre_nombre"],
        clave_normalizada=data["clave_normalizada"],
        criterio=data["criterio"],
        miembros=[BotellaDuplicadaItem(**m) for m in data["miembros"]],
        estados_en_conflicto=data["estados_en_conflicto"],
        estado_mas_restrictivo=data["estado_mas_restrictivo"],
        resoluble=data["resoluble"],
    )


async def leer_cache_duplicados() -> list[GrupoBotellasDuplicadas] | None:
    """`None` = cache frío, payload corrupto, o Redis no disponible — el caller cae al cómputo
    síncrono existente sin cambios."""
    try:
        raw = await get_redis().get(CACHE_KEY)
    except Exception:  # noqa: BLE001 - Redis es best-effort
        logger.warning("action=botellas_duplicados_cache_read result=fail", exc_info=True)
        return None
    if raw is None:
        return None
    try:
        return [_grupo_from_dict(item) for item in json.loads(raw)]
    except (json.JSONDecodeError, TypeError, KeyError):
        logger.warning("action=botellas_duplicados_cache_read result=fail reason=payload_invalido")
        return None


async def guardar_cache_duplicados(grupos: list[GrupoBotellasDuplicadas]) -> None:
    """Best-effort — nunca rompe al caller si Redis no está disponible."""
    try:
        payload = json.dumps([_grupo_to_dict(g) for g in grupos])
        await get_redis().set(CACHE_KEY, payload, ex=CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning("action=botellas_duplicados_cache_write result=fail", exc_info=True)


async def encolar_recalculo_duplicados_botellas(motivo: str) -> None:
    """Invalida la caché y encola un job de recálculo para el worker — best-effort, nunca lanza.
    Llamar SIEMPRE después de confirmar la mutación (después de `session.commit()`), nunca antes."""
    try:
        client = get_redis()
        await client.delete(CACHE_KEY)
        await client.rpush(
            QUEUE_KEY,
            json.dumps({"kind": JOB_KIND_BOTELLAS_DUPLICADOS, "motivo": motivo}),
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "action=botellas_duplicados_recompute_enqueue result=fail motivo=%s", motivo, exc_info=True
        )


__all__ = [
    "CACHE_KEY",
    "QUEUE_KEY",
    "JOB_KIND_BOTELLAS_DUPLICADOS",
    "leer_cache_duplicados",
    "guardar_cache_duplicados",
    "encolar_recalculo_duplicados_botellas",
]
```

- [ ] **Step 4: Escribir los tests**

`tests/test_botella_recompute_queue.py` — mockear `core.cache.redis_client.get_redis` con un fake
mínimo (no una librería nueva de test), siguiendo el patrón "sin DB/servicio real" ya usado en
`tests/test_web_botellas_admin.py`:
```python
# Nombre de archivo: test_botella_recompute_queue.py
# Ubicación de archivo: tests/test_botella_recompute_queue.py
# Descripción: Pruebas de la caché/cola de recálculo de Botellas duplicadas — Redis mockeado, sin instancia real

from __future__ import annotations

import json

import pytest

from core.services import botella_recompute_queue as queue_mod
from core.services.botella_duplicados_service import BotellaDuplicadaItem, GrupoBotellasDuplicadas


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.fail = False

    async def get(self, key: str):
        if self.fail:
            raise ConnectionError("redis caído")
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        if self.fail:
            raise ConnectionError("redis caído")
        self.store[key] = value

    async def delete(self, key: str):
        if self.fail:
            raise ConnectionError("redis caído")
        self.store.pop(key, None)

    async def rpush(self, key: str, value: str):
        if self.fail:
            raise ConnectionError("redis caído")
        self.lists.setdefault(key, []).append(value)


def _grupo() -> GrupoBotellasDuplicadas:
    return GrupoBotellasDuplicadas(
        camara_padre_id=1,
        camara_padre_nombre="Camara Test",
        clave_normalizada="bot 1",
        criterio="nombre",
        miembros=[BotellaDuplicadaItem(origen="cromo", id=100, nombre="Bot 1", estado="LIBRE")],
        estados_en_conflicto=False,
        estado_mas_restrictivo="LIBRE",
        resoluble=False,
    )


@pytest.fixture()
def fake_redis(monkeypatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(queue_mod, "get_redis", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_cache_miss_devuelve_none(fake_redis: _FakeRedis) -> None:
    assert await queue_mod.leer_cache_duplicados() is None


@pytest.mark.asyncio
async def test_guardar_y_leer_cache_roundtrip(fake_redis: _FakeRedis) -> None:
    grupos = [_grupo()]
    await queue_mod.guardar_cache_duplicados(grupos)
    leidos = await queue_mod.leer_cache_duplicados()
    assert leidos is not None
    assert leidos[0].camara_padre_id == 1
    assert leidos[0].miembros[0].nombre == "Bot 1"


@pytest.mark.asyncio
async def test_redis_caido_no_rompe_lectura(fake_redis: _FakeRedis) -> None:
    fake_redis.fail = True
    assert await queue_mod.leer_cache_duplicados() is None


@pytest.mark.asyncio
async def test_redis_caido_no_rompe_encolado(fake_redis: _FakeRedis) -> None:
    fake_redis.fail = True
    await queue_mod.encolar_recalculo_duplicados_botellas(motivo="test")  # no debe lanzar


@pytest.mark.asyncio
async def test_encolar_invalida_y_encola(fake_redis: _FakeRedis) -> None:
    fake_redis.store[queue_mod.CACHE_KEY] = json.dumps([])
    await queue_mod.encolar_recalculo_duplicados_botellas(motivo="consolidar n_id=1")
    assert queue_mod.CACHE_KEY not in fake_redis.store
    jobs = fake_redis.lists[queue_mod.QUEUE_KEY]
    assert len(jobs) == 1
    payload = json.loads(jobs[0])
    assert payload == {"kind": "botellas_duplicados", "motivo": "consolidar n_id=1"}
```

Si el proyecto no tiene `pytest-asyncio` instalado/configurado todavía, revisar `pytest.ini`/
`pyproject.toml`/`setup.cfg` — si falta el marker `asyncio_mode`, agregar `@pytest.mark.asyncio` está
bien siempre que `pytest-asyncio` esté en `requirements-dev.txt` (comprobar primero con
`pip show pytest-asyncio` en el venv activo; si no está, agregarlo pinneado, no `latest`).

- [ ] **Step 5: Correr los tests**

```bash
source .venv/bin/activate
pytest tests/test_botella_recompute_queue.py -v
```
Expected: todos los tests PASS.

- [ ] **Step 6: Commit**

```bash
git add core/cache/ core/services/botella_recompute_queue.py common-requirements.txt tests/test_botella_recompute_queue.py
git commit -m "feat(infra): cliente Redis + caché/cola de recálculo de Botellas duplicadas"
```

---

### Task 2: Caché de lectura en los 3 endpoints que calculan la agrupación

**Files:**
- Modify: `web/app/main.py` (3 call sites: `botellas_viewer_duplicados_web` ~línea 5331,
  `botellas_apropiar_masivo_web` ~línea 5479, `botellas_inconsistencias_exportar_web` ~línea 5647)
- Test: `tests/test_web_botellas_admin.py` (agregar casos nuevos)

**Interfaces:**
- Consumes: `leer_cache_duplicados`, `guardar_cache_duplicados` de Task 1
  (`core.services.botella_recompute_queue`).

Las líneas exactas de arriba son aproximadas (pueden haberse corrido por otros cambios recientes en
el archivo) — ubicar cada función por su firma (`async def botellas_viewer_duplicados_web`, etc.), no
por número de línea.

- [ ] **Step 1: Import**

Agregar cerca de los demás imports de `core.services.*` en `web/app/main.py`:
```python
from core.services.botella_recompute_queue import guardar_cache_duplicados, leer_cache_duplicados
```

- [ ] **Step 2: `botellas_viewer_duplicados_web` (GET viewer de duplicados)**

Reemplazar:
```python
        with SessionLocal() as session:
            grupos = detectar_grupos_duplicados_botellas(session)
            ids_cromo = [m.id for g in grupos for m in g.miembros if m.origen == "cromo"]
```
por:
```python
        with SessionLocal() as session:
            grupos = await leer_cache_duplicados()
            if grupos is None:
                grupos = detectar_grupos_duplicados_botellas(session)
                await guardar_cache_duplicados(grupos)
            ids_cromo = [m.id for g in grupos for m in g.miembros if m.origen == "cromo"]
```
El resto de la función (enriquecimiento con `tiene_cables_asociados_batch_sync` y el `JSONResponse`)
queda exactamente igual — ese enriquecimiento nunca se cachea, es barato y depende del estado actual
de cables.

- [ ] **Step 3: `botellas_apropiar_masivo_web` (POST apropiar-masivo)**

Reemplazar:
```python
        with SessionLocal() as session_deteccion:
            grupos = detectar_grupos_duplicados_botellas(session_deteccion)
```
por:
```python
        grupos = await leer_cache_duplicados()
        if grupos is None:
            with SessionLocal() as session_deteccion:
                grupos = detectar_grupos_duplicados_botellas(session_deteccion)
            await guardar_cache_duplicados(grupos)
```
El resto de la función (`resolubles = [...]`, el loop de apropiación, el `JSONResponse` final) queda
igual — esta ruta SIGUE necesitando `grupos` como insumo de su propia lógica; la caché sólo evita
recalcularlo si ya está tibio, nunca decide sin él.

- [ ] **Step 4: `botellas_inconsistencias_exportar_web` (GET export de inconsistencias)**

Mismo patrón que el Step 2, sobre:
```python
        with SessionLocal() as session:
            grupos = detectar_grupos_duplicados_botellas(session)
```
→
```python
        with SessionLocal() as session:
            grupos = await leer_cache_duplicados()
            if grupos is None:
                grupos = detectar_grupos_duplicados_botellas(session)
                await guardar_cache_duplicados(grupos)
```

- [ ] **Step 5: Tests — agregar a `tests/test_web_botellas_admin.py`**

Mockear `leer_cache_duplicados`/`guardar_cache_duplicados` a nivel de módulo (mismo estilo
`monkeypatch.setattr` que ya usa este archivo para `web_main.psycopg.connect`):
```python
def test_viewer_duplicados_usa_cache_si_hay_hit(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())

    grupo_cacheado = []  # lista vacía es un hit válido — distinto de None

    async def _fake_leer_cache():
        return grupo_cacheado

    llamado = {"detectar": False}

    def _fake_detectar(session):
        llamado["detectar"] = True
        return []

    monkeypatch.setattr(web_main, "leer_cache_duplicados", _fake_leer_cache)
    monkeypatch.setattr(
        "core.services.botella_duplicados_service.detectar_grupos_duplicados_botellas", _fake_detectar
    )

    client = TestClient(app)
    _login(client, "admin", "adminpass")
    res = client.get("/api/admin/infra/botellas/viewer/duplicados")
    assert res.status_code == 200
    assert res.json()["grupos"] == []
    assert llamado["detectar"] is False, "no debió recalcular con un cache hit"
```
Si `detectar_grupos_duplicados_botellas` se importa dentro de la función (`from core.services...
import detectar_grupos_duplicados_botellas`, patrón `import` local ya usado en este archivo — ver el
cuerpo real de `botellas_viewer_duplicados_web`), el monkeypatch tiene que apuntar al símbolo del
MÓDULO ORIGEN (`core.services.botella_duplicados_service.detectar_grupos_duplicados_botellas`), no a
un atributo de `web_main` — el `import` local reimporta el nombre real en cada llamada, así que
parchear el módulo origen es lo único que efectivamente intercepta la llamada. Agregar también el
caso simétrico "cache miss cae al cómputo síncrono" (mockear `_fake_leer_cache` para devolver `None`
y confirmar que `llamado["detectar"] is True`).

- [ ] **Step 6: Correr los tests**

```bash
source .venv/bin/activate
pytest tests/test_web_botellas_admin.py -v
```
Expected: todos PASS, incluidos los nuevos.

- [ ] **Step 7: Commit**

```bash
git add web/app/main.py tests/test_web_botellas_admin.py
git commit -m "feat(infra): leer de caché Redis antes de recalcular grupos de Botellas duplicadas"
```

---

### Task 3: Invalidación + encolado en los 7 endpoints mutadores

**Files:**
- Modify: `web/app/main.py` (7 funciones: `botellas_apropiar_web`, `botellas_apropiar_masivo_web`,
  `botellas_consolidar_web`, `botellas_eliminar_web`, `botella_repoblar_cables_web`,
  `botella_separar_padre_web`, `botella_actualizar_nombre_web`)
- Test: `tests/test_web_botellas_admin.py`

**Interfaces:**
- Consumes: `encolar_recalculo_duplicados_botellas` de Task 1
  (`core.services.botella_recompute_queue`).

**Patrón único, repetido 7 veces:** en cada una de las 7 funciones, ubicar el `return
JSONResponse({"ok": True, ...})` (o equivalente) que sigue inmediatamente a un `session.commit()`
exitoso, y agregar `await encolar_recalculo_duplicados_botellas(motivo="...")` en la línea anterior a
ese `return`. Nunca antes del `commit()` — si la transacción se revierte (excepción, rollback), no
hay nada que invalidar. El `motivo` es un string descriptivo corto para logs, no estructura de datos.

- [ ] **Step 1: Import**

Task 2 ya agregó `from core.services.botella_recompute_queue import guardar_cache_duplicados,
leer_cache_duplicados` en `web/app/main.py`. Extender ESA MISMA línea de import (no agregar una
segunda línea de import del mismo módulo) para que quede:
```python
from core.services.botella_recompute_queue import (
    encolar_recalculo_duplicados_botellas,
    guardar_cache_duplicados,
    leer_cache_duplicados,
)
```

- [ ] **Step 2: `botellas_consolidar_web` (ejemplo completo #1)**

Antes:
```python
            session.commit()
            logger.info(
                "action=botellas_consolidar user=%s destino=%s origenes=%s legados=%s "
                "alias_creados=%d alias_actualizados=%d repuntados=%d",
                username,
                resultado.id_destino_cromo,
                body.ids_origen_cromo,
                body.ids_legado,
                resultado.alias_creados,
                resultado.alias_actualizados,
                len(resultado.alias_repuntados),
            )
            return JSONResponse({
```
Después (una sola línea nueva, antes del `return`):
```python
            session.commit()
            logger.info(
                "action=botellas_consolidar user=%s destino=%s origenes=%s legados=%s "
                "alias_creados=%d alias_actualizados=%d repuntados=%d",
                username,
                resultado.id_destino_cromo,
                body.ids_origen_cromo,
                body.ids_legado,
                resultado.alias_creados,
                resultado.alias_actualizados,
                len(resultado.alias_repuntados),
            )
            await encolar_recalculo_duplicados_botellas(
                motivo=f"consolidar destino={resultado.id_destino_cromo} usuario={username}"
            )
            return JSONResponse({
```

- [ ] **Step 3: `botellas_apropiar_masivo_web` (ejemplo completo #2)**

Antes (justo después del `logger.info(...)` que ya existe al final de la función, antes del
`return JSONResponse({"ok": True, "total_grupos": ...})`):
```python
        logger.info(
            "action=botellas_apropiar_masivo user=%s total_grupos=%d grupos_resolubles=%d "
            "grupos_apropiados=%d grupos_con_error=%d",
            username,
            len(grupos),
            len(resolubles),
            grupos_apropiados,
            grupos_con_error,
        )
        return JSONResponse({
```
Después:
```python
        logger.info(
            "action=botellas_apropiar_masivo user=%s total_grupos=%d grupos_resolubles=%d "
            "grupos_apropiados=%d grupos_con_error=%d",
            username,
            len(grupos),
            len(resolubles),
            grupos_apropiados,
            grupos_con_error,
        )
        if grupos_apropiados > 0:
            await encolar_recalculo_duplicados_botellas(motivo=f"apropiar-masivo usuario={username}")
        return JSONResponse({
```
Nota: acá SÍ conviene condicionar a `grupos_apropiados > 0` — si ningún grupo se apropió, no cambió
nada que invalidar (a diferencia de las otras 6 funciones, que sólo llegan al `return` de éxito
cuando algo realmente mutó).

- [ ] **Step 4: las otras 5 funciones — mismo patrón, sin condición**

Para `botellas_apropiar_web`, `botellas_eliminar_web`, `botella_repoblar_cables_web`,
`botella_separar_padre_web` y `botella_actualizar_nombre_web`: ubicar el `session.commit()` (o el
punto donde el servicio de dominio ya persistió el cambio, si el commit ocurre dentro del servicio en
vez del endpoint — confirmarlo leyendo cada función) y agregar
`await encolar_recalculo_duplicados_botellas(motivo="<accion> usuario=<username>")` inmediatamente
antes del `return JSONResponse(...)` de éxito de cada una. El motivo debe identificar la acción
(`"apropiar legado_id=... cromo_n_id=..."`, `"eliminar origen=... id=..."`, `"repoblar-cables
n_id=..."`, `"separar-padre n_id=..."`, `"actualizar-nombre n_id=..."`) usando las variables ya
disponibles en cada función (`body`, `n_id`, `resultado`, etc. — ya están en scope, no hace falta
declarar nada nuevo).

- [ ] **Step 5: Tests — agregar a `tests/test_web_botellas_admin.py`**

Para al menos 2 de las 7 rutas (consolidar y una más, p. ej. eliminar), agregar un test que mockee
`encolar_recalculo_duplicados_botellas` con un `AsyncMock`/función fake que registre la llamada, y
verifique que se invoca exactamente una vez con un `motivo` no vacío tras una mutación exitosa, y que
NO se invoca si la mutación falla (p. ej. CSRF inválido, o el servicio de dominio lanza su excepción
de validación). Ejemplo para consolidar:
```python
def test_consolidar_exitoso_encola_recalculo(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setenv("TESTING", "true")
    llamadas = []

    async def _fake_encolar(motivo: str):
        llamadas.append(motivo)

    monkeypatch.setattr(web_main, "encolar_recalculo_duplicados_botellas", _fake_encolar)

    # ... setup de SessionLocal fake / datos mínimos para que consolidar_grupo_botellas resuelva OK
    # (reusar el fixture de sesión que ya use test_cromo_consolidacion_service.py si aplica, o un
    # stub de SessionLocal consistente con el resto de este archivo de test).

    client = TestClient(app)
    _login(client, "admin", "adminpass")
    res = client.post(
        "/api/infra/botellas/consolidar",
        json={"id_destino_cromo": 999, "ids_origen_cromo": [100], "csrf_token": "cualquiera"},
    )
    assert res.status_code == 200
    assert len(llamadas) == 1
```
El setup exacto de datos para que `consolidar_grupo_botellas` no falle por validación depende de
fixtures existentes en el archivo/otros tests de consolidar — si no hay uno reusable a nivel de
`main.py`, es válido simplificar el test a nivel de "CSRF inválido no encola" (ruta que sí es 100%
determinística sin DB) y dejar la cobertura del camino feliz al test de integración manual del plan
(sección Verificación), dejando una nota en el reporte del task en vez de forzar un fixture de DB real
en este archivo.

- [ ] **Step 6: Correr los tests**

```bash
source .venv/bin/activate
pytest tests/test_web_botellas_admin.py -v
```
Expected: todos PASS.

- [ ] **Step 7: Commit**

```bash
git add web/app/main.py tests/test_web_botellas_admin.py
git commit -m "feat(infra): invalidar caché y encolar recálculo tras mutar Botellas/duplicados"
```

---

### Task 4: Worker dedicado `botellas_recalculo_worker`

**Files:**
- Create: `modules/botellas_recalculo_worker/__init__.py`
- Create: `modules/botellas_recalculo_worker/config.py`
- Create: `modules/botellas_recalculo_worker/worker.py`
- Create: `modules/botellas_recalculo_worker/requirements.txt`
- Create: `deploy/docker/botellas_recalculo_worker.Dockerfile`
- Test: `tests/test_botellas_recalculo_worker.py`

**Interfaces:**
- Consumes: `core.cache.redis_client.get_redis`, constantes de
  `core.services.botella_recompute_queue` (`QUEUE_KEY`, `JOB_KIND_BOTELLAS_DUPLICADOS`),
  `guardar_cache_duplicados`, `detectar_grupos_duplicados_botellas`
  (`core.services.botella_duplicados_service`), `db.session.SessionLocal`.
- Produces: proceso standalone (`python -m modules.botellas_recalculo_worker.worker`) + FastAPI
  mínima con `GET /health` en el puerto `8097`.

- [ ] **Step 1: `config.py`**

```python
# Nombre de archivo: config.py
# Ubicación de archivo: modules/botellas_recalculo_worker/config.py
# Descripción: Constantes del worker dedicado de recálculo de grupos de Botellas duplicadas

from __future__ import annotations

NOMBRE_SERVICIO = "botellas_recalculo"
HEALTH_PORT = 8097
BLPOP_TIMEOUT_SECONDS = 5
```

`modules/botellas_recalculo_worker/__init__.py`:
```python
# Nombre de archivo: __init__.py
# Ubicación de archivo: modules/botellas_recalculo_worker/__init__.py
# Descripción: Inicializa el paquete del worker de recálculo de Botellas duplicadas
```

- [ ] **Step 2: `requirements.txt`**

Este worker no necesita nada más allá de lo que ya trae `focas-base:latest` (fastapi, uvicorn,
sqlalchemy, redis ya agregado en Task 1) — dejar el archivo presente pero vacío de paquetes extra,
mismo criterio que otros workers cuando no tienen dependencias propias:
```
# Sin dependencias propias — todo lo necesario ya está en focas-base:latest (incluye redis, ver
# Task 1 de docs/superpowers/plans/2026-08-21-botellas-duplicados-redis-ws.md)
```

- [ ] **Step 3: `worker.py`**

```python
# Nombre de archivo: worker.py
# Ubicación de archivo: modules/botellas_recalculo_worker/worker.py
# Descripción: Worker dedicado — consume la cola Redis de recálculo de Botellas duplicadas, recalcula y publica el aviso

"""Corre en su propio contenedor (mismo patrón que `modules/cromo_worker/`, pero sin scheduler: acá
el trigger es un job en una lista Redis, no un intervalo). Un solo loop asyncio hace `BLPOP` sobre
`admin:recompute:jobs`; el dispatch table de abajo tiene un único `kind` registrado hoy
(`botellas_duplicados`) — agregar uno nuevo (p. ej. para Cámaras duplicadas) es agregar una entrada
al dict, no rediseñar el loop."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

import uvicorn
from fastapi import FastAPI

from core.cache.redis_client import get_redis
from core.logging import setup_logging
from core.services.botella_duplicados_service import detectar_grupos_duplicados_botellas
from core.services.botella_recompute_queue import (
    QUEUE_KEY,
    guardar_cache_duplicados,
)
from db.session import SessionLocal
from modules.botellas_recalculo_worker.config import BLPOP_TIMEOUT_SECONDS, HEALTH_PORT, NOMBRE_SERVICIO

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGS_ROOT = Path(os.getenv("LOGS_DIR", "/app/Logs"))
logger = setup_logging(
    "botellas_recalculo_worker", LOG_LEVEL, enable_file=True, logs_dir=LOGS_ROOT,
    filename="botellas_recalculo_worker.log",
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

ADMIN_NOTIFICATIONS_CHANNEL = "admin-notifications"

_worker_status: dict = {
    "status": "starting",
    "service": NOMBRE_SERVICIO,
    "ultimo_job": None,
    "ultimo_error": None,
    "jobs_procesados": 0,
}
_loop_task: asyncio.Task | None = None


async def _recalcular_botellas_duplicados() -> None:
    with SessionLocal() as session:
        grupos = detectar_grupos_duplicados_botellas(session)
    await guardar_cache_duplicados(grupos)
    await get_redis().publish(
        ADMIN_NOTIFICATIONS_CHANNEL,
        json.dumps({
            "type": "botellas_duplicados_recalculado",
            "at": datetime.now(timezone.utc).isoformat(),
        }),
    )


DISPATCH: dict[str, Callable[[], Awaitable[None]]] = {
    "botellas_duplicados": _recalcular_botellas_duplicados,
}


async def _procesar_job(raw: str) -> None:
    try:
        payload = json.loads(raw)
        kind = payload.get("kind")
    except json.JSONDecodeError:
        logger.warning("action=botellas_recalculo_worker evento=job_invalido raw=%s", raw)
        return

    handler = DISPATCH.get(kind)
    if handler is None:
        logger.warning("action=botellas_recalculo_worker evento=kind_desconocido kind=%s", kind)
        return

    try:
        await handler()
        _worker_status["ultimo_job"] = payload
        _worker_status["jobs_procesados"] += 1
        _worker_status["ultimo_error"] = None
        logger.info("action=botellas_recalculo_worker evento=job_procesado kind=%s", kind)
    except Exception as exc:  # noqa: BLE001 - loop de background: no hay a quién propagar
        _worker_status["ultimo_error"] = str(exc)
        logger.exception("action=botellas_recalculo_worker evento=job_error kind=%s", kind)


async def _loop_principal() -> None:
    client = get_redis()
    while True:
        try:
            resultado = await client.blpop(QUEUE_KEY, timeout=BLPOP_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - Redis caído: reintentar tras una pausa, nunca morir
            logger.warning("action=botellas_recalculo_worker evento=blpop_error", exc_info=True)
            await asyncio.sleep(BLPOP_TIMEOUT_SECONDS)
            continue
        if resultado is None:
            continue  # timeout del BLPOP sin jobs — vuelta normal del loop
        _, raw = resultado
        await _procesar_job(raw)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    global _loop_task
    logger.info("action=botellas_recalculo_worker evento=iniciando")
    _loop_task = asyncio.create_task(_loop_principal())
    _worker_status["status"] = "ok"
    try:
        yield
    finally:
        if _loop_task is not None:
            _loop_task.cancel()
        logger.info("action=botellas_recalculo_worker evento=apagando")


app = FastAPI(title="botellas_recalculo_worker", lifespan=_lifespan)


@app.get("/health")
async def health() -> dict:
    return {**_worker_status, "time": datetime.now(timezone.utc).isoformat()}


def main() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=HEALTH_PORT, log_level="warning")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":  # pragma: no cover
    main()
```

- [ ] **Step 4: Dockerfile**

`deploy/docker/botellas_recalculo_worker.Dockerfile` (mirror exacto de
`deploy/docker/cromo_worker.Dockerfile`, sin el paso de `pip install` porque
`requirements.txt` de este worker no tiene paquetes reales):
```dockerfile
FROM focas-base:latest
# curl, tzdata y dependencias Python comunes (fastapi, uvicorn, redis, ...) ya están en focas-base.

COPY core/ /app/core/
COPY db/ /app/db/
COPY modules/__init__.py /app/modules/__init__.py
COPY modules/botellas_recalculo_worker/ /app/modules/botellas_recalculo_worker/

RUN chown -R focas:focas /app
USER focas

CMD ["python", "-m", "modules.botellas_recalculo_worker.worker"]
```

- [ ] **Step 5: Tests**

`tests/test_botellas_recalculo_worker.py` — probar `_procesar_job` con un fake Redis/fake
`SessionLocal`/fake `detectar_grupos_duplicados_botellas`, sin traer FastAPI ni uvicorn a los tests:
```python
# Nombre de archivo: test_botellas_recalculo_worker.py
# Ubicación de archivo: tests/test_botellas_recalculo_worker.py
# Descripción: Pruebas del dispatch de jobs del worker de recálculo de Botellas duplicadas — sin Redis/DB reales

from __future__ import annotations

import json

import pytest

from modules.botellas_recalculo_worker import worker as worker_mod


class _FakeRedisPublish:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str):
        self.published.append((channel, message))


@pytest.mark.asyncio
async def test_procesar_job_desconocido_no_lanza(monkeypatch) -> None:
    await worker_mod._procesar_job(json.dumps({"kind": "algo_inexistente"}))  # no debe lanzar


@pytest.mark.asyncio
async def test_procesar_job_invalido_no_lanza() -> None:
    await worker_mod._procesar_job("no es json")  # no debe lanzar


@pytest.mark.asyncio
async def test_recalcular_botellas_duplicados_publica_evento(monkeypatch) -> None:
    fake_redis = _FakeRedisPublish()
    monkeypatch.setattr(worker_mod, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(worker_mod, "detectar_grupos_duplicados_botellas", lambda session: [])

    async def _fake_guardar(grupos):
        return None

    monkeypatch.setattr(worker_mod, "guardar_cache_duplicados", _fake_guardar)

    class _FakeSessionLocal:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(worker_mod, "SessionLocal", lambda: _FakeSessionLocal())

    await worker_mod._recalcular_botellas_duplicados()

    assert len(fake_redis.published) == 1
    channel, message = fake_redis.published[0]
    assert channel == "admin-notifications"
    payload = json.loads(message)
    assert payload["type"] == "botellas_duplicados_recalculado"
    assert "at" in payload


@pytest.mark.asyncio
async def test_procesar_job_kind_valido_actualiza_status(monkeypatch) -> None:
    llamado = {"veces": 0}

    async def _fake_handler():
        llamado["veces"] += 1

    monkeypatch.setitem(worker_mod.DISPATCH, "botellas_duplicados", _fake_handler)
    await worker_mod._procesar_job(json.dumps({"kind": "botellas_duplicados"}))
    assert llamado["veces"] == 1
```

- [ ] **Step 6: Correr los tests**

```bash
source .venv/bin/activate
pytest tests/test_botellas_recalculo_worker.py -v
```
Expected: todos PASS.

- [ ] **Step 7: Commit**

```bash
git add modules/botellas_recalculo_worker/ deploy/docker/botellas_recalculo_worker.Dockerfile tests/test_botellas_recalculo_worker.py
git commit -m "feat(infra): worker dedicado botellas_recalculo_worker (cola Redis + recálculo + publish)"
```

---

### Task 5: Canal WebSocket `admin-notifications`

**Files:**
- Create: `web/admin_ws.py`
- Modify: `web/app/main.py` (mount + startup/shutdown del subscriber)
- Test: `tests/test_web_admin_ws.py`

**Interfaces:**
- Produces:
  `web.admin_ws.mount_admin_websocket(app: FastAPI, *, allowed_origins: list[str], logger: logging.Logger) -> None`
  (mismo estilo que `mount_chat_websocket` de `web/chat_ws.py`, incluido el chequeo de origen).
- Consumes: `core.cache.redis_client.get_redis`, `CHAT_ALLOWED_ORIGINS` ya calculado en
  `web/app/main.py` (ver Step 2 — se reusa, no se crea una env var nueva).

- [ ] **Step 1: `web/admin_ws.py`**

```python
# Nombre de archivo: admin_ws.py
# Ubicación de archivo: web/admin_ws.py
# Descripción: Canal WebSocket genérico de notificaciones admin — broadcast a todos los paneles conectados

"""A diferencia de `web/chat_ws.py` (1 conexión ↔ 1 orchestrator, sin registro), este canal necesita
hacer BROADCAST: cualquier proceso externo (el worker de recálculo, hoy; potencialmente otros a
futuro) publica en el canal Redis `admin-notifications` y este módulo reenvía el mensaje a TODAS las
conexiones WebSocket activas del panel admin — de ahí el `ConnectionManager` con un `set`, que
`chat_ws.py` no necesita."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect

from core.cache.redis_client import get_redis

ADMIN_NOTIFICATIONS_CHANNEL = "admin-notifications"
_TESTING_HEADER = "x-test-user"


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    def register(self, websocket: WebSocket) -> None:
        self._connections.add(websocket)

    def unregister(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        # Copia de la lista antes de iterar: un cliente puede desconectarse durante el broadcast.
        for connection in list(self._connections):
            try:
                await connection.send_json(message)
            except Exception:  # noqa: BLE001 - una conexión rota no debe tumbar el broadcast
                self.unregister(connection)


async def _get_admin_identity(websocket: WebSocket, allowed_origins: list[str]) -> str:
    session = getattr(websocket, "session", None) or {}
    username: Optional[str] = session.get("username") if isinstance(session, dict) else None
    role: str = session.get("role", "user") if isinstance(session, dict) else "user"

    if not username and os.getenv("TESTING", "false").lower() == "true":
        header_user = websocket.headers.get(_TESTING_HEADER)
        if header_user:
            parts = header_user.split(":", 1)
            username = parts[0]
            if len(parts) > 1:
                role = parts[1]

    # Mismo chequeo de origen que `web/chat_ws.py::_get_user_identity` — evita que otro sitio abra
    # este WebSocket autenticado por cookie de sesión (CSRF-vía-WS).
    origin = websocket.headers.get("origin")
    if allowed_origins and origin and origin not in allowed_origins:
        raise PermissionError("Origen no autorizado")

    if not username:
        raise PermissionError("Sesión no encontrada")
    if role != "admin":
        raise PermissionError("Permisos insuficientes")
    return username


async def _subscriber_loop(manager: ConnectionManager, logger: logging.Logger) -> None:
    """Se reintenta con backoff fijo si Redis no está disponible al arrancar o se cae — nunca tira
    abajo la app: si Redis nunca vuelve, el canal simplemente no emite nada más."""
    while True:
        try:
            client = get_redis()
            pubsub = client.pubsub()
            await pubsub.subscribe(ADMIN_NOTIFICATIONS_CHANNEL)
            logger.info("action=admin_ws_subscriber evento=suscripto canal=%s", ADMIN_NOTIFICATIONS_CHANNEL)
            async for mensaje in pubsub.listen():
                if mensaje.get("type") != "message":
                    continue
                try:
                    data = json.loads(mensaje["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("action=admin_ws_subscriber evento=mensaje_invalido")
                    continue
                await manager.broadcast(data)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - Redis caído/reconectando: loguear y reintentar
            logger.warning("action=admin_ws_subscriber evento=error_reintentando", exc_info=True)
            await asyncio.sleep(5)


def mount_admin_websocket(app: FastAPI, *, allowed_origins: list[str], logger: logging.Logger) -> None:
    router = APIRouter()
    manager = ConnectionManager()
    ws_logger = logger.getChild("admin_ws")
    app.state.admin_ws_manager = manager

    @router.websocket("/ws/admin-notifications")
    async def admin_notifications_endpoint(websocket: WebSocket) -> None:
        try:
            username = await _get_admin_identity(websocket, allowed_origins)
        except PermissionError as exc:
            await websocket.accept()
            ws_logger.warning("action=admin_ws_unauthorized reason=%s", exc)
            await websocket.close(code=4401, reason="No autorizado")
            return

        await websocket.accept()
        manager.register(websocket)
        ws_logger.info("action=admin_ws_connected user=%s", username)
        try:
            while True:
                await websocket.receive_text()  # el cliente no manda nada; sólo detecta desconexión
        except WebSocketDisconnect:
            ws_logger.info("action=admin_ws_disconnected user=%s", username)
        finally:
            manager.unregister(websocket)

    app.include_router(router)

    @app.on_event("startup")
    async def _start_admin_ws_subscriber() -> None:
        app.state.admin_ws_subscriber_task = asyncio.create_task(_subscriber_loop(manager, ws_logger))

    @app.on_event("shutdown")
    async def _stop_admin_ws_subscriber() -> None:
        task = getattr(app.state, "admin_ws_subscriber_task", None)
        if task is not None:
            task.cancel()


__all__ = ["ConnectionManager", "mount_admin_websocket", "ADMIN_NOTIFICATIONS_CHANNEL"]
```

- [ ] **Step 2: Mount en `web/app/main.py`**

Junto al import de `mount_chat_websocket` (cerca de la línea 31):
```python
from web.admin_ws import mount_admin_websocket
```
Junto a la llamada a `mount_chat_websocket(...)` (cerca de la línea 240), inmediatamente después,
reusando el mismo `CHAT_ALLOWED_ORIGINS` ya calculado ahí arriba (es el origen del propio panel — no
hace falta una variable de entorno separada para este segundo canal):
```python
mount_admin_websocket(app, allowed_origins=CHAT_ALLOWED_ORIGINS, logger=logger)
```

- [ ] **Step 3: Tests**

`tests/test_web_admin_ws.py`, mismo patrón que `tests/test_web_chat.py` (`client.websocket_connect`
+ header `X-Test-User` con `TESTING=true`):
```python
# Nombre de archivo: test_web_admin_ws.py
# Ubicación de archivo: tests/test_web_admin_ws.py
# Descripción: Pruebas del canal WebSocket de notificaciones admin — auth y broadcast, sin Redis real

from __future__ import annotations

from starlette.websockets import WebSocketDisconnect
import pytest
from fastapi.testclient import TestClient

from web.admin_ws import ConnectionManager
from web.app.main import app

client = TestClient(app)


def test_admin_ws_sin_identidad_devuelve_4401(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "true")
    with client.websocket_connect("/ws/admin-notifications") as websocket:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()
        assert exc_info.value.code == 4401


def test_admin_ws_no_admin_devuelve_4401(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "true")
    with client.websocket_connect(
        "/ws/admin-notifications", headers={"X-Test-User": "user1:user"}
    ) as websocket:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()
        assert exc_info.value.code == 4401


@pytest.mark.asyncio
async def test_connection_manager_broadcast_ignora_conexion_rota() -> None:
    manager = ConnectionManager()

    class _Rota:
        async def send_json(self, message):
            raise RuntimeError("conexión cerrada")

    class _Ok:
        def __init__(self):
            self.recibido = None

        async def send_json(self, message):
            self.recibido = message

    rota, ok = _Rota(), _Ok()
    manager.register(rota)
    manager.register(ok)
    await manager.broadcast({"type": "test"})
    assert ok.recibido == {"type": "test"}
```
El caso de "admin conectado recibe un broadcast real" (login admin real + conectar WS + publicar en
Redis fake + verificar que llega) requiere levantar `_subscriber_loop` en el test, lo que implica un
Redis fake compatible con `pubsub()`/`.listen()` — más complejo que lo que amerita este task; queda
cubierto por la verificación manual real de la sección Verificación del plan (Task 9), no por un test
unitario acá.

- [ ] **Step 4: Correr los tests**

```bash
source .venv/bin/activate
pytest tests/test_web_admin_ws.py -v
```
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add web/admin_ws.py web/app/main.py tests/test_web_admin_ws.py
git commit -m "feat(infra): canal WebSocket admin-notifications con broadcast a paneles conectados"
```

---

### Task 6: Docker Compose — Redis + worker en dev y prod (código, sin recrear prod)

**Files:**
- Modify: `deploy/docker-compose.dev.yml`
- Modify: `deploy/compose.yml`
- Create: `.secrets/Dev_redis_password_v1.txt`

**Interfaces:** ninguna (infraestructura pura).

- [ ] **Step 1: Generar el secret de dev**

```bash
openssl rand -base64 32 > .secrets/Dev_redis_password_v1.txt
chmod 600 .secrets/Dev_redis_password_v1.txt
```
Confirmar que `.secrets/` sigue cubierto por `.gitignore` (ya lo está — línea 8, `.secrets/`), así que
este archivo nunca se commitea. Para prod, este mismo paso queda documentado como pendiente (el
archivo real `redis_password_v1.txt` lo genera quien tenga acceso al servidor de prod al llegar la
ventana de mantenimiento) — no generar un valor de prod desde este entorno de desarrollo.

- [ ] **Step 2: `deploy/docker-compose.dev.yml` — servicio `redis`**

Agregar junto al servicio `postgres` (mismo nivel, dentro de `services:`):
```yaml
  redis:
    image: redis:7.4-alpine
    container_name: lasfocasdev-redis
    restart: unless-stopped
    command: ["sh", "-c", "redis-server --requirepass \"$$(cat /run/secrets/redis_password_v1)\""]
    secrets:
      - redis_password_v1
    expose:
      - "6379"
    healthcheck:
      test: ["CMD-SHELL", "redis-cli -a \"$$(cat /run/secrets/redis_password_v1)\" ping | grep -q PONG"]
      interval: 5s
      timeout: 5s
      retries: 20
    networks:
      - lasfocas_dev_net
```
Nota de sintaxis: en Docker Compose, `$` literal dentro de `command`/`healthcheck.test` se escapa
como `$$` para que no se interprete como variable de interpolación del propio Compose.

- [ ] **Step 3: `deploy/docker-compose.dev.yml` — servicio `botellas_recalculo_worker`**

Agregar junto a `cromo_worker` (mismo nivel):
```yaml
  botellas_recalculo_worker:
    build:
      context: ..
      dockerfile: deploy/docker/botellas_recalculo_worker.Dockerfile
    container_name: lasfocasdev-botellas-recalculo-worker
    user: "1001:1001"
    env_file:
      - ../.env.dev
    environment:
      POSTGRES_HOST: postgres
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      LOGS_DIR: /app/Logs
      TZ: America/Argentina/Buenos_Aires
      APP_TIMEZONE: America/Argentina/Buenos_Aires
    secrets:
      - db_password_v1
      - redis_password_v1
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    expose:
      - "8097"
    volumes:
      - ../Logs/dev:/app/Logs
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8097/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - lasfocas_dev_net
```

- [ ] **Step 4: `deploy/docker-compose.dev.yml` — servicio `web` (y cualquier otro que necesite Redis)**

Agregar `REDIS_HOST: redis` / `REDIS_PORT: "6379"` a las `environment:` del servicio `web`, y
`redis_password_v1` a sus `secrets:` (el proceso `web` necesita conectarse a Redis desde Task 1-3). Si
`web` ya `depends_on: postgres (healthy)`, agregar también `redis: condition: service_healthy` a esa
misma lista.

- [ ] **Step 5: `deploy/docker-compose.dev.yml` — bloque `secrets:` de nivel superior**

Agregar junto a `db_password_v1`:
```yaml
  redis_password_v1:
    file: ../.secrets/Dev_redis_password_v1.txt
```

- [ ] **Step 6: `deploy/compose.yml` (prod) — mismos dos servicios, mismo estilo que `postgres`/`api`**

Mismo contenido que los Steps 2-3, adaptado al estilo de prod ya visto en el bloque `postgres` de
`deploy/compose.yml` (sin sufijo `dev` en `container_name` — `lasfocas-redis`,
`lasfocas-botellas-recalculo-worker`—, red `lasfocas_net` en vez de `lasfocas_dev_net`, sin
`env_file: ../.env.dev`, usando el `.env`/mecanismo de env vars que ya use el resto de servicios de
`deploy/compose.yml`, y secret `redis_password_v1` apuntando a `../.secrets/redis_password_v1.txt`
sin prefijo `Dev_`, igual que `db_password_v1` en ese archivo). Agregar también `redis_password_v1` al
bloque `secrets:` de nivel superior de `deploy/compose.yml`, y las mismas env vars `REDIS_HOST`/
`REDIS_PORT`/secret al servicio `web` de prod.

**No ejecutar ningún comando `docker compose` contra `deploy/compose.yml` en este step** — es edición
de archivo únicamente. El archivo `.secrets/redis_password_v1.txt` de prod NO se crea desde este
entorno (ver Step 1).

- [ ] **Step 7: Validar sintaxis (dev)**

```bash
cd deploy && docker compose -f docker-compose.dev.yml config --quiet && echo "dev OK"
cd deploy && docker compose -f compose.yml config --quiet && echo "prod OK"
```
Expected: ambos comandos terminan sin error (`config --quiet` sólo valida y no imprime nada si es
válido). Si `compose.yml` de prod falla por variables de entorno de prod que no existen en este
entorno de desarrollo (`.env` real de prod no está presente acá), es esperable — confirmar que el
error es por falta de esas variables y no por un error de sintaxis YAML propio de este cambio.

- [ ] **Step 8: Levantar dev y verificar salud real**

```bash
cd deploy && docker compose -f docker-compose.dev.yml up -d --build redis botellas_recalculo_worker
docker compose -f docker-compose.dev.yml ps redis botellas_recalculo_worker
```
Expected: ambos servicios en estado `healthy`. Si `botellas_recalculo_worker` falla el build porque
`focas-base:latest` todavía no tiene `redis` instalado (Task 1 agregó la dependencia a
`common-requirements.txt`, pero la imagen base hay que reconstruirla), correr primero
`./scripts/build_base.sh` (o el comando equivalente de build de `focas-base` que use este repo) antes
de reintentar.

- [ ] **Step 9: Commit**

```bash
git add deploy/docker-compose.dev.yml deploy/compose.yml
git commit -m "feat(infra): agregar Redis + botellas_recalculo_worker a docker-compose (dev aplicado, prod listo sin recrear)"
```
El secret `.secrets/Dev_redis_password_v1.txt` NUNCA se agrega a git (está ignorado).

---

### Task 7: Composable Vue `useAdminNotifications`

**Files:**
- Create: `web/frontend/src/composables/useAdminNotifications.ts`

**Interfaces:**
- Produces: `useAdminNotifications(): { on(type: string, handler: () => void): () => void }` — el
  composable conecta/desconecta el WebSocket con el ciclo de vida del componente que lo llama
  (`onMounted`/`onUnmounted`), y expone `on(type, handler)` para suscribirse a un tipo de evento;
  devuelve una función de desuscripción.

No hay ningún framework de test de frontend configurado en este proyecto (confirmado: `package.json`
sin `vitest`/`jest`/`@vue/test-utils`, sin archivos `*.spec.ts` existentes) — este task no agrega uno
nuevo sólo para este composable; se verifica manualmente en el navegador como parte de la
Verificación del plan (última sección).

- [ ] **Step 1: Escribir el composable**

```typescript
// Nombre de archivo: useAdminNotifications.ts
// Ubicación de archivo: web/frontend/src/composables/useAdminNotifications.ts
// Descripción: Composable WebSocket genérico para notificaciones admin (/ws/admin-notifications)

import { onMounted, onUnmounted } from 'vue';

interface AdminNotification {
  type: string;
  [key: string]: unknown;
}

type Handler = (message: AdminNotification) => void;

const MAX_RECONNECT_ATTEMPTS = 6;
const BASE_DELAY_MS = 400;
const MAX_DELAY_MS = 15000;
const JITTER_MS = 250;

// Mismo patrón de backoff exponencial con jitter que web/frontend/src/chat/main.ts (único precedente
// de reconexión WS en este repo — no hay composable Vue previo que copiar).
function backoffDelay(attempt: number): number {
  const capped = Math.min(attempt, MAX_RECONNECT_ATTEMPTS);
  const delay = Math.min(Math.pow(2, capped) * BASE_DELAY_MS, MAX_DELAY_MS);
  return delay + Math.random() * JITTER_MS;
}

export function useAdminNotifications() {
  const handlers = new Map<string, Set<Handler>>();
  let socket: WebSocket | null = null;
  let attempt = 0;
  let allowReconnect = true;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function dispatch(message: AdminNotification): void {
    const forType = handlers.get(message.type);
    if (!forType) return;
    for (const handler of forType) handler(message);
  }

  function scheduleReconnect(): void {
    if (!allowReconnect) return;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    const delay = backoffDelay(attempt);
    attempt += 1;
    reconnectTimer = setTimeout(connect, delay);
  }

  function connect(): void {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${window.location.host}/ws/admin-notifications`);

    socket.onopen = () => {
      attempt = 0;
    };
    socket.onmessage = (event: MessageEvent<string>) => {
      try {
        dispatch(JSON.parse(event.data));
      } catch {
        // Mensaje no-JSON: se ignora, no es un error de conexión.
      }
    };
    socket.onclose = (event: CloseEvent) => {
      if (event.code === 4401) {
        allowReconnect = false;
        return;
      }
      scheduleReconnect();
    };
    socket.onerror = () => {
      socket?.close();
    };
  }

  function disconnect(): void {
    allowReconnect = false;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    socket?.close();
    socket = null;
  }

  onMounted(connect);
  onUnmounted(disconnect);

  function on(type: string, handler: Handler): () => void {
    if (!handlers.has(type)) handlers.set(type, new Set());
    handlers.get(type)!.add(handler);
    return () => handlers.get(type)?.delete(handler);
  }

  return { on };
}
```

- [ ] **Step 2: Commit**

```bash
git add web/frontend/src/composables/useAdminNotifications.ts
git commit -m "feat(web): composable useAdminNotifications — WS genérico con reconexión backoff"
```

---

### Task 8: Wiring en `AdminBotellasViewer.vue`

**Files:**
- Modify: `web/frontend/src/admin/views/AdminBotellasViewer.vue`

**Interfaces:**
- Consumes: `useAdminNotifications` de Task 7.

- [ ] **Step 1: Import y suscripción**

Agregar el import junto a los demás (cerca de la línea 265-274):
```typescript
import { useAdminNotifications } from '../../composables/useAdminNotifications';
```
En el cuerpo de `<script setup>`, junto a la declaración de las demás funciones/estado reactivo:
```typescript
const { on } = useAdminNotifications();
on('botellas_duplicados_recalculado', () => {
  void reloadDuplicados();
});
```
`reloadDuplicados()` ya existe (líneas 373-384) y ya maneja sus propios estados de loading/error — no
hace falta tocarla.

- [ ] **Step 2: Reemplazar los 3 reloads bloqueantes**

En `handleApropiada` (líneas 422-425): reemplazar
```typescript
async function handleApropiada(): Promise<void> {
  modalOpen.value = false;
  await Promise.all([reloadDuplicados(), reloadFromZero()]);
}
```
por
```typescript
async function handleApropiada(): Promise<void> {
  modalOpen.value = false;
  await reloadFromZero();
}
```
(`reloadDuplicados()` ya no se llama de forma bloqueante acá — llega vía el evento WS cuando el
worker termine. `reloadFromZero()` sigue siendo síncrono/inmediato porque pagina el listado general,
no el cálculo pesado de duplicados.)

En `confirmarApropiacionMasiva` (líneas 433-448): reemplazar la línea
```typescript
    await Promise.all([reloadDuplicados(), reloadFromZero()]);
```
por
```typescript
    await reloadFromZero();
```
(mismo criterio — el mensaje `resultadoMasiva.value` con el resumen de la operación ya se sigue
mostrando igual, sólo cambia de dónde viene el refresh de `grupos`).

En `handleConsolidado` (líneas 464-466): reemplazar
```typescript
async function handleConsolidado(): Promise<void> {
  await Promise.all([reloadDuplicados(), reloadFromZero()]);
}
```
por
```typescript
async function handleConsolidado(): Promise<void> {
  await reloadFromZero();
}
```

- [ ] **Step 3: Botón manual de refresco (fallback si el WS no está disponible)**

Confirmar que ya existe un botón/acción manual para recargar `grupos` (revisar el `<template>` del
componente — buscar algo tipo "Actualizar"/"Recargar" cerca de la sección de duplicados). Si no
existe ninguno, agregar un botón que llame a `reloadDuplicados()` directamente en la barra de la
sección de duplicados, visible siempre (no sólo cuando el WS falla) — así el usuario nunca depende
100% del WebSocket para ver datos frescos.

- [ ] **Step 4: Verificación manual en navegador**

No hay test automatizado de frontend en este repo (ver Task 7). Verificar a mano, con
`docker compose -f deploy/docker-compose.dev.yml up` corriendo (Task 6) y el frontend en modo dev:
1. Abrir el visor de Botellas duplicados con la consola de red abierta.
2. Confirmar la conexión a `wss://.../ws/admin-notifications` (o `ws://` en dev sin TLS) en la pestaña
   de red.
3. Disparar una apropiación individual/masiva/consolidación real.
4. Confirmar que la respuesta HTTP de la mutación es inmediata (no espera al recálculo).
5. Confirmar que, unos instantes después, llega un mensaje WS `botellas_duplicados_recalculado` y que
   la lista de grupos se actualiza sola, sin recargar la página ni bloquear la UI.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/admin/views/AdminBotellasViewer.vue
git commit -m "feat(web): refetch silencioso de duplicados de Botellas vía WebSocket, no bloqueante"
```

---

### Task 9: Documentación

**Files:**
- Modify: `docs/infra.md`
- Modify: `docs/decisiones.md`

- [ ] **Step 1: `docs/infra.md`**

Agregar una subsección nueva en la sección de Botellas/duplicados (junto a la ya existente sobre
consolidación) describiendo: los 3 endpoints de lectura con caché Redis, los 7 endpoints que
invalidan+encolan, el worker `botellas_recalculo_worker`, el canal WebSocket
`admin-notifications`/`/ws/admin-notifications`, y el fallback (todo sigue funcionando síncrono si
Redis está caído). Enlazar a
`docs/superpowers/specs/2026-08-21-botellas-duplicados-redis-ws.md` para el detalle completo en vez
de duplicar toda la tabla de convenciones ahí.

- [ ] **Step 2: `docs/decisiones.md`**

Agregar una entrada fechada 2026-08-21 documentando: la premisa original del ticket (recalcular en el
hilo de "consolidar") no coincidía con el código real; el alcance real terminó siendo 7 endpoints
mutadores (no 6, corrección post-aprobación registrada acá); sólo `AdminBotellasViewer.vue` necesitó
el refetch WS; Redis+worker se agregaron a `deploy/compose.yml` de prod como código pero sin recrear
contenedores — decisión explícita del usuario, misma política que la migración de subred /24.

- [ ] **Step 3: Commit**

```bash
git add docs/infra.md docs/decisiones.md
git commit -m "docs(infra): documentar Redis + worker + WebSocket del visor de Botellas duplicadas"
```

---

## Verificación final (whole-branch, no por task)

- `pytest tests/ -k "botella or admin_ws"` con el venv activo — todos los tests nuevos y los
  existentes de Botellas siguen en verde.
- `docker compose -f deploy/docker-compose.dev.yml up -d --build` (stack completo) y
  `docker compose -f deploy/docker-compose.dev.yml ps` — todos los servicios `healthy`, incluidos
  `redis` y `botellas_recalculo_worker`.
- Apagar `redis` a propósito (`docker compose -f deploy/docker-compose.dev.yml stop redis`) y repetir
  una consolidación real desde la UI: debe seguir funcionando (fallback síncrono), sin 500 ni
  excepciones sin capturar en los logs de `web` ni del worker.
- Prender `redis` de nuevo, repetir la consolidación, y confirmar en los logs de
  `botellas_recalculo_worker` que consumió el job y publicó el evento, y en la UI que el refetch
  silencioso ocurrió sin que el usuario recargara la página.
