# Nombre de archivo: test_clientes_routes.py
# Ubicación de archivo: tests/test_clientes_routes.py
# Descripción: Tests HTTP del router interno /clientes (categoría por cliente, lista oficial, alias, fusión, sync)

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from core.services.clientes_categoria_service import (
    ClienteCategoriaError,
    ClienteNoEncontradoError,
    PrevisualizacionLista,
    ResumenSync,
)
from core.services.servicios_categoria_service import CategoriaInvalidaError

client = TestClient(app)
API_HEADERS = {"Authorization": "Bearer test-api-key"}
MODULO = "api.app.routes.clientes"


@pytest.fixture
def sesion():
    with patch(f"{MODULO}.SessionLocal") as mock_session_local:
        session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = session
        yield session


class TestAutenticacion:
    @pytest.mark.parametrize(
        ("metodo", "ruta"),
        [
            ("get", "/clientes/por-categoria"),
            ("patch", "/clientes/categoria"),
            ("post", "/clientes/lista/previsualizar"),
            ("post", "/clientes/lista/aplicar"),
            ("post", "/clientes/fusionar"),
            ("post", "/clientes/1/alias"),
            ("delete", "/clientes/alias/1"),
            ("post", "/clientes/sincronizar"),
        ],
    )
    def test_sin_api_key_devuelve_401_o_403(self, metodo: str, ruta: str) -> None:
        assert getattr(client, metodo)(ruta).status_code in (401, 403)


class TestListar:
    def test_devuelve_los_grupos_sin_commit(self, sesion: MagicMock) -> None:
        grupos = {"6": [], "sin": [{"id": 1, "nombre": "X"}]}
        with patch(f"{MODULO}.listar_clientes_por_categoria", return_value=grupos) as listar:
            respuesta = client.get("/clientes/por-categoria", headers=API_HEADERS)

        assert respuesta.status_code == 200
        assert respuesta.json() == {"grupos": grupos}
        listar.assert_called_once_with(sesion)
        sesion.commit.assert_not_called()


class TestCambiarCategoria:
    def test_manual_con_usuario_y_commit(self, sesion: MagicMock) -> None:
        resultado = {"actualizados": 2, "no_encontrados": [9], "sync": ResumenSync().to_dict()}
        with patch(f"{MODULO}.cambiar_categoria", return_value=resultado) as cambiar:
            respuesta = client.patch(
                "/clientes/categoria",
                json={"cliente_ids": [1, 2, 9], "categoria": 4},
                headers={**API_HEADERS, "X-Usuario": "admin"},
            )

        assert respuesta.status_code == 200
        assert respuesta.json() == resultado
        cambiar.assert_called_once_with(sesion, [1, 2, 9], 4, "admin", automatico=False)
        sesion.commit.assert_called_once()

    def test_sin_categorizar_y_automatico(self, sesion: MagicMock) -> None:
        with patch(f"{MODULO}.cambiar_categoria", return_value={}) as cambiar:
            r1 = client.patch("/clientes/categoria", json={"cliente_ids": [1], "categoria": None}, headers=API_HEADERS)
            r2 = client.patch(
                "/clientes/categoria", json={"cliente_ids": [1], "automatico": True}, headers=API_HEADERS
            )

        assert (r1.status_code, r2.status_code) == (200, 200)
        assert cambiar.call_args_list[0].args == (sesion, [1], None, None)
        assert cambiar.call_args_list[1].kwargs == {"automatico": True}

    def test_error_de_validacion_devuelve_400_sin_commit(self, sesion: MagicMock) -> None:
        with patch(f"{MODULO}.cambiar_categoria", side_effect=CategoriaInvalidaError("categoria fuera de rango")):
            respuesta = client.patch(
                "/clientes/categoria", json={"cliente_ids": [1], "categoria": 9}, headers=API_HEADERS
            )

        assert respuesta.status_code == 400
        assert "fuera de rango" in respuesta.json()["detail"]
        sesion.commit.assert_not_called()


