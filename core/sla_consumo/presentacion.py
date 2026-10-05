# Nombre de archivo: presentacion.py
# Ubicación de archivo: core/sla_consumo/presentacion.py
# Descripción: Capa de presentación compartida del informe SLA consumido — etiquetas, colores, leyendas y formateo

from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from core.sla_consumo import metricas as m
from core.utils.excel_duraciones import TZ_AR

VACIO = "—"

# nombre de columna → (etiqueta en español, formato). Formatos: texto, entero, horas, pct, fecha, bool.
COLUMNAS: dict[str, tuple[str, str]] = {
    # Servicios
    "clave_servicio": ("Clave de servicio", "texto"),
    "servicio_id": ("Servicio (ID visible)", "texto"),
    "lineas_asociadas": ("Líneas asociadas", "texto"),
    "nombre_cliente": ("Cliente", "texto"),
    "tipo_servicio": ("Tipo de servicio", "texto"),
    "sla_prometido": ("SLA prometido", "pct"),
    "presupuesto_h": ("Presupuesto anual (h)", "horas"),
    "horas_netas": ("Horas netas (todos los reclamos)", "horas"),
    "horas_computables": ("Horas computables", "horas"),
    "horas_excluidas": ("Horas excluidas (cierre Cliente)", "horas"),
    "horas_fo": ("Horas FO", "horas"),
    "horas_fo_general": ("Horas FO general", "horas"),
    "horas_fo_cod3": ("Horas FO Cod 3", "horas"),
    "horas_carrier": ("Horas Carrier", "horas"),
    "horas_otros": ("Horas Otros", "horas"),
    "horas_restantes": ("Horas restantes", "horas"),
    "horas_excedidas": ("Horas excedidas", "horas"),
    "pct_real": ("% real del presupuesto", "pct"),
    "pct_visible": ("% visible (tope 100 %)", "pct"),
    "aporte_fo_pct": ("Aporte FO (% del presupuesto)", "pct"),
    "participacion_fo_pct": ("Participación FO (% de lo consumido)", "pct"),
    "reclamos": ("Reclamos", "entero"),
    "eventos_reales": ("Eventos reales", "entero"),
    "reclamos_sin_evento": ("Reclamos sin evento", "entero"),
    "semaforo": ("Semáforo", "texto"),
    "estado": ("Estado", "texto"),
    "sla_entregado_oficial": ("SLA entregado (oficial)", "pct"),
    "horas_reclamos_todos_oficial": ("Horas de reclamos (oficial)", "horas"),
    "horas_restantes_oficial": ("Horas restantes (oficial)", "horas"),
    # Reclamos (Servicio x Reclamo, Reclamos sin evento, No vinculados)
    "numero_reclamo": ("Nº de reclamo", "texto"),
    "numero_evento": ("Nº de evento", "texto"),
    "numero_linea": ("Nº de línea", "texto"),
    "numero_primer_servicio": ("Nº de primer servicio", "texto"),
    "fecha_inicio": ("Inicio del reclamo", "fecha"),
    "fecha_cierre": ("Cierre del reclamo", "fecha"),
    "horas_totales_problema": ("Horas totales del problema", "horas"),
    "horas_indisponibilidad_problema": ("Horas de indisponibilidad", "horas"),
    "horas_netas_escalamiento_carrier": ("Horas netas de escalamiento a carrier", "horas"),
    "sector_responsable": ("Sector responsable", "texto"),
    "descripcion_problema": ("Descripción del problema", "texto"),
    "tipo_solucion": ("Tipo de solución", "texto"),
    "descripcion_solucion": ("Descripción de la solución", "texto"),
    "carrier": ("Carrier", "texto"),
    "numero_reclamo_carrier": ("Nº de reclamo del carrier", "texto"),
    "codigo_cierre": ("Código de cierre", "entero"),
    "grupo_cierre": ("Grupo de cierre", "texto"),
    "causa": ("Causa", "texto"),
    "cuenta_sla": ("Cuenta para SLA", "bool"),
    "indicador": ("Indicador del reclamo", "texto"),
    "sin_evento": ("Sin evento", "bool"),
    "evento_clave": ("Evento (o reclamo si no tiene)", "texto"),
    "consumo_acum_antes": ("Acumulado antes (h)", "horas"),
    "consumo_acum_despues": ("Acumulado después (h)", "horas"),
    "restantes_acum": ("Restantes tras el reclamo (h)", "horas"),
    "excedidas_acum": ("Excedidas tras el reclamo (h)", "horas"),
    "pct_aporte_real": ("Aporte real (% del presupuesto)", "pct"),
    "alcanza_primera_vez": ("Alcanza el presupuesto por primera vez", "bool"),
    "supera_primera_vez": ("Supera el presupuesto por primera vez", "bool"),
    # Eventos
    "inicio_observado": ("Inicio observado", "fecha"),
    "cierre_observado": ("Cierre observado", "fecha"),
    "servicios_afectados": ("Servicios afectados", "entero"),
    "horas_servicio": ("Horas-servicio", "horas"),
    "servicios_agotados_o_excedidos": ("Servicios agotados o excedidos", "entero"),
    "n_suficiente_solo": ("Nº servicios donde es suficiente solo", "entero"),
    "servicios_suficiente_solo": ("Servicios donde es suficiente solo", "texto"),
    "n_cruza_umbral": ("Nº servicios donde cruza el umbral", "entero"),
    "servicios_cruza_umbral": ("Servicios donde cruza el umbral", "texto"),
    "n_determinante": ("Nº servicios donde es determinante", "entero"),
    "servicios_determinante": ("Servicios donde es determinante", "texto"),
    # Evento x Servicio / reclamo sin evento
    "reclamos_ids": ("Nº de reclamos incluidos", "texto"),
    "horas_no_fo": ("Horas no FO", "horas"),
    "consumo_total_servicio": ("Consumo total del servicio (h)", "horas"),
    "estado_servicio": ("Estado del servicio", "texto"),
    "suficiente_solo": ("Suficiente solo", "texto"),
    "cruza_umbral": ("Cruza el umbral", "bool"),
    "determinante_al_excluir": ("Determinante al excluir", "bool"),
    "participa_en_agotado_o_excedido": ("Participa en servicio agotado o excedido", "bool"),
    # Inconsistencias
    "tipo": ("Tipo de inconsistencia", "texto"),
    "detalle": ("Detalle", "texto"),
    # Código de cierre, detalle por tipo de solución, composición y Carrier x Cliente
    "grupo": ("Grupo de cierre", "texto"),
    "eventos": ("Eventos", "entero"),
    "eventos_y_reclamos_sin_evento": ("Eventos + reclamos sin evento", "entero"),
    "horas": ("Horas netas", "horas"),
    "horas_sla": ("Horas que cuentan para SLA", "horas"),
    "pct_horas": ("% de horas netas", "pct"),
    "pct": ("% del total computable", "pct"),
    "servicios": ("Servicios", "entero"),
}

