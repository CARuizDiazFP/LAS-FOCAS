<!--
  Nombre de archivo: EmpalmesBotellaCromoView.vue
  Ubicación de archivo: web/frontend/src/views/EmpalmesBotellaCromoView.vue
  Descripción: Tabla dinámica de empalmes (fusiones) internos de una Botella Cromo, filtrable por Cable Origen, con Splitters agrupados
-->
<template>
  <section class="empalmes-botella-page">
    <div class="empalmes-botella-shell">
      <RouterLink
        class="empalmes-botella-back"
        :to="{ path: '/infra/cromo/verificador', query: { tipo: 'botella', n_id: String(botellaNId) } }"
      >
        ← Volver a la Botella
      </RouterLink>

      <div v-if="cargando" class="empalmes-botella-state">Cargando empalmes...</div>
      <div v-else-if="error" class="empalmes-botella-state error">
        <strong>No se pudieron cargar los empalmes.</strong>
        <span>{{ error }}</span>
        <button class="btn subtle" type="button" @click="void cargar()">Reintentar</button>
      </div>

      <template v-else-if="resultado">
        <header class="empalmes-botella-hero">
          <p class="empalmes-botella-hero__eyebrow">Verificador Cromo · Empalmes</p>
          <h1>{{ resultado.nombre || `Botella ${resultado.botella_n_id}` }}</h1>
          <span class="empalmes-botella-id">n_id {{ resultado.botella_n_id }}</span>
        </header>

        <p v-if="resultado.empalmes.length === 0" class="hint">
          No se encontró ningún empalme para esta botella en el inventario ingerido — puede que
          todavía no haya sido barrido (`app.cromo_fusiones` sólo trae clase 132 por barrido
          directo, sin `parent`, ver `core/services/cromo/empalmes.py`).
        </p>

        <template v-else>
          <div class="empalmes-botella-filtro">
            <label for="empalmes-botella-cable">Cable Origen</label>
            <select id="empalmes-botella-cable" v-model="cableSeleccionadoId">
              <option v-for="c in resultado.cables" :key="c.n_id" :value="c.n_id">
                {{ c.nombre || `Cable ${c.n_id}` }} ({{ c.cantidad_empalmes }})
              </option>
            </select>
            <span class="empalmes-botella-chip">{{ empalmesFiltrados.length }} fila(s)</span>
          </div>

          <p v-if="resultado.cables.length === 0" class="hint">
            Ningún cable de esta botella aparece como origen de un empalme resuelto — se muestran
            todos los empalmes encontrados sin filtro.
          </p>

          <table class="tabla-empalmes">
            <thead>
              <tr>
                <th>Fusión</th>
                <th>Tipo</th>
                <th>Buffer origen</th>
                <th>Pelo origen</th>
                <th>Cable destino</th>
                <th>Buffer destino</th>
                <th>Pelo destino</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="e in empalmesFiltrados" :key="e.fusion_n_id">
                <td>{{ e.fusion_n_id }}</td>
                <td>
                  <span v-if="e.es_splitter" class="empalmes-botella-chip empalmes-botella-chip--splitter">
                    {{ etiquetaSplitter(e) }}
                  </span>
                  <span v-else class="empalmes-botella-chip empalmes-botella-chip--fusion">Fusión</span>
                </td>
                <td>{{ e.pelo_origen?.tubo_color || '—' }}</td>
                <td>{{ etiquetaPelo(e.pelo_origen) }}</td>
                <template v-if="e.es_splitter">
                  <td colspan="3">
                    <span v-if="e.splitter_destinos.length === 0" class="hint">
                      Sin patas resueltas (referencia colgada del componente Splitter en Cromo).
                    </span>
                    <span v-else class="empalmes-botella-splitter-destinos">
                      <span v-for="d in e.splitter_destinos" :key="d.n_id" class="empalmes-botella-splitter-pata">
                        {{ etiquetaPelo(d) }} · {{ d.cable_nombre || d.cable_n_id }}
                      </span>
                    </span>
                  </td>
                </template>
                <template v-else>
                  <td>{{ e.pelo_destino?.cable_nombre || '—' }}</td>
                  <td>{{ e.pelo_destino?.tubo_color || '—' }}</td>
                  <td>{{ etiquetaPelo(e.pelo_destino) }}</td>
                </template>
              </tr>
            </tbody>
          </table>
        </template>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { ApiError } from '../api/client';
import {
  obtenerEmpalmesDeBotella,
  type CromoEmpalmeDeBotella,
  type CromoEmpalmesBotella,
  type CromoPeloEmpalme,
} from '../api/cromo';

const route = useRoute();

