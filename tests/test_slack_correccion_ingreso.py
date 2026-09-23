# Nombre de archivo: test_slack_correccion_ingreso.py
# Ubicación de archivo: tests/test_slack_correccion_ingreso.py
# Descripción: Tests del parser y los constructores de respuesta de "Forzar ingreso"/"Forzar egreso" (funciones puras)

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("TESTING", "true")

from modules.slack_baneo_notifier.correccion_ingreso import (
    ComandoForzarEgreso,
    ComandoForzarIngreso,
    IngresoAbiertoInfo,
    MomentoInvalidoError,
    construir_respuesta_camara_ambigua,
    construir_respuesta_egreso_anterior_al_ingreso,
    construir_respuesta_falta_fecha,
    construir_respuesta_hilo_sin_formulario,
    construir_respuesta_ingreso_ya_cerrado,
    construir_respuesta_momento_invalido,
    construir_respuesta_ok_forzar_egreso_asentado,
    construir_respuesta_ok_forzar_egreso_cerrado,
    construir_respuesta_ok_forzar_ingreso,
    construir_respuesta_varios_ingresos_abiertos,
    extraer_comando_forzar_egreso,
    extraer_comando_forzar_ingreso,
    extraer_momento_solo,
    parsear_momento_ar,
)

# Momento de referencia fijo para que los tests de fecha futura / fuera de rango sean deterministas
# sin depender del reloj real ni de la zona horaria del proceso que corre pytest.
_AHORA = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


