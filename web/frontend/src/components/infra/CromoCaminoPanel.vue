<!--
  Nombre de archivo: CromoCaminoPanel.vue
  Ubicación de archivo: web/frontend/src/components/infra/CromoCaminoPanel.vue
  Descripción: Panel reutilizable del camino óptico de Cromo — semillas, resolución cancelable, estadísticas, auditoría de consistencia y secuencia de nodos
-->
<template>
  <section class="cromo-camino">
    <header class="cromo-camino__head">
      <h4 class="cromo-camino__titulo">Camino óptico en Cromo</h4>
      <button
        v-if="camino.tieneSemilla.value"
        class="btn subtle"
        type="button"
        :disabled="camino.resolviendo.value"
        @click="servicioId != null && camino.resolver(servicioId)"
      >
        <i class="ph ph-tree-structure" aria-hidden="true"></i>
        {{ camino.resultado.value ? 'Resolver de nuevo' : 'Resolver camino' }}
      </button>
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
      <p class="cromo-camino__nota">
        <template v-if="camino.caminosEsperados.value">
          Caminos esperados: <strong>{{ camino.caminosEsperados.value }}</strong>
          (pelos del Servicio por cable u ODF)
        </template>
        <template v-if="camino.caminosResueltos.value">
          · resueltos: <strong>{{ camino.caminos.value.length }}</strong>
        </template>
      </p>
      <button
        v-if="servicioId !== null"
        class="btn subtle"
        type="button"
        :disabled="camino.resolviendoCaminos.value || camino.descargando.value"
        title="Resuelve en Cromo un camino por hilo del Servicio y detecta los pelos huérfanos"
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
    </div>
    <p v-if="camino.errorCaminos.value" class="cromo-camino__error">
      {{ camino.errorCaminos.value }}
    </p>
    <ul v-if="camino.caminos.value.length" class="cromo-camino__lista">
      <li v-for="(c, i) in camino.caminos.value" :key="c.pelo_n_id">
        <span>
          Camino {{ i + 1 }} · pelo {{ c.pelo_n_id }}
          <span class="cromo-camino__odf-meta">
            {{ c.pelos_en_camino }} pelos recorridos{{ c.desde_cache ? ' · en caché' : '' }}
          </span>
        </span>
      </li>
    </ul>

    <!-- Huérfanos: tienen la etiqueta del Servicio pero no están en ninguno de sus caminos (un
         pelo que se movió y quedó con la etiqueta vieja). No generan tracking; un admin los saca
         del Servicio en local para que no ensucien las próximas consultas. -->
    <div v-if="camino.huerfanos.value.length" class="cromo-camino__huerfanos">
      <p class="cromo-camino__aviso">
        <i class="ph ph-link-break" aria-hidden="true"></i>
        <span>
          {{ camino.huerfanos.value.length }} pelo(s) con la etiqueta del Servicio no están en
          ninguno de sus caminos. No generan tracking.
          <template v-if="!esAdmin">Un admin puede excluirlos del Servicio.</template>
        </span>
        <button
          v-if="esAdmin && servicioId !== null && camino.huerfanos.value.length > 1"
          class="btn subtle"
          type="button"
          :disabled="camino.peloEnExclusion.value !== null"
          @click="excluirTodos"
        >
          {{ camino.peloEnExclusion.value === -1 ? 'Excluyendo…' : 'Excluir todos' }}
        </button>
      </p>
      <ul class="cromo-camino__lista is-scroll">
        <li v-for="p in camino.huerfanos.value" :key="p.pelo_n_id">
          <span>
            pelo {{ p.pelo_n_id }}
            <span class="cromo-camino__odf-meta">
              {{ [p.cable_nombre, [p.numero_pelo, p.color].filter(Boolean).join(' ')]
                .filter(Boolean)
                .join(' · ') }}
            </span>
          </span>
          <button
            v-if="esAdmin && servicioId !== null"
            class="btn subtle"
            type="button"
            :disabled="camino.peloEnExclusion.value !== null"
            title="Saca el pelo del Servicio en LAS-FOCAS. Cromo no se toca; se puede restaurar."
            @click="camino.excluirPelos(servicioId, [p.pelo_n_id])"
          >
            {{ camino.peloEnExclusion.value === p.pelo_n_id ? 'Excluyendo…' : 'Excluir del Servicio' }}
          </button>
        </li>
      </ul>
    </div>

    <details v-if="camino.excluidos.value.length" class="cromo-camino__excluidos">
      <summary class="cromo-camino__nota">
        {{ camino.excluidos.value.length }} pelo(s) excluidos del Servicio
      </summary>
      <ul class="cromo-camino__lista is-scroll">
        <li v-for="x in camino.excluidos.value" :key="x.pelo_n_id">
          <span>
            pelo {{ x.pelo_n_id }}
            <span class="cromo-camino__odf-meta">
              {{ [x.cable_nombre, [x.numero_pelo, x.color].filter(Boolean).join(' '), x.excluido_por]
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
import { computed } from 'vue';

import type { OdfDelCamino } from '../../api/cromoPath';
import type { useCromoPath } from '../../composables/useCromoPath';
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

/** Normalizar escribe inventario, así que el panel sólo dispara: el servicio decide qué corregir. */
async function normalizar(elementoIds: number[] | null): Promise<void> {
  if (props.servicioId === null) return;
  await props.camino.normalizar(props.servicioId, elementoIds ?? undefined);
}

/** Excluir en lote escribe sobre decenas de pelos: se confirma antes. Es reversible (Restaurar). */
async function excluirTodos(): Promise<void> {
  if (props.servicioId === null) return;
  const pelos = props.camino.huerfanos.value.map((p) => p.pelo_n_id);
  const ok = window.confirm(
    `Se van a excluir ${pelos.length} pelos huérfanos de este Servicio. Cromo no se toca y se ` +
      'pueden restaurar de a uno. ¿Continuar?',
  );
  if (!ok) return;
  await props.camino.excluirPelos(props.servicioId, pelos);
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

.cromo-camino__huerfanos,
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
