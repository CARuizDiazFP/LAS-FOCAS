# Nombre de archivo: check_openai.py
# Ubicación de archivo: scripts/check_openai.py
# Descripción: Script rápido para verificar disponibilidad de la API de OpenAI y la variable OPENAI_API_KEY

from __future__ import annotations

import os
import sys
import json
import textwrap
from typing import Any

import httpx

API_URL = "https://api.openai.com/v1/models"


def exit_error(msg: str, code: int = 1) -> None:
    print(f"[ERROR] {msg}")
    sys.exit(code)


def main() -> None:
    key = os.getenv("OPENAI_API_KEY")
    provider = os.getenv("LLM_PROVIDER", "openai")
    if provider != "openai":
        print(f"[INFO] LLM_PROVIDER={provider} (este script se centra en openai, continuaré de todas formas)")
    if not key:
        exit_error("OPENAI_API_KEY no definida en el entorno.")

    headers = {"Authorization": f"Bearer {key}"}
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(API_URL, headers=headers)
    except httpx.HTTPError as exc:
        exit_error(f"Fallo HTTP al contactar OpenAI: {exc}")

    if resp.status_code == 401:
        exit_error("Credenciales inválidas (401 Unauthorized). Verificar la clave.")
    if resp.status_code >= 400:
        exit_error(f"Respuesta inesperada {resp.status_code}: {resp.text[:200]}")

    try:
        data: Any = resp.json()
    except json.JSONDecodeError:
        exit_error("No se pudo decodificar JSON de la respuesta de OpenAI")

    model_count = len(data.get("data", [])) if isinstance(data, dict) else 0
    print(f"[OK] Conexión exitosa a OpenAI. Modelos accesibles: {model_count}")
    if model_count:
        sample = data["data"][0]
        ident = sample.get("id", "?")
        print(f"[INFO] Ejemplo de modelo disponible: {ident}")

    print("\nSugerencia: ejecutar tests con 'LLM_PROVIDER=heuristic pytest -q' si no querés consumir la cuota de la API.")


if __name__ == "__main__":  # pragma: no cover
    try:
        main()
    except KeyboardInterrupt:
        print("Interrumpido por el usuario.")
        sys.exit(130)
