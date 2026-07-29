<!--
  Nombre de archivo: RepetitividadTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/RepetitividadTab.vue
  Descripción: Tab de generación de Informe de Repetitividad — migrado desde panel.js
-->
<template>
  <section class="rep-view">
    <header class="rep-view__header">
      <span class="rep-view__kicker">Reportes</span>
      <div class="rep-view__heading-row">
        <h1>Informe de Repetitividad</h1>
        <span class="rep-view__chip">FO Legacy+</span>
      </div>
      <p class="rep-view__context">
        Podés cargar un Excel o tomar los datos directo desde la base. El período sólo se usa como etiqueta en los
        archivos generados.
      </p>
    </header>

    <hr class="noc-rule" />

    <div class="rep-view__body">
      <div class="rep-view__column">
        <div
          class="rep-view__dropzone"
          :class="{ disabled: useDb, drag: isDrag }"
          :aria-disabled="useDb"
          @click="!useDb && fileEl?.click()"
          @dragover.prevent="!useDb && (isDrag = true)"
          @dragleave="isDrag = false"
          @drop.prevent="handleDrop"
        >
          <input ref="fileEl" type="file" accept=".xlsx" hidden @change="onFileChange" />
          <i class="ph ph-file-xls" aria-hidden="true"></i>
          <strong>{{ dropLabel }}</strong>
        </div>

        <div class="rep-view__period">
          <div class="rep-view__field">
            <label>Mes</label>
            <input v-model.number="mes" type="number" min="1" max="12" required />
          </div>
          <div class="rep-view__field">
            <label>Año</label>
            <input v-model.number="anio" type="number" min="2000" max="2100" required />
          </div>
        </div>

        <label class="rep-view__checkbox">
          <input v-model="includePdf" type="checkbox" />
          <span class="rep-view__checkbox-box"><i class="ph ph-check" aria-hidden="true"></i></span>
          Generar PDF si está disponible
        </label>
        <label class="rep-view__checkbox">
          <input v-model="withGeo" type="checkbox" />
          <span class="rep-view__checkbox-box"><i class="ph ph-check" aria-hidden="true"></i></span>
          Incluir mapas GEO por servicio
        </label>
        <label class="rep-view__checkbox">
          <input v-model="useDb" type="checkbox" />
          <span class="rep-view__checkbox-box"><i class="ph ph-check" aria-hidden="true"></i></span>
          Usar reclamos desde la base de datos (ignora archivo)
        </label>

        <div class="rep-view__actions">
          <button class="btn primary" :disabled="loading" @click="generate">
            <i class="ph ph-play" aria-hidden="true"></i>
            Generar
          </button>
          <RouterLink class="btn subtle" to="/reports-history" target="_blank">Carpeta de reportes</RouterLink>
        </div>
      </div>

      <div class="rep-view__column">
        <div v-if="links.length" class="rep-view__card">
          <header>
            <i class="ph ph-repeat" aria-hidden="true"></i>
            <h2>Salidas de la última corrida</h2>
          </header>
          <div class="rep-view__hairline"></div>
          <div class="rep-view__outputs">
            <a v-for="l in links" :key="l.href" :href="l.href" target="_blank" rel="noopener" class="rep-view__output-link">{{ l.label }}</a>
          </div>
        </div>

        <div class="rep-view__status-box" :class="`is-${resultClass}`">
          <span class="rep-view__status-label">Estado</span>
          <p>{{ resultText }}</p>
        </div>
      </div>
    </div>
  </section>
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

<style scoped>
.rep-view {
  padding-bottom: 26px;
}

.rep-view__header {
  padding: 22px 26px 0;
}

.rep-view__kicker {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.rep-view__heading-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}

.rep-view__heading-row h1 {
  font-size: 27px;
  margin: 3px 0 0;
}

.rep-view__chip {
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 10.5px;
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.rep-view__context {
  max-width: 620px;
  margin: 8px 0 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: color-mix(in srgb, var(--color-text) 52%, transparent);
  text-wrap: pretty;
}

.rep-view__body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 22px;
  padding: 20px 26px 26px;
}

.rep-view__column {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.rep-view__dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 34px 22px;
  border: 1px dashed var(--color-neutral-700);
  border-radius: var(--radius-md);
  text-align: center;
  cursor: pointer;
}

.rep-view__dropzone i {
  font-size: 26px;
  color: var(--color-neutral-500);
}

.rep-view__dropzone strong {
  font-family: var(--font-heading);
  font-size: 14px;
  font-weight: 500;
}

.rep-view__dropzone:hover,
.rep-view__dropzone.drag {
  border-color: var(--color-accent);
}

.rep-view__dropzone.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.rep-view__period {
  display: grid;
  grid-template-columns: 120px 120px;
  gap: 11px;
}

.rep-view__field label {
  display: block;
  margin-bottom: 5px;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}

.rep-view__field input {
  width: 100%;
  min-height: 36px;
  padding: 0 10px;
  font-size: 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.rep-view__checkbox {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 13px;
  cursor: pointer;
}

.rep-view__checkbox input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
}

.rep-view__checkbox-box {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  flex: none;
  border-radius: 4px;
  border: 1px solid var(--color-divider);
}

.rep-view__checkbox-box i {
  font-size: 11px;
  color: var(--color-accent);
  opacity: 0;
}

.rep-view__checkbox input:checked + .rep-view__checkbox-box {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 20%, transparent);
}

.rep-view__checkbox input:checked + .rep-view__checkbox-box i {
  opacity: 1;
}

.rep-view__checkbox input:focus-visible + .rep-view__checkbox-box {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}

.rep-view__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.rep-view__actions .btn {
  min-height: 38px;
}

.rep-view__card {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 14px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.rep-view__card header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rep-view__card header i {
  font-size: 16px;
  color: var(--color-accent);
}

.rep-view__card h2 {
  margin: 0;
  font-size: 15px;
}

.rep-view__hairline {
  height: 1px;
  background: var(--color-divider);
}

.rep-view__outputs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.rep-view__output-link {
  font-size: 11px;
  padding: 3px 9px;
  border: 1px solid var(--color-divider);
  border-radius: 4px;
  color: color-mix(in srgb, var(--color-text) 72%, transparent);
  text-decoration: none;
}

.rep-view__output-link:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.rep-view__status-box {
  padding: 12px 14px;
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-neutral-800);
}

.rep-view__status-label {
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-neutral-500);
}

.rep-view__status-box p {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
}

.rep-view__status-box.is-success {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-state-ok) 45%, transparent);
}

.rep-view__status-box.is-error {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-state-error) 45%, transparent);
}

.rep-view__status-box.is-error p {
  color: var(--color-state-error);
}

@media (max-width: 1100px) {
  .rep-view__body {
    grid-template-columns: 1fr;
  }
}
</style>
