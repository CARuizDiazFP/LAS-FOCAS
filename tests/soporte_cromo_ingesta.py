# Nombre de archivo: soporte_cromo_ingesta.py
# Ubicación de archivo: tests/soporte_cromo_ingesta.py
# Descripción: Fakes y helpers compartidos por los tests de la ingesta de Cromo Red (test_cromo_ingesta*.py)

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

from core.services.cromo import ingesta
from db.models.cromo import CromoIngestaCorrida


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "cromo"


@dataclass
class _GeometriaFoFake:
    llamadas: list
    original: Any


@pytest.fixture(autouse=True)
def geometria_fo(monkeypatch) -> _GeometriaFoFake:
    """`_actualizar_geometria_fo` abre su propia `SessionLocal` sync: ningún test de orquestación
    puede pegarle a la DB real. Registra los `corrida_id` y conserva la función real."""
    fake = _GeometriaFoFake(llamadas=[], original=ingesta._actualizar_geometria_fo)

    async def _registrar(corrida_id: int) -> None:
        fake.llamadas.append(corrida_id)

    monkeypatch.setattr(ingesta, "_actualizar_geometria_fo", _registrar)
    return fake


class _NestedCM:
    """Emula `AsyncSession.begin_nested()`: no absorbe la excepción, igual que el savepoint real."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ResultadoFilas:
    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None

    def scalars(self):
        return _Escalares([f[0] for f in self._filas])


class _Escalares:
    def __init__(self, valores: list[Any]) -> None:
        self._valores = valores

    def all(self):
        return self._valores

    def first(self):
        return self._valores[0] if self._valores else None


class _SesionFake:
    """Reemplaza sólo lo que el servicio de ingesta necesita de AsyncSession."""

    def __init__(
        self,
        existentes: Optional[dict[tuple[type, int], Any]] = None,
        respuestas_execute: Optional[dict[str, list[tuple]]] = None,
    ) -> None:
        self._existentes = existentes or {}
        self._respuestas_execute = respuestas_execute or {}
        self.agregados: list[Any] = []
        self.eliminados: list[Any] = []
        self.gets = 0
        self.precargas = 0

    async def get(self, modelo_cls: type, pk: int) -> Any:
        self.gets += 1
        return self._existentes.get((modelo_cls, pk))

    def add(self, obj: Any) -> None:
        self.agregados.append(obj)
        # Refleja el identity map real de SQLAlchemy: un objeto con PK manual (n_id) ya asignada
        # es encontrable vía session.get() apenas se agrega, sin necesitar flush/commit
        # (verificado empíricamente contra una Session real — ver docstring de
        # _procesar_botella_completa en ingesta.py, protección de nombre_editado_manual).
        n_id = getattr(obj, "n_id", None)
        if n_id is not None:
            self._existentes[(type(obj), n_id)] = obj

    def begin_nested(self) -> _NestedCM:
        return _NestedCM()

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        # `precargar_por_n_id`: `select(Modelo).where(Modelo.n_id.in_(ids))`, respondido desde
        # `_existentes` como lo haría la base. Sin esto la precarga vería todo como inexistente.
        where = getattr(stmt, "whereclause", None)
        if getattr(getattr(where, "left", None), "key", None) == "n_id" and getattr(
            getattr(where, "operator", None), "__name__", ""
        ) == "in_op":
            self.precargas += 1
            entidad = stmt.column_descriptions[0]["entity"]
            ids = set(where.right.value)
            return _ResultadoFilas(
                [(obj,) for (cls, pk), obj in self._existentes.items() if cls is entidad and pk in ids]
            )
        texto = str(stmt)
        for clave, filas in self._respuestas_execute.items():
            if clave in texto:
                return _ResultadoFilas(filas)
        return _ResultadoFilas([])

    async def commit(self) -> None:
        return None

    async def delete(self, obj: Any) -> None:
        self.eliminados.append(obj)


# ── Orquestación de alto nivel (fases mockeadas, sólo se prueba el control de flujo) ──


class _SesionFakeCorrida(_SesionFake):
    def __init__(self) -> None:
        super().__init__()
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, obj: Any) -> None:
        if isinstance(obj, CromoIngestaCorrida) and obj.id is None:
            obj.id = 1
        if isinstance(obj, CromoIngestaCorrida):
            # continuar_corrida() re-obtiene la corrida por id con sesion.get(): que la encuentre.
            self._existentes[(CromoIngestaCorrida, obj.id)] = obj


# ── Fases con cliente/páginas fake ──────────────────────────────────────────


class _ClientePaginado:
    def __init__(self, paginas: list[dict]) -> None:
        self._paginas = paginas

    async def iterar_coleccion(self, filtro, *, psize=None, show=None, max_paginas=None):
        for pagina in self._paginas:
            yield pagina


# ── Contrato de `modo` (Task 3): SOLO_ODF vs COMPLETA ────────────────────────


def _spies_de_fases(monkeypatch, llamadas: list[str]) -> None:
    """Instala un spy por cada fase (registra su nombre en `llamadas` sin hacer nada más),
    incluida `fase_odfs` — el punto central que este task agrega a la orquestación. `__nombre` se
    fija por default-arg (no por closure) para no pisar todas las funciones con el último `nombre`
    de la iteración."""
    for nombre in (
        "fase_cables",
        "fase_botellas",
        "fase_fusiones",
        "fase_odfs",
        "fase_reconciliacion",
        "fase_servicios",
        "fase_splitters",
        "fase_puertos_splitter",
        "fase_cajas_pon",
        "fase_rosetas",
        "fase_cables_bajada",
        "fase_cables_terceros",
    ):

        async def _fn(*args, __nombre=nombre, **kwargs):
            llamadas.append(__nombre)

        monkeypatch.setattr(ingesta, nombre, _fn)
