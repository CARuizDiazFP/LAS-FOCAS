<!--
  Nombre de archivo: SlaConsumoPanel.vue
  Ubicación de archivo: web/frontend/src/components/sla/SlaConsumoPanel.vue
  Descripción: Pestaña "SLA consumido": sube Servicios + Reclamos, persiste el histórico y genera el informe
-->
<template>
  <div class="sla-consumo">
    <header class="sla-consumo__header">
      <span class="sla-consumo__kicker">Reportes</span>
      <h1>SLA consumido</h1>
      <p class="sla-consumo__context">
        Subí los Excel de Servicios y Reclamos del corte. Los reclamos se guardan en el histórico y el informe
        muestra cuánto del presupuesto de SLA consumió cada servicio.
      </p>
    </header>

    <hr class="noc-rule" />

    <div class="sla-consumo__body">
      <div class="sla-consumo__column">
        <div
          class="sla-consumo__dropzone"
          :class="{ drag: isDrag }"
          @click="fileEl?.click()"
          @dragover.prevent="isDrag = true"
          @dragleave="isDrag = false"
          @drop.prevent="onDrop"
        >
          <input ref="fileEl" type="file" accept=".xlsx" multiple hidden @change="onFileChange" />
          <i class="ph ph-file-xls" aria-hidden="true"></i>
          <strong>{{ dropLabel }}</strong>
          <span class="sla-consumo__hint">Servicios Fuera de SLA.xlsx + Reclamos SLA.xlsx</span>
        </div>

        <div v-if="archivos.length > 0" class="sla-consumo__files">
          <span v-for="file in archivos" :key="file.name" class="sla-consumo__chip">
            <i class="ph ph-check-circle" aria-hidden="true"></i>
            {{ file.name }}
          </span>
        </div>

        <label class="sla-consumo__checkbox">
          <input v-model="pdfEnabled" type="checkbox" />
          <span class="sla-consumo__checkbox-box"><i class="ph ph-check" aria-hidden="true"></i></span>
          Generar PDF si LibreOffice está disponible
        </label>

        <div class="sla-consumo__actions">
          <button type="button" class="btn primary" :disabled="loading" @click="generar(pdfEnabled)">
            <i class="ph ph-play" aria-hidden="true"></i>
            Generar informe
          </button>
        </div>
      </div>

      <div class="sla-consumo__column">
        <div v-if="resultado?.totales" class="sla-consumo__card">
          <header>
            <i class="ph ph-chart-bar" aria-hidden="true"></i>
            <h2>Totales del corte</h2>
          </header>
          <div class="sla-consumo__hairline"></div>
          <div class="sla-consumo__stats">
            <div class="sla-consumo__stat">
              <strong>{{ resultado.totales.reclamos ?? 0 }}</strong>
              <span>reclamos</span>
            </div>
            <div class="sla-consumo__stat">
              <strong>{{ resultado.totales.eventos ?? 0 }}</strong>
              <span>eventos (+{{ resultado.totales.reclamos_aislados ?? 0 }} reclamos aislados)</span>
            </div>
            <div class="sla-consumo__stat">
              <strong>{{ resultado.totales.servicios ?? 0 }}</strong>
              <span>servicios</span>
            </div>
            <div class="sla-consumo__stat">
              <strong>{{ resultado.totales.servicios_excedidos ?? 0 }}</strong>
              <span>servicios excedidos</span>
            </div>
            <div class="sla-consumo__stat">
              <strong>{{ formatHoras(resultado.totales.horas_sla) }}</strong>
              <span>horas SLA</span>
            </div>
          </div>
        </div>

        <div v-if="paths.length > 0" class="sla-consumo__card">
          <header>
            <i class="ph ph-check-circle" aria-hidden="true"></i>
            <h2>Salidas generadas</h2>
          </header>
          <div class="sla-consumo__hairline"></div>
          <div class="sla-consumo__outputs">
            <a
              v-for="[kind, href] in paths"
              :key="kind"
              :href="href"
              target="_blank"
              rel="noopener"
              class="sla-consumo__output-link"
            >{{ kind.toUpperCase() }}</a>
          </div>
        </div>

        <div class="sla-consumo__status-box" :class="`is-${tono}`" role="status" aria-live="polite">
          <span class="sla-consumo__status-label">Estado</span>
          <p>{{ mensaje }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useSlaConsumo } from '../../composables/useSlaConsumo';

