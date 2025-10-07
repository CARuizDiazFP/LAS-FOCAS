# Nombre de archivo: faq_data.py
# Ubicación de archivo: modules/common/faq_data.py
# Descripción: Base de conocimientos mínima (FAQ) para respuestas rápidas de consultas dominio telecom

from __future__ import annotations

FAQ_ENTRIES = [
    {
        "patterns": ["que es sla", "qué es sla", "sla"],
        "answer": "El SLA (Service Level Agreement) define compromisos de disponibilidad y tiempos de respuesta entre el proveedor y el cliente. Incluye métricas como disponibilidad porcentual, tiempo de reparación y ventanas de mantenimiento.",
    },
    {
        "patterns": ["que es repetitividad", "qué es repetitividad", "repetitividad"],
        "answer": "La repetitividad identifica servicios o elementos de red con incidencias recurrentes en un período, ayudando a priorizar acciones preventivas.",
    },
    {
        "patterns": ["fiber", "fibra", "corte de fibra"],
        "answer": "Un corte de fibra implica pérdida de continuidad física en el enlace óptico; suele reflejarse como caída total o degradación severa de niveles ópticos. Se diagnostica con OTDR y monitoreo de potencia.",
    },
]


def match_faq(normalized: str) -> str | None:
    for item in FAQ_ENTRIES:
        for p in item["patterns"]:
            if p in normalized:
                return item["answer"]
    return None
