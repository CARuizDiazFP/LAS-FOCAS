<!--
  Nombre de archivo: AdminClientesCategoria.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminClientesCategoria.vue
  Descripción: Vista /admin/servicios/clientes-categoria — clientes agrupados por categoría (C6→C0, sin categorizar) con cambio individual y masivo, lista oficial, alias y fusión
-->
<template>
  <AdminPageHeader
    kicker="Panel admin · Servicios"
    title="Clientes por categoría"
    subtitle="La categoría se define por cliente y se propaga a todos sus servicios (salvo excepciones)."
  />

  <div class="clientes-toolbar">
    <input
      v-model="busqueda"
      class="clientes-toolbar__buscar"
      type="search"
      placeholder="Buscar por nombre o alias"
      aria-label="Buscar cliente por nombre o alias"
    />
    <div class="clientes-toolbar__acciones">
      <button class="btn primary" type="button" @click="listaOpen = true">Cargar lista</button>
      <button class="btn subtle" type="button" :disabled="sincronizando" @click="resincronizar">
        {{ sincronizando ? 'Sincronizando...' : 'Re-sincronizar' }}
      </button>
    </div>
  </div>

  <p v-if="mensaje" class="clientes-mensaje">{{ mensaje }}</p>
  <p v-if="error" class="clientes-mensaje is-error">{{ error }}</p>

  <div v-if="grupos" class="clientes-resumen" aria-label="Clientes por grupo">
    <span
      v-for="clave in ORDEN_GRUPOS_CLIENTES"
      :key="clave"
      :class="['clientes-resumen__chip', { 'is-sin': clave === 'sin' }]"
    >
      <strong>{{ etiquetaGrupo(clave) }}</strong> {{ grupos[clave].length }}
    </span>
  </div>

  <p v-if="cargando && !grupos" class="clientes-vacio">Cargando clientes...</p>

  <div v-if="grupos" class="clientes-grupos">
    <AccordionItem
      v-for="clave in ORDEN_GRUPOS_CLIENTES"
      :key="clave"
      :model-value="abiertos[clave] ?? false"
      :title="etiquetaGrupo(clave)"
      :description="busquedaNormalizada ? `${visibles[clave].length} coincidencia(s)` : undefined"
      @update:model-value="abiertos[clave] = $event"
    >
      <template #meta>
        <span :class="['clientes-grupo__count', { 'is-sin': clave === 'sin' }]">
          {{ grupos[clave].length }} cliente{{ grupos[clave].length !== 1 ? 's' : '' }}
        </span>
      </template>

      <p v-if="visibles[clave].length === 0" class="clientes-vacio">
        {{ busquedaNormalizada ? 'Sin coincidencias en este grupo.' : 'No hay clientes en este grupo.' }}
      </p>
      <ul v-else class="clientes-lista">
        <li v-for="cliente in visibles[clave]" :key="cliente.id" class="clientes-fila">
          <input
            type="checkbox"
            class="clientes-fila__check"
            :checked="seleccionados.has(cliente.id)"
            :aria-label="`Seleccionar ${cliente.nombre}`"
            @change="toggleSeleccion(cliente.id)"
          />

          <div class="clientes-fila__info">
            <div class="clientes-fila__titulo">
              <span class="clientes-fila__nombre">{{ cliente.nombre }}</span>
              <span :class="['clientes-badge', `is-${cliente.origen_categoria.toLowerCase()}`]">
                {{ etiquetaOrigen(cliente.origen_categoria) }}
              </span>
              <span v-if="cliente.a_revisar" class="clientes-badge is-revisar">A revisar</span>
            </div>
            <div class="clientes-fila__meta">
              <span>{{ cliente.servicios }} servicio{{ cliente.servicios !== 1 ? 's' : '' }}</span>
              <span v-if="cliente.excepciones > 0">
                · {{ cliente.excepciones }} excepción{{ cliente.excepciones !== 1 ? 'es' : '' }}
              </span>
              <details v-if="cliente.alias.length > 1" class="clientes-fila__alias">
                <summary>{{ cliente.alias.length }} alias</summary>
                <ul>
                  <li v-for="alias in cliente.alias" :key="alias.id">{{ alias.nombre_original }}</li>
                </ul>
              </details>
              <button class="clientes-fila__link" type="button" @click="abrirAlias(cliente.id)">Gestionar alias</button>
            </div>
          </div>

          <select
            class="clientes-fila__select"
            :value="valorSelect(cliente)"
            :disabled="guardandoFila !== null"
            :aria-label="`Categoría de ${cliente.nombre}`"
            @change="cambiarFila(cliente, ($event.target as HTMLSelectElement).value)"
          >
            <option v-for="opcion in ORDEN_GRUPOS_CLIENTES" :key="opcion" :value="opcion">{{ etiquetaGrupo(opcion) }}</option>
            <option value="auto">
              Automático{{ esAutomatico(cliente) ? ` (${etiquetaCategoria(cliente.categoria)})` : '' }}
            </option>
          </select>
        </li>
      </ul>
    </AccordionItem>
  </div>

  <!-- Barra de acciones masivas flotante -->
  <div v-if="seleccionados.size > 0" class="clientes-bulk" role="toolbar" aria-label="Acciones masivas de clientes">
    <span class="clientes-bulk__count">{{ seleccionados.size }} seleccionado{{ seleccionados.size !== 1 ? 's' : '' }}</span>
    <select v-model="categoriaMasiva" class="clientes-fila__select" aria-label="Categoría destino">
      <option v-for="opcion in ORDEN_GRUPOS_CLIENTES" :key="opcion" :value="opcion">{{ etiquetaGrupo(opcion) }}</option>
    </select>
    <button class="btn primary" type="button" @click="abrirConfirmacion('categoria')">Cambiar categoría</button>
    <button class="btn subtle" type="button" @click="abrirConfirmacion('automatico')">Volver a automático</button>
    <button
      class="btn subtle"
      type="button"
      :disabled="seleccionados.size < 2"
      :title="seleccionados.size < 2 ? 'Seleccioná al menos dos clientes' : ''"
      @click="abrirFusion"
    >
      Fusionar
    </button>
    <button class="btn subtle" type="button" @click="limpiarSeleccion">Deseleccionar todo</button>
  </div>

  <ModalConfirmarAccionMasiva
    :open="confirmOpen"
    :titulo="accionPendiente === 'automatico' ? 'Volver a automático' : 'Cambiar categoría'"
    :mensaje="mensajeConfirmacion"
    :confirmando="confirmando"
    :error="errorConfirmacion"
    :resultado="resultadoConfirmacion"
    @close="confirmOpen = false"
    @confirm="confirmarAccionMasiva"
  />

  <ClientesListaModal :open="listaOpen" @close="listaOpen = false" @cambiado="cargar" />
  <ClienteAliasModal :open="aliasClienteId !== null" :cliente="clienteAlias" @close="aliasClienteId = null" @cambiado="cargar" />
  <ClientesFusionarModal
    :open="fusionOpen"
    :clientes="clientesFusion"
    @close="fusionOpen = false"
    @fusionado="onFusionado"
  />
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';

