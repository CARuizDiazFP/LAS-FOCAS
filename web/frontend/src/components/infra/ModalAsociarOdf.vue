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
            — {{ justificacionSugerencia }}
          </p>
          <button class="btn subtle" type="button" @click="usarSugerencia">Usar esta ODF</button>
        </div>
      </template>

      <div class="asociar-odf-hairline"></div>

      <template v-if="!odfSeleccionada">
        <input
          v-model="query"
          type="text"
          placeholder="Buscar ODF por nombre o dirección..."
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
import { computed, ref, watch } from 'vue';

import { buscarInventarioOdfs, type CromoOdfInventario } from '../../api/cromo';
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

async function buscar(): Promise<void> {
  if (!query.value.trim()) {
    resultadosOdf.value = [];
    return;
  }
  buscandoOdf.value = true;
  errorBusqueda.value = '';
  try {
    const respuesta = await buscarInventarioOdfs({ q: query.value.trim(), limit: 10 });
    resultadosOdf.value = respuesta.odfs;
  } catch (e: unknown) {
    errorBusqueda.value = e instanceof Error ? e.message : 'No se pudo buscar ODFs.';
  } finally {
    buscandoOdf.value = false;
  }
}

/** Sólo completa el buscador con el nombre sugerido y dispara la búsqueda — el operador sigue
 * teniendo que hacer click en el resultado para seleccionarlo. Nunca dispara el POST por su
 * cuenta: la asociación siempre pasa por `handleConfirmar`. */
function usarSugerencia(): void {
  if (!detalle.value?.sugerencia) return;
  query.value = detalle.value.sugerencia.nombre ?? `ODF ${detalle.value.sugerencia.odf_n_id}`;
  void buscar();
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
}

function handleClose(): void {
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
      void cargarDetalle();
      return;
    }
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
);
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
