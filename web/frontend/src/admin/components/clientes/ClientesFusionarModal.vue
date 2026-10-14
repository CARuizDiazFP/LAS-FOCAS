<!--
  Nombre de archivo: ClientesFusionarModal.vue
  Ubicación de archivo: web/frontend/src/admin/components/clientes/ClientesFusionarModal.vue
  Descripción: Modal para fusionar clientes seleccionados en uno destino (sus alias pasan al destino)
-->
<template>
  <dialog ref="dialogEl" class="clientes-modal" @click.self="handleClose">
    <div class="clientes-modal__content">
      <div class="clientes-modal__title-row">
        <strong>Fusionar clientes</strong>
        <button class="clientes-modal__close" type="button" aria-label="Cerrar" @click="handleClose">×</button>
      </div>

      <p class="clientes-modal__hint">
        Elegí el cliente que queda. Los demás se eliminan y todos sus alias pasan al destino. El destino conserva su
        categoría si la fijó un admin (Lista/Manual); si no, se recalcula con los servicios sumados.
      </p>

      <fieldset class="fusion-opciones" :disabled="fusionando || resultado !== null">
        <legend class="fusion-opciones__legend">Cliente destino</legend>
        <label v-for="cliente in clientes" :key="cliente.id" class="fusion-opciones__item">
          <input v-model="destinoId" type="radio" name="destino-fusion" :value="cliente.id" />
          <span class="fusion-opciones__nombre">{{ cliente.nombre }}</span>
          <span class="fusion-opciones__meta">
            {{ cliente.categoria === null ? 'Sin categorizar' : `C${cliente.categoria}` }} ·
            {{ etiquetaOrigen(cliente.origen_categoria) }} · {{ cliente.servicios }} servicio{{ cliente.servicios !== 1 ? 's' : '' }}
          </span>
        </label>
      </fieldset>

      <p v-if="resultado" class="clientes-modal__ok">{{ resultado }}</p>
      <p v-if="error" class="clientes-modal__error">{{ error }}</p>

      <div class="clientes-modal__actions">
        <button
          v-if="resultado === null"
          class="btn primary"
          type="button"
          :disabled="fusionando || destinoId === null || clientes.length < 2"
          @click="fusionar"
        >
          {{ fusionando ? 'Fusionando...' : `Fusionar ${clientes.length - 1} en el destino` }}
        </button>
        <button class="btn subtle" type="button" :disabled="fusionando" @click="handleClose">
          {{ resultado ? 'Cerrar' : 'Cancelar' }}
        </button>
      </div>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

import { etiquetaOrigen, fusionarClientes, type ClienteCategoria } from '../../api/clientesCategoria';

const props = defineProps<{
  open: boolean;
  clientes: ClienteCategoria[];
}>();

const emit = defineEmits<{
  close: [];
  /** La fusión se aplicó: el padre limpia la selección y recarga. */
  fusionado: [];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const destinoId = ref<number | null>(null);
const fusionando = ref(false);
const error = ref('');
const resultado = ref<string | null>(null);

function handleClose(): void {
  dialogEl.value?.close();
  emit('close');
}

async function fusionar(): Promise<void> {
  if (destinoId.value === null || fusionando.value) return;
  const destino = destinoId.value;
  const origenes = props.clientes.map((c) => c.id).filter((id) => id !== destino);
  if (origenes.length === 0) return;
  fusionando.value = true;
  error.value = '';
  try {
    const respuesta = await fusionarClientes(destino, origenes);
    resultado.value =
      `${respuesta.fusionados.length} cliente${respuesta.fusionados.length !== 1 ? 's' : ''} fusionado` +
      `${respuesta.fusionados.length !== 1 ? 's' : ''} · ${respuesta.alias_movidos} alias movido` +
      `${respuesta.alias_movidos !== 1 ? 's' : ''} · ${respuesta.sync.servicios_actualizados} servicio` +
      `${respuesta.sync.servicios_actualizados !== 1 ? 's' : ''} actualizado${respuesta.sync.servicios_actualizados !== 1 ? 's' : ''}.`;
    emit('fusionado');
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo fusionar los clientes.';
  } finally {
    fusionando.value = false;
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      // Por defecto, el que más servicios tiene: suele ser la grafía "buena".
      const masServicios = [...props.clientes].sort((a, b) => b.servicios - a.servicios)[0];
      destinoId.value = masServicios?.id ?? null;
      error.value = '';
      resultado.value = null;
      dialogEl.value?.showModal();
      return;
    }
    if (dialogEl.value?.open) dialogEl.value.close();
  },
);
</script>

<style scoped>
.clientes-modal {
  width: min(560px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.clientes-modal::backdrop {
  background: rgba(4, 8, 14, 0.74);
  backdrop-filter: blur(8px);
}

.clientes-modal__content {
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--color-text);
  box-shadow: var(--shadow-lg);
}

.clientes-modal__title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.clientes-modal__close {
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 1.4rem;
  line-height: 1;
}

.clientes-modal__close:hover {
  color: var(--color-text);
}

.clientes-modal__hint {
  margin: 0 0 14px;
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--muted);
}

.clientes-modal__error {
  margin: 0 0 12px;
  font-size: 0.85rem;
  color: var(--error);
}

.clientes-modal__ok {
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 0.85rem;
  background: color-mix(in srgb, var(--success) 14%, transparent);
  color: var(--success);
}

.clientes-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.fusion-opciones {
  margin: 0 0 14px;
  padding: 0;
  border: none;
  display: grid;
  gap: 6px;
  max-height: 320px;
  overflow-y: auto;
}

.fusion-opciones__legend {
  margin-bottom: 6px;
  font-size: 0.75rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.fusion-opciones__item {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 10px;
  row-gap: 2px;
  align-items: center;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-divider);
  background: var(--color-bg);
  cursor: pointer;
}

.fusion-opciones__item:has(input:checked) {
  border-color: var(--color-accent);
  background: var(--color-brand-primary-tint);
}

.fusion-opciones__nombre {
  font-size: 0.88rem;
  overflow-wrap: anywhere;
}

.fusion-opciones__meta {
  grid-column: 2;
  font-size: 0.75rem;
  color: var(--muted);
}
</style>
