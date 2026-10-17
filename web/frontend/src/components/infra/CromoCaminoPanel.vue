<!--
  Nombre de archivo: CromoCaminoPanel.vue
  Ubicación de archivo: web/frontend/src/components/infra/CromoCaminoPanel.vue
  Descripción: Panel reutilizable del camino óptico de Cromo — semillas, resolución cancelable, estadísticas, auditoría de consistencia y secuencia de nodos
-->
<template>
  <section class="cromo-camino">
    <header class="cromo-camino__head">
      <h4 class="cromo-camino__titulo">Camino óptico en Cromo</h4>
      <!-- Un solo botón con dos acciones: la principal resuelve los tramos del Servicio (lo que
           se descarga y lo que hace `@bot track`); el menú abre el detalle nodo a nodo del pelo
           elegido (secuencia, estadísticas y consistencia). Antes eran dos botones sueltos con
           nombres casi iguales ("Resolver camino" / "Resolver caminos"). -->
      <div
        v-if="camino.tieneSemilla.value && servicioId !== null"
        ref="menuEl"
        class="cromo-camino__accion"
      >
        <button
          class="btn subtle cromo-camino__accion-principal"
          type="button"
          :disabled="ocupado"
          title="Resuelve en Cromo los tramos del Servicio"
          @click="camino.resolverCaminos(servicioId)"
        >
          <i class="ph ph-path" aria-hidden="true"></i>
          {{
            camino.resolviendoCaminos.value
              ? 'Resolviendo caminos…'
              : camino.caminosResueltos.value
                ? 'Resolver caminos de nuevo'
                : 'Resolver caminos'
          }}
        </button>
        <button
          class="btn subtle cromo-camino__accion-menu"
          type="button"
          :disabled="ocupado"
          aria-haspopup="menu"
          :aria-expanded="menuAbierto"
          aria-label="Más acciones del camino"
          title="Más acciones"
          @click="menuAbierto = !menuAbierto"
        >
          <i class="ph ph-caret-down" aria-hidden="true"></i>
        </button>
        <ul v-if="menuAbierto" class="cromo-camino__menu" role="menu">
          <li role="none">
            <button type="button" role="menuitem" @click="detallePelo(null)">
              <i class="ph ph-tree-structure" aria-hidden="true"></i>
              Ver detalle del pelo elegido
            </button>
          </li>
        </ul>
      </div>
    </header>

    <p v-if="camino.cargandoPelos.value" class="cromo-camino__nota">Buscando pelos…</p>
    <p v-else-if="!camino.tieneSemilla.value" class="cromo-camino__nota">
      Este Servicio no tiene ningún pelo en Cromo, así que no hay camino que resolver.
    </p>

    <!-- Sin conectores de ODF ingeridos no se pueden preseleccionar las posiciones del Servicio.
         No bloquea el tracking: los caminos se resuelven desde los pelos de los cables (hay
         Servicios, como el 94673, cuyos extremos no terminan en ninguna ODF). -->
    <p
      v-if="camino.tieneSemilla.value && !camino.odfRelevada.value"
      class="cromo-camino__aviso"
    >
      <i class="ph ph-info" aria-hidden="true"></i>
      <span>
        Este Servicio no tiene posiciones de ODF relevadas: sus caminos se resuelven desde los
        pelos de los cables.
      </span>
      <!-- Resuelve la causa en vez de sólo reportarla: releva las ODFs que el camino descubrió. -->
      <button
        v-if="esAdmin && servicioId !== null"
        type="button"
        class="btn subtle"
        :disabled="camino.relevandoOdf.value"
        title="Trae de Cromo las ODFs que atraviesa este camino, con sus posiciones de patchera"
        @click="relevarOdf"
      >
        {{ camino.relevandoOdf.value ? 'Relevando…' : 'Relevar la ODF' }}
      </button>
    </p>
    <p v-if="camino.errorRelevarOdf.value" class="cromo-camino__nota is-error">
      {{ camino.errorRelevarOdf.value }}
    </p>

    <!-- Caminos del Servicio: tantos como pelos suyos en un mismo cable u ODF (regla de
         operaciones). Cuáles son lo resuelve el backend contra Cromo, igual que `@bot track`. -->
    <div v-if="camino.tieneSemilla.value" class="cromo-camino__caminos">
      <!-- Sólo lo que declaró el operador: la moda de pelos por cable de `/pelos` no es una
           expectativa (un servicio segmentado tiene más trackings que esa moda). -->
      <p class="cromo-camino__nota">
        <template v-if="camino.esperadosDeclarados.value != null">
          Trackings esperados: <strong>{{ camino.esperadosDeclarados.value }}</strong>
        </template>
        <template v-if="camino.caminosResueltos.value">
          <template v-if="camino.esperadosDeclarados.value != null"> · </template>
          resueltos: <strong>{{ camino.tramos.value.length }}</strong>
        </template>
        <template v-if="camino.caminosResueltos.value && camino.segmentos.value > 1">
          · Servicio segmentado en {{ camino.segmentos.value }} tramos
          ({{ camino.tramos.value.length }} trackings).
        </template>
      </p>
    </div>
    <p v-if="camino.errorCaminos.value" class="cromo-camino__error">
      {{ camino.errorCaminos.value }}
    </p>
    <!-- Un tramo por `.txt`: cada fila baja el suyo; "Descargar todos" baja uno por tramo en
         serie desde el botón de la vista. -->
    <ul v-if="camino.tramos.value.length" class="cromo-camino__lista">
      <li v-for="t in camino.tramos.value" :key="t.pelo_n_id">
        <span>
          {{ etiquetaTramo(t) }}
          <span v-if="t.desde_cache" class="cromo-camino__odf-meta">· en caché</span>
        </span>
        <span v-if="servicioId !== null" class="cromo-camino__acciones">
          <button
            class="btn subtle"
            type="button"
            :disabled="ocupado"
            title="Detalle nodo a nodo de este tramo"
            @click="detallePelo(t.pelo_n_id)"
          >
            Detalle
          </button>
          <button
            class="btn subtle"
            type="button"
            :disabled="camino.descargando.value || camino.resolviendoCaminos.value"
            :title="t.nombre_archivo"
            @click="camino.descargarTramo(servicioId, t)"
          >
            Descargar
          </button>
        </span>
      </li>
    </ul>
    <!-- Lo que declara el operador sobre el tracking: cuántos espera y qué ODF son del recorrido.
         Un camino que toca una ODF confirmada es siempre tramo. Sólo un admin escribe. -->
    <div v-if="camino.caminosResueltos.value" class="cromo-camino__declaracion">
      <label class="cromo-camino__esperados">
        <span class="cromo-camino__nota">Trackings esperados</span>
        <input
          v-model="esperadosEditado"
          class="cromo-camino__input"
          type="number"
          min="1"
          max="32767"
          inputmode="numeric"
          placeholder="sin declarar"
          :disabled="!esAdmin || camino.guardandoDeclaracion.value"
          @change="guardarEsperados"
        />
      </label>

      <!-- Todas las ODF de tramos y residuales (extremos e intermedias) más las confirmadas, que
           siempre aparecen para poder quitarlas. -->
      <template v-if="camino.odfsDelCamino.value.length">
        <p class="cromo-camino__nota">ODF del camino</p>
        <ul class="cromo-camino__lista">
          <li v-for="o in camino.odfsDelCamino.value" :key="o.odf_n_id">
            <span>
              {{ o.clase === 86 ? 'ODF Nodo' : 'ODF' }} {{ o.nombre ?? o.odf_n_id }}
              <span v-if="confirmadaDe(o.odf_n_id)" class="cromo-camino__confirmada">
                <i class="ph ph-check-circle" aria-hidden="true"></i>
                confirmada ({{ rolLabel(confirmadaDe(o.odf_n_id)!.rol) }})
              </span>
            </span>
            <span v-if="esAdmin && servicioId !== null" class="cromo-camino__acciones">
              <template v-if="confirmadaDe(o.odf_n_id)">
                <button
                  class="btn subtle"
                  type="button"
                  :disabled="camino.guardandoDeclaracion.value"
                  @click="camino.quitarOdf(servicioId, confirmadaDe(o.odf_n_id)!.odf_n_id)"
                >
                  Quitar
                </button>
              </template>
              <template v-else>
                <select
                  class="cromo-camino__input"
                  :value="rolDe(o)"
                  :disabled="camino.guardandoDeclaracion.value"
                  :aria-label="`Rol de la ODF ${o.nombre ?? o.odf_n_id}`"
                  @change="rolesElegidos[o.odf_n_id] = ($event.target as HTMLSelectElement).value as RolOdfConfirmada"
                >
                  <option value="EXTREMO">Extremo</option>
                  <option value="TRANSITO">Tránsito</option>
                </select>
                <button
                  class="btn subtle"
                  type="button"
                  :disabled="camino.guardandoDeclaracion.value"
                  @click="camino.confirmarOdf(servicioId, o.odf_n_id, rolDe(o))"
                >
                  Confirmar
                </button>
              </template>
            </span>
          </li>
        </ul>
      </template>
      <p v-if="camino.declaracionCambio.value" class="cromo-camino__nota">
        Lo declarado se aplica al volver a resolver los caminos.
      </p>
      <p v-if="camino.errorDeclaracion.value" class="cromo-camino__error">
        {{ camino.errorDeclaracion.value }}
      </p>
    </div>

    <!-- Residuales: caminos de pelos con la etiqueta del Servicio que no son un tramo suyo. No
         se descargan; la auditoría los revisa. -->
    <p v-if="camino.residuales.value.length" class="cromo-camino__nota">
      {{ camino.residuales.value.length }} caminos residuales (no se descargan)
      <template v-if="esAdmin && servicioId !== null">
        ·
        <RouterLink
          class="cromo-camino__link"
          :to="{ path: '/admin/servicios/viewer/Huerfanos', query: { servicio: String(servicioId) } }"
        >
          revisar en Huérfanos
        </RouterLink>
      </template>
    </p>

    <!-- Pelos del Servicio en casos de inconsistencias de Cromo: en cuarentena no cuentan como uso;
         en revisión siguen contando hasta que un admin decida. -->
    <p
      v-if="camino.inconsistencias.value.cuarentena || camino.inconsistencias.value.en_revision"
      class="cromo-camino__nota cromo-camino__aviso"
    >
      <i class="ph ph-warning" aria-hidden="true"></i>
      <template v-if="camino.inconsistencias.value.cuarentena">
        {{ camino.inconsistencias.value.cuarentena }} caso(s) de inconsistencias de Cromo en
        cuarentena: esos pelos no cuentan como uso del Servicio.
      </template>
      <template v-if="camino.inconsistencias.value.en_revision">
        {{ camino.inconsistencias.value.en_revision }} caso(s) en revisión.
      </template>
      <template v-if="esAdmin && servicioId !== null">
        <RouterLink
          class="cromo-camino__link"
          :to="{
            path: '/admin/servicios/viewer/InconsistenciasCromo',
            query: { servicio_id: String(servicioId) },
          }"
        >
          revisar en Inconsistencias
        </RouterLink>
      </template>
    </p>

    <details v-if="camino.excluidos.value.length" class="cromo-camino__excluidos">
      <summary class="cromo-camino__nota">
        {{ camino.excluidos.value.length }} pelo(s) excluidos del Servicio
      </summary>
      <ul class="cromo-camino__lista is-scroll">
        <li v-for="x in camino.excluidos.value" :key="x.pelo_n_id">
          <span>
            pelo {{ x.pelo_n_id }}
            <span class="cromo-camino__odf-meta">
              {{ [
                x.cable_nombre,
                [x.numero_pelo, x.color].filter(Boolean).join(' '),
                x.excluido_por,
                x.origen === 'AUDITORIA' ? `auditoría: ${x.motivo ?? ''}` : null,
              ]
                .filter(Boolean)
                .join(' · ') }}
            </span>
          </span>
          <button
            v-if="esAdmin && servicioId !== null"
            class="btn subtle"
            type="button"
            :disabled="camino.peloEnExclusion.value !== null"
            @click="camino.restaurarPelo(servicioId, x.pelo_n_id)"
          >
            {{ camino.peloEnExclusion.value === x.pelo_n_id ? 'Restaurando…' : 'Restaurar' }}
          </button>
        </li>
      </ul>
    </details>
    <p v-if="camino.errorExclusion.value" class="cromo-camino__error">
      {{ camino.errorExclusion.value }}
    </p>

    <CromoPeloSelector
      v-if="camino.tieneSemilla.value"
      :pelos="camino.pelos.value"
      :model-value="camino.peloElegido.value"
      :seleccionados="camino.pelosSeleccionados.value"
      :total-matcheados="camino.totalMatcheados.value"
      :disabled="camino.resolviendo.value || camino.descargando.value"
      @update:model-value="camino.peloElegido.value = $event"
      @alternar="camino.alternarPelo($event)"
      @seleccionar-todos="camino.seleccionarTodos()"
      @limpiar-seleccion="camino.limpiarSeleccion()"
    />

    <!-- Espera honesta: sin progreso del servidor, el único progreso real es el tiempo. -->
    <div
      v-if="camino.resolviendo.value"
      class="cromo-camino__esperando"
      aria-live="polite"
      aria-busy="true"
    >
      <i class="ph ph-circle-notch cromo-camino__spin" aria-hidden="true"></i>
      <span>Resolviendo camino en Cromo… {{ camino.segundos.value }} s</span>
      <button class="btn subtle" type="button" @click="camino.cancelar()">Cancelar</button>
      <p v-if="camino.avisoLento.value" class="cromo-camino__nota">
        Cromo resuelve el grafo en memoria; un camino largo puede tardar más. Podés cancelar y
        seguir sin él: el camino es una señal, no un requisito.
      </p>
    </div>

    <p v-else-if="camino.cancelado.value" class="cromo-camino__nota">
      Cancelaste la resolución.
    </p>
    <p v-else-if="camino.errorPath.value" class="cromo-camino__error">
      {{ camino.errorPath.value }}
    </p>

    <template v-else-if="camino.resultado.value">
      <p v-if="camino.resultado.value.estado !== 'OK'" class="cromo-camino__nota">
        {{ camino.resultado.value.motivo }}
      </p>

      <template v-else>
        <p class="cromo-camino__meta">
          {{ camino.resultado.value.estadisticas.nodos }} nodos ·
          {{ camino.resultado.value.estadisticas.cables }} cables ·
          {{ camino.resultado.value.estadisticas.odfs }} ODFs ·
          <!-- La red de acceso PON se cuenta aparte: un cable de bajada no es un tramo de la
               troncal y sumarlo distorsionaría la longitud óptica del backbone. -->
          <template v-if="camino.resultado.value.estadisticas.splitters">
            {{ camino.resultado.value.estadisticas.splitters }} splitters ·
          </template>
          <template v-if="camino.resultado.value.estadisticas.cajas_pon">
            {{ camino.resultado.value.estadisticas.cajas_pon }} cajas PON ·
          </template>
          <template v-if="camino.resultado.value.estadisticas.cables_bajada">
            {{ camino.resultado.value.estadisticas.cables_bajada }} bajadas ·
          </template>
          {{ Math.round(camino.resultado.value.estadisticas.longitud_optica_m) }} m ópticos ·
          pelo n_id {{ camino.resultado.value.pelo_n_id }}
          <template v-if="camino.resultado.value.servicio_at62">
            · at.62 <strong>{{ camino.resultado.value.servicio_at62 }}</strong>
          </template>
          <template v-if="camino.resultado.value.duracion_ms">
            · {{ (camino.resultado.value.duracion_ms / 1000).toFixed(1) }} s
          </template>
        </p>

        <p
          v-for="(aviso, i) in camino.resultado.value.advertencias"
          :key="i"
          class="cromo-camino__aviso"
        >
          <i class="ph ph-warning" aria-hidden="true"></i> {{ aviso }}
        </p>

        <!-- ODFs descubiertas: se ofrecen, no se aplican. -->
        <ul v-if="camino.resultado.value.odfs.length > 0" class="cromo-camino__odfs">
          <li v-for="odf in camino.resultado.value.odfs" :key="odf.odf_id">
            <span class="cromo-camino__odf-nombre">
              {{ odf.nombre || `ODF ${odf.odf_id}` }}
              <span class="cromo-camino__odf-meta">
                lado {{ odf.lado }}
                <template v-if="odf.patchera_nombre"> · {{ odf.patchera_nombre }}</template>
                <template v-if="odf.conector_numero"> · conector {{ odf.conector_numero }}</template>
              </span>
            </span>
            <!-- Qué se puede HACER con una ODF descubierta depende de quién muestre el
                 camino: el modal de asociación la trae al buscador, el detalle del Servicio sólo
                 la informa. El panel no decide por ellos. -->
            <slot name="odf-accion" :odf="odf"></slot>
          </li>
        </ul>

        <CromoConsistenciaPanel
          v-if="camino.resultado.value.consistencia"
          :consistencia="camino.resultado.value.consistencia"
          :puede-normalizar="esAdmin && servicioId !== null"
          :normalizando="camino.normalizando.value"
          :resumen="camino.resumenNormalizacion.value"
          :error="camino.errorNormalizar.value"
          @normalizar="normalizar"
        />

        <CromoPathSecuencia
          :nodos="[
            ...camino.resultado.value.lado_b.slice().reverse(),
            ...(camino.resultado.value.raiz ? [camino.resultado.value.raiz] : []),
            ...camino.resultado.value.lado_a,
          ]"
          :truncado="camino.resultado.value.ids_no_resueltos.length > 0"
        />
      </template>
    </template>
  </section>
