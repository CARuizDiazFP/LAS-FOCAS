# Nombre de archivo: test_cromo_arbitro_motor.py
# Ubicación de archivo: tests/test_cromo_arbitro_motor.py
# Descripción: Tests del motor del árbitro de Cromo con reglas fake sobre una sesión real con savepoint

"""Las reglas son fakes que devuelven evaluaciones fijas; la base es la de dev dentro de una
transacción que se revierte, con ids sintéticos `999_920_6xx` y reglas de config sintéticas
(`QA_MOTOR_*`), para ejercitar el índice único parcial, los CHECK y las acciones reales."""

from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo.arbitro import motor
from core.services.cromo.arbitro.motor import (
    LOCK_ARBITRO,
    ResumenEvaluacion,
    actualizar_regla,
    aplicar_manual,
    evaluar,
    listar_propuestas,
    precision_por_regla,
    rechazar,
    revertir_manual,
)
from core.services.cromo.arbitro.senales import USUARIO_ARBITRO, Alcance, Evaluacion, Senal
from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real
from tests.test_cromo_arbitro_migracion_real_db import _correr

_REGLA = "QA_MOTOR_A"
_REGLA_B = "QA_MOTOR_B"
_NUMEROS = ("999920601", "999920602")
_ODF = 999_920_610
_ODF_B = 999_920_611
_PELO = 999_920_612
_NOMBRE = "QA Arbitro Motor Zzyzx 999920"
_TODO = Alcance("TODO")


class ReglaFake:
    def __init__(self, codigo: str = _REGLA) -> None:
        self.codigo = codigo
        self.evaluaciones: list[Evaluacion] = []
        self.falla = False
        self.llamadas: list[dict[str, Any]] = []

    async def evaluar(self, sesion, alcance, *, propios, contexto):
        self.llamadas.append({"alcance": alcance, "propios": propios})
        if self.falla:
            raise RuntimeError("boom")
        return list(self.evaluaciones)


def _ev(objeto_id: int, *, peso: int = 100, accion: str = "INFORMAR", parametros=None,
        regla: str = _REGLA, objeto_tipo: str = "SERVICIO") -> Evaluacion:
    return Evaluacion(
        regla=regla,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        accion=accion,
        parametros=parametros if parametros is not None else {"x": 1},
        senales=(Senal("QA", peso, {"d": 1}),),
    )


def _ev_odf(sid: int, *, peso: int = 100, odf: int = _ODF) -> Evaluacion:
    return _ev(sid, peso=peso, accion="ASOCIAR_ODF",
               parametros={"odf_n_id": odf, "pelo_n_id": _PELO})


# ── Sin base ────────────────────────────────────────────────────────────────────────────────────


def test_resumen_a_dict_es_json():
    r = ResumenEvaluacion()
    r.nuevas = 2
    r.aplicadas_auto.append(7)
    r.por_regla["X"] = {"nuevas": 2}
    d = r.a_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["nuevas"] == 2 and d["aplicadas_auto"] == [7] and d["por_regla"] == {"X": {"nuevas": 2}}
    assert d["omitida"] is None


@pytest.mark.asyncio
async def test_codigo_desconocido_lanza():
    with pytest.raises(ValueError):
        await evaluar(None, _TODO, "VIEWER", reglas=[ReglaFake()], codigos=["NO_EXISTE"])


@pytest.mark.asyncio
async def test_disparo_invalido_lanza():
    with pytest.raises(ValueError):
        await evaluar(None, _TODO, "OTRO", reglas=[ReglaFake()])


# ── Con base ────────────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def entorno():
    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            existe = (await conn.execute(text("SELECT to_regclass('app.cromo_propuesta')"))).scalar()
            if existe is None:
                await conn.run_sync(_correr, "upgrade")
            for codigo in (_REGLA, _REGLA_B):
                await conn.execute(
                    text(
                        "INSERT INTO app.cromo_regla_correccion (codigo, descripcion) "
                        "VALUES (:c, 'QA motor')"
                    ),
                    {"c": codigo},
                )
            sesion = AsyncSession(
                bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
            )
            yield sesion, conn, engine
            await sesion.close()
        finally:
            await trans.rollback()
    await engine.dispose()


@pytest.fixture
def sin_ingesta(monkeypatch):
    """La DB de dev puede tener una ingesta real EN_CURSO: los tests que no prueban eso la ignoran."""

    async def _ninguna(_sesion):
        return None

    monkeypatch.setattr(motor, "ingesta_en_curso", _ninguna)


