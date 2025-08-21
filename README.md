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

  - **Telegram Bot** (primer canal de operación). Ver [docs/bot.md](docs/bot.md) para guía rápida.
  - **Web Panel** (autenticación simple, accesible por IP interna .28).
  - CLI opcional para utilidades.

- **Integraciones externas**

  - **Notion**, **Correo** (SMTP).
  - A futuro: **APIs internas**, Slack, Salesforce.

- **Autenticación**

  - **Allowlist de IDs de Telegram** para uso del bot.
  - **Web:** usuario/contraseña (básico al inicio; SSO interno a futuro).

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
├─ .env
├─ .gitignore
├─ LICENSE
└─ README.md
```

---

## 🔐 Configuración y credenciales

**.env (ejemplo)**

```
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=lasfocas
POSTGRES_USER=lasfocas
POSTGRES_PASSWORD=superseguro
APP_SECRET_KEY=change-me
ENV=development
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_ALLOWED_IDS=11111111,22222222
NOTION_TOKEN=secret_notion
NOTION_DB_ID=xxxxx
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=notificaciones@example.com
SMTP_PASS=secret
```

---

## 🗳️ Logging & Métricas

- **Logging** desde el día 1 (rotación, exclusión en `.gitignore`).
- **Métricas** opcionales (Prometheus/Grafana).

---

## 🛥️ Despliegue

Se recomienda **docker-compose** desde el inicio para reproducibilidad.

**Requisitos (Debian 12.4)**

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git make
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
```

**Primer arranque**

```bash
cp deploy/env.sample .env
docker compose -f deploy/compose.yml up -d --build
```

Luego de iniciar los contenedores, puede verificarse el estado del servicio:

```bash
curl -sS http://localhost:8000/health
curl -sS http://localhost:8000/db-check
```

---

## 📪 CI/CD

**CI (Integración Continua):** test, lint, build docker en cada push/PR.\
**CD (Entrega Continua):** despliegue automático opcional.

---

## 🔒 Seguridad

- Allowlist de IDs Telegram.
- Login básico en Web.
- Tokens rotados.
- Usuario DB de mínimos privilegios.

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
cp deploy/env.sample .env
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

MIT: libre uso/modificación con aviso de copyright.

---

