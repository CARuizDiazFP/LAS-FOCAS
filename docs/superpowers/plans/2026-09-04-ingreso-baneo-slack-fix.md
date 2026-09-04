# Fix flujo Ingreso/Baneo vía Slack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cuando un técnico intenta ingresar (vía Slack) a una Cámara/Botella baneada — directamente o por herencia de una Botella hermana — el sistema debe registrar un **Intento bloqueado** (no un Ingreso "en curso"), resolver el nombre real del técnico (no el ID crudo de Slack), etiquetar correctamente la Botella cuando no se especifica ("Botella 1"), y calcular el estado de baneo del badge **una sola vez, en el backend**, consistente en Slack y en el frontend.

**Architecture:** Todo el cálculo de "¿está baneado este grupo (Cámara + Botellas hermanas)?" se centraliza en `core/services/camara_estado_service.get_camara_estado_contexto()` — hoy ya existe y ya lo consume el frontend, pero tiene un bug real (sólo mira `IncidenteBaneo`, nunca baneo manual) que lo hace devolver falsos negativos; se corrige ahí, no se duplica. El listener de Slack (`modules/slack_baneo_notifier/listener.py`) deja de tener su propia lógica de acceso paralela y pasa a reusar esa misma función — así Slack y el badge web quedan estructuralmente forzados a coincidir. Se agrega una columna `Ingreso.tipo` (INGRESO/EGRESO/INTENTO_BLOQUEADO) para distinguir un intento bloqueado de un ingreso real con el mismo `fecha_fin IS NULL`, y un resolver nuevo (`slack_user_resolver.py`) que llama `users.info` de Slack para obtener el nombre real del técnico antes de persistir.

**Tech Stack:** FastAPI (async, `web/app/main.py`), SQLAlchemy ORM síncrono (`core/services/*`, `modules/slack_baneo_notifier/*` usan `Session` síncrona, no `AsyncSession`), Alembic, `slack_bolt`/`slack_sdk` (Socket Mode), pytest (`unittest.TestCase` en tests del listener, funciones planas en tests de servicios), Vue 3 + `<script setup lang="ts">`.

**Spec:** Ticket del usuario (sin archivo — pegado en la conversación): 4 bugs reportados (Ingreso no bloqueado en DB pese a bloquearse en Slack; ID crudo de Slack como técnico; sin fallback "Botella 1"; badge de baneo no hereda de Botellas) + 6 pasos propuestos. **Corrección de premisas verificada contra el código real (no asumida) antes de este plan:**
- El endpoint `/api/infra/camaras/{id}` **ya** devuelve `tiene_baneo_activo` (no hace falta un campo `has_active_ban` nuevo) y `ModalRegistros.vue`/`CamaraEstadoModal.vue`/`BaneosActivosPanel.vue` **ya** sólo renderizan ese valor del backend, sin cálculo local. El bug real es que `get_camara_estado_contexto()` sólo mira `IncidenteBaneo`, nunca `Camara.estado == BANEADA` — un baneo manual (override admin, sin incidente de protección asociado) queda invisible tanto para Slack como para el badge. Se corrige esa función (Task 3), no se agrega un campo duplicado.
- `core/parsers/tracking_parser.py` es un parser de archivos `.txt` de tracking, no tiene nada que ver con Slack — el parser real de comandos de Slack es `modules/slack_baneo_notifier/camara_search.py`.
- No existe una entidad "Botella 1" en `CromoBotella` — por convención ya codificada (`detectar_multi_bot`), "Botella 1" ES la Cámara raíz misma. El fallback es una corrección de **etiqueta** (`botella_label`), no una FK nueva.

## Global Constraints

- Nunca commitear/pushear parado en `dev`/`main` — rama efímera obligatoria (ya activa: `fix/ingresos-slack-baneo-flujo`).
- Todas las migraciones Alembic deben implementar `downgrade()` reversible.
- Nunca usar `docker compose -f deploy/compose.yml` para nada de esto — sólo `docker-compose.dev.yml` / `start_dev.sh`.
- `LLM_PROVIDER=heuristic` no aplica acá (sin dependencia de LLM en este flujo).
- Mantener el nombre de columna `Ingreso.tecnico_id` sin renombrar (aunque ahora almacena un nombre, no un ID) — evita una migración de rename + actualizar todos los consumidores fuera del alcance de este fix; se documenta el cambio semántico en el docstring del modelo.
- Un "Egreso" nunca se bloquea, sólo "Ingreso" — salir de una cámara que pasó a estar baneada durante la visita sigue permitido.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `db/models/infra.py` | Modifica: agrega enum `IngresoTipo` y columna `Ingreso.tipo` + relationship `Ingreso.cromo_botella`. |
| `db/alembic/versions/20260904_01_ingreso_tipo_movimiento.py` | Crea: migración de la columna/enum nuevos. |
| `modules/slack_baneo_notifier/slack_user_resolver.py` | Crea: `resolver_nombre_tecnico(client, slack_user_id)` — llamada a `users.info`. |
| `tests/test_slack_user_resolver.py` | Crea: tests del resolver. |
| `core/services/camara_estado_service.py` | Modifica: `get_camara_estado_contexto` — `tiene_baneo_activo` grupo-consciente de baneo manual; `tiene_ingreso_activo` filtra `tipo == INGRESO`. |
| `tests/test_camara_estado_service.py` | Modifica: agrega `TestGetCamaraEstadoContexto` (no existía cobertura directa de esta función). |
| `core/services/ingreso_service.py` | Modifica: renombra `slack_user_id`→`tecnico_nombre`, estampa `tipo` al crear, filtra `tipo==INGRESO` en el cierre de Egreso; agrega `registrar_intento_bloqueado()`. |
| `tests/test_ingreso_service.py` | Reescribe: adapta a `tecnico_nombre`, agrega cobertura de `tipo` y de `registrar_intento_bloqueado`. |
| `modules/slack_baneo_notifier/listener.py` | Modifica: `_evaluar_estado_acceso_camara` reusa `get_camara_estado_contexto` (grupo-consciente) y devuelve `_ResultadoAccesoCamara(texto, bloqueado)`; enhebra `client` hasta `_registrar_movimiento_si_corresponde`; llama a `resolver_nombre_tecnico`/`registrar_intento_bloqueado`; elimina `_obtener_incidentes_activos_camara` (código muerto). |
| `tests/test_slack_ingreso_listener.py` | Modifica: reescribe `TestBaneoManualSinIncidente` y `TestObtenerIncidentesActivosCamara` (retirada) para el nuevo mecanismo; actualiza los tests de `TestRegistrarMovimientoIngreso` al nuevo kwarg. |
| `web/app/main.py` | Modifica: `_serialize_camara_ingreso` agrega `botella_label`/`tipo`. |
| `tests/test_web_infra_camera_state.py` | Modifica: agrega aserciones/test nuevo para `botella_label`/`tipo`. |
| `web/frontend/src/components/infra/ModalRegistros.vue` | Modifica: usa `botella_label`, distingue visualmente un `INTENTO_BLOQUEADO`. |
| `web/frontend/src/views/CamaraDetailView.vue` | Modifica: interface `RegistrosIngreso` agrega `botella_label`/`tipo`. |
| `docs/bot.md` | Modifica: documenta `tipo`, resolución de nombre, chequeo grupo-consciente. |
| `docs/infra.md` | Modifica: documenta el fix de `tiene_baneo_activo` y `botella_label`. |

---

### Task 1: Modelo `IngresoTipo` + columna `Ingreso.tipo` + migración

**Files:**
- Modify: `db/models/infra.py`
- Create: `db/alembic/versions/20260904_01_ingreso_tipo_movimiento.py`
- Test: `tests/test_ingreso_service.py` (cobertura real de `tipo` llega en Task 4 — acá sólo se verifica el enum)

**Interfaces:**
- Produces: `db.models.infra.IngresoTipo` (enum `str`, valores `"INGRESO"`, `"EGRESO"`, `"INTENTO_BLOQUEADO"`); `Ingreso.tipo` (columna, default Python-side `IngresoTipo.INGRESO`); `Ingreso.cromo_botella` (relationship read-only hacia `CromoBotella`).

- [ ] **Step 1: Agregar el enum `IngresoTipo` en `db/models/infra.py`**

Insertar después de `PuntoTerminalTipo` (línea 86, antes del bloque `# TABLAS ASOCIATIVAS`):

```python
class IngresoTipo(str, Enum):
    """Tipo de movimiento registrado en `Ingreso` — desde la migración `20260904_01`. Antes, el tipo
    de movimiento vivía sólo implícito en fecha_inicio/fecha_fin: no había forma de distinguir un
    intento BLOQUEADO por baneo de un ingreso real "en curso", ambos con `fecha_fin IS NULL` — ver
    `core/services/ingreso_service.py::registrar_intento_bloqueado`."""

    INGRESO = "INGRESO"
    EGRESO = "EGRESO"
    INTENTO_BLOQUEADO = "INTENTO_BLOQUEADO"
```

- [ ] **Step 2: Agregar la columna y la relationship en la clase `Ingreso`**

En `db/models/infra.py`, dentro de `class Ingreso(Base):` (línea ~539), reemplazar:

```python
    tecnico_id = Column(String(128), nullable=True)
    fecha_inicio = Column(DateTime(timezone=True), nullable=True)
    fecha_fin = Column(DateTime(timezone=True), nullable=True)

    camara = relationship("Camara", back_populates="ingresos")

    def __repr__(self) -> str:
        return f"<Ingreso id={self.id} camara_id={self.camara_id}>"
```

por:

```python
    # Desde 2026-09-04 (Tarea 3 del refactor de baneo/Slack): almacena el NOMBRE resuelto del
    # técnico (vía `modules/slack_baneo_notifier/slack_user_resolver.py::resolver_nombre_tecnico`),
    # no ya el Slack user ID crudo — se mantiene el nombre de columna `tecnico_id` para no forzar una
    # migración de rename + actualizar todos los consumidores, fuera del alcance de ese fix.
    tecnico_id = Column(String(128), nullable=True)
    tipo = Column(
        SQLEnum(IngresoTipo, name="ingreso_tipo", create_type=False, schema="app"),
        nullable=False,
        default=IngresoTipo.INGRESO,
    )
    fecha_inicio = Column(DateTime(timezone=True), nullable=True)
    fecha_fin = Column(DateTime(timezone=True), nullable=True)

    camara = relationship("Camara", back_populates="ingresos")
    cromo_botella = relationship("CromoBotella", foreign_keys=[cromo_botella_id])

    def __repr__(self) -> str:
        return f"<Ingreso id={self.id} camara_id={self.camara_id} tipo={self.tipo.value if self.tipo else '?'}>"
```

- [ ] **Step 3: Crear la migración**

Crear `db/alembic/versions/20260904_01_ingreso_tipo_movimiento.py`:

