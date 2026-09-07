<!--
  Nombre de archivo: ModalServicios.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalServicios.vue
  Descripción: Modal aislado para visualizar servicios y rutas asociados a una cámara
-->
<template>
  <dialog ref="dialogEl" class="infra-detail-modal" @click.self="handleClose">
    <section class="infra-detail-modal__content">
      <header class="infra-detail-modal__header">
        <div>
          <p class="infra-detail-modal__eyebrow">Servicios Asociados</p>
          <h3>{{ camaraNombre }} · ID {{ camaraId ?? '—' }}</h3>
        </div>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </header>

      <div v-if="groupedServicios.length === 0" class="infra-detail-empty">
        No hay rutas ni servicios asociados para esta cámara.
      </div>
      <div v-else class="infra-service-list-shell">
        <div class="infra-service-list-copy">
          <p class="infra-service-list-copy__eyebrow">Selección rápida</p>
          <p>La lista muestra únicamente los IDs de servicio asociados a la cámara. Hacé clic sobre uno para abrir el tracking en un modal superpuesto.</p>
        </div>

        <div class="infra-service-list">
          <button
            v-for="servicio in groupedServicios"
            :key="servicio.servicioId"
            class="infra-service-id-btn"
            type="button"
            @click="openServiceTracking(servicio.servicioId)"
          >
            {{ servicio.servicioId }}
          </button>
        </div>
      </div>
    </section>
  </dialog>

  <dialog ref="trackingDialogEl" class="infra-service-overlay" @click.self="closeServiceTracking">
    <section v-if="selectedServicio" class="infra-service-overlay__card" role="dialog" aria-modal="true">
      <header class="infra-service-overlay__header">
        <div>
          <p class="infra-service-overlay__eyebrow">Tracking del servicio</p>
          <h4>{{ selectedServicio.servicioId }}</h4>
        </div>
        <button class="close-btn" type="button" @click="closeServiceTracking">×</button>
      </header>

      <div class="infra-service-overlay__summary">
        <span>{{ selectedServicio.pelos }} pelo{{ selectedServicio.pelos !== 1 ? 's' : '' }}</span>
        <span>{{ selectedServicio.rutas.length }} ruta{{ selectedServicio.rutas.length !== 1 ? 's' : '' }}</span>
        <span>{{ selectedServicio.transitosTotales }} tránsito{{ selectedServicio.transitosTotales !== 1 ? 's' : '' }}</span>
      </div>

      <TrackingDetail
        :servicio-id="selectedServicio.servicioId"
        :rutas="selectedServicio.rutas"
        @error="handleTrackingError"
        @downloaded="handleTrackingDownloaded"
      />
    </section>
  </dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import TrackingDetail from './TrackingDetail.vue';

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
  open: boolean;
  camaraId: number | null;
  camaraNombre: string;
  rutas: RutaItem[];
}>();

const emit = defineEmits<{
  close: [];
  error: [message: string];
  downloaded: [filename: string];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const trackingDialogEl = ref<HTMLDialogElement | null>(null);
const activeServicioId = ref<string | null>(null);

const groupedServicios = computed(() => {
  const groups = new Map<string, RutaItem[]>();
  props.rutas.forEach((ruta) => {
    const current = groups.get(ruta.servicio_id) ?? [];
    current.push(ruta);
    groups.set(ruta.servicio_id, current);
  });
  return [...groups.entries()]
    .map(([servicioId, rutas]) => ({
      servicioId,
      rutas,
      pelos: rutas.length,
      rutasSecundarias: rutas.filter((ruta) => ruta.ruta_tipo !== 'PRINCIPAL').length,
      transitosTotales: rutas.reduce((total, ruta) => total + ruta.transitos_count, 0),
    }))
    .sort((left, right) => compareServicioIdsDesc(left.servicioId, right.servicioId));
});

const selectedServicio = computed(() => {
  return groupedServicios.value.find((servicio) => servicio.servicioId === activeServicioId.value) ?? null;
});

function compareServicioIdsDesc(left: string, right: string): number {
  const leftNumeric = Number(left);
  const rightNumeric = Number(right);
  const leftIsNumeric = Number.isFinite(leftNumeric);
  const rightIsNumeric = Number.isFinite(rightNumeric);

  if (leftIsNumeric && rightIsNumeric) {
    return rightNumeric - leftNumeric;
  }

  return right.localeCompare(left, 'es-AR', { numeric: true, sensitivity: 'base' });
}

function handleClose(): void {
  activeServicioId.value = null;
  trackingDialogEl.value?.close();
  dialogEl.value?.close();
  emit('close');
}

function openServiceTracking(servicioId: string): void {
  activeServicioId.value = servicioId;
}

function closeServiceTracking(): void {
  activeServicioId.value = null;
}

function handleTrackingError(message: string): void {
  emit('error', message);
}

function handleTrackingDownloaded(filename: string): void {
  emit('downloaded', filename);
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      activeServicioId.value = null;
      dialogEl.value?.showModal();
      return;
    }
    if (trackingDialogEl.value?.open) {
      trackingDialogEl.value.close();
    }
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
);

