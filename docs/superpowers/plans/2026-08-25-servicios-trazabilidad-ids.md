# Trazabilidad histórica de IDs de Servicios SLA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que la ingesta de Excel de Servicios SLA calcule correctamente el ID de línea vigente de cada familia de servicio (siguiendo la cadena de upgrades), lo escriba donde el bot de Slack y la UI de cables ya lo leen (`Servicio.servicio_id`), acumule el historial en `alias_ids`, repurponga `categoria` para "Nivel Cliente", agregue verificabilidad editable, y arregle el mapeo de columnas del Excel real que hoy se pierde.

**Architecture:** Toda la lógica de cálculo (ID final, alias, verificabilidad) vive en un módulo de servicio puro y testeable (`core/services/servicios_consolidacion_service.py`), sin acceso a DB — el endpoint de ingesta hace un `SELECT` en lote de las filas existentes, llama al servicio por fila, y arma el mismo `pg_insert(...).on_conflict_do_update(...)` que ya existe hoy. El histórico se reusa de `alias_ids` (ya consultado por el matching de Cromo) — no hay tabla ni migración nueva para eso. Un script de backfill aparte reconcilia `cromo_servicio_match` con el estado ya consolidado.

**Tech Stack:** FastAPI async + SQLAlchemy (Postgres `ON CONFLICT`), Alembic, pandas (parser Excel), Vue 3 + TypeScript.

**Spec:** `/home/support-focal-01/.claude/plans/rol-desarrollador-full-stack-streamed-fiddle.md`

## Global Constraints

- No modificar `cromo_pelos.servicio_raw` ni `servicio_numero` bajo ninguna circunstancia — la descripción cruda del pelo es intocable.
- `servicio_id` sólo se sobreescribe con el ID final calculado si su valor actual es numérico o la fila es nueva — si el módulo de tracking físico ya lo dejó en un ID no numérico, esa fila queda fuera de esta consolidación.
- No crear tabla ni migración nueva para el histórico de IDs — se reusa `alias_ids` (`ARRAY(String(64))`, ya existente en `Servicio`).
- `categoria` (0-6) no cambia de tipo/esquema — sólo cambia su fuente de datos (Excel "Nivel Cliente" en vez de sólo edición manual). Los valores legacy (0 y 6) se dejan como están, sin backfill.
- `es_verificable = True` sólo si `tipo_servicio` ∈ {INT, RPV, ISI, ISIS, TLS, EWS}, salvo que exista un override manual (`es_verificable_override IS NOT NULL`), que siempre gana sobre el cálculo automático.
- Toda fragmentación cruzada detectada entre `numero_primer_servicio` distintos se registra con `logger.warning` — nunca se resuelve en silencio ni se hace merge automático de filas (fuera de alcance).
- Backend: `source .venv/bin/activate` antes de correr pytest/alembic. Frontend: este proyecto no tiene test runner (no hay `.spec.ts`/vitest) — los cambios de Vue se verifican en el navegador contra `docker compose` de dev, no con tests automatizados.

---

## Contexto adicional para quien ejecute este plan

El Excel real de Servicios (`docs/Doc Privada/Servicios C4.xlsx`) usa encabezados con sufijo
"Servicio" (`Dirección Servicio`, `Localidad Servicio`, `Provincia Servicio`, `Dirección 2
Servicio`) que el parser actual no reconoce — hoy esas columnas quedan sin mapear en cualquier
ingesta real. También trae `Nivel Cliente` (entero 0-6), `Es Upgrade de` (Si/No), `Línea Upgrade
(De)`, `Es Upgrade a` (Si/No), `Línea Upgrade (A)` — las columnas fuente de la cadena de upgrades.
Regla de negocio confirmada con el usuario: **el ID numérico más alto conocido de una familia es
siempre el ID de línea vigente** — no hace falta perseguir los punteros "Es Upgrade de/a" en
cadena, sólo tomar el máximo.

---

### Task 1: Modelo + migración — `es_verificable` / `es_verificable_override`

**Files:**
- Modify: `db/models/infra.py` (clase `Servicio`, después de la línea `categoria = Column(...)`, ~línea 400)
- Create: `db/alembic/versions/20260825_02_servicios_verificable.py`

**Interfaces:**
- Produces: `Servicio.es_verificable: bool` (NOT NULL), `Servicio.es_verificable_override: bool | None` — usados por Task 5 y Task 6.

- [ ] **Step 1: Agregar las columnas al modelo `Servicio`**

En `db/models/infra.py`, inmediatamente después de la línea `categoria = Column(Integer, nullable=False, server_default=text("6"))` (dentro de la clase `Servicio`), agregar:

```python
    # True si tipo_servicio está en TIPOS_SERVICIO_VERIFICABLES (ver
    # core/services/servicios_consolidacion_service.py), recalculado en cada ingesta salvo que
    # es_verificable_override no sea NULL.
    es_verificable = Column(Boolean, nullable=False, server_default=text("false"))
    # Corrección manual de admin — cuando no es NULL, la ingesta de Excel respeta este valor y no
    # recalcula es_verificable. Sin tabla de auditoría dedicada, mismo criterio ya usado para
    # `categoria` (ver core/services/servicios_categoria_service.py).
    es_verificable_override = Column(Boolean, nullable=True)
```

Confirmar que `Boolean` y `text` ya están importados en el archivo (ambos se usan para otras columnas en el mismo módulo); si `Boolean` no está importado desde `sqlalchemy`, agregarlo al import existente.

- [ ] **Step 2: Escribir la migración**

Crear `db/alembic/versions/20260825_02_servicios_verificable.py`:

```python
# Nombre de archivo: 20260825_02_servicios_verificable.py
# Ubicación de archivo: db/alembic/versions/20260825_02_servicios_verificable.py
# Descripción: Agrega es_verificable (calculado por tipo_servicio, con backfill) y es_verificable_override (corrección manual) a app.servicios

"""es_verificable + es_verificable_override en servicios

Revision ID: 20260825_02
Revises: 20260825_01
Create Date: 2026-08-25

Cambios:
- `es_verificable` (Boolean NOT NULL): True si `tipo_servicio` está en {INT, RPV, ISI, ISIS, TLS,
  EWS} (ver `core/services/servicios_consolidacion_service.py::TIPOS_SERVICIO_VERIFICABLES`).
  Backfill con la misma regla para las filas existentes ANTES de fijar NOT NULL — mismo orden que
  `20260814_01_servicios_categoria_check.py` (backfill antes de SET NOT NULL/CHECK).
- `es_verificable_override` (Boolean, nullable, default NULL): corrección manual de admin. Cuando
  no es NULL, la ingesta de Excel no recalcula `es_verificable` para esa fila — mismo criterio ya
  usado para no auditar `categoria`, sin tabla de auditoría dedicada.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260825_02"
down_revision = "20260825_01"
branch_labels = None
depends_on = None

_TIPOS_VERIFICABLES = ("INT", "RPV", "ISI", "ISIS", "TLS", "EWS")


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "servicios",
        sa.Column("es_verificable", sa.Boolean(), nullable=True),
        schema="app",
    )
    op.add_column(
        "servicios",
        sa.Column("es_verificable_override", sa.Boolean(), nullable=True),
        schema="app",
    )

    # Backfill ANTES de SET NOT NULL — calcula desde tipo_servicio para las filas existentes.
    # _TIPOS_VERIFICABLES es una constante fija del código (no dato de usuario): el f-string es un
    # literal IN (...), no una concatenación de datos externos.
    tipos_sql = ", ".join(f"'{tipo}'" for tipo in _TIPOS_VERIFICABLES)
    bind.execute(
        sa.text(
            f"UPDATE app.servicios SET es_verificable = (tipo_servicio IN ({tipos_sql})) "
            "WHERE es_verificable IS NULL"
        )
    )

    op.alter_column(
        "servicios",
        "es_verificable",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.text("false"),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("servicios", "es_verificable_override", schema="app")
    op.drop_column("servicios", "es_verificable", schema="app")
```

