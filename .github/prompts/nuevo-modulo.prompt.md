# Nombre de archivo: nuevo-modulo.prompt.md
# Ubicación de archivo: .github/prompts/nuevo-modulo.prompt.md
# Descripción: Prompt para crear scaffolding de un nuevo módulo con tests y documentación

---
name: Nuevo Módulo
description: Genera la estructura completa para un nuevo módulo de LAS-FOCAS
mode: agent
variables:
  - name: nombre_modulo
    description: Nombre del módulo a crear (ej. informes_vlan, parser_nokia)
  - name: ubicacion
    default: modules/
    description: Ubicación del módulo (modules/, core/, etc.)
  - name: descripcion
    description: Descripción breve del propósito del módulo
---

# Crear Nuevo Módulo: ${nombre_modulo}

Genera la estructura completa para el módulo `${nombre_modulo}` en `${ubicacion}`.

## Estructura a Crear

```
${ubicacion}${nombre_modulo}/
├── __init__.py
├── config.py       # Configuración del módulo
├── schemas.py      # Modelos Pydantic
├── processor.py    # Lógica de procesamiento
├── service.py      # API de servicio
└── README.md       # Documentación del módulo
```

## Archivos a Generar

### 1. `__init__.py`
```python
# Nombre de archivo: __init__.py
# Ubicación de archivo: ${ubicacion}${nombre_modulo}/__init__.py
# Descripción: Inicializador del módulo ${nombre_modulo}

"""
Módulo ${nombre_modulo}
${descripcion}
"""

from .service import ${nombre_modulo.title().replace('_', '')}Service
from .schemas import *

__all__ = ["${nombre_modulo.title().replace('_', '')}Service"]
```

### 2. `config.py`
```python
# Nombre de archivo: config.py
# Ubicación de archivo: ${ubicacion}${nombre_modulo}/config.py
# Descripción: Configuración del módulo ${nombre_modulo}

"""Configuración del módulo ${nombre_modulo}."""

import os
from pydantic import BaseSettings

class ${nombre_modulo.title().replace('_', '')}Config(BaseSettings):
    """Configuración para ${nombre_modulo}."""
    
    enabled: bool = True
    timeout: int = 30
    # Agregar configuraciones específicas
    
    class Config:
        env_prefix = "${nombre_modulo.upper()}_"

config = ${nombre_modulo.title().replace('_', '')}Config()
```

### 3. `schemas.py`
```python
# Nombre de archivo: schemas.py
# Ubicación de archivo: ${ubicacion}${nombre_modulo}/schemas.py
# Descripción: Modelos Pydantic del módulo ${nombre_modulo}

"""Schemas del módulo ${nombre_modulo}."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class ${nombre_modulo.title().replace('_', '')}Request(BaseModel):
    """Request para ${nombre_modulo}."""
    # Definir campos de entrada
    pass

class ${nombre_modulo.title().replace('_', '')}Response(BaseModel):
    """Response de ${nombre_modulo}."""
    success: bool
    message: str
    data: Optional[dict] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

### 4. `processor.py`
```python
# Nombre de archivo: processor.py
# Ubicación de archivo: ${ubicacion}${nombre_modulo}/processor.py
# Descripción: Lógica de procesamiento del módulo ${nombre_modulo}

"""Procesador del módulo ${nombre_modulo}."""

import logging
from typing import Any
from .schemas import ${nombre_modulo.title().replace('_', '')}Request, ${nombre_modulo.title().replace('_', '')}Response

logger = logging.getLogger(__name__)

