<!--
  Nombre de archivo: ModalRegistrarEgreso.vue
  Ubicación de archivo: web/frontend/src/components/servicios/ModalRegistrarEgreso.vue
  Descripción: Modal para registrar desde el panel el egreso de un ingreso técnico que quedó "en curso" (el formulario de Egreso nunca llegó por Slack)
-->
<template>
  <dialog ref="dialogEl" class="egreso-modal" @click.self="handleClose">
    <form class="modal-content" @submit.prevent="handleConfirmar">
      <div class="egreso-title-row">
        <strong>Registrar egreso</strong>
        <button class="close-btn" type="button" aria-label="Cerrar" @click="handleClose">×</button>
      </div>

      <dl v-if="ingreso" class="egreso-datos">
        <dt>Cámara</dt>
        <dd>{{ ingreso.camara_nombre ?? ingreso.camara_id }}</dd>
        <dt>Botella</dt>
        <dd>{{ ingreso.botella_label || '—' }}</dd>
        <dt>Técnico</dt>
        <dd>{{ ingreso.tecnico_id ?? '—' }}</dd>
        <dt>Ingreso</dt>
        <dd>{{ fechaLegible(ingreso.fecha_inicio) }}</dd>
      </dl>

      <label class="egreso-campo">
        <span>Fecha y hora de egreso</span>
        <input v-model="momento" type="datetime-local" :min="minimo" :max="maximo" required />
      </label>

      <label class="egreso-campo">
        <span>Motivo</span>
        <textarea
          v-model="motivo"
          rows="2"
          maxlength="500"
          required
          placeholder="Ej.: el formulario de egreso no llegó por Slack; confirmado con el técnico"
        />
      </label>

      <p class="egreso-hint">
        Se cierra exactamente este ingreso y queda auditado con tu usuario, igual que el comando de
        Slack "Forzar egreso".
      </p>

      <div v-if="error" class="egreso-error">{{ error }}</div>

      <div class="egreso-actions">
        <button class="btn primary" type="submit" :disabled="!puedeConfirmar">
          {{ enviando ? 'Registrando...' : 'Registrar egreso' }}
        </button>
        <button class="btn subtle" type="button" :disabled="enviando" @click="handleClose">Cancelar</button>
      </div>
    </form>
  </dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import { type InfraServicioIngreso, registrarEgresoIngreso } from '../../api/servicioSecciones';

const props = defineProps<{
  open: boolean;
  ingreso: InfraServicioIngreso | null;
}>();

const emit = defineEmits<{
  close: [];
  registrado: [];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const momento = ref('');
const motivo = ref('');
const enviando = ref(false);
const error = ref('');

/** `Date` → valor de `<input type="datetime-local">` (hora local, sin zona, a minutos). */
function aInputLocal(fecha: Date): string {
  const local = new Date(fecha.getTime() - fecha.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function fechaLegible(valor: string | null): string {
  if (!valor) return '—';
  const parsed = new Date(valor);
  return Number.isNaN(parsed.getTime()) ? valor : parsed.toLocaleString('es-AR');
}

const minimo = computed(() =>
  props.ingreso?.fecha_inicio ? aInputLocal(new Date(props.ingreso.fecha_inicio)) : undefined,
);
const maximo = ref(aInputLocal(new Date()));

const puedeConfirmar = computed(
  () => !enviando.value && momento.value !== '' && motivo.value.trim().length >= 3,
);

function handleClose(): void {
  dialogEl.value?.close();
  emit('close');
}

async function handleConfirmar(): Promise<void> {
  if (!props.ingreso || !puedeConfirmar.value) return;
  // `datetime-local` no trae zona: `new Date(valor)` lo interpreta como hora local del navegador y
  // `toISOString()` lo manda en UTC — el backend rechaza cualquier fecha sin zona horaria.
  const elegido = new Date(momento.value);
  if (Number.isNaN(elegido.getTime())) {
    error.value = 'Fecha inválida.';
    return;
  }
  enviando.value = true;
  error.value = '';
  try {
    await registrarEgresoIngreso(props.ingreso.id, elegido.toISOString(), motivo.value.trim());
    emit('registrado');
    handleClose();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo registrar el egreso.';
  } finally {
    enviando.value = false;
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      const ahora = new Date();
      maximo.value = aInputLocal(ahora);
      momento.value = aInputLocal(ahora);
      motivo.value = '';
      error.value = '';
      dialogEl.value?.showModal();
      return;
    }
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
);
</script>

<style scoped>
.egreso-modal {
  width: min(480px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.egreso-modal::backdrop {
  background: rgba(4, 8, 14, 0.74);
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

.egreso-title-row {
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

.close-btn:hover {
  color: var(--color-text);
}

.egreso-datos {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 14px;
  margin: 0;
  font-size: 0.85rem;
}

.egreso-datos dt {
  color: var(--muted);
}

.egreso-datos dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.egreso-campo {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 0.8rem;
  color: var(--muted);
}

.egreso-campo input,
.egreso-campo textarea {
  font: inherit;
  font-size: 0.88rem;
  color: var(--color-text);
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  border-radius: 10px;
  padding: 8px 10px;
  color-scheme: dark;
}

.egreso-campo textarea {
  resize: vertical;
}

.egreso-campo input:focus,
.egreso-campo textarea:focus {
  outline: none;
  border-color: var(--color-accent);
}

.egreso-hint {
  margin: 0;
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--muted);
}

.egreso-error {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--error) 40%, transparent);
  color: var(--error);
  font-size: 0.85rem;
}

.egreso-actions {
  display: flex;
  gap: 10px;
}
</style>
