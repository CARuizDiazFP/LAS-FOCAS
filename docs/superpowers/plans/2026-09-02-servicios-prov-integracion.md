# Integración API PROV para Servicios — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consumir la API interna PROV (`API_Contexto_Servicio`) para enriquecer `Servicio` con datos de última milla y el historial completo de upgrades de ID, exponerlo por un endpoint de refresco on-demand, y mostrarlo en el frontend con un componente `ServiceTimeline.vue` genérico — sin retirar el flujo Excel existente.

**Architecture:** Paquete nuevo `core/services/prov/` (config + rate limiter + cliente httpx + lógica de ingesta) que reusa **sin modificar** `consolidar_identidad_servicio`/`resolver_estado_servicio`/`es_verificable_por_tipo_y_estado` de `core/services/servicios_consolidacion_service.py`. Dos tablas nuevas (`ServicioHistorialId`, `ServicioEquipoUltimaMilla`) que se reescriben completas en cada ingesta/refresh, porque PROV siempre devuelve el estado completo y vigente. Un endpoint nuevo (`POST /servicios/prov/refrescar`) y una extensión de `GET /servicios/detail` sirven los datos ya persistidos a un componente Vue 3 genérico por tipo de evento (`TimelineEvent`), pensado para admitir a futuro Reclamos/Ingresos/Mantenimientos.

**Tech Stack:** FastAPI async + SQLAlchemy (Postgres), Alembic, httpx (cliente async + Basic Auth), Vue 3 + TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-02-servicios-prov-integracion-design.md`

## Global Constraints

- El cliente PROV nunca supera 5 requests por segundo (`PROV_RATE_LIMIT_PER_SECOND`, default `5`) — se hace cumplir con `AsyncRateLimiter`, no con un simple `asyncio.sleep` disperso.
- El payload de PROV "sin contexto" (HTTP 200, `Resultado:` es un **string**, no un objeto) se traduce siempre a un 404 lógico (`ProvServicioNoEncontradoError` → `HTTPException(404)`), nunca a una excepción sin manejar.
- No modificar `core/services/servicios_consolidacion_service.py` — la ingesta PROV reusa `consolidar_identidad_servicio`/`resolver_estado_servicio`/`es_verificable_por_tipo_y_estado` tal cual están.
- No retirar ni modificar `POST /servicios/ingest` (Excel) — coexistencia temporal, decisión explícita del usuario.
- `ServicioHistorialId`/`ServicioEquipoUltimaMilla` se reescriben completas (delete + reinsert) en cada ingesta — PROV nunca da un delta, siempre el estado completo vigente.
- Los dos JSON reales de PROV consultados durante el diseño (con razón social/domicilio de clientes reales) **no se commitean** — los tests usan fixtures sintéticas con la misma forma.
- Backend: `source .venv/bin/activate` antes de correr pytest/alembic. Los tests que golpean Postgres real (`tests/test_servicios_*_routes.py`) no corren en este shell si `POSTGRES_HOST` no apunta al Postgres de dev — se verifican contra los contenedores (`lasfocasdev-postgres`/`lasfocasdev-api`), igual que el resto de la suite de Servicios.
- Frontend: este proyecto no tiene test runner (no hay `.spec.ts`/vitest) — los cambios de Vue se verifican en el navegador contra `docker compose` de dev.

---

## Contexto adicional para quien ejecute este plan

Los dos payloads reales de PROV consultados durante el diseño (ver spec, sección "Datos reales de
PROV") fijan estos mapeos, que todas las tareas de abajo dan por hechos:

- `nro_servicio` (top-level) = ID **vigente**; `nro_servicio_original` = ID más antiguo de la
  cadena. Corresponden exactamente a `Servicio.servicio_id`/`numero_linea` y
  `Servicio.numero_primer_servicio`.
- `cadena_upgrade[]` (cuando existe) trae, por eslabón: `nro_servicio`, `estado_comercial`,
  `fecha_instalacion`, `fecha_baja`, `motivo_baja`, `es_vigente`. Si no viene el array, el
  historial es una sola fila sintética con `nro_servicio_original` + `estado_comercial` +
  `creacion` del nivel superior.
- Los campos de última milla vienen sufijados `Nodo{N}`/`Equipo{N}`/`Port{N}`/`Direccion{N}`/
  `Provincia{N}` (`N` = 1 o 2) — la cardinalidad la decide el propio payload (si `Nodo2`/etc.
  vienen presentes), nunca una regla fija por `tipo_servicio`.
- `id_servicio` = `tipo_servicio` (RPV, EWS, INT, ISI, ISIS, TLS...); `Descripcion` = razón
  social/nombre de cliente.

El repo ya tiene un patrón de cliente HTTP async con reintentos (`core/services/cromo/client.py` +
`core/services/cromo/config.py`) que estas tareas calcan — PROV es más simple porque usa Basic Auth
directo (sin flujo OAuth2 de Cromo).

---

### Task 1: Modelos + migración — `ServicioHistorialId`, `ServicioEquipoUltimaMilla`, enum `INGEST_PROV`

**Files:**
- Modify: `db/models/infra.py`
- Create: `db/alembic/versions/20260902_01_servicios_prov_historial_equipos.py`

**Interfaces:**
- Produces: `ServicioHistorialId` (tabla `app.servicios_historial_id`), `ServicioEquipoUltimaMilla`
  (tabla `app.servicios_equipos_ultima_milla`), `Servicio.historial_ids`,
  `Servicio.equipos_ultima_milla` (relationships), `ServicioOrigenDatos.INGEST_PROV` — usados por
  Task 5, Task 6 y Task 7.

- [ ] **Step 1: Agregar `Date` al import de SQLAlchemy**

En `db/models/infra.py`, el import de `sqlalchemy` (cerca de la línea 10) lista `BigInteger,
Boolean, Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, JSON, String, Table,
Text, UniqueConstraint, text`. Agregar `Date` a esa lista (orden alfabético, entre `Column` y
`DateTime`):

```python
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
```

- [ ] **Step 2: Agregar `INGEST_PROV` al enum `ServicioOrigenDatos`**

En la clase `ServicioOrigenDatos` (cerca de la línea 65), agregar el nuevo valor al final:

```python
class ServicioOrigenDatos(str, Enum):
    """Origen de los datos de un Servicio — distingue un servicio real (alta manual, ingest SLA por
    Excel, tracking) de un placeholder sintetizado por el matching Cromo↔Servicio (2026-08-14, ver
    `core/services/cromo/ingesta.py::fase_servicios`). Las 1.488 filas existentes antes de este campo
    quedaron en `MANUAL` uniforme (no reconstruible con certeza cuáles vinieron de tracking vs. Excel,
    ver `docs/decisiones.md`). `TRACKING` está en el vocabulario pero ningún código lo emite todavía —
    `core/services/infra_service.py`/`upload_tracking` sigue sin fijarlo explícito."""

    MANUAL = "MANUAL"
    TRACKING = "TRACKING"
    INGEST_EXCEL = "INGEST_EXCEL"
    INFERIDO_CROMO = "INFERIDO_CROMO"  # Placeholder sintetizado por el matching Cromo (nombre, no dato real)
    INGEST_PROV = "INGEST_PROV"  # Servicio enriquecido/actualizado por la integración con la API PROV
```

- [ ] **Step 3: Agregar las relaciones nuevas a `Servicio`**

En la clase `Servicio`, después del bloque de la relación `empalmes` (justo antes de `def
__repr__`), agregar:

```python
    # DEPRECATED: Relación directa servicio<->empalme (mantener por retrocompatibilidad)
    empalmes = relationship(
        "Empalme",
        secondary=servicio_empalme_association,
        back_populates="servicios",
    )

    historial_ids = relationship(
        "ServicioHistorialId",
        back_populates="servicio",
        cascade="all, delete-orphan",
        order_by="ServicioHistorialId.orden",
    )

    equipos_ultima_milla = relationship(
        "ServicioEquipoUltimaMilla",
        back_populates="servicio",
        cascade="all, delete-orphan",
        order_by="ServicioEquipoUltimaMilla.extremo",
    )

    def __repr__(self) -> str:
```

- [ ] **Step 4: Agregar las dos clases nuevas**

Inmediatamente después del cierre de la clase `Servicio` (después del método `todos_los_empalmes`,
antes de `class Ingreso(Base):`), agregar:

```python
class ServicioHistorialId(Base):
    """Un eslabón de la cadena de upgrades de ID de un Servicio, según PROV (`cadena_upgrade`).

    Se reescribe completo (delete + reinsert) en cada ingesta/refresh desde PROV — PROV siempre
    devuelve la cadena completa y vigente, nunca un delta. No reemplaza `Servicio.alias_ids` (que
    sigue siendo la fuente para `consolidar_identidad_servicio`): esta tabla existe porque
    `alias_ids` es un array plano de strings que no puede guardar fecha/motivo/estado por ID (ver
    docs/superpowers/specs/2026-09-02-servicios-prov-integracion-design.md).
    """

    __tablename__ = "servicios_historial_id"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    servicio_id = Column(Integer, ForeignKey("app.servicios.id", ondelete="CASCADE"), nullable=False, index=True)
    numero_id = Column(String(64), nullable=False)
    orden = Column(Integer, nullable=False)  # 0 = vigente, crece hacia atrás en la cadena
    fecha_instalacion = Column(Date, nullable=True)
    fecha_baja = Column(Date, nullable=True)
    estado_comercial = Column(String(128), nullable=True)
    motivo_baja = Column(String(255), nullable=True)
    es_vigente = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    servicio = relationship("Servicio", back_populates="historial_ids")

    def __repr__(self) -> str:
        return f"<ServicioHistorialId id={self.id} servicio_id={self.servicio_id} numero_id='{self.numero_id}'>"


class ServicioEquipoUltimaMilla(Base):
    """Equipo/puerto de última milla de un extremo de un Servicio, según PROV (`Nodo{N}`/
    `Equipo{N}`/`Port{N}`). Cardinalidad 1 o 2 según el payload de PROV (no una regla fija por
    `tipo_servicio`): la mayoría de los servicios tiene un solo extremo; los que traen `Nodo2`/
    `Equipo2`/`Port2` tienen dos. Se reescribe completo (delete + reinsert) en cada ingesta/refresh.
    """

    __tablename__ = "servicios_equipos_ultima_milla"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    servicio_id = Column(Integer, ForeignKey("app.servicios.id", ondelete="CASCADE"), nullable=False, index=True)
    extremo = Column(Integer, nullable=False)  # 1 o 2
    nodo = Column(String(255), nullable=True)
    equipo = Column(String(255), nullable=True)
    puerto = Column(String(128), nullable=True)
    direccion = Column(String(255), nullable=True)
    provincia = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    servicio = relationship("Servicio", back_populates="equipos_ultima_milla")

    def __repr__(self) -> str:
        return f"<ServicioEquipoUltimaMilla id={self.id} servicio_id={self.servicio_id} extremo={self.extremo}>"


class Ingreso(Base):
```

- [ ] **Step 5: Escribir la migración**

Crear `db/alembic/versions/20260902_01_servicios_prov_historial_equipos.py`:

```python
# Nombre de archivo: 20260902_01_servicios_prov_historial_equipos.py
# Ubicación de archivo: db/alembic/versions/20260902_01_servicios_prov_historial_equipos.py
# Descripción: Nuevo valor INGEST_PROV en app.servicio_origen_datos + tablas servicios_historial_id y servicios_equipos_ultima_milla para la integración con la API PROV

