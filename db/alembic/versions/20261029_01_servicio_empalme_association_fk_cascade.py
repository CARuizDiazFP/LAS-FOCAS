# Nombre de archivo: 20261029_01_servicio_empalme_association_fk_cascade.py
# Ubicación de archivo: db/alembic/versions/20261029_01_servicio_empalme_association_fk_cascade.py
# Descripción: Fase A del retiro de app.servicio_empalme_association: sus dos FK pasan a ON DELETE CASCADE

"""Fase A del retiro de ``app.servicio_empalme_association`` (P22)

Desde esta versión ningún código lee ni escribe la tabla legada: las rutas
(``ruta_empalme_association`` vía ``RutaServicio``) son la única fuente, y su verdad es el tracking
desde las ODF de los extremos. La tabla queda congelada, como respaldo, hasta la fase B (``DROP TABLE``
en otro deploy).

Al dejar de escribirla, sus FK sin ``ON DELETE`` romperían los borrados que antes la limpiaban a mano
o por la relación ORM: el ``DELETE FROM app.servicios`` de la fusión PROV y de los placeholders de la
ingesta, y el borrado de empalmes por la cascada ORM de ``Camara.empalmes``. Con ``ON DELETE CASCADE``
la tabla queda pasiva.

Sin migración de datos (decisión del usuario, 2026-10-29): las filas sin equivalente en las rutas
(13 del servicio 93153, igual en dev y prod) son restos de un re-tracking y no se pasan a rutas.
Medido el 2026-10-29: dev 2967 filas de 49 servicios, prod 3204 de 55; en ninguno hay servicios con
filas legadas y sin rutas.

Los nombres de las constraints son los mismos en dev y prod (verificado el 2026-10-29).

Revision ID: 20261029_01
Revises: 20261027_02
Create Date: 2026-10-29
"""

from __future__ import annotations

from alembic import op

revision = "20261029_01"
down_revision = "20261027_02"
branch_labels = None
depends_on = None

_TABLA = "servicio_empalme_association"
_FKS = (
    ("servicio_empalme_association_servicio_id_fkey", "servicios", "servicio_id"),
    ("servicio_empalme_association_empalme_id_fkey", "empalmes", "empalme_id"),
)


def _recrear_fks(ondelete: str | None) -> None:
    for nombre, tabla_ref, columna in _FKS:
        op.drop_constraint(nombre, _TABLA, schema="app", type_="foreignkey")
        op.create_foreign_key(
            nombre,
            _TABLA,
            tabla_ref,
            [columna],
            ["id"],
            source_schema="app",
            referent_schema="app",
            ondelete=ondelete,
        )


def upgrade() -> None:
    _recrear_fks("CASCADE")


def downgrade() -> None:
    _recrear_fks(None)
