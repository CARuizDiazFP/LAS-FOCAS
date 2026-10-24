<!--
  Nombre de archivo: ModalAnularIngreso.vue
  Ubicación de archivo: web/frontend/src/components/servicios/ModalAnularIngreso.vue
  Descripción: Modal de admin para anular (baja lógica auditada) un ingreso técnico que nunca ocurrió
-->
<template>
  <dialog
    ref="dialogEl"
    class="anular-modal"
    aria-labelledby="anular-ingreso-titulo"
    @click.self="handleClose"
    @cancel.prevent="handleClose"
  >
    <form class="modal-content" @submit.prevent="handleConfirmar">
      <div class="anular-title-row">
        <strong id="anular-ingreso-titulo">Anular ingreso #{{ ingreso?.id ?? '' }}</strong>
        <button class="close-btn" type="button" aria-label="Cerrar" :disabled="enviando" @click="handleClose">×</button>
      </div>

      <dl v-if="ingreso" class="anular-datos">
        <dt>Cámara</dt>
        <dd>{{ ingreso.camara_nombre ?? ingreso.camara_id ?? '—' }}</dd>
        <dt>Botella</dt>
        <dd>{{ ingreso.botella_label || '—' }}</dd>
        <dt>Técnico</dt>
        <dd>{{ ingreso.tecnico_id ?? '—' }}</dd>
        <dt>Ingreso</dt>
        <dd>{{ fechaLegible(ingreso.fecha_inicio) }}</dd>
        <dt>Egreso</dt>
        <dd>{{ ingreso.fecha_fin ? fechaLegible(ingreso.fecha_fin) : 'En curso' }}</dd>
        <dt>Tipo</dt>
        <dd>{{ ingreso.tipo }}</dd>
      </dl>

      <template v-if="!resultado">
        <p class="anular-hint">
          Usalo cuando el ingreso <strong>nunca ocurrió</strong>. Deja de contar para el estado de la
          cámara y de listarse (sigue visible para un admin con "Mostrar anulados"). Las
          intervenciones de FO Monitor vinculadas que sigan abiertas se cancelan. No se puede
          deshacer desde el portal.
        </p>

        <label class="anular-campo">
          <span class="anular-campo__label">
            Motivo
            <span :class="['anular-contador', { 'is-invalido': motivoLen > 0 && !motivoValido }]" aria-live="polite">
              {{ motivoLen }}/{{ MOTIVO_CORRECCION_MAX }}
            </span>
          </span>
          <textarea
            ref="motivoEl"
            v-model="motivo"
            rows="3"
            :maxlength="MOTIVO_CORRECCION_MAX"
            required
            :disabled="enviando"
            placeholder="Ej.: Fontaine ID mal tipeado; el técnico nunca entró a esta cámara"
          />
          <span class="anular-campo__ayuda">Entre {{ MOTIVO_CORRECCION_MIN }} y {{ MOTIVO_CORRECCION_MAX }} caracteres. Queda auditado con tu usuario.</span>
        </label>

        <div v-if="error" class="anular-error" role="alert">{{ error }}</div>

        <div class="anular-actions">
          <button class="btn danger" type="submit" :disabled="!puedeConfirmar">
            {{ enviando ? 'Anulando...' : 'Anular ingreso' }}
          </button>
          <button class="btn subtle" type="button" :disabled="enviando" @click="handleClose">Cancelar</button>
        </div>
      </template>

      <template v-else>
        <p class="anular-ok" role="status">{{ resultado.mensaje }}</p>
        <div v-if="resultado.intervenciones_fomon_omitidas.length" class="anular-nota" role="note">
          <strong>FO Monitor</strong>
          <ul>
            <li v-for="omitida in resultado.intervenciones_fomon_omitidas" :key="omitida.intervencion_id">
              La intervención #{{ omitida.intervencion_id }} sigue abierta: {{ textoOmision(omitida.motivo) }}
            </li>
          </ul>
        </div>
        <div class="anular-actions">
          <button class="btn subtle" type="button" @click="handleClose">Cerrar</button>
        </div>
      </template>
    </form>
  </dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';