"""INGEST_PROV + servicios_historial_id + servicios_equipos_ultima_milla

Revision ID: 20260902_01
Revises: 20260831_02
Create Date: 2026-09-02

Cambios:
- Nuevo valor en enum app.servicio_origen_datos: INGEST_PROV. El enum ya existe (creado en
  20260814_02) — este es un ALTER TYPE ... ADD VALUE, no una creación. No se usa dentro de esta
  misma migración, así que en rigor no hace falta autocommit_block (mismo caso ya documentado en
  20260810_01_camara_padre_botella.py para INFERIDO) — se envuelve igual por consistencia con el
  resto del repo.
- Tabla nueva app.servicios_historial_id: un eslabón por elemento de `cadena_upgrade` de PROV (o
  una fila sintética si PROV no trae el array).
- Tabla nueva app.servicios_equipos_ultima_milla: un equipo/puerto por extremo de última milla
  (1 o 2 según el payload de PROV).

Downgrade: elimina ambas tablas. INGEST_PROV no se puede quitar del enum en PostgreSQL 11+ (mismo
caso ya documentado en 20260811_01_cromo_botella_camara_padre.py).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260902_01"
down_revision = "20260831_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE app.servicio_origen_datos ADD VALUE IF NOT EXISTS 'INGEST_PROV'")

    op.create_table(
        "servicios_historial_id",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("numero_id", sa.String(64), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("fecha_instalacion", sa.Date(), nullable=True),
        sa.Column("fecha_baja", sa.Date(), nullable=True),
        sa.Column("estado_comercial", sa.String(128), nullable=True),
        sa.Column("motivo_baja", sa.String(255), nullable=True),
        sa.Column("es_vigente", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_index(
        "ix_servicios_historial_id_servicio_id",
        "servicios_historial_id",
        ["servicio_id"],
        schema="app",
    )

    op.create_table(
        "servicios_equipos_ultima_milla",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("extremo", sa.Integer(), nullable=False),
        sa.Column("nodo", sa.String(255), nullable=True),
        sa.Column("equipo", sa.String(255), nullable=True),
        sa.Column("puerto", sa.String(128), nullable=True),
        sa.Column("direccion", sa.String(255), nullable=True),
        sa.Column("provincia", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_index(
        "ix_servicios_equipos_ultima_milla_servicio_id",
        "servicios_equipos_ultima_milla",
        ["servicio_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_servicios_equipos_ultima_milla_servicio_id", table_name="servicios_equipos_ultima_milla", schema="app"
    )
    op.drop_table("servicios_equipos_ultima_milla", schema="app")
    op.drop_index("ix_servicios_historial_id_servicio_id", table_name="servicios_historial_id", schema="app")
    op.drop_table("servicios_historial_id", schema="app")
    # NOTA: no se puede revertir ADD VALUE en PostgreSQL 11+ — INGEST_PROV queda en el enum tras
    # el downgrade, mismo caso ya documentado en 20260811_01_cromo_botella_camara_padre.py.
```

- [ ] **Step 6: Aplicar la migración en dev y verificar contra la DB real**

```bash
source .venv/bin/activate
alembic -c db/alembic.ini upgrade head
```

Verificar:

```bash
export PGPASSWORD=$(cat .secrets/Dev_db_password_v1.txt)
docker exec -e PGPASSWORD="$PGPASSWORD" lasfocasdev-postgres psql -U FOCALBOT -d focas_dev -c "
\d app.servicios_historial_id
\d app.servicios_equipos_ultima_milla
SELECT unnest(enum_range(NULL::app.servicio_origen_datos));
"
```

Confirmar que ambas tablas existen con las columnas esperadas y que `INGEST_PROV` aparece en el
enum.

- [ ] **Step 7: Commit**

```bash
git add db/models/infra.py db/alembic/versions/20260902_01_servicios_prov_historial_equipos.py
git commit -m "feat(servicios): tablas historial_id/equipos_ultima_milla + enum INGEST_PROV para la integración PROV"
```

---

### Task 2: Configuración y secrets — `core/services/prov/config.py`

**Files:**
- Create: `core/services/prov/__init__.py`
- Create: `core/services/prov/config.py`
- Create: `tests/test_prov_config.py`
- Modify: `.env.dev` (agregar `PROV_BASE_URL`)
- Modify: `deploy/docker-compose.dev.yml` (secrets + servicio `api`)
- Rename: `.secrets/api_prov_user` → `.secrets/Dev_api_prov_user_v1.txt`
- Rename: `.secrets/api_prov_pass` → `.secrets/Dev_api_prov_pass_v1.txt`

**Interfaces:**
- Produces: `ProvConfig` (`base_url`, `user`, `password`, `timeout`, `rate_limit_per_second`),
  `ProvConfigError`, `get_prov_config()` — usados por Task 3 y Task 4.

- [ ] **Step 1: Crear el paquete**

```bash
mkdir -p core/services/prov
touch core/services/prov/__init__.py
```

- [ ] **Step 2: Escribir el test de configuración (falla primero)**

Crear `tests/test_prov_config.py`:

```python
# Nombre de archivo: test_prov_config.py
# Ubicación de archivo: tests/test_prov_config.py
# Descripción: Tests de validación de configuración del cliente PROV

from __future__ import annotations

import pytest

from core.services.prov.config import ProvConfigError, get_prov_config


@pytest.fixture(autouse=True)
def _limpiar_cache_config():
    get_prov_config.cache_clear()
    yield
    get_prov_config.cache_clear()


def test_get_prov_config_lee_variables_de_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROV_BASE_URL", "https://prov.metrotel.com.ar/api/v1/ADMEQ")
    monkeypatch.setenv("PROV_USER", "api-claude")
    monkeypatch.setenv("PROV_PASSWORD", "secreto123")
    monkeypatch.delenv("PROV_TIMEOUT", raising=False)
    monkeypatch.delenv("PROV_RATE_LIMIT_PER_SECOND", raising=False)

    config = get_prov_config()

    assert config.base_url == "https://prov.metrotel.com.ar/api/v1/ADMEQ"
    assert config.user == "api-claude"
    assert config.password == "secreto123"
    assert config.timeout == 30.0
    assert config.rate_limit_per_second == 5.0


def test_get_prov_config_falla_si_falta_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROV_BASE_URL", raising=False)
    monkeypatch.setenv("PROV_USER", "api-claude")
    monkeypatch.setenv("PROV_PASSWORD", "secreto123")

    with pytest.raises(ProvConfigError, match="PROV_BASE_URL"):
        get_prov_config()


def test_get_prov_config_falla_si_rate_limit_no_es_numerico(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROV_BASE_URL", "https://prov.metrotel.com.ar/api/v1/ADMEQ")
    monkeypatch.setenv("PROV_USER", "api-claude")
    monkeypatch.setenv("PROV_PASSWORD", "secreto123")
    monkeypatch.setenv("PROV_RATE_LIMIT_PER_SECOND", "no-numero")

    with pytest.raises(ProvConfigError, match="PROV_RATE_LIMIT_PER_SECOND"):
        get_prov_config()
```

- [ ] **Step 3: Confirmar que falla (módulo no existe)**

```bash
source .venv/bin/activate
python -m pytest -q tests/test_prov_config.py
```

Expected: FAIL con `ModuleNotFoundError: No module named 'core.services.prov.config'`.

- [ ] **Step 4: Implementar `core/services/prov/config.py`**

```python
# Nombre de archivo: config.py
# Ubicación de archivo: core/services/prov/config.py
# Descripción: Configuración desde entorno/secrets para el cliente de la API interna PROV, con validación al arranque

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from core.config import get_secret

_TIMEOUT_DEFAULT = 30.0
_RATE_LIMIT_DEFAULT = 5.0


class ProvConfigError(RuntimeError):
    """Configuración de PROV incompleta o inválida."""


@dataclass(slots=True)
class ProvConfig:
    """Configuración validada de acceso a la API PROV (`API_Contexto_Servicio`)."""

    base_url: str
    user: str
    password: str
    timeout: float
    rate_limit_per_second: float


def _construir_config() -> ProvConfig:
    base_url = os.getenv("PROV_BASE_URL", "").strip()
    user = get_secret("api_prov_user_v1", "PROV_USER").strip()
    password = get_secret("api_prov_pass_v1", "PROV_PASSWORD").strip()

    faltantes = [
        nombre
        for nombre, valor in (
            ("PROV_BASE_URL", base_url),
            ("api_prov_user_v1 (o PROV_USER)", user),
            ("api_prov_pass_v1 (o PROV_PASSWORD)", password),
        )
        if not valor
    ]
    if faltantes:
        raise ProvConfigError("Configuración de PROV incompleta. Definir: " + ", ".join(faltantes))

    try:
        timeout = float(os.getenv("PROV_TIMEOUT", str(_TIMEOUT_DEFAULT)))
    except ValueError as exc:
        raise ProvConfigError("PROV_TIMEOUT debe ser numérico") from exc

    try:
        rate_limit_per_second = float(os.getenv("PROV_RATE_LIMIT_PER_SECOND", str(_RATE_LIMIT_DEFAULT)))
    except ValueError as exc:
        raise ProvConfigError("PROV_RATE_LIMIT_PER_SECOND debe ser numérico") from exc
    if rate_limit_per_second <= 0:
        raise ProvConfigError("PROV_RATE_LIMIT_PER_SECOND debe ser mayor a 0")

    return ProvConfig(
        base_url=base_url,
        user=user,
        password=password,
        timeout=timeout,
        rate_limit_per_second=rate_limit_per_second,
    )


@lru_cache(maxsize=1)
def get_prov_config() -> ProvConfig:
    """Lee y valida la configuración de PROV desde variables de entorno/secrets (cacheada)."""
    return _construir_config()


__all__ = ["ProvConfig", "ProvConfigError", "get_prov_config"]
```

- [ ] **Step 5: Correr el test y confirmar que pasa**

```bash
python -m pytest -q tests/test_prov_config.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Renombrar los secrets de dev**

```bash
git mv .secrets/api_prov_user .secrets/Dev_api_prov_user_v1.txt
git mv .secrets/api_prov_pass .secrets/Dev_api_prov_pass_v1.txt
```

Si `.secrets/` no está trackeado por git (confirmar con `git status .secrets/` — estos dos
archivos aparecían como no trackeados antes de este plan), usar `mv` en vez de `git mv`.

- [ ] **Step 7: Agregar el bloque de secrets y la variable de entorno en dev**

En `deploy/docker-compose.dev.yml`, en el bloque `secrets:` de nivel superior (junto a
`cromo_password_v1`), agregar:

```yaml
  api_prov_user_v1:
    file: ../.secrets/Dev_api_prov_user_v1.txt
  api_prov_pass_v1:
    file: ../.secrets/Dev_api_prov_pass_v1.txt
```

En la lista `secrets:` del servicio `api` (junto a `slack_app_token_v1`), agregar:

```yaml
    secrets:
      - api_key_v1
      - db_password_v1
      - smtp_password_v1
      - slack_bot_token_v1
      - slack_app_token_v1
      - api_prov_user_v1
      - api_prov_pass_v1
```

En `.env.dev`, junto a las variables `CROMO_*`, agregar:

```
PROV_BASE_URL=https://prov.metrotel.com.ar/api/v1/ADMEQ
```

- [ ] **Step 8: Reconstruir el contenedor `api` y verificar que lee los secrets**

```bash
cd deploy
docker compose -f docker-compose.dev.yml --env-file ../.env.dev up -d --build api
docker exec lasfocasdev-api cat /run/secrets/api_prov_user_v1
cd ..
```

Confirmar que el contenido coincide con `.secrets/Dev_api_prov_user_v1.txt` (no imprimir el
contenido de `api_prov_pass_v1` en un log compartido — sólo confirmar que el archivo existe con
`docker exec lasfocasdev-api test -f /run/secrets/api_prov_pass_v1 && echo OK`).

- [ ] **Step 9: Commit**

`.env.dev` y todo `.secrets/` están gitignored en este repo (`.gitignore:6-8`, `.env.*` y
`.secrets/`) — igual que cada otro secreto/env del proyecto, nunca se commitean. Sólo se
commitean los archivos versionados; `.env.dev` y los dos secrets renombrados quedan aplicados
localmente (ya verificados contra el contenedor real en el Step 8), sin entrar al `git add`:

```bash
git add core/services/prov/__init__.py core/services/prov/config.py tests/test_prov_config.py \
  deploy/docker-compose.dev.yml
git commit -m "feat(prov): configuración validada del cliente PROV + secrets de dev"
```

---

### Task 3: Rate limiter — `core/services/prov/rate_limiter.py`

**Files:**
- Create: `core/services/prov/rate_limiter.py`
- Create: `tests/test_prov_rate_limiter.py`

**Interfaces:**
- Consumes: nada (módulo independiente).
- Produces: `AsyncRateLimiter(rate_per_second: float)`, método async `esperar_turno()`, soporta
  `async with limiter:` — usado por Task 4.

- [ ] **Step 1: Escribir el test (falla primero)**

Crear `tests/test_prov_rate_limiter.py`:

```python
# Nombre de archivo: test_prov_rate_limiter.py
# Ubicación de archivo: tests/test_prov_rate_limiter.py
# Descripción: Verifica que el limitador de PROV no deje pasar más operaciones por segundo que la tasa configurada — tiempo real, sin mockear asyncio.sleep

from __future__ import annotations

import asyncio
import time

from core.services.prov.rate_limiter import AsyncRateLimiter


def test_rate_limiter_no_supera_la_tasa_configurada() -> None:
    async def _correr() -> float:
        limiter = AsyncRateLimiter(rate_per_second=5.0)
        inicio = time.monotonic()
        for _ in range(6):
            async with limiter:
                pass
        return time.monotonic() - inicio

    elapsed = asyncio.run(_correr())
    # 6 operaciones a 5/s: las primeras 5 caben en el primer segundo, la 6ta empuja al siguiente.
    assert elapsed >= 1.0


def test_rate_limiter_no_espera_si_las_llamadas_ya_vienen_espaciadas() -> None:
    async def _correr() -> float:
        limiter = AsyncRateLimiter(rate_per_second=5.0)
        inicio = time.monotonic()
        async with limiter:
            pass
        await asyncio.sleep(0.25)  # más que el intervalo mínimo entre turnos (0.2s a 5/s)
        async with limiter:
            pass
        return time.monotonic() - inicio

    elapsed = asyncio.run(_correr())
    assert elapsed < 0.4


def test_rate_limiter_rechaza_tasa_no_positiva() -> None:
    import pytest

    with pytest.raises(ValueError):
        AsyncRateLimiter(rate_per_second=0)
```

- [ ] **Step 2: Confirmar que falla**

```bash
python -m pytest -q tests/test_prov_rate_limiter.py
```

Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `core/services/prov/rate_limiter.py`**

```python
# Nombre de archivo: rate_limiter.py
# Ubicación de archivo: core/services/prov/rate_limiter.py
# Descripción: Limitador de tasa en memoria de proceso (pacing uniforme) para no superar N operaciones por segundo

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import Optional


class AsyncRateLimiter:
    """Limita a `rate_per_second` operaciones por segundo, compartido entre corrutinas del mismo
    proceso vía `asyncio.Lock`. Implementación de pacing uniforme (cada turno se espacia
    `1/rate_per_second` segundos del anterior) — no permite ráfagas por encima de la tasa, lo cual
    hace la garantía más simple de verificar que un token bucket con capacidad.

    No coordina entre procesos distintos (ver nota operativa en
    docs/superpowers/specs/2026-09-02-servicios-prov-integracion-design.md) — alcanza para este uso
    porque el proceso de la API corre con un solo worker uvicorn (`api/Dockerfile`, sin
    `--workers`).
    """

    def __init__(self, rate_per_second: float) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second debe ser mayor a 0")
        self._intervalo = 1.0 / rate_per_second
        self._lock = asyncio.Lock()
        self._proximo_turno: Optional[float] = None

    async def esperar_turno(self) -> None:
        async with self._lock:
            ahora = time.monotonic()
            inicio = ahora if self._proximo_turno is None else max(ahora, self._proximo_turno)
            espera = inicio - ahora
            self._proximo_turno = inicio + self._intervalo
            if espera > 0:
                await asyncio.sleep(espera)

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self.esperar_turno()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        return None


__all__ = ["AsyncRateLimiter"]
```

- [ ] **Step 4: Correr los tests y confirmar que pasan**

```bash
python -m pytest -q tests/test_prov_rate_limiter.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/services/prov/rate_limiter.py tests/test_prov_rate_limiter.py
git commit -m "feat(prov): rate limiter de pacing uniforme para el cliente PROV"
```

---

### Task 4: Cliente PROV — `core/services/prov/client.py`

**Files:**
- Create: `core/services/prov/client.py`
- Create: `tests/test_prov_client.py`

**Interfaces:**
- Consumes: `ProvConfig`/`get_prov_config()` (Task 2), `AsyncRateLimiter` (Task 3).
- Produces: `ProvClient`, `ProvClientError`, `ProvServicioNoEncontradoError`,
  `get_prov_client()` (singleton de proceso), método async
  `obtener_contexto_servicio(nro_servicio: str) -> dict[str, Any]` — usado por Task 5, Task 6 y
  Task 7.

- [ ] **Step 1: Escribir el test (falla primero)**

Crear `tests/test_prov_client.py`:

```python
# Nombre de archivo: test_prov_client.py
# Ubicación de archivo: tests/test_prov_client.py
# Descripción: Pruebas del cliente HTTP de PROV (Basic Auth + payload "sin contexto" + reintentos) con httpx mockeado, sin red real

from __future__ import annotations

import httpx
import pytest

from core.services.prov.client import ProvClient, ProvClientError, ProvServicioNoEncontradoError
from core.services.prov.config import ProvConfig

BASE_URL = "http://prov.invalido.test/api/v1/ADMEQ"


def _config() -> ProvConfig:
    return ProvConfig(
        base_url=BASE_URL,
        user="user_test",
        password="pass_test",
        timeout=1.0,
        rate_limit_per_second=1000.0,  # alto en tests que no miden timing, para no frenarlos
    )


def _cliente_con_transport(transport: httpx.MockTransport) -> ProvClient:
    cliente_http = httpx.AsyncClient(base_url=BASE_URL, transport=transport)
    return ProvClient(config=_config(), cliente_http=cliente_http)


async def _sin_espera(*_args, **_kwargs) -> None:
    return None


@pytest.mark.asyncio
async def test_obtiene_contexto_servicio_con_basic_auth():
    capturado: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["auth"] = request.headers["Authorization"]
        capturado["nro_servicio"] = request.url.params["nro_servicio"]
        return httpx.Response(
            200,
            json={
                "Result": "Success",
                "Resultado:": {"nro_servicio": "122214", "estado_comercial": "INSTALADO"},
            },
        )

    cliente = _cliente_con_transport(httpx.MockTransport(handler))
    resultado = await cliente.obtener_contexto_servicio("122214")

    assert resultado == {"nro_servicio": "122214", "estado_comercial": "INSTALADO"}
    assert capturado["nro_servicio"] == "122214"
    assert capturado["auth"].startswith("Basic ")


@pytest.mark.asyncio
async def test_levanta_no_encontrado_cuando_resultado_es_un_string():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ProcessId": "srv-prov4-1",
                "DoneTime": "0.01",
                "Result": "Success",
                "Resultado:": "No hay contexto para el número de servicio ingresado",
            },
        )

    cliente = _cliente_con_transport(httpx.MockTransport(handler))

    with pytest.raises(ProvServicioNoEncontradoError) as exc_info:
        await cliente.obtener_contexto_servicio("000000")

    assert exc_info.value.nro_servicio == "000000"
    assert "No hay contexto" in exc_info.value.mensaje_prov


@pytest.mark.asyncio
async def test_reintenta_en_error_5xx_y_despues_tiene_exito(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.services.prov.client.asyncio.sleep", _sin_espera)
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if llamadas["n"] < 3:
            return httpx.Response(503, text="temporalmente no disponible")
        return httpx.Response(200, json={"Result": "Success", "Resultado:": {"nro_servicio": "1"}})

    cliente = _cliente_con_transport(httpx.MockTransport(handler))
    resultado = await cliente.obtener_contexto_servicio("1")

    assert llamadas["n"] == 3
    assert resultado == {"nro_servicio": "1"}


@pytest.mark.asyncio
async def test_agota_reintentos_y_levanta_prov_client_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.services.prov.client.asyncio.sleep", _sin_espera)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="caído")

    cliente = _cliente_con_transport(httpx.MockTransport(handler))

    with pytest.raises(ProvClientError):
        await cliente.obtener_contexto_servicio("1")


@pytest.mark.asyncio
async def test_error_4xx_no_reintenta_y_levanta_prov_client_error():
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(400, text="parámetro inválido")

    cliente = _cliente_con_transport(httpx.MockTransport(handler))

    with pytest.raises(ProvClientError) as exc_info:
        await cliente.obtener_contexto_servicio("1")

    assert llamadas["n"] == 1
    assert exc_info.value.status_code == 400
```

- [ ] **Step 2: Confirmar que falla**

```bash
python -m pytest -q tests/test_prov_client.py
```

Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `core/services/prov/client.py`**

```python
# Nombre de archivo: client.py
# Ubicación de archivo: core/services/prov/client.py
# Descripción: Cliente HTTP asíncrono para la API interna PROV (contexto de servicio), con Basic Auth, reintentos y rate limiting

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from types import TracebackType
from typing import Any, Optional

import httpx

from core.services.prov.config import ProvConfig, get_prov_config
from core.services.prov.rate_limiter import AsyncRateLimiter

logger = logging.getLogger(__name__)

_REINTENTOS_MAX = 3
_BACKOFF_BASE_SEGUNDOS = 1.0
_RUTA_CONTEXTO_SERVICIO = "/API_Contexto_Servicio"


class ProvClientError(RuntimeError):
    """Error de comunicación con PROV tras agotar los reintentos, o respuesta 4xx."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProvServicioNoEncontradoError(RuntimeError):
    """PROV respondió HTTP 200 pero sin contexto para el número de servicio consultado (payload
    `Resultado:` es un string, no un objeto)."""

    def __init__(self, nro_servicio: str, mensaje_prov: str) -> None:
        super().__init__(f"PROV no tiene contexto para el servicio {nro_servicio}: {mensaje_prov}")
        self.nro_servicio = nro_servicio
        self.mensaje_prov = mensaje_prov


