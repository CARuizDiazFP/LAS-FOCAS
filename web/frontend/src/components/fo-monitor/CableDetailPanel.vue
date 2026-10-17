<!--
  Nombre de archivo: CableDetailPanel.vue
  Ubicación de archivo: web/frontend/src/components/fo-monitor/CableDetailPanel.vue
  Descripción: Ficha de un cable dentro de una intervención — servicios PRE/POST, consultas a burritoIA y reconocimientos
-->
<template>
  <article class="card fomon-ficha">
    <header class="fomon-ficha__header">
      <button class="btn subtle" type="button" aria-label="Volver a la lista" @click="emit('cerrar')">
        <i class="ph ph-arrow-left" aria-hidden="true"></i>
      </button>
      <div>
        <h2>{{ cable?.nombre || `Cable ${cableNId}` }}</h2>
        <small v-if="intervencion">
          Intervención #{{ intervencion.id }} · {{ intervencion.camara || 'sin cámara' }} · {{ intervencion.estado }}
        </small>
      </div>
    </header>

    <p v-if="cargando" class="hint">Cargando…</p>
    <p v-else-if="error" class="msg err visible">{{ error }}</p>

    <template v-else-if="intervencion && cable">
      <div class="fomon-ficha__semaforo">
        <span class="fomon-punto" :class="`is-${cable.color.toLowerCase()}`"></span>
        <strong>{{ ETIQUETA_COLOR[cable.color] }}</strong>
        <span>{{ cable.up }}/{{ cable.evaluables }} UP<template v-if="cable.conocidos < cable.evaluables">
          · {{ cable.evaluables - cable.conocidos }} sin dato</template></span>
      </div>
      <ul class="fomon-ficha__marcas">
        <li v-if="cable.es_objetivo">Botella intervenida</li>
        <li v-if="intervencion.sin_linea_base">Sin línea base PRE (no se marcan caídas nuevas)</li>
        <li v-if="intervencion.post_tardio">POST tardío</li>
        <li v-if="intervencion.egreso_inferido">Egreso inferido</li>
        <li v-if="intervencion.atribucion_compartida">Otra intervención simultánea en la cámara</li>
        <li v-if="intervencion.botella_1_inferida">Botella 1 inferida (¿cámara duplicada en Cromo?)</li>
      </ul>

      <table class="fomon-tabla">
        <thead>
          <tr><th>Servicio</th><th>Cat.</th><th>PRE</th><th>POST</th><th v-if="esAdmin"></th></tr>
        </thead>
        <tbody>
          <tr v-for="s in serviciosOrdenados" :key="s.servicio_pk" :class="{ 'is-caida': cable.caidas_nuevas.includes(s.servicio_pk) }">
            <td>
              <RouterLink :to="`/servicios/ID/${s.servicio_id}`">{{ s.servicio_id }}</RouterLink>
              <small>{{ s.tipo }} · {{ s.cliente || '—' }}</small>
            </td>
            <td>{{ s.categoria === null || s.categoria === 0 ? '—' : `C${s.categoria}` }}</td>
            <td :title="s.pre?.motivo || ''"><span class="fomon-estado" :class="claseEstado(s.pre?.estado)">{{ s.pre?.estado || '—' }}</span></td>
            <td :title="s.post?.motivo || ''"><span class="fomon-estado" :class="claseEstado(s.post?.estado)">{{ s.post?.estado || '—' }}</span>
              <small v-if="s.post?.extremo">ext. {{ s.post.extremo }}</small></td>
            <td v-if="esAdmin">
              <button v-if="cable.caidas_nuevas.includes(s.servicio_pk) && !s.reconocido" class="btn subtle" type="button"
                      @click="reconocer(s.servicio_pk)">Ajena</button>
              <small v-else-if="s.reconocido">reconocida</small>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="cable.servicios.length === 0" class="hint">El cable no tiene servicios verificables activos.</p>

      <details class="fomon-ficha__consultas">
        <summary>Consultas a burritoIA ({{ intervencion.consultas.length }})</summary>
        <ul>
          <li v-for="c in intervencion.consultas" :key="c.id">
            {{ c.fase }} #{{ c.id }} · intento {{ c.intento }} · {{ c.estado }}
            <template v-if="c.permalink"> · <a :href="c.permalink" target="_blank" rel="noopener">Slack</a></template>
            <small>{{ c.ids.join(', ') }}</small>
          </li>
        </ul>
      </details>
      <details v-if="intervencion.reconocimientos.length" class="fomon-ficha__consultas">
        <summary>Reconocimientos ({{ intervencion.reconocimientos.length }})</summary>
        <ul>
          <li v-for="r in intervencion.reconocimientos" :key="r.id">{{ r.usuario }}: {{ r.motivo }}</li>
        </ul>
      </details>
    </template>

    <template v-else-if="historial">
      <p class="hint">El cable no está en una intervención activa. Últimas verificaciones:</p>
      <ul class="fomon-ficha__historial">
        <li v-for="h in historial.items" :key="h.intervencion_id">
          <span class="fomon-punto" :class="`is-${h.color.toLowerCase()}`"></span>
          #{{ h.intervencion_id }} · {{ fecha(h.creada_at) }} · {{ h.up }}/{{ h.evaluables }} UP
          <button class="btn subtle" type="button" @click="emit('abrir-intervencion', h.intervencion_id)">Ver</button>
        </li>
        <li v-if="historial.items.length === 0" class="hint">Sin verificaciones registradas.</li>
      </ul>
    </template>
  </article>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import {
  obtenerHistorialCable, obtenerIntervencion, reconocerComoAjena,
  type EstadoServicio, type HistorialCable, type IntervencionDetalle,
} from '../../api/foMonitor';
import { ETIQUETA_COLOR } from './colores';