- [ ] **Step 3: Aplicar la migración en dev y verificar contra la DB real**

```bash
source .venv/bin/activate
alembic upgrade head
```

Verificar:

```bash
export PGPASSWORD=$(cat .secrets/Dev_db_password_v1.txt)
docker exec -e PGPASSWORD="$PGPASSWORD" lasfocasdev-postgres psql -U FOCALBOT -d focas_dev -c "
SELECT es_verificable, tipo_servicio, count(*)
FROM app.servicios
GROUP BY es_verificable, tipo_servicio
ORDER BY es_verificable DESC
LIMIT 20;
"
```

Confirmar que las filas con `tipo_servicio` en `{INT, RPV, ISI, ISIS, TLS, EWS}` tienen
`es_verificable = true` y el resto `false`.

- [ ] **Step 4: Commit**

```bash
git add db/models/infra.py db/alembic/versions/20260825_02_servicios_verificable.py
git commit -m "feat(servicios): agrega es_verificable y es_verificable_override a Servicio"
```

---

### Task 2: Parser — fix de encabezados reales + nuevas columnas de la cadena de upgrades

**Files:**
- Modify: `core/parsers/servicios_excel.py`
- Test: `tests/test_servicios_excel_parser.py`

**Interfaces:**
- Produces: columnas parseadas `categoria`, `linea_upgrade_de`, `linea_upgrade_a` en el DataFrame devuelto por `parse_servicios_df()` — usadas por Task 6.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_servicios_excel_parser.py`:

```python
def test_parse_servicios_df_mapea_encabezados_reales_con_sufijo_servicio() -> None:
    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["393"],
            "Dirección Servicio": ["GODOY CRUZ 2320"],
            "Dirección 2 Servicio": ["SUIPACHA 128 P.3 - D.F"],
            "Localidad Servicio": ["CABA"],
            "Provincia Servicio": ["CABA"],
        }
    )

    parsed, summary = parse_servicios_df(df)

    assert summary.rows_ok == 1
    assert parsed.iloc[0]["direccion"] == "GODOY CRUZ 2320"
    assert parsed.iloc[0]["direccion_2"] == "SUIPACHA 128 P.3 - D.F"
    assert parsed.iloc[0]["localidad"] == "CABA"
    assert parsed.iloc[0]["provincia"] == "CABA"


def test_parse_servicios_df_mapea_columnas_de_cadena_de_upgrades() -> None:
    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["393", "4397"],
            "Nivel Cliente": ["4", "4"],
            "Línea Upgrade (De)": ["105636", "-"],
            "Línea Upgrade (A)": ["-", "-"],
        }
    )

    parsed, summary = parse_servicios_df(df)

    assert summary.rows_ok == 2
    assert parsed.iloc[0]["categoria"] == "4"
    assert parsed.iloc[0]["linea_upgrade_de"] == "105636"
    assert pd.isna(parsed.iloc[1]["linea_upgrade_de"])
    assert pd.isna(parsed.iloc[0]["linea_upgrade_a"])
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

```bash
source .venv/bin/activate
pytest tests/test_servicios_excel_parser.py -v
```

Esperado: `FAIL` — `direccion`/`direccion_2`/`localidad`/`provincia` quedan vacíos (`<NA>`), y
`categoria`/`linea_upgrade_de`/`linea_upgrade_a` no existen todavía en `RELEVANT_COLS`.

- [ ] **Step 3: Implementar el fix en el parser**

En `core/parsers/servicios_excel.py`, agregar al diccionario `MAPPER` (después de la entrada
`"direccion 2": "direccion_2"` y antes de `"estado servicio"`):

```python
    "direccion servicio": "direccion",
    "domicilio servicio": "direccion",
    "direccion 2 servicio": "direccion_2",
    "localidad servicio": "localidad",
    "provincia servicio": "provincia",
    "nivel cliente": "categoria",
    "linea upgrade de": "linea_upgrade_de",
    "linea upgrade a": "linea_upgrade_a",
```

Actualizar `RELEVANT_COLS`:

```python
RELEVANT_COLS = [
    "nombre_cliente",
    "numero_primer_servicio",
    "numero_linea",
    "tipo_servicio",
    "sla_prometido",
    "direccion",
    "localidad",
    "provincia",
    "direccion_2",
    "estado_servicio",
    "categoria",
    "linea_upgrade_de",
    "linea_upgrade_a",
]
```

Al final de `parse_servicios_df`, justo antes del `return`, tratar `"-"` como nulo específicamente
para las dos columnas de upgrade (no tocar la normalización genérica de las demás columnas, que ya
corre arriba en el mismo `for col in RELEVANT_COLS` y no debe verse afectada por este cambio):

```python
    for col in ("linea_upgrade_de", "linea_upgrade_a"):
        df.loc[df[col] == "-", col] = pd.NA
```

(Insertar esta línea después del bloque `for col in RELEVANT_COLS: df[col] = ...` existente y
antes del cálculo de `valid`/`rows_ok`/`rows_bad`.)

- [ ] **Step 4: Correr los tests para confirmar que pasan**

```bash
pytest tests/test_servicios_excel_parser.py -v
```

Esperado: `PASS` (los 4 tests del archivo, los 2 preexistentes y los 2 nuevos).

- [ ] **Step 5: Commit**

```bash
git add core/parsers/servicios_excel.py tests/test_servicios_excel_parser.py
git commit -m "fix(servicios): mapea encabezados reales con sufijo Servicio + columnas de cadena de upgrades"
```

---

### Task 3: Servicio de consolidación — `es_verificable_por_tipo`

**Files:**
- Create: `core/services/servicios_consolidacion_service.py`
- Test: `tests/test_servicios_consolidacion_service.py`

**Interfaces:**
- Produces: `TIPOS_SERVICIO_VERIFICABLES: frozenset[str]`, `es_verificable_por_tipo(tipo_servicio: str | None) -> bool` — usados por Task 6, y por la migración de Task 1 (misma lista de valores, mantenida en código como fuente de verdad para el cálculo en vivo).

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_servicios_consolidacion_service.py`:

```python
# Nombre de archivo: test_servicios_consolidacion_service.py
# Ubicación de archivo: tests/test_servicios_consolidacion_service.py
# Descripción: Tests del cálculo de verificabilidad y de ID final/alias para la cadena de upgrades de Servicio

