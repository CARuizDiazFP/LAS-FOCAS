<!--
  Nombre de archivo: ModalConsolidarBotellas.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalConsolidarBotellas.vue
  Descripción: Consolidación manual de un grupo LIBRE de Botellas Cromo duplicadas (+ opcionalmente legado) hacia un único destino
-->
<template>
  <dialog ref="dialogEl" class="consolidar-modal" @click.self="handleClose">
    <div class="modal-content">
      <div class="consolidar-title-row">
        <strong>Consolidar Botellas duplicadas</strong>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </div>

      <p class="consolidar-hint">
        Cromo siempre gana: los orígenes quedan marcados como fusionados hacia el destino elegido, y
        cualquier Botella legado incluida hereda sus datos reales (Cables, Empalmes, Ingresos, alias)
        al destino. Esta acción no se puede deshacer.
      </p>

      <section class="consolidar-section">
        <h3>Destino (se conserva)</h3>
        <template v-if="candidatosCromo.length > 0">
          <label v-for="c in candidatosCromo" :key="c.id" class="consolidar-candidato">
            <input
              type="radio"
              name="destino"
              :value="c.id"
              v-model="destinoListaId"
              @change="onDestinoListaChange"
            />
            <span class="consolidar-candidato-nombre">{{ c.nombre || `Botella ${c.id}` }} <code>{{ c.id }}</code></span>
            <span v-if="c.tiene_cables" class="consolidar-badge-operativa">
              <i class="ph ph-check-circle" aria-hidden="true"></i> Operativa
            </span>
          </label>
          <label class="consolidar-candidato">
            <input type="radio" name="destino" value="manual" v-model="destinoModo" />
            <span>ID Cromo manual</span>
          </label>
          <div v-if="destinoModo === 'manual'" class="consolidar-add-row">
            <input
              v-model="destinoManualTexto"
              type="text"
              inputmode="numeric"
              placeholder="n_id Cromo destino"
              class="consolidar-input"
              @input="operatividadManual = null"
            />
            <button class="btn subtle" type="button" @click="verificarOperatividadManual">Verificar</button>
          </div>
        </template>
        <div v-else class="consolidar-add-row">
          <input
            v-model="destinoManualTexto"
            type="text"
            inputmode="numeric"
            placeholder="n_id Cromo destino"
            class="consolidar-input"
            @input="operatividadManual = null"
          />
          <button class="btn subtle" type="button" @click="verificarOperatividadManual">Verificar</button>
        </div>
        <span v-if="operatividadManual === true" class="consolidar-badge-operativa">
          <i class="ph ph-check-circle" aria-hidden="true"></i> Operativa (tiene cables)
        </span>
        <span v-else-if="operatividadManual === false" class="consolidar-badge-no-operativa">
          Sin cables asociados
        </span>
      </section>

      <section class="consolidar-section">
        <h3>Nombre del destino</h3>
        <input
          v-model="nombreDestino"
          type="text"
          placeholder="Nombre (dejar en blanco para no cambiarlo)"
          class="consolidar-input"
        />
      </section>

      <section v-if="candidatosLegado.length > 0" class="consolidar-section">
        <h3>Botellas legado a heredar</h3>
        <label v-for="l in candidatosLegado" :key="l.id" class="consolidar-candidato">
          <input type="checkbox" :value="l.id" v-model="idsLegadoSeleccionados" />
          <span>{{ l.nombre || `Botella ${l.id}` }} (legado, ID {{ l.id }})</span>
        </label>
      </section>

      <section class="consolidar-section">
        <h3>Orígenes Cromo adicionales</h3>
        <p class="hint">
          Las demás Botellas Cromo de este grupo se consolidan automáticamente. Agregá acá n_ids que
          el detector no haya agrupado (ej. botellas sin nombre).
        </p>
        <div class="consolidar-add-row">
          <input
            v-model="nuevoOrigenTexto"
            type="text"
            inputmode="numeric"
            placeholder="n_id Cromo"
            @keydown.enter.prevent="agregarOrigenExtra"
          />
          <button class="btn subtle" type="button" @click="agregarOrigenExtra">Agregar</button>
        </div>
        <ul v-if="origenesExtra.length > 0" class="consolidar-chips">
          <li v-for="id in origenesExtra" :key="id">
            {{ id }}
            <button type="button" @click="quitarOrigenExtra(id)">×</button>
          </li>
        </ul>
      </section>

      <div v-if="error" class="consolidar-empty error">{{ error }}</div>
      <div v-if="resultado" class="consolidar-resultado">
        Consolidado: {{ origenesConsolidadosCount }} Botella(s) Cromo retirada(s) de duplicados,
        {{ resultado.alias_creados }} alias nuevo(s), {{ resultado.alias_actualizados }}
        actualizado(s)<span v-if="resultado.legados_migrados.length">
          · {{ resultado.legados_migrados.length }} Botella(s) legado migrada(s)</span
        ><span v-if="resultado.nombre_nuevo"> · nombre actualizado</span>.
      </div>

      <div class="consolidar-actions">
        <button
          class="btn primary"
          type="button"
          :disabled="consolidando || !puedeConsolidar"
          @click="handleConsolidar"
        >
          {{ consolidando ? 'Consolidando...' : 'Consolidar' }}
        </button>
        <button class="btn subtle" type="button" :disabled="consolidando" @click="handleClose">
          {{ resultado ? 'Cerrar' : 'Cancelar' }}
        </button>
      </div>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import {
  consolidarBotellasCromo,
  getBotellasOperatividad,
  type BotellaDuplicadaItem,
  type ConsolidarBotellasResponse,
  type GrupoBotellasDuplicadas,
} from '../../api/botellas';

