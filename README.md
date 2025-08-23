# Nombre de archivo: README.md
# Ubicación de archivo: README.md
# Descripción: Información general del proyecto

# LAS-FOCAS

Automatizaciones operativas para Metrotel: generación de informes, asistente conversacional para tareas repetitivas y base técnica para integrar sistemas internos a futuro.

## 🌟 Objetivos

1. **Automatizar informes** (Repetitividad, SLA, y otros).
2. **Asistente conversacional** para tareas repetitivas (inicio con Telegram; Web en paralelo).
3. **Integración futura** con sistemas internos (APIs, Slack, Salesforce).

> **Ámbito inicial:** Debian 12.4, despliegue dockerizado (microservicios), base de datos PostgreSQL local.

---

## 🧩 Alcance (MVP y próximos hitos)

- **Migraciones desde Sandy**

  - Informe de **Repetitividad y SLA** → reescritura para **LibreOffice (soffice headless)** en lugar de Word/pywin32.
  - **Comparador de trazas FO**.
  - (Luego) Verificación de ingresos, y demás módulos.

- **Interfaces**

  - **Telegram Bot** (primer canal de operación, con menú accesible por `/menu` o por intención). Incluye los flujos `/repetitividad` y `/sla` y un teclado opcional con atajos a ambos comandos. Ver [docs/bot.md](docs/bot.md) para guía rápida.
  - **Web Panel** (roles `admin`/`lector` configurables vía variables `WEB_ADMIN_USERNAME`/`WEB_ADMIN_PASSWORD` y `WEB_LECTOR_USERNAME`/`WEB_LECTOR_PASSWORD`, accesible por IP interna .28). Ver [docs/web.md](docs/web.md) para el plan del módulo.
  - **nlp_intent** (microservicio NLP para clasificación de intención).
  - CLI opcional para utilidades.

- **Integraciones externas**

  - **Notion** (token `NOTION_TOKEN`).
  - **Correo** SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`).
  - A futuro: **APIs internas**, Slack, Salesforce.

- **Autenticación**

  - **Allowlist de IDs de Telegram** para uso del bot.
  - **Web:** credenciales de `admin` y `lector` configurables mediante `WEB_ADMIN_USERNAME`/`WEB_ADMIN_PASSWORD` y `WEB_LECTOR_USERNAME`/`WEB_LECTOR_PASSWORD` (básico al inicio; SSO interno a futuro).

---

## 🏰 Arquitectura (microservicios)

```
                        ┌───────────────────┐
                        │   Web Panel (FastAPI)│  ← Login básico
                        └───────┬───────┘
                                │
                        ┌────────┬────────┐
                        │                 │
        ┌─────────────┐                    ┌────────────┐
        │  API Core   │← FastAPI/SQLAlchemy│  Worker    │← Celery/RQ (opcional)
        └─────┬─────┘                      └─────┬────┘
               │                                 │
               │                                 │ Jobs/colas (opcional)
               │                                 │
        ┌───────┬─────┐                     ┌─────┬───┐
        │ PostgreSQL  │                     │  Redis  │ (opcional)
        └───────┘                           └───────┘
               │
        ┌───────┬─────┐
        │ Storage/Files │ (Informes, plantillas LibreOffice)
        └───────┘

        ┌─────────┐
        │ Telegram Bot   │  ← Allowlist de IDs
        └─────────┘

        ┌───────────────┐
        │ nlp_intent    │  ← Clasificación de intención
        └───────────────┘

        ┌─────────┐
        │ Notion/Email   │  (Integraciones)
        └─────────┘

        ┌─────────┐
        │ Logging/Metrics│  (Prometheus/Grafana opcional)
        └─────────┘
```

**Stack recomendado**

- **Python 3.11+**, **FastAPI**, **SQLAlchemy + Alembic**, **pydantic**, **pandas**.
- **PostgreSQL 15+**.
- **Uvicorn/Gunicorn** para serving.
- **LibreOffice (soffice headless)** para documentos.
- **Celery o RQ + Redis** (opcional) para tareas asíncronas.
- **Prometheus + Grafana** (opcional) para métricas.
- **Docker / docker-compose** para orquestación.

---

## 🗂️ Estructura de carpetas

```
las-focas/
├─ api/
├─ bot_telegram/
├─ nlp_intent/
├─ core/
├─ modules/
├─ workers/
├─ db/
├─ web/
├─ integrations/
├─ scripts/
├─ deploy/
├─ docs/
├─ tests/
├─ .env.sample
├─ .env
├─ .gitignore
├─ LICENSE
└─ README.md
```

## 📘 Guías por módulo

Cada directorio principal incluye un archivo `AGENTS.md` con lineamientos específicos. Revísalo antes de modificar cualquier código. Para más detalles ver [docs/agents.md](docs/agents.md).

---

## 🔐 Configuración y credenciales

**.env.sample**

```
# Base de datos
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=lasfocas
POSTGRES_USER=lasfocas
POSTGRES_PASSWORD=
# Se carga desde /run/secrets/postgres_password cuando está disponible

