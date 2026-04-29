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
  - **Web Panel** (autenticación simple, Panel con Chat por defecto, accesible por IP interna .28).
  - **nlp_intent** (microservicio NLP para clasificación de intención).
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

        ┌───────────────┐
        │ nlp_intent    │  ← Clasificación de intención
        └───────────────┘

        ┌────────────────────────┐
        │ LibreOffice Service    │ ← Conversión de documentos vía UNO
        └────────────────────────┘

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
├─ Templates/
├─ office_service/
├─ devs/
├─ .env
├─ .gitignore
├─ LICENSE
└─ README.md
```

**Plantillas**

- `Templates/` concentra todas las plantillas productivas (SLA, Repetitividad y futuras). Mantener los archivos maestros en este directorio y versionar cambios junto con la documentación del flujo correspondiente.

**Recursos locales de desarrollo**

- `devs/` queda reservado para materiales de apoyo en desarrollo (datasets de prueba, informes generados localmente, etc.). El directorio completo está en `.gitignore`, por lo que su contenido no se versiona.

**Workers**

- `repetitividad_worker` (perfil `reports-worker`) encapsula `geopandas/contextily` para generar mapas sin incrementar el tamaño de los servicios principales.

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
# NLP / LLM
LLM_PROVIDER=auto
OPENAI_API_KEY=
OLLAMA_URL=http://ollama:11434
INTENT_THRESHOLD=0.7
LANG=es
LOG_RAW_TEXT=false
TEMPLATES_DIR=/app/Templates
SLA_TEMPLATE_PATH=${TEMPLATES_DIR}/Template_Informe_SLA.docx
REP_TEMPLATE_PATH=${TEMPLATES_DIR}/Plantilla_Informe_Repetitividad.docx
REPORTS_DIR=/app/data/reports
UPLOADS_DIR=/app/data/uploads
SOFFICE_BIN=/usr/bin/soffice
MAPS_ENABLED=false
MAPS_LIGHTWEIGHT=true
# Plantillas (host)
# TEMPLATES_HOST_DIR=./Templates
# LibreOffice Service
OFFICE_ENABLE_UNO=true
OFFICE_LOG_LEVEL=INFO
OFFICE_SOFFICE_PORT=2002
OFFICE_SOFFICE_CONNECT_HOST=127.0.0.1
# API de reportes
REPORTS_API_BASE=http://api:8000
REPORTS_API_TIMEOUT=60
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
./Start  # levanta Postgres, NLP, API (8001) y Web (8080) usando el Ollama externo de la VM (host:11434)
# Reconstruir sólo el front (estáticos/JS/CSS del panel):
./Start --rebuild-frontend
# Para levantar también un Ollama interno del stack (opcional):
# ./Start --with-internal-ollama
```

Luego de iniciar los contenedores, puede verificarse el estado del servicio:

```bash
curl -sS http://localhost:8001/health   # API (remapeada)
curl -sS http://localhost:8001/db-check
curl -sS http://192.168.241.28:8080/health   # Web UI (IP privada de la VM)
curl -sS http://192.168.241.28:8080/health/version  # versión de build del Web UI
curl -sS http://localhost:11434/api/tags # Ollama (externo o interno si se usó --with-internal-ollama)
```

### ⚡ Prueba rápida (API + DB)

1) Salud del servicio y DB

- `GET /health` → estado general del microservicio API.
- `GET /db-check` → `SELECT 1` y versión de PostgreSQL.

2) Ingesta de reclamos (opcional)

- Enviar un Excel de prueba al endpoint `POST /ingest/reclamos` para validar mapeo/fechas/GEO.
- Archivo de ejemplo: `devs/Reclamos Nuevo.xlsx` (editar y adaptar a tu dataset real).

3) Métricas de Repetitividad desde DB

- `GET /reports/repetitividad?periodo_mes=7&periodo_anio=2024` devuelve métricas básicas del período.
- Alternativamente, `POST /reports/repetitividad` sin archivo usa modo DB y genera el DOCX (y ZIP si `incluir_pdf=true`).
- El DOCX exportado reemplaza por completo la portada, muestra Horas Netas en formato `HH:MM` y embebe mapas PNG por servicio ajustados a media hoja A4.

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
- Utilidades propias: `core/utils/timefmt` para normalizar duraciones en minutos ↔ `HH:MM` dentro de los informes.

---

## ▶️ Uso rápido

```bash
git clone https://github.com/CARuizDiazFP/LAS-FOCAS
cd LAS-FOCAS
cp deploy/env.sample .env
docker compose -f deploy/compose.yml up -d --build

# Notas de UI:
# - La carpeta histórica de reportes se navega en /reports-history (los archivos se sirven en /reports).
# - En el panel, Repetitividad/SLA muestran enlaces directos a /reports/*.docx|.pdf|.html.
```

---

## �️ Entorno de Desarrollo

Ver [docs/entorno_dev.md](docs/entorno_dev.md) para el flujo completo.

```bash
git checkout dev             # Rama de trabajo habitual
cp deploy/env.dev.sample .env.dev
./scripts/start_dev.sh       # Levanta stack lasfocasdev (puertos alternativos)
```

| | Producción | Dev |
|-|-----------|-----|
| Web panel | `192.168.241.28:8080` | `localhost:8090` |
| API docs  | `:8001/docs` | `:8011/docs` |
| PostgreSQL | `5432` | `5433` |

---

## �📅 Roadmap

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