class TestExtraerComandoForzarIngreso(unittest.TestCase):
    """Cubre las 2 formas de "Forzar ingreso" (Step 1 del brief)."""

    def test_camara_sin_fecha(self) -> None:
        resultado = extraer_comando_forzar_ingreso("Forzar ingreso Cra Mitre 302")
        self.assertEqual(
            resultado, ComandoForzarIngreso(camara_texto="Cra Mitre 302", momento=None, motivo=None)
        )

    def test_camara_con_fecha(self) -> None:
        resultado = extraer_comando_forzar_ingreso(
            "Forzar ingreso Cra Mitre 302 22-09-2026 10:00", ahora=_AHORA
        )
        assert resultado is not None
        self.assertEqual(resultado.camara_texto, "Cra Mitre 302")
        self.assertEqual(resultado.motivo, None)
        # 22-09-2026 10:00 AR (UTC-3) == 22-09-2026 13:00 UTC
        self.assertEqual(resultado.momento, datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc))

    def test_camara_con_fecha_y_motivo_libre(self) -> None:
        """No hay palabra clave de motivo (decisión de producto) — cualquier texto que sobre
        después de la hora se captura como motivo opcional, nunca se exige."""
        resultado = extraer_comando_forzar_ingreso(
            "Forzar ingreso Cra Mitre 302 22-09-2026 10:00 se confirmó con el técnico", ahora=_AHORA
        )
        assert resultado is not None
        self.assertEqual(resultado.camara_texto, "Cra Mitre 302")
        self.assertEqual(resultado.motivo, "se confirmó con el técnico")

    def test_camara_con_guiones_y_numeros(self) -> None:
        resultado = extraer_comando_forzar_ingreso("Forzar ingreso Cra Ruta 9 - Km 45")
        self.assertEqual(resultado.camara_texto, "Cra Ruta 9 - Km 45")

    def test_camara_con_guiones_y_numeros_con_fecha(self) -> None:
        resultado = extraer_comando_forzar_ingreso(
            "Forzar ingreso Cra Ruta 9 - Km 45 22-09-2026 10:00", ahora=_AHORA
        )
        assert resultado is not None
        self.assertEqual(resultado.camara_texto, "Cra Ruta 9 - Km 45")

    def test_regex_no_goloso_discrimina_con_segunda_fecha_embebida(self) -> None:
        """Fix round 1 (Important, hallazgo del revisor): `test_camara_con_guiones_y_numeros_con_fecha`
        de arriba NO alcanza para detectar si alguien cambia el `.+?` de
        `_RE_FORZAR_INGRESO_CON_FECHA` por `.+` (goloso) — con una sola fecha en el string, lazy y
        goloso dan el mismo resultado. La divergencia real sólo aparece con una SEGUNDA subcadena con
        forma de fecha más adelante (acá, dentro del motivo libre): un patrón goloso haría backtrack
        desde el final y tomaría la ÚLTIMA fecha como la del comando, comiéndose el motivo entero
        (incluida la primera fecha) como si fuera parte del nombre de cámara.

        Verificado a mano (evidencia en task-4-report.md, sección "Fix round 1"): cambiando
        `_RE_FORZAR_INGRESO_CON_FECHA` de `.+?` a `.+` este test falla — da
        `camara_texto="Cra Mitre 302 20-09-2026 10:00 visto de nuevo"`, `momento` del 21-09 (no del
        20-09) y `motivo=None`."""
        resultado = extraer_comando_forzar_ingreso(
            "Forzar ingreso Cra Mitre 302 20-09-2026 10:00 visto de nuevo 21-09-2026 11:00",
            ahora=_AHORA,
        )
        assert resultado is not None
        self.assertEqual(resultado.camara_texto, "Cra Mitre 302")
        self.assertEqual(resultado.momento, datetime(2026, 9, 20, 13, 0, tzinfo=timezone.utc))
        self.assertEqual(resultado.motivo, "visto de nuevo 21-09-2026 11:00")

    def test_negrita_slack_en_nombre_de_camara(self) -> None:
        """Bug real 2026-08-25 (mismo que `test_slack_cable_info.py`): Slack manda los asteriscos de
        negrita literales en `event["text"]`."""
        resultado = extraer_comando_forzar_ingreso("Forzar ingreso *Cra Balcarce 302*")
        self.assertEqual(resultado.camara_texto, "Cra Balcarce 302")

    def test_negrita_slack_no_rompe_el_ancla_de_fecha(self) -> None:
        """La negrita también rompía el ancla `$` del regex con sufijo (ver docstring del módulo) —
        sin quitarla antes, el "*" final no encajaría después de la hora."""
        resultado = extraer_comando_forzar_ingreso(
            "Forzar ingreso *Cra Balcarce 302* 22-09-2026 10:00", ahora=_AHORA
        )
        assert resultado is not None
        self.assertEqual(resultado.camara_texto, "Cra Balcarce 302")
        self.assertEqual(resultado.momento, datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc))

    def test_ruido_operativo_se_recorta(self) -> None:
        resultado = extraer_comando_forzar_ingreso("Forzar ingreso Cra Quesada 2396 CF - Móvil 4")
        self.assertEqual(resultado.camara_texto, "Cra Quesada 2396 CF")

    def test_normaliza_espacios_multiples(self) -> None:
        resultado = extraer_comando_forzar_ingreso("Forzar   ingreso   Cra Mitre 302")
        self.assertEqual(resultado.camara_texto, "Cra Mitre 302")

    def test_case_insensitive(self) -> None:
        resultado = extraer_comando_forzar_ingreso("FORZAR INGRESO Cra Mitre 302")
        self.assertEqual(resultado.camara_texto, "Cra Mitre 302")

    def test_no_matchea_texto_sin_relacion(self) -> None:
        self.assertIsNone(extraer_comando_forzar_ingreso("Hola, ¿cómo estás?"))

    def test_no_matchea_forzar_egreso(self) -> None:
        self.assertIsNone(extraer_comando_forzar_ingreso("Forzar egreso Cra Mitre 302"))

    def test_camara_vacia_no_matchea(self) -> None:
        self.assertIsNone(extraer_comando_forzar_ingreso("Forzar ingreso"))

    def test_fecha_futura_propaga_error(self) -> None:
        with self.assertRaises(MomentoInvalidoError) as ctx:
            extraer_comando_forzar_ingreso(
                "Forzar ingreso Cra Mitre 302 24-09-2026 10:00", ahora=_AHORA
            )
        self.assertEqual(ctx.exception.razon, "futuro")

    def test_fecha_fuera_de_rango_propaga_error(self) -> None:
        with self.assertRaises(MomentoInvalidoError) as ctx:
            extraer_comando_forzar_ingreso(
                "Forzar ingreso Cra Mitre 302 01-01-2026 10:00", ahora=_AHORA
            )
        self.assertEqual(ctx.exception.razon, "fuera_de_rango")

    def test_fecha_malformada_propaga_error(self) -> None:
        with self.assertRaises(MomentoInvalidoError) as ctx:
            extraer_comando_forzar_ingreso(
                "Forzar ingreso Cra Mitre 302 32-13-2026 10:00", ahora=_AHORA
            )
        self.assertEqual(ctx.exception.razon, "formato")

    def test_hora_invalida_propaga_error(self) -> None:
        with self.assertRaises(MomentoInvalidoError) as ctx:
            extraer_comando_forzar_ingreso(
                "Forzar ingreso Cra Mitre 302 22-09-2026 25:00", ahora=_AHORA
            )
        self.assertEqual(ctx.exception.razon, "formato")


