# Nombre de archivo: test_cromo_ingesta_objetos.py
# Ubicación de archivo: tests/test_cromo_ingesta_objetos.py
# Descripción: Tests de la ingesta de Cromo Red: procesamiento de cables/botellas/fusiones, ID dual, fases paginadas, reconciliación, servicios y cables de terceros

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from core.services.cromo import ingesta
from core.services.cromo.alias_service import AliasBotella
from core.services.cromo.client import CromoClientError
from core.services.cromo.modelos import ConectorOdf
from db.models.cromo import (
    CromoBotella,
    CromoCable,
    CromoFusion,
    CromoIngestaCorrida,
    CromoPelo,
    CromoTubo,
)
from tests.soporte_cromo_ingesta import (
    FIXTURES_DIR,
    _ClientePaginado,
    _ResultadoFilas,
    _SesionFake,
    _SesionFakeCorrida,
    _spies_de_fases,
)
from tests.soporte_cromo_ingesta import geometria_fo  # noqa: F401 - fixture


class _ClienteTopologiaFake:
    """Lo único que `id_dual_resolver.fetch_objeto` le pide a `CromoClient`, más un contador de
    pedidos: el barrido bulk de botellas NUNCA debe pegarle a este método (regresiones de costo de
    la detección dirigida de "ID dual"). Un id no cargado responde 404, igual que Cromo real."""

    def __init__(self, objetos: Optional[dict[int, dict]] = None) -> None:
        self._objetos = objetos or {}
        self.pedidos: list[int] = []

    async def get_objeto_con_topologia(self, n_id_o_id: int) -> dict[str, Any]:
        self.pedidos.append(n_id_o_id)
        if n_id_o_id not in self._objetos:
            raise CromoClientError(f"Cromo respondió 404 en /db/objects/{n_id_o_id}", status_code=404)
        return {"st": "ok", "response": self._objetos[n_id_o_id]}


# ── Procesamiento de un objeto (savepoint real, tolerancia a errores) ──────


