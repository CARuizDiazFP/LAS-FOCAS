<!--
  Nombre de archivo: ModalMoverIngreso.vue
  Ubicación de archivo: web/frontend/src/components/servicios/ModalMoverIngreso.vue
  Descripción: Modal de admin para mover un ingreso técnico registrado en la Cámara equivocada a otra Cámara raíz (y opcionalmente a una Botella Cromo vigente)
-->
<template>
  <dialog
    ref="dialogEl"
    class="mover-modal"
    aria-labelledby="mover-ingreso-titulo"
    @click.self="handleClose"
    @cancel.prevent="handleClose"
  >
    <form class="modal-content" @submit.prevent="handleConfirmar">
      <div class="mover-title-row">
        <strong id="mover-ingreso-titulo">Mover ingreso #{{ ingreso?.id ?? '' }}</strong>
        <button class="close-btn" type="button" aria-label="Cerrar" :disabled="enviando" @click="handleClose">×</button>
      </div>

      <dl v-if="ingreso" class="mover-datos">
        <dt>Cámara actual</dt>
        <dd>{{ ingreso.camara_nombre ?? ingreso.camara_id ?? '—' }}</dd>
        <dt>Botella actual</dt>
        <dd>{{ ingreso.botella_label || '—' }}</dd>
        <dt>Técnico</dt>
        <dd>{{ ingreso.tecnico_id ?? '—' }}</dd>
        <dt>Ingreso</dt>
        <dd>{{ fechaLegible(ingreso.fecha_inicio) }}</dd>
        <dt>Egreso</dt>
        <dd>{{ ingreso.fecha_fin ? fechaLegible(ingreso.fecha_fin) : 'En curso' }}</dd>
      </dl>

      <template v-if="!resultado">
        <p class="mover-hint">
          Usalo cuando el ingreso <strong>existió</strong> pero quedó en la cámara equivocada. Las
          fechas no cambian (un ingreso en curso sigue en curso) y las intervenciones de FO Monitor
          abiertas se reubican en el destino.
        </p>

        <fieldset class="mover-campo" :disabled="enviando">
          <legend>Cámara destino</legend>
          <template v-if="!destino">
            <input
              ref="busquedaEl"
              v-model="query"
              type="text"
              class="mover-input"
              placeholder="Buscar cámara por nombre..."
              aria-label="Buscar cámara destino por nombre"
              autocomplete="off"
              @input="onSearchInput"
            />
            <div v-if="buscando" class="mover-vacio">Buscando...</div>
            <div v-else-if="errorBusqueda" class="mover-vacio is-error">{{ errorBusqueda }}</div>
            <div v-else-if="query.trim() && buscado && resultados.length === 0" class="mover-vacio">
              Ninguna cámara coincide con "{{ query.trim() }}".
            </div>
            <ul v-else-if="resultados.length" class="mover-resultados" aria-label="Cámaras encontradas">
              <li v-for="candidata in resultados" :key="candidata.id">
                <button class="mover-resultado" type="button" @click="elegirDestino(candidata)">
                  <strong>{{ candidata.nombre }}</strong>
                  <span class="mover-resultado__meta">
                    ID {{ candidata.id }} · {{ candidata.estado }} · {{ candidata.botellas_count }} botella{{ candidata.botellas_count !== 1 ? 's' : '' }}
                    <template v-if="candidata.id === ingreso?.camara_id"> · cámara actual</template>
                  </span>
                </button>
              </li>
            </ul>
          </template>

          <div v-else class="mover-destino">
            <div>
              <strong>{{ destino.nombre }}</strong>
              <span class="mover-resultado__meta">
                ID {{ destino.id }} · {{ destino.estado }}<template v-if="destino.id === ingreso?.camara_id"> · cámara actual</template>
              </span>
            </div>
            <button class="btn subtle mover-btn-chico" type="button" @click="cambiarDestino">Cambiar</button>
          </div>
        </fieldset>

        <label v-if="destino" class="mover-campo mover-campo--label">
          <span>Botella en el destino (opcional)</span>
          <select v-model="botellaNId" class="mover-input" :disabled="enviando || cargandoBotellas">
            <option :value="null">Sin botella</option>
            <option v-for="botella in botellas" :key="botella.id" :value="botella.id">
              {{ botella.nombre || `Botella #${botella.id}` }}{{ botella.estado ? ` · ${botella.estado}` : '' }}
            </option>
          </select>
          <span v-if="cargandoBotellas" class="mover-ayuda">Cargando botellas...</span>
          <span v-else-if="errorBotellas" class="mover-ayuda is-error">{{ errorBotellas }}</span>
          <span v-else-if="botellas.length === 0" class="mover-ayuda">Esta cámara no tiene botellas Cromo vigentes.</span>
          <span v-else class="mover-ayuda">Sólo botellas Cromo vigentes de la cámara destino.</span>
        </label>

        <p v-if="mismoDestino" class="mover-ayuda is-error" role="status">
          El ingreso ya está en esa cámara con esa botella: elegí otra cámara u otra botella.
        </p>

        <label class="mover-campo mover-campo--label">
          <span class="mover-campo__label">
            Motivo
            <span :class="['mover-contador', { 'is-invalido': motivoLen > 0 && !motivoValido }]" aria-live="polite">
              {{ motivoLen }}/{{ MOTIVO_CORRECCION_MAX }}
            </span>
          </span>
          <textarea
            v-model="motivo"
            class="mover-input"
            rows="3"
            :maxlength="MOTIVO_CORRECCION_MAX"
            required
            :disabled="enviando"
            placeholder="Ej.: Fontaine ID mal tipeado; el técnico confirmó que entró a otra cámara"
          />
          <span class="mover-ayuda">Entre {{ MOTIVO_CORRECCION_MIN }} y {{ MOTIVO_CORRECCION_MAX }} caracteres. Queda auditado con tu usuario.</span>
        </label>

        <div v-if="error" class="mover-error" role="alert">{{ error }}</div>

        <div class="mover-actions">
          <button class="btn primary" type="submit" :disabled="!puedeConfirmar">
            {{ enviando ? 'Moviendo...' : 'Mover ingreso' }}
          </button>
          <button class="btn subtle" type="button" :disabled="enviando" @click="handleClose">Cancelar</button>
        </div>
      </template>

      <template v-else>
        <p class="mover-ok" role="status">{{ resultado.mensaje }}</p>
        <div v-if="resultado.intervenciones_fomon_omitidas.length" class="mover-nota" role="note">
          <strong>FO Monitor</strong>
          <ul>
            <li v-for="omitida in resultado.intervenciones_fomon_omitidas" :key="omitida.intervencion_id">
              La intervención #{{ omitida.intervencion_id }} quedó en la cámara anterior: {{ textoOmision(omitida.motivo) }}
            </li>
          </ul>
        </div>
        <div class="mover-actions">
          <button class="btn subtle" type="button" @click="handleClose">Cerrar</button>
        </div>
      </template>
    </form>
  </dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';