</template>

<script setup lang="ts">
// El estado vive en el PADRE, no acá: tanto el modal de asociación (que persiste el
// `pelo_n_id` del camino resuelto al confirmar) como el detalle del Servicio (que descarga el
// .txt del pelo elegido) necesitan leerlo. El panel dibuja y dispara; no es dueño de nada.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';

import {
  type OdfConfirmada,
  type OdfDelCamino,
  type RolOdfConfirmada,
  etiquetaTramo,
} from '../../api/cromoPath';
import type { OdfDelTramo, useCromoPath } from '../../composables/useCromoPath';
import { useSession } from '../../composables/useSession';
import CromoConsistenciaPanel from './CromoConsistenciaPanel.vue';
import CromoPathSecuencia from './CromoPathSecuencia.vue';
import CromoPeloSelector from './CromoPeloSelector.vue';

const props = defineProps<{
  camino: ReturnType<typeof useCromoPath>;
  servicioId: number | null;
}>();

const { state: sesion } = useSession();
// Mismo criterio que el resto del SPA: el rol viaja en la sesión, no hay un `isAdmin` propio.
const esAdmin = computed(() => (sesion.value.role ?? '').toLowerCase() === 'admin');

// --- Botón único "Resolver caminos" con menú de acciones ---
const menuAbierto = ref(false);
const menuEl = ref<HTMLElement | null>(null);
const ocupado = computed(
  () =>
    props.camino.resolviendo.value ||
    props.camino.resolviendoCaminos.value ||
    props.camino.descargando.value,
);

