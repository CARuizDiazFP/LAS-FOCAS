# Nombre de archivo: clientes.py
# Ubicación de archivo: api/app/routes/clientes.py
# Descripción: Endpoints internos de categoría por cliente: listado, cambio, lista oficial, alias, fusión y sync

"""Router interno `/clientes` (detrás de la API key, lo consume el proxy admin de `web/app/main.py`).

Toda la lógica vive en `core/services/clientes_categoria_service.py`, que es sync y no commitea:
cada endpoint la corre en un thread aparte con su propia `SessionLocal` (mismo patrón que
`PATCH /servicios/bulk-categoria`) y commitea sólo si la operación escribe y terminó bien.

Errores: `ClienteNoEncontradoError` → 404; cualquier otro `CategoriaInvalidaError` (incluye
`ClienteCategoriaError`) → 400. El usuario que audita los cambios llega en el header `X-Usuario`
(lo pone el proxy web con el usuario de la sesión).

Lista oficial (`/lista/previsualizar` y `/lista/aplicar`): un mismo endpoint acepta
`multipart/form-data` (`file` .xlsx/.xlsm/.csv/.txt de hasta 5 MB + `categoria` + `modo`) o JSON
`{nombres, categoria, modo}`; se elige por `Content-Type`. En el form, `categoria` vacía o `sin`
= sin categorizar. `aplicar` recibe la lista completa y vuelve a resolverla en el servidor: nunca
aplica un diff armado por el cliente.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Literal, TypeVar

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from core.parsers.lista_clientes import EXTENSIONES_LISTA, FormatoNoSoportadoError, extraer_nombres_lista
from core.services.clientes_categoria_service import (
    ClienteNoEncontradoError,
    agregar_alias,
    aplicar_lista,
    cambiar_categoria,
    fusionar_clientes,
    listar_clientes_por_categoria,
    previsualizar_lista,
    quitar_alias,
    sincronizar_categorias,
)
from core.services.servicios_categoria_service import CategoriaInvalidaError
from db.session import SessionLocal

router = APIRouter(prefix="/clientes", tags=["clientes"])
logger = logging.getLogger(__name__)

TAMANO_MAXIMO_LISTA = 5 * 1024 * 1024  # 5 MB

T = TypeVar("T")


async def _ejecutar(operacion: Callable[[Session], T], *, commit: bool) -> T:
    """Corre `operacion` en un thread con su propia sesión sync; commitea si `commit`. Traduce los
    errores de dominio a HTTP (404 / 400) — en ese caso la sesión se cierra sin commit."""

    def _correr() -> T:
        with SessionLocal() as session:
            resultado = operacion(session)
            if commit:
                session.commit()
            return resultado

    try:
        return await asyncio.to_thread(_correr)
    except ClienteNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CategoriaInvalidaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── Listado y cambio de categoría ───────────────────────────────────────────


@router.get("/por-categoria")
async def listar_por_categoria() -> dict[str, Any]:
    """Clientes agrupados por categoría (`"6"`…`"0"`, `"sin"`), con alias y conteo de servicios."""
    grupos = await _ejecutar(listar_clientes_por_categoria, commit=False)
    return {"grupos": grupos}


class CambiarCategoriaRequest(BaseModel):
    cliente_ids: list[int]
    categoria: int | None = None
    automatico: bool = False


@router.patch("/categoria")
async def cambiar_categoria_clientes(
    body: CambiarCategoriaRequest,
    usuario: str | None = Header(default=None, alias="X-Usuario"),
) -> dict[str, Any]:
    """Fija la categoría (`MANUAL`; `null` = sin categorizar) de uno o varios clientes, o con
    `automatico=true` los devuelve al cálculo automático. Propaga a sus servicios."""
    return await _ejecutar(
        lambda s: cambiar_categoria(s, body.cliente_ids, body.categoria, usuario, automatico=body.automatico),
        commit=True,
    )


# ─── Lista oficial ───────────────────────────────────────────────────────────


class ListaRequest(BaseModel):
    nombres: list[str]
    categoria: int | None = None
    modo: Literal["agregar", "reemplazar"] = "agregar"


def _categoria_de_form(valor: Any) -> int | None:
    texto = str(valor or "").strip().lower()
    if texto in ("", "sin"):
        return None
    try:
        return int(texto)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="categoria inválida") from exc


async def _leer_pedido_lista(request: Request) -> ListaRequest:
    """`ListaRequest` desde multipart (archivo) o JSON, según el `Content-Type`."""
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        archivo = form.get("file")
        if not isinstance(archivo, UploadFile) or not archivo.filename:
            raise HTTPException(status_code=400, detail="Falta el archivo de la lista")
        if not archivo.filename.lower().endswith(EXTENSIONES_LISTA):
            raise HTTPException(status_code=415, detail="Formato no soportado (use .xlsx, .csv o .txt)")
        contenido = await archivo.read(TAMANO_MAXIMO_LISTA + 1)
        if len(contenido) > TAMANO_MAXIMO_LISTA:
            raise HTTPException(status_code=413, detail="El archivo supera los 5 MB")
        try:
            nombres = extraer_nombres_lista(archivo.filename, contenido)
        except FormatoNoSoportadoError as exc:
            raise HTTPException(status_code=415, detail="Formato no soportado (use .xlsx, .csv o .txt)") from exc
        except Exception as exc:  # noqa: BLE001 — planilla corrupta / encoding inválido
            logger.warning("action=clientes_lista_read_error archivo=%s error=%s", archivo.filename, exc)
            raise HTTPException(status_code=400, detail="No se pudo leer el archivo") from exc
        datos: dict[str, Any] = {"nombres": nombres, "categoria": _categoria_de_form(form.get("categoria"))}
        modo = str(form.get("modo") or "").strip()
        if modo:
            datos["modo"] = modo
    else:
        try:
            datos = await request.json()
        except Exception as exc:  # noqa: BLE001 — cuerpo vacío o JSON inválido
            raise HTTPException(status_code=400, detail="Cuerpo JSON inválido") from exc
    try:
        return ListaRequest.model_validate(datos)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Pedido de lista inválido: {exc.errors()}") from exc


@router.post("/lista/previsualizar")
async def previsualizar_lista_clientes(request: Request) -> dict[str, Any]:
    """Diff de aplicar la lista (sube / baja / sin cambio / nuevos / sugerencias / quitados). No escribe."""
    pedido = await _leer_pedido_lista(request)
    previa = await _ejecutar(
        lambda s: previsualizar_lista(s, pedido.nombres, pedido.categoria, pedido.modo), commit=False
    )
    return previa.to_dict()


@router.post("/lista/aplicar")
async def aplicar_lista_clientes(
    request: Request,
    usuario: str | None = Header(default=None, alias="X-Usuario"),
) -> dict[str, Any]:
    """Aplica la lista: re-resuelve los nombres en el servidor (mismo cálculo que `previsualizar`)."""
    pedido = await _leer_pedido_lista(request)
    return await _ejecutar(
        lambda s: aplicar_lista(s, pedido.nombres, pedido.categoria, pedido.modo, usuario=usuario),
        commit=True,
    )


# ─── Fusión, alias y sincronización ──────────────────────────────────────────


class FusionarRequest(BaseModel):
    destino_id: int
    origen_ids: list[int] = Field(min_length=1)


@router.post("/fusionar")
async def fusionar(body: FusionarRequest) -> dict[str, Any]:
    """Mueve los alias de `origen_ids` al destino y borra los clientes origen."""
    return await _ejecutar(lambda s: fusionar_clientes(s, body.destino_id, body.origen_ids), commit=True)


class AliasRequest(BaseModel):
    nombre: str


@router.post("/{cliente_id}/alias")
async def agregar_alias_cliente(cliente_id: int, body: AliasRequest) -> dict[str, Any]:
    """Vincula un nombre como alias (`MANUAL`) del cliente."""

    def _agregar(session: Session) -> dict[str, Any]:
        alias = agregar_alias(session, cliente_id, body.nombre)
        return {
            "id": alias.id,
            "cliente_id": alias.cliente_id,
            "clave": alias.clave,
            "nombre_original": alias.nombre_original,
            "origen": alias.origen,
        }

    return await _ejecutar(_agregar, commit=True)


@router.delete("/alias/{alias_id}")
async def quitar_alias_cliente(alias_id: int) -> dict[str, Any]:
    """Quita un alias (no el canónico); sus servicios pasan a un cliente propio en la sync."""
    return await _ejecutar(lambda s: quitar_alias(s, alias_id), commit=True)


@router.post("/sincronizar")
async def sincronizar_global() -> dict[str, Any]:
    """Sincronización global: registra clientes nuevos, recalcula los automáticos y propaga."""
    resumen = await _ejecutar(sincronizar_categorias, commit=True)
    return resumen.to_dict()
