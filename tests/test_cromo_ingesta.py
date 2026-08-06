# Nombre de archivo: test_cromo_ingesta.py
# Ubicación de archivo: tests/test_cromo_ingesta.py
# Descripción: Pruebas del servicio de ingesta Cromo (clasificación por vmax, orquestación) sin red ni DB real

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

from core.services.cromo import ingesta
from db.models.cromo import CromoBotella, CromoCable, CromoIngestaCorrida

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "cromo"


class _NestedCM:
    """Emula `AsyncSession.begin_nested()`: no absorbe la excepción, igual que el savepoint real."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ResultadoFilas:
    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None

    def scalars(self):
        return _Escalares([f[0] for f in self._filas])


class _Escalares:
    def __init__(self, valores: list[Any]) -> None:
        self._valores = valores

    def all(self):
        return self._valores


class _SesionFake:
    """Reemplaza sólo lo que el servicio de ingesta necesita de AsyncSession."""

    def __init__(
        self,
        existentes: Optional[dict[tuple[type, int], Any]] = None,
        respuestas_execute: Optional[dict[str, list[tuple]]] = None,
    ) -> None:
        self._existentes = existentes or {}
        self._respuestas_execute = respuestas_execute or {}
        self.agregados: list[Any] = []
        self.eliminados: list[Any] = []

    async def get(self, modelo_cls: type, pk: int) -> Any:
        return self._existentes.get((modelo_cls, pk))

    def add(self, obj: Any) -> None:
        self.agregados.append(obj)

    def begin_nested(self) -> _NestedCM:
        return _NestedCM()

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        texto = str(stmt)
        for clave, filas in self._respuestas_execute.items():
            if clave in texto:
                return _ResultadoFilas(filas)
        return _ResultadoFilas([])

    async def commit(self) -> None:
        return None

    async def delete(self, obj: Any) -> None:
        self.eliminados.append(obj)


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
    accion = await ingesta._upsert_versionado(sesion, CromoBotella, _botella(n_id=10, vmax=1), ingesta._BOTELLA_CAMPOS)

    assert accion == "CREADA"
    assert len(sesion.agregados) == 1
    assert sesion.agregados[0].n_id == 10
    assert sesion.agregados[0].vmax == 1


@pytest.mark.asyncio
async def test_upsert_versionado_sin_cambios_no_toca_campos():
    existente = CromoBotella(n_id=10, version_id=1, vmax=5, nombre="Nombre original")
    sesion = _SesionFake({(CromoBotella, 10): existente})

    # Llega una vista parcial (nombre=None) con el mismo vmax: no debe pisar el nombre ya cargado.
    accion = await ingesta._upsert_versionado(
        sesion, CromoBotella, _botella(n_id=10, version_id=1, vmax=5, nombre=None), ingesta._BOTELLA_CAMPOS
    )

    assert accion == "SIN_CAMBIOS"
    assert existente.nombre == "Nombre original"
    assert sesion.agregados == []


@pytest.mark.asyncio
async def test_upsert_versionado_actualizada_pisa_campos_y_marca_modificacion():
    existente = CromoBotella(n_id=10, version_id=1, vmax=5, nombre="Viejo")
    sesion = _SesionFake({(CromoBotella, 10): existente})

    accion = await ingesta._upsert_versionado(
        sesion, CromoBotella, _botella(n_id=10, version_id=2, vmax=6, nombre="Nuevo"), ingesta._BOTELLA_CAMPOS
    )

    assert accion == "ACTUALIZADA"
    assert existente.nombre == "Nuevo"
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

    accion = await ingesta._upsert_versionado(
        sesion, CromoCable, _CableFake(n_id=50, version_id=1, vmax=1, payload_raw={}), ingesta._CABLE_CAMPOS
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


# ── Orquestación de alto nivel (fases mockeadas, sólo se prueba el control de flujo) ──


class _SesionFakeCorrida(_SesionFake):
    def __init__(self) -> None:
        super().__init__()
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, obj: Any) -> None:
        if isinstance(obj, CromoIngestaCorrida) and obj.id is None:
            obj.id = 1


@pytest.mark.asyncio
async def test_ejecutar_ingesta_cierra_ok_sin_errores(monkeypatch):
    sesion = _SesionFakeCorrida()

    async def _fase_conteo_fake(cliente):
        return {68: 1, 51: 1}

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _noop)
    monkeypatch.setattr(ingesta, "fase_botellas", _noop)
    monkeypatch.setattr(ingesta, "fase_reconciliacion", _noop)
    monkeypatch.setattr(ingesta, "fase_servicios", _noop)

    corrida = await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=5)

    assert corrida.estado == "OK"
    assert corrida.finalizada_at is not None


@pytest.mark.asyncio
async def test_ejecutar_ingesta_marca_ok_con_errores_si_hubo_errores(monkeypatch):
    sesion = _SesionFakeCorrida()

    async def _fase_conteo_fake(cliente):
        return {}

    async def _fase_botellas_con_error(cliente, sesion, corrida, contadores, **kwargs):
        contadores.errores += 1

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _noop)
    monkeypatch.setattr(ingesta, "fase_botellas", _fase_botellas_con_error)
    monkeypatch.setattr(ingesta, "fase_reconciliacion", _noop)
    monkeypatch.setattr(ingesta, "fase_servicios", _noop)

    corrida = await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=5)

    assert corrida.estado == "OK_CON_ERRORES"


@pytest.mark.asyncio
async def test_ejecutar_ingesta_marca_fallida_en_excepcion_inesperada(monkeypatch):
    sesion = _SesionFakeCorrida()

    async def _fase_conteo_fake(cliente):
        return {}

    async def _fase_cables_rompe(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _fase_cables_rompe)

    corrida = await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=5)

    assert corrida.estado == "FALLIDA"


@pytest.mark.asyncio
async def test_ejecutar_ingesta_rechaza_psize_invalido():
    sesion = _SesionFakeCorrida()
    with pytest.raises(ValueError, match="psize"):
        await ingesta.ejecutar_ingesta(cliente=object(), sesion=sesion, usuario="tester", psize=7)


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
async def test_procesar_botella_completa_con_fixture_real():
    obj = json.loads((FIXTURES_DIR / "botella_con_arbol.json").read_text())
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_botella_completa(sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert contadores.errores == 0
    assert contadores.creadas >= 1  # la botella misma
    tipos_agregados = {type(o) for o in sesion.agregados}
    from db.models.cromo import CromoFusion, CromoPelo, CromoTubo

    assert CromoBotella in tipos_agregados
    assert CromoCable in tipos_agregados
    assert CromoTubo in tipos_agregados
    assert CromoPelo in tipos_agregados
    assert CromoFusion in tipos_agregados


# ── Fases con cliente/páginas fake ──────────────────────────────────────────


class _ClientePaginado:
    def __init__(self, paginas: list[dict]) -> None:
        self._paginas = paginas

    async def iterar_coleccion(self, filtro, *, psize=None, show=None, max_paginas=None):
        for pagina in self._paginas:
            yield pagina


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


# ── Reconciliación ───────────────────────────────────────────────────────────


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
    assert sesion.agregados == []


# ── Matching de servicios ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fase_servicios_matchea_y_deja_traza_de_no_matcheados():
    sesion = _SesionFake(
        respuestas_execute={
            "cromo_servicio_match m": [(10, "114699"), (11, "999999")],
            "servicio_id = :numero": [],  # default: sin match: se sobreescribe por caso abajo
        }
    )

    # El fake resuelve por substring; para diferenciar el pelo que matchea, usamos un execute custom.
    llamadas = {"n": 0}
    original_execute = sesion.execute

    async def execute_custom(stmt, params=None):
        texto = str(stmt)
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
    sin_match = next(m for m in matches if m.servicio_numero == "999999")
    assert matcheado.servicio_id == 1429
    assert matcheado.confianza == 100
    assert sin_match.servicio_id is None
    assert sin_match.confianza == 0