/** Detalle nodo a nodo de un pelo: el de la fila del tramo, o el elegido en el selector. */
function detallePelo(peloNId: number | null): void {
  menuAbierto.value = false;
  if (props.servicioId === null) return;
  if (peloNId !== null) props.camino.peloElegido.value = peloNId;
  void props.camino.resolver(props.servicioId);
}

function cerrarMenuFuera(ev: MouseEvent): void {
  if (menuAbierto.value && menuEl.value && !menuEl.value.contains(ev.target as Node)) {
    menuAbierto.value = false;
  }
}
onMounted(() => document.addEventListener('click', cerrarMenuFuera));
onBeforeUnmount(() => document.removeEventListener('click', cerrarMenuFuera));

// Rol elegido a mano por ODF antes de confirmar; sin elección vale el sugerido (ODF en un extremo
// de camino → extremo; ODF Nodo o intermedia → tránsito).
const rolesElegidos = reactive<Record<number, RolOdfConfirmada>>({});
function rolDe(odf: OdfDelTramo): RolOdfConfirmada {
  return rolesElegidos[odf.odf_n_id] ?? odf.rolSugerido;
}
function rolLabel(rol: RolOdfConfirmada): string {
  return rol === 'TRANSITO' ? 'tránsito' : 'extremo';
}
/** La confirmación vigente de la ODF; el id del camino puede ser el de versión, no el de linaje. */
function confirmadaDe(odfNId: number): OdfConfirmada | undefined {
  return props.camino.odfConfirmadas.value.find((c) => c.odf_n_id === odfNId);
}

