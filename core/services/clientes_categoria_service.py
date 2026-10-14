# Nombre de archivo: clientes_categoria_service.py
# Ubicación de archivo: core/services/clientes_categoria_service.py
# Descripción: Clientes por categoría — normalización de nombres, sincronización set-based de categorías y operaciones de admin

"""Categoría por **cliente** (`app.clientes` + `app.clientes_alias`, migración `20261014_01`) que se
propaga a sus `servicios`.

Un cliente se identifica por su *clave*: el nombre normalizado (`normalizar_clave_cliente`). Cada
variante de nombre que apunta a un cliente es un `ClienteAlias`; el alias cuya clave coincide con
`Cliente.clave` es el **canónico** y no se puede quitar.

Precedencia de la categoría de un cliente: `LISTA`/`MANUAL` (fijada por un admin, nunca se
recalcula) > `SLA` (moda de `servicios.categoria_sla` 1..6, empate → la más alta) > `AUTO` (0 si
tiene servicios pero ninguno con dato SLA) > `NULL` (sin servicios). Un servicio con `categoria_excepcion = true` nunca es pisado
por la propagación.

Todo es sync con `Session` (se llama desde rutas vía `asyncio.to_thread` + `SessionLocal`) y la
sincronización es set-based: la clave de cada `nombre_cliente` distinto se calcula en Python (una
sola vez, ~3k nombres) y se carga en una tabla temporal; el resto son `INSERT … SELECT` /
`UPDATE … FROM` sobre esa tabla. Ninguna función hace `commit`: lo hace el llamador.
"""

from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass, field
from typing import Iterable, Literal

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from core.parsers.servicios_excel import limpiar_clave
from core.services.servicios_categoria_service import CategoriaInvalidaError, validar_categoria
from db.models.infra import Cliente, ClienteAlias, ClienteOrigenCategoria

# Sufijos societarios que se quitan del FINAL de la clave (ya en mayúsculas y con la puntuación
# convertida en espacios: "S.A.U." → "S A U"). Se quitan repetidamente ("X SA SAU" → "X"), del más
# largo al más corto, y nunca dejan la clave vacía. Lista validada contra los 3050 `nombre_cliente`
# distintos de dev (2026-10-14): colapsan a 2856 claves y ningún par de empresas distintas
# comparte clave. No se incluyen formas ambiguas como "SCS", "SE" o "SH".
SUFIJOS_SOCIETARIOS: tuple[str, ...] = (
    "SOCIEDAD DE RESPONSABILIDAD LIMITADA",
    "SOCIEDAD POR ACCIONES SIMPLIFICADA",
    "SOCIEDAD ANONIMA UNIPERSONAL",
    "SOCIEDAD ANONIMA",
    "COOPERATIVO LTDO",
    "COOPERATIVA LTDA",
    "S A C I F",
    "S A U",
    "S A I C",
    "S A C I",
    "S A S",
    "S R L",
    "S A",
    "SACIF",
    "SAIC",
    "SACI",
    "SAU",
    "SAS",
    "SRL",
    "SA",
    "LIMITADA",
    "LTDO",
    "LTDA",
    "LTD",
    "INC",
)
_SUFIJOS_TOKENS: tuple[tuple[str, ...], ...] = tuple(
    sorted((tuple(s.split()) for s in SUFIJOS_SOCIETARIOS), key=len, reverse=True)
)

CATEGORIAS_SLA = range(1, 7)
ORDEN_GRUPOS: tuple[int | None, ...] = (6, 5, 4, 3, 2, 1, 0, None)
_TABLA_MAPA = "tmp_cliente_nombre_clave"
_ORIGENES_RECALCULABLES = (ClienteOrigenCategoria.SLA.value, ClienteOrigenCategoria.AUTO.value)
_ORIGENES_ALIAS = ("AUTO", "MANUAL")

ModoLista = Literal["agregar", "reemplazar"]


class ClienteCategoriaError(CategoriaInvalidaError):
    """Error de validación de una operación de clientes — el endpoint lo traduce a 400."""


class ClienteNoEncontradoError(ClienteCategoriaError):
    """El cliente o alias pedido no existe — el endpoint lo traduce a 404."""


