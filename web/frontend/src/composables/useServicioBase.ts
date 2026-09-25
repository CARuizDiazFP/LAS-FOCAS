// Nombre de archivo: useServicioBase.ts
// Ubicación de archivo: web/frontend/src/composables/useServicioBase.ts
// Descripción: Carga la identidad de un Servicio por su ID de origen — base compartida por la
// ficha compacta y por cada vista dedicada de sección (histórico, ingresos, camino, reclamos, baneos)

/**
 * Cada vista de sección necesita saber de qué Servicio está hablando (nombre del cliente, estado,
 * `id` interno para las llamadas que lo piden) antes de cargar lo suyo. Tener esa carga en un solo
 * lugar evita repetirla cinco veces y que las cabeceras diverjan entre secciones.
 *
 * Deliberadamente **no** carga las secciones: cada vista pide sólo su parte. La ficha llegó a
 * disparar cinco cargas en paralelo para mostrarlas todas juntas, que es justamente la densidad
 * que este rediseño viene a bajar.
 */

import { ref } from 'vue';

import {
  type ServicioEquipoUltimaMillaItem,
  type ServicioHistorialIdItem,
  type ServicioItem,
  getServicioDetail,
} from '../api/servicios';

export function useServicioBase() {
  const servicio = ref<ServicioItem | null>(null);
  const historialIds = ref<ServicioHistorialIdItem[]>([]);
  const equiposUltimaMilla = ref<ServicioEquipoUltimaMillaItem[]>([]);
  /** El ID de origen normalizado que devolvió el backend, que puede no ser el de la URL. */
  const idOrigen = ref('');
  const loading = ref(false);
  const error = ref('');

  async function cargar(id: string): Promise<boolean> {
    if (!id) {
      error.value = 'Falta el ID del servicio';
      return false;
    }
    loading.value = true;
    error.value = '';
    try {
      const respuesta = await getServicioDetail(id);
      servicio.value = respuesta.servicio;
      historialIds.value = respuesta.historial_ids;
      equiposUltimaMilla.value = respuesta.equipos_ultima_milla;
      idOrigen.value = respuesta.id_origen.trim();
      return true;
    } catch (err: unknown) {
      servicio.value = null;
      historialIds.value = [];
      equiposUltimaMilla.value = [];
      idOrigen.value = '';
      error.value =
        err instanceof Error ? err.message : 'No se pudo cargar el detalle del servicio';
      return false;
    } finally {
      loading.value = false;
    }
  }

  return { servicio, historialIds, equiposUltimaMilla, idOrigen, loading, error, cargar };
}