```python
# Nombre de archivo: 20260904_01_ingreso_tipo_movimiento.py
# Ubicación de archivo: db/alembic/versions/20260904_01_ingreso_tipo_movimiento.py
# Descripción: Nuevo enum app.ingreso_tipo + columna app.ingresos.tipo — distingue INGRESO/EGRESO real de un INTENTO_BLOQUEADO por baneo

"""Enum ingreso_tipo + columna ingresos.tipo

Revision ID: 20260904_01
Revises: 20260902_01
Create Date: 2026-09-04

Cambios:
- Nuevo enum Postgres ``app.ingreso_tipo``: INGRESO, EGRESO, INTENTO_BLOQUEADO — mismo patrón que
  ``app.servicio_origen_datos`` (migración ``20260814_02``).
- Nueva columna ``app.ingresos.tipo``: ``NOT NULL DEFAULT 'INGRESO'`` — todas las filas existentes
  hasta esta fecha representan movimientos reales creados como "Ingreso" (nunca hubo un camino de
  escritura de Intento bloqueado antes de esta migración), así que el default es exacto para el
  histórico, no una aproximación.

Motivación: antes de esta columna, un Ingreso real "en curso" (`fecha_fin IS NULL`) era
indistinguible de un futuro Intento bloqueado con la misma condición — `tiene_ingreso_activo`
(``core/services/camara_estado_service.py``) y el cierre de Egreso NULL-safe
(``core/services/ingreso_service.py``) necesitan filtrar explícitamente por
``tipo == 'INGRESO'`` para no confundir ambos casos.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260904_01"
down_revision = "20260902_01"
branch_labels = None
depends_on = None


_VALORES = ("INGRESO", "EGRESO", "INTENTO_BLOQUEADO")


def upgrade() -> None:
    bind = op.get_bind()

    ingreso_tipo_enum = postgresql.ENUM(*_VALORES, name="ingreso_tipo", schema="app", create_type=False)
    ingreso_tipo_enum.create(bind, checkfirst=True)

    op.add_column(
        "ingresos",
        sa.Column(
            "tipo",
            postgresql.ENUM(*_VALORES, name="ingreso_tipo", schema="app", create_type=False),
            nullable=False,
            server_default="INGRESO",
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("ingresos", "tipo", schema="app")
    ingreso_tipo_enum = postgresql.ENUM(*_VALORES, name="ingreso_tipo", schema="app", create_type=False)
    ingreso_tipo_enum.drop(bind=op.get_bind(), checkfirst=True)
```

- [ ] **Step 4: Verificar que el modelo importa sin errores**

Run: `source .venv/bin/activate && python -c "from db.models.infra import Ingreso, IngresoTipo; print(IngresoTipo.INGRESO.value, Ingreso.__table__.columns.keys())"`
Expected: imprime `INGRESO` y la lista de columnas de `ingresos` incluyendo `tipo`, sin traceback.

- [ ] **Step 5: Commit**

```bash
git add db/models/infra.py db/alembic/versions/20260904_01_ingreso_tipo_movimiento.py
git commit -m "feat(infra): agregar Ingreso.tipo (INGRESO/EGRESO/INTENTO_BLOQUEADO)"
```

---

### Task 2: Resolver de nombre de técnico vía Slack `users.info`

**Files:**
- Create: `modules/slack_baneo_notifier/slack_user_resolver.py`
- Test: `tests/test_slack_user_resolver.py`

**Interfaces:**
- Produces: `resolver_nombre_tecnico(client: Any, slack_user_id: str | None) -> str | None`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_slack_user_resolver.py`:

```python
# Nombre de archivo: test_slack_user_resolver.py
# Ubicación de archivo: tests/test_slack_user_resolver.py
# Descripción: Pruebas de resolver_nombre_tecnico (Slack users.info -> nombre real del técnico)

from __future__ import annotations

from unittest.mock import MagicMock

from modules.slack_baneo_notifier.slack_user_resolver import resolver_nombre_tecnico


def test_resuelve_display_name_cuando_esta_poblado() -> None:
    client = MagicMock()
    client.users_info.return_value = {
        "user": {
            "real_name": "Rider Fernandez",
            "profile": {"display_name": "rider.fernandez", "real_name": "Rider Fernandez"},
        }
    }

    resultado = resolver_nombre_tecnico(client, "U0AUB6CRE4A")

    assert resultado == "rider.fernandez"
    client.users_info.assert_called_once_with(user="U0AUB6CRE4A")


def test_cae_a_real_name_cuando_display_name_esta_vacio() -> None:
    client = MagicMock()
    client.users_info.return_value = {
        "user": {"real_name": "Rider Fernandez", "profile": {"display_name": "", "real_name": "Rider Fernandez"}}
    }

    resultado = resolver_nombre_tecnico(client, "U0AUB6CRE4A")

    assert resultado == "Rider Fernandez"


def test_cae_al_id_crudo_si_la_api_falla() -> None:
    client = MagicMock()
    client.users_info.side_effect = Exception("boom")

    resultado = resolver_nombre_tecnico(client, "U0AUB6CRE4A")

    assert resultado == "U0AUB6CRE4A"


def test_none_si_no_hay_slack_user_id() -> None:
    client = MagicMock()

    resultado = resolver_nombre_tecnico(client, None)

    assert resultado is None
    client.users_info.assert_not_called()
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `source .venv/bin/activate && pytest tests/test_slack_user_resolver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.slack_baneo_notifier.slack_user_resolver'`

- [ ] **Step 3: Implementar `slack_user_resolver.py`**

Crear `modules/slack_baneo_notifier/slack_user_resolver.py`:

```python
# Nombre de archivo: slack_user_resolver.py
# Ubicación de archivo: modules/slack_baneo_notifier/slack_user_resolver.py
# Descripción: Resuelve el nombre real de un técnico a partir de su Slack user ID (users.info)

"""Resuelve `slack_user_id` (ej. 'U03DPFK0Q69') al nombre visible del técnico, vía la Slack Web API
`users.info` — hasta la Tarea 3 del refactor de baneo/Slack (2026-09-04), `Ingreso.tecnico_id`
guardaba el ID crudo porque nada en el repo llamaba `users.info` (ver docs/bot.md, sección
"Registro de movimiento Ingreso/Egreso").

El `client` recibido es el mismo `slack_sdk.WebClient` que Slack Bolt inyecta en cada handler de
evento (`IngresoListener._handle_message(self, event, client)`) — esta función no crea un cliente
nuevo, reusa el token/sesión ya autenticada del listener.

Requiere el scope `users:read` en la Slack App (agregar en el panel de Slack — no verificable desde
código, mismo criterio que `app_mentions:read` documentado en `listener.py`).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("slack_baneo_worker.slack_user_resolver")

__all__ = ["resolver_nombre_tecnico"]


def resolver_nombre_tecnico(client: Any, slack_user_id: str | None) -> str | None:
    """Devuelve el nombre visible del técnico (`display_name` o, si está vacío, `real_name`) para
    `slack_user_id`, o `None` si `slack_user_id` es `None` (nadie que resolver).

    Nunca lanza: cualquier error de la API (token sin scope `users:read`, usuario borrado, timeout de
    red) se loguea como warning y cae al ID crudo de Slack — preferible una fila con el ID crudo
    (comportamiento previo a esta tarea) a que un fallo de red bloquee el registro de ingreso.
    """
    if not slack_user_id:
        return None
    try:
        respuesta = client.users_info(user=slack_user_id)
        usuario = (respuesta or {}).get("user") or {}
        perfil = usuario.get("profile") or {}
        nombre = perfil.get("display_name") or perfil.get("real_name") or usuario.get("real_name")
        return nombre or slack_user_id
    except Exception as exc:
        logger.warning("No se pudo resolver nombre para slack_user_id=%s: %s", slack_user_id, exc)
        return slack_user_id
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `source .venv/bin/activate && pytest tests/test_slack_user_resolver.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add modules/slack_baneo_notifier/slack_user_resolver.py tests/test_slack_user_resolver.py
git commit -m "feat(slack): resolver nombre real del técnico vía users.info"
```

---

### Task 3: `get_camara_estado_contexto` grupo-consciente de baneo manual + filtro de tipo en ingreso activo

**Files:**
- Modify: `core/services/camara_estado_service.py:155-217`
- Test: `tests/test_camara_estado_service.py`

**Interfaces:**
- Consumes: `db.models.infra.IngresoTipo` (Task 1), `miembros_del_grupo(camara) -> list[Camara]` (ya existente en este mismo archivo).
- Produces: `get_camara_estado_contexto(session, camara_id) -> CamaraEstadoContexto | None` — **cambio de comportamiento**: `tiene_baneo_activo` ahora también es `True` cuando cualquier miembro del grupo tiene `estado == BANEADA` (antes sólo miraba `IncidenteBaneo`); `tiene_ingreso_activo` ahora excluye filas `tipo != INGRESO`.

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_camara_estado_service.py`, agregar al final del archivo (después de `test_override_camara_estado_manual_grupo_entero_en_destino_no_cambia`):

```python
class TestGetCamaraEstadoContexto(unittest.TestCase):
    """Cobertura nueva para `get_camara_estado_contexto` (Tarea 3, 2026-09-04) — hasta esta revisión
    la función no tenía NINGÚN test directo (sólo se la mockeaba desde otros módulos). Hallazgo real
    de esta tarea: `tiene_baneo_activo` sólo miraba `IncidenteBaneo`, nunca `Camara.estado ==
    BANEADA` — un baneo manual (override admin, sin incidente de protección asociado) quedaba
    invisible tanto para el badge web como para el listener de Slack de ingreso."""

    def _entity_name(self, entity: Any) -> str:
        name = getattr(entity, "__name__", "")
        if name:
            return name
        cls = getattr(entity, "class_", None)
        return getattr(cls, "__name__", "") if cls is not None else ""

    def _fake_session(self, camara: Any, capturar_filtros_ingreso: list | None = None) -> Any:
        session = MagicMock()

        def _query(*entities):
            entity_name = self._entity_name(entities[0])
            query_mock = MagicMock()
            if entity_name == "Camara":
                query_mock.filter.return_value.first.return_value = camara
            elif entity_name == "Ingreso":
                def _filter(*args, **kwargs):
                    if capturar_filtros_ingreso is not None:
                        capturar_filtros_ingreso.extend(args)
                    inner = MagicMock()
                    inner.first.return_value = None
                    return inner
                query_mock.filter.side_effect = _filter
            elif entity_name == "IncidenteBaneo":
                query_mock.filter.return_value.order_by.return_value.all.return_value = []
            return query_mock

        session.query.side_effect = _query
        return session

    def test_baneo_manual_de_una_botella_hermana_marca_tiene_baneo_activo(self) -> None:
        """Bug real (esta tarea): consultar el contexto de la cámara RAÍZ (estado LIBRE) mientras una
        Botella hermana está BANEADA manualmente (sin incidente) debía dar tiene_baneo_activo=True —
        antes daba False porque la función nunca miraba `Camara.estado`, sólo `IncidenteBaneo`."""
        from core.services.camara_estado_service import get_camara_estado_contexto

        padre, bot1, bot2 = _grupo(
            estado_padre=CamaraEstado.LIBRE, estado_bot1=CamaraEstado.BANEADA, estado_bot2=CamaraEstado.LIBRE
        )
        padre.empalmes = []
        session = self._fake_session(padre)

        contexto = get_camara_estado_contexto(session, padre.id)

        self.assertTrue(contexto.tiene_baneo_activo)
        self.assertEqual(contexto.incidentes_activos, [])

    def test_baneo_manual_de_la_camara_misma_marca_tiene_baneo_activo(self) -> None:
        from core.services.camara_estado_service import get_camara_estado_contexto

        padre, bot1, bot2 = _grupo(estado_padre=CamaraEstado.BANEADA)
        padre.empalmes = []
        session = self._fake_session(padre)

        contexto = get_camara_estado_contexto(session, padre.id)

        self.assertTrue(contexto.tiene_baneo_activo)

    def test_sin_baneo_manual_ni_incidente_da_false(self) -> None:
        from core.services.camara_estado_service import get_camara_estado_contexto

        padre, bot1, bot2 = _grupo()
        padre.empalmes = []
        session = self._fake_session(padre)

        contexto = get_camara_estado_contexto(session, padre.id)

        self.assertFalse(contexto.tiene_baneo_activo)

    def test_tiene_ingreso_activo_filtra_por_tipo_ingreso(self) -> None:
        """La query de `tiene_ingreso_activo` debe filtrar explícitamente `tipo == INGRESO` — sin
        esto, un `INTENTO_BLOQUEADO` (mismo `fecha_fin IS NULL`) contaría como ingreso activo real."""
        from core.services.camara_estado_service import get_camara_estado_contexto
        from db.models.infra import IngresoTipo

        padre, bot1, bot2 = _grupo()
        padre.empalmes = []
        filtros: list[Any] = []
        session = self._fake_session(padre, capturar_filtros_ingreso=filtros)

        contexto = get_camara_estado_contexto(session, padre.id)

        self.assertFalse(contexto.tiene_ingreso_activo)
        tipo_filtrado = any(
            getattr(getattr(expr, "left", None), "key", None) == "tipo"
            and getattr(expr, "right", None) is not None
            and expr.right.value == IngresoTipo.INGRESO
            for expr in filtros
        )
        self.assertTrue(tipo_filtrado, "Se esperaba un filtro Ingreso.tipo == IngresoTipo.INGRESO")
```

