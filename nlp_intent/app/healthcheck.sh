# Nombre de archivo: healthcheck.sh
# Ubicación de archivo: nlp_intent/app/healthcheck.sh
# Descripción: Comprueba que el microservicio nlp_intent responda al endpoint de health
#!/bin/sh
curl -fsS http://localhost:8100/health || exit 1
