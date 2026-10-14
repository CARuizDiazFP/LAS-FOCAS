# Ampliación del informe SLA consumido — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconstruir el cálculo del informe SLA consumido sobre el **servicio unificado** (semáforos de causa, estados de presupuesto, acumulados, impacto Evento × Servicio con tres indicadores) y entregar XLSX completo + DOCX ejecutivo + DOCX exhaustivo.

**Architecture:** La lógica vive en módulos puros de pandas dentro de `core/sla_consumo/`: `metricas.py` (reglas atómicas), `identidad.py` (unificación), `impacto.py` (acumulados e indicadores), orquestados por `engine.calcular()`. `presentacion.py` concentra etiquetas, leyendas, colores y formatos que comparten XLSX y DOCX. Los builders y Vue no calculan nada. No hay migración: la persistencia y la idempotencia actuales se conservan.

**Tech Stack:** Python 3.11, pandas 2.2, openpyxl 3.1, python-docx 1.1, matplotlib 3.9 (Agg), FastAPI, Vue 3 + TS.

**Spec:** `/home/support-focal-01/.claude/plans/pasted-content-id-946d-problema-no-buzzing-curry.md` (plan aprobado 2026-10-05 con las decisiones del usuario). El prompt correctivo completo del usuario está resumido allí; las secciones §N citadas abajo refieren a ese prompt.

## Global Constraints

- Ventana de 365 días; los reclamos que solapan la ventana se cuentan completos (la regla actual de `cargar_ventana`, sin cambios).
- Fuente del consumo: `Horas Netas Problema Reclamo` (`horas_netas`). Se suman aunque se superpongan en el tiempo; **nunca deduplicar intervalos**.
- Presupuesto: `(1 − SLA_prometido/100) · 8760` h, calculado por `engine.presupuesto_horas`. **Nunca una constante de 26 h** en código productivo.
- Presupuesto válido = finito y `> EPS_HORAS`. En cualquier otro caso el estado es **"No evaluable"** y los porcentajes quedan `None`/NaN, nunca inventados.
- `EPS_HORAS = 1e-6` es la tolerancia de las comparaciones de estados; se compara sin redondear.
- Servicio unificado:
  - clave = `numero_primer_servicio`, con fallback `numero_linea`;
  - **ID visible = línea de referencia** = la `numero_linea` numéricamente mayor del grupo (comparación `int`; las no numéricas pierden contra las numéricas);
  - SLA prometido y métricas oficiales salen **sólo** de la fila de referencia y nunca se suman.
- `numero_primer_servicio` no se muestra como ID. Tampoco se muestra la "línea original" del reclamo.
- Causas:
  - FO = grupo `"FO (excepto Cod 3)"` ("FO general") + `"FO Cod 3 (Corte en Bandeja)"` ("FO Cod 3");
  - `"Carrier"` y `"Otros"` son no FO;
  - `"Cierre Cliente"` = excluido, sin causa.
  - La clasificación usa el clasificador existente; tener número de evento **no** convierte un reclamo en FO.
- Semáforo de servicio, sobre horas computables: Rojo = sólo FO; Amarillo = FO y no FO; Verde = sólo no FO; Sin color = 0 horas computables.
- Indicador de reclamo: Rojo = FO con horas > 0; Verde = no FO con horas > 0; Sin color = 0 horas o excluido. Un reclamo nunca es Amarillo.
- Estados: "Sin consumo" / "Dentro de SLA" / "Presupuesto agotado" / "SLA excedido" / "No evaluable". Son independientes del semáforo.
- % real sin truncar (para cálculos y para el aporte por reclamo o evento). % visible del consumo total = `min(% real, 100)`, mostrado junto a las horas excedidas.
- Orden del acumulado: `fecha_inicio` y luego `numero_reclamo` numérico (desempate determinista). El acumulado es una atribución por orden, no el instante físico de la ruptura.
- Una sola **torta global** de causas; **no hay tortas por servicio ni por reclamo**. Su denominador es el total de horas computables.
- Encabezado obligatorio de 3 líneas (`# Nombre de archivo / # Ubicación de archivo / # Descripción`) en todo archivo nuevo.
- Commits con trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Sin push. Sin `git stash`. Sin deploy a prod.
- Tests real-db con DEV:
  ```
  export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_DB=focas_dev POSTGRES_USER=FOCALBOT POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)"
  ```
  Nunca usar el puerto 5432 ni `lasfocas-postgres`.

## Review Focus

1. **Servicio sin presupuesto válido** (SLA ausente, o SLA 100 → presupuesto 0) que tiene reclamos: debe quedar "No evaluable", sin porcentajes, sin indicadores de evento en verdadero y sin `inf`, tanto en las vistas como en las exportaciones. Tests en Tasks 1, 3 y 4.
2. **Reclamo que no se vincula** a ningún servicio del universo: aparece en "no vinculados" e "inconsistencias", fuera del consumo de los servicios y de la torta, y contado en los totales. Tests en Tasks 3 y 4.
3. **Fechas `fecha_inicio` empatadas** dentro de un servicio: el orden se desempata por número de reclamo numérico ("10" va después de "9"). Test en Task 2.
4. **Evento cuyas horas son 0 o excluidas**: no cruza el umbral, no es determinante y no altera el semáforo. Test en Task 2.
5. **Universo completo con datos reales** (7228 servicios, 4517 reclamos): las exportaciones no truncan filas y generan en tiempo razonable (< 3 min en total). Se verifica en Task 7.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `core/sla_consumo/metricas.py` (nuevo) | Constantes y funciones puras: causa, indicador, semáforo, estado, porcentajes, tolerancia |
| `core/sla_consumo/identidad.py` (nuevo) | Unificación de servicios y vinculación de reclamos |
| `core/sla_consumo/impacto.py` (nuevo) | Acumulados, Evento×Servicio, reclamos sin evento, resumen de eventos, inconsistencias |
| `core/sla_consumo/engine.py` (reescritura) | `calcular()` + `ResultadoSlaConsumo` ampliado; conserva `presupuesto_horas`, `HORAS_ANIO` |
| `core/sla_consumo/presentacion.py` (nuevo) | Etiquetas de columnas, leyendas, colores, formateo horas/% (compartido XLSX/DOCX) |
| `core/sla_consumo/charts.py` (reescritura) | Torta global de causas + gráfico de magnitud de eventos |
| `core/sla_consumo/xlsx_builder.py` (reescritura) | XLSX universo completo con formatos |
| `core/sla_consumo/docx_builder.py` (reescritura) | `construir_docx_ejecutivo`, `construir_docx_exhaustivo` |
| `core/services/sla_consumo.py` (mod) | Genera las 3 salidas + PDFs identificados |
| `web/app/main.py` (mod) | `report_paths` ampliado |
| `web/frontend/src/composables/useSlaConsumo.ts`, `web/frontend/src/components/sla/SlaConsumoPanel.vue` (mod) | Enlaces diferenciados |
| `docs/informes/sla_consumo.md` (mod) | Reglas finales |
| Tests | `tests/test_sla_consumo_metricas.py`, `tests/test_sla_consumo_identidad.py`, `tests/test_sla_consumo_impacto.py`, `tests/test_sla_consumo_engine.py` (reescrito), `tests/test_sla_consumo_builders.py` (reescrito), `tests/test_web_sla_consumo.py` (mod) |

---

### Task 1: Reglas atómicas (`metricas.py`) y unificación de servicios (`identidad.py`)

**Files:**
- Create: `core/sla_consumo/metricas.py`, `core/sla_consumo/identidad.py`
- Test: `tests/test_sla_consumo_metricas.py`, `tests/test_sla_consumo_identidad.py`

**Interfaces:**
- Consumes: constantes de grupo de `core/sla_consumo/clasificador.py` (`GRUPO_FO`, `GRUPO_FO_COD3`, `GRUPO_CARRIER`, `GRUPO_OTROS`, `GRUPO_CLIENTE`); `core.sla_consumo.engine.presupuesto_horas` NO se importa acá: para evitar ciclos, `metricas.py` define `presupuesto_horas` y `HORAS_ANIO`, y en Task 3 `engine.py` los re-exporta.
- Produces (`metricas.py`):
  - `HORAS_ANIO = 8760.0`, `EPS_HORAS = 1e-6`
  - `CAUSA_FO_GENERAL = "FO general"`, `CAUSA_FO_COD3 = "FO Cod 3"`, `CAUSA_CARRIER = "Carrier"`, `CAUSA_OTROS = "Otros"`, `CAUSAS_ORDEN = (CAUSA_FO_GENERAL, CAUSA_FO_COD3, CAUSA_CARRIER, CAUSA_OTROS)`, `CAUSAS_FO = frozenset({CAUSA_FO_GENERAL, CAUSA_FO_COD3})`
  - `ROJO = "Rojo"`, `AMARILLO = "Amarillo"`, `VERDE = "Verde"`, `SIN_COLOR = "Sin color"`
  - `ESTADO_SIN_CONSUMO = "Sin consumo"`, `ESTADO_DENTRO = "Dentro de SLA"`, `ESTADO_AGOTADO = "Presupuesto agotado"`, `ESTADO_EXCEDIDO = "SLA excedido"`, `ESTADO_NO_EVALUABLE = "No evaluable"`, `ESTADOS_AGOTADO_O_EXCEDIDO = frozenset({ESTADO_AGOTADO, ESTADO_EXCEDIDO})`
  - `presupuesto_horas(sla_prometido) -> float | None`; `presupuesto_valido(p) -> bool`
  - `causa_de_grupo(grupo: str | None) -> str | None`
  - `indicador_reclamo(causa: str | None, horas_computables: float) -> str`
  - `semaforo_servicio(horas_fo: float, horas_no_fo: float) -> str`
  - `estado_presupuesto(consumo: float, presupuesto: float | None) -> str`
  - `pct_real(horas: float, presupuesto: float | None) -> float | None`; `pct_visible(pct: float | None) -> float | None`
- Produces (`identidad.py`):
  - `@dataclass(frozen=True) Unificacion(servicios: pd.DataFrame, linea_a_clave: dict[str, str])`. Columnas de `servicios`: `clave_servicio, servicio_id, lineas_asociadas, nombre_cliente, tipo_servicio, sla_prometido, presupuesto_h, sla_entregado_oficial, horas_reclamos_todos_oficial, horas_restantes_oficial`.
  - `unificar_servicios(servicios: pd.DataFrame) -> Unificacion`. La entrada tiene las columnas de `parser.SERVICIOS_COLS`.
  - `vincular_reclamos(reclamos: pd.DataFrame, unificacion: Unificacion) -> tuple[pd.DataFrame, pd.DataFrame]` → `(vinculados, no_vinculados)`. A `vinculados` se le agregan `clave_servicio`, `servicio_id` y `presupuesto_h`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sla_consumo_metricas.py`:

```python
# Nombre de archivo: test_sla_consumo_metricas.py
# Ubicación de archivo: tests/test_sla_consumo_metricas.py
# Descripción: Reglas atómicas del informe SLA consumido — causa, indicador, semáforo, estado y porcentajes

