# Nombre de archivo: agent-nlp-agent.md
# Ubicación de archivo: .gemini/rules/agent-nlp-agent.md
# Descripción: Regla Gemini portable migrada desde .github/agents/nlp.agent.md
---
name: "agent-nlp-agent"
description: "Usar cuando la tarea trate de clasificación de intención, providers heurístico/OpenAI o compatibilidad heredada con Ollama dentro de nlp_intent/"
source: ".github/agents/nlp.agent.md"
triggers:
  - "nlp"
  - "agente"
  - "trate"
  - "clasificaci-n"
  - "intenci-n"
  - "providers"
  - "heur-stico"
  - "openai"
  - "compatibilidad"
  - "heredada"
  - "ollama"
  - "dentro"
  - "nlp-intent"
globs:
  - "api/**"
  - "api_app/**"
  - "bot_telegram/**"
  - "modules/informes_sla/**"
  - "core/sla/**"
  - "Templates/**"
  - "docs/informes/sla.md"
  - "modules/informes_repetitividad/**"
  - "docs/informes/repetitividad.md"
  - "nlp_intent/**"
  - "core/mcp/**"
  - "core/chatbot/**"
commands:
  []
---

# Regla Agente: NLP Agent

> Fuente original: `.github/agents/nlp.agent.md`. Aplicar cuando el pedido coincida con esta automatización.

# Agente NLP

Soy el agente especializado en procesamiento de lenguaje natural de LAS-FOCAS.

## Mi Alcance

- Clasificación de intención del usuario
- Proveedores de NLP (heurístico, OpenAI y compatibilidad heredada con Ollama)
- Entrenamiento y ajuste de modelos
- Métricas de precisión

## Estructura

```
nlp_intent/
├── __init__.py
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app
│   ├── config.py        # Configuración
│   ├── classifier.py    # Clasificador principal
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py      # Interfaz base
│   │   ├── heuristic.py # Basado en reglas
│   │   ├── ollama.py    # Compatibilidad heredada con Ollama
│   │   └── openai.py    # OpenAI API
│   └── intents/
│       ├── __init__.py
│       └── definitions.py  # Definiciones de intenciones
└── tests/
    └── test_classifier.py
```

## Intenciones Definidas

| Intent | Descripción | Ejemplos |
|--------|-------------|----------|
| `informe_sla` | Solicitar informe SLA | "Quiero un informe SLA", "Generar SLA" |
| `informe_repetitividad` | Informe de repetitividad | "Informe de repetitividad", "Reporte de alarmas" |
| `buscar_infraestructura` | Buscar en infra | "Buscar cliente X", "¿Dónde está Y?" |
| `saludo` | Saludos | "Hola", "Buenos días" |
| `ayuda` | Solicitar ayuda | "Help", "Ayuda", "¿Qué puedes hacer?" |
| `desconocido` | No clasificable | - |

## Arquitectura del Clasificador

```
Mensaje del usuario
        ↓
┌───────────────────┐
│   Classifier      │
│  (main entry)     │
└────────┬──────────┘
         │
    ┌────┴────┐
    ↓         ↓
Heuristic  LLM Provider
(rápido)   (OpenAI/compat)
    ↓         ↓
    └────┬────┘
         ↓
   IntentResult
   - intent: str
   - confidence: float
   - entities: dict
```

## Provider Pattern

```python
# providers/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel

class IntentResult(BaseModel):
    intent: str
    confidence: float
    entities: dict = {}

class IntentProvider(ABC):
    @abstractmethod
    async def classify(self, text: str) -> IntentResult:
        pass

# providers/heuristic.py
class HeuristicProvider(IntentProvider):
    PATTERNS = {
        "informe_sla": ["sla", "acuerdo de nivel"],
        "informe_repetitividad": ["repetitividad", "alarmas repetidas"],
        "buscar_infraestructura": ["buscar", "donde está", "encontrar"],
    }

    async def classify(self, text: str) -> IntentResult:
        text_lower = text.lower()
        for intent, keywords in self.PATTERNS.items():
            if any(kw in text_lower for kw in keywords):
                return IntentResult(intent=intent, confidence=0.8)
        return IntentResult(intent="desconocido", confidence=0.5)
```

## Endpoint de Clasificación

```python
# app/main.py
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="NLP Intent Service")

class ClassifyRequest(BaseModel):
    text: str
    provider: str = "openai"  # openai, heuristic, auto, ollama(legacy)

class ClassifyResponse(BaseModel):
    intent: str
    confidence: float
    entities: dict
    provider_used: str

@app.post("/classify", response_model=ClassifyResponse)
async def classify_intent(request: ClassifyRequest):
    result = await classifier.classify(request.text, provider=request.provider)
    return ClassifyResponse(
        intent=result.intent,
        confidence=result.confidence,
        entities=result.entities,
        provider_used=classifier.last_provider
    )
```

## Reglas que Sigo

1. **Fallback a heurístico**: si LLM falla, usar reglas
2. **Confidence threshold**: < 0.6 = desconocido
3. **Mock en tests**: nunca llamar a OpenAI en tests
4. **Cache de resultados**: cachear clasificaciones frecuentes
5. **Logging de clasificaciones**: registrar para mejorar modelo
6. **Timeout de LLM**: máximo 5s para clasificación

## Configuración

```
NLP_DEFAULT_PROVIDER=openai  # openai, heuristic, auto, ollama(legacy)
NLP_OLLAMA_URL=http://localhost:11434  # sólo para compatibilidad heredada
NLP_OPENAI_API_KEY=sk-xxx
NLP_CONFIDENCE_THRESHOLD=0.6
```

## Documentación

- `docs/nlp/intent.md` - Documentación del clasificador

## Traspasos (Handoffs)

- **→ MCP Chatbot Agent**: cuando la clasificación está lista para integrar
- **→ Bot Agent**: para ajustar clasificación de comandos de Telegram
