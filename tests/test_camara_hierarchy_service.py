# Nombre de archivo: test_camara_hierarchy_service.py
# Ubicación de archivo: tests/test_camara_hierarchy_service.py
# Descripción: Pruebas de la jerarquía Cámara/Botella — detección de sufijo "Bot N" y resolución/creación de la cámara padre

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.services.camara_hierarchy_service import (
    estado_mas_restrictivo,
    extraer_base,
    ids_camaras_con_cromo_hijos,
    normalizar_para_agrupar,
    normalizar_para_agrupar_extendido,
    resolver_o_crear_padre,
    resolver_o_crear_padre_desde_base,
)
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos


@pytest.fixture(autouse=True)
def _sin_botellas_cromo(monkeypatch):
    """Por defecto, ninguna Cámara candidata tiene Botellas Cromo propias — los tests que sí quieren
    ejercitar esa protección (hallazgo real, 2026-08-12: ver `test_resolver_o_crear_padre_desde_base_*
    _con_botellas_cromo*`) sobreescriben este mismo patch dentro del test."""
    monkeypatch.setattr(
        "core.services.camara_hierarchy_service.ids_camaras_con_cromo_hijos",
        lambda session: set(),
    )


@pytest.mark.parametrize(
    "nombre,base_esperada",
    [
        ("Cra 14 de Julio 240 Bot 2 CF", "Cra 14 de Julio 240 CF"),
        ("Cra Cerrito 208 Bot 2 CF", "Cra Cerrito 208 CF"),
        # Sin espacio tras el número ("Bot 3CF") — el lookahead (no un \b de cierre) permite que la
        # letra "C" siga inmediatamente al dígito.
        ("Cra Av Triunvirato 3174 Bot 3CF", "Cra Av Triunvirato 3174 CF"),
        # Sin espacio ANTES del número ("Bot2").
        ("Cra 25 de Mayo 201 Bot2 C.F.", "Cra 25 de Mayo 201 C.F."),
        # "Bot N" al inicio del string — la seguridad viene de la clase de un solo dígito, no de la
        # posición.
        ("Bot 2 Tunel Calle 1 N 2670", "Tunel Calle 1 N 2670"),
        # Minúscula — la regex es case-insensitive.
        ("bot 2 calle principal 100", "calle principal 100"),
        # Punto DESPUÉS del dígito (2026-08-14, bug real): sin el `\.?` final, el punto sobrevivía
        # como residuo al inicio del resultado — ids reales 7683 y 6561.
        ("Bot 2. Cra Marcos Sastre y Colectora Este", "Cra Marcos Sastre y Colectora Este"),
        # El punto interno legítimo ("Poste Est .") no debe tocarse — sólo el residuo del token "Bot N.".
        ("Bot 2. Poste Est . Bs. As. C.F", "Poste Est . Bs. As. C.F"),
        # Punto pegado sin espacio tras el dígito, análogo al caso ya cubierto "Bot 3CF" sin punto.
        ("Cra Test 100 Bot 2.CF", "Cra Test 100 CF"),
    ],
)
def test_extraer_base_casos_reales(nombre: str, base_esperada: str) -> None:
    assert extraer_base(nombre) == base_esperada


@pytest.mark.parametrize(
    "nombre",
    [
        # Hallazgo real: "30" no es un índice de botella, es parte del nombre de la calle "30 de
        # Septiembre" — la clase de un solo dígito [1-9] evita este falso positivo a propósito.
        "Bot 30 de Septiembre y J.M.Estrada (Adrogue)",
        "Cra Concepcion Arenal 3602 CF",
        None,
        "",
    ],
)
def test_extraer_base_no_matchea_casos_ambiguos_o_ausentes(nombre) -> None:
    assert extraer_base(nombre) is None


def test_normalizar_para_agrupar_ignora_acentos_mayusculas_y_puntuacion() -> None:
    a = normalizar_para_agrupar("Cra. 14 de Julio 240, CF")
    b = normalizar_para_agrupar("cra 14 de julio 240 cf")
    assert a == b


