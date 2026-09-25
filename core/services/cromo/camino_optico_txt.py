# Nombre de archivo: camino_optico_txt.py
# Ubicación de archivo: core/services/cromo/camino_optico_txt.py
# Descripción: Serializa un camino óptico de Cromo al formato de los trackings .txt legacy, sin la columna de atenuación

from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.services.cromo.camino_optico_service import (
    TIPO_CONECTOR_ODF,
    TIPO_FUSION,
    TIPO_NO_RESUELTO,
    TIPO_PELO,
    CaminoOptico,
    NodoCamino,
)

# Decoraciones medidas carácter por carácter sobre los archivos reales (45 archivos, 10.400
# líneas): 10 flechas por lado, 31 `+`, y 51 `-` en los separadores que rodean el tramo del cable
# de la cabecera.
_FLECHA_IZQ = "⇃" * 10
_FLECHA_DER = "⇂" * 10
_SEPARADOR_PLUS = "+" * 31
_SEPARADOR_GUION = "-" * 51
_MARCA_PELO = "\U0001f82b"

# Los trackings legacy usan CRLF (verificado: 397 CR en las 398 líneas del archivo de oro).
_EOL = "\r\n"


def _numero(valor: Optional[float]) -> str:
    """Formatea un metraje como lo hacen los archivos reales: sin decimales si es entero, y con
    uno si no (`328`, `201.9`, `2348.3`)."""
    if valor is None:
        return "0"
    redondeado = round(float(valor), 1)
    if redondeado == int(redondeado):
        return str(int(redondeado))
    return f"{redondeado:.1f}"


def _ordinal_humano(valor: Optional[str]) -> str:
    """El orden de Cromo es 0-based y el del tracking legacy 1-based.

    Verificado contra el archivo de oro: el pelo con `at.74 = 8` y su tubo con `at.72 = 1` se
    imprimen como `(NR / 2 - 9)`. Es la misma corrección que ya documentó este repo para el
    comando "Info cable" de Slack ("orden humano = orden de Cromo + 1").
    """
    if valor is None:
        return "?"
    try:
        return str(int(valor) + 1)
    except (TypeError, ValueError):
        return str(valor)


def nombre_archivo_tracking(servicio_numero: Optional[str], pelo_n_id: int) -> str:
    """Nombre del archivo generado.

    Los trackings manuales se llaman `<servicio> <alias>.txt` (ej. `93154 C21.txt`) y el parser
    saca el servicio del NOMBRE del archivo, no del contenido. Se usa `CROMO` como sufijo en vez
    de un alias tipo `C21`: el regex de alias exige letra+dígitos, así que `CROMO` no matchea y el
    archivo no finge ser uno de los trackings numerados a mano — pero el número de servicio sí se
    recupera.
    """
    if servicio_numero and servicio_numero.isdigit() and len(servicio_numero) >= 4:
        return f"{servicio_numero} CROMO.txt"
    return f"tracking_cromo_pelo_{pelo_n_id}.txt"


def _linea_tramo(nodo: NodoCamino, acum_geo: float, acum_real: float) -> str:
    return (
        f"{nodo.cable_nombre or '?'}: {nodo.numero_pelo or '?'} "
        f"({nodo.tubo_color or '?'} / {_ordinal_humano(nodo.tubo_orden)} - "
        f"{_ordinal_humano(nodo.orden_pelo)}) --> {_numero(nodo.distancia_geo_m)} / "
        f"{_numero(acum_geo)} mts * {_numero(acum_real)} mts"
    )


def _linea_terminal(nodo: NodoCamino, acum_geo: float, acum_real: float) -> str:
    return (
        f"{nodo.patchera_nombre or nodo.odf_nombre or '?'}: {nodo.conector_numero or '?'} "
        f"--> Sin longitud / {_numero(acum_geo)} mts * {_numero(acum_real)} mts"
    )


def secuencia_para_tracking(camino: CaminoOptico) -> list[NodoCamino]:
    """Orden lineal del archivo: `reversed(lado_b)` → raíz → `lado_a`.

    Los dos lados nacen en el pelo consultado, así que el archivo lineal recorre uno al revés,
    pasa por la raíz y sigue por el otro. Esta dirección reproduce la del archivo de oro
    (`93154 C21.txt`), pero **cuál lado es `a` y cuál es `b` lo decide Cromo arbitrariamente**
    (lo dice el manual), así que un tracking legacy puede venir recorrido al revés sin que eso
    signifique que alguno de los dos esté mal.
    """
    nodos = list(reversed(camino.lado_b))
    if camino.raiz is not None:
        nodos.append(camino.raiz)
    nodos.extend(camino.lado_a)
    return nodos


