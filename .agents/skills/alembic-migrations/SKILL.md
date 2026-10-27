---
name: alembic-migrations
description: "Usar cuando haya que crear, revisar o aplicar migraciones Alembic y validar cambios de esquema en la base de datos"
argument-hint: "Describe cambio de esquema, por ejemplo: agregar columna email_subject a incidentes_baneo"
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agents/skills/alembic-migrations/SKILL.md
# Descripción: Habilidad para gestionar migraciones Alembic en LAS-FOCAS (mirror Agent Skills de .agentes-comunes/skills/alembic-migrations/SKILL.md — fuente de verdad)

# Habilidad: Migraciones Alembic

Guía breve para crear, validar y aplicar migraciones Alembic sin sobrecargar el contexto base.

## Cuándo usar

- cuando haya cambios de esquema en `db/models/`
- cuando se necesite crear una migración manual o autogenerada
- cuando haga falta revisar rollback, SQL generado o troubleshooting Alembic

## Procedimiento

1. Revisar estado actual de migraciones.
2. Declarar el cambio en el modelo y generar la migración con `revision --autogenerate -m "..."`
   contra la DB de dev (encendido desde 2026-10-27, P18). Revisar lo generado: renombrar el archivo
   y completar el encabezado de 3 líneas (la plantilla deja `<slug>`), y escribir a mano lo que el
   autogenerate no ve (datos, `CONCURRENTLY`, triggers, `IF EXISTS` cuando prod puede diferir).
   Antes y después: `python scripts/check_drift_modelos.py` tiene que dar 0 (ver gotcha 5).
3. Implementar `upgrade()` y `downgrade()`.
4. Validar con `--sql` y aplicar solo si corresponde.
5. Actualizar `docs/db.md` o PR diario cuando el cambio tenga impacto visible.
6. Regenerar la tabla "Historial de migraciones" de `docs/db.md` (está entre los marcadores
   `<!-- tabla-migraciones:inicio/fin -->` y no se edita a mano): correr
   `python scripts/gen_tabla_migraciones.py` y pegar la salida entre los marcadores, y después
   `python scripts/gen_tabla_migraciones.py --verificar docs/db.md`, que tiene que salir con 0.
   Su stderr además avisa de heads múltiples o `down_revision` colgadas. Antes de 2026-10-26 la
   tabla se mantenía a mano y le faltaban 25 de 72 migraciones (ver `docs/cierres/2026-10-26.md`).

## Referencias

- [Recetas y operaciones comunes](../../../.agentes-comunes/skills/alembic-migrations/references/recetas.md)
- [Prompt de migración](../../prompts/migracion-alembic.prompt.md)

## Guardrails

1. Toda migración debe preservar datos salvo advertencia explícita.
2. Toda migración debe incluir `downgrade()` salvo excepción justificada.
3. Revisar SQL antes de aplicar cambios delicados en entornos reales.
3b. **Una columna `JSONB` que deba distinguir "sin dato" de "vacío" necesita `none_as_null=True`
   explícito en el modelo.** Por defecto SQLAlchemy serializa Python `None` como el **escalar JSON
   `null`**, no como SQL NULL: entonces `IS NOT NULL` da TRUE, cualquier función de array
   (`jsonb_array_length`) **aborta la consulta entera** con *"cannot get array length of a scalar"*,
   y los tres estados que la columna pretendía modelar colapsan en dos. Hallazgo real (2026-09-17,
   `cromo_splitter_puertos.servicios_atributo`): no lo detecta ningún test con mocks, sólo aparece
   al correr contra la base. Como cinturón, filtrar por `jsonb_typeof(col) = 'array'` antes de
   llamar a una función de array, en vez de confiar sólo en `IS NOT NULL`.
4. Si el cambio de esquema modifica el SIGNIFICADO de un campo/función ya existente y ampliamente
   consumido (no sólo agrega uno nuevo), grep-auditar TODOS los consumidores reales de ese campo/función
   en el repo — no sólo los que la tarea o el plan ya tocan — antes de dar el cambio por completo.
   Hallazgo real (2026-09-04, ver `docs/cierres/2026-09-04.md`): ampliar el significado de
   `tiene_baneo_activo` en `get_camara_estado_contexto()` fue correcto para sus consumidores previstos
   (badge web, listener de Slack), pero rompió silenciosamente `baneos_grupos_service.py` (panel admin
   de baneos activos), un consumidor preexistente nunca auditado por el plan de esa tarea — sólo lo
   detectó una revisión final de rama completa, no las revisiones acotadas por tarea.