from __future__ import annotations

import math

import pytest

from core.sla_consumo import metricas as m
from core.sla_consumo.clasificador import GRUPO_CARRIER, GRUPO_CLIENTE, GRUPO_FO, GRUPO_FO_COD3, GRUPO_OTROS

SLA_26 = 100 * (1 - 26 / 8760)  # presupuesto exacto de 26 h, sólo para fixtures


def test_presupuesto_y_validez():
    assert m.presupuesto_horas(99.7) == pytest.approx(26.28)
    assert m.presupuesto_horas(SLA_26) == pytest.approx(26.0)
    assert m.presupuesto_horas(None) is None
    assert m.presupuesto_valido(26.0) is True
    for invalido in (None, 0.0, float("nan"), float("inf"), -1.0):
        assert m.presupuesto_valido(invalido) is False


@pytest.mark.parametrize("grupo, causa", [
    (GRUPO_FO, m.CAUSA_FO_GENERAL), (GRUPO_FO_COD3, m.CAUSA_FO_COD3), (GRUPO_CARRIER, m.CAUSA_CARRIER),
    (GRUPO_OTROS, m.CAUSA_OTROS), (GRUPO_CLIENTE, None), (None, None),
])
def test_causa_de_grupo(grupo, causa):
    assert m.causa_de_grupo(grupo) == causa


def test_indicador_reclamo_nunca_amarillo():
    assert m.indicador_reclamo(m.CAUSA_FO_GENERAL, 4.0) == m.ROJO
    assert m.indicador_reclamo(m.CAUSA_FO_COD3, 0.5) == m.ROJO
    assert m.indicador_reclamo(m.CAUSA_CARRIER, 1.0) == m.VERDE
    assert m.indicador_reclamo(m.CAUSA_OTROS, 1.0) == m.VERDE
    assert m.indicador_reclamo(m.CAUSA_FO_GENERAL, 0.0) == m.SIN_COLOR
    assert m.indicador_reclamo(None, 5.0) == m.SIN_COLOR


@pytest.mark.parametrize("fo, no_fo, esperado", [
    (4, 0, m.ROJO), (4, 1, m.AMARILLO), (0, 4, m.VERDE), (0, 0, m.SIN_COLOR), (27, 1, m.AMARILLO),
    (2 / 60, 27, m.AMARILLO),
])
def test_semaforo_servicio(fo, no_fo, esperado):
    assert m.semaforo_servicio(fo, no_fo) == esperado


@pytest.mark.parametrize("consumo, presupuesto, esperado", [
    (0.0, 26.0, m.ESTADO_SIN_CONSUMO),
    (4.0, 26.0, m.ESTADO_DENTRO),
    (26.0, 26.0, m.ESTADO_AGOTADO),
    (26.0 + 1e-9, 26.0, m.ESTADO_AGOTADO),       # dentro de la tolerancia
    (28.0, 26.0, m.ESTADO_EXCEDIDO),
    (25.999, 26.0, m.ESTADO_DENTRO),             # no se redondea
    (5.0, None, m.ESTADO_NO_EVALUABLE),
    (0.0, None, m.ESTADO_NO_EVALUABLE),
    (5.0, 0.0, m.ESTADO_NO_EVALUABLE),
])
def test_estado_presupuesto(consumo, presupuesto, esperado):
    assert m.estado_presupuesto(consumo, presupuesto) == esperado


def test_porcentajes():
    assert m.pct_real(28.0, 26.0) == pytest.approx(107.6923, abs=1e-4)
    assert m.pct_visible(107.69) == 100.0
    assert m.pct_visible(50.0) == 50.0
    assert m.pct_real(5.0, None) is None
    assert m.pct_real(5.0, 0.0) is None
    assert m.pct_visible(None) is None
    assert not math.isinf(m.pct_real(5.0, 26.0))
```

`tests/test_sla_consumo_identidad.py`:

```python
# Nombre de archivo: test_sla_consumo_identidad.py
# Ubicación de archivo: tests/test_sla_consumo_identidad.py
# Descripción: Unificación de servicios por primer servicio y vinculación de reclamos

from __future__ import annotations

import pandas as pd
import pytest

from core.sla_consumo.identidad import unificar_servicios, vincular_reclamos
from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS


def _s(primer, linea, sla, oficial_h=0.0, cliente="C"):
    fila = {c: None for c in SERVICIOS_COLS}
    fila.update(numero_primer_servicio=primer, numero_linea=linea, sla_prometido=sla, nombre_cliente=cliente,
                horas_reclamos_todos=oficial_h, sla_entregado=1 - oficial_h / 8760)
    return fila


def _r(numero, linea, primer):
    fila = {c: None for c in RECLAMOS_COLS}
    fila.update(numero_reclamo=numero, numero_linea=linea, numero_primer_servicio=primer, horas_netas=1.0)
    return fila


def test_mismo_primer_servicio_una_ficha_con_linea_numericamente_mayor():
    servicios = pd.DataFrame([_s("A", "9", 99.0, 5.0), _s("A", "10", 99.7, 7.0), _s(None, "77", 99.5)],
                             columns=SERVICIOS_COLS)
    uni = unificar_servicios(servicios)
    s = uni.servicios.set_index("clave_servicio")
    assert len(s) == 2
    assert s.loc["A", "servicio_id"] == "10"            # "10" > "9" numéricamente
    assert s.loc["A", "lineas_asociadas"] == "9, 10"
    assert s.loc["A", "sla_prometido"] == pytest.approx(99.7)
    assert s.loc["A", "presupuesto_h"] == pytest.approx(26.28)   # un único presupuesto, no sumado
    assert s.loc["A", "horas_reclamos_todos_oficial"] == pytest.approx(7.0)
    assert s.loc["77", "servicio_id"] == "77"            # fallback numero_linea
    assert uni.linea_a_clave == {"9": "A", "10": "A", "77": "77"}


def test_linea_no_numerica_pierde_contra_numerica():
    uni = unificar_servicios(pd.DataFrame([_s("A", "X-1", 99.7), _s("A", "5", 99.0)], columns=SERVICIOS_COLS))
    assert uni.servicios.iloc[0]["servicio_id"] == "5"


def test_vincular_por_primer_servicio_y_fallback_por_linea():
    uni = unificar_servicios(pd.DataFrame([_s("A", "9", 99.7), _s("A", "10", 99.7), _s(None, "77", 99.5)],
                                          columns=SERVICIOS_COLS))
    reclamos = pd.DataFrame([_r("1", "9", "A"), _r("2", "10", "A"), _r("3", "77", None),
                             _r("4", "9", None), _r("5", "555", "ZZ")], columns=RECLAMOS_COLS)
    vinc, no_vinc = vincular_reclamos(reclamos, uni)
    assert dict(zip(vinc["numero_reclamo"], vinc["servicio_id"])) == {"1": "10", "2": "10", "3": "77", "4": "10"}
    assert list(no_vinc["numero_reclamo"]) == ["5"]
    assert "presupuesto_h" in vinc.columns and "presupuesto_h" not in no_vinc.columns
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sla_consumo_metricas.py tests/test_sla_consumo_identidad.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.sla_consumo.metricas'`

- [ ] **Step 3: Implement `metricas.py`**

```python
# Nombre de archivo: metricas.py
# Ubicación de archivo: core/sla_consumo/metricas.py
# Descripción: Reglas atómicas del informe SLA consumido — causa, indicador, semáforo, estado, porcentajes

from __future__ import annotations

import math

from core.sla_consumo.clasificador import GRUPO_CARRIER, GRUPO_FO, GRUPO_FO_COD3, GRUPO_OTROS

HORAS_ANIO = 8760.0
# Tolerancia de las comparaciones de estado (≈3,6 ms): absorbe el ruido de punto flotante de sumas
# acumuladas sin que un redondeo de presentación cambie un estado.
EPS_HORAS = 1e-6

CAUSA_FO_GENERAL = "FO general"
CAUSA_FO_COD3 = "FO Cod 3"
CAUSA_CARRIER = "Carrier"
CAUSA_OTROS = "Otros"
CAUSAS_ORDEN = (CAUSA_FO_GENERAL, CAUSA_FO_COD3, CAUSA_CARRIER, CAUSA_OTROS)
CAUSAS_FO = frozenset({CAUSA_FO_GENERAL, CAUSA_FO_COD3})

ROJO, AMARILLO, VERDE, SIN_COLOR = "Rojo", "Amarillo", "Verde", "Sin color"

ESTADO_SIN_CONSUMO = "Sin consumo"
ESTADO_DENTRO = "Dentro de SLA"
ESTADO_AGOTADO = "Presupuesto agotado"
ESTADO_EXCEDIDO = "SLA excedido"
ESTADO_NO_EVALUABLE = "No evaluable"
ESTADOS_AGOTADO_O_EXCEDIDO = frozenset({ESTADO_AGOTADO, ESTADO_EXCEDIDO})

_CAUSA_POR_GRUPO = {GRUPO_FO: CAUSA_FO_GENERAL, GRUPO_FO_COD3: CAUSA_FO_COD3,
                    GRUPO_CARRIER: CAUSA_CARRIER, GRUPO_OTROS: CAUSA_OTROS}


def _numero(valor: object) -> float | None:
    if valor is None:
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(numero) else numero


def presupuesto_horas(sla_prometido: object) -> float | None:
    sla = _numero(sla_prometido)
    return None if sla is None else (1 - sla / 100) * HORAS_ANIO


def presupuesto_valido(presupuesto: object) -> bool:
    p = _numero(presupuesto)
    return p is not None and math.isfinite(p) and p > EPS_HORAS


def causa_de_grupo(grupo: str | None) -> str | None:
    """Cierre Cliente (excluido) y grupos desconocidos no tienen causa."""
    return _CAUSA_POR_GRUPO.get(grupo)


def indicador_reclamo(causa: str | None, horas_computables: float) -> str:
    if causa is None or not horas_computables or horas_computables <= EPS_HORAS:
        return SIN_COLOR
    return ROJO if causa in CAUSAS_FO else VERDE


def semaforo_servicio(horas_fo: float, horas_no_fo: float) -> str:
    hay_fo, hay_no_fo = horas_fo > EPS_HORAS, horas_no_fo > EPS_HORAS
    if hay_fo and hay_no_fo:
        return AMARILLO
    if hay_fo:
        return ROJO
    return VERDE if hay_no_fo else SIN_COLOR


def estado_presupuesto(consumo: float, presupuesto: object) -> str:
    if not presupuesto_valido(presupuesto):
        return ESTADO_NO_EVALUABLE
    p = float(presupuesto)
    if consumo <= EPS_HORAS:
        return ESTADO_SIN_CONSUMO
    if abs(consumo - p) <= EPS_HORAS:
        return ESTADO_AGOTADO
    return ESTADO_EXCEDIDO if consumo > p else ESTADO_DENTRO


def pct_real(horas: float, presupuesto: object) -> float | None:
    return float(horas) / float(presupuesto) * 100 if presupuesto_valido(presupuesto) else None


def pct_visible(pct: float | None) -> float | None:
    return None if pct is None else min(pct, 100.0)
```

