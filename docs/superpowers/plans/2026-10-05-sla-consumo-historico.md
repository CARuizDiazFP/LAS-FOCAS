# Informe SLA Consumido + histórico de reclamos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generar, desde los Excel de Servicios y Reclamos, un informe de SLA consumido (x Evento, x Servicio, x Servicio x Reclamo, x Código de cierre, Carrier x Cliente, con gráficos) que al mismo tiempo persiste de forma idempotente un histórico de reclamos y fotos de SLA por servicio, visible en la vista Reclamos del detalle de servicio.

**Architecture:** Módulo nuevo `core/sla_consumo/` con capas puras (duraciones → clasificador → parser → engine → builders) y una capa de persistencia sync (psycopg3) sobre `app.reclamos` (ampliada), `app.sla_ingestas` y `app.servicio_sla_snapshot`. Un orquestador (`core/services/sla_consumo.py`) parsea → persiste → lee la ventana de 12 meses desde la DB → calcula → genera XLSX/DOCX/PDF. Se expone en `web/app/main.py` (`POST /api/reports/sla-consumo`) y el detalle de servicio (`api/app/routes/servicios.py`) devuelve los reclamos y el histórico de SLA.

**Tech Stack:** Python 3.11, pandas 2.2, openpyxl 3.1, python-docx 1.1, matplotlib 3.9 (Agg), SQLAlchemy 2 + Alembic, FastAPI, Vue 3 + TypeScript + Vite.

**Spec:** `/home/support-focal-01/.claude/plans/pasted-content-id-946d-problema-no-buzzing-curry.md` (plan aprobado 2026-10-05). Excel de referencia: `docs/Doc Privada/Servicios_ Nuevo SLA.xlsx`, `docs/Doc Privada/Reclamos_Nuevo SLA.xlsx` (privados, NO commitear ni copiar a tests).

## Global Constraints

- Base de horas: `Horas Netas Problema Reclamo`, guardada **en horas** (nunca minutos).
- Presupuesto anual: `(1 − SLA Prometido/100) · 8760` h. Métricas: `pct_presupuesto = horas / presupuesto · 100` y `pp_disponibilidad = horas / 8760 · 100`.
- Grupos (literales exactos): `"FO (excepto Cod 3)"`, `"FO Cod 3 (Corte en Bandeja)"`, `"Carrier"`, `"Otros"`, `"Cierre Cliente"`. Sólo `"Cierre Cliente"` NO consume SLA.
- FO = tipo de solución que empieza con `PE-`; Cod 3 = código numérico 3; Carrier = valor `Carrier`; Cliente = lista configurable `SLA_CIERRE_CLIENTE_VALORES` (env, separada por `;`, vacía por defecto); resto = Otros.
- Fecha de corte automática = máx. `Fecha Cierre Problema Reclamo` (fecha local `America/Argentina/Buenos_Aires`).
- Ventana del informe: reclamos con `fecha_inicio` en `(fecha_corte − 365 días, fecha_corte]`.
- Idempotencia: upsert por `numero_reclamo`; foto UNIQUE `(numero_linea, fecha_corte)`; resubir el mismo par no crea filas nuevas.
- `Número Evento = "-"` o vacío → NULL. Fila "Totales" del Excel de reclamos se descarta.
- Encabezado de archivo obligatorio en todo archivo nuevo (`# Nombre de archivo / # Ubicación de archivo / # Descripción`), como el resto del repo.
- Colores del frontend sólo vía tokens de `tokens.css` (skill `nocturne-token-compliance`).
- Todo el trabajo en el worktree `/home/support-focal-01/LAS-FOCAS-agentes/claude-slaconsumo-sla-consumo-historico`; `source .venv/bin/activate` antes de pytest/alembic. Nada en prod sin aviso explícito.
- Migraciones: adquirir lease `db:migrations` (`python scripts/agent_lock.py acquire "db:migrations" --agent claude-slaconsumo --reason "sla consumo"`), liberarlo al terminar la Task 4.

## Review Focus

1. **Duraciones > 24 h y > 60 días** en celdas `[h]:mm` (openpyxl las entrega como `datetime(1900,1,D,…)`; desde el serial 61 cambia el epoch por el bug del 29/02/1900) → horas exactas, nunca 0 ni NULL. Test en Task 1.
2. **Resubir el mismo par de archivos** dos veces, y luego un par con ventana solapada → 0 reclamos duplicados, fotos reemplazadas, conteo `insertados/actualizados` correcto. Test en Task 5.
3. **Un `Número Reclamo` repetido dentro del mismo archivo** → se queda la última fila, sin `CardinalityViolation` de Postgres. Test en Task 5.
4. **Reclamo cuya línea no está en el Excel de Servicios** (sin SLA Prometido) → aparece en los informes con presupuesto vacío y marca `sin_sla_prometido`, sin romper el engine ni dividir por cero. Test en Task 6.
5. **Servicio con `numero_linea` distinta a la del reclamo pero mismo `numero_primer_servicio` o alias** → la vista Reclamos del detalle igual los muestra. Test en Task 9.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `core/utils/excel_duraciones.py` (nuevo) | Celdas Excel → horas decimales y → datetime con tz |
| `core/sla_consumo/__init__.py` (nuevo) | Paquete |
| `core/sla_consumo/clasificador.py` (nuevo) | `clasificar_cierre()` → grupo + código |
| `core/sla_consumo/parser.py` (nuevo) | Bytes Excel → DataFrames normalizados de servicios y reclamos |
| `core/sla_consumo/persistencia.py` (nuevo) | Ingesta idempotente + lectura de ventana desde la DB |
| `core/sla_consumo/engine.py` (nuevo) | Cálculo de todas las vistas (pandas puro) |
| `core/sla_consumo/charts.py` (nuevo) | PNG de repercutores |
| `core/sla_consumo/xlsx_builder.py` (nuevo) | XLSX con una hoja por vista |
| `core/sla_consumo/docx_builder.py` (nuevo) | DOCX ejecutivo con gráficos |
| `core/services/sla_consumo.py` (nuevo) | Orquestador `generar_informe_sla_consumo()` |
| `db/models/reclamo.py` (mod) | Columnas nuevas |
| `db/models/sla_consumo.py` (nuevo) | `SlaIngesta`, `ServicioSlaSnapshot` |
| `db/alembic/versions/20261005_02_sla_consumo_historico.py` (nuevo) | Migración reversible + vista `app.v_eventos_sla` |
| `core/parsers/reclamos_excel.py` (mod) | Reemplaza conversión de horas/fechas rota |
| `core/parsers/reclamos_xlsx.py` (borrar) | Código muerto |
| `api/app/routes/ingest.py` (mod) | Lee Excel sin `dtype=str` |
| `api/app/routes/servicios.py` (mod) | `reclamos` + `sla_historico` en el detalle |
| `web/app/main.py` (mod) | `POST /api/reports/sla-consumo` |
| `web/frontend/src/composables/useSlaConsumo.ts` (nuevo) | Estado + llamada |
| `web/frontend/src/components/sla/SlaConsumoPanel.vue` (nuevo) | Pestaña "SLA consumido" |
| `web/frontend/src/views/SlaView.vue` (mod) | Tabs Informe SLA / SLA consumido |
| `web/frontend/src/views/servicios/ServicioReclamosView.vue` (mod) | Columnas fijas + histórico SLA |
| `web/frontend/src/api/servicios.ts` (mod) | Tipos `ReclamoServicio`, `SlaSnapshot` |
| `docs/informes/sla_consumo.md` (nuevo), `docs/decisiones.md`, `docs/PR/2026-10-05.md` | Documentación |

---

### Task 1: Conversión de celdas Excel (duraciones y fechas)

**Files:**
- Create: `core/utils/excel_duraciones.py`
- Test: `tests/test_excel_duraciones.py`

**Interfaces:**
- Produces: `duracion_a_horas(valor: object) -> float | None`; `fecha_excel(valor: object, tz: ZoneInfo = TZ_AR) -> pd.Timestamp | None`; constante `TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")`.

- [ ] **Step 1: Write the failing test**

```python
# Nombre de archivo: test_excel_duraciones.py
# Ubicación de archivo: tests/test_excel_duraciones.py
# Descripción: Conversión de celdas Excel [h]:mm y fechas seriales a horas/datetime

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from core.utils.excel_duraciones import TZ_AR, duracion_a_horas, fecha_excel


@pytest.mark.parametrize(
    "valor, esperado",
    [
        (dt.time(11, 41, 6), 11 + 41 / 60 + 6 / 3600),
        (dt.datetime(1900, 1, 1, 17, 55, 47), 24 + 17 + 55 / 60 + 47 / 3600),   # 41.93 h
        (dt.datetime(1900, 1, 16, 6, 3, 32), 16 * 24 + 6 + 3 / 60 + 32 / 3600),  # 390.06 h
        (dt.datetime(1900, 3, 1, 0, 0), 61 * 24.0),  # serial 61: epoch corrido por el 29/02/1900
        (pd.Timestamp("1900-01-02 06:00:00"), 54.0),
        (dt.timedelta(hours=30), 30.0),
        (0.5, 12.0),                   # serial en días
        (Decimal("1.25"), 30.0),
        ("030:15:00", 30.25),
        ("1,5", 1.5),                  # texto decimal = horas
        ("1 days 06:00:00", 30.0),
        ("-", None), ("", None), (None, None), (float("nan"), None),
    ],
)
def test_duracion_a_horas(valor, esperado):
    resultado = duracion_a_horas(valor)
    if esperado is None:
        assert resultado is None
    else:
        assert resultado == pytest.approx(esperado, abs=1e-6)


def test_fecha_excel_serial_y_iso_no_invierte_dia_mes():
    serial = fecha_excel(45957.5)
    assert serial == pd.Timestamp("2025-10-27 12:00:00", tz=TZ_AR)
    assert fecha_excel("2025-12-09 12:00:00") == pd.Timestamp("2025-12-09 12:00:00", tz=TZ_AR)
    assert fecha_excel("09/12/2025 12:00") == pd.Timestamp("2025-12-09 12:00:00", tz=TZ_AR)
    assert fecha_excel(dt.datetime(2026, 1, 5, 7, 44)) == pd.Timestamp("2026-01-05 07:44", tz=TZ_AR)
    assert fecha_excel("-") is None
    assert fecha_excel(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_excel_duraciones.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.utils.excel_duraciones'`

- [ ] **Step 3: Write minimal implementation**

```python
# Nombre de archivo: excel_duraciones.py
# Ubicación de archivo: core/utils/excel_duraciones.py
# Descripción: Convierte celdas Excel ([h]:mm, seriales, texto) a horas decimales y datetimes con tz

from __future__ import annotations

import datetime as dt
import math
import re
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd

TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")

# openpyxl convierte el serial s en datetime: s < 60 → 1899-12-31 + s; s ≥ 61 → 1899-12-30 + s
# (Excel cuenta el 29/02/1900 inexistente). Una duración [h]:mm es el serial en días.
_EPOCH_CORTO = dt.datetime(1899, 12, 31)
_EPOCH_LARGO = dt.datetime(1899, 12, 30)
_LIMITE_EPOCH = dt.datetime(1900, 3, 1)
_VACIOS = {"", "-", "nan", "none", "null", "nat"}
_HMS_RE = re.compile(r"^(\d+):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?$")


def _es_vacio(valor: object) -> bool:
    if valor is None or valor is pd.NaT or valor is pd.NA:
        return True
    if isinstance(valor, float) and math.isnan(valor):
        return True
    return isinstance(valor, str) and valor.strip().lower() in _VACIOS


def duracion_a_horas(valor: object) -> float | None:
    """Horas decimales de una celda de duración. Números puros = serial Excel en días."""
    if _es_vacio(valor):
        return None
    if isinstance(valor, (dt.timedelta, pd.Timedelta)):
        return pd.Timedelta(valor).total_seconds() / 3600
    if isinstance(valor, dt.datetime):  # incluye pd.Timestamp
        ingenuo = pd.Timestamp(valor).tz_localize(None).to_pydatetime()
        epoch = _EPOCH_LARGO if ingenuo >= _LIMITE_EPOCH else _EPOCH_CORTO
        return (ingenuo - epoch).total_seconds() / 3600
    if isinstance(valor, dt.time):
        return valor.hour + valor.minute / 60 + (valor.second + valor.microsecond / 1e6) / 3600
    if isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
        return float(valor) * 24
    texto = str(valor).strip().replace(",", ".")
    coincidencia = _HMS_RE.match(texto)
    if coincidencia:
        horas, minutos, segundos = coincidencia.groups()
        return int(horas) + int(minutos) / 60 + float(segundos or 0) / 3600
    try:
        return float(texto)
    except ValueError:
        pass
    try:
        return pd.to_timedelta(texto).total_seconds() / 3600
    except (ValueError, TypeError):
        return None


def fecha_excel(valor: object, tz: ZoneInfo = TZ_AR) -> pd.Timestamp | None:
    """Datetime con tz a partir de serial Excel, datetime o texto (ISO primero, luego dd/mm/aaaa)."""
    if _es_vacio(valor):
        return None
    if isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
        ts = pd.Timestamp(_EPOCH_LARGO) + pd.to_timedelta(float(valor), unit="D")
        ts = ts.round("s")
    elif isinstance(valor, dt.datetime):
        ts = pd.Timestamp(valor)
    else:
        texto = str(valor).strip()
        dayfirst = not re.match(r"^\d{4}-\d{2}-\d{2}", texto)
        ts = pd.to_datetime(texto, dayfirst=dayfirst, errors="coerce")
        if pd.isna(ts):
            return None
    return ts.tz_localize(tz) if ts.tzinfo is None else ts.tz_convert(tz)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_excel_duraciones.py -v`
Expected: PASS (all parametrized cases)

- [ ] **Step 5: Commit**

```bash
git add core/utils/excel_duraciones.py tests/test_excel_duraciones.py
git commit -m "feat(sla): conversión robusta de duraciones y fechas Excel a horas/datetime"
```

---

### Task 2: Clasificador de código de cierre

**Files:**
- Create: `core/sla_consumo/__init__.py`, `core/sla_consumo/clasificador.py`
- Test: `tests/test_sla_consumo_clasificador.py`

**Interfaces:**
- Produces: constantes `GRUPO_FO`, `GRUPO_FO_COD3`, `GRUPO_CARRIER`, `GRUPO_OTROS`, `GRUPO_CLIENTE`, `GRUPOS_ORDEN: tuple[str, ...]`; `@dataclass(frozen=True) Cierre(grupo: str, codigo: int | None, cuenta_sla: bool)`; `clasificar_cierre(tipo_solucion: str | None, valores_cliente: frozenset[str] | None = None) -> Cierre`; `valores_cliente_config() -> frozenset[str]` (lee env `SLA_CIERRE_CLIENTE_VALORES`, normalizado).

- [ ] **Step 1: Write the failing test**

