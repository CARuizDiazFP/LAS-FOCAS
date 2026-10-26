# Nombre de archivo: README.md
# Ubicación de archivo: scripts/README.md
# Descripción: Inventario por categoría y convenciones de los scripts utilitarios

## Scripts utilitarios

Este directorio contiene herramientas auxiliares no incluidas en la ejecución principal de los microservicios.

### Inventario por categoría

Una línea por archivo, tomada del encabezado o docstring de cada script. No existe
`scripts/historico/`: los scripts de uso único conviven en la raíz de `scripts/` y se
agrupan abajo como históricos. Los que tocan la base o Cromo indican en su docstring dónde
correrlos (en general, dentro del contenedor del entorno) y si son dry-run por defecto:
leerlo antes de ejecutar.

#### Gobernanza y agentes

- `agent_worktree.py`: Ciclo de vida de agentes concurrentes — worktree, rama efímera y puertos propios por agente (`start`, `list`, `status`, `heartbeat`, `sync`, `ready`, `integrate`, `handoff`, `accept-handoff`, `finish`, `cleanup`, `doctor`).
- `agent_lock.py`: Leases por recurso compartido entre agentes (`acquire`, `heartbeat`/`renew`, `release`, `status`, `list`, `stale-cleanup`).
- `agentes/`: Capas internas del tooling agéntico — `rutas` (descubrimiento del repo y del `git-common-dir`), `estado` (registro SQLite de agentes, leases, handoffs y eventos), `gitops` (operaciones Git y worktrees), `calidad` (gate local de lint + tests focales que corre `agent_worktree.py ready`) y `consola` (salida y logging). Sólo stdlib: funciona sin el venv y desde cualquier worktree.
- `hooks/pre-commit`: Bloquea commits directos en `dev`/`main` y advierte si se commitea en el checkout de control.
- `instalar_hooks.sh`: Instala los hooks versionados de `scripts/hooks` configurando `core.hooksPath`.
- `audit_agentic_environment.py`: Auditor determinista de los contratos del entorno agéntico (gobernanza, skills, mirrors, mapa, exclusiones y estado de agentes).
- `generate_repository_map.py`: Genera y verifica `docs/REPOSITORY_MAP.md` a partir de `config/repository-map.json`.
- `gen_tabla_migraciones.py`: Genera la tabla "Historial de migraciones" de `docs/db.md` desde `db/alembic/versions/` (sólo lectura, stdlib); `--verificar docs/db.md` sale con 1 si el bloque quedó desactualizado.
- `sync_agentes_comunes.sh`: Sincroniza skills desde `.agentes-comunes/skills/` hacia los mirrors de `.github`, `.claude`, `.agents`, `.gemini` (adaptadores livianos) y `.codex-skills`.
- `sync_skill_mirrors.py`: Propagador determinista que usa `sync_agentes_comunes.sh`; preserva el frontmatter de cada mirror, reescribe los enlaces entre skills según cada entorno y `--check` verifica drift sin escribir.
- `check_skill_mirror_drift.sh`: Verifica drift entre `.agentes-comunes/skills/` y todos sus mirrors.

#### Operación y entorno dev

- `start_dev.sh`: Levanta el stack de desarrollo (`lasfocasdev`) en puertos alternativos, con migraciones y healthchecks (`--clone-db`, `--no-build`, `--down`). Ver `docs/entorno_dev.md`.
- `build_base.sh`: Construye la imagen base `focas-base:latest` (multi-stage) a partir de `common-requirements.txt`.
- `setup_local_secrets.sh`: Bootstrap idempotente de `.secrets/*.txt` (Docker Secrets) para desarrollo local y CI, sin imprimir secretos.
- `check_no_plaintext_secrets.sh`: Control preventivo contra secretos versionados y passwords en texto plano.
- `firewall_hardening.sh`: Endurecimiento idempotente de iptables y `rp_filter` del host.
- `logs_cleanup.py`: Rotación por renombre, retención y truncado seguro de `Logs/` con los servicios corriendo; por defecto sólo reporta.
- `logs_verificar.py`: Verifica que cada contenedor del stack tenga su colecta de logs (archivo en `Logs/` + rotación de `docker logs`).
- `api_clients.py`: Alta, listado, desactivación y rotación de clientes OAuth2 M2M (`app.api_clients`) de la API v1.
- `fo_monitor_descargar_basemap.sh`: Descarga el mapa base offline de FO Monitor (recorte PMTiles del AMBA + fuentes y sprites).
- `fo_monitor_generar_geo.py`: Carga o actualiza `app.fomon_cable_geo` (polilíneas WGS84 de cables Cromo) para el mapa de FO Monitor.
- `check_openai.py`: Verifica disponibilidad de la API de OpenAI y la variable `OPENAI_API_KEY`. No se ejecuta en CI.

