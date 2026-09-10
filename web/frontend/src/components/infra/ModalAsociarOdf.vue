<!--
  Nombre de archivo: ModalAsociarOdf.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalAsociarOdf.vue
  Descripción: Modal para asociar manualmente un Servicio sin ODF a la ODF correcta — causa/extremos, sugerencia no auto-aplicada, buscador de ODF (reusa el inventario Cromo) y badge de señal de dirección no bloqueante
-->
<template>
  <dialog ref="dialogEl" class="asociar-odf-modal" @click.self="handleClose" @cancel="handleCancelKey">
    <div class="modal-content">
      <div class="asociar-odf-title-row">
        <strong>Asociar ODF — Servicio {{ servicioNumero || servicioId }}</strong>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </div>

      <div v-if="cargandoDetalle" class="asociar-odf-empty">Cargando causa del Servicio...</div>
      <div v-else-if="errorDetalle" class="asociar-odf-empty error">{{ errorDetalle }}</div>

      <template v-else-if="detalle">
        <div class="asociar-odf-causa">
          <span class="asociar-odf-badge-categoria">{{ categoriaLabelActual }}</span>
          <span v-if="subcategoriaLabelActual" class="asociar-odf-badge-subcategoria">{{ subcategoriaLabelActual }}</span>
        </div>

        <p class="asociar-odf-direccion"><strong>Dirección PROV:</strong> {{ detalle.direccion || 'sin dato' }}</p>

        <div v-if="detalle.extremos.length > 0" class="asociar-odf-extremos">
          <div
            v-for="(extremo, index) in detalle.extremos"
            :key="`${extremo.extremo ?? index}`"
            :class="['asociar-odf-extremo', { 'is-ganador': index === detalle.indice_extremo_categorizado }]"
          >
            <span class="asociar-odf-extremo-label">
              Extremo {{ extremo.extremo ?? index + 1 }}
              <i
                v-if="index === detalle.indice_extremo_categorizado"
                class="ph ph-check-circle"
                title="Extremo que determinó la categoría"
                aria-hidden="true"
              ></i>
            </span>
            <span>{{ extremo.nodo || '—' }} / {{ extremo.equipo || '—' }}</span>
          </div>
        </div>
        <p v-else class="asociar-odf-direccion">Sin fila de última milla PROV.</p>

        <div v-if="detalle.sugerencia" class="asociar-odf-sugerencia">
          <p>
            <i class="ph ph-lightbulb" aria-hidden="true"></i>
            Sugerencia: <strong>{{ detalle.sugerencia.nombre || `ODF ${detalle.sugerencia.odf_n_id}` }}</strong>
            <span class="asociar-odf-sugerencia-nid">(n_id {{ detalle.sugerencia.odf_n_id }})</span>
            — {{ justificacionSugerencia }}
          </p>
          <p v-if="detalle.sugerencia.cantidad_candidatas > 1" class="asociar-odf-sugerencia-aviso">
            <i class="ph ph-warning" aria-hidden="true"></i>
            Hay <strong>{{ detalle.sugerencia.cantidad_candidatas }} ODFs candidatas</strong> para este grupo de
            última milla. Esta es la más corroborada (la que más Servicios hermanos ya tienen resuelta), no la
            única — conviene verificarla antes de confirmar.
          </p>
          <button class="btn subtle" type="button" @click="usarSugerencia">Usar esta ODF</button>
        </div>
      </template>

      <div class="asociar-odf-hairline"></div>

      <!-- ── Camino óptico de Cromo ─────────────────────────────────────────────────────── -->
      <section class="asociar-odf-camino">
        <header class="asociar-odf-camino__head">
          <h4 class="asociar-odf-camino__titulo">Camino óptico en Cromo</h4>
          <button
            v-if="camino.tieneSemilla.value"
            class="btn subtle"
            type="button"
            :disabled="camino.resolviendo.value"
            @click="props.servicioId != null && camino.resolver(props.servicioId)"
          >
            <i class="ph ph-tree-structure" aria-hidden="true"></i>
            {{ camino.resultado.value ? 'Resolver de nuevo' : 'Resolver camino' }}
          </button>
        </header>

        <p v-if="camino.cargandoPelos.value" class="asociar-odf-camino__nota">Buscando pelos…</p>
        <p v-else-if="!camino.tieneSemilla.value" class="asociar-odf-camino__nota">
          Este Servicio no tiene ningún pelo en Cromo, así que no hay camino que resolver.
        </p>

        <CromoPeloSelector
          v-if="camino.tieneSemilla.value"
          :pelos="camino.pelos.value"
          :model-value="camino.peloElegido.value"
          :disabled="camino.resolviendo.value"
          @update:model-value="camino.peloElegido.value = $event"
        />

        <!-- Espera honesta: sin progreso del servidor, el único progreso real es el tiempo. -->
        <div
          v-if="camino.resolviendo.value"
          class="asociar-odf-camino__esperando"
          aria-live="polite"
          aria-busy="true"
        >
          <i class="ph ph-circle-notch asociar-odf-camino__spin" aria-hidden="true"></i>
          <span>Resolviendo camino en Cromo… {{ camino.segundos.value }} s</span>
          <button class="btn subtle" type="button" @click="camino.cancelar()">Cancelar</button>
          <p v-if="camino.avisoLento.value" class="asociar-odf-camino__nota">
            Cromo resuelve el grafo en memoria; un camino largo puede tardar más. Podés cancelar y
            seguir con la asociación manual: el camino es una señal, no un requisito.
          </p>
        </div>

        <p v-else-if="camino.cancelado.value" class="asociar-odf-camino__nota">
          Cancelaste la resolución.
        </p>
        <p v-else-if="camino.errorPath.value" class="asociar-odf-camino__error">
          {{ camino.errorPath.value }}
        </p>

        <template v-else-if="camino.resultado.value">
          <p v-if="camino.resultado.value.estado !== 'OK'" class="asociar-odf-camino__nota">
            {{ camino.resultado.value.motivo }}
          </p>

          <template v-else>
            <p class="asociar-odf-camino__meta">
              {{ camino.resultado.value.estadisticas.nodos }} nodos ·
              {{ camino.resultado.value.estadisticas.cables }} cables ·
              {{ camino.resultado.value.estadisticas.odfs }} ODFs ·
              {{ Math.round(camino.resultado.value.estadisticas.longitud_optica_m) }} m ópticos ·
              pelo n_id {{ camino.resultado.value.pelo_n_id }}
              <template v-if="camino.resultado.value.servicio_at62">
                · at.62 <strong>{{ camino.resultado.value.servicio_at62 }}</strong>
              </template>
              <template v-if="camino.resultado.value.duracion_ms">
                · {{ (camino.resultado.value.duracion_ms / 1000).toFixed(1) }} s
              </template>
            </p>

            <p
              v-for="(aviso, i) in camino.resultado.value.advertencias"
              :key="i"
              class="asociar-odf-camino__aviso"
            >
              <i class="ph ph-warning" aria-hidden="true"></i> {{ aviso }}
            </p>

            <!-- ODFs descubiertas: se ofrecen, no se aplican. -->
            <ul v-if="camino.resultado.value.odfs.length > 0" class="asociar-odf-camino__odfs">
              <li v-for="odf in camino.resultado.value.odfs" :key="odf.odf_id">
                <span class="asociar-odf-camino__odf-nombre">
                  {{ odf.nombre || `ODF ${odf.odf_id}` }}
                  <span class="asociar-odf-camino__odf-meta">
                    lado {{ odf.lado }}
                    <template v-if="odf.patchera_nombre"> · {{ odf.patchera_nombre }}</template>
                    <template v-if="odf.conector_numero"> · conector {{ odf.conector_numero }}</template>
                  </span>
                </span>
                <button
                  v-if="odf.vinculo_local"
                  class="btn subtle"
                  type="button"
                  @click="usarOdfDelCamino(odf)"
                >
                  Traer al buscador
                </button>
                <!-- Sin fila local no se puede armar la asociación: se dice, no se ofrece un
                     botón que fallaría. -->
                <span v-else class="asociar-odf-camino__odf-sin-vinculo">
                  No está en el inventario ingerido — buscala a mano
                </span>
              </li>
            </ul>

            <CromoConsistenciaPanel
              v-if="camino.resultado.value.consistencia"
              :consistencia="camino.resultado.value.consistencia"
            />

            <CromoPathSecuencia
              :nodos="[
                ...camino.resultado.value.lado_b.slice().reverse(),
                ...(camino.resultado.value.raiz ? [camino.resultado.value.raiz] : []),
                ...camino.resultado.value.lado_a,
              ]"
              :truncado="camino.resultado.value.ids_no_resueltos.length > 0"
            />
          </template>
        </template>
      </section>

      <div class="asociar-odf-hairline"></div>

      <template v-if="!odfSeleccionada">
        <!-- El placeholder dice SÓLO "nombre" porque es lo único que el backend matchea:
             `odf_inventario.py::_FILTROS_SQL` filtra por `o.nombre ILIKE`, nunca por calle/altura.
             Prometer "o dirección" hacía que una búsqueda legítima por domicilio pareciera "no hay
             ninguna ODF ahí" cuando en realidad ese filtro no existe. -->
        <input
          v-model="query"
          type="text"
          placeholder="Buscar ODF por nombre..."
          class="asociar-odf-search"
          @input="onSearchInput"
        />

        <div v-if="buscandoOdf" class="asociar-odf-empty">Buscando...</div>
        <div v-else-if="errorBusqueda" class="asociar-odf-empty error">{{ errorBusqueda }}</div>
        <div v-else-if="query.trim() && resultadosOdf.length === 0" class="asociar-odf-empty">
          Ninguna ODF coincide con "{{ query }}".
        </div>
        <ul v-else-if="resultadosOdf.length" class="asociar-odf-results">
          <li
            v-for="candidata in resultadosOdf"
            :key="candidata.n_id"
            class="asociar-odf-result-item"
            @click="odfSeleccionada = candidata"
          >
            <strong>{{ candidata.nombre || `ODF ${candidata.n_id}` }}</strong>
            <span class="asociar-odf-result-meta">
              n_id {{ candidata.n_id }} ·
              {{ [candidata.calle, candidata.altura].filter(Boolean).join(' ') || 'sin dirección' }} ·
              {{ candidata.localidad || '—' }}
            </span>
          </li>
        </ul>
      </template>

      <template v-else>
        <div class="asociar-odf-seleccion">
          <div class="asociar-odf-seleccion-row">
            <strong>{{ odfSeleccionada.nombre || `ODF ${odfSeleccionada.n_id}` }}</strong>
            <span class="asociar-odf-seleccion-meta">
              n_id {{ odfSeleccionada.n_id }} ·
              {{ [odfSeleccionada.calle, odfSeleccionada.altura].filter(Boolean).join(' ') || 'sin dirección' }}
            </span>
          </div>
          <span :class="['asociar-odf-senal', `is-${senalTokenActual}`]">
            <i :class="['ph', senalIconoActual, { 'asociar-odf-senal-spin': cargandoSenal }]" aria-hidden="true"></i>
            {{ senalLabelActual }}
          </span>
        </div>

        <textarea v-model="notas" class="asociar-odf-notas" rows="2" placeholder="Notas (opcional)"></textarea>

        <div v-if="errorConfirmar" class="asociar-odf-empty error">{{ errorConfirmar }}</div>

        <div class="asociar-odf-actions">
          <button class="btn primary" type="button" :disabled="confirmando" @click="handleConfirmar">
            {{ confirmando ? 'Asociando...' : 'Confirmar asociación' }}
          </button>
          <button class="btn subtle" type="button" :disabled="confirmando" @click="odfSeleccionada = null">
            Volver a buscar
          </button>
        </div>
      </template>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';

