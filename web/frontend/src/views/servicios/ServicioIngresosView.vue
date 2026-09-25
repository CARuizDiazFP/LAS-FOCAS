<!--
  Nombre de archivo: ServicioIngresosView.vue
  Ubicación de archivo: web/frontend/src/views/servicios/ServicioIngresosView.vue
  Descripción: Ingresos técnicos a las cámaras que atraviesa un Servicio, en su vista dedicada
-->
<template>
  <ServicioSeccionLayout
    :id-servicio="idServicio"
    titulo="Ingresos"
    descripcion="Ingresos de técnicos a las cámaras que atraviesa el Servicio, registrados desde Slack."
    :servicio="base.servicio.value"
    :loading="base.loading.value"
    :error="base.error.value"
  >
    <p v-if="cargando" class="ingresos__estado">Cargando ingresos…</p>
    <p v-else-if="error" class="ingresos__estado is-error">{{ error }}</p>
    <p v-else-if="ingresos.length === 0" class="ingresos__estado">
      Este Servicio no tiene ingresos registrados.
    </p>
    <div v-else class="ingresos__tabla-wrap">
      <table class="ingresos__tabla">
        <thead>
          <tr>
            <th scope="col">Cámara</th>
            <th scope="col">Botella</th>
            <th scope="col">Técnico</th>
            <th scope="col">Desde</th>
            <th scope="col">Hasta</th>
            <th scope="col">Tipo</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ingreso in ingresos" :key="ingreso.id">
            <td>{{ ingreso.camara_nombre ?? ingreso.camara_id }}</td>
            <td>{{ ingreso.botella_label || '—' }}</td>
            <td>{{ ingreso.tecnico_id ?? '—' }}</td>
            <td>{{ fecha(ingreso.fecha_inicio) }}</td>
            <!-- `fecha_fin` en null es "en curso" para un ingreso real, pero también lo tiene un
                 INTENTO_BLOQUEADO: por eso el tipo se muestra siempre, al lado. -->
            <td>{{ ingreso.fecha_fin ? fecha(ingreso.fecha_fin) : 'En curso' }}</td>
            <td>{{ ingreso.tipo }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </ServicioSeccionLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { type InfraServicioIngreso, getIngresosServicio } from '../../api/servicioSecciones';
import { useServicioBase } from '../../composables/useServicioBase';
import ServicioSeccionLayout from './ServicioSeccionLayout.vue';

const route = useRoute();
const base = useServicioBase();

const idServicio = computed(() => String(route.params.idServicio ?? ''));
const ingresos = ref<InfraServicioIngreso[]>([]);
const cargando = ref(false);
const error = ref('');

async function cargar(id: string): Promise<void> {
  const ok = await base.cargar(id);
  if (!ok) return;
  cargando.value = true;
  error.value = '';
  try {
    ingresos.value = (await getIngresosServicio(base.idOrigen.value)).ingresos;
  } catch (err: unknown) {
    ingresos.value = [];
    error.value = err instanceof Error ? err.message : 'No se pudieron cargar los ingresos';
  } finally {
    cargando.value = false;
  }
}

function fecha(valor: string | null): string {
  if (!valor) return '—';
  const parsed = new Date(valor);
  return Number.isNaN(parsed.getTime()) ? valor : parsed.toLocaleString('es-AR');
}

onMounted(() => cargar(idServicio.value));
watch(idServicio, (id) => cargar(id));
</script>

<style scoped>
.ingresos__estado {
  margin: 0;
  font-size: 13px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.ingresos__estado.is-error {
  color: var(--color-state-error);
}

.ingresos__tabla-wrap {
  overflow-x: auto;
}

.ingresos__tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.ingresos__tabla th,
.ingresos__tabla td {
  padding: 6px 10px;
  text-align: left;
  border-bottom: 1px solid var(--color-divider);
  white-space: nowrap;
}

.ingresos__tabla th {
  font-size: 10.5px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}
</style>
