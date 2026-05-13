<!--
  Nombre de archivo: TrackingDetail.vue
  Ubicación de archivo: web/frontend/src/components/infra/TrackingDetail.vue
  Descripción: Detalle reutilizable del tracking de rutas FO con tabs, secuencia óptica y descarga de TXT
-->
<template>
  <section class="tracking-detail-embedded">
    <div class="tracking-detail-header tracking-detail-header--embedded">
      <div>
        <h4 class="tracking-detail-title">Tracking del servicio {{ servicioId }}</h4>
        <p class="tracking-detail-subtitle">
          {{ rutas.length }} camino{{ rutas.length !== 1 ? 's' : '' }} disponible{{ rutas.length !== 1 ? 's' : '' }}
        </p>
      </div>
      <button
        class="tracking-download-btn"
        type="button"
        :disabled="!activeRutaId || downloadLoading"
        @click="downloadActiveTracking"
      >
        {{ downloadLoading ? 'Descargando…' : 'Descargar TXT' }}
      </button>
    </div>

    <div class="tracking-rutas-tabs">
      <button
        v-for="ruta in rutas"
        :key="ruta.ruta_id"
        :class="['tracking-ruta-tab', { active: ruta.ruta_id === activeRutaId }]"
        :style="{ '--tab-color': getRutaColor(ruta, rutas.findIndex((item) => item.ruta_id === ruta.ruta_id)) }"
        type="button"
        @click="void selectRuta(ruta.ruta_id)"
      >
        {{ ruta.ruta_nombre || `Ruta ${ruta.ruta_id}` }}
      </button>
    </div>

    <div v-if="activeRuta" class="tracking-detail-info">
      <div class="tracking-summary-grid">
        <span class="tracking-summary-chip">Tipo: {{ activeRuta.ruta_tipo }}</span>
        <span class="tracking-summary-chip">Tránsitos: {{ activeRuta.transitos_count }}</span>
        <span class="tracking-summary-chip">Pelos: {{ rutas.length }}</span>
        <span v-if="activeRuta.alias_ids.length" class="tracking-summary-chip">Alias: {{ activeRuta.alias_ids.join(', ') }}</span>
      </div>
    </div>

    <div class="tracking-detail-list">
      <div v-if="loading" class="tracking-loading">Cargando tracking…</div>
      <div v-else-if="errorMessage" class="tracking-error">{{ errorMessage }}</div>
      <div v-else-if="detail" class="tracking-sequence">
        <template v-if="detail.punta_a">
          <div class="tracking-item tracking-punta tracking-punta-a">
            <span class="tracking-icon">🔌</span>
            <span class="tracking-text">
              <span class="tracking-punta-label">Punta A</span>
              <span class="tracking-punta-sitio">{{ detail.punta_a.sitio }}{{ detail.punta_a.conector ? `: ${detail.punta_a.conector}` : '' }}</span>
              <span v-if="detail.punta_a.identificador" class="tracking-punta-id">{{ detail.punta_a.identificador }}</span>
            </span>
          </div>
        </template>

        <template v-for="(item, index) in detail.tracking" :key="`${detail.ruta_id}-${index}`">
          <div v-if="item.tipo === 'camara'" class="tracking-item tracking-camara">
            <span class="tracking-icon">📍</span>
            <span class="tracking-text">{{ item.descripcion || 'Cámara' }}</span>
            <span v-if="item.empalme_id" class="tracking-empalme-id">#{{ item.empalme_id }}</span>
          </div>
          <div v-else-if="item.tipo === 'cable'" class="tracking-item tracking-cable">
            <span class="tracking-cable-line"></span>
            <span class="tracking-cable-info">
              <span class="tracking-cable-name">{{ item.nombre || 'Cable' }}</span>
              <span v-if="item.atenuacion_db != null" class="tracking-atenuacion">{{ item.atenuacion_db }} dB</span>
            </span>
          </div>
        </template>

        <template v-if="detail.punta_b">
          <div class="tracking-item tracking-punta tracking-punta-b">
            <span class="tracking-icon">🔌</span>
            <span class="tracking-text">
              <span class="tracking-punta-label">Punta B</span>
              <span class="tracking-punta-sitio">{{ detail.punta_b.sitio }}{{ detail.punta_b.conector ? `: ${detail.punta_b.conector}` : '' }}</span>
              <span v-if="detail.punta_b.identificador" class="tracking-punta-id">{{ detail.punta_b.identificador }}</span>
            </span>
          </div>
        </template>
      </div>
      <div v-else class="tracking-empty">No se encontró tracking estructurado para esta ruta.</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { downloadTracking, loadTrackingDetail, type TrackingDetailPayload } from '../../composables/useTracking';