import { buscarInventarioOdfs, type CromoOdfInventario } from '../../api/cromo';
import type { OdfDelCamino } from '../../api/cromoPath';
import { useCromoPath } from '../../composables/useCromoPath';
import CromoConsistenciaPanel from './CromoConsistenciaPanel.vue';
import CromoPathSecuencia from './CromoPathSecuencia.vue';
import CromoPeloSelector from './CromoPeloSelector.vue';
import {
  asociarServicioOdf,
  categoriaServicioLabel,
  getSenalDireccionPreview,
  getSugerenciaServicio,
  subcategoriaLabel,
  type SenalDireccion,
  type SugerenciaServicioResponse,
} from '../../api/serviciosOdf';

const props = defineProps<{
  open: boolean;
  servicioId: number | null;
  servicioNumero?: string;
  /** Entrar directamente en modo camino (viene del botón "Resolver camino" de la tarjeta). Es una
   * PROP y no estado interno a propósito: así es inmune a `resetState()`, que corre al abrir. */
  iniciarEnCamino?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  asociado: [servicioId: number];
  error: [message: string];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);

const cargandoDetalle = ref(false);
const errorDetalle = ref('');
const detalle = ref<SugerenciaServicioResponse | null>(null);

const query = ref('');
const resultadosOdf = ref<CromoOdfInventario[]>([]);
const buscandoOdf = ref(false);
const errorBusqueda = ref('');

