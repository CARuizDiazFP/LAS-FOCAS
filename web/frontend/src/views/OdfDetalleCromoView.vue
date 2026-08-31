<!--
  Nombre de archivo: OdfDetalleCromoView.vue
  Ubicación de archivo: web/frontend/src/views/OdfDetalleCromoView.vue
  Descripción: Vista dedicada de detalle de un ODF Cromo — metadata, cables asociados, ODFs vecinos y servicios asociados
-->
<template>
  <section class="odf-detalle-page">
    <div class="odf-detalle-shell">
      <RouterLink class="odf-detalle-back" to="/infra/cromo/odfs">← Volver al Inventario de ODFs</RouterLink>

      <div v-if="cargando" class="odf-detalle-state">Cargando detalle del ODF...</div>
      <div v-else-if="error" class="odf-detalle-state error">
        <strong>No se pudo cargar el ODF.</strong>
        <span>{{ error }}</span>
        <button class="btn subtle" type="button" @click="void cargar()">Reintentar</button>
      </div>

      <template v-else-if="detalle">
        <header class="odf-detalle-hero">
          <div class="odf-detalle-hero__content">
            <p class="odf-detalle-hero__eyebrow">Inventario Cromo · ODF</p>
            <h1>{{ detalle.nombre || `ODF ${detalle.n_id}` }}</h1>
            <div class="odf-detalle-hero__meta">
              <span class="odf-detalle-id">n_id {{ detalle.n_id }}</span>
              <span :class="['tipo-elemento-chip', `tipo-elemento-chip--${tipoElementoClase(detalle.tipo_elemento)}`]">
                {{ tipoElementoLabel(detalle.tipo_elemento) }}
              </span>
              <span class="odf-detalle-vigente" :class="{ 'is-no': !detalle.vigente }">
                {{ detalle.vigente ? 'Vigente' : 'No vigente' }}
              </span>
            </div>
          </div>
        </header>

        <dl class="odf-detalle-modal__meta">
          <div><dt>Dirección</dt><dd>{{ direccionCompleta }}</dd></div>
          <div><dt>Localidad</dt><dd>{{ detalle.localidad || '—' }}</dd></div>
          <div><dt>Provincia</dt><dd>{{ detalle.provincia || '—' }}</dd></div>
          <div><dt>Propietario</dt><dd>{{ detalle.propietario || '—' }}</dd></div>
        </dl>

        <article class="card odf-detalle-card">
          <header class="odf-detalle-card__header">
            <h2>Cables asociados</h2>
            <span class="odf-detalle-chip">{{ detalle.cables_asociados.length }} cable(s)</span>
          </header>

          <p v-if="detalle.cables_asociados.length === 0" class="hint">
            Este ODF no tiene cables asociados en el inventario ingerido.
          </p>
          <ul v-else class="odf-detalle-lista">
            <li v-for="c in detalle.cables_asociados" :key="c.n_id">
              <RouterLink :to="`/infra/cromo/cables/ID${c.n_id}`">
                {{ c.nombre || `Cable ${c.n_id}` }}
              </RouterLink>
            </li>
          </ul>
        </article>

        <article class="card odf-detalle-card">
          <header class="odf-detalle-card__header">
            <h2>ODFs en la misma dirección</h2>
            <span class="odf-detalle-chip">{{ detalle.odfs_en_la_misma_direccion.length }} ODF(s)</span>
          </header>

          <p v-if="detalle.odfs_en_la_misma_direccion.length === 0" class="hint">
            No hay otros ODFs registrados en esta misma dirección.
          </p>
          <ul v-else class="odf-detalle-lista">
            <li v-for="vecino in detalle.odfs_en_la_misma_direccion" :key="vecino.n_id">
              <RouterLink :to="`/infra/cromo/odfs/ID${vecino.n_id}`">
                {{ vecino.nombre || `ODF ${vecino.n_id}` }}
              </RouterLink>
            </li>
          </ul>
        </article>

        <article class="card odf-detalle-card">
          <header class="odf-detalle-card__header">
            <h2>Servicios asociados</h2>
            <span class="odf-detalle-chip">{{ servicios.length }} servicio(s)</span>
          </header>

          <p v-if="serviciosError" class="msg err visible">{{ serviciosError }}</p>
          <p v-else-if="serviciosCargando" class="hint">Cargando servicios…</p>
          <p v-else-if="servicios.length === 0" class="hint">
            No se encontró ningún servicio matcheado que pase por este ODF — puede que todavía no
            haya sido ingerido, que no tenga servicio asociado, o que el match no se haya resuelto.
          </p>

          <table v-else class="tabla-servicios">
            <thead>
              <tr>
                <th>Servicio</th>
                <th>Cliente</th>
                <th>Estado</th>
                <th>Tipo</th>
                <th>Pelo</th>
                <th>Método</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in servicios" :key="`${s.servicio_id}-${s.pelo_n_id}`">
                <td>
                  <button class="odf-detalle-servicio-link" type="button" @click="irAServicioPorId(s.servicio_id_externo)">
                    {{ s.servicio_id_externo }}
                  </button>
                </td>
                <td>{{ s.nombre_cliente || s.cliente || '—' }}</td>
                <td>{{ s.estado_servicio || '—' }}</td>
                <td>{{ s.tipo_servicio || '—' }}</td>
                <td>{{ s.pelo_n_id }}</td>
                <td>{{ s.metodo }}</td>
              </tr>
            </tbody>
          </table>
        </article>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { ApiError } from '../api/client';