from core.services.servicios_consolidacion_service import (
    es_verificable_por_tipo,
)


def test_es_verificable_por_tipo_acepta_los_tipos_del_negocio() -> None:
    for tipo in ("INT", "RPV", "ISI", "ISIS", "TLS", "EWS"):
        assert es_verificable_por_tipo(tipo) is True


def test_es_verificable_por_tipo_rechaza_otros_tipos_y_normaliza_mayusculas() -> None:
    assert es_verificable_por_tipo("int") is True
    assert es_verificable_por_tipo("ATI") is False
    assert es_verificable_por_tipo(None) is False
    assert es_verificable_por_tipo("") is False
```

- [ ] **Step 2: Correr el test para confirmar que falla**

```bash
pytest tests/test_servicios_consolidacion_service.py -v
```

Esperado: `FAIL` con `ModuleNotFoundError: No module named 'core.services.servicios_consolidacion_service'`.

- [ ] **Step 3: Implementación mínima**

Crear `core/services/servicios_consolidacion_service.py`:

```python
# Nombre de archivo: servicios_consolidacion_service.py
# Ubicación de archivo: core/services/servicios_consolidacion_service.py
# Descripción: Cálculo del ID final de una familia de Servicio (cadena de upgrades SLA) y de si un tipo de servicio es verificable

"""Consolida la identidad de un `Servicio` a partir de los IDs conocidos de su familia (columna
`Número Primer Servicio` del Excel SLA como ancla estable, más `Número Línea`/`Línea Upgrade
(De)`/`Línea Upgrade (A)` de cada ingesta). Regla de negocio confirmada con el usuario: el ID más
alto (numéricamente) es siempre el ID de línea vigente — no hace falta perseguir los punteros
`Es Upgrade de/a`, sólo tomar el máximo de todos los IDs numéricos conocidos.

`servicio_id` (el campo que ya leen el bot de Slack y la UI de cables) sólo se sobreescribe si su
valor actual es numérico o no existía todavía — si el módulo de tracking físico
(`core/services/infra_service.py::execute_upgrade`) ya lo dejó en un ID no numérico (ej. "O1C1"),
esa fila queda fuera de la autoridad de esta consolidación; el nuevo ID conocido de todas formas se
agrega a `alias_ids` para que el matching de Cromo lo resuelva igual.
"""

from __future__ import annotations

from dataclasses import dataclass

TIPOS_SERVICIO_VERIFICABLES = frozenset({"INT", "RPV", "ISI", "ISIS", "TLS", "EWS"})


def es_verificable_por_tipo(tipo_servicio: str | None) -> bool:
    if not tipo_servicio:
        return False
    return tipo_servicio.strip().upper() in TIPOS_SERVICIO_VERIFICABLES
```

- [ ] **Step 4: Correr el test para confirmar que pasa**

```bash
pytest tests/test_servicios_consolidacion_service.py -v
```

Esperado: `PASS`.

- [ ] **Step 5: Commit**

```bash
git add core/services/servicios_consolidacion_service.py tests/test_servicios_consolidacion_service.py
git commit -m "feat(servicios): agrega es_verificable_por_tipo"
```

---

### Task 4: Servicio de consolidación — `consolidar_identidad_servicio`

**Files:**
- Modify: `core/services/servicios_consolidacion_service.py`
- Test: `tests/test_servicios_consolidacion_service.py`

**Interfaces:**
- Consumes: nada de tareas anteriores (función pura independiente).
- Produces: `@dataclass IdentidadConsolidada(servicio_id: str, numero_linea: str, alias_ids: list[str])` y `consolidar_identidad_servicio(*, numero_primer_servicio: str, numero_linea_excel: str | None, linea_upgrade_de: str | None, linea_upgrade_a: str | None, servicio_id_actual: str | None, numero_linea_actual: str | None, alias_ids_actual: list[str] | None) -> IdentidadConsolidada` — usada por Task 6.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_servicios_consolidacion_service.py` (actualizar el import del encabezado a
`from core.services.servicios_consolidacion_service import (consolidar_identidad_servicio,
es_verificable_por_tipo)`):

```python
def test_consolidar_identidad_alta_nueva_sin_upgrade() -> None:
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="393",
        numero_linea_excel="393",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=None,
    )
    assert resultado.servicio_id == "393"
    assert resultado.numero_linea == "393"
    assert resultado.alias_ids == []


def test_consolidar_identidad_toma_el_id_mas_alto_como_final() -> None:
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="393",
        numero_linea_excel="116916",
        linea_upgrade_de="105636",
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=None,
    )
    assert resultado.servicio_id == "116916"
    assert resultado.numero_linea == "116916"
    assert resultado.alias_ids == ["393", "105636"]


def test_consolidar_identidad_acumula_alias_previos_y_avanza_al_nuevo_maximo() -> None:
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="4397",
        numero_linea_excel="130000",
        linea_upgrade_de="108368",
        linea_upgrade_a=None,
        servicio_id_actual="108368",
        numero_linea_actual="108368",
        alias_ids_actual=["4397"],
    )
    assert resultado.servicio_id == "130000"
    assert resultado.numero_linea == "130000"
    assert resultado.alias_ids == ["4397", "108368"]


def test_consolidar_identidad_no_pisa_servicio_id_no_numerico_de_tracking() -> None:
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="45789",
        numero_linea_excel="111743",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual="O1C1",
        numero_linea_actual="45789",
        alias_ids_actual=[],
    )
    assert resultado.servicio_id == "O1C1"
    assert resultado.numero_linea == "111743"
    assert resultado.alias_ids == ["45789"]


def test_consolidar_identidad_ignora_guion_como_valor_vacio() -> None:
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="99761",
        numero_linea_excel="106608",
        linea_upgrade_de="-",
        linea_upgrade_a="118984",
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=None,
    )
    assert resultado.servicio_id == "118984"
    assert "-" not in resultado.alias_ids
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

```bash
pytest tests/test_servicios_consolidacion_service.py -v
```

Esperado: `FAIL` con `ImportError: cannot import name 'consolidar_identidad_servicio'`.

- [ ] **Step 3: Implementación**

Agregar al final de `core/services/servicios_consolidacion_service.py`:

```python
def _a_entero(valor: str | None) -> int | None:
    if valor is None:
        return None
    texto = valor.strip()
    if not texto:
        return None
    try:
        return int(texto)
    except ValueError:
        return None


@dataclass(slots=True)
class IdentidadConsolidada:
    servicio_id: str
    numero_linea: str
    alias_ids: list[str]


