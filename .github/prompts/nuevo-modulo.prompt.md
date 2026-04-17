# Nombre de archivo: nuevo-modulo.prompt.md
# Ubicación de archivo: .github/prompts/nuevo-modulo.prompt.md
# Descripción: Prompt para crear scaffolding de un nuevo módulo con tests y documentación

---
name: Nuevo Módulo
description: "Crea el scaffolding de un módulo nuevo con estructura, tests y documentación alineados a LAS-FOCAS"
argument-hint: "Nombre, ubicación y propósito, por ejemplo: parser_nokia en core para parsear alarmas Nokia"
agent: "agent"
---

# Crear Nuevo Módulo

Crear un módulo nuevo a partir del nombre, ubicación y propósito indicados por el usuario. Si faltan datos, inferir la estructura mínima y declarar los supuestos.

## Objetivo

- generar una estructura coherente con la arquitectura del repo
- incluir código base, tests y documentación inicial
- respetar encabezado obligatorio, español, logging y type hints

## Entradas esperadas

- nombre del módulo
- ubicación objetivo, por ejemplo `modules/`, `core/` o `api/`
- propósito funcional del módulo
- si expone servicio, parser, endpoint o integración

## Flujo de trabajo

### 1. Ubicar el módulo correctamente

Elegir la carpeta según la responsabilidad:

- `modules/` para lógica funcional de informes o dominios concretos
- `core/` para utilidades, parsers, servicios y componentes compartidos
- `api/` o `web/` solo si el cambio es de superficie HTTP/UI

### 2. Crear estructura mínima

```
<ubicacion>/<nombre_modulo>/
├── __init__.py
├── config.py
├── schemas.py
├── processor.py
├── service.py
└── README.md
```

Agregar `tests/test_<nombre_modulo>.py` y, si corresponde, `docs/<nombre_modulo>.md`.

### 3. Implementar base coherente

Usar estos lineamientos en lugar de generar boilerplate arbitrario:

- configuración separada en `config.py`
- contratos o modelos en `schemas.py` si aporta claridad
- lógica principal en `processor.py` o `service.py`
- `logging` en vez de `print()`
- nombres en español y type hints
- tests enfocados al comportamiento principal y casos de error

### 4. Crear tests y documentación

- tests en `tests/` siguiendo el patrón existente del repo
- documentación breve en `docs/` o `README.md` del módulo
- si hay impacto transversal, reflejarlo también en el PR diario

## Reglas obligatorias

1. Todo archivo nuevo debe llevar encabezado obligatorio de 3 líneas.
2. El código y la documentación deben quedar en español.
3. No duplicar lógica ya existente en `core/`, `modules/` o `bot_telegram/`.
4. Mantener límites arquitectónicos del repo: no meter UI en `api`, ni acceso directo a DB dentro de `nlp_intent`.
5. Crear solo la cantidad de archivos que aporte valor real; no generar boilerplate inútil.

## Checklist de validación

- [ ] Estructura creada en la ubicación correcta
- [ ] Encabezado de 3 líneas presente en archivos nuevos
- [ ] Tests base agregados o pendientes explicitados
- [ ] Imports y nombres coherentes con el resto del repo
- [ ] Documentación mínima creada o actualizada
- [ ] PR diario actualizado si corresponde

## Salida esperada

1. Crear archivos y tests necesarios, no más.
2. Explicar brevemente la estructura elegida.
3. Indicar validaciones ejecutadas o pendientes.
4. Actualizar documentación relacionada cuando aplique.
