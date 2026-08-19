<!--
  Nombre de archivo: ModalFusionarGrupo.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalFusionarGrupo.vue
  Descripción: Modal para fusionar TODAS las Cámaras de un grupo de duplicados dentro de una única principal, elegida por el admin
-->
<template>
  <dialog ref="dialogEl" class="unificar-modal" @click.self="handleClose">
    <div class="modal-content">
      <div class="unificar-title-row">
        <strong>Fusionar grupo completo</strong>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </div>

      <p class="unificar-hint" v-if="grupo">
        Elegí qué Cámara conserva la identidad — absorberá todo lo heredable de las demás
        (Botellas, Cables, Empalmes, Ingresos, alias e historial), que se eliminarán físicamente.
      </p>

      <div v-if="grupo" class="unificar-confirmacion">
        <label
          v-for="miembro in grupo.miembros"
          :key="miembro.id"
          class="fusionar-grupo-opcion"
          :class="{ 'is-selected': principalId === miembro.id }"
        >
          <input v-model.number="principalId" type="radio" :value="miembro.id" name="principal-grupo" />
          <div class="fusionar-grupo-opcion__info">
            <strong>{{ miembro.nombre }}</strong>
            <span class="unificar-result-meta">
              ID {{ miembro.id }} · {{ miembro.estado }} · {{ miembro.botellas_count }} botella{{ miembro.botellas_count !== 1 ? 's' : '' }} · {{ miembro.cables_count }} cable{{ miembro.cables_count !== 1 ? 's' : '' }}
            </span>
          </div>
          <span v-if="principalId === miembro.id" class="unificar-badge principal">Principal</span>
        </label>

        <label class="unificar-checkbox">
          <input v-model="guardarAlias" type="checkbox" />
          Guardar los nombres de las demás como alias de la principal
        </label>
      </div>

      <div v-if="error" class="unificar-empty error">{{ error }}</div>

      <div class="unificar-actions">
        <button class="btn primary" type="button" :disabled="confirmando || principalId == null" @click="handleConfirmar">
          {{ confirmando ? 'Fusionando...' : 'Confirmar fusión' }}
        </button>
        <button class="btn subtle" type="button" :disabled="confirmando" @click="handleClose">Cancelar</button>
      </div>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

import { useSession } from '../../composables/useSession';
import type { GrupoCamarasDuplicadas } from '../../api/camaras';

const props = defineProps<{
  open: boolean;
  grupo: GrupoCamarasDuplicadas | null;
}>();

const emit = defineEmits<{
  close: [];
  merged: [];
  error: [message: string];
}>();

const { csrf } = useSession();
const dialogEl = ref<HTMLDialogElement | null>(null);
const principalId = ref<number | null>(null);
const guardarAlias = ref(true);
const confirmando = ref(false);
const error = ref('');

function sugerirPrincipalId(grupo: GrupoCamarasDuplicadas): number {
  return [...grupo.miembros].sort((a, b) => {
    const pesoA = a.botellas_count + a.cables_count;
    const pesoB = b.botellas_count + b.cables_count;
    if (pesoB !== pesoA) return pesoB - pesoA;
    return a.id - b.id;
  })[0].id;
}

function resetState(): void {
  principalId.value = props.grupo ? sugerirPrincipalId(props.grupo) : null;
  guardarAlias.value = true;
  error.value = '';
}

function handleClose(): void {
  dialogEl.value?.close();
  resetState();
  emit('close');
}

async function handleConfirmar(): Promise<void> {
  if (!props.grupo || principalId.value == null) return;
  confirmando.value = true;
  error.value = '';
  try {
    const secundarias = props.grupo.miembros.filter((m) => m.id !== principalId.value).map((m) => m.id);
    const res = await fetch('/api/infra/camaras/merge-grupo', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        camara_principal_id: principalId.value,
        camara_secundaria_ids: secundarias,
        guardar_alias: guardarAlias.value,
        csrf_token: csrf(),
      }),
    });
    const data = await res.json() as { error?: string; ok?: boolean };
    if (!res.ok || !data.ok) throw new Error(data.error ?? 'No se pudo fusionar el grupo de Cámaras.');
    emit('merged');
    handleClose();
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : 'No se pudo fusionar el grupo de Cámaras.';
    error.value = message;
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
      return;
    }
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
);
</script>

<style scoped>
.unificar-modal {
  width: min(560px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.unificar-modal::backdrop {
  background: rgba(4, 8, 14, 0.74);
  backdrop-filter: blur(8px);
}

.modal-content {
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--text);
  box-shadow: var(--shadow-lg);
}

.unificar-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.unificar-hint {
  font-size: 0.85rem;
  color: var(--muted);
  line-height: 1.5;
  margin: 0 0 14px;
}

.unificar-empty {
  padding: 14px;
  border-radius: 10px;
  border: 1px dashed var(--color-divider);
  color: var(--muted);
  font-size: 0.85rem;
  text-align: center;
}

.unificar-empty.error {
  border-color: color-mix(in srgb, var(--error) 40%, transparent);
  color: var(--error);
}

.unificar-result-meta {
  font-size: 0.75rem;
  color: var(--muted);
}

.unificar-confirmacion {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
}

.unificar-badge {
  display: inline-flex;
  align-self: flex-start;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.68rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.unificar-badge.principal {
  background: color-mix(in srgb, var(--success) 18%, transparent);
  color: var(--success);
}

.unificar-actions {
  display: flex;
  gap: 10px;
}

.unificar-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  color: var(--text);
  cursor: pointer;
}

.fusionar-grupo-opcion {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  cursor: pointer;
  transition: border-color 0.15s ease;
}

.fusionar-grupo-opcion:hover {
  border-color: var(--color-accent);
}

.fusionar-grupo-opcion.is-selected {
  border-color: var(--success);
}

.fusionar-grupo-opcion__info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}
</style>
