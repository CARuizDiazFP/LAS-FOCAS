<!--
  Nombre de archivo: CamaraEstadoModal.vue
  Ubicación de archivo: web/frontend/src/components/infra/CamaraEstadoModal.vue
  Descripción: Modal aislado para consulta y edición manual del estado operativo de una cámara
-->
<template>
  <dialog ref="dialogEl" class="camera-state-modal" @click.self="handleClose">
    <div class="modal-content">
      <div class="camera-state-title-row">
        <strong>{{ camaraNombre || `Cámara ${camaraId ?? ''}` }}</strong>
        <span v-if="contexto" :class="['camera-state-badge', contexto.inconsistente ? 'warning' : 'ok']">
          {{ contexto.inconsistente ? 'Inconsistente' : 'Alineada' }}
        </span>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </div>

      <div v-if="loading" class="camera-state-empty">Cargando contexto operativo...</div>
      <div v-else-if="errorMessage" class="camera-state-empty error">{{ errorMessage }}</div>
      <template v-else-if="contexto">
        <div class="camera-state-meta-row">
          <span>Actual: <strong>{{ contexto.estado_actual }}</strong></span>
          <span>Sugerido: <strong>{{ contexto.estado_sugerido || contexto.estado_actual }}</strong></span>
          <span>Baneo activo: <strong>{{ contexto.tiene_baneo_activo ? 'Sí' : 'No' }}</strong></span>
          <span>Ingreso activo: <strong>{{ contexto.tiene_ingreso_activo ? 'Sí' : 'No' }}</strong></span>
        </div>
        <div v-if="contexto.incidentes_activos.length" class="camera-state-incidents">
          <div class="camera-state-incidents-title">Incidentes activos vinculados</div>
          <div
            v-for="incidente in contexto.incidentes_activos"
            :key="incidente.id"
            class="camera-state-incident-item"
          >
            <strong>{{ incidente.ticket_asociado || `Incidente ${incidente.id}` }}</strong>
            <span>Servicio: {{ incidente.servicio_protegido_id || '-' }}</span>
            <span>Ruta: {{ incidente.ruta_protegida_id ?? '-' }}</span>
          </div>
        </div>
        <div v-else class="camera-state-empty">No hay incidentes activos vinculados.</div>

        <label class="form-label">Nuevo estado</label>
        <select v-model="newEstado" class="camera-state-select">
          <option v-for="estado in estadosDisponibles" :key="estado" :value="estado">{{ estado }}</option>
        </select>

        <label class="form-label">Motivo del cambio (mínimo 5 caracteres)</label>
        <input v-model="motivo" type="text" placeholder="Describí brevemente el motivo" />

        <div class="camera-state-actions">
          <button class="btn primary" type="button" :disabled="savingState" @click="saveCameraState">Guardar</button>
          <button class="btn subtle" type="button" :disabled="savingState" @click="handleClose">Cancelar</button>
        </div>
      </template>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { useSession } from '../../composables/useSession';

interface EstadoContextoItem {
  id: number;
  ticket_asociado: string | null;
  servicio_protegido_id: string;
  ruta_protegida_id: number | null;
}

interface EstadoContexto {
  estado_actual: string;
  estado_sugerido: string | null;
  tiene_baneo_activo: boolean;
  tiene_ingreso_activo: boolean;
  inconsistente: boolean;
  incidentes_activos: EstadoContextoItem[];
}

const props = defineProps<{
  open: boolean;
  camaraId: number | null;
  camaraNombre: string;
}>();

const emit = defineEmits<{
  close: [];
  updated: [];
  error: [message: string];
}>();

const { csrf } = useSession();
const dialogEl = ref<HTMLDialogElement | null>(null);
const contexto = ref<EstadoContexto | null>(null);
// Fallback si el fetch de /estado todavía no resolvió — vocabulario vigente desde 2026-08-11
// (LIBRE/OCUPADA/BANEADA/NO_OPERATIVA); se pisa siempre con `data.estados_disponibles` real abajo.
const estadosDisponibles = ref<string[]>(['LIBRE', 'OCUPADA', 'BANEADA', 'NO_OPERATIVA']);
const newEstado = ref('LIBRE');
const motivo = ref('');
const loading = ref(false);
const savingState = ref(false);
const errorMessage = ref('');