const odfSeleccionada = ref<CromoOdfInventario | null>(null);
const senalPreview = ref<SenalDireccion | null>(null);
const cargandoSenal = ref(false);
const notas = ref('');
const confirmando = ref(false);
const errorConfirmar = ref('');

let debounceTimer: ReturnType<typeof setTimeout> | null = null;

const camino = useCromoPath();
/** Pelo que se persiste al confirmar: sólo si la ODF elegida salió de un camino resuelto. */
const peloParaPersistir = ref<number | null>(null);

const categoriaLabelActual = computed(() => (detalle.value ? categoriaServicioLabel(detalle.value.categoria_causa) : ''));
const subcategoriaLabelActual = computed(() => subcategoriaLabel(detalle.value?.subcategoria ?? null));

/** Justifica la sugerencia con datos que la API SÍ da (el extremo que ganó la categorización), no
 * con un conteo inventado — `GET .../sugerencia` no devuelve cuántos servicios comparten ODF. */
const justificacionSugerencia = computed(() => {
  if (!detalle.value?.sugerencia) return '';
  const indice = detalle.value.indice_extremo_categorizado;
  const extremo = indice != null ? detalle.value.extremos[indice] : null;
  if (extremo && (extremo.nodo || extremo.equipo)) {
    return `un Servicio del mismo OLT (${extremo.nodo || '—'} / ${extremo.equipo || '—'}) ya está asociado a esta ODF.`;
  }
  return 'un Servicio hermano del mismo equipo de última milla ya está asociado a esta ODF.';
});

