# AGENTS.md

Este documento está diseñado para orientar a **CODEX** en la comprensión del proyecto **LAS-FOCAS** y establecer las directrices para el desarrollo, asegurando consistencia en la estructura y propósito del código.

## 🎯 Objetivo del Proyecto

**LAS-FOCAS** es un sistema modular, dockerizado y diseñado para Debian 12.4, cuyo propósito principal es:

1. Automatizar informes operativos (Repetitividad, SLA, Comparador de trazas FO, etc.).
2. Actuar como asistente conversacional para tareas repetitivas.
3. Integrarse con sistemas internos de Metrotel a futuro.

## 📜 Alcance y Expectativas

- Migrar y adaptar módulos de **Sandy** a un entorno Linux.
- Implementar microservicios dockerizados con **PostgreSQL** como base de datos local.
- Proveer interfaces vía **Telegram Bot** (con IDs permitidos) y **Web Panel** (con login básico).
- Incorporar logs desde el inicio y documentar todo en `/docs`.
- Mantener la estructura modular para permitir la incorporación de un **agente autónomo** en el futuro.

## 📝 Primera Instrucción para CODEX

**Regla obligatoria:** Todo archivo modificable debe iniciar con un encabezado de 3 líneas con el siguiente formato:

```
# Nombre de archivo: <nombre_del_archivo.ext>
# Ubicación de archivo: <ruta_relativa_en_el_proyecto>
# Descripción: <breve_descripción_del_uso_o_función_del_archivo>
```

- Si el archivo ya existe y no tiene encabezado, agregarlo.
- Si es un archivo nuevo, crearlo con este encabezado incluido desde el inicio.

**Ejemplo:**

```
# Nombre de archivo: main.py
# Ubicación de archivo: sandy_bot/main.py
# Descripción: Archivo Main, en este se centralizan las funciones y operaciones del bot
```

📌 Instrucciones Generales
1.	Estructura de carpetas: Respetar la organización definida en el README. evita crear carpetas fuera de la estructura en el caso que no se pueda evitar informar y documentar.
2.	Estilo de código: Seguir PEP8 para Python. Nombres descriptivos, comentarios claros y docstrings en funciones y clases.
3.	Commits: Usar mensajes de commit descriptivos en español, siguiendo formato "[módulo] Acción realizada".
4.	Logs: Incluir logging en puntos clave del código. No usar print() en producción.
5.	Variables sensibles: Nunca commitear .env ni credenciales. Usar .env y Docker Secrets cuando corresponda.
6.	Documentación: Cualquier módulo nuevo debe tener su documentación en /docs.
7.	Pruebas: Crear o actualizar tests para cualquier cambio funcional. Los tests deben pasar antes de mergear.
8.	Docker: Mantener imágenes ligeras y basadas en versiones específicas, no usar latest.
9.	Dependencias: Actualizar requirements.txt al añadir librerías y verificar compatibilidad.
10.	Integraciones externas: Probar en entornos de staging antes de aplicar a producción.
