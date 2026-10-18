<!--
  Nombre de archivo: CableFichaPanel.vue
  Ubicación de archivo: web/frontend/src/components/fo-monitor/CableFichaPanel.vue
  Descripción: Ficha de un cable fuera de una intervención — id, nombre, extremos y servicios con su último estado verificado
-->
<template>
  <article class="card fomon-cable">
    <header class="fomon-cable__header">
      <button class="btn subtle" type="button" aria-label="Volver a la lista" @click="emit('cerrar')">
        <i class="ph ph-arrow-left" aria-hidden="true"></i>
      </button>
      <div>
        <h2>{{ ficha?.nombre || `Cable ${cableNId}` }}</h2>
        <small>ID {{ cableNId }}<template v-if="ficha?.capacidad"> · {{ ficha.capacidad }}</template>
          <template v-if="ficha?.propietario"> · {{ ficha.propietario }}</template></small>
      </div>
    </header>

    <p v-if="cargando" class="hint">Cargando…</p>
    <p v-else-if="error" class="msg err visible">{{ error }}</p>

    <template v-else-if="ficha">
      <dl class="fomon-cable__extremos">
        <dt>Extremo A</dt><dd>{{ ficha.extremo_a || '—' }}</dd>
        <dt>Extremo B</dt><dd>{{ ficha.extremo_b || '—' }}</dd>
      </dl>

      <header class="fomon-cable__subtitulo">
        <h3>Servicios ({{ ficha.servicios.length }})</h3>
        <small>{{ ficha.verificables }} verificables · tildá para resaltar en el mapa</small>
      </header>
      <p v-if="ficha.servicios.length === 0" class="hint">El cable no tiene servicios asociados.</p>
      <ul v-else class="fomon-cable__servicios">
        <li v-for="s in ficha.servicios" :key="s.servicio_pk" :class="{ 'is-no-verificable': !s.es_verificable }">
          <label class="fomon-cable__check" :title="`Resaltar ${s.servicio_id} en el mapa`">
            <input
              type="checkbox"
              :checked="seleccionados.includes(s.servicio_id || '')"
              :disabled="!s.servicio_id || (!seleccionados.includes(s.servicio_id) && seleccionados.length >= 8)"
              @change="s.servicio_id && emit('alternar-servicio', s.servicio_id)"
            />
            <span v-if="colorDe(s.servicio_id)" class="fomon-cable__muestra" :style="{ background: colorDe(s.servicio_id) }"></span>
          </label>
          <div class="fomon-cable__datos">
            <div class="fomon-cable__fila">
              <RouterLink :to="`/servicios/ID/${s.servicio_id}`">{{ s.servicio_id }}</RouterLink>
              <span>{{ s.tipo || '—' }}</span>
              <span v-if="s.categoria">C{{ s.categoria }}</span>
              <span class="fomon-cable__comercial">{{ s.estado_servicio || '—' }}</span>
            </div>
            <small>{{ s.cliente || '—' }}</small>
            <small v-if="!s.es_verificable" class="fomon-cable__estado">No verificable</small>
            <small v-else-if="!s.ultimo" class="fomon-cable__estado">Verificable · sin verificar</small>
            <small v-else class="fomon-cable__estado" :title="s.ultimo.motivo || ''">
              <span class="fomon-estado" :class="`is-${s.ultimo.estado.toLowerCase().replace('_', '-')}`">{{ s.ultimo.estado }}</span>
              · {{ fecha(s.ultimo.medido_at) }} ({{ s.ultimo.fase }}, intervención #{{ s.ultimo.intervencion_id }})
            </small>
          </div>
        </li>
      </ul>

      <details v-if="historial && historial.items.length" class="fomon-cable__historial">
        <summary>Verificaciones del cable ({{ historial.items.length }})</summary>
        <ul>
          <li v-for="h in historial.items" :key="h.intervencion_id">
            <span class="fomon-punto" :class="`is-${h.color.toLowerCase()}`"></span>
            #{{ h.intervencion_id }} · {{ fecha(h.creada_at) }} · {{ h.up }}/{{ h.evaluables }} UP
            <button class="btn subtle" type="button" @click="emit('abrir-intervencion', h.intervencion_id)">Ver</button>
          </li>
        </ul>
      </details>
    </template>
  </article>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { obtenerFichaCable, obtenerHistorialCable, type FichaCable, type HistorialCable } from '../../api/foMonitor';

const props = defineProps<{ cableNId: number; seleccionados: string[]; colores: Record<string, string> }>();
const emit = defineEmits<{
  (e: 'cerrar'): void;
  (e: 'abrir-intervencion', id: number): void;
  (e: 'alternar-servicio', servicioId: string): void;
}>();

const ficha = ref<FichaCable | null>(null);
const historial = ref<HistorialCable | null>(null);
const cargando = ref(false);
const error = ref('');

function colorDe(servicioId: string | null): string | undefined {
  return servicioId ? props.colores[servicioId] : undefined;
}

function fecha(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' }) : '—';
}

async function cargar(): Promise<void> {
  cargando.value = true;
  error.value = '';
  try {
    [ficha.value, historial.value] = await Promise.all([
      obtenerFichaCable(props.cableNId),
      obtenerHistorialCable(props.cableNId),
    ]);
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    cargando.value = false;
  }
}

watch(() => props.cableNId, cargar, { immediate: true });
</script>

<style scoped>
.fomon-cable {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 18px;
  font-size: 13px;
}

.fomon-cable__header {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.fomon-cable__header h2 {
  margin: 0 0 2px;
  font-size: 1.05rem;
}

.fomon-cable small {
  color: var(--color-text-muted);
  font-size: 11px;
}

.fomon-cable__extremos {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px 10px;
  margin: 0;
}

.fomon-cable__extremos dt {
  color: var(--color-text-muted);
}

.fomon-cable__extremos dd {
  margin: 0;
}

.fomon-cable__subtitulo h3 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 500;
}

.fomon-cable__servicios {
  list-style: none;
  margin: 0;
  padding: 0;
}

.fomon-cable__servicios li {
  display: flex;
  gap: 8px;
  padding: 7px 0;
  border-bottom: 1px solid var(--color-border-default);
}

.fomon-cable__servicios li.is-no-verificable {
  opacity: 0.7;
}

.fomon-cable__check {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding-top: 2px;
}

.fomon-cable__muestra {
  width: 14px;
  height: 4px;
  border-radius: var(--radius-pill);
}

.fomon-cable__datos {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.fomon-cable__fila {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.fomon-cable__comercial {
  color: var(--color-text-muted);
}

.fomon-estado.is-up { color: var(--color-state-ok); }
.fomon-estado.is-down { color: var(--color-state-error); }
.fomon-estado.is-admin-down,
.fomon-estado.is-desconocido,
.fomon-estado.is-no-soportado { color: var(--color-text-muted); }

.fomon-cable__historial ul {
  margin: 6px 0 0;
  padding-left: 0;
  list-style: none;
}

.fomon-cable__historial li {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
