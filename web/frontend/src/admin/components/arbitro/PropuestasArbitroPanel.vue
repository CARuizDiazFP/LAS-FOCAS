<!--
  Nombre de archivo: PropuestasArbitroPanel.vue
  Ubicación de archivo: web/frontend/src/admin/components/arbitro/PropuestasArbitroPanel.vue
  Descripción: Pestaña Propuestas del árbitro de Cromo — análisis retroactivo arriba y tabla filtrable de propuestas con señales, selección múltiple y acciones Aplicar, Rechazar y Revertir
-->
<template>
  <div class="propuestas">
    <AnalisisRetroactivoPanel @terminada="onEvaluacionTerminada" />

    <div class="propuestas__toolbar">
      <label class="propuestas__campo">
        <span>Regla</span>
        <select v-model="filtroRegla" @change="reloadFromZero">
          <option value="">Todas</option>
          <option v-for="codigo in codigosRegla" :key="codigo" :value="codigo">{{ codigo }}</option>
        </select>
      </label>
      <div class="propuestas__chips">
        <span class="propuestas__etiqueta">Estado</span>
        <button
          v-for="opcion in estadosFiltro"
          :key="opcion.valor"
          type="button"
          :class="['propuestas__chip', { 'is-active': filtroEstado === opcion.valor }]"
          @click="setEstado(opcion.valor)"
        >
          {{ opcion.label }}
        </button>
      </div>
      <button class="btn primary" type="button" :disabled="loading" @click="reloadFromZero">
        <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
        Actualizar
      </button>
      <span class="propuestas__count">
        <strong>{{ total.toLocaleString('es-AR') }}</strong> propuestas · mostrando {{ items.length }}
      </span>
    </div>

    <div class="propuestas__toolbar">
      <button class="btn primary" type="button" :disabled="accionando || seleccion.size === 0" @click="ejecutar('aplicar')">
        <i class="ph ph-check" aria-hidden="true"></i>
        Aplicar ({{ seleccion.size }})
      </button>
      <button class="btn" type="button" :disabled="accionando || seleccion.size === 0" @click="ejecutar('rechazar')">
        <i class="ph ph-x" aria-hidden="true"></i>
        Rechazar ({{ seleccion.size }})
      </button>
      <button class="btn" type="button" :disabled="accionando || seleccion.size === 0" @click="ejecutar('revertir')">
        <i class="ph ph-arrow-counter-clockwise" aria-hidden="true"></i>
        Revertir ({{ seleccion.size }})
      </button>
    </div>

    <div v-if="error" class="propuestas__error">{{ error }}</div>
    <div v-if="mensaje" class="propuestas__ok">{{ mensaje }}</div>
    <div v-if="rechazados.length" class="propuestas__rechazados" role="status">
      <strong>{{ rechazados.length }} propuesta(s) no se procesaron:</strong>
      <ul>
        <li v-for="r in rechazados" :key="r.id">Propuesta {{ r.id }}: {{ r.motivo }}</li>
      </ul>
      <button type="button" class="btn subtle" @click="rechazados = []">Cerrar</button>
    </div>

    <div class="propuestas__scroll">
      <table v-if="items.length > 0" class="propuestas__tabla">
        <thead>
          <tr>
            <th class="propuestas__check">
              <input
                type="checkbox"
                :checked="todosSeleccionados"
                aria-label="Seleccionar todas las propuestas visibles"
                @change="toggleTodos"
              />
            </th>
            <th>Regla</th>
            <th>Objeto</th>
            <th>Acción</th>
            <th>Confianza</th>
            <th>Señales</th>
            <th>Disparo</th>
            <th>Estado</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in items" :key="p.id">
            <td class="propuestas__check">
              <input
                type="checkbox"
                :checked="seleccion.has(p.id)"
                :aria-label="`Seleccionar propuesta ${p.id}`"
                @change="toggle(p.id)"
              />
            </td>
            <td>{{ p.regla }}</td>
            <td>
              <router-link v-if="p.objeto_tipo === 'SERVICIO'" :to="{ name: 'servicios-detail', params: { idServicio: p.objeto_id } }">
                Servicio {{ p.objeto_id }}
              </router-link>
              <template v-else>{{ p.objeto_tipo }} {{ p.objeto_id }}</template>
            </td>
            <td>
              {{ p.accion }}
              <span v-if="p.nota" class="propuestas__sub">{{ p.nota }}</span>
            </td>
            <td>
              <div class="propuestas__barra" :title="`${p.confianza}`">
                <div class="propuestas__barra-relleno" :style="{ width: `${porcentaje(p.confianza)}%` }"></div>
              </div>
              <span class="propuestas__sub">{{ p.confianza }}</span>
            </td>
            <td>
              <details class="propuestas__senales">
                <summary>{{ p.senales.length }} señal(es){{ p.senales.some((s) => s.veto) ? ' · veto' : '' }}</summary>
                <ul>
                  <li v-for="(s, i) in p.senales" :key="i" :class="{ 'is-veto': s.veto }" :title="s.detalle ?? ''">
                    {{ s.codigo }} {{ s.peso >= 0 ? '+' : '' }}{{ s.peso }}<template v-if="s.veto"> (veto)</template>
                  </li>
                </ul>
              </details>
            </td>
            <td>
              {{ p.disparo }}
              <span class="propuestas__sub">{{ p.modo_al_evaluar }}</span>
            </td>
            <td>
              <span :class="['propuestas__estado', `is-${p.estado.toLowerCase()}`]">{{ p.estado }}</span>
              <span v-if="p.decidida_por" class="propuestas__sub">{{ p.decidida_por }}</span>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-else-if="!loading" class="propuestas__vacio">
        <h3>Sin propuestas</h3>
        <p>Nada coincide con los filtros. Las propuestas aparecen al correr el análisis retroactivo o tras cada ingesta.</p>
      </div>

      <div v-if="loading" class="propuestas__cargando">
        <i class="ph ph-circle-notch propuestas__spin" aria-hidden="true"></i>
        Cargando...
      </div>

      <div v-if="hasMore && !loading" class="propuestas__cargando">
        <button type="button" class="btn" @click="loadNextPage">Cargar más</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import {
  aplicarPropuestas,
  listarPropuestas,
  listarReglas,
  rechazarPropuestas,
  revertirPropuestas,
  type PropuestaArbitro,
} from '../../../api/arbitroCromo';
import { useAdminNotifications } from '../../../composables/useAdminNotifications';
import AnalisisRetroactivoPanel from './AnalisisRetroactivoPanel.vue';

