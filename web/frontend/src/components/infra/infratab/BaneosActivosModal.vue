<!--
  Nombre de archivo: BaneosActivosModal.vue
  Ubicación de archivo: web/frontend/src/components/infra/infratab/BaneosActivosModal.vue
  Descripción: Modal de InfraTab con los baneos activos: lista, levantar baneo y apertura del aviso por email
-->
<template>
  <dialog ref="activeBansModalEl" class="infra-generic-modal active-bans-modal" @click.self="cerrar()" @cancel.prevent="cerrar()">
    <div class="modal-inner">
      <div class="modal-header-row">
        <h3 class="modal-title">🔒 Baneos Activos</h3>
        <button class="close-btn" @click="cerrar()">×</button>
      </div>

      <!-- Cargando -->
      <div v-if="activeBansLoading" class="active-bans-loading">Cargando baneos activos...</div>

      <!-- Error -->
      <div v-else-if="activeBansError" class="active-bans-error">⚠ {{ activeBansError }}</div>

      <!-- Sin baneos -->
      <div v-else-if="activeBans.length === 0" class="active-bans-empty">
        <span>✅ No hay baneos activos en este momento.</span>
      </div>

      <!-- Lista de incidentes -->
      <template v-else>
        <div class="active-bans-count">{{ activeBans.length }} incidente{{ activeBans.length !== 1 ? 's' : '' }} activo{{ activeBans.length !== 1 ? 's' : '' }}</div>
        <div class="active-bans-list">
          <div v-for="inc in activeBans" :key="inc.id" class="active-ban-card">
            <div class="active-ban-card-header">
              <div class="active-ban-ticket">
                <span class="active-ban-ticket-label">Ticket</span>
                <strong>{{ inc.ticket_asociado || '—' }}</strong>
              </div>
              <div class="active-ban-duracion">{{ formatDuracion(inc.duracion_horas) }}</div>
            </div>
            <div class="active-ban-servicios">
              <span class="active-ban-svc-item afectado">
                <span class="active-ban-svc-dot afectado"></span>
                Afectado: <strong>{{ inc.servicio_afectado_id }}</strong>
              </span>
              <span class="active-ban-arrow">→</span>
              <span class="active-ban-svc-item protegido">
                <span class="active-ban-svc-dot protegido"></span>
                Protegido: <strong>{{ inc.servicio_protegido_id }}</strong>
              </span>
            </div>
            <div v-if="inc.ruta_protegida_id" class="active-ban-ruta">
              Ruta: <span>ID {{ inc.ruta_protegida_id }}</span>
            </div>
            <div v-if="inc.motivo" class="active-ban-motivo">{{ inc.motivo }}</div>
            <div class="active-ban-meta">
              <span>Inicio: {{ formatFecha(inc.fecha_inicio) }}</span>
              <span v-if="inc.camaras_count">· {{ inc.camaras_count }} cámara{{ inc.camaras_count !== 1 ? 's' : '' }}</span>
              <span v-if="inc.usuario_ejecutor">· por {{ inc.usuario_ejecutor }}</span>
            </div>
            <div class="active-ban-actions">
              <button
                class="btn warning small"
                @click="abrirAviso(inc)"
              >📧 Dar Aviso</button>
              <button
                class="btn success small"
                :disabled="liftLoadingId === inc.id"
                @click="confirmLiftBan(inc)"
              >{{ liftLoadingId === inc.id ? 'Levantando...' : '🔓 Levantar Baneo' }}</button>
            </div>
          </div>
        </div>
      </template>

      <div class="modal-actions" style="margin-top:8px">
        <button class="btn subtle" @click="cerrar()">Cerrar</button>
        <button class="btn primary small" :disabled="activeBansLoading" @click="loadActiveBans">↻ Actualizar</button>
      </div>
    </div>
  </dialog>

  <!-- Sub-modal: Dar Aviso por email -->
  <AvisoEmailModal ref="avisoEmailModal" :notificar="notificar" />
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import type { IncidenteActivo } from '../../../api/infra';
import type { Notificar } from '../../../composables/infra/tipos';
import { useBaneosActivos } from '../../../composables/infra/useBaneosActivos';
import AvisoEmailModal from './AvisoEmailModal.vue';

const props = defineProps<{ notificar: Notificar }>();
const emit = defineEmits<{
  'baneo-levantado': [];
  // Cantidad de baneos de la última carga, para el badge del botón de InfraTab.
  'cantidad-cambiada': [cantidad: number];
}>();

const {
  activeBansModalEl,
  activeBans,
  activeBansLoading,
  activeBansError,
  liftLoadingId,
  loadActiveBans,
  abrir,
  cerrar,
  confirmLiftBan,
  formatDuracion,
  formatFecha,
} = useBaneosActivos(props.notificar, () => emit('baneo-levantado'));

watch(() => activeBans.value.length, (n) => emit('cantidad-cambiada', n));

// --- Sub-modal Dar Aviso ---
const avisoEmailModal = ref<InstanceType<typeof AvisoEmailModal> | null>(null);
function abrirAviso(inc: IncidenteActivo) {
  avisoEmailModal.value?.abrir(inc);
}

defineExpose({ abrir });
</script>

<style scoped src="./infra-modal.css"></style>

<style scoped>
.btn.success { background: transparent; color: var(--color-state-ok); border: 1px solid color-mix(in srgb, var(--color-state-ok) 50%, transparent); }
.btn.success:hover:not(:disabled) { background: color-mix(in srgb, var(--color-state-ok) 12%, transparent); }
.active-bans-loading, .active-bans-empty {
  padding: 20px 0; text-align: center; color: var(--muted); font-size: .88rem;
}
.active-bans-error { color: var(--color-state-error); font-size: .85rem; padding: 8px 0; }
.active-bans-count { font-size: .8rem; color: var(--muted); margin-bottom: 10px; }
.active-bans-list { display: flex; flex-direction: column; gap: 10px; max-height: 60vh; overflow-y: auto; }
.active-ban-card {
  background: color-mix(in srgb, var(--color-text) 4%, transparent); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column; gap: 6px;
}
.active-ban-card-header { display: flex; justify-content: space-between; align-items: flex-start; }
.active-ban-ticket { display: flex; flex-direction: column; gap: 2px; }
.active-ban-ticket-label { font-size: .72rem; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.active-ban-duracion {
  font-size: .78rem; font-weight: 600; color: var(--color-state-warn);
  background: color-mix(in srgb, var(--color-state-warn) 10%, transparent); padding: 2px 8px; border-radius: 10px;
  white-space: nowrap; align-self: flex-start;
}
.active-ban-servicios { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: .85rem; }
.active-ban-svc-item { display: flex; align-items: center; gap: 5px; }
.active-ban-svc-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.active-ban-svc-dot.afectado { background: var(--color-state-warn); }
.active-ban-svc-dot.protegido { background: var(--color-state-error); }
.active-ban-arrow { color: var(--muted); font-size: .9rem; }
.active-ban-ruta { font-size: .8rem; color: var(--muted); }
.active-ban-motivo { font-size: .83rem; color: var(--text); font-style: italic; border-left: 2px solid var(--border); padding-left: 8px; }
.active-ban-meta { display: flex; flex-wrap: wrap; gap: 8px; font-size: .78rem; color: var(--muted); }
.active-ban-actions { display: flex; gap: 8px; margin-top: 4px; flex-wrap: wrap; }
</style>
