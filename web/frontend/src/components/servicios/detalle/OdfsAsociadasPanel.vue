<!--
  Nombre de archivo: OdfsAsociadasPanel.vue
  Ubicación de archivo: web/frontend/src/components/servicios/detalle/OdfsAsociadasPanel.vue
  Descripción: ODFs y empalmes que declara el archivo de tracking de ruta de un Servicio, agrupados
  por ruta — bloque propio dentro de la vista de Camino óptico
-->
<template>
  <section class="odfs" aria-label="ODFs asociadas">
    <header class="odfs__head">
      <h4 class="odfs__titulo">ODFs asociadas (tracking de ruta)</h4>
      <div class="odfs__head-right">
        <label class="odfs__toggle">
          <input v-model="mostrarTodos" type="checkbox" />
          Mostrar todos los empalmes (incl. no-ODF)
        </label>
        <span class="odfs__chip">{{ totalOdfs }} ODF(s)</span>
      </div>
    </header>

    <!-- El aviso de fuente no es decorativo: arriba de este bloque vive el camino que declara
         Cromo. Son dos sistemas independientes sobre el mismo Servicio y confundirlos lleva a
         "corregir" el que estaba bien. -->
    <p class="odfs__fuente">
      Salen del archivo de tracking subido para la ruta, no de la ingesta de Cromo. Que difieran del
      camino de arriba es un dato, no un error de esta pantalla.
    </p>

    <p v-if="cargando" class="odfs__nota">Cargando ODFs asociadas…</p>
    <p v-else-if="error" class="odfs__nota is-error">{{ error }}</p>
    <p v-else-if="filas.length === 0" class="odfs__nota">
      Sin ODFs detectadas en el tracking de este Servicio.
    </p>

    <template v-else>
      <div v-for="grupo in porRuta" :key="grupo.ruta_id" class="odfs__grupo">
        <h5 class="odfs__subtitulo">{{ grupo.ruta_nombre }} ({{ grupo.ruta_tipo }})</h5>
        <p v-if="grupo.terminal_a && grupo.terminal_b" class="odfs__puntas">
          Puntas ODF: {{ grupo.terminal_a.odf_id }}:{{ grupo.terminal_a.conector }} →
          {{ grupo.terminal_b.odf_id }}:{{ grupo.terminal_b.conector }}
        </p>

        <table class="tabla-odfs">
          <thead>
            <tr>
              <th>Empalme ID</th>
              <th>Descripción</th>
              <th>Tipo</th>
              <th>Cámara</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fila in grupo.filas" :key="fila.empalme_id">
              <td>{{ fila.empalme_id }}</td>
              <td>{{ fila.descripcion }}</td>
              <td>
                <span :class="['odfs__chip', { 'is-outline': fila.es_transito }]">
                  {{ fila.es_transito ? 'ODF' : 'Empalme' }}
                </span>
              </td>
              <td>
                <span v-if="fila.camara_nombre">{{ fila.camara_nombre }}</span>
                <span v-else class="odfs__muted">Sin match</span>
              </td>
              <td>
                <span v-if="fila.camara_estado" class="odfs__estado">
                  <span
                    :class="['odfs__dot', `is-${estadoCamaraToken(fila.camara_estado)}`]"
                    aria-hidden="true"
                  ></span>
                  {{ fila.camara_estado }}
                </span>
                <span v-else class="odfs__muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import { estadoCamaraToken } from '../../../api/camaras';
import {
  type InfraOdfEmpalme,
  type InfraOdfRuta,
  type InfraOdfTerminal,
  getOdfsServicio,
} from '../../../api/servicioSecciones';

const props = defineProps<{
  /** ID de origen ya normalizado del Servicio, que es lo que pide el endpoint (no la PK). */
  idOrigen: string;
}>();

const cargando = ref(false);
const error = ref('');
const rutas = ref<InfraOdfRuta[]>([]);
const totalOdfs = ref(0);
// Por defecto sólo se ven los empalmes que son ODF (es_transito === true); tildar el checkbox
// revela también los empalmes simples (cámaras de paso, etc.) del tracking.
const mostrarTodos = ref(false);

