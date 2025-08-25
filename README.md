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
  - **Worker** para procesar tareas en segundo plano. Ver [docs/worker.md](docs/worker.md).
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
│  └─ worker.py  ← lógica del worker
├─ db/
├─ web/
├─ integrations/
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
La lista completa de variables de entorno se encuentra en [.env.sample](.env.sample). Tanto `.env` como `deploy/.env` deben copiarse desde allí para mantenerse idénticos. Se destacan:

- **Redis**: `REDIS_PASSWORD` y `REDIS_URL`, necesarias para habilitar la caché y las colas internas.
- **Panel Web**: credenciales `WEB_ADMIN_USERNAME` / `WEB_ADMIN_PASSWORD` y `WEB_LECTOR_USERNAME` / `WEB_LECTOR_PASSWORD` para los roles administrativos y de lectura.

Las credenciales definidas en este archivo (por ejemplo `WEB_LECTOR_PASSWORD=lectura`) son exclusivas para pruebas y deben sustituirse antes de cualquier despliegue en producción.

La variable `WORK_HOURS` permite ajustar el cálculo del TTR al horario laboral; en `false` se usa el total de horas calendario.
Las solicitudes a la API deben incluir el encabezado `X-API-Key`; el límite se calcula por clave (o por IP si falta).

El bot aplica `BOT_RATE_LIMIT` mensajes por usuario dentro de `BOT_RATE_INTERVAL` segundos.

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

1. Copiar el archivo de variables de entorno de ejemplo y replicarlo para `deploy`:

   ```bash
   cp .env.sample .env
   cp .env deploy/.env
   ```

2. Crear los archivos de texto en `deploy/secrets/` que contendrán las credenciales. El nombre del archivo identifica la variable que se inyectará (por ejemplo: `postgres_password`, `web_admin_password`). Cada archivo debe incluir únicamente el valor de la clave y nada más.

3. Iniciar el stack de contenedores:

   ```bash
   docker compose -f deploy/compose.yml up -d --build
   ```

   El bot de Telegram se inicia solo cuando se especifica el perfil `bot`:

   ```bash
   docker compose -f deploy/compose.yml --profile bot up -d
   ```

   Para pruebas rápidas, puede comentarse la referencia a `secrets` en `deploy/compose.yml` y utilizar las variables definidas en `.env`.

Luego de iniciar los contenedores, puede verificarse el estado del servicio:

```bash
curl -sS http://localhost:8000/health
curl -sS http://localhost:8000/db-check
```

La base de datos PostgreSQL no publica su puerto en el host; se expone únicamente a otros servicios del stack mediante `expose: 5432`.
De igual forma, el servicio `ollama` expone `11434` solo dentro de la red interna.

---

## 📪 CI/CD

**CI (Integración Continua):** `pytest`, `ruff` y `pip-audit` se ejecutan en cada push o pull request mediante [GitHub Actions](docs/ci.md). El escaneo de imágenes con `trivy` puede activarse manualmente.
**CD (Entrega Continua):** despliegue automático opcional.

---

## 🔒 Seguridad

- Allowlist de IDs Telegram.
- Login básico en Web.
- Tokens rotados.
- Usuario DB de mínimos privilegios (incluye cuenta de solo lectura).
- Rate limiting configurable en API, bot y nlp_intent.
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
cp .env deploy/.env
docker compose -f deploy/compose.yml up -d --build
docker compose -f deploy/compose.yml --profile bot up -d
```

El segundo comando levanta el bot de Telegram.

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

