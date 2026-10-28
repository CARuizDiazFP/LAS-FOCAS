<!--
  Nombre de archivo: TrackingResolveModal.vue
  Ubicación de archivo: web/frontend/src/components/infra/infratab/TrackingResolveModal.vue
  Descripción: Modal de InfraTab que analiza un tracking subido y ofrece cómo resolverlo (flujo Portero 2 fases)
-->
<template>
  <dialog ref="trackingResolveModalEl" class="infra-generic-modal tracking-resolve-modal" @click.self="cerrar()" @cancel.prevent="cerrar()">
    <div class="modal-inner">
      <div class="modal-header-row">
        <h3 class="modal-title">📁 Subir Tracking</h3>
        <button class="close-btn" @click="cerrar()">×</button>
      </div>
      <div v-if="uploadAnalyzing" class="upload-analyzing">
        ⏳ Analizando <strong>{{ fileName }}</strong>...
      </div>
      <template v-else-if="analyzeResult">
        <div :class="['resolve-status-badge', 'status-' + (analyzeResult.status ?? 'error').toLowerCase()]">
          {{ analyzeResult.status }}
        </div>
        <p class="resolve-message">{{ analyzeResult.message }}</p>
        <div v-if="analyzeResult.servicio_id" class="resolve-svc-info">
          Servicio: <strong>{{ analyzeResult.servicio_id }}</strong>
          <span v-if="analyzeResult.parsed_empalmes_count"> · {{ analyzeResult.parsed_empalmes_count }} empalmes</span>
          <template v-if="analyzeResult.punta_a_sitio">
            <span> · {{ analyzeResult.punta_a_sitio }} → {{ analyzeResult.punta_b_sitio ?? '?' }}</span>
          </template>
        </div>

        <!-- NEW: crear servicio nuevo -->
        <template v-if="analyzeResult.status === 'NEW'">
          <p class="resolve-hint">El servicio no existe. Se creará con una ruta Principal.</p>
          <div class="modal-actions">
            <button class="btn primary" :disabled="uploadResolving" @click="resolveTracking('CREATE_NEW', {})">
              {{ uploadResolving ? 'Procesando...' : 'Crear nuevo servicio' }}
            </button>
            <button class="btn subtle" @click="cerrar()">Cancelar</button>
          </div>
        </template>

        <!-- IDENTICAL: ya existe igual -->
        <template v-else-if="analyzeResult.status === 'IDENTICAL'">
          <p class="resolve-hint">El archivo es idéntico a una ruta existente. Sin cambios necesarios.</p>
          <div class="modal-actions">
            <button class="btn subtle" @click="cerrar()">Cerrar</button>
          </div>
        </template>

        <!-- CONFLICT: servicio existe con contenido diferente -->
        <template v-else-if="analyzeResult.status === 'CONFLICT'">
          <p class="resolve-hint">El servicio ya existe con contenido diferente.</p>
          <div v-if="analyzeResult.rutas_existentes.length" class="resolve-rutas-list">
            <div v-for="r in analyzeResult.rutas_existentes" :key="r.id" class="resolve-ruta-item">
              <strong>{{ r.nombre }}</strong>
              <span class="resolve-ruta-meta">{{ r.tipo }} · {{ r.empalmes_count }} emp.</span>
            </div>
          </div>
          <label v-if="analyzeResult.rutas_existentes.length > 0" class="form-label">Ruta destino para Merge / Reemplazar</label>
          <select
            v-if="analyzeResult.rutas_existentes.length > 0"
            v-model="resolveTargetRutaId"
            class="resolve-select"
          >
            <option v-for="r in analyzeResult.rutas_existentes" :key="r.id" :value="r.id">
              {{ r.nombre }} ({{ r.tipo }}, {{ r.empalmes_count }} emp.)
            </option>
          </select>
          <label class="form-label">Nombre del nuevo camino (para "Crear Camino")</label>
          <input v-model="resolveNewRutaNombre" type="text" placeholder="Ej: Backup Corrientes" />
          <div class="modal-actions resolve-conflict-actions">
            <button class="btn subtle" :disabled="uploadResolving" @click="resolveTracking('MERGE_APPEND', { target_ruta_id: resolveTargetRutaId })">
              {{ uploadResolving ? '...' : '+ Merge empalmes' }}
            </button>
            <button class="btn warning" :disabled="uploadResolving" @click="resolveTracking('REPLACE', { target_ruta_id: resolveTargetRutaId })">
              {{ uploadResolving ? '...' : '↺ Reemplazar ruta' }}
            </button>
            <button
              class="btn primary"
              :disabled="uploadResolving || !resolveNewRutaNombre.trim()"
              @click="resolveTracking('BRANCH', { new_ruta_name: resolveNewRutaNombre, new_ruta_tipo: 'ALTERNATIVA' })"
            >{{ uploadResolving ? '...' : '⑂ Crear Camino' }}</button>
            <button
              class="btn primary"
              :disabled="uploadResolving"
              @click="resolveTracking('ADD_STRAND', { target_ruta_id: resolveTargetRutaId })"
            >{{ uploadResolving ? '...' : '🧵 Nuevo Pelo' }}</button>
            <button class="btn subtle" @click="cerrar()">Cancelar</button>
          </div>
        </template>

        <!-- POTENTIAL_UPGRADE: posible upgrade de servicio -->
        <template v-else-if="analyzeResult.status === 'POTENTIAL_UPGRADE'">
          <p class="resolve-hint">Se detectó un posible upgrade de servicio.</p>
          <div v-if="analyzeResult.upgrade_info" class="resolve-upgrade-info">
            <div>Servicio viejo: <strong>{{ analyzeResult.upgrade_info.old_service_id }}</strong></div>
            <div>Razón: {{ analyzeResult.upgrade_info.match_reason }}</div>
            <div v-if="analyzeResult.upgrade_info.punta_a_match">Punta A: {{ analyzeResult.upgrade_info.punta_a_match }}</div>
            <div v-if="analyzeResult.upgrade_info.punta_b_match">Punta B: {{ analyzeResult.upgrade_info.punta_b_match }}</div>
          </div>
          <div class="modal-actions">
            <button
              class="btn primary"
              :disabled="uploadResolving"
              @click="resolveTracking('CONFIRM_UPGRADE', { old_service_id: analyzeResult?.upgrade_info?.old_service_id ?? '' })"
            >{{ uploadResolving ? '...' : 'Confirmar upgrade' }}</button>
            <button class="btn subtle" :disabled="uploadResolving" @click="resolveTracking('CREATE_NEW', {})">
              {{ uploadResolving ? '...' : 'Crear como nuevo' }}
            </button>
            <button class="btn subtle" @click="cerrar()">Cancelar</button>
          </div>
        </template>

        <!-- NEW_STRAND: nuevo pelo -->
        <template v-else-if="analyzeResult.status === 'NEW_STRAND'">
          <p class="resolve-hint">Se detectó un nuevo pelo para un servicio existente.</p>
          <div v-if="analyzeResult.strand_info" class="resolve-upgrade-info">
            <div>Servicio: <strong>{{ analyzeResult.strand_info.service_id }}</strong></div>
            <div>Pelos actuales: {{ analyzeResult.strand_info.current_strands }}</div>
            <div v-if="analyzeResult.strand_info.new_strand_pelo">Nuevo pelo: {{ analyzeResult.strand_info.new_strand_pelo }}</div>
          </div>
          <div class="modal-actions">
            <button
              class="btn primary"
              :disabled="uploadResolving"
              @click="resolveTracking('ADD_STRAND', { target_ruta_id: analyzeResult?.strand_info?.ruta_id })"
            >{{ uploadResolving ? '...' : 'Agregar pelo' }}</button>
            <button class="btn subtle" :disabled="uploadResolving" @click="resolveTracking('CREATE_NEW', {})">
              {{ uploadResolving ? '...' : 'Crear como nuevo' }}
            </button>
            <button class="btn subtle" @click="cerrar()">Cancelar</button>
          </div>
        </template>

        <!-- ERROR (y cualquier status desconocido) -->
        <template v-else>
          <p class="resolve-error">{{ analyzeResult.error ?? 'Error desconocido durante el análisis.' }}</p>
          <div class="modal-actions">
            <button class="btn subtle" @click="cerrar()">Cerrar</button>
          </div>
        </template>
      </template>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import type { Notificar } from '../../../composables/infra/tipos';
