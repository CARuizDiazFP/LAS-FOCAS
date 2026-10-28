<!--
  Nombre de archivo: BaneoWizardModal.vue
  Ubicación de archivo: web/frontend/src/components/infra/infratab/BaneoWizardModal.vue
  Descripción: Modal del Protocolo de Protección de InfraTab — wizard de 3 pasos para dar de alta un baneo
-->
<template>
  <dialog
    ref="banModalEl"
    class="infra-generic-modal ban-wizard-modal"
    @click.self="cerrar()"
    @cancel.prevent="cerrar()"
  >
    <div class="modal-inner">

      <!-- Header fijo -->
      <div class="modal-header-row">
        <h3 class="modal-title">🔴 Protocolo de Protección</h3>
        <button class="close-btn" :disabled="banLoading" @click="cerrar()">×</button>
      </div>

      <!-- Stepper visual -->
      <div class="wizard-stepper">
        <div v-for="(label, i) in ['Identificación', 'Selección', 'Confirmación']" :key="i" class="wizard-step-row">
          <div :class="['wizard-step-item', { active: currentBanStep === i + 1, done: currentBanStep > i + 1 }]">
            <span class="wizard-step-num">{{ currentBanStep > i + 1 ? '✓' : i + 1 }}</span>
            <span class="wizard-step-label">{{ label }}</span>
          </div>
          <div v-if="i < 2" class="wizard-step-connector"></div>
        </div>
      </div>

      <!-- ─── PASO 1: Identificación ─── -->
      <template v-if="currentBanStep === 1">
        <label class="form-label">Ticket del incidente (opcional)</label>
        <input v-model="banForm.ticket_asociado" type="text" placeholder="INC0012345" />
        <label class="form-label">Servicio afectado (el que se cortó) <span class="req">*</span></label>
        <input
          v-model="banForm.servicio_afectado_id"
          type="text"
          placeholder="Ej: 52547"
          @keydown.enter.prevent="banGoNext"
        />
        <label class="form-label">Motivo (opcional)</label>
        <textarea v-model="banForm.motivo" rows="2" placeholder="Corte de fibra en Av. Corrientes..."></textarea>
        <div class="modal-actions">
          <button class="btn subtle" @click="cerrar()">Cancelar</button>
          <button
            class="btn primary"
            :disabled="!banForm.servicio_afectado_id.trim()"
            @click="banGoNext"
          >Siguiente →</button>
        </div>
      </template>

      <!-- ─── PASO 2: Selección del objetivo ─── -->
      <template v-else-if="currentBanStep === 2">
        <div class="ban-step2-affected">
          Servicio afectado: <strong>{{ banForm.servicio_afectado_id }}</strong>
        </div>

        <!-- Tabs: mismo / otro servicio -->
        <div class="ban-prot-tabs">
          <button
            :class="['ban-prot-tab', { active: banProtMode === 'same' }]"
            @click="banSwitchMode('same')"
          >Proteger el mismo servicio</button>
          <button
            :class="['ban-prot-tab', { active: banProtMode === 'other' }]"
            @click="banSwitchMode('other')"
          >Otro servicio (redundancia cruzada)</button>
        </div>

        <!-- Input solo para "otro servicio" -->
        <template v-if="banProtMode === 'other'">
          <label class="form-label">ID del servicio a proteger <span class="req">*</span></label>
          <div class="ban-search-row">
            <input
              v-model="banSearchServicioInput"
              type="text"
              placeholder="Ej: 52548"
              @keydown.enter.prevent="loadRutasForBan(banSearchServicioInput.trim())"
            />
            <button
              class="btn primary"
              :disabled="banLoadingRutas || !banSearchServicioInput.trim()"
              @click="loadRutasForBan(banSearchServicioInput.trim())"
            >{{ banLoadingRutas ? '...' : 'Buscar rutas' }}</button>
          </div>
        </template>

        <!-- Error de carga de rutas -->
        <div v-if="banRutasError" class="ban-rutas-error">⚠ {{ banRutasError }}</div>

        <!-- Grilla de rutas -->
        <template v-if="banRutas.length > 0">
          <label class="form-label" style="margin-top: 10px;">Ruta a proteger</label>
          <div class="ban-ruta-grid">
            <!-- Opción "Todas las rutas activas" -->
            <div
              :class="['ban-ruta-card', 'all-option', { selected: banSelectedRutaId === null }]"
              @click="banSelectedRutaId = null"
            >
              <span class="ban-ruta-icon">📡</span>
              <div>
                <div class="ban-ruta-nombre">Todas las rutas activas</div>
                <div class="ban-ruta-meta">{{ banRutas.filter(r => r.activa).length }} caminos · ~{{ banEstimatedCamaras }} empalmes</div>
              </div>
            </div>
            <!-- Una tarjeta por ruta -->
            <div
              v-for="ruta in banRutas"
              :key="ruta.id"
              :class="['ban-ruta-card', { selected: banSelectedRutaId === ruta.id }]"
              @click="banSelectedRutaId = ruta.id"
            >
              <span class="ban-ruta-icon">{{ ruta.tipo === 'PRINCIPAL' ? '🔵' : ruta.tipo === 'BACKUP' ? '🟡' : '🟣' }}</span>
              <div>
                <div class="ban-ruta-nombre">{{ ruta.nombre }}</div>
                <div class="ban-ruta-meta">{{ ruta.tipo }} · {{ ruta.empalmes_count }} empalmes{{ !ruta.activa ? ' · INACTIVA' : '' }}</div>
                <!-- Alerta tracking desactualizado -->
                <div v-if="ruta.hash_contenido === null && banSelectedRutaId === ruta.id" class="ban-tracking-alert">
                  ⚠ Sin tracking guardado para esta ruta.
                  <div class="ban-tracking-alert-actions">
                    <button class="btn subtle small" @click.stop="downloadTrackingByRutaId(ruta.id)">📄 Descargar TXT</button>
                    <button class="btn warning small" @click.stop="actualizarTracking()">⬆ Actualizar Tracking</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>
        <div v-else-if="!banLoadingRutas && !banRutasError && banRutas.length === 0 && banForm.servicio_protegido_id" class="ban-rutas-empty">
          Sin rutas registradas para este servicio.
        </div>

        <div class="modal-actions">
          <button class="btn subtle" @click="banGoPrev">← Anterior</button>
          <button
            class="btn primary"
            :disabled="!banForm.servicio_protegido_id.trim() || banLoadingRutas"
            @click="banGoNext"
          >Siguiente →</button>
        </div>
      </template>

      <!-- ─── PASO 3: Confirmación ─── -->
      <template v-else-if="currentBanStep === 3">
        <div class="ban-summary-block">
          <div class="ban-summary-row"><span class="ban-summary-label">Ticket</span><span>{{ banForm.ticket_asociado || '—' }}</span></div>
          <div class="ban-summary-row"><span class="ban-summary-label">Servicio afectado</span><strong>{{ banForm.servicio_afectado_id }}</strong></div>
          <div class="ban-summary-row"><span class="ban-summary-label">Servicio a proteger</span><strong>{{ banForm.servicio_protegido_id }}</strong></div>
          <div class="ban-summary-row">
            <span class="ban-summary-label">Ruta</span>
            <span>{{ banSelectedRutaId === null ? 'Todas las rutas activas' : (banRutas.find(r => r.id === banSelectedRutaId)?.nombre ?? '—') }}</span>
          </div>
          <div class="ban-summary-row"><span class="ban-summary-label">Empalmes estimados</span><strong>~{{ banEstimatedCamaras }}</strong></div>
          <div v-if="banForm.motivo" class="ban-summary-row"><span class="ban-summary-label">Motivo</span><span>{{ banForm.motivo }}</span></div>
        </div>
        <label class="ban-confirm-row">
          <input v-model="banConfirmChecked" type="checkbox" />
          <span>Confirmo que entiendo que las cámaras de este servicio serán <strong>bloqueadas</strong></span>
        </label>
        <div class="modal-actions">
          <button class="btn subtle" :disabled="banLoading" @click="banGoPrev">← Anterior</button>
          <button
            class="btn danger"
            :disabled="banLoading || !banConfirmChecked"
            @click="submitBan"
          >{{ banLoading ? 'Activando...' : '🚨 EJECUTAR BANEO' }}</button>
        </div>
      </template>

    </div>
  </dialog>
