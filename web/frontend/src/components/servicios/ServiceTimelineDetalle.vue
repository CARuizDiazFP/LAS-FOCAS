<!--
  Nombre de archivo: ServiceTimelineDetalle.vue
  Ubicación de archivo: web/frontend/src/components/servicios/ServiceTimelineDetalle.vue
  Descripción: Histórico completo de un Servicio en vertical — el render extenso, que ahora vive en
  su propia vista en vez de ocupar la ficha del Servicio
-->
<template>
  <ol v-if="events.length > 0" class="service-timeline">
    <li v-for="event in events" :key="event.id" class="service-timeline__item">
      <div class="service-timeline__marker" aria-hidden="true"></div>
      <div class="service-timeline__body">
        <div class="service-timeline__headline">
          <strong>{{ event.titulo }}</strong>
          <span v-if="event.estado" :class="['service-timeline__chip', estadoClase(event.estado)]">
            {{ event.estado }}
          </span>
        </div>
        <span v-if="event.fecha" class="service-timeline__fecha">{{ formatearFecha(event.fecha) }}</span>
        <p v-if="event.descripcion" class="service-timeline__descripcion">{{ event.descripcion }}</p>
      </div>
    </li>
  </ol>
  <p v-else class="service-timeline__empty">Sin eventos para mostrar.</p>
</template>

<script setup lang="ts">
import type { TimelineEvent } from '../../types/timeline';
import { estadoClase, formatearFecha } from './timelineFormato';

defineProps<{
  events: TimelineEvent[];
}>();
</script>

<style scoped>
.service-timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}

.service-timeline__item {
  display: grid;
  gap: 4px;
  padding: 10px 0 10px 16px;
  margin-left: 5px;
  border-left: 2px solid var(--color-divider);
}

.service-timeline__item:last-child {
  border-left-color: transparent;
}

.service-timeline__marker {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--color-accent-success);
  margin-left: -23px;
  margin-bottom: -12px;
}

.service-timeline__body {
  display: grid;
  gap: 4px;
}

.service-timeline__headline {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.service-timeline__fecha {
  font-size: 0.8rem;
  color: var(--muted);
}

.service-timeline__descripcion {
  margin: 0;
  font-size: 0.85rem;
  color: var(--muted);
}

.service-timeline__chip {
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 0.7rem;
  font-weight: 700;
}

.service-timeline__chip.is-ok {
  background: color-mix(in srgb, var(--success) 18%, transparent);
  color: var(--success);
}

.service-timeline__chip.is-error {
  background: color-mix(in srgb, var(--error) 18%, transparent);
  color: var(--error);
}

.service-timeline__chip.is-idle {
  background: color-mix(in srgb, var(--muted) 18%, transparent);
  color: var(--muted);
}

.service-timeline__empty {
  color: var(--muted);
  font-size: 0.85rem;
}
</style>