- [ ] **Step 4: Implement `identidad.py`**

```python
# Nombre de archivo: identidad.py
# Ubicación de archivo: core/sla_consumo/identidad.py
# Descripción: Unifica servicios por primer servicio (ID visible = línea numéricamente mayor) y vincula reclamos

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.sla_consumo.metricas import presupuesto_horas


@dataclass(frozen=True)
class Unificacion:
    servicios: pd.DataFrame
    linea_a_clave: dict[str, str]


def _texto(valor: object) -> str | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor is pd.NA:
        return None
    texto = str(valor).strip()
    return texto or None


def _orden_linea(linea: str) -> tuple[int, int, str]:
    """Las numéricas ganan a las no numéricas; entre numéricas compara el entero, no el texto."""
    try:
        return (1, int(linea), "")
    except ValueError:
        return (0, 0, linea)


def _clave(primer: object, linea: object) -> str | None:
    return _texto(primer) or _texto(linea)


def unificar_servicios(servicios: pd.DataFrame) -> Unificacion:
    df = servicios.copy()
    df["numero_linea"] = df["numero_linea"].map(_texto)
    df = df[df["numero_linea"].notna()]
    df["clave_servicio"] = [_clave(p, l) for p, l in zip(df["numero_primer_servicio"], df["numero_linea"])]
    filas = []
    for clave, grupo in df.groupby("clave_servicio", sort=False):
        lineas = sorted(grupo["numero_linea"].unique(), key=_orden_linea)
        referencia = grupo[grupo["numero_linea"] == lineas[-1]].iloc[-1]
        filas.append({
            "clave_servicio": clave,
            "servicio_id": lineas[-1],
            "lineas_asociadas": ", ".join(lineas),
            "nombre_cliente": referencia["nombre_cliente"],
            "tipo_servicio": referencia["tipo_servicio"],
            "sla_prometido": referencia["sla_prometido"],
            "presupuesto_h": presupuesto_horas(referencia["sla_prometido"]),
            "sla_entregado_oficial": referencia["sla_entregado"],
            "horas_reclamos_todos_oficial": referencia["horas_reclamos_todos"],
            "horas_restantes_oficial": referencia["horas_restantes"],
        })
    columnas = ["clave_servicio", "servicio_id", "lineas_asociadas", "nombre_cliente", "tipo_servicio",
                "sla_prometido", "presupuesto_h", "sla_entregado_oficial", "horas_reclamos_todos_oficial",
                "horas_restantes_oficial"]
    unificados = pd.DataFrame(filas, columns=columnas)
    unificados["presupuesto_h"] = unificados["presupuesto_h"].astype(float)
    linea_a_clave = dict(zip(df["numero_linea"], df["clave_servicio"]))
    return Unificacion(unificados, linea_a_clave)


def vincular_reclamos(reclamos: pd.DataFrame, unificacion: Unificacion) -> tuple[pd.DataFrame, pd.DataFrame]:
    claves = set(unificacion.servicios["clave_servicio"])

    def _resolver(primer: object, linea: object) -> str | None:
        p = _texto(primer)
        if p is not None and p in claves:
            return p
        return unificacion.linea_a_clave.get(_texto(linea) or "")

    df = reclamos.copy()
    df["clave_servicio"] = [_resolver(p, l) for p, l in zip(df["numero_primer_servicio"], df["numero_linea"])]
    no_vinculados = df[df["clave_servicio"].isna()].drop(columns="clave_servicio").reset_index(drop=True)
    vinculados = df[df["clave_servicio"].notna()].merge(
        unificacion.servicios[["clave_servicio", "servicio_id", "presupuesto_h"]], on="clave_servicio", how="left")
    return vinculados.reset_index(drop=True), no_vinculados
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_sla_consumo_metricas.py tests/test_sla_consumo_identidad.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/sla_consumo/metricas.py core/sla_consumo/identidad.py tests/test_sla_consumo_metricas.py tests/test_sla_consumo_identidad.py
git commit -m "feat(sla): reglas de semáforo/estado y unificación de servicios por primer servicio"
```

---

### Task 2: Acumulados e impacto (`impacto.py`)

**Files:**
- Create: `core/sla_consumo/impacto.py`
- Test: `tests/test_sla_consumo_impacto.py`

**Interfaces:**
- Consumes: `metricas` (Task 1).
- Produces:
  - `acumulados(vinculados: pd.DataFrame) -> pd.DataFrame`.
    - **Input:** `clave_servicio`, `servicio_id`, `presupuesto_h`, `numero_reclamo`, `numero_evento`, `fecha_inicio`, `fecha_cierre`, `causa`, `horas_computables`, plus any other columns.
    - **Adds:** `consumo_acum_antes`, `consumo_acum_despues`, `restantes_acum`, `excedidas_acum`, `pct_aporte_real`, `alcanza_primera_vez`, `supera_primera_vez`.
    - **Ordering:** by `clave_servicio`, `fecha_inicio`, numeric `numero_reclamo`, text `numero_reclamo`.
  - `impacto(acum: pd.DataFrame, servicios: pd.DataFrame, por: str) -> pd.DataFrame`.
    - **`por`:** `"numero_evento"` uses only rows with an event; `"numero_reclamo"` uses only rows without one.
    - **`servicios`:** must carry `clave_servicio`, `servicio_id`, `nombre_cliente`, `presupuesto_h`, `horas_computables`, `estado`.
    - **Output columns:** `<por>`, `clave_servicio`, `servicio_id`, `nombre_cliente`, `reclamos`, `reclamos_ids`, `horas_computables`, `horas_fo`, `horas_no_fo`, `presupuesto_h`, `pct_aporte_real`, `consumo_total_servicio`, `estado_servicio`, `suficiente_solo` (`"Excede" | "Agota" | "No" | "No evaluable"`), `cruza_umbral` (bool), `determinante_al_excluir` (bool), `participa_en_agotado_o_excedido` (bool).
  - `resumen_eventos(acum: pd.DataFrame, ev_srv: pd.DataFrame) -> pd.DataFrame`.
    - **Columns:** `numero_evento`, `inicio_observado`, `cierre_observado`, `reclamos`, `servicios_afectados`, `horas_servicio`, `horas_<causa>` for each cause (`horas_fo_general`, `horas_fo_cod3`, `horas_carrier`, `horas_otros`), `servicios_agotados_o_excedidos`, `n_suficiente_solo`, `servicios_suficiente_solo`, `n_cruza_umbral`, `servicios_cruza_umbral`, `n_determinante`, `servicios_determinante`.
    - **Ordering:** by `horas_servicio` descending.
  - `inconsistencias(acum: pd.DataFrame, no_vinculados: pd.DataFrame, servicios: pd.DataFrame) -> pd.DataFrame`.
    - **Columns:** `tipo`, `numero_evento`, `numero_reclamo`, `servicio_id`, `detalle`.
    - **Constants for `tipo`:** `INCONS_CARRIER_CON_EVENTO = "Reclamo Carrier con evento"`, `INCONS_EVENTO_MIXTO = "Evento con causas FO y no FO"`, `INCONS_NO_VINCULADO = "Reclamo no vinculado a un servicio"`, `INCONS_NO_EVALUABLE = "Servicio no evaluable (sin presupuesto válido)"`.

- [ ] **Step 1: Write the failing test**

