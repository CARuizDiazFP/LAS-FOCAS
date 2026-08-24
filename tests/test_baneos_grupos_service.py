# Nombre de archivo: test_baneos_grupos_service.py
# Ubicación de archivo: tests/test_baneos_grupos_service.py
# Descripción: Pruebas del listado y liberación masiva de grupos baneados (Cámara padre + Botellas)

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from core.services.baneos_grupos_service import (
    liberar_grupos_masivo,
    listar_grupos_baneados,
)
from core.services.camara_estado_service import ActualizacionEstadoResultado, CamaraEstadoContexto
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado, CamaraEstadoAuditoria


def _sesion_listado(
    raices: list[Camara],
    legado: list[Camara] | None = None,
    cromo: list[CromoBotella] | None = None,
    auditorias: list[CamaraEstadoAuditoria] | None = None,
) -> MagicMock:
    """Sesión mockeada para `listar_grupos_baneados` — 4 "sub-queries" distintas sobre la misma
    `Session`, la 1ra y la 2da ambas sobre `Camara` (raíces, luego botellas legado) — se
    diferencian por orden de invocación, no por modelo, igual que hace el servicio real."""
    legado = legado or []
    cromo = cromo or []
    auditorias = auditorias or []

    raices_query = MagicMock()
    raices_query.filter.return_value = raices_query
    raices_query.count.return_value = len(raices)
    raices_query.order_by.return_value = raices_query
    raices_query.offset.return_value = raices_query
    raices_query.limit.return_value = raices_query
    raices_query.all.return_value = raices

    legado_query = MagicMock()
    legado_query.filter.return_value = legado_query
    legado_query.all.return_value = legado

    cromo_query = MagicMock()
    cromo_query.filter.return_value = cromo_query
    cromo_query.all.return_value = cromo

    auditoria_query = MagicMock()
    auditoria_query.filter.return_value = auditoria_query
    auditoria_query.order_by.return_value = auditoria_query
    auditoria_query.all.return_value = auditorias

    llamadas_camara = {"n": 0}

    def query_side_effect(model, *_a):
        if model is Camara:
            llamadas_camara["n"] += 1
            return raices_query if llamadas_camara["n"] == 1 else legado_query
        if model is CromoBotella:
            return cromo_query
        if model is CamaraEstadoAuditoria:
            return auditoria_query
        raise AssertionError(f"query inesperada sobre {model!r}")

    session = MagicMock()
    session.query.side_effect = query_side_effect
    session.raices_query = raices_query
    session.legado_query = legado_query
    session.cromo_query = cromo_query
    session.auditoria_query = auditoria_query
    return session


def test_listar_grupos_baneados_agrupa_hijos_legado_y_cromo_bajo_su_raiz() -> None:
    raiz1 = Camara(id=1, nombre="Cra Uno CF", direccion=None, fontine_id=None, estado=CamaraEstado.BANEADA)
    raiz2 = Camara(id=2, nombre="Cra Dos CF", direccion=None, fontine_id=None, estado=CamaraEstado.BANEADA)

    bot1 = Camara(id=11, nombre="Cra Uno Bot 11 CF", camara_padre_id=1, estado=CamaraEstado.BANEADA)
    bot2 = Camara(id=21, nombre="Cra Dos Bot 21 CF", camara_padre_id=2, estado=CamaraEstado.BANEADA)

    cb1 = CromoBotella(n_id=101, camara_id=1, nombre="Cromo Uno", estado=CamaraEstado.BANEADA)
    cb2 = CromoBotella(n_id=201, camara_id=2, nombre="Cromo Dos", estado=CamaraEstado.BANEADA)

    session = _sesion_listado([raiz1, raiz2], legado=[bot1, bot2], cromo=[cb1, cb2])

    resultado = listar_grupos_baneados(session, incluir_contexto=False)

    assert resultado.total == 2
    grupo1 = next(g for g in resultado.grupos if g.camara_id == 1)
    grupo2 = next(g for g in resultado.grupos if g.camara_id == 2)

    assert {(b.origen, b.id) for b in grupo1.botellas} == {("legado", 11), ("cromo", 101)}
    assert {(b.origen, b.id) for b in grupo2.botellas} == {("legado", 21), ("cromo", 201)}
    assert grupo1.botellas_count == 2
    assert grupo2.botellas_count == 2


