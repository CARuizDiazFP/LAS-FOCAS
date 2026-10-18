# Nombre de archivo: 20261017_03_cromo_servicio_match_vigente.py
# Ubicación de archivo: db/alembic/versions/20261017_03_cromo_servicio_match_vigente.py
# Descripción: Vista app.v_cromo_servicio_match_vigente — cromo_servicio_match sin los pelos de casos
# de inconsistencia de Cromo en CUARENTENA

"""v_cromo_servicio_match_vigente

Revision ID: 20261017_03
Revises: 20261017_02
Create Date: 2026-10-17

Cambios:
- Nueva vista ``app.v_cromo_servicio_match_vigente``: las mismas columnas que
  ``app.cromo_servicio_match``, sin las filas cuyo pelo pertenece a un caso de
  ``app.cromo_inconsistencia`` en estado ``CUARENTENA``.

Por qué una vista y no un borrado: la cuarentena no toca los datos de Cromo. Los escritores
(ingesta, bajas, fusión de servicios) siguen sobre la tabla; todo lo que consume "qué servicio
ocupa este pelo" lee la vista, y cuando el caso sale de cuarentena el uso vuelve solo. El
``NOT EXISTS`` se resuelve con el índice por pelo de ``cromo_inconsistencia_pelo`` (anti-join);
ver los tiempos medidos en el informe de la Tarea 3.
"""

from __future__ import annotations

from alembic import op

revision = "20261017_03"
down_revision = "20261017_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW app.v_cromo_servicio_match_vigente AS
        SELECT m.*
        FROM app.cromo_servicio_match m
        WHERE NOT EXISTS (
            SELECT 1
            FROM app.cromo_inconsistencia_pelo ip
            JOIN app.cromo_inconsistencia i ON i.id = ip.inconsistencia_id
            WHERE ip.pelo_n_id = m.pelo_n_id AND i.estado = 'CUARENTENA'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW app.v_cromo_servicio_match_vigente")
