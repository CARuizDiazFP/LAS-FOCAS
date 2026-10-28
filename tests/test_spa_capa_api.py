# Nombre de archivo: test_spa_capa_api.py
# Ubicación de archivo: tests/test_spa_capa_api.py
# Descripción: Guardia estática del SPA — fetch, CSRF y transportes crudos sólo dentro de la capa api/ (P10)

"""Escaneo de texto sobre `web/frontend/src/**/*.{ts,vue}` (sin backend).

La capa HTTP del SPA es `src/api/client.ts` (`request`, `requestJson`, `requestDownload`), que pone el
header `X-CSRF-Token` en todo método mutante. Estos tests impiden que vuelvan `fetch(`, CSRF armado a mano
o transportes crudos fuera de esa capa. `PENDIENTES_FETCH` es la lista de archivos todavía sin migrar:
cada tarea de P10 la achica y la última la deja vacía.

Capa api = los directorios `api/` del SPA (`src/api/` y `src/admin/api/`, que también usa `client.ts`).
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "web" / "frontend" / "src"

# Archivos con `fetch(` aún sin migrar a la capa api/ (rutas relativas a web/frontend/src).
PENDIENTES_FETCH: set[str] = {
    "views/ReportsHistoryView.vue",
    "views/tabs/VlanTab.vue",
    "views/tabs/InfraTab.vue",
    "views/tabs/RepetitividadTab.vue",
    "composables/useTracking.ts",
    "views/tabs/ChatTab.vue",
}

# EventSource directo aún fuera de composables/ (se migran a useCorridaSse).
PENDIENTES_SSE: set[str] = {
    "admin/views/AdminHuerfanosViewer.vue",
    "admin/views/AdminIngestaCromo.vue",
}

CSRF_A_MANO = re.compile(r"csrf_token|X-CSRF-Token|\bcsrf\(\)")
FETCH = re.compile(r"\bfetch\(")


def _fuentes() -> dict[str, str]:
    """Todos los `.ts`/`.vue` del SPA: ruta relativa a `src` (con `/`) -> texto."""
    return {
        p.relative_to(SRC).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(SRC.rglob("*"))
        if p.suffix in {".ts", ".vue"} and "node_modules" not in p.parts
    }


def _en_capa_api(ruta: str) -> bool:
    return ruta.startswith(("api/", "admin/api/"))


def _fuera_de_api() -> dict[str, str]:
    return {r: t for r, t in _fuentes().items() if not _en_capa_api(r)}


def test_fetch_solo_en_capa_api() -> None:
    # `fetch(` fuera de api/ sólo se tolera en los archivos pendientes de migrar.
    con_fetch = {r for r, t in _fuera_de_api().items() if FETCH.search(t)}
    sobran = sorted(con_fetch - PENDIENTES_FETCH)
    assert not sobran, f"fetch( fuera de src/api/ (usar request/requestJson): {sobran}"


def test_pendientes_siguen_pendientes() -> None:
    # Obliga a sacar del set el archivo apenas se migra: el set sólo se achica.
    fuentes = _fuentes()
    migrados = sorted(r for r in PENDIENTES_FETCH if r not in fuentes or not FETCH.search(fuentes[r]))
    assert not migrados, f"ya sin fetch( — quitar de PENDIENTES_FETCH: {migrados}"


def test_sin_csrf_a_mano_fuera_de_api() -> None:
    # El CSRF lo pone `request()`; armarlo a mano fuera de api/ se tolera sólo junto a un fetch pendiente.
    a_mano = {r for r, t in _fuera_de_api().items() if CSRF_A_MANO.search(t)}
    sobran = sorted(a_mano - PENDIENTES_FETCH)
    assert not sobran, f"CSRF armado a mano fuera de src/api/: {sobran}"


def test_transportes_crudos_solo_en_api_o_composables() -> None:
    # XMLHttpRequest sólo en api/; EventSource sólo en composables/ (más los pendientes de migrar).
    xhr, sse = [], []
    for r, t in _fuera_de_api().items():
        if "XMLHttpRequest" in t:
            xhr.append(r)
        if "new EventSource" in t and not r.startswith("composables/") and r not in PENDIENTES_SSE:
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
