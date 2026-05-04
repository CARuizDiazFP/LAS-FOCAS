<!--
  Nombre de archivo: InfraTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/InfraTab.vue
  Descripción: Tab de Infraestructura / Dashboard de Cámaras — migrado desde panel.js
-->
<template>
  <article class="card" style="padding:0">
    <!-- Toast container -->
    <teleport to="body">
      <div id="infra-toast-container" class="toast-container" aria-live="polite">
        <transition-group name="toast-anim">
          <div
            v-for="t in toasts"
            :key="t.id"
            :class="['toast', t.type]"
          >
            <span class="toast-icon">{{ toastIcon(t.type) }}</span>
            <div class="toast-content">
              <div class="toast-title">{{ t.title }}</div>
              <div v-if="t.message" class="toast-message">{{ t.message }}</div>
            </div>
            <button class="toast-close" @click="removeToast(t.id)">×</button>
          </div>
        </transition-group>
      </div>
    </teleport>

    <!-- Camera state modal -->
    <dialog ref="cameraStateModalEl" class="camera-state-modal" @click.self="closeCameraStateModal">
      <div class="modal-content" v-if="cameraStateData">
        <div class="camera-state-title-row">
          <strong>{{ cameraStateData.camara.nombre || cameraStateData.camara.direccion || 'Sin nombre' }}</strong>
          <span :class="['camera-state-badge', cameraStateData.contexto.inconsistente ? 'warning' : 'ok']">
            {{ cameraStateData.contexto.inconsistente ? 'Inconsistente' : 'Alineada' }}
          </span>
          <button class="close-btn" @click="closeCameraStateModal">×</button>
        </div>
        <div class="camera-state-meta-row">
          <span>Actual: <strong>{{ cameraStateData.contexto.estado_actual }}</strong></span>
          <span>Sugerido: <strong>{{ cameraStateData.contexto.estado_sugerido || cameraStateData.contexto.estado_actual }}</strong></span>
          <span>Baneo activo: <strong>{{ cameraStateData.contexto.tiene_baneo_activo ? 'Sí' : 'No' }}</strong></span>
          <span>Ingreso activo: <strong>{{ cameraStateData.contexto.tiene_ingreso_activo ? 'Sí' : 'No' }}</strong></span>
        </div>
        <div v-if="(cameraStateData.contexto.incidentes_activos ?? []).length" class="camera-state-incidents">
          <div class="camera-state-incidents-title">Incidentes activos vinculados</div>
          <div
            v-for="inc in cameraStateData.contexto.incidentes_activos"
            :key="inc.ticket_asociado"
            class="camera-state-incident-item"
          >
            <strong>{{ inc.ticket_asociado || 'Sin ticket' }}</strong>
            <span>Servicio: {{ inc.servicio_protegido_id || '-' }}</span>
            <span>Ruta: {{ inc.ruta_protegida_id ?? '-' }}</span>
          </div>
        </div>
        <div v-else class="camera-state-empty">No hay incidentes activos vinculados.</div>
        <label class="form-label">Nuevo estado</label>
        <select v-model="newEstado" class="camera-state-select">
          <option v-for="s in ESTADOS" :key="s" :value="s">{{ s }}</option>
        </select>
        <label class="form-label">Motivo del cambio (mínimo 5 caracteres)</label>
        <input v-model="motivo" type="text" placeholder="Describí brevemente el motivo" />
        <div class="camera-state-actions">
          <button class="btn primary" :disabled="savingState" @click="saveCameraState">Guardar</button>
          <button class="btn subtle" @click="closeCameraStateModal">Cancelar</button>
        </div>
      </div>
    </dialog>

    <!-- Tracking modal -->
    <dialog ref="trackingModalEl" class="tracking-detail-modal" @click.self="trackingModalEl?.close()">
      <div class="tracking-detail-content">
        <div class="tracking-detail-header">
          <h3 class="tracking-detail-title">{{ trackingTitle }}</h3>
          <button class="tracking-download-btn" type="button" @click="downloadTracking">📄 Descargar TXT</button>
          <button class="tracking-detail-close" @click="trackingModalEl?.close()">×</button>
        </div>
        <div class="tracking-rutas-tabs">
          <button
            v-for="ruta in trackingRutas"
            :key="ruta.id"
            :class="['tracking-ruta-tab', { active: ruta.id === activeRutaId }]"
            :style="{ '--tab-color': ruta.color }"
            @click="loadRutaTracking(ruta.id)"
          >{{ ruta.nombre }}</button>
        </div>
        <div class="tracking-detail-list">
          <div v-if="trackingLoading" class="tracking-loading">Cargando tracking...</div>
          <div v-else-if="trackingError" class="tracking-error">{{ trackingError }}</div>
          <div v-else class="tracking-sequence">
            <template v-if="trackingItems.punta_a">
              <div class="tracking-item tracking-punta tracking-punta-a">
                <span class="tracking-icon">🔌</span>
                <span class="tracking-text">
                  <span class="tracking-punta-label">Punta A</span>
                  <span class="tracking-punta-sitio">{{ trackingItems.punta_a.sitio }}{{ trackingItems.punta_a.conector ? ': ' + trackingItems.punta_a.conector : '' }}</span>
                  <span v-if="trackingItems.punta_a.identificador" class="tracking-punta-id">{{ trackingItems.punta_a.identificador }}</span>
                </span>
              </div>
            </template>
            <template v-for="(item, i) in trackingItems.tracking ?? []" :key="i">
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
            <template v-if="trackingItems.punta_b">
              <div class="tracking-item tracking-punta tracking-punta-b">
                <span class="tracking-icon">🔌</span>
                <span class="tracking-text">
                  <span class="tracking-punta-label">Punta B</span>
                  <span class="tracking-punta-sitio">{{ trackingItems.punta_b.sitio }}{{ trackingItems.punta_b.conector ? ': ' + trackingItems.punta_b.conector : '' }}</span>
                  <span v-if="trackingItems.punta_b.identificador" class="tracking-punta-id">{{ trackingItems.punta_b.identificador }}</span>
                </span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </dialog>

    <!-- Hidden file input para tracking upload -->
    <input ref="trackingFileInputEl" type="file" accept=".txt" style="display:none" @change="handleTrackingFile">

    <!-- Modal: Protocolo de Protección (ban) -->
    <dialog ref="banModalEl" class="infra-generic-modal" @click.self="closeBanModal">
      <div class="modal-inner">
        <div class="modal-header-row">
          <h3 class="modal-title">🔴 Protocolo de Protección</h3>
          <button class="close-btn" @click="closeBanModal">×</button>
        </div>
        <p class="modal-desc">Activa el baneo de cámaras del servicio protegido (backup/respaldo).</p>
        <label class="form-label">Ticket asociado (opcional)</label>
        <input v-model="banForm.ticket_asociado" type="text" placeholder="INC0012345" />
        <label class="form-label">Servicio afectado (el que se cortó) <span class="req">*</span></label>
        <input v-model="banForm.servicio_afectado_id" type="text" placeholder="ID del servicio cortado" />
        <label class="form-label">Servicio a proteger (banear) <span class="req">*</span></label>
        <input v-model="banForm.servicio_protegido_id" type="text" placeholder="ID del servicio a proteger" />
        <label class="form-label">Motivo (opcional)</label>
        <textarea v-model="banForm.motivo" rows="2" placeholder="Corte de fibra en Av. Corrientes..."></textarea>
        <label class="form-label">Operador (opcional)</label>
        <input v-model="banForm.usuario_ejecutor" type="text" placeholder="usuario@empresa.com" />
        <div class="modal-actions">
          <button
            class="btn danger"
            :disabled="banLoading || !banForm.servicio_afectado_id.trim() || !banForm.servicio_protegido_id.trim()"
            @click="submitBan"
          >{{ banLoading ? 'Activando...' : 'Activar Protocolo' }}</button>
          <button class="btn subtle" @click="closeBanModal">Cancelar</button>
        </div>
      </div>
    </dialog>

    <!-- Modal: Resolución de tracking (flujo Portero 2 fases) -->
    <dialog ref="trackingResolveModalEl" class="infra-generic-modal tracking-resolve-modal" @click.self="closeUploadModal">
      <div class="modal-inner">
        <div class="modal-header-row">
          <h3 class="modal-title">📁 Subir Tracking</h3>
          <button class="close-btn" @click="closeUploadModal">×</button>
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
              <button class="btn subtle" @click="closeUploadModal">Cancelar</button>
            </div>
          </template>

          <!-- IDENTICAL: ya existe igual -->
          <template v-else-if="analyzeResult.status === 'IDENTICAL'">
            <p class="resolve-hint">El archivo es idéntico a una ruta existente. Sin cambios necesarios.</p>
            <div class="modal-actions">
              <button class="btn subtle" @click="closeUploadModal">Cerrar</button>
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
              <button class="btn subtle" @click="closeUploadModal">Cancelar</button>
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
              <button class="btn subtle" @click="closeUploadModal">Cancelar</button>
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
              <button class="btn subtle" @click="closeUploadModal">Cancelar</button>
            </div>
          </template>

          <!-- ERROR (y cualquier status desconocido) -->
          <template v-else>
            <p class="resolve-error">{{ analyzeResult.error ?? 'Error desconocido durante el análisis.' }}</p>
            <div class="modal-actions">
              <button class="btn subtle" @click="closeUploadModal">Cerrar</button>
            </div>
          </template>
        </template>
      </div>
    </dialog>

    <!-- Modal: Limpiar servicio -->
    <dialog ref="limpiarModalEl" class="infra-generic-modal" @click.self="closeLimpiarModal">
      <div class="modal-inner">
        <div class="modal-header-row">
          <h3 class="modal-title">🗑 Limpiar Servicio</h3>
          <button class="close-btn" @click="closeLimpiarModal">×</button>
        </div>
        <p class="modal-desc danger-text">⚠️ Operación destructiva e irreversible. Se eliminarán todas las asociaciones de empalmes y rutas del servicio.</p>
        <label class="form-label">ID del servicio <span class="req">*</span></label>
        <input v-model="limpiarServicioId" type="text" placeholder="Ej: 52547" />
        <div class="modal-actions">
          <button
            class="btn danger"
            :disabled="limpiarLoading || !limpiarServicioId.trim()"
            @click="submitLimpiar"
          >{{ limpiarLoading ? 'Limpiando...' : 'Limpiar servicio' }}</button>
          <button class="btn subtle" @click="closeLimpiarModal">Cancelar</button>
        </div>
      </div>
    </dialog>

    <!-- Main content -->
    <div class="infra-panel">
      <div class="infra-toolbar">
        <h2 class="infra-toolbar-title">Infraestructura FO</h2>
        <div class="infra-toolbar-actions">
          <button class="btn danger" @click="openBanModal">🔴 Protocolo Protección</button>
          <div
            class="upload-drop-zone"
            :class="{ 'drag-over': isDragOver }"
            role="button"
            tabindex="0"
            @click="triggerUploadTracking"
            @keydown.enter.prevent="triggerUploadTracking"
            @keydown.space.prevent="triggerUploadTracking"
            @dragover.prevent="onDragOver"
            @dragenter.prevent="onDragEnter"
            @dragleave="onDragLeave"
            @drop.prevent="onDrop"
          >📁 Subir Tracking</div>
          <button class="btn danger-subtle" @click="openLimpiarModal">🗑 Limpiar Servicio</button>
          <div class="download-dropdown-wrapper" ref="downloadDropdownEl">
            <button class="btn success" @click.stop="toggleDownloadMenu">
              ⬇ Descargar <span class="dropdown-caret" :class="{ open: isDownloadMenuOpen }">▾</span>
            </button>
            <ul v-if="isDownloadMenuOpen" class="download-dropdown-menu" @click.stop>
              <li class="dropdown-item" @click="downloadCameras('xlsx', null)">📊 Todas (XLSX)</li>
              <li class="dropdown-item" @click="downloadCameras('csv', null)">📄 Todas (CSV)</li>
              <li class="dropdown-divider"></li>
              <li class="dropdown-item" @click="downloadCameras('xlsx', 'BANEADA')">🔴 Solo Baneadas</li>
              <li class="dropdown-item" @click="downloadCameras('xlsx', 'OCUPADA')">🟡 Con Ingreso</li>
            </ul>
          </div>
        </div>
      </div>
      <div class="infra-search-area">
        <div class="infra-search-row">
          <input
            v-model="searchInput"
            type="text"
            placeholder="Buscar por nombre, dirección, servicio..."
            @keydown.enter="addTerm"
          />
          <button class="btn" @click="addTerm">Agregar</button>
          <button class="btn primary" :disabled="loading || searchTerms.length === 0" @click="searchCamaras">Buscar</button>
          <button class="btn subtle" @click="clearAll">Limpiar</button>
        </div>
        <div v-if="searchTerms.length" class="infra-search-terms">
          <span v-for="(term, i) in searchTerms" :key="i" class="infra-search-term">
            <span class="infra-search-term-value">{{ term }}</span>
            <button class="infra-search-term-remove" @click="removeTerm(i)">×</button>
          </span>
        </div>
        <div v-if="statusText" :class="['infra-status', statusVariant]">{{ statusText }}</div>
      </div>

      <!-- Leyenda de estados -->
      <div class="infra-legend">
        <span class="infra-legend-item"><span class="infra-legend-dot libre"></span>LIBRE</span>
        <span class="infra-legend-item"><span class="infra-legend-dot ocupada"></span>OCUPADA</span>
        <span class="infra-legend-item"><span class="infra-legend-dot baneada"></span>BANEADA</span>
        <span class="infra-legend-item"><span class="infra-legend-dot detectada"></span>DETECTADA</span>
        <span class="infra-legend-item"><span style="font-size:.85rem">📍</span>TRACKING</span>
      </div>

      <div v-if="loading" class="infra-loading">Buscando...</div>
      <div v-else-if="!hasSearched" class="infra-empty">
        <span>Agregá términos de búsqueda y presioná "Buscar"</span>
      </div>
      <div v-else-if="camaras.length === 0" class="infra-empty">Sin resultados para estos términos.</div>
      <div v-else class="infra-grid">
        <div
          v-for="camara in camaras"
          :key="camara.id"
          :class="['infra-camara-card']"
          :data-estado="camara.estado ?? 'LIBRE'"
          :data-inconsistente="camara.inconsistente ? 'true' : 'false'"
        >
          <div class="infra-camara-header">
            <div class="infra-camara-estado">
              <span :class="['infra-estado-icon', (camara.estado ?? 'libre').toLowerCase()]"></span>
              <span class="infra-estado-text">{{ camara.estado || 'LIBRE' }}</span>
            </div>
            <div class="infra-camara-header-actions">
              <span v-if="camara.fontine_id" class="infra-camara-id">{{ camara.fontine_id }}</span>
              <button
                v-if="isAdmin && camara.editable !== false"
                class="infra-edit-btn"
                @click.stop="openCameraStateModal(camara)"
              >Editar estado</button>
            </div>
          </div>
          <div class="infra-camara-nombre">{{ camara.nombre || camara.direccion || 'Sin nombre' }}</div>
          <div v-if="camara.inconsistente && camara.estado_sugerido" class="infra-camara-warning">
            <strong>Estado manual distinto al sugerido.</strong>
            <span>Actual: {{ camara.estado }} · Sugerido: {{ camara.estado_sugerido }}</span>
          </div>
          <div class="infra-camara-servicios">
            <template v-if="(camara.rutas ?? []).length > 0">
              <span
                v-for="chip in buildServiceChips(camara.rutas)"
                :key="chip.servicioId"
                class="infra-servicio-chip"
                :style="{ backgroundColor: chip.color, cursor: 'pointer' }"
                :title="chip.title"
                @click.stop="openTrackingModal(chip.rutaId, chip.servicioId, chip.rutaNombre, chip.rutaTipo, chip.color)"
              >
                <span class="servicio-id-main">Svc: {{ chip.servicioId }}</span>
                <span v-if="chip.aliasHtml" class="servicio-alias">(ex {{ chip.aliasHtml }})</span>
                <span v-if="chip.pelos > 1" class="servicio-pelos-badge">x{{ chip.pelos }}</span>
              </span>
            </template>
            <span v-else class="infra-no-servicios">Sin servicios asociados</span>
          </div>
          <div v-if="camara.estado === 'BANEADA' && camara.ticket_baneo" class="infra-ban-ticket">{{ camara.ticket_baneo }}</div>
        </div>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { useSession } from '../../composables/useSession';

