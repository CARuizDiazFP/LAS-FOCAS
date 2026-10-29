# Nombre de archivo: test_cromo_ingesta.py
# Ubicación de archivo: tests/test_cromo_ingesta.py
# Descripción: Pruebas del servicio de ingesta Cromo (clasificación por vmax, orquestación, modos) sin red ni DB real; objetos y ODF en test_cromo_ingesta_objetos.py y test_cromo_ingesta_odf.py

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from core.services.cromo import ingesta
from core.services.cromo.alias_service import AliasBotella
from db.models.cromo import (
    CromoBotella,
    CromoCable,
    CromoIngestaCorrida,
)
from tests.soporte_cromo_ingesta import (
    FIXTURES_DIR,
    _ClientePaginado,
    _SesionFake,
    _SesionFakeCorrida,
    _spies_de_fases,
)
from tests.soporte_cromo_ingesta import geometria_fo  # noqa: F401 - fixture


async def _fase_noop(*_args, **_kwargs) -> None:
    """Fase que no hace nada, para los tests de orquestación que no la ejercitan."""


@dataclass(slots=True)
class _BotellaDominioFake:
    n_id: int
    version_id: int
    vmax: int
    clase: int = 68
    nombre: Optional[str] = None
    codigo_modelo: Optional[str] = None
    id_legacy: Optional[str] = None
    notas: Optional[str] = None
    calle: Optional[str] = None
    altura: Optional[str] = None
    localidad: Optional[str] = None
    provincia: Optional[str] = None
    ubicacion_fisica: Optional[str] = None
    tendido: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    pts_raw: Optional[list] = None
    payload_raw: Optional[dict] = None


def _botella(n_id=1, version_id=1, vmax=1, **kwargs) -> _BotellaDominioFake:
    kwargs.setdefault("payload_raw", {})
    return _BotellaDominioFake(n_id=n_id, version_id=version_id, vmax=vmax, **kwargs)


# ── Clasificación por vmax (CREADA / ACTUALIZADA / SIN_CAMBIOS) ─────────────


@pytest.mark.asyncio
async def test_upsert_versionado_crea_si_no_existe():
    sesion = _SesionFake()
    accion = await ingesta.upsert_versionado(sesion, CromoBotella, _botella(n_id=10, vmax=1), ingesta.BOTELLA_CAMPOS)

    assert accion == "CREADA"
    assert len(sesion.agregados) == 1
    assert sesion.agregados[0].n_id == 10
    assert sesion.agregados[0].vmax == 1


@pytest.mark.asyncio
async def test_upsert_versionado_sin_cambios_no_toca_campos():
    existente = CromoBotella(n_id=10, version_id=1, vmax=5, nombre="Nombre original")
    sesion = _SesionFake({(CromoBotella, 10): existente})

    # Llega una vista parcial (nombre=None) con el mismo vmax: no debe pisar el nombre ya cargado.
    accion = await ingesta.upsert_versionado(
        sesion, CromoBotella, _botella(n_id=10, version_id=1, vmax=5, nombre=None), ingesta.BOTELLA_CAMPOS
    )

    assert accion == "SIN_CAMBIOS"
    assert existente.nombre == "Nombre original"
    assert sesion.agregados == []


@pytest.mark.asyncio
async def test_registrar_evento_omite_sin_cambios_y_conserva_el_resto():
    """Decisión 2026-10-27: `SIN_CAMBIOS` no genera evento (era el 79 % de una corrida COMPLETA);
    el total sigue en `CromoIngestaCorrida.sin_cambios`. El resto se registra igual."""
    sesion = _SesionFake()

    for accion in ("SIN_CAMBIOS", "CREADA", "ACTUALIZADA", "OMITIDA", "ERROR", "REF_COLGADA"):
        await ingesta.registrar_evento(sesion, 1, 10, 51, accion)

    assert [e.accion for e in sesion.agregados] == ["CREADA", "ACTUALIZADA", "OMITIDA", "ERROR", "REF_COLGADA"]


@pytest.mark.asyncio
async def test_upsert_versionado_actualizada_pisa_campos_y_marca_modificacion():
    # "nombre" ya no está en BOTELLA_CAMPOS (ver comentario ahí) — lo protege
    # _procesar_botella_completa, no este helper genérico. Este test verifica el resto de los
    # campos de BOTELLA_CAMPOS (ej. version_id), no nombre.
    existente = CromoBotella(n_id=10, version_id=1, vmax=5, nombre="Viejo")
    sesion = _SesionFake({(CromoBotella, 10): existente})

    accion = await ingesta.upsert_versionado(
        sesion, CromoBotella, _botella(n_id=10, version_id=2, vmax=6, nombre="Nuevo"), ingesta.BOTELLA_CAMPOS
    )

    assert accion == "ACTUALIZADA"
    assert existente.nombre == "Viejo"  # no tocado por upsert_versionado: no está en BOTELLA_CAMPOS
    assert existente.version_id == 2
    assert existente.vmax == 6
    assert existente.ultima_modificacion is not None


