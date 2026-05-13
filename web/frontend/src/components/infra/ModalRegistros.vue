<!--
  Nombre de archivo: ModalRegistros.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalRegistros.vue
  Descripción: Modal aislado para visualizar registros operativos e históricos parciales de una cámara
-->
<template>
  <dialog ref="dialogEl" class="infra-detail-modal" @click.self="handleClose">
    <section class="infra-detail-modal__content">
      <header class="infra-detail-modal__header">
        <div>
          <p class="infra-detail-modal__eyebrow">Registros</p>
          <h3>{{ camaraNombre }} · ID {{ camaraId ?? '—' }}</h3>
        </div>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </header>

      <section v-if="contexto" class="infra-registros-overview">
        <div class="infra-registros-overview__header">
          <div>
            <p class="infra-registros-overview__eyebrow">Contexto operativo</p>
            <h4>Estado actual de la cámara</h4>
          </div>
          <span :class="['infra-state-chip', contexto.tiene_baneo_activo ? 'danger' : 'ok']">
            {{ contexto.tiene_baneo_activo ? 'Baneo activo' : 'Sin baneo activo' }}
          </span>
        </div>
        <div class="infra-registros-badges">
          <span class="infra-registro-pill">Actual: {{ contexto.estado_actual }}</span>
          <span class="infra-registro-pill">Sugerido: {{ contexto.estado_sugerido || contexto.estado_actual }}</span>
          <span class="infra-registro-pill">Ingreso activo: {{ contexto.tiene_ingreso_activo ? 'Sí' : 'No' }}</span>
        </div>
      </section>

      <nav class="infra-registros-tabs" aria-label="Categorías de registros">
        <button
          :class="['infra-registros-tab', { active: activeTab === 'ingresos' }]"
          type="button"
          :aria-pressed="activeTab === 'ingresos'"
          @click="activeTab = 'ingresos'"
        >
          Ingresos
          <span class="infra-registros-tab__hint">Próximamente</span>
        </button>
        <button
          :class="['infra-registros-tab', { active: activeTab === 'baneos' }]"
          type="button"
          :aria-pressed="activeTab === 'baneos'"
          @click="activeTab = 'baneos'"
        >
          Baneos
          <span class="infra-registros-tab__hint">{{ sortedBaneos.length }} historial{{ sortedBaneos.length !== 1 ? 'es' : '' }}</span>
        </button>
      </nav>

      <section v-if="activeTab === 'ingresos'" class="infra-registros-section">
        <div class="infra-tab-intro">
          <div>
            <p class="infra-tab-intro__eyebrow">Vista estructural</p>
            <h4>Ingresos listos para hidratar</h4>
          </div>
          <span class="infra-future-chip">Backend pendiente</span>
        </div>

        <div v-if="sortedIngresos.length === 0" class="infra-detail-empty">
          <strong>Sin ingresos disponibles todavía.</strong>
          <p>{{ placeholders.ingresos }}</p>
          <p>{{ placeholders.egresos }}</p>
        </div>

        <div v-else class="infra-baneos-list">
          <AccordionItem
            v-for="ingreso in sortedIngresos"
            :key="ingreso.id"
            :model-value="expandedIngresoId === ingreso.id"
            :title="buildIngresoRangeTitle(ingreso)"
            @update:model-value="toggleIngreso(ingreso.id, $event)"
          >
            <dl class="infra-baneo-detail-grid">
              <div class="infra-baneo-detail-row full-width">
                <dt>Técnico solicitante</dt>
                <dd>{{ ingreso.tecnico_solicitante || 'Pendiente de hidratar desde backend.' }}</dd>
              </div>
            </dl>
          </AccordionItem>
        </div>
      </section>

      <section v-else class="infra-registros-section">
        <div class="infra-tab-intro">
          <div>
            <p class="infra-tab-intro__eyebrow">Historial técnico</p>
            <h4>Baneos ordenados del más reciente al más antiguo</h4>
          </div>
          <span class="infra-history-chip">{{ sortedBaneos.length }} registro{{ sortedBaneos.length !== 1 ? 's' : '' }}</span>
        </div>

        <div v-if="sortedBaneos.length === 0" class="infra-detail-empty">Sin baneos relacionados para mostrar.</div>
        <div v-else class="infra-baneos-list">
          <AccordionItem
            v-for="ban in sortedBaneos"
            :key="ban.id"
            :model-value="expandedBaneoId === ban.id"
            :title="buildBaneoRangeTitle(ban)"
            @update:model-value="toggleBaneo(ban.id, $event)"
          >
            <dl class="infra-baneo-detail-grid">
              <div class="infra-baneo-detail-row">
                <dt>Inicio</dt>
                <dd>{{ formatFechaCompleta(ban.fecha_inicio) }}</dd>
              </div>
              <div class="infra-baneo-detail-row">
                <dt>Fin</dt>
                <dd>{{ ban.fecha_fin ? formatFechaCompleta(ban.fecha_fin) : 'En curso' }}</dd>
              </div>
              <div class="infra-baneo-detail-row">
                <dt>Ticket</dt>
                <dd>{{ ban.ticket_asociado || `Incidente ${ban.id}` }}</dd>
              </div>
              <div class="infra-baneo-detail-row">
                <dt>Estado del baneo</dt>
                <dd>{{ ban.activo ? 'Activo' : 'Cerrado' }}</dd>
              </div>
              <div class="infra-baneo-detail-row">
                <dt>Servicio protegido</dt>
                <dd>{{ ban.servicio_protegido_id }}</dd>
              </div>
              <div class="infra-baneo-detail-row full-width">
                <dt>Motivo</dt>
                <dd>{{ ban.motivo || 'Sin motivo registrado.' }}</dd>
              </div>
            </dl>
          </AccordionItem>
        </div>

        <section class="infra-registros-auditoria">
          <div class="infra-tab-intro compact">
            <div>
              <p class="infra-tab-intro__eyebrow">Trazabilidad auxiliar</p>
              <h4>Auditoría manual de estado</h4>
            </div>
          </div>
          <div v-if="auditoria.length === 0" class="infra-detail-empty">No hay auditoría manual registrada.</div>
          <ul v-else class="infra-detail-list">
            <li v-for="item in auditoriaOrdenada" :key="item.id" class="infra-detail-list__item vertical compact">
              <div class="infra-detail-list__headline wrap">
                <strong>{{ item.usuario }}</strong>
                <span>{{ formatFechaCompleta(item.created_at) }}</span>
              </div>
              <span>{{ item.estado_anterior }} → {{ item.estado_nuevo }}</span>
              <span v-if="item.estado_sugerido">Sugerido al momento: {{ item.estado_sugerido }}</span>
              <span>{{ item.motivo }}</span>
            </li>
          </ul>
        </section>
      </section>
    </section>
  </dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import AccordionItem from './AccordionItem.vue';

