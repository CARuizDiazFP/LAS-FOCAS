# Nombre de archivo: revisar-seguridad.prompt.md
# Ubicación de archivo: .github/prompts/revisar-seguridad.prompt.md
# Descripción: Prompt para auditoría de seguridad del proyecto

---
name: Revisar Seguridad
description: Realiza una auditoría de seguridad del proyecto o archivos específicos
mode: agent
variables:
  - name: alcance
    default: full
    description: Alcance de la revisión (full, dependencies, secrets, network, files)
  - name: archivos
    default: ""
    description: Archivos específicos a revisar (opcional, separados por coma)
---

# Auditoría de Seguridad - LAS-FOCAS

Realizar revisión de seguridad con alcance: **${alcance}**

## 1. Auditoría de Dependencias

```bash
# Python - pip-audit
pip-audit -r requirements.txt
pip-audit -r api/requirements.txt
pip-audit -r nlp_intent/requirements.txt
pip-audit -r bot_telegram/requirements.txt
pip-audit -r office_service/requirements.txt

# npm (si aplica)
cd web/frontend && npm audit
```

### Reportar
- Vulnerabilidades críticas/altas encontradas
- Dependencias desactualizadas
- Recomendaciones de actualización

## 2. Búsqueda de Secretos Expuestos

```bash
# Buscar patrones de secretos en código
grep -r -E "(password|secret|token|api_key|apikey|auth)" --include="*.py" --include="*.yml" --include="*.yaml" --include="*.json" .

# Buscar strings que parecen tokens
grep -r -E "['\"][A-Za-z0-9_-]{20,}['\"]" --include="*.py" .

# Verificar .env no está en git
git ls-files | grep -E "\.env$"

# Verificar .gitignore incluye archivos sensibles
cat .gitignore | grep -E "(\.env|secrets|credentials|\.pem|\.key)"
```

### Verificar que NO existan:
- [ ] Tokens/API keys hardcodeados
- [ ] Contraseñas en código
- [ ] Archivos .env commiteados
- [ ] Archivos de certificados/llaves

## 3. Configuración de Red y Puertos

```bash
# Revisar compose.yml por puertos expuestos
grep -A5 "ports:" deploy/compose.yml

# Verificar que servicios internos usen 'expose' no 'ports'
grep -E "(expose|ports):" deploy/compose.yml
```

### Verificar:
- [ ] PostgreSQL NO expone puerto al host
- [ ] Servicios internos (nlp_intent, office) solo con `expose`
- [ ] Solo interfaces públicas (api, web) con `ports`
- [ ] Web panel con IP específica, no 0.0.0.0

## 4. Permisos y Usuarios

```bash
# Verificar Dockerfiles usan usuario no-root
grep -l "USER" */Dockerfile deploy/docker/Dockerfile.*

# Buscar operaciones como root
grep -r "sudo\|chmod 777\|chown.*root" --include="*.sh" --include="*.py" .
```

### Verificar:
- [ ] Contenedores con usuario no-root cuando es viable
- [ ] Sin chmod 777 en código
- [ ] Sin operaciones como sudo

## 5. Logging y Datos Sensibles

```bash
# Buscar logs que podrían exponer datos sensibles
grep -r -E "(print\(|logger\.(info|debug|warning|error))" --include="*.py" . | head -50

# Verificar LOG_RAW_TEXT está respetado
grep -r "LOG_RAW_TEXT" --include="*.py" .
```

### Verificar:
- [ ] No se loguea texto del usuario por defecto
- [ ] LOG_RAW_TEXT controla logging de mensajes
- [ ] Sin print() en código de producción
- [ ] Logs no exponen tokens/passwords

## 6. Validación de Entrada

```bash
# Buscar endpoints sin validación Pydantic
grep -r "@app\.\(get\|post\|put\|delete\)" --include="*.py" -A3 . | grep -v "BaseModel\|Pydantic"
```

### Verificar:
- [ ] Todos los endpoints usan Pydantic para validación
- [ ] Inputs de usuario son escapados/sanitizados
- [ ] SQL queries usan parámetros (no concatenación)

## 7. Checklist de Seguridad

### Crítico
- [ ] No hay secretos en código
- [ ] Dependencias sin vulnerabilidades críticas
- [ ] Servicios internos no expuestos

### Importante
- [ ] Usuarios no-root en contenedores
- [ ] Logging prudente
- [ ] Rate limiting en superficies expuestas

### Recomendado
- [ ] HTTPS en producción
- [ ] Firewall configurado
- [ ] Auditorías periódicas

## 8. Generar Reporte

Al finalizar, crear un resumen con:

1. **Hallazgos críticos** (requieren acción inmediata)
2. **Hallazgos importantes** (resolver pronto)
3. **Recomendaciones** (mejoras sugeridas)
4. **Estado general** (puntuación de seguridad)

Actualizar `docs/Seguridad.md` si hay cambios en lineamientos.
