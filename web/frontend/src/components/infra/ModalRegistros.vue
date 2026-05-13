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

      <section v-if="contexto" class="infra-registros-section">
        <h4>Contexto operativo actual</h4>
        <div class="infra-registros-badges">
          <span class="infra-registro-pill">Actual: {{ contexto.estado_actual }}</span>
          <span class="infra-registro-pill">Sugerido: {{ contexto.estado_sugerido || contexto.estado_actual }}</span>
          <span class="infra-registro-pill">Baneo activo: {{ contexto.tiene_baneo_activo ? 'Sí' : 'No' }}</span>
          <span class="infra-registro-pill">Ingreso activo: {{ contexto.tiene_ingreso_activo ? 'Sí' : 'No' }}</span>
        </div>
      </section>

      <section class="infra-registros-section">
        <h4>Baneos relacionados</h4>
        <div v-if="baneos.length === 0" class="infra-detail-empty">Sin baneos relacionados para mostrar.</div>
        <ul v-else class="infra-detail-list">
          <li v-for="ban in baneos" :key="ban.id" class="infra-detail-list__item vertical">
            <div class="infra-detail-list__headline">
              <strong>{{ ban.ticket_asociado || `Incidente ${ban.id}` }}</strong>
              <span :class="['infra-state-chip', ban.activo ? 'danger' : 'ok']">{{ ban.activo ? 'Activo' : 'Cerrado' }}</span>
            </div>
            <span>Servicio protegido: {{ ban.servicio_protegido_id }}</span>
            <span>Ruta protegida: {{ ban.ruta_protegida_id ?? 'Todas' }}</span>
            <span>Inicio: {{ formatFecha(ban.fecha_inicio) }}</span>
            <span v-if="ban.fecha_fin">Fin: {{ formatFecha(ban.fecha_fin) }}</span>
            <span v-if="ban.motivo">Motivo: {{ ban.motivo }}</span>
          </li>
        </ul>
      </section>

      <section class="infra-registros-section">
        <h4>Auditoría de estado manual</h4>
        <div v-if="auditoria.length === 0" class="infra-detail-empty">No hay auditoría manual registrada.</div>
        <ul v-else class="infra-detail-list">
          <li v-for="item in auditoria" :key="item.id" class="infra-detail-list__item vertical">
            <div class="infra-detail-list__headline">
              <strong>{{ item.usuario }}</strong>
              <span>{{ formatFecha(item.created_at) }}</span>
            </div>
            <span>{{ item.estado_anterior }} → {{ item.estado_nuevo }}</span>
            <span v-if="item.estado_sugerido">Sugerido al momento: {{ item.estado_sugerido }}</span>
            <span>{{ item.motivo }}</span>
          </li>
        </ul>
      </section>

      <section class="infra-registros-section">
        <h4>Próxima iteración</h4>
        <div class="infra-placeholder-grid">
          <article class="infra-placeholder-card">
            <strong>Ingresos</strong>
            <p>{{ placeholders.ingresos }}</p>
          </article>
          <article class="infra-placeholder-card">
            <strong>Egresos</strong>
            <p>{{ placeholders.egresos }}</p>
          </article>
        </div>
      </section>
    </section>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

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

function formatFecha(value: string | null): string {
  if (!value) return 'Sin fecha';
  return new Date(value).toLocaleString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function handleClose(): void {
  dialogEl.value?.close();
  emit('close');
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      dialogEl.value?.showModal();
      return;
    }
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
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

.infra-registros-section + .infra-registros-section {
  margin-top: 24px;
}

.infra-registros-section h4 {
  margin: 0 0 12px;
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

.infra-detail-list__headline {
  width: 100%;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
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

.infra-placeholder-card {
  padding: 16px;
  border-radius: 14px;
  border: 1px dashed rgba(148, 163, 184, 0.24);
  background: rgba(15, 23, 42, 0.45);
}

.infra-placeholder-card p {
  margin: 8px 0 0;
  color: var(--muted);
}
</style>