```python
# Nombre de archivo: test_sla_consumo_impacto.py
# Ubicación de archivo: tests/test_sla_consumo_impacto.py
# Descripción: Acumulados por servicio e indicadores de impacto Evento × Servicio (casos de aceptación)

from __future__ import annotations

import pandas as pd
import pytest

from core.sla_consumo import metricas as m
from core.sla_consumo.impacto import (INCONS_CARRIER_CON_EVENTO, INCONS_EVENTO_MIXTO, INCONS_NO_EVALUABLE,
                                      INCONS_NO_VINCULADO, acumulados, impacto, inconsistencias, resumen_eventos)
from core.utils.excel_duraciones import TZ_AR

P26 = 26.0


def _c(numero, horas, causa=m.CAUSA_FO_GENERAL, evento=None, clave="A", dia=1, presupuesto=P26):
    return {"clave_servicio": clave, "servicio_id": clave, "presupuesto_h": presupuesto,
            "numero_reclamo": numero, "numero_evento": evento, "causa": causa,
            "horas_computables": horas if causa is not None else 0.0,
            "fecha_inicio": pd.Timestamp(f"2026-09-{dia:02d} 10:00", tz=TZ_AR),
            "fecha_cierre": pd.Timestamp(f"2026-09-{dia:02d} 20:00", tz=TZ_AR)}


def _servicios(acum):
    tot = acum.groupby("clave_servicio").agg(horas_computables=("horas_computables", "sum"),
                                             presupuesto_h=("presupuesto_h", "first")).reset_index()
    tot["servicio_id"] = tot["clave_servicio"]
    tot["nombre_cliente"] = "C"
    tot["estado"] = [m.estado_presupuesto(c, p) for c, p in zip(tot["horas_computables"], tot["presupuesto_h"])]
    return tot


def _ev(filas):
    acum = acumulados(pd.DataFrame(filas))
    return acum, impacto(acum, _servicios(acum), "numero_evento").set_index(["numero_evento", "clave_servicio"])


def test_orden_desempata_por_numero_de_reclamo_numerico():
    acum = acumulados(pd.DataFrame([_c("10", 1), _c("9", 1)]))
    assert list(acum["numero_reclamo"]) == ["9", "10"]
    assert list(acum["consumo_acum_despues"]) == [1.0, 2.0]


def test_acumulado_y_primera_vez():
    acum = acumulados(pd.DataFrame([_c("1", 25, dia=1), _c("2", 2, dia=2), _c("3", 1, dia=3)]))
    f = acum.set_index("numero_reclamo")
    assert f.loc["2", "consumo_acum_antes"] == 25 and f.loc["2", "consumo_acum_despues"] == 27
    assert bool(f.loc["2", "alcanza_primera_vez"]) and bool(f.loc["2", "supera_primera_vez"])
    assert not f.loc["3", "alcanza_primera_vez"] and not f.loc["3", "supera_primera_vez"]
    assert f.loc["3", "excedidas_acum"] == pytest.approx(2.0) and f.loc["3", "restantes_acum"] == 0.0
    assert f.loc["2", "pct_aporte_real"] == pytest.approx(2 / 26 * 100)


def test_evento_27h_suficiente_por_si_solo():
    _, ev = _ev([_c("1", 27, evento="E")])
    fila = ev.loc[("E", "A")]
    assert fila["suficiente_solo"] == "Excede" and bool(fila["cruza_umbral"]) and bool(fila["determinante_al_excluir"])


def test_evento_que_agota_exacto():
    _, ev = _ev([_c("1", 26, evento="E")])
    assert ev.loc[("E", "A"), "suficiente_solo"] == "Agota"


def test_previo_25_mas_evento_2_cruza_y_es_determinante():
    _, ev = _ev([_c("1", 25, dia=1), _c("2", 2, evento="E", dia=2)])
    fila = ev.loc[("E", "A")]
    assert fila["suficiente_solo"] == "No"
    assert bool(fila["cruza_umbral"]) and bool(fila["determinante_al_excluir"])
    assert bool(fila["participa_en_agotado_o_excedido"])


def test_previo_27_mas_evento_2_solo_participa():
    _, ev = _ev([_c("1", 27, dia=1), _c("2", 2, evento="E", dia=2)])
    fila = ev.loc[("E", "A")]
    assert not fila["cruza_umbral"] and not fila["determinante_al_excluir"]
    assert fila["suficiente_solo"] == "No" and bool(fila["participa_en_agotado_o_excedido"])


def test_27_no_fo_mas_evento_fo_de_2_minutos_no_explica_el_agotamiento():
    _, ev = _ev([_c("1", 27, causa=m.CAUSA_CARRIER, dia=1), _c("2", 2 / 60, evento="E", dia=2)])
    fila = ev.loc[("E", "A")]
    assert not fila["cruza_umbral"] and not fila["determinante_al_excluir"] and fila["suficiente_solo"] == "No"


def test_evento_con_horas_cero_o_excluidas_no_tiene_indicadores():
    _, ev = _ev([_c("1", 26, dia=1), _c("2", 5, causa=None, evento="E", dia=2)])
    fila = ev.loc[("E", "A")]
    assert fila["horas_computables"] == 0 and not fila["cruza_umbral"] and not fila["determinante_al_excluir"]


def test_servicio_no_evaluable_sin_indicadores_ni_porcentajes():
    _, ev = _ev([_c("1", 30, evento="E", presupuesto=None)])
    fila = ev.loc[("E", "A")]
    assert fila["suficiente_solo"] == "No evaluable" and pd.isna(fila["pct_aporte_real"])
    assert not fila["cruza_umbral"] and not fila["determinante_al_excluir"]


def test_mismo_evento_en_varias_lineas_del_mismo_servicio_cuenta_un_servicio():
    filas = [_c("1", 10, evento="E", dia=1), _c("2", 10, evento="E", dia=2)]
    filas[1]["servicio_id"] = "A"  # otra línea, mismo servicio unificado (clave A)
    acum, ev = _ev(filas)
    resumen = resumen_eventos(acum, ev.reset_index()).set_index("numero_evento")
    assert resumen.loc["E", "servicios_afectados"] == 1 and resumen.loc["E", "reclamos"] == 2
    assert resumen.loc["E", "horas_servicio"] == pytest.approx(20.0)


def test_reclamos_sin_evento_en_vista_aparte_y_no_son_eventos():
    acum = acumulados(pd.DataFrame([_c("7", 27), _c("8", 1, evento="E", dia=2)]))
    ais = impacto(acum, _servicios(acum), "numero_reclamo")
    assert list(ais["numero_reclamo"]) == ["7"]
    assert ais.iloc[0]["suficiente_solo"] == "Excede"
    assert list(resumen_eventos(acum, impacto(acum, _servicios(acum), "numero_evento"))["numero_evento"]) == ["E"]


def test_inconsistencias():
    acum = acumulados(pd.DataFrame([
        _c("1", 3, causa=m.CAUSA_CARRIER, evento="E1"),
        _c("2", 3, causa=m.CAUSA_FO_GENERAL, evento="E2", clave="B"),
        _c("3", 3, causa=m.CAUSA_OTROS, evento="E2", clave="B", dia=2),
    ]))
    servicios = _servicios(acum)
    servicios.loc[servicios["clave_servicio"] == "B", "estado"] = m.ESTADO_NO_EVALUABLE
    no_vinc = pd.DataFrame([{"numero_reclamo": "9", "numero_evento": None, "numero_linea": "555"}])
    inc = inconsistencias(acum, no_vinc, servicios)
    tipos = inc.groupby("tipo").size().to_dict()
    assert tipos == {INCONS_CARRIER_CON_EVENTO: 1, INCONS_EVENTO_MIXTO: 1, INCONS_NO_VINCULADO: 1,
                     INCONS_NO_EVALUABLE: 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sla_consumo_impacto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.sla_consumo.impacto'`

- [ ] **Step 3: Implement `impacto.py`**

```python
# Nombre de archivo: impacto.py
# Ubicación de archivo: core/sla_consumo/impacto.py
# Descripción: Acumulados por servicio e impacto Evento × Servicio / reclamo sin evento (tres indicadores)

from __future__ import annotations

import numpy as np
import pandas as pd

from core.sla_consumo import metricas as m

INCONS_CARRIER_CON_EVENTO = "Reclamo Carrier con evento"
INCONS_EVENTO_MIXTO = "Evento con causas FO y no FO"
INCONS_NO_VINCULADO = "Reclamo no vinculado a un servicio"
INCONS_NO_EVALUABLE = "Servicio no evaluable (sin presupuesto válido)"

_COL_CAUSA = {m.CAUSA_FO_GENERAL: "horas_fo_general", m.CAUSA_FO_COD3: "horas_fo_cod3",
              m.CAUSA_CARRIER: "horas_carrier", m.CAUSA_OTROS: "horas_otros"}


def _validos(presupuesto: pd.Series) -> pd.Series:
    return presupuesto.map(m.presupuesto_valido).astype(bool)


def acumulados(vinculados: pd.DataFrame) -> pd.DataFrame:
    """Suma las horas completas de cada reclamo en orden fecha_inicio → número de reclamo.

    Es una atribución por orden: no identifica el instante físico en que se rompió el presupuesto.
    """
    df = vinculados.copy()
    df["horas_computables"] = pd.to_numeric(df["horas_computables"], errors="coerce").fillna(0.0)
    df["_orden"] = pd.to_numeric(df["numero_reclamo"], errors="coerce")
    df = df.sort_values(["clave_servicio", "fecha_inicio", "_orden", "numero_reclamo"],
                        kind="mergesort", na_position="last").drop(columns="_orden")
    df["consumo_acum_despues"] = df.groupby("clave_servicio")["horas_computables"].cumsum()
    df["consumo_acum_antes"] = df["consumo_acum_despues"] - df["horas_computables"]
    p = pd.to_numeric(df["presupuesto_h"], errors="coerce")
    valido = _validos(df["presupuesto_h"])
    antes, despues, eps = df["consumo_acum_antes"], df["consumo_acum_despues"], m.EPS_HORAS
    df["restantes_acum"] = np.where(valido, np.maximum(p - despues, 0.0), np.nan)
    df["excedidas_acum"] = np.where(valido, np.maximum(despues - p, 0.0), np.nan)
    df["pct_aporte_real"] = np.where(valido, df["horas_computables"] / p * 100, np.nan)
    df["alcanza_primera_vez"] = valido & (antes < p - eps) & (despues >= p - eps)
    df["supera_primera_vez"] = valido & (antes <= p + eps) & (despues > p + eps)
    return df.reset_index(drop=True)


def _suficiente(horas: float, presupuesto: object) -> str:
    if not m.presupuesto_valido(presupuesto):
        return "No evaluable"
    p = float(presupuesto)
    if horas > p + m.EPS_HORAS:
        return "Excede"
    return "Agota" if abs(horas - p) <= m.EPS_HORAS else "No"


def impacto(acum: pd.DataFrame, servicios: pd.DataFrame, por: str) -> pd.DataFrame:
    if por == "numero_evento":
        sub = acum[acum["numero_evento"].notna()]
    elif por == "numero_reclamo":
        sub = acum[acum["numero_evento"].isna()]
    else:
        raise ValueError(f"por inválido: {por}")
    sub = sub.assign(
        _cruza=sub["alcanza_primera_vez"] | sub["supera_primera_vez"],
        _fo=np.where(sub["causa"].isin(m.CAUSAS_FO), sub["horas_computables"], 0.0),
        _no_fo=np.where(sub["causa"].notna() & ~sub["causa"].isin(m.CAUSAS_FO), sub["horas_computables"], 0.0),
    )
    columnas = [por, "clave_servicio", "servicio_id", "nombre_cliente", "reclamos", "reclamos_ids",
                "horas_computables", "horas_fo", "horas_no_fo", "presupuesto_h", "pct_aporte_real",
                "consumo_total_servicio", "estado_servicio", "suficiente_solo", "cruza_umbral",
                "determinante_al_excluir", "participa_en_agotado_o_excedido"]
    if sub.empty:
        return pd.DataFrame(columns=columnas)
    g = (sub.groupby([por, "clave_servicio"], sort=False)
         .agg(reclamos=("numero_reclamo", "count"),
              reclamos_ids=("numero_reclamo", lambda s: ", ".join(map(str, s))),
              horas_computables=("horas_computables", "sum"), horas_fo=("_fo", "sum"),
              horas_no_fo=("_no_fo", "sum"), cruza_umbral=("_cruza", "any"))
         .reset_index())
    svc = servicios[["clave_servicio", "servicio_id", "nombre_cliente", "presupuesto_h", "horas_computables",
                     "estado"]].rename(columns={"horas_computables": "consumo_total_servicio",
                                                "estado": "estado_servicio"})
    g = g.merge(svc, on="clave_servicio", how="left")
    valido = _validos(g["presupuesto_h"])
    p = pd.to_numeric(g["presupuesto_h"], errors="coerce")
    g["pct_aporte_real"] = np.where(valido, g["horas_computables"] / p * 100, np.nan)
    g["suficiente_solo"] = [_suficiente(h, pr) for h, pr in zip(g["horas_computables"], g["presupuesto_h"])]
    agot = g["estado_servicio"].isin(m.ESTADOS_AGOTADO_O_EXCEDIDO)
    g["participa_en_agotado_o_excedido"] = agot
    g["determinante_al_excluir"] = (agot & valido & (g["horas_computables"] > m.EPS_HORAS)
                                    & ((g["consumo_total_servicio"] - g["horas_computables"]) < p - m.EPS_HORAS))
    g["cruza_umbral"] = g["cruza_umbral"].astype(bool) & valido
    return g[columnas]


def _lista(serie: pd.Series) -> str:
    return ", ".join(sorted(map(str, serie.unique()), key=lambda x: (len(x), x)))


def resumen_eventos(acum: pd.DataFrame, ev_srv: pd.DataFrame) -> pd.DataFrame:
    ev = acum[acum["numero_evento"].notna()]
    if ev.empty:
        return pd.DataFrame(columns=["numero_evento", "inicio_observado", "cierre_observado", "reclamos",
                                     "servicios_afectados", "horas_servicio", *_COL_CAUSA.values(),
                                     "servicios_agotados_o_excedidos", "n_suficiente_solo",
                                     "servicios_suficiente_solo", "n_cruza_umbral", "servicios_cruza_umbral",
                                     "n_determinante", "servicios_determinante"])
    base = ev.groupby("numero_evento").agg(
        inicio_observado=("fecha_inicio", "min"), cierre_observado=("fecha_cierre", "max"),
        reclamos=("numero_reclamo", "count"), servicios_afectados=("clave_servicio", "nunique"),
        horas_servicio=("horas_computables", "sum"))
    causas = (ev[ev["causa"].notna()].pivot_table(index="numero_evento", columns="causa",
                                                   values="horas_computables", aggfunc="sum", fill_value=0.0)
              .reindex(columns=list(_COL_CAUSA), fill_value=0.0).rename(columns=_COL_CAUSA))
    base = base.join(causas).fillna({c: 0.0 for c in _COL_CAUSA.values()})
    es = ev_srv.assign(_suf=ev_srv["suficiente_solo"].isin(["Agota", "Excede"]))
    indic = es.groupby("numero_evento").apply(lambda g: pd.Series({
        "servicios_agotados_o_excedidos": int(g["participa_en_agotado_o_excedido"].sum()),
        "n_suficiente_solo": int(g["_suf"].sum()),
        "servicios_suficiente_solo": _lista(g.loc[g["_suf"], "servicio_id"]),
        "n_cruza_umbral": int(g["cruza_umbral"].sum()),
        "servicios_cruza_umbral": _lista(g.loc[g["cruza_umbral"], "servicio_id"]),
        "n_determinante": int(g["determinante_al_excluir"].sum()),
        "servicios_determinante": _lista(g.loc[g["determinante_al_excluir"], "servicio_id"]),
    }), include_groups=False)
    return base.join(indic).reset_index().sort_values("horas_servicio", ascending=False, kind="mergesort")


def inconsistencias(acum: pd.DataFrame, no_vinculados: pd.DataFrame, servicios: pd.DataFrame) -> pd.DataFrame:
    filas: list[dict] = []
    carrier_ev = acum[(acum["causa"] == m.CAUSA_CARRIER) & acum["numero_evento"].notna()]
    for _, r in carrier_ev.iterrows():
        filas.append({"tipo": INCONS_CARRIER_CON_EVENTO, "numero_evento": r["numero_evento"],
                      "numero_reclamo": r["numero_reclamo"], "servicio_id": r["servicio_id"],
                      "detalle": "La regla de negocio no asocia Carrier a eventos FO: revisar; la causa no se reasigna."})
    con_causa = acum[acum["numero_evento"].notna() & acum["causa"].notna()]
    for evento, g in con_causa.groupby("numero_evento"):
        fo = g["causa"].isin(m.CAUSAS_FO)
        if fo.any() and (~fo).any():
            filas.append({"tipo": INCONS_EVENTO_MIXTO, "numero_evento": evento, "numero_reclamo": None,
                          "servicio_id": None,
                          "detalle": "Causas: " + ", ".join(sorted(g["causa"].unique()))})
    for _, r in no_vinculados.iterrows():
        filas.append({"tipo": INCONS_NO_VINCULADO, "numero_evento": r.get("numero_evento"),
                      "numero_reclamo": r["numero_reclamo"], "servicio_id": None,
                      "detalle": f"Línea {r.get('numero_linea')} / primer servicio {r.get('numero_primer_servicio')} "
                                 "fuera del universo de Servicios: sin presupuesto."})
    for _, s in servicios[servicios["estado"] == m.ESTADO_NO_EVALUABLE].iterrows():
        filas.append({"tipo": INCONS_NO_EVALUABLE, "numero_evento": None, "numero_reclamo": None,
                      "servicio_id": s["servicio_id"], "detalle": "Falta SLA prometido o presupuesto válido."})
    return pd.DataFrame(filas, columns=["tipo", "numero_evento", "numero_reclamo", "servicio_id", "detalle"])
```

