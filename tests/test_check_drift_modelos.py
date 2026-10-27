# Nombre de archivo: test_check_drift_modelos.py
# Ubicación de archivo: tests/test_check_drift_modelos.py
# Descripción: Tests sin base de la clasificación de drift, la convención de nombres de índice y el alcance del autogenerate

from __future__ import annotations

from sqlalchemy import Column, Index, Integer, MetaData, Table, Text

from db.base import Base
from db.models.autogenerate import OPCIONES_COMPARACION, TABLAS_SIN_MODELO, include_name, include_object
from scripts.check_drift_modelos import clasificar


def _tabla(nombre: str = "t") -> Table:
    return Table(nombre, MetaData(), Column("id", Integer, primary_key=True), Column("a", Text), Column("b", Text), schema="app")


def test_clasificar_empareja_indices_por_columnas_y_por_nombre():
    t = _tabla()
    diffs = [
        ("remove_index", Index("ix_corto", t.c.a)),
        ("add_index", Index("ix_t_a", t.c.a)),  # mismas columnas, otro nombre
        ("remove_index", Index("ix_t_b", t.c.b)),
        ("add_index", Index("ix_t_b", t.c.a, t.c.b)),  # mismo nombre, otra definición
        ("remove_index", Index("ix_solo_base", t.c.id)),
        ("add_index", Index("ix_solo_modelo", t.c.b, unique=True)),
    ]
    grupos = clasificar(diffs)
    assert grupos["indice_nombre_distinto"] == ["t: base ix_corto ↔ modelo ix_t_a"]
    assert len(grupos["indice_definicion_distinta"]) == 1
    assert grupos["indice_solo_base"] == ["t.ix_solo_base (id)"]
    assert grupos["indice_solo_modelo"] == ["t.ix_solo_modelo UNIQUE (b)"]


def test_clasificar_columnas_y_tablas():
    t = _tabla("x")
    diffs = [
        ("remove_table", t),
        [("modify_nullable", "app", "x", "a", {}, True, False)],
        [("modify_comment", "app", "x", "b", {}, "en base", None)],
    ]
    grupos = clasificar(diffs)
    assert grupos["tabla_solo_base"] == ["x"]
    assert grupos["nulabilidad"] == ["x.a: base=True modelo=False"]
    assert grupos["comentario"] == ["x.b: base='en base' modelo=None"]
    assert clasificar([]) == {}


def test_index_true_usa_el_nombre_de_las_migraciones():
    # Sin la convención de db/base.py el nombre sería ix_app_cromo_cables_nombre.
    tabla = Base.metadata.tables["app.cromo_cables"]
    nombres = {i.name for i in tabla.indexes}
    assert "ix_cromo_cables_nombre" in nombres
    assert not any(n.startswith("ix_app_cromo_") for n in nombres)


def test_alcance_sólo_esquema_app_y_tablas_sin_modelo_explícitas():
    assert include_name("app", "schema", {}) is True
    assert include_name(None, "schema", {}) is False  # public
    tablas_modeladas = {t.name for t in Base.metadata.tables.values()}
    assert not (TABLAS_SIN_MODELO & tablas_modeladas)
    # Una tabla reflejada sin modelo y fuera de la lista sigue apareciendo como drift.
    assert include_object(None, "report_history", "table", True, None) is False
    assert include_object(None, "tabla_nueva_sin_modelo", "table", True, None) is True
    assert OPCIONES_COMPARACION["compare_server_default"] is True
