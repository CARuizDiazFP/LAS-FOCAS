// Nombre de archivo: cromoVerificacion.ts
// Ubicación de archivo: web/frontend/src/api/cromoVerificacion.ts
// Descripción: Cliente API de los verificadores de servicios Cromo (por cable, tubo, botella y ODF)

import { requestJson } from './client';

// ── Verificador de servicios (Etapa 6) ───────────────────────────────────────
// Consultas de sólo lectura sobre el inventario ya ingerido — sin rol admin, cualquier usuario
// autenticado puede consultarlas (ver docs/Doc Privada/ingesta_cromo.md §8.2).

export interface CromoServicioEncontrado {
  servicio_id: number;
  servicio_id_externo: string;
  numero_primer_servicio: string | null;
  nombre_cliente: string | null;
  cliente: string | null;
  estado_servicio: string | null;
  categoria: number | null;
  tipo_servicio: string | null;
  // Puede venir `null`: `/api/infra/cromo/odfs/{odf_n_id}/servicios` ahora incluye también los
  // servicios asociados por override manual (gestor de Servicios sin ODF), y un override sin
  // conector puntual no tiene pelo — ver `ServicioOdfAsociarRequestModel` en `web/app/main.py`.
  pelo_n_id: number | null;
  servicio_numero_match: string;
  metodo: string;
}

export interface CromoVerificacionCable {
  cable_n_id: number;
  nombre: string | null;
  capacidad: string | null;
  extremo_a_nombre: string | null;
  extremo_b_nombre: string | null;
  servicios: CromoServicioEncontrado[];
}

export interface CromoVerificacionTubo {
  tubo_n_id: number;
  cable_n_id: number | null;
  orden: number | null;
  nombre_color: string | null;
  servicios: CromoServicioEncontrado[];
}

/** Un cable que tiene la botella como uno de sus extremos — fila de la tarjeta "Cables asociados"
 * del detalle de Botella (sin tubos/pelos, eso vive en `CromoDetalleCable`). */
export interface CromoCableDeBotella {
  n_id: number;
  nombre: string | null;
  cantidad_servicios: number;
}

export interface CromoVerificacionBotella {
  botella_n_id: number;
  nombre: string | null;
  clase: number | null;
  localidad: string | null;
  servicios: CromoServicioEncontrado[];
  cables: CromoCableDeBotella[];
  // Empalmes (fusiones internas) tienen su propio endpoint/vista dedicada — ver
  // `CromoEmpalmesBotella`/`obtenerEmpalmesDeBotella` más abajo, no una tarjeta de este resultado.
}

export async function verificarServiciosPorCable(cableNId: number): Promise<CromoVerificacionCable> {
  return requestJson(`/api/infra/cromo/cables/${cableNId}/servicios`);
}

export async function verificarServiciosPorTubo(tuboNId: number): Promise<CromoVerificacionTubo> {
  return requestJson(`/api/infra/cromo/tubos/${tuboNId}/servicios`);
}

export async function verificarServiciosPorBotella(botellaNId: number): Promise<CromoVerificacionBotella> {
  return requestJson(`/api/infra/cromo/botellas/${botellaNId}/servicios`);
}

// ── Verificador de servicios por ODF (Tarea 5, plan ODFs) ────────────────────
// Mismo patrón que `verificarServiciosPorBotella` — servicios que pasan por los cables asociados a
// este ODF puntual.

export interface CromoVerificacionOdf {
  odf_n_id: number;
  nombre: string | null;
  tipo_elemento: string;
  localidad: string | null;
  servicios: CromoServicioEncontrado[];
  cables: CromoCableDeBotella[];
}

export async function verificarServiciosPorOdf(odfNId: number): Promise<CromoVerificacionOdf> {
  return requestJson(`/api/infra/cromo/odfs/${odfNId}/servicios`);
}
