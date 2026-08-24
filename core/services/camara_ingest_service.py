# Nombre de archivo: camara_ingest_service.py
# Ubicación de archivo: core/services/camara_ingest_service.py
# Descripción: Servicio síncrono para ingesta masiva de cámaras desde Excel y baneo administrativo

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from db.models.infra import Camara, CamaraAlias, CamaraEstado, IngresoSinMatch
from db.session import SessionLocal
from core.services.camara_estado_service import override_camara_estado_manual

logger = logging.getLogger(__name__)

# Origen registrado en `IngresoSinMatch.origen` para los casos generados por este servicio —
# distingue esta fuente de "slack" y "tracking" (ver `core/services/infra_service.py`).
ORIGEN_EXCEL_CAMARAS = "excel_camaras"


@dataclass(slots=True)
class NombreSinMatch:
    """Un alias del Excel que no matcheó contra ninguna `Camara`/`CromoBotella` — queda registrado
    como `IngresoSinMatch` para revisión manual (ver `asociar_nombres_a_camara`)."""

    caso_id: int  # id de app.ingresos_sin_match
    nombre: str  # texto_original — lo único que se muestra en el visor del frontend


@dataclass(slots=True)
class CamaraIngestaResultado:
    """Resultado del procesamiento de ingesta masiva de cámaras."""

    total_leidos: int = 0
    grupos_baneados: int = 0  # grupos que transicionaron a BANEADA en esta corrida
    grupos_ya_baneados: int = 0  # matchearon pero el grupo ya estaba BANEADA
    sin_match: list[NombreSinMatch] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConflictoAsociacion:
    """Un `caso_id` de `asociar_nombres_a_camara` cuyo texto ya está aliasado a OTRA cámara — no se
    reasigna automáticamente, queda para que el admin decida."""

    caso_id: int
    nombre: str
    camara_actual_id: int
    camara_actual_nombre: str


@dataclass(slots=True)
class AsociacionManualResultado:
    """Resultado de `asociar_nombres_a_camara`."""

    ok: bool
    camara_id: int
    camara_nombre: str
    estado_final: str
    baneo_aplicado: bool  # True si `override_camara_estado_manual` reportó changed=True
    alias_creados: int
    alias_preexistentes: int  # alias ya existía apuntando a la misma cámara — no-op idempotente
    casos_marcados: int
    conflictos: list[ConflictoAsociacion] = field(default_factory=list)
    error: str | None = None  # cámara no encontrada, o el baneo final falló (alias/casos ya aplicados igual)


def _registrar_sin_match(
    session: Session,
    nombre: str,
    motivo_baneo: str,
    usuario: str,
    archivo_origen: str | None,
) -> NombreSinMatch:
    """Registra (o reusa, si ya existe uno idéntico pendiente de revisión) un `IngresoSinMatch`
    para `nombre` — nunca crea una `Camara`. Idempotente dentro de un mismo lote y entre corridas:
    dos alias iguales del mismo Excel, o el mismo alias en dos uploads distintos mientras el caso
    anterior siga sin revisar, comparten una única fila."""
    texto = nombre.strip()[:512]

    existente = (
        session.query(IngresoSinMatch)
        .filter(
            IngresoSinMatch.origen == ORIGEN_EXCEL_CAMARAS,
            IngresoSinMatch.texto_original == texto,
            IngresoSinMatch.revisado == False,  # noqa: E712
        )
        .first()
    )
    if existente is not None:
        logger.info(
            "action=camara_ingest_sin_match_reusado caso_id=%d nombre=%s usuario=%s",
            existente.id,
            texto,
            usuario,
        )
        return NombreSinMatch(caso_id=existente.id, nombre=texto)

    if archivo_origen is not None:
        contexto = f"{archivo_origen} | motivo: {motivo_baneo}"
    else:
        contexto = f"motivo: {motivo_baneo}"

    caso = IngresoSinMatch(
        texto_original=texto,
        origen=ORIGEN_EXCEL_CAMARAS,
        contexto=contexto,
    )
    session.add(caso)
    session.flush()  # obtener el id generado

    logger.info(
        "action=camara_ingest_sin_match_nuevo caso_id=%d nombre=%s usuario=%s",
        caso.id,
        texto,
        usuario,
    )
    return NombreSinMatch(caso_id=caso.id, nombre=texto)


