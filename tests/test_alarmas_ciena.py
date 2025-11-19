# Nombre de archivo: test_alarmas_ciena.py
# Ubicación de archivo: tests/test_alarmas_ciena.py
# Descripción: Tests para el procesamiento de alarmas Ciena (SiteManager y MCP)

"""
Tests para el módulo de procesamiento de alarmas Ciena.

Cubre:
- Detección automática de formato (SiteManager vs MCP)
- Parsing de archivos CSV de ambos formatos
- Generación de archivos Excel
- Validaciones y manejo de errores
- Integración con endpoint de API
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_web_admin import _connect_user_ok
from web.web_app import main as web_main  # type: ignore
from web.web_app.main import app  # type: ignore

from core.parsers.alarmas_ciena import (
    detectar_formato,
    parsear_sitemanager,
    parsear_mcp,
    parsear_alarmas_ciena,
    dataframe_to_excel,
    FormatoAlarma,
)


# ===== Fixtures de archivos CSV de ejemplo =====

@pytest.fixture
def csv_sitemanager() -> bytes:
    """CSV de ejemplo en formato SiteManager (campos entrecomillados)."""
    content = '''"Unit","Class","Severity","Service","Description","Time Raised","Time Cleared","Duration","Acknowledge","Owner"
"NE-001","Equipment","Critical","Service-A","Fiber optic link down","2024-11-15 10:23:45","2024-11-15 11:45:30","01:21:45","Yes","Admin"
"NE-002","Environment","Major","Service-B","High temperature detected"," 2024-11-15 12:30:00 "," - "," - ","No"," - "
"NE-003","Communication","Minor","Service-C","Link degradation","2024-11-15 14:15:22","2024-11-15 14:20:10","00:04:48","Yes","Operator"
'''
    return content.encode('utf-8')


@pytest.fixture
def csv_mcp() -> bytes:
    """CSV de ejemplo en formato MCP (formato estándar)."""
    content = '''Severity,Description,Class,Card type,Device type,Device name,Note,Device tags,NMS alarm ID,NMS alarm instance ID
Critical,Port down on interface GigE 1/1,Equipment,Line Card,Switch,SW-CORE-01,Incident #12345,priority:high;location:datacenter,ALM-001,INST-001
Major,"Temperature threshold exceeded
Detailed description: Temperature sensor reading 85°C",Environment,Environmental,Router,RTR-EDGE-02,,critical:yes,ALM-002,INST-002
Minor,BGP session flapping,Protocol,Control Card,Router,RTR-PE-01,Check peer config,,ALM-003,INST-003
'''
    return content.encode('utf-8')


@pytest.fixture
def csv_invalido() -> bytes:
    """CSV que no corresponde a ningún formato conocido."""
    content = '''Esta,No,Es,Una,Cabecera,Valida
dato1,dato2,dato3,dato4,dato5,dato6
'''
    return content.encode('utf-8')


@pytest.fixture
def csv_vacio() -> bytes:
    """Archivo vacío."""
    return b''


@pytest.fixture
def web_client_logged(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    """Devuelve un TestClient autenticado y el token CSRF correspondiente."""

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok("userpass"))

    client = TestClient(app)
    client.post("/login", data={"username": "user", "password": "userpass"})
    html = client.get("/").text
    csrf = re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", html).group(1)
    return client, csrf


# ===== Tests de detección de formato =====

def test_detectar_formato_sitemanager(csv_sitemanager: bytes):
    """Debe detectar correctamente el formato SiteManager."""
    formato = detectar_formato(csv_sitemanager)
    assert formato == FormatoAlarma.SITEMANAGER


def test_detectar_formato_mcp(csv_mcp: bytes):
    """Debe detectar correctamente el formato MCP."""
    formato = detectar_formato(csv_mcp)
    assert formato == FormatoAlarma.MCP


def test_detectar_formato_invalido(csv_invalido: bytes):
    """Debe devolver DESCONOCIDO para formatos no soportados."""
    formato = detectar_formato(csv_invalido)
    assert formato == FormatoAlarma.DESCONOCIDO


def test_detectar_formato_vacio(csv_vacio: bytes):
    """Debe manejar correctamente archivos vacíos."""
    formato = detectar_formato(csv_vacio)
    assert formato == FormatoAlarma.DESCONOCIDO


# ===== Tests de parsing SiteManager =====

def test_parsear_sitemanager_columnas(csv_sitemanager: bytes):
    """Debe parsear correctamente las columnas de SiteManager."""
    df = parsear_sitemanager(csv_sitemanager)
    
    assert len(df) == 3
    assert len(df.columns) == 10
    
    # Verificar nombres de columnas
    expected_cols = [
        'Unit', 'Class', 'Severity', 'Service', 'Description',
        'Time Raised', 'Time Cleared', 'Duration', 'Acknowledge', 'Owner'
    ]
    assert list(df.columns) == expected_cols


def test_parsear_sitemanager_limpieza_espacios(csv_sitemanager: bytes):
    """Debe limpiar espacios padding en los valores."""
    df = parsear_sitemanager(csv_sitemanager)
    
    # Segunda fila tiene espacios padding en Time Raised
    time_raised = df.iloc[1]['Time Raised']
    assert time_raised == '2024-11-15 12:30:00'  # Sin espacios
    assert not time_raised.startswith(' ')
    assert not time_raised.endswith(' ')


def test_parsear_sitemanager_guiones_vacios(csv_sitemanager: bytes):
    """Debe convertir guiones aislados en cadenas vacías."""
    df = parsear_sitemanager(csv_sitemanager)
    
    # Segunda fila tiene guiones en Time Cleared, Duration y Owner
    assert df.iloc[1]['Time Cleared'] == ''
    assert df.iloc[1]['Duration'] == ''
    assert df.iloc[1]['Owner'] == ''


def test_parsear_sitemanager_valores_validos(csv_sitemanager: bytes):
    """Debe preservar correctamente los valores válidos."""
    df = parsear_sitemanager(csv_sitemanager)
    
    # Primera fila
    assert df.iloc[0]['Unit'] == 'NE-001'
    assert df.iloc[0]['Severity'] == 'Critical'
    assert df.iloc[0]['Description'] == 'Fiber optic link down'
    assert df.iloc[0]['Duration'] == '01:21:45'


# ===== Tests de parsing MCP =====

def test_parsear_mcp_columnas(csv_mcp: bytes):
    """Debe parsear correctamente las columnas de MCP."""
    df = parsear_mcp(csv_mcp)
    
    assert len(df) == 3
    assert len(df.columns) == 10
    
    # Verificar nombres de columnas
    expected_cols = [
        'Severity', 'Description', 'Class', 'Card type', 'Device type',
        'Device name', 'Note', 'Device tags', 'NMS alarm ID', 'NMS alarm instance ID'
    ]
    assert list(df.columns) == expected_cols


def test_parsear_mcp_multilinea(csv_mcp: bytes):
    """Debe manejar correctamente campos con saltos de línea."""
    df = parsear_mcp(csv_mcp)
    
    # Segunda fila tiene descripción multilínea
    desc = df.iloc[1]['Description']
    assert 'Temperature threshold exceeded' in desc
    assert 'Detailed description' in desc
    assert 'Temperature sensor reading 85°C' in desc


def test_parsear_mcp_valores_vacios(csv_mcp: bytes):
    """Debe preservar campos vacíos."""
    df = parsear_mcp(csv_mcp)
    
    # Segunda y tercera fila tienen campos vacíos en Note
    assert df.iloc[1]['Note'] == ''
    assert df.iloc[2]['Note'] == 'Check peer config'


def test_parsear_mcp_valores_complejos(csv_mcp: bytes):
    """Debe manejar valores con caracteres especiales (;, :)."""
    df = parsear_mcp(csv_mcp)
    
    # Primera fila tiene tags con formato key:value;key:value
    tags = df.iloc[0]['Device tags']
    assert 'priority:high' in tags
    assert 'location:datacenter' in tags


# ===== Tests de función principal =====

def test_parsear_alarmas_ciena_sitemanager(csv_sitemanager: bytes):
    """Debe parsear correctamente un CSV de SiteManager."""
    df, formato = parsear_alarmas_ciena(csv_sitemanager)
    
    assert formato == FormatoAlarma.SITEMANAGER
    assert len(df) == 3
    assert 'Unit' in df.columns
    assert 'Severity' in df.columns


def test_parsear_alarmas_ciena_mcp(csv_mcp: bytes):
    """Debe parsear correctamente un CSV de MCP."""
    df, formato = parsear_alarmas_ciena(csv_mcp)
    
    assert formato == FormatoAlarma.MCP
    assert len(df) == 3
    assert 'Device name' in df.columns
    assert 'NMS alarm ID' in df.columns


def test_parsear_alarmas_ciena_invalido(csv_invalido: bytes):
    """Debe lanzar ValueError para formatos no soportados."""
    with pytest.raises(ValueError, match="no soportado"):
        parsear_alarmas_ciena(csv_invalido)


def test_parsear_alarmas_ciena_vacio(csv_vacio: bytes):
    """Debe lanzar ValueError para archivos vacíos."""
    with pytest.raises(ValueError, match="vacío"):
        parsear_alarmas_ciena(csv_vacio)


# ===== Tests de generación de Excel =====

def test_dataframe_to_excel_estructura(csv_sitemanager: bytes):
    """Debe generar un archivo Excel válido."""
    df = parsear_sitemanager(csv_sitemanager)
    excel_bytes = dataframe_to_excel(df)
    
    # Verificar que se generó contenido
    assert len(excel_bytes) > 0
    
    # Verificar que es un Excel válido leyéndolo
    excel_io = io.BytesIO(excel_bytes)
    df_reloaded = pd.read_excel(excel_io, sheet_name='Alarmas')
    
    assert len(df_reloaded) == len(df)
    assert list(df_reloaded.columns) == list(df.columns)


def test_dataframe_to_excel_preserva_datos(csv_mcp: bytes):
    """Debe preservar correctamente los datos en el Excel."""
    df = parsear_mcp(csv_mcp)
    excel_bytes = dataframe_to_excel(df)
    
    # Recargar y verificar datos
    excel_io = io.BytesIO(excel_bytes)
    df_reloaded = pd.read_excel(excel_io, sheet_name='Alarmas')
    
    # Verificar primera fila
    assert df_reloaded.iloc[0]['Severity'] == 'Critical'
    assert df_reloaded.iloc[0]['Device name'] == 'SW-CORE-01'
    
    # Verificar que los valores multilínea se preservan
    desc = df_reloaded.iloc[1]['Description']
    assert 'Temperature threshold exceeded' in desc


def test_dataframe_to_excel_sin_indice(csv_sitemanager: bytes):
    """Debe generar Excel sin columna de índice."""
    df = parsear_sitemanager(csv_sitemanager)
    excel_bytes = dataframe_to_excel(df)
    
    excel_io = io.BytesIO(excel_bytes)
    df_reloaded = pd.read_excel(excel_io, sheet_name='Alarmas')
    
    # No debe haber columna "Unnamed: 0" ni similar
    assert not any('Unnamed' in col for col in df_reloaded.columns)


# ===== Tests de integración con API =====

def test_api_endpoint_sitemanager(csv_sitemanager: bytes, web_client_logged):
    """Debe procesar correctamente un CSV de SiteManager vía API."""
    from io import BytesIO

    client, csrf = web_client_logged
    files = {'file': ('alarmas_sitemanager.csv', BytesIO(csv_sitemanager), 'text/csv')}
    data = {'csrf_token': csrf}

    response = client.post(
        '/api/tools/alarmas-ciena',
        files=files,
        data=data
    )

    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert 'attachment' in response.headers['content-disposition']
    assert 'X-Formato-Detectado' in response.headers
    assert response.headers['X-Formato-Detectado'] == 'SiteManager'
    assert 'X-Filas-Procesadas' in response.headers
    assert int(response.headers['X-Filas-Procesadas']) == 3


def test_api_endpoint_mcp(csv_mcp: bytes, web_client_logged):
    """Debe procesar correctamente un CSV de MCP vía API."""
    from io import BytesIO

    client, csrf = web_client_logged
    files = {'file': ('alarmas_mcp.csv', BytesIO(csv_mcp), 'text/csv')}
    data = {'csrf_token': csrf}

    response = client.post(
        '/api/tools/alarmas-ciena',
        files=files,
        data=data
    )

    assert response.status_code == 200
    assert response.headers['X-Formato-Detectado'] == 'MCP'


def test_api_endpoint_invalido(csv_invalido: bytes, web_client_logged):
    """Debe rechazar archivos con formato no soportado."""
    from io import BytesIO

    client, csrf = web_client_logged
    files = {'file': ('invalido.csv', BytesIO(csv_invalido), 'text/csv')}
    data = {'csrf_token': csrf}

    response = client.post(
        '/api/tools/alarmas-ciena',
        files=files,
        data=data
    )

    assert response.status_code == 415  # Unsupported Media Type
    json_data = response.json()
    assert 'error' in json_data
    assert 'no soportado' in json_data['error'].lower()


def test_api_endpoint_extension_incorrecta(web_client_logged):
    """Debe rechazar archivos que no sean .csv."""
    from io import BytesIO

    client, csrf = web_client_logged
    files = {'file': ('archivo.txt', BytesIO(b'contenido'), 'text/plain')}
    data = {'csrf_token': csrf}

    response = client.post(
        '/api/tools/alarmas-ciena',
        files=files,
        data=data
    )

    assert response.status_code == 400
    json_data = response.json()
    assert 'CSV' in json_data['error']


def test_api_endpoint_vacio(csv_vacio: bytes, web_client_logged):
    """Debe rechazar archivos vacíos."""
    from io import BytesIO

    client, csrf = web_client_logged
    files = {'file': ('vacio.csv', BytesIO(csv_vacio), 'text/csv')}
    data = {'csrf_token': csrf}

    response = client.post(
        '/api/tools/alarmas-ciena',
        files=files,
        data=data
    )

    assert response.status_code == 400
    json_data = response.json()
    assert 'vacío' in json_data['error'].lower()


def test_api_endpoint_sin_auth(csv_sitemanager: bytes):
    """Debe requerir autenticación."""
    from io import BytesIO

    client = TestClient(app)
    files = {'file': ('alarmas.csv', BytesIO(csv_sitemanager), 'text/csv')}
    data = {'csrf_token': 'fake-token'}

    response = client.post(
        '/api/tools/alarmas-ciena',
        files=files,
        data=data
    )

    # Debe redirigir al login o devolver 401
    assert response.status_code in [401, 302, 303]


def test_api_endpoint_csrf_invalido(csv_sitemanager: bytes, web_client_logged):
    """Debe validar el token CSRF."""
    from io import BytesIO

    client, _ = web_client_logged
    files = {'file': ('alarmas.csv', BytesIO(csv_sitemanager), 'text/csv')}
    data = {'csrf_token': 'token-incorrecto'}

    response = client.post(
        '/api/tools/alarmas-ciena',
        files=files,
        data=data
    )

    assert response.status_code == 403