@pytest.mark.asyncio
async def test_upsert_versionado_funciona_igual_para_cable():
    sesion = _SesionFake()

    @dataclass(slots=True)
    class _CableFake:
        n_id: int
        version_id: int
        vmax: int
        clase: Optional[int] = None
        nombre: Optional[str] = None
        capacidad: Optional[str] = None
        capacidad_pelos: Optional[int] = None
        propietario: Optional[str] = None
        jerarquia: Optional[str] = None
        tendido: Optional[str] = None
        distancia_geo: Optional[float] = None
        distancia_real: Optional[float] = None
        id_legacy: Optional[str] = None
        notas: Optional[str] = None
        extremo_a_n_id: Optional[int] = None
        extremo_a_clase: Optional[int] = None
        extremo_a_legacy: Optional[str] = None
        extremo_a_nombre: Optional[str] = None
        extremo_b_n_id: Optional[int] = None
        extremo_b_clase: Optional[int] = None
        extremo_b_legacy: Optional[str] = None
        extremo_b_nombre: Optional[str] = None
        pts_raw: Optional[list] = None
        payload_raw: Optional[dict] = None

    accion = await ingesta.upsert_versionado(
        sesion, CromoCable, _CableFake(n_id=50, version_id=1, vmax=1, payload_raw={}), ingesta.CABLE_CAMPOS
    )

    assert accion == "CREADA"
    assert sesion.agregados[0].n_id == 50
    # CromoCable no tiene ultima_modificacion: no debe reventar por el hasattr guard.
    assert not hasattr(sesion.agregados[0], "ultima_modificacion") or sesion.agregados[0].ultima_modificacion is None


# ── Contadores ───────────────────────────────────────────────────────────────


def test_contadores_corrida_cuenta_cada_accion():
    contadores = ingesta.ContadoresCorrida()
    contadores.contar("CREADA")
    contadores.contar("ACTUALIZADA")
    contadores.contar("ACTUALIZADA")
    contadores.contar("SIN_CAMBIOS")
    contadores.contar("ERROR")  # no es una de las 3 clasificadas: no debe incrementar nada silenciosamente mal

    assert contadores.creadas == 1
    assert contadores.actualizadas == 2
    assert contadores.sin_cambios == 1


# ── Fase de conteo (sólo cliente mockeado, sin DB) ──────────────────────────


class _ClienteFakeConteo:
    def __init__(self, stats_por_clase: dict[int, int]) -> None:
        self._stats = stats_por_clase

    async def get_coleccion(self, filtro: str, *, psize=None, show=None, next_cursor=None):
        clase = int(filtro)
        if clase not in self._stats:
            return {"stats": [], "response": []}
        return {"stats": [{"id": clase, "count": self._stats[clase]}], "response": []}


@pytest.mark.asyncio
async def test_fase_conteo_arma_diccionario_por_clase():
    cliente = _ClienteFakeConteo({68: 100, 121: 5, 51: 200})
    totales = await ingesta.fase_conteo(cliente)

    assert totales == {68: 100, 121: 5, 51: 200}
    # Clases sin stats (122, 123, 125) simplemente no aparecen, no rompen.
    assert 122 not in totales


@pytest.mark.asyncio
async def test_fase_conteo_cae_al_catalogo_cuando_stats_miente_con_cero():
    """`stats[].count` devuelve 0 para las clases 133 y 134 aunque la colección pagine perfecto.

    Medido 2026-09-19: los totales reales son 20.238 splitters y 154.284 puertos. Sin este
    fallback, `total_objetivo` de una corrida de splitters queda en 0 y la barra de progreso no
    significa nada.
    """
    cliente = _ClienteFakeConteo({133: 0, 134: 0})
    sesion = _SesionFake(
        respuestas_execute={"FROM app.cromo_clases": [(133, 20238), (134, 154284)]}
    )

    totales = await ingesta.fase_conteo(cliente, sesion=sesion, clases=(133, 134))

    assert totales == {133: 20238, 134: 154284}


@pytest.mark.asyncio
async def test_fase_conteo_prefiere_la_api_sobre_el_catalogo():
    """El catálogo es una foto con fecha; la API es el presente. Sólo manda cuando la API dice 0."""
    cliente = _ClienteFakeConteo({69: 7955})
    sesion = _SesionFake(respuestas_execute={"FROM app.cromo_clases": [(69, 1)]})

    totales = await ingesta.fase_conteo(cliente, sesion=sesion, clases=(69,))

    assert totales == {69: 7955}


@pytest.mark.asyncio
async def test_fase_conteo_sin_sesion_se_comporta_como_siempre():
    """Los llamadores viejos no pasan sesión: no pueden empezar a fallar por esto."""
    cliente = _ClienteFakeConteo({133: 0})

    totales = await ingesta.fase_conteo(cliente, clases=(133,))

    assert totales == {133: 0}