#### Diagnóstico, sondas y pruebas manuales

- `cromo_sonda.py`: Descubrimiento de sólo lectura contra la API de Cromo Red (incluye el modo `--camino-optico` sobre `/path`).
- `cromo_relevamiento_cables_fantasma.py`: Relevamiento de sólo lectura de cables vigentes en la base local que Cromo ya borró, con sucesores y cobertura de servicios.
- `cromo_inconsistencias_medicion.py`: Mide el detector de inconsistencias de Cromo en modo reporte (no escribe): conteos por tipo, caso testigo y muestra validada contra Cromo en vivo.
- `arnes_busqueda_camaras.py`: Arneses de sólo lectura de la búsqueda de cámaras para comparar el código base contra una rama.
- `linea_base_busqueda_camaras.py`: Graba y compara la línea base de smart search y exportación de Cámaras contra la base de dev.
- `fo_monitor_poc_burrito.py`: Fase 0 de FO Monitor — prueba real bot→bot contra burritoIA en Slack (latencia, hilo, bloque FOMON).
- `fo_monitor_simular_ingreso.py`: Simula un ingreso/egreso de técnico (vía `registrar_movimiento_ingreso`) para probar FO Monitor en dev.
- `test_map_generation.py`: Prueba manual de la generación de mapas estáticos.
- `test_sla_web.py`: Prueba manual del endpoint SLA, capturando errores.

#### Mantenimiento de datos re-ejecutable (dry-run por defecto)

- `cromo_barrido_pelos_inner.py`: Barrido manual `/inner` por cable (at.61/62/63 de los pelos) y conciliación de servicios por pelo.
- `cromo_pelos_snapshot.py`: Copia los at.61/62/63 de pelos leídos por `/inner` de un entorno a otro (dev → prod) y concilia los servicios sin consultar Cromo.
- `ingresos_reprocesar_sin_match.py`: Reproceso por lote de `app.ingresos_sin_match` (Slack) con la búsqueda actual.
- `servicios_backfill_prov.py`: Backfill masivo que enriquece Servicios existentes consultando la API PROV, respetando el rate limit de 5 req/s.
- `servicios_alta_prov_desde_cromo.py`: Da de alta desde PROV los servicios que Cromo asigna a pelos (at.62) y que no existen en `app.servicios`.

#### Backfills y remediaciones de uso único (históricos)

Corrieron para corregir un estado puntual de la base; se conservan como registro y para
reaplicarlos en otro entorno si hiciera falta.

