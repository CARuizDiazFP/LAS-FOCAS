# Nombre de archivo: test_servicios_ingest_routes.py
# Ubicación de archivo: tests/test_servicios_ingest_routes.py
# Descripción: Tests de integración de la consolidación de identidad dentro de POST /servicios/ingest contra un Postgres real de test

from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.app.main import app
from db.session import SessionLocal

API_HEADERS = {"Authorization": "Bearer test-api-key"}


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def client():
    # `with TestClient(app) as client:` (en vez de `TestClient(app)` a nivel de módulo, usado
    # "en frío" por request) mantiene un único blocking portal/event loop mientras dure el bloque.
    # Sin esto, cada llamada suelta del cliente abre su propio loop nuevo y el pool de asyncpg
    # (motor async global, ver db/session.py) intenta reusar una conexión creada en un loop ya
    # cerrado -> `RuntimeError: ... attached to a different loop`. Se reproduce incluso con 2 GET
    # simples sin tocar código de este endpoint. Scope "module" (no función) porque el pool asyncpg
    # es un singleton a nivel de proceso (`db.session.async_engine`): si cada test abriera y cerrara
    # su propio portal, el segundo test heredaría en el pool una conexión atada al loop ya cerrado
    # del primero y volvería a romper — un solo loop para todo el archivo evita la colisión.
    with TestClient(app) as test_client:
        yield test_client


_NUMEROS_DE_TEST = (
    "900001", "900002", "900003", "900004", "900005",
    "900090", "900091", "900092",
)

# n_id de pelo sintético para el árbol mínimo de Cromo del test de fusión. Fuera del rango real de
# Cromo (verificado: no existe en app.cromo_pelos de dev) para no pisar datos reales.
_PELO_N_ID_FUSION = 990000901


@pytest.fixture(autouse=True)
def _limpiar_servicios_de_test():
    yield
    with SessionLocal() as session:
        # Orden obligatorio: `app.cromo_servicio_match.servicio_id` referencia `app.servicios.id`
        # SIN `ON DELETE CASCADE` (verificado real con `\d app.cromo_servicio_match` contra
        # lasfocasdev-postgres), así que el match se borra antes que el Servicio.
        session.execute(
            text("DELETE FROM app.cromo_servicio_match WHERE pelo_n_id = :pelo"),
            {"pelo": _PELO_N_ID_FUSION},
        )
        session.execute(text("DELETE FROM app.cromo_pelos WHERE n_id = :pelo"), {"pelo": _PELO_N_ID_FUSION})
        # `app.rutas_servicio` no necesita DELETE explícito: su FK a `app.servicios` es
        # `ON DELETE CASCADE`, así que la ruta que crea
        # `test_ingest_no_fusiona_placeholder_con_tracking_fisico_encima` se va con su Servicio.
        session.execute(
            text("DELETE FROM app.servicios WHERE numero_primer_servicio = ANY(:numeros ::varchar[])"),
            {"numeros": list(_NUMEROS_DE_TEST)},
        )
        session.commit()


def test_ingest_calcula_servicio_id_como_el_id_mas_alto_de_la_cadena(client: TestClient) -> None:
    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["900001"],
            "Número Línea": ["900050"],
            "Línea Upgrade (De)": ["900010"],
            "Tipo Servicio": ["TLS"],
            "Nivel Cliente": ["4"],
            "Estado Servicio": ["Activo"],
        }
    )

    response = client.post(
        "/servicios/ingest",
        files={"file": ("servicios.xlsx", _excel_bytes(df), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["inserted"] == 1

    detail = client.get("/servicios/detail", params={"id": "900001"}, headers=API_HEADERS)
    body = detail.json()["servicio"]
    assert body["numero_linea"] == "900050"
    assert set(body["alias_ids"]) == {"900001", "900010"}
    assert body["categoria"] == 4
    assert body["es_verificable"] is True


def _crear_placeholder_puro(numero: str) -> int:
    """Inserta un placeholder Cromo PURO (`servicio_id == numero_primer_servicio`, origen
    `INFERIDO_CROMO`, sin rutas ni empalmes) igual que
    `core/services/cromo/ingesta.py::_SQL_CREAR_PLACEHOLDER_SERVICIO`, y devuelve su `id`."""
    with SessionLocal() as session:
        placeholder_id = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios "
                    "(servicio_id, numero_primer_servicio, categoria, origen_datos, estado_servicio) "
                    "VALUES (:numero, :numero, 0, 'INFERIDO_CROMO', 'DESCONOCIDO') RETURNING id"
                ),
                {"numero": numero},
            ).scalar_one()
        )
        session.commit()
    return placeholder_id