@pytest.mark.asyncio
async def test_ejecutar_ingesta_cierra_ok_sin_errores(monkeypatch):
    sesion = _SesionFakeCorrida()

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {68: 1, 51: 1}

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _noop)
    monkeypatch.setattr(ingesta, "fase_cables_terceros", _fase_noop)
    monkeypatch.setattr(ingesta, "fase_botellas", _noop)
    monkeypatch.setattr(ingesta, "fase_fusiones", _noop)
    monkeypatch.setattr(ingesta, "fase_odfs", _noop)
    monkeypatch.setattr(ingesta, "fase_reconciliacion", _noop)
    monkeypatch.setattr(ingesta, "fase_servicios", _noop)

    corrida = await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=5)

    assert corrida.estado == "OK"
    assert corrida.finalizada_at is not None


@pytest.mark.asyncio
async def test_ejecutar_ingesta_marca_ok_con_errores_si_hubo_errores(monkeypatch):
    sesion = _SesionFakeCorrida()

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {}

    async def _fase_botellas_con_error(cliente, sesion, corrida, contadores, **kwargs):
        contadores.errores += 1

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _noop)
    monkeypatch.setattr(ingesta, "fase_cables_terceros", _fase_noop)
    monkeypatch.setattr(ingesta, "fase_botellas", _fase_botellas_con_error)
    monkeypatch.setattr(ingesta, "fase_fusiones", _noop)
    monkeypatch.setattr(ingesta, "fase_odfs", _noop)
    monkeypatch.setattr(ingesta, "fase_reconciliacion", _noop)
    monkeypatch.setattr(ingesta, "fase_servicios", _noop)

    corrida = await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=5)

    assert corrida.estado == "OK_CON_ERRORES"


@pytest.mark.asyncio
async def test_ejecutar_ingesta_marca_fallida_en_excepcion_inesperada(monkeypatch):
    sesion = _SesionFakeCorrida()

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {}

    async def _fase_cables_rompe(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _fase_cables_rompe)
    monkeypatch.setattr(ingesta, "fase_cables_terceros", _fase_noop)

    corrida = await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=5)

    assert corrida.estado == "FALLIDA"


@pytest.mark.asyncio
async def test_ejecutar_ingesta_rechaza_psize_invalido():
    sesion = _SesionFakeCorrida()
    with pytest.raises(ValueError, match="psize"):
        await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=7)


@pytest.mark.asyncio
async def test_ejecutar_ingesta_propaga_modo_a_continuar_corrida(monkeypatch):
    """Task 3, requisito 8: `modo` debe llegar intacto hasta `continuar_corrida` (bare name resuelto
    vía el namespace del módulo en el momento de la llamada, igual que ya vale para las fases)."""
    sesion = _SesionFakeCorrida()
    recibido: dict[str, Any] = {}

    async def _continuar_corrida_fake(cliente, sesion, corrida_id, *, psize, max_paginas, clases, modo="COMPLETA"):
        recibido["modo"] = modo
        corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
        corrida.estado = "OK"
        corrida.finalizada_at = "2026-01-01"
        return corrida

    monkeypatch.setattr(ingesta, "continuar_corrida", _continuar_corrida_fake)

    corrida = await ingesta.ejecutar_ingesta(
        cliente=object(), sesion=sesion, usuario="tester", psize=5, modo="SOLO_ODF"
    )

    assert recibido["modo"] == "SOLO_ODF"
    assert corrida.params.get("modo") == "SOLO_ODF"


def _fases_noop(monkeypatch, conteo=None) -> None:
    async def _fase_conteo_fake(cliente, **_kwargs):
        return conteo or {}

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    for nombre in (
        "fase_cables", "fase_cables_terceros", "fase_botellas", "fase_fusiones", "fase_odfs",
        "fase_reconciliacion", "fase_servicios",
    ):
        monkeypatch.setattr(ingesta, nombre, _fase_noop)


@pytest.mark.asyncio
@pytest.mark.parametrize("modo", ["COMPLETA", "SOLO_ODF", "SOLO_PELOS_INNER"])
async def test_continuar_corrida_dispara_el_detector_de_inconsistencias_despues_del_commit(
    monkeypatch, modo
):
    """Paso posterior al commit (patrón `encolar_recalculo_duplicados_botellas`): la corrida ya
    quedó cerrada y commiteada cuando corre el detector."""
    from core.services.cromo import inconsistencias_cromo

    sesion = _SesionFakeCorrida()
    _fases_noop(monkeypatch)
    monkeypatch.setattr(ingesta, "MODOS_ACOTADOS", {
        **ingesta.MODOS_ACOTADOS,
        **{m: ingesta._ModoAcotado((51,), _fase_noop) for m in ("SOLO_ODF", "SOLO_PELOS_INNER")},
    })
    recibido: dict[str, Any] = {}

    async def _detector(cliente, sesion_arg, corrida_id, modo_arg):
        corrida = await sesion_arg.get(CromoIngestaCorrida, corrida_id)
        recibido.update(
            corrida_id=corrida_id, modo=modo_arg, estado_al_detectar=corrida.estado,
            commits_al_detectar=sesion_arg.commits,
        )
        return "OK"

    monkeypatch.setattr(inconsistencias_cromo, "detectar_post_ingesta", _detector)

    corrida = await ingesta.ejecutar_ingesta(
        cliente=object(), sesion=sesion, usuario="tester", psize=5, modo=modo
    )

    assert corrida.estado == "OK"
    assert recibido["modo"] == modo and recibido["corrida_id"] == corrida.id
    assert recibido["estado_al_detectar"] == "OK" and recibido["commits_al_detectar"] >= 2