interface ContextoRegistros {
  estado_actual: string;
  estado_sugerido: string | null;
  tiene_baneo_activo: boolean;
  tiene_ingreso_activo: boolean;
}

interface BaneoItem {
  id: number;
  ticket_asociado: string | null;
  servicio_protegido_id: string;
  ruta_protegida_id: number | null;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  motivo: string | null;
  activo: boolean;
}

interface AuditoriaItem {
  id: number;
  usuario: string;
  motivo: string;
  estado_anterior: string | null;
  estado_nuevo: string | null;
  estado_sugerido: string | null;
  created_at: string | null;
}

interface IngresoItem {
  id: number;
  fecha_ingreso: string | null;
  fecha_egreso: string | null;
  tecnico_solicitante: string | null;
}

const props = defineProps<{
  open: boolean;
  camaraId: number | null;
  camaraNombre: string;
  contexto: ContextoRegistros | null;
  baneos: BaneoItem[];
  auditoria: AuditoriaItem[];
  placeholders: { ingresos: string; egresos: string };
}>();

const emit = defineEmits<{ close: [] }>();
const dialogEl = ref<HTMLDialogElement | null>(null);
const activeTab = ref<'ingresos' | 'baneos'>('baneos');
const expandedBaneoId = ref<number | null>(null);
const expandedIngresoId = ref<number | null>(null);
const ingresos = ref<IngresoItem[]>([]);

const sortedBaneos = computed(() => {
  return [...props.baneos].sort((left, right) => getTimestamp(right.fecha_inicio) - getTimestamp(left.fecha_inicio));
});

const sortedIngresos = computed(() => {
  return [...ingresos.value].sort((left, right) => getTimestamp(right.fecha_ingreso) - getTimestamp(left.fecha_ingreso));
});

const auditoriaOrdenada = computed(() => {
  return [...props.auditoria].sort((left, right) => getTimestamp(right.created_at) - getTimestamp(left.created_at));
});