def test_normalizar_para_agrupar_extendido_colapsa_caso_real() -> None:
    """Caso real documentado (docs/decisiones.md, docs/infra.md): ninguna comparte sufijo/prefijo, ni
    siquiera el mismo token inicial ("Cámara" vs "Cra") — sólo colapsan aplicando abreviatura
    ("cf" -> "") y sinónimo ("camara" -> "cra") sobre el string ya normalizado."""
    a = normalizar_para_agrupar_extendido("Cámara 14 de Julio 240")
    b = normalizar_para_agrupar_extendido("Cra 14 de Julio 240 CF")
    assert a == b == "cra 14 de julio 240"


def test_estado_mas_restrictivo_prioriza_baneada() -> None:
    resultado = estado_mas_restrictivo([CamaraEstado.LIBRE, CamaraEstado.BANEADA, CamaraEstado.OCUPADA])
    assert resultado == CamaraEstado.BANEADA


def test_estado_mas_restrictivo_ocupada_sobre_libre() -> None:
    resultado = estado_mas_restrictivo([CamaraEstado.LIBRE, CamaraEstado.OCUPADA])
    assert resultado == CamaraEstado.OCUPADA


def test_estado_mas_restrictivo_lista_vacia_da_libre() -> None:
    assert estado_mas_restrictivo([]) == CamaraEstado.LIBRE


def test_estado_mas_restrictivo_ignora_pendiente_revision() -> None:
    """Bug real encontrado corriendo el backfill contra datos reales: PENDIENTE_REVISION no es un
    nivel de severidad física — no debe "ganarle" a LIBRE ni a ningún otro estado del grupo."""
    resultado = estado_mas_restrictivo([CamaraEstado.LIBRE, CamaraEstado.PENDIENTE_REVISION])
    assert resultado == CamaraEstado.LIBRE


def test_estado_mas_restrictivo_solo_pendiente_revision_da_libre() -> None:
    resultado = estado_mas_restrictivo([CamaraEstado.PENDIENTE_REVISION, CamaraEstado.PENDIENTE_REVISION])
    assert resultado == CamaraEstado.LIBRE


def test_estado_mas_restrictivo_no_operativa_sobre_libre() -> None:
    """NO_OPERATIVA (sin señal real, backfill Cromo) es más conservador que LIBRE — no debe quedar
    oculto por una hermana LIBRE del mismo grupo."""
    resultado = estado_mas_restrictivo([CamaraEstado.LIBRE, CamaraEstado.NO_OPERATIVA])
    assert resultado == CamaraEstado.NO_OPERATIVA


def test_estado_mas_restrictivo_ocupada_sobre_no_operativa() -> None:
    """Un uso/baneo confirmado del resto del grupo no debe quedar oculto por una hermana sin señal
    real (NO_OPERATIVA)."""
    resultado = estado_mas_restrictivo([CamaraEstado.NO_OPERATIVA, CamaraEstado.OCUPADA])
    assert resultado == CamaraEstado.OCUPADA


def test_resolver_o_crear_padre_nombre_sin_sufijo_no_toca_la_db() -> None:
    session = MagicMock()

    resultado = resolver_o_crear_padre(session, "Cra Piedras 401 CF", usuario="test")

    assert resultado is None
    session.execute.assert_not_called()
    session.add.assert_not_called()


def test_resolver_o_crear_padre_reusa_padre_ya_establecido() -> None:
    """Un padre "ya establecido" es una fila raíz que YA tiene al menos una botella — sólo esas se
    reusan, para no promover por casualidad de nombre una fila que todavía no es un padre real."""
    session = MagicMock()
    padre_existente = Camara(id=99, nombre="Cra 14 de Julio 240 CF", camara_padre_id=None)
    padre_existente.botellas = [Camara(id=50, nombre="Cra 14 de Julio 240 Bot 5 CF")]
    session.query.return_value.filter.return_value.all.return_value = [padre_existente]

    resultado = resolver_o_crear_padre(session, "Cra 14 de Julio 240 Bot 2 CF", usuario="test")

    assert resultado is padre_existente
    session.add.assert_not_called()
    # Sí debe tomar el advisory lock antes de decidir — protege contra altas concurrentes.
    session.execute.assert_called_once()