@pytest.mark.asyncio
async def test_continuar_corrida_no_dispara_el_detector_si_la_corrida_fallo(monkeypatch):
    from core.services.cromo import inconsistencias_cromo

    sesion = _SesionFakeCorrida()
    _fases_noop(monkeypatch)

    async def _rompe(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(ingesta, "fase_cables", _rompe)
    llamadas: list = []

    async def _detector(*a, **k):
        llamadas.append(a)
        return "OK"

    monkeypatch.setattr(inconsistencias_cromo, "detectar_post_ingesta", _detector)

    corrida = await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=5)

    assert corrida.estado == "FALLIDA" and llamadas == []


@pytest.mark.asyncio
async def test_continuar_corrida_un_detector_que_rompe_no_hace_fallar_la_ingesta(monkeypatch):
    """Best-effort: aunque el detector levante (no debería: `detectar_post_ingesta` atrapa todo),
    la ingesta ya cerrada sigue OK."""
    from core.services.cromo import inconsistencias_cromo

    sesion = _SesionFakeCorrida()
    _fases_noop(monkeypatch)

    async def _detector(*a, **k):
        raise RuntimeError("detector roto")

    monkeypatch.setattr(inconsistencias_cromo, "detectar_post_ingesta", _detector)

    corrida = await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=5)

    assert corrida.estado == "OK"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "modo, encola", [("COMPLETA", True), ("SOLO_ODF", True), ("SOLO_CABLES", False)]
)
async def test_post_ingesta_encola_arbitro(monkeypatch, modo, encola):
    """Tras el detector, una corrida cerrada OK en un modo post-ingesta encola al árbitro (TODO);
    un modo acotado fuera de `MODOS_POST_INGESTA` no."""
    from core.services.cromo import inconsistencias_cromo
    from core.services.cromo.arbitro import cola
    from core.services.cromo.arbitro.senales import Alcance

    sesion = _SesionFakeCorrida()
    _fases_noop(monkeypatch)
    monkeypatch.setattr(ingesta, "MODOS_ACOTADOS", {
        **ingesta.MODOS_ACOTADOS,
        **{m: ingesta._ModoAcotado((51,), _fase_noop) for m in ("SOLO_ODF", "SOLO_CABLES")},
    })

    async def _detector(*a, **k):
        return "OK"

    llamadas: list[tuple] = []

    async def _encolar(alcance, disparo, motivo="", **kw):
        llamadas.append((alcance, disparo, motivo))

    monkeypatch.setattr(inconsistencias_cromo, "detectar_post_ingesta", _detector)
    monkeypatch.setattr(cola, "encolar_evaluacion", _encolar)

    corrida = await ingesta.ejecutar_ingesta(
        cliente=object(), sesion=sesion, usuario="tester", psize=5, modo=modo
    )

    assert corrida.estado == "OK"
    if encola:
        assert llamadas == [(Alcance("TODO"), "INGESTA", f"corrida:{corrida.id}")]
    else:
        assert llamadas == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "modo, actualiza",
    [
        ("COMPLETA", True),
        ("SOLO_CABLES", True),
        ("SOLO_CABLES_BAJADA", True),
        ("SOLO_CABLES_TERCEROS", True),
        ("SOLO_ODF", False),
        ("SOLO_PELOS_INNER", False),
    ],
)
async def test_post_ingesta_actualiza_geometria_fo_solo_en_modos_de_cables(
    monkeypatch, geometria_fo, modo, actualiza  # noqa: F811 - fixture importada
):
    """Sólo los modos que escriben `pts_raw`/`vigente` de cables refrescan el mapa de FO Monitor."""
    from core.services.cromo import inconsistencias_cromo

    sesion = _SesionFakeCorrida()
    _fases_noop(monkeypatch)
    monkeypatch.setattr(ingesta, "MODOS_ACOTADOS", {
        m: ingesta._ModoAcotado((51,), _fase_noop) for m in ingesta.MODOS_ACOTADOS
    })

    async def _detector(*a, **k):
        return None

    monkeypatch.setattr(inconsistencias_cromo, "detectar_post_ingesta", _detector)

    corrida = await ingesta.ejecutar_ingesta(
        cliente=object(), sesion=sesion, usuario="tester", psize=5, modo=modo
    )

    assert corrida.estado == "OK"
    assert geometria_fo.llamadas == ([corrida.id] if actualiza else [])