```python
# Nombre de archivo: test_sla_consumo_clasificador.py
# Ubicación de archivo: tests/test_sla_consumo_clasificador.py
# Descripción: Agrupación de Tipo Solución Reclamo en los grupos del informe SLA consumido

from __future__ import annotations

import pytest

from core.sla_consumo.clasificador import (
    GRUPO_CARRIER, GRUPO_CLIENTE, GRUPO_FO, GRUPO_FO_COD3, GRUPO_OTROS,
    clasificar_cierre, valores_cliente_config,
)

# Valores reales observados en Reclamos_Nuevo SLA.xlsx (2026-10-05), incluidos los truncados.
CASOS = [
    ("PE-I-FO Corte/Aten Troncal Can/Subt (7)", GRUPO_FO, 7),
    ("PE-I-FO Corte/Atenuacion Troncal Aereo (vand.) (91", GRUPO_FO, 91),
    ("PE-E-FO Corte en Bandeja (3)", GRUPO_FO_COD3, 3),
    ("PE-E-FO Corte Empalme (2)", GRUPO_FO, 2),
    ("PE-I Error Manipulacion de Instaladores (12)", GRUPO_FO, 12),
    ("PE-E-Error de documentacion en red On Net (18)", GRUPO_FO, 18),
    ("Carrier", GRUPO_CARRIER, None),
    ("  carrier ", GRUPO_CARRIER, None),
    ("IN - Falla Equipo CPE", GRUPO_OTROS, None),
    ("OP-conf-asegured", GRUPO_OTROS, None),
    ("TE - Falla Carrier", GRUPO_OTROS, None),
    ("DC - Reset/Configuración VM", GRUPO_OTROS, None),
    ("Problema Masivo  - Contingencia Metrotel", GRUPO_OTROS, None),
    (None, GRUPO_OTROS, None),
    ("-", GRUPO_OTROS, None),
]


@pytest.mark.parametrize("tipo, grupo, codigo", CASOS)
def test_clasificar_cierre(tipo, grupo, codigo):
    cierre = clasificar_cierre(tipo, frozenset())
    assert (cierre.grupo, cierre.codigo, cierre.cuenta_sla) == (grupo, codigo, True)


def test_cierre_cliente_configurable_no_cuenta_sla(monkeypatch):
    monkeypatch.setenv("SLA_CIERRE_CLIENTE_VALORES", "Cliente; CL - Falla en sitio del cliente")
    valores = valores_cliente_config()
    cierre = clasificar_cierre("cl - falla en sitio del CLIENTE", valores)
    assert cierre.grupo == GRUPO_CLIENTE
    assert cierre.cuenta_sla is False
    assert clasificar_cierre("Carrier", valores).grupo == GRUPO_CARRIER


def test_sin_config_cliente_vacio(monkeypatch):
    monkeypatch.delenv("SLA_CIERRE_CLIENTE_VALORES", raising=False)
    assert valores_cliente_config() == frozenset()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sla_consumo_clasificador.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.sla_consumo'`

- [ ] **Step 3: Write minimal implementation**

`core/sla_consumo/__init__.py`:

```python
# Nombre de archivo: __init__.py
# Ubicación de archivo: core/sla_consumo/__init__.py
# Descripción: Informe de SLA consumido por evento/servicio/reclamo/código de cierre
```

`core/sla_consumo/clasificador.py`:

```python
# Nombre de archivo: clasificador.py
# Ubicación de archivo: core/sla_consumo/clasificador.py
# Descripción: Agrupa el Tipo Solución Reclamo en FO / FO Cod 3 / Carrier / Otros / Cierre Cliente

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

GRUPO_FO = "FO (excepto Cod 3)"
GRUPO_FO_COD3 = "FO Cod 3 (Corte en Bandeja)"
GRUPO_CARRIER = "Carrier"
GRUPO_OTROS = "Otros"
GRUPO_CLIENTE = "Cierre Cliente"
GRUPOS_ORDEN: tuple[str, ...] = (GRUPO_FO, GRUPO_FO_COD3, GRUPO_CARRIER, GRUPO_OTROS, GRUPO_CLIENTE)

# El código va entre paréntesis al final; el origen trunca a 50 caracteres y puede faltar el ")".
_CODIGO_RE = re.compile(r"\((\d+)\)?\s*$")


@dataclass(frozen=True)
class Cierre:
    grupo: str
    codigo: int | None
    cuenta_sla: bool


def _normalizar(texto: str) -> str:
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sin_acentos).strip().lower()


def valores_cliente_config() -> frozenset[str]:
    crudo = os.getenv("SLA_CIERRE_CLIENTE_VALORES", "")
    return frozenset(_normalizar(v) for v in crudo.split(";") if v.strip())


def clasificar_cierre(tipo_solucion: str | None, valores_cliente: frozenset[str] | None = None) -> Cierre:
    if valores_cliente is None:
        valores_cliente = valores_cliente_config()
    texto = _normalizar(tipo_solucion or "")
    coincidencia = _CODIGO_RE.search(texto)
    codigo = int(coincidencia.group(1)) if coincidencia else None
    if texto in valores_cliente:
        return Cierre(GRUPO_CLIENTE, codigo, cuenta_sla=False)
    if texto == "carrier":
        return Cierre(GRUPO_CARRIER, None, cuenta_sla=True)
    if texto.startswith("pe-"):
        grupo = GRUPO_FO_COD3 if codigo == 3 else GRUPO_FO
        return Cierre(grupo, codigo, cuenta_sla=True)
    return Cierre(GRUPO_OTROS, None, cuenta_sla=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sla_consumo_clasificador.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/sla_consumo/__init__.py core/sla_consumo/clasificador.py tests/test_sla_consumo_clasificador.py
git commit -m "feat(sla): clasificador de código de cierre para SLA consumido"
```

---

### Task 3: Parser de los dos Excel

**Files:**
- Create: `core/sla_consumo/parser.py`
- Test: `tests/test_sla_consumo_parser.py`

**Interfaces:**
- Consumes: `duracion_a_horas`, `fecha_excel` (Task 1); `clasificar_cierre`, `valores_cliente_config` (Task 2); `core.sla.legacy_report._normalize`, `_normalize_line_value`.
- Produces:
  - `parse_servicios(content: bytes) -> pd.DataFrame` con columnas `SERVICIOS_COLS = ["numero_linea", "numero_primer_servicio", "nombre_cliente", "tipo_servicio", "sla_prometido", "sla_entregado", "horas_reclamos_mes", "horas_carriers_mes", "horas_reclamos_todos", "horas_carriers_todos", "horas_restantes", "abono_usd", "cantidad_reclamos_todos"]` (`sla_prometido` en %, p. ej. 99.7; `sla_entregado` fracción 0-1).
  - `parse_reclamos(content: bytes) -> pd.DataFrame` con columnas `RECLAMOS_COLS = ["numero_reclamo", "numero_evento", "numero_linea", "numero_primer_servicio", "tipo_servicio", "nombre_cliente", "fecha_inicio", "fecha_cierre", "horas_totales_problema", "horas_indisponibilidad_problema", "horas_netas", "horas_netas_escalamiento_carrier", "sector_responsable", "descripcion_problema", "tipo_solucion", "descripcion_solucion", "carrier", "numero_reclamo_carrier", "codigo_cierre", "grupo_cierre"]`. Dedup por `numero_reclamo` (`keep="last"`), sin fila "Totales".
  - `fecha_corte(reclamos: pd.DataFrame) -> datetime.date`.
  - Error: `ValueError("Faltan columnas en <tipo>: ...")` si falta una columna obligatoria.

- [ ] **Step 1: Write the failing test**

```python
# Nombre de archivo: test_sla_consumo_parser.py
# Ubicación de archivo: tests/test_sla_consumo_parser.py
# Descripción: Parser de los Excel Servicios/Reclamos del informe SLA consumido (celdas como las reales)

from __future__ import annotations

import datetime as dt
import io

import openpyxl
import pytest

from core.sla_consumo.parser import fecha_corte, parse_reclamos, parse_servicios

RECLAMOS_HEADERS = [
    "Número Reclamo", "Número Evento", "Número Línea Reclamo", "Número Primer Servicio", "Número Línea",
    "Tipo Servicio", "Nombre Cliente", "Fecha Inicio Problema Reclamo", "Fecha Cierre Problema Reclamo",
    "Horas Totales Problema Reclamo", "Horas Indisponibilidad Problema Reclamo",
    "Horas Netas Problema Reclamo", "Horas Netas Escalamientos Carriers", "Sector Responsable Reclamo",
    "Descripción Problema Reclamo", "Tipo Solución Reclamo", "Descripción Solución Reclamo",
    "Carrier Reclamo", "Número Reclamo Carrier",
]
SERVICIOS_HEADERS = [
    "Número Primer Servicio", "Número Línea", "Tipo Servicio", "Nombre Cliente",
    "Horas Carriers Mes", "Horas Reclamos Mes", "Cantidad Reclamos Todos", "Horas Carriers Todos",
    "Horas Reclamos Todos", "Horas Restantes Límite SLA", "SLA Prometido", "SLA \nEntregado", "Abono \nUSD",
]


def _xlsx(headers, filas) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for fila in filas:
        ws.append(fila)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _reclamo(numero, evento="-", linea=76232, netas=dt.datetime(1900, 1, 6, 3, 21, 2), tipo="Carrier",
             inicio=45957.42457175926, cierre=45964.72430555556):
    return [numero, evento, linea, linea, linea, "RPV", "BANCO X", inicio, cierre,
            dt.datetime(1900, 1, 7, 7, 11, 37), dt.datetime(1900, 1, 1, 3, 50, 35), netas,
            dt.time(1, 53, 31), "NOC", "Enlace caído", tipo, "Se normalizó", "TELESPAZIO ARG SA", "jD"]


def test_parse_reclamos_convierte_horas_largas_eventos_y_descarta_totales():
    contenido = _xlsx(RECLAMOS_HEADERS, [
        ["Totales"] + [""] * (len(RECLAMOS_HEADERS) - 1),
        _reclamo(1226756),
        _reclamo(1227405, evento=1229336, linea=94058, netas=dt.time(11, 41, 6),
                 tipo="PE-E-FO Corte en Bandeja (3)"),
        _reclamo(1227405, evento=1229336, linea=94058, netas=dt.time(12, 0, 0),
                 tipo="PE-E-FO Corte en Bandeja (3)"),  # duplicado: gana la última
    ])
    df = parse_reclamos(contenido)
    assert list(df["numero_reclamo"]) == ["1226756", "1227405"]
    fila = df.set_index("numero_reclamo")
    assert fila.loc["1226756", "horas_netas"] == pytest.approx(6 * 24 + 3 + 21 / 60 + 2 / 3600)
    assert fila.loc["1226756", "numero_evento"] is None
    assert fila.loc["1227405", "numero_evento"] == "1229336"
    assert fila.loc["1227405", "horas_netas"] == pytest.approx(12.0)
    assert fila.loc["1227405", "grupo_cierre"] == "FO Cod 3 (Corte en Bandeja)"
    assert fila.loc["1227405", "codigo_cierre"] == 3
    assert fila.loc["1226756", "numero_linea"] == "76232"
    assert fila.loc["1226756", "fecha_inicio"].month == 10  # serial 45957 = 27/10/2025, sin inversión
    assert fecha_corte(df) == dt.date(2025, 11, 3)


def test_parse_reclamos_falta_columna():
    with pytest.raises(ValueError, match="Faltan columnas en reclamos"):
        parse_reclamos(_xlsx(["Número Reclamo"], [[1]]))


def test_parse_servicios_convierte_sla_y_horas():
    contenido = _xlsx(SERVICIOS_HEADERS, [[
        88102, 88102, "RPV", "BANCO MACRO SA", dt.time(0, 0), dt.time(0, 0), 6,
        dt.datetime(1900, 1, 15, 22, 34, 6), dt.datetime(1900, 1, 16, 6, 3, 32), dt.time(0, 0),
        99.7, 0.9554737442922374, 670,
    ]])
    df = parse_servicios(contenido)
    fila = df.iloc[0]
    assert fila["numero_linea"] == "88102"
    assert fila["sla_prometido"] == pytest.approx(99.7)
    assert fila["sla_entregado"] == pytest.approx(0.95547, abs=1e-5)
    assert fila["horas_reclamos_todos"] == pytest.approx(390.0589, abs=1e-3)
    assert 1 - fila["horas_reclamos_todos"] / 8760 == pytest.approx(fila["sla_entregado"], abs=1e-5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sla_consumo_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.sla_consumo.parser'`

- [ ] **Step 3: Write minimal implementation**

