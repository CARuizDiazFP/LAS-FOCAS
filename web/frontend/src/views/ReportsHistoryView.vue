<!--
  Nombre de archivo: ReportsHistoryView.vue
  Ubicación de archivo: web/frontend/src/views/ReportsHistoryView.vue
  Descripción: Vista de histórico persistente de reportes generados desde /api/reports/history
-->
<template>
  <section class="reports-view">
    <header class="reports-view__header">
      <div>
        <span class="reports-view__kicker">Reportes</span>
        <h1>Historial</h1>
        <p class="reports-view__subtitle">Todas las corridas registradas, con sus salidas.</p>
      </div>
      <button class="btn subtle" @click="loadFiles">
        <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
        Actualizar
      </button>
    </header>

    <hr class="noc-rule" />

    <section class="reports-view__filters" aria-label="Filtros de reportes">
      <label class="reports-view__field reports-view__field--type">
        <span>Tipo</span>
        <select v-model="filters.type" @change="loadFiles">
          <option value="">Todos</option>
          <option value="sla">SLA</option>
          <option value="repetitividad">Repetitividad</option>
        </select>
      </label>
      <label class="reports-view__field reports-view__field--status">
        <span>Estado</span>
        <select v-model="filters.status" @change="loadFiles">
          <option value="">Todos</option>
          <option value="success">Correcto</option>
          <option value="error">Error</option>
          <option value="running">En curso</option>
        </select>
      </label>
      <label class="reports-view__field reports-view__field--month">
        <span>Mes</span>
        <input v-model.number="filters.month" min="1" max="12" type="number" @change="loadFiles" />
      </label>
      <label class="reports-view__field reports-view__field--year">
        <span>Año</span>
        <input v-model.number="filters.year" min="2000" max="2100" type="number" @change="loadFiles" />
      </label>
      <button class="btn reports-view__clear" @click="clearFilters">Limpiar</button>
      <span class="reports-view__count"><strong>{{ items.length }}</strong> corridas</span>
    </section>

    <div class="reports-view__scroll">
      <div v-if="loading" class="reports-view__state-box">
        <i class="ph ph-circle-notch reports-view__spin" aria-hidden="true"></i>
        Cargando...
      </div>
      <div v-else-if="error" class="reports-view__state-box is-error">
        <i class="ph ph-warning-circle" aria-hidden="true"></i>
        <p>{{ error }}</p>
      </div>
      <div v-else-if="items.length === 0" class="reports-view__state-box">
        <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
        <p>No hay reportes disponibles aún.</p>
      </div>
      <table v-else class="reports-view__table">
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
            <td><span :class="['reports-view__pill', `is-${item.status}`]">{{ statusLabel(item.status) }}</span></td>
            <td>{{ reportLabel(item.report_type) }}</td>
            <td class="reports-view__num">{{ formatPeriod(item.period_month, item.period_year) }}</td>
            <td class="reports-view__muted">{{ sourceLabel(item.source) }}</td>
            <td class="reports-view__muted">{{ item.username }}</td>
            <td class="reports-view__num reports-view__muted">{{ formatIsoDate(item.started_at) }}</td>
            <td class="reports-view__num reports-view__muted">{{ formatDuration(item.duration_ms) }}</td>
            <td>
              <div class="reports-view__outputs">
                <a
                  v-for="link in outputLinks(item)"
                  :key="`${item.id}-${link.label}-${link.href}`"
                  :href="link.href"
                  target="_blank"
                  rel="noopener"
                  class="reports-view__output-link"
                >{{ link.label }}</a>
              </div>
            </td>
            <td class="reports-view__error-cell">
              {{ item.error_message || item.error_code || '—' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
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
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function formatIsoDate(value: string | null): string {
  if (!value) return '—';
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
.reports-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.reports-view__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 26px 0;
}

.reports-view__kicker {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.reports-view__header h1 {
  font-size: 27px;
  margin: 3px 0 0;
}

.reports-view__subtitle {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 52%, transparent);
}

.reports-view__header .btn {
  min-height: 34px;
  font-size: 12.5px;
}

.reports-view__filters {
  display: flex;
  align-items: flex-end;
  gap: 11px;
  padding: 15px 26px 14px;
  flex-wrap: wrap;
}

.reports-view__field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}

.reports-view__field--type,
.reports-view__field--status { width: 150px; }
.reports-view__field--month { width: 92px; }
.reports-view__field--year { width: 104px; }

.reports-view__field select,
.reports-view__field input {
  min-height: 36px;
  padding: 0 10px;
  font-size: 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.reports-view__clear {
  color: var(--color-accent);
  padding-inline: 2.8px;
}

.reports-view__clear:hover {
  background: transparent;
  text-decoration: underline;
}

.reports-view__count {
  margin-left: auto;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.reports-view__count strong {
  color: var(--color-text);
  font-weight: 500;
}

.reports-view__scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0 26px 26px;
}

.reports-view__state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  max-width: 260px;
  margin: 34px auto;
  padding: 34px 22px;
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-neutral-800);
  text-align: center;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.reports-view__state-box i {
  font-size: 26px;
  color: var(--color-neutral-600);
}

.reports-view__state-box p {
  margin: 0;
}

.reports-view__state-box.is-error {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-state-error) 45%, transparent);
}