# ─── Lógica pura ─────────────────────────────────────────────────────────────


def normalizar_clave_cliente(nombre: str | None) -> str | None:
    """Clave única de un cliente: `limpiar_clave` en mayúsculas y sin sufijos societarios finales.

    `None` si el nombre queda vacío. "BANCO DE GALICIA Y BUENOS AIRES S A U" y "… SA" dan la misma
    clave; "… (ARSAT)" y "… SOCIEDAD ANONIMA ARSAT" no (el sufijo no está al final) → alias manual.
    """
    if nombre is None:
        return None
    tokens = limpiar_clave(nombre).upper().split()
    if not tokens:
        return None
    recortado = True
    while recortado:
        recortado = False
        for sufijo in _SUFIJOS_TOKENS:
            largo = len(sufijo)
            if len(tokens) > largo and tuple(tokens[-largo:]) == sufijo:
                tokens = tokens[:-largo]
                recortado = True
                break
    return " ".join(tokens)


def claves_de_nombres(nombres: Iterable[str | None]) -> set[str]:
    """Claves distintas de un lote de nombres (ignora vacíos). La usan los hooks de ingesta para
    llamar a `sincronizar_categorias(claves=...)` sólo con los clientes tocados."""
    claves: set[str] = set()
    for nombre in nombres:
        clave = normalizar_clave_cliente(nombre)
        if clave:
            claves.add(clave)
    return claves


def nombre_mas_frecuente(frecuencias: dict[str, int]) -> str:
    """Grafía más usada entre los servicios de una clave; empate → la primera alfabéticamente."""
    return min(frecuencias.items(), key=lambda item: (-item[1], item[0]))[0]


def elegir_categoria_automatica(
    conteos_sla: dict[int, int], *, hay_servicios: bool
) -> tuple[int | None, str, bool]:
    """Categoría automática de un cliente `SLA`/`AUTO` → `(categoria, origen, a_revisar)`.

    - Moda de `categoria_sla` en 1..6 (empate → la más alta) → origen `SLA`.
    - Sin datos SLA pero con al menos un servicio → `0`, origen `AUTO`.
    - Sin servicios → `NULL` con origen `AUTO`.
    No se mira `servicios.categoria`: es el resultado de la propagación (sería circular).
    `a_revisar` = hay más de una categoría SLA distinta en 1..6.
    """
    validos = {cat: n for cat, n in conteos_sla.items() if cat in CATEGORIAS_SLA and n > 0}
    if validos:
        moda = max(validos.items(), key=lambda item: (item[1], item[0]))[0]
        return moda, ClienteOrigenCategoria.SLA.value, len(validos) > 1
    if hay_servicios:
        return 0, ClienteOrigenCategoria.AUTO.value, False
    return None, ClienteOrigenCategoria.AUTO.value, False


def _clave_orden(nombre: str) -> tuple[str, str]:
    return (limpiar_clave(nombre), nombre)


def _rango(categoria: int | None) -> int:
    return -1 if categoria is None else categoria


def _validar_categoria(categoria: int | None) -> None:
    validar_categoria(categoria, permitir_none=True)


# ─── Soporte SQL ─────────────────────────────────────────────────────────────


def _cargar_mapa_temporal(session: Session) -> dict[str, dict[str, int]]:
    """Carga `tmp_cliente_nombre_clave(nombre_cliente, clave)` con todos los `nombre_cliente`
    distintos de `servicios` y devuelve `{clave: {nombre: cantidad_de_servicios}}`.

    La tabla es `ON COMMIT DROP`: vive sólo en la transacción del llamador."""
    filas = session.execute(
        text(
            "SELECT nombre_cliente, count(*) FROM app.servicios "
            "WHERE nombre_cliente IS NOT NULL GROUP BY nombre_cliente"
        )
    ).all()
    por_clave: dict[str, dict[str, int]] = {}
    nombres: list[str] = []
    claves: list[str] = []
    for nombre, cantidad in filas:
        clave = normalizar_clave_cliente(nombre)
        if clave is None:
            continue
        por_clave.setdefault(clave, {})[nombre] = int(cantidad)
        nombres.append(nombre)
        claves.append(clave)

    session.execute(text(f"DROP TABLE IF EXISTS pg_temp.{_TABLA_MAPA}"))
    session.execute(
        text(
            f"CREATE TEMP TABLE {_TABLA_MAPA} (nombre_cliente varchar(255) PRIMARY KEY, "
            "clave varchar(255) NOT NULL) ON COMMIT DROP"
        )
    )
    if nombres:
        session.execute(
            text(
                f"INSERT INTO {_TABLA_MAPA} (nombre_cliente, clave) "
                "SELECT * FROM unnest(CAST(:nombres AS varchar[]), CAST(:claves AS varchar[]))"
            ),
            {"nombres": nombres, "claves": claves},
        )
    session.execute(text(f"CREATE INDEX ON {_TABLA_MAPA} (clave)"))
    session.execute(text(f"ANALYZE {_TABLA_MAPA}"))
    return por_clave