import {
  obtenerDetalleOdf,
  verificarServiciosPorOdf,
  type CromoDetalleOdf,
  type CromoServicioEncontrado,
} from '../api/cromo';

const route = useRoute();
const router = useRouter();

const cargando = ref(true);
const error = ref('');
const detalle = ref<CromoDetalleOdf | null>(null);

const servicios = ref<CromoServicioEncontrado[]>([]);
const serviciosCargando = ref(false);
const serviciosError = ref('');

const direccionCompleta = computed(() => {
  if (!detalle.value) return '—';
  const partes = [detalle.value.calle, detalle.value.altura].filter((v): v is string => Boolean(v));
  return partes.length > 0 ? partes.join(' ') : '—';
});

function getOdfNId(): number {
  const raw = String(route.params.nId ?? '');
  const value = Number(raw);
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error('El identificador de ODF no es válido.');
  }
  return value;
}

/** "ODF" → verde, "EMPALME" → ámbar, "SIN_CLASIFICAR" (u otro valor) → gris — mismo patrón de badge
 * de estado ya usado en `CableDetalleCromoView.vue` (`color-mix()` sobre tokens.css), sin crear una
 * utilidad de mapeo de colores compartida nueva. */
function tipoElementoClase(tipo: string): 'ok' | 'warn' | 'idle' {
  if (tipo === 'ODF') return 'ok';
  if (tipo === 'EMPALME') return 'warn';
  return 'idle';
}

function tipoElementoLabel(tipo: string): string {
  if (tipo === 'ODF') return 'ODF';
  if (tipo === 'EMPALME') return 'Empalme';
  return 'Sin clasificar';
}

// Mismo patrón que CableDetalleCromoView.vue::irAServicioPorId — navega al Detalle de Servicio por
// el ID externo (`servicio_id_externo`, ya resuelto por `verificarServiciosPorOdf`).
function irAServicioPorId(servicioIdExterno: string): void {
  void router.push(`/servicios/ID/${encodeURIComponent(servicioIdExterno)}`);
}

async function cargarServicios(nId: number): Promise<void> {
  serviciosCargando.value = true;
  serviciosError.value = '';
  try {
    const r = await verificarServiciosPorOdf(nId);
    servicios.value = r.servicios;
  } catch (e) {
    servicios.value = [];
    serviciosError.value = e instanceof Error ? e.message : 'Error consultando los servicios del ODF.';
  } finally {
    serviciosCargando.value = false;
  }
}