Notes:
- pandas 2.2 supports `include_groups=False` in `groupby.apply`; if a FutureWarning appears, keep the call free of warnings.
- `_lista` orders IDs by length and then text, which approximates numeric order for numeric IDs.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sla_consumo_impacto.py -v -W error::FutureWarning`
Expected: PASS, no warnings

- [ ] **Step 5: Commit**

```bash
git add core/sla_consumo/impacto.py tests/test_sla_consumo_impacto.py
git commit -m "feat(sla): acumulados por servicio e impacto Evento × Servicio con tres indicadores"
```

---

### Task 3: Engine sobre el servicio unificado (`engine.py` + `ResultadoSlaConsumo`)

**Files:**
- Modify (rewrite): `core/sla_consumo/engine.py`
- Test: `tests/test_sla_consumo_engine.py` (rewrite)

**Interfaces:**
- Consumes: Tasks 1-2; `clasificador.clasificar_cierre`, `valores_cliente_config`, `GRUPOS_ORDEN`, `GRUPO_CARRIER`, `GRUPO_CLIENTE`.
- Produces:
  - Re-exports `HORAS_ANIO` and `presupuesto_horas`, because `api/app/routes/servicios.py` imports `presupuesto_horas` from `core.sla_consumo.engine` and that must keep working.
  - `@dataclass ResultadoSlaConsumo` with these fields:
    - `fecha_corte: date`
    - `servicios: DataFrame` (complete universe)
    - `servicio_reclamo: DataFrame` (acumulados + `indicador`, `tipo_solucion`, `grupo_cierre`, `codigo_cierre`, `horas_netas`, `cuenta_sla`, `sin_evento`, `fecha_cierre`, `nombre_cliente`)
    - `eventos: DataFrame` (output of `resumen_eventos`)
    - `evento_servicio: DataFrame`
    - `reclamos_sin_evento: DataFrame` (output of `impacto(..., "numero_reclamo")`)
    - `inconsistencias: DataFrame`
    - `no_vinculados: DataFrame`
    - `composicion: DataFrame` (columns `causa, horas, pct`; one row per `CAUSAS_ORDEN`)
    - `codigo_cierre: DataFrame`, `codigo_cierre_detalle: DataFrame`, `carrier_cliente: DataFrame`
    - `totales: dict`
  - `servicios` columns: `clave_servicio, servicio_id, lineas_asociadas, nombre_cliente, tipo_servicio, sla_prometido, presupuesto_h, horas_netas, horas_computables, horas_excluidas, horas_fo, horas_fo_general, horas_fo_cod3, horas_carrier, horas_otros, horas_restantes, horas_excedidas, pct_real, pct_visible, aporte_fo_pct, participacion_fo_pct, reclamos, eventos_reales, reclamos_sin_evento, semaforo, estado, sla_entregado_oficial, horas_reclamos_todos_oficial, horas_restantes_oficial`.
    - Sorted by estado severity (Excedido, Agotado, Dentro, Sin consumo, No evaluable), then by `pct_real` descending.
  - `totales` keys (all JSON-safe Python ints and floats): `servicios_universo, servicios_con_reclamos, servicios_dentro, servicios_agotados, servicios_excedidos, servicios_sin_consumo, servicios_no_evaluables, reclamos, reclamos_vinculados, reclamos_no_vinculados, eventos, reclamos_sin_evento, horas_netas, horas_computables, horas_excluidas, horas_no_vinculadas, horas_fo_general, horas_fo_cod3, horas_carrier, horas_otros, inconsistencias`.
  - `calcular(reclamos: DataFrame, servicios: DataFrame, fecha_corte: date) -> ResultadoSlaConsumo`. Inputs are as returned by `persistencia.cargar_ventana` (columns `RECLAMOS_COLS` / `SERVICIOS_COLS`).

Rules this task must apply:
- **Classification of each claim.**
  - Always re-classify from `tipo_solucion` using `clasificar_cierre` with `valores_cliente_config()`, as today.
  - Map the group to a cause with `causa_de_grupo`.
  - `cuenta_sla = grupo != GRUPO_CLIENTE`.
  - `horas_netas` as float, NaN → 0.
  - `horas_computables = horas_netas if cuenta_sla else 0`; `horas_excluidas = horas_netas if not cuenta_sla else 0`.
  - `indicador = indicador_reclamo(causa, horas_computables)`.
  - `sin_evento = numero_evento is null`.
- **Universe and linking.**
  - Unify with `unificar_servicios(servicios)`. The universe is **every** unified service, including those without claims (estado "Sin consumo", semáforo "Sin color").
  - Link with `vincular_reclamos`.
  - Unlinked claims go only to `no_vinculados`: they are not in any service, not in the pie, and not in Evento × Servicio. They are counted in `totales` (`reclamos_no_vinculados`, `horas_no_vinculadas`).
- **Per-service metrics** (aggregated over linked claims):
  - FO = `horas_fo_general + horas_fo_cod3`.
  - `horas_restantes = max(p − c, 0)` and `horas_excedidas = max(c − p, 0)` when the budget is valid; `None` otherwise.
  - `pct_real = metricas.pct_real`, `pct_visible = metricas.pct_visible`.
  - `aporte_fo_pct = horas_fo / p · 100`.
  - `participacion_fo_pct = horas_fo / horas_computables · 100`, or `None` when there are 0 computable hours.
  - `eventos_reales` = distinct `numero_evento`; `reclamos_sin_evento` = count of claims without an event.
  - `semaforo = semaforo_servicio(horas_fo, horas_carrier + horas_otros)`; `estado = estado_presupuesto(horas_computables, presupuesto_h)`.
- **Composition:** `horas` per cause over linked claims; `pct = horas / Σ horas_computables · 100`, or 0 when the total is 0.
- **Current views kept:** `codigo_cierre`, `codigo_cierre_detalle` and `carrier_cliente` are computed over **all** classified claims, linked or not. Use the same columns as today. In `carrier_cliente`, replace `numero_linea` with `servicio_id` when available.

- [ ] **Step 1: Write the failing test** (it reproduces all the acceptance cases in §11 of the prompt through `calcular`)

```python
# Nombre de archivo: test_sla_consumo_engine.py
# Ubicación de archivo: tests/test_sla_consumo_engine.py
# Descripción: Casos de aceptación del informe SLA consumido sobre el servicio unificado

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core.sla_consumo import metricas as m
from core.sla_consumo.engine import calcular, presupuesto_horas
from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS
from core.utils.excel_duraciones import TZ_AR

