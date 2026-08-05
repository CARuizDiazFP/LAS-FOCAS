# Nombre de archivo: modulo_ingesta_cromo.md
# Ubicación de archivo: docs/modulo_ingesta_cromo.md
# Descripción: Contexto estructural del módulo de ingesta de inventario de fibra óptica desde Cromo Red

# Módulo de ingesta de inventario FO desde Cromo

**Estado:** en desarrollo, por etapas. Etapa 1 (acceso y parseo) y Etapa 2 (persistencia) completas.

## Qué resuelve

Cromo Red es el sistema externo de Metrotel donde vive el inventario físico de planta externa de fibra
óptica: botellas/empalmes, cables, tubos, pelos y fusiones, con su geolocalización. Ese inventario no
está replicado en la base de LAS-FOCAS. Este módulo lo ingiere de forma periódica (disparada a demanda,
no automática) para poblar tablas propias y habilitar un **verificador de servicios**: dado un cable,
un buffer o una botella, saber qué servicios de `app.servicios` pasan por ahí.

Es una integración de **sólo lectura**: LAS-FOCAS nunca escribe en Cromo. La ingesta no reemplaza el
flujo existente de trackings `.txt`/`app.ingresos`; convive con ellos en un namespace propio dentro del
esquema `app`.

## Por qué por etapas

El volumen (del orden de 10 mil botellas y sus cables asociados) y la necesidad de validar el modelo de
datos contra la API real antes de comprometerse a un esquema de base llevaron a dividir el trabajo:

1. **Etapa 1 — Acceso y parseo** (completa): cliente HTTP de sólo lectura, parser puro de payloads a
   estructuras de dominio, script de sondeo, tests. Sin tocar la base de datos ni la interfaz. La sonda
   corrió contra el Cromo real de Metrotel y cerró los puntos abiertos del diseño (autenticación OAuth2,
   formato de respuesta, identificación de clases, peso de página).
2. **Etapa 2 — Persistencia** (completa): migración Alembic y modelos SQLAlchemy para las tablas propias
   del módulo, aisladas del resto del esquema. Sin código todavía que escriba en ellas.
3. **Etapa 3 — Servicio de ingesta**: orquesta la lectura paginada, clasifica cada objeto como
   creado/actualizado/sin cambios, reconcilia referencias cruzadas y audita cada corrida.
4. **Etapa 4 — API**: endpoints para disparar una corrida y seguir su progreso en vivo.
5. **Etapa 5 — Interfaz**: vista de administración para operar la ingesta manualmente.
6. **Etapa 6 — Verificador**: consultas sobre las tablas ya pobladas para responder "qué servicios
   pasan por este cable/buffer/botella".

Cada etapa se habilita una vez cerrada la anterior; las decisiones de una etapa pueden ajustar el diseño
de las siguientes si el sondeo contra la API real revela algo distinto de lo asumido.

## Dónde vive el código

- `core/services/cromo/`: paquete del módulo.
  - `config.py`: configuración desde variables de entorno (y Docker Secrets para credenciales),
    validada al arranque.
  - `client.py`: cliente HTTP asíncrono de sólo lectura contra la API externa, con paginación y
    reintentos acotados. No implementa ninguna operación de escritura, por diseño.
  - `parser.py`: funciones puras que traducen los payloads recibidos a las estructuras de dominio.
    Sin acceso a red ni a base de datos.
  - `modelos.py`: las estructuras de dominio del inventario (botella, cable, tubo, pelo, fusión).
- `scripts/cromo_sonda.py`: script de descubrimiento de sólo lectura, para relevar aspectos de la API
  externa que no se pueden resolver leyendo documentación (identificar clases desconocidas, medir
  tamaños de respuesta, etc.). No se ejecuta como parte del flujo normal de la aplicación.
- `tests/test_cromo_parser.py`, `tests/test_cromo_client.py`, `tests/fixtures/cromo/`: cobertura de
  parser y cliente sin red real, con payloads de ejemplo como fixtures.
- `db/models/cromo.py`: modelos SQLAlchemy de las tablas `app.cromo_*` (catálogo, auditoría de
  corridas/eventos e inventario). Documentación de cada tabla en `docs/db.md`.
- `db/alembic/versions/20260805_01_cromo_ingesta.py`: migración que crea esas tablas y siembra el
  catálogo de clases conocidas.

## Principios de diseño

- **Sólo lectura, siempre.** El cliente no expone ningún método de escritura contra el sistema externo.
- **Credenciales fuera del código.** Se leen de variables de entorno o de Docker Secrets si están
  disponibles; nunca se loguea una credencial completa (a lo sumo, los últimos caracteres para poder
  reconocerla en logs sin exponerla).
- **Tolerancia a fallos parciales.** Un objeto malformado o inesperado no aborta el procesamiento del
  resto de una página; se reporta como error puntual y se continúa.
- **Reintentos acotados y selectivos.** Sólo ante errores de red o de servidor, con backoff exponencial
  y un tope fijo. Nunca se reintenta un error de solicitud (datos o permisos inválidos).
- **Paginación dirigida por el propio servidor externo**, no por una suposición local de tamaño de
  página o cantidad de resultados.

## Dónde está el detalle sensible

El modelo de datos completo (estructura exacta del payload, diccionario de atributos, esquema de tablas
propuesto, mecanismo de autenticación) vive en documentación interna no versionada en este repositorio,
por contener detalles operativos del proveedor. Quien continúe una etapa siguiente debe partir de ese
documento, no de este.