class ProvClient:
    """Cliente de sólo lectura contra `API_Contexto_Servicio` de PROV. Basic Auth por request (sin
    token OAuth, a diferencia de `CromoClient`) y throttling compartido a
    `config.rate_limit_per_second`.
    """

    def __init__(
        self,
        config: Optional[ProvConfig] = None,
        cliente_http: Optional[httpx.AsyncClient] = None,
        limiter: Optional[AsyncRateLimiter] = None,
    ) -> None:
        self._config = config or get_prov_config()
        self._cliente_propio = cliente_http is None
        self._cliente = cliente_http or httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=httpx.Timeout(self._config.timeout),
        )
        # Basic Auth se aplica por-request (no en la construcción del AsyncClient): si
        # `cliente_http` viene inyectado (como en los tests, para mockear el transport),
        # aplicarlo sólo en la rama de auto-construcción lo dejaría sin auth — bug real
        # encontrado en la implementación de este Task, ver `_get`.
        self._auth = httpx.BasicAuth(self._config.user, self._config.password)
        self._limiter = limiter or AsyncRateLimiter(self._config.rate_limit_per_second)
        logger.info("action=prov_client_init evento=inicializado base_url=%s", self._config.base_url)

    async def cerrar(self) -> None:
        if self._cliente_propio:
            await self._cliente.aclose()

    async def __aenter__(self) -> "ProvClient":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.cerrar()

    async def obtener_contexto_servicio(self, nro_servicio: str) -> dict[str, Any]:
        """`GET /API_Contexto_Servicio?nro_servicio=...`.

        Lanza `ProvServicioNoEncontradoError` si PROV responde 200 con el payload de "sin
        contexto" (``Resultado:`` es un string en vez de un objeto). Devuelve el dict de
        ``Resultado:`` en el caso de éxito.
        """
        cuerpo = await self._get({"nro_servicio": nro_servicio})
        resultado = cuerpo.get("Resultado:")
        if isinstance(resultado, dict):
            return resultado
        mensaje = resultado if isinstance(resultado, str) else "respuesta de PROV sin campo 'Resultado:' reconocible"
        raise ProvServicioNoEncontradoError(nro_servicio, mensaje)

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        intento = 0
        while True:
            intento += 1
            await self._limiter.esperar_turno()
            try:
                respuesta = await self._cliente.get(_RUTA_CONTEXTO_SERVICIO, params=params, auth=self._auth)
            except httpx.TransportError as exc:
                if intento > _REINTENTOS_MAX:
                    logger.error(
                        "action=prov_get params=%s intento=%d resultado=agotado error=%s", params, intento, exc
                    )
                    raise ProvClientError(f"No se pudo contactar a PROV: {exc}") from exc
                espera = _BACKOFF_BASE_SEGUNDOS * (2 ** (intento - 1))
                logger.warning(
                    "action=prov_get params=%s intento=%d resultado=reintento_red espera=%.1f",
                    params, intento, espera,
                )
                await asyncio.sleep(espera)
                continue

            if respuesta.status_code >= 500:
                if intento > _REINTENTOS_MAX:
                    logger.error(
                        "action=prov_get params=%s intento=%d resultado=agotado status=%d",
                        params, intento, respuesta.status_code,
                    )
                    raise ProvClientError(f"PROV respondió {respuesta.status_code} tras {intento} intentos")
                espera = _BACKOFF_BASE_SEGUNDOS * (2 ** (intento - 1))
                logger.warning(
                    "action=prov_get params=%s intento=%d resultado=reintento_5xx status=%d espera=%.1f",
                    params, intento, respuesta.status_code, espera,
                )
                await asyncio.sleep(espera)
                continue

            if respuesta.status_code >= 400:
                logger.error(
                    "action=prov_get params=%s resultado=error_4xx status=%d", params, respuesta.status_code
                )
                raise ProvClientError(
                    f"PROV respondió {respuesta.status_code}: {respuesta.text}",
                    status_code=respuesta.status_code,
                )

            try:
                return respuesta.json()
            except ValueError as exc:
                raise ProvClientError(f"Respuesta de PROV no es JSON válido: {exc}") from exc


