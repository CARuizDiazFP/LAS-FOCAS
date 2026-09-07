<!--
  Nombre de archivo: ServiciosBulkActionsPanel.vue
  Ubicación de archivo: web/frontend/src/components/servicios/ServiciosBulkActionsPanel.vue
  Descripción: Panel flotante de cambio de categoría masivo para el visor de Servicios — visible sólo con selección activa
-->
<template>
  <div class="bulk-panel" role="toolbar" aria-label="Acciones masivas de Servicios">
    <span class="bulk-panel__count">{{ count }} seleccionado{{ count !== 1 ? 's' : '' }}</span>

    <select
      class="bulk-panel__select"
      :value="modelValue"
      @change="$emit('update:modelValue', Number(($event.target as HTMLSelectElement).value))"
    >
      <option v-for="categoria in CATEGORIAS_SERVICIO" :key="categoria" :value="categoria">
        {{ categoriaLabel(categoria) }}
      </option>
    </select>

    <button class="btn primary" type="button" @click="$emit('apply')">Aplicar</button>
    <button class="btn subtle" type="button" @click="$emit('clear')">Deseleccionar todo</button>

    <span v-if="error" class="bulk-panel__error">{{ error }}</span>
  </div>
</template>

<script setup lang="ts">
import { CATEGORIAS_SERVICIO, categoriaLabel } from '../../api/servicios';

defineProps<{
  count: number;
  modelValue: number;
  error?: string;
}>();

defineEmits<{
  'update:modelValue': [value: number];
  apply: [];
  clear: [];
}>();
</script>

<style scoped>
.bulk-panel {
  position: fixed;
  left: 50%;
  bottom: 22px;
  transform: translateX(-50%);
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-size: 12.5px;
  color: var(--color-text);
  background: var(--color-surface);
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-divider), 0 10px 28px rgba(0, 0, 0, 0.45);
}

.bulk-panel__count {
  font-weight: 500;
  white-space: nowrap;
}

.bulk-panel__select {
  padding: 5px 8px;
  font-size: 12.5px;
  background: var(--color-surface-2, var(--color-surface));
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.bulk-panel__error {
  color: var(--color-state-error);
}

@media (max-width: 700px) {
  .bulk-panel {
    left: 12px;
    right: 12px;
    bottom: 12px;
    transform: none;
    flex-wrap: wrap;
  }
}
</style>
