// Nombre de archivo: useCromoPath.ts
// Ubicación de archivo: web/frontend/src/composables/useCromoPath.ts
// Descripción: Estado reutilizable para resolver el camino óptico de Cromo — elección de semilla,
// espera cancelable, memoización por pelo, descarga de un .txt por cada tramo del Servicio y su
// posición vigente declarada (conectores de ODF de los que sale el tracking)

import { type Ref, computed, ref } from 'vue';

import {
  type CaminoAdicional,
  type CaminoResidual,
  type CaminoOpticoResponse,
  type CaminosServicioResponse,
  type EstadoPosicionCaminos,
  type OdfConfirmada,
  type RolOdfConfirmada,
  type PeloExcluido,
  type PeloSemilla,
  type PelosCaminoResponse,
  type PosicionDeclarada,
  type PosicionPosible,
  type ResumenInconsistenciasServicio,
  type TramoDelServicio,
  confirmarOdfsServicio,
  declararPosicionVigente,
  declararTrackingsEsperados,
  desconfirmarOdfServicio,
  descargarTrackingCromo,
  listarPelosCamino,
  mensajeErrorCromoPath,
  mensajeErrorPosicionVigente,
  normalizarConsistencia,
  obtenerPosicionVigente,
  relevarOdfsDelCamino,
  resolverCaminoOptico,
  resolverCaminosServicio,
  restaurarPeloServicio,
  retirarPosicionVigente,
} from '../api/cromoPath';

/** Resultado de bajar los trackings de los pelos elegidos. */
export interface ResultadoDescargaTrackings {
  descargados: string[];
  fallidos: { peloNId: number; motivo: string }[];
}

/** ODF que toca algún camino resuelto (tramo, adicional o residual) o que ya está confirmada. */
export interface OdfDelTramo {
  odf_n_id: number;
  nombre: string | null;
  /** 86 = ODF Nodo, 69 = ODF. */
  clase: number | null;
  /** Rol sugerido: ODF (69) en un extremo de camino → extremo; cualquier otra → tránsito. */
  rolSugerido: RolOdfConfirmada;
}

/**
 * ODF que el operador puede confirmar o quitar: todas las que tocan los tramos y los residuales
 * (extremos e intermedias) y, siempre, las confirmadas vigentes —aunque ya no aparezcan en ningún
 * camino, para poder quitarlas—. Un residual puede ser la única vía a una ODF del Servicio.
 */
export function odfsConfirmables(
  caminos: (TramoDelServicio | CaminoAdicional | CaminoResidual)[],
  confirmadas: OdfConfirmada[],
): OdfDelTramo[] {
  const vistas = new Map<number, OdfDelTramo>();
  const agregar = (odf: OdfDelTramo) => {
    const previa = vistas.get(odf.odf_n_id);
    if (!previa) {
      vistas.set(odf.odf_n_id, odf);
      return;
    }
    // Una ODF que es extremo en un camino e intermedia en otro se sugiere como extremo.
    vistas.set(odf.odf_n_id, {
      odf_n_id: odf.odf_n_id,
      nombre: previa.nombre ?? odf.nombre,
      clase: previa.clase ?? odf.clase,
      rolSugerido:
        previa.rolSugerido === 'EXTREMO' || odf.rolSugerido === 'EXTREMO' ? 'EXTREMO' : 'TRANSITO',
    });
  };
  for (const camino of caminos) {
    const extremos = [camino.extremos.a, camino.extremos.b].filter(
      (e): e is NonNullable<typeof e> => e != null && e.odf_n_id != null,
    );
    const enExtremo = new Set(extremos.map((e) => e.odf_n_id));
    for (const e of extremos) {
      agregar({
        odf_n_id: e.odf_n_id as number,
        nombre: e.odf_nombre,
        clase: e.odf_clase,
        rolSugerido: e.odf_clase === 69 ? 'EXTREMO' : 'TRANSITO',
      });
    }
    for (const o of camino.odfs ?? []) {
      agregar({
        odf_n_id: o.odf_n_id,
        nombre: o.odf_nombre,
        clase: o.odf_clase,
        rolSugerido: enExtremo.has(o.odf_n_id) && o.odf_clase === 69 ? 'EXTREMO' : 'TRANSITO',
      });
    }
  }
  for (const c of confirmadas) {
    if (vistas.has(c.odf_n_id)) continue;
    vistas.set(c.odf_n_id, {
      odf_n_id: c.odf_n_id,
      nombre: c.odf_nombre,
      clase: c.odf_tipo === 'ODF_NODO' ? 86 : c.odf_tipo === 'ODF' ? 69 : null,
      rolSugerido: c.rol,
    });
  }
  return [...vistas.values()];
}

