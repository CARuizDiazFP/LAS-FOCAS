<!--
  Nombre de archivo: ServicioReclamosView.vue
  Ubicación de archivo: web/frontend/src/views/servicios/ServicioReclamosView.vue
  Descripción: Reclamos registrados de un Servicio y el último informe de SLA/Repetitividad
-->
<template>
  <ServicioSeccionLayout
    :id-servicio="idServicio"
    titulo="Reclamos"
    descripcion="Reclamos registrados del Servicio y estado de los informes que los consolidan."
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
            <th v-for="columna in columnas" :key="columna" scope="col">{{ columna }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(reclamo, indice) in reclamos" :key="indice">
            <td v-for="columna in columnas" :key="columna">{{ celda(reclamo[columna]) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="ultimoInforme" class="reclamos__estado">Último informe: {{ ultimoInforme }}</p>
  </ServicioSeccionLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { getUltimoReporte } from '../../api/servicioSecciones';
import { useServicioBase } from '../../composables/useServicioBase';
import ServicioSeccionLayout from './ServicioSeccionLayout.vue';

const route = useRoute();
const base = useServicioBase();

const idServicio = computed(() => String(route.params.idServicio ?? ''));
const ultimoInforme = ref('');

const reclamos = computed(() => base.servicio.value?.reclamos ?? []);

/** Las columnas salen de los propios reclamos: el backend los devuelve como filas sin esquema
 * fijo, así que inventar un set de columnas acá los dejaría truncados. */
const columnas = computed(() => {
  const claves = new Set<string>();
  for (const reclamo of reclamos.value) {
    Object.keys(reclamo).forEach((clave) => claves.add(clave));
  }
  return [...claves];
});

function celda(valor: unknown): string {
  if (valor === null || valor === undefined) return '—';
  return typeof valor === 'object' ? JSON.stringify(valor) : String(valor);
}

async function cargar(id: string): Promise<void> {
  ultimoInforme.value = '';
  const ok = await base.cargar(id);
  if (!ok) return;
  try {
    const historial = await getUltimoReporte('sla');
    const item = historial.items?.[0];
    if (item) {
      const cuando = item.started_at ? new Date(item.started_at).toLocaleString('es-AR') : 's/f';
      ultimoInforme.value = `${item.report_type} · ${item.status} · ${cuando}`;
    }
  } catch {
    // El último informe es contexto, no el dato central de la vista: si falla, no se muestra y
    // los reclamos se ven igual.
    ultimoInforme.value = '';
  }
}

onMounted(() => cargar(idServicio.value));
watch(idServicio, (id) => cargar(id));
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
</style>