def _registrar_clientes(session: Session, nuevos: dict[str, str]) -> int:
    """Crea `Cliente` (`AUTO`) + alias canónico `AUTO` para cada clave que todavía no es alias."""
    if not nuevos:
        return 0
    params = {"claves": list(nuevos), "nombres": list(nuevos.values())}
    creados = session.execute(
        text(
            "INSERT INTO app.clientes (nombre, clave, origen_categoria) "
            "SELECT u.nombre, u.clave, CAST('AUTO' AS app.cliente_origen_categoria) "
            "FROM unnest(CAST(:claves AS varchar[]), CAST(:nombres AS varchar[])) AS u(clave, nombre) "
            "WHERE NOT EXISTS (SELECT 1 FROM app.clientes_alias a WHERE a.clave = u.clave) "
            "ON CONFLICT (clave) DO NOTHING"
        ),
        params,
    ).rowcount
    session.execute(
        text(
            "INSERT INTO app.clientes_alias (clave, nombre_original, cliente_id, origen) "
            "SELECT u.clave, u.nombre, c.id, 'AUTO' "
            "FROM unnest(CAST(:claves AS varchar[]), CAST(:nombres AS varchar[])) AS u(clave, nombre) "
            "JOIN app.clientes c ON c.clave = u.clave "
            "WHERE NOT EXISTS (SELECT 1 FROM app.clientes_alias a WHERE a.clave = u.clave) "
            "ON CONFLICT (clave) DO NOTHING"
        ),
        params,
    )
    return int(creados or 0)


def _ids_de_claves(session: Session, claves: Iterable[str]) -> list[int]:
    lista = sorted(set(claves))
    if not lista:
        return []
    return sorted(
        session.execute(
            select(ClienteAlias.cliente_id).where(ClienteAlias.clave.in_(lista)).distinct()
        ).scalars()
    )


def _claves_de_clientes(session: Session, cliente_ids: Iterable[int]) -> set[str]:
    ids = sorted(set(cliente_ids))
    if not ids:
        return set()
    return set(session.execute(select(ClienteAlias.clave).where(ClienteAlias.cliente_id.in_(ids))).scalars())


def _filtro_ids(columna: str, cliente_ids: list[int] | None) -> str:
    return "" if cliente_ids is None else f" AND {columna} = ANY(CAST(:ids AS integer[]))"