def _procesar_ingesta_camaras_en_sesion(
    session: Session,
    aliases: list[str],
    motivo_baneo: str,
    usuario: str,
    *,
    archivo_origen: str | None = None,
) -> CamaraIngestaResultado:
    """Núcleo testeable de `procesar_ingesta_camaras` — recibe la `Session` ya abierta (el caller
    maneja commit/rollback/close), lo que permite testear con una `Session` `MagicMock()` sin tocar
    la base real."""
    resultado = CamaraIngestaResultado(total_leidos=len(aliases))
    raices_procesadas_en_lote: set[int] = set()

    # Import diferido: evita cargar el paquete `core.services.cromo` (que a su vez importa
    # CromoClient/httpx vía su `__init__.py`) en cada arranque que sólo necesita este servicio —
    # mismo criterio que `infra_service.py::_resolve_camara_o_registrar_sin_match`.
    from core.services.cromo.camara_botella_busqueda import buscar_camara_o_botella_cromo
    from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError

    for alias in aliases:
        try:
            try:
                match = buscar_camara_o_botella_cromo(alias, session)
                camara = match.camara
            except AmbiguousSearchError:
                # Nombre insuficientemente específico o múltiples candidatas: nunca desambiguamos
                # a ciegas en un lote masivo, se trata igual que "sin match".
                camara = None

            if camara is None:
                sin_match = _registrar_sin_match(session, alias, motivo_baneo, usuario, archivo_origen)
                resultado.sin_match.append(sin_match)
                continue

            ban_result = override_camara_estado_manual(
                session, camara.id, CamaraEstado.BANEADA, usuario=usuario, motivo=motivo_baneo,
            )
            if not ban_result.success:
                resultado.errores.append(f"{alias}: {ban_result.error or 'baneo fallido'}")
                logger.warning(
                    "action=camara_ingest_baneo_error alias=%s camara_id=%d error=%s",
                    alias,
                    camara.id,
                    ban_result.error,
                )
                continue

            logger.info(
                "action=camara_ingest_baneo alias=%s camara_id=%d changed=%s usuario=%s",
                alias,
                camara.id,
                ban_result.changed,
                usuario,
            )

            # Dedup por raíz de grupo: si dos alias del lote resuelven al mismo grupo, sólo el
            # primero cuenta en grupos_baneados/grupos_ya_baneados — el segundo ya encuentra el
            # grupo baneado por la cascada de `override_camara_estado_manual` y no debe inflar
            # el conteo.
            raiz_id = camara.camara_padre_id or camara.id
            if raiz_id not in raices_procesadas_en_lote:
                raices_procesadas_en_lote.add(raiz_id)
                if ban_result.changed:
                    resultado.grupos_baneados += 1
                else:
                    resultado.grupos_ya_baneados += 1
        except Exception as exc:  # noqa: BLE001
            resultado.errores.append(f"{alias}: {exc!s}")
            logger.exception(
                "action=camara_ingest_alias_error alias=%s usuario=%s error=%s",
                alias,
                usuario,
                exc,
            )

    logger.info(
        "action=camara_ingest_procesado usuario=%s total_leidos=%d grupos_baneados=%d "
        "grupos_ya_baneados=%d sin_match=%d errores=%d",
        usuario,
        resultado.total_leidos,
        resultado.grupos_baneados,
        resultado.grupos_ya_baneados,
        len(resultado.sin_match),
        len(resultado.errores),
    )
    return resultado