.reports-view__state-box.is-error i {
  color: var(--color-state-error);
}

.reports-view__spin {
  animation: spin 1s linear infinite;
}

.reports-view__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.reports-view__table th {
  text-align: left;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  padding: var(--space-2);
  border-bottom: 1px solid transparent;
}

.reports-view__table td {
  padding: var(--space-2);
  border-bottom: 1px solid transparent;
}

.reports-view__table thead tr {
  background: linear-gradient(to right, transparent,
    var(--color-divider) 48px, var(--color-divider) calc(100% - 48px), transparent)
    no-repeat bottom / 100% 1px;
}

.reports-view__table tbody tr {
  background: linear-gradient(to right, transparent,
    color-mix(in srgb, var(--color-text) 8%, transparent) 48px,
    color-mix(in srgb, var(--color-text) 8%, transparent) calc(100% - 48px), transparent)
    no-repeat bottom / 100% 1px;
}

.reports-view__table tbody tr:hover {
  background:
    linear-gradient(color-mix(in srgb, var(--color-text) 4%, transparent),
                    color-mix(in srgb, var(--color-text) 4%, transparent)) no-repeat 0 0 / 100% 100%,
    linear-gradient(to right, transparent,
      color-mix(in srgb, var(--color-text) 8%, transparent) 48px,
      color-mix(in srgb, var(--color-text) 8%, transparent) calc(100% - 48px), transparent)
      no-repeat bottom / 100% 1px;
}

.reports-view__num {
  font-variant-numeric: tabular-nums;
}

.reports-view__muted {
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.reports-view__pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  white-space: nowrap;
  color: color-mix(in srgb, var(--color-text) 82%, transparent);
}

.reports-view__pill::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.reports-view__pill.is-success { border: 1px solid color-mix(in srgb, var(--color-state-ok) 40%, transparent); }
.reports-view__pill.is-running { border: 1px solid color-mix(in srgb, var(--color-state-warn) 40%, transparent); }
.reports-view__pill.is-error { border: 1px solid color-mix(in srgb, var(--color-state-error) 40%, transparent); }

.reports-view__outputs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.reports-view__output-link {
  font-size: 10.5px;
  padding: 2px 8px;
  border: 1px solid var(--color-divider);
  border-radius: 4px;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
  text-decoration: none;
}

.reports-view__output-link:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.reports-view__error-cell {
  max-width: 260px;
  overflow-wrap: anywhere;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.reports-view__error-cell:not(:empty) {
  color: var(--color-state-error);
}

@media (max-width: 900px) {
  .reports-view__table { min-width: 920px; }
  .reports-view__scroll { overflow-x: auto; }
}
</style>