def _recalcular(session: Session, cliente_ids: list[int] | None) -> int:
    """Recalcula categoría/origen/`a_revisar` de los clientes `SLA`/`AUTO` (todos o `cliente_ids`).
    Dos agregaciones + un `UPDATE … FROM unnest(...)` con sólo los que cambian.

    Los servicios con `categoria_excepcion = true` siguen votando en la moda con su `categoria_sla`:
    ese dato viene de la planilla SLA, no de una decisión del admin (la excepción sólo protege su
    `categoria` de la propagación)."""
    params = {"origenes": list(_ORIGENES_RECALCULABLES), "ids": cliente_ids}
    actuales = session.execute(
        text(
            "SELECT c.id, c.categoria, CAST(c.origen_categoria AS text), c.a_revisar FROM app.clientes c "
            "WHERE CAST(c.origen_categoria AS text) = ANY(CAST(:origenes AS text[]))"
            + _filtro_ids("c.id", cliente_ids)
        ),
        params,
    ).all()
    if not actuales:
        return 0

    conteos: dict[int, dict[int, int]] = {}
    con_servicios: set[int] = set()
    for cliente_id, categoria_sla, cantidad in session.execute(
        text(
            "SELECT a.cliente_id, s.categoria_sla, count(*) "
            "FROM app.clientes c "
            "JOIN app.clientes_alias a ON a.cliente_id = c.id "
            f"JOIN {_TABLA_MAPA} t ON t.clave = a.clave "
            "JOIN app.servicios s ON s.nombre_cliente = t.nombre_cliente "
            "WHERE CAST(c.origen_categoria AS text) = ANY(CAST(:origenes AS text[]))"
            + _filtro_ids("c.id", cliente_ids)
            + " GROUP BY a.cliente_id, s.categoria_sla"
        ),
        params,
    ):
        if categoria_sla is not None:  # (cliente_id, categoria_sla) es único por el GROUP BY
            conteos.setdefault(cliente_id, {})[categoria_sla] = int(cantidad)
        con_servicios.add(cliente_id)

    cambios: list[tuple[int, int | None, str, bool]] = []
    for cliente_id, categoria, origen, a_revisar in actuales:
        nuevo = elegir_categoria_automatica(conteos.get(cliente_id, {}), hay_servicios=cliente_id in con_servicios)
        if (categoria, origen, a_revisar) != nuevo:
            cambios.append((cliente_id, *nuevo))
    if not cambios:
        return 0

    session.execute(
        text(
            "UPDATE app.clientes c SET categoria = u.categoria, "
            "origen_categoria = CAST(u.origen AS app.cliente_origen_categoria), "
            "a_revisar = u.a_revisar, actualizado_en = now() "
            "FROM unnest(CAST(:ids AS integer[]), CAST(:categorias AS smallint[]), "
            "CAST(:origenes AS text[]), CAST(:revisar AS boolean[])) AS u(id, categoria, origen, a_revisar) "
            "WHERE c.id = u.id"
        ),
        {
            "ids": [c[0] for c in cambios],
            "categorias": [c[1] for c in cambios],
            "origenes": [c[2] for c in cambios],
            "revisar": [c[3] for c in cambios],
        },
    )
    return len(cambios)


def _propagar(session: Session, cliente_ids: list[int] | None) -> int:
    """`servicios.categoria` = categoría de su cliente, salvo excepciones y sin escrituras vacías."""
    resultado = session.execute(
        text(
            "UPDATE app.servicios s SET categoria = c.categoria "
            f"FROM {_TABLA_MAPA} t "
            "JOIN app.clientes_alias a ON a.clave = t.clave "
            "JOIN app.clientes c ON c.id = a.cliente_id "
            "WHERE s.nombre_cliente = t.nombre_cliente AND NOT s.categoria_excepcion "
            "AND s.categoria IS DISTINCT FROM c.categoria" + _filtro_ids("c.id", cliente_ids)
        ),
        {"ids": cliente_ids},
    )
    return int(resultado.rowcount or 0)


# ─── Sincronización ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class ResumenSync:
    clientes_creados: int = 0
    clientes_recalculados: int = 0
    servicios_actualizados: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def sincronizar_categorias(session: Session, claves: set[str] | None = None) -> ResumenSync:
    """Registra clientes/alias nuevos, recalcula los `SLA`/`AUTO` y propaga a `servicios`.

    Con `claves` se limita a esas claves y a los clientes que las tienen como alias (todas sus
    variantes se recalculan juntas); sin `claves` recorre todo (lo usa el script de regularización).
    """
    session.flush()
    por_clave = _cargar_mapa_temporal(session)
    objetivo = set(por_clave) if claves is None else set(claves) & set(por_clave)
    creados = _registrar_clientes(session, {c: nombre_mas_frecuente(por_clave[c]) for c in sorted(objetivo)})

    cliente_ids: list[int] | None = None
    if claves is not None:
        cliente_ids = _ids_de_claves(session, claves)
        if not cliente_ids:
            session.expire_all()
            return ResumenSync(clientes_creados=creados)

    resumen = ResumenSync(
        clientes_creados=creados,
        clientes_recalculados=_recalcular(session, cliente_ids),
        servicios_actualizados=_propagar(session, cliente_ids),
    )
    session.expire_all()
    return resumen