import {
  type BotellaCromoHija,
  type CamaraCandidata,
  buscarCamarasRaiz,
  getBotellasCromoDeCamara,
} from '../../api/camaras';
import {
  type CorreccionIngresoResponse,
  type IngresoCorregible,
  MOTIVO_CORRECCION_MAX,
  MOTIVO_CORRECCION_MIN,
  moverIngreso,
} from '../../api/servicioSecciones';

const props = defineProps<{
  open: boolean;
  ingreso: IngresoCorregible | null;
}>();

const emit = defineEmits<{
  close: [];
  movido: [respuesta: CorreccionIngresoResponse];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const busquedaEl = ref<HTMLInputElement | null>(null);

const query = ref('');
const resultados = ref<CamaraCandidata[]>([]);
const buscando = ref(false);
const buscado = ref(false);
const errorBusqueda = ref('');
const destino = ref<CamaraCandidata | null>(null);

const botellas = ref<BotellaCromoHija[]>([]);
const botellaNId = ref<number | null>(null);
const cargandoBotellas = ref(false);
const errorBotellas = ref('');

const motivo = ref('');
const enviando = ref(false);
const error = ref('');
const resultado = ref<CorreccionIngresoResponse | null>(null);

let debounceTimer: ReturnType<typeof setTimeout> | null = null;
let busquedaCtrl: AbortController | null = null;
let botellasCtrl: AbortController | null = null;

const motivoLen = computed(() => motivo.value.trim().length);
const motivoValido = computed(
  () => motivoLen.value >= MOTIVO_CORRECCION_MIN && motivoLen.value <= MOTIVO_CORRECCION_MAX,
);
/** Espejo de `MISMO_DESTINO` del backend: misma cámara y misma botella (incluido "sin botella"). */
const mismoDestino = computed(
  () =>
    destino.value !== null &&
    props.ingreso !== null &&
    destino.value.id === props.ingreso.camara_id &&
    botellaNId.value === props.ingreso.cromo_botella_id,
);
const puedeConfirmar = computed(
  () =>
    !enviando.value &&
    !cargandoBotellas.value &&
    props.ingreso !== null &&
    destino.value !== null &&
    !mismoDestino.value &&
    motivoValido.value,
);

function fechaLegible(valor: string | null): string {
  if (!valor) return '—';
  const parsed = new Date(valor);
  return Number.isNaN(parsed.getTime()) ? valor : parsed.toLocaleString('es-AR');
}

function textoOmision(motivoOmision: string): string {
  if (motivoOmision === 'OTROS_INGRESOS_VIGENTES') {
    return 'tiene otros ingresos vigentes en otra cámara (moviéndolos también se reubica).';
  }
  if (motivoOmision === 'CONSULTAS_YA_ENVIADAS') {
    return 'ya había enviado consultas con el alcance anterior.';
  }
  return `no se reubicó (${motivoOmision}).`;
}

function cancelarPendientes(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = null;
  busquedaCtrl?.abort();
  busquedaCtrl = null;
  botellasCtrl?.abort();
  botellasCtrl = null;
}

function onSearchInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => void buscar(), 300);
}

