# Nombre de archivo: AGENTS.md
# Ubicación de archivo: AGENTS.md
# Descripción: Instrucciones base para Agentes IA en el proyecto LAS-FOCAS

# AGENTS.md

Instrucciones base para Agentes IA en **LAS-FOCAS**. Las instrucciones específicas por dominio están en `.github/agents/`, prompts automatizados en `.github/prompts/` y habilidades reutilizables en `.github/skills/`.

## 🎯 Arquitectura del Proyecto

**LAS-FOCAS** es un sistema modular dockerizado (Debian 12.4) para Metrotel:

- **Informes operativos**: SLA, Repetitividad, Comparador de trazas FO
- **Asistente conversacional**: Telegram Bot + Web Panel
- **Stack**: Python 3.11+, FastAPI, PostgreSQL 16, LibreOffice headless, Ollama/OpenAI

**Estructura de directorios:**
```
api/          # Endpoints REST (FastAPI)
bot_telegram/ # Bot Telegram (aiogram)
core/         # Funcionalidades compartidas (chatbot, mcp, parsers, services)
db/           # Modelos SQLAlchemy + migraciones Alembic
deploy/       # Docker Compose y configuración de despliegue
docs/         # Documentación del proyecto
modules/      # Informes específicos (repetitividad, SLA)
nlp_intent/   # Clasificación de intención
office_service/ # Microservicio LibreOffice
tests/        # Tests pytest
web/          # Panel web con chat
```

## 🔒 Regla Inquebrantable: Encabezado de 3 Líneas

**Todo archivo modificable** debe iniciar con:

```
# Nombre de archivo: <nombre_del_archivo.ext>
# Ubicación de archivo: <ruta_relativa_en_el_proyecto>
# Descripción: <breve_descripción_del_uso_o_función_del_archivo>
```

Sin excepciones. Si el archivo existe sin encabezado, agregarlo.

## 🛡️ Seguridad (Obligatorio)

> Entorno: VM Debian 12.4 con salida a Internet y acceso a red local.

- **Secrets**: nunca exponer en código ni logs. Usar `.env` / Docker Secrets
- **Mínimos privilegios**: usuario no root cuando sea viable
- **Red interna**: servicios con `expose`, evitar `ports` salvo interfaces públicas
- **Logs prudentes**: no loguear texto del usuario salvo `LOG_RAW_TEXT=true`
- **Versionado estricto**: nunca usar `latest` en imágenes ni librerías
- **Auditoría**: revisar vulnerabilidades antes de incorporar paquetes

Lineamientos completos: `docs/Seguridad.md`

## ⚙️ Docker y Despliegue

**Ubicación del Compose**: `deploy/compose.yml` (NO en raíz)

```bash
# Desde raíz del proyecto:
docker compose -f deploy/compose.yml up -d
docker compose -f deploy/compose.yml build <servicio>
docker compose -f deploy/compose.yml logs -f <servicio>
```

- Redes internas por defecto, volúmenes nombrados
- Imágenes ligeras (slim, alpine), multi-stage builds
- Healthchecks cuando sea posible
- Migraciones DB con Alembic

## 📝 Código y Calidad

- **Idioma**: español en código, commits, PRs y documentación
- **PEP8 + type hints**: anotaciones de tipo, `pydantic` para contratos
- **Logging estructurado**: JSON/clave=valor con `service`, `action`, `request_id`
- **Sin `print()` en producción**: solo `logging`
- **Tratamiento de errores**: timeouts (HTTP default 15s), reintentos con backoff
- **Docstrings**: en módulos, clases y funciones públicas
- **Dependencias**: mantener `requirements.txt` actualizado y versionado

## 🧪 Testing

- **pytest** obligatorio para cambios funcionales
- **Cobertura mínima**: 60% para módulos nuevos
- **Mocks** para proveedores externos (OpenAI/Ollama/SMTP)
- **CI**: GitHub Actions configurado en `.github/workflows/ci.yml`

## 📚 Documentación

- Actualizar `docs/` para cada módulo tocado
- Decisiones técnicas en `docs/decisiones.md`
- PRs diarios en `docs/PR/YYYY-MM-DD.md` (usar prompt automatizado)

## 🤖 Sistema Multi-Agente

Este proyecto utiliza agentes especializados para diferentes dominios:

| Agente | Descripción |
|--------|-------------|
| `docker.agent.md` | Despliegue y contenedores |
| `testing.agent.md` | Pytest, mocks, cobertura |
| `reports.agent.md` | Informes SLA/Repetitividad |
| `mcp-chatbot.agent.md` | Herramientas MCP, orquestador |
| `bot.agent.md` | Telegram bot y flows |
| `web.agent.md` | Panel web, login, frontend |
| `api.agent.md` | Endpoints FastAPI |
| `db.agent.md` | Modelos, Alembic |
| `nlp.agent.md` | Clasificación de intención |
| `office.agent.md` | LibreOffice, conversiones |
| `security.agent.md` | Hardening, secrets |
| `infra.agent.md` | Infraestructura interna |

Los agentes están en `.github/agents/` y pueden traspasar contexto entre sí (handoffs).
