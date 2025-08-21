# Nombre de archivo: healthcheck.sh
# Ubicación de archivo: bot_telegram/healthcheck.sh
# Descripción: Verifica que el proceso principal del bot esté activo
#!/bin/sh
pgrep -f "bot_telegram.app" >/dev/null || exit 1