/** Carga el preview real de `senal_direccion` para la ODF que el operador acaba de seleccionar —
 * fix round 1: antes esto sólo se conocía para la ODF sugerida (y sólo existe sugerencia para
 * OLT_PON_COMPARTIDO, 53% del universo); ahora se calcula igual para CUALQUIER ODF elegida a mano
 * vía `GET .../senal-direccion` (puro read-only, nunca persiste). Si falla (red, 404 de una ODF
 * que dejó de existir entre la búsqueda y el click, etc.) se degrada a "no se pudo comparar" sin
 * romper el flujo — nunca bloquea la selección ni el botón de confirmar.
 *
 * Fix round 2: guarda contra resolución fuera de orden. `odf` queda capturado en el closure de
 * esta invocación puntual del watcher — si para cuando la response llega `odfSeleccionada.value`
 * ya cambió (el operador volvió a buscar y eligió otra ODF, o deseleccionó), esta respuesta es
 * stale y se descarta sin tocar el estado. Sin esta guarda, una respuesta vieja que llega después
 * de una más nueva (jitter de red normal) pisa la señal correcta con la de una ODF que ya no es la
 * seleccionada — silenciosa y sin nada que la corrija después. Una señal de la ODF equivocada es
 * peor que ninguna señal, porque el operador le cree. */
watch(odfSeleccionada, async (odf) => {
  senalPreview.value = null;
  if (!odf || props.servicioId == null) return;
  cargandoSenal.value = true;
  try {
    const respuesta = await getSenalDireccionPreview(props.servicioId, odf.n_id);
    if (odf !== odfSeleccionada.value) return; // selección cambió mientras esperábamos: descartar
    senalPreview.value = respuesta.senal_direccion;
  } catch {
    if (odf !== odfSeleccionada.value) return;
    senalPreview.value = null;
  } finally {
    if (odf === odfSeleccionada.value) cargandoSenal.value = false;
  }
});

const senalLabelActual = computed(() => {
  if (cargandoSenal.value) return 'Comparando direcciones...';
  const senal = senalPreview.value;
  if (senal === 'coincide') return 'Dirección coincide';
  if (senal === 'no_coincide') return 'Dirección no coincide, ¿confirmás igual?';
  return 'No se pudo comparar';
});

const senalTokenActual = computed<'ok' | 'warn' | 'idle'>(() => {
  const senal = senalPreview.value;
  if (senal === 'coincide') return 'ok';
  if (senal === 'no_coincide') return 'warn';
  return 'idle';
});

