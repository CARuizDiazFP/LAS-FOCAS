# Nombre de archivo: operacion.md
# Ubicación de archivo: .agentes-comunes/skills/logs-cleanup/references/operacion.md
# Descripción: Comandos y procedimientos detallados para leer, verificar y limpiar los logs del proyecto y contenedores

# Operación de Logs

Rutas relativas al checkout de control (`/home/support-focal-01/LAS-FOCAS`), que es el que montan
los compose (`../Logs` en prod, `../Logs/dev` en dev).

## Umbrales

| Categoría | Normal | Advertencia | Acción requerida |
|-----------|--------|-------------|------------------|
| Logs totales del proyecto | <300MB | 300-500MB | >500MB |
| Log individual | <50MB | 50-100MB | >100MB |
| Logs de contenedor | rotan solos (20 MB × 5) | — | — |

## Lectura acotada

```bash
tail -n 200 Logs/dev/cromo_worker.log
grep -m 50 'level=ERROR' Logs/api.log
grep '^2026-09-30 14:' Logs/web.log | tail -n 100          # una hora puntual
docker logs --since 30m lasfocasdev-postgres 2>&1 | tail -n 100
```

## Verificación de la colecta

```bash
python scripts/logs_verificar.py --entorno dev
python scripts/logs_verificar.py --entorno prod --json
```

Qué revisa por contenedor: driver `json-file`/`local` con `max-size`, y (servicios Python) que su
`Logs/<servicio>.log` exista y se haya escrito después de que arrancó el contenedor.
`core/logging.py` escribe `action=logging evento=inicio` al arrancar, así que un servicio sano lo
cumple aunque todavía no haya tenido tráfico.

## Limpieza del proyecto

```bash
python scripts/logs_cleanup.py                              # reporte de Logs/ (con dev/)
python scripts/logs_cleanup.py --apply
python scripts/logs_cleanup.py --apply --truncar Logs/dev/web.log
python scripts/logs_cleanup.py --max-mb 20 --dias 7 --max-total-mb 300
```

- Rotar = renombrar a `x.log.YYYYMMDD-HHMMSS`. Seguro en uso: el servicio vuelve a crear `x.log`
  en su volcado siguiente (≤2 s).
- Los rotados del formato anterior (`web.log.1`, `.2`, `.3`, de `RotatingFileHandler`) cuentan como
  rotados y se borran por edad.
- Archivos con `ERROR`/`CRITICAL` en los últimos 10 min quedan `protegido` (ver `--ventana-error-min`
  y `--forzar`).

## Logs Docker

Rotan solos por el anchor `x-logging` de `deploy/compose.yml` y `deploy/docker-compose.dev.yml`
(`json-file`, `max-size: 20m`, `max-file: 5`). Aplica a contenedores creados después del cambio:
uno viejo conserva su driver sin límite hasta que se recrea (`logs_verificar.py` lo marca).

## Guardrails

- No borrar logs si todavía se necesitan para diagnóstico activo.
- Leer siempre acotado; nunca `cat` completo de un log.
- Truncar a mano un log de Docker requiere `sudo` y confirmación del usuario.
