# Nombre de archivo: test_web_event_loop_sin_io_sync.py
# Ubicación de archivo: tests/test_web_event_loop_sin_io_sync.py
# Descripción: Guardia AST: ningún endpoint async del panel hace I/O sync en el event loop

"""El panel web corre uvicorn con un solo proceso: un endpoint `async def` que abre una `Session`
sync, conecta con psycopg, verifica bcrypt o habla con Slack/SMTP/Docker sin pasar por un hilo congela
el panel, el chat y los WebSocket de todos los usuarios mientras dura. La auditoría del 2026-10-24
encontró 66 casos; este test evita que vuelvan.

Regla: si el endpoint no hace `await` de nada, que sea `def` (FastAPI lo corre en el threadpool); si
mezcla, la parte sync va en una función que se pasa a `asyncio.to_thread`. Detecta llamadas directas
en el cuerpo del endpoint y en funciones anidadas que se invoquen sin `to_thread`."""

from __future__ import annotations

import ast
from pathlib import Path

ROUTERS = Path(__file__).resolve().parents[1] / "web" / "app" / "routers"
METODOS = {"get", "post", "put", "patch", "delete", "websocket", "api_route"}
ENVOLTORIOS = {"to_thread", "run_in_threadpool", "run_in_executor"}
PREFIJOS_IO = ("smtplib.", "requests.", "subprocess.", "docker_sdk.", "httpx.get", "httpx.post", "httpx.Client")
NOMBRES_IO = {"SessionLocal", "verify_password", "psycopg.connect"}


def _nombre(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        base = f.value
        prefijo = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else ""
        return f"{prefijo}.{f.attr}"
    return ""


def _es_io_sync(nombre: str) -> bool:
    return nombre in NOMBRES_IO or nombre.startswith(PREFIJOS_IO) or nombre.endswith(".chat_postMessage")


def _llamadas_directas(nodo: ast.AST) -> list[ast.Call]:
    """Llamadas del cuerpo sin entrar a funciones ni lambdas anidadas."""
    llamadas, pila = [], list(ast.iter_child_nodes(nodo))
    while pila:
        n = pila.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(n, ast.Call):
            llamadas.append(n)
        pila.extend(ast.iter_child_nodes(n))
    return llamadas


def _es_endpoint(fn: ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in METODOS
        for d in fn.decorator_list
    )


def _hallazgos(fn: ast.AsyncFunctionDef) -> list[str]:
    anidadas = {n.name: n for n in ast.walk(fn) if isinstance(n, ast.FunctionDef)}
    directas = _llamadas_directas(fn)
    en_hilo = {
        arg.id
        for c in directas
        if _nombre(c).split(".")[-1] in ENVOLTORIOS
        for arg in c.args
        if isinstance(arg, ast.Name)
    }
    hallazgos = []
    for c in directas:
        nombre = _nombre(c)
        if _es_io_sync(nombre):
            hallazgos.append(f"{nombre}:{c.lineno}")
        elif isinstance(c.func, ast.Name) and c.func.id in anidadas and c.func.id not in en_hilo:
            hallazgos += [
                f"{c.func.id}->{_nombre(cc)}:{cc.lineno}"
                for cc in _llamadas_directas(anidadas[c.func.id])
                if _es_io_sync(_nombre(cc))
            ]
    return hallazgos


def test_ningun_endpoint_async_hace_io_sync_en_el_event_loop():
    encontrados = []
    for archivo in sorted(ROUTERS.glob("*.py")):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.AsyncFunctionDef) and _es_endpoint(nodo) and (h := _hallazgos(nodo)):
                encontrados.append(f"{archivo.name}::{nodo.name} {h}")
    assert encontrados == [], "I/O sync en el event loop:\n" + "\n".join(encontrados)


def test_la_guardia_detecta_los_casos_que_debe_detectar():
    fuente = '''
@router.get("/a")
async def directo():
    with SessionLocal() as s:
        pass

@router.post("/b")
async def anidada_sin_hilo():
    def _sync():
        return psycopg.connect(DSN)
    return _sync()

@router.post("/c")
async def anidada_en_hilo():
    def _sync():
        return psycopg.connect(DSN)
    return await asyncio.to_thread(_sync)

@router.get("/d")
def sync_ok():
    with SessionLocal() as s:
        pass
'''
    fns = {n.name: n for n in ast.walk(ast.parse(fuente)) if isinstance(n, ast.AsyncFunctionDef)}
    assert _hallazgos(fns["directo"]) == ["SessionLocal:4"]
    assert _hallazgos(fns["anidada_sin_hilo"]) == ["_sync->psycopg.connect:10"]
    assert _hallazgos(fns["anidada_en_hilo"]) == []
    assert "sync_ok" not in fns