def procesar_ingesta_camaras(
    aliases: list[str],
    motivo_baneo: str,
    usuario: str,
    *,
    archivo_origen: str | None = None,
) -> CamaraIngestaResultado:
    """Procesa una lista de aliases de cámaras desde un Excel de baneo masivo: resuelve cada uno
    contra el inventario real (`Camara`/`CromoBotella`, vía `buscar_camara_o_botella_cromo`) y
    aplica baneo administrativo (BANEADA) a los que matchean. **Nunca crea una `Camara` nueva** —
    Cromo Red es la fuente de verdad del inventario; un alias sin match queda registrado en
    `IngresoSinMatch` para revisión manual (ver `asociar_nombres_a_camara`), no se da de alta una
    cámara a partir del Excel.

    Args:
        aliases: Lista de identificadores/aliases de cámaras leídos del Excel.
        motivo_baneo: Texto obligatorio que describe el motivo del baneo masivo.
        usuario: Nombre del usuario admin que ejecuta la operación.
        archivo_origen: Nombre del archivo Excel origen (contexto de los `IngresoSinMatch`).

    Returns:
        CamaraIngestaResultado con conteos de operaciones realizadas.
    """
    session: Session = SessionLocal()
    try:
        resultado = _procesar_ingesta_camaras_en_sesion(
            session, aliases, motivo_baneo, usuario, archivo_origen=archivo_origen,
        )
        session.commit()
        return resultado
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def asociar_nombres_a_camara(
    session: Session,
    *,
    caso_ids: list[int],
    camara_id: int,
    motivo: str,
    usuario: str,
) -> AsociacionManualResultado:
    """Resuelve a mano uno o más `IngresoSinMatch` (`origen=ORIGEN_EXCEL_CAMARAS`) hacia una
    `Camara` existente: crea un `CamaraAlias` por cada texto que no lo tenga ya, marca los casos
    como revisados, y banea la cámara destino una sola vez. Nunca reasigna un alias que ya apunta a
    otra cámara — ese caso queda en `conflictos` sin marcar revisado, para que el admin decida.

    Args:
        session: Sesión de SQLAlchemy activa (el caller maneja commit — igual que el resto de
            servicios del repo que reciben una sesión ya abierta).
        caso_ids: Ids de `IngresoSinMatch` a resolver.
        camara_id: Id de la `Camara` destino.
        motivo: Motivo del baneo aplicado a la cámara destino.
        usuario: Usuario admin que ejecuta la asociación.

    Returns:
        AsociacionManualResultado con los conteos de la operación. `ok=False` únicamente si
        `camara_id` no existe (no lanza excepción para ese caso esperado).
    """
    camara = session.query(Camara).filter(Camara.id == camara_id).first()
    if camara is None:
        return AsociacionManualResultado(
            ok=False,
            camara_id=camara_id,
            camara_nombre="",
            estado_final="",
            baneo_aplicado=False,
            alias_creados=0,
            alias_preexistentes=0,
            casos_marcados=0,
            error="Cámara no encontrada",
        )

    resultado = AsociacionManualResultado(
        ok=True,
        camara_id=camara.id,
        camara_nombre=camara.nombre,
        estado_final=camara.estado.value if camara.estado else "",
        baneo_aplicado=False,
        alias_creados=0,
        alias_preexistentes=0,
        casos_marcados=0,
    )

    casos = (
        session.query(IngresoSinMatch)
        .filter(
            IngresoSinMatch.id.in_(caso_ids),
            IngresoSinMatch.origen == ORIGEN_EXCEL_CAMARAS,
        )
        .all()
    )

    for caso in casos:
        texto = caso.texto_original[:255]  # CamaraAlias.alias_nombre es más corto que texto_original

        alias_existente = (
            session.query(CamaraAlias)
            .filter(CamaraAlias.alias_nombre == texto)
            .first()
        )

        if alias_existente is None:
            session.add(CamaraAlias(camara_id=camara.id, alias_nombre=texto))
            resultado.alias_creados += 1
            caso.revisado = True
            resultado.casos_marcados += 1
        elif alias_existente.camara_id == camara.id:
            # Mismo target, no hay ambigüedad — no-op idempotente.
            resultado.alias_preexistentes += 1
            caso.revisado = True
            resultado.casos_marcados += 1
        else:
            resultado.conflictos.append(
                ConflictoAsociacion(
                    caso_id=caso.id,
                    nombre=texto,
                    camara_actual_id=alias_existente.camara_id,
                    camara_actual_nombre=alias_existente.camara.nombre,
                )
            )
            logger.warning(
                "action=camara_ingest_asociacion_conflicto caso_id=%d nombre=%s "
                "camara_destino_id=%d camara_actual_id=%d usuario=%s",
                caso.id,
                texto,
                camara.id,
                alias_existente.camara_id,
                usuario,
            )

    ban_result = override_camara_estado_manual(
        session, camara.id, CamaraEstado.BANEADA, usuario=usuario, motivo=motivo,
    )
    resultado.baneo_aplicado = ban_result.changed
    if ban_result.success:
        resultado.estado_final = CamaraEstado.BANEADA.value
    else:
        resultado.error = ban_result.error or "baneo fallido"
        logger.warning(
            "action=camara_ingest_asociacion_baneo_error camara_id=%d error=%s usuario=%s",
            camara.id,
            ban_result.error,
            usuario,
        )

    session.flush()

    logger.info(
        "action=camara_ingest_asociacion camara_id=%d usuario=%s alias_creados=%d "
        "alias_preexistentes=%d casos_marcados=%d conflictos=%d baneo_aplicado=%s",
        camara.id,
        usuario,
        resultado.alias_creados,
        resultado.alias_preexistentes,
        resultado.casos_marcados,
        len(resultado.conflictos),
        resultado.baneo_aplicado,
    )

    return resultado


__all__ = [
    "ORIGEN_EXCEL_CAMARAS",
    "AsociacionManualResultado",
    "CamaraIngestaResultado",
    "ConflictoAsociacion",
    "NombreSinMatch",
    "asociar_nombres_a_camara",
    "procesar_ingesta_camaras",
]