@pytest.mark.asyncio
async def test_post_ingesta_no_actualiza_geometria_fo_si_la_corrida_fallo(monkeypatch, geometria_fo):  # noqa: F811 - fixture importada
    sesion = _SesionFakeCorrida()
    _fases_noop(monkeypatch)

    async def _rompe(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(ingesta, "fase_cables", _rompe)

    corrida = await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=5)

    assert corrida.estado == "FALLIDA" and geometria_fo.llamadas == []


class _SessionLocalFake:
    def __enter__(self):
        return "sesion-sync"

    def __exit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_actualizar_geometria_fo_usa_sesion_propia_y_loguea_el_resumen(monkeypatch, geometria_fo, caplog):  # noqa: F811 - fixture importada
    from core.services.fo_monitor import geometria
    from db import session as db_session

    recibidas: list = []

    def _actualizar(session, **_kw):
        recibidas.append(session)
        return geometria.ResumenGeo(actualizados=3, sin_geometria=1, marcados_calidad=0, purgados=2)

    monkeypatch.setattr(geometria, "actualizar_geometrias", _actualizar)
    monkeypatch.setattr(db_session, "SessionLocal", _SessionLocalFake)

    with caplog.at_level("INFO", logger=ingesta.logger.name):
        await geometria_fo.original(77)

    assert recibidas == ["sesion-sync"]
    assert "evento=geometria_fo_actualizada corrida_id=77 actualizados=3" in caplog.text
    assert "purgados=2" in caplog.text


@pytest.mark.asyncio
async def test_actualizar_geometria_fo_nunca_levanta(monkeypatch, geometria_fo, caplog):  # noqa: F811 - fixture importada
    """Best-effort: un error de la geometría queda en el log y no tumba la ingesta ya cerrada."""
    from core.services.fo_monitor import geometria
    from db import session as db_session

    def _rompe(session, **_kw):
        raise RuntimeError("pyproj roto")

    monkeypatch.setattr(geometria, "actualizar_geometrias", _rompe)
    monkeypatch.setattr(db_session, "SessionLocal", _SessionLocalFake)

    with caplog.at_level("WARNING", logger=ingesta.logger.name):
        await geometria_fo.original(78)

    assert "evento=geometria_fo_fallida corrida_id=78" in caplog.text


# ── Cancelación cooperativa entre páginas ───────────────────────────────────


@pytest.mark.asyncio
async def test_fase_cables_se_detiene_si_fue_cancelada_externamente():
    cable_obj = json.loads((FIXTURES_DIR / "cable_barrido_directo.json").read_text())
    # 3 páginas disponibles, pero la corrida "ya fue cancelada" desde la primera consulta de estado.
    cliente = _ClientePaginado([{"response": [cable_obj]}, {"response": [cable_obj]}, {"response": [cable_obj]}])
    sesion = _SesionFake(respuestas_execute={"SELECT estado FROM app.cromo_ingesta_corridas": [("CANCELADA",)]})
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    with pytest.raises(ingesta._CorridaCancelada):
        await ingesta.fase_cables(cliente, sesion, corrida, contadores, psize=5, max_paginas=None)

    # Se procesó la página en curso antes de detenerse (cierra la página, no la corta a mitad).
    assert contadores.leidas == 1


@pytest.mark.asyncio
async def test_fase_odfs_se_detiene_si_fue_cancelada_externamente():
    """Mismo contrato de cancelación cooperativa que `fase_cables` (Task 6, cierre de cobertura):
    `fase_odfs` también debe frenar entre páginas si la corrida fue cancelada externamente, sin
    cortar la página en curso a mitad de camino."""
    odf_obj = {"id": 900300, "n_id": 800300, "class": 69, "vmax": 1, "at": []}
    # 3 páginas disponibles, pero la corrida "ya fue cancelada" desde la primera consulta de estado.
    cliente = _ClientePaginado([{"response": [odf_obj]}, {"response": [odf_obj]}, {"response": [odf_obj]}])
    sesion = _SesionFake(respuestas_execute={"SELECT estado FROM app.cromo_ingesta_corridas": [("CANCELADA",)]})
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    with pytest.raises(ingesta._CorridaCancelada):
        await ingesta.fase_odfs(cliente, sesion, corrida, contadores, psize=5, max_paginas=None)

    # Se procesó la página en curso antes de detenerse (cierra la página, no la corta a mitad).
    assert contadores.leidas == 1