# ─── Listado ─────────────────────────────────────────────────────────────────


def _nombre_grupo(categoria: int | None) -> str:
    return "sin" if categoria is None else str(categoria)


def listar_clientes_por_categoria(session: Session) -> dict[str, list[dict]]:
    """Clientes agrupados `"6"`…`"0"`, `"sin"` (NULL), cada grupo ordenado por nombre (sin
    distinguir mayúsculas ni acentos). Dos consultas agregadas, sin N+1."""
    _cargar_mapa_temporal(session)
    filas = session.execute(
        text(
            "SELECT c.id, c.nombre, c.categoria, CAST(c.origen_categoria AS text), c.a_revisar, "
            "count(s.id), count(s.id) FILTER (WHERE s.categoria_excepcion) "
            "FROM app.clientes c "
            "LEFT JOIN app.clientes_alias a ON a.cliente_id = c.id "
            f"LEFT JOIN {_TABLA_MAPA} t ON t.clave = a.clave "
            "LEFT JOIN app.servicios s ON s.nombre_cliente = t.nombre_cliente "
            "GROUP BY c.id"
        )
    ).all()
    alias_por_cliente: dict[int, list[dict]] = {}
    # `canonico`: el alias cuya clave es la del cliente — no se puede quitar (ver `quitar_alias`).
    for alias_id, cliente_id, nombre_original, origen, canonico in session.execute(
        select(
            ClienteAlias.id,
            ClienteAlias.cliente_id,
            ClienteAlias.nombre_original,
            ClienteAlias.origen,
            ClienteAlias.clave == Cliente.clave,
        ).join(Cliente, Cliente.id == ClienteAlias.cliente_id)
    ):
        alias_por_cliente.setdefault(cliente_id, []).append(
            {"id": alias_id, "nombre_original": nombre_original, "origen": origen, "canonico": bool(canonico)}
        )

    grupos: dict[str, list[dict]] = {_nombre_grupo(cat): [] for cat in ORDEN_GRUPOS}
    for cliente_id, nombre, categoria, origen, a_revisar, servicios, excepciones in filas:
        alias = sorted(alias_por_cliente.get(cliente_id, []), key=lambda a: _clave_orden(a["nombre_original"]))
        grupos[_nombre_grupo(categoria)].append(
            {
                "id": cliente_id,
                "nombre": nombre,
                "categoria": categoria,
                "origen_categoria": origen,
                "a_revisar": a_revisar,
                "servicios": int(servicios),
                "excepciones": int(excepciones),
                "alias": alias,
            }
        )
    for clientes in grupos.values():
        clientes.sort(key=lambda c: _clave_orden(c["nombre"]))
    return grupos


# ─── Cambio de categoría ─────────────────────────────────────────────────────


def cambiar_categoria(
    session: Session,
    ids: list[int],
    categoria: int | None,
    usuario: str | None,
    *,
    automatico: bool = False,
) -> dict:
    """Fija la categoría de uno o varios clientes (`origen = MANUAL`, `None` = "sin categorizar").
    Con `automatico=True` los devuelve a `AUTO` (se ignora `categoria`) y se recalculan."""
    if not ids:
        raise ClienteCategoriaError("No se especificaron clientes")
    if not automatico:
        _validar_categoria(categoria)

    pedidos = set(ids)
    encontrados = set(session.execute(select(Cliente.id).where(Cliente.id.in_(pedidos))).scalars())
    valores: dict = {"actualizado_por": usuario}
    if automatico:
        valores["origen_categoria"] = ClienteOrigenCategoria.AUTO
    else:
        valores.update(categoria=categoria, origen_categoria=ClienteOrigenCategoria.MANUAL, a_revisar=False)

    actualizados = 0
    resumen = ResumenSync()
    if encontrados:
        actualizados = session.execute(
            update(Cliente).where(Cliente.id.in_(encontrados)).values(**valores)
        ).rowcount
        resumen = sincronizar_categorias(session, _claves_de_clientes(session, encontrados))
    return {
        "actualizados": int(actualizados or 0),
        "no_encontrados": sorted(pedidos - encontrados),
        "sync": resumen.to_dict(),
    }


# ─── Carga de lista oficial ──────────────────────────────────────────────────


