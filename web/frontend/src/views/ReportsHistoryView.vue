<!--
  Nombre de archivo: ReportsHistoryView.vue
  Ubicación de archivo: web/frontend/src/views/ReportsHistoryView.vue
  Descripción: Vista de historial de reportes generados — lista archivos desde /api/reports/history
-->
<template>
  <div class="reports-view">
    <header class="reports-header">
      <h1>Historial de Reportes</h1>
      <button class="btn subtle" @click="loadFiles">Actualizar</button>
    </header>

    <div v-if="loading" class="result-box info">Cargando...</div>
    <div v-else-if="error" class="result-box error">{{ error }}</div>
    <div v-else-if="files.length === 0" class="result-box muted">No hay reportes disponibles aún.</div>
    <table v-else class="reports-table">
      <thead>
        <tr>
          <th>Archivo</th>
          <th>Tamaño</th>
          <th>Fecha</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="f in files" :key="f.href">
          <td class="file-name">{{ f.name }}</td>
          <td class="file-size">{{ formatSize(f.size) }}</td>
          <td class="file-date">{{ formatDate(f.mtime) }}</td>
          <td>
            <a :href="f.href" target="_blank" rel="noopener" class="btn subtle small">Descargar</a>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';

interface ReportFile {
  name: string;
  size: number;
  mtime: number;
  href: string;
}

const files = ref<ReportFile[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

async function loadFiles() {
  loading.value = true;
  error.value = null;
  try {
    const res = await fetch('/api/reports/history', { credentials: 'include' });
    if (!res.ok) throw new Error(`Error ${res.status}`);
    const data = await res.json();
    files.value = data.files ?? [];
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Error cargando reportes';
  } finally {
    loading.value = false;
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' });
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
}
.reports-table tr:hover td { background: rgba(255,255,255,0.02); }
.file-name { font-family: "SFMono-Regular", Consolas, monospace; font-size: 0.85rem; }
.file-size, .file-date { color: var(--muted); font-size: 0.82rem; }
.btn.small { padding: 5px 10px; font-size: 0.8rem; }
</style>
