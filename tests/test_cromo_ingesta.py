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
from core.services.cromo.alias_service import AliasBotella
from core.services.cromo.client import CromoClientError
from db.models.cromo import CromoBotella, CromoCable, CromoFusion, CromoIngestaCorrida

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

    def first(self):
        return self._valores[0] if self._valores else None


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
        # Refleja el identity map real de SQLAlchemy: un objeto con PK manual (n_id) ya asignada
        # es encontrable vía session.get() apenas se agrega, sin necesitar flush/commit
        # (verificado empíricamente contra una Session real — ver docstring de
        # _procesar_botella_completa en ingesta.py, protección de nombre_editado_manual).
        n_id = getattr(obj, "n_id", None)
        if n_id is not None:
            self._existentes[(type(obj), n_id)] = obj

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
        if isinstance(obj, CromoIngestaCorrida):
            # continuar_corrida() re-obtiene la corrida por id con sesion.get(): que la encuentre.
            self._existentes[(CromoIngestaCorrida, obj.id)] = obj


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
    monkeypatch.setattr(ingesta, "fase_fusiones", _noop)
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
    monkeypatch.setattr(ingesta, "fase_fusiones", _noop)
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
    from db.models.cromo import CromoFusion, CromoPelo, CromoTubo

    assert CromoBotella in tipos_agregados
    assert CromoCable in tipos_agregados
    assert CromoTubo in tipos_agregados
    assert CromoPelo in tipos_agregados
    assert CromoFusion in tipos_agregados


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
async def test_ejecutar_ingesta_marca_cancelada_sin_tratarla_como_falla(monkeypatch):
    sesion = _SesionFakeCorrida()

    async def _fase_conteo_fake(cliente):
        return {}

    async def _fase_cables_cancela(*args, **kwargs):
        raise ingesta._CorridaCancelada()

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _fase_cables_cancela)
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
async def test_continuar_corrida_reusa_una_corrida_ya_creada(monkeypatch):
    sesion = _SesionFakeCorrida()
    corrida_existente = CromoIngestaCorrida(id=42, usuario="tester", estado="EN_CURSO")
    sesion._existentes[(CromoIngestaCorrida, 42)] = corrida_existente

    async def _fase_conteo_fake(cliente):
        return {}

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _noop)
    monkeypatch.setattr(ingesta, "fase_botellas", _noop)
    monkeypatch.setattr(ingesta, "fase_fusiones", _noop)
    monkeypatch.setattr(ingesta, "fase_reconciliacion", _noop)
    monkeypatch.setattr(ingesta, "fase_servicios", _noop)

    corrida = await ingesta.continuar_corrida(
        cliente=object(), sesion=sesion, corrida_id=42, psize=5, max_paginas=None, clases=ingesta.CLASES_BOTELLA
    )

    assert corrida is corrida_existente
    assert corrida.estado == "OK"


@pytest.mark.asyncio
async def test_continuar_corrida_carga_alias_una_vez_y_lo_pasa_a_las_tres_fases(monkeypatch):
    sesion = _SesionFakeCorrida()
    corrida_existente = CromoIngestaCorrida(id=42, usuario="tester", estado="EN_CURSO")
    sesion._existentes[(CromoIngestaCorrida, 42)] = corrida_existente
    alias_falso = {10178728: AliasBotella(accion="ignorar", id_cromo_destino=None)}
    llamadas_cargar: list[int] = []
    recibidos: dict[str, Any] = {}

    async def _fase_conteo_fake(cliente):
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

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta.alias_service, "cargar_alias_vigentes", _cargar_alias_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _fase_cables_fake)
    monkeypatch.setattr(ingesta, "fase_botellas", _fase_botellas_fake)
    monkeypatch.setattr(ingesta, "fase_fusiones", _fase_fusiones_fake)
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


# ── Invalidación de la caché de Botellas duplicadas al cerrar la corrida ────


def _monkeypatch_fases_noop(monkeypatch, *, fase_botellas) -> None:
    async def _fase_conteo_fake(cliente):
        return {}

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_cables", _noop)
    monkeypatch.setattr(ingesta, "fase_botellas", fase_botellas)
    monkeypatch.setattr(ingesta, "fase_fusiones", _noop)
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