def _crear_placeholder_cromo_con_match(numero: str) -> int:
    """Crea un placeholder Cromo PURO (`servicio_id == numero_primer_servicio`, origen
    `INFERIDO_CROMO`) más el árbol MÍNIMO de Cromo necesario para colgarle una fila de
    `app.cromo_servicio_match`, y devuelve el `id` del placeholder.

    El árbol mínimo es una sola fila de `app.cromo_pelos`: `tubo_n_id`/`cable_n_id` son `NOT NULL`
    pero NO tienen FK dura (verificado real con `\\d app.cromo_pelos` — sólo hay índices, ver también
    el docstring de `CromoPelo` en db/models/cromo.py: "parent, sin FK dura"), así que no hace falta
    materializar cromo_tubos/cromo_cables/cromo_botellas para que el INSERT sea válido.
    """
    with SessionLocal() as session:
        placeholder_id = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios "
                    "(servicio_id, numero_primer_servicio, categoria, origen_datos, estado_servicio) "
                    "VALUES (:numero, :numero, 0, 'INFERIDO_CROMO', 'DESCONOCIDO') RETURNING id"
                ),
                {"numero": numero},
            ).scalar_one()
        )
        session.execute(
            text(
                "INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, servicio_numero) "
                "VALUES (:pelo, :pelo, :pelo, :numero)"
            ),
            {"pelo": _PELO_N_ID_FUSION, "numero": numero},
        )
        session.execute(
            text(
                "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo) "
                "VALUES (:pelo, :numero, :servicio_id, 'REGEX_EXACTO')"
            ),
            {"pelo": _PELO_N_ID_FUSION, "numero": numero, "servicio_id": placeholder_id},
        )
        session.commit()
    return placeholder_id


