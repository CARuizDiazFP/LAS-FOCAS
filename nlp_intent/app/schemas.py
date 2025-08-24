# Nombre de archivo: schemas.py
# Ubicación de archivo: nlp_intent/app/schemas.py
# Descripción: Esquemas pydantic para solicitudes y respuestas del servicio

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IntentRequest(BaseModel):
    text: str = Field(..., description="Texto del usuario")


class IntentResponse(BaseModel):
    intent: Literal["Consulta", "Acción", "Otros"]
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Nivel de confianza devuelto por el proveedor"
    )
    provider: str
    normalized_text: str

    class Config:
        orm_mode = True


class ProviderConfig(BaseModel):
    llm_provider: Literal["auto", "heuristic", "ollama", "openai"] = Field(
        ..., description="Proveedor LLM activo"
    )