function getTimestamp(value: string | null): number {
  if (!value) return 0;
  const timestamp = new Date(value).getTime();
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function formatFechaCompleta(value: string | null): string {
  if (!value) return 'Sin fecha';
  return new Date(value).toLocaleString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatFechaCompacta(value: string | null): string {
  if (!value) return 'Sin fecha';
  return new Date(value).toLocaleString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function buildBaneoRangeTitle(item: BaneoItem): string {
  const inicio = formatFechaCompacta(item.fecha_inicio);
  const fin = item.fecha_fin ? formatFechaCompacta(item.fecha_fin) : 'En curso';
  return `${inicio} - ${fin}`;
}

function buildIngresoRangeTitle(item: IngresoItem): string {
  const ingreso = formatFechaCompacta(item.fecha_ingreso);
  const egreso = item.fecha_egreso ? formatFechaCompacta(item.fecha_egreso) : 'Pendiente';
  return `Ingreso - ${ingreso} * Egreso - ${egreso}`;
}

function toggleBaneo(id: number, nextValue: boolean): void {
  expandedBaneoId.value = nextValue ? id : null;
}

function toggleIngreso(id: number, nextValue: boolean): void {
  expandedIngresoId.value = nextValue ? id : null;
}

function handleClose(): void {
  dialogEl.value?.close();
  emit('close');
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      activeTab.value = 'baneos';
      expandedBaneoId.value = null;
      expandedIngresoId.value = null;
      dialogEl.value?.showModal();
      return;
    }
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
);

watch(
  sortedBaneos,
  (items) => {
    if (expandedBaneoId.value != null && !items.some((item) => item.id === expandedBaneoId.value)) {
      expandedBaneoId.value = null;
    }
  },
  { immediate: true },
);

watch(
  sortedIngresos,
  (items) => {
    if (expandedIngresoId.value != null && !items.some((item) => item.id === expandedIngresoId.value)) {
      expandedIngresoId.value = null;
    }
  },
  { immediate: true },
);
</script>

<style scoped>
.infra-detail-modal {
  width: min(860px, calc(100vw - 32px));
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
  color: #c4b5fd;
  font-size: 0.76rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.infra-registros-overview {
  margin-bottom: 18px;
  padding: 18px;
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: linear-gradient(160deg, rgba(15, 23, 42, 0.88), rgba(11, 18, 32, 0.94));
}

.infra-registros-overview__header,
.infra-tab-intro {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.infra-registros-overview__header {
  margin-bottom: 14px;
}

.infra-registros-overview__header h4,
.infra-tab-intro h4 {
  margin: 4px 0 0;
  color: #f8fafc;
}

.infra-registros-overview__eyebrow,
.infra-tab-intro__eyebrow {
  margin: 0;
  color: #7dd3fc;
  font-size: 0.72rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.infra-registros-section + .infra-registros-section {
  margin-top: 24px;
}

.infra-registros-section {
  display: grid;
  gap: 16px;
}

.infra-registros-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.infra-registros-tab {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.56);
  color: #cbd5e1;
  cursor: pointer;
  transition: border-color 0.18s ease, transform 0.18s ease, background 0.18s ease;
}

.infra-registros-tab:hover {
  transform: translateY(-1px);
  border-color: rgba(96, 165, 250, 0.3);
}

.infra-registros-tab.active {
  border-color: rgba(96, 165, 250, 0.42);
  background: linear-gradient(160deg, rgba(30, 41, 59, 0.98), rgba(15, 23, 42, 0.9));
  color: #f8fafc;
  box-shadow: 0 18px 40px rgba(2, 6, 23, 0.18);
}

.infra-registros-tab__hint,
.infra-history-chip,
.infra-future-chip {
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 0.72rem;
  font-weight: 700;
}

.infra-registros-tab__hint {
  background: rgba(148, 163, 184, 0.14);
  color: var(--muted);
}

.infra-history-chip {
  background: rgba(96, 165, 250, 0.16);
  color: #dbeafe;
}

.infra-future-chip {
  background: rgba(250, 204, 21, 0.14);
  color: #fde68a;
}

.infra-registros-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.infra-registro-pill {
  border-radius: 999px;
  padding: 6px 12px;
  background: rgba(76, 29, 149, 0.28);
  border: 1px solid rgba(196, 181, 253, 0.2);
  color: #e9d5ff;
  font-size: 0.82rem;
}

.infra-baneos-list {
  display: grid;
  gap: 12px;
}

.infra-baneo-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.infra-baneo-detail-row {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(9, 14, 23, 0.82);
  border: 1px solid rgba(148, 163, 184, 0.12);
}

.infra-baneo-detail-row.full-width {
  grid-column: 1 / -1;
}

.infra-baneo-detail-row dt {
  color: #7dd3fc;
  font-size: 0.74rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.infra-baneo-detail-row dd {
  margin: 0;
  color: #e2e8f0;
  line-height: 1.45;
}

.infra-registros-auditoria {
  margin-top: 8px;
  display: grid;
  gap: 12px;
}

.infra-tab-intro.compact {
  margin-bottom: -2px;
}

.infra-detail-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 12px;
}

.infra-detail-list__item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.14);
}

.infra-detail-list__item.vertical {
  flex-direction: column;
  align-items: flex-start;
}

.infra-detail-list__item.compact {
  gap: 8px;
}

.infra-detail-list__headline {
  width: 100%;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.infra-detail-list__headline.wrap {
  flex-wrap: wrap;
}

.infra-detail-empty {
  padding: 18px;
  border-radius: 14px;
  border: 1px dashed rgba(148, 163, 184, 0.24);
  color: var(--muted);
  background: rgba(15, 23, 42, 0.45);
}

.infra-state-chip {
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 0.72rem;
  font-weight: 700;
}

.infra-state-chip.ok {
  background: rgba(16, 185, 129, 0.18);
  color: #bbf7d0;
}

.infra-state-chip.danger {
  background: rgba(239, 68, 68, 0.18);
  color: #fecaca;
}

.infra-placeholder-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.infra-detail-empty strong {
  display: block;
  margin-bottom: 8px;
  color: #f8fafc;
}

.infra-detail-empty p + p {
  margin-top: 10px;
}

@media (max-width: 720px) {
  .infra-registros-tabs {
    grid-template-columns: 1fr;
  }

  .infra-registros-overview__header,
  .infra-tab-intro,
  .infra-detail-list__headline {
    flex-direction: column;
    align-items: flex-start;
  }

  .infra-baneo-detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>