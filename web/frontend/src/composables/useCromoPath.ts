// Nombre de archivo: useCromoPath.ts
// Ubicación de archivo: web/frontend/src/composables/useCromoPath.ts
// Descripción: Estado reutilizable para resolver el camino óptico de Cromo — elección de semilla, espera cancelable y memoización por pelo

import { computed, ref } from 'vue';

import {
  type CaminoOpticoResponse,
  type PeloSemilla,
  descargarTrackingCromo,
  listarPelosCamino,
  mensajeErrorCromoPath,
  resolverCaminoOptico,
} from '../api/cromoPath';

/** 30 s: seis veces el peor caso medido por objeto contra Cromo, sobre un endpoint documentado
 * como más caro que los demás (latencia real observada del camino: ~12 s). */
const TIMEOUT_MS = 30_000;
/** A los 8 s el operador ya cree que se colgó, así que ahí aparece la explicación. */
const AVISO_LENTO_MS = 8_000;

export function useCromoPath() {
  const pelos = ref<PeloSemilla[]>([]);
  const cargandoPelos = ref(false);
  const errorPelos = ref('');
  const peloElegido = ref<number | null>(null);

  const resultado = ref<CaminoOpticoResponse | null>(null);
  const resolviendo = ref(false);
  const errorPath = ref('');
  const cancelado = ref(false);
  const segundos = ref(0);

  const descargando = ref(false);
  const errorDescarga = ref('');

  // Cada resolución cuesta ~12 s del lado del proveedor: ir y volver entre dos semillas no
  // vuelve a pagarla dentro de la misma sesión del modal.
  const cache = new Map<number, CaminoOpticoResponse>();

  let controller: AbortController | null = null;
  let timeoutId: number | null = null;
  let tickId: number | null = null;

  const tieneSemilla = computed(() => pelos.value.length > 0);
  const avisoLento = computed(() => resolviendo.value && segundos.value >= AVISO_LENTO_MS / 1000);
  const peloActivo = computed<PeloSemilla | null>(
    () => pelos.value.find((p) => p.pelo_n_id === peloElegido.value) ?? pelos.value[0] ?? null,
  );

  function _limpiarTemporizadores(): void {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
      timeoutId = null;
    }
    if (tickId !== null) {
      window.clearInterval(tickId);
      tickId = null;
    }
  }

  function setPelos(lista: PeloSemilla[]): void {
    pelos.value = lista;
    peloElegido.value = lista.length > 0 ? lista[0].pelo_n_id : null;
  }

  async function cargarPelos(servicioId: number): Promise<void> {
    cargandoPelos.value = true;
    errorPelos.value = '';
    try {
      const respuesta = await listarPelosCamino(servicioId);
      setPelos(respuesta.pelos);
    } catch (error) {
      errorPelos.value = mensajeErrorCromoPath(error);
      pelos.value = [];
    } finally {
      cargandoPelos.value = false;
    }
  }

  async function resolver(servicioId: number): Promise<void> {
    const pelo = peloElegido.value ?? peloActivo.value?.pelo_n_id ?? null;
    if (pelo !== null && cache.has(pelo)) {
      resultado.value = cache.get(pelo) ?? null;
      errorPath.value = '';
      cancelado.value = false;
      return;
    }

    resolviendo.value = true;
    errorPath.value = '';
    cancelado.value = false;
    resultado.value = null;
    segundos.value = 0;

    controller = new AbortController();
    // El motivo del abort se distingue por el `name` de la excepción: `TimeoutError` cuando lo
    // corta el reloj, `AbortError` cuando lo corta el operador. Sin esto, cancelar a mano se
    // vería como un error.
    timeoutId = window.setTimeout(
      () => controller?.abort(new DOMException('timeout', 'TimeoutError')),
      TIMEOUT_MS,
    );
    tickId = window.setInterval(() => {
      segundos.value += 1;
    }, 1000);

    try {
      const respuesta = await resolverCaminoOptico(servicioId, {
        peloNId: pelo,
        signal: controller.signal,
      });
      // Guarda de identidad: abortar no es instantáneo, y si el operador cambió de semilla
      // mientras la respuesta venía en camino, mostrarla sería mostrarle un camino ajeno.
      if (pelo !== null && pelo !== peloElegido.value) {
        return;
      }
      resultado.value = respuesta;
      if (respuesta.pelo_n_id != null) {
        cache.set(respuesta.pelo_n_id, respuesta);
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        cancelado.value = true;
      } else {
        errorPath.value = mensajeErrorCromoPath(error, { peloNId: pelo });
      }
    } finally {
      _limpiarTemporizadores();
      controller = null;
      resolviendo.value = false;
    }
  }

  function cancelar(): void {
    controller?.abort();
    _limpiarTemporizadores();
  }

  async function descargarTxt(servicioId: number): Promise<string | null> {
    descargando.value = true;
    errorDescarga.value = '';
    try {
      return await descargarTrackingCromo(servicioId, { peloNId: peloElegido.value });
    } catch (error) {
      errorDescarga.value = mensajeErrorCromoPath(error, { peloNId: peloElegido.value });
      return null;
    } finally {
      descargando.value = false;
    }
  }

  function reset(): void {
    cancelar();
    pelos.value = [];
    peloElegido.value = null;
    resultado.value = null;
    errorPath.value = '';
    errorPelos.value = '';
    errorDescarga.value = '';
    cancelado.value = false;
    segundos.value = 0;
    cache.clear();
  }

  /** Sólo se auto-resuelve cuando el operador entró explícitamente por el botón de camino Y hay
   * una única semilla: con varias hay que dejarlo elegir, no gastar una llamada por él. */
  async function autoResolverSiUnicaSemilla(servicioId: number): Promise<void> {
    if (pelos.value.length === 1) {
      await resolver(servicioId);
    }
  }

  return {
    pelos,
    cargandoPelos,
    errorPelos,
    peloElegido,
    peloActivo,
    tieneSemilla,
    resultado,
    resolviendo,
    errorPath,
    cancelado,
    segundos,
    avisoLento,
    descargando,
    errorDescarga,
    cargarPelos,
    setPelos,
    resolver,
    cancelar,
    descargarTxt,
    reset,
    autoResolverSiUnicaSemilla,
  };
}