def renderizar_tracking_txt(camino: CaminoOptico, *, generado_en: datetime) -> str:
    """Serializa un camino al formato de los trackings `.txt` legacy.

    Reproduce la gramática real (cabecera con cable/tubo/pelo, `Empalme <botella>: <nombre>`,
    líneas de tramo con los dos ordinales +1 y los metrajes acumulados, terminales de ODF, y los
    separadores que rodean el tramo del cable de cabecera), con **una diferencia deliberada: no
    lleva la columna de atenuación**. Cromo no publica el dB por API — su web lo calcula — y
    fabricar un número que un técnico usa para localizar fallas no es aceptable. Consecuencia
    asumida: el parser legacy no reconoce estas líneas como tramos (su regex exige terminar en un
    número seguido de `dB`), así que un re-upload recupera empalmes y puntas pero no tramos.

    Función pura: no toca red ni base. El camino es un elemento vivo —cambia ante cortes— por eso
    la cabecera lleva la fecha y hora de generación.
    """
    acum_geo = 0.0
    acum_real = 0.0
    raiz = camino.raiz

    lineas: list[str] = [
        "# Tracking óptico GENERADO desde Cromo por LAS-FOCAS — no es una medición de campo.",
        f"# Fuente: GET /network/fo/{camino.pelo_n_id}/path · generado {generado_en.isoformat()}",
        f"# Servicio at.62={camino.servicio_at62 or 's/d'} · at.61={camino.servicio_at61 or 's/d'}",
        "# El camino es un elemento vivo: cambia ante cortes y reruteos. Cromo es la fuente de la verdad.",
        "# Cromo no publica la atenuación por API: las líneas de tramo NO llevan la columna dB.",
        "",
        f"Cable: {(raiz.cable_nombre if raiz else None) or '?'}",
        f"{_FLECHA_IZQ} TUBO: {(raiz.tubo_color if raiz else None) or '?'} / "
        f"{_ordinal_humano(raiz.tubo_orden if raiz else None)} {_FLECHA_DER}",
        "",
        _SEPARADOR_PLUS,
        f"Nombre de Pelo: {(raiz.numero_pelo if raiz else None) or '?'} {_MARCA_PELO}",
        "",
    ]

    for indice, nodo in enumerate(secuencia_para_tracking(camino)):
        es_raiz = raiz is not None and nodo is raiz
        es_primer_nodo = indice == 0

        if nodo.tipo == TIPO_PELO:
            acum_geo += nodo.distancia_geo_m or 0.0
            acum_real += nodo.distancia_real_m or 0.0
            cuerpo = [_linea_tramo(nodo, acum_geo, acum_real)]
            if es_raiz:
                # El tramo del cable nombrado en la cabecera va entre separadores, igual que en
                # los archivos reales.
                lineas.extend(["", _SEPARADOR_GUION, cuerpo[0], "", _SEPARADOR_GUION])
                continue
        elif nodo.tipo == TIPO_FUSION:
            cuerpo = [f"Empalme {nodo.botella_id or nodo.id_cromo}: {nodo.botella_nombre or 's/d'}"]
        elif nodo.tipo == TIPO_CONECTOR_ODF:
            # El legacy emite también la ODF como un `Empalme <id_odf>: <nombre>`, y va del lado
            # que mira al interior del camino: al principio del archivo después del terminal, al
            # final antes. Verificado en el archivo de oro (línea 8 terminal → línea 10 ODF al
            # inicio; línea 396 ODF → línea 398 terminal al final).
            #
            # Cromo además usa a veces la etiqueta `Patch <id_odf>` cuando el camino pasa de una
            # ODF a otra por un patch cord (visto en su web, no en ninguno de los 45 archivos
            # reales). No se emite: distinguirlo con certeza necesita más muestras que una.
            terminal = _linea_terminal(nodo, acum_geo, acum_real)
            linea_odf = (
                f"Empalme {nodo.odf_id}: {nodo.odf_nombre or 's/d'}" if nodo.odf_id else None
            )
            if linea_odf is None:
                cuerpo = [terminal]
            elif es_primer_nodo:
                cuerpo = [terminal, "", linea_odf]
            else:
                cuerpo = [linea_odf, "", terminal]
        elif nodo.tipo == TIPO_NO_RESUELTO:
            # Un camino incompleto se declara en el archivo en vez de disimularse: el parser
            # ignora las líneas que empiezan con `#`, y el hueco queda documentado en su posición.
            cuerpo = [f"# Elemento {nodo.id_cromo} del camino no vino resuelto en la respuesta de Cromo."]
        else:
            cuerpo = [f"# {nodo.tipo} {nodo.id_cromo}: {nodo.nombre or 's/d'}"]

        lineas.append("")
        lineas.extend(cuerpo)

    return _EOL.join(lineas) + _EOL


__all__ = ["nombre_archivo_tracking", "renderizar_tracking_txt", "secuencia_para_tracking"]