const senalIconoActual = computed(() => {
  if (cargandoSenal.value) return 'ph-circle-notch';
  const senal = senalPreview.value;
  if (senal === 'coincide') return 'ph-check-circle';
  if (senal === 'no_coincide') return 'ph-warning';
  return 'ph-question';
});

function onSearchInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => void buscar(), 300);
}

/** Búsqueda de ODFs en el inventario Cromo. Por defecto busca por el texto del buscador
 * (`nombre ILIKE`), pero con `nId` busca por identidad EXACTA (`o.n_id = :n_id` en
 * `odf_inventario.py`), que es lo que usa `usarSugerencia()`. */
async function buscar(opciones: { nId?: number } = {}): Promise<void> {
  const texto = query.value.trim();
  if (opciones.nId === undefined && !texto) {
    resultadosOdf.value = [];
    return;
  }
  buscandoOdf.value = true;
  errorBusqueda.value = '';
  try {
    const respuesta = await buscarInventarioOdfs(
      opciones.nId !== undefined ? { nId: opciones.nId, limit: 10 } : { q: texto, limit: 10 },
    );
    resultadosOdf.value = respuesta.odfs;
  } catch (e: unknown) {
    errorBusqueda.value = e instanceof Error ? e.message : 'No se pudo buscar ODFs.';
  } finally {
    buscandoOdf.value = false;
  }
}

/** Trae la ODF sugerida al buscador por su `n_id`, NUNCA por su nombre — el operador sigue
 * teniendo que hacer click en el resultado para seleccionarlo, y la asociación siempre pasa por
 * `handleConfirmar` (esto nunca dispara el POST por su cuenta).
 *
 * Por qué por `n_id` y no por nombre: **217 ODFs de dev comparten nombre con otra** (100 grupos de
 * homónimos, hasta 4 por grupo, medido real 2026-09-09). Buscando por nombre, una sugerencia como
 * "ODF Azopardo 250 Piso 12" devolvía las 3 homónimas sin ninguna forma de saber cuál había
 * sugerido la API — el operador tenía 1 de 3 de acertar y confirmaba creyendo que confirmaba la
 * sugerida, escribiendo la ODF equivocada en `cromo_servicio_odf_override`. El filtro `n_id` de
 * `odf_inventario.py` es igualdad exacta sobre la PK, así que devuelve exactamente esa ODF.
 *
 * `query` queda con el `n_id` en texto para que el estado vacío ("Ninguna ODF coincide con ...")
 * diga contra qué se buscó si la ODF sugerida dejó de existir entre el detalle y este click. */
/** Único camino para traer una ODF al buscador: **siempre por `n_id`, nunca por nombre**.
 * 217 ODFs de dev comparten nombre (100 grupos de homónimos), así que buscar por nombre le daba
 * al operador 1 de 3 de acertar. */
function traerAlBuscadorPorNId(nId: number): void {
  query.value = String(nId);
  void buscar({ nId });
}

function usarSugerencia(): void {
  const sugerencia = detalle.value?.sugerencia;
  if (!sugerencia) return;
  peloParaPersistir.value = null;
  traerAlBuscadorPorNId(sugerencia.odf_n_id);
}

/**
 * Trae al buscador una ODF descubierta en el camino.
 *
 * NO auto-selecciona ni confirma: `cromo_servicio_odf_override` es append-only sin tombstone
 * —desasociar todavía no existe en la UI— así que el costo de no auto-seleccionar es un click y
 * el de equivocarse es un registro irreversible.
 */
function usarOdfDelCamino(odf: OdfDelCamino): void {
  const nId = odf.vinculo_local?.n_id;
  if (!nId) return;
  peloParaPersistir.value = camino.resultado.value?.pelo_n_id ?? null;
  // La procedencia queda escrita en la asociación, no sólo en pantalla. No pisa lo que el
  // operador ya escribió.
  if (!notas.value.trim() && camino.resultado.value) {
    const r = camino.resultado.value;
    notas.value =
      `Camino Cromo /path desde pelo n_id=${r.pelo_n_id} · ${r.estadisticas.nodos} nodos · ` +
      `${((r.duracion_ms ?? 0) / 1000).toFixed(1)} s · ${new Date().toISOString()}`;
  }
  traerAlBuscadorPorNId(nId);
}