```python
# Nombre de archivo: parser.py
# Ubicación de archivo: core/sla_consumo/parser.py
# Descripción: Lee los Excel Servicios/Reclamos del informe SLA consumido con tipos reales (sin dtype=str)

from __future__ import annotations

import datetime as dt
import io

import pandas as pd

from core.sla.legacy_report import _normalize, _normalize_line_value
from core.sla_consumo.clasificador import clasificar_cierre, valores_cliente_config
from core.utils.excel_duraciones import TZ_AR, duracion_a_horas, fecha_excel

# encabezado normalizado (_normalize) → columna destino
_RECLAMOS_MAP = {
    "numero reclamo": "numero_reclamo",
    "numero evento": "numero_evento",
    "numero linea": "numero_linea",
    "numero primer servicio": "numero_primer_servicio",
    "tipo servicio": "tipo_servicio",
    "nombre cliente": "nombre_cliente",
    "fecha inicio problema reclamo": "fecha_inicio",
    "fecha cierre problema reclamo": "fecha_cierre",
    "horas totales problema reclamo": "horas_totales_problema",
    "horas indisponibilidad problema reclamo": "horas_indisponibilidad_problema",
    "horas netas problema reclamo": "horas_netas",
    "horas netas escalamientos carriers": "horas_netas_escalamiento_carrier",
    "sector responsable reclamo": "sector_responsable",
    "descripcion problema reclamo": "descripcion_problema",
    "tipo solucion reclamo": "tipo_solucion",
    "descripcion solucion reclamo": "descripcion_solucion",
    "carrier reclamo": "carrier",
    "numero reclamo carrier": "numero_reclamo_carrier",
}
_RECLAMOS_OBLIGATORIAS = ["numero_reclamo", "numero_linea", "nombre_cliente", "fecha_inicio",
                          "fecha_cierre", "horas_netas", "tipo_solucion"]
_RECLAMOS_HORAS = ["horas_totales_problema", "horas_indisponibilidad_problema", "horas_netas",
                   "horas_netas_escalamiento_carrier"]
RECLAMOS_COLS = list(dict.fromkeys(_RECLAMOS_MAP.values())) + ["codigo_cierre", "grupo_cierre"]

_SERVICIOS_MAP = {
    "numero linea": "numero_linea",
    "numero primer servicio": "numero_primer_servicio",
    "nombre cliente": "nombre_cliente",
    "tipo servicio": "tipo_servicio",
    "sla prometido": "sla_prometido",
    "sla entregado": "sla_entregado",
    "horas reclamos mes": "horas_reclamos_mes",
    "horas carriers mes": "horas_carriers_mes",
    "horas reclamos todos": "horas_reclamos_todos",
    "horas carriers todos": "horas_carriers_todos",
    "horas restantes limite sla": "horas_restantes",
    "abono usd": "abono_usd",
    "cantidad reclamos todos": "cantidad_reclamos_todos",
}
_SERVICIOS_OBLIGATORIAS = ["numero_linea", "nombre_cliente", "sla_prometido", "horas_reclamos_todos"]
_SERVICIOS_HORAS = ["horas_reclamos_mes", "horas_carriers_mes", "horas_reclamos_todos",
                    "horas_carriers_todos", "horas_restantes"]
SERVICIOS_COLS = list(_SERVICIOS_MAP.values())


def _leer(content: bytes, mapa: dict[str, str], obligatorias: list[str], tipo: str) -> pd.DataFrame:
    # Primera hoja siempre (Servicios trae una "Hoja2" filtrada a mano que se ignora).
    df = pd.read_excel(io.BytesIO(content), sheet_name=0, engine="openpyxl")
    renombres = {}
    for col in df.columns:
        destino = mapa.get(_normalize(str(col)))
        if destino and destino not in renombres.values():
            renombres[col] = destino
    df = df.rename(columns=renombres)
    faltan = [c for c in obligatorias if c not in df.columns]
    if faltan:
        raise ValueError(f"Faltan columnas en {tipo}: {', '.join(faltan)}")
    for col in mapa.values():
        if col not in df.columns:
            df[col] = None
    return df[list(dict.fromkeys(mapa.values()))]


def _texto(valor: object) -> str | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = _normalize_line_value(valor)
    return None if texto in ("", "-") else texto


def parse_reclamos(content: bytes) -> pd.DataFrame:
    df = _leer(content, _RECLAMOS_MAP, _RECLAMOS_OBLIGATORIAS, "reclamos")
    df["numero_reclamo"] = df["numero_reclamo"].map(_texto)
    df = df[df["numero_reclamo"].notna() & (df["numero_reclamo"].str.lower() != "totales")].copy()
    for col in ("numero_evento", "numero_linea", "numero_primer_servicio", "numero_reclamo_carrier",
                "carrier", "tipo_servicio", "nombre_cliente", "sector_responsable", "tipo_solucion",
                "descripcion_problema", "descripcion_solucion"):
        df[col] = df[col].map(_texto)
    for col in _RECLAMOS_HORAS:
        df[col] = df[col].map(duracion_a_horas)
    df["fecha_inicio"] = df["fecha_inicio"].map(fecha_excel)
    df["fecha_cierre"] = df["fecha_cierre"].map(fecha_excel)
    df = df[df["numero_linea"].notna() & df["fecha_inicio"].notna()]
    valores_cliente = valores_cliente_config()
    cierres = df["tipo_solucion"].map(lambda t: clasificar_cierre(t, valores_cliente))
    df["codigo_cierre"] = cierres.map(lambda c: c.codigo).astype("Int64")
    df["grupo_cierre"] = cierres.map(lambda c: c.grupo)
    df = df.drop_duplicates(subset="numero_reclamo", keep="last").reset_index(drop=True)
    return df[RECLAMOS_COLS]


def _sla_pct(valor: object) -> float | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    numero = float(str(valor).replace("%", "").replace(",", ".").strip())
    return numero


def parse_servicios(content: bytes) -> pd.DataFrame:
    df = _leer(content, _SERVICIOS_MAP, _SERVICIOS_OBLIGATORIAS, "servicios")
    for col in ("numero_linea", "numero_primer_servicio", "nombre_cliente", "tipo_servicio"):
        df[col] = df[col].map(_texto)
    df = df[df["numero_linea"].notna()].copy()
    df["sla_prometido"] = df["sla_prometido"].map(_sla_pct)          # 99.7
    df["sla_entregado"] = df["sla_entregado"].map(_sla_pct)
    df.loc[df["sla_entregado"] > 1, "sla_entregado"] /= 100            # siempre fracción 0-1
    for col in _SERVICIOS_HORAS:
        df[col] = df[col].map(duracion_a_horas)
    df["abono_usd"] = pd.to_numeric(df["abono_usd"], errors="coerce")
    df["cantidad_reclamos_todos"] = pd.to_numeric(df["cantidad_reclamos_todos"], errors="coerce").astype("Int64")
    return df.drop_duplicates(subset="numero_linea", keep="last").reset_index(drop=True)[SERVICIOS_COLS]


def fecha_corte(reclamos: pd.DataFrame) -> dt.date:
    maximo = reclamos["fecha_cierre"].dropna().max()
    if maximo is None or pd.isna(maximo):
        maximo = reclamos["fecha_inicio"].max()
    return pd.Timestamp(maximo).tz_convert(TZ_AR).date()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sla_consumo_parser.py -v`
Expected: PASS

- [ ] **Step 5: Smoke contra los Excel reales (no se commitea nada)**

```bash
python - <<'EOF'
from pathlib import Path
from core.sla_consumo.parser import parse_reclamos, parse_servicios, fecha_corte
base = Path("/home/support-focal-01/LAS-FOCAS/docs/Doc Privada")
r = parse_reclamos((base / "Reclamos_Nuevo SLA.xlsx").read_bytes())
s = parse_servicios((base / "Servicios_ Nuevo SLA.xlsx").read_bytes())
print(len(r), r["numero_evento"].nunique(), r["horas_netas"].isna().sum(), r["grupo_cierre"].value_counts().to_dict())
print(len(s), fecha_corte(r))
EOF
```
Expected: `4518 402 0 {...FO..., 'Carrier': 581, 'FO Cod 3 (Corte en Bandeja)': 154, ...}` y `7228 2026-10-0X`.

- [ ] **Step 6: Commit**

```bash
git add core/sla_consumo/parser.py tests/test_sla_consumo_parser.py
git commit -m "feat(sla): parser de Excel Servicios/Reclamos para SLA consumido"
```

---

### Task 4: Migración y modelos del histórico

**Files:**
- Modify: `db/models/reclamo.py`
- Create: `db/models/sla_consumo.py`, `db/alembic/versions/20261005_02_sla_consumo_historico.py`
- Modify: `db/models/__init__.py` (exportar los modelos nuevos si el paquete los registra ahí; verificar con `grep -n "Reclamo" db/models/__init__.py`)
- Test: `tests/test_sla_consumo_migracion_real_db.py`

**Interfaces:**
- Produces: tablas `app.reclamos` (columnas nuevas), `app.sla_ingestas`, `app.servicio_sla_snapshot`, vista `app.v_eventos_sla`; modelos `SlaIngesta`, `ServicioSlaSnapshot`.

- [ ] **Step 0: Lease**

```bash
python scripts/agent_lock.py acquire "db:migrations" --agent claude-slaconsumo --reason "sla consumo historico"
alembic heads   # debe ser 20261005_01; si no, usar el head real como down_revision
```

- [ ] **Step 1: Write the failing test**

```python
# Nombre de archivo: test_sla_consumo_migracion_real_db.py
# Ubicación de archivo: tests/test_sla_consumo_migracion_real_db.py
# Descripción: El esquema del histórico SLA consumido existe en Postgres real (tablas, columnas, vista)

from __future__ import annotations

from sqlalchemy import text

from db.session import SessionLocal
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real


def _columnas(session, tabla: str) -> dict[str, str]:
    filas = session.execute(text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'app' AND table_name = :t"), {"t": tabla}).all()
    return {f.column_name: f.data_type for f in filas}


def test_esquema_historico_sla():
    with SessionLocal() as session:
        reclamos = _columnas(session, "reclamos")
        for col in ("horas_totales_problema", "horas_indisponibilidad_problema",
                    "horas_netas_escalamiento_carrier", "carrier", "numero_reclamo_carrier",
                    "numero_primer_servicio", "sector_responsable", "descripcion_problema",
                    "codigo_cierre", "grupo_cierre", "ingesta_id", "first_seen_at", "last_seen_at"):
            assert col in reclamos, col
        assert reclamos["horas_netas"] == "numeric"
        assert {"fecha_corte", "hash_servicios", "hash_reclamos"} <= set(_columnas(session, "sla_ingestas"))
        assert {"numero_linea", "fecha_corte", "sla_prometido", "sla_entregado"} <= set(
            _columnas(session, "servicio_sla_snapshot"))
        session.execute(text("SELECT * FROM app.v_eventos_sla LIMIT 1"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sla_consumo_migracion_real_db.py -v`
Expected: FAIL (`AssertionError: horas_totales_problema`). Si dice SKIPPED, levantar el compose dev (`docker compose --env-file .env.dev ...`, ver `tests/soporte_postgres_real.py`) y reintentar: este test no puede quedar en SKIP.

- [ ] **Step 3: Models**

`db/models/reclamo.py` — reemplazar el cuerpo de la clase por:

```python
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, func


class Reclamo(Base):
    __tablename__ = "reclamos"
    __table_args__ = {"schema": "app"}

    numero_reclamo = Column(String(64), primary_key=True)
    numero_evento = Column(String(64), nullable=True, index=True)
    numero_linea = Column(String(64), nullable=False, index=True)
    numero_primer_servicio = Column(String(64), nullable=True, index=True)
    tipo_servicio = Column(String(80), nullable=True, index=True)
    nombre_cliente = Column(String(128), nullable=False, index=True)
    tipo_solucion = Column(String(160), nullable=True)
    codigo_cierre = Column(Integer, nullable=True)
    grupo_cierre = Column(String(40), nullable=True, index=True)
    fecha_inicio = Column(DateTime(timezone=True), nullable=True, index=True)
    fecha_cierre = Column(DateTime(timezone=True), nullable=True, index=True)
    # Horas decimales (no minutos). Base del SLA: Horas Netas Problema Reclamo.
    horas_netas = Column(Numeric(12, 4), nullable=True)
    horas_totales_problema = Column(Numeric(12, 4), nullable=True)
    horas_indisponibilidad_problema = Column(Numeric(12, 4), nullable=True)
    horas_netas_escalamiento_carrier = Column(Numeric(12, 4), nullable=True)
    carrier = Column(String(128), nullable=True)
    numero_reclamo_carrier = Column(String(128), nullable=True)
    sector_responsable = Column(String(80), nullable=True)
    descripcion_problema = Column(Text, nullable=True)
    descripcion_solucion = Column(Text, nullable=True)
    latitud = Column(Numeric(9, 6), nullable=True)
    longitud = Column(Numeric(9, 6), nullable=True)
    ingesta_id = Column(BigInteger, ForeignKey("app.sla_ingestas.id", ondelete="SET NULL"), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=True, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=True, server_default=func.now())
```

`db/models/sla_consumo.py`:

```python
# Nombre de archivo: sla_consumo.py
# Ubicación de archivo: db/models/sla_consumo.py
# Descripción: Ingestas del informe SLA consumido y fotos de SLA por servicio y fecha de corte

from __future__ import annotations

from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, Numeric, String, UniqueConstraint, func

from db.base import Base


class SlaIngesta(Base):
    __tablename__ = "sla_ingestas"
    __table_args__ = (UniqueConstraint("hash_servicios", "hash_reclamos", name="uq_sla_ingestas_hashes"),
                      {"schema": "app"})

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    fecha_corte = Column(Date, nullable=False, index=True)
    hash_servicios = Column(String(64), nullable=False)
    hash_reclamos = Column(String(64), nullable=False)
    usuario = Column(String(128), nullable=True)
    reclamos_insertados = Column(Integer, nullable=False, default=0)
    reclamos_actualizados = Column(Integer, nullable=False, default=0)
    servicios_snapshot = Column(Integer, nullable=False, default=0)
    report_history_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ServicioSlaSnapshot(Base):
    __tablename__ = "servicio_sla_snapshot"
    __table_args__ = (UniqueConstraint("numero_linea", "fecha_corte", name="uq_sla_snapshot_linea_corte"),
                      {"schema": "app"})

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    numero_linea = Column(String(64), nullable=False, index=True)
    numero_primer_servicio = Column(String(64), nullable=True, index=True)
    fecha_corte = Column(Date, nullable=False, index=True)
    nombre_cliente = Column(String(128), nullable=True)
    tipo_servicio = Column(String(80), nullable=True)
    sla_prometido = Column(Numeric(6, 3), nullable=True)
    sla_entregado = Column(Numeric(9, 6), nullable=True)
    horas_reclamos_mes = Column(Numeric(12, 4), nullable=True)
    horas_carriers_mes = Column(Numeric(12, 4), nullable=True)
    horas_reclamos_todos = Column(Numeric(12, 4), nullable=True)
    horas_carriers_todos = Column(Numeric(12, 4), nullable=True)
    horas_restantes = Column(Numeric(12, 4), nullable=True)
    abono_usd = Column(Numeric(14, 2), nullable=True)
    cantidad_reclamos_todos = Column(Integer, nullable=True)
    ingesta_id = Column(BigInteger, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

- [ ] **Step 4: Migración**

```python
# Nombre de archivo: 20261005_02_sla_consumo_historico.py
# Ubicación de archivo: db/alembic/versions/20261005_02_sla_consumo_historico.py
# Descripción: Histórico SLA consumido — amplía app.reclamos, crea sla_ingestas, servicio_sla_snapshot y v_eventos_sla