async def _modo(conn, modo: str, *, umbral: int = 90, presupuesto: int = 50, codigo: str = _REGLA):
    await conn.execute(
        text(
            "UPDATE app.cromo_regla_correccion SET modo = :m, umbral = :u, "
            "presupuesto_por_corrida = :p WHERE codigo = :c"
        ),
        {"m": modo, "u": umbral, "p": presupuesto, "c": codigo},
    )


async def _servicio(conn, numero: str) -> int:
    return (
        await conn.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, nombre_cliente, "
                "categoria, origen_datos, estado_servicio, es_verificable) "
                "VALUES (:n, :n, 'QA Arbitro Motor', 6, 'INGEST_EXCEL', 'Activo', true) RETURNING id"
            ),
            {"n": numero},
        )
    ).scalar_one()


async def _odf(conn, n_id: int = _ODF) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.cromo_odfs (n_id, version_id, vmax, clase, nombre, payload_raw) "
            "VALUES (:n, :n, 1, 69, :nombre, '{}'::jsonb)"
        ),
        {"n": n_id, "nombre": _NOMBRE},
    )


async def _filas(conn, regla: str = _REGLA) -> list:
    return (
        await conn.execute(
            text(
                "SELECT id, objeto_id, estado, confianza, evidencia_hash, nota, disparo, decidida_por, "
                "parametros, reversion FROM app.cromo_propuesta WHERE regla = :r ORDER BY id"
            ),
            {"r": regla},
        )
    ).all()


async def _overrides(conn, sid: int) -> list:
    return (
        await conn.execute(
            text("SELECT origen, odf_n_id FROM app.cromo_servicio_odf_override WHERE servicio_id = :s"),
            {"s": sid},
        )
    ).all()


requiere_db = requiere_postgres_real