async function loadContexto(): Promise<void> {
  if (!props.camaraId) {
    return;
  }
  loading.value = true;
  errorMessage.value = '';
  try {
    const res = await fetch(`/api/infra/camaras/${props.camaraId}/estado`, { credentials: 'include' });
    const data = await res.json() as {
      error?: string;
      contexto?: EstadoContexto;
      estados_disponibles?: string[];
    };
    if (!res.ok) {
      throw new Error(data.error ?? `Error ${res.status}`);
    }
    contexto.value = data.contexto ?? null;
    estadosDisponibles.value = data.estados_disponibles?.length ? data.estados_disponibles : estadosDisponibles.value;
    newEstado.value = data.contexto?.estado_actual ?? 'LIBRE';
    motivo.value = '';
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error);
    emit('error', errorMessage.value);
  } finally {
    loading.value = false;
  }
}

function handleClose(): void {
  dialogEl.value?.close();
  contexto.value = null;
  motivo.value = '';
  errorMessage.value = '';
  emit('close');
}

async function saveCameraState(): Promise<void> {
  if (!props.camaraId) {
    return;
  }
  if (motivo.value.trim().length < 5) {
    errorMessage.value = 'Ingresá al menos 5 caracteres para auditar el cambio.';
    emit('error', errorMessage.value);
    return;
  }

  savingState.value = true;
  errorMessage.value = '';
  try {
    const res = await fetch(`/api/infra/camaras/${props.camaraId}/estado`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ estado: newEstado.value, motivo: motivo.value.trim(), csrf_token: csrf() }),
    });
    const data = await res.json() as { error?: string; success?: boolean };
    if (!res.ok || !data.success) {
      throw new Error(data.error ?? 'No se pudo guardar el estado');
    }
    emit('updated');
    handleClose();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error);
    emit('error', errorMessage.value);
  } finally {
    savingState.value = false;
  }
}

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) {
      if (dialogEl.value?.open) {
        dialogEl.value.close();
      }
      return;
    }
    dialogEl.value?.showModal();
    await loadContexto();
  },
);
</script>

<style scoped>
.camera-state-modal {
  width: min(760px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.camera-state-modal::backdrop {
  background: rgba(4, 8, 14, 0.78);
  backdrop-filter: blur(10px);
}

.modal-content {
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--text);
  box-shadow: var(--shadow-lg);
}

.camera-state-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.camera-state-title-row strong {
  font-size: 1.2rem;
  color: var(--color-text);
}

.close-btn {
  margin-left: auto;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 1.4rem;
  line-height: 1;
}

.close-btn:hover {
  color: var(--text);
}

.camera-state-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.camera-state-badge.ok {
  background: color-mix(in srgb, var(--success) 16%, transparent);
  color: var(--success);
}

.camera-state-badge.warning {
  background: color-mix(in srgb, var(--warning) 16%, transparent);
  color: var(--warning);
}

.camera-state-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.camera-state-meta-row span {
  border-radius: 999px;
  padding: 8px 12px;
  background: color-mix(in srgb, var(--color-neutral-400) 12%, transparent);
  color: var(--muted);
  font-size: 0.82rem;
}

.camera-state-incidents {
  margin-bottom: 18px;
  padding: 16px;
  border-radius: 14px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
}

.camera-state-incidents-title {
  margin-bottom: 10px;
  color: var(--color-accent);
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.camera-state-incident-item {
  display: grid;
  gap: 4px;
  padding: 10px 0;
}

.camera-state-incident-item + .camera-state-incident-item {
  border-top: 1px solid var(--color-divider);
}

.camera-state-incident-item strong {
  color: var(--color-text);
}

.camera-state-incident-item span {
  color: var(--muted);
  font-size: 0.82rem;
}

.camera-state-empty {
  margin-bottom: 16px;
  padding: 16px;
  border-radius: 14px;
  border: 1px dashed var(--color-divider);
  color: var(--muted);
  background: var(--color-bg);
}

.camera-state-select {
  width: 100%;
  margin: 8px 0 14px;
}

.camera-state-actions {
  display: flex;
  gap: 10px;
  margin-top: 18px;
}

.camera-state-actions .btn {
  min-width: 120px;
}

.error {
  color: var(--error);
}

@media (max-width: 720px) {
  .modal-content {
    padding: 20px;
  }

  .camera-state-actions {
    flex-direction: column;
  }

  .camera-state-actions .btn {
    width: 100%;
  }
}
</style>