# Nombre de archivo: 20260919_01_cromo_clases_pon_ingeribles.py
# Ubicación de archivo: db/alembic/versions/20260919_01_cromo_clases_pon_ingeribles.py
# Descripción: Da de alta las 5 clases de caja PON que faltaban en app.cromo_clases y marca
# ingeribles las clases de la red de acceso que el submódulo PON pasa a barrer

"""Clases de la red de acceso PON, ahora ingeribles

Revision ID: 20260919_01
Revises: 20260917_03
Create Date: 2026-09-19

Cambios:

1. **Alta de 126, 127, 138, 139 y 140**, cinco clases de caja PON que no existían en el catálogo.
   Sin esta fila, `camino_optico_service._tipo_de_clase` las dibuja como ``CLASE_139`` y la FK de
   cualquier tabla que las referencie no se puede crear.
2. **``ingerible=true``** para las clases que el submódulo pasa a barrer: 66, 84, 85, 133, 134, 137
   (más las 5 nuevas). Se revierte así, parcialmente, la decisión de `20260917_02`, que las dejó en
   ``false`` porque entonces el objetivo era sólo etiquetar nodos del diagrama. El objetivo ahora es
   inventario, y el argumento de aquella decisión —que ingerirlas no arregla el truncamiento de
   ``/path``— **sigue siendo cierto y sigue fuera de alcance**.
3. **``count_cromo``/``count_fecha``** con los conteos reales. Las dos columnas existen desde
   `20260805_01` y hasta hoy no tenía consumidores: pasan a ser la fuente del fallback de conteo
   de `fase_conteo` para las clases cuyo ``stats[].count`` miente.

`86` (NODO) y `141` (FUSION_ODF) **quedan en ``ingerible=false``**: son nodos de paso del diagrama,
no inventario, y no entran en este submódulo.

Diagnóstico real que sostiene los números (2026-09-19, contra la API de Cromo):

- Los conteos salen de ``get_coleccion(clase, psize=1, show=["BASIC"])`` leyendo ``stats[].count``,
  igual que `fase_conteo`.
- **``stats[].count`` devuelve 0 para las clases 133 y 134** aunque la colección pagina
  perfectamente. Por eso sus conteos se midieron **paginando hasta el final**, no leyendo
  ``stats``, y por eso existe el fallback del punto 3: sin él, ``total_objetivo`` de un modo de
  splitters quedaría en 0. Los totales reales son **20.238 splitters (405 páginas) y 154.284
  puertos (3.086 páginas)** — una medición parcial de 16 páginas daba 800 y habría sido 25 veces
  menor que la realidad, que es exactamente el error que un ``stats`` mentiroso induce.
- Las 7 clases de caja PON (84, 126, 127, 137, 138, 139, 140) comparten esquema exacto: todas raíz
  (``parent=None``), con ``ll``/``pts``/``vmax`` y los mismos ``at`` (16, 20, 34, 35, 40, 41, 45,
  46, 47, 67, 68, 69, 91, 203). La entidad ``CAJA_PON`` para las cinco nuevas se confirmó por
  muestra de nombres reales: "Caja PON Libertador 1650 Vicente Lopez" (126), "PON subsuelo Lima
  1111" (127), "IAAS - PON camacua 105 RED 81005" (138), "IAAS PON DOBLAS 497 RED 90857" (139),
  "IAAS - PON EMILIO MITRE 190" (140).
- La **85 (Roseta) sí existe y tiene 17.348 objetos**, pese a que `20260917_02` la registró como
  "no observada todavia en ningun camino real". Las dos cosas son ciertas: no aparece en los
  recorridos de ``/path``, pero la colección está y es barrible. Se corrige el
  ``motivo_exclusion``, que hoy induce a error.

``ON CONFLICT DO NOTHING`` para que el alta sea reejecutable sin romper si alguna clase ya fue
cargada a mano en algún ambiente.
"""

from __future__ import annotations

from alembic import op

revision = "20260919_01"
down_revision = "20260917_03"
branch_labels = None
depends_on = None

# Clases dadas de alta acá: el `downgrade` las borra.
_CLASES_NUEVAS = (126, 127, 138, 139, 140)

# Clases que ya existían con `ingerible=false` y pasan a `true`: el `downgrade` las devuelve a su
# estado anterior, con el `motivo_exclusion` textual que traían de `20260917_02`.
_MOTIVO_PON = "Red de acceso PON: visible en /path, no se barre en la ingesta"
_MOTIVO_ROSETA = "Red de acceso PON: no observada todavia en ningun camino real"
_CLASES_REACTIVADAS = {
    66: _MOTIVO_PON,
    84: _MOTIVO_PON,
    85: _MOTIVO_ROSETA,
    133: _MOTIVO_PON,
    134: _MOTIVO_PON,
    137: _MOTIVO_PON,
}


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app.cromo_clases
            (clase, etiqueta, entidad, ingerible, homologada, motivo_exclusion, count_cromo, count_fecha)
        VALUES
            (126, NULL, 'CAJA_PON', true, true, NULL,  391, '2026-09-19'),
            (127, NULL, 'CAJA_PON', true, true, NULL,  111, '2026-09-19'),
            (138, NULL, 'CAJA_PON', true, true, NULL, 1394, '2026-09-19'),
            (139, NULL, 'CAJA_PON', true, true, NULL, 1814, '2026-09-19'),
            (140, NULL, 'CAJA_PON', true, true, NULL,  490, '2026-09-19')
        ON CONFLICT (clase) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE app.cromo_clases AS c
           SET ingerible = true,
               motivo_exclusion = NULL,
               count_cromo = v.count_cromo,
               count_fecha = '2026-09-19'
          FROM (VALUES
                    (66,  19030),
                    (84,   3045),
                    (85,  17348),
                    (137,  6237)
               ) AS v(clase, count_cromo)
         WHERE c.clase = v.clase
        """
    )
    # 133 y 134 aparte: su `count_cromo` NO sale de `stats[].count` —que devuelve 0— sino de
    # paginar la colección hasta el final. Es justamente el caso que el fallback de `fase_conteo`
    # viene a cubrir, así que el valor tiene que estar sí o sí para que la barra de progreso de
    # una corrida de splitters signifique algo.
    op.execute(
        """
        UPDATE app.cromo_clases AS c
           SET ingerible = true,
               motivo_exclusion = NULL,
               count_cromo = v.count_cromo,
               count_fecha = '2026-09-19'
          FROM (VALUES
                    (133,  20238),
                    (134, 154284)
               ) AS v(clase, count_cromo)
         WHERE c.clase = v.clase
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE app.cromo_clases
           SET ingerible = false,
               motivo_exclusion = CASE clase
                    WHEN 85 THEN '%(roseta)s'
                    ELSE '%(pon)s'
               END,
               count_cromo = NULL,
               count_fecha = NULL
         WHERE clase IN (%(clases)s)
        """
        % {
            "roseta": _MOTIVO_ROSETA,
            "pon": _MOTIVO_PON,
            "clases": ", ".join(str(c) for c in sorted(_CLASES_REACTIVADAS)),
        }
    )
    # Igual que en `20260917_02`: si alguna fila las referencia, el DELETE falla ruidosamente y eso
    # es lo correcto — borrar el catálogo de una clase en uso dejaría filas sin etiqueta. Bajar
    # esta migración con elementos PON ya ingeridos exige bajar antes la que creó esa tabla.
    op.execute(
        "DELETE FROM app.cromo_clases WHERE clase IN (%s)"
        % ", ".join(str(c) for c in _CLASES_NUEVAS)
    )