@pytest.mark.asyncio
async def test_ejecutar_ingesta_marca_cancelada_sin_tratarla_como_falla(monkeypatch):
    sesion = _SesionFakeCorrida()

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {}

    async def _fase_cables_cancela(*args, **kwargs):
        raise ingesta._CorridaCancelada()

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _fase_cables_cancela)
    monkeypatch.setattr(ingesta, "fase_cables_terceros", _fase_noop)
    monkeypatch.setattr(ingesta, "fase_botellas", _noop)
    monkeypatch.setattr(ingesta, "fase_reconciliacion", _noop)
    monkeypatch.setattr(ingesta, "fase_servicios", _noop)

    corrida = await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=5)

    assert corrida.estado == "CANCELADA"


# ── continuar_corrida (llamado directo, sin pasar por ejecutar_ingesta) ────


@pytest.mark.asyncio
async def test_continuar_corrida_falla_clara_si_no_existe():
    sesion = _SesionFakeCorrida()
    with pytest.raises(ValueError, match="corrida 999"):
        await ingesta.continuar_corrida(
            cliente=object(), sesion=sesion, corrida_id=999, psize=5, max_paginas=None, clases=ingesta.CLASES_BOTELLA
        )


@pytest.mark.asyncio
async def test_continuar_corrida_modo_solo_odf_llama_unicamente_fase_odfs(monkeypatch):
    """Contrato central del brief (el más fácil de romper en silencio): `modo="SOLO_ODF"` debe
    saltear POR COMPLETO Cable/Botella/Fusión/reconciliación/servicios — no sólo "la mayoría"."""
    sesion = _SesionFakeCorrida()
    sesion._existentes[(CromoIngestaCorrida, 42)] = CromoIngestaCorrida(id=42, usuario="tester", estado="EN_CURSO")
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
        modo="SOLO_ODF",
    )

    assert corrida.estado == "OK"
    # Assert explícito, no implícito: NINGUNA otra fase corrió, sólo fase_odfs.
    assert "fase_cables" not in llamadas
    assert "fase_botellas" not in llamadas
    assert "fase_fusiones" not in llamadas
    assert "fase_reconciliacion" not in llamadas
    assert "fase_servicios" not in llamadas
    assert llamadas == ["fase_odfs"]


@pytest.mark.asyncio
async def test_continuar_corrida_modo_completa_incluye_fase_odfs_ademas_de_las_existentes(monkeypatch):
    """Guardarraíl de regresión: el default `modo="COMPLETA"` debe seguir corriendo la secuencia de
    siempre Y agregar `fase_odfs` incondicionalmente, justo después de Fusión y antes de
    reconciliación/servicios — un refactor futuro no puede sacarla del camino por defecto sin que
    este test lo note."""
    sesion = _SesionFakeCorrida()
    sesion._existentes[(CromoIngestaCorrida, 42)] = CromoIngestaCorrida(id=42, usuario="tester", estado="EN_CURSO")
    llamadas: list[str] = []

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {}

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    _spies_de_fases(monkeypatch, llamadas)

    corrida = await ingesta.continuar_corrida(
        cliente=object(), sesion=sesion, corrida_id=42, psize=5, max_paginas=None, clases=ingesta.CLASES_BOTELLA
    )  # modo default = "COMPLETA"

    assert corrida.estado == "OK"
    assert llamadas == [
        "fase_cables",
        "fase_cables_terceros",
        "fase_botellas",
        "fase_fusiones",
        "fase_odfs",
        "fase_reconciliacion",
        "fase_servicios",
    ]


@pytest.mark.asyncio
async def test_continuar_corrida_modo_solo_odf_total_objetivo_solo_suma_clase_odf(monkeypatch):
    sesion = _SesionFakeCorrida()
    sesion._existentes[(CromoIngestaCorrida, 42)] = CromoIngestaCorrida(id=42, usuario="tester", estado="EN_CURSO")

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {68: 100, ingesta.CLASE_CABLE: 50, ingesta.CLASE_FUSION: 10, ingesta.CLASE_ODF: 7}

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_odfs", _noop)

    corrida = await ingesta.continuar_corrida(
        cliente=object(),
        sesion=sesion,
        corrida_id=42,
        psize=5,
        max_paginas=None,
        clases=ingesta.CLASES_BOTELLA,
        modo="SOLO_ODF",
    )

    assert corrida.total_objetivo == 7


@pytest.mark.asyncio
async def test_continuar_corrida_modo_completa_total_objetivo_incluye_clase_odf(monkeypatch):
    sesion = _SesionFakeCorrida()
    sesion._existentes[(CromoIngestaCorrida, 42)] = CromoIngestaCorrida(id=42, usuario="tester", estado="EN_CURSO")

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {68: 100, ingesta.CLASE_CABLE: 50, ingesta.CLASE_FUSION: 10, ingesta.CLASE_ODF: 7}

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _noop)
    monkeypatch.setattr(ingesta, "fase_cables_terceros", _fase_noop)
    monkeypatch.setattr(ingesta, "fase_botellas", _noop)
    monkeypatch.setattr(ingesta, "fase_fusiones", _noop)
    monkeypatch.setattr(ingesta, "fase_odfs", _noop)
    monkeypatch.setattr(ingesta, "fase_reconciliacion", _noop)
    monkeypatch.setattr(ingesta, "fase_servicios", _noop)

    corrida = await ingesta.continuar_corrida(
        cliente=object(), sesion=sesion, corrida_id=42, psize=5, max_paginas=None, clases=ingesta.CLASES_BOTELLA
    )

    # clases_final=CLASES_BOTELLA (sólo la clase 68 tiene stats en el fake) + CABLE + FUSION + ODF.
    assert corrida.total_objetivo == 100 + 50 + 10 + 7