const LIMIT = 100;

type Accion = 'aplicar' | 'rechazar' | 'revertir';

const ACCIONES: Record<Accion, { verbo: string; confirmar: string }> = {
  aplicar: { verbo: 'aplicadas', confirmar: 'Se aplicarán {n} propuesta(s) sobre el inventario real. ¿Continuar?' },
  rechazar: {
    verbo: 'rechazadas',
    confirmar: 'Se rechazarán {n} propuesta(s); no se volverán a proponer con la misma evidencia. ¿Continuar?',
  },
  revertir: { verbo: 'revertidas', confirmar: 'Se revertirán {n} propuesta(s) en observación o aplicadas. ¿Continuar?' },
};

const estadosFiltro = [
  { valor: 'PROPUESTA', label: 'Propuestas' },
  { valor: 'EN_OBSERVACION', label: 'En observación' },
  { valor: 'APLICADA', label: 'Aplicadas' },
  { valor: 'RECHAZADA', label: 'Rechazadas' },
  { valor: 'REVERTIDA', label: 'Revertidas' },
  { valor: 'OBSOLETA', label: 'Obsoletas' },
  { valor: '', label: 'Todas' },
];

const items = ref<PropuestaArbitro[]>([]);
const total = ref(0);
const offset = ref(0);
const hasMore = ref(false);
const loading = ref(false);
const accionando = ref(false);
const error = ref('');
const mensaje = ref('');
const rechazados = ref<{ id: number; motivo: string }[]>([]);
const filtroRegla = ref('');
const filtroEstado = ref('PROPUESTA');
const codigosRegla = ref<string[]>([]);
const seleccion = ref(new Set<number>());