const cargando = ref(true);
const error = ref('');
const resultado = ref<CromoEmpalmesBotella | null>(null);
const cableSeleccionadoId = ref<number | null>(null);

const botellaNId = computed(() => {
  const raw = String(route.query.n_id ?? '');
  const value = Number(raw);
  return Number.isInteger(value) && value > 0 ? value : null;
});

// Filtra por el Cable Origen seleccionado — si ningún cable de la botella quedó identificado como
// origen de un empalme resuelto, se muestran todos sin filtrar (mejor que una tabla vacía).
const empalmesFiltrados = computed<CromoEmpalmeDeBotella[]>(() => {
  const todos = resultado.value?.empalmes ?? [];
  if (cableSeleccionadoId.value == null) return todos;
  return todos.filter((e) => e.pelo_origen?.cable_n_id === cableSeleccionadoId.value);
});

function etiquetaPelo(pelo: CromoPeloEmpalme | null): string {
  if (!pelo) return '—';
  const partes = [pelo.numero_pelo ?? `#${pelo.n_id}`];
  if (pelo.orden != null) partes.push(`orden ${pelo.orden}`);
  if (pelo.color) partes.push(pelo.color);
  return partes.join(' · ');
}

function etiquetaSplitter(empalme: CromoEmpalmeDeBotella): string {
  return empalme.splitter_ratio != null ? `Splitter 1-${empalme.splitter_ratio}` : 'Splitter';
}

async function cargar(): Promise<void> {
  const nId = botellaNId.value;
  if (nId == null) {
    error.value = 'Falta el parámetro n_id de la Botella en la URL.';
    cargando.value = false;
    return;
  }

  cargando.value = true;
  error.value = '';
  resultado.value = null;
  cableSeleccionadoId.value = null;

  try {
    const r = await obtenerEmpalmesDeBotella(nId);
    resultado.value = r;
    // Selecciona por defecto el primer cable "OK" — es decir, el primero que efectivamente
    // aparece como origen de al menos un empalme resuelto (ver `_cables_origen` en empalmes.py).
    cableSeleccionadoId.value = r.cables[0]?.n_id ?? null;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      error.value = `No existe una botella con n_id=${nId} en el inventario ingerido.`;
    } else {
      error.value = e instanceof Error ? e.message : 'Error consultando los empalmes.';
    }
  } finally {
    cargando.value = false;
  }
}

watch(() => route.query.n_id, () => void cargar());

onMounted(() => void cargar());
</script>

<style scoped>
.empalmes-botella-page {
  min-height: 100%;
}

.empalmes-botella-shell {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 20px 40px;
}

.empalmes-botella-back {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-accent);
  text-decoration: none;
  margin-bottom: 18px;
}

.empalmes-botella-back:hover {
  color: var(--color-accent-300);
}

.empalmes-botella-state {
  padding: 24px;
  border-radius: 16px;
  border: 1px solid var(--color-divider);
  background: var(--color-surface);
  color: var(--muted);
}

.empalmes-botella-state.error {
  display: flex;
  flex-direction: column;
  gap: 10px;
  color: var(--error);
  border-color: color-mix(in srgb, var(--error) 30%, transparent);
}

.empalmes-botella-hero {
  margin-bottom: 18px;
}

.empalmes-botella-hero__eyebrow {
  margin: 0;
  color: var(--color-accent);
  font-size: 0.76rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.empalmes-botella-hero h1 {
  margin: 6px 0 6px;
  font-size: 1.6rem;
  color: var(--color-text);
}

.empalmes-botella-id {
  font-size: 0.8rem;
  color: var(--muted);
}

.empalmes-botella-filtro {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.empalmes-botella-filtro label {
  font-size: 0.8rem;
  color: var(--muted);
}

.empalmes-botella-filtro select {
  min-width: 260px;
}

.empalmes-botella-chip {
  display: inline-flex;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 9px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-text) 10%, transparent);
  color: var(--muted);
}

.empalmes-botella-chip--splitter {
  background: color-mix(in srgb, var(--color-accent) 16%, transparent);
  color: var(--color-accent);
}

.empalmes-botella-chip--fusion {
  background: color-mix(in srgb, var(--color-text) 8%, transparent);
}

.empalmes-botella-splitter-destinos {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.empalmes-botella-splitter-pata {
  font-size: 12.5px;
  color: var(--color-text);
}

.tabla-empalmes {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.tabla-empalmes th,
.tabla-empalmes td {
  text-align: left;
  padding: 7px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--color-text) 10%, transparent);
  vertical-align: top;
}

.tabla-empalmes th {
  font-weight: 500;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  font-size: 12px;
}

.hint {
  font-size: 0.8rem;
  color: var(--muted);
}
</style>