def test_resolver_o_crear_padre_no_promueve_una_fila_pelada_sin_botellas_a_padre() -> None:
    """Hallazgo real: si sólo existe la fila "pelada" (sin sufijo, sin botellas todavía) con el mismo
    nombre base, NO se la promueve a padre — se crea una fila nueva y la pelada queda absorbida como
    botella más (mismo criterio que el backfill)."""
    session = MagicMock()
    pelada = Camara(id=5, nombre="Cra 14 de Julio 240 CF", camara_padre_id=None)
    session.query.return_value.filter.return_value.all.return_value = [pelada]

    resultado = resolver_o_crear_padre(session, "Cra 14 de Julio 240 Bot 2 CF", usuario="test")

    assert resultado is not pelada
    assert resultado.nombre == "Cra 14 de Julio 240 CF"
    assert resultado.origen_datos == CamaraOrigenDatos.INFERIDO
    # La fila pelada queda absorbida como botella del padre nuevo, no promovida a padre.
    assert pelada.camara_padre_id == resultado.id


def test_resolver_o_crear_padre_ignora_una_camara_con_nombre_distinto() -> None:
    session = MagicMock()
    otra_camara = Camara(id=5, nombre="Cra Otra Dirección 999 CF", camara_padre_id=None)
    session.query.return_value.filter.return_value.all.return_value = [otra_camara]

    resultado = resolver_o_crear_padre(session, "Cra 14 de Julio 240 Bot 2 CF", usuario="test")

    assert resultado is not otra_camara
    assert resultado.nombre == "Cra 14 de Julio 240 CF"
    assert otra_camara.camara_padre_id is None  # no se toca, el nombre no coincide
    session.add.assert_called_once_with(resultado)


def test_resolver_o_crear_padre_crea_uno_nuevo_si_no_existe() -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    resultado = resolver_o_crear_padre(session, "Cra 14 de Julio 240 Bot 2 CF", usuario="test")

    assert resultado is not None
    assert resultado.nombre == "Cra 14 de Julio 240 CF"
    assert resultado.estado == CamaraEstado.LIBRE
    assert resultado.origen_datos == CamaraOrigenDatos.INFERIDO
    session.add.assert_called_once_with(resultado)
    session.flush.assert_called()


def test_resolver_o_crear_padre_desde_base_permite_estado_y_origen_custom() -> None:
    """Núcleo reutilizable por otros backfills (ej. Botellas Cromo) — parametrizado en
    estado_si_nuevo/origen_si_nuevo, sin duplicar la lógica de advisory lock/absorción."""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    resultado = resolver_o_crear_padre_desde_base(
        session,
        "Cra Plaza de los Ingleses CF",
        usuario="cromo_backfill",
        estado_si_nuevo=CamaraEstado.NO_OPERATIVA,
        origen_si_nuevo=CamaraOrigenDatos.INFERIDO_CROMO,
    )

    assert resultado.nombre == "Cra Plaza de los Ingleses CF"
    assert resultado.estado == CamaraEstado.NO_OPERATIVA
    assert resultado.origen_datos == CamaraOrigenDatos.INFERIDO_CROMO
    session.add.assert_called_once_with(resultado)