async function cargar(): Promise<void> {
  cargando.value = true;
  error.value = '';
  detalle.value = null;
  servicios.value = [];
  serviciosError.value = '';
  try {
    const nId = getOdfNId();
    detalle.value = await obtenerDetalleOdf(nId);
    void cargarServicios(nId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      error.value = 'No existe un ODF con ese n_id en el inventario ingerido.';
    } else {
      error.value = e instanceof Error ? e.message : 'Error consultando el detalle del ODF.';
    }
  } finally {
    cargando.value = false;
  }
}

watch(() => route.params.nId, () => void cargar());

onMounted(() => void cargar());
</script>

<style scoped>
.odf-detalle-page {
  min-height: 100%;
}

.odf-detalle-shell {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 20px 40px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.odf-detalle-back {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-accent);
  text-decoration: none;
  margin-bottom: 2px;
}

.odf-detalle-back:hover {
  color: var(--color-accent-300);
}

.odf-detalle-state {
  padding: 24px;
  border-radius: 16px;
  border: 1px solid var(--color-divider);
  background: var(--color-surface);
  color: var(--muted);
}

.odf-detalle-state.error {
  display: flex;
  flex-direction: column;
  gap: 10px;
  color: var(--error);
  border-color: color-mix(in srgb, var(--error) 30%, transparent);
}

.odf-detalle-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.odf-detalle-hero__eyebrow {
  margin: 0;
  color: var(--color-accent);
  font-size: 0.76rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.odf-detalle-hero__content h1 {
  margin: 6px 0 0;
  font-size: 1.6rem;
  color: var(--color-text);
}

.odf-detalle-hero__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.odf-detalle-id {
  font-size: 0.8rem;
  color: var(--muted);
}

.odf-detalle-vigente {
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 0.75rem;
  background: color-mix(in srgb, var(--color-state-ok) 16%, transparent);
  color: var(--color-state-ok);
}

.odf-detalle-vigente.is-no {
  background: color-mix(in srgb, var(--color-state-idle) 16%, transparent);
  color: var(--muted);
}

.odf-detalle-modal__meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  margin: 0;
}

.odf-detalle-modal__meta div {
  border: 1px solid var(--color-divider);
  border-radius: 12px;
  padding: 10px 12px;
  background: var(--color-surface);
}

.odf-detalle-modal__meta dt {
  font-size: 0.72rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.odf-detalle-modal__meta dd {
  margin: 4px 0 0;
  font-size: 0.9rem;
  color: var(--color-text);
  word-break: break-word;
}

.odf-detalle-card {
  padding: 18px 20px;
}

.odf-detalle-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.odf-detalle-card__header h2 {
  font-size: 15px;
  margin: 0;
}

.odf-detalle-chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  color: var(--color-accent);
  white-space: nowrap;
}

.odf-detalle-lista {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.odf-detalle-lista a {
  color: var(--color-accent);
  text-decoration: none;
}

.odf-detalle-lista a:hover {
  color: var(--color-accent-300);
  text-decoration: underline;
}

.tabla-servicios {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.tabla-servicios th,
.tabla-servicios td {
  text-align: left;
  padding: 7px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--color-text) 10%, transparent);
}

.tabla-servicios th {
  font-weight: 500;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  font-size: 12px;
}

.odf-detalle-servicio-link {
  display: inline-block;
  padding: 2px 8px;
  border: none;
  border-radius: 999px;
  background: var(--color-brand-primary-tint);
  color: var(--color-accent-200);
  font-size: 0.78rem;
  cursor: pointer;
}

.odf-detalle-servicio-link:hover {
  background: var(--color-brand-primary-soft);
}

.tipo-elemento-chip {
  display: inline-flex;
  font-size: 0.75rem;
  font-weight: 500;
  padding: 3px 10px;
  border-radius: 999px;
  white-space: nowrap;
}

.tipo-elemento-chip--ok {
  background: color-mix(in srgb, var(--color-state-ok) 16%, transparent);
  color: var(--color-state-ok);
}

.tipo-elemento-chip--warn {
  background: color-mix(in srgb, var(--color-state-warn) 16%, transparent);
  color: var(--color-state-warn);
}

.tipo-elemento-chip--idle {
  background: color-mix(in srgb, var(--color-state-idle) 16%, transparent);
  color: var(--muted);
}
</style>