# Columnas con formato "pct" que el origen ya entrega como fracción 0-1 (no como 0-100).
COLUMNAS_FRACCION = frozenset({"sla_entregado_oficial"})

COLORES_SEMAFORO: dict[str, str | None] = {m.ROJO: "C0392B", m.AMARILLO: "F1C40F", m.VERDE: "27AE60",
                                           m.SIN_COLOR: None}
COLORES_ESTADO: dict[str, str] = {m.ESTADO_EXCEDIDO: "C0392B", m.ESTADO_AGOTADO: "E67E22",
                                  m.ESTADO_DENTRO: "27AE60", m.ESTADO_SIN_CONSUMO: "BDC3C7",
                                  m.ESTADO_NO_EVALUABLE: "7F8C8D"}
COLORES_CAUSA: dict[str, str] = {m.CAUSA_FO_GENERAL: "C0392B", m.CAUSA_FO_COD3: "E67E22",
                                 m.CAUSA_CARRIER: "2980B9", m.CAUSA_OTROS: "7F8C8D"}
COLORES_SUFICIENTE: dict[str, str] = {"Excede": "C0392B", "Agota": "E67E22", "No evaluable": "7F8C8D"}

# Etiquetas de `totales`: reclamos y horas_netas cubren TODOS los reclamos; el resto de las horas, sólo los vinculados.
TOTALES: dict[str, tuple[str, str]] = {
    "servicios_universo": ("Servicios (universo)", "entero"),
    "servicios_con_reclamos": ("Servicios con reclamos", "entero"),
    "servicios_dentro": ("Servicios dentro de SLA", "entero"),
    "servicios_agotados": ("Servicios con presupuesto agotado", "entero"),
    "servicios_excedidos": ("Servicios con SLA excedido", "entero"),
    "servicios_sin_consumo": ("Servicios sin consumo", "entero"),
    "servicios_no_evaluables": ("Servicios no evaluables", "entero"),
    "reclamos": ("Reclamos (todos)", "entero"),
    "reclamos_vinculados": ("Reclamos vinculados a un servicio", "entero"),
    "reclamos_no_vinculados": ("Reclamos no vinculados", "entero"),
    "eventos": ("Eventos reales", "entero"),
    "reclamos_sin_evento": ("Reclamos sin evento (vinculados)", "entero"),
    "horas_netas": ("Horas netas (todos los reclamos)", "horas"),
    "horas_computables": ("Horas computables (reclamos vinculados)", "horas"),
    "horas_excluidas": ("Horas excluidas por cierre Cliente (reclamos vinculados)", "horas"),
    "horas_no_vinculadas": ("Horas netas de reclamos no vinculados", "horas"),
    "horas_fo_general": ("Horas FO general (reclamos vinculados)", "horas"),
    "horas_fo_cod3": ("Horas FO Cod 3 (reclamos vinculados)", "horas"),
    "horas_carrier": ("Horas Carrier (reclamos vinculados)", "horas"),
    "horas_otros": ("Horas Otros (reclamos vinculados)", "horas"),
    "inconsistencias": ("Inconsistencias", "entero"),
}