def test_resolver_o_crear_padre_desde_base_reusa_padre_existente_sin_tocar_su_estado() -> None:
    """Si ya existe un padre real (con estado propio, trackeado), se reutiliza tal cual — no se
    inventa ni se sobreescribe su estado sólo porque el llamador pasó un default distinto."""
    session = MagicMock()
    padre_existente = Camara(id=99, nombre="Cra 14 de Julio 240 CF", estado=CamaraEstado.BANEADA, camara_padre_id=None)
    padre_existente.botellas = [Camara(id=50, nombre="Cra 14 de Julio 240 Bot 5 CF")]
    session.query.return_value.filter.return_value.all.return_value = [padre_existente]

    resultado = resolver_o_crear_padre_desde_base(
        session,
        "Cra 14 de Julio 240 CF",
        usuario="cromo_backfill",
        estado_si_nuevo=CamaraEstado.NO_OPERATIVA,
        origen_si_nuevo=CamaraOrigenDatos.INFERIDO_CROMO,
    )

    assert resultado is padre_existente
    assert resultado.estado == CamaraEstado.BANEADA
    session.add.assert_not_called()


def test_resolver_o_crear_padre_desde_base_reusa_camara_con_solo_botellas_cromo(monkeypatch) -> None:
    """Hallazgo real (2026-08-12, detectado en --dry-run del backfill de Cromo, nunca llegó a tocar
    datos reales): una Cámara padre creada por el backfill de Cromo tiene CERO Botellas legado
    (`.botellas` vacío) — sin este chequeo se la trataría como "pelada" y NO se reusaría como padre."""
    session = MagicMock()
    padre_cromo = Camara(id=6526, nombre="Cra Bernardo de Irigoyen 194 CF", estado=CamaraEstado.NO_OPERATIVA, camara_padre_id=None)
    padre_cromo.botellas = []  # cero Botellas legado — sus hijas son CromoBotella, tabla distinta
    session.query.return_value.filter.return_value.all.return_value = [padre_cromo]
    monkeypatch.setattr(
        "core.services.camara_hierarchy_service.ids_camaras_con_cromo_hijos",
        lambda session: {6526},
    )

    resultado = resolver_o_crear_padre_desde_base(session, "Cra Bernardo de Irigoyen 194 CF", usuario="test")

    assert resultado is padre_cromo
    session.add.assert_not_called()


def test_resolver_o_crear_padre_desde_base_reusa_padre_que_solo_coincide_por_normalizacion_extendida() -> None:
    """Hallazgo real 2026-08-14: con la normalización básica, 'Bot Tza San Antonio 640' (ya padre) y
    'Bot. Tza.San Antonio 640 CF' (nueva base a resolver) generaban 2 filas para el mismo sitio."""
    session = MagicMock()
    padre_existente = Camara(id=10, nombre="Bot Tza San Antonio 640", camara_padre_id=None)
    padre_existente.botellas = [Camara(id=11, nombre="Bot Tza San Antonio 640 Bot 2")]
    session.query.return_value.filter.return_value.all.return_value = [padre_existente]

    resultado = resolver_o_crear_padre_desde_base(session, "Bot. Tza.San Antonio 640 CF", usuario="test")

    assert resultado is padre_existente
    session.add.assert_not_called()


def test_resolver_o_crear_padre_desde_base_absorbe_pelada_que_solo_coincide_por_normalizacion_extendida() -> None:
    """Ídem, sin hijos previos: la pelada 'Cra Balcarce 302' se absorbe como botella del padre nuevo en
    vez de quedar como una segunda fila raíz para el mismo sitio."""
    session = MagicMock()
    pelada = Camara(id=20, nombre="Cra Balcarce 302", camara_padre_id=None)
    session.query.return_value.filter.return_value.all.return_value = [pelada]

    resultado = resolver_o_crear_padre_desde_base(session, "Cra Balcarce 302 CF", usuario="test")

    assert resultado is not pelada
    assert pelada.camara_padre_id == resultado.id


def test_ids_camaras_con_cromo_hijos_dedupe_y_descarta_nulos() -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [(6526,), (6526,), (6529,)]

    resultado = ids_camaras_con_cromo_hijos(session)

    assert resultado == {6526, 6529}
