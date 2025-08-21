# Nombre de archivo: test_intent.py
# Ubicación de archivo: nlp_intent/tests/test_intent.py
# Descripción: Pruebas del clasificador de intención con dataset mínimo

from __future__ import annotations

import asyncio

import pytest
import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from nlp_intent.app.service import classify_text, cache

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
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")
    cache.clear()

    async def _run():
        hits = 0
        for text, expected in TEST_DATA:
            resp = await classify_text(text)
            if resp.intent == expected:
                hits += 1
        return hits / len(TEST_DATA)

    accuracy = asyncio.run(_run())
    assert accuracy >= 0.9


