<!--
  Nombre de archivo: ServiceTimeline.vue
  Ubicación de archivo: web/frontend/src/components/servicios/ServiceTimeline.vue
  Descripción: Línea de tiempo HORIZONTAL y colapsada de un Servicio — muestra los hitos en una
  tira que cabe en una tarjeta; el histórico completo vive en su propia vista
-->
<template>
  <div v-if="events.length > 0" class="tl">
    <ol class="tl__pista" :aria-label="`Histórico del Servicio, ${events.length} hitos`">
      <li
        v-for="(event, indice) in visibles"
        :key="event.id"
        class="tl__hito"
        :class="{ 'is-ultimo': indice === visibles.length - 1 }"
      >
        <span class="tl__linea" aria-hidden="true"></span>
        <span
          class="tl__punto"
          :class="event.estado ? estadoClase(event.estado) : 'is-idle'"
          aria-hidden="true"
        ></span>
        <span class="tl__cuerpo">
          <span class="tl__titulo" :title="event.titulo">{{ event.titulo }}</span>
          <span v-if="event.fecha" class="tl__fecha">{{ formatearFechaCorta(event.fecha) }}</span>
          <span
            v-if="event.estado"
            class="tl__chip"
            :class="estadoClase(event.estado)"
            :title="event.descripcion || event.estado"
          >
            {{ event.estado }}
          </span>
        </span>
      </li>
    </ol>

    <!-- Colapsada a propósito: la tarjeta muestra los últimos hitos y el resto se ve entero en la
         vista dedicada, que es linkeable y no compite por espacio con el resto de la ficha. -->
    <p v-if="ocultos > 0" class="tl__resto">
      + {{ ocultos }} hito{{ ocultos === 1 ? '' : 's' }} anterior{{ ocultos === 1 ? '' : 'es' }}
    </p>
  </div>
  <p v-else class="tl__empty">Sin eventos para mostrar.</p>
</template>

<script setup lang="ts">
import { computed } from 'vue';

import type { TimelineEvent } from '../../types/timeline';
import { estadoClase, formatearFechaCorta } from './timelineFormato';

const props = withDefaults(
  defineProps<{
    events: TimelineEvent[];
    /** Cuántos hitos entran en la tira antes de colapsar el resto. */
    maximo?: number;
  }>(),
  { maximo: 4 },
);

/** Se muestran los ÚLTIMOS hitos: el estado actual del Servicio es lo que se consulta a diario. */
const visibles = computed(() =>
  props.events.length > props.maximo ? props.events.slice(-props.maximo) : props.events,
);

const ocultos = computed(() => Math.max(0, props.events.length - visibles.value.length));
</script>

<style scoped>
.tl {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.tl__pista {
  list-style: none;
  display: flex;
  align-items: flex-start;
  gap: 0;
  margin: 0;
  padding: 2px 0 0;
  overflow-x: auto;
  scrollbar-width: thin;
}

.tl__hito {
  position: relative;
  flex: 1 1 0;
  min-width: 92px;
  padding-right: 8px;
}

.tl__linea {
  position: absolute;
  top: 5px;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--color-divider);
}

.tl__hito.is-ultimo .tl__linea {
  right: calc(100% - 12px);
}

.tl__punto {
  position: relative;
  display: block;
  width: 12px;
  height: 12px;
  border-radius: var(--radius-pill);
  box-shadow: 0 0 0 3px var(--color-surface);
}

.tl__punto.is-ok {
  background: var(--color-state-ok);
}

.tl__punto.is-error {
  background: var(--color-state-error);
}

.tl__punto.is-idle {
  background: var(--color-state-idle);
}

.tl__cuerpo {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-top: 6px;
  min-width: 0;
}

.tl__titulo {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tl__fecha {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.tl__chip {
  align-self: flex-start;
  margin-top: 1px;
  padding: 0 6px;
  border-radius: var(--radius-pill);
  font-size: 9.5px;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  white-space: nowrap;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tl__chip.is-ok {
  background: color-mix(in srgb, var(--color-state-ok) 18%, transparent);
  color: var(--color-state-ok);
}

.tl__chip.is-error {
  background: color-mix(in srgb, var(--color-state-error) 18%, transparent);
  color: var(--color-state-error);
}

.tl__chip.is-idle {
  background: color-mix(in srgb, var(--color-text) 10%, transparent);
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
}

.tl__resto,
.tl__empty {
  margin: 0;
  font-size: 11px;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}
</style>
