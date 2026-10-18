<!--
  Nombre de archivo: IntervencionesPanel.vue
  Ubicación de archivo: web/frontend/src/components/fo-monitor/IntervencionesPanel.vue
  Descripción: Lista filtrable de intervenciones de FO Monitor (estado, técnico, cable) con color resumen
-->
<template>
  <article class="card fomon-lista">
    <form class="fomon-lista__filtros" @submit.prevent="emit('filtrar', { ...filtros })">
      <select v-model="filtros.estado" aria-label="Estado">
        <option value="ACTIVAS">Activas</option>
        <option value="">Todas</option>
        <option value="CERRADA">Cerradas</option>
        <option value="SIN_EGRESO">Sin egreso</option>
      </select>
      <input v-model="filtros.tecnico" type="search" placeholder="Técnico…" aria-label="Técnico" />
      <input v-model="filtros.cable" type="search" placeholder="Cable (nombre o n_id)…" aria-label="Cable" />
      <button class="btn subtle" type="submit" aria-label="Filtrar"><i class="ph ph-funnel" aria-hidden="true"></i></button>
    </form>

    <p v-if="!listado" class="hint">Cargando…</p>
    <p v-else-if="listado.items.length === 0" class="hint">Sin intervenciones para estos filtros.</p>
    <ul v-else class="fomon-lista__items">
      <li v-for="i in listado.items" :key="i.id">
        <button class="fomon-lista__item" type="button" @click="emit('abrir', i)">
          <span class="fomon-punto" :class="`is-${(i.color || 'GRIS').toLowerCase()}`"></span>
          <span class="fomon-lista__texto">
            <strong>#{{ i.id }} · {{ i.camara || (i.cable_n_id_manual ? `Cable ${i.cable_n_id_manual}` : '—') }}</strong>
            <small>
              {{ i.origen === 'MANUAL' ? `Manual (${i.iniciada_por})` : i.tecnico || '—' }} · {{ i.estado }} ·
              {{ i.cables }} cables / {{ i.servicios }} serv.
              <template v-if="i.caidas_nuevas"> · <em>{{ i.caidas_nuevas }} caída(s) nueva(s)</em></template>
            </small>
          </span>
        </button>
      </li>
    </ul>
    <p v-if="listado && listado.total > listado.items.length" class="hint">
      Mostrando {{ listado.items.length }} de {{ listado.total }}.
    </p>
  </article>
</template>

<script setup lang="ts">
import { reactive } from 'vue';
import type { FiltrosIntervenciones, IntervencionResumen, ListadoIntervenciones } from '../../api/foMonitor';

defineProps<{ listado: ListadoIntervenciones | null }>();
const emit = defineEmits<{
  (e: 'abrir', intervencion: IntervencionResumen): void;
  (e: 'filtrar', filtros: FiltrosIntervenciones): void;
}>();

const filtros = reactive<FiltrosIntervenciones>({ estado: 'ACTIVAS', tecnico: '', cable: '' });
</script>

<style scoped>
.fomon-lista {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
}

.fomon-lista__filtros {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.fomon-lista__filtros input,
.fomon-lista__filtros select {
  flex: 1 1 110px;
  min-width: 0;
}

.fomon-lista__items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.fomon-lista__item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  width: 100%;
  padding: 8px 4px;
  text-align: left;
  background: none;
  border: 0;
  border-bottom: 1px solid var(--color-border-default);
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.fomon-lista__item:hover {
  background: color-mix(in srgb, var(--color-text) 5%, transparent);
}

.fomon-lista__item:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: -2px;
}

.fomon-lista__texto {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
}

.fomon-lista__texto small {
  color: var(--color-text-muted);
  font-size: 11px;
}

.fomon-lista__texto em {
  color: var(--color-state-warn);
  font-style: normal;
}
</style>