const { state, csrf } = useSession();
const isAdmin = computed(() => (state.value.role ?? '').toLowerCase() === 'admin');

// --- Toast ---
interface Toast { id: number; type: string; title: string; message?: string }
const toasts = ref<Toast[]>([]);
let _toastId = 0;
function showToast(type: string, title: string, message?: string, duration = 5000) {
  const id = ++_toastId;
  toasts.value.push({ id, type, title, message });
  if (duration > 0) setTimeout(() => removeToast(id), duration);
}
function removeToast(id: number) {
  const i = toasts.value.findIndex(t => t.id === id);
  if (i !== -1) toasts.value.splice(i, 1);
}
function toastIcon(type: string) {
  return { success: '✓', error: '✗', warning: '⚠', info: 'ℹ' }[type] ?? 'ℹ';
}

// --- Search ---
const searchInput = ref('');
const searchTerms = ref<string[]>([]);
const camaras = ref<Record<string, unknown>[]>([]);
const loading = ref(false);
const hasSearched = ref(false);
const statusText = ref('');
const statusVariant = ref('muted');

function setStatus(text: string, variant = 'muted') {
  statusText.value = text;
  statusVariant.value = variant;
}

function addTerm() {
  const val = searchInput.value.trim();
  if (!val) return;
  if (searchTerms.value.some(t => t.toLowerCase() === val.toLowerCase())) {
    showToast('warning', 'Término duplicado', 'Este término ya está activo');
    return;
  }
  searchTerms.value.push(val);
  searchInput.value = '';
}