@pytest.mark.asyncio
async def test_procesar_cable_directo_crea_y_registra_evento():
    obj = json.loads((FIXTURES_DIR / "cable_barrido_directo.json").read_text())
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_cable_directo(sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert contadores.leidas == 1
    assert contadores.creadas == 1
    assert contadores.errores == 0
    cables_agregados = [o for o in sesion.agregados if isinstance(o, CromoCable)]
    assert len(cables_agregados) == 1
    assert cables_agregados[0].n_id == 50010


@pytest.mark.asyncio
async def test_procesar_cable_directo_objeto_malformado_no_rompe_registra_error():
    obj = {"class": 51, "id": 1, "n_id": 1}  # sin at[] ni vmax coherente: fuerza un camino de error
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    # Forzamos un error real: vmax ausente + n_id ya "existente" con tipo incompatible en _copiar_campos.
    sesion._existentes[(CromoCable, 1)] = object()  # sin atributo .vmax -> AttributeError real al comparar

    await ingesta._procesar_cable_directo(sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert contadores.errores == 1
    assert contadores.creadas == 0
    eventos_error = [o for o in sesion.agregados if getattr(o, "accion", None) == "ERROR"]
    assert len(eventos_error) == 1
    assert eventos_error[0].n_id == 1


@pytest.mark.asyncio
async def test_procesar_cable_directo_remapea_extremo_fusionar():
    obj = json.loads((FIXTURES_DIR / "cable_barrido_directo.json").read_text())
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    alias_por_origen = {10178728: AliasBotella(accion="fusionar", id_cromo_destino=999999)}

    await ingesta._procesar_cable_directo(
        sesion, corrida_id=1, obj=obj, contadores=contadores, alias_por_origen=alias_por_origen
    )

    cables_agregados = [o for o in sesion.agregados if isinstance(o, CromoCable)]
    assert len(cables_agregados) == 1
    assert cables_agregados[0].extremo_a_n_id == 999999
    assert cables_agregados[0].extremo_b_n_id == 10444555  # sin alias, sin cambios


@pytest.mark.asyncio
async def test_procesar_cable_directo_anula_extremo_ignorar():
    obj = json.loads((FIXTURES_DIR / "cable_barrido_directo.json").read_text())
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    alias_por_origen = {10444555: AliasBotella(accion="ignorar", id_cromo_destino=None)}

    await ingesta._procesar_cable_directo(
        sesion, corrida_id=1, obj=obj, contadores=contadores, alias_por_origen=alias_por_origen
    )

    cables_agregados = [o for o in sesion.agregados if isinstance(o, CromoCable)]
    assert cables_agregados[0].extremo_a_n_id == 10178728  # sin alias, sin cambios
    assert cables_agregados[0].extremo_b_n_id is None


@pytest.mark.asyncio
async def test_procesar_cable_directo_sin_alias_no_cambia_extremos():
    """Regresión explícita: sin `alias_por_origen`, el comportamiento es idéntico al de antes."""
    obj = json.loads((FIXTURES_DIR / "cable_barrido_directo.json").read_text())
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_cable_directo(sesion, corrida_id=1, obj=obj, contadores=contadores)

    cables_agregados = [o for o in sesion.agregados if isinstance(o, CromoCable)]
    assert cables_agregados[0].extremo_a_n_id == 10178728
    assert cables_agregados[0].extremo_b_n_id == 10444555


@pytest.mark.asyncio
async def test_procesar_fusion_directa_remapea_botella_n_id_fusionar():
    obj = {"class": 132, "n_id": 90010, "parent": 10178728, "at": [{"seq": 1, "id": 84, "value": "53-17"}]}
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    alias_por_origen = {10178728: AliasBotella(accion="fusionar", id_cromo_destino=999999)}

    await ingesta._procesar_fusion_directa(
        sesion, corrida_id=1, obj=obj, contadores=contadores, alias_por_origen=alias_por_origen
    )

    fusiones_agregadas = [o for o in sesion.agregados if isinstance(o, CromoFusion)]
    assert len(fusiones_agregadas) == 1
    assert fusiones_agregadas[0].botella_n_id == 999999


@pytest.mark.asyncio
async def test_procesar_fusion_directa_anula_botella_n_id_ignorar():
    obj = {"class": 132, "n_id": 90020, "parent": 10178728, "at": [{"seq": 1, "id": 84, "value": "53-18"}]}
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    alias_por_origen = {10178728: AliasBotella(accion="ignorar", id_cromo_destino=None)}

    await ingesta._procesar_fusion_directa(
        sesion, corrida_id=1, obj=obj, contadores=contadores, alias_por_origen=alias_por_origen
    )

    fusiones_agregadas = [o for o in sesion.agregados if isinstance(o, CromoFusion)]
    assert len(fusiones_agregadas) == 1
    assert fusiones_agregadas[0].botella_n_id is None


@pytest.mark.asyncio
async def test_procesar_botella_completa_con_fixture_real():
    obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_botella_completa(
        _ClienteTopologiaFake(), sesion, corrida_id=1, obj=obj, contadores=contadores
    )

    assert contadores.errores == 0
    assert contadores.creadas >= 1  # la botella misma
    tipos_agregados = {type(o) for o in sesion.agregados}
    from db.models.cromo import CromoFusion  # noqa: F401 - CromoPelo/CromoTubo ya importados arriba

    assert CromoBotella in tipos_agregados
    assert CromoCable in tipos_agregados
    assert CromoTubo in tipos_agregados
    assert CromoPelo in tipos_agregados
    assert CromoFusion in tipos_agregados


@pytest.mark.asyncio
async def test_procesar_botella_completa_no_marca_relevado_si_el_payload_no_trajo_inner():
    """La marca es un hecho del payload, no del recorrido.

    `fase_botellas` barre con `show=["SHOW","REL_ATTRIBUTE","TIME"]`, y eso **no** trae `inner[]`
    (medido 2026-09-17 contra Cromo real: 0 de 10 botellas; sólo `show=["ALL"]` lo trae). Marcar
    igual equivale a afirmar "Cromo dice que esta botella no tiene splitters", que es justo lo que
    `empalmes.py` usa para apagar la heurística de fan-out en toda la botella.
    """
    obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    sin_arbol = {clave: valor for clave, valor in obj.items() if clave != "inner"}
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_botella_completa(
        _ClienteTopologiaFake(), sesion, corrida_id=1, obj=sin_arbol, contadores=contadores
    )

    botella = next(o for o in sesion.agregados if isinstance(o, CromoBotella))
    assert not botella.splitters_relevados


@pytest.mark.asyncio
async def test_procesar_botella_completa_marca_relevado_cuando_el_payload_trajo_el_arbol():
    """El contrapeso del test anterior: con `inner[]` presente la marca sí corresponde.

    El fixture tiene `inner` con una fusión y ningún splitter — y ese es exactamente el caso que la
    marca existe para representar: "se miró el árbol y no hay splitters acá".
    """
    obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    assert obj.get("inner"), "el fixture debe traer el arbol para que este test signifique algo"
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_botella_completa(
        _ClienteTopologiaFake(), sesion, corrida_id=1, obj=obj, contadores=contadores
    )

    botella = next(o for o in sesion.agregados if isinstance(o, CromoBotella))
    assert botella.splitters_relevados


@pytest.mark.asyncio
async def test_procesar_botella_completa_crea_copia_nombre_con_flag_false_por_defecto():
    obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_botella_completa(
        _ClienteTopologiaFake(), sesion, corrida_id=1, obj=obj, contadores=contadores
    )

    botella_creada = next(o for o in sesion.agregados if isinstance(o, CromoBotella))
    assert botella_creada.nombre == "Cra San Martin 201 Bot 2 CF"
    # nombre_editado_manual queda None hasta el flush real (el default de la columna se aplica en
    # el INSERT, no al instanciar en Python) — lo que importa es que no bloquea la copia de nombre.
    assert not botella_creada.nombre_editado_manual


@pytest.mark.asyncio
async def test_procesar_botella_completa_respeta_nombre_editado_manual():
    obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    existente = CromoBotella(
        n_id=10178728, version_id=1, vmax=1, nombre="Nombre corregido a mano", nombre_editado_manual=True
    )
    sesion = _SesionFake({(CromoBotella, 10178728): existente})
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_botella_completa(
        _ClienteTopologiaFake(), sesion, corrida_id=1, obj=obj, contadores=contadores
    )

    assert contadores.errores == 0
    assert existente.nombre == "Nombre corregido a mano"  # protegido: no lo pisa Cromo
    assert existente.vmax == 3  # el resto de los campos SÍ se actualiza normalmente


@pytest.mark.asyncio
async def test_procesar_botella_completa_actualiza_nombre_si_flag_false():
    obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    existente = CromoBotella(
        n_id=10178728, version_id=1, vmax=1, nombre="Nombre viejo de Cromo", nombre_editado_manual=False
    )
    sesion = _SesionFake({(CromoBotella, 10178728): existente})
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_botella_completa(
        _ClienteTopologiaFake(), sesion, corrida_id=1, obj=obj, contadores=contadores
    )

    assert contadores.errores == 0
    assert existente.nombre == "Cra San Martin 201 Bot 2 CF"  # regresión: sigue actualizándose


@pytest.mark.asyncio
async def test_procesar_botella_completa_alias_ignorar_omite_creacion_de_la_botella():
    obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    alias_por_origen = {10178728: AliasBotella(accion="ignorar", id_cromo_destino=None)}

    await ingesta._procesar_botella_completa(
        _ClienteTopologiaFake(),
        sesion,
        corrida_id=1,
        obj=obj,
        contadores=contadores,
        alias_por_origen=alias_por_origen,
    )

    assert contadores.errores == 0
    assert [o for o in sesion.agregados if isinstance(o, CromoBotella)] == []
    eventos = [o for o in sesion.agregados if getattr(o, "accion", None) == "ALIAS_IGNORADA"]
    assert len(eventos) == 1
    assert eventos[0].n_id == 10178728


@pytest.mark.asyncio
async def test_procesar_botella_completa_alias_fusionar_omite_creacion_y_registra_destino():
    obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    alias_por_origen = {10178728: AliasBotella(accion="fusionar", id_cromo_destino=999999)}

    await ingesta._procesar_botella_completa(
        _ClienteTopologiaFake(),
        sesion,
        corrida_id=1,
        obj=obj,
        contadores=contadores,
        alias_por_origen=alias_por_origen,
    )

    assert contadores.errores == 0
    assert [o for o in sesion.agregados if isinstance(o, CromoBotella)] == []
    eventos = [o for o in sesion.agregados if getattr(o, "accion", None) == "ALIAS_FUSIONADA"]
    assert len(eventos) == 1
    assert eventos[0].n_id == 10178728
    assert "999999" in eventos[0].detalle


@pytest.mark.asyncio
async def test_procesar_botella_completa_remapea_extremos_de_cable_embebido():
    """Fixture sintética: `botella_con_arbol.json` tiene un cable embebido sin `tp[]` propio (vista
    parcial real, ver docstring de `_upsert_versionado`), así que no sirve para probar el remapeo
    de extremos embebidos. Acá el cable embebido SÍ trae su propio `tp[]` con dos extremos."""
    obj = {
        "n_id": 5001,
        "vmax": 1,
        "class": 68,
        "name": "Botella Test",
        "tp": [
            {
                "type": 2,
                "nfrom": 0,
                "id_to": 5001,
                "nto": 1,
                "class": 51,
                "n_id": 6001,
                "vmax": 1,
                "name": "Cable embebido",
                "tp": [
                    {"type": 1, "nfrom": 0, "id_to": 5001, "nto": 0, "class": 68},
                    {"type": 1, "nfrom": 1, "id_to": 7001, "nto": 0, "class": 68},
                ],
            }
        ],
    }
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    alias_por_origen = {7001: AliasBotella(accion="fusionar", id_cromo_destino=9001)}

    await ingesta._procesar_botella_completa(
        _ClienteTopologiaFake(),
        sesion,
        corrida_id=1,
        obj=obj,
        contadores=contadores,
        alias_por_origen=alias_por_origen,
    )

    cables_agregados = [o for o in sesion.agregados if isinstance(o, CromoCable)]
    assert len(cables_agregados) == 1
    assert cables_agregados[0].extremo_a_n_id == 5001  # sin alias, sin cambios
    assert cables_agregados[0].extremo_b_n_id == 9001  # remapeado


# ── Detección dirigida de "ID dual" en la ingesta automática ────────────────


def _cascaron_sin_topologia(n_id: int = 5001) -> dict[str, Any]:
    """Objeto tal como llega del barrido bulk (`show=SHOW,REL_ATTRIBUTE,TIME`): sin `tp[]` ni
    `inner[]`, o sea sin cables ni fusiones — el patrón del placeholder "ID dual" real."""
    return {
        "n_id": n_id,
        "id": n_id,
        "vmax": 1,
        "class": 68,
        "name": "BOT interna Hotel Nuevo fondo Posadas 1557",
    }


def _cable_embebido(n_id: int, botella_n_id: int, otro_extremo: int) -> dict[str, Any]:
    return {
        "type": 2,
        "nfrom": 0,
        "id_to": botella_n_id,
        "nto": 1,
        "class": 51,
        "n_id": n_id,
        "vmax": 1,
        "name": "Cable del objeto vigente",
        "tp": [
            {"type": 1, "nfrom": 0, "id_to": botella_n_id, "nto": 0, "class": 68},
            {"type": 1, "nfrom": 1, "id_to": otro_extremo, "nto": 0, "class": 68},
        ],
    }


@pytest.mark.asyncio
async def test_procesar_botella_completa_omite_placeholder_si_hist_matchea_local_existente():
    """Caso raíz del bug: Cromo devuelve en el barrido un id nuevo y vacío que es otra versión del
    MISMO sitio físico ya ingerido bajo otro n_id. Antes se creaba un placeholder duplicado por
    corrida; ahora se omite y queda la traza `ID_DUAL_OMITIDA`."""
    obj = _cascaron_sin_topologia(5001)
    ya_local = CromoBotella(n_id=4444, version_id=4444, vmax=2, nombre="BOT interna Hotel Nuevo fondo Posadas 1557")
    sesion = _SesionFake(
        {(CromoBotella, 4444): ya_local},
        # La consulta de la cadena hist[] contra las filas locales vigentes.
        {"cromo_botellas.n_id IN": [(4444,)]},
    )
    contadores = ingesta.ContadoresCorrida()
    cliente = _ClienteTopologiaFake(
        {5001: {"n_id": 5001, "id": 5001, "class": 68, "hist": [{"id": 4444, "next_id": 5001}, {"id": 5001, "next_id": 0}]}}
    )

    await ingesta._procesar_botella_completa(cliente, sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert contadores.errores == 0
    assert [o for o in sesion.agregados if isinstance(o, CromoBotella)] == []  # no se crea el placeholder
    assert contadores.creadas == 0
    assert contadores.leidas == 1
    eventos = [o for o in sesion.agregados if getattr(o, "accion", None) == "ID_DUAL_OMITIDA"]
    assert len(eventos) == 1
    assert eventos[0].n_id == 5001
    assert "4444" in eventos[0].detalle
    assert cliente.pedidos == [5001]  # un único fetch extra, sólo para este candidato


@pytest.mark.asyncio
async def test_procesar_botella_completa_usa_objeto_vigente_de_la_cadena_en_vez_del_cascaron_vacio():
    """Si nadie de la cadena existe localmente todavía, se ingiere el objeto VIGENTE completo (con
    su árbol real), no el cascarón vacío que trajo el barrido."""
    obj = _cascaron_sin_topologia(5001)
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    cliente = _ClienteTopologiaFake(
        {
            5001: {
                "n_id": 5001,
                "id": 5001,
                "class": 68,
                "vmax": 1,
                "hist": [{"id": 5001, "next_id": 6001}, {"id": 6001, "next_id": 0}],
            },
            6001: {
                "n_id": 6001,
                "id": 6001,
                "class": 68,
                "vmax": 2,
                "name": "BOT interna Hotel Nuevo fondo Posadas 1557",
                "hist": [{"id": 5001, "next_id": 6001}, {"id": 6001, "next_id": 0}],
                "tp": [_cable_embebido(7001, botella_n_id=6001, otro_extremo=8001)],
            },
        }
    )

    await ingesta._procesar_botella_completa(cliente, sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert contadores.errores == 0
    botellas = [o for o in sesion.agregados if isinstance(o, CromoBotella)]
    assert [b.n_id for b in botellas] == [6001]  # el vigente, no el cascarón 5001
    assert botellas[0].vmax == 2
    # El árbol COMPLETO del vigente se procesa, no sólo su fila de botella.
    cables = [o for o in sesion.agregados if isinstance(o, CromoCable)]
    assert [c.n_id for c in cables] == [7001]
    assert {cables[0].extremo_a_n_id, cables[0].extremo_b_n_id} == {6001, 8001}
    assert cliente.pedidos == [5001, 6001]


@pytest.mark.asyncio
async def test_procesar_botella_completa_marca_relevado_segun_el_payload_del_arbol_procesado():
    """En la redirección por "ID dual" el árbol viene de OTRO payload que el del barrido.

    El cascarón no trae `inner[]`; el objeto vigente sí. Lo que se relevó es el árbol del vigente,
    así que la marca corresponde — consultar el cascarón daría la respuesta de un payload que no es
    el que se procesó. `inner: []` es deliberado: "vino el árbol y está vacío" es exactamente el
    caso que la marca existe para poder afirmar.
    """
    obj = _cascaron_sin_topologia(5001)
    assert "inner" not in obj, "el cascaron no debe traer arbol, si no el test no discrimina nada"
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    cliente = _ClienteTopologiaFake(
        {
            5001: {
                "n_id": 5001,
                "id": 5001,
                "class": 68,
                "vmax": 1,
                "hist": [{"id": 5001, "next_id": 6001}, {"id": 6001, "next_id": 0}],
            },
            6001: {
                "n_id": 6001,
                "id": 6001,
                "class": 68,
                "vmax": 2,
                "name": "BOT interna Hotel Nuevo fondo Posadas 1557",
                "hist": [{"id": 5001, "next_id": 6001}, {"id": 6001, "next_id": 0}],
                # `tp` es lo que marca a un objeto de la cadena como vigente
                # (`_resolver_posible_id_dual`), sin el la redireccion no dispara.
                "tp": [_cable_embebido(7001, botella_n_id=6001, otro_extremo=8001)],
                "inner": [],
            },
        }
    )

    await ingesta._procesar_botella_completa(cliente, sesion, corrida_id=1, obj=obj, contadores=contadores)

    botella = next(o for o in sesion.agregados if isinstance(o, CromoBotella))
    assert botella.n_id == 6001
    assert botella.splitters_relevados


def _cliente_cadena_5001_a_6001() -> _ClienteTopologiaFake:
    """Cadena mínima del fenómeno: el barrido trae el cascarón 5001, cuya `hist[]` lleva al objeto
    vigente 6001 (el que tiene `tp[]`, o sea topología real)."""
    return _ClienteTopologiaFake(
        {
            5001: {
                "n_id": 5001,
                "id": 5001,
                "class": 68,
                "vmax": 1,
                "hist": [{"id": 5001, "next_id": 6001}, {"id": 6001, "next_id": 0}],
            },
            6001: {
                "n_id": 6001,
                "id": 6001,
                "class": 68,
                "vmax": 2,
                "name": "BOT interna Hotel Nuevo fondo Posadas 1557",
                "hist": [{"id": 5001, "next_id": 6001}, {"id": 6001, "next_id": 0}],
                "tp": [_cable_embebido(7001, botella_n_id=6001, otro_extremo=8001)],
            },
        }
    )


@pytest.mark.asyncio
async def test_procesar_botella_completa_registra_id_dual_redirigida_con_origen_y_destino():
    """Traza auditable de la redirección: sin este evento el n_id del cascarón desaparece del
    histórico (el único evento sería el CREADA bajo el n_id vigente) y no habría forma de medir
    cuántas veces disparó esta rama tras una corrida masiva real."""
    obj = _cascaron_sin_topologia(5001)
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_botella_completa(
        _cliente_cadena_5001_a_6001(), sesion, corrida_id=1, obj=obj, contadores=contadores
    )

    assert contadores.errores == 0
    redirigidas = [o for o in sesion.agregados if getattr(o, "accion", None) == "ID_DUAL_REDIRIGIDA"]
    assert len(redirigidas) == 1
    assert redirigidas[0].n_id == 5001  # el cascarón que trajo el barrido, no el destino
    assert redirigidas[0].detalle == "destino_n_id=6001"
    assert redirigidas[0].clase == 68
    # La redirección NO reemplaza al evento normal: siguen siendo dos señales distintas.
    assert [o.n_id for o in sesion.agregados if getattr(o, "accion", None) == "CREADA"] == [6001, 7001]


@pytest.mark.parametrize(
    ("accion", "id_cromo_destino", "evento_alias", "extremo_esperado"),
    [("ignorar", None, "ALIAS_IGNORADA", None), ("fusionar", 9001, "ALIAS_FUSIONADA", 9001)],
)
@pytest.mark.asyncio
async def test_procesar_botella_completa_respeta_alias_del_n_id_vigente_tras_redirigir(
    accion, id_cromo_destino, evento_alias, extremo_esperado
):
    """El alias se evalúa primero sobre el n_id del cascarón; tras redirigir hay que volver a
    evaluarlo sobre el n_id VIGENTE. Caso real: `camara_botella_delete_service` elimina a mano una
    Botella (sólo permitido si no tiene cables/fusiones locales — el placeholder vacío que este
    fenómeno genera) y registra su n_id con accion='ignorar' "para que la ingesta no la resucite".
    Sin esta re-evaluación, la redirección la volvía a crear, ahora con sus cables.

    Mismo criterio que el camino de alias original: se saltea sólo el upsert de la fila
    `CromoBotella`; el resto del árbol (cables/fusiones/tubos/pelos) SÍ se procesa, con las
    referencias al n_id aliaseado ya redirigidas por `alias_service.resolver_referencia`.
    """
    obj = _cascaron_sin_topologia(5001)
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    alias_por_origen = {6001: AliasBotella(accion=accion, id_cromo_destino=id_cromo_destino)}

    await ingesta._procesar_botella_completa(
        _cliente_cadena_5001_a_6001(),
        sesion,
        corrida_id=1,
        obj=obj,
        contadores=contadores,
        alias_por_origen=alias_por_origen,
    )

    assert contadores.errores == 0
    # Ni la fila del vigente (aliaseado) ni la del cascarón: no se resucita nada.
    assert [o for o in sesion.agregados if isinstance(o, CromoBotella)] == []
    eventos_alias = [o for o in sesion.agregados if getattr(o, "accion", None) == evento_alias]
    assert len(eventos_alias) == 1
    assert eventos_alias[0].n_id == 6001
    # Las dos señales conviven: la redirección queda registrada igual.
    redirigidas = [o for o in sesion.agregados if getattr(o, "accion", None) == "ID_DUAL_REDIRIGIDA"]
    assert len(redirigidas) == 1
    assert redirigidas[0].n_id == 5001
    assert redirigidas[0].detalle == "destino_n_id=6001"
    # El árbol del vigente sí se procesa, con el extremo aliaseado resuelto.
    cables = [o for o in sesion.agregados if isinstance(o, CromoCable)]
    assert [c.n_id for c in cables] == [7001]
    assert {cables[0].extremo_a_n_id, cables[0].extremo_b_n_id} == {extremo_esperado, 8001}


@pytest.mark.asyncio
async def test_procesar_botella_completa_no_hace_request_extra_si_ya_tiene_cables():
    """REGRESIÓN DE COSTO: una botella con topología en el snapshot no es candidata — cero fetches
    extra sobre las ~11k del barrido completo."""
    obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    cliente = _ClienteTopologiaFake()

    await ingesta._procesar_botella_completa(cliente, sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert cliente.pedidos == []
    assert contadores.errores == 0
    assert contadores.creadas >= 1


@pytest.mark.asyncio
async def test_procesar_botella_completa_no_hace_request_extra_si_ya_existe_localmente():
    """REGRESIÓN DE COSTO: una botella que ya tiene fila local propia tampoco es candidata, aunque
    llegue vacía en este snapshot."""
    obj = _cascaron_sin_topologia(5001)
    existente = CromoBotella(n_id=5001, version_id=5001, vmax=1, nombre="Ya ingerida")
    sesion = _SesionFake({(CromoBotella, 5001): existente})
    contadores = ingesta.ContadoresCorrida()
    cliente = _ClienteTopologiaFake()

    await ingesta._procesar_botella_completa(cliente, sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert cliente.pedidos == []
    assert contadores.errores == 0
    assert contadores.sin_cambios == 1


@pytest.mark.asyncio
async def test_procesar_botella_completa_ignora_deteccion_id_dual_cuando_hay_alias():
    """Ruling del diseño: con un alias manual cargado (`app.cromo_botella_alias`), ESE mecanismo ya
    resuelve el caso — la detección automática nunca corre y no se gasta el fetch extra."""
    obj = _cascaron_sin_topologia(5001)
    sesion = _SesionFake({}, {"cromo_botellas.n_id IN": [(4444,)]})
    contadores = ingesta.ContadoresCorrida()
    # El cliente TIENE cargado el caso: si la detección corriera, encontraría la cadena.
    cliente = _ClienteTopologiaFake(
        {5001: {"n_id": 5001, "id": 5001, "class": 68, "hist": [{"id": 4444, "next_id": 5001}, {"id": 5001, "next_id": 0}]}}
    )
    alias_por_origen = {5001: AliasBotella(accion="ignorar", id_cromo_destino=None)}

    await ingesta._procesar_botella_completa(
        cliente, sesion, corrida_id=1, obj=obj, contadores=contadores, alias_por_origen=alias_por_origen
    )

    assert cliente.pedidos == []  # la detección automática nunca corrió
    assert contadores.errores == 0
    assert [o for o in sesion.agregados if isinstance(o, CromoBotella)] == []
    acciones = [getattr(o, "accion", None) for o in sesion.agregados]
    assert "ALIAS_IGNORADA" in acciones  # el camino de alias sigue intacto
    assert "ID_DUAL_OMITIDA" not in acciones


@pytest.mark.asyncio
async def test_fase_cables_procesa_todas_las_paginas_y_commitea_cada_una():
    cable_obj = json.loads((FIXTURES_DIR / "cable_barrido_directo.json").read_text())
    cliente = _ClientePaginado(
        [
            {"response": [cable_obj]},
            {"response": []},
        ]
    )
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    await ingesta.fase_cables(cliente, sesion, corrida, contadores, psize=5, max_paginas=None)

    assert contadores.leidas == 1
    assert corrida.creadas == 1


@pytest.mark.asyncio
async def test_fase_botellas_procesa_pagina_de_botellas():
    botella_obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    cliente = _ClientePaginado([{"response": [botella_obj]}])
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    await ingesta.fase_botellas(
        cliente, sesion, corrida, contadores, psize=5, max_paginas=None, clases=ingesta.CLASES_BOTELLA
    )

    assert contadores.errores == 0
    assert corrida.creadas >= 1


@pytest.mark.asyncio
async def test_fase_fusiones_procesa_pagina_y_suma_leidas():
    """Etapa 8: fusiones vía barrido directo (filter=132) — hallazgo real, no llegan embebidas en
    botella.inner[] en un barrido paginado real. Sin vmax propio: no suman creadas/actualizadas
    (mismo criterio que tubo/pelo), pero sí `leidas` porque ahora es una colección contada."""
    fusion_obj = json.loads((FIXTURES_DIR / "fusion_barrido_directo.json").read_text())
    cliente = _ClientePaginado([{"response": [fusion_obj]}, {"response": []}])
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    await ingesta.fase_fusiones(cliente, sesion, corrida, contadores, psize=5, max_paginas=None)

    assert contadores.leidas == 1
    assert contadores.errores == 0
    # Sin evento individual (igual que tubo/pelo) — sólo el evento FASE de inicio + PAGINA.
    acciones = [getattr(o, "accion", None) for o in sesion.agregados]
    assert "REF_COLGADA" not in acciones
    assert "ERROR" not in acciones


@pytest.mark.asyncio
async def test_fase_cables_pasa_alias_por_origen_a_procesar_cable_directo(monkeypatch):
    cable_obj = json.loads((FIXTURES_DIR / "cable_barrido_directo.json").read_text())
    cliente = _ClientePaginado([{"response": [cable_obj]}])
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)
    alias_por_origen = {10178728: AliasBotella(accion="fusionar", id_cromo_destino=999999)}
    recibido: dict[str, Any] = {}

    async def _procesar_fake(sesion, corrida_id, obj, contadores, *, alias_por_origen=None):
        recibido["alias_por_origen"] = alias_por_origen

    monkeypatch.setattr(ingesta, "_procesar_cable_directo", _procesar_fake)

    await ingesta.fase_cables(
        cliente, sesion, corrida, contadores, psize=5, max_paginas=None, alias_por_origen=alias_por_origen
    )

    assert recibido["alias_por_origen"] is alias_por_origen


@pytest.mark.asyncio
async def test_fase_botellas_pasa_alias_por_origen_a_procesar_botella_completa(monkeypatch):
    botella_obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    cliente = _ClientePaginado([{"response": [botella_obj]}])
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)
    alias_por_origen = {10178728: AliasBotella(accion="ignorar", id_cromo_destino=None)}
    recibido: dict[str, Any] = {}

    async def _procesar_fake(cliente, sesion, corrida_id, obj, contadores, *, alias_por_origen=None):
        recibido["cliente"] = cliente
        recibido["alias_por_origen"] = alias_por_origen

    monkeypatch.setattr(ingesta, "_procesar_botella_completa", _procesar_fake)

    await ingesta.fase_botellas(
        cliente,
        sesion,
        corrida,
        contadores,
        psize=5,
        max_paginas=None,
        clases=ingesta.CLASES_BOTELLA,
        alias_por_origen=alias_por_origen,
    )

    assert recibido["alias_por_origen"] is alias_por_origen
    # `cliente` enhebrado hasta el procesamiento de cada objeto (detección dirigida de "ID dual").
    assert recibido["cliente"] is cliente


@pytest.mark.asyncio
async def test_fase_fusiones_pasa_alias_por_origen_a_procesar_fusion_directa(monkeypatch):
    fusion_obj = json.loads((FIXTURES_DIR / "fusion_barrido_directo.json").read_text())
    cliente = _ClientePaginado([{"response": [fusion_obj]}])
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)
    alias_por_origen = {10178728: AliasBotella(accion="fusionar", id_cromo_destino=999999)}
    recibido: dict[str, Any] = {}

    async def _procesar_fake(sesion, corrida_id, obj, contadores, *, alias_por_origen=None):
        recibido["alias_por_origen"] = alias_por_origen

    monkeypatch.setattr(ingesta, "_procesar_fusion_directa", _procesar_fake)

    await ingesta.fase_fusiones(
        cliente, sesion, corrida, contadores, psize=5, max_paginas=None, alias_por_origen=alias_por_origen
    )

    assert recibido["alias_por_origen"] is alias_por_origen


# ── Reconciliación ───────────────────────────────────────────────────────────


def test_reconciliacion_fusion_sin_botella_excluye_null_explicitamente():
    """Hallazgo real (Etapa 8): las fusiones del barrido directo no traen `parent`, así que
    `botella_n_id` queda NULL de forma estructural, no como referencia colgada — la consulta debe
    excluir NULL explícitamente o marcaría cada fusión directa como colgada."""
    sql_fusion = next(sql for descripcion, _clase, sql in ingesta._RECONCILIACIONES if "fusión" in descripcion)
    assert "botella_n_id IS NOT NULL" in sql_fusion


@pytest.mark.asyncio
async def test_fase_reconciliacion_reporta_refs_colgadas_agregadas():
    sesion = _SesionFake(
        respuestas_execute={
            "extremo_a_n_id IS NOT NULL": [(111,), (222,)],
            "cromo_tubos t\n        WHERE NOT EXISTS": [(333,)],
        }
    )
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    await ingesta.fase_reconciliacion(sesion, corrida, contadores)

    assert contadores.refs_colgadas == 3  # 2 extremo_a + 1 tubo sin cable
    eventos = [o for o in sesion.agregados if getattr(o, "accion", None) == "REF_COLGADA"]
    assert len(eventos) == 2  # un evento agregado por relación con hallazgos, no uno por fila


@pytest.mark.asyncio
async def test_fase_reconciliacion_sin_hallazgos_no_registra_eventos():
    sesion = _SesionFake()  # ninguna respuesta configurada -> todas las consultas devuelven []
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    await ingesta.fase_reconciliacion(sesion, corrida, contadores)

    assert contadores.refs_colgadas == 0
    # Se registra el evento FASE de inicio, pero ningún REF_COLGADA (no hubo hallazgos).
    assert [o.accion for o in sesion.agregados] == ["FASE"]


# ── Matching de servicios ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fase_servicios_matchea_y_deja_traza_de_no_matcheados():
    # "99" (2 dígitos) es implausible a propósito (fuera de LONGITUD_SERVICIO_PLAUSIBLE=4-6) — sigue
    # probando "no matchea, no se crea ningún placeholder". Antes de la heurística (2026-08-14) acá
    # había un número de 6 dígitos ("999999"), que con la heurística nueva sí dispararía un intento
    # de creación — cambiado para no confundir dos comportamientos distintos en el mismo test.
    sesion = _SesionFake(
        respuestas_execute={
            "cromo_servicio_match m": [(10, "114699"), (11, "99")],
            "servicio_id = :numero": [],  # default: sin match: se sobreescribe por caso abajo
        }
    )

    # El fake resuelve por substring; para diferenciar el pelo que matchea, usamos un execute custom.
    llamadas = {"n": 0}
    intentos_insert = {"n": 0}
    original_execute = sesion.execute

    async def execute_custom(stmt, params=None):
        texto = str(stmt)
        if "INSERT INTO app.servicios" in texto:
            intentos_insert["n"] += 1
            return _ResultadoFilas([])
        if "servicio_id = :numero" in texto:
            llamadas["n"] += 1
            if params and params.get("numero") == "114699":
                return _ResultadoFilas([(1429,)])
            return _ResultadoFilas([])
        return await original_execute(stmt, params)

    sesion.execute = execute_custom
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    await ingesta.fase_servicios(sesion, corrida, contadores)

    from db.models.cromo import CromoServicioMatch

    matches = [o for o in sesion.agregados if isinstance(o, CromoServicioMatch)]
    assert len(matches) == 2
    matcheado = next(m for m in matches if m.servicio_numero == "114699")
    sin_match = next(m for m in matches if m.servicio_numero == "99")
    assert matcheado.servicio_id == 1429
    assert matcheado.confianza == 100
    assert sin_match.servicio_id is None
    assert sin_match.confianza == 0
    # "99" es implausible (2 dígitos, fuera de 4-6): nunca debe intentar el INSERT de placeholder.
    assert intentos_insert["n"] == 0


@pytest.mark.asyncio
async def test_fase_servicios_crea_placeholder_para_numero_plausible_sin_match():
    """Número de 5 dígitos ("84213") sin match real → crea un Servicio placeholder y el
    CromoServicioMatch queda apuntando a él, con confianza=100 (matcheó, aunque contra algo recién
    creado) — y se registra un evento PLACEHOLDER_CREADO."""
    sesion = _SesionFake(
        respuestas_execute={
            "cromo_servicio_match m": [(20, "84213")],
        }
    )
    original_execute = sesion.execute

    async def execute_custom(stmt, params=None):
        texto = str(stmt)
        if "INSERT INTO app.servicios" in texto:
            return _ResultadoFilas([(555,)])
        if "servicio_id = :numero" in texto:
            return _ResultadoFilas([])  # nunca hay un Servicio real con ese número
        return await original_execute(stmt, params)

    sesion.execute = execute_custom
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    await ingesta.fase_servicios(sesion, corrida, contadores)

    from db.models.cromo import CromoIngestaEvento, CromoServicioMatch

    matches = [o for o in sesion.agregados if isinstance(o, CromoServicioMatch)]
    assert len(matches) == 1
    assert matches[0].servicio_id == 555
    assert matches[0].confianza == 100

    eventos_placeholder = [
        o for o in sesion.agregados if isinstance(o, CromoIngestaEvento) and o.accion == "PLACEHOLDER_CREADO"
    ]
    assert len(eventos_placeholder) == 1
    assert "84213" in eventos_placeholder[0].detalle
    assert "555" in eventos_placeholder[0].detalle


@pytest.mark.asyncio
async def test_fase_servicios_cache_evita_recrear_placeholder_para_numero_repetido():
    """Dos pelos distintos con el MISMO número plausible sin match → sólo UN intento de INSERT
    (cache en memoria de la corrida) — evita crear el mismo placeholder cientos de veces cuando un
    número se repite en muchos pelos, hallazgo real documentado en fase_servicios."""
    sesion = _SesionFake(
        respuestas_execute={
            "cromo_servicio_match m": [(30, "77123"), (31, "77123")],
        }
    )
    original_execute = sesion.execute
    intentos_insert = {"n": 0}

    async def execute_custom(stmt, params=None):
        texto = str(stmt)
        if "INSERT INTO app.servicios" in texto:
            intentos_insert["n"] += 1
            return _ResultadoFilas([(777,)])
        if "servicio_id = :numero" in texto:
            return _ResultadoFilas([])
        return await original_execute(stmt, params)

    sesion.execute = execute_custom
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    await ingesta.fase_servicios(sesion, corrida, contadores)

    from db.models.cromo import CromoServicioMatch

    matches = [o for o in sesion.agregados if isinstance(o, CromoServicioMatch)]
    assert len(matches) == 2
    assert all(m.servicio_id == 777 for m in matches)
    assert intentos_insert["n"] == 1


# ── Cables de terceros: clases 52, 59 (Telefónica) y 60 (Telecom) (2026-09-29) ──


def _cable_tercero_obj(clase: int = 60) -> dict:
    """Forma liviana real del barrido con `show=ALL` (F-TECO-DC1, 2026-09-29): el `inner[]` trae
    tubos y pelos embebidos, y el pelo trae at.61 con la descripción del servicio."""
    obj = json.loads((FIXTURES_DIR / "cable_barrido_directo.json").read_text())
    obj["class"] = clase
    obj["inner"] = [
        {"id": 7968009, "class": 129, "name": "AZ", "parent": obj.get("n_id") or obj["id"],
         "at": [{"id": 72, "value": "1"}, {"id": 73, "value": "AZ"}]},
        {"id": 7968010, "class": 130, "name": "1", "parent": 7968009,
         "at": [{"id": 74, "value": "0"}, {"id": 75, "value": "1"}, {"id": 77, "value": "AZ"},
                {"id": 61, "value": "FO 42351- 42352 - ODF Catolica 1324 CF - g"}]},
    ]
    return obj


def test_clases_de_cable_de_terceros():
    assert ingesta.CLASES_CABLE_TERCEROS == (52, 59, 60)


@pytest.mark.asyncio
async def test_procesar_cable_tercero_guarda_cable_tubos_y_pelos():
    """A diferencia de la clase 51 —cuyos pelos llegan por el árbol de su botella—, un cable de
    tercero suele ir cámara↔ODF u ODF↔ODF: si esta fase no guarda sus pelos, nadie lo hace."""
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_cable_tercero_directo(
        sesion, corrida_id=1, obj=_cable_tercero_obj(60), contadores=contadores
    )

    assert contadores.errores == 0
    assert contadores.creadas == 1
    cable = next(o for o in sesion.agregados if isinstance(o, CromoCable))
    assert cable.clase == 60
    tubos = [o for o in sesion.agregados if isinstance(o, CromoTubo)]
    pelos = [o for o in sesion.agregados if isinstance(o, CromoPelo)]
    assert [t.n_id for t in tubos] == [7968009]
    assert [p.n_id for p in pelos] == [7968010]
    assert pelos[0].cable_n_id == cable.n_id
    assert pelos[0].servicio_numero == "42351"


@pytest.mark.asyncio
async def test_procesar_cable_tercero_actualiza_pelo_existente_via_precarga_sin_get_por_objeto():
    """Precarga por lote (2026-10-26): el pelo que ya existe se actualiza en su fila, no se agrega
    otra, y ni tubos ni pelos cuestan un `sesion.get()` cada uno."""
    pelo_existente = CromoPelo(n_id=7968010, tubo_n_id=7968009, cable_n_id=1, numero_pelo="1")
    sesion = _SesionFake({(CromoPelo, 7968010): pelo_existente})
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_cable_tercero_directo(
        sesion, corrida_id=1, obj=_cable_tercero_obj(60), contadores=contadores
    )

    assert contadores.errores == 0
    assert not any(isinstance(o, CromoPelo) for o in sesion.agregados)
    assert pelo_existente.servicio_numero == "42351"
    assert pelo_existente.ultima_ingesta is not None
    assert sesion.precargas == 2  # una para tubos, otra para pelos
    assert sesion.gets == 2  # sólo el cable (upsert_versionado) y `_reactivar_si_estaba_de_baja`


@pytest.mark.asyncio
async def test_precargar_por_n_id_descarta_nulos_y_parte_en_lotes(monkeypatch):
    monkeypatch.setattr(ingesta, "_LOTE_PRECARGA", 2)
    tubos = {n: CromoTubo(n_id=n) for n in (1, 2, 3)}
    sesion = _SesionFake({(CromoTubo, n): t for n, t in tubos.items()})

    encontrados = await ingesta.precargar_por_n_id(sesion, CromoTubo, [3, None, 1, 2, 2, 99])

    assert encontrados == tubos
    assert sesion.precargas == 2  # [1, 2, 3, 99] en lotes de 2


@pytest.mark.asyncio
async def test_upsert_simple_con_precargados_registra_la_fila_creada():
    """Un segundo arribo del mismo n_id dentro del lote encuentra la fila recién creada, igual que
    `sesion.get()` la encontraba en el identity map."""
    sesion = _SesionFake()
    precargados: dict = {}

    @dataclass(slots=True)
    class _TuboFake:
        n_id: int
        cable_n_id: int = 1
        orden: Optional[int] = None
        nombre_color: Optional[str] = None

    campos = ingesta.TUBO_CAMPOS
    await ingesta.upsert_simple(sesion, CromoTubo, _TuboFake(n_id=5, orden=1), campos, precargados=precargados)
    await ingesta.upsert_simple(sesion, CromoTubo, _TuboFake(n_id=5, orden=2), campos, precargados=precargados)

    assert len(sesion.agregados) == 1
    assert precargados[5] is sesion.agregados[0]
    assert sesion.agregados[0].orden == 2
    assert sesion.gets == 0


@pytest.mark.asyncio
async def test_procesar_cable_tercero_malformado_no_rompe_registra_error():
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    sesion._existentes[(CromoCable, 1)] = object()  # sin .vmax -> error real al comparar

    await ingesta._procesar_cable_tercero_directo(
        sesion, corrida_id=1, obj={"class": 60, "id": 1, "n_id": 1}, contadores=contadores
    )

    assert contadores.errores == 1
    assert contadores.creadas == 0


@pytest.mark.asyncio
async def test_modo_solo_cables_terceros_corre_su_fase_y_el_matching_de_servicios(monkeypatch):
    """Excepción deliberada al contrato "un modo acotado corre sólo su fase": sin `fase_servicios`
    los pelos nuevos quedan sin vincular a ningún Servicio y no sirven de semilla para `track`."""
    sesion = _SesionFakeCorrida()
    sesion._existentes[(CromoIngestaCorrida, 42)] = CromoIngestaCorrida(
        id=42, usuario="tester", estado="EN_CURSO"
    )
    llamadas: list[str] = []

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {}

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    _spies_de_fases(monkeypatch, llamadas)

    corrida = await ingesta.continuar_corrida(
        cliente=object(),
        sesion=sesion,
        corrida_id=42,
        psize=5,
        max_paginas=None,
        clases=ingesta.CLASES_BOTELLA,
        modo="SOLO_CABLES_TERCEROS",
    )

    assert corrida.estado == "OK"
    assert llamadas == ["fase_cables_terceros", "fase_servicios"]
    assert ingesta.MODOS_ACOTADOS["SOLO_CABLES_TERCEROS"].clases_objetivo == (52, 59, 60)


@pytest.mark.asyncio
async def test_resolver_servicio_conectores_prefiere_el_pelo_del_cable_propio():
    """Con los cables de terceros ingeridos, los DOS pelos de la posición existen. Caso real TASA
    conector 2: 7968239 (F-CRZ-FB, Telefónica, clase 59) y 6976963 (F-MDO-ILC, propio). La
    posición de ODF del Servicio es la del cable propio, aunque venga segundo en `tp[]`."""
    conector = ConectorOdf(
        n_id=8595049, odf_n_id=6644198, bandeja_n_id=None, bandeja_nombre=None, bandeja_modelo=None,
        numero_conector="2", pelo_n_id=7968239, servicio_numero_atributo="42351",
        pelos_candidatos=[7968239, 6976963],
    )
    sesion = _SesionFake(
        respuestas_execute={"FROM app.cromo_pelos": [(7968239, "42351", 59), (6976963, "42351", 51)]}
    )

    await ingesta.resolver_servicio_conectores(sesion, [conector])

    assert conector.pelo_n_id == 6976963