watch(
  selectedServicio,
  (servicio) => {
    if (servicio) {
      if (!trackingDialogEl.value?.open) {
        trackingDialogEl.value?.showModal();
      }
      return;
    }

    if (trackingDialogEl.value?.open) {
      trackingDialogEl.value.close();
    }
  },
);

watch(
  () => props.rutas,
  (rutas) => {
    if (!rutas.length) {
      activeServicioId.value = null;
      return;
    }
    if (activeServicioId.value && !groupedServicios.value.some((servicio) => servicio.servicioId === activeServicioId.value)) {
      activeServicioId.value = null;
    }
  },
  { immediate: true },
);
</script>

<style scoped>
.infra-detail-modal {
  position: relative;
  width: min(1024px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.infra-detail-modal::backdrop {
  background: rgba(4, 8, 14, 0.74);
  backdrop-filter: blur(8px);
}

.infra-detail-modal__content {
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--text);
  box-shadow: var(--shadow-lg);
}

.infra-detail-modal__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 20px;
}

.infra-detail-modal__header h3 {
  margin: 6px 0 0;
  font-size: 1.3rem;
}

.infra-detail-modal__eyebrow {
  margin: 0;
  color: var(--color-accent);
  font-size: 0.76rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.infra-service-list-shell {
  display: grid;
  gap: 18px;
}

.infra-service-list-copy {
  padding: 16px 18px;
  border-radius: 16px;
  border: 1px solid var(--color-divider);
  background: var(--color-bg);
  color: var(--muted);
}

.infra-service-list-copy__eyebrow,
.infra-service-overlay__eyebrow {
  margin: 0 0 8px;
  color: var(--color-accent);
  font-size: 0.72rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.infra-service-list-copy p:last-child {
  margin: 0;
}

.infra-service-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}

.infra-service-id-btn {
  min-height: 78px;
  border: 1px solid var(--color-divider);
  border-radius: 16px;
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 1.15rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.infra-service-id-btn:hover {
  transform: translateY(-2px);
  border-color: var(--color-accent);
  box-shadow: var(--shadow-sm);
}

.infra-service-id-btn:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}

.infra-service-overlay {
  width: min(1120px, calc(100vw - 48px));
  max-width: calc(100vw - 48px);
  background: transparent;
  border: none;
  padding: 0;
}

.infra-service-overlay::backdrop {
  background: rgba(4, 8, 14, 0.78);
  backdrop-filter: blur(10px);
}

.infra-service-overlay__card {
  width: 100%;
  max-height: calc(100vh - 48px);
  overflow: auto;
  border-radius: 20px;
  border: 1px solid var(--color-divider);
  background: var(--color-surface);
  color: var(--text);
  box-shadow: var(--shadow-lg);
  padding: 24px;
}

.infra-service-overlay__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.infra-service-overlay__header h4 {
  margin: 0;
  color: var(--color-text);
  font-size: 1.4rem;
}

.infra-service-overlay__summary {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.infra-service-overlay__summary span {
  border-radius: 999px;
  padding: 4px 10px;
  background: color-mix(in srgb, var(--color-neutral-400) 12%, transparent);
  color: var(--muted);
  font-size: 0.76rem;
}

.infra-detail-empty {
  padding: 18px;
  border-radius: 14px;
  border: 1px dashed var(--color-divider);
  color: var(--muted);
  background: var(--color-bg);
}

@media (max-width: 720px) {
  .infra-service-overlay {
    padding: 16px;
  }

  .infra-service-overlay__card {
    width: calc(100vw - 32px);
    max-height: calc(100vh - 32px);
    padding: 20px;
  }

  .infra-service-overlay__header {
    flex-direction: column;
  }
}
</style>