"""sla_consumo_historico

Revision ID: 20261005_02
Revises: 20261005_01
Create Date: 2026-10-05

Cambios:
- ``app.reclamos``: horas en horas decimales Numeric(12,4) (antes Numeric(10,2) con minutos por bug
  del parser; la tabla estaba vacía en dev y prod el 2026-10-05), columnas de Carrier, código y
  grupo de cierre, ingesta y first/last seen.
- ``app.sla_ingestas`` (una fila por par de archivos, única por hashes).
- ``app.servicio_sla_snapshot`` (foto del Excel de Servicios por fecha de corte).
- Vista ``app.v_eventos_sla`` derivada de reclamos.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261005_02"
down_revision = "20261005_01"
branch_labels = None
depends_on = None

_NUEVAS = [
    ("numero_primer_servicio", sa.String(64)),
    ("codigo_cierre", sa.Integer()),
    ("grupo_cierre", sa.String(40)),
    ("horas_totales_problema", sa.Numeric(12, 4)),
    ("horas_indisponibilidad_problema", sa.Numeric(12, 4)),
    ("horas_netas_escalamiento_carrier", sa.Numeric(12, 4)),
    ("carrier", sa.String(128)),
    ("numero_reclamo_carrier", sa.String(128)),
    ("sector_responsable", sa.String(80)),
    ("descripcion_problema", sa.Text()),
]


def upgrade() -> None:
    op.create_table(
        "sla_ingestas",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("fecha_corte", sa.Date(), nullable=False, index=True),
        sa.Column("hash_servicios", sa.String(64), nullable=False),
        sa.Column("hash_reclamos", sa.String(64), nullable=False),
        sa.Column("usuario", sa.String(128)),
        sa.Column("reclamos_insertados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reclamos_actualizados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("servicios_snapshot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report_history_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("hash_servicios", "hash_reclamos", name="uq_sla_ingestas_hashes"),
        schema="app",
    )
    op.create_table(
        "servicio_sla_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("numero_linea", sa.String(64), nullable=False, index=True),
        sa.Column("numero_primer_servicio", sa.String(64), index=True),
        sa.Column("fecha_corte", sa.Date(), nullable=False, index=True),
        sa.Column("nombre_cliente", sa.String(128)),
        sa.Column("tipo_servicio", sa.String(80)),
        sa.Column("sla_prometido", sa.Numeric(6, 3)),
        sa.Column("sla_entregado", sa.Numeric(9, 6)),
        sa.Column("horas_reclamos_mes", sa.Numeric(12, 4)),
        sa.Column("horas_carriers_mes", sa.Numeric(12, 4)),
        sa.Column("horas_reclamos_todos", sa.Numeric(12, 4)),
        sa.Column("horas_carriers_todos", sa.Numeric(12, 4)),
        sa.Column("horas_restantes", sa.Numeric(12, 4)),
        sa.Column("abono_usd", sa.Numeric(14, 2)),
        sa.Column("cantidad_reclamos_todos", sa.Integer()),
        sa.Column("ingesta_id", sa.BigInteger()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("numero_linea", "fecha_corte", name="uq_sla_snapshot_linea_corte"),
        schema="app",
    )
    for nombre, tipo in _NUEVAS:
        op.add_column("reclamos", sa.Column(nombre, tipo, nullable=True), schema="app")
    op.add_column("reclamos", sa.Column("ingesta_id", sa.BigInteger(),
                  sa.ForeignKey("app.sla_ingestas.id", ondelete="SET NULL")), schema="app")
    op.add_column("reclamos", sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()), schema="app")
    op.add_column("reclamos", sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()), schema="app")
    op.alter_column("reclamos", "horas_netas", type_=sa.Numeric(12, 4), schema="app")
    op.alter_column("reclamos", "tipo_solucion", type_=sa.String(160), schema="app")
    op.create_index("ix_app_reclamos_numero_primer_servicio", "reclamos", ["numero_primer_servicio"], schema="app")
    op.create_index("ix_app_reclamos_grupo_cierre", "reclamos", ["grupo_cierre"], schema="app")
    op.create_index("ix_app_reclamos_fecha_inicio", "reclamos", ["fecha_inicio"], schema="app")
    op.execute("""
        CREATE VIEW app.v_eventos_sla AS
        SELECT numero_evento,
               COUNT(*) AS reclamos,
               COUNT(DISTINCT numero_linea) AS servicios_afectados,
               MIN(fecha_inicio) AS inicio,
               MAX(fecha_cierre) AS cierre,
               SUM(horas_netas) AS horas_netas,
               MODE() WITHIN GROUP (ORDER BY grupo_cierre) AS grupo_predominante
        FROM app.reclamos
        WHERE numero_evento IS NOT NULL
        GROUP BY numero_evento
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS app.v_eventos_sla")
    op.drop_index("ix_app_reclamos_fecha_inicio", table_name="reclamos", schema="app")
    op.drop_index("ix_app_reclamos_grupo_cierre", table_name="reclamos", schema="app")
    op.drop_index("ix_app_reclamos_numero_primer_servicio", table_name="reclamos", schema="app")
    op.alter_column("reclamos", "tipo_solucion", type_=sa.String(80), schema="app")
    op.alter_column("reclamos", "horas_netas", type_=sa.Numeric(10, 2), schema="app")
    for nombre in ("last_seen_at", "first_seen_at", "ingesta_id"):
        op.drop_column("reclamos", nombre, schema="app")
    for nombre, _ in reversed(_NUEVAS):
        op.drop_column("reclamos", nombre, schema="app")
    op.drop_table("servicio_sla_snapshot", schema="app")
    op.drop_table("sla_ingestas", schema="app")
```

Nota: el índice de `fecha_inicio` ya podría existir si el modelo lo declara con `index=True` y alguna migración previa lo creó — verificar con `\d app.reclamos` antes; si existe, no crearlo.

- [ ] **Step 5: Aplicar, probar reversibilidad y correr el test**

```bash
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
pytest tests/test_sla_consumo_migracion_real_db.py -v
```
Expected: los tres comandos alembic sin error; test PASS.

- [ ] **Step 6: Commit y liberar lease**

```bash
git add db/models/reclamo.py db/models/sla_consumo.py db/models/__init__.py db/alembic/versions/20261005_02_sla_consumo_historico.py tests/test_sla_consumo_migracion_real_db.py
git commit -m "feat(db): histórico SLA consumido — reclamos ampliados, ingestas, fotos de SLA y vista de eventos"
python scripts/agent_lock.py release "db:migrations" --agent claude-slaconsumo
```

---

### Task 5: Persistencia idempotente + arreglo de `/ingest/reclamos`

**Files:**
- Create: `core/sla_consumo/persistencia.py`
- Modify: `core/parsers/reclamos_excel.py` (horas con `duracion_a_horas`, fechas con `fecha_excel`, `"-"` → None, dedup), `api/app/routes/ingest.py:41-43` (quitar `dtype=str, keep_default_na=False` en Excel), `core/services/repetitividad.py:45-73` (`upsert_reclamos` delega en `upsert_reclamos_df`)
- Delete: `core/parsers/reclamos_xlsx.py` (verificar antes `grep -rn reclamos_xlsx --include=*.py .` = sólo el propio archivo)
- Modify: `tests/test_ingest_parser.py` (horas esperadas en horas: `"1,5"` → 1.5)
- Test: `tests/test_sla_consumo_persistencia_real_db.py`

**Interfaces:**
- Consumes: `parse_reclamos`, `parse_servicios`, `fecha_corte` (Task 3); tablas de Task 4.
- Produces:
  - `@dataclass ResultadoIngesta(ingesta_id: int, fecha_corte: date, ya_ingestado: bool, reclamos_insertados: int, reclamos_actualizados: int, servicios_snapshot: int)`
  - `ingerir(servicios: pd.DataFrame, reclamos: pd.DataFrame, *, hash_servicios: str, hash_reclamos: str, usuario: str | None, engine: Engine | None = None) -> ResultadoIngesta`
  - `upsert_reclamos_df(conn: Connection, reclamos: pd.DataFrame, ingesta_id: int | None) -> tuple[int, int]`
  - `cargar_ventana(fecha_corte: date, engine: Engine | None = None) -> tuple[pd.DataFrame, pd.DataFrame]` → (reclamos en `RECLAMOS_COLS` de la ventana de 365 días, foto de servicios de esa `fecha_corte` en `SERVICIOS_COLS`).
  - `sha256(content: bytes) -> str`

- [ ] **Step 1: Write the failing test**

```python
# Nombre de archivo: test_sla_consumo_persistencia_real_db.py
# Ubicación de archivo: tests/test_sla_consumo_persistencia_real_db.py
# Descripción: Ingesta idempotente del histórico SLA consumido contra Postgres real

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from sqlalchemy import text

from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS
from core.sla_consumo.persistencia import cargar_ventana, ingerir
from core.utils.excel_duraciones import TZ_AR
from db.session import SessionLocal
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real
_PREFIJO = "TSTSLA"  # nunca colisiona con números reales (son enteros)


def _reclamos(netas: float, extra: bool = False) -> pd.DataFrame:
    base = {c: None for c in RECLAMOS_COLS}
    filas = [
        {**base, "numero_reclamo": f"{_PREFIJO}1", "numero_linea": f"{_PREFIJO}L1", "nombre_cliente": "X",
         "fecha_inicio": pd.Timestamp("2026-09-01 10:00", tz=TZ_AR),
         "fecha_cierre": pd.Timestamp("2026-09-01 20:00", tz=TZ_AR), "horas_netas": netas,
         "tipo_solucion": "Carrier", "grupo_cierre": "Carrier"},
    ]
    if extra:
        filas.append({**filas[0], "numero_reclamo": f"{_PREFIJO}2",
                      "fecha_inicio": pd.Timestamp("2026-09-20 10:00", tz=TZ_AR),
                      "fecha_cierre": pd.Timestamp("2026-09-21 10:00", tz=TZ_AR)})
    return pd.DataFrame(filas, columns=RECLAMOS_COLS)


def _servicios() -> pd.DataFrame:
    base = {c: None for c in SERVICIOS_COLS}
    return pd.DataFrame([{**base, "numero_linea": f"{_PREFIJO}L1", "nombre_cliente": "X",
                          "sla_prometido": 99.7, "sla_entregado": 0.999, "horas_reclamos_todos": 10.0}],
                        columns=SERVICIOS_COLS)


@pytest.fixture
def limpiar():
    yield
    with SessionLocal() as s:
        s.execute(text("DELETE FROM app.reclamos WHERE numero_reclamo LIKE :p"), {"p": f"{_PREFIJO}%"})
        s.execute(text("DELETE FROM app.servicio_sla_snapshot WHERE numero_linea LIKE :p"), {"p": f"{_PREFIJO}%"})
        s.execute(text("DELETE FROM app.sla_ingestas WHERE hash_servicios LIKE :p"), {"p": f"{_PREFIJO}%"})
        s.commit()


def test_resubir_mismo_par_no_duplica(limpiar):
    r1 = ingerir(_servicios(), _reclamos(10.0), hash_servicios=f"{_PREFIJO}s1", hash_reclamos="r1", usuario="t")
    r2 = ingerir(_servicios(), _reclamos(10.0), hash_servicios=f"{_PREFIJO}s1", hash_reclamos="r1", usuario="t")
    assert (r1.reclamos_insertados, r1.ya_ingestado) == (1, False)
    assert r2.ya_ingestado is True and r2.ingesta_id == r1.ingesta_id
    assert r1.fecha_corte == dt.date(2026, 9, 1)


def test_par_solapado_actualiza_y_agrega(limpiar):
    ingerir(_servicios(), _reclamos(10.0), hash_servicios=f"{_PREFIJO}s1", hash_reclamos="r1", usuario="t")
    r = ingerir(_servicios(), _reclamos(12.5, extra=True), hash_servicios=f"{_PREFIJO}s2", hash_reclamos="r2", usuario="t")
    assert (r.reclamos_insertados, r.reclamos_actualizados) == (1, 1)
    reclamos, servicios = cargar_ventana(r.fecha_corte)
    mios = reclamos[reclamos["numero_reclamo"].str.startswith(_PREFIJO)]
    assert len(mios) == 2
    assert mios.set_index("numero_reclamo").loc[f"{_PREFIJO}1", "horas_netas"] == pytest.approx(12.5)
    assert f"{_PREFIJO}L1" in set(servicios["numero_linea"])
    with SessionLocal() as s:
        fotos = s.execute(text("SELECT COUNT(*) FROM app.servicio_sla_snapshot WHERE numero_linea = :l"),
                          {"l": f"{_PREFIJO}L1"}).scalar_one()
    assert fotos == 2  # una por fecha de corte (2026-09-01 y 2026-09-21)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sla_consumo_persistencia_real_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.sla_consumo.persistencia'`

- [ ] **Step 3: Write minimal implementation**

```python
# Nombre de archivo: persistencia.py
# Ubicación de archivo: core/sla_consumo/persistencia.py
# Descripción: Ingesta idempotente de reclamos y fotos de SLA, y lectura de la ventana de 12 meses

from __future__ import annotations

import datetime as dt
import hashlib
import math
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS, fecha_corte as calcular_fecha_corte
from db.models.reclamo import Reclamo
from db.models.sla_consumo import ServicioSlaSnapshot, SlaIngesta
from db.session import engine as engine_default  # verificar nombre real con: grep -n "^engine\|create_engine" db/session.py

VENTANA_DIAS = 365


@dataclass
class ResultadoIngesta:
    ingesta_id: int
    fecha_corte: dt.date
    ya_ingestado: bool
    reclamos_insertados: int
    reclamos_actualizados: int
    servicios_snapshot: int


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _limpio(valor: object) -> object:
    """NaN/NaT/pd.NA → None; Timestamp → datetime; numpy → Python (psycopg no adapta pd.NA)."""
    if valor is None or valor is pd.NA or valor is pd.NaT:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.to_pydatetime()
    if hasattr(valor, "item"):
        return valor.item()
    return valor


def _registros(df: pd.DataFrame, columnas: list[str]) -> list[dict]:
    return [{c: _limpio(v) for c, v in fila.items()} for fila in df[columnas].to_dict(orient="records")]


def upsert_reclamos_df(conn: Connection, reclamos: pd.DataFrame, ingesta_id: int | None) -> tuple[int, int]:
    if reclamos.empty:
        return 0, 0
    reclamos = reclamos.drop_duplicates(subset="numero_reclamo", keep="last")
    columnas = [c for c in RECLAMOS_COLS if c in Reclamo.__table__.c]
    filas = _registros(reclamos, columnas)
    for fila in filas:
        fila["ingesta_id"] = ingesta_id
    insertados = actualizados = 0
    tabla = Reclamo.__table__
    for inicio in range(0, len(filas), 1000):
        stmt = pg_insert(tabla).values(filas[inicio:inicio + 1000])
        # Un reclamo re-exportado trae su estado vigente: se pisa todo menos first_seen_at.
        cambios = {c: stmt.excluded[c] for c in columnas + ["ingesta_id"] if c != "numero_reclamo"}
        cambios["last_seen_at"] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=[tabla.c.numero_reclamo], set_=cambios)
        for fila in conn.execute(stmt.returning(text("(xmax = 0) AS inserted"))):
            if fila.inserted:
                insertados += 1
            else:
                actualizados += 1
    return insertados, actualizados


def _upsert_snapshot(conn: Connection, servicios: pd.DataFrame, corte: dt.date, ingesta_id: int) -> int:
    if servicios.empty:
        return 0
    filas = _registros(servicios, SERVICIOS_COLS)
    for fila in filas:
        fila.update(fecha_corte=corte, ingesta_id=ingesta_id)
    tabla = ServicioSlaSnapshot.__table__
    total = 0
    for inicio in range(0, len(filas), 1000):
        stmt = pg_insert(tabla).values(filas[inicio:inicio + 1000])
        cambios = {c: stmt.excluded[c] for c in SERVICIOS_COLS + ["ingesta_id"] if c != "numero_linea"}
        cambios["updated_at"] = func.now()
        conn.execute(stmt.on_conflict_do_update(constraint="uq_sla_snapshot_linea_corte", set_=cambios))
        total += len(filas[inicio:inicio + 1000])
    return total


def ingerir(servicios: pd.DataFrame, reclamos: pd.DataFrame, *, hash_servicios: str, hash_reclamos: str,
            usuario: str | None, engine: Engine | None = None) -> ResultadoIngesta:
    engine = engine or engine_default
    corte = calcular_fecha_corte(reclamos)
    with engine.begin() as conn:
        previa = conn.execute(
            select(SlaIngesta).where(SlaIngesta.hash_servicios == hash_servicios,
                                     SlaIngesta.hash_reclamos == hash_reclamos)).first()
        if previa is not None:
            return ResultadoIngesta(previa.id, previa.fecha_corte, True, 0, 0, 0)
        ingesta_id = conn.execute(
            pg_insert(SlaIngesta.__table__).values(
                fecha_corte=corte, hash_servicios=hash_servicios, hash_reclamos=hash_reclamos, usuario=usuario,
            ).returning(SlaIngesta.__table__.c.id)).scalar_one()
        insertados, actualizados = upsert_reclamos_df(conn, reclamos, ingesta_id)
        fotos = _upsert_snapshot(conn, servicios, corte, ingesta_id)
        conn.execute(SlaIngesta.__table__.update().where(SlaIngesta.__table__.c.id == ingesta_id).values(
            reclamos_insertados=insertados, reclamos_actualizados=actualizados, servicios_snapshot=fotos))
    return ResultadoIngesta(ingesta_id, corte, False, insertados, actualizados, fotos)


def cargar_ventana(fecha_corte: dt.date, engine: Engine | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    engine = engine or engine_default
    hasta = pd.Timestamp(fecha_corte + dt.timedelta(days=1), tz="America/Argentina/Buenos_Aires")
    desde = hasta - pd.Timedelta(days=VENTANA_DIAS)
    columnas_r = ", ".join(c for c in RECLAMOS_COLS)
    with engine.connect() as conn:
        reclamos = pd.read_sql(
            text(f"SELECT {columnas_r} FROM app.reclamos WHERE fecha_inicio >= :desde AND fecha_inicio < :hasta"),
            conn, params={"desde": desde.to_pydatetime(), "hasta": hasta.to_pydatetime()})
        servicios = pd.read_sql(
            text(f"SELECT {', '.join(SERVICIOS_COLS)} FROM app.servicio_sla_snapshot WHERE fecha_corte = :c"),
            conn, params={"c": fecha_corte})
    for col in ("horas_netas", "horas_totales_problema", "horas_indisponibilidad_problema",
                "horas_netas_escalamiento_carrier"):
        reclamos[col] = pd.to_numeric(reclamos[col], errors="coerce")
    for col in SERVICIOS_COLS[4:]:
        servicios[col] = pd.to_numeric(servicios[col], errors="coerce")
    reclamos["fecha_inicio"] = pd.to_datetime(reclamos["fecha_inicio"], utc=True).dt.tz_convert("America/Argentina/Buenos_Aires")
    reclamos["fecha_cierre"] = pd.to_datetime(reclamos["fecha_cierre"], utc=True).dt.tz_convert("America/Argentina/Buenos_Aires")
    return reclamos, servicios
```