import {
  type CorreccionIngresoResponse,
  type IngresoCorregible,
  MOTIVO_CORRECCION_MAX,
  MOTIVO_CORRECCION_MIN,
  anularIngreso,
} from '../../api/servicioSecciones';

const props = defineProps<{
  open: boolean;
  ingreso: IngresoCorregible | null;
}>();

const emit = defineEmits<{
  close: [];
  anulado: [respuesta: CorreccionIngresoResponse];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const motivoEl = ref<HTMLTextAreaElement | null>(null);
const motivo = ref('');
const enviando = ref(false);
const error = ref('');
const resultado = ref<CorreccionIngresoResponse | null>(null);

const motivoLen = computed(() => motivo.value.trim().length);
const motivoValido = computed(
  () => motivoLen.value >= MOTIVO_CORRECCION_MIN && motivoLen.value <= MOTIVO_CORRECCION_MAX,
);
const puedeConfirmar = computed(() => !enviando.value && props.ingreso !== null && motivoValido.value);

function fechaLegible(valor: string | null): string {
  if (!valor) return '—';
  const parsed = new Date(valor);
  return Number.isNaN(parsed.getTime()) ? valor : parsed.toLocaleString('es-AR');
}

function textoOmision(motivoOmision: string): string {
  if (motivoOmision === 'OTROS_INGRESOS_VIGENTES') {
    return 'tiene otros ingresos vigentes, así que no se canceló.';
  }
  return `no se canceló (${motivoOmision}).`;
}

/** Escape (evento `cancel`) y clic en el fondo pasan por acá: mientras se envía, no se cierra. */
function handleClose(): void {
  if (enviando.value) return;
  dialogEl.value?.close();
  emit('close');
}

async function handleConfirmar(): Promise<void> {
  if (!props.ingreso || !puedeConfirmar.value) return;
  enviando.value = true;
  error.value = '';
  try {
    const respuesta = await anularIngreso(props.ingreso.id, motivo.value.trim());
    emit('anulado', respuesta);
    if (respuesta.intervenciones_fomon_omitidas.length) {
      // Queda abierto para que el admin lea la nota de FO Monitor; la lista ya se recarga detrás.
      resultado.value = respuesta;
      return;
    }
    enviando.value = false;
    handleClose();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo anular el ingreso.';
  } finally {
    enviando.value = false;
  }
}

watch(
  () => props.open,
  async (isOpen) => {
    if (isOpen) {
      motivo.value = '';
      error.value = '';
      resultado.value = null;
      enviando.value = false;
      dialogEl.value?.showModal();
      await nextTick();
      motivoEl.value?.focus();
      return;
    }
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
);
</script>

<style scoped>
.anular-modal {
  width: min(480px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

/* Scrim derivado del token de fondo (sin rgba literal). */
.anular-modal::backdrop {
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

.anular-title-row {
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

.anular-datos {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 14px;
  margin: 0;
  font-size: 0.85rem;
}

.anular-datos dt {
  color: var(--muted);
}

.anular-datos dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.anular-hint {
  margin: 0;
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--muted);
}

.anular-campo {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 0.8rem;
  color: var(--muted);
}

.anular-campo__label {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.anular-campo__ayuda {
  font-size: 0.74rem;
}

.anular-contador {
  font-variant-numeric: tabular-nums;
}

.anular-contador.is-invalido {
  color: var(--error);
}

.anular-campo textarea {
  font: inherit;
  font-size: 0.88rem;
  color: var(--color-text);
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  border-radius: 10px;
  padding: 8px 10px;
  color-scheme: dark;
  resize: vertical;
}

.anular-campo textarea:focus {
  outline: none;
  border-color: var(--color-accent);
}

.anular-error {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--error) 40%, transparent);
  color: var(--error);
  font-size: 0.85rem;
}

.anular-ok {
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--success) 40%, transparent);
  color: var(--success);
  font-size: 0.85rem;
}

.anular-nota {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--warning) 40%, transparent);
  background: color-mix(in srgb, var(--warning) 8%, transparent);
  font-size: 0.82rem;
  line-height: 1.5;
}

.anular-nota strong {
  color: var(--warning);
}

.anular-nota ul {
  margin: 6px 0 0;
  padding-left: 18px;
}

.anular-actions {
  display: flex;
  gap: 10px;
}
</style>