def consolidar_identidad_servicio(
    *,
    numero_primer_servicio: str,
    numero_linea_excel: str | None,
    linea_upgrade_de: str | None,
    linea_upgrade_a: str | None,
    servicio_id_actual: str | None,
    numero_linea_actual: str | None,
    alias_ids_actual: list[str] | None,
) -> IdentidadConsolidada:
    candidatos_str = {
        valor
        for valor in (
            numero_primer_servicio,
            numero_linea_excel,
            linea_upgrade_de,
            linea_upgrade_a,
            numero_linea_actual,
            servicio_id_actual,
            *(alias_ids_actual or []),
        )
        if valor and valor != "-"
    }

    candidatos_numericos = [
        (valor, entero) for valor in candidatos_str if (entero := _a_entero(valor)) is not None
    ]

    id_final = (
        max(candidatos_numericos, key=lambda par: par[1])[0]
        if candidatos_numericos
        else numero_primer_servicio
    )

    servicio_id_es_numerico_o_vacio = servicio_id_actual is None or _a_entero(servicio_id_actual) is not None
    servicio_id_final = id_final if servicio_id_es_numerico_o_vacio else servicio_id_actual

    alias_existentes = list(alias_ids_actual or [])
    alias_nuevos = sorted(
        (
            valor
            for valor in candidatos_str
            if valor not in (id_final, servicio_id_final) and valor not in alias_existentes
        ),
        key=lambda valor: (_a_entero(valor) is None, _a_entero(valor) or 0, valor),
    )

    return IdentidadConsolidada(
        servicio_id=servicio_id_final,
        numero_linea=id_final,
        alias_ids=[*alias_existentes, *alias_nuevos],
    )
```

- [ ] **Step 4: Correr los tests para confirmar que pasan**

```bash
pytest tests/test_servicios_consolidacion_service.py -v
```

Esperado: `PASS` (los 2 tests de Task 3 + los 5 nuevos).

- [ ] **Step 5: Commit**

```bash
git add core/services/servicios_consolidacion_service.py tests/test_servicios_consolidacion_service.py
git commit -m "feat(servicios): agrega consolidar_identidad_servicio (ID final + alias de la cadena de upgrades)"
```

---

### Task 5: Endpoint `PATCH /servicios/{id}/verificable` + nuevos campos de respuesta

**Files:**
- Modify: `api/app/routes/servicios.py` (`ServicioItemResponse`, `_to_servicio_item`, nuevo endpoint al final del archivo)
- Test: `tests/test_servicios_verificable_routes.py` (nuevo)

**Interfaces:**
- Produces: `ServicioItemResponse.es_verificable: bool`, `.es_verificable_override: bool | None`,
  `.alias_ids: list[str]`; endpoint `PATCH /servicios/{id}/verificable` — consumido por Task 8
  (frontend) y por el test de Task 6 (que consulta `GET /servicios/detail` y espera estos campos).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_servicios_verificable_routes.py` (mismo patrón que
`tests/test_servicios_categoria_routes.py`):

```python
# Nombre de archivo: test_servicios_verificable_routes.py
# Ubicación de archivo: tests/test_servicios_verificable_routes.py
# Descripción: Tests HTTP del endpoint de corrección manual de es_verificable

from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.app.main import app
from db.models.infra import Servicio, ServicioOrigenDatos
from db.session import get_async_db

client = TestClient(app)
API_HEADERS = {"Authorization": "Bearer test-api-key"}


class _FakeAsyncSession:
    def __init__(self, servicio: Servicio | None) -> None:
        self._servicio = servicio
        self.committed = False

    async def get(self, _model, _id):
        return self._servicio

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _obj) -> None:
        pass


def _make_servicio(**overrides) -> MagicMock:
    defaults = dict(
        id=1,
        servicio_id="12345",
        numero_primer_servicio="12345",
        nombre_cliente="Cliente Test",
        numero_linea=None,
        tipo_servicio="ATI",
        sla_prometido=None,
        direccion=None,
        localidad=None,
        provincia=None,
        direccion_2=None,
        estado_servicio="ACTIVO",
        categoria=6,
        origen_datos=ServicioOrigenDatos.MANUAL,
        es_verificable=False,
        es_verificable_override=None,
        alias_ids=[],
    )
    defaults.update(overrides)
    svc = MagicMock(spec=Servicio)
    for key, value in defaults.items():
        setattr(svc, key, value)
    return svc


def _override_con(fake_session: _FakeAsyncSession):
    async def _dep() -> AsyncGenerator[_FakeAsyncSession, None]:
        yield fake_session

    return _dep


class TestPatchVerificable:
    def teardown_method(self) -> None:
        app.dependency_overrides.pop(get_async_db, None)

    def test_marca_override_manual_y_lo_refleja_en_es_verificable(self) -> None:
        svc = _make_servicio(es_verificable=False, es_verificable_override=None)
        app.dependency_overrides[get_async_db] = _override_con(_FakeAsyncSession(svc))

        response = client.patch("/servicios/1/verificable", json={"es_verificable": True}, headers=API_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["es_verificable"] is True
        assert body["es_verificable_override"] is True
        assert svc.es_verificable_override is True

    def test_servicio_inexistente_devuelve_404(self) -> None:
        app.dependency_overrides[get_async_db] = _override_con(_FakeAsyncSession(None))

        response = client.patch("/servicios/999/verificable", json={"es_verificable": False}, headers=API_HEADERS)

        assert response.status_code == 404

    def test_sin_api_key_devuelve_401_o_403(self) -> None:
        response = client.patch("/servicios/1/verificable", json={"es_verificable": True})

        assert response.status_code in (401, 403)
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

```bash
pytest tests/test_servicios_verificable_routes.py -v
```

Esperado: `FAIL` — el endpoint no existe (`404` genérico de FastAPI por ruta no encontrada, no el
`404` esperado del test) y `ServicioItemResponse` no tiene los campos nuevos.

- [ ] **Step 3: Implementación**

En `api/app/routes/servicios.py`, agregar los campos a `ServicioItemResponse` (después de
`categoria: int`):

```python
    es_verificable: bool
    es_verificable_override: bool | None = None
    alias_ids: list[str] = []
```

En `_to_servicio_item`, agregar al `return ServicioItemResponse(...)`:

```python
        es_verificable=svc.es_verificable,
        es_verificable_override=svc.es_verificable_override,
        alias_ids=list(svc.alias_ids or []),
```

Al final del archivo, agregar el nuevo request model y endpoint (mismo patrón exacto que
`actualizar_categoria_servicio`, líneas 384-406):

```python
class ServicioVerificableUpdateRequest(BaseModel):
    es_verificable: bool


@router.patch("/{id}/verificable", response_model=ServicioItemResponse)
async def actualizar_verificable_servicio(
    id: int,
    body: ServicioVerificableUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
) -> ServicioItemResponse:
    svc = await db.get(Servicio, id)
    if svc is None:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")

    svc.es_verificable_override = body.es_verificable
    svc.es_verificable = body.es_verificable
    await db.commit()
    await db.refresh(svc)

    item = _to_servicio_item(svc)
    if item is None:
        raise HTTPException(status_code=404, detail="Servicio sin ID origen")
    return item
```

- [ ] **Step 4: Correr los tests para confirmar que pasan**

```bash
pytest tests/test_servicios_verificable_routes.py tests/test_servicios_categoria_routes.py -v
```

Esperado: todos `PASS`.

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/servicios.py tests/test_servicios_verificable_routes.py
git commit -m "feat(servicios): endpoint PATCH /servicios/{id}/verificable + alias_ids/es_verificable en la respuesta"
```

---

### Task 6: Reescritura de `ingest_servicios` — consolidación + categoria + verificabilidad

