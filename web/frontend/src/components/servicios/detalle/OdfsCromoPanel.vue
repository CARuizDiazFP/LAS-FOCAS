<!--
  Nombre de archivo: OdfsCromoPanel.vue
  Ubicación de archivo: web/frontend/src/components/servicios/detalle/OdfsCromoPanel.vue
  Descripción: ODFs de un Servicio según lo ingerido de Cromo — canal por defecto del Detalle de
  Servicio, con el origen de cada resolución rotulado
-->
<template>
  <section class="odfs-cromo" aria-label="ODFs asociadas">
    <header class="odfs-cromo__head">
      <h4 class="odfs-cromo__titulo">ODFs asociadas</h4>
      <span v-if="!cargando && !error" class="odfs-cromo__chip">{{ odfs.length }} ODF(s)</span>
    </header>

    <p class="odfs-cromo__fuente">Según lo ingerido de Cromo, la fuente de verdad del Servicio.</p>

    <p v-if="cargando" class="odfs-cromo__nota">Cargando ODFs…</p>
    <p v-else-if="error" class="odfs-cromo__nota is-error">{{ error }}</p>

    <!-- Vacío no es un error: es el caso en que hay que ir al segundo canal. El panel de Cromo de
         abajo tiene el botón que consulta en vivo, así que se apunta ahí en vez de dejar al
         operador sin siguiente paso. -->
    <p v-else-if="odfs.length === 0" class="odfs-cromo__nota">
      Cromo no resuelve ninguna ODF para este Servicio con lo ingerido. Probá
      <strong>Resolver camino</strong> acá abajo, que consulta Cromo en vivo.
    </p>

    <ul v-else class="odfs-cromo__lista">
      <li v-for="odf in odfs" :key="odf.odf_n_id" class="odfs-cromo__item">
        <div class="odfs-cromo__item-main">
          <RouterLink class="odfs-cromo__link" :to="`/infra/cromo/odfs/ID${odf.odf_n_id}`">
            {{ odf.nombre || `ODF ${odf.odf_n_id}` }}
          </RouterLink>
          <span :class="['odfs-cromo__origen', `is-${odf.origen}`]" :title="tituloOrigen(odf.origen)">
            {{ etiquetaOrigen(odf.origen) }}
          </span>
        </div>
        <p v-if="domicilio(odf)" class="odfs-cromo__domicilio">{{ domicilio(odf) }}</p>
        <p class="odfs-cromo__conteo">{{ conteo(odf) }}</p>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { RouterLink } from 'vue-router';

import {
  type CromoOdfDeServicio,
  getOdfsCromoServicio,
} from '../../../api/servicioSecciones';

const props = defineProps<{
  /** PK interna del Servicio (no el ID de origen): es lo que pide este endpoint. */
  servicioId: number | null;
}>();

const cargando = ref(false);
const error = ref('');
const odfs = ref<CromoOdfDeServicio[]>([]);

const ETIQUETAS: Record<CromoOdfDeServicio['origen'], string> = {
  servicio_resuelto: 'Resuelta',
  pelo: 'Por pelo',
  override_manual: 'Manual',
};

// El tooltip del caso `pelo` es lo que evita que las dos pantallas parezcan contradecirse: la ODF
// es real, pero el gestor de Servicios sin ODF no la cuenta porque su definición canónica mira
// sólo `servicio_resuelto`.
const TITULOS: Record<CromoOdfDeServicio['origen'], string> = {
  servicio_resuelto: 'El conector de la ODF declara este Servicio: es la resolución canónica.',
  pelo: 'Se llega por un pelo matcheado, no por el conector. El gestor de Servicios sin ODF no la cuenta como resuelta.',
  override_manual: 'Asociación confirmada a mano por un operador desde el gestor de Servicios sin ODF.',
};

function etiquetaOrigen(origen: CromoOdfDeServicio['origen']): string {
  return ETIQUETAS[origen] ?? origen;
}

function tituloOrigen(origen: CromoOdfDeServicio['origen']): string {
  return TITULOS[origen] ?? '';
}

function domicilio(odf: CromoOdfDeServicio): string {
  return [[odf.calle, odf.altura].filter(Boolean).join(' '), odf.localidad]
    .filter(Boolean)
    .join(', ');
}

function conteo(odf: CromoOdfDeServicio): string {
  const partes = [odf.conectores === 1 ? '1 conector' : `${odf.conectores} conectores`];
  // Un override manual no pasa por ningún conector, así que sus dos contadores son 0 y mostrarlos
  // sólo confundiría.
  if (odf.origen === 'override_manual') return 'Asociada a mano, sin conector resuelto';
  if (odf.pelos > 0) partes.push(odf.pelos === 1 ? '1 pelo' : `${odf.pelos} pelos`);
  return partes.join(' · ');
}

async function cargar(servicioId: number | null): Promise<void> {
  odfs.value = [];
  error.value = '';
  if (servicioId == null) return;

  cargando.value = true;
  try {
    const data = await getOdfsCromoServicio(servicioId);
    odfs.value = data.odfs ?? [];
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudieron cargar las ODFs de Cromo';
  } finally {
    cargando.value = false;
  }
}

watch(() => props.servicioId, cargar, { immediate: true });
</script>

<style scoped>
.odfs-cromo {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.odfs-cromo__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.odfs-cromo__titulo {
  margin: 0;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.odfs-cromo__chip {
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 10.5px;
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.odfs-cromo__fuente,
.odfs-cromo__nota {
  margin: 0;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.odfs-cromo__nota.is-error {
  color: var(--color-state-error);
}

.odfs-cromo__lista {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.odfs-cromo__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
}

.odfs-cromo__item-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.odfs-cromo__link {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-accent);
}

.odfs-cromo__origen {
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 10px;
  border: 1px solid var(--color-divider);
  color: color-mix(in srgb, var(--color-text) 65%, transparent);
}

.odfs-cromo__origen.is-servicio_resuelto {
  border-color: var(--color-state-ok);
  color: var(--color-state-ok);
}

.odfs-cromo__origen.is-pelo {
  border-color: var(--color-state-warn);
  color: var(--color-state-warn);
}

.odfs-cromo__origen.is-override_manual {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.odfs-cromo__domicilio,
.odfs-cromo__conteo {
  margin: 0;
  font-size: 11px;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}
</style>