import AccordionItem from '../../components/infra/AccordionItem.vue';
import ModalConfirmarAccionMasiva from '../../components/infra/ModalConfirmarAccionMasiva.vue';
import {
  ORDEN_GRUPOS_CLIENTES,
  cambiarCategoriaClientes,
  etiquetaGrupo,
  etiquetaOrigen,
  getClientesPorCategoria,
  sincronizarClientes,
  type ClaveGrupoCliente,
  type ClienteCategoria,
} from '../api/clientesCategoria';
import AdminPageHeader from '../components/AdminPageHeader.vue';
import ClienteAliasModal from '../components/clientes/ClienteAliasModal.vue';
import ClientesFusionarModal from '../components/clientes/ClientesFusionarModal.vue';
import ClientesListaModal from '../components/clientes/ClientesListaModal.vue';

type Grupos = Record<ClaveGrupoCliente, ClienteCategoria[]>;

const grupos = ref<Grupos | null>(null);
const cargando = ref(false);
const error = ref('');
const mensaje = ref('');
const busqueda = ref('');
const abiertos = ref<Partial<Record<ClaveGrupoCliente, boolean>>>({ '6': true });

const seleccionados = ref<Set<number>>(new Set());
const categoriaMasiva = ref<ClaveGrupoCliente>('6');
const guardandoFila = ref<number | null>(null);
const sincronizando = ref(false);