**Files:**
- Modify: `api/app/routes/servicios.py:116-233` (función `ingest_servicios` y el diccionario `rows_by_id`)
- Test: `tests/test_servicios_ingest_routes.py` (nuevo)

**Interfaces:**
- Consumes: `consolidar_identidad_servicio`, `es_verificable_por_tipo` (Task 3/4), columnas `categoria`/`linea_upgrade_de`/`linea_upgrade_a` del parser (Task 2), campos `alias_ids`/`categoria`/`es_verificable` ya expuestos en `ServicioItemResponse` (Task 5).
- Produces: el endpoint `POST /servicios/ingest` deja de escribir `servicio_id = numero_primer_servicio` a ciegas; escribe `servicio_id`/`numero_linea`/`alias_ids`/`categoria`/`es_verificable` ya consolidados.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_servicios_ingest_routes.py` (sigue el patrón de mock de sesión async de
`tests/test_servicios_categoria_routes.py`, pero contra el endpoint de ingesta; usa un DataFrame
chico en memoria en vez de un archivo real):

```python
# Nombre de archivo: test_servicios_ingest_routes.py
# Ubicación de archivo: tests/test_servicios_ingest_routes.py
# Descripción: Tests de integración de la consolidación de identidad dentro de POST /servicios/ingest contra un Postgres real de test

from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.app.main import app
from db.session import SessionLocal

client = TestClient(app)
API_HEADERS = {"Authorization": "Bearer test-api-key"}


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _limpiar_servicios_de_test():
    yield
    with SessionLocal() as session:
        session.execute(text("DELETE FROM app.servicios WHERE numero_primer_servicio IN ('900001', '900002')"))
        session.commit()


