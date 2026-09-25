# Nombre de archivo: 20260917_02_cromo_clases_pon.py
# Ubicación de archivo: db/alembic/versions/20260917_02_cromo_clases_pon.py
# Descripción: Registra en app.cromo_clases las clases de la red de acceso PON que el camino
# óptico atraviesa pero la ingesta no barre, para que el diagrama deje de mostrar "CLASE_84"

"""Clases de la red de acceso PON en el catálogo

Revision ID: 20260917_02
Revises: 20260917_01
Create Date: 2026-09-17

Cambios:
- `INSERT` en ``app.cromo_clases`` de las clases de la red PON. El docstring de ``CromoClase``
  ya lo anticipa: incorporar una clase es un ``INSERT``, no un cambio de esquema. Se hace como
  migración —y no a mano— para que dev, prod y cualquier base nueva queden iguales.
- Todas van con ``ingerible=false``: **no** se barren en una corrida. Sólo se catalogan para que
  ``camino_optico_service._catalogo_clases`` les dé nombre y el diagrama de camino muestre qué es
  cada nodo en vez del genérico ``CLASE_<n>``.

Diagnóstico real que las identificó (2026-09-17, contra Cromo; ver `docs/decisiones.md`):

- Sembrando el camino desde un pelo del **lado de red**, el recorrido **se corta en el splitter**:
  sobre 6 servicios OLT reales aparecieron 133/134/86/141 y **nunca** 84/66/85.
- Sembrando desde una **salida** del splitter (`splitter_a.c_out`), aparecen 84 (Caja PON, ×1) y
  66 (Cable de bajada, ×19), más la 137. Es exactamente la regla operativa que aportó el usuario:
  "un splitter muestra camino óptico ok siempre y cuando se use la posición de la Roseta o puerto
  PON asociado al servicio en el extremo cliente; si se releva un splitter de mayor nivel el
  camino quedará cortado".
- Evidencia por clase: 84 → ``at.34`` "Caja PON Subs Libertador 602" (y ``at.35`` con potencias
  ópticas por salida); 66 → ``at.27`` = "Bajada", ``at.26`` = "FBJ-31363"; 137 → ``at.34`` =
  "PON 2 Sub Libertador 602 RED 91574", contiene un splitter; 133 → ``at.83`` = "1x8"/"1x4", el
  ratio **publicado** por Cromo; 134 → ``at.80``/``at.82`` = "S6"/"SALIDA"; 86 → ``at.34`` =
  "Nodo Paraguay 2302 P3 D5 Rack 1 de FO C.F."; 141 → fusión dentro de una ODF (la 132 es la de
  Botella).
- La 85 (Roseta, id confirmado por el usuario) se cataloga igual, pero **no se observó en ningún
  camino real**: el recorrido termina en la caja PON. Queda registrada para que el día que
  aparezca se muestre con nombre en vez de como "CLASE_85".

``ON CONFLICT DO NOTHING`` para que sea reejecutable sin romper si alguna clase ya fue cargada a
mano en algún ambiente.
"""

from __future__ import annotations

from alembic import op

revision = "20260917_02"
down_revision = "20260917_01"
branch_labels = None
depends_on = None

_CLASES_PON = (66, 84, 85, 86, 133, 134, 137, 141)


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app.cromo_clases
            (clase, etiqueta, entidad, ingerible, homologada, motivo_exclusion, count_cromo, count_fecha)
        VALUES
            (66,  NULL, 'CABLE_BAJADA',    false, true, 'Red de acceso PON: visible en /path, no se barre en la ingesta', NULL, NULL),
            (84,  NULL, 'CAJA_PON',        false, true, 'Red de acceso PON: visible en /path, no se barre en la ingesta', NULL, NULL),
            (85,  NULL, 'ROSETA',          false, true, 'Red de acceso PON: no observada todavia en ningun camino real', NULL, NULL),
            (86,  NULL, 'NODO',            false, true, 'Nodo/sala: visible en /path, no se barre en la ingesta', NULL, NULL),
            (133, NULL, 'SPLITTER',        false, true, 'Red de acceso PON: visible en /path, no se barre en la ingesta', NULL, NULL),
            (134, NULL, 'PUERTO_SPLITTER', false, true, 'Red de acceso PON: visible en /path, no se barre en la ingesta', NULL, NULL),
            (137, NULL, 'CAJA_PON',        false, true, 'Red de acceso PON: visible en /path, no se barre en la ingesta', NULL, NULL),
            (141, NULL, 'FUSION_ODF',      false, true, 'Fusion dentro de una ODF: visible en /path, no se barre en la ingesta', NULL, NULL)
        ON CONFLICT (clase) DO NOTHING
        """
    )


def downgrade() -> None:
    # Sólo se borran si nadie las referencia: `cromo_botellas.clase` y `cromo_odfs.clase` tienen FK
    # contra este catálogo. Ninguna de estas clases se ingiere, así que en condiciones normales no
    # hay filas apuntando a ellas; el DELETE fallaría ruidosamente si las hubiera, que es lo
    # correcto — perder el catálogo de una clase en uso dejaría filas huérfanas de etiqueta.
    op.execute(
        "DELETE FROM app.cromo_clases WHERE clase IN (%s)"
        % ", ".join(str(c) for c in _CLASES_PON)
    )
