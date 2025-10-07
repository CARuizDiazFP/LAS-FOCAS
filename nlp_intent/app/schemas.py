# Nombre de archivo: schemas.py
# Ubicación de archivo: nlp_intent/app/schemas.py
# Descripción: Esquemas pydantic para solicitudes y respuestas del servicio

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


class IntentRequest(BaseModel):
    text: str = Field(..., description="Texto del usuario")


class IntentResponse(BaseModel):
    intent: Literal["Consulta", "Acción", "Otros"]
    confidence: float
    provider: str
    normalized_text: str

    model_config = ConfigDict(from_attributes=True)


class IntentionResult(BaseModel):
    """Resultado enriquecido de la etapa de análisis de intención.

    Campos:
    - intention_raw: etiqueta original devuelta por el clasificador primario (Consulta|Acción|Otros).
    - intention: etiqueta normalizada final (Consulta/Generico|Solicitud de acción|Otros).
    - confidence: confianza reportada por el proveedor (o heurística derivada).
    - provider: nombre del proveedor utilizado.
    - normalized_text: texto normalizado.
    - need_clarification: indica si se requiere clarificar (caso Otros ambiguo / baja confianza).
    - clarification_question: pregunta sugerida (presente solo si need_clarification=True).
    - next_action: placeholder para futura orquestación de flujos (None en esta fase).
    """

    intention_raw: Literal["Consulta", "Acción", "Otros"]
    intention: Literal["Consulta/Generico", "Solicitud de acción", "Otros"]
    confidence: float
    provider: str
    normalized_text: str
    need_clarification: bool = False
    clarification_question: str | None = None
    next_action: str | None = None
    # Fase 2
    action_code: str | None = None
    action_supported: bool | None = None
    action_reason: str | None = None
    answer: str | None = None
    answer_source: str | None = None
    domain_confidence: float | None = None
    schema_version: int = 2

    model_config = ConfigDict(from_attributes=True)