const todosSeleccionados = computed(
  () => items.value.length > 0 && items.value.every((p) => seleccion.value.has(p.id)),
);

function porcentaje(confianza: number): number {
  return Math.max(0, Math.min(100, confianza));
}

async function loadNextPage(): Promise<void> {
  if (loading.value) return;
  loading.value = true;
  error.value = '';
  try {
    const respuesta = await listarPropuestas({
      regla: filtroRegla.value || undefined,
      estado: filtroEstado.value || undefined,
      limit: LIMIT,
      offset: offset.value,
    });
    total.value = respuesta.total;
    const vistos = new Set(items.value.map((p) => p.id));
    items.value.push(...respuesta.items.filter((p) => !vistos.has(p.id)));
    offset.value += respuesta.items.length;
    hasMore.value = respuesta.items.length === LIMIT && offset.value < respuesta.total;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudieron consultar las propuestas';
  } finally {
    loading.value = false;
  }
}

async function reloadFromZero(): Promise<void> {
  items.value = [];
  total.value = 0;
  offset.value = 0;
  hasMore.value = false;
  seleccion.value = new Set();
  await loadNextPage();
}

function setEstado(valor: string): void {
  filtroEstado.value = valor;
  void reloadFromZero();
}

function toggle(id: number): void {
  const nuevo = new Set(seleccion.value);
  if (nuevo.has(id)) nuevo.delete(id);
  else nuevo.add(id);
  seleccion.value = nuevo;
}

function toggleTodos(): void {
  seleccion.value = todosSeleccionados.value ? new Set() : new Set(items.value.map((p) => p.id));
}

async function ejecutar(accion: Accion): Promise<void> {
  const ids = [...seleccion.value];
  if (!ids.length) return;
  const cfg = ACCIONES[accion];
  if (!window.confirm(cfg.confirmar.replace('{n}', String(ids.length)))) return;
  accionando.value = true;
  error.value = '';
  mensaje.value = '';
  rechazados.value = [];
  try {
    if (accion === 'aplicar') {
      const r = await aplicarPropuestas(ids);
      mensaje.value = `${r.aplicados.length} propuesta(s) aplicadas.`;
      rechazados.value = r.rechazados;
    } else if (accion === 'rechazar') {
      const r = await rechazarPropuestas(ids);
      mensaje.value = `${r.rechazados.length} propuesta(s) rechazadas.`;
      rechazados.value = r.omitidos;
    } else {
      const r = await revertirPropuestas(ids);
      mensaje.value = `${r.revertidos.length} propuesta(s) revertidas.`;
      rechazados.value = r.omitidos;
    }
    await reloadFromZero();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : `No se pudo completar: ${cfg.verbo}`;
  } finally {
    accionando.value = false;
  }
}

/** Al terminar un análisis se muestran sus propuestas: filtro por la regla de la corrida (si fue una sola). */
function onEvaluacionTerminada(reglas: string[]): void {
  filtroRegla.value = reglas.length === 1 ? reglas[0] : '';
  filtroEstado.value = 'PROPUESTA';
  void reloadFromZero();
}

// Otras corridas (ingesta, viewer) también dejan propuestas: se recarga la lista al terminar cada evaluación.
const { on } = useAdminNotifications();
on('arbitro_cromo_evaluado', () => void reloadFromZero());

onMounted(async () => {
  void listarReglas()
    .then((reglas) => {
      codigosRegla.value = reglas.map((r) => r.codigo);
    })
    .catch(() => undefined);
  await reloadFromZero();
});
</script>

<style scoped>
.propuestas { display: flex; flex-direction: column; flex: 1; min-height: 0; }

.propuestas__toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 4px 0 10px; }

