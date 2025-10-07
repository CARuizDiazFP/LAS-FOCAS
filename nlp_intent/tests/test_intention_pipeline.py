# Nombre de archivo: test_intention_pipeline.py
# Ubicación de archivo: nlp_intent/tests/test_intention_pipeline.py
# Descripción: Pruebas del nuevo pipeline analyze_intention (mapping y clarificación)

from __future__ import annotations

import os
import sys
import pathlib
import asyncio

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("LLM_PROVIDER", "heuristic")  # Evitar llamadas externas

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))

from nlp_intent.app.service import analyze_intention, settings  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def test_pipeline_accion():
    r = _run(analyze_intention("generá el informe SLA de julio"))
    assert r.intention_raw == "Acción"
    assert r.intention == "Solicitud de acción"
    assert not r.need_clarification


def test_pipeline_consulta():
    r = _run(analyze_intention("¿cómo genero el informe de repetitividad?"))
    assert r.intention_raw == "Consulta"
    assert r.intention == "Consulta/Generico"
    assert not r.need_clarification


def test_pipeline_otros_clarificacion(monkeypatch):
    # Forzamos heurística a devolver Otros bajando reglas (texto neutro)
    r = _run(analyze_intention("hola"))
    assert r.intention_raw == "Otros"
    assert r.intention == "Otros"
    assert r.need_clarification
    assert r.clarification_question