@lru_cache(maxsize=1)
def get_prov_client() -> ProvClient:
    """Instancia única de proceso — comparte el rate limiter entre todas las llamadas del mismo
    worker uvicorn (ver nota en `AsyncRateLimiter`)."""
    return ProvClient()


__all__ = ["ProvClient", "ProvClientError", "ProvServicioNoEncontradoError", "get_prov_client"]
```

- [ ] **Step 4: Correr los tests y confirmar que pasan**

```bash
python -m pytest -q tests/test_prov_client.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add core/services/prov/client.py tests/test_prov_client.py
git commit -m "feat(prov): cliente HTTP de PROV con Basic Auth, reintentos y 404 lógico"
```

---

### Task 5: Lógica de ingesta — `core/services/prov/ingesta.py`

**Files:**
- Create: `core/services/prov/ingesta.py`
- Create: `tests/test_prov_ingesta.py`

**Interfaces:**
- Consumes: `consolidar_identidad_servicio`/`resolver_estado_servicio`/
  `es_verificable_por_tipo_y_estado` (`core/services/servicios_consolidacion_service.py`, sin
  modificar), modelos `Servicio`/`ServicioHistorialId`/`ServicioEquipoUltimaMilla`/
  `ServicioOrigenDatos` (Task 1).
- Produces: `parsear_contexto_prov(contexto_raw: dict) -> ContextoProvParseado`,
  `async def ingerir_contexto_prov(session: AsyncSession, servicio: Servicio, contexto_raw: dict) -> None`
  — usado por Task 6 y Task 7.

- [ ] **Step 1: Escribir los tests de parseo (puros, sin DB) — fallan primero**

Crear `tests/test_prov_ingesta.py`:

```python
# Nombre de archivo: test_prov_ingesta.py
# Ubicación de archivo: tests/test_prov_ingesta.py
# Descripción: Tests puros del parseo del contexto de PROV (sin DB) — mapeo de campos, cadena de upgrades y fallback sin cadena

from __future__ import annotations

from datetime import date

from core.services.prov.ingesta import parsear_contexto_prov

_CONTEXTO_SIN_UPGRADES = {
    "id_servicio": "RPV",
    "nro_servicio": "122214",
    "nro_servicio_original": "122214",
    "estado_comercial": "INSTALADO",
    "creacion": "2026-07-14 15:47:15",
    "Descripcion": "BANCO MACRO SA",
    "Direccion1": "RECONQUISTA 590 P.1",
    "Provincia1": "Capital Federal",
    "Nodo1": "CLI_Reconquista590P1_BancoITAU",
    "Equipo1": "SW_Reconquista590P1_BancoITAU",
    "Port1": "GigabitEthernet1/0/5",
}

_CONTEXTO_CON_UPGRADES = {
    "id_servicio": "EWS",
    "nro_servicio": "63871",
    "nro_servicio_original": "15872",
    "nro_servicio_consultado": "15872",
    "nro_servicio_vigente": "63871",
    "fue_upgradeado": True,
    "estado_comercial": "INSTALADO",
    "Descripcion": "CONSEJO PROFESIONAL DE CIENCIAS ECONOMICAS CABA",
    "Direccion1": "AYACUCHO 652",
    "Provincia1": "Capital Federal",
    "Nodo1": "Paraguay2302_CABA",
    "Equipo1": "SW_3_Paraguay2302_CABA",
    "Port1": "6",
    "cadena_upgrade": [
        {
            "nro_servicio": "63871", "estado_comercial": "INSTALADO",
            "fecha_instalacion": "2019-11-01", "fecha_baja": None, "motivo_baja": "", "es_vigente": True,
        },
        {
            "nro_servicio": "46215", "estado_comercial": "DADO BAJA",
            "fecha_instalacion": "2017-11-23", "fecha_baja": "2019-11-01", "motivo_baja": "UPGRADE", "es_vigente": False,
        },
        {
            "nro_servicio": "15872", "estado_comercial": "DADO BAJA",
            "fecha_instalacion": "2012-04-23", "fecha_baja": "2017-11-23", "motivo_baja": "UPGRADE", "es_vigente": False,
        },
    ],
}


def test_parsea_contexto_sin_cadena_de_upgrades_sintetiza_una_fila() -> None:
    parseado = parsear_contexto_prov(_CONTEXTO_SIN_UPGRADES)

    assert parseado.nro_servicio_vigente == "122214"
    assert parseado.nro_servicio_original == "122214"
    assert parseado.tipo_servicio == "RPV"
    assert parseado.nombre_cliente == "BANCO MACRO SA"
    assert len(parseado.historial) == 1
    assert parseado.historial[0].numero_id == "122214"
    assert parseado.historial[0].orden == 0
    assert parseado.historial[0].es_vigente is True
    assert parseado.historial[0].fecha_instalacion == date(2026, 7, 14)

    assert len(parseado.equipos) == 1
    assert parseado.equipos[0].extremo == 1
    assert parseado.equipos[0].nodo == "CLI_Reconquista590P1_BancoITAU"
    assert parseado.equipos[0].puerto == "GigabitEthernet1/0/5"


def test_parsea_cadena_de_upgrades_completa_en_orden() -> None:
    parseado = parsear_contexto_prov(_CONTEXTO_CON_UPGRADES)

    assert parseado.nro_servicio_vigente == "63871"
    assert parseado.nro_servicio_original == "15872"
    assert len(parseado.historial) == 3

    assert parseado.historial[0].numero_id == "63871"
    assert parseado.historial[0].orden == 0
    assert parseado.historial[0].es_vigente is True
    assert parseado.historial[0].fecha_baja is None

    assert parseado.historial[2].numero_id == "15872"
    assert parseado.historial[2].orden == 2
    assert parseado.historial[2].fecha_instalacion == date(2012, 4, 23)
    assert parseado.historial[2].fecha_baja == date(2017, 11, 23)
    assert parseado.historial[2].motivo_baja == "UPGRADE"


def test_parsea_un_solo_extremo_cuando_no_hay_nodo2() -> None:
    parseado = parsear_contexto_prov(_CONTEXTO_CON_UPGRADES)
    assert len(parseado.equipos) == 1


def test_parsea_dos_extremos_cuando_el_payload_trae_nodo2() -> None:
    contexto = dict(_CONTEXTO_SIN_UPGRADES, Nodo2="NODO-B", Equipo2="SW-B", Port2="2", Direccion2="OTRA CALLE 456")
    parseado = parsear_contexto_prov(contexto)

    assert len(parseado.equipos) == 2
    assert parseado.equipos[1].extremo == 2
    assert parseado.equipos[1].nodo == "NODO-B"
    assert parseado.equipos[1].direccion == "OTRA CALLE 456"
```

- [ ] **Step 2: Confirmar que falla**

```bash
python -m pytest -q tests/test_prov_ingesta.py
```

Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar el parseo en `core/services/prov/ingesta.py`**

```python
# Nombre de archivo: ingesta.py
# Ubicación de archivo: core/services/prov/ingesta.py
# Descripción: Mapea el contexto de servicio de PROV a los campos/tablas de Servicio y aplica la consolidación de identidad ya existente

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.servicios_consolidacion_service import (
    consolidar_identidad_servicio,
    es_verificable_por_tipo_y_estado,
    resolver_estado_servicio,
)
from db.models.infra import Servicio, ServicioEquipoUltimaMilla, ServicioHistorialId, ServicioOrigenDatos

_TRADUCCION_ESTADO_COMERCIAL = {
    "INSTALADO": "Activo",
    "DADO BAJA": "Baja",
}


def _traducir_estado_comercial(estado_comercial: str | None) -> str:
    """Traduce el vocabulario de PROV (`estado_comercial`) al propio (`estado_servicio`).

    Sólo se conocen dos valores reales (ver los payloads verificados en
    docs/superpowers/specs/2026-09-02-servicios-prov-integracion-design.md); un valor nuevo no
    mapeado se pasa tal cual, en vez de perderlo silenciosamente, para poder detectarlo en datos
    reales y ampliar el diccionario.
    """
    if not estado_comercial:
        return "DESCONOCIDO"
    return _TRADUCCION_ESTADO_COMERCIAL.get(estado_comercial.strip().upper(), estado_comercial.strip())