class TestExtraerComandoForzarEgreso(unittest.TestCase):
    """Cubre las 3 formas de "Forzar egreso" (bare, cámara+fecha, `#<id>`) más el caso derivado
    "cámara sin fecha" (ver docstring del módulo)."""

    def test_bare(self) -> None:
        resultado = extraer_comando_forzar_egreso("Forzar egreso")
        self.assertEqual(
            resultado,
            ComandoForzarEgreso(camara_texto=None, ingreso_id=None, momento=None, motivo=None),
        )

    def test_bare_case_insensitive_y_espacios(self) -> None:
        resultado = extraer_comando_forzar_egreso("  forzar   EGRESO  ")
        self.assertEqual(resultado.camara_texto, None)
        self.assertEqual(resultado.ingreso_id, None)

    def test_camara_con_fecha(self) -> None:
        resultado = extraer_comando_forzar_egreso(
            "Forzar egreso Cra Mitre 302 22-09-2026 10:00", ahora=_AHORA
        )
        assert resultado is not None
        self.assertEqual(resultado.camara_texto, "Cra Mitre 302")
        self.assertEqual(resultado.ingreso_id, None)
        self.assertEqual(resultado.momento, datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc))

    def test_camara_con_fecha_y_motivo_libre(self) -> None:
        resultado = extraer_comando_forzar_egreso(
            "Forzar egreso Cra Mitre 302 22-09-2026 10:00 formulario nunca llegó", ahora=_AHORA
        )
        assert resultado is not None
        self.assertEqual(resultado.motivo, "formulario nunca llegó")

    def test_camara_con_guiones_y_numeros(self) -> None:
        resultado = extraer_comando_forzar_egreso(
            "Forzar egreso Cra Ruta 9 - Km 45 22-09-2026 10:00", ahora=_AHORA
        )
        assert resultado is not None
        self.assertEqual(resultado.camara_texto, "Cra Ruta 9 - Km 45")

    def test_regex_no_goloso_discrimina_con_segunda_fecha_embebida(self) -> None:
        """Fix round 1 (Important) — gemelo egreso de
        `TestExtraerComandoForzarIngreso.test_regex_no_goloso_discrimina_con_segunda_fecha_embebida`.
        Con `_RE_FORZAR_EGRESO_CON_FECHA` cambiado a `.+` (goloso), este test falla exactamente igual:
        toma la segunda fecha embebida en el motivo en vez de la primera."""
        resultado = extraer_comando_forzar_egreso(
            "Forzar egreso Cra Mitre 302 20-09-2026 10:00 visto de nuevo 21-09-2026 11:00",
            ahora=_AHORA,
        )
        assert resultado is not None
        self.assertEqual(resultado.camara_texto, "Cra Mitre 302")
        self.assertEqual(resultado.momento, datetime(2026, 9, 20, 13, 0, tzinfo=timezone.utc))
        self.assertEqual(resultado.motivo, "visto de nuevo 21-09-2026 11:00")

    def test_por_id(self) -> None:
        resultado = extraer_comando_forzar_egreso("Forzar egreso #123")
        self.assertEqual(
            resultado,
            ComandoForzarEgreso(camara_texto=None, ingreso_id=123, momento=None, motivo=None),
        )

    def test_por_id_con_motivo_libre(self) -> None:
        resultado = extraer_comando_forzar_egreso("Forzar egreso #123 se fue antes de tiempo")
        assert resultado is not None
        self.assertEqual(resultado.ingreso_id, 123)
        self.assertEqual(resultado.motivo, "se fue antes de tiempo")

    def test_camara_sin_fecha_queda_incompleto(self) -> None:
        """No es una forma válida de la gramática de "Forzar egreso" (a diferencia de "Forzar
        ingreso") — el parser no conoce el tipo de hilo, así que devuelve `camara_texto` seteado +
        `momento is None` + `ingreso_id is None` de forma neutral. La Task 5 decide qué responder
        (momento implícito del hilo si es de tipo Egreso, o `construir_respuesta_falta_fecha` si
        no)."""
        resultado = extraer_comando_forzar_egreso("Forzar egreso Cra Mitre 302")
        self.assertEqual(resultado.camara_texto, "Cra Mitre 302")
        self.assertEqual(resultado.momento, None)
        self.assertEqual(resultado.ingreso_id, None)

    def test_negrita_slack(self) -> None:
        resultado = extraer_comando_forzar_egreso("Forzar egreso *Cra Balcarce 302*")
        self.assertEqual(resultado.camara_texto, "Cra Balcarce 302")

    def test_negrita_slack_no_rompe_el_ancla_de_fecha(self) -> None:
        """Mismo bug real 2026-08-25 que en "Forzar ingreso" — la negrita literal de Slack también
        rompía el ancla `$` del regex con sufijo de fecha."""
        resultado = extraer_comando_forzar_egreso(
            "Forzar egreso *Cra Balcarce 302* 22-09-2026 10:00", ahora=_AHORA
        )
        assert resultado is not None
        self.assertEqual(resultado.camara_texto, "Cra Balcarce 302")
        self.assertEqual(resultado.momento, datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc))

    def test_no_matchea_texto_sin_relacion(self) -> None:
        self.assertIsNone(extraer_comando_forzar_egreso("Hola, ¿cómo estás?"))

    def test_no_matchea_forzar_ingreso(self) -> None:
        self.assertIsNone(extraer_comando_forzar_egreso("Forzar ingreso Cra Mitre 302"))

    def test_fecha_futura_propaga_error(self) -> None:
        with self.assertRaises(MomentoInvalidoError) as ctx:
            extraer_comando_forzar_egreso(
                "Forzar egreso Cra Mitre 302 24-09-2026 10:00", ahora=_AHORA
            )
        self.assertEqual(ctx.exception.razon, "futuro")

    def test_fecha_fuera_de_rango_propaga_error(self) -> None:
        with self.assertRaises(MomentoInvalidoError) as ctx:
            extraer_comando_forzar_egreso(
                "Forzar egreso Cra Mitre 302 01-01-2026 10:00", ahora=_AHORA
            )
        self.assertEqual(ctx.exception.razon, "fuera_de_rango")

    def test_fecha_malformada_propaga_error(self) -> None:
        with self.assertRaises(MomentoInvalidoError) as ctx:
            extraer_comando_forzar_egreso(
                "Forzar egreso Cra Mitre 302 32-13-2026 10:00", ahora=_AHORA
            )
        self.assertEqual(ctx.exception.razon, "formato")

    def test_hora_invalida_propaga_error(self) -> None:
        with self.assertRaises(MomentoInvalidoError) as ctx:
            extraer_comando_forzar_egreso(
                "Forzar egreso Cra Mitre 302 22-09-2026 25:00", ahora=_AHORA
            )
        self.assertEqual(ctx.exception.razon, "formato")