</template>

<script setup lang="ts">
import type { Notificar } from '../../../composables/infra/tipos';
import { useBaneoWizard } from '../../../composables/infra/useBaneoWizard';

const props = defineProps<{ notificar: Notificar }>();
const emit = defineEmits<{
  'baneo-creado': [];
  'subir-tracking': [];
}>();

const {
  banModalEl,
  banLoading,
  currentBanStep,
  banProtMode,
  banSearchServicioInput,
  banRutas,
  banLoadingRutas,
  banRutasError,
  banSelectedRutaId,
  banConfirmChecked,
  banForm,
  banEstimatedCamaras,
  abrir,
  cerrar,
  ocultar,
  loadRutasForBan,
  banSwitchMode,
  banGoNext,
  banGoPrev,
  downloadTrackingByRutaId,
  submitBan,
} = useBaneoWizard(props.notificar, () => emit('baneo-creado'));

// "Actualizar Tracking": cierra el wizard (sin resetearlo) y le pide a InfraTab que abra el selector
// de archivo del flujo de tracking. El emit es sincrónico, así que el click() del input oculto sigue
// dentro del gesto del usuario.
function actualizarTracking() {
  ocultar();
  emit('subir-tracking');
}

defineExpose({ abrir });
</script>

<style scoped src="./infra-modal.css"></style>