SLA_26 = 100 * (1 - 26 / 8760)
FO, COD3, CARRIER, OTROS = "PE-I-FO Corte/Aten Troncal Can/Subt (7)", "PE-E-FO Corte en Bandeja (3)", "Carrier", "IN - Falla Equipo CPE"


def _s(linea, sla=SLA_26, primer=None, cliente="CLIENTE"):
    fila = {c: None for c in SERVICIOS_COLS}
    fila.update(numero_linea=linea, numero_primer_servicio=primer or linea, sla_prometido=sla, nombre_cliente=cliente)
    return fila


def _r(numero, linea, horas, tipo=FO, evento=None, dia=1, primer=None):
    fila = {c: None for c in RECLAMOS_COLS}
    fila.update(numero_reclamo=numero, numero_linea=linea, numero_primer_servicio=primer or linea,
                horas_netas=horas, tipo_solucion=tipo, numero_evento=evento, nombre_cliente="CLIENTE",
                fecha_inicio=pd.Timestamp(f"2026-09-{dia:02d} 10:00", tz=TZ_AR),
                fecha_cierre=pd.Timestamp(f"2026-09-{dia:02d} 20:00", tz=TZ_AR))
    return fila


def _calc(servicios, reclamos, monkeypatch=None):
    return calcular(pd.DataFrame(reclamos, columns=RECLAMOS_COLS), pd.DataFrame(servicios, columns=SERVICIOS_COLS),
                    dt.date(2026, 10, 1))


def _svc(res, sid):
    return res.servicios.set_index("servicio_id").loc[sid]


def test_reexporta_presupuesto():
    assert presupuesto_horas(99.7) == pytest.approx(26.28)


@pytest.mark.parametrize("reclamos, semaforo, estado", [
    ([("1", 4, FO)], m.ROJO, m.ESTADO_DENTRO),
    ([("1", 4, FO), ("2", 1, CARRIER)], m.AMARILLO, m.ESTADO_DENTRO),
    ([("1", 4, OTROS)], m.VERDE, m.ESTADO_DENTRO),
    ([("1", 0, FO)], m.SIN_COLOR, m.ESTADO_SIN_CONSUMO),
    ([("1", 26, FO)], m.ROJO, m.ESTADO_AGOTADO),
    ([("1", 27, FO), ("2", 1, CARRIER)], m.AMARILLO, m.ESTADO_EXCEDIDO),
])
def test_semaforo_y_estado(reclamos, semaforo, estado):
    res = _calc([_s("100")], [_r(n, "100", h, t, dia=i + 1) for i, (n, h, t) in enumerate(reclamos)])
    fila = _svc(res, "100")
    assert (fila["semaforo"], fila["estado"]) == (semaforo, estado)


def test_27_fo_mas_1_carrier_visible_100_y_2h_excedidas():
    fila = _svc(_calc([_s("100")], [_r("1", "100", 27, FO), _r("2", "100", 1, CARRIER, dia=2)]), "100")
    assert fila["pct_real"] == pytest.approx(28 / 26 * 100)
    assert fila["pct_visible"] == 100.0 and fila["horas_excedidas"] == pytest.approx(2.0)
    assert fila["horas_restantes"] == 0.0
    assert fila["horas_fo"] == 27 and fila["horas_carrier"] == 1
    assert fila["aporte_fo_pct"] == pytest.approx(27 / 26 * 100)
    assert fila["participacion_fo_pct"] == pytest.approx(27 / 28 * 100)


def test_fo_cod3_cuenta_como_fo_y_se_separa():
    fila = _svc(_calc([_s("100")], [_r("1", "100", 2, COD3), _r("2", "100", 3, FO, dia=2)]), "100")
    assert (fila["horas_fo_cod3"], fila["horas_fo_general"], fila["horas_fo"]) == (2, 3, 5)
    assert fila["semaforo"] == m.ROJO


def test_reclamo_fo_sin_evento_rojo_y_no_suma_eventos():
    res = _calc([_s("100")], [_r("1", "100", 4, FO)])
    rec = res.servicio_reclamo.iloc[0]
    assert rec["indicador"] == m.ROJO and bool(rec["sin_evento"])
    assert res.totales["eventos"] == 0 and res.totales["reclamos_sin_evento"] == 1
    assert _svc(res, "100")["horas_fo"] == 4


def test_reclamo_excluido_o_cero_no_altera_semaforo(monkeypatch):
    monkeypatch.setenv("SLA_CIERRE_CLIENTE_VALORES", "Cierre por cliente")
    res = _calc([_s("100")], [_r("1", "100", 4, CARRIER), _r("2", "100", 9, "Cierre por cliente", dia=2),
                              _r("3", "100", 0, FO, dia=3)])
    fila = _svc(res, "100")
    assert fila["semaforo"] == m.VERDE and fila["horas_excluidas"] == 9 and fila["horas_computables"] == 4
    ind = dict(zip(res.servicio_reclamo["numero_reclamo"], res.servicio_reclamo["indicador"]))
    assert ind == {"1": m.VERDE, "2": m.SIN_COLOR, "3": m.SIN_COLOR}


def test_primer_servicio_con_lineas_9_y_10_una_ficha():
    res = _calc([_s("9", 99.0, primer="A"), _s("10", SLA_26, primer="A")],
                [_r("1", "9", 3, FO, primer="A"), _r("2", "10", 4, CARRIER, dia=2, primer="A")])
    assert list(res.servicios["servicio_id"]) == ["10"]
    fila = _svc(res, "10")
    assert fila["reclamos"] == 2 and fila["presupuesto_h"] == pytest.approx(26.0)
    assert fila["lineas_asociadas"] == "9, 10" and fila["semaforo"] == m.AMARILLO
    assert set(res.servicio_reclamo["servicio_id"]) == {"10"}


def test_servicio_sin_reclamos_incluido_y_no_evaluable_sin_porcentajes():
    res = _calc([_s("100"), _s("200"), _s("300", sla=None)], [_r("1", "300", 5, FO)])
    assert set(res.servicios["servicio_id"]) == {"100", "200", "300"}
    assert _svc(res, "200")["estado"] == m.ESTADO_SIN_CONSUMO and _svc(res, "200")["semaforo"] == m.SIN_COLOR
    ne = _svc(res, "300")
    assert ne["estado"] == m.ESTADO_NO_EVALUABLE and pd.isna(ne["pct_real"]) and pd.isna(ne["horas_excedidas"])
    assert res.totales["servicios_universo"] == 3 and res.totales["servicios_no_evaluables"] == 1


def test_reclamo_no_vinculado_aparte():
    res = _calc([_s("100")], [_r("1", "100", 2, FO), _r("2", "999", 5, FO)])
    assert list(res.no_vinculados["numero_reclamo"]) == ["2"]
    assert res.totales["reclamos_no_vinculados"] == 1 and res.totales["horas_no_vinculadas"] == 5
    assert res.composicion.set_index("causa").loc[m.CAUSA_FO_GENERAL, "horas"] == 2
    assert "2" not in set(res.servicio_reclamo["numero_reclamo"])


def test_evento_en_dos_lineas_mismo_servicio_y_indicadores():
    res = _calc([_s("9", primer="A"), _s("10", primer="A")],
                [_r("1", "9", 25, FO, primer="A"), _r("2", "10", 2, FO, evento="E", dia=2, primer="A"),
                 _r("3", "9", 0.5, FO, evento="E", dia=3, primer="A")])
    ev = res.eventos.set_index("numero_evento").loc["E"]
    assert ev["servicios_afectados"] == 1 and ev["n_cruza_umbral"] == 1 and ev["n_determinante"] == 1
    es = res.evento_servicio.iloc[0]
    assert es["servicio_id"] == "10" and es["horas_computables"] == pytest.approx(2.5)


def test_composicion_global():
    res = _calc([_s("100"), _s("200")], [_r("1", "100", 3, FO), _r("2", "100", 1, COD3, dia=2),
                                          _r("3", "200", 4, CARRIER), _r("4", "200", 2, OTROS, dia=2)])
    comp = res.composicion.set_index("causa")
    assert comp["horas"].sum() == pytest.approx(10) and comp["pct"].sum() == pytest.approx(100)
    assert comp.loc[m.CAUSA_FO_COD3, "pct"] == pytest.approx(10)


def test_totales_json_safe():
    res = _calc([_s("100")], [_r("1", "100", 4, FO)])
    for valor in res.totales.values():
        assert type(valor) in (int, float)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sla_consumo_engine.py -v`
Expected: FAIL. The old engine has no `semaforo`, `estado` or `servicio_id` columns.

- [ ] **Step 3: Rewrite `engine.py`**

Implement with these helper functions, keeping each one short:

- `_clasificar(reclamos) -> DataFrame` applies the classification rules above.
- `_metricas_servicios(unificados, acum) -> DataFrame` adds the per-service columns. Use `groupby("clave_servicio")` over `acum` with `causa` pivoted to `horas_fo_general/horas_fo_cod3/horas_carrier/horas_otros`. Left-join onto `unificados` so the services without claims stay, filling 0 for hours and counts. Then compute the derived columns with the `metricas` functions; a row-wise list comprehension is fine, since 7228 rows is cheap.
- `_composicion(acum)`, `_codigo_cierre(clasificados)`, `_carrier_cliente(clasificados)`. Port the current logic of `codigo_cierre`, `detalle` and `carrier` from the old `calcular`.
- `calcular` wires everything together:
  1. `clasificados = _clasificar(reclamos)`.
  2. `uni = unificar_servicios(servicios)`.
  3. `vinc, no_vinc = vincular_reclamos(clasificados, uni)`.
  4. `acum = acumulados(vinc)`.
  5. Build `svc`.
  6. `ev_srv = impacto(acum, svc, "numero_evento")`.
  7. `sin_ev = impacto(acum, svc, "numero_reclamo")`.
  8. `eventos = resumen_eventos(acum, ev_srv)`.
  9. `inc = inconsistencias(acum, no_vinc, svc)`.
  10. Composition, current views and `totales`, casting every value with `int()`/`float()`.

  `servicio_reclamo` is `acum` with `nombre_cliente` taken from the service.

Remove `_col_grupo`, `pp_disponibilidad`, `sla_calculado`, `diferencia_horas_oficial` and the old `hechos` field. They have no consumers outside the builders, which Tasks 4-5 rewrite. Run `grep -rn "hechos\|pp_disponibilidad\|sla_calculado" core api web tests` to confirm, and adapt any other caller.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sla_consumo_engine.py tests/test_sla_consumo_impacto.py tests/test_sla_consumo_metricas.py tests/test_sla_consumo_identidad.py -v -W error::FutureWarning`
Expected: PASS

