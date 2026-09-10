<!--
  Nombre de archivo: CromoPeloSelector.vue
  Ubicación de archivo: web/frontend/src/components/infra/CromoPeloSelector.vue
  Descripción: Selector del pelo semilla con el que se resuelve el camino óptico de un Servicio
-->
<template>
  <!-- Con una sola semilla no hay nada que elegir: un <select> de un elemento es ruido, así que
       se informa cuál se va a usar en una oración. -->
  <p v-if="pelos.length === 1" class="cromo-pelo-selector__unico">
    Se resolverá desde el pelo
    <strong>{{ pelos[0].numero_pelo ?? pelos[0].pelo_n_id }}</strong>
    <span v-if="pelos[0].color"> ({{ pelos[0].color }})</span>
    <span v-if="pelos[0].cable_nombre"> del cable {{ pelos[0].cable_nombre }}</span>
    · n_id {{ pelos[0].pelo_n_id }}
  </p>

  <fieldset v-else-if="pelos.length > 1" class="cromo-pelo-selector">
    <legend class="cromo-pelo-selector__legend">
      {{ pelos.length }} pelos de Cromo para este Servicio — elegí desde cuál resolver
    </legend>
    <label
      v-for="pelo in pelos"
      :key="pelo.pelo_n_id"
      class="cromo-pelo-selector__opcion"
      :class="{ 'is-elegido': pelo.pelo_n_id === modelValue }"
    >
      <input
        type="radio"
        :name="`pelo-semilla-${pelos[0].pelo_n_id}`"
        :value="pelo.pelo_n_id"
        :checked="pelo.pelo_n_id === modelValue"
        :disabled="disabled"
        @change="$emit('update:modelValue', pelo.pelo_n_id)"
      />
      <span class="cromo-pelo-selector__cuerpo">
        <span class="cromo-pelo-selector__titulo">
          Pelo {{ pelo.numero_pelo ?? '—' }}
          <span v-if="pelo.color" class="cromo-pelo-selector__color">{{ pelo.color }}</span>
          <span v-if="pelo.cable_nombre" class="cromo-pelo-selector__cable">
            · {{ pelo.cable_nombre }}
          </span>
          <!-- Un pelo que ya tiene conector no aporta una ODF nueva: se marca para que el
               operador sepa que la información nueva está en los otros. -->
          <span v-if="pelo.tiene_conector_odf" class="cromo-pelo-selector__chip is-ok">
            ODF ya conocida
          </span>
        </span>
        <span class="cromo-pelo-selector__meta">
          n_id {{ pelo.pelo_n_id }}
          <template v-if="pelo.metodo"> · {{ pelo.metodo }}</template>
          <template v-if="pelo.confianza !== null"> · confianza {{ pelo.confianza }}</template>
        </span>
        <!-- `at.61` crudo: es el "por qué matcheó". Con el 96,6% de los pelos sin número
             extraído, ver el texto original es lo que le permite al operador evaluar la semilla. -->
        <span v-if="pelo.servicio_raw" class="cromo-pelo-selector__raw" :title="pelo.servicio_raw">
          {{ pelo.servicio_raw }}
        </span>
      </span>
    </label>
  </fieldset>
</template>

<script setup lang="ts">
import type { PeloSemilla } from '../../api/cromoPath';

defineProps<{
  pelos: PeloSemilla[];
  modelValue: number | null;
  disabled?: boolean;
}>();

defineEmits<{
  'update:modelValue': [pelo: number];
}>();
</script>

<style scoped>
.cromo-pelo-selector {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 8px 9px;
  border: 0;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-text) 4%, transparent);
}

.cromo-pelo-selector__legend {
  padding: 0 0 4px;
  font-size: 10px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.cromo-pelo-selector__unico {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  color: color-mix(in srgb, var(--color-text) 66%, transparent);
}

.cromo-pelo-selector__opcion {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 6px 7px;
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  cursor: pointer;
}

.cromo-pelo-selector__opcion.is-elegido {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
}

.cromo-pelo-selector__cuerpo {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.cromo-pelo-selector__titulo {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  font-size: 12.5px;
}

.cromo-pelo-selector__color,
.cromo-pelo-selector__cable {
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.cromo-pelo-selector__chip {
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  font-size: 9.5px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.cromo-pelo-selector__chip.is-ok {
  background: color-mix(in srgb, var(--color-state-ok) 18%, transparent);
  color: var(--color-state-ok);
}

.cromo-pelo-selector__meta {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.cromo-pelo-selector__raw {
  font-size: 10.5px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