Agregar `import unittest` y `from typing import Any` al principio de `tests/test_camara_estado_service.py` si no están ya (el archivo actual empieza con `from unittest.mock import MagicMock, patch` — agregar `import unittest` justo antes de esa línea, y `from typing import Any` junto a los imports de dataclasses/typing existentes).

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `source .venv/bin/activate && pytest tests/test_camara_estado_service.py::TestGetCamaraEstadoContexto -v`
Expected: `test_baneo_manual_de_una_botella_hermana_marca_tiene_baneo_activo` y `test_baneo_manual_de_la_camara_misma_marca_tiene_baneo_activo` FALLAN (`tiene_baneo_activo` da `False`); `test_tiene_ingreso_activo_filtra_por_tipo_ingreso` FALLA con `AttributeError` (columna `tipo` no existe todavía en el `Ingreso` importado si Task 1 no corrió antes — confirmar que Task 1 ya está mergeado en esta rama antes de correr esto).

- [ ] **Step 3: Implementar el fix**

En `core/services/camara_estado_service.py`, actualizar el import (línea 15):

```python
from db.models.infra import Camara, CamaraEstado, CamaraEstadoAuditoria, IncidenteBaneo, Ingreso, IngresoTipo
```

Y reemplazar el bloque (líneas 177-189):

```python
    ids_grupo = [miembro.id for miembro in miembros_del_grupo(camara)]
    tiene_ingreso_activo = (
        session.query(Ingreso.id)
        .filter(
            Ingreso.camara_id.in_(ids_grupo),
            Ingreso.fecha_fin == None,  # noqa: E711
        )
        .first()
        is not None
    )

    estado_actual = camara.estado or CamaraEstado.LIBRE
    tiene_baneo_activo = len(incidentes_activos_db) > 0
```

por:

```python
    miembros = miembros_del_grupo(camara)
    ids_grupo = [miembro.id for miembro in miembros]
    tiene_ingreso_activo = (
        session.query(Ingreso.id)
        .filter(
            Ingreso.camara_id.in_(ids_grupo),
            Ingreso.tipo == IngresoTipo.INGRESO,
            Ingreso.fecha_fin == None,  # noqa: E711
        )
        .first()
        is not None
    )

    estado_actual = camara.estado or CamaraEstado.LIBRE
    # Baneo manual (Camara.estado == BANEADA) de CUALQUIER miembro del grupo cuenta como baneo activo
    # — hallazgo real (2026-09-04): antes sólo se miraba IncidenteBaneo, así que un baneo manual
    # (override admin, sin incidente de protección asociado) dejaba tiene_baneo_activo=False aunque
    # la cámara o una Botella hermana estuviera BANEADA — el badge "Contexto operativo"
    # (ModalRegistros.vue) y el listener de Slack de ingreso mostraban "Sin baneo activo"/permitían
    # el ingreso sobre un grupo realmente baneado.
    tiene_baneo_manual = any(miembro.estado == CamaraEstado.BANEADA for miembro in miembros)
    tiene_baneo_activo = len(incidentes_activos_db) > 0 or tiene_baneo_manual
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `source .venv/bin/activate && pytest tests/test_camara_estado_service.py -v`
Expected: todos los tests del archivo pasan (los pre-existentes + los 4 nuevos de `TestGetCamaraEstadoContexto`).

- [ ] **Step 5: Commit**

```bash
git add core/services/camara_estado_service.py tests/test_camara_estado_service.py
git commit -m "fix(infra): tiene_baneo_activo considera baneo manual del grupo, no sólo IncidenteBaneo"
```

---

### Task 4: `ingreso_service.py` — `tecnico_nombre`, `tipo`, `registrar_intento_bloqueado`

**Files:**
- Modify: `core/services/ingreso_service.py`
- Test: `tests/test_ingreso_service.py` (reescritura completa)

**Interfaces:**
- Consumes: `db.models.infra.IngresoTipo` (Task 1).
- Produces: `registrar_movimiento_ingreso(session, *, camara, botella, tipo_movimiento, tecnico_nombre) -> Ingreso` (**breaking change**: el kwarg se llamaba `slack_user_id`, ahora `tecnico_nombre` — único caller productivo es `listener.py`, actualizado en Task 5). `registrar_intento_bloqueado(session, *, camara, botella, tecnico_nombre) -> Ingreso` (nueva).

- [ ] **Step 1: Escribir los tests que fallan (reescritura completa del archivo)**

Reemplazar el contenido completo de `tests/test_ingreso_service.py`:

```python
# Nombre de archivo: test_ingreso_service.py
# Ubicación de archivo: tests/test_ingreso_service.py
# Descripción: Pruebas de registrar_movimiento_ingreso/registrar_intento_bloqueado (creación de Ingreso, cierre NULL-safe de Egreso, Intento bloqueado por baneo)

from __future__ import annotations

import operator
from datetime import datetime, timezone
from unittest.mock import MagicMock

from sqlalchemy.sql import operators as sa_operators
from sqlalchemy.sql.elements import Null

from core.services.ingreso_service import registrar_intento_bloqueado, registrar_movimiento_ingreso
from db.models.cromo import CromoBotella
from db.models.infra import Camara, Ingreso, IngresoTipo


def _assert_filtro_null_safe(filtros, columna_attr: str, valor_esperado) -> None:
    """Verifica que, entre los filtros posicionales pasados a `session.query(...).filter(...)`, exista
    uno para `columna_attr` que sea NULL-safe respecto de `valor_esperado`:

    - Si `valor_esperado` es `None`, el filtro debe ser `columna.is_(None)` (operador `is_`, lado
      derecho `Null()`) — nunca `columna == None`, que en SQL genera `columna = NULL` y jamás matchea
      (ni siquiera contra otra fila con la columna en NULL).
    - Si `valor_esperado` no es `None`, el filtro debe comparar por igualdad contra ese valor exacto.
    """
    for expr in filtros:
        if getattr(getattr(expr, "left", None), "key", None) != columna_attr:
            continue
        if valor_esperado is None:
            assert expr.operator is sa_operators.is_, f"{columna_attr}: se esperaba IS NULL (NULL-safe)"
            assert isinstance(expr.right, Null), f"{columna_attr}: el lado derecho debería ser NULL"
        else:
            assert expr.right.value == valor_esperado, f"{columna_attr}: valor de filtro incorrecto"
            assert expr.operator in (operator.eq, sa_operators.is_), f"{columna_attr}: operador inesperado"
        return
    raise AssertionError(f"No se encontró un filtro para la columna '{columna_attr}'")


def _assert_filtro_igualdad(filtros, columna_attr: str, valor_esperado) -> None:
    """Verifica un filtro de igualdad simple (no NULL-safe) — usado para `tipo`, que nunca es None."""
    for expr in filtros:
        if getattr(getattr(expr, "left", None), "key", None) != columna_attr:
            continue
        assert expr.right.value == valor_esperado, f"{columna_attr}: valor de filtro incorrecto"
        return
    raise AssertionError(f"No se encontró un filtro para la columna '{columna_attr}'")


def _camara(camara_id: int = 10) -> Camara:
    return Camara(id=camara_id, nombre="Cra Test CF")


def _botella(n_id: int = 555) -> CromoBotella:
    return CromoBotella(n_id=n_id)


# --- (a) Ingreso: siempre crea fila nueva ---------------------------------------------------------


def test_ingreso_con_botella_crea_fila_con_cromo_botella_id_poblado() -> None:
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)

    resultado = registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Ingreso", tecnico_nombre="Rider Fernández"
    )

    assert isinstance(resultado, Ingreso)
    assert resultado.camara_id == 10
    assert resultado.cromo_botella_id == 555
    assert resultado.tecnico_id == "Rider Fernández"
    assert resultado.tipo == IngresoTipo.INGRESO
    assert resultado.fecha_inicio is not None
    assert resultado.fecha_fin is None
    session.add.assert_called_once_with(resultado)
    session.commit.assert_called_once()
    # Ingreso nunca busca reabrir/reutilizar filas existentes.
    session.query.assert_not_called()


def test_ingreso_sin_botella_deja_cromo_botella_id_en_none() -> None:
    session = MagicMock()
    camara = _camara()

    resultado = registrar_movimiento_ingreso(
        session, camara=camara, botella=None, tipo_movimiento="Ingreso", tecnico_nombre="Rider Fernández"
    )

    assert resultado.cromo_botella_id is None
    assert resultado.tipo == IngresoTipo.INGRESO
    assert resultado.fecha_fin is None
    session.add.assert_called_once_with(resultado)
    session.commit.assert_called_once()


# --- (b) Egreso con Ingreso abierto matcheando -----------------------------------------------------


def test_egreso_con_ingreso_abierto_matching_cierra_esa_fila_sin_crear_una_nueva() -> None:
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    ingreso_abierto = Ingreso(
        id=1,
        camara_id=10,
        cromo_botella_id=555,
        tecnico_id="Rider Fernández",
        tipo=IngresoTipo.INGRESO,
        fecha_inicio=datetime(2026, 8, 30, tzinfo=timezone.utc),
        fecha_fin=None,
    )
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = ingreso_abierto

    resultado = registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Egreso", tecnico_nombre="Rider Fernández"
    )

    assert resultado is ingreso_abierto
    assert resultado.fecha_fin is not None
    session.add.assert_not_called()
    session.commit.assert_called_once()

    filtros = session.query.return_value.filter.call_args[0]
    _assert_filtro_null_safe(filtros, "tecnico_id", "Rider Fernández")
    _assert_filtro_null_safe(filtros, "camara_id", 10)
    _assert_filtro_null_safe(filtros, "cromo_botella_id", 555)
    # "ABIERTO" — sin este filtro, un Ingreso ya cerrado (fecha_fin no nula) sería candidato a
    # "cerrarse" de nuevo, pisando su fecha_fin real con la de este movimiento.
    _assert_filtro_null_safe(filtros, "fecha_fin", None)
    # Sin este filtro, un Intento bloqueado (mismo fecha_fin IS NULL) podría cerrarse como si fuera
    # un Ingreso real — ver registrar_intento_bloqueado() más abajo.
    _assert_filtro_igualdad(filtros, "tipo", IngresoTipo.INGRESO)
    session.query.return_value.filter.return_value.order_by.assert_called_once()


# --- (c) Egreso sin Ingreso abierto matcheando -------------------------------------------------------