def _a_fecha(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


@dataclass(slots=True)
class EslabonHistorial:
    numero_id: str
    orden: int
    fecha_instalacion: date | None
    fecha_baja: date | None
    estado_comercial: str | None
    motivo_baja: str | None
    es_vigente: bool


@dataclass(slots=True)
class EquipoUltimaMilla:
    extremo: int
    nodo: str | None
    equipo: str | None
    puerto: str | None
    direccion: str | None
    provincia: str | None


@dataclass(slots=True)
class ContextoProvParseado:
    nro_servicio_vigente: str
    nro_servicio_original: str
    tipo_servicio: str | None
    nombre_cliente: str | None
    estado_comercial: str | None
    historial: list[EslabonHistorial]
    equipos: list[EquipoUltimaMilla]


def parsear_contexto_prov(contexto_raw: dict[str, Any]) -> ContextoProvParseado:
    """Parsea el dict de `Resultado:` (ya validado como éxito por `ProvClient`)."""
    nro_servicio_vigente = str(contexto_raw.get("nro_servicio") or "").strip()
    nro_servicio_original = str(contexto_raw.get("nro_servicio_original") or nro_servicio_vigente).strip()

    cadena = contexto_raw.get("cadena_upgrade")
    historial: list[EslabonHistorial]
    if isinstance(cadena, list) and cadena:
        historial = [
            EslabonHistorial(
                numero_id=str(eslabon.get("nro_servicio") or "").strip(),
                orden=indice,
                fecha_instalacion=_a_fecha(eslabon.get("fecha_instalacion")),
                fecha_baja=_a_fecha(eslabon.get("fecha_baja")),
                estado_comercial=eslabon.get("estado_comercial"),
                motivo_baja=eslabon.get("motivo_baja") or None,
                es_vigente=bool(eslabon.get("es_vigente")),
            )
            for indice, eslabon in enumerate(cadena)
            if str(eslabon.get("nro_servicio") or "").strip()
        ]
    else:
        historial = [
            EslabonHistorial(
                numero_id=nro_servicio_original,
                orden=0,
                fecha_instalacion=_a_fecha(contexto_raw.get("creacion")),
                fecha_baja=None,
                estado_comercial=contexto_raw.get("estado_comercial"),
                motivo_baja=None,
                es_vigente=True,
            )
        ]

    equipos: list[EquipoUltimaMilla] = []
    for extremo in (1, 2):
        nodo = contexto_raw.get(f"Nodo{extremo}")
        equipo = contexto_raw.get(f"Equipo{extremo}")
        puerto = contexto_raw.get(f"Port{extremo}")
        direccion = contexto_raw.get(f"Direccion{extremo}")
        provincia = contexto_raw.get(f"Provincia{extremo}")
        if not any((nodo, equipo, puerto, direccion, provincia)):
            continue
        equipos.append(
            EquipoUltimaMilla(
                extremo=extremo, nodo=nodo, equipo=equipo, puerto=puerto, direccion=direccion, provincia=provincia
            )
        )

    return ContextoProvParseado(
        nro_servicio_vigente=nro_servicio_vigente,
        nro_servicio_original=nro_servicio_original,
        tipo_servicio=contexto_raw.get("id_servicio"),
        nombre_cliente=contexto_raw.get("Descripcion"),
        estado_comercial=contexto_raw.get("estado_comercial"),
        historial=historial,
        equipos=equipos,
    )
```

- [ ] **Step 4: Correr los tests de parseo y confirmar que pasan**

```bash
python -m pytest -q tests/test_prov_ingesta.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Agregar `ingerir_contexto_prov` (con DB) al mismo archivo**

Agregar al final de `core/services/prov/ingesta.py`:

```python
async def ingerir_contexto_prov(session: AsyncSession, servicio: Servicio, contexto_raw: dict[str, Any]) -> None:
    """Aplica un contexto de PROV ya obtenido a un `Servicio` existente, en memoria — el caller hace
    `session.commit()`. Reusa la consolidación de identidad y la regla de estado ya validadas para
    Excel (`servicios_consolidacion_service.py`, sin modificar): son agnósticas de la fuente.
    """
    parseado = parsear_contexto_prov(contexto_raw)

    # Todos los IDs de la cadena (salvo el vigente, que ya entra como `numero_linea_excel`) se
    # tratan como aliases ya conocidos — `consolidar_identidad_servicio` los combina con los
    # aliases existentes en DB y dedupe. No hace falta usar `linea_upgrade_de`/`linea_upgrade_a`
    # (esos parámetros modelan un puntero simple; PROV ya da la cadena completa).
    ids_de_la_cadena = {eslabon.numero_id for eslabon in parseado.historial if eslabon.numero_id}
    ids_de_la_cadena.discard(parseado.nro_servicio_vigente)
    alias_combinados = sorted(set(servicio.alias_ids or []) | ids_de_la_cadena)

    identidad = consolidar_identidad_servicio(
        numero_primer_servicio=parseado.nro_servicio_original,
        numero_linea_excel=parseado.nro_servicio_vigente,
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual=servicio.servicio_id,
        numero_linea_actual=servicio.numero_linea,
        alias_ids_actual=alias_combinados,
    )

    estado_prov = _traducir_estado_comercial(parseado.estado_comercial)
    servicio.estado_servicio = resolver_estado_servicio(
        estado_actual=servicio.estado_servicio,
        estado_excel=estado_prov,
        avanza_identidad=identidad.avanza_por_excel,
    )
    servicio.servicio_id = identidad.servicio_id
    servicio.numero_linea = identidad.numero_linea
    servicio.alias_ids = identidad.alias_ids
    if not servicio.numero_primer_servicio:
        servicio.numero_primer_servicio = parseado.nro_servicio_original

    if parseado.nombre_cliente:
        servicio.nombre_cliente = parseado.nombre_cliente
        servicio.cliente = parseado.nombre_cliente
    if parseado.tipo_servicio:
        servicio.tipo_servicio = parseado.tipo_servicio
    if parseado.equipos:
        primero = parseado.equipos[0]
        if primero.direccion:
            servicio.direccion = primero.direccion
        if primero.provincia:
            servicio.provincia = primero.provincia
        if len(parseado.equipos) > 1 and parseado.equipos[1].direccion:
            servicio.direccion_2 = parseado.equipos[1].direccion

    if servicio.es_verificable_override is not None:
        servicio.es_verificable = servicio.es_verificable_override
    else:
        servicio.es_verificable = es_verificable_por_tipo_y_estado(servicio.tipo_servicio, servicio.estado_servicio)

    # Mismo criterio que ya usa `POST /servicios/ingest`: cada ingesta re-etiqueta `origen_datos`
    # con su propia fuente incondicionalmente (ver `api/app/routes/servicios.py::ingest_servicios`,
    # `set_map["origen_datos"] = excluded.origen_datos`) — no hay una jerarquía de "orígenes más
    # autoritativos" implementada hoy en el repo.
    servicio.origen_datos = ServicioOrigenDatos.INGEST_PROV

    await session.execute(delete(ServicioHistorialId).where(ServicioHistorialId.servicio_id == servicio.id))
    for eslabon in parseado.historial:
        session.add(
            ServicioHistorialId(
                servicio_id=servicio.id,
                numero_id=eslabon.numero_id,
                orden=eslabon.orden,
                fecha_instalacion=eslabon.fecha_instalacion,
                fecha_baja=eslabon.fecha_baja,
                estado_comercial=eslabon.estado_comercial,
                motivo_baja=eslabon.motivo_baja,
                es_vigente=eslabon.es_vigente,
            )
        )

    await session.execute(
        delete(ServicioEquipoUltimaMilla).where(ServicioEquipoUltimaMilla.servicio_id == servicio.id)
    )
    for equipo in parseado.equipos:
        session.add(
            ServicioEquipoUltimaMilla(
                servicio_id=servicio.id,
                extremo=equipo.extremo,
                nodo=equipo.nodo,
                equipo=equipo.equipo,
                puerto=equipo.puerto,
                direccion=equipo.direccion,
                provincia=equipo.provincia,
            )
        )


__all__ = ["parsear_contexto_prov", "ingerir_contexto_prov", "ContextoProvParseado", "EslabonHistorial", "EquipoUltimaMilla"]
```

Nota: `ingerir_contexto_prov` no tiene test unitario propio en este Task porque requiere una
sesión de DB real y un `Servicio` con `id` asignado — se verifica de punta a punta en el Task 6
(tests de integración del endpoint) y en el Task 1/6 contra la DB real de dev.

- [ ] **Step 6: Commit**

```bash
git add core/services/prov/ingesta.py tests/test_prov_ingesta.py
git commit -m "feat(prov): mapeo de contexto PROV a Servicio/historial/equipos, reusando la consolidación de identidad existente"
```

---

### Task 6: Endpoints — refresco on-demand + extensión de `GET /servicios/detail`

**Files:**
- Modify: `api/app/routes/servicios.py`
- Create: `tests/test_servicios_prov_routes.py`

**Interfaces:**
- Consumes: `get_prov_client`, `ProvClientError`, `ProvServicioNoEncontradoError` (Task 4),
  `ingerir_contexto_prov` (Task 5), `Servicio.historial_ids`/`equipos_ultima_milla` (Task 1).
- Produces: `POST /servicios/prov/refrescar?id=...`, `GET /servicios/detail` extendido con
  `historial_ids`/`equipos_ultima_milla` — usados por Task 8/9/10 (frontend).

- [ ] **Step 1: Escribir los tests de integración (fallan primero)**

Crear `tests/test_servicios_prov_routes.py`:

```python
# Nombre de archivo: test_servicios_prov_routes.py
# Ubicación de archivo: tests/test_servicios_prov_routes.py
# Descripción: Tests de integración del endpoint de refresco on-demand desde PROV y de la extensión de GET /servicios/detail con historial_ids/equipos_ultima_milla

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import api.app.routes.servicios as servicios_routes
from api.app.main import app
from core.services.prov.client import ProvServicioNoEncontradoError
from db.session import SessionLocal

API_HEADERS = {"Authorization": "Bearer test-api-key"}

pytestmark = pytest.mark.skipif(
    os.getenv("CI") == "true",
    reason="requiere Postgres real alcanzable; el workflow de CI no tiene ese servicio configurado",
)

_NUMEROS_DE_TEST = ("900101", "900102", "900103")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _limpiar_servicios_de_test():
    yield
    with SessionLocal() as session:
        session.execute(
            text("DELETE FROM app.servicios WHERE numero_primer_servicio = ANY(:numeros ::varchar[])"),
            {"numeros": list(_NUMEROS_DE_TEST)},
        )
        session.commit()


def _crear_servicio(numero: str) -> None:
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.servicios "
                "(servicio_id, numero_primer_servicio, numero_linea, estado_servicio, tipo_servicio, origen_datos) "
                "VALUES (:numero, :numero, :numero, 'DESCONOCIDO', 'EWS', 'MANUAL'::app.servicio_origen_datos)"
            ),
            {"numero": numero},
        )
        session.commit()


class _ClientePROVFalso:
    def __init__(self, contexto: dict | None = None, error: Exception | None = None) -> None:
        self._contexto = contexto
        self._error = error

    async def obtener_contexto_servicio(self, nro_servicio: str) -> dict:
        if self._error:
            raise self._error
        return self._contexto


def test_refrescar_persiste_historial_y_equipos_de_una_cadena_de_upgrades(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _crear_servicio("900101")

    contexto = {
        "nro_servicio": "900101",
        "nro_servicio_original": "900101",
        "id_servicio": "EWS",
        "Descripcion": "CLIENTE DE PRUEBA SA",
        "estado_comercial": "INSTALADO",
        "Nodo1": "NODO-TEST",
        "Equipo1": "SW-TEST",
        "Port1": "1",
        "Direccion1": "CALLE FALSA 123",
        "Provincia1": "Buenos Aires",
        "cadena_upgrade": [
            {
                "nro_servicio": "900101",
                "estado_comercial": "INSTALADO",
                "fecha_instalacion": "2020-01-01",
                "fecha_baja": None,
                "motivo_baja": "",
                "es_vigente": True,
            }
        ],
    }
    monkeypatch.setattr(servicios_routes, "get_prov_client", lambda: _ClientePROVFalso(contexto=contexto))

    response = client.post("/servicios/prov/refrescar", params={"id": "900101"}, headers=API_HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["servicio"]["estado_servicio"] == "Activo"
    assert body["servicio"]["nombre_cliente"] == "CLIENTE DE PRUEBA SA"
    assert len(body["historial_ids"]) == 1
    assert body["historial_ids"][0]["numero_id"] == "900101"
    assert body["historial_ids"][0]["estado_comercial"] == "INSTALADO"
    assert len(body["equipos_ultima_milla"]) == 1
    assert body["equipos_ultima_milla"][0]["nodo"] == "NODO-TEST"

    detail = client.get("/servicios/detail", params={"id": "900101"}, headers=API_HEADERS)
    assert len(detail.json()["historial_ids"]) == 1


def test_refrescar_devuelve_404_logico_cuando_prov_no_tiene_contexto(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _crear_servicio("900102")
    monkeypatch.setattr(
        servicios_routes,
        "get_prov_client",
        lambda: _ClientePROVFalso(
            error=ProvServicioNoEncontradoError("900102", "No hay contexto para el número de servicio ingresado")
        ),
    )

    response = client.post("/servicios/prov/refrescar", params={"id": "900102"}, headers=API_HEADERS)
    assert response.status_code == 404
    assert "900102" in response.json()["detail"]


def test_refrescar_404_si_el_servicio_no_existe_en_la_db(client: TestClient) -> None:
    response = client.post("/servicios/prov/refrescar", params={"id": "900103-inexistente"}, headers=API_HEADERS)
    assert response.status_code == 404


def test_detail_incluye_listas_vacias_cuando_no_hay_historial_ni_equipos(client: TestClient) -> None:
    _crear_servicio("900103")
    detail = client.get("/servicios/detail", params={"id": "900103"}, headers=API_HEADERS)
    assert detail.status_code == 200
    body = detail.json()
    assert body["historial_ids"] == []
    assert body["equipos_ultima_milla"] == []
```

- [ ] **Step 2: Confirmar que falla**

Estos tests necesitan el Postgres real de dev, alcanzable en `127.0.0.1:5433` (puerto mapeado en
`deploy/docker-compose.dev.yml`) — y la contraseña REAL del secret de dev, no el placeholder de
`.env.dev` (`POSTGRES_PASSWORD=cambiar_por_password_dev_seguro` nunca es la contraseña real; el
contenedor la toma de `/run/secrets/db_password_v1`, ver `.secrets/Dev_db_password_v1.txt`):

```bash
source .venv/bin/activate
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5433
export POSTGRES_USER=FOCALBOT
export POSTGRES_DB=focas_dev
export POSTGRES_PASSWORD=$(cat .secrets/Dev_db_password_v1.txt)
python -m pytest -q tests/test_servicios_prov_routes.py
```

Expected: FAIL — `AttributeError`/404 por falta de la ruta `/servicios/prov/refrescar` y de los
campos `historial_ids`/`equipos_ultima_milla` en `/servicios/detail`.

- [ ] **Step 3: Agregar los imports necesarios**

En `api/app/routes/servicios.py`, agregar a los imports existentes:

```python
from datetime import date

from sqlalchemy.orm import selectinload

from core.services.prov.client import ProvClientError, ProvServicioNoEncontradoError, get_prov_client
from core.services.prov.ingesta import ingerir_contexto_prov
from db.models.infra import Servicio, ServicioEquipoUltimaMilla, ServicioHistorialId, ServicioOrigenDatos
```

(`Servicio`/`ServicioOrigenDatos` ya están importados desde `db.models.infra` — agregar
`ServicioEquipoUltimaMilla`/`ServicioHistorialId` a esa misma línea de import existente en vez de
duplicarla.)

- [ ] **Step 4: Agregar los schemas de respuesta**

Después de `ServicioItemResponse`, agregar:

```python
class ServicioHistorialIdItemResponse(BaseModel):
    numero_id: str
    orden: int
    fecha_instalacion: date | None = None
    fecha_baja: date | None = None
    estado_comercial: str | None = None
    motivo_baja: str | None = None
    es_vigente: bool


class ServicioEquipoUltimaMillaItemResponse(BaseModel):
    extremo: int
    nodo: str | None = None
    equipo: str | None = None
    puerto: str | None = None
    direccion: str | None = None
    provincia: str | None = None
```

- [ ] **Step 5: Extender `ServicioDetailResponse`**

```python
class ServicioDetailResponse(BaseModel):
    status: str = "ok"
    id_consultado: str
    id_origen: str
    servicio: ServicioItemResponse
    historial_ids: list[ServicioHistorialIdItemResponse] = []
    equipos_ultima_milla: list[ServicioEquipoUltimaMillaItemResponse] = []
```

- [ ] **Step 6: Agregar los helpers de conversión y de búsqueda**

Después de `_to_servicio_item`, agregar:

```python
def _historial_a_response(historial: list[ServicioHistorialId]) -> list[ServicioHistorialIdItemResponse]:
    return [
        ServicioHistorialIdItemResponse(
            numero_id=item.numero_id,
            orden=item.orden,
            fecha_instalacion=item.fecha_instalacion,
            fecha_baja=item.fecha_baja,
            estado_comercial=item.estado_comercial,
            motivo_baja=item.motivo_baja,
            es_vigente=item.es_vigente,
        )
        for item in sorted(historial, key=lambda item: item.orden)
    ]


def _equipos_a_response(equipos: list[ServicioEquipoUltimaMilla]) -> list[ServicioEquipoUltimaMillaItemResponse]:
    return [
        ServicioEquipoUltimaMillaItemResponse(
            extremo=item.extremo,
            nodo=item.nodo,
            equipo=item.equipo,
            puerto=item.puerto,
            direccion=item.direccion,
            provincia=item.provincia,
        )
        for item in sorted(equipos, key=lambda item: item.extremo)
    ]


async def _buscar_servicio_por_id(db: AsyncSession, id_consultado: str) -> Servicio:
    stmt = (
        select(Servicio)
        .options(selectinload(Servicio.historial_ids), selectinload(Servicio.equipos_ultima_milla))
        .where(
            or_(
                Servicio.numero_primer_servicio == id_consultado,
                Servicio.numero_linea == id_consultado,
                Servicio.servicio_id == id_consultado,
            )
        )
        .order_by(Servicio.id.desc())
        .limit(1)
    )
    svc = (await db.execute(stmt)).scalars().first()
    if svc is None:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return svc
```

- [ ] **Step 7: Reescribir `detail_servicio` para usar el helper y devolver los campos nuevos**

Reemplazar la función `detail_servicio` completa (la que arranca en `@router.get("/detail",
response_model=ServicioDetailResponse)`) por:

```python
@router.get("/detail", response_model=ServicioDetailResponse)
async def detail_servicio(
    id: str = Query(..., description="ID de consulta (origen o línea actual)"),
    db: AsyncSession = Depends(get_async_db),
) -> ServicioDetailResponse:
    id_consultado = id.strip()
    if not id_consultado:
        raise HTTPException(status_code=400, detail="ID requerido")

    svc = await _buscar_servicio_por_id(db, id_consultado)

    item = _to_servicio_item(svc)
    if item is None:
        raise HTTPException(status_code=404, detail="Servicio sin ID origen")

    return ServicioDetailResponse(
        id_consultado=id_consultado,
        id_origen=item.numero_primer_servicio,
        servicio=item,
        historial_ids=_historial_a_response(svc.historial_ids),
        equipos_ultima_milla=_equipos_a_response(svc.equipos_ultima_milla),
    )
```

- [ ] **Step 8: Agregar el endpoint de refresco**

Inmediatamente después de `detail_servicio`, agregar:

```python
@router.post("/prov/refrescar", response_model=ServicioDetailResponse)
async def refrescar_servicio_desde_prov(
    id: str = Query(..., description="ID de consulta (origen o línea actual)"),
    db: AsyncSession = Depends(get_async_db),
) -> ServicioDetailResponse:
    id_consultado = id.strip()
    if not id_consultado:
        raise HTTPException(status_code=400, detail="ID requerido")

    svc = await _buscar_servicio_por_id(db, id_consultado)

    cliente = get_prov_client()
    try:
        contexto = await cliente.obtener_contexto_servicio(svc.numero_primer_servicio or svc.servicio_id)
    except ProvServicioNoEncontradoError as exc:
        logger.warning("action=servicios_prov_refrescar evento=no_encontrado id=%s", id_consultado)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProvClientError as exc:
        logger.error("action=servicios_prov_refrescar evento=error_cliente id=%s error=%s", id_consultado, exc)
        raise HTTPException(status_code=502, detail=f"No se pudo consultar PROV: {exc}") from exc

    await ingerir_contexto_prov(db, svc, contexto)
    await db.commit()
    await db.refresh(svc, attribute_names=["historial_ids", "equipos_ultima_milla"])

    item = _to_servicio_item(svc)
    if item is None:
        raise HTTPException(status_code=404, detail="Servicio sin ID origen")

    return ServicioDetailResponse(
        id_consultado=id_consultado,
        id_origen=item.numero_primer_servicio,
        servicio=item,
        historial_ids=_historial_a_response(svc.historial_ids),
        equipos_ultima_milla=_equipos_a_response(svc.equipos_ultima_milla),
    )
```

Nota de rutas: `POST /servicios/prov/refrescar` se registra ANTES que cualquier ruta con
`{id}`/`{servicio_id}` como segmento — no hay ninguna en este router hoy, pero si se agregara una a
futuro (ver `feedback_fastapi_route_ordering` en memoria del proyecto), esta ruta literal debe
seguir yendo antes.

- [ ] **Step 9: Correr los tests y confirmar que pasan (contra Postgres real de dev)**

Con las mismas variables de entorno del Step 2 ya exportadas en el shell:

```bash
python -m pytest -q tests/test_servicios_prov_routes.py -v
python -m pytest -q tests/test_servicios_ingest_routes.py -v  # regresión: no debe romper /detail existente
```

Expected: todos pasan.

- [ ] **Step 10: Reconstruir `api` y verificar con curl real**

```bash
cd deploy
docker compose -f docker-compose.dev.yml --env-file ../.env.dev up -d --build api
cd ..
curl -s -H "Authorization: Bearer $(cat .secrets/Dev_api_key_v1.txt)" \
  "http://localhost:8011/servicios/detail?id=<numero_real_de_dev>" | python3 -m json.tool
```

Confirmar que la respuesta incluye `historial_ids: []` y `equipos_ultima_milla: []` para un
servicio que todavía no pasó por PROV.

- [ ] **Step 11: Commit**

```bash
git add api/app/routes/servicios.py tests/test_servicios_prov_routes.py
git commit -m "feat(servicios): endpoint de refresco on-demand desde PROV + historial_ids/equipos_ultima_milla en /detail"
```

---

### Task 7: Script de backfill — `scripts/servicios_backfill_prov.py`

**Files:**
- Create: `scripts/servicios_backfill_prov.py`

**Interfaces:**
- Consumes: `ProvClient`, `ProvClientError`, `ProvServicioNoEncontradoError` (Task 4),
  `ingerir_contexto_prov` (Task 5), `AsyncSessionLocal` (`db/session.py`, ya existente).

- [ ] **Step 1: Implementar el script**

```python
# Nombre de archivo: servicios_backfill_prov.py
# Ubicación de archivo: scripts/servicios_backfill_prov.py
# Descripción: Backfill masivo — enriquece Servicios existentes consultando la API PROV, respetando el rate limit de 5 req/s

"""Recorre `app.servicios` y enriquece cada fila con el contexto de PROV (última milla + historial
de upgrades), reusando `ingerir_contexto_prov` — la misma función que usa el endpoint on-demand
`POST /servicios/prov/refrescar`. Respeta el rate limit configurado en `ProvConfig`
(`PROV_RATE_LIMIT_PER_SECOND`, 5 req/s por defecto) durante todo el recorrido.

A diferencia de otros scripts de backfill del repo (síncronos, `SessionLocal`), este es async de
punta a punta porque el cliente PROV lo es — usa `AsyncSessionLocal` (`db/session.py`).

Uso:
    source .venv/bin/activate
    python scripts/servicios_backfill_prov.py                                   # sólo reporta (dry-run)
    python scripts/servicios_backfill_prov.py --apply                            # aplica el cambio
    python scripts/servicios_backfill_prov.py --solo-ids 122214,15872 --apply    # subconjunto acotado
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.logging import setup_logging
from core.services.prov.client import ProvClient, ProvClientError, ProvServicioNoEncontradoError
from core.services.prov.ingesta import ingerir_contexto_prov
from db.models.infra import Servicio
from db.session import AsyncSessionLocal

logger = setup_logging("servicios_backfill_prov")


async def _obtener_candidatos(solo_ids: list[str] | None) -> list[int]:
    async with AsyncSessionLocal() as session:
        stmt = select(Servicio.id).where(Servicio.numero_primer_servicio.isnot(None))
        if solo_ids:
            stmt = stmt.where(Servicio.numero_primer_servicio.in_(solo_ids))
        stmt = stmt.order_by(Servicio.id)
        return [fila[0] for fila in (await session.execute(stmt)).all()]


async def main(apply: bool, solo_ids: list[str] | None) -> None:
    inicio = time.perf_counter()
    ids_candidatos = await _obtener_candidatos(solo_ids)
    logger.info(
        "action=backfill_prov candidatas=%d modo=%s", len(ids_candidatos), "aplicado" if apply else "dry_run"
    )

    exitosos = 0
    no_encontrados = 0
    errores = 0

    async with ProvClient() as cliente:
        for servicio_id in ids_candidatos:
            async with AsyncSessionLocal() as session:
                stmt = (
                    select(Servicio)
                    .options(selectinload(Servicio.historial_ids), selectinload(Servicio.equipos_ultima_milla))
                    .where(Servicio.id == servicio_id)
                )
                servicio = (await session.execute(stmt)).scalars().first()
                if servicio is None:
                    continue

                numero_consulta = servicio.numero_primer_servicio or servicio.servicio_id
                try:
                    contexto = await cliente.obtener_contexto_servicio(numero_consulta)
                except ProvServicioNoEncontradoError:
                    no_encontrados += 1
                    logger.warning("action=backfill_prov evento=no_encontrado numero=%s", numero_consulta)
                    continue
                except ProvClientError as exc:
                    errores += 1
                    logger.error(
                        "action=backfill_prov evento=error_cliente numero=%s error=%s", numero_consulta, exc
                    )
                    continue

                await ingerir_contexto_prov(session, servicio, contexto)
                if apply:
                    await session.commit()
                else:
                    await session.rollback()
                exitosos += 1

    elapsed = time.perf_counter() - inicio
    logger.info(
        "action=backfill_prov modo=%s candidatas=%d exitosos=%d no_encontrados=%d errores=%d elapsed_seg=%.1f",
        "aplicado" if apply else "dry_run",
        len(ids_candidatos),
        exitosos,
        no_encontrados,
        errores,
        elapsed,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Aplica los cambios (por defecto sólo reporta)")
    parser.add_argument(
        "--solo-ids",
        type=str,
        default=None,
        help="Lista de numero_primer_servicio separados por coma, para correr sobre un subconjunto acotado",
    )
    args = parser.parse_args()
    solo_ids_parsed = [valor.strip() for valor in args.solo_ids.split(",")] if args.solo_ids else None
    asyncio.run(main(apply=args.apply, solo_ids=solo_ids_parsed))
```

- [ ] **Step 2: Probar en dry-run contra un subconjunto acotado real**

```bash
source .venv/bin/activate
python scripts/servicios_backfill_prov.py --solo-ids 122214 --apply
```

(Usar `--apply` aquí es intencional para un subconjunto de una sola fila conocida, para confirmar
de punta a punta que el enriquecimiento se escribe — revisar con una consulta `psql` a
`app.servicios_historial_id`/`app.servicios_equipos_ultima_milla` antes de correr sin `--solo-ids`
sobre toda la tabla.)

- [ ] **Step 3: Commit**

```bash
git add scripts/servicios_backfill_prov.py
git commit -m "feat(prov): script de backfill masivo respetando el rate limit de 5 req/s"
```

---

### Task 8: Frontend — tipos genéricos de Timeline + cliente API

**Files:**
- Create: `web/frontend/src/types/timeline.ts`
- Modify: `web/frontend/src/api/servicios.ts`

**Interfaces:**
- Produces: `TimelineEvent`, `TimelineEventType` (`types/timeline.ts`);
  `ServicioHistorialIdItem`, `ServicioEquipoUltimaMillaItem`,
  `refrescarServicioDesdeProv(id): Promise<ServicioDetailResponse>`,
  `historialIdsToTimelineEvents(historial): TimelineEvent[]` (`api/servicios.ts`) — usados por
  Task 9 y Task 10.

- [ ] **Step 1: Crear el tipo genérico de evento**

Crear `web/frontend/src/types/timeline.ts`:

```typescript
// Nombre de archivo: timeline.ts
// Ubicación de archivo: web/frontend/src/types/timeline.ts
// Descripción: Tipo genérico de evento para el componente ServiceTimeline — admite historial de upgrades de ID hoy, y Reclamos/Ingresos/Mantenimientos a futuro

export type TimelineEventType = 'upgrade_id' | 'reclamo' | 'ingreso' | 'mantenimiento';

export interface TimelineEvent {
  id: string | number;
  fecha: string | null;
  tipo: TimelineEventType;
  titulo: string;
  estado?: string;
  descripcion?: string;
  metadata?: Record<string, string | number | null>;
}
```

- [ ] **Step 2: Extender `web/frontend/src/api/servicios.ts`**

Agregar el import de `TimelineEvent` al inicio del archivo (después del import de `./client`):

```typescript
import type { TimelineEvent } from '../types/timeline';
```

Agregar, después de `ServicioItem`, las dos interfaces nuevas:

```typescript
export interface ServicioHistorialIdItem {
  numero_id: string;
  orden: number;
  fecha_instalacion: string | null;
  fecha_baja: string | null;
  estado_comercial: string | null;
  motivo_baja: string | null;
  es_vigente: boolean;
}

export interface ServicioEquipoUltimaMillaItem {
  extremo: number;
  nodo: string | null;
  equipo: string | null;
  puerto: string | null;
  direccion: string | null;
  provincia: string | null;
}
```

Extender `ServicioDetailResponse`:

```typescript
export interface ServicioDetailResponse {
  status: string;
  id_consultado: string;
  id_origen: string;
  servicio: ServicioItem;
  historial_ids: ServicioHistorialIdItem[];
  equipos_ultima_milla: ServicioEquipoUltimaMillaItem[];
}
```

Agregar, después de `getServicioDetail`, la función de refresco y el conversor a `TimelineEvent[]`:

```typescript
/** Dispara un refresco on-demand del servicio contra PROV y persiste el resultado. Ver
 * `POST /api/servicios/prov/refrescar`. */
export async function refrescarServicioDesdeProv(id: string): Promise<ServicioDetailResponse> {
  const query = new URLSearchParams({ id: id.trim() }).toString();
  return requestJson<ServicioDetailResponse>(`/api/servicios/prov/refrescar?${query}`, {
    method: 'POST',
    csrf: true,
  });
}

/** Convierte el historial de IDs (PROV) al tipo genérico que consume `ServiceTimeline.vue`. */
export function historialIdsToTimelineEvents(historial: ServicioHistorialIdItem[]): TimelineEvent[] {
  return historial
    .slice()
    .sort((a, b) => a.orden - b.orden)
    .map((item) => ({
      id: `${item.numero_id}-${item.orden}`,
      fecha: item.fecha_instalacion,
      tipo: 'upgrade_id' as const,
      titulo: `ID ${item.numero_id}`,
      estado: item.estado_comercial ?? undefined,
      descripcion: item.motivo_baja || (item.es_vigente ? 'Vigente' : undefined),
      metadata: {
        fecha_baja: item.fecha_baja,
        es_vigente: item.es_vigente ? 'true' : 'false',
      },
    }));
}
```

- [ ] **Step 3: Verificar que compila**

```bash
cd web/frontend
npm run build
cd ../..
```

Expected: build sin errores de TypeScript.

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/types/timeline.ts web/frontend/src/api/servicios.ts
git commit -m "feat(servicios): tipo genérico TimelineEvent + cliente API para historial/equipos/refresco PROV"
```

---

### Task 9: Frontend — componente `ServiceTimeline.vue`

**Files:**
- Create: `web/frontend/src/components/servicios/ServiceTimeline.vue`

**Interfaces:**
- Consumes: `TimelineEvent` (Task 8).
- Produces: componente `<ServiceTimeline :events="TimelineEvent[]" />` — usado por Task 10.

- [ ] **Step 1: Implementar el componente**

Crear `web/frontend/src/components/servicios/ServiceTimeline.vue`:

```vue
<!--
  Nombre de archivo: ServiceTimeline.vue
  Ubicación de archivo: web/frontend/src/components/servicios/ServiceTimeline.vue
  Descripción: Línea de tiempo genérica de eventos — historial de upgrades de ID hoy, Reclamos/Ingresos/Mantenimientos a futuro
-->
<template>
  <ol v-if="events.length > 0" class="service-timeline">
    <li v-for="event in events" :key="event.id" class="service-timeline__item">
      <div class="service-timeline__marker" aria-hidden="true"></div>
      <div class="service-timeline__body">
        <div class="service-timeline__headline">
          <strong>{{ event.titulo }}</strong>
          <span v-if="event.estado" :class="['service-timeline__chip', estadoClase(event.estado)]">
            {{ event.estado }}
          </span>
        </div>
        <span v-if="event.fecha" class="service-timeline__fecha">{{ formatearFecha(event.fecha) }}</span>
        <p v-if="event.descripcion" class="service-timeline__descripcion">{{ event.descripcion }}</p>
      </div>
    </li>
  </ol>
  <p v-else class="service-timeline__empty">Sin eventos para mostrar.</p>
</template>

<script setup lang="ts">
import type { TimelineEvent } from '../../types/timeline';

defineProps<{
  events: TimelineEvent[];
}>();

const ESTADOS_OK = new Set(['instalado', 'activo', 'vigente']);
const ESTADOS_ERROR = new Set(['dado baja', 'baja']);

function estadoClase(estado: string): string {
  const valor = estado.trim().toLowerCase();
  if (ESTADOS_OK.has(valor)) return 'is-ok';
  if (ESTADOS_ERROR.has(valor)) return 'is-error';
  return 'is-idle';
}

function formatearFecha(fecha: string): string {
  const parsed = new Date(fecha);
  if (Number.isNaN(parsed.getTime())) return fecha;
  return parsed.toLocaleDateString('es-AR', { year: 'numeric', month: '2-digit', day: '2-digit' });
}
</script>

<style scoped>
.service-timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}

