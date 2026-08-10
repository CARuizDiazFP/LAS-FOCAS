<!--
  Nombre de archivo: CableDetalleCromoView.vue
  Ubicación de archivo: web/frontend/src/views/CableDetalleCromoView.vue
  Descripción: Vista dedicada de detalle jerárquico de un cable Cromo — extremos, Buffers (tubos) y Pelos en acordeón
-->
<template>
  <section class="cable-detalle-page">
    <div class="cable-detalle-shell">
      <RouterLink class="cable-detalle-back" to="/infra/cromo/cables">← Volver al Inventario de Cables</RouterLink>

      <div v-if="cargando" class="cable-detalle-state">Cargando detalle del cable...</div>
      <div v-else-if="error" class="cable-detalle-state error">
        <strong>No se pudo cargar el cable.</strong>
        <span>{{ error }}</span>
        <button class="btn subtle" type="button" @click="void cargar()">Reintentar</button>
      </div>

      <template v-else-if="detalle">
        <header class="cable-detalle-hero">
          <div class="cable-detalle-hero__content">
            <p class="cable-detalle-hero__eyebrow">Inventario Cromo · Cable</p>
            <h1>{{ detalle.nombre || `Cable ${detalle.n_id}` }}</h1>
            <div class="cable-detalle-hero__meta">
              <span class="cable-detalle-id">n_id {{ detalle.n_id }}</span>
              <span class="cable-detalle-vigente" :class="{ 'is-no': !detalle.vigente }">
                {{ detalle.vigente ? 'Vigente' : 'No vigente' }}
              </span>
            </div>
          </div>
        </header>

        <dl class="cable-detalle-modal__meta">
          <div>
            <dt>Capacidad</dt>
            <dd>{{ detalle.capacidad || '—' }}<template v-if="detalle.capacidad_pelos"> ({{ detalle.capacidad_pelos }})</template></dd>
          </div>
          <div><dt>Jerarquía</dt><dd>{{ detalle.jerarquia || '—' }}</dd></div>
          <div><dt>Propietario</dt><dd>{{ detalle.propietario || '—' }}</dd></div>
          <div><dt>Tendido</dt><dd>{{ detalle.tendido || '—' }}</dd></div>
        </dl>

        <section class="cable-detalle-modal__extremos">
          <button
            class="cable-detalle-modal__extremo"
            type="button"
            :disabled="detalle.extremo_a.n_id == null"
            @click="irABotella(detalle.extremo_a.n_id)"
          >
            <span class="cable-detalle-modal__extremo-label">Extremo A</span>
            <strong>{{ detalle.extremo_a.nombre || '—' }}</strong>
          </button>
          <button
            class="cable-detalle-modal__extremo"
            type="button"
            :disabled="detalle.extremo_b.n_id == null"
            @click="irABotella(detalle.extremo_b.n_id)"
          >
            <span class="cable-detalle-modal__extremo-label">Extremo B</span>
            <strong>{{ detalle.extremo_b.nombre || '—' }}</strong>
          </button>
        </section>

        <h2 class="cable-detalle-section-title">Buffers y pelos</h2>
        <p v-if="detalle.tubos.length === 0" class="hint">Este cable no tiene tubos/buffers ingeridos.</p>
        <div v-else class="cable-detalle-modal__tubos">
          <AccordionItem
            v-for="tubo in detalle.tubos"
            :key="tubo.n_id"
            :model-value="tuboExpandidoId === tubo.n_id"
            :title="`Buffer ${tubo.nombre_color || tubo.n_id}`"
            :description="`${tubo.pelos.length} pelo(s)${tubo.tiene_fila_propia ? '' : ' · referencia colgada'}`"
            @update:model-value="toggleTubo(tubo.n_id, $event)"
          >
            <table class="tabla-pelos">
              <thead>
                <tr>
                  <th>Pelo</th>
                  <th>Color</th>
                  <th>Tipo</th>
                  <th>Descripción</th>
                  <th>Servicio</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="pelo in tubo.pelos" :key="pelo.n_id">
                  <td>{{ pelo.numero_pelo || pelo.n_id }}</td>
                  <td>{{ pelo.color || '—' }}</td>
                  <td>{{ pelo.tipo_asociacion }}</td>
                  <td>{{ pelo.servicio_raw || '—' }}</td>
                  <td>
                    <template v-if="pelo.servicios.length === 0">—</template>
                    <button
                      v-for="s in pelo.servicios"
                      :key="`${s.servicio_id}-${s.pelo_n_id}`"
                      class="cable-detalle-modal__servicio-link"
                      type="button"
                      @click="irAServicio(s)"
                    >
                      {{ s.servicio_id_externo }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </AccordionItem>
        </div>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import AccordionItem from '../components/infra/AccordionItem.vue';
import { ApiError } from '../api/client';
import { obtenerDetalleCable, type CromoDetalleCable, type CromoServicioEncontrado } from '../api/cromo';

const route = useRoute();
const router = useRouter();

const cargando = ref(true);
const error = ref('');
const detalle = ref<CromoDetalleCable | null>(null);
const tuboExpandidoId = ref<number | null>(null);

function getCableNId(): number {
  const raw = String(route.params.nId ?? '');
  const value = Number(raw);
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error('El identificador de cable no es válido.');
  }
  return value;
}

