# Nombre de archivo: test_intent.py
# Ubicación de archivo: nlp_intent/tests/test_intent.py
# Descripción: Pruebas del clasificador de intención con dataset mínimo

from __future__ import annotations

import asyncio
import os
from unittest import mock

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
# config de nlp_intent valida al importarse; TESTING=true dura sólo el import (no se filtra al resto de la suite).
with mock.patch.dict(os.environ, {"TESTING": "true"}):
    from nlp_intent.app.service import classify_text, settings as svc_settings

TEST_DATA = [
    ("hola", "Otros"),
    ("buen día", "Otros"),
    ("gracias", "Otros"),
    ("qué onda?", "Otros"),
    ("¿cómo genero el informe de repetitividad?", "Consulta"),
    ("qué es el comparador de FO?", "Consulta"),
    ("podés explicarme SLA?", "Consulta"),
    ("generá el informe SLA de julio", "Acción"),
    ("armá el reporte de repetitividad de agosto 2025", "Acción"),
    ("enviá el informe por correo", "Acción"),
    ("ejecutá el comparador FO contra archivo X", "Acción"),
    ("actualizá los datos", "Acción"),
]


def test_dataset_accuracy(monkeypatch):
    # Forzar proveedor heurístico en runtime (config ya cargada)
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")
    svc_settings.llm_provider = "heuristic"
    # Nota: este test fuerza heurística para evitar llamadas a OpenAI en CI.
    async def _run():
        hits = 0
        for text, expected in TEST_DATA:
            resp = await classify_text(text)
            if resp.intent == expected:
                hits += 1
        return hits / len(TEST_DATA)

    accuracy = asyncio.run(_run())
    # Dado el dataset reducido la heurística debe alcanzar al menos 0.75
    assert accuracy >= 0.75