const confirmOpen = ref(false);
const accionPendiente = ref<'categoria' | 'automatico'>('categoria');
// Cantidad seleccionada al abrir el modal: tras aplicar se limpia la selección y el mensaje no
// debe pasar a decir "0 clientes" mientras se muestra el resultado.
const cantidadConfirmacion = ref(0);
const confirmando = ref(false);
const errorConfirmacion = ref('');
const resultadoConfirmacion = ref<string | null>(null);

const listaOpen = ref(false);
const aliasClienteId = ref<number | null>(null);
const fusionOpen = ref(false);
const clientesFusion = ref<ClienteCategoria[]>([]);

function normalizar(valor: string): string {
  return valor
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim();
}

const busquedaNormalizada = computed(() => normalizar(busqueda.value));

function compararNombres(a: ClienteCategoria, b: ClienteCategoria): number {
  return a.nombre.localeCompare(b.nombre, 'es', { sensitivity: 'base' });
}

function coincide(cliente: ClienteCategoria, termino: string): boolean {
  if (normalizar(cliente.nombre).includes(termino)) return true;
  return cliente.alias.some((alias) => normalizar(alias.nombre_original).includes(termino));
}

/** Filas visibles por grupo: filtradas por la búsqueda y ordenadas alfabéticamente. */
const visibles = computed<Grupos>(() => {
  const resultado = {} as Grupos;
  const termino = busquedaNormalizada.value;
  for (const clave of ORDEN_GRUPOS_CLIENTES) {
    const lista = grupos.value?.[clave] ?? [];
    resultado[clave] = (termino ? lista.filter((c) => coincide(c, termino)) : [...lista]).sort(compararNombres);
  }
  return resultado;
});

const clientesPorId = computed(() => {
  const mapa = new Map<number, ClienteCategoria>();
  for (const clave of ORDEN_GRUPOS_CLIENTES) {
    for (const cliente of grupos.value?.[clave] ?? []) mapa.set(cliente.id, cliente);
  }
  return mapa;
});

const clienteAlias = computed(() =>
  aliasClienteId.value === null ? null : clientesPorId.value.get(aliasClienteId.value) ?? null,
);

// Al buscar, se abren los grupos que tienen coincidencias (el usuario puede volver a cerrarlos).
watch(busquedaNormalizada, (termino) => {
  if (!termino) return;
  for (const clave of ORDEN_GRUPOS_CLIENTES) {
    if (visibles.value[clave].length > 0) abiertos.value[clave] = true;
  }
});

function etiquetaCategoria(categoria: number | null): string {
  return categoria === null ? 'Sin categorizar' : `C${categoria}`;
}

function esAutomatico(cliente: ClienteCategoria): boolean {
  return cliente.origen_categoria === 'AUTO' || cliente.origen_categoria === 'SLA';
}

function valorSelect(cliente: ClienteCategoria): string {
  if (esAutomatico(cliente)) return 'auto';
  return cliente.categoria === null ? 'sin' : String(cliente.categoria);
}

function categoriaDeClave(clave: ClaveGrupoCliente): number | null {
  return clave === 'sin' ? null : Number(clave);
}