async function cargarDetalle(): Promise<void> {
  if (props.servicioId == null) return;
  cargandoDetalle.value = true;
  errorDetalle.value = '';
  detalle.value = null;
  try {
    detalle.value = await getSugerenciaServicio(props.servicioId);
  } catch (e: unknown) {
    errorDetalle.value = e instanceof Error ? e.message : 'No se pudo cargar la causa del Servicio.';
  } finally {
    cargandoDetalle.value = false;
  }
  // Las semillas son SQL local: no tocan Cromo, así que se pueden pedir al abrir sin costo para
  // el proveedor. Lo costoso es resolver el camino, y eso lo dispara el operador.
  await camino.cargarPelos(props.servicioId);
}

function resetState(): void {
  query.value = '';
  resultadosOdf.value = [];
  odfSeleccionada.value = null;
  senalPreview.value = null;
  cargandoSenal.value = false;
  notas.value = '';
  errorBusqueda.value = '';
  errorConfirmar.value = '';
  errorDetalle.value = '';
  detalle.value = null;
  peloParaPersistir.value = null;
  camino.reset();
}

function handleClose(): void {
  // Cancela una resolución en vuelo: sin esto, una respuesta de 12 s llegaría a un modal ya
  // cerrado y apagaría el spinner de un modal reabierto para OTRO Servicio.
  camino.cancelar();
  dialogEl.value?.close();
  resetState();
  emit('close');
}

/** Escape dispara el evento nativo `cancel` de `<dialog>` ANTES de cerrarlo — sin este listener,
 * el browser cierra el `<dialog>` por su cuenta pero nunca llama a `handleClose()`, así que
 * `modalOpen` en el padre queda en `true` (nadie emitió `close`) y un click posterior en "Asociar
 * ODF" de cualquier tarjeta vuelve a asignar el mismo `true` — no-op para la reactividad de Vue, el
 * modal no vuelve a abrirse. `preventDefault()` frena el auto-cierre nativo para que `handleClose()`
 * sea el ÚNICO camino que cierra el diálogo y sincroniza el estado — Escape pasa por exactamente el
 * mismo código que el botón "×"/el click en el backdrop, nunca un camino paralelo. */
function handleCancelKey(event: Event): void {
  event.preventDefault();
  handleClose();
}

async function handleConfirmar(): Promise<void> {
  if (props.servicioId == null || !odfSeleccionada.value) return;
  confirmando.value = true;
  errorConfirmar.value = '';
  try {
    await asociarServicioOdf(props.servicioId, {
      odfNId: odfSeleccionada.value.n_id,
      // Llena el `pelo_n_id` que hoy viaja siempre `null`: sólo cuando la ODF salió de un camino
      // resuelto de ESTE Servicio, así queda la trazabilidad de dónde vino la asociación.
      peloNId: peloParaPersistir.value,
      notas: notas.value.trim() || null,
    });
    emit('asociado', props.servicioId);
    handleClose();
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : 'No se pudo asociar el Servicio a la ODF.';
    errorConfirmar.value = message;
    emit('error', message);
  } finally {
    confirmando.value = false;
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      resetState();
      dialogEl.value?.showModal();
      void cargarDetalle().then(() => {
        if (props.iniciarEnCamino && props.servicioId != null) {
          void camino.autoResolverSiUnicaSemilla(props.servicioId);
        }
      });
      return;
    }
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
);

// Si el componente se desmonta con una resolución en vuelo, se aborta: la respuesta ya no tiene
// dónde aterrizar.
onBeforeUnmount(() => camino.cancelar());
</script>

<style scoped>
.asociar-odf-modal {
  width: min(600px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.asociar-odf-modal::backdrop {
  background: color-mix(in srgb, var(--color-bg) 82%, transparent);
  backdrop-filter: blur(8px);
}

.modal-content {
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-lg);
  padding: 24px;
  color: var(--text);
  box-shadow: var(--shadow-lg);
  max-height: calc(100vh - 64px);
  overflow-y: auto;
}

.asociar-odf-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--muted);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}

.asociar-odf-causa {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.asociar-odf-badge-categoria,
.asociar-odf-badge-subcategoria {
  display: inline-flex;
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  font-size: 11.5px;
  border: 1px solid var(--color-divider);
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}

.asociar-odf-direccion {
  font-size: 0.85rem;
  color: var(--muted);
  margin: 0 0 10px;
}

.asociar-odf-extremos {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 12px;
}

.asociar-odf-extremo {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-text) 4%, transparent);
  font-size: 12.5px;
}

