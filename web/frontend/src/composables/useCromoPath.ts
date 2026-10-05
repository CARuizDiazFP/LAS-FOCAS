// Nombre de archivo: useCromoPath.ts
// Ubicación de archivo: web/frontend/src/composables/useCromoPath.ts
// Descripción: Estado reutilizable para resolver el camino óptico de Cromo — elección de semilla,
// espera cancelable, memoización por pelo y descarga de un .txt por cada pelo del Servicio

import { computed, ref } from 'vue';

import {
  type CaminoDelServicio,
  type CaminoOpticoResponse,
  type PeloExcluido,
  type PeloSemilla,
  type PelosCaminoResponse,
  descargarTrackingCromo,
  excluirPelosServicio,
  listarPelosCamino,
  mensajeErrorCromoPath,
  normalizarConsistencia,
  relevarOdfsDelCamino,
  resolverCaminoOptico,
  resolverCaminosServicio,
  restaurarPeloServicio,
} from '../api/cromoPath';

/** Resultado de bajar los trackings de los pelos elegidos. */
export interface ResultadoDescargaTrackings {
  descargados: string[];
  fallidos: { peloNId: number; motivo: string }[];
}

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
  /** Pelos tildados para descargar. Arranca en las posiciones de ODF del Servicio. */
  const pelosSeleccionados = ref<number[]>([]);
  /** `false` cuando ninguna semilla tiene conector de ODF: hay que relevar la ODF primero. */
  const odfRelevada = ref(true);
  /** Universo real de pelos matcheados, sin el tope que trunca la lista. */
  const totalMatcheados = ref(0);
  /** Cuántos de esos son posición de ODF: los que el operador llama "los pelos del Servicio". */
  const totalConPosicionOdf = ref(0);
  /** Progreso de la descarga: cuántos trackings se bajaron de cuántos. */
  const descargadosCount = ref(0);
  const descargaTotal = ref(0);

  const normalizando = ref(false);
  const errorNormalizar = ref('');
  const resumenNormalizacion = ref('');
  const relevandoOdf = ref(false);
  const errorRelevarOdf = ref('');

  /** Caminos que tiene el Servicio según la regla de operaciones (pelos por cable u ODF). */
  const caminosEsperados = ref(0);
  /** Un pelo por camino distinto, resuelto en el backend contra Cromo (`/caminos`). */
  const caminos = ref<CaminoDelServicio[]>([]);
  const caminosResueltos = ref(false);
  const resolviendoCaminos = ref(false);
  const errorCaminos = ref('');
  /** Pelos con la etiqueta del Servicio que no están en ninguno de sus caminos. */
  const huerfanos = ref<PeloSemilla[]>([]);
  /** Pelos ya sacados del Servicio en local. */
  const excluidos = ref<PeloExcluido[]>([]);
  /** Pelo que se está excluyendo o restaurando, para deshabilitar sólo su botón. */
  const peloEnExclusion = ref<number | null>(null);
  const errorExclusion = ref('');
  /**
   * `true` cuando el operador tocó la selección a mano. Mientras sea `false`, descargar baja un
   * `.txt` por camino del Servicio (resolviéndolos antes si hace falta), no lo preseleccionado:
   * sin ODF la preselección local no puede saber qué pelos son del mismo hilo (Servicio 94673).
   */
  const seleccionManual = ref(false);
  let ultimasOpcionesPelos: { priorizarConector?: boolean } = {};

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
  /** Cuántos `.txt` va a bajar el botón: con la selección automática, los caminos esperados. */
  const cantidadDescarga = computed(() => {
    if (seleccionManual.value || caminosResueltos.value) return pelosSeleccionados.value.length;
    return Math.max(caminosEsperados.value, pelosSeleccionados.value.length);
  });

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

  function setPelos(lista: PeloSemilla[], respuesta?: Partial<PelosCaminoResponse>): void {
    pelos.value = lista;
    // `peloElegido` es el pelo que se dibuja en pantalla: sigue siendo uno solo, porque resolver
    // el camino cuesta una llamada a Cromo por pelo.
    peloElegido.value = lista.length > 0 ? lista[0].pelo_n_id : null;
    odfRelevada.value = respuesta?.odf_relevada ?? lista.some((p) => p.tiene_conector_odf);
    // La selección de descarga sí es múltiple: por defecto, las posiciones de ODF del Servicio.
    const porDefecto = respuesta?.preseleccionados?.length
      ? respuesta.preseleccionados
      : lista.filter((p) => p.tiene_conector_odf).map((p) => p.pelo_n_id);
    pelosSeleccionados.value = porDefecto.length
      ? [...porDefecto]
      : lista.slice(0, 1).map((p) => p.pelo_n_id);
    seleccionManual.value = false;
    // Si los caminos ya se resolvieron, la selección son ellos y no la preselección local.
    if (caminosResueltos.value) {
      pelosSeleccionados.value = caminos.value.map((c) => c.pelo_n_id);
    }
  }

  function alternarPelo(peloNId: number): void {
    const actuales = pelosSeleccionados.value;
    pelosSeleccionados.value = actuales.includes(peloNId)
      ? actuales.filter((p) => p !== peloNId)
      : [...actuales, peloNId];
    seleccionManual.value = true;
  }

  function seleccionarTodos(): void {
    pelosSeleccionados.value = pelos.value.map((p) => p.pelo_n_id);
    seleccionManual.value = true;
  }

  function limpiarSeleccion(): void {
    pelosSeleccionados.value = [];
    seleccionManual.value = true;
  }

  async function cargarPelos(
    servicioId: number,
    opciones: { priorizarConector?: boolean } = {},
  ): Promise<void> {
    cargandoPelos.value = true;
    errorPelos.value = '';
    ultimasOpcionesPelos = opciones;
    try {
      const respuesta = await listarPelosCamino(servicioId, opciones);
      setPelos(respuesta.pelos, respuesta);
      totalMatcheados.value = respuesta.total_matcheados ?? respuesta.pelos.length;
      totalConPosicionOdf.value = respuesta.total_con_posicion_odf ?? 0;
      caminosEsperados.value = respuesta.caminos_esperados ?? 0;
      excluidos.value = respuesta.excluidos ?? [];
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

  /**
   * Baja un `.txt` por cada pelo tildado: un Servicio tiene tantos trackings como pelos (1 en PON,
   * 2 o más en FO o con un SW de módulo bifilar).
   *
   * Las descargas van **en serie**, no en paralelo: cada pelo que no esté cacheado cuesta una
   * llamada a Cromo de 4,6-14 s, y disparar seis a la vez sólo lograría que el proveedor las
   * encole igual, con el rate limiter del cliente, pero sin poder informar progreso.
   *
   * Un pelo que falla no corta el resto — se junta y se informa al final, igual que en el backend.
   */
  async function descargarTrackings(servicioId: number): Promise<ResultadoDescargaTrackings> {
    const resultado: ResultadoDescargaTrackings = { descargados: [], fallidos: [] };
    descargando.value = true;
    errorDescarga.value = '';
    descargadosCount.value = 0;
    descargaTotal.value = 0;
    try {
      // Con la selección automática se baja un `.txt` por camino del Servicio: si todavía no se
      // resolvieron, se resuelven primero (deja cada tracking cacheado, así bajarlos es inmediato).
      if (!seleccionManual.value && !caminosResueltos.value) {
        const ok = await resolverCaminos(servicioId);
        if (!ok) {
          errorDescarga.value = errorCaminos.value;
          return resultado;
        }
      }
      const elegidos = pelosSeleccionados.value.length
        ? [...pelosSeleccionados.value]
        : pelos.value.slice(0, 1).map((p) => p.pelo_n_id);
      descargaTotal.value = elegidos.length;

      for (const peloNId of elegidos) {
        try {
          resultado.descargados.push(await descargarTrackingCromo(servicioId, { peloNId }));
        } catch (error) {
          resultado.fallidos.push({ peloNId, motivo: mensajeErrorCromoPath(error, { peloNId }) });
        } finally {
          descargadosCount.value += 1;
        }
      }
      if (resultado.fallidos.length) {
        const detalle = resultado.fallidos
          .map((f) => `pelo ${f.peloNId}: ${f.motivo}`)
          .join(' · ');
        errorDescarga.value = resultado.descargados.length
          ? `Se bajaron ${resultado.descargados.length} de ${elegidos.length}. Falló ${detalle}`
          : detalle;
      } else if (!seleccionManual.value && errorCaminos.value) {
        // Caminos faltantes: se bajó lo que hay, pero el operador tiene que saber que falta.
        errorDescarga.value = errorCaminos.value;
      }
      return resultado;
    } finally {
      descargando.value = false;
    }
  }

  /**
   * Resuelve los caminos del Servicio en el backend y deja tildado un pelo por camino. Los pelos
   * que no cayeron en ningún camino quedan en `huerfanos`, para que un admin los excluya.
   */
  async function resolverCaminos(servicioId: number): Promise<boolean> {
    resolviendoCaminos.value = true;
    errorCaminos.value = '';
    try {
      const respuesta = await resolverCaminosServicio(servicioId);
      caminos.value = respuesta.caminos;
      huerfanos.value = respuesta.huerfanos;
      caminosEsperados.value = respuesta.esperados;
      caminosResueltos.value = true;
      seleccionManual.value = false;
      pelosSeleccionados.value = respuesta.caminos.map((c) => c.pelo_n_id);
      if (!respuesta.completo) {
        errorCaminos.value =
          `Se esperaban ${respuesta.esperados} caminos y se resolvieron ${respuesta.caminos.length}.` +
          (respuesta.errores.length ? ` ${respuesta.errores.join(' · ')}` : '');
      }
      return respuesta.caminos.length > 0;
    } catch (error) {
      errorCaminos.value = mensajeErrorCromoPath(error);
      return false;
    } finally {
      resolviendoCaminos.value = false;
    }
  }

  /** Saca pelos huérfanos del Servicio (uno o todos) y recarga las semillas. Los caminos ya
   * resueltos siguen valiendo: los huérfanos no estaban en ninguno. */
  async function excluirPelos(servicioId: number, pelosNId: number[]): Promise<boolean> {
    if (!pelosNId.length) return false;
    // Con un lote no hay un pelo puntual que marcar: -1 deshabilita todos los botones.
    peloEnExclusion.value = pelosNId.length === 1 ? pelosNId[0] : -1;
    errorExclusion.value = '';
    try {
      const respuesta = await excluirPelosServicio(
        servicioId,
        pelosNId,
        'Huérfano: fuera de todo camino del Servicio',
      );
      const sacados = new Set(respuesta.excluidos);
      huerfanos.value = huerfanos.value.filter((p) => !sacados.has(p.pelo_n_id));
      await cargarPelos(servicioId, ultimasOpcionesPelos);
      return true;
    } catch (error) {
      errorExclusion.value = mensajeErrorCromoPath(error);
      return false;
    } finally {
      peloEnExclusion.value = null;
    }
  }

  /** Devuelve un pelo al Servicio. Invalida los caminos resueltos: el pelo puede cambiarlos. */
  async function restaurarPelo(servicioId: number, peloNId: number): Promise<boolean> {
    peloEnExclusion.value = peloNId;
    errorExclusion.value = '';
    try {
      await restaurarPeloServicio(servicioId, peloNId);
      caminosResueltos.value = false;
      caminos.value = [];
      huerfanos.value = [];
      await cargarPelos(servicioId, ultimasOpcionesPelos);
      return true;
    } catch (error) {
      errorExclusion.value = mensajeErrorCromoPath(error, { peloNId });
      return false;
    } finally {
      peloEnExclusion.value = null;
    }
  }

  /**
   * Normaliza las inconsistencias del camino contra Cromo y vuelve a resolverlo.
   *
   * Invalida la memoización del pelo antes de re-resolver: el punto de normalizar es que la tabla
   * de consistencia cambie, y servir el resultado memoizado mostraría las mismas discrepancias que
   * se acaban de corregir.
   */
  async function normalizar(servicioId: number, elementoIds?: number[]): Promise<boolean> {
    const pelo = peloElegido.value ?? peloActivo.value?.pelo_n_id ?? null;
    if (pelo === null) return false;

    normalizando.value = true;
    errorNormalizar.value = '';
    resumenNormalizacion.value = '';
    try {
      const respuesta = await normalizarConsistencia(servicioId, pelo, { elementoIds });
      const tocados = respuesta.creados + respuesta.actualizados;
      resumenNormalizacion.value = tocados
        ? `Se reingirieron ${tocados} elemento(s) desde Cromo` +
          (respuesta.errores ? `, ${respuesta.errores} con error` : '') +
          '.'
        : 'No hubo nada que normalizar.';
      cache.delete(pelo);
      await resolver(servicioId);
      return respuesta.errores === 0;
    } catch (error) {
      errorNormalizar.value = mensajeErrorCromoPath(error, { peloNId: pelo });
      return false;
    } finally {
      normalizando.value = false;
    }
  }

  /** Releva las ODFs del camino y recarga las semillas, para que aparezcan sus posiciones. */
  async function relevarOdf(servicioId: number): Promise<boolean> {
    const pelo = peloElegido.value ?? peloActivo.value?.pelo_n_id ?? null;
    if (pelo === null) return false;

    relevandoOdf.value = true;
    errorRelevarOdf.value = '';
    try {
      await relevarOdfsDelCamino(servicioId, pelo);
      await cargarPelos(servicioId);
      return true;
    } catch (error) {
      errorRelevarOdf.value = mensajeErrorCromoPath(error, { peloNId: pelo });
      return false;
    } finally {
      relevandoOdf.value = false;
    }
  }

  function reset(): void {
    cancelar();
    pelos.value = [];
    peloElegido.value = null;
    pelosSeleccionados.value = [];
    odfRelevada.value = true;
    totalMatcheados.value = 0;
    totalConPosicionOdf.value = 0;
    descargadosCount.value = 0;
    descargaTotal.value = 0;
    resultado.value = null;
    errorPath.value = '';
    errorPelos.value = '';
    errorDescarga.value = '';
    errorNormalizar.value = '';
    errorRelevarOdf.value = '';
    resumenNormalizacion.value = '';
    cancelado.value = false;
    segundos.value = 0;
    cache.clear();
    caminosEsperados.value = 0;
    caminos.value = [];
    caminosResueltos.value = false;
    resolviendoCaminos.value = false;
    errorCaminos.value = '';
    huerfanos.value = [];
    excluidos.value = [];
    peloEnExclusion.value = null;
    errorExclusion.value = '';
    seleccionManual.value = false;
    ultimasOpcionesPelos = {};
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
    pelosSeleccionados,
    odfRelevada,
    totalMatcheados,
    totalConPosicionOdf,
    descargadosCount,
    descargaTotal,
    normalizando,
    errorNormalizar,
    resumenNormalizacion,
    relevandoOdf,
    errorRelevarOdf,
    caminosEsperados,
    caminos,
    caminosResueltos,
    resolviendoCaminos,
    errorCaminos,
    huerfanos,
    excluidos,
    peloEnExclusion,
    errorExclusion,
    seleccionManual,
    cantidadDescarga,
    cargarPelos,
    setPelos,
    alternarPelo,
    seleccionarTodos,
    limpiarSeleccion,
    resolver,
    cancelar,
    descargarTxt,
    descargarTrackings,
    normalizar,
    relevarOdf,
    resolverCaminos,
    excluirPelos,
    restaurarPelo,
    reset,
    autoResolverSiUnicaSemilla,
  };
}
