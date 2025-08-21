# Nombre de archivo: infra.md
# Ubicación de archivo: docs/infra.md
# Descripción: Detalle de las redes, puertos y volúmenes del stack dockerizado

## Redes

- `lasfocas_net`: red bridge interna que conecta todos los servicios. Limita la exposición externa y permite la comunicación directa entre contenedores.

## Puertos

- `postgres` expone `5432` solo a la red interna mediante `expose`.
- `api` publica `8000:8000` para acceso HTTP desde el host.
- `nlp_intent` expone `8100` únicamente a la red interna.
- `pgadmin` (perfil opcional) publica `5050:80` para administración de PostgreSQL.

## Volúmenes

- `postgres_data`: persiste los datos de la base en `/var/lib/postgresql/data`.
- `bot_data`: almacena archivos y estados del bot en `/app/data`.
- `./db/init.sql` se monta de forma de solo lectura para inicializar la base.