.propuestas__campo { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--color-neutral-500); }

.propuestas__campo select {
  min-height: 34px;
  padding: 5px 10px;
  font-size: 13px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.propuestas__chips { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; flex: 1; }

.propuestas__etiqueta {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-neutral-500);
}

.propuestas__chip {
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  font-size: 11.5px;
  cursor: pointer;
  border: 1px solid var(--color-divider);
  background: transparent;
  color: color-mix(in srgb, var(--color-text) 66%, transparent);
}

.propuestas__chip:hover { border-color: var(--color-accent); }

.propuestas__chip.is-active {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  color: var(--color-accent-200);
}

.propuestas__count {
  margin-left: auto;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
  white-space: nowrap;
}

.propuestas__count strong { color: var(--color-text); font-weight: 500; }

.propuestas__error,
.propuestas__ok,
.propuestas__rechazados {
  margin-bottom: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  font-size: 12.5px;
}

.propuestas__error { background: color-mix(in srgb, var(--color-state-error) 14%, transparent); color: var(--color-state-error); }
.propuestas__ok { background: color-mix(in srgb, var(--color-state-ok) 14%, transparent); color: var(--color-state-ok); }
.propuestas__rechazados { background: color-mix(in srgb, var(--color-state-warn) 14%, transparent); color: var(--color-state-warn); }
.propuestas__rechazados ul { margin: 6px 0 8px; padding-left: 18px; }

.propuestas__scroll { flex: 1; min-height: 0; overflow: auto; }
.propuestas__tabla { width: 100%; border-collapse: collapse; font-size: 12.5px; }

.propuestas__tabla th {
  position: sticky;
  top: 0;
  z-index: 1;
  text-align: left;
  font-weight: 500;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 8px 10px;
  background: var(--color-surface);
  color: var(--color-neutral-500);
  border-bottom: 1px solid var(--color-divider);
}

.propuestas__tabla td {
  padding: 8px 10px;
  vertical-align: top;
  border-bottom: 1px solid var(--color-neutral-800);
  color: var(--color-text);
}

.propuestas__tabla a { color: var(--color-accent-200); text-decoration: none; }
.propuestas__tabla a:hover { text-decoration: underline; }
.propuestas__check { width: 28px; }

.propuestas__sub { display: block; font-size: 11px; color: color-mix(in srgb, var(--color-text) 50%, transparent); }

.propuestas__barra { width: 90px; height: 6px; border-radius: var(--radius-pill); background: var(--color-neutral-800); overflow: hidden; }
.propuestas__barra-relleno { height: 100%; background: var(--color-accent); }

.propuestas__senales summary { cursor: pointer; font-size: 11.5px; color: var(--color-neutral-500); }
.propuestas__senales ul { margin: 4px 0 0; padding-left: 16px; font-size: 11.5px; }
.propuestas__senales li.is-veto { color: var(--color-state-error); font-weight: 500; }

.propuestas__estado { font-size: 11.5px; font-weight: 500; }
.propuestas__estado.is-propuesta { color: var(--color-state-warn); }
.propuestas__estado.is-en_observacion { color: var(--color-accent-200); }
.propuestas__estado.is-aplicada { color: var(--color-state-ok); }
.propuestas__estado.is-rechazada,
.propuestas__estado.is-revertida { color: var(--color-state-error); }
.propuestas__estado.is-obsoleta { color: var(--color-state-idle); }

.propuestas__vacio {
  max-width: 320px;
  margin: 34px auto;
  padding: 34px 22px;
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-neutral-800);
  text-align: center;
}

.propuestas__vacio h3 { font-size: 15px; font-weight: 500; margin: 0 0 6px; }
.propuestas__vacio p { font-size: 12.5px; line-height: 1.5; margin: 0; color: color-mix(in srgb, var(--color-text) 60%, transparent); }

.propuestas__cargando {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.propuestas__spin { animation: propuestas-spin 1s linear infinite; }

@keyframes propuestas-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