// Campo "Trackings esperados": vacío = sin declarar. Se re-sincroniza con lo que declara el Servicio.
const esperadosEditado = ref<string | number>('');
watch(
  () => props.camino.esperadosDeclarados.value,
  (valor) => {
    esperadosEditado.value = valor ?? '';
  },
  { immediate: true },
);
async function guardarEsperados(): Promise<void> {
  if (props.servicioId === null || !esAdmin.value) return;
  const texto = String(esperadosEditado.value).trim();
  const cantidad = texto === '' ? null : Number(texto);
  if (cantidad !== null && (!Number.isInteger(cantidad) || cantidad <= 0)) {
    esperadosEditado.value = props.camino.esperadosDeclarados.value ?? '';
    return;
  }
  const ok = await props.camino.declararEsperados(props.servicioId, cantidad);
  if (!ok) esperadosEditado.value = props.camino.esperadosDeclarados.value ?? '';
}

/** Normalizar escribe inventario, así que el panel sólo dispara: el servicio decide qué corregir. */
async function normalizar(elementoIds: number[] | null): Promise<void> {
  if (props.servicioId === null) return;
  await props.camino.normalizar(props.servicioId, elementoIds ?? undefined);
}

/** Releva las ODFs del camino para que aparezcan sus posiciones de patchera. */
async function relevarOdf(): Promise<void> {
  if (props.servicioId === null) return;
  await props.camino.relevarOdf(props.servicioId);
}