async function cargar(): Promise<void> {
  cargando.value = true;
  error.value = '';
  try {
    const respuesta = await getClientesPorCategoria();
    grupos.value = respuesta.grupos;
    // La selección sólo conserva clientes que siguen existiendo (fusiones, alias movidos).
    const vigentes = new Set([...seleccionados.value].filter((id) => clientesPorId.value.has(id)));
    if (vigentes.size !== seleccionados.value.size) seleccionados.value = vigentes;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo cargar el listado de clientes.';
  } finally {
    cargando.value = false;
  }
}

async function cambiarFila(cliente: ClienteCategoria, valor: string): Promise<void> {
  if (valor === valorSelect(cliente) || guardandoFila.value !== null) return;
  guardandoFila.value = cliente.id;
  error.value = '';
  mensaje.value = '';
  try {
    const cambio =
      valor === 'auto'
        ? ({ automatico: true } as const)
        : { categoria: categoriaDeClave(valor as ClaveGrupoCliente) };
    const respuesta = await cambiarCategoriaClientes([cliente.id], cambio);
    mensaje.value = `${cliente.nombre}: ${respuesta.sync.servicios_actualizados} servicio(s) actualizado(s).`;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo cambiar la categoría.';
  } finally {
    guardandoFila.value = null;
    // Recarga siempre: si falló, el select vuelve a mostrar el valor real.
    await cargar();
  }
}

function toggleSeleccion(id: number): void {
  const next = new Set(seleccionados.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  seleccionados.value = next;
}

function limpiarSeleccion(): void {
  seleccionados.value = new Set();
}

const mensajeConfirmacion = computed(() => {
  const cantidad = cantidadConfirmacion.value;
  const clientes = `${cantidad} cliente${cantidad !== 1 ? 's' : ''}`;
  if (accionPendiente.value === 'automatico') {
    return `${clientes} vuelve${cantidad !== 1 ? 'n' : ''} a categoría automática (se recalcula por SLA de sus servicios).`;
  }
  return `Se fija ${etiquetaGrupo(categoriaMasiva.value)} (origen Manual) a ${clientes}. La categoría se propaga a sus servicios, salvo excepciones.`;
});

function abrirConfirmacion(accion: 'categoria' | 'automatico'): void {
  accionPendiente.value = accion;
  cantidadConfirmacion.value = seleccionados.value.size;
  errorConfirmacion.value = '';
  resultadoConfirmacion.value = null;
  confirmOpen.value = true;
}

async function confirmarAccionMasiva(): Promise<void> {
  if (confirmando.value || resultadoConfirmacion.value !== null || seleccionados.value.size === 0) return;
  confirmando.value = true;
  errorConfirmacion.value = '';
  try {
    const cambio =
      accionPendiente.value === 'automatico'
        ? ({ automatico: true } as const)
        : { categoria: categoriaDeClave(categoriaMasiva.value) };
    const respuesta = await cambiarCategoriaClientes([...seleccionados.value], cambio);
    resultadoConfirmacion.value =
      `${respuesta.actualizados} cliente(s) actualizado(s) · ` +
      `${respuesta.sync.servicios_actualizados} servicio(s) actualizado(s)` +
      (respuesta.no_encontrados.length > 0 ? ` · ${respuesta.no_encontrados.length} no encontrado(s).` : '.');
    limpiarSeleccion();
    await cargar();
  } catch (err: unknown) {
    errorConfirmacion.value = err instanceof Error ? err.message : 'No se pudo aplicar el cambio.';
  } finally {
    confirmando.value = false;
  }
}

function abrirAlias(clienteId: number): void {
  aliasClienteId.value = clienteId;
}

function abrirFusion(): void {
  // Foto de la selección: el modal la sigue mostrando aunque la recarga posterior la cambie.
  clientesFusion.value = [...seleccionados.value]
    .map((id) => clientesPorId.value.get(id))
    .filter((c): c is ClienteCategoria => c !== undefined)
    .sort(compararNombres);
  fusionOpen.value = true;
}

async function onFusionado(): Promise<void> {
  limpiarSeleccion();
  await cargar();
}

async function resincronizar(): Promise<void> {
  if (sincronizando.value) return;
  sincronizando.value = true;
  error.value = '';
  mensaje.value = '';
  try {
    const resumen = await sincronizarClientes();
    mensaje.value =
      `Sincronización completa: ${resumen.clientes_creados} cliente(s) nuevo(s), ` +
      `${resumen.clientes_recalculados} recalculado(s), ${resumen.servicios_actualizados} servicio(s) actualizado(s).`;
    await cargar();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo re-sincronizar.';
  } finally {
    sincronizando.value = false;
  }
}

onMounted(() => {
  void cargar();
});
</script>

<style scoped>
.clientes-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 16px 0 12px;
}

