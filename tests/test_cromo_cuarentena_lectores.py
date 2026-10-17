# Nombre de archivo: test_cromo_cuarentena_lectores.py
# Ubicación de archivo: tests/test_cromo_cuarentena_lectores.py
# Descripción: Guardia de repo — ningún consumidor del uso lee app.cromo_servicio_match directo;
# todos pasan por la vista app.v_cromo_servicio_match_vigente (cuarentena de inconsistencias)

"""La cuarentena de inconsistencias de Cromo (Tarea 3) sólo es efectiva si TODO lo que consume "qué
servicio ocupa este pelo" lee la vista `app.v_cromo_servicio_match_vigente`, que excluye los pelos
de casos en `CUARENTENA`. Basta un SELECT nuevo contra la tabla para que un pelo en cuarentena
vuelva a contar como uso en algún rincón (Slack, FO Monitor, API v1...).

Este test recorre el código Python del repo y falla si algún módulo fuera de la lista de
escritores lee la tabla con `FROM`/`JOIN`. Los escritores (ingesta, bajas, fusión de servicios y
el propio detector, que necesita el uso crudo) quedan explícitos abajo con su motivo.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# Directorios que no son código de la aplicación en ejecución: tests, scripts de uso único,
# migraciones (la vista misma se crea leyendo la tabla) y entornos/artefactos.
_DIRECTORIOS_EXCLUIDOS = {"tests", "scripts", "node_modules", "__pycache__", "alembic"}

# Módulos que leen la tabla a propósito. Cualquier otro lector es un bug de cuarentena.
ESCRITORES_PERMITIDOS: dict[str, str] = {
    "core/services/cromo/ingesta.py": (
        "fase_servicios / conciliar_matches_de_cable escriben la tabla y leen sus propias filas "
        "para reconciliarlas"
    ),
    "core/services/cromo/bajas_service.py": "baja lógica de cables: lee y borra matches",
    "core/services/servicios_fusion_prov.py": "fusión de servicios: cuenta y reasigna matches",
    "core/services/cromo/inconsistencias_cromo.py": (
        "el detector necesita el uso crudo (un pelo en cuarentena sigue 'en uso' para detectar) y el "
        "filtro por servicio del listado de casos busca justamente los pelos en cuarentena"
    ),
}

_LECTURA_DIRECTA = re.compile(r"\b(FROM|JOIN)\s+app\.cromo_servicio_match\b", re.IGNORECASE)
# Lecturas por ORM del modelo de la tabla: `select(CromoServicioMatch)`, `select(CromoServicioMatch.x)`,
# `session.query(CromoServicioMatch)`, `session.get(CromoServicioMatch, ...)`, `.join(CromoServicioMatch`.
# Construir filas (`CromoServicioMatch(...)`) es escritura y no matchea.
_LECTURA_ORM = re.compile(r"\b(select|query|get|join|outerjoin)\(\s*[^)]*?\bCromoServicioMatch\b")


def _archivos_python() -> list[Path]:
    archivos = []
    for ruta in RAIZ.rglob("*.py"):
        relativas = ruta.relative_to(RAIZ).parts
        if any(p in _DIRECTORIOS_EXCLUIDOS or p.startswith(".") for p in relativas[:-1]):
            continue
        archivos.append(ruta)
    return archivos


def test_ningun_consumidor_lee_la_tabla_de_matches_directo() -> None:
    infractores = []
    for ruta in _archivos_python():
        relativa = ruta.relative_to(RAIZ).as_posix()
        if relativa in ESCRITORES_PERMITIDOS:
            continue
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        # Sobre el texto entero, no por línea: `\s+` también cubre un `FROM` y la tabla en líneas
        # distintas.
        for patron in (_LECTURA_DIRECTA, _LECTURA_ORM):
            for hallazgo in patron.finditer(texto):
                numero = texto.count("\n", 0, hallazgo.start()) + 1
                infractores.append(f"{relativa}:{numero}: {' '.join(hallazgo.group(0).split())}")
    assert not infractores, (
        "Estos lectores ignoran la cuarentena de inconsistencias; usar "
        "app.v_cromo_servicio_match_vigente:\n" + "\n".join(infractores)
    )


def test_el_patron_orm_detecta_lecturas_y_no_escrituras() -> None:
    for lectura in (
        "select(CromoServicioMatch)",
        "select(CromoServicioMatch.servicio_id).where(x)",
        "session.query(CromoServicioMatch).filter(y)",
        "session.query(CromoPelo, CromoServicioMatch)",
        "session.get(CromoServicioMatch, 1)",
        "stmt.join(CromoServicioMatch, CromoServicioMatch.pelo_n_id == CromoPelo.n_id)",
    ):
        assert _LECTURA_ORM.search(lectura), lectura
    for escritura in ("sesion.add(CromoServicioMatch(pelo_n_id=1))", "class CromoServicioMatch(Base):"):
        assert not _LECTURA_ORM.search(escritura), escritura


def test_la_lista_de_escritores_no_tiene_entradas_viejas() -> None:
    """Una entrada que ya no lee la tabla es un permiso que sobra: se quita."""
    for relativa in ESCRITORES_PERMITIDOS:
        ruta = RAIZ / relativa
        assert ruta.exists(), f"{relativa} ya no existe"
        texto = ruta.read_text(encoding="utf-8")
        assert _LECTURA_DIRECTA.search(texto) or _LECTURA_ORM.search(texto), (
            f"{relativa} ya no lee app.cromo_servicio_match: sacarlo de ESCRITORES_PERMITIDOS"
        )


def test_los_consumidores_principales_leen_la_vista() -> None:
    for relativa in (
        "core/services/cromo/verificador.py",
        "core/services/servicio_traza.py",
        "core/services/cromo/servicios_sin_odf.py",
        "core/services/cromo/detalle.py",
        "core/services/cromo/inventario.py",
        "core/services/cromo/odf_inventario.py",
        "core/services/fo_monitor/consultas_web.py",
        "core/services/cromo/camino_optico_service.py",
        "core/services/cromo/auditoria_huerfanos_global.py",
    ):
        texto = (RAIZ / relativa).read_text(encoding="utf-8")
        assert "app.v_cromo_servicio_match_vigente" in texto, relativa
