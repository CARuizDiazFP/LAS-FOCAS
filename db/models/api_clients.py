# Nombre de archivo: api_clients.py
# Ubicación de archivo: db/models/api_clients.py
# Descripción: Clientes OAuth2 client_credentials (M2M) de la API v1 para integraciones interáreas

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import ARRAY

from db.base import Base


class ApiClient(Base):
    """Cliente máquina-a-máquina autorizado a pedir tokens en `POST /api/v1/oauth/token`.

    Una fila por área corporativa integrada. El secreto nunca se guarda en claro: sólo su hash
    (`core/password.py::hash_password`, SHA-256 + bcrypt), y el CLI `scripts/api_clients.py` lo muestra
    una única vez al crearlo o rotarlo.

    `activo` se consulta en **cada** request autenticada, no sólo al emitir el token: los JWT duran
    7 días y desactivar el cliente tiene que cortar el acceso de inmediato.
    """

    __tablename__ = "api_clients"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    client_id = Column(String(64), nullable=False, unique=True, index=True)
    client_secret_hash = Column(String(255), nullable=False)
    nombre_area = Column(String(128), nullable=False)
    activo = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    scopes = Column(ARRAY(String(64)), nullable=False, default=list, server_default=text("'{}'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    ultimo_uso_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ApiClient client_id={self.client_id!r} area={self.nombre_area!r} activo={self.activo}>"