def test_ingest_fusiona_placeholder_cromo_puro_que_ocupa_el_servicio_id_final(client: TestClient) -> None:
    """REPRO A: el `id_final` de la familia ya está tomado por un placeholder Cromo puro.

    Antes del fix, el upsert reventaba con `duplicate key value violates unique constraint
    "ix_servicios_servicio_id"` y se perdía el chunk completo. Ahora el placeholder se fusiona:
    sus referencias se reasignan a la familia real y la fila placeholder se elimina, liberando el
    `servicio_id` para que la familia lo tome.
    """
    placeholder_id = _crear_placeholder_cromo_con_match("900090")

    # numero_primer_servicio=900003 + numero_linea=900090 -> id_final = max(900003, 900090) = 900090,
    # que es exactamente el servicio_id que ya ocupa el placeholder.
    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["900003"],
            "Número Línea": ["900090"],
            "Tipo Servicio": ["INT"],
        }
    )

    response = client.post(
        "/servicios/ingest",
        files={"file": ("servicios.xlsx", _excel_bytes(df), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=API_HEADERS,
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as session:
        # El placeholder ya no existe.
        assert (
            session.execute(
                text("SELECT COUNT(*) FROM app.servicios WHERE id = :id"), {"id": placeholder_id}
            ).scalar_one()
            == 0
        )

        familia = session.execute(
            text("SELECT id, servicio_id FROM app.servicios WHERE numero_primer_servicio = '900003'")
        ).one()
        # La familia real se quedó con el servicio_id que liberó el placeholder.
        assert familia.servicio_id == "900090"

        # La fila de cromo_servicio_match sobrevivió y ahora apunta a la familia real (no quedó
        # colgada ni fue borrada: su FK a app.servicios NO tiene ON DELETE CASCADE).
        match_servicio_id = session.execute(
            text("SELECT servicio_id FROM app.cromo_servicio_match WHERE pelo_n_id = :pelo"),
            {"pelo": _PELO_N_ID_FUSION},
        ).scalar_one()
        assert match_servicio_id == familia.id

        # `app.servicio_empalme_association` es la tercera tabla que referencia app.servicios sin
        # ON DELETE CASCADE, y la fusión la limpia con un DELETE (no reasigna: PK compuesta + tabla
        # DEPRECATED, ver el comentario en el endpoint). Este placeholder no tenía filas ahí — el caso
        # común, 0 de 9054 en dev —, así que lo que cubre esta aserción es que el DELETE extra no
        # rompe nada cuando no hay nada que borrar, y que no quedó ninguna fila colgada.
        assert (
            session.execute(
                text("SELECT COUNT(*) FROM app.servicio_empalme_association WHERE servicio_id = :id"),
                {"id": placeholder_id},
            ).scalar_one()
            == 0
        )


def test_ingest_no_fusiona_colision_con_servicio_real_y_degrada_a_alias(client: TestClient) -> None:
    """REPRO B: el `id_final` de la familia está tomado por una fila que NO es placeholder puro.

    Fusionar dos registros reales sin confirmación humana está explícitamente fuera de alcance, así
    que la familia NO pisa `servicio_id` (se queda con su valor seguro) pero el `id_final` calculado
    se agrega igual a `alias_ids` para que el matching de Cromo lo pueda resolver.
    """
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, estado_servicio, origen_datos) "
                "VALUES ('900091', '900091', 'DESCONOCIDO', 'MANUAL')"
            )
        )
        session.commit()

    # id_final = max(900004, 900091) = 900091, ya ocupado por la fila MANUAL de arriba.
    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["900004"],
            "Número Línea": ["900091"],
            "Tipo Servicio": ["INT"],
        }
    )

    response = client.post(
        "/servicios/ingest",
        files={"file": ("servicios.xlsx", _excel_bytes(df), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=API_HEADERS,
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as session:
        # La fila MANUAL quedó intacta.
        manual = session.execute(
            text(
                "SELECT servicio_id, origen_datos::text AS origen FROM app.servicios "
                "WHERE numero_primer_servicio = '900091'"
            )
        ).one()
        assert manual.servicio_id == "900091"
        assert manual.origen == "MANUAL"

        familia = session.execute(
            text(
                "SELECT servicio_id, alias_ids FROM app.servicios WHERE numero_primer_servicio = '900004'"
            )
        ).one()
        # No pisó el servicio_id ajeno...
        assert familia.servicio_id != "900091"
        assert familia.servicio_id == "900004"
        # ...pero el id_final sí quedó como alias, para que el matching de Cromo lo resuelva.
        assert "900091" in list(familia.alias_ids or [])


def test_ingest_no_fusiona_placeholder_que_es_otra_familia_del_mismo_archivo(client: TestClient) -> None:
    """El placeholder que ocupa el `id_final` de una familia es, a su vez, OTRA familia de ESTE mismo
    archivo.

    Fusionarlo sería borrar una fila que el upsert de esta misma corrida está por escribir. El
    predicado de "placeholder puro" tiene que degradar en este caso aunque el resto de las
    condiciones (INFERIDO_CROMO, no divergido, sin tracking) se cumplan.

    Antes del guard `colisiona_con_otra_familia_del_batch`, la fila del placeholder se descartaba de
    la detección de colisiones por venir en el batch, y las DOS familias terminaban reclamando
    `servicio_id='900090'` en el mismo INSERT -> `UniqueViolationError` y 500.
    """
    _crear_placeholder_puro("900090")

    # Fila 1: la familia del propio placeholder. Fila 2: otra familia cuyo id_final es 900090.
    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["900090", "900003"],
            "Número Línea": ["900090", "900090"],
            "Tipo Servicio": ["INT", "INT"],
        }
    )

    response = client.post(
        "/servicios/ingest",
        files={"file": ("servicios.xlsx", _excel_bytes(df), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=API_HEADERS,
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as session:
        # La familia del placeholder sigue existiendo y conserva su servicio_id: NO fue fusionada.
        propia = session.execute(
            text("SELECT servicio_id FROM app.servicios WHERE numero_primer_servicio = '900090'")
        ).one()
        assert propia.servicio_id == "900090"

        # La otra familia degradó: no pisó el servicio_id ajeno, pero se lo quedó como alias.
        otra = session.execute(
            text("SELECT servicio_id, alias_ids FROM app.servicios WHERE numero_primer_servicio = '900003'")
        ).one()
        assert otra.servicio_id == "900003"
        assert "900090" in list(otra.alias_ids or [])


def test_ingest_no_fusiona_placeholder_con_tracking_fisico_encima(client: TestClient) -> None:
    """Un placeholder que ya tiene tracking físico encima NO es fusionable, aunque siga marcado
    `INFERIDO_CROMO` y sin divergir.

    `core/services/infra_service.py::create_new` reusa un Servicio existente (`if existing: servicio
    = existing` — puede ser un placeholder Cromo), le cuelga una `RutaServicio` y le hace
    `servicio.empalmes.append(...)`, todo SIN cambiarle `origen_datos`. Por eso el guard chequea el
    HECHO (¿tiene filas en rutas_servicio / servicio_empalme_association?) y no sólo el flag: un hard
    delete no puede apoyarse en que hoy sean 0 casos en dev.
    """
    placeholder_id = _crear_placeholder_puro("900092")
    with SessionLocal() as session:
        # Sólo `servicio_id` es obligatorio: nombre/tipo/activa tienen server_default.
        session.execute(
            text("INSERT INTO app.rutas_servicio (servicio_id) VALUES (:id)"), {"id": placeholder_id}
        )
        session.commit()

    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["900005"],
            "Número Línea": ["900092"],
            "Tipo Servicio": ["INT"],
        }
    )

    response = client.post(
        "/servicios/ingest",
        files={"file": ("servicios.xlsx", _excel_bytes(df), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=API_HEADERS,
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as session:
        # El placeholder NO fue borrado y conserva su servicio_id.
        placeholder = session.execute(
            text("SELECT servicio_id FROM app.servicios WHERE id = :id"), {"id": placeholder_id}
        ).one()
        assert placeholder.servicio_id == "900092"

        # Su ruta sigue apuntándolo (no se reasignó a la familia real).
        assert (
            session.execute(
                text("SELECT COUNT(*) FROM app.rutas_servicio WHERE servicio_id = :id"),
                {"id": placeholder_id},
            ).scalar_one()
            == 1
        )

        familia = session.execute(
            text("SELECT servicio_id, alias_ids FROM app.servicios WHERE numero_primer_servicio = '900005'")
        ).one()
        assert familia.servicio_id == "900005"
        assert "900092" in list(familia.alias_ids or [])


def test_ingest_no_pisa_servicio_id_no_numerico_de_tracking(client: TestClient) -> None:
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, numero_linea, estado_servicio) "
                "VALUES ('TRK-900002', '900002', '900002', 'DESCONOCIDO')"
            )
        )
        session.commit()

    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["900002"],
            "Número Línea": ["900070"],
            "Tipo Servicio": ["INT"],
        }
    )

    response = client.post(
        "/servicios/ingest",
        files={"file": ("servicios.xlsx", _excel_bytes(df), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=API_HEADERS,
    )
    assert response.status_code == 200

    detail = client.get("/servicios/detail", params={"id": "900002"}, headers=API_HEADERS)
    body = detail.json()["servicio"]
    assert body["numero_linea"] == "900070"
    assert "TRK-900002" not in body["alias_ids"]  # servicio_id de tracking no se toca