def test_listar_grupos_baneados_toma_auditoria_mas_reciente() -> None:
    raiz = Camara(id=1, nombre="Cra Uno CF", estado=CamaraEstado.BANEADA)

    reciente = CamaraEstadoAuditoria(
        camara_id=1,
        usuario="userB",
        motivo="motivo reciente",
        estado_anterior=CamaraEstado.LIBRE,
        estado_nuevo=CamaraEstado.BANEADA,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    vieja = CamaraEstadoAuditoria(
        camara_id=1,
        usuario="userA",
        motivo="motivo vieja",
        estado_anterior=CamaraEstado.LIBRE,
        estado_nuevo=CamaraEstado.BANEADA,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    # El query real ya viene `order_by(created_at desc())` — el mock simula ese orden.
    session = _sesion_listado([raiz], auditorias=[reciente, vieja])

    resultado = listar_grupos_baneados(session, incluir_contexto=False)

    grupo = resultado.grupos[0]
    assert grupo.motivo == "motivo reciente"
    assert grupo.usuario == "userB"
    assert grupo.fecha == reciente.created_at.isoformat()


def test_listar_grupos_baneados_sin_auditoria_deja_campos_en_none() -> None:
    raiz = Camara(id=1, nombre="Cra Uno CF", estado=CamaraEstado.BANEADA)
    session = _sesion_listado([raiz], auditorias=[])

    resultado = listar_grupos_baneados(session, incluir_contexto=False)

    grupo = resultado.grupos[0]
    assert grupo.motivo is None
    assert grupo.usuario is None
    assert grupo.fecha is None


def test_listar_grupos_baneados_incluir_contexto_false_no_llama_get_contexto() -> None:
    raiz = Camara(id=1, nombre="Cra Uno CF", estado=CamaraEstado.BANEADA)
    session = _sesion_listado([raiz])

    with patch("core.services.baneos_grupos_service.get_camara_estado_contexto") as mock_contexto:
        resultado = listar_grupos_baneados(session, incluir_contexto=False)

    mock_contexto.assert_not_called()
    grupo = resultado.grupos[0]
    assert grupo.tiene_baneo_activo is False
    assert grupo.ticket_baneo is None
    assert grupo.incidentes_activos_ids == []
    assert grupo.puede_liberar is True


def test_listar_grupos_baneados_estado_mixto() -> None:
    raiz_mixta = Camara(id=1, nombre="Cra Uno CF", estado=CamaraEstado.BANEADA)
    raiz_uniforme = Camara(id=2, nombre="Cra Dos CF", estado=CamaraEstado.BANEADA)

    bot_distinta = Camara(id=11, nombre="Cra Uno Bot 11 CF", camara_padre_id=1, estado=CamaraEstado.LIBRE)
    bot_igual = Camara(id=21, nombre="Cra Dos Bot 21 CF", camara_padre_id=2, estado=CamaraEstado.BANEADA)

    session = _sesion_listado([raiz_mixta, raiz_uniforme], legado=[bot_distinta, bot_igual])

    resultado = listar_grupos_baneados(session, incluir_contexto=False)

    grupo_mixto = next(g for g in resultado.grupos if g.camara_id == 1)
    grupo_uniforme = next(g for g in resultado.grupos if g.camara_id == 2)
    assert grupo_mixto.estado_mixto is True
    assert grupo_uniforme.estado_mixto is False


def test_listar_grupos_baneados_limit_none_no_pagina() -> None:
    raices = [Camara(id=i, nombre=f"Cra {i} CF", estado=CamaraEstado.BANEADA) for i in range(1, 4)]
    session = _sesion_listado(raices)

    resultado = listar_grupos_baneados(session, limit=None, offset=10, incluir_contexto=False)

    session.raices_query.limit.assert_not_called()
    session.raices_query.offset.assert_not_called()
    assert resultado.total == 3
    assert len(resultado.grupos) == 3


# ── liberar_grupos_masivo ──────────────────────────────────────────────────


def _camara(id_: int, camara_padre_id: int | None = None) -> Camara:
    return Camara(id=id_, nombre=f"Cra {id_} CF", camara_padre_id=camara_padre_id, estado=CamaraEstado.BANEADA)


def _contexto(*, tiene_baneo_activo: bool, estado_sugerido: CamaraEstado) -> CamaraEstadoContexto:
    return CamaraEstadoContexto(
        camara_id=1,
        estado_actual=CamaraEstado.BANEADA,
        estado_sugerido=estado_sugerido,
        tiene_baneo_activo=tiene_baneo_activo,
        tiene_ingreso_activo=False,
        inconsistente=False,
        incidentes_activos=[],
        ticket_baneo=None,
    )


def test_liberar_grupos_masivo_incidente_activo_sin_forzar_se_omite() -> None:
    camara = _camara(1)
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = camara

    contexto = _contexto(tiene_baneo_activo=True, estado_sugerido=CamaraEstado.BANEADA)

    with patch("core.services.baneos_grupos_service.get_camara_estado_contexto", return_value=contexto), patch(
        "core.services.baneos_grupos_service.override_camara_estado_manual"
    ) as mock_override:
        resultado = liberar_grupos_masivo(session, [1], usuario="admin", motivo="test", forzar=False)

    mock_override.assert_not_called()
    assert resultado.liberados == 0
    assert resultado.omitidos == 1
    assert resultado.detalle[0].razon_omision == "bloqueado_por_incidente"


def test_liberar_grupos_masivo_incidente_activo_con_forzar_libera_a_libre() -> None:
    camara = _camara(1)
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = camara

    contexto = _contexto(tiene_baneo_activo=True, estado_sugerido=CamaraEstado.BANEADA)

    with patch("core.services.baneos_grupos_service.get_camara_estado_contexto", return_value=contexto), patch(
        "core.services.baneos_grupos_service.override_camara_estado_manual"
    ) as mock_override:
        mock_override.return_value = ActualizacionEstadoResultado(success=True, camara_id=1, changed=True)
        resultado = liberar_grupos_masivo(session, [1], usuario="admin", motivo="test", forzar=True)

    mock_override.assert_called_once()
    args, _kwargs = mock_override.call_args
    assert args[1] == 1
    assert args[2] == CamaraEstado.LIBRE
    assert resultado.liberados == 1
    assert resultado.detalle[0].estado_final == "LIBRE"


def test_liberar_grupos_masivo_sin_incidente_usa_estado_sugerido() -> None:
    """Un grupo sin incidente activo pero con un ingreso activo debe liberarse a `OCUPADA`
    (estado_sugerido), no a `LIBRE` hardcodeado."""
    camara = _camara(1)
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = camara

    contexto = _contexto(tiene_baneo_activo=False, estado_sugerido=CamaraEstado.OCUPADA)

    with patch("core.services.baneos_grupos_service.get_camara_estado_contexto", return_value=contexto), patch(
        "core.services.baneos_grupos_service.override_camara_estado_manual"
    ) as mock_override:
        mock_override.return_value = ActualizacionEstadoResultado(success=True, camara_id=1, changed=True)
        resultado = liberar_grupos_masivo(session, [1], usuario="admin", motivo="test", forzar=False)

    args, _kwargs = mock_override.call_args
    assert args[2] == CamaraEstado.OCUPADA
    assert resultado.detalle[0].estado_final == "OCUPADA"


def test_liberar_grupos_masivo_dedup_por_raiz() -> None:
    """Dos ids del mismo grupo (la raíz y una de sus botellas) en la misma llamada — se libera una
    sola vez."""
    padre = _camara(1, camara_padre_id=None)
    botella = _camara(2, camara_padre_id=1)

    session = MagicMock()
    session.query.return_value.filter.return_value.first.side_effect = [padre, botella]

    contexto = _contexto(tiene_baneo_activo=False, estado_sugerido=CamaraEstado.LIBRE)

    with patch("core.services.baneos_grupos_service.get_camara_estado_contexto", return_value=contexto), patch(
        "core.services.baneos_grupos_service.override_camara_estado_manual"
    ) as mock_override:
        mock_override.return_value = ActualizacionEstadoResultado(success=True, camara_id=1, changed=True)
        resultado = liberar_grupos_masivo(session, [1, 2], usuario="admin", motivo="test")

    mock_override.assert_called_once()
    assert mock_override.call_args[0][1] == 1
    assert resultado.total_solicitados == 2
    assert resultado.liberados == 1
    assert len(resultado.detalle) == 1