`cargar_ventana` lee el snapshot de esa fecha de corte exacta; si no existe (p. ej. solo se ingestó por `/ingest/reclamos`), devuelve un DataFrame vacío y el engine marca `sin_sla_prometido`.

- [ ] **Step 4: Arreglar el escritor legacy**

En `core/parsers/reclamos_excel.py`, dentro de `parse_reclamos_df`, reemplazar la conversión de horas (línea ~115, `value_to_minutes` + `Int64`) por `df["horas_netas"] = df["horas_netas"].map(duracion_a_horas)` y la de fechas (línea ~111, `pd.to_datetime(..., dayfirst=True)`) por `df[col] = df[col].map(fecha_excel)`. Mapear `numero_evento` con `lambda v: None if str(v).strip() in ("", "-") else str(v).strip()`, y antes de devolver `df_ok = df_ok.drop_duplicates(subset="numero_reclamo", keep="last")`. Importar `from core.utils.excel_duraciones import duracion_a_horas, fecha_excel`.
En `api/app/routes/ingest.py:41`: `pd.read_excel(io.BytesIO(content), engine="openpyxl")` (sin `dtype=str, keep_default_na=False`). El CSV sigue con `dtype=str`.
En `core/services/repetitividad.py`, `upsert_reclamos(df)`: reemplazar el cuerpo por

```python
    if df is None or df.empty:
        return 0, 0
    from core.sla_consumo.persistencia import upsert_reclamos_df

    engine = create_engine(_engine_url())
    with engine.begin() as conn:
        return upsert_reclamos_df(conn, df, ingesta_id=None)
```

y en `upsert_reclamos_df` tolerar columnas faltantes: `columnas = [c for c in RECLAMOS_COLS + ["latitud", "longitud"] if c in reclamos.columns and c in Reclamo.__table__.c]`.
Actualizar `tests/test_ingest_parser.py`: la aserción de horas pasa a `1.5` y `0.75` horas. Borrar `core/parsers/reclamos_xlsx.py`.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_sla_consumo_persistencia_real_db.py tests/test_ingest_parser.py tests/test_sla_module.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/sla_consumo/persistencia.py core/parsers/reclamos_excel.py api/app/routes/ingest.py core/services/repetitividad.py tests/test_sla_consumo_persistencia_real_db.py tests/test_ingest_parser.py
git rm core/parsers/reclamos_xlsx.py
git commit -m "feat(sla): ingesta idempotente de reclamos y fotos de SLA; corrige horas/fechas de /ingest/reclamos"
```

---

### Task 6: Engine de SLA consumido

**Files:**
- Create: `core/sla_consumo/engine.py`
- Test: `tests/test_sla_consumo_engine.py`

**Interfaces:**
- Consumes: DataFrames de `cargar_ventana` (columnas `RECLAMOS_COLS`, `SERVICIOS_COLS`); constantes de grupos (Task 2).
- Produces:
  - `HORAS_ANIO = 8760.0`; `presupuesto_horas(sla_prometido: float | None) -> float | None`
  - `@dataclass ResultadoSlaConsumo(fecha_corte: date, hechos: DataFrame, eventos: DataFrame, servicios: DataFrame, servicio_reclamo: DataFrame, codigo_cierre: DataFrame, codigo_cierre_detalle: DataFrame, carrier_cliente: DataFrame, totales: dict[str, float | int])`
  - `calcular(reclamos: DataFrame, servicios: DataFrame, fecha_corte: date) -> ResultadoSlaConsumo`
  - Columnas clave: `hechos` → `+ presupuesto_h, cuenta_sla, horas_sla, pct_presupuesto, pp_disponibilidad, sin_sla_prometido, evento_clave`; `eventos` → `evento_clave, numero_evento, es_aislado, inicio, cierre, reclamos, servicios_afectados, servicios_excedidos, horas_sla, pct_presupuesto_medio, pct_presupuesto_max, grupo_predominante, mixto`; `servicios` → `numero_linea, nombre_cliente, tipo_servicio, sla_prometido, presupuesto_h, reclamos, horas_<grupo> por grupo, horas_sla, pct_presupuesto, pp_disponibilidad, sla_calculado, sla_oficial, diferencia_horas_oficial, horas_restantes_calc, excedido`; `codigo_cierre` → `grupo, eventos, reclamos, horas, horas_sla, pct_horas`.

- [ ] **Step 1: Write the failing test**

```python
# Nombre de archivo: test_sla_consumo_engine.py
# Ubicación de archivo: tests/test_sla_consumo_engine.py
# Descripción: Cálculo de SLA consumido por evento, servicio, reclamo y código de cierre

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core.sla_consumo.clasificador import GRUPO_CARRIER, GRUPO_CLIENTE, GRUPO_FO, GRUPO_FO_COD3
from core.sla_consumo.engine import calcular, presupuesto_horas
from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS
from core.utils.excel_duraciones import TZ_AR


def _r(numero, linea, horas, grupo, evento=None, cliente="C1"):
    fila = {c: None for c in RECLAMOS_COLS}
    fila.update(numero_reclamo=numero, numero_linea=linea, horas_netas=horas, grupo_cierre=grupo,
                numero_evento=evento, nombre_cliente=cliente, tipo_solucion=grupo,
                fecha_inicio=pd.Timestamp("2026-09-01", tz=TZ_AR), fecha_cierre=pd.Timestamp("2026-09-02", tz=TZ_AR))
    return fila


def _s(linea, prometido, oficial_h):
    fila = {c: None for c in SERVICIOS_COLS}
    fila.update(numero_linea=linea, nombre_cliente="C1", sla_prometido=prometido,
                sla_entregado=1 - oficial_h / 8760, horas_reclamos_todos=oficial_h)
    return fila


@pytest.fixture
def resultado():
    reclamos = pd.DataFrame([
        _r("1", "L1", 13.14, GRUPO_FO, evento="E1"),
        _r("2", "L2", 20.0, GRUPO_FO, evento="E1"),
        _r("3", "L1", 5.0, GRUPO_CARRIER, cliente="BANCO"),
        _r("4", "L1", 4.0, GRUPO_FO_COD3),
        _r("5", "L1", 100.0, GRUPO_CLIENTE),
        _r("6", "L9", 2.0, GRUPO_FO),  # línea sin foto de servicios
    ], columns=RECLAMOS_COLS)
    servicios = pd.DataFrame([_s("L1", 99.7, 22.0), _s("L2", 99.9, 20.0)], columns=SERVICIOS_COLS)
    return calcular(reclamos, servicios, dt.date(2026, 10, 1))


def test_presupuesto():
    assert presupuesto_horas(99.7) == pytest.approx(26.28)
    assert presupuesto_horas(None) is None


def test_hechos_metricas(resultado):
    h = resultado.hechos.set_index("numero_reclamo")
    assert h.loc["1", "pct_presupuesto"] == pytest.approx(50.0)
    assert h.loc["1", "pp_disponibilidad"] == pytest.approx(13.14 / 8760 * 100)
    assert h.loc["5", "horas_sla"] == 0.0 and bool(h.loc["5", "cuenta_sla"]) is False
    assert bool(h.loc["6", "sin_sla_prometido"]) is True and pd.isna(h.loc["6", "pct_presupuesto"])


def test_por_servicio(resultado):
    s = resultado.servicios.set_index("numero_linea")
    assert s.loc["L1", "horas_sla"] == pytest.approx(22.14)
    assert s.loc["L1", "pct_presupuesto"] == pytest.approx(22.14 / 26.28 * 100)
    assert s.loc["L1", "sla_calculado"] == pytest.approx(1 - 22.14 / 8760)
    assert s.loc["L1", "diferencia_horas_oficial"] == pytest.approx(22.14 - 22.0)
    assert bool(s.loc["L2", "excedido"]) is True   # 20 h > 8.76 h de presupuesto
    assert "L9" in s.index


def test_por_evento(resultado):
    e = resultado.eventos.set_index("evento_clave")
    assert e.loc["E1", "servicios_afectados"] == 2
    assert e.loc["E1", "servicios_excedidos"] == 1
    assert e.loc["E1", "horas_sla"] == pytest.approx(33.14)
    assert e.loc["E1", "grupo_predominante"] == GRUPO_FO
    assert bool(e.loc["R-3", "es_aislado"]) is True   # reclamo sin evento = evento propio


def test_codigo_cierre_y_carrier(resultado):
    c = resultado.codigo_cierre.set_index("grupo")
    assert c.loc[GRUPO_FO, "reclamos"] == 3 and c.loc[GRUPO_FO, "eventos"] == 2
    assert c.loc[GRUPO_CLIENTE, "horas_sla"] == 0.0
    assert c["horas"].sum() == pytest.approx(resultado.hechos["horas_netas"].sum())
    assert resultado.carrier_cliente.iloc[0]["nombre_cliente"] == "BANCO"
    assert resultado.totales["reclamos"] == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sla_consumo_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.sla_consumo.engine'`

- [ ] **Step 3: Write minimal implementation**

```python
# Nombre de archivo: engine.py
# Ubicación de archivo: core/sla_consumo/engine.py
# Descripción: Calcula el SLA consumido por evento, servicio, reclamo y código de cierre (pandas puro)

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.sla_consumo.clasificador import GRUPO_CARRIER, GRUPO_CLIENTE, GRUPOS_ORDEN

HORAS_ANIO = 8760.0


def presupuesto_horas(sla_prometido: float | None) -> float | None:
    if sla_prometido is None or pd.isna(sla_prometido):
        return None
    return (1 - float(sla_prometido) / 100) * HORAS_ANIO


def _col_grupo(grupo: str) -> str:
    return "horas_" + {
        "FO (excepto Cod 3)": "fo", "FO Cod 3 (Corte en Bandeja)": "fo_cod3", "Carrier": "carrier",
        "Otros": "otros", "Cierre Cliente": "cliente"}[grupo]


@dataclass
class ResultadoSlaConsumo:
    fecha_corte: dt.date
    hechos: pd.DataFrame
    eventos: pd.DataFrame
    servicios: pd.DataFrame
    servicio_reclamo: pd.DataFrame
    codigo_cierre: pd.DataFrame
    codigo_cierre_detalle: pd.DataFrame
    carrier_cliente: pd.DataFrame
    totales: dict = field(default_factory=dict)


def _hechos(reclamos: pd.DataFrame, servicios: pd.DataFrame) -> pd.DataFrame:
    sla = servicios[["numero_linea", "sla_prometido"]].drop_duplicates("numero_linea")
    h = reclamos.merge(sla, on="numero_linea", how="left")
    h["horas_netas"] = pd.to_numeric(h["horas_netas"], errors="coerce").fillna(0.0)
    h["presupuesto_h"] = h["sla_prometido"].map(presupuesto_horas).astype(float)
    h["sin_sla_prometido"] = h["presupuesto_h"].isna()
    h["cuenta_sla"] = h["grupo_cierre"] != GRUPO_CLIENTE
    h["horas_sla"] = np.where(h["cuenta_sla"], h["horas_netas"], 0.0)
    h["pct_presupuesto"] = h["horas_sla"] / h["presupuesto_h"] * 100
    h["pp_disponibilidad"] = h["horas_sla"] / HORAS_ANIO * 100
    h["evento_clave"] = h["numero_evento"].where(h["numero_evento"].notna(), "R-" + h["numero_reclamo"].astype(str))
    return h


def _servicios(h: pd.DataFrame, servicios: pd.DataFrame) -> pd.DataFrame:
    pivote = h.pivot_table(index="numero_linea", columns="grupo_cierre", values="horas_netas",
                           aggfunc="sum", fill_value=0.0)
    pivote = pivote.reindex(columns=list(GRUPOS_ORDEN), fill_value=0.0)
    pivote.columns = [_col_grupo(g) for g in pivote.columns]
    base = h.groupby("numero_linea").agg(
        nombre_cliente=("nombre_cliente", "first"), tipo_servicio=("tipo_servicio", "first"),
        reclamos=("numero_reclamo", "count"), horas_sla=("horas_sla", "sum"))
    df = base.join(pivote).reset_index()
    oficial = servicios[["numero_linea", "sla_prometido", "sla_entregado", "horas_reclamos_todos"]]
    df = df.merge(oficial, on="numero_linea", how="left")
    df["presupuesto_h"] = df["sla_prometido"].map(presupuesto_horas).astype(float)
    df["pct_presupuesto"] = df["horas_sla"] / df["presupuesto_h"] * 100
    df["pp_disponibilidad"] = df["horas_sla"] / HORAS_ANIO * 100
    df["sla_calculado"] = 1 - df["horas_sla"] / HORAS_ANIO
    df["sla_oficial"] = df["sla_entregado"]
    df["diferencia_horas_oficial"] = df["horas_sla"] - df["horas_reclamos_todos"]
    df["horas_restantes_calc"] = (df["presupuesto_h"] - df["horas_sla"]).clip(lower=0)
    df["excedido"] = df["horas_sla"] > df["presupuesto_h"]
    return df.drop(columns=["sla_entregado"]).sort_values("pct_presupuesto", ascending=False, na_position="last")


def _eventos(h: pd.DataFrame, por_servicio_evento_excedido: pd.DataFrame) -> pd.DataFrame:
    def _predominante(g: pd.DataFrame) -> pd.Series:
        horas = g.groupby("grupo_cierre")["horas_netas"].sum()
        return pd.Series({"grupo_predominante": horas.idxmax() if len(horas) else None,
                          "mixto": g["grupo_cierre"].nunique() > 1})

    agg = h.groupby("evento_clave").agg(
        numero_evento=("numero_evento", "first"), inicio=("fecha_inicio", "min"), cierre=("fecha_cierre", "max"),
        reclamos=("numero_reclamo", "count"), servicios_afectados=("numero_linea", "nunique"),
        horas_sla=("horas_sla", "sum"), pct_presupuesto_medio=("pct_presupuesto", "mean"),
        pct_presupuesto_max=("pct_presupuesto", "max"))
    agg = agg.join(h.groupby("evento_clave")[["grupo_cierre", "horas_netas"]].apply(_predominante))
    agg = agg.join(por_servicio_evento_excedido)
    agg["servicios_excedidos"] = agg["servicios_excedidos"].fillna(0).astype(int)
    agg["es_aislado"] = agg["numero_evento"].isna()
    return agg.reset_index().sort_values("horas_sla", ascending=False)


def calcular(reclamos: pd.DataFrame, servicios: pd.DataFrame, fecha_corte: dt.date) -> ResultadoSlaConsumo:
    h = _hechos(reclamos, servicios)
    svc = _servicios(h, servicios)
    excedidos = set(svc.loc[svc["excedido"], "numero_linea"])
    exc_evento = (h[h["numero_linea"].isin(excedidos)].groupby("evento_clave")["numero_linea"]
                  .nunique().rename("servicios_excedidos").to_frame())
    eventos = _eventos(h, exc_evento)

    servicio_reclamo = h[["numero_linea", "nombre_cliente", "numero_reclamo", "numero_evento", "fecha_inicio",
                          "fecha_cierre", "tipo_solucion", "grupo_cierre", "codigo_cierre", "horas_netas",
                          "horas_sla", "presupuesto_h", "pct_presupuesto", "pp_disponibilidad"]
                         ].sort_values(["numero_linea", "fecha_inicio"])

    total_horas = h["horas_netas"].sum()
    codigo = h.groupby("grupo_cierre").agg(eventos=("evento_clave", "nunique"), reclamos=("numero_reclamo", "count"),
                                            horas=("horas_netas", "sum"), horas_sla=("horas_sla", "sum"))
    codigo = codigo.reindex(list(GRUPOS_ORDEN), fill_value=0).reset_index().rename(columns={"index": "grupo"})
    codigo = codigo.rename(columns={"grupo_cierre": "grupo"})
    codigo["pct_horas"] = codigo["horas"] / total_horas * 100 if total_horas else 0.0
    detalle = (h.groupby(["grupo_cierre", "tipo_solucion"], dropna=False)
               .agg(eventos=("evento_clave", "nunique"), reclamos=("numero_reclamo", "count"), horas=("horas_netas", "sum"))
               .reset_index().rename(columns={"grupo_cierre": "grupo"}).sort_values(["grupo", "horas"], ascending=[True, False]))
    carrier = (h[h["grupo_cierre"] == GRUPO_CARRIER]
               .groupby(["nombre_cliente", "carrier"], dropna=False)
               .agg(reclamos=("numero_reclamo", "count"), servicios=("numero_linea", "nunique"), horas=("horas_netas", "sum"))
               .reset_index().sort_values("horas", ascending=False))

    totales = {"reclamos": int(len(h)), "eventos": int(h["numero_evento"].nunique()),
               "reclamos_aislados": int(h["numero_evento"].isna().sum()),
               "servicios": int(svc["numero_linea"].nunique()), "servicios_excedidos": int(svc["excedido"].sum()),
               "horas": float(total_horas), "horas_sla": float(h["horas_sla"].sum())}
    return ResultadoSlaConsumo(fecha_corte, h, eventos, svc, servicio_reclamo, codigo, detalle, carrier, totales)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sla_consumo_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/sla_consumo/engine.py tests/test_sla_consumo_engine.py
git commit -m "feat(sla): engine de SLA consumido por evento, servicio, reclamo y código de cierre"
```

