<!--
  Nombre de archivo: AvisoEmailModal.vue
  Ubicación de archivo: web/frontend/src/components/infra/infratab/AvisoEmailModal.vue
  Descripción: Sub-modal de Baneos activos para dar aviso por email de un baneo (envío o descarga del .eml)
-->
<template>
  <dialog ref="avisoModalEl" class="infra-generic-modal aviso-modal" @click.self="cerrar()" @cancel.prevent="cerrar()">
    <div class="modal-inner" v-if="avisoIncidente">
      <div class="modal-header-row">
        <h3 class="modal-title">📧 Dar Aviso — {{ avisoIncidente.ticket_asociado || 'Sin ticket' }}</h3>
        <button class="close-btn" @click="cerrar()">×</button>
      </div>
      <label class="form-label">Destinatarios <span class="req">*</span> <span class="aviso-hint">(separados por coma)</span></label>
      <input v-model="avisoForm.to" type="text" placeholder="operador@empresa.com, supervisor@empresa.com" />
      <label class="form-label">Con copia (CC) <span class="aviso-hint">(opcional)</span></label>
      <input v-model="avisoForm.cc" type="text" placeholder="noc@empresa.com" />
      <label class="form-label">Asunto <span class="req">*</span></label>
      <input v-model="avisoForm.subject" type="text" />
      <label class="form-label">Cuerpo del mensaje <span class="req">*</span> <span class="aviso-hint">(editable)</span></label>
      <textarea v-model="avisoForm.body" rows="11" class="aviso-body-textarea"></textarea>
      <div class="aviso-options">
        <label class="aviso-checkbox-row">
          <input v-model="avisoForm.include_xls" type="checkbox" />
          <span>Adjuntar resumen XLS</span>
        </label>
        <label class="aviso-checkbox-row">
          <input v-model="avisoForm.include_txt" type="checkbox" />
          <span>Adjuntar tracking TXT</span>
        </label>
      </div>
      <div class="modal-actions">
        <button class="btn subtle" :disabled="avisoSending" @click="cerrar()">Cancelar</button>
        <button
          class="btn primary small"
          :disabled="avisoSending"
          @click="downloadEml"
        >📥 Descargar EML</button>
        <button
          class="btn warning"
          :disabled="avisoSending || !avisoForm.to.trim() || !avisoForm.subject.trim() || !avisoForm.body.trim()"
          @click="sendAviso"
        >{{ avisoSending ? 'Enviando...' : '📧 Enviar Aviso' }}</button>
      </div>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import type { Notificar } from '../../../composables/infra/tipos';
import { useNotificacionEmail } from '../../../composables/infra/useNotificacionEmail';

const props = defineProps<{ notificar: Notificar }>();

const {
  avisoModalEl,
  avisoIncidente,
  avisoSending,
  avisoForm,
  abrir,
  cerrar,
  sendAviso,
  downloadEml,
} = useNotificacionEmail(props.notificar);

defineExpose({ abrir });
</script>

<style scoped src="./infra-modal.css"></style>

<style scoped>
.aviso-hint { font-size: .75rem; color: var(--muted); font-weight: 400; }
.aviso-body-textarea { font-family: inherit; font-size: .84rem; line-height: 1.5; resize: vertical; min-height: 200px; }
.aviso-options { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.aviso-checkbox-row { display: flex; align-items: center; gap: 8px; font-size: .85rem; cursor: pointer; }
.aviso-checkbox-row input[type=checkbox] { flex-shrink: 0; }
</style>
