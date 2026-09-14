# Nombre de archivo: README.md
# Ubicación de archivo: scripts/README.md
# Descripción: Documentación breve de los scripts utilitarios

## Scripts utilitarios

Este directorio contiene herramientas auxiliares no incluidas en la ejecución principal de los microservicios.

### Lista actual

- `agent_worktree.py`: Ciclo de vida de agentes concurrentes — un worktree y una rama efímera por agente (`start`, `list`, `status`, `heartbeat`, `sync`, `ready`, `integrate`, `handoff`, `accept-handoff`, `finish`, `cleanup`, `doctor`).
- `agent_lock.py`: Leases por recurso compartido entre agentes (`acquire`, `heartbeat`/`renew`, `release`, `status`, `list`, `stale-cleanup`).
- `agentes/`: Capas internas del tooling agéntico — `rutas` (descubrimiento del repo y del `git-common-dir`), `estado` (registro SQLite), `gitops` (operaciones Git) y `consola` (salida y logging). Sólo stdlib: funciona sin el venv y desde cualquier worktree.
- `check_openai.py`: Verifica conectividad y credenciales de OpenAI (`OPENAI_API_KEY`). No se ejecuta en CI por defecto.
- `setup_local_secrets.sh`: Crea `.secrets/*.txt` para desarrollo local o CI sin imprimir secretos.
- `check_no_plaintext_secrets.sh`: Bloquea secretos versionados y passwords dev en texto plano.
- `sync_agentes_comunes.sh` / `check_skill_mirror_drift.sh`: Sincronizan y verifican los mirrors de skills desde `.agentes-comunes/skills/`.

### Convenciones

1. Cada script debe incluir encabezado obligatorio de 3 líneas (ver `AGENTS.md`).
2. Evitar dependencias adicionales; reutilizar librerías ya presentes en `requirements.txt`.
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

### Próximos scripts (ideas)

- `gen_decision_entry.py`: plantilla interactiva para agregar entradas a `docs/decisiones.md`.

---

Para contribuciones, mantener el enfoque mínimo y portable. Cualquier script que evolucione a funcionalidad estable debería migrarse a un módulo formal dentro de la estructura (`modules/` o `core/`).