async function buscar(): Promise<void> {
  const texto = query.value.trim();
  busquedaCtrl?.abort();
  if (!texto) {
    resultados.value = [];
    buscado.value = false;
    buscando.value = false;
    errorBusqueda.value = '';
    return;
  }
  const ctrl = new AbortController();
  busquedaCtrl = ctrl;
  buscando.value = true;
  errorBusqueda.value = '';
  try {
    // Sin `excluir_id` a propósito: mover dentro de la misma cámara a otra botella es válido; el
    // caso "misma cámara y misma botella" lo frena `mismoDestino` (y el backend con 409).
    resultados.value = await buscarCamarasRaiz(texto, { limit: 10, signal: ctrl.signal });
    buscado.value = true;
  } catch (err: unknown) {
    if (ctrl.signal.aborted) return;
    resultados.value = [];
    errorBusqueda.value = err instanceof Error ? err.message : 'No se pudo buscar cámaras.';
  } finally {
    if (busquedaCtrl === ctrl) {
      buscando.value = false;
      busquedaCtrl = null;
    }
  }
}

async function elegirDestino(candidata: CamaraCandidata): Promise<void> {
  destino.value = candidata;
  botellaNId.value = null;
  botellas.value = [];
  errorBotellas.value = '';
  botellasCtrl?.abort();
  const ctrl = new AbortController();
  botellasCtrl = ctrl;
  cargandoBotellas.value = true;
  try {
    botellas.value = await getBotellasCromoDeCamara(candidata.id, ctrl.signal);
  } catch (err: unknown) {
    if (ctrl.signal.aborted) return;
    errorBotellas.value = err instanceof Error ? err.message : 'No se pudieron cargar las botellas.';
  } finally {
    if (botellasCtrl === ctrl) {
      cargandoBotellas.value = false;
      botellasCtrl = null;
    }
  }
}

async function cambiarDestino(): Promise<void> {
  botellasCtrl?.abort();
  botellasCtrl = null;
  cargandoBotellas.value = false;
  destino.value = null;
  botellas.value = [];
  botellaNId.value = null;
  errorBotellas.value = '';
  await nextTick();
  busquedaEl.value?.focus();
}

function resetState(): void {
  cancelarPendientes();
  query.value = '';
  resultados.value = [];
  buscando.value = false;
  buscado.value = false;
  errorBusqueda.value = '';
  destino.value = null;
  botellas.value = [];
  botellaNId.value = null;
  cargandoBotellas.value = false;
  errorBotellas.value = '';
  motivo.value = '';
  enviando.value = false;
  error.value = '';
  resultado.value = null;
}

/** Escape (evento `cancel`) y clic en el fondo pasan por acá: mientras se envía, no se cierra. */
function handleClose(): void {
  if (enviando.value) return;
  cancelarPendientes();
  dialogEl.value?.close();
  emit('close');
}

