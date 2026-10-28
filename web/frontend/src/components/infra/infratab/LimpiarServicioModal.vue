<!--
  Nombre de archivo: LimpiarServicioModal.vue
  Ubicación de archivo: web/frontend/src/components/infra/infratab/LimpiarServicioModal.vue
  Descripción: Modal de InfraTab para limpiar las asociaciones de empalmes y rutas de un servicio
-->
<template>
  <dialog ref="dialogEl" class="infra-generic-modal" @click.self="cerrar()" @cancel.prevent="cerrar()">
    <div class="modal-inner">
      <div class="modal-header-row">
        <h3 class="modal-title">🗑 Limpiar Servicio</h3>
        <button class="close-btn" @click="cerrar()">×</button>
      </div>
      <p class="modal-desc danger-text">⚠️ Operación destructiva e irreversible. Se eliminarán todas las asociaciones de empalmes y rutas del servicio.</p>
      <label class="form-label">ID del servicio <span class="req">*</span></label>
      <input v-model="limpiarServicioId" type="text" placeholder="Ej: 52547" />
      <div class="modal-actions">
        <button
          class="btn danger"
          :disabled="limpiarLoading || !limpiarServicioId.trim()"
          @click="submitLimpiar"
        >{{ limpiarLoading ? 'Limpiando...' : 'Limpiar servicio' }}</button>
        <button class="btn subtle" @click="cerrar()">Cancelar</button>
      </div>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { limpiarEmpalmesServicio } from '../../../api/infra';
import type { Notificar } from '../../../composables/infra/tipos';

const props = defineProps<{ notificar: Notificar }>();
const emit = defineEmits<{ 'servicio-limpiado': [] }>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const limpiarServicioId = ref('');
const limpiarLoading = ref(false);

function abrir() {
  limpiarServicioId.value = '';
  dialogEl.value?.showModal();
}

function cerrar() {
  dialogEl.value?.close();
}

async function submitLimpiar() {
  const svcId = limpiarServicioId.value.trim();
  if (!svcId) return;
  limpiarLoading.value = true;
  try {
    const data = await limpiarEmpalmesServicio(svcId);
    cerrar();
    props.notificar('success', 'Servicio limpiado', data.message ?? '');
    emit('servicio-limpiado');
  } catch (e: unknown) {
    props.notificar('error', 'Error al limpiar servicio', e instanceof Error ? e.message : String(e));
  } finally {
    limpiarLoading.value = false;
  }
}

defineExpose({ abrir });
</script>

<style scoped src="./infra-modal.css"></style>

<style scoped>
.modal-desc { margin: 0 0 6px; font-size: .83rem; color: var(--muted); }
.danger-text { color: var(--color-state-warn); }
</style>
