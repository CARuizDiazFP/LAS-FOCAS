<!--
  Nombre de archivo: ReglasArbitroPanel.vue
  Ubicación de archivo: web/frontend/src/admin/components/arbitro/ReglasArbitroPanel.vue
  Descripción: Pestaña Reglas del árbitro de Cromo — modo, umbral y presupuesto por regla, con precisión histórica y aviso de las listas para pasar a AUTO
-->
<template>
  <div class="reglas">
    <div v-if="error" class="reglas__error">{{ error }}</div>
    <div v-if="mensaje" class="reglas__ok">{{ mensaje }}</div>

    <div class="reglas__scroll">
      <table v-if="filas.length" class="reglas__tabla">
        <thead>
          <tr>
            <th>Regla</th>
            <th>Modo</th>
            <th>Umbral</th>
            <th>Presupuesto por corrida</th>
            <th>Aceptadas</th>
            <th>Rechazadas</th>
            <th>Precisión</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in filas" :key="f.codigo">
            <td>
              <strong>{{ f.codigo }}</strong>
              <span class="reglas__sub">{{ f.descripcion }}</span>
              <span v-if="f.sugerir_auto" class="reglas__badge">Lista para AUTO</span>
            </td>
            <td>
              <select v-model="f.modo" :aria-label="`Modo de ${f.codigo}`">
                <option v-for="m in modos" :key="m" :value="m">{{ m }}</option>
              </select>
            </td>
            <td>
              <input v-model.number="f.umbral" type="number" min="0" max="100" step="1" :aria-label="`Umbral de ${f.codigo}`" />
            </td>
            <td>
              <input
                v-model.number="f.presupuesto_por_corrida"
                type="number"
                min="0"
                step="1"
                :aria-label="`Presupuesto por corrida de ${f.codigo}`"
              />
            </td>
            <td>{{ f.aceptadas }}</td>
            <td>{{ f.rechazadas }}</td>
            <td>{{ f.precision === null ? '—' : `${(f.precision * 100).toFixed(0)} %` }}</td>
            <td>
              <button
                type="button"
                class="btn"
                :disabled="guardando === f.codigo || !cambiada(f) || problema(f) !== ''"
                @click="guardar(f)"
              >
                Guardar
              </button>
              <span v-if="problema(f)" class="reglas__invalido" role="alert">{{ problema(f) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="!loading" class="reglas__vacio">No hay reglas configuradas.</p>
      <p v-if="loading" class="reglas__vacio">Cargando...</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';

import { MODOS_REGLA, actualizarRegla, listarReglas, type ReglaArbitro } from '../../../api/arbitroCromo';

const modos = MODOS_REGLA;
const filas = ref<ReglaArbitro[]>([]);
const guardadas = ref(new Map<string, ReglaArbitro>());
const loading = ref(false);
const guardando = ref('');
const error = ref('');
const mensaje = ref('');

async function cargar(): Promise<void> {
  loading.value = true;
  error.value = '';
  try {
    const reglas = await listarReglas();
    filas.value = reglas.map((r) => ({ ...r }));
    guardadas.value = new Map(reglas.map((r) => [r.codigo, { ...r }]));
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudieron consultar las reglas';
  } finally {
    loading.value = false;
  }
}

function cambiada(f: ReglaArbitro): boolean {
  const base = guardadas.value.get(f.codigo);
  return (
    !base || base.modo !== f.modo || base.umbral !== f.umbral || base.presupuesto_por_corrida !== f.presupuesto_por_corrida
  );
}

/** Mensaje de validación (vacío si los valores son guardables). Un input vacío llega como '' y no debe guardar 0. */
function problema(f: ReglaArbitro): string {
  const umbral: unknown = f.umbral;
  const presupuesto: unknown = f.presupuesto_por_corrida;
  if (typeof umbral !== 'number' || !Number.isInteger(umbral) || umbral < 0 || umbral > 100) {
    return 'El umbral debe ser un entero entre 0 y 100.';
  }
  if (typeof presupuesto !== 'number' || !Number.isInteger(presupuesto) || presupuesto < 0) {
    return 'El presupuesto debe ser un entero mayor o igual a 0.';
  }
  return '';
}

async function guardar(f: ReglaArbitro): Promise<void> {
  if (problema(f)) return;
  if (
    f.modo === 'AUTO' &&
    guardadas.value.get(f.codigo)?.modo !== 'AUTO' &&
    !window.confirm(
      `${f.codigo} pasará a AUTO: aplicará cambios sobre el inventario sin revisión humana (hasta ${f.presupuesto_por_corrida} por corrida). ¿Confirmar?`,
    )
  )
    return;
  guardando.value = f.codigo;
  error.value = '';
  mensaje.value = '';
  try {
    await actualizarRegla(f.codigo, {
      modo: f.modo,
      umbral: Number(f.umbral),
      presupuesto_por_corrida: Number(f.presupuesto_por_corrida),
    });
    mensaje.value = `Regla ${f.codigo} guardada.`;
    await cargar();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : `No se pudo guardar la regla ${f.codigo}`;
  } finally {
    guardando.value = '';
  }
}

onMounted(cargar);
</script>

<style scoped>
.reglas { display: flex; flex-direction: column; flex: 1; min-height: 0; }

.reglas__error,
.reglas__ok { margin-bottom: 10px; padding: 10px 14px; border-radius: var(--radius-md); font-size: 12.5px; }
.reglas__error { background: color-mix(in srgb, var(--color-state-error) 14%, transparent); color: var(--color-state-error); }
.reglas__ok { background: color-mix(in srgb, var(--color-state-ok) 14%, transparent); color: var(--color-state-ok); }

.reglas__scroll { flex: 1; min-height: 0; overflow: auto; }
.reglas__tabla { width: 100%; border-collapse: collapse; font-size: 12.5px; }

.reglas__tabla th {
  text-align: left;
  font-weight: 500;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 8px 10px;
  color: var(--color-neutral-500);
  border-bottom: 1px solid var(--color-divider);
}

.reglas__tabla td {
  padding: 8px 10px;
  vertical-align: top;
  border-bottom: 1px solid var(--color-neutral-800);
  color: var(--color-text);
}

.reglas__tabla select,
.reglas__tabla input {
  min-height: 32px;
  padding: 4px 8px;
  font-size: 13px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.reglas__tabla input { width: 90px; }

.reglas__sub { display: block; font-size: 11px; color: color-mix(in srgb, var(--color-text) 50%, transparent); }

.reglas__badge {
  display: inline-block;
  margin-top: 4px;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  background: color-mix(in srgb, var(--color-state-ok) 16%, transparent);
  color: var(--color-state-ok);
}

.reglas__invalido { display: block; margin-top: 4px; font-size: 11px; color: var(--color-state-error); }

.reglas__vacio { font-size: 12.5px; color: color-mix(in srgb, var(--color-text) 60%, transparent); }
</style>
