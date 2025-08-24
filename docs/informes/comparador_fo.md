# Nombre de archivo: comparador_fo.md
# Ubicación de archivo: docs/informes/comparador_fo.md
# Descripción: Documentación del comparador de trazas de fibra óptica

## Insumos requeridos
- Dos archivos de trazas FO en formato binario (`.sor` u otros).
- Tamaño máximo recomendado: 10MB por archivo.

## Validaciones
- Ambos archivos deben existir y ser legibles.
- Los hashes SHA256 permiten detectar diferencias con exactitud.

## Uso básico
1. Proveer las rutas de los dos archivos a comparar.
2. El módulo calcula el hash de cada archivo.
3. Se informa si las trazas son idénticas mediante el campo `iguales`.
4. Las comparaciones extensas pueden encolarse para ser procesadas por el worker.

## Paths de salida
- No se generan archivos nuevos; solo se devuelve un diccionario con resultados.

## Variables de entorno
- Ninguna por el momento.