.clientes-toolbar__buscar {
  flex: 1;
  min-width: 220px;
  max-width: 420px;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-divider);
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 0.88rem;
}

.clientes-toolbar__acciones {
  display: flex;
  gap: 8px;
}

.clientes-mensaje {
  margin: 0 0 12px;
  font-size: 0.85rem;
  color: var(--success);
}

.clientes-mensaje.is-error {
  color: var(--error);
}

.clientes-resumen {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}

.clientes-resumen__chip,
.clientes-grupo__count {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 0.75rem;
  background: var(--color-brand-primary-tint);
  color: var(--color-text);
  white-space: nowrap;
}

.clientes-resumen__chip strong {
  color: var(--color-accent);
}

.clientes-resumen__chip.is-sin,
.clientes-grupo__count.is-sin {
  background: color-mix(in srgb, var(--color-state-idle) 22%, transparent);
}

.clientes-resumen__chip.is-sin strong {
  color: var(--color-state-idle);
}

.clientes-grupos {
  display: grid;
  gap: 10px;
  padding-bottom: 80px; /* espacio para la barra masiva flotante */
}

.clientes-vacio {
  margin: 12px 0 0;
  font-size: 0.85rem;
  color: var(--muted);
}

.clientes-lista {
  list-style: none;
  margin: 0;
  padding: 0;
}

.clientes-fila {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-divider);
}

.clientes-fila:last-child {
  border-bottom: none;
}

.clientes-fila__info {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.clientes-fila__titulo {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.clientes-fila__nombre {
  font-size: 0.9rem;
  color: var(--color-text);
  overflow-wrap: anywhere;
}

.clientes-fila__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  font-size: 0.76rem;
  color: var(--muted);
}

.clientes-fila__alias summary {
  cursor: pointer;
}

.clientes-fila__alias ul {
  margin: 4px 0 0;
  padding-left: 16px;
}

.clientes-fila__link {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--color-accent);
  font-size: 0.76rem;
  cursor: pointer;
}

.clientes-fila__link:hover {
  text-decoration: underline;
}

.clientes-fila__select {
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--color-divider);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: 0.8rem;
}

.clientes-badge {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 600;
  white-space: nowrap;
  background: color-mix(in srgb, var(--color-state-idle) 18%, transparent);
  color: var(--muted);
}

.clientes-badge.is-lista,
.clientes-badge.is-manual {
  background: var(--color-brand-primary-soft);
  color: var(--color-accent-200);
}

.clientes-badge.is-sla {
  background: color-mix(in srgb, var(--success) 14%, transparent);
  color: var(--success);
}

.clientes-badge.is-revisar {
  background: color-mix(in srgb, var(--warning) 15%, transparent);
  color: var(--warning);
  border: 1px solid color-mix(in srgb, var(--warning) 33%, transparent);
}

.clientes-bulk {
  position: fixed;
  left: 50%;
  bottom: 22px;
  transform: translateX(-50%);
  z-index: 40;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-size: 12.5px;
  color: var(--color-text);
  background: var(--color-surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  max-width: calc(100vw - 32px);
}

.clientes-bulk__count {
  font-weight: 500;
  white-space: nowrap;
}

@media (max-width: 700px) {
  .clientes-fila {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .clientes-fila__select {
    grid-column: 2;
    justify-self: start;
  }

  .clientes-bulk {
    left: 12px;
    right: 12px;
    bottom: 12px;
    transform: none;
  }
}
</style>