// Fila individual aplanada de un empalme, etiquetada con los datos de su ruta padre. terminal_a y
// terminal_b viven aparte, a nivel de ruta (ver porRuta) — nunca se cruzan contra una fila puntual.
interface OdfFlatRow extends InfraOdfEmpalme {
  ruta_id: number;
  ruta_nombre: string;
  ruta_tipo: string;
}

interface OdfGrupoRuta {
  ruta_id: number;
  ruta_nombre: string;
  ruta_tipo: string;
  terminal_a: InfraOdfTerminal | null;
  terminal_b: InfraOdfTerminal | null;
  filas: OdfFlatRow[];
}

const filas = computed<OdfFlatRow[]>(() =>
  rutas.value.flatMap((ruta) =>
    ruta.empalmes
      .filter((empalme) => empalme.es_transito || mostrarTodos.value)
      .map((empalme) => ({
        ...empalme,
        ruta_id: ruta.ruta_id,
        ruta_nombre: ruta.ruta_nombre,
        ruta_tipo: ruta.ruta_tipo,
      })),
  ),
);

// Reagrupa las filas por ruta para el render (subtítulo + leyenda de puntas + tabla por ruta),
// omitiendo rutas sin ninguna fila visible bajo el filtro actual.
const porRuta = computed<OdfGrupoRuta[]>(() =>
  rutas.value
    .map((ruta) => ({
      ruta_id: ruta.ruta_id,
      ruta_nombre: ruta.ruta_nombre,
      ruta_tipo: ruta.ruta_tipo,
      terminal_a: ruta.terminal_a,
      terminal_b: ruta.terminal_b,
      filas: filas.value.filter((fila) => fila.ruta_id === ruta.ruta_id),
    }))
    .filter((grupo) => grupo.filas.length > 0),
);

async function cargar(idOrigen: string): Promise<void> {
  const limpio = idOrigen.trim();
  rutas.value = [];
  totalOdfs.value = 0;
  error.value = '';
  // La vista monta este panel antes de resolver la identidad del Servicio: sin ID todavía no hay
  // nada que pedir, y el watch vuelve a entrar acá en cuanto el ID llega.
  if (!limpio) return;

  cargando.value = true;
  try {
    const data = await getOdfsServicio(limpio);
    rutas.value = data.rutas ?? [];
    totalOdfs.value = data.total_odfs ?? 0;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo cargar ODFs asociadas';
  } finally {
    cargando.value = false;
  }
}

watch(() => props.idOrigen, cargar, { immediate: true });
</script>

<style scoped>
.odfs {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.odfs__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.odfs__titulo {
  margin: 0;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.odfs__head-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.odfs__toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  cursor: pointer;
}

.odfs__chip {
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 10.5px;
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.odfs__chip.is-outline {
  background: transparent;
  border: 1px solid var(--color-accent);
  color: var(--color-accent);
}

.odfs__fuente {
  margin: 0;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.odfs__nota {
  margin: 0;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.odfs__nota.is-error {
  color: var(--color-state-error);
}

.odfs__grupo {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.odfs__grupo + .odfs__grupo {
  margin-top: 10px;
  padding-top: 12px;
  border-top: 1px solid var(--color-divider);
}

.odfs__subtitulo {
  margin: 0;
  font-size: 13px;
  font-weight: 500;
}

.odfs__puntas {
  margin: 0;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.odfs__muted {
  color: color-mix(in srgb, var(--color-text) 40%, transparent);
}

.odfs__estado {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.odfs__dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--color-state-idle);
}
.odfs__dot.is-ok { background: var(--color-state-ok); }
.odfs__dot.is-warn { background: var(--color-state-warn); }
.odfs__dot.is-error { background: var(--color-state-error); }
.odfs__dot.is-idle { background: var(--color-state-idle); }

.tabla-odfs {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.tabla-odfs th,
.tabla-odfs td {
  text-align: left;
  padding: 6px 9px;
  border-bottom: 1px solid var(--color-divider);
}

.tabla-odfs th {
  font-weight: 500;
  font-size: 11px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

@media (max-width: 720px) {
  .odfs__head-right {
    width: 100%;
    justify-content: space-between;
  }
}
</style>