.service-timeline__item {
  display: grid;
  gap: 4px;
  padding: 10px 0 10px 16px;
  margin-left: 5px;
  border-left: 2px solid var(--color-divider);
}

.service-timeline__item:last-child {
  border-left-color: transparent;
}

.service-timeline__marker {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--color-accent-success);
  margin-left: -23px;
  margin-bottom: -12px;
}

.service-timeline__body {
  display: grid;
  gap: 4px;
}

.service-timeline__headline {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.service-timeline__fecha {
  font-size: 0.8rem;
  color: var(--muted);
}

.service-timeline__descripcion {
  margin: 0;
  font-size: 0.85rem;
  color: var(--muted);
}

.service-timeline__chip {
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 0.7rem;
  font-weight: 700;
}

.service-timeline__chip.is-ok {
  background: color-mix(in srgb, var(--success) 18%, transparent);
  color: var(--success);
}

.service-timeline__chip.is-error {
  background: color-mix(in srgb, var(--error) 18%, transparent);
  color: var(--error);
}

.service-timeline__chip.is-idle {
  background: color-mix(in srgb, var(--muted) 18%, transparent);
  color: var(--muted);
}

.service-timeline__empty {
  color: var(--muted);
  font-size: 0.85rem;
}
</style>
```

Todas las variables de color usadas (`--color-divider`, `--color-accent-success`, `--muted`,
`--success`, `--error`) ya existen en `web/frontend/src/assets/styles/tokens.css` — ninguna se
inventa acá (cumple `nocturne-token-compliance`).

- [ ] **Step 2: Verificar que compila**

```bash
cd web/frontend
npm run build
cd ../..
```

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/components/servicios/ServiceTimeline.vue
git commit -m "feat(servicios): componente ServiceTimeline.vue genérico por tipo de evento"
```

---

### Task 10: Frontend — integrar el Timeline y el refresco en `ServicioDetalleView.vue`

**Files:**
- Modify: `web/frontend/src/views/ServicioDetalleView.vue`

**Interfaces:**
- Consumes: `ServiceTimeline` (Task 9), `historialIdsToTimelineEvents`,
  `refrescarServicioDesdeProv`, `ServicioHistorialIdItem`, `ServicioEquipoUltimaMillaItem`
  (Task 8).

- [ ] **Step 1: Agregar los imports**

En el bloque `<script setup>`, junto al import existente de `../api/servicios`, agregar los
símbolos nuevos y el componente:

```typescript
import ServiceTimeline from '../components/servicios/ServiceTimeline.vue';
import {
  CATEGORIAS_SERVICIO,
  categoriaLabel,
  estadoServicioToken,
  getServicioDetail,
  historialIdsToTimelineEvents,
  refrescarServicioDesdeProv,
  updateServicioCategoria,
  updateServicioVerificable,
  type ServicioEquipoUltimaMillaItem,
  type ServicioHistorialIdItem,
  type ServicioItem,
} from '../api/servicios';
import type { TimelineEvent } from '../types/timeline';
```

- [ ] **Step 2: Agregar el estado nuevo**

Junto a `const servicio = ref<ServicioItem | null>(null);`, agregar:

```typescript
const historialIds = ref<ServicioHistorialIdItem[]>([]);
const equiposUltimaMilla = ref<ServicioEquipoUltimaMillaItem[]>([]);
const refrescandoProv = ref(false);
const errorRefrescoProv = ref('');
```

- [ ] **Step 3: Poblar el estado nuevo en `loadDetalle`**

En `loadDetalle`, inmediatamente después de `servicio.value = response.servicio;`, agregar:

```typescript
    historialIds.value = response.historial_ids;
    equiposUltimaMilla.value = response.equipos_ultima_milla;
```

En el bloque `catch` de la misma función, junto a `servicio.value = null;`, agregar:

```typescript
    historialIds.value = [];
    equiposUltimaMilla.value = [];
```

- [ ] **Step 4: Agregar el computed `timelineEvents` con fallback a `historicoIds`**

Después del computed `historicoIds` ya existente, agregar:

```typescript
const timelineEvents = computed<TimelineEvent[]>(() => {
  if (historialIds.value.length > 0) {
    return historialIdsToTimelineEvents(historialIds.value);
  }
  // Fallback para servicios que todavía no pasaron por un refresco/backfill de PROV: reusa la
  // misma cadena simple de `alias_ids` que mostraba el track horizontal anterior, sin
  // fecha/estado/motivo (esos datos sólo existen una vez que PROV enriqueció el servicio).
  return historicoIds.value.map((id, index) => ({
    id,
    fecha: null,
    tipo: 'upgrade_id' as const,
    titulo: `ID ${id}`,
    descripcion: index === historicoIds.value.length - 1 ? 'Vigente' : undefined,
  }));
});
```

- [ ] **Step 5: Agregar la acción de refresco**

Junto a `onCambiarVerificable`, agregar:

```typescript
async function onRefrescarDesdeProv(): Promise<void> {
  if (!servicio.value || refrescandoProv.value) return;
  refrescandoProv.value = true;
  errorRefrescoProv.value = '';
  try {
    const response = await refrescarServicioDesdeProv(idParam.value);
    servicio.value = response.servicio;
    historialIds.value = response.historial_ids;
    equiposUltimaMilla.value = response.equipos_ultima_milla;
  } catch (err: unknown) {
    errorRefrescoProv.value = err instanceof Error ? err.message : 'No se pudo actualizar desde PROV';
  } finally {
    refrescandoProv.value = false;
  }
}
```

- [ ] **Step 6: Reemplazar el track de "Histórico de IDs" por el Timeline y agregar el panel de equipos**

Reemplazar el bloque:

```html
    <section class="servicio-detalle__historico" aria-label="Histórico de IDs">
      <span class="servicio-detalle__historico-label">Histórico de IDs</span>
      <div class="servicio-detalle__historico-track">
        <template v-for="(id, index) in historicoIds" :key="`${id}-${index}`">
          <span :class="['servicio-detalle__nodo', { 'is-current': index === historicoIds.length - 1 }]">{{ id }}</span>
          <i v-if="index < historicoIds.length - 1" class="ph ph-arrow-right" aria-hidden="true"></i>
        </template>
      </div>
    </section>
```

por:

```html
    <section class="servicio-detalle__historico" aria-label="Histórico de IDs">
      <div class="servicio-detalle__historico-header">
        <span class="servicio-detalle__historico-label">Histórico de IDs</span>
        <button class="btn subtle" type="button" :disabled="refrescandoProv" @click="onRefrescarDesdeProv">
          <i :class="['ph', refrescandoProv ? 'ph-spinner' : 'ph-arrow-clockwise']" aria-hidden="true"></i>
          {{ refrescandoProv ? 'Actualizando…' : 'Actualizar desde PROV' }}
        </button>
      </div>
      <p v-if="errorRefrescoProv" class="servicio-detalle__categoria-error">{{ errorRefrescoProv }}</p>
      <ServiceTimeline :events="timelineEvents" />
    </section>

    <section v-if="equiposUltimaMilla.length > 0" class="servicio-detalle__equipos" aria-label="Equipos de última milla">
      <span class="servicio-detalle__historico-label">Equipos de última milla</span>
      <div class="servicio-detalle__equipos-grid">
        <div v-for="equipo in equiposUltimaMilla" :key="equipo.extremo" class="servicio-detalle__equipo-card">
          <span class="servicio-detalle__equipo-extremo">Extremo {{ equipo.extremo }}</span>
          <span>{{ equipo.nodo || 'Nodo sin dato' }}</span>
          <span>{{ equipo.equipo || 'Equipo sin dato' }} · Puerto {{ equipo.puerto || '—' }}</span>
        </div>
      </div>
    </section>
```

- [ ] **Step 7: Agregar el CSS nuevo**

Junto al resto de los estilos `.servicio-detalle__historico*` existentes, agregar:

```css
.servicio-detalle__historico-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.servicio-detalle__equipos {
  margin-top: 16px;
}

.servicio-detalle__equipos-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 8px;
}

.servicio-detalle__equipo-card {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border-radius: 14px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  font-size: 0.85rem;
}

.servicio-detalle__equipo-extremo {
  font-weight: 700;
  font-size: 0.75rem;
  color: var(--muted);
  text-transform: uppercase;
}
```

- [ ] **Step 8: Reconstruir el frontend y verificar en el navegador**

```bash
cd deploy
docker compose -f docker-compose.dev.yml --env-file ../.env.dev up -d --build web
cd ..
```

Abrir `http://localhost:<puerto-dev-web>/servicios/ID/<numero_real>` y confirmar:
- El panel "Histórico de IDs" muestra el Timeline vertical (fallback simple si el servicio todavía
  no pasó por PROV).
- El botón "Actualizar desde PROV" dispara `POST /api/servicios/prov/refrescar` (ver pestaña
  Network) y, si el servicio existe en PROV, el Timeline pasa a mostrar fecha/estado/motivo por
  eslabón y aparece el panel "Equipos de última milla".
- Si el servicio no existe en PROV, se muestra el mensaje de error de `errorRefrescoProv` sin
  romper el resto de la vista.

- [ ] **Step 9: Commit**

```bash
git add web/frontend/src/views/ServicioDetalleView.vue
git commit -m "feat(servicios): integra ServiceTimeline y el refresco desde PROV en el detalle de servicio"
```

---

### Task 11: Documentación

**Files:**
- Modify: `docs/db.md`
- Modify: `docs/decisiones.md`
- Create: `docs/PR/2026-09-02.md` (o agregar sección si ya existe una entrada de hoy)

**Interfaces:** ninguna (sólo documentación).

- [ ] **Step 1: `docs/db.md`**

Agregar una entrada describiendo `app.servicios_historial_id` y
`app.servicios_equipos_ultima_milla` (columnas, FK `ondelete=CASCADE`, por qué se reescriben
completas en cada ingesta) y el nuevo valor `INGEST_PROV` del enum `app.servicio_origen_datos`,
siguiendo el mismo formato que las entradas existentes de `servicios`/`rutas_servicio`.

- [ ] **Step 2: `docs/decisiones.md`**

Agregar una entrada fechada 2026-09-02 con:
- La decisión de coexistencia temporal entre `/servicios/ingest` (Excel) y la integración PROV.
- Por qué el historial de upgrades necesitó una tabla nueva (`ServicioHistorialId`) en vez de
  reusar `alias_ids`, pese a la decisión previa de 2026-08-25 — explicitar el contraste: esa
  decisión aplicaba al historial de IDs *sin* fecha/estado/motivo; PROV sí los trae.
  aplicar
- La decisión de no construir un rate limiter distribuido (Redis) para PROV, y la nota operativa
  de no correr el backfill masivo junto con uso interactivo intensivo.

- [ ] **Step 3: PR diario**

Ejecutar (o invocar) `/generar-pr-diario` con fecha `2026-09-02`, o agregar manualmente a
`docs/PR/2026-09-02.md` un resumen de: paquete `core/services/prov/`, tablas nuevas, endpoint de
refresco, script de backfill, componente `ServiceTimeline.vue`, comandos ejecutados (migración,
tests, rebuilds) e impacto/riesgos (rate limit combinado backfill+interactivo, secrets de prod
pendientes).

- [ ] **Step 4: Commit**

```bash
git add docs/db.md docs/decisiones.md docs/PR/2026-09-02.md
git commit -m "docs(servicios): documenta la integración PROV (tablas, decisiones, PR diario)"
```
