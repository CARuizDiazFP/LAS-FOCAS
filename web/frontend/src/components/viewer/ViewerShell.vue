<!--
  Nombre de archivo: ViewerShell.vue
  Ubicación de archivo: web/frontend/src/components/viewer/ViewerShell.vue
  Descripción: Armazón común de los viewers paginados — toolbar, error inline, contenedor de scroll con estados (vacío, cargando más, carga inicial) y sentinel con IntersectionObserver que emite `cargar-mas`
-->
<template>
  <section :class="['viewer-shell', bloque]">
    <slot name="toolbar" />

    <div v-if="error && errorInline" class="viewer-shell__inline-error">{{ error }}</div>

    <slot name="avisos" />

    <div ref="scrollEl" class="viewer-shell__scroll">
      <slot v-if="!vacio" />

      <div v-else-if="!loading" class="viewer-shell__state-box" :style="estiloCaja">
        <i :class="['ph', iconoVacio]" aria-hidden="true"></i>
        <h3>{{ textoVacio }}</h3>
        <slot name="vacio" />
      </div>

      <div v-if="loading && (!vacio || cargaInicial === 'fila')" class="viewer-shell__loading-more">
        <i class="ph ph-circle-notch viewer-shell__spin" aria-hidden="true"></i>
        {{ textoCargando }}
      </div>

      <div v-if="loading && vacio && cargaInicial === 'caja'" class="viewer-shell__state-box" :style="estiloCaja">
        <i class="ph ph-circle-notch viewer-shell__spin" aria-hidden="true"></i>
        <h3 v-if="textoCargaInicial">{{ textoCargaInicial }}</h3>
      </div>

      <slot name="pie" />

      <div v-if="scrollInfinito" ref="sentinel" class="viewer-shell__sentinel" aria-hidden="true"></div>
    </div>

    <slot name="extra" />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    /** Clase BEM del viewer: va en la raíz junto a `viewer-shell` y cuelga sus reglas propias. */
    bloque: string;
    loading: boolean;
    error: string;
    /** Sin items: muestra el estado vacío (o el de carga inicial) en lugar del slot default. */
    vacio: boolean;
    hayMas: boolean;
    /** Título del estado vacío; el slot `vacio` agrega lo que va debajo (texto, botón). */
    textoVacio: string;
    /** Texto de la fila "cargando más". */
    textoCargando: string;
    /** Sentinel + IntersectionObserver. En false no hay sentinel (viewers con botón "Cargar más"). */
    scrollInfinito?: boolean;
    /** Ícono Phosphor del estado vacío. */
    iconoVacio?: string;
    /** Qué se ve mientras carga sin items: nada, la caja de estado con `textoCargaInicial` o la
     * misma fila de "cargando más". */
    cargaInicial?: 'nada' | 'caja' | 'fila';
    /** Título de la caja de carga inicial; si falta, la caja muestra sólo el spinner. */
    textoCargaInicial?: string;
    /** Si es false no se pinta el error inline (el viewer muestra el suyo), pero `error` sigue
     * siendo el error real: la re-medición del sentinel lo usa para no reintentar en loop. */
    errorInline?: boolean;
    /** `max-width` de la caja de estado (p. ej. `260px`); si falta, sin tope. */
    anchoEstado?: string;
  }>(),
  {
    scrollInfinito: true,
    iconoVacio: 'ph-magnifying-glass',
    cargaInicial: 'nada',
    textoCargaInicial: '',
    anchoEstado: undefined,
    errorInline: true,
  },
);

const estiloCaja = computed(() => (props.anchoEstado ? { maxWidth: props.anchoEstado } : undefined));

const emit = defineEmits<{
  'cargar-mas': [];
}>();

const scrollEl = ref<HTMLElement | null>(null);
const sentinel = ref<HTMLElement | null>(null);

let observer: IntersectionObserver | null = null;

function observarDeNuevo(el: HTMLElement): void {
  // `observe` sobre un target recién des-observado entrega una medición inicial, aunque la
  // intersección no haya cambiado.
  observer?.unobserve(el);
  observer?.observe(el);
}

onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting && props.hayMas && !props.loading) emit('cargar-mas');
      }
    },
    { root: scrollEl.value, rootMargin: '300px 0px', threshold: 0.1 },
  );
  if (sentinel.value) observer.observe(sentinel.value);
});

// El sentinel entra y sale con `scrollInfinito` (p. ej. un modo del viewer sin paginación).
watch(
  sentinel,
  (nuevo, viejo) => {
    if (!observer) return;
    if (viejo) observer.unobserve(viejo);
    if (nuevo) observer.observe(nuevo);
  },
  { flush: 'post' },
);

// El observer se crea antes de la primera carga y sólo avisa cuando la intersección cambia: si al
// terminar una página el sentinel sigue a la vista (la lista no llena el scroll), nadie pediría la
// siguiente. Se vuelve a medir tras cada carga sin error; con error no, para no reintentar en loop.
watch(
  () => props.loading,
  (ahora, antes) => {
    if (antes && !ahora && !props.error && sentinel.value) observarDeNuevo(sentinel.value);
  },
  { flush: 'post' },
);

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
});

defineExpose({ scrollEl });
</script>

<style scoped>
.viewer-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.viewer-shell__inline-error {
  margin-bottom: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-state-error) 14%, transparent);
  color: var(--color-state-error);
  font-size: 12.5px;
}

.viewer-shell__scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.viewer-shell__state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  margin: 34px auto;
  padding: 34px 22px;
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-neutral-800);
  text-align: center;
}
.viewer-shell__state-box i { font-size: 26px; color: var(--color-neutral-600); margin-bottom: 4px; }
.viewer-shell__state-box h3 { font-size: 15px; font-weight: 500; margin: 0; }
.viewer-shell__state-box :slotted(p) {
  font-size: 12.5px;
  line-height: 1.5;
  margin: 0;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.viewer-shell__loading-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.viewer-shell__spin { font-size: 14px; animation: spin 1s linear infinite; }
.viewer-shell__sentinel { height: 2px; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
