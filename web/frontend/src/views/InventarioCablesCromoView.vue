<!--
  Nombre de archivo: InventarioCablesCromoView.vue
  Ubicación de archivo: web/frontend/src/views/InventarioCablesCromoView.vue
  Descripción: Inventario navegable (búsqueda + paginación) de cables ya ingeridos desde Cromo Red
-->
<template>
  <section class="inventario-cables">
    <header class="inventario-cables__header">
      <h1>Inventario de Cables Cromo</h1>
      <p class="section-subtitle">
        Buscá y paginá los cables ya ingeridos desde Cromo Red. Para ver qué servicios pasan por un
        cable puntual (por `n_id`), usá el <RouterLink to="/infra/cromo/verificador">Verificador</RouterLink>.
      </p>
    </header>

    <hr class="noc-rule" />

    <article class="card inventario-cables__card">
      <form class="inventario-cables__filtros" @submit.prevent="buscar(0)">
        <div class="inventario-cables__campo">
          <label>Nombre</label>
          <input v-model="filtros.q" type="search" placeholder="Buscar por nombre…" />
        </div>
        <div class="inventario-cables__campo">
          <label>Jerarquía</label>
          <input v-model="filtros.jerarquia" type="text" placeholder="Acceso, Troncal…" />
        </div>
        <div class="inventario-cables__campo">
          <label>Propietario</label>
          <input v-model="filtros.propietario" type="text" placeholder="SBASE…" />
        </div>
        <div class="inventario-cables__campo">
          <label>Vigente</label>
          <select v-model="filtros.vigente">
            <option value="">Todos</option>
            <option value="true">Sólo vigentes</option>
            <option value="false">Sólo no vigentes</option>
          </select>
        </div>
        <button class="btn primary" type="submit" :disabled="cargando">
          <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
          {{ cargando ? 'Buscando…' : 'Buscar' }}
        </button>
      </form>

      <p v-if="error" class="msg err visible">{{ error }}</p>
    </article>

    <article class="card inventario-cables__card">
      <header class="inventario-cables__resultado-header">
        <span>{{ resultado ? `${resultado.total} cable(s) encontrado(s)` : '—' }}</span>
        <div class="inventario-cables__paginado" v-if="resultado && resultado.total > resultado.limit">
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
      <p v-else-if="resultado && resultado.cables.length === 0" class="hint">
        Sin resultados para estos filtros.
      </p>

      <table v-else-if="resultado" class="tabla-cables">
        <thead>
          <tr>
            <th>Nombre</th>
            <th>Capacidad</th>
            <th>Jerarquía</th>
            <th>Propietario</th>
            <th>Extremo A</th>
            <th>Extremo B</th>
            <th>Vigente</th>
            <th>Servicios</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in resultado.cables" :key="c.n_id">
            <td>
              {{ c.nombre || '—' }}
              <small class="inventario-cables__n_id">n_id {{ c.n_id }}</small>
            </td>
            <td>{{ c.capacidad || '—' }}<template v-if="c.capacidad_pelos"> ({{ c.capacidad_pelos }})</template></td>
            <td>{{ c.jerarquia || '—' }}</td>
            <td>{{ c.propietario || '—' }}</td>
            <td>{{ c.extremo_a_nombre || '—' }}</td>
            <td>{{ c.extremo_b_nombre || '—' }}</td>
            <td>
              <span class="inventario-cables__vigente" :class="{ 'is-no': !c.vigente }">
                {{ c.vigente ? 'Sí' : 'No' }}
              </span>
            </td>
            <td>{{ c.cantidad_servicios }}</td>
          </tr>
        </tbody>
      </table>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { RouterLink } from 'vue-router';

import { ApiError } from '../api/client';
import { buscarInventarioCables, type CromoInventarioCablesResultado } from '../api/cromo';

const filtros = reactive({
  q: '',
  jerarquia: '',
  propietario: '',
  vigente: '' as '' | 'true' | 'false',
});

const limit = 50;
const offset = ref(0);
const cargando = ref(false);
const error = ref('');
const resultado = ref<CromoInventarioCablesResultado | null>(null);

const paginaActual = computed(() => Math.floor(offset.value / limit) + 1);
const totalPaginas = computed(() => Math.max(1, Math.ceil((resultado.value?.total ?? 0) / limit)));

async function buscar(nuevoOffset: number): Promise<void> {
  offset.value = Math.max(0, nuevoOffset);
  cargando.value = true;
  error.value = '';
  try {
    resultado.value = await buscarInventarioCables({
      q: filtros.q.trim() || undefined,
      jerarquia: filtros.jerarquia.trim() || undefined,
      propietario: filtros.propietario.trim() || undefined,
      vigente: filtros.vigente === '' ? undefined : filtros.vigente === 'true',
      limit,
      offset: offset.value,
    });
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Error buscando el inventario de cables.';
  } finally {
    cargando.value = false;
  }
}

onMounted(() => buscar(0));
</script>

<style scoped>
.inventario-cables {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px 26px 30px;
}

.inventario-cables__header h1 {
  margin: 4px 0 6px;
}

.inventario-cables .hint {
  font-size: 0.8rem;
  color: var(--muted);
}

.inventario-cables__card {
  padding: 18px 20px;
}

.inventario-cables__filtros {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 14px;
}

.inventario-cables__campo {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 160px;
}

.inventario-cables__campo label {
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.inventario-cables__resultado-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  font-size: 13px;
  color: color-mix(in srgb, var(--color-text) 65%, transparent);
}

.inventario-cables__paginado {
  display: flex;
  align-items: center;
  gap: 10px;
}

.inventario-cables__n_id {
  display: block;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
  font-size: 11px;
}

.inventario-cables__vigente {
  color: var(--color-state-ok, #16a34a);
}

.inventario-cables__vigente.is-no {
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.tabla-cables {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.tabla-cables th,
.tabla-cables td {
  text-align: left;
  padding: 7px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--color-text) 10%, transparent);
}

.tabla-cables th {
  font-weight: 500;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  font-size: 12px;
}
</style>