/** Avisos de una resolución de caminos: semillas sin resolver, tope tocado, esperados distintos. */
export function avisosDeCaminos(respuesta: CaminosServicioResponse): string[] {
  const avisos: string[] = [];
  const sinResolver = Math.max(respuesta.no_cubiertos ?? 0, respuesta.errores.length);
  if (sinResolver > 0 || !respuesta.completo) {
    avisos.push(`Tracking incompleto: ${sinResolver} semilla(s) no resolvieron.`);
    if (respuesta.errores.length) avisos.push(respuesta.errores.join(' · '));
  }
  if (respuesta.tope_llamadas) {
    avisos.push('Se alcanzó el tope de consultas a Cromo.');
  }
  // Lo esperado se compara contra todo lo que Cromo documenta (tramos + adicionales, lo que baja
  // `track N full`), no sólo contra los tramos: un adicional también es un tracking del Servicio.
  // Un backend anterior a la posición vigente no manda `caminos_resueltos`: ahí son los tramos.
  const resueltos = respuesta.caminos_resueltos ?? respuesta.tramos.length;
  if (respuesta.esperados_declarados != null && respuesta.esperados_declarados !== resueltos) {
    avisos.push(
      `Se esperaban ${respuesta.esperados_declarados} trackings y Cromo documenta ${resueltos} camino(s).`,
    );
  }
  return avisos;
}

