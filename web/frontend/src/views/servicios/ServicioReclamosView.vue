<!--
  Nombre de archivo: ServicioReclamosView.vue
  Ubicación de archivo: web/frontend/src/views/servicios/ServicioReclamosView.vue
  Descripción: Reclamos registrados de un Servicio y su histórico de fotos de SLA
-->
<template>
  <ServicioSeccionLayout
    :id-servicio="idServicio"
    titulo="Reclamos"
    descripcion="Reclamos registrados del Servicio y su histórico de SLA."
    :servicio="base.servicio.value"
    :loading="base.loading.value"
    :error="base.error.value"
  >
    <p class="reclamos__resumen">
      {{ reclamos.length }} reclamo(s) registrado(s) ·
      SLA prometido {{ base.servicio.value?.sla_prometido || '—' }}
    </p>

    <p v-if="reclamos.length === 0" class="reclamos__estado">
      Este Servicio no tiene reclamos cargados.
    </p>
    <div v-else class="reclamos__tabla-wrap">
      <table class="reclamos__tabla">
        <thead>
          <tr>
            <th scope="col">Reclamo</th>
            <th scope="col">Evento</th>
            <th scope="col">Inicio</th>
            <th scope="col">Cierre</th>
            <th scope="col">Tipo solución</th>
            <th scope="col">Grupo</th>
            <th scope="col">Horas netas</th>
            <th scope="col">% presupuesto</th>
            <th scope="col">Carrier</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="reclamo in reclamos" :key="`${reclamo.numero_reclamo}-${reclamo.numero_linea}`">
            <td>{{ reclamo.numero_reclamo }}</td>
            <td>{{ reclamo.numero_evento ?? '—' }}</td>
            <td>{{ fecha(reclamo.fecha_inicio) }}</td>
            <td>{{ fecha(reclamo.fecha_cierre) }}</td>
            <td>{{ reclamo.tipo_solucion ?? '—' }}</td>
            <td>{{ reclamo.grupo_cierre ?? '—' }}</td>
            <td>{{ numero(reclamo.horas_netas) }}</td>
            <td>{{ reclamo.cuenta_sla ? numero(reclamo.pct_presupuesto, '%') : 'no cuenta' }}</td>
            <td>{{ reclamo.carrier ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h2 class="reclamos__subtitulo">Histórico de SLA</h2>
    <p v-if="slaHistorico.length === 0" class="reclamos__estado">
      Todavía no hay fotos de SLA para este Servicio.
    </p>
    <template v-else>
      <p class="reclamos__estado">Última foto de SLA: {{ ultimaFotoSla?.fecha_corte }}</p>
      <div class="reclamos__tabla-wrap">
        <table class="reclamos__tabla">
          <thead>
            <tr>
              <th scope="col">Fecha de corte</th>
              <th scope="col">SLA prometido (%)</th>
              <th scope="col">SLA entregado (%)</th>
              <th scope="col">Horas reclamos</th>
              <th scope="col">Horas restantes</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="foto in slaHistorico" :key="`${foto.numero_linea}-${foto.fecha_corte}`">
              <td>{{ foto.fecha_corte }}</td>
              <td>{{ numero(foto.sla_prometido) }}</td>
              <td>{{ foto.sla_entregado === null ? '—' : (foto.sla_entregado * 100).toFixed(3) }}</td>
              <td>{{ numero(foto.horas_reclamos_todos) }}</td>
              <td>{{ numero(foto.horas_restantes) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </ServicioSeccionLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';

import { useServicioBase } from '../../composables/useServicioBase';
import ServicioSeccionLayout from './ServicioSeccionLayout.vue';

const route = useRoute();
const base = useServicioBase();
const slaHistorico = base.slaHistorico;
// La API devuelve las fotos en orden cronológico: la última es la más reciente.
const ultimaFotoSla = computed(() => slaHistorico.value[slaHistorico.value.length - 1]);

const idServicio = computed(() => String(route.params.idServicio ?? ''));

const reclamos = computed(() => base.servicio.value?.reclamos ?? []);

function fecha(valor: string | null): string {
  if (!valor) return '—';
  const d = new Date(valor);
  return Number.isNaN(d.getTime()) ? valor : d.toLocaleString('es-AR');
}

function numero(valor: number | null | undefined, sufijo = ''): string {
  return typeof valor === 'number' ? `${valor.toFixed(2)}${sufijo}` : '—';
}

onMounted(() => base.cargar(idServicio.value));
watch(idServicio, (id) => base.cargar(id));
</script>

<style scoped>
.reclamos__resumen,
.reclamos__estado {
  margin: 0;
  font-size: 13px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.reclamos__tabla-wrap {
  overflow-x: auto;
}

.reclamos__tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.reclamos__tabla th,
.reclamos__tabla td {
  padding: 6px 10px;
  text-align: left;
  border-bottom: 1px solid var(--color-divider);
  white-space: nowrap;
}

.reclamos__tabla th {
  font-size: 10.5px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.reclamos__subtitulo {
  margin: var(--space-4) 0 0;
  font-size: 15px;
}
</style>
