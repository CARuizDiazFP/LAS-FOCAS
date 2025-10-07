# Nombre de archivo: README.md
# Ubicación de archivo: scripts/README.md
# Descripción: Documentación breve de los scripts utilitarios

## Scripts utilitarios

Este directorio contiene herramientas auxiliares no incluidas en la ejecución principal de los microservicios.

### Lista actual

- `check_openai.py`: Verifica conectividad y credenciales de OpenAI (`OPENAI_API_KEY`). No se ejecuta en CI por defecto.

### Convenciones

1. Cada script debe incluir encabezado obligatorio de 3 líneas (ver `AGENTS.md`).
2. Evitar dependencias adicionales; reutilizar librerías ya presentes en `requirements.txt`.
3. No imprimir secretos. Mensajes de error concisos y claros.
4. Si un script requiere variables obligatorias, validar al inicio (fail-fast) y documentarlas en este README.

### Ejecución típica

```bash
python scripts/check_openai.py
```

### Próximos scripts (ideas)

- `hash_templates.py`: recalcula hashes de plantillas para tests de integridad.
- `gen_decision_entry.py`: plantilla interactiva para agregar entradas a `docs/decisiones.md`.

---

Para contribuciones, mantener el enfoque mínimo y portable. Cualquier script que evolucione a funcionalidad estable debería migrarse a un módulo formal dentro de la estructura (`modules/` o `core/`).