@pytest.mark.asyncio
async def test_continuar_corrida_reusa_una_corrida_ya_creada(monkeypatch):
    sesion = _SesionFakeCorrida()
    corrida_existente = CromoIngestaCorrida(id=42, usuario="tester", estado="EN_CURSO")
    sesion._existentes[(CromoIngestaCorrida, 42)] = corrida_existente

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {}

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _noop)
    monkeypatch.setattr(ingesta, "fase_cables_terceros", _fase_noop)
    monkeypatch.setattr(ingesta, "fase_botellas", _noop)
    monkeypatch.setattr(ingesta, "fase_fusiones", _noop)
    monkeypatch.setattr(ingesta, "fase_odfs", _noop)
    monkeypatch.setattr(ingesta, "fase_reconciliacion", _noop)
    monkeypatch.setattr(ingesta, "fase_servicios", _noop)

    corrida = await ingesta.continuar_corrida(
        cliente=object(), sesion=sesion, corrida_id=42, psize=5, max_paginas=None, clases=ingesta.CLASES_BOTELLA
    )

    assert corrida is corrida_existente
    assert corrida.estado == "OK"


@pytest.mark.asyncio
async def test_continuar_corrida_carga_alias_una_vez_y_lo_pasa_a_las_cuatro_fases(monkeypatch):
    """Task 3: `fase_odfs` se sumó al mismo grupo de fases directas que ya recibían
    `alias_por_origen` (cables/botellas/fusiones) — verifica que la ampliación no la dejó afuera."""
    sesion = _SesionFakeCorrida()
    corrida_existente = CromoIngestaCorrida(id=42, usuario="tester", estado="EN_CURSO")
    sesion._existentes[(CromoIngestaCorrida, 42)] = corrida_existente
    alias_falso = {10178728: AliasBotella(accion="ignorar", id_cromo_destino=None)}
    llamadas_cargar: list[int] = []
    recibidos: dict[str, Any] = {}

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {}

    async def _cargar_alias_fake(sesion):
        llamadas_cargar.append(1)
        return alias_falso

    async def _fase_cables_fake(*args, **kwargs):
        recibidos["cables"] = kwargs.get("alias_por_origen")

    async def _fase_botellas_fake(*args, **kwargs):
        recibidos["botellas"] = kwargs.get("alias_por_origen")

    async def _fase_fusiones_fake(*args, **kwargs):
        recibidos["fusiones"] = kwargs.get("alias_por_origen")

    async def _fase_odfs_fake(*args, **kwargs):
        recibidos["odfs"] = kwargs.get("alias_por_origen")

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta.alias_service, "cargar_alias_vigentes", _cargar_alias_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _fase_cables_fake)
    monkeypatch.setattr(ingesta, "fase_cables_terceros", _fase_noop)
    monkeypatch.setattr(ingesta, "fase_botellas", _fase_botellas_fake)
    monkeypatch.setattr(ingesta, "fase_fusiones", _fase_fusiones_fake)
    monkeypatch.setattr(ingesta, "fase_odfs", _fase_odfs_fake)
    monkeypatch.setattr(ingesta, "fase_reconciliacion", _noop)
    monkeypatch.setattr(ingesta, "fase_servicios", _noop)

    corrida = await ingesta.continuar_corrida(
        cliente=object(), sesion=sesion, corrida_id=42, psize=5, max_paginas=None, clases=ingesta.CLASES_BOTELLA
    )

    assert corrida.estado == "OK"
    assert len(llamadas_cargar) == 1
    assert recibidos["cables"] is alias_falso
    assert recibidos["botellas"] is alias_falso
    assert recibidos["fusiones"] is alias_falso
    assert recibidos["odfs"] is alias_falso


# ── Invalidación de la caché de Botellas duplicadas al cerrar la corrida ────


def _monkeypatch_fases_noop(monkeypatch, *, fase_botellas) -> None:
    async def _fase_conteo_fake(cliente, **_kwargs):
        return {}

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _noop)
    monkeypatch.setattr(ingesta, "fase_cables_terceros", _fase_noop)
    monkeypatch.setattr(ingesta, "fase_botellas", fase_botellas)
    monkeypatch.setattr(ingesta, "fase_fusiones", _noop)
    monkeypatch.setattr(ingesta, "fase_odfs", _noop)
    monkeypatch.setattr(ingesta, "fase_reconciliacion", _noop)
    monkeypatch.setattr(ingesta, "fase_servicios", _noop)


