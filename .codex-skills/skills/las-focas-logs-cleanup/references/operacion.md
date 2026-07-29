# Nombre de archivo: operacion.md
# Ubicación de archivo: .github/skills/logs-cleanup/references/operacion.md
# Descripción: Comandos y procedimientos detallados para análisis y limpieza de logs del proyecto y contenedores

# Operación de Limpieza de Logs

## Umbrales

| Categoría | Normal | Advertencia | Acción requerida |
|-----------|--------|-------------|------------------|
| Logs totales del proyecto | <300MB | 300-500MB | >500MB |
| Log individual | <50MB | 50-100MB | >100MB |
| Logs de contenedor | <100MB | 100-500MB | >500MB |

## Análisis

```bash
du -sh /home/focal/proyectos/LAS-FOCAS/Logs/
ls -lah /home/focal/proyectos/LAS-FOCAS/Logs/*.log* 2>/dev/null
ls -lahS /home/focal/proyectos/LAS-FOCAS/Logs/*.log* 2>/dev/null
grep -i "error\|exception\|critical" /home/focal/proyectos/LAS-FOCAS/Logs/*.log 2>/dev/null | tail -20
docker ps -q | while read cid; do NAME=$(docker inspect --format '{{.Name}}' "$cid" | sed 's/^\///'); LOG_PATH=$(docker inspect --format '{{.LogPath}}' "$cid"); if [ -f "$LOG_PATH" ]; then SIZE=$(sudo du -sh "$LOG_PATH" 2>/dev/null | cut -f1); echo "$NAME: $SIZE"; fi; done
```

## Limpieza del proyecto

```bash
rm -f /home/focal/proyectos/LAS-FOCAS/Logs/*.log.[0-9]* 2>/dev/null
for log in /home/focal/proyectos/LAS-FOCAS/Logs/*.log; do
    [ -f "$log" ] && truncate -s 0 "$log"
done
```

## Limpieza de logs Docker

```bash
CONTAINER="lasfocas-web-1"
LOG_PATH=$(docker inspect --format '{{.LogPath}}' "$CONTAINER")
sudo truncate -s 0 "$LOG_PATH"
docker ps -q | while read cid; do
    LOG_PATH=$(docker inspect --format '{{.LogPath}}' "$cid")
    [ -f "$LOG_PATH" ] && sudo truncate -s 0 "$LOG_PATH"
done
```

## Rotación

- Rotación del proyecto: `core/logging.py`.
- Rotación Docker recomendada en `deploy/compose.yml` con `max-size` y `max-file`.

## Guardrails

- No borrar logs si todavía se necesitan para diagnóstico activo.
- Preferir truncar antes que eliminar archivos activos.
- Los logs de contenedor pueden requerir `sudo`.