- `camara_backfill_padre_botella.py`: Jerarquía Cámara/Botella (`camaras.camara_padre_id`) sobre filas ya ingeridas.
- `cromo_backfill_camara_padre.py`: Vincula Botellas Cromo (`app.cromo_botellas`) a una Cámara padre propia y les asigna estado (idempotente).
- `cromo_backfill_conectores_odf.py`: Puebla `app.cromo_odf_conectores` para las ODFs ingeridas antes de que existiera el submódulo de Conectores.
- `cromo_backfill_estado_no_operativa_retroactivo.py`: Pasa a `LIBRE` las Cámaras padre Cromo que nacieron `NO_OPERATIVA` bajo el default fail-closed ya revertido, sin auditoría propia.
- `cromo_backfill_fase_servicios.py`: Catch-up puntual de la fase de servicios de la ingesta (matching `cromo_pelos.servicio_numero` → `app.servicios`).
- `cromo_backfill_geo.py`: Latitud/longitud en `cromo_botellas`/`cromo_fusiones` ya ingeridas, sin re-crawlear Cromo.
- `cromo_backfill_placeholders_servicios.py`: Crea un Servicio placeholder por cada `servicio_numero` sin match acumulado y actualiza las filas de `cromo_servicio_match` que lo comparten.
- `cromo_backfill_reconciliar_servicio_final.py`: Re-resuelve todas las filas de `cromo_servicio_match` contra el estado actual de `app.servicios` (consolidaciones de la cadena de upgrades SLA).
- `cromo_backfill_repoblar_cables_empalmes.py`: Repuebla cables en botellas sin cables y empalmes en todas las botellas Cromo.
- `cromo_backfill_servicio_prefijos.py`: `servicio_numero`/`tipo_asociacion` en `cromo_pelos` ya ingeridos, tras ampliar los prefijos reconocidos.
- `cromo_bajas_cables_fantasma.py`: Fix retroactivo de cables fantasma — alta de los que faltan, sus pelos por `/inner` y baja lógica de los que Cromo borró (dry-run por defecto).
- `cromo_fix_nombre_camara_padre_residual.py`: Quita el punto residual al inicio del nombre de Cámaras padre sintetizadas desde Cromo.
- `resync_cromo_botella_estado.py`: Resincroniza `CromoBotella.estado` con el estado real actual de su Cámara padre.
- `retirar_estado_detectada.py`: Migra toda Cámara/Botella con estado `DETECTADA` a su estado real (`LIBRE`/`OCUPADA`/`BANEADA`).
- `servicios_backfill_no_verificable_por_baja.py`: Marca No verificable los Servicios en Baja que quedaron verificables antes de `es_verificable_por_tipo_y_estado`.
- `servicios_fusionar_identidades_duplicadas.py`: Detecta y fusiona pares de `app.servicios` que representan el mismo servicio real bajo dos filas.
- `servicios_fusionar_por_cadena_prov.py`: Fusiona las filas de `app.servicios` que PROV identifica como el mismo servicio y deja el ID operativo (INSTALADO) como `servicio_id`.
- `clientes_categoria_regularizar.py`: Regularización única de categorías por cliente (sync global, alias, Lista C6 y propagación; dry-run con rollback). Lee `data/clientes_c6_inicial.txt`.
- `migrate_legacy_rutas.py`: Migra servicios legacy al modelo de rutas versionadas.

#### Datos

- `data/clientes_c6_inicial.txt`: Lista C6 inicial y alias conocidos para `clientes_categoria_regularizar.py`.

### Convenciones

1. Cada script debe incluir encabezado obligatorio de 3 líneas (ver `AGENTS.md`).
2. Evitar dependencias adicionales; reutilizar librerías ya presentes en `requirements.txt` / `common-requirements.txt`.
3. No imprimir secretos. Mensajes de error concisos y claros.
4. Si un script requiere variables obligatorias, validar al inicio (fail-fast) y documentarlas en este README.

### Ejecución típica

```bash
./scripts/setup_local_secrets.sh
./scripts/check_no_plaintext_secrets.sh
python scripts/check_openai.py

# Trabajo concurrente multi-agente (ver docs/arquitectura_agentes_worktrees.md)
python scripts/agent_worktree.py start --agent claude-api --type feat --task busqueda-camaras
python scripts/agent_worktree.py list
python scripts/agent_lock.py acquire "db:migrations" --agent claude-api --reason "migración"
python scripts/agent_worktree.py doctor
```

---

Para contribuciones, mantener el enfoque mínimo y portable. Cualquier script que evolucione a funcionalidad estable debería migrarse a un módulo formal dentro de la estructura (`modules/` o `core/`).
