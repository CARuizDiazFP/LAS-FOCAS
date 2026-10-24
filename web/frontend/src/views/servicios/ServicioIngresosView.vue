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
    <label v-if="esAdmin" class="ingresos__toggle">
      <input v-model="mostrarAnulados" type="checkbox" :disabled="cargando" />
      Mostrar anulados
      <span v-if="mostrarAnulados && totalAnulados !== null" class="ingresos__toggle-cuenta">
        ({{ totalAnulados }} anulado{{ totalAnulados !== 1 ? 's' : '' }})
      </span>
    </label>
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
          <template v-for="ingreso in ingresos" :key="ingreso.id">
            <tr :class="{ 'is-anulado': ingreso.anulado }">
              <td>{{ ingreso.camara_nombre ?? ingreso.camara_id }}</td>
              <td>{{ ingreso.botella_label || '—' }}</td>
              <td>{{ ingreso.tecnico_id ?? '—' }}</td>
              <td>{{ fecha(ingreso.fecha_inicio) }}</td>
              <!-- `fecha_fin` en null es "en curso" para un ingreso real, pero también lo tiene un
                   INTENTO_BLOQUEADO: por eso el tipo se muestra siempre, al lado. -->
              <td>{{ ingreso.fecha_fin ? fecha(ingreso.fecha_fin) : 'En curso' }}</td>
              <td>
                {{ ingreso.tipo }}
                <span v-if="ingreso.anulado" class="ingresos__chip-anulado">Anulado</span>
              </td>
              <td class="ingresos__accion">
                <div class="ingresos__botones">
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
                  <template v-if="esAdmin && !ingreso.anulado">
                    <button class="btn subtle ingresos__btn" type="button" @click="abrirMover(ingreso)">
                      Mover
                    </button>
                    <button class="btn danger ingresos__btn" type="button" @click="abrirAnular(ingreso)">
                      Anular
                    </button>
                  </template>
                </div>
              </td>
            </tr>
            <tr v-if="ingreso.anulado" class="is-anulado ingresos__fila-anulado">
              <td colspan="7">
                Anulado por {{ ingreso.anulado_por ?? 'desconocido' }} el {{ fecha(ingreso.anulado_at) }}:
                {{ ingreso.anulado_motivo ?? 'sin motivo registrado' }}
              </td>
            </tr>
          </template>
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
    <ModalMoverIngreso
      :open="ingresoAMover !== null"
      :ingreso="ingresoAMover"
      @close="ingresoAMover = null"
      @movido="onIngresoMovido"
    />
    <ModalAnularIngreso
      :open="ingresoAAnular !== null"
      :ingreso="ingresoAAnular"
      @close="ingresoAAnular = null"
      @anulado="onIngresoAnulado"
    />
  </ServicioSeccionLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import {
  type CorreccionIngresoResponse,
  type InfraServicioIngreso,
  getIngresosServicio,
} from '../../api/servicioSecciones';
import ModalAnularIngreso from '../../components/servicios/ModalAnularIngreso.vue';
import ModalMoverIngreso from '../../components/servicios/ModalMoverIngreso.vue';
import ModalRegistrarEgreso from '../../components/servicios/ModalRegistrarEgreso.vue';
import { useServicioBase } from '../../composables/useServicioBase';
import { useSession } from '../../composables/useSession';
import ServicioSeccionLayout from './ServicioSeccionLayout.vue';

const route = useRoute();
const base = useServicioBase();
const { state: sesion } = useSession();
// Mover/anular y "Mostrar anulados" son sólo de admin (el backend igual lo exige: 403 / se ignora).
const esAdmin = computed(() => (sesion.value.role ?? '').toLowerCase() === 'admin');

const idServicio = computed(() => String(route.params.idServicio ?? ''));
const ingresos = ref<InfraServicioIngreso[]>([]);
const cargando = ref(false);
const error = ref('');
const ingresoSeleccionado = ref<InfraServicioIngreso | null>(null);
const aviso = ref('');
const mostrarAnulados = ref(false);
const totalAnulados = ref<number | null>(null);
const ingresoAMover = ref<InfraServicioIngreso | null>(null);
const ingresoAAnular = ref<InfraServicioIngreso | null>(null);

function esCerrable(ingreso: InfraServicioIngreso): boolean {
  return ingreso.tipo === 'INGRESO' && !ingreso.fecha_fin && !ingreso.anulado;
}

function abrirMover(ingreso: InfraServicioIngreso): void {
  aviso.value = '';
  ingresoAMover.value = ingreso;
}

function abrirAnular(ingreso: InfraServicioIngreso): void {
  aviso.value = '';
  ingresoAAnular.value = ingreso;
}

// El modal puede quedar abierto (nota de FO Monitor): sólo se recarga la lista detrás; se cierra
// con su propio `close`.
async function onIngresoMovido(respuesta: CorreccionIngresoResponse): Promise<void> {
  aviso.value = respuesta.mensaje;
  await cargarIngresos();
}

async function onIngresoAnulado(respuesta: CorreccionIngresoResponse): Promise<void> {
  aviso.value = respuesta.mensaje;
  await cargarIngresos();
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
    const respuesta = await getIngresosServicio(base.idOrigen.value, esAdmin.value && mostrarAnulados.value);
    ingresos.value = respuesta.ingresos;
    totalAnulados.value = respuesta.total_anulados ?? null;
  } catch (err: unknown) {
    ingresos.value = [];
    totalAnulados.value = null;
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
watch(mostrarAnulados, () => {
  if (base.idOrigen.value) void cargarIngresos();
});
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

.ingresos__botones {
  display: inline-flex;
  gap: 6px;
  justify-content: flex-end;
}

.ingresos__toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 10px;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 75%, transparent);
  cursor: pointer;
}

.ingresos__toggle-cuenta {
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

/* Anulado: atenuado, sin tachado (el texto sigue siendo legible para auditar). */
.ingresos__tabla tr.is-anulado td {
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.ingresos__tabla tr.is-anulado:not(.ingresos__fila-anulado) td {
  border-bottom-style: dashed;
}

.ingresos__fila-anulado td {
  padding-top: 0;
  white-space: normal;
  font-style: italic;
  font-size: 12px;
}

.ingresos__chip-anulado {
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 10.5px;
  font-style: normal;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-state-error);
  background: color-mix(in srgb, var(--color-state-error) 14%, transparent);
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
