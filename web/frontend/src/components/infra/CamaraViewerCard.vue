<!--
  Nombre de archivo: CamaraViewerCard.vue
  Ubicación de archivo: web/frontend/src/components/infra/CamaraViewerCard.vue
  Descripción: Tarjeta mínima de Cámara (estado, botellas, cables) — reusada en el grid del listado general y en cada miembro de una tarjeta de grupo de duplicados
-->
<template>
  <article class="camara-viewer-card" role="button" tabindex="0" @click="goToDetail" @keyup.enter="goToDetail">
    <div class="camara-viewer-card__row">
      <span :class="['camara-viewer-card__dot', `is-${estadoToken}`]" :title="camara.estado" aria-hidden="true"></span>
      <span class="camara-viewer-card__estado">{{ camara.estado }}</span>
      <i class="ph ph-arrow-up-right camara-viewer-card__arrow" aria-hidden="true"></i>
    </div>

    <h3 class="camara-viewer-card__name">{{ camara.nombre || `Cámara ${camara.id}` }}</h3>

    <div class="camara-viewer-card__hairline"></div>

    <div class="camara-viewer-card__row">
      <span class="camara-viewer-card__stat">{{ camara.botellas_count }} botella{{ camara.botellas_count !== 1 ? 's' : '' }}</span>
      <span class="camara-viewer-card__stat">{{ camara.cables_count }} cable{{ camara.cables_count !== 1 ? 's' : '' }}</span>

      <button
        v-if="mostrarFusionar"
        class="btn subtle camara-viewer-card__fusionar"
        type="button"
        @click.stop="$emit('fusionar', camara)"
      >
        Fusionar
      </button>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';

import { estadoCamaraToken, type CamaraViewerItem } from '../../api/camaras';

const props = defineProps<{
  camara: CamaraViewerItem;
  mostrarFusionar?: boolean;
}>();

defineEmits<{
  fusionar: [camara: CamaraViewerItem];
}>();

const router = useRouter();
const estadoToken = computed(() => estadoCamaraToken(props.camara.estado));

function goToDetail(): void {
  void router.push(`/infra/Camaras/${props.camara.id}`);
}
</script>

<style scoped>
.camara-viewer-card {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 12px 13px 11px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  overflow: hidden;
  transition: box-shadow 0.15s ease;
}

.camara-viewer-card:hover,
.camara-viewer-card:focus-visible {
  box-shadow: 0 0 0 1px var(--color-accent), 0 6px 18px rgba(0, 0, 0, 0.5);
}

.camara-viewer-card__row {
  display: flex;
  align-items: center;
  gap: 7px;
}

.camara-viewer-card__dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--color-state-idle);
}

.camara-viewer-card__dot.is-ok { background: var(--color-state-ok); }
.camara-viewer-card__dot.is-warn { background: var(--color-state-warn); }
.camara-viewer-card__dot.is-error { background: var(--color-state-error); }
.camara-viewer-card__dot.is-idle { background: var(--color-state-idle); }

.camara-viewer-card__estado {
  font-size: 10px;
  letter-spacing: 0.08em;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.camara-viewer-card__arrow {
  margin-left: auto;
  font-size: 13px;
  color: var(--color-neutral-600);
}

.camara-viewer-card__name {
  margin: 0;
  min-height: 36px;
  font-size: 14.5px;
  font-weight: 500;
  line-height: 1.25;
  letter-spacing: -0.005em;
  text-wrap: pretty;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.camara-viewer-card__hairline {
  height: 1px;
  background: var(--color-divider);
}

.camara-viewer-card__stat {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.camara-viewer-card__fusionar {
  margin-left: auto;
  padding: 3px 9px;
  font-size: 11px;
}
</style>