const props = defineProps<{
  open: boolean;
  grupo: GrupoBotellasDuplicadas | null;
}>();

const emit = defineEmits<{
  close: [];
  consolidado: [];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const consolidando = ref(false);
const error = ref('');
const resultado = ref<ConsolidarBotellasResponse | null>(null);
const origenesConsolidadosCount = ref(0);

const destinoModo = ref<'lista' | 'manual'>('manual');
const destinoListaId = ref<number | null>(null);
const destinoManualTexto = ref('');
const nombreDestino = ref('');
const idsLegadoSeleccionados = ref<number[]>([]);
const origenesExtra = ref<number[]>([]);
const nuevoOrigenTexto = ref('');
const operatividadManual = ref<boolean | null>(null);

const candidatosCromo = computed<BotellaDuplicadaItem[]>(
  () => props.grupo?.miembros.filter((m) => m.origen === 'cromo') ?? [],
);
const candidatosLegado = computed<BotellaDuplicadaItem[]>(
  () => props.grupo?.miembros.filter((m) => m.origen === 'legado') ?? [],
);

const destinoId = computed<number | null>(() => {
  if (candidatosCromo.value.length > 0 && destinoModo.value === 'lista') {
    return destinoListaId.value;
  }
  const n = Number(destinoManualTexto.value.trim());
  return Number.isInteger(n) && n > 0 ? n : null;
});

const origenesFinal = computed<number[]>(() => {
  const deGrupo = candidatosCromo.value.map((c) => c.id).filter((id) => id !== destinoId.value);
  return Array.from(new Set([...deGrupo, ...origenesExtra.value]));
});

const puedeConsolidar = computed(
  () =>
    destinoId.value != null &&
    (origenesFinal.value.length > 0 || idsLegadoSeleccionados.value.length > 0 || nombreDestino.value.trim().length > 0),
);

function onDestinoListaChange(): void {
  const elegido = candidatosCromo.value.find((c) => c.id === destinoListaId.value);
  nombreDestino.value = elegido?.nombre || '';
}

function agregarOrigenExtra(): void {
  const n = Number(nuevoOrigenTexto.value.trim());
  if (!Number.isInteger(n) || n <= 0) return;
  if (!origenesExtra.value.includes(n)) origenesExtra.value.push(n);
  nuevoOrigenTexto.value = '';
}

function quitarOrigenExtra(id: number): void {
  origenesExtra.value = origenesExtra.value.filter((x) => x !== id);
}

async function verificarOperatividadManual(): Promise<void> {
  const n = Number(destinoManualTexto.value.trim());
  if (!Number.isInteger(n) || n <= 0) return;
  try {
    const operativos = await getBotellasOperatividad([n]);
    operatividadManual.value = operativos.includes(n);
  } catch {
    operatividadManual.value = null;
  }
}

function resetState(): void {
  error.value = '';
  resultado.value = null;
  origenesExtra.value = [];
  nuevoOrigenTexto.value = '';
  operatividadManual.value = null;

  const operativos = candidatosCromo.value.filter((c) => c.tiene_cables === true);
  if (candidatosCromo.value.length > 0) {
    destinoModo.value = 'lista';
    destinoListaId.value = operativos.length === 1 ? operativos[0].id : null;
    nombreDestino.value = operativos.length === 1 ? operativos[0].nombre || '' : '';
  } else {
    destinoModo.value = 'manual';
    destinoListaId.value = null;
    nombreDestino.value = '';
  }
  destinoManualTexto.value = '';
  idsLegadoSeleccionados.value = candidatosLegado.value.map((l) => l.id);
}

function handleClose(): void {
  dialogEl.value?.close();
  emit('close');
}

async function handleConsolidar(): Promise<void> {
  if (destinoId.value == null) return;
  consolidando.value = true;
  error.value = '';
  try {
    const origenes = origenesFinal.value;
    const data = await consolidarBotellasCromo({
      idsOrigenCromo: origenes,
      idDestinoCromo: destinoId.value,
      idsLegado: idsLegadoSeleccionados.value,
      nombreDestino: nombreDestino.value.trim() || null,
    });
    origenesConsolidadosCount.value = origenes.length;
    resultado.value = data;
    emit('consolidado');
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'No se pudo consolidar el grupo.';
  } finally {
    consolidando.value = false;
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      resetState();
      dialogEl.value?.showModal();
      return;
    }
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
);
</script>

<style scoped>
.consolidar-modal {
  width: min(620px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.consolidar-modal::backdrop {
  background: rgba(4, 8, 14, 0.78);
  backdrop-filter: blur(10px);
}

.modal-content {
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--color-text);
  box-shadow: var(--shadow-lg);
  max-height: calc(100vh - 64px);
  overflow-y: auto;
}

.consolidar-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.consolidar-title-row strong {
  font-size: 1.1rem;
}

.close-btn {
  margin-left: auto;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 1.4rem;
  line-height: 1;
}

.close-btn:hover {
  color: var(--color-text);
}

.consolidar-hint {
  font-size: 0.82rem;
  color: var(--muted);
  line-height: 1.5;
  margin: 0 0 16px;
}

.consolidar-section {
  margin-bottom: 16px;
}

.consolidar-section h3 {
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 8px;
}

.consolidar-section .hint {
  font-size: 0.78rem;
  color: var(--muted);
  margin: 0 0 8px;
}

.consolidar-candidato {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 4px;
  font-size: 0.85rem;
  cursor: pointer;
}

.consolidar-candidato-nombre {
  flex: 1;
  min-width: 0;
}

.consolidar-badge-operativa {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.68rem;
  background: color-mix(in srgb, var(--success) 16%, transparent);
  color: var(--success);
}

.consolidar-badge-no-operativa {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.68rem;
  background: var(--color-bg);
  color: var(--muted);
  margin-top: 6px;
}

.consolidar-input {
  width: 100%;
  margin-top: 6px;
}

.consolidar-add-row {
  display: flex;
  gap: 8px;
}

.consolidar-add-row input {
  flex: 1;
}

.consolidar-chips {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 10px 0 0;
  padding: 0;
}

.consolidar-chips li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  font-size: 0.78rem;
}

.consolidar-chips button {
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 0.9rem;
  line-height: 1;
}

.consolidar-empty {
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px dashed var(--color-divider);
  color: var(--muted);
  font-size: 0.85rem;
  margin-bottom: 12px;
}

.consolidar-empty.error {
  border-color: color-mix(in srgb, var(--error) 40%, transparent);
  color: var(--error);
}

.consolidar-resultado {
  padding: 12px 14px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--success) 12%, transparent);
  color: var(--success);
  font-size: 0.85rem;
  margin-bottom: 12px;
}

.consolidar-actions {
  display: flex;
  gap: 10px;
}
</style>
