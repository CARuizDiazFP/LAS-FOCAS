#!/usr/bin/env python3
# Nombre de archivo: gen_tabla_migraciones.py
# Ubicación de archivo: scripts/gen_tabla_migraciones.py
# Descripción: Genera (solo lectura) la tabla Markdown del historial de migraciones Alembic en orden de cadena y la verifica contra docs/db.md

"""Tabla del historial de migraciones Alembic, generada desde `db/alembic/versions/`.

Lee cada `*.py` de versiones **sin importarlo** (parseo con `ast`, sólo stdlib) y extrae:

- `revision` y `down_revision` (con o sin anotación de tipo; `down_revision` puede ser tupla en un
  merge);
- la descripción del encabezado obligatorio (`# Descripción: ...`, con sus líneas de continuación),
  o la primera línea del docstring si no hay encabezado;
- la fecha: `Create Date:` del docstring o, si falta, el prefijo `AAAAMMDD` de la revisión.

Ordena por la cadena (`down_revision` → `revision`, desde la raíz) y emite la tabla Markdown por
stdout. Por stderr informa raíces, heads, merges, ramas (una revisión con más de un hijo) y
`down_revision` que apuntan a revisiones inexistentes.

Uso:

    python scripts/gen_tabla_migraciones.py                     # imprime la tabla
    python scripts/gen_tabla_migraciones.py --verificar docs/db.md

`--verificar` compara la tabla generada con el bloque entre los marcadores
`<!-- tabla-migraciones:inicio -->` y `<!-- tabla-migraciones:fin -->` del archivo indicado y sale
con código 1 si difieren. Nunca escribe archivos: para actualizar el doc, pegar la salida entre los
marcadores.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent
VERSIONES_DEFAULT = RAIZ_REPO / "db" / "alembic" / "versions"
MARCA_INICIO = "<!-- tabla-migraciones:inicio -->"
MARCA_FIN = "<!-- tabla-migraciones:fin -->"

_RE_DESCRIPCION = re.compile(r"^#\s*Descripci[oó]n:\s*(.*)$")
_RE_CONTINUACION = re.compile(r"^#\s+(?!Nombre de archivo:|Ubicaci[oó]n de archivo:)(\S.*)$")
_RE_CREATE_DATE = re.compile(r"^\s*Create Date:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
_RE_PREFIJO_FECHA = re.compile(r"^(\d{4})(\d{2})(\d{2})")


@dataclass
class Migracion:
    revision: str
    padres: tuple[str, ...]
    archivo: str
    descripcion: str
    fecha: str
    hijos: list[str] = field(default_factory=list)


def _valor_literal(nodo: ast.AST) -> tuple[str, ...]:
    """`None` → (); `"x"` → ("x",); `("a", "b")` → ("a", "b")."""
    valor = ast.literal_eval(nodo)
    if valor is None:
        return ()
    if isinstance(valor, str):
        return (valor,)
    return tuple(str(v) for v in valor)


def _asignaciones(arbol: ast.Module) -> dict[str, ast.AST]:
    encontrados: dict[str, ast.AST] = {}
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign):
            for destino in nodo.targets:
                if isinstance(destino, ast.Name):
                    encontrados[destino.id] = nodo.value
        elif isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name) and nodo.value is not None:
            encontrados[nodo.target.id] = nodo.value
    return encontrados


def _descripcion(texto: str, docstring: str | None) -> str:
    lineas = texto.splitlines()
    for indice, linea in enumerate(lineas[:20]):
        coincidencia = _RE_DESCRIPCION.match(linea.strip())
        if not coincidencia:
            continue
        partes = [coincidencia.group(1).strip()]
        for siguiente in lineas[indice + 1 : indice + 6]:
            continuacion = _RE_CONTINUACION.match(siguiente.strip())
            if not continuacion:
                break
            partes.append(continuacion.group(1).strip())
        return " ".join(p for p in partes if p)
    if docstring:
        for linea in docstring.strip().splitlines():
            if linea.strip() and not linea.strip().startswith("#"):
                return linea.strip()
    return ""


def _fecha(revision: str, docstring: str | None) -> str:
    if docstring:
        coincidencia = _RE_CREATE_DATE.search(docstring)
        if coincidencia:
            return coincidencia.group(1)
    prefijo = _RE_PREFIJO_FECHA.match(revision)
    if prefijo:
        return "-".join(prefijo.groups())
    return ""


def leer_migraciones(directorio: Path) -> dict[str, Migracion]:
    migraciones: dict[str, Migracion] = {}
    for ruta in sorted(directorio.glob("*.py")):
        if ruta.name == "__init__.py":
            continue
        texto = ruta.read_text(encoding="utf-8")
        arbol = ast.parse(texto, filename=str(ruta))
        valores = _asignaciones(arbol)
        if "revision" not in valores:
            print(f"aviso: {ruta.name} no define `revision`; se omite", file=sys.stderr)
            continue
        revision = _valor_literal(valores["revision"])[0]
        padres = _valor_literal(valores["down_revision"]) if "down_revision" in valores else ()
        docstring = ast.get_docstring(arbol)
        if revision in migraciones:
            print(f"aviso: revisión duplicada {revision} ({ruta.name})", file=sys.stderr)
        migraciones[revision] = Migracion(
            revision=revision,
            padres=padres,
            archivo=ruta.name,
            descripcion=_descripcion(texto, docstring),
            fecha=_fecha(revision, docstring),
        )
    for migracion in migraciones.values():
        for padre in migracion.padres:
            if padre in migraciones:
                migraciones[padre].hijos.append(migracion.revision)
    return migraciones


def orden_de_cadena(migraciones: dict[str, Migracion]) -> list[Migracion]:
    """Orden topológico (Kahn) desde las raíces; empates por revisión, que es cronológica."""
    pendientes = {
        rev: sum(1 for p in m.padres if p in migraciones) for rev, m in migraciones.items()
    }
    listas = sorted(rev for rev, n in pendientes.items() if n == 0)
    orden: list[Migracion] = []
    while listas:
        actual = listas.pop(0)
        orden.append(migraciones[actual])
        for hijo in migraciones[actual].hijos:
            pendientes[hijo] -= 1
            if pendientes[hijo] == 0:
                listas.append(hijo)
        listas.sort()
    if len(orden) != len(migraciones):
        faltantes = sorted(set(migraciones) - {m.revision for m in orden})
        print(f"aviso: ciclo en la cadena; sin ordenar: {', '.join(faltantes)}", file=sys.stderr)
        orden.extend(migraciones[rev] for rev in faltantes)
    return orden


def resumen(migraciones: dict[str, Migracion]) -> list[str]:
    raices = sorted(r for r, m in migraciones.items() if not m.padres)
    heads = sorted(r for r, m in migraciones.items() if not m.hijos)
    merges = sorted(r for r, m in migraciones.items() if len(m.padres) > 1)
    ramas = sorted(r for r, m in migraciones.items() if len(m.hijos) > 1)
    colgadas = sorted(
        f"{r} → {p}" for r, m in migraciones.items() for p in m.padres if p not in migraciones
    )
    return [
        f"migraciones: {len(migraciones)}",
        f"raíces: {', '.join(raices) or '-'}",
        f"heads: {', '.join(heads) or '-'}",
        f"merges: {', '.join(merges) or '-'}",
        f"ramas (revisión con más de un hijo): {', '.join(ramas) or '-'}",
        f"down_revision inexistente: {', '.join(colgadas) or '-'}",
    ]


def _celda(texto: str) -> str:
    return texto.replace("|", "\\|").replace("\n", " ")


def tabla_markdown(orden: list[Migracion]) -> str:
    filas = [
        "| Revisión | Revisa a | Fecha | Archivo | Descripción |",
        "|----------|----------|-------|---------|-------------|",
    ]
    for m in orden:
        padres = ", ".join(f"`{p}`" for p in m.padres) or "—"
        filas.append(
            f"| `{m.revision}` | {padres} | {m.fecha} | `{m.archivo}` | {_celda(m.descripcion)} |"
        )
    return "\n".join(filas)


def bloque_del_doc(ruta: Path) -> str | None:
    texto = ruta.read_text(encoding="utf-8")
    if MARCA_INICIO not in texto or MARCA_FIN not in texto:
        return None
    return texto.split(MARCA_INICIO, 1)[1].split(MARCA_FIN, 1)[0].strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--versiones", type=Path, default=VERSIONES_DEFAULT, help="directorio de versiones Alembic")
    parser.add_argument("--verificar", type=Path, help="doc con el bloque entre marcadores a comparar")
    args = parser.parse_args(argv)

    migraciones = leer_migraciones(args.versiones)
    tabla = tabla_markdown(orden_de_cadena(migraciones))
    for linea in resumen(migraciones):
        print(linea, file=sys.stderr)

    if args.verificar is None:
        print(tabla)
        return 0

    actual = bloque_del_doc(args.verificar)
    if actual is None:
        print(f"error: {args.verificar} no tiene los marcadores {MARCA_INICIO} / {MARCA_FIN}", file=sys.stderr)
        return 1
    if actual != tabla.strip():
        print(f"desactualizada: la tabla de {args.verificar} no coincide con db/alembic/versions/", file=sys.stderr)
        return 1
    print(f"ok: la tabla de {args.verificar} está al día", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
