# Nombre de archivo: test_spa_capa_api.py
# Ubicación de archivo: tests/test_spa_capa_api.py
# Descripción: Guardia estática del SPA — fetch, CSRF y transportes crudos sólo dentro de la capa api/ (P10)

"""Escaneo de texto sobre `web/frontend/src/**/*.{ts,vue}` (sin backend).

La capa HTTP del SPA es `src/api/client.ts` (`request`, `requestJson`, `requestDownload`), que pone el
header `X-CSRF-Token` en todo método mutante. Estos tests impiden que vuelvan `fetch(`, CSRF armado a mano
o transportes crudos fuera de esa capa: no hay excepciones.

Capa api = los directorios `api/` del SPA (`src/api/` y `src/admin/api/`, que también usa `client.ts`).
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "web" / "frontend" / "src"

CSRF_A_MANO = re.compile(r"csrf_token|X-CSRF-Token|\bcsrf\(\)")
FETCH = re.compile(r"\bfetch\(")
# Import (de una o varias líneas) desde el cliente HTTP; se captura la lista de nombres importados.
IMPORT_CLIENT = re.compile(r"import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*['\"][./]*(?:api/)?client['\"]", re.S)
TRANSPORTE_HTTP = {"request", "requestJson", "requestDownload"}


def _fuentes() -> dict[str, str]:
    """Todos los `.ts`/`.vue` del SPA: ruta relativa a `src` (con `/`) -> texto."""
    fuentes = {
        p.relative_to(SRC).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(SRC.rglob("*"))
        if p.suffix in {".ts", ".vue"} and "node_modules" not in p.parts
    }
    # Sanidad: si la ruta base cambia, los tests de abajo pasarían en vacío.
    assert len(fuentes) > 100, f"se esperaban >100 fuentes del SPA en {SRC}, hay {len(fuentes)}"
    return fuentes


def _en_capa_api(ruta: str) -> bool:
    return ruta.startswith(("api/", "admin/api/"))


def _fuera_de_api() -> dict[str, str]:
    return {r: t for r, t in _fuentes().items() if not _en_capa_api(r)}


def test_fetch_solo_en_client_ts() -> None:
    # El único `fetch(` del SPA es el de `api/client.ts`: el resto de la capa api pasa por request().
    con_fetch = sorted(r for r, t in _fuentes().items() if FETCH.search(t))
    assert con_fetch == ["api/client.ts"], f"fetch( fuera de api/client.ts (usar request/requestJson): {con_fetch}"


def test_cliente_http_solo_desde_capa_api() -> None:
    # Fuera de api/ y admin/api/ nadie importa request/requestJson/requestDownload: toda llamada HTTP
    # es una función tipada de la capa api. Importar ApiError, saveBlob, setCsrfToken o tipos sí se permite.
    infractores = {}
    for r, t in _fuera_de_api().items():
        for lista in IMPORT_CLIENT.findall(t):
            nombres = {n.strip().removeprefix("type ").split(" as ")[0].strip() for n in lista.split(",")}
            usados = sorted(nombres & TRANSPORTE_HTTP)
            if usados:
                infractores[r] = usados
    assert not infractores, f"transporte HTTP de client.ts importado fuera de api/: {infractores}"


def test_sin_csrf_a_mano_fuera_de_api() -> None:
    # El CSRF lo pone `request()`; armarlo a mano fuera de api/ no se tolera.
    a_mano = sorted(r for r, t in _fuera_de_api().items() if CSRF_A_MANO.search(t))
    assert not a_mano, f"CSRF armado a mano fuera de src/api/: {a_mano}"


def test_transportes_crudos_solo_en_api_o_composables() -> None:
    # XMLHttpRequest sólo en api/; EventSource sólo en composables/ (useCorridaSse).
    xhr, sse = [], []
    for r, t in _fuera_de_api().items():
        if "XMLHttpRequest" in t:
            xhr.append(r)
        if "new EventSource" in t and not r.startswith("composables/"):
            sse.append(r)
    assert not xhr, f"XMLHttpRequest fuera de src/api/: {sorted(xhr)}"
    assert not sse, f"new EventSource fuera de composables/: {sorted(sse)}"


def test_xhr_mutante_lleva_header_csrf() -> None:
    # Un XHR mutante (POST/PUT/PATCH/DELETE) en api/ debe mandar el header CSRF: no pasa por request().
    mutante = re.compile(r"xhr\.open\(\s*['\"](POST|PUT|PATCH|DELETE)['\"]")
    sin_header = [
        r
        for r, t in _fuentes().items()
        if _en_capa_api(r) and mutante.search(t) and "setRequestHeader(CSRF_HEADER" not in t
    ]
    assert not sin_header, f"XHR mutante sin header CSRF: {sin_header}"