const props = defineProps<{ cableNId: number; intervencionId: number | null; esAdmin: boolean; version: number }>();
const emit = defineEmits<{ (e: 'cerrar'): void; (e: 'abrir-intervencion', id: number): void }>();

const intervencion = ref<IntervencionDetalle | null>(null);
const historial = ref<HistorialCable | null>(null);
const cargando = ref(false);
const error = ref('');

const cable = computed(() => intervencion.value?.cables_detalle.find((c) => c.cable_n_id === props.cableNId) ?? null);
const serviciosOrdenados = computed(() =>
  [...(cable.value?.servicios ?? [])].sort((a, b) => (b.categoria ?? 0) - (a.categoria ?? 0)),
);

function claseEstado(e?: EstadoServicio | null): string {
  return e ? `is-${e.toLowerCase().replace('_', '-')}` : '';
}

function fecha(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' }) : '—';
}

async function cargar(): Promise<void> {
  cargando.value = true;
  error.value = '';
  try {
    if (props.intervencionId) {
      intervencion.value = await obtenerIntervencion(props.intervencionId);
      historial.value = null;
    } else {
      intervencion.value = null;
      historial.value = await obtenerHistorialCable(props.cableNId);
    }
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    cargando.value = false;
  }
}

async function reconocer(servicioPk: number): Promise<void> {
  const motivo = window.prompt('Motivo por el que la caída es ajena a la intervención:');
  if (!motivo || motivo.trim().length < 3 || !intervencion.value) return;
  try {
    await reconocerComoAjena(intervencion.value.id, motivo.trim(), servicioPk);
    await cargar();
  } catch (err) {
    error.value = (err as Error).message;
  }
}

watch(() => [props.cableNId, props.intervencionId, props.version], cargar, { immediate: true });
</script>

<style scoped>
.fomon-ficha {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 18px;
  font-size: 13px;
}

.fomon-ficha__header {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.fomon-ficha__header h2 {
  margin: 0 0 2px;
  font-size: 1.05rem;
}

.fomon-ficha__header small,
.fomon-tabla small,
.fomon-ficha__consultas small {
  display: block;
  color: var(--color-text-muted);
  font-size: 11px;
}

.fomon-ficha__semaforo {
  display: flex;
  align-items: center;
  gap: 8px;
}

.fomon-ficha__marcas {
  margin: 0;
  padding-left: 18px;
  color: var(--color-accent-warning);
  font-size: 12px;
}

.fomon-tabla {
  width: 100%;
  border-collapse: collapse;
}

.fomon-tabla th,
.fomon-tabla td {
  text-align: left;
  padding: 6px 6px;
  border-bottom: 1px solid var(--color-border-default);
  vertical-align: top;
}

.fomon-tabla th {
  font-weight: 500;
  font-size: 12px;
  color: var(--color-text-muted);
}

.fomon-tabla tr.is-caida td {
  background: color-mix(in srgb, var(--color-state-warn) 12%, transparent);
}

.fomon-estado.is-up { color: var(--color-state-ok); }
.fomon-estado.is-down { color: var(--color-state-error); }
.fomon-estado.is-admin-down,
.fomon-estado.is-desconocido,
.fomon-estado.is-no-soportado { color: var(--color-text-muted); }

.fomon-ficha__consultas ul,
.fomon-ficha__historial {
  margin: 6px 0 0;
  padding-left: 16px;
}

.fomon-ficha__historial li {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
