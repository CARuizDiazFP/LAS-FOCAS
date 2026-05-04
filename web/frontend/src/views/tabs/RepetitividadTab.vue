<!--
  Nombre de archivo: RepetitividadTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/RepetitividadTab.vue
  Descripción: Tab de generación de Informe de Repetitividad — migrado desde panel.js
-->
<template>
  <article class="card">
    <header class="card-header">
      <h1>Informe de Repetitividad</h1>
      <span class="badge">FO Legacy+</span>
    </header>
    <p class="muted">Podés cargar un Excel o tomar los datos directo desde la base. El período sólo se usa como etiqueta en los archivos generados.</p>
    <div class="stack">
      <div
        class="dropzone"
        :class="{ disabled: useDb, drag: isDrag }"
        :aria-disabled="useDb"
        @click="!useDb && fileEl?.click()"
        @dragover.prevent="!useDb && (isDrag = true)"
        @dragleave="isDrag = false"
        @drop.prevent="handleDrop"
      >
        <input ref="fileEl" type="file" accept=".xlsx" hidden @change="onFileChange" />
        <span>{{ dropLabel }}</span>
      </div>
      <div class="form-grid">
        <div class="field">
          <label class="form-label">Mes</label>
          <input v-model.number="mes" type="number" min="1" max="12" required />
        </div>
        <div class="field">
          <label class="form-label">Año</label>
          <input v-model.number="anio" type="number" min="2000" max="2100" required />
        </div>
      </div>
      <label class="checkbox">
        <input v-model="includePdf" type="checkbox" /> Generar PDF si está disponible
      </label>
      <label class="checkbox">
        <input v-model="withGeo" type="checkbox" /> Incluir mapas GEO por servicio
      </label>
      <label class="checkbox">
        <input v-model="useDb" type="checkbox" /> Usar reclamos desde la base de datos (ignora archivo)
      </label>
      <div class="card-actions">
        <button class="btn primary" :disabled="loading" @click="generate">Generar</button>
        <RouterLink class="btn subtle" to="/reports-history" target="_blank">Carpeta de reportes</RouterLink>
      </div>
    </div>
    <div :class="['result-box', resultClass]">{{ resultText }}</div>
    <div v-if="links.length" class="card-actions" style="margin-top:8px">
      <a v-for="l in links" :key="l.href" :href="l.href" target="_blank" rel="noopener" class="btn subtle">{{ l.label }}</a>
    </div>
  </article>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useSession } from '../../composables/useSession';

const { csrf } = useSession();
const mes = ref(new Date().getMonth() + 1);
const anio = ref(new Date().getFullYear());
const includePdf = ref(true);
const withGeo = ref(false);
const useDb = ref(false);
const isDrag = ref(false);
const loading = ref(false);
const resultText = ref('Aún no se generó ningún informe.');
const resultClass = ref('muted');
const links = ref<{ label: string; href: string }[]>([]);
const fileEl = ref<HTMLInputElement | null>(null);
let selectedFile: File | null = null;

const dropLabel = computed(() => {
  if (useDb.value) return 'Usando datos desde la base (archivo opcional)';
  return selectedFile ? `Seleccionado: ${selectedFile.name}` : 'Arrastrá el .xlsx acá o hacé click';
});

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  selectedFile = input.files?.[0] ?? null;
}

function handleDrop(e: DragEvent) {
  isDrag.value = false;
  if (useDb.value) return;
  const f = e.dataTransfer?.files?.[0];
  if (f) { selectedFile = f; }
}

async function generate() {
  if (!useDb.value && !selectedFile) {
    resultText.value = 'Seleccioná un archivo';
    resultClass.value = 'error';
    return;
  }
  links.value = [];
  resultText.value = 'Procesando...';
  resultClass.value = 'info';
  loading.value = true;
  const data = new FormData();
  if (selectedFile && !useDb.value) data.append('file', selectedFile);
  data.append('mes', String(mes.value));
  data.append('anio', String(anio.value));
  data.append('include_pdf', includePdf.value ? 'true' : 'false');
  data.append('with_geo', withGeo.value ? 'true' : 'false');
  data.append('use_db', useDb.value ? 'true' : 'false');
  data.append('csrf_token', csrf());
  try {
    const res = await fetch('/api/flows/repetitividad', { method: 'POST', body: data, credentials: 'include' });
    const j = await res.json();
    if (!res.ok) throw new Error(j.error ?? 'Error');
    const newLinks: typeof links.value = [];
    if (j.docx) newLinks.push({ label: 'DOCX', href: j.docx });
    if (j.pdf) newLinks.push({ label: 'PDF', href: j.pdf });
    (j.map_images ?? []).forEach((url: string, idx: number) => {
      newLinks.push({ label: (j.map_images.length > 1 ? `Mapa PNG ${idx + 1}` : 'Mapa PNG'), href: url });
    });
    links.value = newLinks;
    resultText.value = newLinks.length ? 'Listo.' : 'Generado sin archivos de salida.';
    resultClass.value = 'success';
  } catch (e: unknown) {
    resultText.value = `Error: ${e instanceof Error ? e.message : String(e)}`;
    resultClass.value = 'error';
  } finally {
    loading.value = false;
  }
}
</script>