LEYENDAS: list[tuple[str, str]] = [
    ("Semáforo del servicio e indicador del reclamo",
     "Rojo: horas de FO (general o Cod 3) y ninguna de otra causa. Amarillo: horas de FO y también de Carrier u "
     "Otros. Verde: sólo horas de Carrier u Otros. Sin color: sin horas computables. El indicador del reclamo es "
     "Rojo si su causa es FO, Verde si es Carrier u Otros y Sin color si no computa."),
    ("Verde no significa cumplimiento",
     "El color describe la causa de las horas, no el estado del presupuesto: un servicio verde puede estar "
     "agotado o excedido por causas ajenas a FO. El cumplimiento se lee en la columna Estado."),
    ("Estados del presupuesto",
     "Sin consumo: sin horas computables. Dentro de SLA: consumo menor al presupuesto. Presupuesto agotado: "
     "consumo igual al presupuesto (dentro de la tolerancia). SLA excedido: consumo mayor al presupuesto. "
     "No evaluable: sin SLA prometido o sin presupuesto válido."),
    ("Suficiente solo / cruza el umbral / determinante al excluir",
     "Suficiente solo: el evento (o reclamo sin evento) por sí solo agota o excede el presupuesto del servicio. "
     "Cruza el umbral: en el orden de atribución es quien lleva el acumulado a alcanzar o superar el presupuesto "
     "por primera vez. Determinante al excluir: si se lo excluye, el servicio deja de estar agotado o excedido."),
    ("Participación ≠ causa",
     "Participar en un servicio agotado o excedido no implica haberlo causado: los tres indicadores describen "
     "el aporte numérico de cada evento, no una responsabilidad."),
    ("Acumulado = atribución por orden, no instante físico",
     "Los acumulados suman los reclamos por fecha de inicio y número de reclamo. Indican a quién se atribuye "
     "el cruce del presupuesto según ese orden, no el instante físico en que ocurrió."),
    ("Horas-servicio ≠ duración del evento",
     "Las horas-servicio de un evento suman las horas de cada reclamo en cada servicio afectado: un evento que "
     "afecta a 10 servicios durante 2 h suma 20 horas-servicio."),
    ("Rango observado ≠ duración oficial",
     "Inicio y cierre observados son el mínimo y el máximo de las fechas de los reclamos del evento; no "
     "constituyen la duración oficial del evento."),
    ("Tolerancia de comparación",
     f"Las comparaciones de estado usan una tolerancia de {m.EPS_HORAS:g} horas (unos 3,6 ms) para absorber "
     "el ruido de punto flotante. Por eso un servicio agotado puede mostrar horas excedidas ínfimas: el estado "
     "se lee siempre en la columna Estado."),
    ("% visible ≤ 100 y aporte en % real",
     "El % visible del servicio se topa en 100 %; el exceso se informa como horas excedidas. El aporte por "
     "reclamo o evento se expresa en % real del presupuesto y puede superar 100 %."),
]


def _faltante(valor: object) -> bool:
    if valor is None or valor is pd.NA or valor is pd.NaT:
        return True
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return False
    return math.isnan(numero) or math.isinf(numero)


def fmt_horas(h: object) -> str:
    if _faltante(h):
        return VACIO
    minutos = round(float(h) * 60)
    signo = "-" if minutos < 0 else ""
    return f"{signo}{abs(minutos) // 60}:{abs(minutos) % 60:02d}"


def fmt_pct(p: object) -> str:
    if _faltante(p):
        return VACIO
    return f"{float(p):.2f}".replace(".", ",") + " %"


def a_fecha_ar(ts: object) -> dt.datetime | None:
    """Datetime naive en hora de Argentina (los naive se asumen ya en AR); None si falta."""
    if _faltante(ts):
        return None
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert(TZ_AR).tz_localize(None)
    return t.to_pydatetime()


def fmt_fecha(ts: object) -> str:
    fecha = a_fecha_ar(ts)
    return VACIO if fecha is None else fecha.strftime("%d/%m/%Y %H:%M")


def fmt_bool(b: object) -> str:
    if _faltante(b):
        return VACIO
    return "Sí" if bool(b) else "No"