@dataclass(slots=True)
class PrevisualizacionLista:
    categoria: int | None
    modo: str
    sube: list[dict] = field(default_factory=list)
    baja: list[dict] = field(default_factory=list)
    sin_cambio: list[dict] = field(default_factory=list)
    nuevos: list[str] = field(default_factory=list)
    sugerencias: dict[str, list[dict]] = field(default_factory=dict)
    quitados: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _entradas_lista(nombres: list[str]) -> dict[str, str]:
    """`{clave: nombre}` deduplicado por clave (gana la primera grafía), sin vacíos."""
    entradas: dict[str, str] = {}
    for nombre in nombres:
        limpio = (nombre or "").strip()
        clave = normalizar_clave_cliente(limpio)
        if clave and clave not in entradas:
            entradas[clave] = limpio
    return entradas


def _resolver_lista(
    session: Session, nombres: list[str], categoria: int | None, modo: str
) -> tuple[PrevisualizacionLista, set[int], dict[str, str]]:
    if modo not in ("agregar", "reemplazar"):
        raise ClienteCategoriaError("modo debe ser 'agregar' o 'reemplazar'")
    _validar_categoria(categoria)
    entradas = _entradas_lista(nombres)
    if not entradas:
        raise ClienteCategoriaError("La lista no tiene nombres")

    alias_a_cliente: dict[str, tuple[int, str, int | None, str]] = {
        clave: (cid, nombre, cat, origen)
        for clave, cid, nombre, cat, origen in session.execute(
            text(
                "SELECT a.clave, c.id, c.nombre, c.categoria, CAST(c.origen_categoria AS text) "
                "FROM app.clientes_alias a JOIN app.clientes c ON c.id = a.cliente_id"
            )
        )
    }

    previa = PrevisualizacionLista(categoria=categoria, modo=modo)
    coincidentes: set[int] = set()
    sin_match: dict[str, str] = {}
    for clave, nombre in entradas.items():
        encontrado = alias_a_cliente.get(clave)
        if encontrado is None:
            sin_match[clave] = nombre
            previa.nuevos.append(nombre)
            candidatos: list[dict] = []
            for parecida in difflib.get_close_matches(clave, list(alias_a_cliente), n=10, cutoff=0.75):
                cid, cnombre, _, _ = alias_a_cliente[parecida]
                if all(c["id"] != cid for c in candidatos):
                    candidatos.append({"id": cid, "nombre": cnombre})
            if candidatos:
                previa.sugerencias[nombre] = candidatos[:5]
            continue
        cliente_id, cliente_nombre, categoria_actual, origen_actual = encontrado
        if cliente_id in coincidentes:
            continue
        coincidentes.add(cliente_id)
        item = {
            "cliente_id": cliente_id,
            "nombre": cliente_nombre,
            "nombre_lista": nombre,
            "categoria_actual": categoria_actual,
            "origen_actual": origen_actual,
        }
        if _rango(categoria) > _rango(categoria_actual):
            previa.sube.append(item)
        elif _rango(categoria) < _rango(categoria_actual):
            previa.baja.append(item)
        else:
            previa.sin_cambio.append(item)

    if modo == "reemplazar":
        for cid, cnombre, cat in session.execute(
            select(Cliente.id, Cliente.nombre, Cliente.categoria)
            .where(Cliente.origen_categoria == ClienteOrigenCategoria.LISTA)
            .where(Cliente.categoria.is_not_distinct_from(categoria))
        ):
            if cid not in coincidentes:
                previa.quitados.append({"cliente_id": cid, "nombre": cnombre, "categoria_actual": cat})
        previa.quitados.sort(key=lambda q: _clave_orden(q["nombre"]))
    return previa, coincidentes, sin_match


def previsualizar_lista(
    session: Session,
    nombres: list[str],
    categoria: int | None,
    modo: ModoLista,
    usuario: str | None = None,
) -> PrevisualizacionLista:
    """Diff de aplicar la lista (sube / baja / sin cambio / nuevos / sugerencias / quitados).
    No escribe nada."""
    del usuario  # misma firma que aplicar_lista; la previsualización no audita
    previa, _, _ = _resolver_lista(session, nombres, categoria, modo)
    return previa


