# Nombre de archivo: README.md
# Ubicación de archivo: Templates/README.md
# Descripción: Guía de gestión de plantillas oficiales

## Plantillas disponibles

- `Template_Informe_SLA.docx`
- `Plantilla_Informe_Repetitividad.docx`

## Buenas prácticas

- Modificar las plantillas sólo cuando haya un cambio funcional acordado.
- Después de cualquier cambio, actualizar los hashes esperados en `tests/test_templates_integrity.py`.
- Mantener un registro en `docs/informes/*.md` de los ajustes realizados.
- Las versiones empaquetadas en Docker se montan en `/app/Templates`.
- Servicios consumidores actuales: `web` (montado en `deploy/compose.yml`) y el worker `repetitividad_worker` (perfil `reports-worker`).