---

### Task 7: Gráficos y builders XLSX/DOCX

**Files:**
- Create: `core/sla_consumo/charts.py`, `core/sla_consumo/xlsx_builder.py`, `core/sla_consumo/docx_builder.py`
- Test: `tests/test_sla_consumo_builders.py`

**Interfaces:**
- Consumes: `ResultadoSlaConsumo` (Task 6).
- Produces:
  - `charts.pareto_eventos(res, destino: Path, top: int = 15) -> Path`; `charts.top_servicios(res, destino: Path, top: int = 20) -> Path`; `charts.horas_por_grupo(res, destino: Path) -> Path`; `charts.servicio(res, numero_linea: str, destino: Path) -> Path`
  - `xlsx_builder.construir_xlsx(res, destino: Path) -> Path` — hojas `Resumen`, `Eventos`, `Servicios`, `Servicio x Reclamo`, `Código de cierre`, `Detalle tipo solución`, `Carrier x Cliente`.
  - `docx_builder.construir_docx(res, destino: Path, top_servicios: int = 20) -> Path`

- [ ] **Step 1: Write the failing test**

```python
# Nombre de archivo: test_sla_consumo_builders.py
# Ubicación de archivo: tests/test_sla_consumo_builders.py
# Descripción: Gráficos, XLSX y DOCX del informe SLA consumido

from __future__ import annotations

import openpyxl
from docx import Document

from core.sla_consumo import charts
from core.sla_consumo.docx_builder import construir_docx
from core.sla_consumo.xlsx_builder import HOJAS, construir_xlsx
from tests.test_sla_consumo_engine import resultado  # noqa: F401  (fixture reutilizada)


def test_charts_generan_png(resultado, tmp_path):
    for archivo in (charts.pareto_eventos(resultado, tmp_path / "a.png"),
                    charts.top_servicios(resultado, tmp_path / "b.png"),
                    charts.horas_por_grupo(resultado, tmp_path / "c.png"),
                    charts.servicio(resultado, "L1", tmp_path / "d.png")):
        assert archivo.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_xlsx_tiene_todas_las_hojas(resultado, tmp_path):
    wb = openpyxl.load_workbook(construir_xlsx(resultado, tmp_path / "x.xlsx"))
    assert wb.sheetnames == list(HOJAS)
    assert wb["Servicios"].max_row == len(resultado.servicios) + 1


def test_docx_con_graficos(resultado, tmp_path):
    doc = Document(construir_docx(resultado, tmp_path / "x.docx", top_servicios=2))
    texto = "\n".join(p.text for p in doc.paragraphs)
    assert "SLA consumido" in texto and "2026-10-01" in texto
    assert len(doc.inline_shapes) >= 3 + 2   # 3 generales + 1 por servicio del top
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sla_consumo_builders.py -v`
Expected: FAIL with `ImportError: cannot import name 'charts'`

- [ ] **Step 3: Implement `charts.py`**

```python
# Nombre de archivo: charts.py
# Ubicación de archivo: core/sla_consumo/charts.py
# Descripción: Gráficos PNG de mayores repercutores de SLA (matplotlib Agg)

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from core.sla_consumo.clasificador import GRUPOS_ORDEN  # noqa: E402

# Paleta fija por grupo: el mismo grupo tiene el mismo color en todos los gráficos.
COLORES = dict(zip(GRUPOS_ORDEN, ("#2a6fdb", "#e0892b", "#7a5bd6", "#8a8f98", "#3aa57a")))


def _guardar(fig, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(destino, dpi=150)
    plt.close(fig)
    return destino


def pareto_eventos(res, destino: Path, top: int = 15) -> Path:
    datos = res.eventos.head(top)
    total = res.eventos["horas_sla"].sum() or 1.0
    fig, ax = plt.subplots(figsize=(10, 5))
    etiquetas = [str(e) for e in datos["evento_clave"]]
    ax.bar(etiquetas, datos["horas_sla"], color=[COLORES.get(g, "#8a8f98") for g in datos["grupo_predominante"]])
    ax.set_ylabel("Horas que consumen SLA")
    ax.set_title(f"Top {len(datos)} eventos por horas de SLA consumidas")
    ax.tick_params(axis="x", rotation=60, labelsize=8)
    ax2 = ax.twinx()
    ax2.plot(etiquetas, datos["horas_sla"].cumsum() / total * 100, color="#222", marker="o", linewidth=1)
    ax2.set_ylabel("% acumulado del total")
    ax2.set_ylim(0, 100)
    return _guardar(fig, destino)


def top_servicios(res, destino: Path, top: int = 20) -> Path:
    datos = res.servicios.dropna(subset=["pct_presupuesto"]).head(top)[::-1]
    fig, ax = plt.subplots(figsize=(10, max(4, len(datos) * 0.35)))
    ax.barh([f"{l} · {str(c)[:28]}" for l, c in zip(datos["numero_linea"], datos["nombre_cliente"])],
            datos["pct_presupuesto"], color="#2a6fdb")
    ax.axvline(100, color="#c0392b", linestyle="--", linewidth=1)
    ax.set_xlabel("% del presupuesto anual de SLA consumido")
    ax.set_title(f"Top {len(datos)} servicios por SLA consumido")
    return _guardar(fig, destino)


def horas_por_grupo(res, destino: Path) -> Path:
    datos = res.codigo_cierre
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(datos["grupo"], datos["horas"], color=[COLORES[g] for g in datos["grupo"]])
    ax.set_ylabel("Horas netas")
    ax.set_title("Horas por código de cierre")
    ax.tick_params(axis="x", rotation=20, labelsize=8)
    return _guardar(fig, destino)


def servicio(res, numero_linea: str, destino: Path) -> Path:
    datos = res.servicio_reclamo[res.servicio_reclamo["numero_linea"] == numero_linea]
    presupuesto = datos["presupuesto_h"].iloc[0] if len(datos) else None
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.bar(datos["numero_reclamo"].astype(str), datos["horas_sla"],
           color=[COLORES.get(g, "#8a8f98") for g in datos["grupo_cierre"]])
    ax.plot(datos["numero_reclamo"].astype(str), datos["horas_sla"].cumsum(), color="#222", marker="o", linewidth=1,
            label="Acumulado")
    if presupuesto:
        ax.axhline(presupuesto, color="#c0392b", linestyle="--", linewidth=1, label="Presupuesto anual")
    ax.set_ylabel("Horas")
    ax.set_title(f"Servicio {numero_linea}: reclamos y SLA acumulado")
    ax.tick_params(axis="x", rotation=60, labelsize=8)
    ax.legend(fontsize=8)
    return _guardar(fig, destino)
```

- [ ] **Step 4: Implement `xlsx_builder.py`**

```python
# Nombre de archivo: xlsx_builder.py
# Ubicación de archivo: core/sla_consumo/xlsx_builder.py
# Descripción: XLSX del informe SLA consumido, una hoja por vista

from __future__ import annotations

from pathlib import Path

import pandas as pd

HOJAS = ("Resumen", "Eventos", "Servicios", "Servicio x Reclamo", "Código de cierre",
         "Detalle tipo solución", "Carrier x Cliente")


def _sin_tz(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if isinstance(df[col].dtype, pd.DatetimeTZDtype):
            df[col] = df[col].dt.tz_localize(None)
    return df


def construir_xlsx(res, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    resumen = pd.DataFrame([{"fecha_corte": res.fecha_corte.isoformat(), **res.totales}]).T.reset_index()
    resumen.columns = ["indicador", "valor"]
    vistas = (resumen, res.eventos, res.servicios, res.servicio_reclamo, res.codigo_cierre,
              res.codigo_cierre_detalle, res.carrier_cliente)
    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        for nombre, df in zip(HOJAS, vistas):
            _sin_tz(df).to_excel(writer, sheet_name=nombre, index=False)
            hoja = writer.sheets[nombre]
            hoja.freeze_panes = "A2"
            for columna in hoja.columns:
                ancho = max(len(str(c.value or "")) for c in columna[:200])
                hoja.column_dimensions[columna[0].column_letter].width = min(max(10, ancho + 2), 50)
    return destino
```

- [ ] **Step 5: Implement `docx_builder.py`**

```python
# Nombre de archivo: docx_builder.py
# Ubicación de archivo: core/sla_consumo/docx_builder.py
# Descripción: DOCX ejecutivo del informe SLA consumido con gráficos de repercutores

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Cm

from core.sla_consumo import charts


def _tabla(doc, df, columnas: list[tuple[str, str]], formato=lambda v: v) -> None:
    tabla = doc.add_table(rows=1, cols=len(columnas))
    tabla.style = "Light Grid Accent 1"
    for celda, (_, titulo) in zip(tabla.rows[0].cells, columnas):
        celda.text = titulo
    for _, fila in df.iterrows():
        celdas = tabla.add_row().cells
        for celda, (col, _) in zip(celdas, columnas):
            valor = fila[col]
            celda.text = f"{valor:,.2f}" if isinstance(valor, float) else str(valor if valor is not None else "—")


def construir_docx(res, destino: Path, top_servicios: int = 20) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    graficos = destino.parent / f"{destino.stem}_graficos"
    doc = Document()
    doc.add_heading("Informe de SLA consumido", level=0)
    t = res.totales
    doc.add_paragraph(
        f"Fecha de corte: {res.fecha_corte.isoformat()} · ventana de 12 meses. "
        f"{t['reclamos']} reclamos en {t['eventos']} eventos (+{t['reclamos_aislados']} reclamos aislados), "
        f"{t['servicios']} servicios afectados, {t['servicios_excedidos']} superan su presupuesto anual de SLA. "
        f"Horas que consumen SLA: {t['horas_sla']:,.1f} de {t['horas']:,.1f} h netas.")

    doc.add_heading("SLA consumido por código de cierre", level=1)
    _tabla(doc, res.codigo_cierre, [("grupo", "Grupo"), ("eventos", "Eventos"), ("reclamos", "Reclamos"),
                                    ("horas", "Horas"), ("horas_sla", "Horas SLA"), ("pct_horas", "% horas")])
    doc.add_picture(str(charts.horas_por_grupo(res, graficos / "grupos.png")), width=Cm(15))

    doc.add_heading("Mayores repercutores — eventos", level=1)
    doc.add_picture(str(charts.pareto_eventos(res, graficos / "pareto_eventos.png")), width=Cm(16))
    _tabla(doc, res.eventos.head(15), [("evento_clave", "Evento"), ("reclamos", "Reclamos"),
                                       ("servicios_afectados", "Servicios"), ("servicios_excedidos", "Excedidos"),
                                       ("horas_sla", "Horas SLA"), ("grupo_predominante", "Grupo")])

    doc.add_heading("Mayores repercutores — servicios", level=1)
    doc.add_picture(str(charts.top_servicios(res, graficos / "top_servicios.png")), width=Cm(16))

    doc.add_heading("Fichas por servicio", level=1)
    for _, svc in res.servicios.dropna(subset=["pct_presupuesto"]).head(top_servicios).iterrows():
        doc.add_heading(f"{svc['numero_linea']} — {svc['nombre_cliente']}", level=2)
        doc.add_paragraph(
            f"SLA prometido {svc['sla_prometido']} % · presupuesto {svc['presupuesto_h']:.2f} h · "
            f"consumido {svc['horas_sla']:.2f} h ({svc['pct_presupuesto']:.1f} % del presupuesto, "
            f"{svc['pp_disponibilidad']:.3f} pp) · SLA calculado {svc['sla_calculado'] * 100:.3f} %.")
        doc.add_picture(str(charts.servicio(res, svc["numero_linea"], graficos / f"svc_{svc['numero_linea']}.png")),
                        width=Cm(15))
    doc.save(destino)
    return destino
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_sla_consumo_builders.py -v`
Expected: PASS (si el estilo `"Light Grid Accent 1"` no existe en el template por defecto de python-docx, usar `"Table Grid"`).