function removeTerm(i: number) {
  searchTerms.value.splice(i, 1);
}

function clearAll() {
  searchTerms.value = [];
  searchInput.value = '';
  camaras.value = [];
  hasSearched.value = false;
  setStatus('');
}

async function searchCamaras() {
  if (searchTerms.value.length === 0) return;
  loading.value = true;
  hasSearched.value = true;
  setStatus(`Buscando con ${searchTerms.value.length} término(s)...`, 'loading');
  try {
    const res = await fetch('/api/infra/smart-search', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ terms: searchTerms.value, limit: 100, offset: 0 }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error((err as Record<string, string>).detail ?? (err as Record<string, string>).error ?? `Error ${res.status}`);
    }
    const data = await res.json();
    camaras.value = data.camaras ?? [];
    const count = camaras.value.length;
    const total = data.total ?? count;
    setStatus(
      count === 0
        ? 'Sin resultados para estos términos'
        : total > count
          ? `Mostrando ${count} de ${total} cámaras`
          : `${count} cámara${count !== 1 ? 's' : ''} encontrada${count !== 1 ? 's' : ''}`,
      count > 0 ? 'success' : 'muted',
    );
  } catch (e: unknown) {
    camaras.value = [];
    setStatus(`Error: ${e instanceof Error ? e.message : String(e)}`, 'error');
  } finally {
    loading.value = false;
  }
}