# Bot de Telegram
TELEGRAM_BOT_TOKEN=
# Se carga desde /run/secrets/telegram_bot_token cuando está disponible
TELEGRAM_ALLOWED_IDS=11111111,22222222

# NLP / LLM
LLM_PROVIDER=auto
OPENAI_API_KEY=
# Se carga desde /run/secrets/openai_api_key cuando está disponible
# URL base para el servicio Ollama interno
OLLAMA_URL=http://ollama:11434
INTENT_THRESHOLD=0.7
LANG=es
LOG_RAW_TEXT=false
CACHE_TTL=300

# Informes
SLA_TEMPLATE_PATH=/app/templates/sla.docx
REP_TEMPLATE_PATH=/app/templates/repetitividad.docx
REPORTS_DIR=/app/data/reports
UPLOADS_DIR=/app/data/uploads
SOFFICE_BIN=/usr/bin/soffice
MAPS_ENABLED=false
MAPS_LIGHTWEIGHT=true
# Cálculo de TTR en horario laboral (true) o 24/7 (false)
WORK_HOURS=false

# Rate limiting
API_RATE_LIMIT=60/minute
NLP_RATE_LIMIT=60/minute

# Integraciones
NOTION_TOKEN=
SMTP_HOST=
# Se carga desde /run/secrets/smtp_host cuando está disponible
SMTP_PORT=587
SMTP_USER=
# Se carga desde /run/secrets/smtp_user cuando está disponible
SMTP_PASSWORD=
# Se carga desde /run/secrets/smtp_password cuando está disponible
SMTP_FROM=
# Se carga desde /run/secrets/smtp_from cuando está disponible
```
La variable `WORK_HOURS` permite ajustar el cálculo del TTR al horario laboral; en `false` se usa el total de horas calendario.
Las solicitudes a la API deben incluir el encabezado `X-API-Key`; el límite se calcula por clave (o por IP si falta).

La imagen del servicio `bot` incluye LibreOffice, por lo que al definir
`SOFFICE_BIN=/usr/bin/soffice` se habilita la exportación de informes a PDF.

---

## 🗳️ Logging & Métricas

- **Logging** desde el día 1 (rotación, exclusión en `.gitignore`).
- **Métricas** opcionales (Prometheus/Grafana).

---

## 🛥️ Despliegue

Se recomienda **docker-compose** desde el inicio para reproducibilidad. Los detalles de redes, puertos y volúmenes están en [docs/infra.md](docs/infra.md).

**Requisitos (Debian 12.4)**

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git make
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
```

**Primer arranque**

```bash
cp .env.sample .env
docker compose -f deploy/compose.yml up -d --build
```

Luego de iniciar los contenedores, puede verificarse el estado del servicio:

```bash
curl -sS http://localhost:8000/health
curl -sS http://localhost:8000/db-check
```

La base de datos PostgreSQL no publica su puerto en el host; se expone únicamente a otros servicios del stack mediante `expose: 5432`.
De igual forma, el servicio `ollama` expone `11434` solo dentro de la red interna.

---

## 📪 CI/CD

**CI (Integración Continua):** `pytest` y `ruff` se ejecutan en cada push o pull request mediante [GitHub Actions](docs/ci.md).\
**CD (Entrega Continua):** despliegue automático opcional.

---

## 🔒 Seguridad

- Allowlist de IDs Telegram.
- Login básico en Web.
- Tokens rotados.
- Usuario DB de mínimos privilegios (incluye cuenta de solo lectura).
- Rate limiting configurable en API y nlp_intent.
- Políticas detalladas en [docs/security.md](docs/security.md).
---

## 🧠 Agente autónomo (futuro)

Microservicio adicional usando el core y la DB.

Modelos sugeridos para 32 GB RAM:

- **Llama 3.1 8B Instruct**, **Mistral 7B**, **Qwen2 7B** (cuantizados Q4).

---

## 💡 Tecnologías clave

- **Python**: FastAPI, SQLAlchemy, Alembic, pydantic, pandas, python-telegram-bot/aiogram.
- **Office**: LibreOffice headless.
- **DB**: PostgreSQL.
- **Infra**: Docker, docker-compose.

---

## ▶️ Uso rápido

```bash
git clone https://github.com/CARuizDiazFP/LAS-FOCAS
cd LAS-FOCAS
cp .env.sample .env
docker compose -f deploy/compose.yml up -d --build
```

---

## 📅 Roadmap

1. Infra base.
2. Migrar Repetitividad/SLA.
3. Migrar Comparador FO.
4. Integraciones Notion/Email.
5. Métricas.
6. Agente autónomo.
7. Seguridad avanzada.

---

## 📓 Licencia

Este proyecto se distribuye bajo la [Licencia MIT](LICENSE).

---

