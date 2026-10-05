# Nombre de archivo: clasificador.py
# Ubicación de archivo: core/sla_consumo/clasificador.py
# Descripción: Agrupa el Tipo Solución Reclamo en FO / FO Cod 3 / Carrier / Otros / Cierre Cliente

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

GRUPO_FO = "FO (excepto Cod 3)"
GRUPO_FO_COD3 = "FO Cod 3 (Corte en Bandeja)"
GRUPO_CARRIER = "Carrier"
GRUPO_OTROS = "Otros"
GRUPO_CLIENTE = "Cierre Cliente"
GRUPOS_ORDEN: tuple[str, ...] = (GRUPO_FO, GRUPO_FO_COD3, GRUPO_CARRIER, GRUPO_OTROS, GRUPO_CLIENTE)

# El código va entre paréntesis al final; el origen trunca a 50 caracteres y puede faltar el ")".
_CODIGO_RE = re.compile(r"\((\d+)\)?\s*$")


@dataclass(frozen=True)
class Cierre:
    grupo: str
    codigo: int | None
    cuenta_sla: bool


def _normalizar(texto: str) -> str:
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sin_acentos).strip().lower()


def valores_cliente_config() -> frozenset[str]:
    crudo = os.getenv("SLA_CIERRE_CLIENTE_VALORES", "")
    return frozenset(_normalizar(v) for v in crudo.split(";") if v.strip())


def clasificar_cierre(tipo_solucion: str | None, valores_cliente: frozenset[str] | None = None) -> Cierre:
    if valores_cliente is None:
        valores_cliente = valores_cliente_config()
    texto = _normalizar(tipo_solucion or "")
    coincidencia = _CODIGO_RE.search(texto)
    codigo = int(coincidencia.group(1)) if coincidencia else None
    if texto in valores_cliente:
        return Cierre(GRUPO_CLIENTE, codigo, cuenta_sla=False)
    if texto == "carrier":
        return Cierre(GRUPO_CARRIER, None, cuenta_sla=True)
    if texto.startswith("pe-"):
        grupo = GRUPO_FO_COD3 if codigo == 3 else GRUPO_FO
        return Cierre(grupo, codigo, cuenta_sla=True)
    return Cierre(GRUPO_OTROS, None, cuenta_sla=True)
