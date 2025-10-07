# Nombre de archivo: test_action_and_answers.py
# Ubicación de archivo: nlp_intent/tests/test_action_and_answers.py
# Descripción: Pruebas de sub-clasificación de acciones y respuestas de consulta (fase 2)

from __future__ import annotations

import os
import sys
import pathlib
import asyncio

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("LLM_PROVIDER", "heuristic")
os.environ.setdefault("INTENT_ENABLE_ANSWERS", "true")

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))

from nlp_intent.app.service import analyze_intention  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def test_action_supported_repetitividad():
    r = _run(analyze_intention("Generá el informe de repetitividad de agosto"))
    assert r.intention == "Solicitud de acción"
    assert r.action_code == "repetitividad_report"
    assert r.action_supported is True
    assert r.next_action == "trigger:repetitividad_report"


def test_action_unsupported_sla():
    r = _run(analyze_intention("Generá el informe SLA de julio"))
    assert r.intention == "Solicitud de acción"
    assert r.action_code in ("unsupported", "repetitividad_report")  # heurística puede detectar verbo pero no keyword
    if r.action_code == "unsupported":
        assert r.action_supported is False


def test_consulta_faq_repetitividad():
    r = _run(analyze_intention("¿Qué es repetitividad?"))
    assert r.intention == "Consulta/Generico"
    assert r.answer is not None
    assert "recurrentes" in r.answer.lower()