defineSlots<{
  'odf-accion'(props: { odf: OdfDelCamino }): unknown;
}>();
</script>

<style scoped>
.cromo-camino {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cromo-camino__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.cromo-camino__accion {
  position: relative;
  display: inline-flex;
}

.cromo-camino__accion-principal {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}

.cromo-camino__accion-menu {
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
  border-left: 1px solid var(--color-divider);
  padding-inline: 6px;
}

.cromo-camino__menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 20;
  min-width: 220px;
  margin: 0;
  padding: 4px 0;
  list-style: none;
  background: var(--color-surface);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-md);
}

.cromo-camino__menu button {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 8px 12px;
  border: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
  font-size: 12.5px;
  text-align: left;
  cursor: pointer;
}

.cromo-camino__menu button:hover,
.cromo-camino__menu button:focus-visible {
  background: color-mix(in srgb, var(--color-text) 7%, transparent);
}

.cromo-camino__titulo {
  margin: 0;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.cromo-camino__nota {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.45;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.cromo-camino__aviso {
  color: var(--color-state-warn);
}

.cromo-camino__link {
  color: var(--color-accent-200);
  text-decoration: none;
}

.cromo-camino__link:hover { text-decoration: underline; }

.cromo-camino__error {
  margin: 0;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  font-size: 11.5px;
  background: color-mix(in srgb, var(--color-state-error) 14%, transparent);
  color: var(--color-state-error);
}

.cromo-camino__aviso {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 0;
  font-size: 11.5px;
  color: var(--color-state-warn);
}

.cromo-camino__esperando {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 9px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
  font-size: 12px;
}

/* Reusa el `@keyframes spin` global de tokens.css en vez de definir uno local. */
.cromo-camino__spin {
  animation: spin 1s linear infinite;
}

.cromo-camino__meta {
  margin: 0;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
}

.cromo-camino__odfs {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.cromo-camino__odfs li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-accent) 8%, transparent);
}

.cromo-camino__caminos {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.cromo-camino__declaracion {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cromo-camino__esperados {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cromo-camino__input {
  width: 110px;
  padding: 3px 6px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: 12px;
}

.cromo-camino__acciones {
  display: flex;
  align-items: center;
  gap: 6px;
}

.cromo-camino__confirmada {
  margin-left: 6px;
  font-size: 10.5px;
  color: var(--color-state-ok);
}

.cromo-camino__lista {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.cromo-camino__lista.is-scroll {
  max-height: 220px;
  overflow-y: auto;
}

.cromo-camino__lista li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-accent) 8%, transparent);
  font-size: 12px;
}

.cromo-camino__excluidos {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cromo-camino__excluidos summary {
  cursor: pointer;
}

.cromo-camino__odf-nombre {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  font-size: 12.5px;
}

.cromo-camino__odf-meta {
  font-size: 10.5px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}


.cromo-camino__aviso {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 0;
  padding: 7px 9px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-state-warn) 12%, transparent);
  color: color-mix(in srgb, var(--color-text) 80%, transparent);
  font-size: 11.5px;
  line-height: 1.45;
}
</style>