The old builders' tests (`tests/test_sla_consumo_builders.py`) will break here. That is expected, because Tasks 4-5 rewrite them. Mark that test module with `pytest.skip("reescrito en Task 4-5", allow_module_level=True)` in this commit so the suite stays green, and say so in the report.

- [ ] **Step 5: Smoke against the real files (nothing is committed)**

```bash
python - <<'EOF'
import datetime as dt, time
from pathlib import Path
from core.sla_consumo.parser import parse_reclamos, parse_servicios
from core.sla_consumo.engine import calcular
b = Path("/home/support-focal-01/LAS-FOCAS/docs/Doc Privada")
r = parse_reclamos((b / "Reclamos_Nuevo SLA.xlsx").read_bytes()); s = parse_servicios((b / "Servicios_ Nuevo SLA.xlsx").read_bytes())
t = time.time(); res = calcular(r, s, dt.date(2026, 10, 2)); print("seg", round(time.time() - t, 1))
print(res.totales)
print(res.servicios["estado"].value_counts().to_dict(), res.servicios["semaforo"].value_counts().to_dict())
print(len(res.eventos), len(res.evento_servicio), len(res.reclamos_sin_evento), res.inconsistencias["tipo"].value_counts().to_dict())
EOF
```
Expected:
- `servicios_universo` 7228, `reclamos` 4517, `reclamos_no_vinculados` 0, `eventos` 402.
- About 420 services in Agotado + Excedido.
- Inconsistencies include 66 "Reclamo Carrier con evento".
- Under 30 seconds.

- [ ] **Step 6: Commit**

```bash
git add core/sla_consumo/engine.py tests/test_sla_consumo_engine.py tests/test_sla_consumo_builders.py
git commit -m "feat(sla): engine sobre servicio unificado con semáforos, estados, acumulados e impacto de eventos"
```

---

### Task 4: Presentación compartida, gráficos y XLSX completo

**Files:**
- Create: `core/sla_consumo/presentacion.py`
- Modify (rewrite): `core/sla_consumo/charts.py`, `core/sla_consumo/xlsx_builder.py`
- Test: `tests/test_sla_consumo_builders.py`. Rewrite the XLSX and chart parts and remove the module-level skip.

**Interfaces:**
- Consumes: `ResultadoSlaConsumo` (Task 3) and the constants in `metricas`.
- Produces:
  - **`presentacion.py`:**
    - `COLUMNAS: dict[str, tuple[str, str]]`, mapping column name to `(label in Spanish, format)`. The format is one of `"texto"`, `"entero"`, `"horas"`, `"pct"`, `"fecha"`, `"bool"`. It must cover every column exported by Tasks 4-5.
    - `COLORES_SEMAFORO: dict[str, str]` (hex without `#`): Rojo `C0392B`, Amarillo `F1C40F`, Verde `27AE60`, Sin color = None.
    - `COLORES_ESTADO`: SLA excedido `C0392B`, Presupuesto agotado `E67E22`, Dentro de SLA `27AE60`, Sin consumo `BDC3C7`, No evaluable `7F8C8D`.
    - `COLORES_CAUSA`: FO general `C0392B`, FO Cod 3 `E67E22`, Carrier `2980B9`, Otros `7F8C8D`.
    - `LEYENDAS: list[tuple[str, str]]`, pairs of `(concept, explanation)`, in the spec's own words:
      - service semáforo and claim indicator;
      - "verde no significa cumplimiento";
      - the budget states;
      - the three indicators plus "participación ≠ causa";
      - "acumulado = atribución por orden, no instante físico";
      - "horas-servicio ≠ duración del evento";
      - "rango observado ≠ duración oficial";
      - tolerance `EPS_HORAS`;
      - "% visible ≤ 100 con horas excedidas; aporte por reclamo/evento en % real".
    - `fmt_horas(h) -> str`: `"HHH:MM"`, or `"—"` for None/NaN/inf.
    - `fmt_pct(p) -> str`: `"12,34 %"`, or `"—"`.
    - `fmt_fecha(ts) -> str`: `"dd/mm/aaaa hh:mm"` in AR time, or `"—"`.
    - `fmt_bool(b) -> str`: `"Sí"` / `"No"`.
  - **`charts.py`:**
    - `torta_causas(res, destino: Path) -> Path | None`. Returns `None` when total computable hours are ≤ `EPS_HORAS`. Labels show hours (`fmt_horas`) and %, the legend is clear, and the caption mentions excluded and unlinked hours.
    - `magnitud_eventos(res, destino: Path, top: int) -> Path | None`. Horizontal bars of hours-service for the top N events, with a text annotation per event: `"<servicios_afectados> servicios · suficiente <n> · cruza <n> · determinante <n>"`. Returns `None` when there are no events.
    - Remove `pareto_eventos`, `top_servicios`, `horas_por_grupo` and `servicio` once `grep` confirms nothing else uses them.
  - **`xlsx_builder.py`:**
    - `HOJAS = ("Resumen y leyendas", "Servicios", "Servicio x Reclamo", "Eventos", "Evento x Servicio", "Reclamos sin evento", "Inconsistencias", "No vinculados", "Codigo de cierre", "Detalle tipo solucion", "Carrier x Cliente")`.
    - `construir_xlsx(res, destino: Path) -> Path`.

XLSX requirements:
- **Every sheet:**
  - Headers from `COLUMNAS`, bold, with fill.
  - `ws.auto_filter.ref = ws.dimensions`, `freeze_panes = "B2"` (or `"A2"` on summary sheets).
  - Width per column capped at 50.
  - **All rows** written; never truncate.
- **Cell formats:**
  - **"horas":** store `h / 24` with `number_format = "[h]:mm"`. Precision is kept: the cell holds the exact value.
  - **"pct":** store `p / 100` with `"0.00%"`.
  - **"fecha":** naive AR datetime with `"dd/mm/yyyy hh:mm"`.
  - **"bool":** "Sí"/"No".
  - **NaN/inf:** empty cell.
- **Conditional formatting:** apply `FormulaRule` per text value of the `semaforo`, `indicador`, `estado`, `estado_servicio` and `suficiente_solo` columns, using the fill colors from `presentacion`. Not static per-cell fills.
- **Writing:** use `openpyxl` directly (write-only mode is not compatible with conditional formatting, so use a normal workbook). Write rows with `ws.append` for speed.
- **"Resumen y leyendas" sheet:**
  - Cut-off date and 365-day window.
  - `totales` as label → value.
  - Composition by cause (hours + %).
  - Then the `LEYENDAS` table.

- [ ] **Step 1: Write failing tests** in `tests/test_sla_consumo_builders.py`. Build a small `ResultadoSlaConsumo` through `calcular` with the fixture helpers in Task 3's style (import `_s`, `_r`, `_calc` from `tests.test_sla_consumo_engine`). Cover:
  1. `construir_xlsx` writes exactly the `HOJAS` sheets, and the number of data rows on "Servicios" / "Servicio x Reclamo" / "Evento x Servicio" equals `len()` of the matching frame.
  2. A "horas" cell holds `27/24` with `number_format == "[h]:mm"`; a "pct" cell holds `pct_real/100` with `"0.00%"`.
  3. The "Servicios" sheet has `conditional_formatting` with at least one rule per semáforo color.
  4. The "No evaluable" service has empty cells for its percentages (None), never `inf`.
  5. `auto_filter.ref` and `freeze_panes` are set on every sheet.
  6. `torta_causas` returns a PNG (`b"\x89PNG"` header) when there is consumption and `None` when there is none.
  7. `magnitud_eventos` returns a PNG, or `None` without events.
  8. `fmt_horas(27.5) == "27:30"`, `fmt_horas(None) == "—"`, `fmt_pct(float("inf")) == "—"`.

- [ ] **Step 2: Run** `pytest tests/test_sla_consumo_builders.py -v`. Expected: FAIL (`ImportError: presentacion`).

- [ ] **Step 3: Implement** `presentacion.py`, `charts.py` and `xlsx_builder.py` per the requirements above. No calculations: every value comes from `res`.

- [ ] **Step 4: Run** `pytest tests/test_sla_consumo_builders.py -v`. Expected: PASS. Silence only openpyxl's own `utcnow` warnings with `pytest.mark.filterwarnings`.

- [ ] **Step 5: Real smoke** (no commit). Parse the real files, call `calcular`, then `construir_xlsx` and `torta_causas` into the scratchpad `/tmp/claude-1001/-home-support-focal-01-LAS-FOCAS/e57b2de2-1f79-438d-acc6-a5837f518051/scratchpad/`. Report time and size, and open the file with `openpyxl` to check the row counts (7228 services, 4517 claims).

- [ ] **Step 6: Commit**

```bash
git add core/sla_consumo/presentacion.py core/sla_consumo/charts.py core/sla_consumo/xlsx_builder.py tests/test_sla_consumo_builders.py
git commit -m "feat(sla): XLSX completo con formatos y colores, torta global de causas y magnitud de eventos"
```

---

### Task 5: DOCX ejecutivo y exhaustivo

**Files:**
- Modify (rewrite): `core/sla_consumo/docx_builder.py`
- Test: `tests/test_sla_consumo_docx.py` (new)

**Interfaces:**
- Consumes: `ResultadoSlaConsumo` (Task 3), `presentacion` and `charts` (Task 4).
- Produces:
  - `TOP_EVENTOS_DEFAULT = 20`; `top_eventos_config() -> int` reads env `SLA_CONSUMO_TOP_EVENTOS` (positive int, otherwise the default).
  - `construir_docx_ejecutivo(res, destino: Path, top_eventos: int | None = None) -> Path`
  - `construir_docx_exhaustivo(res, destino: Path) -> Path`
  - `construir_docx` is removed; Task 6 adapts its caller.

**Shared requirements:**
- **Page and styles:**
  - A4 landscape with narrow margins, so wide tables fit.
  - Table style "Table Grid" or "Light Grid Accent 1".
  - **The header row repeats on every page**: set `w:tblHeader` on the first row's `trPr`.
- **Formatting and colors:**
  - Hours, percentages and dates always go through `presentacion.fmt_*`.
  - The semáforo, indicator and estado cells are shaded with the `presentacion` colors **and** show the text (e.g. "Rojo").
  - A legend section is built from `LEYENDAS`.