// --- Camera cards ---
const RUTA_COLORS: Record<string, string> = {
  PRINCIPAL: '#3B82F6',
  BACKUP: '#37BC7D',
  ALTERNATIVA: '#F54927',
  CUARTO: '#E61876',
};

function getRutaColor(ruta: Record<string, unknown>, index: number): string {
  const fallback = [RUTA_COLORS.PRINCIPAL, RUTA_COLORS.BACKUP, RUTA_COLORS.ALTERNATIVA, RUTA_COLORS.CUARTO];
  if (ruta.ruta_tipo === 'PRINCIPAL') return RUTA_COLORS.PRINCIPAL;
  if (ruta.ruta_tipo === 'BACKUP') return RUTA_COLORS.BACKUP;
  if (ruta.ruta_tipo === 'ALTERNATIVA') return RUTA_COLORS.ALTERNATIVA;
  const n = String(ruta.ruta_nombre ?? '').toLowerCase();
  if (n.includes('principal') || n === 'camino 1') return RUTA_COLORS.PRINCIPAL;
  if (n.includes('backup') || n.includes('secundario') || n === 'camino 2') return RUTA_COLORS.BACKUP;
  if (n === 'camino 3' || n.includes('alternativ')) return RUTA_COLORS.ALTERNATIVA;
  if (n === 'camino 4') return RUTA_COLORS.CUARTO;
  return fallback[index % fallback.length];
}

interface ServiceChip {
  servicioId: string; rutaId: string; rutaNombre: string; rutaTipo: string;
  color: string; title: string; pelos: number; aliasHtml: string;
}

function buildServiceChips(rutas: Record<string, unknown>[]): ServiceChip[] {
  const grouped: Record<string, Record<string, unknown>[]> = {};
  rutas.forEach((r, idx) => {
    const sid = String(r.servicio_id ?? '');
    if (!grouped[sid]) grouped[sid] = [];
    grouped[sid].push({ ...r, _index: idx });
  });
  return Object.entries(grouped).map(([svcId, svcRutas]) => {
    const first = svcRutas[0];
    const allAlias = new Set<string>();
    svcRutas.forEach(r => ((r.alias_ids as string[]) ?? []).forEach(a => allAlias.add(a)));
    return {
      servicioId: svcId,
      rutaId: String(first.ruta_id ?? ''),
      rutaNombre: String(first.ruta_nombre ?? ''),
      rutaTipo: String(first.ruta_tipo ?? ''),
      color: getRutaColor(first, first._index as number),
      title: svcRutas.length > 1 ? `${svcRutas.length} pelos` : String(first.ruta_nombre ?? ''),
      pelos: svcRutas.length,
      aliasHtml: [...allAlias].join(', '),
    };
  });
}

// --- Camera state modal ---
const cameraStateModalEl = ref<HTMLDialogElement | null>(null);
interface CameraStateData {
  camara: Record<string, unknown>;
  contexto: Record<string, unknown>;
}
const cameraStateData = ref<CameraStateData | null>(null);
const newEstado = ref('');
const motivo = ref('');
const savingState = ref(false);
const ESTADOS = ['LIBRE', 'BANEADA', 'EN_MANTENIMIENTO', 'INACCESIBLE'];

async function openCameraStateModal(camara: Record<string, unknown>) {
  try {
    const res = await fetch(`/api/infra/camaras/${camara.id}/estado`, { credentials: 'include' });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).error ?? `Error ${res.status}`);
    cameraStateData.value = { camara, contexto: data.contexto ?? {} };
    newEstado.value = String((data.contexto as Record<string, unknown>)?.estado_actual ?? camara.estado ?? 'LIBRE');
    motivo.value = '';
    cameraStateModalEl.value?.showModal();
  } catch (e: unknown) {
    showToast('error', 'No se pudo abrir el editor', e instanceof Error ? e.message : String(e));
  }
}

function closeCameraStateModal() {
  cameraStateData.value = null;
  motivo.value = '';
  cameraStateModalEl.value?.close();
}

async function saveCameraState() {
  if (!cameraStateData.value) return;
  if (motivo.value.trim().length < 5) {
    showToast('warning', 'Motivo insuficiente', 'Ingresá al menos 5 caracteres para auditar el cambio');
    return;
  }
  savingState.value = true;
  try {
    const res = await fetch(`/api/infra/camaras/${cameraStateData.value.camara.id}/estado`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ estado: newEstado.value, motivo: motivo.value.trim(), csrf_token: csrf() }),
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error((data as Record<string, string>).error ?? 'No se pudo guardar');
    closeCameraStateModal();
    await searchCamaras();
    showToast('success', 'Estado actualizado', data.changed ? 'El cambio quedó auditado' : 'La cámara ya tenía ese estado');
  } catch (e: unknown) {
    showToast('error', 'Error al guardar', e instanceof Error ? e.message : String(e));
  } finally {
    savingState.value = false;
  }
}

// --- Tracking modal ---
const trackingModalEl = ref<HTMLDialogElement | null>(null);
const trackingTitle = ref('');
const trackingRutas = ref<{ id: number; nombre: string; color: string }[]>([]);
const activeRutaId = ref<number | null>(null);
const currentRutaIdForDownload = ref<number | null>(null);
const trackingLoading = ref(false);
const trackingError = ref<string | null>(null);
interface TrackingData {
  tracking: Record<string, unknown>[];
  punta_a?: Record<string, unknown> | null;
  punta_b?: Record<string, unknown> | null;
}
const trackingItems = ref<TrackingData>({ tracking: [] });