def test_ingest_calcula_servicio_id_como_el_id_mas_alto_de_la_cadena() -> None:
    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["900001"],
            "Número Línea": ["900050"],
            "Línea Upgrade (De)": ["900010"],
            "Tipo Servicio": ["TLS"],
            "Nivel Cliente": ["4"],
            "Estado Servicio": ["Activo"],
        }
    )

    response = client.post(
        "/servicios/ingest",
        files={"file": ("servicios.xlsx", _excel_bytes(df), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["inserted"] == 1

    detail = client.get("/servicios/detail", params={"id": "900001"}, headers=API_HEADERS)
    body = detail.json()["servicio"]
    assert body["numero_linea"] == "900050"
    assert set(body["alias_ids"]) == {"900001", "900010"}
    assert body["categoria"] == 4
    assert body["es_verificable"] is True


def test_ingest_no_pisa_servicio_id_no_numerico_de_tracking() -> None:
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, numero_linea, estado_servicio) "
                "VALUES ('TRK-900002', '900002', '900002', 'DESCONOCIDO')"
            )
        )
        session.commit()

    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["900002"],
            "Número Línea": ["900070"],
            "Tipo Servicio": ["INT"],
        }
    )

    response = client.post(
        "/servicios/ingest",
        files={"file": ("servicios.xlsx", _excel_bytes(df), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=API_HEADERS,
    )
    assert response.status_code == 200

    detail = client.get("/servicios/detail", params={"id": "900002"}, headers=API_HEADERS)
    body = detail.json()["servicio"]
    assert body["numero_linea"] == "900070"
    assert "TRK-900002" not in body["alias_ids"]  # servicio_id de tracking no se toca
```

- [ ] **Step 2: Correr el test para confirmar que falla**

```bash
pytest tests/test_servicios_ingest_routes.py -v
```

Esperado: `FAIL` — hoy `servicio_id` queda pisado a `numero_primer_servicio` (`900001`) o al ID de
tracking existente (`TRK-900002`) sin avanzar nunca al ID más alto conocido de la cadena.

- [ ] **Step 3: Implementación — reescribir `ingest_servicios`**

En `api/app/routes/servicios.py`, agregar el import al principio del archivo:

```python
from core.services.servicios_consolidacion_service import consolidar_identidad_servicio, es_verificable_por_tipo
```

Reemplazar el cuerpo de `rows_by_id[...] = {...}` (líneas ~157-174) — quitar la línea `"servicio_id":
numero_primer_servicio,` y agregar los campos nuevos:

```python
        rows_by_id[numero_primer_servicio] = {
            "numero_primer_servicio": numero_primer_servicio,
            "nombre_cliente": _normalize_value(row.get("nombre_cliente")),
            "numero_linea": _normalize_value(row.get("numero_linea")),
            "tipo_servicio": _normalize_value(row.get("tipo_servicio")),
            "sla_prometido": _normalize_value(row.get("sla_prometido")),
            "direccion": _normalize_value(row.get("direccion")),
            "localidad": _normalize_value(row.get("localidad")),
            "provincia": _normalize_value(row.get("provincia")),
            "direccion_2": _normalize_value(row.get("direccion_2")),
            "estado_servicio": _normalize_value(row.get("estado_servicio")) or "DESCONOCIDO",
            "categoria": _normalize_value(row.get("categoria")),
            "linea_upgrade_de": _normalize_value(row.get("linea_upgrade_de")),
            "linea_upgrade_a": _normalize_value(row.get("linea_upgrade_a")),
            "origen_datos": ServicioOrigenDatos.INGEST_EXCEL.value,
        }
```

Inmediatamente después de `rows = list(rows_by_id.values())`, y **antes** del `for chunk in
_chunked(rows, size=500):`, insertar el paso de consolidación:

```python
    numeros = list(rows_by_id.keys())
    existentes_por_id: dict[str, Any] = {}
    if numeros:
        existentes_stmt = select(
            Servicio.numero_primer_servicio,
            Servicio.servicio_id,
            Servicio.numero_linea,
            Servicio.alias_ids,
            Servicio.categoria,
            Servicio.es_verificable_override,
        ).where(Servicio.numero_primer_servicio.in_(numeros))
        for fila in (await db.execute(existentes_stmt)).all():
            existentes_por_id[fila.numero_primer_servicio] = fila

    ids_reclamados: dict[str, str] = {}
    for numero, row in rows_by_id.items():
        existente = existentes_por_id.get(numero)
        linea_upgrade_de = row.pop("linea_upgrade_de", None)
        linea_upgrade_a = row.pop("linea_upgrade_a", None)

        identidad = consolidar_identidad_servicio(
            numero_primer_servicio=numero,
            numero_linea_excel=row.get("numero_linea"),
            linea_upgrade_de=linea_upgrade_de,
            linea_upgrade_a=linea_upgrade_a,
            servicio_id_actual=existente.servicio_id if existente else None,
            numero_linea_actual=existente.numero_linea if existente else None,
            alias_ids_actual=list(existente.alias_ids) if existente and existente.alias_ids else None,
        )
        row["servicio_id"] = identidad.servicio_id
        row["numero_linea"] = identidad.numero_linea
        row["alias_ids"] = identidad.alias_ids

        categoria_excel = row.get("categoria")
        row["categoria"] = (
            int(categoria_excel)
            if categoria_excel is not None and str(categoria_excel).isdigit()
            else (existente.categoria if existente else 6)
        )

        override_actual = existente.es_verificable_override if existente else None
        row["es_verificable"] = (
            override_actual
            if override_actual is not None
            else es_verificable_por_tipo(row.get("tipo_servicio"))
        )

        for candidato in (row["servicio_id"], row["numero_linea"], *row["alias_ids"]):
            dueño_previo = ids_reclamados.get(candidato)
            if dueño_previo and dueño_previo != numero:
                logger.warning(
                    "action=servicios_ingest evento=fragmentacion_detectada id=%s "
                    "numero_primer_servicio_a=%s numero_primer_servicio_b=%s",
                    candidato,
                    dueño_previo,
                    numero,
                )
            else:
                ids_reclamados[candidato] = numero

    rows = list(rows_by_id.values())
```

Actualizar `set_map` y `changed_where` dentro del `for chunk in _chunked(rows, size=500):` para
incluir los campos nuevos:

```python
        set_map = {
            "servicio_id": excluded.servicio_id,
            "nombre_cliente": excluded.nombre_cliente,
            "numero_linea": excluded.numero_linea,
            "tipo_servicio": excluded.tipo_servicio,
            "sla_prometido": excluded.sla_prometido,
            "direccion": excluded.direccion,
            "localidad": excluded.localidad,
            "provincia": excluded.provincia,
            "direccion_2": excluded.direccion_2,
            "estado_servicio": excluded.estado_servicio,
            "origen_datos": excluded.origen_datos,
            "categoria": excluded.categoria,
            "es_verificable": excluded.es_verificable,
            "alias_ids": excluded.alias_ids,
        }

        changed_where = or_(
            Servicio.nombre_cliente.is_distinct_from(excluded.nombre_cliente),
            Servicio.numero_linea.is_distinct_from(excluded.numero_linea),
            Servicio.tipo_servicio.is_distinct_from(excluded.tipo_servicio),
            Servicio.sla_prometido.is_distinct_from(excluded.sla_prometido),
            Servicio.direccion.is_distinct_from(excluded.direccion),
            Servicio.localidad.is_distinct_from(excluded.localidad),
            Servicio.provincia.is_distinct_from(excluded.provincia),
            Servicio.direccion_2.is_distinct_from(excluded.direccion_2),
            Servicio.estado_servicio.is_distinct_from(excluded.estado_servicio),
            Servicio.servicio_id.is_distinct_from(excluded.servicio_id),
            Servicio.origen_datos.is_distinct_from(excluded.origen_datos),
            Servicio.categoria.is_distinct_from(excluded.categoria),
            Servicio.es_verificable.is_distinct_from(excluded.es_verificable),
            Servicio.alias_ids.is_distinct_from(excluded.alias_ids),
        )
```

- [ ] **Step 4: Correr el test para confirmar que pasa**

```bash
pytest tests/test_servicios_ingest_routes.py -v
pytest tests/test_servicios_excel_parser.py tests/test_servicios_routes_utils.py tests/test_servicios_categoria_routes.py tests/test_servicios_categoria_service.py -v
```

Esperado: todos `PASS` (incluidos los tests preexistentes de categoría — confirma que no se rompió
el endpoint `/categoria`).

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/servicios.py tests/test_servicios_ingest_routes.py
git commit -m "feat(servicios): consolida ID final/alias/categoria/verificabilidad en la ingesta de Excel"
```

---

### Task 7: Script de backfill de Cromo — reconciliar `cromo_servicio_match` con el ID final consolidado

**Files:**
- Create: `scripts/cromo_backfill_reconciliar_servicio_final.py`

**Interfaces:**
- Consumes: estado real de `app.servicios`/`app.cromo_servicio_match` tras correr Task 6 en dev.
- No produce interfaces consumidas por otras tareas — es una herramienta operativa standalone, igual que `scripts/cromo_backfill_placeholders_servicios.py`.

- [ ] **Step 1: Escribir el script**

Crear `scripts/cromo_backfill_reconciliar_servicio_final.py`:

```python
# Nombre de archivo: cromo_backfill_reconciliar_servicio_final.py
# Ubicación de archivo: scripts/cromo_backfill_reconciliar_servicio_final.py
# Descripción: Backfill retroactivo — re-resuelve TODAS las filas de cromo_servicio_match (no sólo servicio_id IS NULL) contra el estado actual de app.servicios, para reflejar consolidaciones de la cadena de upgrades SLA

"""Re-resuelve `cromo_servicio_match.servicio_id` para TODOS los `servicio_numero` conocidos
(no sólo los que tienen `servicio_id IS NULL`, a diferencia de
`scripts/cromo_backfill_placeholders_servicios.py`) contra el estado ACTUAL de `app.servicios`.

Necesario porque la consolidación de la cadena de upgrades de Servicios SLA
(`api/app/routes/servicios.py::ingest_servicios` + `core/services/servicios_consolidacion_service.py`)
puede mover un `numero_linea` histórico desde un `Servicio` placeholder (`origen_datos=
INFERIDO_CROMO`) hacia la fila real consolidada, agregándolo a su `alias_ids`. Sin este backfill,
un pelo cuyo match ya apuntaba al placeholder viejo se queda ahí para siempre — la fase regular de
ingesta de Cromo (`core/services/cromo/ingesta.py::fase_servicios`) sólo procesa pares
`(pelo_n_id, servicio_numero)` SIN fila de match previa (`_SQL_PELOS_SIN_MATCH`), nunca reevalúa
matches ya resueltos.

No toca `cromo_pelos.servicio_raw` ni `servicio_numero` — sólo `cromo_servicio_match.servicio_id`.
Mismo patrón que `scripts/cromo_backfill_placeholders_servicios.py`: batch, `--dry-run`, idempotente.

Uso:
    source .venv/bin/activate
    python scripts/cromo_backfill_reconciliar_servicio_final.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text

from core.logging import setup_logging
from db.session import SessionLocal

logger = setup_logging("cromo_backfill_reconciliar_servicio_final")

_CHUNK_SIZE = 500

_SQL_TODOS_LOS_NUMEROS = text(
    """
    SELECT DISTINCT servicio_numero, servicio_id
    FROM app.cromo_servicio_match
    """
)

_SQL_RESOLUCION_ACTUAL = text(
    """
    SELECT id, servicio_id, numero_primer_servicio, alias_ids
    FROM app.servicios
    WHERE servicio_id = ANY(:numeros ::varchar[])
       OR numero_primer_servicio = ANY(:numeros ::varchar[])
       OR alias_ids && :numeros ::varchar[]
    """
)


def _chunked(items: list[Any], size: int = _CHUNK_SIZE) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _resolver_contra_servicios_actuales(session, numeros: list[str]) -> dict[str, int]:
    resueltos: dict[str, int] = {}
    for chunk in _chunked(numeros):
        numeros_set = set(chunk)
        filas = session.execute(_SQL_RESOLUCION_ACTUAL, {"numeros": chunk}).all()
        for servicio_db_id, servicio_id_col, numero_primer_servicio_col, alias_ids_col in filas:
            for candidato in (servicio_id_col, numero_primer_servicio_col):
                if candidato in numeros_set:
                    resueltos[candidato] = servicio_db_id
            for alias in alias_ids_col or []:
                if alias in numeros_set:
                    resueltos[alias] = servicio_db_id
    return resueltos


def _actualizar_matches_cambiados(session, cambios: dict[str, int]) -> int:
    items = list(cambios.items())
    total_actualizado = 0
    for chunk in _chunked(items):
        placeholders_sql = ", ".join(f"(:numero_{j} ::text, :id_{j} ::integer)" for j in range(len(chunk)))
        params: dict[str, Any] = {}
        for j, (numero, servicio_id) in enumerate(chunk):
            params[f"numero_{j}"] = numero
            params[f"id_{j}"] = servicio_id
        resultado = session.execute(
            text(
                f"""
                UPDATE app.cromo_servicio_match AS m
                SET servicio_id = v.nuevo_servicio_id
                FROM (VALUES {placeholders_sql}) AS v(numero, nuevo_servicio_id)
                WHERE m.servicio_numero = v.numero
                  AND m.servicio_id IS DISTINCT FROM v.nuevo_servicio_id
                """
            ),
            params,
        )
        total_actualizado += resultado.rowcount
    return total_actualizado


def main(dry_run: bool) -> None:
    inicio = time.perf_counter()
    session = SessionLocal()
    try:
        filas = session.execute(_SQL_TODOS_LOS_NUMEROS).all()
        numeros = [servicio_numero for servicio_numero, _ in filas]
        guardado_por_numero = {servicio_numero: guardado for servicio_numero, guardado in filas}
        logger.info("action=backfill_reconciliar_servicio_final numeros_distintos=%d", len(numeros))

        resueltos = _resolver_contra_servicios_actuales(session, numeros)

        cambios = {
            numero: nuevo_id
            for numero, nuevo_id in resueltos.items()
            if guardado_por_numero.get(numero) != nuevo_id
        }
        logger.info(
            "action=backfill_reconciliar_servicio_final resueltos=%d cambios_detectados=%d",
            len(resueltos),
            len(cambios),
        )

        filas_actualizadas = _actualizar_matches_cambiados(session, cambios)
        logger.info("action=backfill_reconciliar_servicio_final filas_match_actualizadas=%d", filas_actualizadas)

        elapsed = time.perf_counter() - inicio
        logger.info(
            "action=backfill_reconciliar_servicio_final modo=%s numeros_distintos=%d cambios=%d "
            "filas_match_actualizadas=%d elapsed_seg=%.1f",
            "dry_run" if dry_run else "aplicado",
            len(numeros),
            len(cambios),
            filas_actualizadas,
            elapsed,
        )

        if dry_run:
            logger.info("action=backfill_reconciliar_servicio_final modo=dry_run — no se aplican cambios, rollback")
            session.rollback()
        else:
            session.commit()
            logger.info("action=backfill_reconciliar_servicio_final modo=aplicado — cambios commiteados")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Sólo reporta qué cambiaría, sin aplicar cambios")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
```

- [ ] **Step 2: Correr en dry-run contra dev y revisar el log**

```bash
source .venv/bin/activate
python scripts/cromo_backfill_reconciliar_servicio_final.py --dry-run
```

Revisar `cambios_detectados` en el log — debe ser bajo o cero si Task 6 todavía no corrió ninguna
ingesta real en este ambiente; no debe tirar excepción.

- [ ] **Step 3: Commit**

```bash
git add scripts/cromo_backfill_reconciliar_servicio_final.py
git commit -m "feat(cromo): script de backfill que reconcilia cromo_servicio_match con la cadena de upgrades consolidada"
```

---

### Task 8: Frontend — `api/servicios.ts`

**Files:**
- Modify: `web/frontend/src/api/servicios.ts`

**Interfaces:**
- Consumes: campos `es_verificable`/`es_verificable_override`/`alias_ids` y endpoint `PATCH
  /servicios/{id}/verificable` de Task 5.
- Produces: `ServicioItem.es_verificable: boolean`, `.es_verificable_override: boolean | null`,
  `.alias_ids: string[]`; `updateServicioVerificable(id, esVerificable): Promise<ServicioItem>` —
  usados por Task 9/10.

- [ ] **Step 1: Actualizar la interfaz `ServicioItem`**

En `web/frontend/src/api/servicios.ts`, agregar campos a `ServicioItem` (después de `categoria:
number;`):

```typescript
  es_verificable: boolean;
  es_verificable_override: boolean | null;
  alias_ids: string[];
```

- [ ] **Step 2: Agregar `updateServicioVerificable`**

Después de `updateServicioCategoria`, agregar:

```typescript
/** Cambia la verificabilidad de un Servicio (corrección manual) — sólo admin. Devuelve el item
 * actualizado. Ver `PATCH /api/servicios/{id}/verificable`. */
export async function updateServicioVerificable(id: number, esVerificable: boolean): Promise<ServicioItem> {
  return requestJson<ServicioItem>(`/api/servicios/${id}/verificable`, {
    method: 'PATCH',
    json: { es_verificable: esVerificable },
    csrf: true,
  });
}
```

- [ ] **Step 3: Verificar en el navegador (dev)**

```bash
docker compose -f docker-compose.dev.yml up -d --build web
```

Abrir el listado de Servicios en dev y confirmar en la pestaña Network que `GET
/api/servicios/search` devuelve `es_verificable`/`alias_ids` en cada item sin error de tipos en la
consola del navegador.

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/api/servicios.ts
git commit -m "feat(servicios): agrega es_verificable/alias_ids al cliente API y updateServicioVerificable"
```

---

### Task 9: Frontend — `ServicioDetalleView.vue` (histórico real, verificable editable, nombre rojo en baja)

**Files:**
- Modify: `web/frontend/src/views/ServicioDetalleView.vue`

**Interfaces:**
- Consumes: `ServicioItem.alias_ids`/`.es_verificable`/`.es_verificable_override`,
  `updateServicioVerificable` (Task 8).

- [ ] **Step 1: Import y estado nuevo**

En el bloque `<script setup>`, actualizar el import de `../api/servicios` para incluir
`updateServicioVerificable`:

```typescript
import {
  CATEGORIAS_SERVICIO,
  categoriaLabel,
  estadoServicioToken,
  getServicioDetail,
  updateServicioCategoria,
  updateServicioVerificable,
  type ServicioItem,
} from '../api/servicios';
```

Después de `const errorCategoria = ref('');`, agregar:

```typescript
const guardandoVerificable = ref(false);
const errorVerificable = ref('');
```

- [ ] **Step 2: Alimentar el histórico real desde `alias_ids`**

Reemplazar el computed `historicoIds` (líneas 265-273) por:

```typescript
const historicoIds = computed(() => {
  if (!servicio.value) return [] as string[];

  const alias = [...(servicio.value.alias_ids ?? [])].sort((a, b) => {
    const numA = Number(a);
    const numB = Number(b);
    if (Number.isFinite(numA) && Number.isFinite(numB)) return numA - numB;
    return a.localeCompare(b);
  });

  const ids = [servicio.value.numero_primer_servicio, ...alias, servicio.value.numero_linea]
    .map((value) => (value ?? '').trim())
    .filter((value, index, arr) => value.length > 0 && arr.indexOf(value) === index);

  return ids.length > 0 ? ids : [idParam.value];
});
```

- [ ] **Step 3: Control editable de verificable + función de guardado**

En el `<template>`, después del `<span v-else-if="servicio" class="servicio-detalle__chip
is-outline">{{ categoriaLabel(servicio.categoria) }}</span>` (línea 40), agregar:

```html
          <select
            v-if="isAdmin && servicio"
            class="servicio-detalle__verificable-select"
            :value="String(servicio.es_verificable)"
            :disabled="guardandoVerificable"
            @change="onCambiarVerificable(($event.target as HTMLSelectElement).value === 'true')"
          >
            <option value="true">Verificable</option>
            <option value="false">No verificable</option>
          </select>
          <span v-else-if="servicio && !servicio.es_verificable" class="servicio-detalle__chip is-warning">No verificable</span>
```

Después de `<p v-if="errorCategoria" class="servicio-detalle__categoria-error">{{ errorCategoria
}}</p>` (línea 42), agregar:

```html
        <p v-if="errorVerificable" class="servicio-detalle__categoria-error">{{ errorVerificable }}</p>
```

En `<script setup>`, después de `onCambiarCategoria`, agregar:

```typescript
async function onCambiarVerificable(esVerificable: boolean): Promise<void> {
  if (!servicio.value || guardandoVerificable.value) return;
  const anterior = servicio.value.es_verificable;
  guardandoVerificable.value = true;
  errorVerificable.value = '';
  try {
    servicio.value = await updateServicioVerificable(servicio.value.id, esVerificable);
  } catch (err: unknown) {
    errorVerificable.value = err instanceof Error ? err.message : 'No se pudo cambiar la verificabilidad';
    if (servicio.value) servicio.value.es_verificable = anterior;
  } finally {
    guardandoVerificable.value = false;
  }
}
```

- [ ] **Step 4: Nombre en rojo cuando la cadena está de baja**

En el `<template>`, reemplazar:

```html
        <h1>{{ servicio?.nombre_cliente || 'Cliente sin dato' }}</h1>
```

por:

```html
        <h1 :class="{ 'is-baja': estadoToken === 'error' }">{{ servicio?.nombre_cliente || 'Cliente sin dato' }}</h1>
```

(`estadoToken` ya existe como computed en el archivo, línea 276.)

En `<style scoped>`, después de la regla `.servicio-detalle__header h1 { ... }`, agregar:

```css
.servicio-detalle__header h1.is-baja {
  color: var(--color-state-error);
}

.servicio-detalle__verificable-select {
  padding: 3px 8px;
  font-size: 10.5px;
  border-radius: 6px;
  background: var(--color-surface);
  border: 1px solid var(--color-state-warn);
  color: var(--color-state-warn);
}

.servicio-detalle__chip.is-warning {
  background: transparent;
  border: 1px solid var(--color-state-warn);
  color: var(--color-state-warn);
}
```

- [ ] **Step 5: Verificar en el navegador (dev)**

Abrir el detalle de un servicio con `estado_servicio` conteniendo "baja" (o forzarlo vía `PATCH
/servicios/{id}/categoria`-equivalente manual en DB de test) y confirmar: el nombre se ve en rojo,
el histórico de IDs muestra la cadena completa (no sólo 2 nodos) cuando `alias_ids` tiene datos, y
el select de verificable cambia el badge sin recargar la página. Confirmar rollback visual si se
simula un error de red (cortar el backend un instante).

- [ ] **Step 6: Commit**

```bash
git add web/frontend/src/views/ServicioDetalleView.vue
git commit -m "feat(servicios): histórico real de IDs, verificable editable y nombre en rojo para servicios de baja en el detalle"
```

---

### Task 10: Frontend — listado (`ServicioCard.vue` + `ServiciosView.vue`)

**Files:**
- Modify: `web/frontend/src/components/servicios/ServicioCard.vue`
- Modify: `web/frontend/src/views/ServiciosView.vue`

**Interfaces:**
- Consumes: `ServicioItem.es_verificable`, `estadoServicioToken` (ya existente) — Task 8.

- [ ] **Step 1: `ServicioCard.vue` — nombre rojo + badge no verificable**

Reemplazar (línea 29):

```html
    <h3 class="servicio-card__name">{{ servicio.nombre_cliente || 'Cliente sin dato' }}</h3>
```

por:

```html
    <h3 :class="['servicio-card__name', { 'is-baja': estadoToken === 'error' }]">{{ servicio.nombre_cliente || 'Cliente sin dato' }}</h3>
```

(`estadoToken` ya es un computed existente en este archivo, línea 74.)

Después de la línea `<span class="servicio-card__categoria">{{ categoriaLabel(servicio.categoria)
}}</span>` (línea 25), agregar:

```html
      <span v-if="!servicio.es_verificable" class="servicio-card__badge-no-verificable">No verificable</span>
```

En el bloque `<style scoped>`, agregar (junto a las demás reglas de `.servicio-card__`):

```css
.servicio-card__name.is-baja {
  color: var(--color-state-error);
}

.servicio-card__badge-no-verificable {
  padding: 2px 7px;
  border-radius: 5px;
  font-size: 9.5px;
  border: 1px solid var(--color-state-warn);
  color: var(--color-state-warn);
}
```

- [ ] **Step 2: `ServiciosView.vue` — nombre rojo en vista de lista y en el panel de vista previa**

Reemplazar (línea 135):

```html
              <span class="servicios-view__list-cliente">{{ item.nombre_cliente || 'Cliente sin dato' }}</span>
```

por:

```html
              <span :class="['servicios-view__list-cliente', { 'is-baja': estadoServicioToken(item.estado_servicio) === 'error' }]">{{ item.nombre_cliente || 'Cliente sin dato' }}</span>
```

Reemplazar (línea 146):

```html
              <h2 class="servicios-view__preview-title">{{ selectedItem.nombre_cliente || 'Cliente sin dato' }}</h2>
```

por:

```html
              <h2 :class="['servicios-view__preview-title', { 'is-baja': estadoServicioToken(selectedItem.estado_servicio) === 'error' }]">{{ selectedItem.nombre_cliente || 'Cliente sin dato' }}</h2>
```

(`estadoServicioToken` ya está importado y en uso en este archivo, ver línea 134.)

No se agrega el badge "No verificable" a la vista de lista densa (`vista === 'list'`) para no
alterar el `grid-template-columns` fijo de `.servicios-view__list-row` — el badge sólo vive en la
vista de tarjetas (`ServicioCard.vue`, Step 1) y en el detalle (Task 9).

En `<style scoped>`, agregar:

```css
.servicios-view__list-cliente.is-baja,
.servicios-view__preview-title.is-baja {
  color: var(--color-state-error);
}
```

- [ ] **Step 3: Verificar en el navegador (dev)**

Abrir `/servicios` en dev, alternar entre vista `grid` y `list`, y confirmar visualmente: un
servicio con estado de baja muestra el nombre en rojo en ambas vistas y en el panel de vista
previa; un servicio con `tipo_servicio` fuera de la lista verificable muestra el badge "No
verificable" en la tarjeta (vista grid).

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/components/servicios/ServicioCard.vue web/frontend/src/views/ServiciosView.vue
git commit -m "feat(servicios): nombre en rojo para servicios de baja y badge no verificable en el listado"
```
