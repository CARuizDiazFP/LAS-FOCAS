<!--
  Nombre de archivo: InventarioPonCromoView.vue
  Ubicación de archivo: web/frontend/src/views/InventarioPonCromoView.vue
  Descripción: Inventario navegable (búsqueda + paginación) de la red de acceso PON — cajas PON y
  rosetas ingeridas desde Cromo Red
-->
<template>
  <section class="inventario-pon">
    <header class="inventario-pon__header">
      <h1>{{ titulo }}</h1>
      <p class="section-subtitle">{{ subtitulo }}</p>
    </header>

    <hr class="noc-rule" />

    <article class="card inventario-pon__card">
      <form class="inventario-pon__filtros" @submit.prevent="buscar(0)">
        <div class="inventario-pon__campo">
          <label>Nombre</label>
          <input v-model="filtros.q" type="search" placeholder="Buscar por nombre…" />
        </div>
        <div class="inventario-pon__campo">
          <label>Localidad</label>
          <input v-model="filtros.localidad" type="text" placeholder="Capital Federal…" />
        </div>
        <div class="inventario-pon__campo">
          <label>Propietario</label>
          <input v-model="filtros.propietario" type="text" placeholder="Metrotel…" />
        </div>
        <button class="btn primary" type="submit" :disabled="cargando">
          <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
          {{ cargando ? 'Buscando…' : 'Buscar' }}
        </button>
      </form>

      <p v-if="error" class="msg err visible">{{ error }}</p>
    </article>

    <article class="card inventario-pon__card">
      <header class="inventario-pon__resultado-header">
        <span>{{ resultado ? `${resultado.total} ${sustantivo}(s) encontrado(s)` : '—' }}</span>
        <div v-if="resultado && resultado.total > resultado.limit" class="inventario-pon__paginado">
          <button class="btn subtle" type="button" :disabled="cargando || offset === 0" @click="buscar(offset - limit)">
            <i class="ph ph-caret-left" aria-hidden="true"></i>
          </button>
          <span>{{ paginaActual }} / {{ totalPaginas }}</span>
          <button
            class="btn subtle"
            type="button"
            :disabled="cargando || offset + limit >= (resultado?.total ?? 0)"
            @click="buscar(offset + limit)"
          >
            <i class="ph ph-caret-right" aria-hidden="true"></i>
          </button>
        </div>
      </header>

      <p v-if="cargando && !resultado" class="hint">Cargando…</p>
      <p v-else-if="resultado && resultado.elementos.length === 0" class="hint">
        Sin resultados para estos filtros. Si el inventario está vacío, hace falta correr la ingesta
        de {{ sustantivo.toLowerCase() }}s desde Administración → Ingesta → Cromo Red.
      </p>

      <table v-else-if="resultado" class="tabla-pon">
        <thead>
          <tr>
            <th>Nombre</th>
            <th>Dirección</th>
            <th v-if="esCajaPon">Capacidad</th>
            <th v-if="esCajaPon">Conector</th>
            <th>Propietario</th>
            <th v-if="esCajaPon">Splitters</th>
            <th>Vigente</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in resultado.elementos" :key="e.n_id">
            <td>
              {{ e.nombre || '—' }}
              <small class="inventario-pon__n_id">n_id {{ e.n_id }} · clase {{ e.clase }}</small>
            </td>
            <td>
              <div>{{ calleAltura(e) }}</div>
              <small class="inventario-pon__localidad">{{ e.localidad || '—' }}</small>
            </td>
            <td v-if="esCajaPon">
              <span v-if="e.capacidad_puertos" class="inventario-pon__cap">
                {{ e.capacidad_puertos }} puertos
              </span>
              <span v-else>—</span>
            </td>
            <td v-if="esCajaPon">{{ e.tipo_conector || '—' }}</td>
            <td>{{ e.propietario || '—' }}</td>
            <td v-if="esCajaPon">{{ e.cantidad_splitters }}</td>
            <td>
              <span class="inventario-pon__vigente" :class="{ 'is-no': !e.vigente }">
                {{ e.vigente ? 'Sí' : 'No' }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { ApiError } from '../api/client';
import {
  CROMO_CLASES_CAJA_PON,
  CROMO_CLASE_ROSETA,
  buscarInventarioPon,
  type CromoInventarioPonResultado,
  type CromoPonElementoInventario,
} from '../api/cromo';

// Una sola vista para las dos rutas: cajas PON y rosetas comparten tabla, endpoint y columnas
// salvo las tres que sólo tiene una caja (capacidad, conector, splitters). Duplicar el archivo
// para ocultar tres columnas sería duplicar también cada arreglo futuro.
const route = useRoute();
const esCajaPon = computed(() => route.meta?.ponVariante !== 'roseta');

const titulo = computed(() => (esCajaPon.value ? 'Inventario de Cajas PON' : 'Inventario de Rosetas'));
const sustantivo = computed(() => (esCajaPon.value ? 'Caja PON' : 'Roseta'));
const subtitulo = computed(() =>
  esCajaPon.value
    ? 'Cajas PON de la red de acceso ingeridas desde Cromo Red, con su capacidad y cuántos splitters contienen.'
    : 'Rosetas de la red de acceso ingeridas desde Cromo Red. No aparecen en los recorridos de camino óptico: el trazado termina en la caja PON.',
);
const clases = computed<readonly number[]>(() =>
  esCajaPon.value ? CROMO_CLASES_CAJA_PON : [CROMO_CLASE_ROSETA],
);

const filtros = reactive({ q: '', localidad: '', propietario: '' });

const limit = 50;
const offset = ref(0);
const cargando = ref(false);
const error = ref('');
const resultado = ref<CromoInventarioPonResultado | null>(null);

const paginaActual = computed(() => Math.floor(offset.value / limit) + 1);
const totalPaginas = computed(() => Math.max(1, Math.ceil((resultado.value?.total ?? 0) / limit)));

async function buscar(nuevoOffset: number): Promise<void> {
  offset.value = Math.max(0, nuevoOffset);
  cargando.value = true;
  error.value = '';
  try {
    resultado.value = await buscarInventarioPon({
      q: filtros.q.trim() || undefined,
      localidad: filtros.localidad.trim() || undefined,
      propietario: filtros.propietario.trim() || undefined,
      clases: clases.value,
      limit,
      offset: offset.value,
    });
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Error buscando el inventario de la red PON.';
  } finally {
    cargando.value = false;
  }
}

function calleAltura(e: CromoPonElementoInventario): string {
  const partes = [e.calle, e.altura].filter((v): v is string => Boolean(v));
  return partes.length > 0 ? partes.join(' ') : '—';
}

// Al navegar entre /infra/cromo/pon y /infra/cromo/rosetas el componente se reusa: sin este watch
// la vista cambiaría de título pero seguiría mostrando los resultados de la otra clase.
watch(
  () => route.path,
  () => {
    resultado.value = null;
    void buscar(0);
  },
);

onMounted(() => buscar(0));
</script>

<style scoped>
.inventario-pon {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px 26px 30px;
}

.inventario-pon__header h1 {
  margin: 4px 0 6px;
}

.inventario-pon .hint {
  font-size: 0.8rem;
  color: var(--muted);
}

.inventario-pon__card {
  padding: 18px 20px;
}

.inventario-pon__filtros {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
}

.inventario-pon__campo {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 200px;
  flex: 1 1 200px;
}

.inventario-pon__campo label {
  font-size: 0.78rem;
  color: var(--muted);
}

.inventario-pon__resultado-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  font-size: 0.85rem;
  color: var(--muted);
}

.inventario-pon__paginado {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tabla-pon {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.tabla-pon th,
.tabla-pon td {
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid var(--color-divider);
  vertical-align: top;
}

.tabla-pon th {
  color: var(--muted);
  font-weight: 600;
  font-size: 0.78rem;
}

.inventario-pon__n_id,
.inventario-pon__localidad {
  display: block;
  color: var(--muted);
  font-size: 0.72rem;
}

.inventario-pon__cap {
  border: 1px solid color-mix(in srgb, var(--color-accent) 40%, transparent);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  border-radius: var(--radius-pill);
  padding: 2px 8px;
  white-space: nowrap;
}

.inventario-pon__vigente {
  color: var(--success);
}

.inventario-pon__vigente.is-no {
  color: var(--warning);
}
</style>
