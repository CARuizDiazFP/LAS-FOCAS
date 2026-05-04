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

    <!-- Main content -->
    <div class="infra-panel">
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
import { ref, computed } from 'vue';
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
</style>