- [ ] **Step 7: Commit**

```bash
git add core/sla_consumo/charts.py core/sla_consumo/xlsx_builder.py core/sla_consumo/docx_builder.py tests/test_sla_consumo_builders.py
git commit -m "feat(sla): gráficos de repercutores y builders XLSX/DOCX del informe SLA consumido"
```

---

### Task 8: Orquestador + endpoint web

**Files:**
- Create: `core/services/sla_consumo.py`
- Modify: `web/app/main.py` (nuevo endpoint debajo de `generar_informe_sla_web`, ~l.720)
- Test: `tests/test_web_sla_consumo.py`

**Interfaces:**
- Consumes: Tasks 3, 5, 6, 7; `modules.common.libreoffice_export.convert_to_pdf(docx_path: str, soffice_bin: str) -> str`; `sla_service.identify_excel_kind(content) -> "servicios" | "reclamos"`; `REPORT_HISTORY.start/finish_success/finish_error`, `_report_href`, `_require_auth`.
- Produces:
  - `@dataclass InformeSlaConsumo(xlsx: Path, docx: Path, pdf: Path | None, ingesta: ResultadoIngesta, totales: dict)`
  - `generar_informe_sla_consumo(servicios_bytes: bytes, reclamos_bytes: bytes, *, usuario: str | None, incluir_pdf: bool, reports_dir: Path) -> InformeSlaConsumo`
  - `POST /api/reports/sla-consumo` (form: `files[]`×2, `pdf_enabled`, `csrf_token`) → `{"ok": true, "fecha_corte": "YYYY-MM-DD", "ya_ingestado": bool, "reclamos_insertados": int, "reclamos_actualizados": int, "totales": {...}, "report_paths": {"xlsx", "docx", "pdf"?}}`

- [ ] **Step 1: Write the failing test**

```python
# Nombre de archivo: test_web_sla_consumo.py
# Ubicación de archivo: tests/test_web_sla_consumo.py
# Descripción: Endpoint web /api/reports/sla-consumo (orquestador mockeado, sin DB)

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi.testclient import TestClient

from core.sla_consumo.persistencia import ResultadoIngesta
from core.services.sla_consumo import InformeSlaConsumo
from web.app import main as web_main  # type: ignore
from web.app.main import app  # type: ignore
from tests.test_web_admin import _connect_user_ok  # noqa: F401
from tests.test_web_sla_flow import _reclamos_excel_bytes, _servicios_excel_bytes


def _login(client: TestClient) -> None:
    # Reusar el helper de login que usa tests/test_web_sla_flow.py (mismo patrón de sesión + CSRF).
    from tests.test_web_sla_flow import _login as login_sla  # si el helper tiene otro nombre, usar ese
    login_sla(client)


def test_sla_consumo_ok(monkeypatch, tmp_path):
    llamado = {}

    def falso(servicios_bytes, reclamos_bytes, *, usuario, incluir_pdf, reports_dir):
        llamado.update(servicios=servicios_bytes, reclamos=reclamos_bytes)
        xlsx = Path(reports_dir) / "a.xlsx"; xlsx.parent.mkdir(parents=True, exist_ok=True); xlsx.write_bytes(b"x")
        docx = Path(reports_dir) / "a.docx"; docx.write_bytes(b"x")
        return InformeSlaConsumo(xlsx, docx, None,
                                 ResultadoIngesta(7, dt.date(2026, 10, 1), False, 10, 2, 5), {"reclamos": 12})

    monkeypatch.setattr(web_main.sla_consumo_service, "generar_informe_sla_consumo", falso)
    client = TestClient(app)
    _login(client)
    resp = client.post("/api/reports/sla-consumo", files=[
        ("files", ("servicios.xlsx", _servicios_excel_bytes())),
        ("files", ("reclamos.xlsx", _reclamos_excel_bytes())),
    ])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["fecha_corte"] == "2026-10-01"
    assert body["reclamos_insertados"] == 10 and "xlsx" in body["report_paths"]
    assert llamado["servicios"] == _servicios_excel_bytes()


def test_sla_consumo_un_solo_archivo_400():
    client = TestClient(app)
    _login(client)
    resp = client.post("/api/reports/sla-consumo", files=[("files", ("s.xlsx", _servicios_excel_bytes()))])
    assert resp.status_code == 400
```

Antes de escribirlo, abrir `tests/test_web_sla_flow.py` y copiar el helper real de login/sesión que usa (nombre exacto); reemplazar `_login` por ese helper.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_sla_consumo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.services.sla_consumo'`

- [ ] **Step 3: Orquestador**

```python
# Nombre de archivo: sla_consumo.py
# Ubicación de archivo: core/services/sla_consumo.py
# Descripción: Orquesta el informe SLA consumido — parsea, persiste el histórico y genera XLSX/DOCX/PDF

from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from core.sla_consumo.docx_builder import construir_docx
from core.sla_consumo.engine import calcular
from core.sla_consumo.parser import parse_reclamos, parse_servicios
from core.sla_consumo.persistencia import ResultadoIngesta, cargar_ventana, ingerir, sha256
from core.sla_consumo.xlsx_builder import construir_xlsx

logger = logging.getLogger(__name__)


@dataclass
class InformeSlaConsumo:
    xlsx: Path
    docx: Path
    pdf: Path | None
    ingesta: ResultadoIngesta
    totales: dict


def generar_informe_sla_consumo(servicios_bytes: bytes, reclamos_bytes: bytes, *, usuario: str | None,
                                incluir_pdf: bool, reports_dir: Path) -> InformeSlaConsumo:
    servicios = parse_servicios(servicios_bytes)
    reclamos = parse_reclamos(reclamos_bytes)
    if reclamos.empty:
        raise ValueError("El Excel de reclamos no tiene filas válidas")
    ingesta = ingerir(servicios, reclamos, hash_servicios=sha256(servicios_bytes),
                      hash_reclamos=sha256(reclamos_bytes), usuario=usuario)
    logger.info("action=sla_consumo stage=ingesta id=%s corte=%s ya=%s ins=%s upd=%s", ingesta.ingesta_id,
                ingesta.fecha_corte, ingesta.ya_ingestado, ingesta.reclamos_insertados, ingesta.reclamos_actualizados)
    reclamos_db, servicios_db = cargar_ventana(ingesta.fecha_corte)
    resultado = calcular(reclamos_db, servicios_db, ingesta.fecha_corte)

    sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta = Path(reports_dir) / "sla_consumo" / ingesta.fecha_corte.strftime("%Y%m")
    xlsx = construir_xlsx(resultado, carpeta / f"SLA_consumido_{ingesta.fecha_corte}_{sello}.xlsx")
    docx = construir_docx(resultado, carpeta / f"SLA_consumido_{ingesta.fecha_corte}_{sello}.docx")
    pdf = None
    soffice = os.getenv("SOFFICE_BIN")
    if incluir_pdf and soffice:
        from modules.common.libreoffice_export import convert_to_pdf

        pdf = Path(convert_to_pdf(str(docx), soffice))
    return InformeSlaConsumo(xlsx, docx, pdf, ingesta, resultado.totales)
```

- [ ] **Step 4: Endpoint en `web/app/main.py`**

Agregar `from core.services import sla_consumo as sla_consumo_service` junto a los imports de `sla_service`, y debajo de `generar_informe_sla_web`:

```python
@app.post("/api/reports/sla-consumo")
async def generar_informe_sla_consumo_web(
    request: Request,
    pdf_enabled: bool = Form(False),
    csrf_token: str | None = Form(None),
    files: List[UploadFile] = File(default=[]),
):
    username, _ = _require_auth(request)
    expected_csrf = request.session.get("csrf")
    if expected_csrf and os.getenv("TESTING", "false").lower() != "true" and csrf_token != expected_csrf:
        return JSONResponse({"ok": False, "error": "CSRF inválido"}, status_code=403)

    archivos = [a for a in files if a and a.filename]
    history_id = REPORT_HISTORY.start(
        report_type="sla_consumo", username=username, source="excel", period_month=None, period_year=None,
        input_metadata={"archivos": [Path(a.filename or "").name for a in archivos], "pdf_enabled": bool(pdf_enabled)},
    )

    def _error(status: int, mensaje: str) -> JSONResponse:
        REPORT_HISTORY.finish_error(history_id, error_code=f"HTTP_{status}", error_message=mensaje,
                                    output_metadata={"source": "excel"})
        return JSONResponse({"ok": False, "error": mensaje}, status_code=status)

    if len(archivos) != 2:
        for a in archivos:
            await a.close()
        return _error(400, "Debés adjuntar dos archivos: servicios y reclamos")

    contenidos: dict[str, bytes] = {}
    for archivo in archivos:
        nombre = Path(archivo.filename).name
        contenido = await archivo.read()
        await archivo.close()
        if not nombre.lower().endswith(".xlsx") or not contenido:
            return _error(415, f"{nombre} debe ser un .xlsx no vacío")
        try:
            tipo = sla_service.identify_excel_kind(contenido)
        except ValueError as exc:
            return _error(422, str(exc))
        if tipo in contenidos:
            return _error(422, f"Se recibió más de un Excel de {tipo}")
        contenidos[tipo] = contenido
    if set(contenidos) != {"servicios", "reclamos"}:
        return _error(400, "Adjuntá los archivos de servicios y reclamos")

    try:
        informe = await asyncio.to_thread(
            sla_consumo_service.generar_informe_sla_consumo, contenidos["servicios"], contenidos["reclamos"],
            usuario=username, incluir_pdf=pdf_enabled, reports_dir=REPORTS_DIR,
        )
    except ValueError as exc:
        return _error(422, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=sla_consumo_web stage=unexpected user=%s", username)
        return _error(500, f"No se pudo generar el informe de SLA consumido: {exc or exc.__class__.__name__}")

    report_paths = {"xlsx": _report_href(informe.xlsx), "docx": _report_href(informe.docx)}
    if informe.pdf:
        report_paths["pdf"] = _report_href(informe.pdf)
    ingesta = informe.ingesta
    salida = {
        "fecha_corte": ingesta.fecha_corte.isoformat(), "ya_ingestado": ingesta.ya_ingestado,
        "reclamos_insertados": ingesta.reclamos_insertados, "reclamos_actualizados": ingesta.reclamos_actualizados,
        "totales": informe.totales, "report_paths": report_paths,
    }
    REPORT_HISTORY.finish_success(history_id, output_metadata={"source": "excel", **salida})
    return JSONResponse({"ok": True, "message": "Informe de SLA consumido generado", **salida})
```

Verificar que `asyncio` ya esté importado en `web/app/main.py` (`grep -n "^import asyncio" web/app/main.py`), que `REPORT_HISTORY.start` acepte `period_month=None` (ver `core/services/report_history.py:24`), y que `_report_href` resuelva rutas bajo `REPORTS_DIR` (lo hace, l.~496). Si `identify_excel_kind` rechaza el Excel real de Servicios por exigir "SLA Entregado"/"Horas Reclamos Todos", no hace falta cambiarlo: ambos están.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_web_sla_consumo.py tests/test_web_sla_flow.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/services/sla_consumo.py web/app/main.py tests/test_web_sla_consumo.py
git commit -m "feat(sla): endpoint web del informe SLA consumido con persistencia del histórico"
```

---

### Task 9: Reclamos e histórico de SLA en el detalle de servicio (API)

**Files:**
- Modify: `api/app/routes/servicios.py` (`ServicioDetailResponse`, `detail_servicio` l.~655)
- Test: `tests/test_servicios_detalle_reclamos_real_db.py`

**Interfaces:**
- Consumes: `app.reclamos`, `app.servicio_sla_snapshot`; `presupuesto_horas` (Task 6).
- Produces: `ServicioDetailResponse` con `servicio.reclamos: list[ReclamoServicioResponse]` (antes `None`) y nuevo campo `sla_historico: list[SlaSnapshotResponse]`.
  - `ReclamoServicioResponse`: `numero_reclamo: str, numero_evento: str | None, numero_linea: str, fecha_inicio: datetime | None, fecha_cierre: datetime | None, tipo_solucion: str | None, grupo_cierre: str | None, codigo_cierre: int | None, horas_netas: float | None, cuenta_sla: bool, pct_presupuesto: float | None, carrier: str | None, descripcion_solucion: str | None`
  - `SlaSnapshotResponse`: `fecha_corte: date, sla_prometido: float | None, sla_entregado: float | None, horas_reclamos_todos: float | None, horas_restantes: float | None, cantidad_reclamos_todos: int | None`

- [ ] **Step 1: Write the failing test**

```python
# Nombre de archivo: test_servicios_detalle_reclamos_real_db.py
# Ubicación de archivo: tests/test_servicios_detalle_reclamos_real_db.py
# Descripción: El detalle de servicio devuelve sus reclamos (por línea, primer servicio o alias) y fotos de SLA

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.app.main import app  # verificar import real del app de api con: grep -n "FastAPI(" api/app/main.py
from db.session import SessionLocal
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real
_ORIGEN, _LINEA_VIEJA, _LINEA = "999801", "999802", "999803"


@pytest.fixture
def datos():
    with SessionLocal() as s:
        s.execute(text("""INSERT INTO app.servicios (servicio_id, numero_primer_servicio, numero_linea, nombre_cliente,
                          sla_prometido, alias_ids, estado_servicio)
                          VALUES (:o, :o, :l, 'TEST', '99.7', ARRAY[:v], 'Activo')"""),
                  {"o": _ORIGEN, "l": _LINEA, "v": _LINEA_VIEJA})
        for numero, linea, grupo in (("TSTD1", _LINEA, "Carrier"), ("TSTD2", _LINEA_VIEJA, "FO (excepto Cod 3)"),
                                     ("TSTD3", "000000", "Carrier")):
            s.execute(text("""INSERT INTO app.reclamos (numero_reclamo, numero_linea, nombre_cliente, fecha_inicio,
                              horas_netas, grupo_cierre) VALUES (:n, :l, 'TEST', now() - interval '10 days', 13.14, :g)"""),
                      {"n": numero, "l": linea, "g": grupo})
        s.execute(text("""INSERT INTO app.servicio_sla_snapshot (numero_linea, fecha_corte, sla_prometido, sla_entregado)
                          VALUES (:l, CURRENT_DATE, 99.7, 0.997)"""), {"l": _LINEA})
        s.commit()
    yield
    with SessionLocal() as s:
        s.execute(text("DELETE FROM app.reclamos WHERE numero_reclamo LIKE 'TSTD%'"))
        s.execute(text("DELETE FROM app.servicio_sla_snapshot WHERE numero_linea = :l"), {"l": _LINEA})
        s.execute(text("DELETE FROM app.servicios WHERE servicio_id = :o"), {"o": _ORIGEN})
        s.commit()


