# Nombre de archivo: test_cromo_camara_botella_busqueda.py
# Ubicación de archivo: tests/test_cromo_camara_botella_busqueda.py
# Descripción: Tests unitarios para la búsqueda extendida Camara + CromoBotella

"""
Tests para:
 - core.services.cromo.camara_botella_busqueda.buscar_camara_o_botella_cromo()
 - core.services.cromo.camara_botella_busqueda._buscar_botella_ilike_lista() /
   _buscar_botella_tokens_lista() (armado de la query ORM contra CromoBotella)
 - core.services.cromo.camara_botella_busqueda._cascada_botella() con el algoritmo real (Intento
   1→2, filtro de bots secundarios, guardia de input degenerado) — sólo se mockean las queries hoja.
 - Cap de AmbiguousSearchError a 3 candidatos, incluido el camino directo de
   modules.slack_baneo_notifier.camara_search.buscar_camara() (no pasa por esta función nueva).
 - cantidad de AmbiguousSearchError tras la fusión Camara+CromoBotella nunca reporta menos de lo
   que Camara sola ya había encontrado (aunque exc.candidatos venga recortado a 3).
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "true")

from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError, buscar_camara
from core.services.cromo.camara_botella_busqueda import (
    ResultadoBusquedaExtendida,
    _buscar_botella_ilike_lista,
    _buscar_botella_tokens_lista,
    _cascada_botella,
    buscar_camara_o_botella_cromo,
)

MODULE = "core.services.cromo.camara_botella_busqueda"


def _make_camara(id_: int, nombre: str) -> MagicMock:
    cam = MagicMock()
    cam.id = id_
    cam.nombre = nombre
    return cam


def _make_botella(n_id: int, nombre: str, camara_id: "int | None", camara: "MagicMock | None" = None) -> MagicMock:
    bot = MagicMock()
    bot.n_id = n_id
    bot.nombre = nombre
    bot.camara_id = camara_id
    bot.camara = camara
    return bot


class TestBuscarCamaraOBotellaCromo(unittest.TestCase):
    """Prueba la orquestación de buscar_camara_o_botella_cromo() con buscar_camara() y
    _cascada_botella() mockeados: el foco acá es la lógica de fusión/branching, no el armado de
    queries SQL (eso lo cubre TestCascadaBotellaQueryBuilding)."""

    def test_match_unico_en_camara_no_consulta_cromo_botella(self) -> None:
        camara = _make_camara(1, "Cra Mitre 440")
        with (
            patch(f"{MODULE}.buscar_camara", return_value=(camara, "cra mitre 440")) as mock_bc,
            patch(f"{MODULE}._cascada_botella") as mock_cascada,
        ):
            resultado = buscar_camara_o_botella_cromo("Cra Mitre 440", MagicMock())

        mock_bc.assert_called_once()
        mock_cascada.assert_not_called()
        self.assertEqual(
            resultado,
            ResultadoBusquedaExtendida(
                camara=camara, nombre_norm="cra mitre 440", fuente="camara", botella=None
            ),
        )

    def test_sin_match_camara_match_unico_cromo_botella_con_camara_id(self) -> None:
        camara_raiz = _make_camara(9, "Cra Mitre 440")
        botella = _make_botella(100, "Bot 2 Cra Mitre 440", camara_id=9, camara=camara_raiz)
        with (
            patch(f"{MODULE}.buscar_camara", return_value=(None, "bot 2 cra mitre 440")),
            patch(f"{MODULE}._cascada_botella", return_value=[botella]),
        ):
            resultado = buscar_camara_o_botella_cromo("Bot 2 Cra Mitre 440", MagicMock())

        self.assertEqual(resultado.fuente, "cromo_botella")
        self.assertIs(resultado.camara, camara_raiz)
        self.assertIs(resultado.botella, botella)
        self.assertEqual(resultado.nombre_norm, "bot 2 cra mitre 440")

    def test_match_cromo_botella_sin_camara_id_es_no_match_completo(self) -> None:
        botella = _make_botella(101, "Bot 2 Cra Mitre 440", camara_id=None, camara=None)
        with (
            patch(f"{MODULE}.buscar_camara", return_value=(None, "bot 2 cra mitre 440")),
            patch(f"{MODULE}._cascada_botella", return_value=[botella]),
        ):
            resultado = buscar_camara_o_botella_cromo("Bot 2 Cra Mitre 440", MagicMock())

        self.assertIsNone(resultado.camara)
        self.assertIsNone(resultado.fuente)
        self.assertIsNone(resultado.botella)

    def test_sin_match_en_ninguna_fuente(self) -> None:
        with (
            patch(f"{MODULE}.buscar_camara", return_value=(None, "inexistente 9999")),
            patch(f"{MODULE}._cascada_botella", return_value=[]),
        ):
            resultado = buscar_camara_o_botella_cromo("Inexistente 9999", MagicMock())

        self.assertIsNone(resultado.camara)
        self.assertIsNone(resultado.fuente)
        self.assertIsNone(resultado.botella)

    def test_ambiguo_solo_cromo_botella_cuando_camara_no_matcheo_limpio(self) -> None:
        """buscar_camara() retorna (None, norm) sin lanzar (no ambiguo del lado Camara), pero la
        cascada CromoBotella encuentra 2+ candidatos sin reducirse a 1 -> también debe tratarse
        como ambiguo (comportamiento simétrico al de Camara, ver docstring del módulo)."""
        b1 = _make_botella(1, "Bot 2 Cra Mitre 440", camara_id=9)
        b2 = _make_botella(2, "Bot 2 Cra Mitre 441", camara_id=10)
        with (
            patch(f"{MODULE}.buscar_camara", return_value=(None, "bot 2 cra mitre 44")),
            patch(f"{MODULE}._cascada_botella", return_value=[b1, b2]),
            self.assertRaises(AmbiguousSearchError) as ctx,
        ):
            buscar_camara_o_botella_cromo("Bot 2 Cra Mitre 44", MagicMock())

        self.assertEqual(ctx.exception.cantidad, 2)
        self.assertCountEqual(
            ctx.exception.candidatos, ["Bot 2 Cra Mitre 440", "Bot 2 Cra Mitre 441"]
        )

    def test_ambiguo_fusiona_camara_y_cromo_botella_camara_primero(self) -> None:
        """buscar_camara() lanza AmbiguousSearchError -> se fusiona con candidatos de
        CromoBotella; los de Camara (fuente canónica) van primero en la lista fusionada."""
        exc_original = AmbiguousSearchError(
            "Vicente Lopez", 2, ["Cra Vicente Lopez Norte", "Cra Vicente Lopez Sur"]
        )
        botella = _make_botella(5, "Bot 2 Vicente Lopez Este", camara_id=3)
        with (
            patch(f"{MODULE}.buscar_camara", side_effect=exc_original),
            patch(f"{MODULE}._cascada_botella", return_value=[botella]),
            self.assertRaises(AmbiguousSearchError) as ctx,
        ):
            buscar_camara_o_botella_cromo("Vicente Lopez", MagicMock())

        self.assertEqual(
            ctx.exception.candidatos,
            ["Cra Vicente Lopez Norte", "Cra Vicente Lopez Sur", "Bot 2 Vicente Lopez Este"],
        )
        self.assertEqual(ctx.exception.cantidad, 3)

    def test_dedup_por_nombre_normalizado_entre_camara_y_cromo_botella(self) -> None:
        """Camara y CromoBotella matchean nombres que son equivalentes tras normalizar
        (mayúsculas/espaciado distintos) -> se deduplica, no aparece duplicado en la lista final."""
        exc_original = AmbiguousSearchError(
            "Bot 2 Cra Mitre", 2, ["Bot 2 Cra Mitre 440", "Bot 3 Cra Mitre 440"]
        )
        # "Bot 2 CRA Mitre 440" normaliza igual que "Bot 2 Cra Mitre 440" (case-insensitive) -> dup
        botella_dup = _make_botella(7, "Bot 2 CRA Mitre 440", camara_id=1)
        botella_nueva = _make_botella(8, "Bot 4 Cra Mitre 440", camara_id=2)
        with (
            patch(f"{MODULE}.buscar_camara", side_effect=exc_original),
            patch(f"{MODULE}._cascada_botella", return_value=[botella_dup, botella_nueva]),
            self.assertRaises(AmbiguousSearchError) as ctx,
        ):
            buscar_camara_o_botella_cromo("Bot 2 Cra Mitre", MagicMock())

        self.assertEqual(
            ctx.exception.candidatos,
            ["Bot 2 Cra Mitre 440", "Bot 3 Cra Mitre 440", "Bot 4 Cra Mitre 440"],
        )

    def test_ambiguous_search_error_respeta_cap_de_3_tras_fusion(self) -> None:
        """3 candidatos Camara + 3 CromoBotella (6 únicos tras dedup) -> el mensaje final expone
        sólo 3 (Camara primero), pero `cantidad` refleja el total real fusionado (6)."""
        exc_original = AmbiguousSearchError(
            "Test Zona", 3, ["Cra Test Zona 1", "Cra Test Zona 2", "Cra Test Zona 3"]
        )
        botellas = [_make_botella(i, f"Bot 2 Test Zona {i}", camara_id=i) for i in range(1, 4)]
        with (
            patch(f"{MODULE}.buscar_camara", side_effect=exc_original),
            patch(f"{MODULE}._cascada_botella", return_value=botellas),
            self.assertRaises(AmbiguousSearchError) as ctx,
        ):
            buscar_camara_o_botella_cromo("Test Zona", MagicMock())

        self.assertEqual(len(ctx.exception.candidatos), 3)
        self.assertEqual(
            ctx.exception.candidatos,
            ["Cra Test Zona 1", "Cra Test Zona 2", "Cra Test Zona 3"],
        )
        self.assertEqual(ctx.exception.cantidad, 6)

    def test_ambiguo_cantidad_no_bajo_reporta_cuando_camara_ya_superaba_3(self) -> None:
        """Important #2 (revisión 2026-08-23): exc.candidatos ya viene recortado a 3 por
        AmbiguousSearchError.__init__, pero exc.cantidad conserva el conteo real de Camara (7 en
        este caso). La cantidad fusionada nunca debe reportar menos de ese real, aunque la fusión
        con CromoBotella (sólo 1 candidata nueva) dé un total fusionado más chico (4)."""
        exc_original = AmbiguousSearchError(
            "Vicente Lopez", 7,
            ["Cra Vicente Lopez Norte", "Cra Vicente Lopez Sur", "Cra Vicente Lopez Este"],
        )
        botella = _make_botella(5, "Bot 2 Vicente Lopez Oeste", camara_id=3)
        with (
            patch(f"{MODULE}.buscar_camara", side_effect=exc_original),
            patch(f"{MODULE}._cascada_botella", return_value=[botella]),
            self.assertRaises(AmbiguousSearchError) as ctx,
        ):
            buscar_camara_o_botella_cromo("Vicente Lopez", MagicMock())

        # fusionados = 3 (Camara, ya recortados) + 1 (CromoBotella) = 4 únicos -> sin el fix,
        # cantidad hubiera sido 4, silenciosamente por debajo de los 7 reales de Camara.
        self.assertEqual(len(ctx.exception.candidatos), 3)
        self.assertEqual(ctx.exception.cantidad, 7)
        self.assertGreaterEqual(ctx.exception.cantidad, exc_original.cantidad)


class TestAmbiguousSearchErrorCapDirecto(unittest.TestCase):
    """El cap a 3 aplica también al camino que NO pasa por esta función nueva: directamente desde
    modules.slack_baneo_notifier.camara_search.buscar_camara()."""

    def test_buscar_camara_directo_nunca_excede_3_candidatos(self) -> None:
        cams = [MagicMock(id=i, nombre=f"Cra Test Zona {i}") for i in range(1, 8)]
        with (
            patch(
                "modules.slack_baneo_notifier.camara_search._buscar_ilike_lista",
                return_value=cams,
            ),
            patch(
                "modules.slack_baneo_notifier.camara_search._buscar_tokens_lista",
                return_value=cams,
            ),
            self.assertRaises(AmbiguousSearchError) as ctx,
        ):
            buscar_camara("Test Zona", session=MagicMock())

        self.assertEqual(len(ctx.exception.candidatos), 3)


class TestCascadaBotellaQueryBuilding(unittest.TestCase):
    """Verifica que _buscar_botella_ilike_lista / _buscar_botella_tokens_lista arman la query ORM
    esperada contra session.query(CromoBotella)... (mismo patrón de sesión simulada que
    TestBuscarCamara en tests/test_slack_ingreso_listener.py)."""

    def test_buscar_botella_ilike_lista_usa_session_query_filter_all(self) -> None:
        session = MagicMock()
        botella = _make_botella(1, "Bot 2 Cra Mitre 440", camara_id=1)
        query_mock = MagicMock()
        query_mock.filter.return_value.all.return_value = [botella]
        session.query.return_value = query_mock

        resultado = _buscar_botella_ilike_lista("bot 2 cra mitre 440", session)

        self.assertEqual(resultado, [botella])
        session.query.assert_called_once()
        query_mock.filter.assert_called_once()

    def test_buscar_botella_tokens_lista_usa_session_query_filter_all(self) -> None:
        session = MagicMock()
        botella = _make_botella(1, "Bot 2 Cra Mitre 440", camara_id=1)
        query_mock = MagicMock()
        query_mock.filter.return_value.all.return_value = [botella]
        session.query.return_value = query_mock

        resultado = _buscar_botella_tokens_lista(["bot", "cra", "mitre"], session)

        self.assertEqual(resultado, [botella])
        session.query.assert_called_once()
        query_mock.filter.assert_called_once()


class TestCascadaBotellaReal(unittest.TestCase):
    """Ejercita el algoritmo REAL de _cascada_botella() (Intento 1→2, filtro de bots secundarios,
    guardia de input degenerado) — sólo se mockean las dos queries hoja
    (_buscar_botella_ilike_lista / _buscar_botella_tokens_lista), nunca _cascada_botella en sí.
    Agregado en la revisión del 2026-08-23 (Important #4): antes, los 8 tests de orquestación
    mockeaban _cascada_botella por completo, dejando su lógica interna (justo donde vivían los
    Important #1 y #3) sin cobertura directa."""

    def test_excluye_bot_secundario_sin_mencion_bot_en_input(self) -> None:
        """Important #1: 'Cra Mitre 440' (sin mencionar 'bot'/'botella') no debe emparejar
        'Bot 2 Cra Mitre 440', igual que ya hace _filtrar_bots_secundarios() para Camara."""
        botella_bot2 = _make_botella(1, "Bot 2 Cra Mitre 440", camara_id=1)
        with (
            patch(f"{MODULE}._buscar_botella_ilike_lista", return_value=[botella_bot2]),
            patch(f"{MODULE}._buscar_botella_tokens_lista", return_value=[]),
        ):
            resultado = _cascada_botella("Cra Mitre 440", MagicMock())

        self.assertEqual(resultado, [])

    def test_incluye_bot_secundario_con_mencion_bot_en_input(self) -> None:
        """Contraste del test anterior: si el input SÍ menciona 'bot' explícitamente, la candidata
        'Bot 2 ...' no se excluye (mismo criterio que buscar_camara())."""
        botella_bot2 = _make_botella(1, "Bot 2 Cra Mitre 440", camara_id=1)
        with (
            patch(f"{MODULE}._buscar_botella_ilike_lista", return_value=[botella_bot2]),
            patch(f"{MODULE}._buscar_botella_tokens_lista", return_value=[]),
        ):
            resultado = _cascada_botella("Bot 2 Cra Mitre 440", MagicMock())

        self.assertEqual(resultado, [botella_bot2])

    def test_input_degenerado_no_consulta_db(self) -> None:
        """Important #3: input con < 2 tokens significativos y sin números corta antes de
        consultar la DB — nunca debe emitir un ILIKE '%%' de tabla completa."""
        with (
            patch(f"{MODULE}._buscar_botella_ilike_lista") as mock_ilike,
            patch(f"{MODULE}._buscar_botella_tokens_lista") as mock_tokens,
        ):
            resultado = _cascada_botella("VL", MagicMock())

        self.assertEqual(resultado, [])
        mock_ilike.assert_not_called()
        mock_tokens.assert_not_called()

    def test_input_vacio_no_consulta_db(self) -> None:
        """Mismo caso límite que el anterior pero con string vacía/sólo puntuación."""
        with (
            patch(f"{MODULE}._buscar_botella_ilike_lista") as mock_ilike,
            patch(f"{MODULE}._buscar_botella_tokens_lista") as mock_tokens,
        ):
            resultado = _cascada_botella("...", MagicMock())

        self.assertEqual(resultado, [])
        mock_ilike.assert_not_called()
        mock_tokens.assert_not_called()

    def test_intento1_ambiguo_intento2_reduce_a_uno(self) -> None:
        """Important #4: Intento 1 (ILIKE nombre completo) devuelve 2 candidatas ambiguas; Intento
        2 (AND-ILIKE por tokens) las reduce a 1 -> ese es el resultado final de la cascada."""
        c1 = _make_botella(1, "Bot 2 Cra Mitre 440", camara_id=1)
        c2 = _make_botella(2, "Bot 3 Cra Mitre 441", camara_id=2)
        with (
            patch(f"{MODULE}._buscar_botella_ilike_lista", return_value=[c1, c2]),
            patch(f"{MODULE}._buscar_botella_tokens_lista", return_value=[c1]),
        ):
            resultado = _cascada_botella("Bot Mitre", MagicMock())

        self.assertEqual(resultado, [c1])

    def test_numeros_requeridos_filtra_dentro_de_la_cascada(self) -> None:
        """El filtro de números (_filtrar_por_numeros, reusado real) se aplica de verdad dentro de
        _cascada_botella: de 2 candidatas devueltas por el Intento 1, sólo la que contiene "440"
        sobrevive cuando el input pide "440"."""
        c440 = _make_botella(1, "Bot 2 Cra Mitre 440", camara_id=1)
        c441 = _make_botella(2, "Bot 2 Cra Mitre 441", camara_id=2)
        with (
            patch(f"{MODULE}._buscar_botella_ilike_lista", return_value=[c440, c441]),
            patch(f"{MODULE}._buscar_botella_tokens_lista", return_value=[]),
        ):
            resultado = _cascada_botella("Bot 2 Cra Mitre 440", MagicMock())

        self.assertEqual(resultado, [c440])


if __name__ == "__main__":
    unittest.main()