def aplicar_lista(
    session: Session,
    nombres: list[str],
    categoria: int | None,
    modo: ModoLista,
    usuario: str | None = None,
) -> dict:
    """Asigna `categoria` con `origen = LISTA` a los clientes de la lista; crea un `Cliente`
    (`LISTA`) por cada nombre sin match. Con `modo="reemplazar"` devuelve a `AUTO` los clientes
    `LISTA` de esa categoría que no vienen en la lista. Termina sincronizando los afectados."""
    previa, coincidentes, sin_match = _resolver_lista(session, nombres, categoria, modo)

    if coincidentes:
        session.execute(
            update(Cliente)
            .where(Cliente.id.in_(coincidentes))
            .values(
                categoria=categoria,
                origen_categoria=ClienteOrigenCategoria.LISTA,
                a_revisar=False,
                actualizado_por=usuario,
            )
        )
    quitados = {q["cliente_id"] for q in previa.quitados}
    if quitados:
        session.execute(
            update(Cliente)
            .where(Cliente.id.in_(quitados))
            .values(origen_categoria=ClienteOrigenCategoria.AUTO, actualizado_por=usuario)
        )
    for clave, nombre in sin_match.items():
        cliente = Cliente(
            nombre=nombre,
            clave=clave,
            categoria=categoria,
            origen_categoria=ClienteOrigenCategoria.LISTA,
            actualizado_por=usuario,
        )
        cliente.alias.append(ClienteAlias(clave=clave, nombre_original=nombre, origen="AUTO"))
        session.add(cliente)
    session.flush()

    claves = _claves_de_clientes(session, coincidentes | quitados) | set(sin_match)
    resumen = sincronizar_categorias(session, claves)
    return {**previa.to_dict(), "creados": len(sin_match), "sync": resumen.to_dict()}


# ─── Alias y fusión ──────────────────────────────────────────────────────────


def _obtener_cliente(session: Session, cliente_id: int) -> Cliente:
    cliente = session.get(Cliente, cliente_id)
    if cliente is None:
        raise ClienteNoEncontradoError(f"Cliente {cliente_id} no encontrado")
    return cliente


def resolver_cliente(session: Session, nombre: str | None) -> Cliente | None:
    """Cliente al que apunta un nombre (vía la clave de sus alias), o `None`."""
    clave = normalizar_clave_cliente(nombre)
    if clave is None:
        return None
    return session.execute(
        select(Cliente).join(ClienteAlias, ClienteAlias.cliente_id == Cliente.id).where(ClienteAlias.clave == clave)
    ).scalar_one_or_none()


def fusionar_clientes(session: Session, destino_id: int, origen_ids: list[int]) -> dict:
    """Mueve todos los alias de `origen_ids` al destino y borra los clientes origen. El destino
    conserva su categoría si es `LISTA`/`MANUAL`; si no, se recalcula con los servicios sumados."""
    origenes = set(origen_ids) - {destino_id}
    if not origenes:
        raise ClienteCategoriaError("No se especificaron clientes a fusionar distintos del destino")
    _obtener_cliente(session, destino_id)
    existentes = set(session.execute(select(Cliente.id).where(Cliente.id.in_(origenes))).scalars())
    faltantes = sorted(origenes - existentes)
    if faltantes:
        raise ClienteNoEncontradoError(f"Clientes no encontrados: {faltantes}")

    claves = _claves_de_clientes(session, origenes | {destino_id})
    movidos = session.execute(
        update(ClienteAlias).where(ClienteAlias.cliente_id.in_(origenes)).values(cliente_id=destino_id)
    ).rowcount
    session.execute(delete(Cliente).where(Cliente.id.in_(origenes)))
    session.expire_all()
    resumen = sincronizar_categorias(session, claves)
    return {
        "destino_id": destino_id,
        "fusionados": sorted(origenes),
        "alias_movidos": int(movidos or 0),
        "sync": resumen.to_dict(),
    }