class ${nombre_modulo.title().replace('_', '')}Processor:
    """Procesador principal de ${nombre_modulo}."""
    
    def __init__(self):
        """Inicializar procesador."""
        logger.info("${nombre_modulo} processor inicializado")
    
    async def process(self, request: ${nombre_modulo.title().replace('_', '')}Request) -> ${nombre_modulo.title().replace('_', '')}Response:
        """
        Procesar request.
        
        Args:
            request: Datos de entrada
            
        Returns:
            Response con resultado del procesamiento
        """
        try:
            # TODO: Implementar lógica de procesamiento
            logger.info("Procesando request", extra={"module": "${nombre_modulo}"})
            
            return ${nombre_modulo.title().replace('_', '')}Response(
                success=True,
                message="Procesamiento completado",
                data={}
            )
        except Exception as e:
            logger.exception("Error en procesamiento")
            return ${nombre_modulo.title().replace('_', '')}Response(
                success=False,
                message=str(e)
            )
```

### 5. `service.py`
```python
# Nombre de archivo: service.py
# Ubicación de archivo: ${ubicacion}${nombre_modulo}/service.py
# Descripción: API de servicio del módulo ${nombre_modulo}

"""Servicio del módulo ${nombre_modulo}."""

from .processor import ${nombre_modulo.title().replace('_', '')}Processor
from .schemas import ${nombre_modulo.title().replace('_', '')}Request, ${nombre_modulo.title().replace('_', '')}Response
from .config import config

class ${nombre_modulo.title().replace('_', '')}Service:
    """Servicio principal de ${nombre_modulo}."""
    
    def __init__(self):
        """Inicializar servicio."""
        self.processor = ${nombre_modulo.title().replace('_', '')}Processor()
        self.config = config
    
    async def execute(self, request: ${nombre_modulo.title().replace('_', '')}Request) -> ${nombre_modulo.title().replace('_', '')}Response:
        """
        Ejecutar el servicio.
        
        Args:
            request: Request con datos de entrada
            
        Returns:
            Response con resultado
        """
        if not self.config.enabled:
            return ${nombre_modulo.title().replace('_', '')}Response(
                success=False,
                message="Módulo deshabilitado"
            )
        
        return await self.processor.process(request)
```

## Tests a Crear

### `tests/test_${nombre_modulo}.py`
```python
# Nombre de archivo: test_${nombre_modulo}.py
# Ubicación de archivo: tests/test_${nombre_modulo}.py
# Descripción: Tests del módulo ${nombre_modulo}

"""Tests para el módulo ${nombre_modulo}."""

import pytest
from ${ubicacion.replace('/', '.')}${nombre_modulo} import (
    ${nombre_modulo.title().replace('_', '')}Service,
    ${nombre_modulo.title().replace('_', '')}Request,
    ${nombre_modulo.title().replace('_', '')}Response,
)

@pytest.fixture
def service():
    """Fixture del servicio."""
    return ${nombre_modulo.title().replace('_', '')}Service()

@pytest.fixture
def sample_request():
    """Fixture de request de ejemplo."""
    return ${nombre_modulo.title().replace('_', '')}Request()

class Test${nombre_modulo.title().replace('_', '')}Service:
    """Tests del servicio ${nombre_modulo}."""
    
    @pytest.mark.asyncio
    async def test_execute_success(self, service, sample_request):
        """Test de ejecución exitosa."""
        response = await service.execute(sample_request)
        assert response.success is True
        assert response.message == "Procesamiento completado"
    
    @pytest.mark.asyncio
    async def test_execute_disabled(self, service, sample_request, monkeypatch):
        """Test con módulo deshabilitado."""
        monkeypatch.setattr(service.config, "enabled", False)
        response = await service.execute(sample_request)
        assert response.success is False
        assert "deshabilitado" in response.message.lower()
```

## Documentación a Crear

### `docs/${nombre_modulo}.md`
Crear documentación básica del módulo en `docs/`.

## Checklist Post-Creación

1. [ ] Ejecutar tests: `pytest tests/test_${nombre_modulo}.py -v`
2. [ ] Verificar imports: `python -c "from ${ubicacion.replace('/', '.')}${nombre_modulo} import *"`
3. [ ] Actualizar `docs/Mate_y_Ruta.md` con el nuevo módulo
4. [ ] Generar PR diario con los cambios
