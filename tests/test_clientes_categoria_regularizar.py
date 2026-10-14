# Nombre de archivo: test_clientes_categoria_regularizar.py
# Ubicación de archivo: tests/test_clientes_categoria_regularizar.py
# Descripción: Parser del archivo de lista/alias y dry-run real (con rollback) del script de regularización de categorías

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.soporte_postgres_real import requiere_postgres_real

RUTA = Path(__file__).resolve().parents[1] / "scripts" / "clientes_categoria_regularizar.py"
spec = importlib.util.spec_from_file_location("clientes_categoria_regularizar", RUTA)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


def test_parser_ignora_vacias_y_comentarios():
    nombres, alias = script.parsear_archivo("# comentario\n\n  Banco Uno SA  \n   \n# otro\nBanco Dos SA\n")
    assert nombres == ["Banco Uno SA", "Banco Dos SA"]
    assert alias == []


def test_parser_alias_canonico_variante():
    nombres, alias = script.parsear_archivo("BANCO UNO SA\nBANCO UNO SA |  BANCO UNO  \n")
    assert nombres == ["BANCO UNO SA"]
    assert alias == [("BANCO UNO SA", "BANCO UNO")]


def test_parser_deduplica_por_clave_normalizada():
    nombres, alias = script.parsear_archivo(
        "Banco Uno S.A.\nBANCO UNO SA\nA SA | B SA\na sa | b sa\nA SA | \n"
    )
    assert nombres == ["Banco Uno S.A."]
    assert alias == [("A SA", "B SA")]


def test_archivo_inicial_tiene_52_nombres_y_alias_validos():
    nombres, alias = script.parsear_archivo(script.ARCHIVO_POR_DEFECTO.read_text(encoding="utf-8"))
    assert len(nombres) == 52
    assert len(alias) == 6
    assert "MEPADIP S.A." in nombres


@requiere_postgres_real
def test_dry_run_real_no_modifica_la_db():
    from db.session import engine

    consultas = {
        "clientes": "SELECT count(*) FROM app.clientes",
        "alias": "SELECT count(*) FROM app.clientes_alias",
        "cat": "SELECT coalesce(sum(coalesce(categoria, 9)), 0) FROM app.servicios",
    }

    def foto(connection):
        return {k: connection.execute(text(q)).scalar() for k, q in consultas.items()}

    nombres, alias = script.parsear_archivo(script.ARCHIVO_POR_DEFECTO.read_text(encoding="utf-8"))
    with engine.connect() as lectura:
        antes = foto(lectura)
    with engine.connect() as connection:
        resumen = script.ejecutar(connection, nombres, alias, aplicar=False)
    with engine.connect() as lectura:
        despues = foto(lectura)
    assert resumen["modo"] == "dry-run"
    assert resumen["lista_c6"]["nombres_en_archivo"] == 52
    assert antes == despues


@requiere_postgres_real
def test_apply_persiste_dentro_de_la_transaccion_del_llamador():
    """`aplicar=True` debe dejar las escrituras en la conexión (no revertidas con el savepoint de la
    sesión). El test envuelve la corrida en una transacción externa que revierte: nada queda en dev."""
    from db.session import engine

    nombres, alias = script.parsear_archivo(script.ARCHIVO_POR_DEFECTO.read_text(encoding="utf-8"))
    with engine.connect() as lectura:
        antes = lectura.execute(text("SELECT count(*) FROM app.clientes")).scalar()
    with engine.connect() as connection:
        externa = connection.begin()
        resumen = script.ejecutar(connection, nombres, alias, aplicar=True)
        visibles = connection.execute(text("SELECT count(*) FROM app.clientes")).scalar()
        externa.rollback()
    with engine.connect() as lectura:
        despues = lectura.execute(text("SELECT count(*) FROM app.clientes")).scalar()
    assert resumen["modo"] == "apply"
    assert visibles >= antes and visibles == sum(
        sum(v.values()) for v in resumen["clientes_por_categoria_y_origen"]["despues"].values()
    )
    if antes == 0:
        assert visibles > 0
    assert despues == antes
