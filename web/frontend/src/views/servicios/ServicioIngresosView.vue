<!--
  Nombre de archivo: ServicioIngresosView.vue
  Ubicación de archivo: web/frontend/src/views/servicios/ServicioIngresosView.vue
  Descripción: Ingresos técnicos a las cámaras que atraviesa un Servicio, en su vista dedicada
-->
<template>
  <ServicioSeccionLayout
    :id-servicio="idServicio"
    titulo="Ingresos"
    descripcion="Ingresos de técnicos a las cámaras que atraviesa el Servicio, registrados desde Slack. Un ingreso que quedó en curso se puede cerrar desde acá."
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
            <th scope="col"><span class="sr-only">Acciones</span></th>
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
            <td class="ingresos__accion">
              <!-- Sólo un INGRESO real sin egreso: un INTENTO_BLOQUEADO también tiene `fecha_fin`
                   en null, pero no hay salida posible de un ingreso que nunca ocurrió. -->
              <button
                v-if="esCerrable(ingreso)"
                class="btn subtle ingresos__btn"
                type="button"
                @click="abrirEgreso(ingreso)"
              >
                Registrar egreso
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="aviso" class="ingresos__aviso" role="status">{{ aviso }}</p>
    <ModalRegistrarEgreso
      :open="ingresoSeleccionado !== null"
      :ingreso="ingresoSeleccionado"
      @close="ingresoSeleccionado = null"
      @registrado="onEgresoRegistrado"
    />
  </ServicioSeccionLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { type InfraServicioIngreso, getIngresosServicio } from '../../api/servicioSecciones';
import ModalRegistrarEgreso from '../../components/servicios/ModalRegistrarEgreso.vue';
import { useServicioBase } from '../../composables/useServicioBase';
import ServicioSeccionLayout from './ServicioSeccionLayout.vue';

const route = useRoute();
const base = useServicioBase();

const idServicio = computed(() => String(route.params.idServicio ?? ''));
const ingresos = ref<InfraServicioIngreso[]>([]);
const cargando = ref(false);
const error = ref('');
const ingresoSeleccionado = ref<InfraServicioIngreso | null>(null);
const aviso = ref('');

function esCerrable(ingreso: InfraServicioIngreso): boolean {
  return ingreso.tipo === 'INGRESO' && !ingreso.fecha_fin;
}

function abrirEgreso(ingreso: InfraServicioIngreso): void {
  aviso.value = '';
  ingresoSeleccionado.value = ingreso;
}

async function onEgresoRegistrado(): Promise<void> {
  const cerrado = ingresoSeleccionado.value;
  ingresoSeleccionado.value = null;
  aviso.value = cerrado
    ? `Egreso registrado en ${cerrado.camara_nombre ?? `la cámara ${cerrado.camara_id}`}.`
    : 'Egreso registrado.';
  await cargarIngresos();
}

async function cargar(id: string): Promise<void> {
  const ok = await base.cargar(id);
  if (!ok) return;
  await cargarIngresos();
}

async function cargarIngresos(): Promise<void> {
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

.ingresos__accion {
  text-align: right;
}

.ingresos__btn {
  padding: 3px 10px;
  font-size: 11.5px;
}

.ingresos__aviso {
  margin: 10px 0 0;
  font-size: 12.5px;
  color: var(--color-state-ok);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.ingresos__tabla th {
  font-size: 10.5px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}
</style>