import { useResolucionTracking } from '../../../composables/infra/useTrackingAnalisis';

const props = defineProps<{ notificar: Notificar }>();
const emit = defineEmits<{ 'tracking-resuelto': [] }>();

const {
  trackingResolveModalEl,
  uploadAnalyzing,
  uploadResolving,
  analyzeResult,
  fileName,
  resolveTargetRutaId,
  resolveNewRutaNombre,
  abrir,
  resolveTracking,
  cerrar,
} = useResolucionTracking(props.notificar, () => emit('tracking-resuelto'));

defineExpose({ abrir });
</script>

<style scoped src="./infra-modal.css"></style>

<style scoped>
.resolve-conflict-actions { gap: 6px; }
.upload-analyzing { padding: 16px 0; font-size: .88rem; color: var(--muted); }
.resolve-status-badge {
  display: inline-block; padding: 4px 12px; border-radius: 12px;
  font-size: .82rem; font-weight: 700; margin-bottom: 6px; background: color-mix(in srgb, var(--color-text) 7%, transparent);
}
.resolve-status-badge.status-new { background: color-mix(in srgb, var(--color-accent) 15%, transparent); color: var(--color-accent); }
.resolve-status-badge.status-identical { background: color-mix(in srgb, var(--color-state-ok) 15%, transparent); color: var(--color-state-ok); }
.resolve-status-badge.status-conflict { background: color-mix(in srgb, var(--color-state-warn) 15%, transparent); color: var(--color-state-warn); }
.resolve-status-badge.status-potential_upgrade { background: color-mix(in srgb, var(--color-accent) 15%, transparent); color: var(--color-accent); }
.resolve-status-badge.status-new_strand { background: color-mix(in srgb, var(--color-accent) 15%, transparent); color: var(--color-accent); }
.resolve-status-badge.status-error { background: color-mix(in srgb, var(--color-state-error) 15%, transparent); color: var(--color-state-error); }
.resolve-message { margin: 0 0 8px; font-size: .85rem; }
.resolve-svc-info { font-size: .83rem; color: var(--muted); margin-bottom: 8px; }
.resolve-hint { font-size: .85rem; color: var(--muted); margin: 4px 0 8px; }
.resolve-error { color: var(--color-state-error); font-size: .85rem; margin: 8px 0; }
.resolve-rutas-list { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }
.resolve-ruta-item {
  display: flex; align-items: center; gap: 8px; font-size: .82rem;
  padding: 6px 8px; background: color-mix(in srgb, var(--color-text) 4%, transparent); border-radius: 6px;
}
.resolve-ruta-meta { font-size: .78rem; color: var(--muted); }
.resolve-select { width: 100%; margin: 4px 0 10px; }
.resolve-upgrade-info {
  font-size: .83rem; background: color-mix(in srgb, var(--color-text) 4%, transparent); border-radius: 6px;
  padding: 8px 10px; margin: 6px 0; display: flex; flex-direction: column; gap: 3px;
}
</style>
