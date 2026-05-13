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
      <div v-else class="infra-service-groups">
        <article v-for="servicio in groupedServicios" :key="servicio.servicioId" class="infra-service-card">
          <button class="infra-service-toggle" type="button" @click="toggleServicio(servicio.servicioId)">
            <header class="infra-service-card__header">
              <div>
                <p>Servicio</p>
                <h4>{{ servicio.servicioId }}</h4>
              </div>
              <span class="infra-service-card__count">
                {{ servicio.rutas.length }} ruta{{ servicio.rutas.length !== 1 ? 's' : '' }}
                {{ expandedServicioId === servicio.servicioId ? '↑' : '↓' }}
              </span>
            </header>
          </button>

          <div class="infra-service-card__summary">
            <span>{{ servicio.pelos }} pelo{{ servicio.pelos !== 1 ? 's' : '' }}</span>
            <span>{{ servicio.rutasSecundarias }} camino{{ servicio.rutasSecundarias !== 1 ? 's' : '' }} secundario{{ servicio.rutasSecundarias !== 1 ? 's' : '' }}</span>
            <span>{{ servicio.transitosTotales }} tránsito{{ servicio.transitosTotales !== 1 ? 's' : '' }}</span>
          </div>

          <template v-if="expandedServicioId === servicio.servicioId">
            <ul class="infra-route-list">
              <li v-for="ruta in servicio.rutas" :key="ruta.ruta_id" class="infra-route-list__item">
                <div>
                  <strong>{{ ruta.ruta_nombre || `Ruta ${ruta.ruta_id}` }}</strong>
                  <p>{{ ruta.punta_a_sitio || 'Punta A pendiente' }} → {{ ruta.punta_b_sitio || 'Punta B pendiente' }}</p>
                </div>
                <div class="infra-route-list__meta">
                  <span :class="['infra-route-badge', badgeClass(ruta.ruta_tipo)]">{{ ruta.ruta_tipo }}</span>
                  <span v-if="ruta.alias_ids.length">Alias: {{ ruta.alias_ids.join(', ') }}</span>
                  <span>Tránsitos: {{ ruta.transitos_count }}</span>
                  <span class="tracking-link">Tracking en línea</span>
                </div>
              </li>
            </ul>

            <div class="infra-service-card__tracking">
              <TrackingDetail
                :servicio-id="servicio.servicioId"
                :rutas="servicio.rutas"
                @error="handleTrackingError"
                @downloaded="handleTrackingDownloaded"
              />
            </div>

            <div class="infra-service-card__footer">
              El detalle del tracking reutiliza la misma secuencia óptica y descarga TXT del flujo productivo actual.
            </div>
          </template>
        </article>
      </div>
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
const expandedServicioId = ref<string | null>(null);

const groupedServicios = computed(() => {
  const groups = new Map<string, RutaItem[]>();
  props.rutas.forEach((ruta) => {
    const current = groups.get(ruta.servicio_id) ?? [];
    current.push(ruta);
    groups.set(ruta.servicio_id, current);
  });
  return [...groups.entries()].map(([servicioId, rutas]) => ({
    servicioId,
    rutas,
    pelos: rutas.length,
    rutasSecundarias: rutas.filter((ruta) => ruta.ruta_tipo !== 'PRINCIPAL').length,
    transitosTotales: rutas.reduce((total, ruta) => total + ruta.transitos_count, 0),
  }));
});

function badgeClass(tipo: string): string {
  if (tipo === 'PRINCIPAL') return 'principal';
  if (tipo === 'BACKUP') return 'backup';
  return 'alternativa';
}

function handleClose(): void {
  dialogEl.value?.close();
  emit('close');
}

function toggleServicio(servicioId: string): void {
  expandedServicioId.value = expandedServicioId.value === servicioId ? null : servicioId;
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
      if (!expandedServicioId.value && groupedServicios.value.length > 0) {
        expandedServicioId.value = groupedServicios.value[0].servicioId;
      }
      dialogEl.value?.showModal();
      return;
    }
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
);

watch(
  () => props.rutas,
  (rutas) => {
    if (!rutas.length) {
      expandedServicioId.value = null;
      return;
    }
    if (!groupedServicios.value.some((servicio) => servicio.servicioId === expandedServicioId.value)) {
      expandedServicioId.value = groupedServicios.value[0]?.servicioId ?? null;
    }
  },
  { immediate: true },
);
</script>

<style scoped>
.infra-detail-modal {
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
  background: linear-gradient(180deg, rgba(17, 24, 39, 0.98), rgba(9, 14, 23, 0.98));
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 18px;
  padding: 24px;
  color: var(--text);
  box-shadow: 0 28px 60px rgba(0, 0, 0, 0.35);
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
  color: #fcd34d;
  font-size: 0.76rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.infra-service-groups {
  display: grid;
  gap: 16px;
}

.infra-service-card {
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 16px;
  padding: 18px;
  background: rgba(15, 23, 42, 0.75);
}

.infra-service-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 14px;
}

.infra-service-toggle {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  background: transparent;
  border: none;
  color: inherit;
  text-align: left;
  cursor: pointer;
  padding: 0;
}

.infra-service-toggle:hover .infra-service-card__count,
.infra-service-toggle:hover h4 {
  color: #f8fafc;
}

.infra-service-toggle:focus-visible {
  outline: 2px solid rgba(96, 165, 250, 0.6);
  outline-offset: 6px;
  border-radius: 12px;
}

.infra-service-card__header p,
.infra-route-list__item p {
  margin: 0;
  color: var(--muted);
}

.infra-service-card__header h4 {
  margin: 4px 0 0;
  font-size: 1.1rem;
}

.infra-service-card__count {
  color: #fef3c7;
  font-size: 0.84rem;
}

.infra-service-card__summary {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.infra-service-card__summary span {
  border-radius: 999px;
  padding: 4px 10px;
  background: rgba(148, 163, 184, 0.12);
  color: var(--muted);
  font-size: 0.76rem;
}

.infra-route-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 12px;
}

.infra-route-list__item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(9, 14, 23, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.1);
}

.infra-route-list__meta {
  display: grid;
  gap: 6px;
  justify-items: end;
  color: var(--muted);
  font-size: 0.82rem;
}

.infra-route-list__meta .tracking-link {
  justify-self: end;
}

.tracking-link {
  border-radius: 999px;
  padding: 6px 12px;
  border: 1px solid rgba(96, 165, 250, 0.28);
  background: rgba(59, 130, 246, 0.14);
  color: #dbeafe;
  font-size: 0.78rem;
  font-weight: 600;
}

.infra-route-badge {
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.infra-route-badge.principal {
  background: rgba(59, 130, 246, 0.18);
  color: #bfdbfe;
}

.infra-route-badge.backup {
  background: rgba(16, 185, 129, 0.18);
  color: #bbf7d0;
}

.infra-route-badge.alternativa {
  background: rgba(249, 115, 22, 0.18);
  color: #fed7aa;
}

.infra-detail-empty {
  padding: 18px;
  border-radius: 14px;
  border: 1px dashed rgba(148, 163, 184, 0.24);
  color: var(--muted);
  background: rgba(15, 23, 42, 0.45);
}

.infra-service-card__tracking {
  margin-top: 16px;
}

.infra-service-card__footer {
  margin-top: 12px;
  color: var(--muted);
  font-size: 0.78rem;
}

@media (max-width: 720px) {
  .infra-route-list__item {
    flex-direction: column;
  }

  .infra-route-list__meta {
    justify-items: start;
  }

  .infra-service-toggle {
    flex-direction: column;
  }
}
</style>