def agregar_alias(
    session: Session, cliente_id: int, nombre: str, origen: str = "MANUAL"
) -> ClienteAlias:
    """Vincula `nombre` como alias del cliente.

    Si esa clave ya es alias de otro cliente, se mueve: cuando era el único alias de aquel cliente
    y es `AUTO`/`SLA` (auto-creado para esa variante), el cliente vacío se borra. Se rechaza (usar
    `fusionar_clientes`) si era el único alias de un cliente `LISTA`/`MANUAL` (se perdería la
    categoría fijada por un admin) o el canónico de un cliente con otros alias."""
    if origen not in _ORIGENES_ALIAS:
        raise ClienteCategoriaError("origen de alias debe ser 'AUTO' o 'MANUAL'")
    clave = normalizar_clave_cliente(nombre)
    if clave is None:
        raise ClienteCategoriaError("El nombre del alias está vacío")
    _obtener_cliente(session, cliente_id)
    nombre_limpio = nombre.strip()

    existente = session.execute(select(ClienteAlias).where(ClienteAlias.clave == clave)).scalar_one_or_none()
    claves = _claves_de_clientes(session, [cliente_id]) | {clave}
    if existente is not None and existente.cliente_id == cliente_id:
        return existente
    if existente is not None:
        otro = _obtener_cliente(session, existente.cliente_id)
        cantidad_otro = len(_claves_de_clientes(session, [otro.id]))
        fijado_por_admin = otro.origen_categoria in (ClienteOrigenCategoria.LISTA, ClienteOrigenCategoria.MANUAL)
        if cantidad_otro == 1 and fijado_por_admin:
            raise ClienteCategoriaError(
                f"'{nombre_limpio}' es el único nombre de '{otro.nombre}', con categoría fijada por un "
                "admin: usar fusionar clientes"
            )
        if existente.clave == otro.clave and cantidad_otro > 1:
            raise ClienteCategoriaError(
                f"'{nombre_limpio}' es el nombre canónico de '{otro.nombre}', que tiene otros alias: "
                "usar fusionar clientes"
            )
        otro_id = otro.id
        alias_id = existente.id
        session.execute(
            update(ClienteAlias)
            .where(ClienteAlias.id == alias_id)
            .values(cliente_id=cliente_id, origen=origen)
        )
        if cantidad_otro == 1:
            session.execute(delete(Cliente).where(Cliente.id == otro_id))
        session.expire_all()
    else:
        nuevo = ClienteAlias(clave=clave, nombre_original=nombre_limpio, cliente_id=cliente_id, origen=origen)
        session.add(nuevo)
        session.flush()
        alias_id = nuevo.id

    sincronizar_categorias(session, claves)
    return session.get(ClienteAlias, alias_id)


# Nombre explícito para el script de regularización (líneas `canónico | variante`).
agregar_alias_por_nombre = agregar_alias


def quitar_alias(session: Session, alias_id: int) -> dict:
    """Quita un alias. El canónico (clave == `Cliente.clave`) no se puede quitar. Los servicios
    con esa variante quedan como un cliente propio (`AUTO`) en la sincronización."""
    alias = session.get(ClienteAlias, alias_id)
    if alias is None:
        raise ClienteNoEncontradoError(f"Alias {alias_id} no encontrado")
    cliente = _obtener_cliente(session, alias.cliente_id)
    if alias.clave == cliente.clave:
        raise ClienteCategoriaError("No se puede quitar el alias canónico del cliente")
    claves = _claves_de_clientes(session, [cliente.id])
    session.execute(delete(ClienteAlias).where(ClienteAlias.id == alias_id))
    session.expire_all()
    resumen = sincronizar_categorias(session, claves)
    return {"alias_id": alias_id, "cliente_id": cliente.id, "sync": resumen.to_dict()}


__all__ = [
    "ClienteCategoriaError",
    "ClienteNoEncontradoError",
    "ORDEN_GRUPOS",
    "PrevisualizacionLista",
    "ResumenSync",
    "SUFIJOS_SOCIETARIOS",
    "agregar_alias",
    "agregar_alias_por_nombre",
    "aplicar_lista",
    "cambiar_categoria",
    "claves_de_nombres",
    "elegir_categoria_automatica",
    "fusionar_clientes",
    "listar_clientes_por_categoria",
    "nombre_mas_frecuente",
    "normalizar_clave_cliente",
    "previsualizar_lista",
    "quitar_alias",
    "resolver_cliente",
    "sincronizar_categorias",
]