class TestExtraerMomentoSolo(unittest.TestCase):
    """Regex de la respuesta de seguimiento (Task 6): sólo "DD-MM-AAAA HH:MM"."""

    def test_matchea_fecha_sola(self) -> None:
        momento = extraer_momento_solo("22-09-2026 10:00", ahora=_AHORA)
        self.assertEqual(momento, datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc))

    def test_no_matchea_texto_con_mas_contenido(self) -> None:
        self.assertIsNone(extraer_momento_solo("Forzar egreso Cra Mitre 302"))

    def test_no_matchea_texto_vacio(self) -> None:
        self.assertIsNone(extraer_momento_solo(""))

    def test_tolera_negrita_slack(self) -> None:
        momento = extraer_momento_solo("*22-09-2026 10:00*", ahora=_AHORA)
        self.assertEqual(momento, datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc))

    def test_fecha_futura_propaga_error(self) -> None:
        with self.assertRaises(MomentoInvalidoError) as ctx:
            extraer_momento_solo("24-09-2026 10:00", ahora=_AHORA)
        self.assertEqual(ctx.exception.razon, "futuro")


class TestParsearMomentoAr(unittest.TestCase):
    """Tests directos de `parsear_momento_ar` — conversión de zona horaria y límites de rango."""

    def test_convierte_ar_a_utc(self) -> None:
        # Buenos Aires es UTC-3 todo el año (sin horario de verano).
        momento = parsear_momento_ar("22-09-2026", "10:00", ahora=_AHORA)
        self.assertEqual(momento, datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc))
        self.assertEqual(momento.tzinfo, timezone.utc)

    def test_limite_exacto_90_dias_es_valido(self) -> None:
        # _AHORA es 2026-09-23 12:00 UTC. 90 días atrás en UTC == 2026-06-25 12:00 UTC.
        # 25-06-2026 09:00 AR == 25-06-2026 12:00 UTC -> exactamente en el límite, no lo excede.
        momento = parsear_momento_ar("25-06-2026", "09:00", ahora=_AHORA)
        self.assertEqual(momento, datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc))

    def test_un_minuto_mas_alla_de_90_dias_falla(self) -> None:
        with self.assertRaises(MomentoInvalidoError) as ctx:
            parsear_momento_ar("25-06-2026", "08:59", ahora=_AHORA)
        self.assertEqual(ctx.exception.razon, "fuera_de_rango")

    def test_momento_igual_a_ahora_es_valido(self) -> None:
        # 23-09-2026 09:00 AR == 23-09-2026 12:00 UTC == _AHORA exacto (no es "futuro").
        momento = parsear_momento_ar("23-09-2026", "09:00", ahora=_AHORA)
        self.assertEqual(momento, _AHORA)

    def test_texto_crudo_del_error_incluye_fecha_y_hora(self) -> None:
        with self.assertRaises(MomentoInvalidoError) as ctx:
            parsear_momento_ar("22-09-2026", "25:00", ahora=_AHORA)
        self.assertEqual(ctx.exception.texto_crudo, "22-09-2026 25:00")


