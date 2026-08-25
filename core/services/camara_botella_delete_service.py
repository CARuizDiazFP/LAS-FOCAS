# Nombre de archivo: camara_botella_delete_service.py
# Ubicación de archivo: core/services/camara_botella_delete_service.py
# Descripción: Eliminación permanente de Cámaras/Botellas genuinamente vacías (basura de backfills), con bloqueo si tienen datos reales asociados y registro automático de exclusión Cromo

"""Cierra el pedido de limpiar basura heredada de backfills viejos (Botellas Cromo con nombre "0",
sin cables asociados; Cámaras padre sintéticas que quedaron sin nada más). Política confirmada
explícitamente por el usuario: **bloquear, nunca forzar** — si el elemento (o, para una Cámara,
cualquiera de sus hijos) tiene Cables/Empalmes/Ingresos reales asociados, la eliminación se rechaza
sin borrar nada; y **todo o nada** para `eliminar_camara` — un solo hijo bloqueado aborta la
operación completa, sin dejar nada a mitad de camino.

Mismo esqueleto que `camara_merge_service.py`/`botella_merge_service.py` (sesión síncrona,
`sqlalchemy.orm.Session`), pero sin sobreviviente: acá no hay a quién reasignarle las FKs, así que en
vez de "reasignar y borrar" el criterio es "verificar que no haga falta reasignar nada, y recién
entonces borrar". `eliminar_botella` reusa literalmente `eliminar_camara` para el paso "¿el padre
quedó vacío?" — evita mantener dos implementaciones del mismo criterio "¿esto está vacío?" que puedan
divergir con el tiempo, y de paso hereda gratis el mismo fail-safe contra los 6 casos reales conocidos
que violan el invariante de 2 niveles (ver `botella_merge_service.py`): un padre que resulta ser él
mismo una Botella se rechaza (`camara_padre_id is not None`), nunca se toca.

Sin sobreviviente también significa sin rastro de auditoría en DB: `CamaraEstadoAuditoria` cascadea
(`ondelete=CASCADE`) junto con la fila borrada — a diferencia de `unificar_camaras`/
`apropiar_legado_a_cromo`, que siempre dejan un evento en el sobreviviente. Queda sólo el
`logger.info(...)` del endpoint. Aceptado como limitación conocida — no se pidió una tabla de
auditoría nueva."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.services.cromo.alias_service import ACCION_IGNORAR
from db.models.cromo import CromoBotella, CromoBotellaAlias, CromoCable, CromoFusion
from db.models.infra import Cable, Camara, Empalme, Ingreso


@dataclass(slots=True)
class BloqueoDetalle:
    origen: str  # "legado" | "cromo" | "camara"
    id: int
    nombre: Optional[str]
    razon: str


class EliminacionBloqueadaError(Exception):
    """Error de validación — el llamador (endpoint) debe traducirlo a un 400, no a un 500."""

    def __init__(self, mensaje: str, bloqueos: Optional[list[BloqueoDetalle]] = None) -> None:
        super().__init__(mensaje)
        self.bloqueos = bloqueos or []


@dataclass(slots=True)
class ResultadoEliminacionBotella:
    origen: str
    id: int
    camara_padre_eliminada: Optional[int] = None
    alias_registrado: bool = False


@dataclass(slots=True)
class ResultadoEliminacionCamara:
    camara_id: int
    botellas_legado_eliminadas: int = 0
    botellas_cromo_eliminadas: int = 0
    aliases_registrados: int = 0


@dataclass(slots=True)
class ResultadoEliminacionGrupoCromo:
    ids_solicitados: list[int]
    botellas_eliminadas: list[int] = field(default_factory=list)
    cables_eliminados: int = 0
    fusiones_eliminadas: int = 0
    aliases_registrados: int = 0
    no_encontradas: list[int] = field(default_factory=list)


def _bloqueo_camara(
    session: Session, camara_id: int, *, origen_etiqueta: str = "legado", nombre: Optional[str] = None
) -> Optional[BloqueoDetalle]:
    """¿Esta fila `Camara` (raíz o con forma de Botella) tiene Cables/Empalmes/Ingresos REALES
    apuntándole DIRECTAMENTE — nunca vía hijos, eso lo chequea el llamador aparte."""
    razones: list[str] = []
    if (
        session.query(Cable)
        .filter(or_(Cable.origen_camara_id == camara_id, Cable.destino_camara_id == camara_id))
        .first()
        is not None
    ):
        razones.append("tiene cables asociados")
    if session.query(Empalme).filter(Empalme.camara_id == camara_id).first() is not None:
        razones.append("tiene empalmes asociados")
    if session.query(Ingreso).filter(Ingreso.camara_id == camara_id).first() is not None:
        razones.append("tiene ingresos asociados")
    if not razones:
        return None
    return BloqueoDetalle(origen=origen_etiqueta, id=camara_id, nombre=nombre, razon="; ".join(razones))


def _bloqueo_cromo_botella(session: Session, n_id: int) -> Optional[BloqueoDetalle]:
    """¿Este n_id de Cromo tiene cables/fusiones Cromo reales asociados, o ya es el destino de una
    fusión previa (otro alias ya lo usa como "golden record")? `CromoCable`/`CromoFusion` — NO
    `Cable`/`Empalme` (tablas de la jerarquía legado, espacio de ids completamente distinto)."""
    if (
        session.query(CromoCable)
        .filter(or_(CromoCable.extremo_a_n_id == n_id, CromoCable.extremo_b_n_id == n_id))
        .first()
        is not None
    ):
        return BloqueoDetalle(origen="cromo", id=n_id, nombre=None, razon="tiene cables Cromo asociados")
    if session.query(CromoFusion).filter(CromoFusion.botella_n_id == n_id).first() is not None:
        return BloqueoDetalle(origen="cromo", id=n_id, nombre=None, razon="tiene fusiones Cromo asociadas")
    if session.query(CromoBotellaAlias).filter(CromoBotellaAlias.id_cromo_destino == n_id).first() is not None:
        return BloqueoDetalle(
            origen="cromo", id=n_id, nombre=None, razon="es destino de otra fila de alias (fusión previa)"
        )
    return None


def _registrar_alias_ignorar(session: Session, n_id: int, usuario: str) -> None:
    """Upsert-por-origen en `CromoBotellaAlias` — mismo patrón exacto que
    `core/services/cromo/consolidacion_service.py`: crea si no existía, actualiza in-place si ya
    había una fila (una corrección legítima, no un error)."""
    motivo = f"Eliminado manualmente por {usuario}"
    existente = session.query(CromoBotellaAlias).filter(CromoBotellaAlias.id_cromo_origen == n_id).first()
    if existente is None:
        session.add(
            CromoBotellaAlias(
                id_cromo_origen=n_id,
                id_cromo_destino=None,
                accion=ACCION_IGNORAR,
                motivo=motivo,
                creado_por=usuario,
            )
        )
        return
    existente.accion = ACCION_IGNORAR
    existente.id_cromo_destino = None
    existente.motivo = motivo
    existente.creado_por = usuario


def eliminar_botella(session: Session, *, origen: str, id: int, usuario: str) -> ResultadoEliminacionBotella:
    if origen not in ("legado", "cromo"):
        raise EliminacionBloqueadaError(f"Origen inválido: '{origen}' (debe ser 'legado' o 'cromo')")

    alias_registrado = False
    if origen == "cromo":
        cromo = session.query(CromoBotella).filter(CromoBotella.n_id == id).first()
        if cromo is None:
            raise EliminacionBloqueadaError(f"No existe una Botella Cromo con n_id={id}")
        bloqueo = _bloqueo_cromo_botella(session, id)
        if bloqueo is not None:
            raise EliminacionBloqueadaError(f"No se puede eliminar: {bloqueo.razon}", [bloqueo])

        camara_padre_id = cromo.camara_id
        _registrar_alias_ignorar(session, id, usuario)
        session.delete(cromo)
        alias_registrado = True
    else:
        legado = session.query(Camara).filter(Camara.id == id).first()
        if legado is None:
            raise EliminacionBloqueadaError(f"No existe una Cámara/Botella con id={id}")
        if legado.camara_padre_id is None:
            raise EliminacionBloqueadaError("La fila indicada no es una Botella (no tiene Cámara padre)")
        bloqueo = _bloqueo_camara(session, id, nombre=legado.nombre)
        if bloqueo is not None:
            raise EliminacionBloqueadaError(f"No se puede eliminar: {bloqueo.razon}", [bloqueo])

        camara_padre_id = legado.camara_padre_id
        session.delete(legado)

    # Flush obligatorio antes de intentar limpiar el padre: con autoflush=False (AsyncSessionLocal/
    # SessionLocal, ver db/session.py), sin este flush la comprobación de "¿el padre quedó vacío?"
    # de más abajo todavía vería esta fila recién borrada como un hijo vigente.
    session.flush()

    camara_padre_eliminada: Optional[int] = None
    if camara_padre_id is not None:
        try:
            eliminar_camara(session, camara_id=camara_padre_id, usuario=usuario)
            camara_padre_eliminada = camara_padre_id
        except EliminacionBloqueadaError:
            # El padre sobrevive con otros datos reales (u otros hijos) — es lo esperado, no un error.
            pass

    return ResultadoEliminacionBotella(
        origen=origen, id=id, camara_padre_eliminada=camara_padre_eliminada, alias_registrado=alias_registrado
    )


def eliminar_camara(session: Session, *, camara_id: int, usuario: str) -> ResultadoEliminacionCamara:
    camara = session.query(Camara).filter(Camara.id == camara_id).first()
    if camara is None:
        raise EliminacionBloqueadaError(f"No existe una Cámara con id={camara_id}")
    if camara.camara_padre_id is not None:
        raise EliminacionBloqueadaError(
            "La fila indicada es una Botella, no una Cámara raíz — usá eliminar_botella"
        )

    hijos_legado = session.query(Camara).filter(Camara.camara_padre_id == camara_id).all()
    hijos_cromo = session.query(CromoBotella).filter(CromoBotella.camara_id == camara_id).all()

    # Recolectar TODOS los bloqueos antes de tocar la sesión — todo o nada real: si algo bloquea,
    # no se ejecutó ningún session.delete/add todavía.
    bloqueos: list[BloqueoDetalle] = []
    for hijo in hijos_legado:
        bloqueo = _bloqueo_camara(session, hijo.id, nombre=hijo.nombre)
        if bloqueo is not None:
            bloqueos.append(bloqueo)
    for cromo_hijo in hijos_cromo:
        bloqueo = _bloqueo_cromo_botella(session, cromo_hijo.n_id)
        if bloqueo is not None:
            bloqueos.append(bloqueo)
    bloqueo_raiz = _bloqueo_camara(session, camara_id, origen_etiqueta="camara", nombre=camara.nombre)
    if bloqueo_raiz is not None:
        bloqueos.append(bloqueo_raiz)

    if bloqueos:
        raise EliminacionBloqueadaError(
            f"No se puede eliminar la Cámara: {len(bloqueos)} elemento(s) tienen datos reales asociados",
            bloqueos,
        )

    for cromo_hijo in hijos_cromo:
        _registrar_alias_ignorar(session, cromo_hijo.n_id, usuario)
        session.delete(cromo_hijo)
    for hijo in hijos_legado:
        session.delete(hijo)
    session.flush()

    session.delete(camara)
    session.flush()

    return ResultadoEliminacionCamara(
        camara_id=camara_id,
        botellas_legado_eliminadas=len(hijos_legado),
        botellas_cromo_eliminadas=len(hijos_cromo),
        aliases_registrados=len(hijos_cromo),
    )


def eliminar_y_excluir_grupo_cromo(
    session: Session, *, ids_cromo: list[int], usuario: str
) -> ResultadoEliminacionGrupoCromo:
    """Borrado físico FORZADO de un grupo de `CromoBotella` conflictivas — exclusivo para el botón
    "Borrar y Excluir Cromo" del visor de duplicados. A diferencia de `eliminar_botella`/
    `eliminar_camara`, NUNCA bloquea por Cables/Fusiones reales asociados: es deliberadamente el
    único camino de este módulo que ignora la política "bloquear, nunca forzar" del 2026-08-20 —
    ambas funciones individuales quedan intactas, sin flag de bypass.

    Borra también los `CromoCable`/`CromoFusion` asociados (sin FK dura, la limpieza es explícita) y
    registra cada n_id en `cromo_botella_alias` (`accion='ignorar'`, vía `_registrar_alias_ignorar`)
    para que la ingesta no las resucite. No intenta limpiar la Cámara padre si quedó vacía — no fue
    pedido, y mezclarlo con un borrado sin bloqueos daría una garantía distinta a la de
    `eliminar_botella`."""
    ids_unicos = list(dict.fromkeys(ids_cromo))
    if not ids_unicos:
        raise EliminacionBloqueadaError("No se indicó ninguna Botella Cromo para eliminar.")

    encontradas = session.query(CromoBotella).filter(CromoBotella.n_id.in_(ids_unicos)).all()
    ids_existentes = {b.n_id for b in encontradas}
    no_encontradas = [n_id for n_id in ids_unicos if n_id not in ids_existentes]

    cables_eliminados = (
        session.query(CromoCable)
        .filter(or_(CromoCable.extremo_a_n_id.in_(ids_unicos), CromoCable.extremo_b_n_id.in_(ids_unicos)))
        .delete(synchronize_session=False)
    )
    fusiones_eliminadas = (
        session.query(CromoFusion)
        .filter(CromoFusion.botella_n_id.in_(ids_unicos))
        .delete(synchronize_session=False)
    )

    for botella in encontradas:
        _registrar_alias_ignorar(session, botella.n_id, usuario)
        session.delete(botella)

    session.flush()

    return ResultadoEliminacionGrupoCromo(
        ids_solicitados=ids_unicos,
        botellas_eliminadas=[b.n_id for b in encontradas],
        cables_eliminados=cables_eliminados,
        fusiones_eliminadas=fusiones_eliminadas,
        aliases_registrados=len(encontradas),
        no_encontradas=no_encontradas,
    )


__all__ = [
    "BloqueoDetalle",
    "EliminacionBloqueadaError",
    "ResultadoEliminacionBotella",
    "ResultadoEliminacionCamara",
    "ResultadoEliminacionGrupoCromo",
    "eliminar_botella",
    "eliminar_camara",
    "eliminar_y_excluir_grupo_cromo",
]
