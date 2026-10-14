# Nombre de archivo: test_clientes_categoria_migracion_real_db.py
# Ubicación de archivo: tests/test_clientes_categoria_migracion_real_db.py
# Descripción: Esquema de la migración 20261014_01 (clientes, alias y categoría SLA de servicios) contra Postgres real

"""Verifica contra el Postgres de dev el esquema que deja `20261014_01_clientes_categoria`:

- `app.clientes` y `app.clientes_alias` con sus columnas, nulabilidad y FK en cascada.
- `app.servicios.categoria` nullable y sin default; `categoria_sla` nullable; `categoria_excepcion`
  NOT NULL DEFAULT false.
- Los CHECK aceptan `NULL` y rechazan `7`.

Todo corre en una transacción que se revierte: no deja datos sintéticos.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from db.session import SessionLocal
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

SERVICIO_ID = "TEST-CLI-CAT-990001"


def _columnas(sesion, tabla: str) -> dict[str, tuple[str, str, str | None]]:
    filas = sesion.execute(
        text(
            "SELECT column_name, is_nullable, udt_name, column_default "
            "FROM information_schema.columns WHERE table_schema = 'app' AND table_name = :t"
        ),
        {"t": tabla},
    ).all()
    return {f.column_name: (f.is_nullable, f.udt_name, f.column_default) for f in filas}


@pytest.fixture
def sesion():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_tabla_clientes_columnas(sesion) -> None:
    cols = _columnas(sesion, "clientes")
    assert set(cols) == {
        "id",
        "nombre",
        "clave",
        "categoria",
        "origen_categoria",
        "a_revisar",
        "creado_en",
        "actualizado_en",
        "actualizado_por",
    }
    assert cols["categoria"][0] == "YES"
    assert cols["origen_categoria"][0] == "NO"
    assert cols["origen_categoria"][1] == "cliente_origen_categoria"
    assert "AUTO" in (cols["origen_categoria"][2] or "")
    assert cols["a_revisar"][0] == "NO"
    assert cols["actualizado_por"][0] == "YES"


def test_tabla_clientes_alias_columnas_y_fk_cascade(sesion) -> None:
    cols = _columnas(sesion, "clientes_alias")
    assert set(cols) == {"id", "clave", "nombre_original", "cliente_id", "origen"}
    assert cols["cliente_id"][0] == "NO"
    regla = sesion.execute(
        text(
            "SELECT rc.delete_rule FROM information_schema.referential_constraints rc "
            "JOIN information_schema.table_constraints tc ON tc.constraint_name = rc.constraint_name "
            "AND tc.constraint_schema = rc.constraint_schema "
            "WHERE tc.table_schema = 'app' AND tc.table_name = 'clientes_alias' AND tc.constraint_type = 'FOREIGN KEY'"
        )
    ).scalar_one()
    assert regla == "CASCADE"
    indice = sesion.execute(
        text(
            "SELECT 1 FROM pg_indexes WHERE schemaname = 'app' AND tablename = 'clientes_alias' "
            "AND indexdef LIKE '%(cliente_id)%'"
        )
    ).scalar()
    assert indice == 1


def test_servicios_columnas_de_categoria(sesion) -> None:
    cols = _columnas(sesion, "servicios")
    assert cols["categoria"][0] == "YES"
    assert cols["categoria"][2] is None
    assert cols["categoria_sla"][0] == "YES"
    assert cols["categoria_excepcion"][0] == "NO"
    assert cols["categoria_excepcion"][2] == "false"


def test_servicios_check_categoria_acepta_null_y_rechaza_7(sesion) -> None:
    sesion.execute(
        text("INSERT INTO app.servicios (servicio_id, estado_servicio) VALUES (:s, 'TEST')"),
        {"s": SERVICIO_ID},
    )
    fila = sesion.execute(
        text("SELECT categoria, categoria_sla, categoria_excepcion FROM app.servicios WHERE servicio_id = :s"),
        {"s": SERVICIO_ID},
    ).one()
    assert fila.categoria is None
    assert fila.categoria_sla is None
    assert fila.categoria_excepcion is False

    for columna in ("categoria", "categoria_sla"):
        punto = sesion.begin_nested()
        with pytest.raises(IntegrityError):
            sesion.execute(
                text(f"UPDATE app.servicios SET {columna} = 7 WHERE servicio_id = :s"),
                {"s": SERVICIO_ID},
            )
        punto.rollback()


def test_clientes_check_categoria_acepta_null_y_rechaza_7(sesion) -> None:
    cliente_id = sesion.execute(
        text("INSERT INTO app.clientes (nombre, clave) VALUES ('Test Cliente', 'test cliente 990001') RETURNING id")
    ).scalar_one()
    fila = sesion.execute(
        text("SELECT categoria, origen_categoria::text AS origen, a_revisar FROM app.clientes WHERE id = :i"),
        {"i": cliente_id},
    ).one()
    assert fila.categoria is None
    assert fila.origen == "AUTO"
    assert fila.a_revisar is False

    punto = sesion.begin_nested()
    with pytest.raises(IntegrityError):
        sesion.execute(text("UPDATE app.clientes SET categoria = 7 WHERE id = :i"), {"i": cliente_id})
    punto.rollback()

    punto = sesion.begin_nested()
    with pytest.raises(IntegrityError):
        sesion.execute(
            text("INSERT INTO app.clientes (nombre, clave) VALUES ('Duplicado', 'test cliente 990001')")
        )
    punto.rollback()


def test_alias_rechaza_origen_invalido_y_se_borra_en_cascada_con_su_cliente(sesion) -> None:
    cliente_id = sesion.execute(
        text("INSERT INTO app.clientes (nombre, clave) VALUES ('Test Alias', 'test alias 990002') RETURNING id")
    ).scalar_one()
    sesion.execute(
        text(
            "INSERT INTO app.clientes_alias (clave, nombre_original, cliente_id, origen) "
            "VALUES ('test alias 990002 sa', 'Test Alias S.A.', :c, 'AUTO')"
        ),
        {"c": cliente_id},
    )
    punto = sesion.begin_nested()
    with pytest.raises(IntegrityError):
        sesion.execute(
            text(
                "INSERT INTO app.clientes_alias (clave, nombre_original, cliente_id, origen) "
                "VALUES ('test alias 990002 otro', 'Otro', :c, 'LISTA')"
            ),
            {"c": cliente_id},
        )
    punto.rollback()

    sesion.execute(text("DELETE FROM app.clientes WHERE id = :c"), {"c": cliente_id})
    restantes = sesion.execute(
        text("SELECT count(*) FROM app.clientes_alias WHERE cliente_id = :c"), {"c": cliente_id}
    ).scalar_one()
    assert restantes == 0