.asociar-odf-extremo.is-ganador {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
}

.asociar-odf-extremo-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.asociar-odf-sugerencia {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  margin-bottom: 12px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-accent) 35%, transparent);
}

.asociar-odf-sugerencia p {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--text);
}

.asociar-odf-sugerencia .btn {
  align-self: flex-start;
}

.asociar-odf-sugerencia-nid {
  font-size: 0.78rem;
  color: var(--muted);
}

/* Selector con el `p` incluido a propósito: `.asociar-odf-sugerencia p` (0,1,1) le gana en
   especificidad a una clase sola (0,1,0) y le pisaría el color de aviso. */
.asociar-odf-sugerencia p.asociar-odf-sugerencia-aviso {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  color: var(--color-state-warn);
}

.asociar-odf-sugerencia p.asociar-odf-sugerencia-aviso strong {
  color: var(--color-state-warn);
}

.asociar-odf-camino {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.asociar-odf-camino__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.asociar-odf-camino__titulo {
  margin: 0;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.asociar-odf-camino__nota {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.45;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.asociar-odf-camino__error {
  margin: 0;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  font-size: 11.5px;
  background: color-mix(in srgb, var(--color-state-error) 14%, transparent);
  color: var(--color-state-error);
}

.asociar-odf-camino__aviso {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 0;
  font-size: 11.5px;
  color: var(--color-state-warn);
}

.asociar-odf-camino__esperando {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 9px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
  font-size: 12px;
}

/* Reusa el `@keyframes spin` global de tokens.css en vez de definir uno local. */
.asociar-odf-camino__spin {
  animation: spin 1s linear infinite;
}

.asociar-odf-camino__meta {
  margin: 0;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
}

.asociar-odf-camino__odfs {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.asociar-odf-camino__odfs li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-accent) 8%, transparent);
}

.asociar-odf-camino__odf-nombre {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  font-size: 12.5px;
}

.asociar-odf-camino__odf-meta {
  font-size: 10.5px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.asociar-odf-camino__odf-sin-vinculo {
  flex: none;
  font-size: 10.5px;
  color: var(--color-state-idle);
}

.asociar-odf-hairline {
  height: 1px;
  background: var(--color-divider);
  margin: 4px 0 14px;
}

.asociar-odf-search {
  width: 100%;
  padding: 8px 12px;
  margin-bottom: 12px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  color: var(--text);
}

.asociar-odf-empty {
  padding: 14px;
  border-radius: var(--radius-md);
  border: 1px dashed var(--color-divider);
  color: var(--muted);
  font-size: 0.85rem;
  text-align: center;
}

.asociar-odf-empty.error {
  border-color: color-mix(in srgb, var(--error) 40%, transparent);
  color: var(--error);
}

.asociar-odf-results {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.asociar-odf-result-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  cursor: pointer;
  transition: border-color 0.15s ease;
}

.asociar-odf-result-item:hover {
  border-color: var(--color-accent);
}

.asociar-odf-result-meta {
  font-size: 0.75rem;
  color: var(--muted);
}

.asociar-odf-seleccion {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  margin-bottom: 10px;
  border-radius: var(--radius-md);
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
}

.asociar-odf-seleccion-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.asociar-odf-seleccion-meta {
  font-size: 0.75rem;
  color: var(--muted);
}

.asociar-odf-senal {
  display: inline-flex;
  align-self: flex-start;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  font-size: 11.5px;
}

.asociar-odf-senal.is-ok {
  background: color-mix(in srgb, var(--color-state-ok) 18%, transparent);
  color: var(--color-state-ok);
}

.asociar-odf-senal.is-warn {
  background: color-mix(in srgb, var(--color-state-warn) 18%, transparent);
  color: var(--color-state-warn);
}

.asociar-odf-senal.is-idle {
  background: color-mix(in srgb, var(--color-state-idle) 18%, transparent);
  color: var(--color-state-idle);
}

.asociar-odf-senal-spin {
  animation: asociar-odf-spin 1s linear infinite;
}

@keyframes asociar-odf-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.asociar-odf-notas {
  width: 100%;
  padding: 8px 12px;
  margin-bottom: 12px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  color: var(--text);
  font-family: inherit;
  resize: vertical;
}

.asociar-odf-actions {
  display: flex;
  gap: 10px;
}
</style>