@pytest.mark.asyncio
async def test_continuar_corrida_encola_recalculo_si_hubo_creadas_o_actualizadas(monkeypatch):
    sesion = _SesionFakeCorrida()
    sesion._existentes[(CromoIngestaCorrida, 42)] = CromoIngestaCorrida(id=42, usuario="tester", estado="EN_CURSO")
    motivos: list[str] = []

    async def _encolar_spy(motivo: str) -> None:
        motivos.append(motivo)

    async def _fase_botellas_productiva(cliente, sesion, corrida, contadores, **kwargs):
        contadores.creadas += 1

    monkeypatch.setattr(ingesta, "encolar_recalculo_duplicados_botellas", _encolar_spy)
    _monkeypatch_fases_noop(monkeypatch, fase_botellas=_fase_botellas_productiva)

    await ingesta.continuar_corrida(
        cliente=object(), sesion=sesion, corrida_id=42, psize=5, max_paginas=None, clases=ingesta.CLASES_BOTELLA
    )

    assert len(motivos) == 1
    assert "corrida_id=42" in motivos[0]


@pytest.mark.asyncio
async def test_continuar_corrida_no_encola_recalculo_si_todo_sin_cambios(monkeypatch):
    sesion = _SesionFakeCorrida()
    sesion._existentes[(CromoIngestaCorrida, 42)] = CromoIngestaCorrida(id=42, usuario="tester", estado="EN_CURSO")
    motivos: list[str] = []

    async def _encolar_spy(motivo: str) -> None:
        motivos.append(motivo)

    async def _fase_botellas_sin_cambios(cliente, sesion, corrida, contadores, **kwargs):
        contadores.sin_cambios += 1

    monkeypatch.setattr(ingesta, "encolar_recalculo_duplicados_botellas", _encolar_spy)
    _monkeypatch_fases_noop(monkeypatch, fase_botellas=_fase_botellas_sin_cambios)

    await ingesta.continuar_corrida(
        cliente=object(), sesion=sesion, corrida_id=42, psize=5, max_paginas=None, clases=ingesta.CLASES_BOTELLA
    )

    assert motivos == []


# ── Modos de la red de acceso PON (2026-09-19) ──


@pytest.mark.parametrize(
    "modo,fase_esperada",
    [
        ("SOLO_SPLITTERS", "fase_splitters"),
        ("SOLO_PUERTOS_SPLITTER", "fase_puertos_splitter"),
        ("SOLO_CAJAS_PON", "fase_cajas_pon"),
        ("SOLO_ROSETAS", "fase_rosetas"),
        ("SOLO_CABLES", "fase_cables"),
        ("SOLO_CABLES_BAJADA", "fase_cables_bajada"),
    ],
)
@pytest.mark.asyncio
async def test_cada_modo_acotado_corre_solo_su_fase(monkeypatch, modo, fase_esperada):
    """Mismo contrato que `SOLO_ODF`, extendido a los cinco modos de la red de acceso.

    El assert es de exclusión total y no de inclusión: lo que hay que impedir es que un modo
    acotado arrastre `fase_botellas` (horas) o `fase_servicios` (que ya dejó 944 pelos sin match
    una vez, por correr cuando no debía).
    """
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
        modo=modo,
    )

    assert corrida.estado == "OK"
    assert llamadas == [fase_esperada]


@pytest.mark.asyncio
async def test_completa_no_arrastra_ninguna_fase_de_la_red_pon(monkeypatch):
    """Decisión explícita: sumarlas a COMPLETA convertiría una corrida de rutina en una de horas.

    Las cajas PON solas son ~2 h (medido 2026-09-29) y los puertos de splitter ~91 min.
    """
    sesion = _SesionFakeCorrida()
    sesion._existentes[(CromoIngestaCorrida, 42)] = CromoIngestaCorrida(
        id=42, usuario="tester", estado="EN_CURSO"
    )
    llamadas: list[str] = []

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {}

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    _spies_de_fases(monkeypatch, llamadas)

    await ingesta.continuar_corrida(
        cliente=object(),
        sesion=sesion,
        corrida_id=42,
        psize=5,
        max_paginas=None,
        clases=ingesta.CLASES_BOTELLA,
        modo="COMPLETA",
    )

    assert llamadas == [
        "fase_cables",
        "fase_cables_terceros",
        "fase_botellas",
        "fase_fusiones",
        "fase_odfs",
        "fase_reconciliacion",
        "fase_servicios",
    ]


def test_todos_los_modos_acotados_estan_en_la_lista_que_valida_el_endpoint():
    """`MODOS_INGESTA` es lo que importa `web/app/main.py`: si se desincronizan, un modo que el
    frontend ofrece devuelve 400 sin que ningún test lo note."""
    assert set(ingesta.MODOS_INGESTA) == {"COMPLETA", *ingesta.MODOS_ACOTADOS}