async function cargar(): Promise<void> {
  cargando.value = true;
  error.value = '';
  detalle.value = null;
  tuboExpandidoId.value = null;
  try {
    const nId = getCableNId();
    detalle.value = await obtenerDetalleCable(nId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      error.value = 'No existe un cable con ese n_id en el inventario ingerido.';
    } else {
      error.value = e instanceof Error ? e.message : 'Error consultando el detalle del cable.';
    }
  } finally {
    cargando.value = false;
  }
}

function toggleTubo(nId: number, next: boolean): void {
  tuboExpandidoId.value = next ? nId : null;
}

function irAServicio(servicio: CromoServicioEncontrado): void {
  void router.push(`/servicios/ID/${encodeURIComponent(servicio.servicio_id_externo)}`);
}

function irABotella(nId: number | null): void {
  if (nId == null) return;
  void router.push({ path: '/infra/cromo/verificador', query: { tipo: 'botella', n_id: String(nId) } });
}

watch(() => route.params.nId, () => void cargar());

onMounted(() => void cargar());
</script>

<style scoped>
.cable-detalle-page {
  min-height: 100%;
  background:
    radial-gradient(circle at top left, rgba(59, 130, 246, 0.12), transparent 35%),
    radial-gradient(circle at top right, rgba(16, 185, 129, 0.1), transparent 30%),
    linear-gradient(180deg, #0b1118 0%, #0f1419 100%);
}

.cable-detalle-shell {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 20px 40px;
}

.cable-detalle-back {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #93c5fd;
  text-decoration: none;
  margin-bottom: 18px;
}

.cable-detalle-back:hover {
  color: #dbeafe;
}

.cable-detalle-state {
  padding: 24px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.56);
  color: var(--muted);
}

.cable-detalle-state.error {
  display: flex;
  flex-direction: column;
  gap: 10px;
  color: #fecaca;
  border-color: rgba(239, 68, 68, 0.3);
}

.cable-detalle-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 20px;
}

.cable-detalle-hero__eyebrow {
  margin: 0;
  color: #7dd3fc;
  font-size: 0.76rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.cable-detalle-hero__content h1 {
  margin: 6px 0 0;
  font-size: 1.6rem;
  color: #f8fafc;
}

.cable-detalle-hero__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.cable-detalle-id {
  font-size: 0.8rem;
  color: var(--muted);
}

.cable-detalle-vigente {
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 0.75rem;
  background: rgba(16, 185, 129, 0.16);
  color: #bbf7d0;
}

.cable-detalle-vigente.is-no {
  background: rgba(148, 163, 184, 0.16);
  color: var(--muted);
}

.cable-detalle-section-title {
  margin: 24px 0 12px;
  font-size: 1.05rem;
  color: #f8fafc;
}

.cable-detalle-modal__meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  margin: 0 0 16px;
}

.cable-detalle-modal__meta div {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  padding: 10px 12px;
  background: rgba(15, 23, 42, 0.56);
}

.cable-detalle-modal__meta dt {
  font-size: 0.72rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #7dd3fc;
}

.cable-detalle-modal__meta dd {
  margin: 4px 0 0;
  font-size: 0.9rem;
  color: #f8fafc;
  word-break: break-word;
}

.cable-detalle-modal__extremos {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.cable-detalle-modal__extremo {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.56);
  color: #e2e8f0;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.15s ease;
}

.cable-detalle-modal__extremo:hover:not(:disabled) {
  border-color: rgba(96, 165, 250, 0.4);
  transform: translateY(-1px);
}

.cable-detalle-modal__extremo:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.cable-detalle-modal__extremo-label {
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #7dd3fc;
}

.cable-detalle-modal__tubos {
  display: grid;
  gap: 12px;
}

.tabla-pelos {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
  margin-top: 4px;
}

.tabla-pelos th,
.tabla-pelos td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.tabla-pelos th {
  font-weight: 500;
  color: var(--muted);
  font-size: 0.75rem;
}

.cable-detalle-modal__servicio-link {
  display: inline-block;
  margin: 0 4px 4px 0;
  padding: 2px 8px;
  border: none;
  border-radius: 999px;
  background: rgba(96, 165, 250, 0.16);
  color: #dbeafe;
  font-size: 0.78rem;
  cursor: pointer;
}

.cable-detalle-modal__servicio-link:hover {
  background: rgba(96, 165, 250, 0.28);
}

@media (max-width: 720px) {
  .cable-detalle-modal__extremos {
    grid-template-columns: 1fr;
  }
}
</style>