async function openTrackingModal(rutaId: string, servicioId: string, rutaNombre: string, _rutaTipo: string, _color: string) {
  trackingTitle.value = `Svc: ${servicioId}`;
  trackingRutas.value = [];
  activeRutaId.value = null;
  trackingItems.value = { tracking: [] };
  trackingError.value = null;
  trackingLoading.value = true;
  trackingModalEl.value?.showModal();
  try {
    const res = await fetch(`/api/infra/servicios/${servicioId}/rutas`, { credentials: 'include' });
    const data = await res.json();
    const rutas: Record<string, unknown>[] = data.rutas ?? [];
    if (rutas.length === 0) {
      trackingRutas.value = [{ id: Number(rutaId), nombre: rutaNombre, color: _color }];
    } else {
      trackingRutas.value = rutas.map((r, i) => ({
        id: r.id as number,
        nombre: String(r.nombre ?? r.ruta_nombre ?? ''),
        color: getRutaColor(r, i),
      }));
    }
    await loadRutaTracking(Number(rutaId));
  } catch (e: unknown) {
    trackingLoading.value = false;
    trackingError.value = e instanceof Error ? e.message : String(e);
  }
}

async function loadRutaTracking(rutaId: number) {
  activeRutaId.value = rutaId;
  currentRutaIdForDownload.value = rutaId;
  trackingLoading.value = true;
  trackingError.value = null;
  try {
    const res = await fetch(`/api/infra/rutas/${rutaId}/tracking`, { credentials: 'include' });
    const data = await res.json();
    if (data.error) { trackingError.value = data.error; return; }
    trackingItems.value = { tracking: data.tracking ?? [], punta_a: data.punta_a, punta_b: data.punta_b };
  } catch (e: unknown) {
    trackingError.value = e instanceof Error ? e.message : String(e);
  } finally {
    trackingLoading.value = false;
  }
}

async function downloadTracking() {
  const rid = currentRutaIdForDownload.value;
  if (!rid) return;
  try {
    const res = await fetch(`/api/infra/tracking/${rid}/download`, { credentials: 'include' });
    if (res.status === 404) { showToast('warning', 'Archivo no disponible', 'El TXT original no está disponible'); return; }
    if (!res.ok) throw new Error(`Error ${res.status}`);
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') ?? '';
    const match = cd.match(/filename="(.+?)"/);
    const filename = match ? match[1] : `tracking_ruta_${rid}.txt`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('success', 'Descarga completa', filename);
  } catch (e: unknown) {
    showToast('error', 'Error de descarga', e instanceof Error ? e.message : String(e));
  }
}

// --- Protocolo de Protección (ban) ---
interface BanFormData {
  ticket_asociado: string;
  servicio_afectado_id: string;
  servicio_protegido_id: string;
  motivo: string;
  usuario_ejecutor: string;
}
const banModalEl = ref<HTMLDialogElement | null>(null);
const banLoading = ref(false);
const banForm = ref<BanFormData>({
  ticket_asociado: '',
  servicio_afectado_id: '',
  servicio_protegido_id: '',
  motivo: '',
  usuario_ejecutor: '',
});

function openBanModal() {
  banForm.value = {
    ticket_asociado: '',
    servicio_afectado_id: '',
    servicio_protegido_id: '',
    motivo: '',
    usuario_ejecutor: '',
  };
  banModalEl.value?.showModal();
}

function closeBanModal() {
  banModalEl.value?.close();
}

async function submitBan() {
  if (!banForm.value.servicio_afectado_id.trim() || !banForm.value.servicio_protegido_id.trim()) {
    showToast('warning', 'Campos requeridos', 'Completá los dos IDs de servicio');
    return;
  }
  banLoading.value = true;
  try {
    const payload: Record<string, string | null> = {
      ticket_asociado: banForm.value.ticket_asociado.trim() || null,
      servicio_afectado_id: banForm.value.servicio_afectado_id.trim(),
      servicio_protegido_id: banForm.value.servicio_protegido_id.trim(),
      motivo: banForm.value.motivo.trim() || null,
      usuario_ejecutor: banForm.value.usuario_ejecutor.trim() || null,
    };
    const res = await fetch('/api/infra/ban/create', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRF-Token': csrf() },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).detail ?? `Error ${res.status}`);
    closeBanModal();
    const baneadas = (data as Record<string, number>).camaras_baneadas ?? 0;
    showToast('success', 'Protocolo activado', `${baneadas} cámara(s) baneadas`);
    if (hasSearched.value) await searchCamaras();
  } catch (e: unknown) {
    showToast('error', 'Error al activar protocolo', e instanceof Error ? e.message : String(e));
  } finally {
    banLoading.value = false;
  }
}

// --- Upload Tracking (flujo Portero 2 fases) ---
interface RutaInfo {
  id: number; nombre: string; tipo: string; empalmes_count: number; activa: boolean;
}
interface UpgradeInfo {
  old_service_id: string; old_service_db_id: number; new_service_id: string;
  match_reason: string; punta_a_match?: string | null; punta_b_match?: string | null;
}
interface StrandInfo {
  service_id: string; service_db_id: number; ruta_id: number;
  current_strands: number; new_strand_pelo?: string | null;
}
interface AnalyzeResult {
  status: string; servicio_id?: string | null; servicio_db_id?: number | null;
  rutas_existentes: RutaInfo[]; parsed_empalmes_count: number; message: string;
  error?: string | null; upgrade_info?: UpgradeInfo | null; strand_info?: StrandInfo | null;
  punta_a_sitio?: string | null; punta_b_sitio?: string | null;
}

const trackingFileInputEl = ref<HTMLInputElement | null>(null);
const trackingResolveModalEl = ref<HTMLDialogElement | null>(null);
const uploadAnalyzing = ref(false);
const uploadResolving = ref(false);
const analyzeResult = ref<AnalyzeResult | null>(null);
const fileContent = ref('');
const fileName = ref('');
const resolveTargetRutaId = ref<number | null>(null);
const resolveNewRutaNombre = ref('');

function triggerUploadTracking() {
  trackingFileInputEl.value?.click();
}

// --- Drag & Drop para la zona de upload de tracking ---
const isDragOver = ref(false);

function onDragOver() {
  isDragOver.value = true;
}

function onDragEnter() {
  isDragOver.value = true;
}

function onDragLeave(e: DragEvent) {
  // Solo desactivar si el mouse salió del wrapper completo
  const target = e.currentTarget as HTMLElement;
  if (!target.contains(e.relatedTarget as Node)) {
    isDragOver.value = false;
  }
}

function onDrop(e: DragEvent) {
  isDragOver.value = false;
  const file = e.dataTransfer?.files?.[0];
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.txt')) {
    showToast('warning', 'Archivo inválido', 'Solo se aceptan archivos .txt');
    return;
  }
  const reader = new FileReader();
  reader.onload = (ev) => {
    fileContent.value = (ev.target?.result as string) ?? '';
    fileName.value = file.name;
    void analyzeTracking();
  };
  reader.readAsText(file, 'utf-8');
}

function handleTrackingFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.txt')) {
    showToast('warning', 'Archivo inválido', 'Solo se aceptan archivos .txt');
    return;
  }
  const reader = new FileReader();
  reader.onload = (e) => {
    fileContent.value = (e.target?.result as string) ?? '';
    fileName.value = file.name;
    void analyzeTracking();
  };
  reader.readAsText(file, 'utf-8');
}

async function analyzeTracking() {
  uploadAnalyzing.value = true;
  analyzeResult.value = null;
  resolveTargetRutaId.value = null;
  resolveNewRutaNombre.value = '';
  trackingResolveModalEl.value?.showModal();
  try {
    const blob = new Blob([fileContent.value], { type: 'text/plain' });
    const formData = new FormData();
    formData.append('file', blob, fileName.value);
    const res = await fetch('/api/infra/trackings/analyze', {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json' },
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).detail ?? `Error ${res.status}`);
    analyzeResult.value = data as AnalyzeResult;
    if (analyzeResult.value.rutas_existentes?.length) {
      resolveTargetRutaId.value = analyzeResult.value.rutas_existentes[0].id;
    }
  } catch (e: unknown) {
    analyzeResult.value = {
      status: 'ERROR', message: 'Error analizando el archivo',
      parsed_empalmes_count: 0, rutas_existentes: [],
      error: e instanceof Error ? e.message : String(e),
    };
  } finally {
    uploadAnalyzing.value = false;
  }
}

async function resolveTracking(action: string, extras: Record<string, unknown> = {}) {
  uploadResolving.value = true;
  try {
    const body: Record<string, unknown> = {
      action,
      content: fileContent.value,
      filename: fileName.value,
      ...extras,
    };
    const res = await fetch('/api/infra/trackings/resolve', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRF-Token': csrf() },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).detail ?? `Error ${res.status}`);
    if (!(data as Record<string, boolean>).success) {
      throw new Error((data as Record<string, string>).error ?? 'Error al resolver el tracking');
    }
    closeUploadModal();
    showToast('success', 'Tracking procesado', (data as Record<string, string>).message ?? '');
    if (hasSearched.value) await searchCamaras();
  } catch (e: unknown) {
    showToast('error', 'Error al procesar tracking', e instanceof Error ? e.message : String(e));
  } finally {
    uploadResolving.value = false;
  }
}

function closeUploadModal() {
  trackingResolveModalEl.value?.close();
  uploadAnalyzing.value = false;
  analyzeResult.value = null;
  fileContent.value = '';
  fileName.value = '';
  resolveTargetRutaId.value = null;
  resolveNewRutaNombre.value = '';
}

// --- Limpiar servicio ---
const limpiarModalEl = ref<HTMLDialogElement | null>(null);
const limpiarServicioId = ref('');
const limpiarLoading = ref(false);

function openLimpiarModal() {
  limpiarServicioId.value = '';
  limpiarModalEl.value?.showModal();
}

function closeLimpiarModal() {
  limpiarModalEl.value?.close();
}

async function submitLimpiar() {
  const svcId = limpiarServicioId.value.trim();
  if (!svcId) return;
  limpiarLoading.value = true;
  try {
    const res = await fetch(`/api/infra/servicios/${encodeURIComponent(svcId)}/empalmes`, {
      method: 'DELETE',
      credentials: 'include',
      headers: { Accept: 'application/json', 'X-CSRF-Token': csrf() },
    });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).detail ?? `Error ${res.status}`);
    closeLimpiarModal();
    showToast('success', 'Servicio limpiado', (data as Record<string, string>).message ?? '');
    if (hasSearched.value) await searchCamaras();
  } catch (e: unknown) {
    showToast('error', 'Error al limpiar servicio', e instanceof Error ? e.message : String(e));
  } finally {
    limpiarLoading.value = false;
  }
}

// --- Descargar: dropdown de exportación ---
const downloadDropdownEl = ref<HTMLElement | null>(null);
const isDownloadMenuOpen = ref(false);

function toggleDownloadMenu() {
  isDownloadMenuOpen.value = !isDownloadMenuOpen.value;
}

function _closeDownloadMenu(e: MouseEvent) {
  if (downloadDropdownEl.value && !downloadDropdownEl.value.contains(e.target as Node)) {
    isDownloadMenuOpen.value = false;
  }
}

onMounted(() => document.addEventListener('click', _closeDownloadMenu));
onUnmounted(() => document.removeEventListener('click', _closeDownloadMenu));

async function downloadCameras(format: 'xlsx' | 'csv', filterStatus: string | null) {
  isDownloadMenuOpen.value = false;
  const params = new URLSearchParams({ format });
  if (filterStatus) params.set('filter_status', filterStatus);
  if (!filterStatus && searchTerms.value.length === 1 && /^\d+$/.test(searchTerms.value[0].trim())) {
    params.set('servicio_id', searchTerms.value[0].trim());
  }
  const ext = format === 'csv' ? 'csv' : 'xlsx';
  const filterLabel = filterStatus ? ` (${filterStatus})` : '';
  showToast('info', 'Preparando descarga...', `Exportando cámaras${filterLabel} en ${format.toUpperCase()}`);
  try {
    const res = await fetch(`/api/infra/export/cameras?${params.toString()}`, { credentials: 'include' });
    if (!res.ok) throw new Error(`Error ${res.status}`);
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') ?? '';
    const match = cd.match(/filename="(.+?)"/);
    const filename = match ? match[1] : `camaras_${Date.now()}.${ext}`;
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);
    showToast('success', 'Descarga completa', filename);
  } catch (e: unknown) {
    showToast('error', 'Error al descargar', e instanceof Error ? e.message : String(e));
  }
}
</script>