5. **Correr alembic desde el host contra dev: `-c db/alembic.ini` + `DATABASE_URL`/`ALEMBIC_URL`.**
   `db/alembic/env.py` toma la URL con precedencia `DATABASE_URL > ALEMBIC_URL > ini` e **ignora
   `POSTGRES_HOST/PORT/...`** (las que sí usan `db/session.py` y los tests `*_real_db`). Dev está
   publicado en `127.0.0.1:5433`; prod en `5432`. Antes de `upgrade`, correr `alembic -c
   db/alembic.ini current` y confirmar el head esperado de **dev** — si no coincide, detenerse.
   La contraseña se lee de `.secrets/Dev_db_password_v1.txt` dentro de la URL, nunca impresa.
   **Autogenerate encendido desde 2026-10-27 (P18)**: `env.py` usa `Base.metadata` con el alcance
   de `db/models/autogenerate.py` (sólo `app`, sin las 7 tablas listadas en `TABLAS_SIN_MODELO`,
   comparando tipos y `server_default`). Los modelos se alinearon con dev (149 diferencias → 0): la
   convención `ix_<tabla>_<columnas>` en `db/base.py`, `Index(...)` explícito cuando el nombre real
   es otro, y `server_default`/comentarios iguales a los de la base. Reglas para no reabrir el drift:
   (a) todo índice/constraint/default creado por migración se declara también en el modelo, con el
   mismo nombre; (b) `alembic check` (o `scripts/check_drift_modelos.py --detalle`) tiene que dar 0
   antes de integrar, y `tests/test_drift_modelos_real_db.py` lo exige contra dev; (c) una tabla sin
   modelo se agrega a `TABLAS_SIN_MODELO`, nunca a un filtro genérico. **Dev no es la cadena**: dev
   tenía nombres y defaults que las migraciones no crean, así que una base nueva difería en 9 puntos
   (normalizados por `20261027_02`). `scripts/check_drift_desde_cero.sh` migra un Postgres efímero
   desde cero y exige drift 0; corre local (no está en GitHub Actions, por decisión del usuario).
   Antes de P18, `env.py` tenía `target_metadata = None` y la plantilla `script.py.mako` usaba
   `${repr(revision)}` y `pass` fijo: `alembic revision` fallaba y el autogenerate descartaba lo
   detectado (ver `docs/cierres/2026-10-05.md` y `docs/PR/2026-10-27.md`).
6. **Una migración de una rama SIN integrar aplicada al Postgres de dev compartido bloquea a las
   demás ramas.** El dev DB queda en un head que `dev` (y toda rama que parte de él) no conoce:
   `alembic upgrade` de otra rama falla ("Can't locate revision"), y si esa rama también encadenó
   sobre el head anterior, al integrar quedan dos heads. Si hace falta aplicarla para probar en dev,
   integrar la rama pronto o avisar al agente afectado (`/estado-agentes`, `SendMessage`); quien
   integra después reencadena su primera migración (`down_revision`) sobre el head ya integrado.
   Hallazgo real (2026-10-17, ver `docs/cierres/2026-10-17.md`): `20261014_02` (FO Monitor) estuvo
   3 días aplicada en dev sin integrar y frenó a `claude-tramos` (`20261016_01..04` sobre `20261014_01`).
7. **Una tabla de auditoría append-only (trigger `BEFORE UPDATE OR DELETE` que hace `RAISE`) no puede
   tener FKs con `ON DELETE SET NULL` ni `CASCADE`.** El `SET NULL` de una FK se ejecuta como un
   `UPDATE`: el trigger lo rechaza y **el borrado de la fila referenciada falla**. Eso bloquea, por
   ejemplo, el merge de Cámaras, que borra la secundaria. En una auditoría inmutable, los ids son
   históricos: van sin FK y con índice. Hallazgo real (2026-10-23, `app.ingresos_correcciones`, migración
   `20261023_01`): latente desde `20260923_01`, y se volvía frecuente al registrar `camara_id_anterior`
   en cada "mover ingreso". Se confirmó recreando la FK en una transacción revertida: el borrado falló
   con el error "append-only" del trigger.