const pdfEnabled = ref(false);
const isDrag = ref(false);
const fileEl = ref<HTMLInputElement | null>(null);
const { archivos, resultado, loading, mensaje, tono, setArchivos, generar } = useSlaConsumo();

const paths = computed(() => Object.entries(resultado.value?.report_paths ?? {}));

const dropLabel = computed(() => {
  if (archivos.value.length === 0) return 'Adjuntá los dos archivos Excel';
  if (archivos.value.length === 1) return `Falta el segundo archivo (actual: ${archivos.value[0].name})`;
  return `${archivos.value[0].name} + ${archivos.value[1].name}`;
});

function formatHoras(valor: number | undefined): string {
  return typeof valor === 'number' ? valor.toFixed(2) : '—';
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  setArchivos(Array.from(input.files ?? []));
}

function onDrop(e: DragEvent) {
  isDrag.value = false;
  setArchivos(Array.from(e.dataTransfer?.files ?? []));
}
</script>

<style scoped>
.sla-consumo {
  padding-bottom: 26px;
}

.sla-consumo__header {
  padding: 22px 0 0;
}

.sla-consumo__kicker {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.sla-consumo__header h1 {
  font-size: 27px;
  margin: 3px 0 0;
}

.sla-consumo__context {
  max-width: 620px;
  margin: 8px 0 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: color-mix(in srgb, var(--color-text) 52%, transparent);
  text-wrap: pretty;
}

.sla-consumo__body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 22px;
  padding: 20px 0 26px;
}

.sla-consumo__column {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sla-consumo__dropzone {
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

.sla-consumo__dropzone i {
  font-size: 26px;
  color: var(--color-neutral-500);
}

.sla-consumo__dropzone strong {
  font-family: var(--font-heading);
  font-size: 14px;
  font-weight: 500;
}

.sla-consumo__hint {
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.sla-consumo__dropzone:hover,
.sla-consumo__dropzone.drag {
  border-color: var(--color-accent);
}

.sla-consumo__files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.sla-consumo__chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 4px;
  background: var(--color-surface);
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 72%, transparent);
}

.sla-consumo__chip i {
  font-size: 13px;
  color: var(--color-state-ok);
}

.sla-consumo__checkbox {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 13px;
  cursor: pointer;
}

.sla-consumo__checkbox input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
}

.sla-consumo__checkbox-box {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  flex: none;
  border-radius: 4px;
  border: 1px solid var(--color-divider);
}

.sla-consumo__checkbox-box i {
  font-size: 11px;
  color: var(--color-accent);
  opacity: 0;
}

.sla-consumo__checkbox input:checked + .sla-consumo__checkbox-box {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 20%, transparent);
}

.sla-consumo__checkbox input:checked + .sla-consumo__checkbox-box i {
  opacity: 1;
}

.sla-consumo__checkbox input:focus-visible + .sla-consumo__checkbox-box {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}

.sla-consumo__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.sla-consumo__actions .btn {
  min-height: 38px;
}

.sla-consumo__card {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 14px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.sla-consumo__card header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sla-consumo__card header i {
  font-size: 16px;
  color: var(--color-state-ok);
}

.sla-consumo__card h2 {
  margin: 0;
  font-size: 15px;
}

.sla-consumo__hairline {
  height: 1px;
  background: var(--color-divider);
}

.sla-consumo__stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.sla-consumo__stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sla-consumo__stat strong {
  font-family: var(--font-heading);
  font-size: 20px;
  font-weight: 500;
}

.sla-consumo__stat span {
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.sla-consumo__outputs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.sla-consumo__output-link {
  font-size: 11px;
  padding: 3px 9px;
  border: 1px solid var(--color-divider);
  border-radius: 4px;
  color: color-mix(in srgb, var(--color-text) 72%, transparent);
  text-decoration: none;
}

.sla-consumo__output-link:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.sla-consumo__status-box {
  padding: 12px 14px;
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-neutral-800);
}

.sla-consumo__status-label {
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-neutral-500);
}

.sla-consumo__status-box p {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
}

.sla-consumo__status-box.is-success {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-state-ok) 45%, transparent);
}

.sla-consumo__status-box.is-error {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-state-error) 45%, transparent);
}

.sla-consumo__status-box.is-error p {
  color: var(--color-state-error);
}

@media (max-width: 1100px) {
  .sla-consumo__body {
    grid-template-columns: 1fr;
  }
}
</style>