<style scoped>
.infra-panel { padding: 16px; }
.infra-search-row { display: flex; gap: 8px; flex-wrap: wrap; }
.infra-search-row input { flex: 1; min-width: 220px; }
.infra-search-terms { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.infra-search-term {
  display: inline-flex; align-items: center; gap: 4px;
  background: rgba(59,130,246,.15); color: #60a5fa;
  border: 1px solid rgba(59,130,246,.3); border-radius: 14px;
  padding: 3px 10px 3px 10px; font-size: .82rem;
}
.infra-search-term-remove { background: none; border: none; cursor: pointer; color: inherit; padding: 0; line-height: 1; }
.infra-status { margin-top: 10px; font-size: .85rem; }
.infra-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin-top: 16px; }
.infra-empty { margin-top: 32px; text-align: center; color: var(--muted); }
.infra-loading { margin-top: 32px; text-align: center; color: var(--muted); }
.infra-camara-card { background: #1a1a1a; border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
.infra-camara-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.infra-camara-estado { display: flex; align-items: center; gap: 6px; font-size: .85rem; }
.infra-estado-icon { width: 10px; height: 10px; border-radius: 50%; display: inline-block; background: #6b7280; }
.infra-estado-icon.libre { background: #22c55e; }
.infra-estado-icon.baneada { background: #ef4444; }
.infra-estado-icon.en_mantenimiento { background: #f59e0b; }
.infra-estado-icon.inaccesible { background: #9ca3af; }
.infra-camara-nombre { font-weight: 600; font-size: .9rem; color: var(--text); margin-bottom: 8px; }
.infra-camara-warning { font-size: .78rem; color: #f59e0b; margin-bottom: 6px; }
.infra-camara-servicios { display: flex; flex-wrap: wrap; gap: 6px; }
.infra-servicio-chip { padding: 3px 8px; border-radius: 12px; font-size: .78rem; color: #fff; display: inline-flex; align-items: center; gap: 4px; }
.infra-no-servicios { color: var(--muted); font-size: .82rem; }
.infra-edit-btn { font-size: .75rem; padding: 3px 8px; background: rgba(255,255,255,.07); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; color: var(--text); }
.infra-ban-ticket { margin-top: 6px; font-size: .78rem; color: #ef4444; }
/* Modal */
.camera-state-modal, .tracking-detail-modal { border: 1px solid var(--border); border-radius: 10px; background: #1c1c1c; color: var(--text); padding: 24px; max-width: 520px; width: 95vw; max-height: 90vh; overflow-y: auto; }
.camera-state-modal::backdrop, .tracking-detail-modal::backdrop { background: rgba(0,0,0,.6); }
.camera-state-title-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.camera-state-meta-row { display: flex; gap: 16px; flex-wrap: wrap; font-size: .85rem; margin-bottom: 8px; color: var(--muted); }
.camera-state-badge { padding: 2px 8px; border-radius: 10px; font-size: .75rem; }
.camera-state-badge.ok { background: rgba(34,197,94,.15); color: #22c55e; }
.camera-state-badge.warning { background: rgba(245,158,11,.15); color: #f59e0b; }
.camera-state-incidents { margin: 12px 0; }
.camera-state-incidents-title { font-size: .8rem; font-weight: 600; color: var(--muted); margin-bottom: 6px; }
.camera-state-incident-item { font-size: .82rem; padding: 6px 0; border-bottom: 1px solid var(--border); display: flex; gap: 12px; flex-wrap: wrap; }
.camera-state-empty { font-size: .82rem; color: var(--muted); margin: 8px 0; }
.camera-state-select { width: 100%; margin: 8px 0 14px; }
.camera-state-actions { display: flex; gap: 8px; margin-top: 14px; }
.close-btn { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 1.3rem; margin-left: auto; }
/* Tracking modal */
.tracking-detail-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.tracking-detail-title { margin: 0; font-size: 1rem; flex: 1; }
.tracking-detail-close { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 1.3rem; }
.tracking-download-btn { font-size: .78rem; padding: 4px 10px; background: rgba(255,255,255,.07); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; color: var(--text); }
.tracking-rutas-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.tracking-ruta-tab { padding: 5px 12px; border-radius: 14px; font-size: .8rem; border: 1px solid var(--border); background: none; cursor: pointer; color: var(--text); }
.tracking-ruta-tab.active { background: var(--tab-color, #3b82f6); color: #fff; border-color: transparent; }
.tracking-sequence { display: flex; flex-direction: column; gap: 6px; }
.tracking-item { display: flex; align-items: flex-start; gap: 8px; font-size: .85rem; padding: 6px 0; border-bottom: 1px solid var(--border); }
.tracking-punta { color: #60a5fa; }
.tracking-punta-label { font-size: .72rem; color: var(--muted); display: block; }
.tracking-cable { flex-direction: column; gap: 2px; }
.tracking-cable-name { font-weight: 600; }
.tracking-atenuacion { color: #f59e0b; font-size: .78rem; }
.tracking-empalme-id { color: var(--muted); font-size: .75rem; }
.tracking-loading, .tracking-error, .tracking-empty { padding: 16px; color: var(--muted); font-size: .85rem; }
.tracking-error { color: #ef4444; }
/* Toasts */
.toast-container { position: fixed; bottom: 24px; right: 24px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
.toast { display: flex; align-items: flex-start; gap: 10px; background: #1e1e1e; border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; min-width: 260px; max-width: 380px; pointer-events: all; box-shadow: 0 4px 12px rgba(0,0,0,.4); }
.toast.success { border-left: 3px solid #22c55e; }
.toast.error { border-left: 3px solid #ef4444; }
.toast.warning { border-left: 3px solid #f59e0b; }
.toast.info { border-left: 3px solid #3b82f6; }
.toast-icon { font-size: 1rem; line-height: 1; }
.toast-content { flex: 1; }
.toast-title { font-weight: 600; font-size: .88rem; }
.toast-message { font-size: .82rem; color: var(--muted); margin-top: 2px; }
.toast-close { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 1.1rem; padding: 0; }
.toast-anim-enter-active, .toast-anim-leave-active { transition: all .25s ease; }
.toast-anim-enter-from, .toast-anim-leave-to { opacity: 0; transform: translateX(24px); }

/* Estado icons — colores faltantes en la migración */
.infra-estado-icon.ocupada { background: #f59e0b; }
.infra-estado-icon.detectada { background: #9ca3af; }

/* Toolbar */
.infra-toolbar {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;
  gap: 10px; padding: 12px 0 16px; border-bottom: 1px solid var(--border); margin-bottom: 16px;
}
.infra-toolbar-title { margin: 0; font-size: 1.05rem; font-weight: 700; color: var(--text); }
.infra-toolbar-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

/* Zona Drag & Drop de upload tracking */
.upload-drop-zone {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 7px 14px; border-radius: 8px; font-size: .88rem; font-weight: 500; cursor: pointer;
  user-select: none; transition: background .15s, border-color .15s;
  background: rgba(255,255,255,.06); color: var(--text);
  border: 1.5px dashed var(--border);
  min-height: 36px;
}
.upload-drop-zone:hover { background: rgba(255,255,255,.12); border-color: #60a5fa; }
.upload-drop-zone.drag-over {
  background: rgba(96,165,250,.12); border-color: #60a5fa;
  color: #60a5fa; outline: none;
}

/* Botones extra (modificadores de .btn global) */
.btn.danger { background: rgba(239,68,68,.15); color: #ef4444; border: 1px solid rgba(239,68,68,.3); }
.btn.danger:hover:not(:disabled) { background: rgba(239,68,68,.25); }
.btn.danger-subtle { background: none; color: #ef4444; border: 1px solid rgba(239,68,68,.2); }
.btn.danger-subtle:hover:not(:disabled) { background: rgba(239,68,68,.1); }
.btn.success { background: rgba(34,197,94,.15); color: #22c55e; border: 1px solid rgba(34,197,94,.3); }
.btn.success:hover:not(:disabled) { background: rgba(34,197,94,.25); }

/* Dropdown descargar */
.download-dropdown-wrapper { position: relative; }
.dropdown-caret { display: inline-block; transition: transform .2s; font-size: .75rem; margin-left: 2px; }
.dropdown-caret.open { transform: rotate(180deg); }
.download-dropdown-menu {
  position: absolute; top: calc(100% + 4px); right: 0; z-index: 200;
  min-width: 180px; margin: 0; padding: 4px 0; list-style: none;
  background: #1e1e1e; border: 1px solid var(--border); border-radius: 8px;
  box-shadow: 0 6px 18px rgba(0,0,0,.45);
}
.dropdown-item {
  padding: 9px 14px; font-size: .85rem; cursor: pointer;
  color: var(--text); display: flex; align-items: center; gap: 7px; white-space: nowrap;
}
.dropdown-item:hover { background: rgba(255,255,255,.07); }
.dropdown-divider { border: none; border-top: 1px solid var(--border); margin: 4px 0; }
.btn.warning { background: rgba(245,158,11,.15); color: #f59e0b; border: 1px solid rgba(245,158,11,.3); }
.btn.warning:hover:not(:disabled) { background: rgba(245,158,11,.25); }

/* Leyenda de estados */
.infra-legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 12px 0 8px; font-size: .8rem; color: var(--muted); }
.infra-legend-item { display: flex; align-items: center; gap: 5px; }
.infra-legend-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.infra-legend-dot.libre { background: #22c55e; }
.infra-legend-dot.ocupada { background: #f59e0b; }
.infra-legend-dot.baneada { background: #ef4444; }
.infra-legend-dot.detectada { background: #9ca3af; }

/* Modal genérico compartido */
.infra-generic-modal {
  border: 1px solid var(--border); border-radius: 10px; background: #1c1c1c;
  color: var(--text); padding: 0; max-width: 520px; width: 95vw; max-height: 90vh; overflow-y: auto;
}
.infra-generic-modal::backdrop { background: rgba(0,0,0,.6); }
.modal-inner { padding: 24px; display: flex; flex-direction: column; gap: 6px; }
.modal-header-row { display: flex; align-items: center; margin-bottom: 10px; }
.modal-title { margin: 0; font-size: 1rem; flex: 1; }
.modal-desc { margin: 0 0 6px; font-size: .83rem; color: var(--muted); }
.danger-text { color: #f59e0b; }
.req { color: #ef4444; }
.modal-actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
.resolve-conflict-actions { gap: 6px; }

/* Modal de resolución de tracking */
.tracking-resolve-modal { max-width: 580px; }
.upload-analyzing { padding: 16px 0; font-size: .88rem; color: var(--muted); }
.resolve-status-badge {
  display: inline-block; padding: 4px 12px; border-radius: 12px;
  font-size: .82rem; font-weight: 700; margin-bottom: 6px; background: rgba(255,255,255,.07);
}
.resolve-status-badge.status-new { background: rgba(59,130,246,.15); color: #60a5fa; }
.resolve-status-badge.status-identical { background: rgba(34,197,94,.15); color: #22c55e; }
.resolve-status-badge.status-conflict { background: rgba(245,158,11,.15); color: #f59e0b; }
.resolve-status-badge.status-potential_upgrade { background: rgba(168,85,247,.15); color: #c084fc; }
.resolve-status-badge.status-new_strand { background: rgba(168,85,247,.15); color: #c084fc; }
.resolve-status-badge.status-error { background: rgba(239,68,68,.15); color: #ef4444; }
.resolve-message { margin: 0 0 8px; font-size: .85rem; }
.resolve-svc-info { font-size: .83rem; color: var(--muted); margin-bottom: 8px; }
.resolve-hint { font-size: .85rem; color: var(--muted); margin: 4px 0 8px; }
.resolve-error { color: #ef4444; font-size: .85rem; margin: 8px 0; }
.resolve-rutas-list { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }
.resolve-ruta-item {
  display: flex; align-items: center; gap: 8px; font-size: .82rem;
  padding: 6px 8px; background: rgba(255,255,255,.04); border-radius: 6px;
}
.resolve-ruta-meta { font-size: .78rem; color: var(--muted); }
.resolve-select { width: 100%; margin: 4px 0 10px; }
.resolve-upgrade-info {
  font-size: .83rem; background: rgba(255,255,255,.04); border-radius: 6px;
  padding: 8px 10px; margin: 6px 0; display: flex; flex-direction: column; gap: 3px;
}
</style>