def test_egreso_sin_ingreso_abierto_matching_crea_fila_nueva_con_fecha_inicio_none() -> None:
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    resultado = registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Egreso", tecnico_nombre="Rider Fernández"
    )

    assert isinstance(resultado, Ingreso)
    assert resultado.camara_id == 10
    assert resultado.cromo_botella_id == 555
    assert resultado.tecnico_id == "Rider Fernández"
    assert resultado.tipo == IngresoTipo.EGRESO
    assert resultado.fecha_inicio is None  # deliberado: nunca fecha_inicio=fecha_fin (duración falsa de 0s)
    assert resultado.fecha_fin is not None
    session.add.assert_called_once_with(resultado)
    session.commit.assert_called_once()

    filtros = session.query.return_value.filter.call_args[0]
    _assert_filtro_null_safe(filtros, "fecha_fin", None)


# --- (d) Egreso sin tecnico_nombre no debe cerrar el ingreso de un técnico real ----------------------


def test_egreso_sin_tecnico_nombre_filtra_por_tecnico_id_is_null() -> None:
    """El query debe exigir `tecnico_id IS NULL` (NULL-safe) cuando `tecnico_nombre` es None — nunca
    omitir el criterio ni tratarlo como comodín que matchee cualquier técnico."""
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Egreso", tecnico_nombre=None
    )

    filtros = session.query.return_value.filter.call_args[0]
    _assert_filtro_null_safe(filtros, "tecnico_id", None)
    _assert_filtro_null_safe(filtros, "fecha_fin", None)


# --- (e) Intento bloqueado (Tarea 4, 2026-09-04) ----------------------------------------------------


def test_registrar_intento_bloqueado_crea_fila_tipo_intento_sin_egreso() -> None:
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)

    resultado = registrar_intento_bloqueado(
        session, camara=camara, botella=botella, tecnico_nombre="Rider Fernández"
    )

    assert isinstance(resultado, Ingreso)
    assert resultado.camara_id == 10
    assert resultado.cromo_botella_id == 555
    assert resultado.tecnico_id == "Rider Fernández"
    assert resultado.tipo == IngresoTipo.INTENTO_BLOQUEADO
    assert resultado.fecha_inicio is not None
    assert resultado.fecha_fin is None
    session.add.assert_called_once_with(resultado)
    session.commit.assert_called_once()
    # Nunca busca reabrir/cerrar una fila existente — un intento bloqueado es siempre una fila nueva.
    session.query.assert_not_called()


def test_registrar_intento_bloqueado_sin_botella_deja_cromo_botella_id_en_none() -> None:
    session = MagicMock()
    camara = _camara()

    resultado = registrar_intento_bloqueado(session, camara=camara, botella=None, tecnico_nombre=None)

    assert resultado.cromo_botella_id is None
    assert resultado.tecnico_id is None
    assert resultado.tipo == IngresoTipo.INTENTO_BLOQUEADO
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `source .venv/bin/activate && pytest tests/test_ingreso_service.py -v`
Expected: FAIL — `TypeError: registrar_movimiento_ingreso() got an unexpected keyword argument 'tecnico_nombre'` y `ImportError: cannot import name 'registrar_intento_bloqueado'`.

- [ ] **Step 3: Implementar el fix**

Reemplazar el contenido completo de `core/services/ingreso_service.py`:

```python
# Nombre de archivo: ingreso_service.py
# Ubicación de archivo: core/services/ingreso_service.py
# Descripción: Persistencia del movimiento Ingreso/Egreso/Intento bloqueado de un técnico a una Cámara

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models.cromo import CromoBotella
from db.models.infra import Camara, Ingreso, IngresoTipo


def _null_safe(columna, valor):
    """Comparación NULL-safe de una columna contra un valor Python ya conocido (no otra columna).

    En SQL, `columna = NULL` nunca es verdadero — ni siquiera cuando la fila también tiene esa
    columna en NULL — así que un `columna == valor` naive con `valor is None` fallaría en encontrar
    esas filas. Acá alcanza con `columna.is_(None)` para ese caso puntual (comparar contra un literal
    conocido, no NULL-safe entre dos columnas, que requeriría `is_not_distinct_from`)."""
    return columna.is_(None) if valor is None else columna == valor


def registrar_movimiento_ingreso(
    session: Session,
    *,
    camara: Camara,
    botella: CromoBotella | None,
    tipo_movimiento: str,  # "Ingreso" | "Egreso" (ya validado por el caller, no se revalida acá)
    tecnico_nombre: str | None,
) -> Ingreso:
    """Persiste un movimiento de Ingreso o Egreso REAL de un técnico a `camara` (Cámara o Botella ya
    resuelta) y comita la transacción antes de retornar. `tecnico_nombre` ya debe venir resuelto por
    el caller (ver `modules/slack_baneo_notifier/slack_user_resolver.py::resolver_nombre_tecnico`) —
    este servicio no conoce Slack, sólo persiste.

    - "Ingreso": SIEMPRE crea una fila nueva (`tipo=INGRESO`), nunca reabre ni reutiliza una fila
      existente.
    - "Egreso": busca el `Ingreso` ABIERTO (`tipo=INGRESO`, `fecha_fin IS NULL`) más reciente cuyo
      `tecnico_id`, `camara_id` y `cromo_botella_id` coincidan EXACTAMENTE (NULL-safe: `None` exige
      `IS NULL` del lado de la fila existente, nunca se trata como comodín) y lo cierra. El filtro
      `tipo=INGRESO` es deliberado: sin él, un `Intento bloqueado` (mismo `fecha_fin IS NULL`, ver
      `registrar_intento_bloqueado` más abajo) sería candidato a "cerrarse" como si fuera un ingreso
      real. Si no encuentra ninguna fila así, crea una nueva con `fecha_inicio=None` (deliberado: no
      hay forma de saber cuándo entró, y setear `fecha_inicio=fecha_fin` registraría una duración
      falsa de 0 segundos en cualquier reporte futuro, `tipo=EGRESO`) — es preferible una fila
      huérfana de más que cerrar el ingreso de otro técnico.

    Para un intento BLOQUEADO por baneo, usar `registrar_intento_bloqueado` — nunca este servicio con
    `tipo_movimiento="Ingreso"`.
    """
    ahora = datetime.now(timezone.utc)
    cromo_botella_id = botella.n_id if botella is not None else None

    if tipo_movimiento == "Ingreso":
        ingreso = Ingreso(
            camara_id=camara.id,
            cromo_botella_id=cromo_botella_id,
            tecnico_id=tecnico_nombre,
            tipo=IngresoTipo.INGRESO,
            fecha_inicio=ahora,
            fecha_fin=None,
        )
        session.add(ingreso)
        session.commit()
        return ingreso

    # tipo_movimiento == "Egreso"
    ingreso_abierto = (
        session.query(Ingreso)
        .filter(
            _null_safe(Ingreso.tecnico_id, tecnico_nombre),
            Ingreso.camara_id == camara.id,
            _null_safe(Ingreso.cromo_botella_id, cromo_botella_id),
            Ingreso.tipo == IngresoTipo.INGRESO,
            Ingreso.fecha_fin.is_(None),
        )
        .order_by(Ingreso.fecha_inicio.desc())
        .first()
    )

    if ingreso_abierto is not None:
        ingreso_abierto.fecha_fin = ahora
        session.commit()
        return ingreso_abierto

    ingreso = Ingreso(
        camara_id=camara.id,
        cromo_botella_id=cromo_botella_id,
        tecnico_id=tecnico_nombre,
        tipo=IngresoTipo.EGRESO,
        fecha_inicio=None,
        fecha_fin=ahora,
    )
    session.add(ingreso)
    session.commit()
    return ingreso


def registrar_intento_bloqueado(
    session: Session,
    *,
    camara: Camara,
    botella: CromoBotella | None,
    tecnico_nombre: str | None,
) -> Ingreso:
    """Persiste un intento de Ingreso BLOQUEADO por baneo (de la Cámara o de una Botella del mismo
    grupo — ver `core/services/camara_estado_service.py::get_camara_estado_contexto`).

    Nunca representa un ingreso real: `fecha_fin` queda en `None` (no hay egreso posible de un
    ingreso que nunca ocurrió) pero `tipo=INTENTO_BLOQUEADO` lo distingue de un `Ingreso` real "en
    curso" en toda consulta que filtre por `tipo` — ver el filtro agregado en
    `get_camara_estado_contexto` (`tiene_ingreso_activo`) y en la búsqueda de Egreso de
    `registrar_movimiento_ingreso` (arriba), ambos ahora exigen `tipo == INGRESO` explícitamente.

    El caller (`IngresoListener._registrar_movimiento_si_corresponde`) sólo invoca esto para
    movimientos de tipo "Ingreso" — un "Egreso" nunca se bloquea (salir de una cámara que pasó a
    estar baneada durante la visita sigue permitido, no hay razón operativa para impedirlo)."""
    ahora = datetime.now(timezone.utc)
    intento = Ingreso(
        camara_id=camara.id,
        cromo_botella_id=botella.n_id if botella is not None else None,
        tecnico_id=tecnico_nombre,
        tipo=IngresoTipo.INTENTO_BLOQUEADO,
        fecha_inicio=ahora,
        fecha_fin=None,
    )
    session.add(intento)
    session.commit()
    return intento


__all__ = ["registrar_intento_bloqueado", "registrar_movimiento_ingreso"]
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `source .venv/bin/activate && pytest tests/test_ingreso_service.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add core/services/ingreso_service.py tests/test_ingreso_service.py
git commit -m "feat(infra): registrar_intento_bloqueado + registrar_movimiento_ingreso usa tecnico_nombre"
```

---

### Task 5: `listener.py` — chequeo de acceso grupo-consciente + Intento bloqueado + resolución de nombre

**Files:**
- Modify: `modules/slack_baneo_notifier/listener.py`
- Test: `tests/test_slack_ingreso_listener.py`

**Interfaces:**
- Consumes: `get_camara_estado_contexto`, `miembros_del_grupo` (Task 3); `registrar_intento_bloqueado`, `registrar_movimiento_ingreso(..., tecnico_nombre=...)` (Task 4); `resolver_nombre_tecnico(client, slack_user_id)` (Task 2).
- Produces: `IngresoListener._evaluar_estado_acceso_camara(camara, session) -> _ResultadoAccesoCamara` (**cambio de tipo de retorno**: antes `str`, ahora dataclass con `.texto`/`.bloqueado`). Elimina `_obtener_incidentes_activos_camara` (código muerto tras este cambio).

- [ ] **Step 1: Escribir/adaptar los tests que fallan**

En `tests/test_slack_ingreso_listener.py`:

1) Eliminar por completo la clase `TestObtenerIncidentesActivosCamara` (líneas 904-931 del archivo actual) — la función que testea deja de existir.

2) Reemplazar la clase `TestBaneoManualSinIncidente` completa (líneas 1567 hasta el final de esa clase, antes de `class TestLibreNoAfectado` o la siguiente clase que exista) por:

```python
class TestBaneoManualSinIncidente(unittest.TestCase):
    """Prueba la jerarquía de validación cuando el GRUPO (cámara + botellas hermanas) tiene un
    miembro BANEADO manualmente (sin IncidenteBaneo activo) — Tarea 5 (2026-09-04): el chequeo ahora
    reusa `get_camara_estado_contexto()` en vez de mirar sólo el `estado`/incidentes de la fila
    puntual resuelta, así que estos tests mockean `get_camara_estado_contexto` (no ya
    `_obtener_incidentes_activos_camara`, retirada — ver `camara_estado_service.CamaraEstadoContexto`
    para el shape exacto)."""

    def _make_listener(self) -> Any:
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event(self, text: str = "Cámara: Cam Test") -> dict:
        return {"text": text, "channel": "C123", "ts": "1234567890.000001"}

    def _make_camara(self, id_: int, nombre: str, estado: Any) -> Any:
        camara = MagicMock()
        camara.id = id_
        camara.nombre = nombre
        camara.estado = estado
        camara.camara_padre = None
        camara.botellas = []
        return camara

    def _contexto(self, camara_id: int, *, incidentes_activos=None) -> Any:
        from core.services.camara_estado_service import CamaraEstadoContexto
        from db.models.infra import CamaraEstado

        incidentes_activos = incidentes_activos or []
        return CamaraEstadoContexto(
            camara_id=camara_id,
            estado_actual=CamaraEstado.BANEADA,
            estado_sugerido=CamaraEstado.BANEADA,
            tiene_baneo_activo=True,
            tiene_ingreso_activo=False,
            inconsistente=False,
            incidentes_activos=incidentes_activos,
            ticket_baneo=None,
        )

    def test_baneada_manual_sin_incidente_bloquea(self) -> None:
        """Grupo BANEADO sin incidente activo → :no_entry: con motivo de auditoría."""
        from db.models.infra import CamaraEstado

        camara_mock = self._make_camara(10, "Cam Baneada Manual", CamaraEstado.BANEADA)
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Baneada Manual")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Baneada Manual"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "baneada manual"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=self._contexto(10),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                return_value="Fibra cortada en nodo norte",
            ),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn(":no_entry:", texto)
        self.assertIn("Cam Baneada Manual", texto)
        self.assertIn("Fibra cortada en nodo norte", texto)
        self.assertNotIn("ATENCIÓN", texto)

    def test_baneada_manual_sin_motivo_auditoria(self) -> None:
        """Grupo BANEADO, `obtener_ultimo_motivo_baneo_manual` retorna None → fallback 'sin motivo
        registrado'."""
        from db.models.infra import CamaraEstado

        camara_mock = self._make_camara(11, "Cam Baneada Sin Audit", CamaraEstado.BANEADA)
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Baneada Sin Audit")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Baneada Sin Audit"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "baneada sin audit"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=self._contexto(11),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                return_value=None,
            ),
        ):
            listener._handle_message(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn(":no_entry:", texto)
        self.assertIn("sin motivo registrado", texto)

    def test_jerarquia_incidente_tiene_prioridad(self) -> None:
        """Grupo BANEADO con IncidenteBaneo activo → 🚨 ATENCIÓN (nivel 1 gana sobre manual)."""
        from core.services.camara_estado_service import IncidenteActivoResumen
        from db.models.infra import CamaraEstado

        camara_mock = self._make_camara(12, "Cam Con Incidente", CamaraEstado.BANEADA)
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Con Incidente")
        incidente = IncidenteActivoResumen(
            id=55, ticket_asociado="TKT-555", servicio_protegido_id="SVC-01",
            ruta_protegida_id=None, fecha_inicio=None, motivo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Con Incidente"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "con incidente"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=self._contexto(12, incidentes_activos=[incidente]),
            ),
            patch("modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual") as mock_motivo,
        ):
            listener._handle_message(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("ATENCIÓN", texto)
        self.assertIn("#55", texto)
        # La función de auditoría no debe haberse llamado cuando hay incidente activo
        mock_motivo.assert_not_called()

    def test_baneo_de_botella_hermana_bloquea_ingreso_a_la_camara_raiz(self) -> None:
        """Bug real que motivó esta tarea: pedir ingreso a la cámara RAÍZ (estado propio LIBRE)
        mientras una Botella hermana está BANEADA debe bloquear igual — antes el listener sólo miraba
        el `estado` de la fila puntual resuelta, nunca el grupo."""
        from db.models.infra import CamaraEstado

        camara_mock = self._make_camara(13, "Cam Raiz Libre", CamaraEstado.LIBRE)
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Raiz Libre")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Raiz Libre"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "raiz libre"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                # tiene_baneo_activo=True aunque la propia fila (`estado_actual`) siga LIBRE — lo
                # aporta una Botella hermana, ya contemplado por Task 3.
                return_value=self._contexto(13),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                return_value="Botella hermana baneada",
            ),
        ):
            listener._handle_message(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn(":no_entry:", texto)

    def test_libre_no_afectado(self) -> None:
        """Grupo LIBRE (sin baneo) → ✅ OK — la nueva rama no interfiere. (regresión)"""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        camara_mock = self._make_camara(14, "Cam Libre", CamaraEstado.LIBRE)
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Libre")
        contexto_libre = CamaraEstadoContexto(
            camara_id=14, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Libre"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "libre"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_libre,
            ),
        ):
            listener._handle_message(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("✅", texto)
        self.assertNotIn(":no_entry:", texto)
        self.assertNotIn("ATENCIÓN", texto)
```

3) En `TestRegistrarMovimientoIngreso`, reemplazar en las 3 llamadas existentes el kwarg `slack_user_id="U0AUB6CRE4A"` de las aserciones `mock_registrar.assert_called_once_with(...)` — dado que ahora el listener resuelve el nombre antes de llamar al servicio, agregar también el mock del resolver. Reemplazar el método `test_registra_movimiento_cuando_hay_match_camara_directa_y_texto_trae_ingreso` completo por:

```python
    def test_registra_movimiento_cuando_hay_match_camara_directa_y_texto_trae_ingreso(self) -> None:
        """fuente='camara' (match directo, sin pasar por CromoBotella) + campo 'Ingreso o Egreso'
        presente, grupo LIBRE (no bloqueado) → registrar_movimiento_ingreso se llama con botella=None
        y el nombre YA resuelto por `resolver_nombre_tecnico`."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = self._make_camara()
        camara_mock.estado = CamaraEstado.LIBRE
        contexto_libre = CamaraEstadoContexto(
            camara_id=camara_mock.id, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Ruta 8 Km 34 MALVINAS ARGENTINAS",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "ruta 8 km 34 malvinas argentinas"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_libre,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_nombre_tecnico",
                return_value="Rider Fernández",
            ) as mock_resolver,
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(self._make_event(text=self.TEXTO_CON_INGRESO), client_mock)

        mock_resolver.assert_called_once_with(client_mock, "U0AUB6CRE4A")
        mock_registrar.assert_called_once_with(
            session_mock,
            camara=camara_mock,
            botella=None,
            tipo_movimiento="Ingreso",
            tecnico_nombre="Rider Fernández",
        )
        # La respuesta de Slack de siempre no debe verse afectada por el registro.
        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("✅", texto_respuesta)
```

Aplicar el mismo criterio (agregar `get_camara_estado_contexto` mockeado a LIBRE + `resolver_nombre_tecnico` mockeado + `tecnico_nombre=` en vez de `slack_user_id=`) a `test_registra_movimiento_con_botella_cromo_y_egreso` y a los demás tests de esa clase que llaman `_handle_message` con un texto que trae el campo `Ingreso o Egreso` (`test_no_registra_movimiento_cuando_texto_no_trae_campo` no necesita el mock de `get_camara_estado_contexto`/`resolver_nombre_tecnico` porque corta antes de llegar ahí — dejarlo como está salvo que falle por el nuevo `client` requerido en `_construir_respuesta_camara`, que ya recibe `client_mock` sin cambios en la llamada a `_handle_message`).

Además, agregar un test nuevo cubriendo el camino de Intento bloqueado, al final de `TestRegistrarMovimientoIngreso`:

```python
    def test_grupo_baneado_registra_intento_bloqueado_no_ingreso(self) -> None:
        """Bug real que motivó esta tarea: un Ingreso a un grupo BANEADO debía cancelarse y
        registrarse como Intento bloqueado, no como un Ingreso 'en curso' — antes se registraba
        siempre, sin condicionar al resultado de la evaluación de acceso."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = self._make_camara()
        camara_mock.estado = CamaraEstado.BANEADA
        contexto_baneado = CamaraEstadoContexto(
            camara_id=camara_mock.id, estado_actual=CamaraEstado.BANEADA, estado_sugerido=CamaraEstado.BANEADA,
            tiene_baneo_activo=True, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Ruta 8 Km 34 MALVINAS ARGENTINAS",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "ruta 8 km 34 malvinas argentinas"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_baneado,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                return_value="Corte de fibra",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_nombre_tecnico",
                return_value="Rider Fernández",
            ),
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
            patch("modules.slack_baneo_notifier.listener.registrar_intento_bloqueado") as mock_intento,
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(self._make_event(text=self.TEXTO_CON_INGRESO), client_mock)

        mock_intento.assert_called_once_with(
            session_mock, camara=camara_mock, botella=None, tecnico_nombre="Rider Fernández"
        )
        mock_registrar.assert_not_called()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn(":no_entry:", texto_respuesta)

    def test_egreso_de_grupo_baneado_no_se_bloquea(self) -> None:
        """Un Egreso nunca se bloquea, incluso si el grupo está BANEADO — sólo Ingreso se convierte
        en Intento."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = self._make_camara()
        camara_mock.estado = CamaraEstado.BANEADA
        contexto_baneado = CamaraEstadoContexto(
            camara_id=camara_mock.id, estado_actual=CamaraEstado.BANEADA, estado_sugerido=CamaraEstado.BANEADA,
            tiene_baneo_activo=True, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Ruta 8 Km 34 MALVINAS ARGENTINAS",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "ruta 8 km 34 malvinas argentinas"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_baneado,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                return_value="Corte de fibra",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_nombre_tecnico",
                return_value="Rider Fernández",
            ),
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
            patch("modules.slack_baneo_notifier.listener.registrar_intento_bloqueado") as mock_intento,
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(self._make_event(text=self.TEXTO_CON_EGRESO), client_mock)

        mock_registrar.assert_called_once_with(
            session_mock, camara=camara_mock, botella=None, tipo_movimiento="Egreso",
            tecnico_nombre="Rider Fernández",
        )
        mock_intento.assert_not_called()
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `source .venv/bin/activate && pytest tests/test_slack_ingreso_listener.py -v 2>&1 | tail -60`
Expected: múltiples FAIL — `ImportError`/`AttributeError` por `get_camara_estado_contexto`/`resolver_nombre_tecnico`/`registrar_intento_bloqueado` no importados todavía en `listener.py`, y `TypeError` por el kwarg `tecnico_nombre` que `registrar_movimiento_ingreso` (mockeado) todavía no espera de ese modo en los tests viejos no actualizados.

- [ ] **Step 3: Implementar el fix**

En `modules/slack_baneo_notifier/listener.py`, actualizar los imports (líneas 24-59):

```python
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Optional

from core.services.camara_estado_service import (
    get_camara_estado_contexto,
    miembros_del_grupo,
    obtener_ultimo_motivo_baneo_manual,
)
from core.services.cromo.camara_botella_busqueda import buscar_camara_o_botella_cromo
from core.services.cromo.detalle import pelos_de_tubo_sync
from core.services.cromo.empalme_resolucion import resolver_botella_por_fusion_sync
from core.services.cromo.verificador import servicios_por_tubo_sync
from core.services.ingreso_service import registrar_intento_bloqueado, registrar_movimiento_ingreso
from db.models.cromo import CromoCable
from db.session import SessionLocal
from modules.slack_baneo_notifier.cable_info import (
    buscar_cable_por_n_id_o_nombre,
    construir_respuesta_ambiguo,
    construir_respuesta_buffer_no_encontrado,
    construir_respuesta_info_buffer,
    construir_respuesta_info_cable,
    construir_respuesta_no_encontrado,
    construir_respuesta_verificar_buffer,
    contar_buffers_cable,
    extraer_comando_cable_buffer,
    extraer_comando_info_cable,
    resolver_tubo_por_numero,
)
from modules.slack_baneo_notifier.camara_search import (
    AmbiguousSearchError,
    detectar_multi_bot,
    extraer_nombre_camara,
    extraer_slack_user_id_autorizacion,
    extraer_tipo_movimiento,
    limpiar_ruido_operativo,
)
from modules.slack_baneo_notifier.slack_user_resolver import resolver_nombre_tecnico

logger = logging.getLogger("slack_baneo_worker.listener")
```

(el resto del bloque de constantes `_RE_MENTION_PREFIX`, `_NOMBRE_SERVICIO_LISTENER`, etc. queda igual, sin cambios).

Agregar la dataclass nueva justo antes de `class IngresoListener:`:

```python
@dataclass(slots=True)
class _ResultadoAccesoCamara:
    """Resultado de evaluar si se puede ingresar a `camara` — separa el texto de respuesta de Slack
    del booleano `bloqueado`, que `_registrar_movimiento_si_corresponde` necesita para decidir entre
    un Ingreso real y un Intento bloqueado (Tarea 5, 2026-09-04)."""

    texto: str
    bloqueado: bool
```

Reemplazar `_construir_respuesta_camara` completa (líneas 142-226) por:

```python
    def _construir_respuesta_camara(
        self,
        nombre_buscado: str,
        session: Any,
        *,
        channel: str = "",
        thread_ts: str | None = None,
        texto_mensaje: str,
        client: Any,
    ) -> str:
        """Busca una cámara por nombre y construye el texto de respuesta.

        Aplica el filtro de ruido operativo antes de buscar y antes de registrar,
        descartando sufijos como '- CUADRILLA DE HIDROCONS' o '/ Móvil 4'.

        Desde la Tarea 2 del refactor de ingreso (2026-08-23), la búsqueda usa
        ``buscar_camara_o_botella_cromo()`` (no ``buscar_camara()`` directo): además de
        ``app.camaras``, cubre botellas que sólo existen en el inventario de Cromo (ver
        `core/services/cromo/camara_botella_busqueda.py`). Puede lanzar ``AmbiguousSearchError``,
        que no se captura acá — la maneja el caller (`_handle_message`).

        Si no encuentra nada en ninguna fuente, NUNCA bloquea el ingreso ni crea una `Camara` nueva
        (2026-08-11 — Cromo es la fuente de verdad del inventario; un caso sin match es un problema
        de escritura/regex, no una cámara faltante de alta). Registra el caso en `IngresoSinMatch`
        (junto con `thread_ts`, para poder detectar más tarde una respuesta de seguimiento con el ID
        de empalme más cercano — ver `_procesar_seguimiento_empalme`) para revisión manual posterior
        y mejora del regex, y responde dejando explícito que el técnico puede continuar igual —
        nunca lee como un rechazo. Si encuentra una cámara (propia o resuelta desde una
        `CromoBotella`), evalúa el estado de acceso vía `_evaluar_estado_acceso_camara` — ANTES de
        intentar ningún registro, para que la respuesta ya calculada quede inmune tanto a un fallo
        de escritura como al `expire_on_commit` de un commit exitoso — y luego, como efecto
        secundario final que nunca condiciona esa respuesta, registra el movimiento de Ingreso/
        Egreso/Intento bloqueado si el mensaje completo del evento (`texto_mensaje` — no
        `nombre_buscado`, que ya viene recortado al nombre de cámara) lo trae — ver
        `_registrar_movimiento_si_corresponde`.

        ``texto_mensaje`` es el texto completo del evento de Slack (no recortado como
        `nombre_buscado`) — los campos "Ingreso o Egreso" y "Persona que solicito La Autorizacion"
        del Workflow viven fuera del campo de nombre de cámara. ``client`` es el `slack_sdk.WebClient`
        inyectado por Bolt (Tarea 5, 2026-09-04) — se enhebra hasta `_registrar_movimiento_si_corresponde`
        para poder resolver el nombre real del técnico vía `resolver_nombre_tecnico`.
        """
        nombre_buscado = limpiar_ruido_operativo(nombre_buscado)
        resultado = buscar_camara_o_botella_cromo(nombre_buscado, session)
        camara = resultado.camara
        nombre_norm = resultado.nombre_norm
        logger.info(
            "Resultado búsqueda — cámara: %s (normalizado: '%s', fuente: %s)",
            camara,
            nombre_norm,
            resultado.fuente,
        )

        if camara is None:
            from db.models.infra import IngresoSinMatch

            caso = IngresoSinMatch(
                texto_original=nombre_buscado,
                origen="slack",
                contexto=channel or None,
                thread_ts=thread_ts,
            )
            session.add(caso)
            session.commit()
            logger.info(
                "Cámara '%s' sin match — registrado IngresoSinMatch id=%s para revisión manual",
                nombre_buscado,
                caso.id,
            )
            return (
                "⚠️ No pude confirmar automáticamente la cámara *{}* contra el inventario — "
                "quedó registrada para revisión manual (puede ser un error de tipeo o una "
                "diferencia de formato). *Podés continuar con el ingreso con normalidad.* "
                "Si conocés el ID de empalme más cercano, respondé en este mismo hilo sólo "
                "con el número."
            ).format(nombre_buscado)

        resultado_acceso = self._evaluar_estado_acceso_camara(camara, session)
        self._registrar_movimiento_si_corresponde(
            resultado, texto_mensaje, session, client, bloqueado=resultado_acceso.bloqueado
        )
        return resultado_acceso.texto

    def _registrar_movimiento_si_corresponde(
        self, resultado: Any, texto_mensaje: str, session: Any, client: Any, *, bloqueado: bool
    ) -> None:
        """Escribe Ingreso/Egreso/Intento bloqueado en DB si el mensaje trae el campo 'Ingreso o
        Egreso' parseable. Nunca lanza — cualquier excepción se loguea y se ignora, la respuesta de
        Slack no debe bloquearse porque falle la escritura en DB.

        Un movimiento "Ingreso" sobre un grupo bloqueado (`bloqueado=True`, calculado por
        `_evaluar_estado_acceso_camara` vía `get_camara_estado_contexto`) se registra como
        `registrar_intento_bloqueado` en vez de `registrar_movimiento_ingreso` — Tarea 5, 2026-09-04.
        Un "Egreso" nunca se bloquea, incluso sobre un grupo BANEADO (salir sigue permitido).

        Si el registro falla después de que su `commit()` ya arrancó la transacción (o por cualquier
        otro error de DB), SQLAlchemy deja la `session` — compartida por el resto de
        `_handle_message`, incluida una eventual llamada a `_construir_respuesta_camara` para el
        próximo nombre en un caso multi-botella — en estado "inactivo": cualquier operación posterior
        sobre ella relanza `PendingRollbackError` hasta que se haga un `rollback()` explícito. Sin
        este `rollback()`, un solo fallo de escritura podía dejar sin respuesta a TODO el mensaje de
        Slack (no sólo a la fila que falló) — viola la garantía de nunca bloquear/romper la respuesta
        por un fallo de DB."""
        tipo = extraer_tipo_movimiento(texto_mensaje)
        if tipo is None:
            return
        slack_user_id = extraer_slack_user_id_autorizacion(texto_mensaje)
        tecnico_nombre = resolver_nombre_tecnico(client, slack_user_id)
        try:
            if bloqueado and tipo == "Ingreso":
                registrar_intento_bloqueado(
                    session,
                    camara=resultado.camara,
                    botella=resultado.botella,
                    tecnico_nombre=tecnico_nombre,
                )
                return
            registrar_movimiento_ingreso(
                session,
                camara=resultado.camara,
                botella=resultado.botella,
                tipo_movimiento=tipo,
                tecnico_nombre=tecnico_nombre,
            )
        except Exception as exc:
            try:
                session.rollback()
            except Exception:
                pass
            logger.warning("No se pudo registrar movimiento de ingreso: %s", exc, exc_info=True)

    def _evaluar_estado_acceso_camara(self, camara: Any, session: Any) -> _ResultadoAccesoCamara:
        """Evalúa el estado de acceso de una `Camara` ya resuelta (raíz o Botella) y arma el texto de
        respuesta — GRUPO-CONSCIENTE desde esta revisión (Tarea 5, 2026-09-04): reusa
        `get_camara_estado_contexto()` (`core/services/camara_estado_service.py`), que evalúa
        incidentes Y baneo manual sobre TODO el grupo (cámara padre + botellas hermanas), en vez de
        la versión anterior que sólo miraba el `estado`/incidentes de la fila puntual resuelta — bug
        real: pedir ingreso a la cámara raíz mientras una Botella hermana estaba BANEADA respondía
        "OK" porque nunca se consultaba el grupo. Ver el fix equivalente en
        `camara_estado_service.get_camara_estado_contexto` (Task 3 de este plan).

        Jerarquía (sin cambios de negocio, sólo de alcance — ahora sobre el grupo completo):

        1. Incidente de red activo (``IncidenteBaneo.activo``) en cualquier miembro del grupo → 🚨 ATENCIÓN.
        2. Baneo manual (``estado == BANEADA``) sin incidente activo, en cualquier miembro del grupo
           → :no_entry: con el motivo extraído de ``camaras_estado_auditoria`` del miembro baneado
           (no siempre `camara` misma — puede ser una Botella hermana).
        3. Cualquier otro estado → ✅ podés proceder.
        """
        from db.models.infra import CamaraEstado

        contexto = get_camara_estado_contexto(session, camara.id)
        if contexto is None:
            logger.warning("get_camara_estado_contexto devolvió None para camara_id=%s ya resuelta", camara.id)
            return _ResultadoAccesoCamara(
                texto=(
                    f"✅ Cámara *{camara.nombre}* registrada en el sistema. "
                    f"Sin incidentes activos.\n_puede continuar con el proceso de aprobación._"
                ),
                bloqueado=False,
            )

        if contexto.incidentes_activos:
            inc = contexto.incidentes_activos[0]
            logger.info("Cámara '%s' BANEADA — incidente #%s", camara.nombre, inc.id)
            return _ResultadoAccesoCamara(
                texto=(
                    f"🚨 *ATENCIÓN* — La cámara *{camara.nombre}* tiene el incidente "
                    f"*#{inc.id}* activo (Baneo de Protección).\n"
                    f"Ticket: {inc.ticket_asociado or 'sin ticket'} | "
                    f"Servicio protegido: {inc.servicio_protegido_id}\n"
                    "_No acceder a esta cámara hasta nuevo aviso._"
                ),
                bloqueado=True,
            )

        if contexto.tiene_baneo_activo:
            # tiene_baneo_activo=True sin incidentes_activos sólo puede ser baneo manual (ver Task 3)
            # — el miembro baneado no siempre es `camara` misma (puede ser una Botella hermana).
            miembro_baneado = next(
                (m for m in miembros_del_grupo(camara) if m.estado == CamaraEstado.BANEADA), camara
            )
            motivo = obtener_ultimo_motivo_baneo_manual(session, miembro_baneado.id)
            motivo_texto = motivo or "sin motivo registrado"
            detalle_miembro = (
                f" (Botella *{miembro_baneado.nombre}* del mismo grupo)"
                if miembro_baneado.id != camara.id
                else ""
            )
            logger.info(
                "Cámara '%s' BANEADA manualmente (miembro '%s' del grupo) — sin incidente activo, motivo: '%s'",
                camara.nombre,
                miembro_baneado.nombre,
                motivo_texto,
            )
            return _ResultadoAccesoCamara(
                texto=(
                    f":no_entry: La cámara *{camara.nombre}*{detalle_miembro} fue baneada manualmente. "
                    f"Motivo: _{motivo_texto}_.\n"
                    "_No podés proceder con el ingreso._"
                ),
                bloqueado=True,
            )

        logger.info("Cámara '%s' OK — sin incidentes activos", camara.nombre)
        return _ResultadoAccesoCamara(
            texto=(
                f"✅ Cámara *{camara.nombre}* registrada en el sistema. "
                f"Sin incidentes activos.\n_puede continuar con el proceso de aprobación._"
            ),
            bloqueado=False,
        )
```

Actualizar `_procesar_seguimiento_empalme` (la llamada a `_evaluar_estado_acceso_camara`, dentro del bloque `if camara is not None:`):

```python
        if camara is not None:
            resultado_acceso = self._evaluar_estado_acceso_camara(camara, session)
            respuesta = resultado_acceso.texto
        else:
```

Actualizar la construcción de `respuestas` dentro de `_handle_message` (agregar `client=client`):

```python
            respuestas = [
                self._construir_respuesta_camara(
                    nombre, session, channel=channel, thread_ts=thread_ts, texto_mensaje=texto, client=client
                )
                for nombre in nombres_a_buscar
            ]
```

Eliminar por completo la función `_obtener_incidentes_activos_camara` (código muerto — antes al final del archivo, sección `# ── Helpers ──`).

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `source .venv/bin/activate && pytest tests/test_slack_ingreso_listener.py -v 2>&1 | tail -80`
Expected: todos los tests del archivo pasan (0 failed).

- [ ] **Step 5: Correr la suite completa relacionada para descartar regresiones cruzadas**

Run: `source .venv/bin/activate && pytest tests/test_slack_ingreso_listener.py tests/test_ingreso_service.py tests/test_camara_estado_service.py tests/test_slack_user_resolver.py -v 2>&1 | tail -20`
Expected: 0 failed.

- [ ] **Step 6: Commit**

```bash
git add modules/slack_baneo_notifier/listener.py tests/test_slack_ingreso_listener.py
git commit -m "fix(slack): chequeo de acceso grupo-consciente + Intento bloqueado + nombre real del técnico"
```

---

### Task 6: Serializador del endpoint `/registros` — `botella_label` + `tipo`

**Files:**
- Modify: `web/app/main.py:2108-2116` (`_serialize_camara_ingreso`)
- Test: `tests/test_web_infra_camera_state.py`

**Interfaces:**
- Consumes: `Ingreso.tipo`, `Ingreso.cromo_botella` (Task 1).
- Produces: `_serialize_camara_ingreso(item) -> dict` — agrega las keys `"botella_label": str` y `"tipo": str` al payload existente (`id`, `fecha_inicio`, `fecha_fin`, `tecnico_id`, `cromo_botella_id` quedan igual).

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_web_infra_camera_state.py`, agregar al final del archivo:

```python
def test_get_camara_registros_web_incluye_botella_label_y_tipo(monkeypatch):
    """Task 6: `botella_label` cae a 'Botella 1' cuando no hay `cromo_botella_id` ni la propia
    Cámara es una Botella (caso más común, técnico no especificó botella); usa el nombre de la
    `CromoBotella` cuando sí está poblado; `tipo` refleja INTENTO_BLOQUEADO cuando corresponde."""
    from core.services import camara_estado_service
    from db import session as db_session
    from db.models.infra import IngresoTipo

    client = TestClient(app)
    _login(client, monkeypatch, role="user", password="userpass")

    ingresos = [
        SimpleNamespace(
            id=5,
            fecha_inicio=datetime(2026, 5, 10, 8, 0, tzinfo=timezone.utc),
            fecha_fin=None,
            tecnico_id="tecnico.lopez",
            cromo_botella_id=None,
            camara=_build_fake_camara(),
            tipo=IngresoTipo.INGRESO,
        ),
        SimpleNamespace(
            id=6,
            fecha_inicio=datetime(2026, 5, 11, 9, 0, tzinfo=timezone.utc),
            fecha_fin=None,
            tecnico_id="Rider Fernández",
            cromo_botella_id=999,
            camara=_build_fake_camara(),
            cromo_botella=SimpleNamespace(nombre="Bot 2 Cra Mitre 440"),
            tipo=IngresoTipo.INTENTO_BLOQUEADO,
        ),
    ]
    fake_session = _InfraDetailSession(
        _build_fake_camara(), _build_aliases(), _build_auditoria(), _build_baneos(), ingresos
    )
    monkeypatch.setattr(db_session, "SessionLocal", _SessionScope(fake_session))
    monkeypatch.setattr(camara_estado_service, "get_camara_estado_contexto", lambda session, camara_id: _build_contexto())

    response = client.get("/api/infra/camaras/7/registros")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingresos"][0]["botella_label"] == "Botella 1"
    assert payload["ingresos"][0]["tipo"] == "INGRESO"
    assert payload["ingresos"][1]["botella_label"] == "Bot 2 Cra Mitre 440"
    assert payload["ingresos"][1]["tipo"] == "INTENTO_BLOQUEADO"
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `source .venv/bin/activate && pytest tests/test_web_infra_camera_state.py::test_get_camara_registros_web_incluye_botella_label_y_tipo -v`
Expected: FAIL — `KeyError: 'botella_label'`

- [ ] **Step 3: Implementar el fix**

En `web/app/main.py`, reemplazar `_serialize_camara_ingreso` (líneas 2108-2116):

```python
def _serialize_camara_ingreso(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "fecha_inicio": item.fecha_inicio.isoformat() if item.fecha_inicio else None,
        "fecha_fin": item.fecha_fin.isoformat() if item.fecha_fin else None,
        "tecnico_id": item.tecnico_id,
        "cromo_botella_id": item.cromo_botella_id,
    }
```

por:

```python
def _serialize_camara_ingreso(item: Any) -> dict[str, Any]:
    """`botella_label` (Tarea 6, 2026-09-04) resuelve el nombre legible de la Botella intervenida —
    reemplaza el fallback "Sin botella asociada" del frontend (`ModalRegistros.vue`), que mostraba el
    `n_id` crudo o ese texto sin distinguir "no se especificó botella" (= la Cámara raíz, "Botella 1"
    por convención — ver `camara_search.detectar_multi_bot`) de "se especificó una Botella legado sin
    CromoBotella asociada". `getattr` defensivo: tolera objetos de test (`SimpleNamespace`) sin
    `.camara`/`.tipo` poblados, cayendo a los defaults más comunes."""
    if item.cromo_botella_id is not None:
        cromo_botella = getattr(item, "cromo_botella", None)
        botella_label = cromo_botella.nombre if cromo_botella is not None else f"Botella #{item.cromo_botella_id}"
    elif getattr(getattr(item, "camara", None), "camara_padre_id", None):
        botella_label = item.camara.nombre
    else:
        botella_label = "Botella 1"

    tipo = getattr(item, "tipo", None)
    return {
        "id": item.id,
        "fecha_inicio": item.fecha_inicio.isoformat() if item.fecha_inicio else None,
        "fecha_fin": item.fecha_fin.isoformat() if item.fecha_fin else None,
        "tecnico_id": item.tecnico_id,
        "cromo_botella_id": item.cromo_botella_id,
        "botella_label": botella_label,
        "tipo": tipo.value if tipo else "INGRESO",
    }
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `source .venv/bin/activate && pytest tests/test_web_infra_camera_state.py -v`
Expected: todos los tests del archivo pasan, incluido el nuevo.

- [ ] **Step 5: Commit**

```bash
git add web/app/main.py tests/test_web_infra_camera_state.py
git commit -m "feat(web): endpoint /registros expone botella_label y tipo de Ingreso"
```

---

### Task 7: Frontend — `ModalRegistros.vue` + `CamaraDetailView.vue`

**Files:**
- Modify: `web/frontend/src/components/infra/ModalRegistros.vue`
- Modify: `web/frontend/src/views/CamaraDetailView.vue:247-253`

**Interfaces:**
- Consumes: `botella_label: string`, `tipo: string` en cada item de `ingresos` (Task 6).

- [ ] **Step 1: Actualizar la interface `RegistrosIngreso` en `CamaraDetailView.vue`**

En `web/frontend/src/views/CamaraDetailView.vue`, reemplazar (líneas 247-253):

```typescript
interface RegistrosIngreso {
  id: number;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  tecnico_id: string | null;
  cromo_botella_id: number | null;
}
```

por:

```typescript
interface RegistrosIngreso {
  id: number;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  tecnico_id: string | null;
  cromo_botella_id: number | null;
  botella_label: string;
  tipo: string;
}
```

- [ ] **Step 2: Actualizar `ModalRegistros.vue` — interface, template y helpers de título**

En `web/frontend/src/components/infra/ModalRegistros.vue`, reemplazar la interface `IngresoItem` (líneas 192-198):

```typescript
interface IngresoItem {
  id: number;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  tecnico_id: string | null;
  cromo_botella_id: number | null;
}
```

por:

```typescript
interface IngresoItem {
  id: number;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  tecnico_id: string | null;
  cromo_botella_id: number | null;
  botella_label: string;
  tipo: string;
}
```

Reemplazar `buildIngresoRangeTitle` (líneas 262-266):

```typescript
function buildIngresoRangeTitle(item: IngresoItem): string {
  const ingreso = formatFechaCompacta(item.fecha_inicio);
  const egreso = item.fecha_fin ? formatFechaCompacta(item.fecha_fin) : 'En curso';
  return `Ingreso - ${ingreso} * Egreso - ${egreso}`;
}
```

por:

```typescript
function buildIngresoRangeTitle(item: IngresoItem): string {
  if (item.tipo === 'INTENTO_BLOQUEADO') {
    return `Intento bloqueado - ${formatFechaCompacta(item.fecha_inicio)}`;
  }
  const ingreso = formatFechaCompacta(item.fecha_inicio);
  const egreso = item.fecha_fin ? formatFechaCompacta(item.fecha_fin) : 'En curso';
  return `Ingreso - ${ingreso} * Egreso - ${egreso}`;
}
```

Reemplazar el bloque del template de la pestaña "Ingresos" (líneas 66-85):

```html
        <div v-else class="infra-baneos-list">
          <AccordionItem
            v-for="ingreso in sortedIngresos"
            :key="ingreso.id"
            :model-value="expandedIngresoId === ingreso.id"
            :title="buildIngresoRangeTitle(ingreso)"
            @update:model-value="toggleIngreso(ingreso.id, $event)"
          >
            <dl class="infra-baneo-detail-grid">
              <div class="infra-baneo-detail-row">
                <dt>Técnico</dt>
                <dd>{{ ingreso.tecnico_id || 'Sin técnico identificado' }}</dd>
              </div>
              <div class="infra-baneo-detail-row">
                <dt>Botella asociada</dt>
                <dd>{{ ingreso.cromo_botella_id ?? 'Sin botella asociada' }}</dd>
              </div>
            </dl>
          </AccordionItem>
        </div>
```

por:

```html
        <div v-else class="infra-baneos-list">
          <AccordionItem
            v-for="ingreso in sortedIngresos"
            :key="ingreso.id"
            :model-value="expandedIngresoId === ingreso.id"
            :title="buildIngresoRangeTitle(ingreso)"
            @update:model-value="toggleIngreso(ingreso.id, $event)"
          >
            <span
              v-if="ingreso.tipo === 'INTENTO_BLOQUEADO'"
              class="infra-state-chip danger"
              style="margin-bottom: 12px; display: inline-block"
            >
              Intento bloqueado por baneo
            </span>
            <dl class="infra-baneo-detail-grid">
              <div class="infra-baneo-detail-row">
                <dt>Técnico</dt>
                <dd>{{ ingreso.tecnico_id || 'Sin técnico identificado' }}</dd>
              </div>
              <div class="infra-baneo-detail-row">
                <dt>Botella asociada</dt>
                <dd>{{ ingreso.botella_label }}</dd>
              </div>
            </dl>
          </AccordionItem>
        </div>
```

- [ ] **Step 3: Levantar el dev server y verificar visualmente**

Run: `source .venv/bin/activate` (si aplica) y seguir el protocolo de `dev-workflow`/`docker-rebuild` para levantar `lasfocasdev-web` con el build de frontend actualizado (ver Task 9 — la verificación real de este paso se hace en conjunto con el rebuild final, no hace falta un ciclo de rebuild separado sólo para esto).

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/components/infra/ModalRegistros.vue web/frontend/src/views/CamaraDetailView.vue
git commit -m "feat(web): frontend muestra botella_label resuelto e Intento bloqueado"
```

---

### Task 8: Documentación — `docs/bot.md` + `docs/infra.md`

**Files:**
- Modify: `docs/bot.md:225-241`
- Modify: `docs/infra.md:95-105`

**Interfaces:**
- Consumes: nada (sólo prosa, no código).

- [ ] **Step 1: Actualizar `docs/bot.md`**

En `docs/bot.md`, ubicar la sección `### Registro de movimiento Ingreso/Egreso (desde 2026-08-31)` (línea 225) y, después del párrafo que termina en `...y cualquier excepción se loguea (\`logger.warning\`) y se ignora...` (línea 241), agregar:

```markdown
**Actualización 2026-09-04 (Tarea de fix baneo/Slack):**

- **Nombre real del técnico**: antes de persistir, el listener resuelve `slack_user_id` al nombre
  visible del técnico vía `modules/slack_baneo_notifier/slack_user_resolver.py::resolver_nombre_tecnico`
  (llama `client.users_info` — el mismo `WebClient` que Bolt ya inyecta en el handler, sin token
  nuevo). Requiere el scope `users:read` en la Slack App (verificar en el panel de Slack). Si la
  llamada falla (scope faltante, usuario borrado, timeout), cae al ID crudo — el registro nunca se
  bloquea por esto. `Ingreso.tecnico_id` ahora almacena ese nombre resuelto, no ya el ID crudo.
- **Chequeo de acceso grupo-consciente**: `_evaluar_estado_acceso_camara` dejó de mirar sólo el
  `estado`/incidentes de la fila puntual resuelta — ahora reusa
  `core/services/camara_estado_service.get_camara_estado_contexto()`, que evalúa incidentes Y baneo
  manual sobre TODO el grupo (cámara padre + botellas hermanas). Bug real corregido: pedir ingreso a
  la cámara raíz mientras una Botella hermana estaba BANEADA respondía "OK".
- **Intento bloqueado**: si el chequeo de acceso determina que el grupo está bloqueado (incidente
  activo o baneo manual) y el movimiento es "Ingreso", el listener llama
  `core/services/ingreso_service.py::registrar_intento_bloqueado` en vez de
  `registrar_movimiento_ingreso` — la fila queda con `tipo=INTENTO_BLOQUEADO`, `fecha_fin=NULL`
  (nunca hubo egreso porque nunca hubo ingreso real). Un "Egreso" nunca se bloquea, incluso sobre un
  grupo BANEADO. `Ingreso.tipo` (INGRESO/EGRESO/INTENTO_BLOQUEADO, migración `20260904_01`) es lo que
  distingue esto de un Ingreso real "en curso" con el mismo `fecha_fin IS NULL` — tanto
  `tiene_ingreso_activo` (`camara_estado_service.py`) como el cierre de Egreso NULL-safe
  (`ingreso_service.py`) filtran explícitamente `tipo == INGRESO`.
```

- [ ] **Step 2: Actualizar `docs/infra.md`**

En `docs/infra.md`, ubicar el párrafo que empieza en `**Escritura de \`Ingreso\` sobre el grupo** (2026-08-31)` (línea 95) y, después de la oración que termina en `...consistente con \`tiene_ingreso_activo\` de \`camara_estado_service.py\`.` (línea 104), agregar:

```markdown
**Actualización 2026-09-04:** `tiene_baneo_activo` (`get_camara_estado_contexto`) tenía un bug real —
sólo miraba `IncidenteBaneo` activo, nunca `Camara.estado == BANEADA` de ningún miembro del grupo. Un
baneo manual (override admin/import Excel, sin incidente de protección asociado) quedaba invisible
tanto para el badge "Contexto operativo" (`ModalRegistros.vue`) como para el chequeo de acceso del
listener de Slack de ingreso. Corregido: `tiene_baneo_activo` ahora también es `True` cuando cualquier
miembro de `miembros_del_grupo(camara)` tiene `estado == BANEADA`, incidente o no. `tiene_ingreso_activo`
ahora filtra explícitamente `Ingreso.tipo == 'INGRESO'` (columna nueva, migración `20260904_01`) para no
contar un `INTENTO_BLOQUEADO` (mismo `fecha_fin IS NULL`) como si alguien estuviera realmente adentro.

`GET /api/infra/camaras/{id}/registros` expone además `botella_label` por cada `Ingreso` — resuelve
"Botella 1" (convención ya usada por `camara_search.detectar_multi_bot`: la Cámara raíz misma, sin fila
propia en `CromoBotella`) cuando no se especificó botella, el nombre de la `CromoBotella` cuando sí hay
`cromo_botella_id`, o el nombre de la Botella legado (self-FK) cuando la fila de `Ingreso.camara_id`
apunta directo a una Botella sin `CromoBotella` asociada.
```

- [ ] **Step 3: Commit**

```bash
git add docs/bot.md docs/infra.md
git commit -m "docs: actualizar bot.md e infra.md con el fix de baneo/Intento bloqueado (2026-09-04)"
```

---

### Task 9: Verificación E2E real (migración aplicada + contenedores reconstruidos + curl real)

**Files:** ninguno (sólo comandos de verificación).

- [ ] **Step 1: Correr la suite completa de tests afectados**

Run: `source .venv/bin/activate && pytest tests/test_ingreso_service.py tests/test_camara_estado_service.py tests/test_slack_ingreso_listener.py tests/test_slack_user_resolver.py tests/test_web_infra_camera_state.py -v`
Expected: 0 failed.

- [ ] **Step 2: Aplicar la migración contra la DB de dev real**

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev exec api alembic upgrade head
```

Expected: log muestra `20260902_01 -> 20260904_01, Enum ingreso_tipo + columna ingresos.tipo` sin error. Verificar la columna:

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev exec postgres psql -U lasfocas -d lasfocas -c "\d app.ingresos"
```

Expected: la salida incluye la columna `tipo` de tipo `app.ingreso_tipo` `NOT NULL`.

- [ ] **Step 3: Identificar y reconstruir el/los contenedor(es) que corren el listener de Slack**

```bash
docker compose -f docker-compose.dev.yml config --services
grep -rn "slack_baneo_notifier\|IngresoListener" docker-compose.dev.yml Dockerfile* 2>/dev/null
```

Reconstruir el contenedor identificado (worker que importa `modules/slack_baneo_notifier`) y `lasfocasdev-web` (sirve el endpoint `/registros` y el frontend), vía la skill `docker-rebuild` (`Skill(skill="docker-rebuild")`) — **no** improvisar comandos `docker build` sueltos, seguir el procedimiento de esa skill (versiones fijas, no tocar `postgres_data`).

- [ ] **Step 4: Verificar contra el sistema real — endpoint `/registros`**

Con una Cámara real de dev que tenga al menos un `Ingreso`:

```bash
curl -s -b cookies.txt http://localhost:<puerto-web>/api/infra/camaras/<id-real>/registros | python -m json.tool | grep -A2 '"botella_label"'
```

Expected: cada objeto de `ingresos` trae `botella_label` (nunca `null`) y `tipo` (`INGRESO`/`EGRESO`/`INTENTO_BLOQUEADO`).

- [ ] **Step 5: Verificar contra el sistema real — badge de baneo heredado**

Elegir en dev un grupo Cámara+Botellas donde sólo una Botella esté `BANEADA` manualmente (sin incidente activo) — si no existe uno, crear el caso de prueba vía el panel admin (override de estado) sobre una cámara de prueba, o vía `docker compose exec api python` llamando `aplicar_estado_a_grupo` sobre una botella de test. Confirmar:

```bash
curl -s -b cookies.txt http://localhost:<puerto-web>/api/infra/camaras/<id-raiz>/registros | python -m json.tool | grep -A1 '"tiene_baneo_activo"'
```

Expected: `"tiene_baneo_activo": true` aunque `estado_actual` de la cámara raíz consultada sea `LIBRE`.

- [ ] **Step 6: Revertir cualquier estado de prueba creado en el Step 5**

Si se creó un baneo de prueba en el Step 5, revertirlo vía `aplicar_estado_a_grupo` (nunca `UPDATE` directo — ver guardrail de `baneo-qa-real` en `CLAUDE.md`) antes de cerrar la tarea.

- [ ] **Step 7: Commit final (si Step 3 generó cambios de config, ej. Dockerfile)**

```bash
git status
# Sólo si hubo cambios reales de config detectados en el Step 3:
git add -A
git commit -m "chore(docker): ajustes de rebuild para el fix de baneo/Slack"
```

---

## Self-Review

**1. Cobertura del ticket:**
- Bug 1 (Ingreso no bloqueado en DB) → Task 5 (`bloqueado` + `registrar_intento_bloqueado`) + Task 1 (columna `tipo`).
- Bug 2 (ID crudo de Slack) → Task 2 (`resolver_nombre_tecnico`) + Task 5 (wiring).
- Bug 3 (sin fallback "Botella 1") → Task 6 (`botella_label`) + Task 7 (frontend).
- Bug 4 (badge no hereda baneo de botellas) → Task 3 (`get_camara_estado_contexto` grupo-consciente) + Task 5 (listener reusa la misma función).
- Paso propuesto "Migración Alembic" → Task 1. "Integración Slack API" → Task 2. "Lógica de Intento" → Task 4 + 5. "Fallback de Botella" → Task 6. "Cálculo backend del badge" → Task 3 (corrige el campo YA existente en vez de agregar uno duplicado — premisa corregida arriba). "Ajuste Frontend" → Task 7 (el frontend ya sólo renderiza el backend; se ajusta el campo consumido).
- "Actualizar documentación relacionada" → Task 8. "Actualizar info que no contrasta con la actualidad" → aplicado en Task 3 (fix de `tiene_baneo_activo`, no nueva feature) y documentado explícitamente en Task 8.

**2. Placeholders:** ninguno — cada step trae código completo o el comando exacto a correr.

**3. Consistencia de tipos:** `registrar_movimiento_ingreso(..., tecnico_nombre: str | None)` (Task 4) es exactamente el nombre que usa el único caller (Task 5). `_ResultadoAccesoCamara(texto: str, bloqueado: bool)` (Task 5) es el tipo que consume `_construir_respuesta_camara` (`.texto`, `.bloqueado`) y `_procesar_seguimiento_empalme` (`.texto`). `IngresoTipo` (Task 1) es el mismo import (`db.models.infra.IngresoTipo`) en Task 3, 4 y los tests de Task 6.