interface RutaItem {
  ruta_id: number;
  servicio_id: string;
  ruta_nombre: string;
  ruta_tipo: string;
  alias_ids: string[];
  transitos_count: number;
  punta_a_sitio: string | null;
  punta_b_sitio: string | null;
}

const props = defineProps<{
  servicioId: string;
  rutas: RutaItem[];
}>();

const emit = defineEmits<{
  error: [message: string];
  downloaded: [filename: string];
}>();

const activeRutaId = ref<number | null>(null);
const detail = ref<TrackingDetailPayload | null>(null);
const loading = ref(false);
const downloadLoading = ref(false);
const errorMessage = ref('');

const activeRuta = computed(() => props.rutas.find((ruta) => ruta.ruta_id === activeRutaId.value) ?? null);

function getRutaColor(ruta: RutaItem, index: number): string {
  const fallback = ['#3B82F6', '#10B981', '#F59E0B', '#E61876'];
  if (ruta.ruta_tipo === 'PRINCIPAL') return '#3B82F6';
  if (ruta.ruta_tipo === 'BACKUP') return '#10B981';
  if (ruta.ruta_tipo === 'ALTERNATIVA') return '#F59E0B';
  const normalized = String(ruta.ruta_nombre ?? '').toLowerCase();
  if (normalized.includes('principal') || normalized === 'camino 1') return '#3B82F6';
  if (normalized.includes('backup') || normalized.includes('secundario') || normalized === 'camino 2') return '#10B981';
  if (normalized === 'camino 3' || normalized.includes('alternativ')) return '#F59E0B';
  if (normalized === 'camino 4') return '#E61876';
  return fallback[index % fallback.length];
}

async function selectRuta(rutaId: number): Promise<void> {
  activeRutaId.value = rutaId;
  loading.value = true;
  errorMessage.value = '';
  try {
    detail.value = await loadTrackingDetail(rutaId);
  } catch (error) {
    detail.value = null;
    errorMessage.value = error instanceof Error ? error.message : String(error);
    emit('error', errorMessage.value);
  } finally {
    loading.value = false;
  }
}

async function downloadActiveTracking(): Promise<void> {
  if (!activeRutaId.value) {
    return;
  }
  downloadLoading.value = true;
  errorMessage.value = '';
  try {
    const filename = await downloadTracking(activeRutaId.value);
    emit('downloaded', filename);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error);
    emit('error', errorMessage.value);
  } finally {
    downloadLoading.value = false;
  }
}

watch(
  () => props.rutas,
  async (rutas) => {
    if (!rutas.length) {
      activeRutaId.value = null;
      detail.value = null;
      errorMessage.value = '';
      return;
    }
    if (!rutas.some((ruta) => ruta.ruta_id === activeRutaId.value)) {
      await selectRuta(rutas[0].ruta_id);
    }
  },
  { immediate: true },
);
</script>

<style scoped>
.tracking-detail-embedded {
  margin-top: 16px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 16px;
  overflow: hidden;
  background: rgba(9, 14, 23, 0.92);
}

.tracking-detail-header--embedded {
  gap: 16px;
}

.tracking-detail-subtitle {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 0.82rem;
}

.tracking-summary-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tracking-summary-chip {
  border-radius: 999px;
  padding: 4px 10px;
  background: rgba(148, 163, 184, 0.12);
  color: var(--text);
  font-size: 0.76rem;
}

@media (max-width: 720px) {
  .tracking-detail-header--embedded {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>