def test_detalle_trae_reclamos_y_sla_historico(datos):
    resp = TestClient(app).get("/servicios/detail", params={"id": _ORIGEN},
                               headers={"X-API-Key": "test-api-key"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    numeros = {r["numero_reclamo"] for r in body["servicio"]["reclamos"]}
    assert numeros == {"TSTD1", "TSTD2"}   # por línea actual y por alias; no el de otra línea
    reclamo = next(r for r in body["servicio"]["reclamos"] if r["numero_reclamo"] == "TSTD1")
    assert reclamo["pct_presupuesto"] == pytest.approx(50.0)
    assert body["sla_historico"][0]["sla_prometido"] == pytest.approx(99.7)
```

Antes de correrlo, confirmar las columnas NOT NULL de `app.servicios` (`\d app.servicios` en dev) y la auth del router (`grep -n "api_key\|X-API-Key" api/app/main.py`), y ajustar el INSERT y el header.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_servicios_detalle_reclamos_real_db.py -v`
Expected: FAIL (`TypeError: 'NoneType' object is not iterable` en `body["servicio"]["reclamos"]`).

- [ ] **Step 3: Implementation**

En `api/app/routes/servicios.py`:

```python
from datetime import date, datetime, timedelta

from core.sla_consumo.engine import presupuesto_horas
from db.models.reclamo import Reclamo
from db.models.sla_consumo import ServicioSlaSnapshot


class ReclamoServicioResponse(BaseModel):
    numero_reclamo: str
    numero_evento: str | None = None
    numero_linea: str
    fecha_inicio: datetime | None = None
    fecha_cierre: datetime | None = None
    tipo_solucion: str | None = None
    grupo_cierre: str | None = None
    codigo_cierre: int | None = None
    horas_netas: float | None = None
    cuenta_sla: bool = True
    pct_presupuesto: float | None = None
    carrier: str | None = None
    descripcion_solucion: str | None = None


class SlaSnapshotResponse(BaseModel):
    fecha_corte: date
    sla_prometido: float | None = None
    sla_entregado: float | None = None
    horas_reclamos_todos: float | None = None
    horas_restantes: float | None = None
    cantidad_reclamos_todos: int | None = None


def _lineas_del_servicio(svc: Servicio) -> list[str]:
    candidatas = {svc.numero_linea, svc.numero_primer_servicio, svc.servicio_id, *(svc.alias_ids or [])}
    return sorted(c.strip() for c in candidatas if c and c.strip())


async def _reclamos_del_servicio(db: AsyncSession, svc: Servicio) -> list[ReclamoServicioResponse]:
    lineas = _lineas_del_servicio(svc)
    desde = datetime.now().astimezone() - timedelta(days=365)
    filas = (await db.execute(
        select(Reclamo)
        .where(or_(Reclamo.numero_linea.in_(lineas), Reclamo.numero_primer_servicio.in_(lineas)),
               Reclamo.fecha_inicio >= desde)
        .order_by(Reclamo.fecha_inicio.desc())
    )).scalars().all()
    try:
        presupuesto = presupuesto_horas(float(svc.sla_prometido)) if svc.sla_prometido else None
    except ValueError:
        presupuesto = None
    salida = []
    for r in filas:
        horas = float(r.horas_netas) if r.horas_netas is not None else None
        cuenta = r.grupo_cierre != "Cierre Cliente"
        pct = (horas / presupuesto * 100) if (horas is not None and presupuesto and cuenta) else None
        salida.append(ReclamoServicioResponse(
            numero_reclamo=r.numero_reclamo, numero_evento=r.numero_evento, numero_linea=r.numero_linea,
            fecha_inicio=r.fecha_inicio, fecha_cierre=r.fecha_cierre, tipo_solucion=r.tipo_solucion,
            grupo_cierre=r.grupo_cierre, codigo_cierre=r.codigo_cierre, horas_netas=horas, cuenta_sla=cuenta,
            pct_presupuesto=pct, carrier=r.carrier, descripcion_solucion=r.descripcion_solucion))
    return salida


async def _sla_historico(db: AsyncSession, svc: Servicio) -> list[SlaSnapshotResponse]:
    filas = (await db.execute(
        select(ServicioSlaSnapshot)
        .where(ServicioSlaSnapshot.numero_linea.in_(_lineas_del_servicio(svc)))
        .order_by(ServicioSlaSnapshot.fecha_corte)
    )).scalars().all()
    def _f(v):
        return float(v) if v is not None else None
    return [SlaSnapshotResponse(fecha_corte=f.fecha_corte, sla_prometido=_f(f.sla_prometido),
                                sla_entregado=_f(f.sla_entregado), horas_reclamos_todos=_f(f.horas_reclamos_todos),
                                horas_restantes=_f(f.horas_restantes),
                                cantidad_reclamos_todos=f.cantidad_reclamos_todos) for f in filas]
```

- `ServicioItemResponse.reclamos`: cambiar el tipo a `list[ReclamoServicioResponse] | None = None` (las búsquedas siguen devolviendo `None`; sólo el detalle lo llena).
- `ServicioDetailResponse`: agregar `sla_historico: list[SlaSnapshotResponse] = []`.
- En `detail_servicio`, después de `item = _to_servicio_item(svc)`: `item.reclamos = await _reclamos_del_servicio(db, svc)` y pasar `sla_historico=await _sla_historico(db, svc)` al response. Hacer lo mismo en `refrescar_servicio_desde_prov` si construye `ServicioDetailResponse` (para no "vaciar" la vista tras refrescar).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_servicios_detalle_reclamos_real_db.py tests/test_servicios_ingest_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/servicios.py tests/test_servicios_detalle_reclamos_real_db.py
git commit -m "feat(servicios): el detalle devuelve reclamos con SLA consumido e histórico de SLA"
```

---

### Task 10: Frontend — pestaña SLA consumido y vista Reclamos

**Files:**
- Create: `web/frontend/src/composables/useSlaConsumo.ts`, `web/frontend/src/components/sla/SlaConsumoPanel.vue`
- Modify: `web/frontend/src/views/SlaView.vue`, `web/frontend/src/views/servicios/ServicioReclamosView.vue`, `web/frontend/src/api/servicios.ts`

**Interfaces:**
- Consumes: `POST /api/reports/sla-consumo` (Task 8); `servicio.reclamos` y `sla_historico` del detalle (Task 9); `request` de `web/frontend/src/api/client.ts` (mismo uso que `useSla.ts`, incluido el CSRF — copiar de `useSla.ts` la forma en que obtiene y manda `csrf_token`).

- [ ] **Step 1: Tipos en `api/servicios.ts`**

```ts
export interface ReclamoServicio {
  numero_reclamo: string;
  numero_evento: string | null;
  numero_linea: string;
  fecha_inicio: string | null;
  fecha_cierre: string | null;
  tipo_solucion: string | null;
  grupo_cierre: string | null;
  codigo_cierre: number | null;
  horas_netas: number | null;
  cuenta_sla: boolean;
  pct_presupuesto: number | null;
  carrier: string | null;
  descripcion_solucion: string | null;
}

export interface SlaSnapshot {
  fecha_corte: string;
  sla_prometido: number | null;
  sla_entregado: number | null;
  horas_reclamos_todos: number | null;
  horas_restantes: number | null;
  cantidad_reclamos_todos: number | null;
}
```

Cambiar `reclamos: Array<Record<string, unknown>> | null;` por `reclamos: ReclamoServicio[] | null;` y agregar `sla_historico?: SlaSnapshot[];` a la interfaz del detalle (`ServicioDetailResponse` o equivalente en el mismo archivo). Revisar con `grep -rn "\.reclamos" web/frontend/src` que `ServicioDetalleView.vue` y `ServiciosView.vue` sigan compilando (sólo usan `.length`).

- [ ] **Step 2: `useSlaConsumo.ts`**

```ts
// Nombre de archivo: useSlaConsumo.ts
// Ubicación de archivo: web/frontend/src/composables/useSlaConsumo.ts
// Descripción: Estado y llamada al informe de SLA consumido (persiste el histórico de reclamos)

import { ref } from 'vue';
import { request } from '../api/client';

export interface SlaConsumoResultado {
  ok?: boolean;
  error?: string;
  fecha_corte?: string;
  ya_ingestado?: boolean;
  reclamos_insertados?: number;
  reclamos_actualizados?: number;
  totales?: Record<string, number>;
  report_paths?: Record<string, string>;
}

type Tono = 'muted' | 'info' | 'success' | 'error';

export function useSlaConsumo() {
  const archivos = ref<File[]>([]);
  const resultado = ref<SlaConsumoResultado | null>(null);
  const loading = ref(false);
  const mensaje = ref('Subí los Excel de Servicios y Reclamos. Los reclamos quedan guardados en el histórico.');
  const tono = ref<Tono>('muted');

  async function generar(pdf: boolean, csrfToken: string | null): Promise<void> {
    resultado.value = null;
    if (archivos.value.length !== 2) {
      mensaje.value = 'Adjuntá exactamente dos archivos: Servicios y Reclamos.';
      tono.value = 'error';
      return;
    }
    const form = new FormData();
    archivos.value.forEach((f) => form.append('files', f));
    form.append('pdf_enabled', String(pdf));
    if (csrfToken) form.append('csrf_token', csrfToken);
    loading.value = true;
    mensaje.value = 'Procesando…';
    tono.value = 'info';
    try {
      const data = await request<SlaConsumoResultado>('/api/reports/sla-consumo', { method: 'POST', body: form });
      resultado.value = data;
      if (data.ok) {
        mensaje.value = data.ya_ingestado
          ? `Corte ${data.fecha_corte}: estos archivos ya estaban ingestados; informe regenerado.`
          : `Corte ${data.fecha_corte}: ${data.reclamos_insertados} reclamos nuevos, ${data.reclamos_actualizados} actualizados.`;
        tono.value = 'success';
      } else {
        mensaje.value = data.error ?? 'No se pudo generar el informe.';
        tono.value = 'error';
      }
    } catch (err) {
      mensaje.value = err instanceof Error ? err.message : 'Error de red';
      tono.value = 'error';
    } finally {
      loading.value = false;
    }
  }

  return { archivos, resultado, loading, mensaje, tono, generar };
}
```

Ajustar la firma de `request` a la real de `api/client.ts` (ver cómo la llama `useSla.ts`; si `request` lanza en status ≠ 2xx con el body, mapear ese error a `mensaje`).

- [ ] **Step 3: `SlaConsumoPanel.vue`** — formulario (input file múltiple `.xlsx`, checkbox PDF, botón Generar), mensaje con clase por tono, tarjetas de `totales` (reclamos, eventos, servicios, servicios excedidos, horas SLA) y links de `report_paths` (XLSX/DOCX/PDF). Reusar las mismas clases/estilos de formulario y flash que `SlaView.vue` (copiar el bloque `<style scoped>` relevante) para que se vea igual; colores sólo con `var(--color-*)`. Obtener el CSRF igual que `SlaView.vue`.

- [ ] **Step 4: `SlaView.vue`** — agregar dos tabs arriba ("Informe SLA" / "SLA consumido") con un `ref<'sla' | 'consumo'>('sla')`; el contenido actual queda bajo `v-if="tab === 'sla'"` y `<SlaConsumoPanel v-else />`.

- [ ] **Step 5: `ServicioReclamosView.vue`** — reemplazar la tabla de columnas dinámicas por columnas fijas: Reclamo, Evento, Inicio, Cierre, Tipo solución, Grupo, Horas netas, % presupuesto (con "no cuenta" cuando `!cuenta_sla`), Carrier. Formatear fechas con `toLocaleString('es-AR')` y números con 2 decimales. Debajo, sección "Histórico de SLA" con una tabla `fecha_corte · SLA prometido · SLA entregado (%) · horas reclamos · horas restantes` desde `base.servicio`/detalle `sla_historico` (exponerlo desde `useServicioBase` si hoy sólo guarda `servicio`: agregar `slaHistorico = ref<SlaSnapshot[]>([])` y llenarlo en `cargar`). Quitar el "Último informe" global (engañoso: no es del servicio) y en su lugar mostrar "Última foto de SLA: <fecha_corte>" si hay histórico.

- [ ] **Step 6: Build y compliance**

```bash
cd web/frontend && ln -sfn /home/support-focal-01/LAS-FOCAS/web/frontend/node_modules node_modules && npx vue-tsc --noEmit && npm run build
```
Expected: sin errores de tipos; build OK. Luego invocar la skill `nocturne-token-compliance` sobre `SlaConsumoPanel.vue`, `SlaView.vue` y `ServicioReclamosView.vue` y corregir hex/rgba literales.

- [ ] **Step 7: Commit**

```bash
git add web/frontend/src
git commit -m "feat(web): pestaña SLA consumido y reclamos con SLA en el detalle de servicio"
```

---

### Task 11: Smoke con datos reales en dev, documentación

**Files:**
- Create: `docs/informes/sla_consumo.md`
- Modify: `docs/decisiones.md`, `docs/PR/2026-10-05.md` (crear o ampliar con `/generar-pr-diario`), `.env.dev.example` o equivalente (documentar `SLA_CIERRE_CLIENTE_VALORES`)

- [ ] **Step 1: Recrear contenedores dev desde el worktree** (ver memoria "SDD: verificar imagen de contenedor": TestClient no prueba lo desplegado). Usar la skill `docker-rebuild` con `--env-file` y rebuild de `api` y `web`; `alembic upgrade head` dentro del contenedor api.

- [ ] **Step 2: E2E real** — desde la SPA en dev (`/sla` → SLA consumido) subir los dos Excel de `docs/Doc Privada/`. Verificar:

```bash
docker exec lasfocasdev-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT count(*), count(DISTINCT numero_evento), round(sum(horas_netas),2) FROM app.reclamos;
SELECT grupo_cierre, count(*) FROM app.reclamos GROUP BY 1 ORDER BY 2 DESC;
SELECT fecha_corte, count(*) FROM app.servicio_sla_snapshot GROUP BY 1;"'
```
Expected: `4518 | 402 | <Σ Horas Netas Problema del Excel>`; Carrier 581, FO Cod 3 154; una fecha de corte con 7228 servicios. Resubir el mismo par → respuesta `ya_ingestado: true` y los mismos conteos. Abrir el detalle del servicio de línea 88102 → vista Reclamos con 6 reclamos y `pct_presupuesto` coherente; abrir XLSX/DOCX y revisar gráficos.

- [ ] **Step 3: Documentación** — `docs/informes/sla_consumo.md`: propósito, columnas de entrada, fórmulas (presupuesto, % presupuesto, pp), grupos de cierre y `SLA_CIERRE_CLIENTE_VALORES`, idempotencia y fecha de corte, salidas, y la nota de conciliación (el SLA oficial `Horas Reclamos Todos` difiere de Σ netas en 99 líneas; el informe usa netas por decisión del usuario del 2026-10-05). `docs/decisiones.md`: decisión "histórico SLA consumido" (persistir al generar, fecha de corte automática, horas en horas). PR diario con comandos y riesgos.

- [ ] **Step 4: Suite completa y commit**

```bash
pytest -q
git add docs .env.dev.example
git commit -m "docs(sla): informe de SLA consumido, decisión del histórico y PR diario"
```
Expected: suite verde, salvo los tests de SPA shell que necesitan `web/frontend/dist` (aviso conocido del worktree).