- **Charts:** they go in a `<stem>_graficos` folder next to the DOCX.
- **Speed:** the exhaustive document carries about 4517 claim rows and 4860 compact rows. Build each table with all its rows up front (`doc.add_table(rows=n+1, cols=k)`), then set `cell.text` through `table.rows[i].cells`; avoid `add_row` in loops if it is slow. Measure with the real data: the target is < 90 s per document.
- **Shared service sheet (`_ficha_servicio(doc, res, fila_servicio)`)**, used by both documents:
  - Header: `"<servicio_id> — <nombre_cliente>"`, plus associated lines when there is more than one.
  - Metrics table: SLA prometido, presupuesto, computable hours, excluded hours, FO general / FO Cod 3 / Carrier / Otros, % visible + exceeded hours, real %, remaining hours, FO contribution, FO share, claims / real events / claims without an event, semáforo (colored) and estado (colored).
  - Claims table ordered as in `servicio_reclamo`, with columns:
    - Reclamo
    - Evento (or "Sin evento")
    - Inicio
    - Cierre
    - Tipo solución
    - Grupo / código
    - Indicador (colored)
    - Horas netas
    - ¿Cuenta?
    - Horas computables
    - % aporte real
    - Acum. antes
    - Acum. después
    - Restantes acum.
    - Excedidas acum.
    - Alcanza/Supera 1ª vez
  - Table of that service's events (`evento_servicio` filtered), with: horas aportadas, % aporte real, suficiente solo, cruza umbral, determinante, participa.
  - **No pie chart per service** (user decision).

**Executive DOCX:**
1. Title, cut-off date, 365-day window, generation date.
2. Global summary (`totales` table).
3. Legends.
4. Global pie of causes (or "Sin consumo"), plus a line with excluded hours and unlinked hours.
5. "Eventos principales":
   - an explicit criterion line: "Ranking por horas-servicio de impacto, descendente; se muestran los primeros N (configurable con SLA_CONSUMO_TOP_EVENTOS)";
   - the `magnitud_eventos` chart;
   - a table of the top N with: evento, rango observado, reclamos, servicios afectados, horas-servicio, agotados/excedidos al cierre, the n for each of the 3 indicators and their service lists, cause breakdown.
   - A note that horas-servicio is not the duration of the event and must not be compared against a single budget.
6. "Servicios agotados o excedidos": a complete sheet for **every** service whose `estado` is in `ESTADOS_AGOTADO_O_EXCEDIDO` (≈420 in real data), ordered as `res.servicios`.

**Exhaustive DOCX:**
1. Same header, summary, legends and global pie.
2. **All** events (full table).
3. Sheets for **all** services with ≥ 1 linked claim (≈2368).
4. "Servicios sin reclamos": a compact table (servicio_id, cliente, tipo, SLA prometido, presupuesto, estado) with every service whose `reclamos == 0`.
5. Claims without an event, with their indicators (`reclamos_sin_evento`).
6. Inconsistencies and unlinked claims.

- [ ] **Step 1: Write failing tests** `tests/test_sla_consumo_docx.py`, with fixtures through `calcular` (reuse the helpers from `tests.test_sla_consumo_engine`). Cover:
  1. The executive document contains one sheet per exhausted/exceeded service and none for in-SLA services: count the level-2 headings with the "servicio_id — cliente" text.
  2. The exhaustive document contains sheets for every service with claims, and the compact table lists the services without claims.
  3. The first row of every table has `w:tblHeader`.
  4. A semáforo cell's text is "Amarillo" and it has shading (`w:shd` fill `F1C40F`).
  5. `top_eventos_config()` honors `SLA_CONSUMO_TOP_EVENTOS=3` and falls back to 20 for invalid values; the executive document shows at most N event rows.
  6. With no consumption, the global pie is replaced by the text "Sin consumo".
  7. No cell contains "inf" or "nan".

- [ ] **Step 2: Run, expect FAIL** (`ImportError: construir_docx_ejecutivo`).

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Real smoke and visual inspection** (no commit):
  - Generate both DOCX from the real files into the scratchpad. Report time, size and page count (the `docProps/app.xml` `Pages` value is not reliable; instead convert with the office container: `docker exec lasfocasdev-office soffice --headless --convert-to pdf ...`, or use the existing `modules/common/libreoffice_export.convert_to_pdf` path if a local `soffice` exists).
  - Render pages 1-3 and the sheet of a service with 15 claims to PNG (`pdftoppm -r 60 -f N -l N`), then read them with the Read tool to check legibility.
  - If `soffice`/`pdftoppm` are not available, report it and inspect the XML structure instead.

- [ ] **Step 6: Commit**

```bash
git add core/sla_consumo/docx_builder.py tests/test_sla_consumo_docx.py
git commit -m "feat(sla): DOCX ejecutivo (agotados/excedidos y eventos principales) y DOCX exhaustivo del universo"
```

---

### Task 6: Orquestador, endpoint y panel web

**Files:**
- Modify: `core/services/sla_consumo.py`, `web/app/main.py` (endpoint `generar_informe_sla_consumo_web`), `web/frontend/src/composables/useSlaConsumo.ts`, `web/frontend/src/components/sla/SlaConsumoPanel.vue`
- Test: `tests/test_web_sla_consumo.py`

**Interfaces:**
- **`InformeSlaConsumo` dataclass:** `xlsx: Path`, `docx_ejecutivo: Path`, `docx_exhaustivo: Path`, `pdf_ejecutivo: Path | None`, `pdf_exhaustivo: Path | None`, `ingesta: ResultadoIngesta`, `totales: dict`, `pdf_omitido: str | None = None`.
- **File names** in `reports/sla_consumo/AAAAMM/`:
  - `SLA_consumido_<corte>_<sello>.xlsx`
  - `SLA_consumido_<corte>_<sello>_ejecutivo.docx`
  - `SLA_consumido_<corte>_<sello>_exhaustivo.docx`
  - the matching `.pdf` files.
- **PDF:**
  - Only when `incluir_pdf` and `SOFFICE_BIN` are set.
  - Convert both DOCX files. If the exhaustive conversion fails or exceeds the time limit, keep the executive PDF and set `pdf_omitido` to explain which one failed; never return a 500 after a successful ingest.
- **Web response:** `report_paths` keys are `xlsx`, `docx_ejecutivo`, `docx_exhaustivo`, plus `pdf_ejecutivo` and `pdf_exhaustivo` when present. The rest of the contract (`ok`, `fecha_corte`, `ya_ingestado`, counts, `totales`, `pdf_omitido`) stays the same.
- **Vue (`useSlaConsumo.ts`):** update the `report_paths` and `totales` types to the new keys from Task 3.
- **Vue (`SlaConsumoPanel.vue`):**
  - Labeled links: "Excel completo (XLSX)", "Word ejecutivo (DOCX)", "Word exhaustivo (DOCX)", "PDF ejecutivo", "PDF exhaustivo".
  - Summary cards from the new `totales`: servicios del universo, con reclamos, agotados, excedidos, no evaluables, reclamos, eventos (+ sin evento), horas computables.
  - Colors only through the existing tokens. No dashboard.

- [ ] **Step 1: Failing tests.**
  - Update `tests/test_web_sla_consumo.py`: the mocked orchestrator returns the new dataclass, and the response carries the 3 links (and the 2 PDFs when they exist).
  - Add an orchestrator test (with `ingerir`/`cargar_ventana` monkeypatched and synthetic frames) asserting that both DOCX and the XLSX exist on disk with the expected names.
  - Add a PDF test using a fake `convert_to_pdf` that fails only for the exhaustive document: the executive PDF is returned and `pdf_omitido` is set.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_web_sla_consumo.py tests/test_web_sla_flow.py tests/test_sla_consumo_*.py -q`, plus the dev real-db env. Expected: PASS.
- [ ] **Step 5: Frontend.**
  - `ln -sfn /home/support-focal-01/LAS-FOCAS/web/frontend/node_modules web/frontend/node_modules` (gitignored; do not commit it).
  - `cd web/frontend && npx vue-tsc --noEmit 2>&1 | grep -v InfraTab` (4 errors in `InfraTab.vue` already exist) and `npm run build`.
  - Grep the changed `.vue` files for hex/rgba colors.
- [ ] **Step 6: Commit**

```bash
git add core/services/sla_consumo.py web/app/main.py web/frontend/src tests/test_web_sla_consumo.py
git commit -m "feat(sla): el informe entrega XLSX, DOCX ejecutivo y DOCX exhaustivo con enlaces diferenciados"
```

---

### Task 7: Documentation, real end-to-end run and full suite

**Files:**
- Modify: `docs/informes/sla_consumo.md`, `docs/decisiones.md`, `docs/PR/2026-10-05.md`, and `deploy/env.sample` / `deploy/env.dev.sample` (to document `SLA_CONSUMO_TOP_EVENTOS`)

- [ ] **Step 1: Documentation.** Rewrite `docs/informes/sla_consumo.md` with the final rules:
  - unified service and visible ID;
  - causes, semáforo, indicator and states, with `EPS_HORAS`;
  - service metrics;
  - cumulative ordering and its limits;
  - the 3 event indicators and "participación ≠ causa";
  - horas-servicio and observed range;
  - the global pie;
  - the three outputs and their contents;
  - `SLA_CONSUMO_TOP_EVENTOS`;
  - unlinked claims and inconsistencies;
  - limitations;
  - real figures from the dev run.

  Add an entry in `docs/decisiones.md` with the user's decisions of 2026-10-05: line ID shown, original line not shown, single pie, compact table, same request. Append a section to the daily PR doc.
- [ ] **Step 2: Real in-process E2E against dev.** Run `generar_informe_sla_consumo` on the real files with `incluir_pdf=False`, into the scratchpad. The same pair is already ingested, so it should return `ya_ingestado=True`. Then:
  - confirm that `app.reclamos` (4517) and `app.servicio_sla_snapshot` (7228 for 2026-10-02) do not change (idempotency);
  - time the run;
  - open the XLSX and check the row counts per sheet;
  - render both DOCX to PDF using the office container, and inspect pages of the executive document (summary, pie, events, one sheet) and of the exhaustive one (a service with 15 claims, and the compact table).
- [ ] **Step 3: Full suite.**
  - `pytest -q` with the dev env exported. Report the counts and classify any failures as from this branch or pre-existing/environment.
  - `vue-tsc` / `npm run build`.
- [ ] **Step 4: Commit the docs.**

```bash
git add docs deploy/env.sample deploy/env.dev.sample
git commit -m "docs(sla): reglas finales del SLA consumido ampliado, decisiones y PR diario"
```