@requiere_db
@pytest.mark.asyncio
async def test_rafaga_misma_evaluacion_una_sola_propuesta(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla = ReglaFake()
    regla.evaluaciones = [_ev(999_920_601)]
    r1 = await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    assert r1.nuevas == 1 and r1.actualizadas == 0
    for _ in range(9):
        r = await evaluar(sesion, _TODO, "REGISTRADOR", reglas=[regla])
    assert r.nuevas == 0 and r.actualizadas == 1
    filas = await _filas(conn)
    assert len(filas) == 1
    assert filas[0].estado == "PROPUESTA" and filas[0].disparo == "REGISTRADOR"
    assert r.a_dict()["por_regla"][_REGLA]["actualizadas"] == 1


@requiere_db
@pytest.mark.asyncio
async def test_propuesta_toma_parametros_y_hash_nuevos(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    sid = await _servicio(conn, _NUMEROS[0])
    regla = ReglaFake()
    regla.evaluaciones = [_ev_odf(sid, peso=70, odf=_ODF)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    hash_a = (await _filas(conn))[0].evidencia_hash
    regla.evaluaciones = [_ev_odf(sid, peso=80, odf=_ODF_B)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    (fila,) = await _filas(conn)
    assert fila.parametros["odf_n_id"] == _ODF_B and fila.confianza == 80
    assert fila.evidencia_hash != hash_a


@requiere_db
@pytest.mark.asyncio
async def test_sombra_nunca_aplica(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    sid = await _servicio(conn, _NUMEROS[0])
    await _odf(conn)
    regla = ReglaFake()
    regla.evaluaciones = [_ev_odf(sid)]
    r = await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    assert r.aplicadas_auto == []
    assert await _overrides(conn, sid) == []
    assert (await _filas(conn))[0].estado == "PROPUESTA"


@requiere_db
@pytest.mark.asyncio
async def test_auto_sobre_umbral_aplica_y_queda_en_observacion(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    sid = await _servicio(conn, _NUMEROS[0])
    await _odf(conn)
    await _modo(conn, "AUTO")
    regla = ReglaFake()
    regla.evaluaciones = [_ev_odf(sid, peso=95)]
    r = await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    (fila,) = await _filas(conn)
    assert r.aplicadas_auto == [fila.id]
    assert fila.estado == "EN_OBSERVACION" and fila.decidida_por == USUARIO_ARBITRO
    assert "override_id" in fila.reversion
    assert [tuple(o) for o in await _overrides(conn, sid)] == [("AUTO", _ODF)]
    # La corrida siguiente le pasa el objeto como propio.
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    assert regla.llamadas[-1]["propios"] == frozenset({sid})


@requiere_db
@pytest.mark.asyncio
async def test_auto_bajo_umbral_no_aplica(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    sid = await _servicio(conn, _NUMEROS[0])
    await _odf(conn)
    await _modo(conn, "AUTO")
    regla = ReglaFake()
    regla.evaluaciones = [_ev_odf(sid, peso=89)]
    r = await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    assert r.aplicadas_auto == []
    assert (await _filas(conn))[0].estado == "PROPUESTA"
    assert await _overrides(conn, sid) == []


@requiere_db
@pytest.mark.asyncio
async def test_auto_no_aplicable_queda_propuesta_con_nota(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    sid = await _servicio(conn, _NUMEROS[0])  # sin ODF en inventario → odf_inexistente
    await _modo(conn, "AUTO")
    regla = ReglaFake()
    regla.evaluaciones = [_ev_odf(sid)]
    r = await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    (fila,) = await _filas(conn)
    assert r.aplicadas_auto == []
    assert fila.estado == "PROPUESTA" and fila.nota == "odf_inexistente"


@requiere_db
@pytest.mark.asyncio
async def test_presupuesto_excedido_no_aplica_ninguna(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    s1 = await _servicio(conn, _NUMEROS[0])
    s2 = await _servicio(conn, _NUMEROS[1])
    await _odf(conn)
    await _modo(conn, "AUTO", presupuesto=1)
    regla = ReglaFake()
    regla.evaluaciones = [_ev_odf(s1), _ev_odf(s2)]
    r = await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    assert r.presupuesto_excedido == [_REGLA]
    assert r.a_dict()["por_regla"][_REGLA]["presupuesto_excedido"] is True
    assert r.aplicadas_auto == []
    assert {f.estado for f in await _filas(conn)} == {"PROPUESTA"}
    assert await _overrides(conn, s1) == [] and await _overrides(conn, s2) == []


async def _rechazar_unica(sesion, conn) -> None:
    (fila,) = await _filas(conn)
    assert (await rechazar(sesion, [fila.id], "operador-qa"))["rechazados"] == [fila.id]


@requiere_db
@pytest.mark.asyncio
async def test_rechazada_mismo_hash_no_se_repropone(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla = ReglaFake()
    regla.evaluaciones = [_ev(999_920_601)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    await _rechazar_unica(sesion, conn)
    r = await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    assert r.nuevas == 0
    assert [f.estado for f in await _filas(conn)] == ["RECHAZADA"]


@requiere_db
@pytest.mark.asyncio
async def test_rechazada_hash_distinto_se_repropone(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla = ReglaFake()
    regla.evaluaciones = [_ev(999_920_601)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    await _rechazar_unica(sesion, conn)
    regla.evaluaciones = [_ev(999_920_601, parametros={"x": 2})]
    r = await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    assert r.nuevas == 1
    assert [f.estado for f in await _filas(conn)] == ["RECHAZADA", "PROPUESTA"]


async def _aplicada_en_observacion(sesion, conn) -> tuple[ReglaFake, int]:
    sid = await _servicio(conn, _NUMEROS[0])
    await _odf(conn)
    await _modo(conn, "AUTO")
    regla = ReglaFake()
    regla.evaluaciones = [_ev_odf(sid)]
    r = await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    assert len(r.aplicadas_auto) == 1
    return regla, sid


@requiere_db
@pytest.mark.asyncio
async def test_observacion_confirmada_en_ingesta(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla, sid = await _aplicada_en_observacion(sesion, conn)
    r = await evaluar(sesion, _TODO, "INGESTA", reglas=[regla])
    (fila,) = await _filas(conn)
    assert r.confirmadas == [fila.id] and fila.estado == "APLICADA"
    assert fila.decidida_por == USUARIO_ARBITRO
    assert [tuple(o) for o in await _overrides(conn, sid)] == [("AUTO", _ODF)]


@requiere_db
@pytest.mark.asyncio
async def test_observacion_contradicha_en_ingesta_se_revierte_bajo_umbral(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla, sid = await _aplicada_en_observacion(sesion, conn)
    regla.evaluaciones = [_ev_odf(sid, peso=50)]
    r = await evaluar(sesion, _TODO, "INGESTA", reglas=[regla])
    (fila,) = await _filas(conn)
    assert r.revertidas == [fila.id] and fila.estado == "REVERTIDA"
    assert await _overrides(conn, sid) == []


@requiere_db
@pytest.mark.asyncio
async def test_observacion_contradicha_en_ingesta_se_revierte_si_ausente(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla, sid = await _aplicada_en_observacion(sesion, conn)
    regla.evaluaciones = []
    r = await evaluar(sesion, _TODO, "INGESTA", reglas=[regla])
    (fila,) = await _filas(conn)
    assert r.revertidas == [fila.id] and fila.estado == "REVERTIDA"
    assert await _overrides(conn, sid) == []


@requiere_db
@pytest.mark.asyncio
async def test_observacion_con_otro_objetivo_se_revierte(entorno, sin_ingesta):
    """Confianza alta pero hacia otra ODF: la aplicada quedó contradicha."""
    sesion, conn, _ = entorno
    regla, sid = await _aplicada_en_observacion(sesion, conn)
    regla.evaluaciones = [_ev_odf(sid, odf=_ODF_B)]
    r = await evaluar(sesion, _TODO, "INGESTA", reglas=[regla])
    assert len(r.revertidas) == 1
    assert await _overrides(conn, sid) == []


@requiere_db
@pytest.mark.asyncio
async def test_observacion_revertir_fallido_queda_obsoleta(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla, sid = await _aplicada_en_observacion(sesion, conn)
    await conn.execute(
        text("DELETE FROM app.cromo_servicio_odf_override WHERE servicio_id = :s"), {"s": sid}
    )
    regla.evaluaciones = []
    r = await evaluar(sesion, _TODO, "INGESTA", reglas=[regla])
    (fila,) = await _filas(conn)
    assert r.revertidas == []
    assert fila.estado == "OBSOLETA" and fila.nota == "revertir:override_ausente"


@requiere_db
@pytest.mark.asyncio
async def test_observacion_no_se_decide_fuera_de_ingesta(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla, sid = await _aplicada_en_observacion(sesion, conn)
    for evaluaciones in ([], [_ev_odf(sid, peso=10)], [_ev_odf(sid)]):
        regla.evaluaciones = evaluaciones
        r = await evaluar(sesion, _TODO, "REGISTRADOR", reglas=[regla])
        assert r.confirmadas == [] and r.revertidas == [] and r.obsoletas == 0
    assert [f.estado for f in await _filas(conn)] == ["EN_OBSERVACION"]


@requiere_db
@pytest.mark.asyncio
async def test_obsoleta_solo_dentro_del_alcance(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla = ReglaFake()
    regla.evaluaciones = [_ev(999_920_601), _ev(999_920_602)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    regla.evaluaciones = []
    r = await evaluar(sesion, Alcance("SERVICIOS", (999_920_601,)), "VIEWER", reglas=[regla])
    assert r.obsoletas == 1
    estados = {f.objeto_id: f.estado for f in await _filas(conn)}
    assert estados == {999_920_601: "OBSOLETA", 999_920_602: "PROPUESTA"}
    # Un alcance de otro tipo de objeto no cubre servicios.
    r = await evaluar(sesion, Alcance("BOTELLAS", (999_920_602,)), "VIEWER", reglas=[regla])
    assert r.obsoletas == 0


@requiere_db
@pytest.mark.asyncio
async def test_ingesta_en_curso_omite(entorno):
    sesion, conn, _ = entorno
    await conn.execute(
        text(
            "INSERT INTO app.cromo_ingesta_corridas (usuario, estado, params) "
            "VALUES ('qa-motor', 'EN_CURSO', '{}'::jsonb)"
        )
    )
    regla = ReglaFake()
    regla.evaluaciones = [_ev(999_920_601)]
    r = await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    assert r.omitida == "ingesta_en_curso"
    assert regla.llamadas == [] and await _filas(conn) == []


@requiere_db
@pytest.mark.asyncio
async def test_otra_evaluacion_con_el_lock_omite(entorno, sin_ingesta):
    sesion, conn, engine = entorno
    async with engine.connect() as otra:
        await otra.begin()
        await otra.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_ARBITRO})
        regla = ReglaFake()
        r = await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
        await otra.rollback()
    assert r.omitida == "otra_evaluacion" and regla.llamadas == []


@requiere_db
@pytest.mark.asyncio
async def test_regla_apagada_se_saltea(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    await _modo(conn, "APAGADA")
    regla = ReglaFake()
    regla.evaluaciones = [_ev(999_920_601)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    assert regla.llamadas == [] and await _filas(conn) == []


@requiere_db
@pytest.mark.asyncio
async def test_regla_que_falla_no_obsoleta_y_sigue_con_otras(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    a, b = ReglaFake(_REGLA), ReglaFake(_REGLA_B)
    a.evaluaciones = [_ev(999_920_601)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[a, b])
    a.falla = True
    b.evaluaciones = [_ev(999_920_601, regla=_REGLA_B)]
    r = await evaluar(sesion, _TODO, "VIEWER", reglas=[a, b])
    assert "error" in r.a_dict()["por_regla"][_REGLA]
    assert [f.estado for f in await _filas(conn, _REGLA)] == ["PROPUESTA"]
    assert [f.estado for f in await _filas(conn, _REGLA_B)] == ["PROPUESTA"]


@requiere_db
@pytest.mark.asyncio
async def test_codigos_limita_la_corrida(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    a, b = ReglaFake(_REGLA), ReglaFake(_REGLA_B)
    await evaluar(sesion, _TODO, "VIEWER", reglas=[a, b], codigos=[_REGLA_B])
    assert a.llamadas == [] and len(b.llamadas) == 1


# ── Operaciones manuales ────────────────────────────────────────────────────────────────────────


@requiere_db
@pytest.mark.asyncio
async def test_aplicar_manual_informar_marca_aplicada(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla = ReglaFake()
    regla.evaluaciones = [_ev(999_920_601)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    (fila,) = await _filas(conn)
    res = await aplicar_manual(sesion, [fila.id, 999_920_699], "operador-qa")
    assert res["aplicados"] == [fila.id]
    assert res["rechazados"] == [{"id": 999_920_699, "motivo": "inexistente"}]
    (fila,) = await _filas(conn)
    assert fila.estado == "APLICADA" and fila.decidida_por == "operador-qa"
    # Ya no es PROPUESTA: un segundo intento se rechaza.
    res = await aplicar_manual(sesion, [fila.id], "operador-qa")
    assert res["aplicados"] == [] and res["rechazados"][0]["motivo"] == "estado_invalido"


@requiere_db
@pytest.mark.asyncio
async def test_aplicar_manual_asociar_y_revertir_manual(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    sid = await _servicio(conn, _NUMEROS[0])
    await _odf(conn)
    regla = ReglaFake()
    regla.evaluaciones = [_ev_odf(sid)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    (fila,) = await _filas(conn)
    assert (await aplicar_manual(sesion, [fila.id], "operador-qa"))["aplicados"] == [fila.id]
    assert [tuple(o) for o in await _overrides(conn, sid)] == [("AUTO", _ODF)]
    (fila,) = await _filas(conn)
    assert fila.estado == "APLICADA" and fila.reversion is not None

    res = await revertir_manual(sesion, [fila.id], "operador-qa")
    assert res["revertidos"] == [fila.id]
    assert (await _filas(conn))[0].estado == "REVERTIDA"
    assert await _overrides(conn, sid) == []


@requiere_db
@pytest.mark.asyncio
async def test_revertir_manual_informar_omitida(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla = ReglaFake()
    regla.evaluaciones = [_ev(999_920_601)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    (fila,) = await _filas(conn)
    await aplicar_manual(sesion, [fila.id], "operador-qa")
    res = await revertir_manual(sesion, [fila.id], "operador-qa")
    assert res["revertidos"] == [] and res["omitidos"][0]["id"] == fila.id
    assert (await _filas(conn))[0].estado == "APLICADA"


@requiere_db
@pytest.mark.asyncio
async def test_rechazar_solo_propuesta(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla = ReglaFake()
    regla.evaluaciones = [_ev(999_920_601), _ev(999_920_602)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    f1, f2 = await _filas(conn)
    await aplicar_manual(sesion, [f2.id], "operador-qa")
    res = await rechazar(sesion, [f1.id, f2.id], "operador-qa")
    assert res["rechazados"] == [f1.id]
    assert res["omitidos"] == [{"id": f2.id, "motivo": "estado_invalido"}]
    estados = [(f.estado, f.decidida_por) for f in await _filas(conn)]
    assert estados == [("RECHAZADA", "operador-qa"), ("APLICADA", "operador-qa")]


async def _insertar_decididas(conn, estado: str, decidida_por: str, n: int, base: int) -> None:
    for i in range(n):
        await conn.execute(
            text(
                "INSERT INTO app.cromo_propuesta (regla, objeto_tipo, objeto_id, accion, confianza, "
                "evidencia_hash, estado, modo_al_evaluar, disparo, decidida_por) "
                "VALUES (:r, 'SERVICIO', :o, 'INFORMAR', 95, :h, :e, 'SOMBRA', 'VIEWER', :d)"
            ),
            {"r": _REGLA, "o": base + i, "h": "0" * 64, "e": estado, "d": decidida_por},
        )


@requiere_db
@pytest.mark.asyncio
async def test_precision_y_sugerir_auto(entorno):
    sesion, conn, _ = entorno
    await _insertar_decididas(conn, "APLICADA", "operador-qa", 30, 999_920_700)
    await _insertar_decididas(conn, "RECHAZADA", "operador-qa", 1, 999_920_800)
    # No cuentan: decisiones del propio árbitro.
    await _insertar_decididas(conn, "APLICADA", USUARIO_ARBITRO, 5, 999_920_850)
    await _insertar_decididas(conn, "REVERTIDA", USUARIO_ARBITRO, 5, 999_920_870)
    filas = {f["codigo"]: f for f in await precision_por_regla(sesion)}
    f = filas[_REGLA]
    assert (f["aceptadas"], f["rechazadas"], f["decididas"]) == (30, 1, 31)
    assert f["precision"] == pytest.approx(30 / 31, abs=1e-3) and f["sugerir_auto"] is True
    assert f["modo"] == "SOMBRA" and f["umbral"] == 90 and f["presupuesto_por_corrida"] == 50
    assert filas[_REGLA_B]["precision"] is None and filas[_REGLA_B]["sugerir_auto"] is False
    assert json.loads(json.dumps(list(filas.values()))) == list(filas.values())


@requiere_db
@pytest.mark.asyncio
async def test_precision_revertida_humana_cuenta_como_rechazo(entorno):
    sesion, conn, _ = entorno
    await _insertar_decididas(conn, "APLICADA", "operador-qa", 29, 999_920_700)
    await _insertar_decididas(conn, "REVERTIDA", "operador-qa", 1, 999_920_800)
    f = {f["codigo"]: f for f in await precision_por_regla(sesion)}[_REGLA]
    assert (f["rechazadas"], f["decididas"]) == (1, 30) and f["sugerir_auto"] is True


@requiere_db
@pytest.mark.asyncio
async def test_listar_propuestas_orden_y_json(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    regla = ReglaFake()
    regla.evaluaciones = [_ev(999_920_601, peso=50), _ev(999_920_602, peso=80)]
    await evaluar(sesion, _TODO, "VIEWER", reglas=[regla])
    res = await listar_propuestas(sesion, regla=_REGLA, estado="PROPUESTA")
    assert res["total"] == 2
    assert [i["objeto_id"] for i in res["items"]] == [999_920_602, 999_920_601]
    item = res["items"][0]
    assert item["senales"] == [{"codigo": "QA", "peso": 80, "detalle": {"d": 1}, "veto": False}]
    assert json.loads(json.dumps(res)) == res
    assert isinstance(item["creada_en"], str)
    assert (await listar_propuestas(sesion, regla=_REGLA, limit=1, offset=1))["items"][0][
        "objeto_id"
    ] == 999_920_601


@requiere_db
@pytest.mark.asyncio
async def test_actualizar_regla_valida(entorno):
    sesion, conn, _ = entorno
    await actualizar_regla(sesion, _REGLA, modo="AUTO", umbral=85, presupuesto_por_corrida=10,
                           usuario="operador-qa")
    fila = (
        await conn.execute(
            text(
                "SELECT modo, umbral, presupuesto_por_corrida, actualizado_por "
                "FROM app.cromo_regla_correccion WHERE codigo = :c"
            ),
            {"c": _REGLA},
        )
    ).one()
    assert tuple(fila) == ("AUTO", 85, 10, "operador-qa")
    for kwargs in (
        {"modo": "OTRO", "umbral": 90, "presupuesto_por_corrida": 1},
        {"modo": "AUTO", "umbral": 101, "presupuesto_por_corrida": 1},
        {"modo": "AUTO", "umbral": True, "presupuesto_por_corrida": 1},
        {"modo": "AUTO", "umbral": 90, "presupuesto_por_corrida": -1},
    ):
        with pytest.raises(ValueError):
            await actualizar_regla(sesion, _REGLA, usuario="qa", **kwargs)
    with pytest.raises(ValueError):
        await actualizar_regla(sesion, "NO_EXISTE", modo="AUTO", umbral=90,
                               presupuesto_por_corrida=1, usuario="qa")