class TestConstructoresDeRespuesta(unittest.TestCase):
    """Los 10 constructores de `Step 4` del brief — todos devuelven `str` y no dependen de DB/Slack."""

    def test_ok_forzar_ingreso(self) -> None:
        texto = construir_respuesta_ok_forzar_ingreso(
            "Cra Mitre 302", datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc), "rider.fernandez"
        )
        self.assertIsInstance(texto, str)
        self.assertIn("Cra Mitre 302", texto)
        self.assertIn("rider.fernandez", texto)

    def test_ok_forzar_egreso_cerrado_con_tecnico(self) -> None:
        texto = construir_respuesta_ok_forzar_egreso_cerrado(
            "Cra Mitre 302",
            datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc),
            "rider.fernandez",
            tecnico_original="juan.perez",
        )
        self.assertIsInstance(texto, str)
        self.assertIn("Cra Mitre 302", texto)
        self.assertIn("juan.perez", texto)
        self.assertIn("rider.fernandez", texto)

    def test_ok_forzar_egreso_cerrado_sin_tecnico_no_rompe(self) -> None:
        texto = construir_respuesta_ok_forzar_egreso_cerrado(
            "Cra Mitre 302", datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc), "rider.fernandez"
        )
        self.assertIsInstance(texto, str)

    def test_ok_forzar_egreso_asentado(self) -> None:
        texto = construir_respuesta_ok_forzar_egreso_asentado(
            "Cra Mitre 302", datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc), "rider.fernandez"
        )
        self.assertIsInstance(texto, str)
        self.assertIn("Cra Mitre 302", texto)

    def test_falta_fecha_egreso(self) -> None:
        texto = construir_respuesta_falta_fecha("Cra Mitre 302", comando="egreso")
        self.assertIsInstance(texto, str)
        self.assertIn("Cra Mitre 302", texto)
        self.assertIn("DD-MM-AAAA", texto)
        self.assertIn("egreso", texto)
        self.assertIn("Forzar egreso Cra Mitre 302 DD-MM-AAAA HH:MM", texto)

    def test_falta_fecha_ingreso(self) -> None:
        """Fix round 1 (Minor): el hilo de Egreso + "Forzar ingreso <CAMARA>" (tabla "Regla del
        momento implícito" de la Task 5) también exige fecha explícita — mismo constructor,
        parametrizado por verbo, para no duplicar el texto en el servicio de la Task 5."""
        texto = construir_respuesta_falta_fecha("Cra Mitre 302", comando="ingreso")
        self.assertIsInstance(texto, str)
        self.assertIn("Cra Mitre 302", texto)
        self.assertIn("DD-MM-AAAA", texto)
        self.assertIn("ingreso", texto)
        self.assertIn("Forzar ingreso Cra Mitre 302 DD-MM-AAAA HH:MM", texto)
        self.assertNotIn("egreso", texto)

    def test_camara_ambigua(self) -> None:
        texto = construir_respuesta_camara_ambigua(
            "Cra Mitre", ["Cra Mitre 302", "Cra Mitre 399"]
        )
        self.assertIsInstance(texto, str)
        self.assertIn("Cra Mitre 302", texto)
        self.assertIn("Cra Mitre 399", texto)
        self.assertIn("2", texto)

    def test_varios_ingresos_abiertos(self) -> None:
        ingresos = [
            IngresoAbiertoInfo(
                id=10, tecnico="juan.perez", fecha_inicio=datetime(2026, 9, 20, 13, 0, tzinfo=timezone.utc)
            ),
            IngresoAbiertoInfo(id=11, tecnico=None, fecha_inicio=None),
        ]
        texto = construir_respuesta_varios_ingresos_abiertos("Cra Mitre 302", ingresos)
        self.assertIsInstance(texto, str)
        self.assertIn("#10", texto)
        self.assertIn("juan.perez", texto)
        self.assertIn("#11", texto)
        self.assertIn("Forzar egreso #", texto)

    def test_egreso_anterior_al_ingreso(self) -> None:
        texto = construir_respuesta_egreso_anterior_al_ingreso(
            datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc),
        )
        self.assertIsInstance(texto, str)

    def test_ingreso_ya_cerrado(self) -> None:
        texto = construir_respuesta_ingreso_ya_cerrado(
            42, datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
        )
        self.assertIsInstance(texto, str)
        self.assertIn("#42", texto)

    def test_hilo_sin_formulario(self) -> None:
        texto = construir_respuesta_hilo_sin_formulario()
        self.assertIsInstance(texto, str)
        self.assertGreater(len(texto), 0)

    def test_momento_invalido_futuro(self) -> None:
        texto = construir_respuesta_momento_invalido(
            MomentoInvalidoError("futuro", "24-09-2026 10:00")
        )
        self.assertIsInstance(texto, str)
        self.assertIn("24-09-2026 10:00", texto)

    def test_momento_invalido_fuera_de_rango(self) -> None:
        texto = construir_respuesta_momento_invalido(
            MomentoInvalidoError("fuera_de_rango", "01-01-2026 10:00")
        )
        self.assertIsInstance(texto, str)
        self.assertIn("01-01-2026 10:00", texto)

    def test_momento_invalido_formato(self) -> None:
        texto = construir_respuesta_momento_invalido(
            MomentoInvalidoError("formato", "22-09-2026 25:00")
        )
        self.assertIsInstance(texto, str)
        self.assertIn("22-09-2026 25:00", texto)

    def test_los_tres_momento_invalido_dan_texto_distinto(self) -> None:
        """Un solo constructor cubre las 3 razones (Step 4 sólo lista una entrada "fecha fuera de
        rango" — ver docstring del módulo/report) — confirmar que igual distingue el mensaje."""
        textos = {
            razon: construir_respuesta_momento_invalido(MomentoInvalidoError(razon, "x"))
            for razon in ("futuro", "fuera_de_rango", "formato")
        }
        self.assertEqual(len(set(textos.values())), 3)


class TestQuitarFormatoSlackPromovido(unittest.TestCase):
    """Verifica que la promoción de `_quitar_formato_slack` a `quitar_formato_slack` en
    `cable_info.py` (Step 2 del brief) no rompió los call-sites internos de ese módulo."""

    def test_info_cable_sigue_funcionando_con_negrita(self) -> None:
        from modules.slack_baneo_notifier.cable_info import extraer_comando_info_cable

        self.assertEqual(extraer_comando_info_cable("info cable *F-VDP-JUR*"), "F-VDP-JUR")

    def test_cable_buffer_sigue_funcionando_con_negrita(self) -> None:
        from modules.slack_baneo_notifier.cable_info import extraer_comando_cable_buffer

        self.assertEqual(
            extraer_comando_cable_buffer("verificar cable *F-VFL-IND* B1"),
            ("verificar", "F-VFL-IND", 1),
        )

    def test_quitar_formato_slack_es_publico_e_importable(self) -> None:
        from modules.slack_baneo_notifier.cable_info import quitar_formato_slack

        self.assertEqual(quitar_formato_slack("*texto*"), "texto")


if __name__ == "__main__":
    unittest.main()
