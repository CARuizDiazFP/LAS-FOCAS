# Nombre de archivo: 20261016_01_cromo_odf_nodo.py
# Ubicación de archivo: db/alembic/versions/20261016_01_cromo_odf_nodo.py
# Descripción: Habilita la ingesta de la clase 86 de Cromo (ODF Nodo) en app.cromo_odfs, agrega
# cromo_odf_conectores.patch_conector_n_id y corrige los pelo_n_id que no eran pelos.

"""cromo_odf_nodo: clase 86 ingerible, tipo_elemento ODF_NODO y patch_conector_n_id

Revision ID: 20261016_01
Revises: 20261014_02
Create Date: 2026-10-16

Cambios:
- ``cromo_clases``: la 86 pasa a ``entidad='ODF_NODO'``, ``ingerible=true``, sin motivo de
  exclusión y ``count_cromo=154`` (``stats[].count`` medido 2026-10-16). Va a la misma tabla que
  la 69 (``cromo_odfs``) y se distingue por ``tipo_elemento``.
- CHECK de ``cromo_odfs.tipo_elemento``: suma ``ODF_NODO``.
- Columna nueva ``cromo_odf_conectores.patch_conector_n_id`` (BIGINT NULL): ``tp[]`` de clase 136,
  patch de un conector a otro.
- Backfill: el parser guardaba ``tp[0]`` como ``pelo_n_id`` aunque fuera un conector (136), una
  fusión de ODF (141) u otra clase. Se anulan los ``pelo_n_id`` cuyo ``tp`` coincidente no es de
  clase 130 y que no existen en ``cromo_pelos``; si era un 136, el id pasa a
  ``patch_conector_n_id``. Los de clase 130 que no están en ``cromo_pelos`` (pelos de cables de
  terceros no ingeridos) no se tocan.

Downgrade: restituye el CHECK y el catálogo y elimina la columna. El backfill de datos no se
revierte (los ``pelo_n_id`` anulados eran ids que no son pelos; el re-barrido de ODFs los recompone
con la lógica vigente). Se borran las ODF Nodo ingeridas y sus conectores, porque el CHECK anterior las rechaza.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261016_01"
down_revision = "20261014_02"
branch_labels = None
depends_on = None

_CHECK = "ck_cromo_odfs_tipo_elemento_valido"


def upgrade() -> None:
    op.drop_constraint(_CHECK, "cromo_odfs", schema="app", type_="check")
    op.create_check_constraint(
        _CHECK,
        "cromo_odfs",
        "tipo_elemento IN ('ODF', 'EMPALME', 'SIN_CLASIFICAR', 'ODF_NODO')",
        schema="app",
    )
    op.add_column(
        "cromo_odf_conectores",
        sa.Column("patch_conector_n_id", sa.BigInteger(), nullable=True),
        schema="app",
    )
    op.execute(
        """
        UPDATE app.cromo_clases
           SET entidad = 'ODF_NODO', ingerible = true, motivo_exclusion = NULL,
               count_cromo = 154, count_fecha = '2026-10-16'
         WHERE clase = 86
        """
    )
    # Backfill: sólo filas donde el `tp` que coincide con pelo_n_id NO es de clase 130.
    op.execute(
        """
        UPDATE app.cromo_odf_conectores c
           SET patch_conector_n_id = CASE
                   WHEN t.clase_tp = '136' THEN c.pelo_n_id ELSE c.patch_conector_n_id END,
               pelo_n_id = NULL
          FROM (
              SELECT c2.n_id,
                     (SELECT e->>'class'
                        FROM jsonb_array_elements(c2.payload_raw->'tp') e
                       WHERE (e->>'id_to') = c2.pelo_n_id::text
                       LIMIT 1) AS clase_tp
                FROM app.cromo_odf_conectores c2
               WHERE c2.pelo_n_id IS NOT NULL
                 AND jsonb_typeof(c2.payload_raw->'tp') = 'array'
                 AND NOT EXISTS (SELECT 1 FROM app.cromo_pelos p WHERE p.n_id = c2.pelo_n_id)
          ) t
         WHERE t.n_id = c.n_id
           AND t.clase_tp IS NOT NULL
           AND t.clase_tp <> '130'
        """
    )


def downgrade() -> None:
    # Sin backfill inverso: ver docstring del módulo.
    # Primero los conectores de las ODF Nodo (sin FK dura: si no, quedarían huérfanos), después
    # las ODF Nodo, y recién entonces se restaura el CHECK.
    op.execute(
        """
        DELETE FROM app.cromo_odf_conectores
         WHERE odf_n_id IN (SELECT n_id FROM app.cromo_odfs WHERE tipo_elemento = 'ODF_NODO')
        """
    )
    op.execute("DELETE FROM app.cromo_odfs WHERE tipo_elemento = 'ODF_NODO'")
    op.drop_column("cromo_odf_conectores", "patch_conector_n_id", schema="app")
    op.drop_constraint(_CHECK, "cromo_odfs", schema="app", type_="check")
    op.create_check_constraint(
        _CHECK,
        "cromo_odfs",
        "tipo_elemento IN ('ODF', 'EMPALME', 'SIN_CLASIFICAR')",
        schema="app",
    )
    op.execute(
        """
        UPDATE app.cromo_clases
           SET entidad = 'NODO', ingerible = false,
               motivo_exclusion = 'Nodo/sala: visible en /path, no se barre en la ingesta',
               count_cromo = NULL, count_fecha = NULL
         WHERE clase = 86
        """
    )