class TestLista:
    def test_previsualizar_json(self, sesion: MagicMock) -> None:
        previa = PrevisualizacionLista(categoria=6, modo="agregar", nuevos=["BANCO UNO"])
        with patch(f"{MODULO}.previsualizar_lista", return_value=previa) as previsualizar:
            respuesta = client.post(
                "/clientes/lista/previsualizar",
                json={"nombres": ["BANCO UNO"], "categoria": 6, "modo": "agregar"},
                headers=API_HEADERS,
            )

        assert respuesta.status_code == 200
        assert respuesta.json()["nuevos"] == ["BANCO UNO"]
        previsualizar.assert_called_once_with(sesion, ["BANCO UNO"], 6, "agregar")
        sesion.commit.assert_not_called()

    def test_previsualizar_multipart_txt(self, sesion: MagicMock) -> None:
        previa = PrevisualizacionLista(categoria=None, modo="reemplazar")
        with patch(f"{MODULO}.previsualizar_lista", return_value=previa) as previsualizar:
            respuesta = client.post(
                "/clientes/lista/previsualizar",
                files={"file": ("lista.txt", b"BANCO UNO\nBANCO DOS\n", "text/plain")},
                data={"categoria": "sin", "modo": "reemplazar"},
                headers=API_HEADERS,
            )

        assert respuesta.status_code == 200, respuesta.text
        previsualizar.assert_called_once_with(sesion, ["BANCO UNO", "BANCO DOS"], None, "reemplazar")

    def test_aplicar_multipart_csv_con_usuario_y_commit(self, sesion: MagicMock) -> None:
        resultado = {"creados": 1, "sync": ResumenSync().to_dict()}
        with patch(f"{MODULO}.aplicar_lista", return_value=resultado) as aplicar:
            respuesta = client.post(
                "/clientes/lista/aplicar",
                files={"file": ("lista.csv", b"Cliente\nBANCO UNO\n", "text/csv")},
                data={"categoria": "5"},
                headers={**API_HEADERS, "X-Usuario": "admin"},
            )

        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json() == resultado
        aplicar.assert_called_once_with(sesion, ["BANCO UNO"], 5, "agregar", usuario="admin")
        sesion.commit.assert_called_once()

    def test_extension_no_soportada_devuelve_415(self, sesion: MagicMock) -> None:
        respuesta = client.post(
            "/clientes/lista/previsualizar",
            files={"file": ("lista.pdf", b"%PDF", "application/pdf")},
            data={"categoria": "6"},
            headers=API_HEADERS,
        )
        assert respuesta.status_code == 415

    def test_archivo_mayor_a_5_mb_devuelve_413(self, sesion: MagicMock) -> None:
        respuesta = client.post(
            "/clientes/lista/previsualizar",
            files={"file": ("lista.txt", b"x" * (5 * 1024 * 1024 + 1), "text/plain")},
            data={"categoria": "6"},
            headers=API_HEADERS,
        )
        assert respuesta.status_code == 413

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"data": {"categoria": "6"}},  # multipart sin archivo
            {"files": {"file": ("lista.txt", b"X\n", "text/plain")}, "data": {"categoria": "abc"}},
            {"json": {"nombres": "no-es-lista", "categoria": 6}},
            {"content": b"no-json", "headers": {"Content-Type": "application/json"}},
        ],
    )
    def test_pedido_invalido_devuelve_400(self, sesion: MagicMock, kwargs: dict) -> None:
        headers = {**API_HEADERS, **kwargs.pop("headers", {})}
        if "data" in kwargs and "files" not in kwargs:
            kwargs["files"] = {"otro": ("a.txt", b"", "text/plain")}
        respuesta = client.post("/clientes/lista/previsualizar", headers=headers, **kwargs)
        assert respuesta.status_code == 400, respuesta.text

    def test_error_del_servicio_devuelve_400(self, sesion: MagicMock) -> None:
        with patch(f"{MODULO}.aplicar_lista", side_effect=ClienteCategoriaError("La lista no tiene nombres")):
            respuesta = client.post(
                "/clientes/lista/aplicar", json={"nombres": [], "categoria": 6}, headers=API_HEADERS
            )
        assert respuesta.status_code == 400
        sesion.commit.assert_not_called()