async function handleConfirmar(): Promise<void> {
  if (!props.ingreso || !destino.value || !puedeConfirmar.value) return;
  enviando.value = true;
  error.value = '';
  try {
    const respuesta = await moverIngreso(props.ingreso.id, destino.value.id, botellaNId.value, motivo.value.trim());
    emit('movido', respuesta);
    if (respuesta.intervenciones_fomon_omitidas.length) {
      // Queda abierto para que el admin lea la nota de FO Monitor; la lista ya se recarga detrás.
      resultado.value = respuesta;
      return;
    }
    enviando.value = false;
    handleClose();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo mover el ingreso.';
  } finally {
    enviando.value = false;
  }
}

watch(
  () => props.open,
  async (isOpen) => {
    if (isOpen) {
      resetState();
      dialogEl.value?.showModal();
      await nextTick();
      busquedaEl.value?.focus();
      return;
    }
    cancelarPendientes();
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
);

onBeforeUnmount(cancelarPendientes);
</script>

<style scoped>
.mover-modal {
  width: min(540px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

/* Scrim derivado del token de fondo (sin rgba literal). */
.mover-modal::backdrop {
  background: color-mix(in srgb, var(--color-bg) 82%, transparent);
  backdrop-filter: blur(8px);
}

.modal-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--color-text);
  box-shadow: var(--shadow-lg);
}

.mover-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.close-btn {
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 1.4rem;
  line-height: 1;
}

.close-btn:hover:not(:disabled) {
  color: var(--color-text);
}

.close-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.mover-datos {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 14px;
  margin: 0;
  font-size: 0.85rem;
}

.mover-datos dt {
  color: var(--muted);
}

.mover-datos dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.mover-hint {
  margin: 0;
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--muted);
}

.mover-campo {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  border: none;
  min-width: 0;
  font-size: 0.8rem;
  color: var(--muted);
}

.mover-campo legend {
  padding: 0;
  margin-bottom: 6px;
}

.mover-campo__label {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.mover-contador {
  font-variant-numeric: tabular-nums;
}

.mover-contador.is-invalido {
  color: var(--error);
}

.mover-input {
  font: inherit;
  font-size: 0.88rem;
  color: var(--color-text);
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  border-radius: 10px;
  padding: 8px 10px;
  color-scheme: dark;
}

textarea.mover-input {
  resize: vertical;
}

.mover-input:focus {
  outline: none;
  border-color: var(--color-accent);
}

.mover-ayuda {
  margin: 0;
  font-size: 0.74rem;
  color: var(--muted);
}

.mover-ayuda.is-error {
  color: var(--error);
}

.mover-vacio {
  padding: 12px;
  border-radius: 10px;
  border: 1px dashed var(--color-divider);
  font-size: 0.82rem;
  text-align: center;
}

.mover-vacio.is-error {
  border-color: color-mix(in srgb, var(--error) 40%, transparent);
  color: var(--error);
}

.mover-resultados {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 220px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mover-resultado {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 9px 12px;
  border-radius: 10px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  color: var(--color-text);
  font: inherit;
  font-size: 0.85rem;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease;
}

.mover-resultado:hover,
.mover-resultado:focus-visible {
  outline: none;
  border-color: var(--color-accent);
}

.mover-resultado__meta {
  display: block;
  font-size: 0.74rem;
  color: var(--muted);
}

.mover-destino {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--color-brand-primary-tint);
  border: 1px solid color-mix(in srgb, var(--color-accent) 40%, transparent);
  color: var(--color-text);
  font-size: 0.85rem;
}

.mover-btn-chico {
  padding: 3px 10px;
  font-size: 0.78rem;
}

.mover-error {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--error) 40%, transparent);
  color: var(--error);
  font-size: 0.85rem;
}

.mover-ok {
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--success) 40%, transparent);
  color: var(--success);
  font-size: 0.85rem;
}

.mover-nota {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--warning) 40%, transparent);
  background: color-mix(in srgb, var(--warning) 8%, transparent);
  font-size: 0.82rem;
  line-height: 1.5;
}

.mover-nota strong {
  color: var(--warning);
}

.mover-nota ul {
  margin: 6px 0 0;
  padding-left: 18px;
}

.mover-actions {
  display: flex;
  gap: 10px;
}
</style>
