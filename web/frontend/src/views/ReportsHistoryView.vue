<!--
  Nombre de archivo: ReportsHistoryView.vue
  Ubicación de archivo: web/frontend/src/views/ReportsHistoryView.vue
  Descripción: Vista de histórico persistente de reportes generados desde /api/reports/history
-->
<template>
  <div class="reports-view">
    <header class="reports-header">
      <h1>Historial de Reportes</h1>
      <button class="btn subtle" @click="loadFiles">Actualizar</button>
    </header>

    <section class="filters" aria-label="Filtros de reportes">
      <label>
        <span>Tipo</span>
        <select v-model="filters.type" @change="loadFiles">
          <option value="">Todos</option>
          <option value="sla">SLA</option>
          <option value="repetitividad">Repetitividad</option>
        </select>
      </label>
      <label>
        <span>Estado</span>
        <select v-model="filters.status" @change="loadFiles">
          <option value="">Todos</option>
          <option value="success">Correcto</option>
          <option value="error">Error</option>
          <option value="running">En curso</option>
        </select>
      </label>
      <label>
        <span>Mes</span>
        <input v-model.number="filters.month" min="1" max="12" type="number" @change="loadFiles" />
      </label>
      <label>
        <span>Año</span>
        <input v-model.number="filters.year" min="2000" max="2100" type="number" @change="loadFiles" />
      </label>
      <button class="btn subtle small" @click="clearFilters">Limpiar</button>
    </section>

    <div v-if="loading" class="result-box info">Cargando...</div>
    <div v-else-if="error" class="result-box error">{{ error }}</div>
    <div v-else-if="items.length === 0" class="result-box muted">No hay reportes disponibles aún.</div>
    <table v-else class="reports-table">
      <thead>
        <tr>
          <th>Estado</th>
          <th>Informe</th>
          <th>Período</th>
          <th>Fuente</th>
          <th>Usuario</th>
          <th>Fecha</th>
          <th>Duración</th>
          <th>Salidas</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.id">
          <td><span :class="['status-pill', item.status]">{{ statusLabel(item.status) }}</span></td>
          <td>{{ reportLabel(item.report_type) }}</td>
          <td>{{ formatPeriod(item.period_month, item.period_year) }}</td>
          <td>{{ sourceLabel(item.source) }}</td>
          <td>{{ item.username }}</td>
          <td class="file-date">{{ formatIsoDate(item.started_at) }}</td>
          <td class="file-size">{{ formatDuration(item.duration_ms) }}</td>
          <td>
            <div class="outputs">
              <a
                v-for="link in outputLinks(item)"
                :key="`${item.id}-${link.label}-${link.href}`"
                :href="link.href"
                target="_blank"
                rel="noopener"
                class="btn subtle small"
              >
                {{ link.label }}
              </a>
            </div>
          </td>
          <td class="error-cell">
            {{ item.error_message || item.error_code || '-' }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';

interface ReportHistoryItem {
  id: number;
  report_type: string;
  status: string;
  username: string;
  source: string;
  period_month: number;
  period_year: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  input_metadata: Record<string, unknown>;
  output_metadata: {
    outputs?: Record<string, string | string[]>;
    stats?: Record<string, unknown>;
  };
  error_code: string | null;
  error_message: string | null;
}

const items = ref<ReportHistoryItem[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);
const filters = ref({
  type: '',
  status: '',
  month: undefined as number | undefined,
  year: undefined as number | undefined,
});

async function loadFiles() {
  loading.value = true;
  error.value = null;
  try {
    const params = new URLSearchParams();
    if (filters.value.type) params.set('type', filters.value.type);
    if (filters.value.status) params.set('status', filters.value.status);
    if (filters.value.month) params.set('month', String(filters.value.month));
    if (filters.value.year) params.set('year', String(filters.value.year));
    const query = params.toString();
    const res = await fetch(`/api/reports/history${query ? `?${query}` : ''}`, { credentials: 'include' });
    if (!res.ok) throw new Error(`Error ${res.status}`);
    const data = await res.json();
    items.value = data.items ?? [];
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Error cargando reportes';
  } finally {
    loading.value = false;
  }
}

function clearFilters() {
  filters.value = { type: '', status: '', month: undefined, year: undefined };
  loadFiles();
}

function reportLabel(value: string): string {
  if (value === 'sla') return 'SLA';
  if (value === 'repetitividad') return 'Repetitividad';
  return value;
}

function statusLabel(value: string): string {
  if (value === 'success') return 'Correcto';
  if (value === 'error') return 'Error';
  if (value === 'running') return 'En curso';
  return value;
}

function sourceLabel(value: string): string {
  if (value === 'excel-legacy') return 'Excel legacy';
  if (value === 'excel') return 'Excel';
  if (value === 'db') return 'Base';
  return value;
}

function formatPeriod(month: number, year: number): string {
  return `${String(month).padStart(2, '0')}/${year}`;
}

function formatDuration(ms: number | null): string {
  if (ms === null || ms === undefined) return '-';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function formatIsoDate(value: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' });
}

function outputLinks(item: ReportHistoryItem): { label: string; href: string }[] {
  const outputs = item.output_metadata?.outputs ?? {};
  const links: { label: string; href: string }[] = [];
  Object.entries(outputs).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((href, idx) => {
        if (href) links.push({ label: value.length > 1 ? `${labelForOutput(key)} ${idx + 1}` : labelForOutput(key), href });
      });
    } else if (value) {
      links.push({ label: labelForOutput(key), href: value });
    }
  });
  return links;
}

function labelForOutput(key: string): string {
  if (key === 'docx') return 'DOCX';
  if (key === 'pdf') return 'PDF';
  if (key === 'map_image') return 'Mapa';
  if (key === 'map_images') return 'Mapa';
  return key.toUpperCase();
}

onMounted(loadFiles);
</script>

<style scoped>
.reports-view { padding: 24px; }
.reports-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.reports-header h1 { margin: 0; font-size: 1.4rem; color: var(--text); }
.filters {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 10px;
  align-items: end;
  margin-bottom: 18px;
}
.filters label {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 0.78rem;
}
.filters select,
.filters input {
  width: 100%;
  min-height: 36px;
  border: 1px solid var(--border);
  color: var(--text);
  background: rgba(255,255,255,0.04);
  padding: 7px 9px;
}
.reports-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.reports-table th {
  text-align: left;
  padding: 10px 12px;
  color: var(--muted);
  font-weight: 600;
  text-transform: uppercase;
  font-size: 0.72rem;
  letter-spacing: 0.06em;
  border-bottom: 1px solid var(--border);
}
.reports-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  vertical-align: top;
}
.reports-table tr:hover td { background: rgba(255,255,255,0.02); }
.file-size, .file-date { color: var(--muted); font-size: 0.82rem; }
.btn.small { padding: 5px 10px; font-size: 0.8rem; }
.outputs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.status-pill {
  display: inline-flex;
  min-width: 72px;
  justify-content: center;
  padding: 4px 7px;
  border-radius: 999px;
  border: 1px solid var(--border);
  font-size: 0.76rem;
}
.status-pill.success { color: #7ee787; border-color: rgba(126,231,135,0.45); }
.status-pill.error { color: #ff9b9b; border-color: rgba(255,155,155,0.45); }
.status-pill.running { color: #ffd166; border-color: rgba(255,209,102,0.45); }
.error-cell {
  max-width: 260px;
  color: var(--muted);
  overflow-wrap: anywhere;
}
@media (max-width: 900px) {
  .filters { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
  .reports-table { min-width: 920px; }
  .reports-view { overflow-x: auto; }
}
</style>