/** Avisos de la posición vigente declarada (pelo dañado, pelo que cambió, retirada, …). */
export function avisosDePosicion(respuesta: CaminosServicioResponse): string[] {
  return (respuesta.posicion_vigente?.avisos ?? []).map((a) => a.texto);
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
  /** Tramos del Servicio, uno por `.txt`, resueltos en el backend contra Cromo (`/caminos`). */
  const tramos = ref<TramoDelServicio[]>([]);
  /** Caminos que no son tramos del Servicio: no se descargan (la auditoría los trata aparte). */
  const residuales = ref<CaminoResidual[]>([]);
  /**
   * Caminos completos que Cromo también documenta y no son vigentes ni tramos. Tienen `.txt`
   * propio (fila por fila), pero "Descargar todos" baja sólo los tramos/vigentes.
   */
  const adicionales = ref<CaminoAdicional[]>([]);
  /** `true` cuando ya se resolvieron los caminos (gate del panel). */
  const caminosResueltos = ref(false);
  /**
   * Cuántos caminos resolvió el backend: tramos + adicionales (`caminos_resueltos`). Es otro
   * nombre que `caminosResueltos` porque ese ya es el booleano de "se resolvieron".
   */
  const cantidadCaminosResueltos = ref(0);
  /** Cómo se aplicó la posición vigente declarada en la última resolución, o `null`. */
  const estadoPosicion = ref<EstadoPosicionCaminos | null>(null);
  /** Conectores de ODF que pueden ser posición vigente del Servicio (selector, admin). */
  const posicionesPosibles = ref<PosicionPosible[]>([]);
  /** Posiciones vigentes declaradas del Servicio. */
  const posicionesDeclaradas = ref<PosicionDeclarada[]>([]);
  const cargandoPosiciones = ref(false);
  const errorPosiciones = ref('');
  /** `tiene_posiciones` de `/pelos`: lo único que ve un no admin (posiciones es un endpoint admin). */
  const posicionesEnServidor = ref(false);
  /**
   * `true` si las posiciones ya se cargaron una vez (sólo un admin puede): recién ahí tiene sentido
   * recargarlas cuando la resolución de caminos retira alguna. Un no admin recibiría un 403.
   */
  let posicionesCargadas = false;
  const resolviendoCaminos = ref(false);
  const errorCaminos = ref('');
  /** ODF confirmadas vigentes del Servicio (vienen con `/caminos`; los POST las refrescan). */
  const odfConfirmadas = ref<OdfConfirmada[]>([]);
  /** Trackings esperados que declaró el operador en LAS-FOCAS (`null` = sin declarar). */
  const esperadosDeclarados = ref<number | null>(null);
  /** Segmentos físicos de los tramos (grupos que comparten cables); 0 = sin resolver. */
  const segmentos = ref(0);
  /** Casos de inconsistencias de Cromo del Servicio (cuarentena / en revisión), con `/caminos`. */
  const inconsistencias = ref<ResumenInconsistenciasServicio>({ cuarentena: 0, en_revision: 0 });
  const guardandoDeclaracion = ref(false);
  const errorDeclaracion = ref('');
  /** Se confirmó/quitó una ODF o se cambió lo esperado: hay que volver a resolver los caminos. */
  const declaracionCambio = ref(false);

  /** ODF confirmables: las de tramos, adicionales y residuales (extremos e intermedias) más las confirmadas. */
  const odfsDelCamino = computed<OdfDelTramo[]>(() =>
    odfsConfirmables(
      [...tramos.value, ...adicionales.value, ...residuales.value],
      odfConfirmadas.value,
    ),
  );

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
  /**
   * Hay posiciones de ODF con las que resolver aunque no haya semillas etiquetadas: el 93150 va por
   * pelos con la etiqueta de un servicio de Baja del mismo cliente.
   */
  const tienePosiciones = computed(
    () =>
      posicionesEnServidor.value ||
      // Un conector sin pelo se lista en el selector pero no es input de `/path`.
      posicionesPosibles.value.some((p) => p.pelo_n_id !== null) ||
      posicionesDeclaradas.value.length > 0,
  );
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
      pelosSeleccionados.value = tramos.value.map((t) => t.pelo_n_id);
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
      posicionesEnServidor.value = respuesta.tiene_posiciones ?? false;
    } catch (error) {
      errorPelos.value = mensajeErrorCromoPath(error);
      pelos.value = [];
      posicionesEnServidor.value = false;
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
          resultado.descargados.push(
            await descargarTrackingCromo(servicioId, {
              peloNId,
              // Si el pelo es un tramo conocido, el archivo lleva su nombre de tramo.
              tramo: tramos.value.find((t) => t.pelo_n_id === peloNId)?.n ?? null,
            }),
          );
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
   * Resuelve los caminos del Servicio en el backend y deja tildado el pelo de cada tramo. Los
   * residuales sólo se cuentan: no se descargan.
   */
  async function resolverCaminos(servicioId: number): Promise<boolean> {
    resolviendoCaminos.value = true;
    errorCaminos.value = '';
    try {
      const respuesta = await resolverCaminosServicio(servicioId);
      tramos.value = respuesta.tramos;
      residuales.value = respuesta.residuales;
      adicionales.value = respuesta.adicionales ?? [];
      cantidadCaminosResueltos.value = respuesta.caminos_resueltos ?? respuesta.tramos.length;
      estadoPosicion.value = respuesta.posicion_vigente ?? null;
      caminosEsperados.value = respuesta.esperados_declarados ?? respuesta.tramos.length;
      caminosResueltos.value = true;
      odfConfirmadas.value = respuesta.odf_confirmadas ?? [];
      esperadosDeclarados.value = respuesta.esperados_declarados;
      segmentos.value = respuesta.segmentos ?? 0;
      inconsistencias.value = respuesta.inconsistencias ?? { cuarentena: 0, en_revision: 0 };
      declaracionCambio.value = false;
      seleccionManual.value = false;
      pelosSeleccionados.value = respuesta.tramos.map((t) => t.pelo_n_id);
      // Con semillas que no resolvieron se avisa aunque el recorrido haya terminado: puede faltar
      // un tramo entero. El tope de consultas se menciona sólo si de verdad se tocó. Los avisos de
      // la posición vigente van aparte (`estadoPosicion`): el panel los pinta como aviso, no error.
      errorCaminos.value = avisosDeCaminos(respuesta).join(' ');
      // La corrida puede retirar una posición declarada (pelo que cambió, otro camino sano): la
      // lista del selector tiene que reflejarlo sin recargar la vista.
      if (posicionesCargadas && respuesta.posicion_vigente?.avisos.some((a) => a.retirada)) {
        await cargarPosiciones(servicioId);
      }
      return respuesta.tramos.length > 0;
    } catch (error) {
      errorCaminos.value = mensajeErrorCromoPath(error);
      return false;
    } finally {
      resolviendoCaminos.value = false;
    }
  }

  /**
   * Corre una escritura de lo declarado (ODF, esperados o posición vigente) con su estado de carga
   * y su error. La posición vigente reporta en su propio error y con sus propios mensajes: su
   * bloque del panel se ve aunque los caminos no estén resueltos.
   */
  async function guardarDeclaracion(
    accion: () => Promise<void>,
    opciones: { error?: Ref<string>; mensaje?: (error: unknown) => string } = {},
  ): Promise<boolean> {
    const destinoError = opciones.error ?? errorDeclaracion;
    guardandoDeclaracion.value = true;
    destinoError.value = '';
    try {
      await accion();
      declaracionCambio.value = true;
      return true;
    } catch (error) {
      destinoError.value = (opciones.mensaje ?? mensajeErrorCromoPath)(error);
      return false;
    } finally {
      guardandoDeclaracion.value = false;
    }
  }

  /** Confirma una ODF del camino con el rol elegido. Admin. */
  function confirmarOdf(servicioId: number, odfNId: number, rol: RolOdfConfirmada): Promise<boolean> {
    return guardarDeclaracion(async () => {
      const r = await confirmarOdfsServicio(servicioId, [{ odf_n_id: odfNId, rol }]);
      odfConfirmadas.value = r.odf_confirmadas;
    });
  }

  /** Quita la confirmación de una ODF. Admin. */
  function quitarOdf(servicioId: number, odfNId: number): Promise<boolean> {
    return guardarDeclaracion(async () => {
      const r = await desconfirmarOdfServicio(servicioId, odfNId);
      odfConfirmadas.value = r.odf_confirmadas;
    });
  }

  /** Declara cuántos trackings espera el Servicio (`null` borra la declaración). Admin. */
  function declararEsperados(servicioId: number, cantidad: number | null): Promise<boolean> {
    return guardarDeclaracion(async () => {
      const r = await declararTrackingsEsperados(servicioId, cantidad);
      esperadosDeclarados.value = r.trackings_esperados;
    });
  }

  /** Deja las posibles marcadas según lo declarado (el POST devuelve sólo las declaradas). */
  function _sincronizarDeclaradas(declaradas: PosicionDeclarada[]): void {
    posicionesDeclaradas.value = declaradas;
    const vigentes = new Set(declaradas.map((d) => d.conector_n_id));
    posicionesPosibles.value = posicionesPosibles.value.map((p) => ({
      ...p,
      declarada: vigentes.has(p.conector_n_id),
    }));
  }

  /** Posiciones declaradas y posibles del Servicio. SQL local, no toca Cromo. Admin. */
  async function cargarPosiciones(servicioId: number): Promise<boolean> {
    cargandoPosiciones.value = true;
    errorPosiciones.value = '';
    try {
      const respuesta = await obtenerPosicionVigente(servicioId);
      posicionesPosibles.value = respuesta.posibles;
      posicionesDeclaradas.value = respuesta.declaradas;
      posicionesCargadas = true;
      return true;
    } catch (error) {
      errorPosiciones.value = mensajeErrorPosicionVigente(error);
      return false;
    } finally {
      cargandoPosiciones.value = false;
    }
  }

  /**
   * Declara conectores como posición vigente (todo o nada). Se aplica al volver a resolver los
   * caminos: por eso pasa por `guardarDeclaracion`, que prende `declaracionCambio`. Admin.
   */
  function declararPosicion(servicioId: number, conectoresNId: number[]): Promise<boolean> {
    return guardarDeclaracion(
      async () => {
        const r = await declararPosicionVigente(servicioId, conectoresNId);
        _sincronizarDeclaradas(r.declaradas);
      },
      { error: errorPosiciones, mensaje: mensajeErrorPosicionVigente },
    );
  }

  /** Retira a mano una posición vigente; el Servicio vuelve al cálculo automático. Admin. */
  function retirarPosicion(servicioId: number, conectorNId: number): Promise<boolean> {
    return guardarDeclaracion(
      async () => {
        const r = await retirarPosicionVigente(servicioId, conectorNId);
        _sincronizarDeclaradas(r.declaradas);
      },
      { error: errorPosiciones, mensaje: mensajeErrorPosicionVigente },
    );
  }

  /** Baja el `.txt` de un camino adicional (`{servicio} CROMO A{n} pelo {id}.txt`). */
  async function descargarAdicional(servicioId: number, adicional: CaminoAdicional): Promise<boolean> {
    descargando.value = true;
    errorDescarga.value = '';
    try {
      await descargarTrackingCromo(servicioId, {
        peloNId: adicional.pelo_n_id,
        adicional: adicional.n,
      });
      return true;
    } catch (error) {
      errorDescarga.value = mensajeErrorCromoPath(error, { peloNId: adicional.pelo_n_id });
      return false;
    } finally {
      descargando.value = false;
    }
  }

  /** Baja el `.txt` de un solo tramo (botón "Descargar" de su fila). */
  async function descargarTramo(servicioId: number, tramo: TramoDelServicio): Promise<boolean> {
    descargando.value = true;
    errorDescarga.value = '';
    try {
      await descargarTrackingCromo(servicioId, { peloNId: tramo.pelo_n_id, tramo: tramo.n });
      return true;
    } catch (error) {
      errorDescarga.value = mensajeErrorCromoPath(error, { peloNId: tramo.pelo_n_id });
      return false;
    } finally {
      descargando.value = false;
    }
  }

  /** Devuelve un pelo al Servicio. Invalida los caminos resueltos: el pelo puede cambiarlos. */
  async function restaurarPelo(servicioId: number, peloNId: number): Promise<boolean> {
    peloEnExclusion.value = peloNId;
    errorExclusion.value = '';
    try {
      await restaurarPeloServicio(servicioId, peloNId);
      caminosResueltos.value = false;
      tramos.value = [];
      residuales.value = [];
      adicionales.value = [];
      cantidadCaminosResueltos.value = 0;
      estadoPosicion.value = null;
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
    tramos.value = [];
    residuales.value = [];
    adicionales.value = [];
    cantidadCaminosResueltos.value = 0;
    estadoPosicion.value = null;
    posicionesPosibles.value = [];
    posicionesDeclaradas.value = [];
    posicionesEnServidor.value = false;
    cargandoPosiciones.value = false;
    errorPosiciones.value = '';
    posicionesCargadas = false;
    caminosResueltos.value = false;
    resolviendoCaminos.value = false;
    errorCaminos.value = '';
    odfConfirmadas.value = [];
    esperadosDeclarados.value = null;
    segmentos.value = 0;
    inconsistencias.value = { cuarentena: 0, en_revision: 0 };
    errorDeclaracion.value = '';
    declaracionCambio.value = false;
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
    tramos,
    residuales,
    adicionales,
    caminosResueltos,
    cantidadCaminosResueltos,
    estadoPosicion,
    posicionesPosibles,
    posicionesDeclaradas,
    cargandoPosiciones,
    errorPosiciones,
    tienePosiciones,
    resolviendoCaminos,
    errorCaminos,
    odfConfirmadas,
    esperadosDeclarados,
    segmentos,
    inconsistencias,
    guardandoDeclaracion,
    errorDeclaracion,
    declaracionCambio,
    odfsDelCamino,
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
    descargarTramo,
    descargarAdicional,
    cargarPosiciones,
    declararPosicion,
    retirarPosicion,
    confirmarOdf,
    quitarOdf,
    declararEsperados,
    restaurarPelo,
    reset,
    autoResolverSiUnicaSemilla,
  };
}
