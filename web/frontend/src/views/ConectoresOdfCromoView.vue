<!--
  Nombre de archivo: ConectoresOdfCromoView.vue
  Ubicación de archivo: web/frontend/src/views/ConectoresOdfCromoView.vue
  Descripción: Tabla dinámica de conectores/posiciones de patchera de una ODF Cromo, filtrable por Bandeja
-->
<template>
  <section class="conectores-odf-page">
    <div class="conectores-odf-shell">
      <RouterLink
        class="conectores-odf-back"
        :to="{ path: `/infra/cromo/odfs/ID${odfNId ?? ''}` }"
      >
        ← Volver a la ODF
      </RouterLink>

      <div v-if="cargando" class="conectores-odf-state">Cargando conectores...</div>
      <div v-else-if="error" class="conectores-odf-state error">
        <strong>No se pudieron cargar los conectores.</strong>
        <span>{{ error }}</span>
        <button class="btn subtle" type="button" @click="void cargar()">Reintentar</button>
      </div>

      <template v-else-if="resultado">
        <header class="conectores-odf-hero">
          <p class="conectores-odf-hero__eyebrow">Verificador Cromo · Conectores</p>
          <h1>{{ resultado.odf_nombre || `ODF ${resultado.odf_n_id}` }}</h1>
          <span class="conectores-odf-id">n_id {{ resultado.odf_n_id }}</span>
        </header>

        <p v-if="resultado.conectores.length === 0" class="hint">
          No se encontró ningún conector para esta ODF en el inventario ingerido — puede que
          todavía no haya sido barrida con `show=ALL` (ver `core/services/cromo/ingesta.py::fase_odfs`).
        </p>

        <template v-else>
          <div class="conectores-odf-filtro">
            <label for="conectores-odf-bandeja">Bandeja</label>
            <select id="conectores-odf-bandeja" v-model="bandejaSeleccionada">
              <option :value="null">Todas</option>
              <option v-for="b in bandejas" :key="b" :value="b">{{ b }}</option>
            </select>
            <span class="conectores-odf-chip">{{ conectoresFiltrados.length }} fila(s)</span>
          </div>

          <table class="tabla-conectores">
            <thead>
              <tr>
                <th>Bandeja</th>
                <th>Conector</th>
                <th>Pelo</th>
                <th>Servicio</th>
                <th>Cliente</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in conectoresFiltrados" :key="c.n_id">
                <td>{{ c.bandeja_nombre || '—' }}</td>
                <td>{{ c.numero_conector || '—' }}</td>
                <td>{{ c.pelo_numero || (c.pelo_n_id != null ? `#${c.pelo_n_id}` : '—') }}</td>
                <td>
                  <template v-if="c.servicio_resuelto">
                    <button
                      v-if="c.servicio_id_externo"
                      class="conectores-odf-servicio-link"
                      type="button"
                      @click="irAServicioPorId(c.servicio_id_externo)"
                    >
                      {{ c.servicio_resuelto }}
                    </button>
                    <span v-else>{{ c.servicio_resuelto }}</span>
                    <span v-if="c.servicio_id_historico" class="conectores-odf-historico">
                      antes: {{ c.servicio_id_historico }}
                    </span>
                  </template>
                  <span v-else>—</span>
                </td>
                <td>{{ c.nombre_cliente || c.cliente || '—' }}</td>
                <td>{{ c.estado_servicio || '—' }}</td>
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
import { useRoute, useRouter } from 'vue-router';

import { ApiError } from '../api/client';
import { obtenerConectoresDeOdf, type CromoConectoresOdf } from '../api/cromo';

const route = useRoute();
const router = useRouter();

const cargando = ref(true);
const error = ref('');
const resultado = ref<CromoConectoresOdf | null>(null);
const bandejaSeleccionada = ref<string | null>(null);

const odfNId = computed(() => {
  const raw = String(route.query.n_id ?? '');
  const value = Number(raw);
  return Number.isInteger(value) && value > 0 ? value : null;
});

const bandejas = computed(() => {
  const nombres = (resultado.value?.conectores ?? [])
    .map((c) => c.bandeja_nombre)
    .filter((n): n is string => Boolean(n));
  return [...new Set(nombres)];
});

const conectoresFiltrados = computed(() => {
  const todos = resultado.value?.conectores ?? [];
  if (bandejaSeleccionada.value == null) return todos;
  return todos.filter((c) => c.bandeja_nombre === bandejaSeleccionada.value);
});

// Mismo patrón que CableDetalleCromoView.vue/OdfDetalleCromoView.vue::irAServicioPorId.
function irAServicioPorId(servicioIdExterno: string): void {
  void router.push(`/servicios/ID/${encodeURIComponent(servicioIdExterno)}`);
}

async function cargar(): Promise<void> {
  const nId = odfNId.value;
  if (nId == null) {
    error.value = 'Falta el parámetro n_id de la ODF en la URL.';
    cargando.value = false;
    return;
  }

  cargando.value = true;
  error.value = '';
  resultado.value = null;
  bandejaSeleccionada.value = null;

  try {
    resultado.value = await obtenerConectoresDeOdf(nId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      error.value = `No existe una ODF con n_id=${nId} en el inventario ingerido.`;
    } else {
      error.value = e instanceof Error ? e.message : 'Error consultando los conectores.';
    }
  } finally {
    cargando.value = false;
  }
}

watch(() => route.query.n_id, () => void cargar());

onMounted(() => void cargar());
</script>

<style scoped>
.conectores-odf-page {
  min-height: 100%;
}

.conectores-odf-shell {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 20px 40px;
}

.conectores-odf-back {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-accent);
  text-decoration: none;
  margin-bottom: 18px;
}

.conectores-odf-back:hover {
  color: var(--color-accent-300);
}

.conectores-odf-state {
  padding: 24px;
  border-radius: 16px;
  border: 1px solid var(--color-divider);
  background: var(--color-surface);
  color: var(--muted);
}

.conectores-odf-state.error {
  display: flex;
  flex-direction: column;
  gap: 10px;
  color: var(--error);
  border-color: color-mix(in srgb, var(--error) 30%, transparent);
}

.conectores-odf-hero {
  margin-bottom: 18px;
}

.conectores-odf-hero__eyebrow {
  margin: 0;
  color: var(--color-accent);
  font-size: 0.76rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.conectores-odf-hero h1 {
  margin: 6px 0 6px;
  font-size: 1.6rem;
  color: var(--color-text);
}

.conectores-odf-id {
  font-size: 0.8rem;
  color: var(--muted);
}

.conectores-odf-filtro {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.conectores-odf-filtro label {
  font-size: 0.8rem;
  color: var(--muted);
}

.conectores-odf-filtro select {
  min-width: 220px;
}

.conectores-odf-chip {
  display: inline-flex;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 9px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-text) 10%, transparent);
  color: var(--muted);
}

.conectores-odf-servicio-link {
  display: inline-block;
  padding: 2px 8px;
  border: none;
  border-radius: 999px;
  background: var(--color-brand-primary-tint);
  color: var(--color-accent-200);
  font-size: 0.78rem;
  cursor: pointer;
}

.conectores-odf-servicio-link:hover {
  background: var(--color-brand-primary-soft);
}

.conectores-odf-historico {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: var(--muted);
}

.tabla-conectores {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.tabla-conectores th,
.tabla-conectores td {
  text-align: left;
  padding: 7px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--color-text) 10%, transparent);
  vertical-align: top;
}

.tabla-conectores th {
  font-weight: 500;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  font-size: 12px;
}

.hint {
  font-size: 0.8rem;
  color: var(--muted);
}
</style>
