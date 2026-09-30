# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agentes-comunes/skills/logs-cleanup/SKILL.md
# Descripción: Skill para leer de forma acotada, verificar la colecta y limpiar los logs de Logs/ y de contenedores Docker

---
name: logs-cleanup
description: "Usar cuando haya que leer logs para diagnosticar, verificar que todos los servicios estén logueando, o limpiar Logs/ y logs de Docker sin perder evidencia"
argument-hint: "Describe alcance, por ejemplo: errores de cromo_worker de la última hora, o limpiar Logs/ con los servicios corriendo"
---

# Habilidad: Logs (lectura acotada, colecta y limpieza)

`Logs/` está fuera del indexado de todos los entornos agénticos (`.gitignore`, `.geminiignore`): es la
única vía para leer logs, y siempre de forma acotada, porque un log completo puede tener cientos de MB.

## Dónde está cada log

- Servicios Python: `Logs/<servicio>.log` (prod) y `Logs/dev/<servicio>.log` (dev), escritos por
  `core/logging.py` (`office` usa su copia en `office_service/app/logging_setup.py`). Nombres: `api`,
  `web`, `nlp_intent`, `bot`, `office`, `repetitividad_worker`, `slack_baneo_worker`, `cromo_worker`,
  `botellas_recalculo_worker`. Los scripts de `scripts/` escriben el suyo (`Logs/<script>.log`).
- Todos los contenedores (incluidos postgres, redis y docker-socket-proxy): `docker logs`, con
  rotación `json-file` 20 MB × 5 (anchor `x-logging` de los compose).

## Cuándo usar

- diagnosticar un error de un servicio (leer sólo la ventana necesaria)
- confirmar que todos los servicios están escribiendo su log (tras un deploy o un cambio de compose)
- cuando `Logs/` o los logs Docker crecen demasiado

## Procedimiento

1. **Leer acotado, nunca entero**: `tail -n 200`, `grep -m 50 'level=ERROR'`, o filtrar por hora
   (`grep '^2026-09-30 14:'`). Nunca `cat` de un log completo ni lectura recursiva de `Logs/`.
2. **Verificar la colecta**: `python scripts/logs_verificar.py --entorno dev` (o `prod`). Sale con
   código 1 si un contenedor no tiene rotación de `docker logs` o no escribió su archivo desde que
   arrancó. Medir el exit code del comando, no el de un pipe.
3. **Limpiar**: `python scripts/logs_cleanup.py` (reporte) y, si el plan es correcto, `--apply`.
   Rota por renombre lo que supera `--max-mb`, borra rotados más viejos que `--dias` y respeta
   `--max-total-mb`. `--truncar <archivo>` vacía uno puntual.
4. Verificar el estado final con otro reporte.

## Por qué se puede limpiar con los servicios corriendo

El handler junta ~2 s de registros (un `ERROR` se escribe al instante) y en cada volcado abre,
escribe y cierra el archivo. Nada queda bloqueado: borrar, truncar o renombrar un log en uso es
seguro, y el volcado siguiente vuelve a crear el archivo en la misma ruta. Por eso la rotación la
hace el script por renombre, y no hace falta `copytruncate` ni reiniciar servicios.

## Referencias

- [Operación detallada](./references/operacion.md)
- [disk-analysis](../disk-analysis/SKILL.md)
- [temp-cleanup](../temp-cleanup/SKILL.md)

## Guardrails

1. No limpiar logs de un incidente en curso: `logs_cleanup.py` ya protege los archivos con un
   `ERROR` en los últimos 10 min. Usar `--forzar` sólo si el usuario lo pide.
2. Leer siempre acotado (ventana de líneas o de horas), nunca un log entero ni `Logs/` recursivo.
3. Nunca mostrar secretos: si aparece uno en un log, reportarlo enmascarado (skill `secret-detection`).
4. Los logs de Docker no se truncan a mano: los rota el driver. Si igual hace falta, requiere `sudo`
   y confirmación del usuario.