class TestFusionarYAlias:
    def test_fusionar(self, sesion: MagicMock) -> None:
        resultado = {"destino_id": 1, "fusionados": [2], "alias_movidos": 1, "sync": {}}
        with patch(f"{MODULO}.fusionar_clientes", return_value=resultado) as fusionar:
            respuesta = client.post(
                "/clientes/fusionar", json={"destino_id": 1, "origen_ids": [2]}, headers=API_HEADERS
            )
        assert respuesta.status_code == 200
        assert respuesta.json() == resultado
        fusionar.assert_called_once_with(sesion, 1, [2])
        sesion.commit.assert_called_once()

    def test_fusionar_inexistente_devuelve_404(self, sesion: MagicMock) -> None:
        with patch(f"{MODULO}.fusionar_clientes", side_effect=ClienteNoEncontradoError("Cliente 1 no encontrado")):
            respuesta = client.post(
                "/clientes/fusionar", json={"destino_id": 1, "origen_ids": [2]}, headers=API_HEADERS
            )
        assert respuesta.status_code == 404
        sesion.commit.assert_not_called()

    def test_agregar_alias(self, sesion: MagicMock) -> None:
        alias = MagicMock(id=7, cliente_id=1, clave="BANCO UNO", nombre_original="Banco Uno SA", origen="MANUAL")
        with patch(f"{MODULO}.agregar_alias", return_value=alias) as agregar:
            respuesta = client.post("/clientes/1/alias", json={"nombre": "Banco Uno SA"}, headers=API_HEADERS)
        assert respuesta.status_code == 200
        assert respuesta.json() == {
            "id": 7,
            "cliente_id": 1,
            "clave": "BANCO UNO",
            "nombre_original": "Banco Uno SA",
            "origen": "MANUAL",
        }
        agregar.assert_called_once_with(sesion, 1, "Banco Uno SA")
        sesion.commit.assert_called_once()

    def test_agregar_alias_rechazado_devuelve_400(self, sesion: MagicMock) -> None:
        with patch(f"{MODULO}.agregar_alias", side_effect=ClienteCategoriaError("usar fusionar clientes")):
            respuesta = client.post("/clientes/1/alias", json={"nombre": "X"}, headers=API_HEADERS)
        assert respuesta.status_code == 400

    def test_quitar_alias(self, sesion: MagicMock) -> None:
        resultado = {"alias_id": 7, "cliente_id": 1, "sync": {}}
        with patch(f"{MODULO}.quitar_alias", return_value=resultado) as quitar:
            respuesta = client.delete("/clientes/alias/7", headers=API_HEADERS)
        assert respuesta.status_code == 200
        assert respuesta.json() == resultado
        quitar.assert_called_once_with(sesion, 7)
        sesion.commit.assert_called_once()

    def test_quitar_alias_inexistente_devuelve_404(self, sesion: MagicMock) -> None:
        with patch(f"{MODULO}.quitar_alias", side_effect=ClienteNoEncontradoError("Alias 7 no encontrado")):
            respuesta = client.delete("/clientes/alias/7", headers=API_HEADERS)
        assert respuesta.status_code == 404


class TestSincronizar:
    def test_sync_global_con_commit(self, sesion: MagicMock) -> None:
        resumen = ResumenSync(clientes_creados=1, clientes_recalculados=2, servicios_actualizados=3)
        with patch(f"{MODULO}.sincronizar_categorias", return_value=resumen) as sync:
            respuesta = client.post("/clientes/sincronizar", headers=API_HEADERS)
        assert respuesta.status_code == 200
        assert respuesta.json() == resumen.to_dict()
        sync.assert_called_once_with(sesion)
        sesion.commit.assert_called_once()