<style scoped>
.wizard-stepper {
  display: flex; align-items: center; gap: 0; margin: 4px 0 18px;
}
.wizard-step-row { display: flex; align-items: center; flex: 1; }
.wizard-step-row:last-child { flex: 0; }
.wizard-step-item {
  display: flex; align-items: center; gap: 6px; flex-shrink: 0;
}
.wizard-step-num {
  width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-size: .75rem; font-weight: 700; border: 1.5px solid var(--border); color: var(--muted); background: transparent;
  flex-shrink: 0;
}
.wizard-step-label { font-size: .78rem; color: var(--muted); white-space: nowrap; }
.wizard-step-item.active .wizard-step-num { border-color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 15%, transparent); color: var(--color-accent); }
.wizard-step-item.active .wizard-step-label { color: var(--color-accent); font-weight: 600; }
.wizard-step-item.done .wizard-step-num { border-color: var(--color-state-ok); background: color-mix(in srgb, var(--color-state-ok) 15%, transparent); color: var(--color-state-ok); }
.wizard-step-item.done .wizard-step-label { color: var(--color-state-ok); }
.wizard-step-connector { flex: 1; height: 1px; background: var(--border); margin: 0 6px; }

/* Paso 2 */
.ban-step2-affected {
  font-size: .84rem; color: var(--muted); padding: 6px 10px;
  background: color-mix(in srgb, var(--color-text) 4%, transparent); border-radius: 6px; margin-bottom: 10px;
}
.ban-prot-tabs { display: flex; gap: 0; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin-bottom: 10px; }
.ban-prot-tab {
  flex: 1; padding: 8px 10px; font-size: .82rem; cursor: pointer; text-align: center;
  background: transparent; color: var(--muted); border: none; transition: background .15s;
}
.ban-prot-tab:hover { background: color-mix(in srgb, var(--color-text) 6%, transparent); }
.ban-prot-tab.active { background: color-mix(in srgb, var(--color-accent) 12%, transparent); color: var(--color-accent); font-weight: 600; }
.ban-search-row { display: flex; gap: 8px; margin-bottom: 4px; }
.ban-search-row input { flex: 1; }
.ban-rutas-error { font-size: .83rem; color: var(--color-state-error); padding: 6px 0; }
.ban-rutas-empty { font-size: .83rem; color: var(--muted); padding: 10px 0; text-align: center; }
.ban-ruta-grid { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.ban-ruta-card {
  display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px;
  background: color-mix(in srgb, var(--color-text) 4%, transparent); border: 1.5px solid var(--border);
  border-radius: 8px; cursor: pointer; transition: border-color .15s, background .15s;
}
.ban-ruta-card:hover { background: color-mix(in srgb, var(--color-text) 7%, transparent); border-color: color-mix(in srgb, var(--color-accent) 40%, transparent); }
.ban-ruta-card.selected { border-color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 8%, transparent); }
.ban-ruta-card.all-option { border-style: dashed; }
.ban-ruta-icon { font-size: 1.1rem; padding-top: 1px; flex-shrink: 0; }
.ban-ruta-nombre { font-size: .88rem; font-weight: 600; color: var(--text); }
.ban-ruta-meta { font-size: .78rem; color: var(--muted); margin-top: 2px; }
.ban-tracking-alert {
  margin-top: 6px; padding: 6px 8px; border-radius: 6px; font-size: .78rem;
  background: color-mix(in srgb, var(--color-state-warn) 12%, transparent); color: var(--color-state-warn); border: 1px solid color-mix(in srgb, var(--color-state-warn) 25%, transparent);
}
.ban-tracking-alert-actions { display: flex; gap: 6px; margin-top: 6px; }

/* Paso 3 */
.ban-summary-block {
  background: color-mix(in srgb, var(--color-text) 4%, transparent); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column;
  gap: 6px; margin-bottom: 12px; font-size: .85rem;
}
.ban-summary-row { display: flex; gap: 8px; }
.ban-summary-label { color: var(--muted); min-width: 130px; flex-shrink: 0; font-size: .82rem; }
.ban-confirm-row {
  display: flex; align-items: flex-start; gap: 8px; font-size: .85rem;
  cursor: pointer; padding: 8px 10px; border-radius: 6px;
  background: color-mix(in srgb, var(--color-state-error) 6%, transparent); border: 1px solid color-mix(in srgb, var(--color-state-error) 20%, transparent);
}
.ban-confirm-row input[type=checkbox] { margin-top: 2px; flex-shrink: 0; }
</style>
