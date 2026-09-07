<!--
  Nombre de archivo: InventarioOdfsCromoView.vue
  Ubicación de archivo: web/frontend/src/views/InventarioOdfsCromoView.vue
  Descripción: Inventario navegable (búsqueda + paginación) de ODFs ya ingeridos desde Cromo Red
-->
<template>
  <section class="inventario-odfs">
    <header class="inventario-odfs__header">
      <h1>Inventario de ODFs Cromo</h1>
      <p class="section-subtitle">Buscá y paginá los ODFs ya ingeridos desde Cromo Red.</p>
    </header>

    <hr class="noc-rule" />

    <article class="card inventario-odfs__card">
      <form class="inventario-odfs__filtros" @submit.prevent="buscar(0)">
        <div class="inventario-odfs__campo">
          <label>Nodo</label>
          <input v-model="filtros.q" type="search" placeholder="Buscar por nombre…" />
        </div>
        <div class="inventario-odfs__campo">
          <label>Cliente / Servicio asociado</label>
          <input v-model="filtros.servicio" type="text" placeholder="N° de servicio o ID externo…" />
        </div>
        <button class="btn primary" type="submit" :disabled="cargando">
          <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
          {{ cargando ? 'Buscando…' : 'Buscar' }}
        </button>
      </form>

      <p v-if="error" class="msg err visible">{{ error }}</p>
    </article>

    <article class="card inventario-odfs__card">
      <header class="inventario-odfs__resultado-header">
        <span>{{ resultado ? `${resultado.total} ODF(s) encontrado(s)` : '—' }}</span>
        <div class="inventario-odfs__paginado" v-if="resultado && resultado.total > resultado.limit">
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
      <p v-else-if="resultado && resultado.odfs.length === 0" class="hint">
        Sin resultados para estos filtros.
      </p>

      <table v-else-if="resultado" class="tabla-odfs">
        <thead>
          <tr>
            <th>Nombre</th>
            <th>Dirección</th>
            <th>Tipo</th>
            <th>Propietario</th>
            <th>Cables asociados</th>
            <th>Vigente</th>
            <th>Servicios</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="o in resultado.odfs"
            :key="o.n_id"
            class="tabla-odfs__fila"
            tabindex="0"
            role="button"
            :aria-label="`Ver detalle del ODF ${o.nombre || o.n_id}`"
            @click="abrirDetalle(o.n_id)"
            @keydown.enter="abrirDetalle(o.n_id)"
          >
            <td>
              {{ o.nombre || '—' }}
              <small class="inventario-odfs__n_id">n_id {{ o.n_id }}</small>
            </td>
            <td>
              <div>{{ calleAltura(o) }}</div>
              <small class="inventario-odfs__localidad">{{ o.localidad || '—' }}</small>
            </td>
            <td>
              <span :class="['tipo-elemento-chip', `tipo-elemento-chip--${tipoElementoClase(o.tipo_elemento)}`]">
                {{ tipoElementoLabel(o.tipo_elemento) }}
              </span>
            </td>
            <td>{{ o.propietario || '—' }}</td>
            <td>{{ o.cantidad_cables_asociados }}</td>
            <td>
              <span class="inventario-odfs__vigente" :class="{ 'is-no': !o.vigente }">
                {{ o.vigente ? 'Sí' : 'No' }}
              </span>
            </td>
            <td>{{ o.cantidad_servicios }}</td>
          </tr>
        </tbody>
      </table>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';

import { ApiError } from '../api/client';
import { buscarInventarioOdfs, type CromoInventarioOdfsResultado, type CromoOdfInventario } from '../api/cromo';

const router = useRouter();

const filtros = reactive({
  q: '',
  servicio: '',
});

const limit = 50;
const offset = ref(0);
const cargando = ref(false);
const error = ref('');
const resultado = ref<CromoInventarioOdfsResultado | null>(null);

const paginaActual = computed(() => Math.floor(offset.value / limit) + 1);
const totalPaginas = computed(() => Math.max(1, Math.ceil((resultado.value?.total ?? 0) / limit)));

async function buscar(nuevoOffset: number): Promise<void> {
  offset.value = Math.max(0, nuevoOffset);
  cargando.value = true;
  error.value = '';
  try {
    resultado.value = await buscarInventarioOdfs({
      q: filtros.q.trim() || undefined,
      servicio: filtros.servicio.trim() || undefined,
      limit,
      offset: offset.value,
    });
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Error buscando el inventario de ODFs.';
  } finally {
    cargando.value = false;
  }
}

function calleAltura(o: CromoOdfInventario): string {
  const partes = [o.calle, o.altura].filter((v): v is string => Boolean(v));
  return partes.length > 0 ? partes.join(' ') : '—';
}

/** "ODF" → verde, "EMPALME" → ámbar, "SIN_CLASIFICAR" (u otro valor) → gris — mismo patrón de badge
 * de estado ya usado en `CableDetalleCromoView.vue` (`color-mix()` sobre tokens.css), sin crear una
 * utilidad de mapeo de colores compartida nueva. */
function tipoElementoClase(tipo: string): 'ok' | 'warn' | 'idle' {
  if (tipo === 'ODF') return 'ok';
  if (tipo === 'EMPALME') return 'warn';
  return 'idle';
}

function tipoElementoLabel(tipo: string): string {
  if (tipo === 'ODF') return 'ODF';
  if (tipo === 'EMPALME') return 'Empalme';
  return 'Sin clasificar';
}

function abrirDetalle(nId: number): void {
  void router.push(`/infra/cromo/odfs/ID${nId}`);
}

onMounted(() => buscar(0));
</script>

<style scoped>
.inventario-odfs {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px 26px 30px;
}

.inventario-odfs__header h1 {
  margin: 4px 0 6px;
}

.inventario-odfs .hint {
  font-size: 0.8rem;
  color: var(--muted);
}

.inventario-odfs__card {
  padding: 18px 20px;
}

.inventario-odfs__filtros {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 14px;
}

.inventario-odfs__campo {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 220px;
}

.inventario-odfs__campo label {
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.inventario-odfs__resultado-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  font-size: 13px;
  color: color-mix(in srgb, var(--color-text) 65%, transparent);
}

.inventario-odfs__paginado {
  display: flex;
  align-items: center;
  gap: 10px;
}

.inventario-odfs__n_id {
  display: block;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
  font-size: 11px;
}

.inventario-odfs__localidad {
  display: block;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
  font-size: 11px;
}

.inventario-odfs__vigente {
  color: var(--color-state-ok);
}

.inventario-odfs__vigente.is-no {
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.tabla-odfs {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.tabla-odfs th,
.tabla-odfs td {
  text-align: left;
  padding: 7px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--color-text) 10%, transparent);
}

.tabla-odfs th {
  font-weight: 500;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  font-size: 12px;
}

.tabla-odfs__fila {
  cursor: pointer;
}

.tabla-odfs__fila:hover {
  background: color-mix(in srgb, var(--color-text) 5%, transparent);
}

.tabla-odfs__fila:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: -2px;
}

.tipo-elemento-chip {
  display: inline-flex;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 9px;
  border-radius: var(--radius-md);
  white-space: nowrap;
}

.tipo-elemento-chip--ok {
  background: color-mix(in srgb, var(--color-state-ok) 16%, transparent);
  color: var(--color-state-ok);
}

.tipo-elemento-chip--warn {
  background: color-mix(in srgb, var(--color-state-warn) 16%, transparent);
  color: var(--color-state-warn);
}

.tipo-elemento-chip--idle {
  background: color-mix(in srgb, var(--color-state-idle) 16%, transparent);
  color: var(--muted);
}
</style>
