# Nombre de archivo: 20260929_03_cromo_clases_cables_terceros.py
# Ubicación de archivo: db/alembic/versions/20260929_03_cromo_clases_cables_terceros.py
# Descripción: Da de alta en app.cromo_clases las clases de cable de terceros (52, 59 Telefónica,
# 60 Telecom), requisito de la FK cromo_cables.clase para poder ingerirlas.

"""cromo_clases: cables de terceros 52, 59 y 60

Revision ID: 20260929_03
Revises: 20260929_02
Create Date: 2026-09-29

Cambios:
- ``INSERT`` en ``app.cromo_clases`` de 52 (terceros varios: Arsat, Alterplan, Telmex,
  cooperativas…), 59 (Telefónica) y 60 (Telecom). Clases confirmadas por el usuario; propietarios
  medidos contra Cromo (at.25) el 2026-09-29. ``count_cromo`` es ``stats[].count`` de ese día.
- ``entidad='CABLE'``, igual que la 51: es lo que ya espera el camino óptico (``_CLASES_FALLBACK``
  mapeaba la 52 a "CABLE") y la vinculación local (``cromo_cables`` ↔ "CABLE"). Un cable de tercero
  se distingue por ``clase`` y por ``propietario``, no por entidad.
- Sin estas filas, ``cromo_cables_clase_fkey`` rechaza cada cable de la fase nueva.

Downgrade: borra los cables de esas clases **con sus tubos, pelos y matches de servicio** (sin FK
dura, así que hay que hacerlo explícito) y después las filas del catálogo. Es destructivo por
definición: deshace la ingesta que esta migración habilita.
"""

from __future__ import annotations

from alembic import op

revision = "20260929_03"
down_revision = "20260929_02"
branch_labels = None
depends_on = None

_CLASES = "(52, 59, 60)"


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app.cromo_clases
            (clase, etiqueta, entidad, ingerible, homologada, motivo_exclusion, count_cromo, count_fecha)
        VALUES
            (52, NULL, 'CABLE', true, true, NULL, 695, '2026-09-29'),
            (59, NULL, 'CABLE', true, true, NULL,   7, '2026-09-29'),
            (60, NULL, 'CABLE', true, true, NULL,  31, '2026-09-29')
        ON CONFLICT (clase) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM app.cromo_servicio_match m
         USING app.cromo_pelos p, app.cromo_cables c
         WHERE m.pelo_n_id = p.n_id AND p.cable_n_id = c.n_id AND c.clase IN {_CLASES}
        """
    )
    op.execute(
        f"""
        DELETE FROM app.cromo_pelos p
         USING app.cromo_cables c
         WHERE p.cable_n_id = c.n_id AND c.clase IN {_CLASES}
        """
    )
    op.execute(
        f"""
        DELETE FROM app.cromo_tubos t
         USING app.cromo_cables c
         WHERE t.cable_n_id = c.n_id AND c.clase IN {_CLASES}
        """
    )
    op.execute(f"DELETE FROM app.cromo_cables WHERE clase IN {_CLASES}")
    op.execute(f"DELETE FROM app.cromo_clases WHERE clase IN {_CLASES}")
