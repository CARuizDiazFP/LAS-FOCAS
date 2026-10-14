<!--
  Nombre de archivo: ClientesListaModal.vue
  Ubicación de archivo: web/frontend/src/admin/components/clientes/ClientesListaModal.vue
  Descripción: Modal de carga de la lista oficial de clientes de una categoría — pegar o adjuntar, previsualizar el diff y aplicar con confirmación
-->
<template>
  <dialog ref="dialogEl" class="clientes-modal" @click.self="handleClose">
    <div class="clientes-modal__content">
      <div class="clientes-modal__title-row">
        <strong>Cargar lista de clientes</strong>
        <button class="clientes-modal__close" type="button" aria-label="Cerrar" @click="handleClose">×</button>
      </div>

      <p class="clientes-modal__hint">
        Un nombre de cliente por renglón (o la primera columna del archivo). La fila de encabezado
        "Cliente" o "Nombre Cliente" es opcional. Los clientes de la lista quedan con origen <em>Lista</em>.
      </p>

      <div class="lista-fuente" role="tablist" aria-label="Origen de la lista">
        <button
          type="button"
          role="tab"
          :aria-selected="fuenteTipo === 'nombres'"
          :class="['lista-fuente__tab', { 'is-active': fuenteTipo === 'nombres' }]"
          @click="fuenteTipo = 'nombres'"
        >
          Pegar nombres
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="fuenteTipo === 'archivo'"
          :class="['lista-fuente__tab', { 'is-active': fuenteTipo === 'archivo' }]"
          @click="fuenteTipo = 'archivo'"
        >
          Adjuntar archivo
        </button>
      </div>

      <textarea
        v-if="fuenteTipo === 'nombres'"
        v-model="texto"
        class="lista-texto"
        rows="8"
        placeholder="Banco Ejemplo S.A.&#10;Otro Cliente SRL&#10;..."
      />
      <div v-else class="lista-archivo">
        <label class="lista-archivo__dropzone" for="lista-clientes-archivo">
          <span>{{ archivo ? archivo.name : 'Seleccioná el archivo de la lista' }}</span>
          <small>Formatos soportados: .xlsx, .xlsm, .csv, .txt (máx. 5 MB)</small>
        </label>
        <input
          id="lista-clientes-archivo"
          ref="archivoInput"
          type="file"
          :accept="EXTENSIONES_LISTA"
          hidden
          @change="onSeleccionarArchivo"
        />
      </div>

      <div class="lista-opciones">
        <label class="lista-opciones__campo">
          <span>Categoría</span>
          <select v-model="categoriaValor" class="lista-select">
            <option v-for="clave in ORDEN_GRUPOS_CLIENTES" :key="clave" :value="clave">{{ etiquetaGrupo(clave) }}</option>
          </select>
        </label>
        <fieldset class="lista-opciones__modo">
          <legend>Modo</legend>
          <label><input v-model="modo" type="radio" value="agregar" /> Agregar</label>
          <label><input v-model="modo" type="radio" value="reemplazar" /> Reemplazar</label>
        </fieldset>
      </div>

      <p v-if="modo === 'reemplazar'" class="lista-aviso">
        <strong>Reemplazar:</strong> los clientes que hoy están en {{ etiquetaGrupo(categoriaValor) }} por una lista
        anterior y no vienen en esta vuelven a <em>Automático</em> (su categoría se recalcula por SLA).
      </p>

      <p v-if="error" class="clientes-modal__error">{{ error }}</p>

      <section v-if="previa" class="lista-diff" aria-live="polite">
        <div class="lista-diff__resumen">
          <span class="lista-diff__chip is-sube">Suben {{ previa.sube.length }}</span>
          <span class="lista-diff__chip is-baja">Bajan {{ previa.baja.length }}</span>
          <span class="lista-diff__chip">Sin cambio {{ previa.sin_cambio.length }}</span>
          <span class="lista-diff__chip is-nuevo">Nuevos {{ previa.nuevos.length }}</span>
          <span v-if="previa.modo === 'reemplazar'" class="lista-diff__chip is-baja">Quitados {{ previa.quitados.length }}</span>
        </div>

        <details v-if="previa.sube.length" class="lista-diff__grupo">
          <summary>Suben de categoría ({{ previa.sube.length }})</summary>
          <ul>
            <li v-for="item in previa.sube" :key="item.cliente_id">
              {{ item.nombre }} <span class="lista-diff__meta">{{ etiquetaCategoria(item.categoria_actual) }} → {{ etiquetaGrupo(categoriaValor) }}</span>
            </li>
          </ul>
        </details>
        <details v-if="previa.baja.length" class="lista-diff__grupo">
          <summary>Bajan de categoría ({{ previa.baja.length }})</summary>
          <ul>
            <li v-for="item in previa.baja" :key="item.cliente_id">
              {{ item.nombre }} <span class="lista-diff__meta">{{ etiquetaCategoria(item.categoria_actual) }} → {{ etiquetaGrupo(categoriaValor) }}</span>
            </li>
          </ul>
        </details>
        <details v-if="previa.sin_cambio.length" class="lista-diff__grupo">
          <summary>Sin cambio de categoría ({{ previa.sin_cambio.length }})</summary>
          <ul>
            <li v-for="item in previa.sin_cambio" :key="item.cliente_id">
              {{ item.nombre }} <span class="lista-diff__meta">{{ etiquetaOrigen(item.origen_actual) }}</span>
            </li>
          </ul>
        </details>
        <details v-if="previa.nuevos.length" class="lista-diff__grupo" open>
          <summary>Nuevos, sin cliente existente ({{ previa.nuevos.length }})</summary>
          <p class="lista-diff__nota">
            Se crean como clientes nuevos. Si es otra grafía de un cliente existente, vinculala como alias.
          </p>
          <ul>
            <li v-for="nombre in previa.nuevos" :key="nombre" class="lista-diff__nuevo">
              <span>{{ nombre }}</span>
              <span v-if="previa.sugerencias[nombre]?.length" class="lista-diff__sugerencias">
                <span class="lista-diff__meta">¿Es…?</span>
                <button
                  v-for="sugerencia in previa.sugerencias[nombre]"
                  :key="sugerencia.id"
                  class="btn subtle lista-diff__vincular"
                  type="button"
                  :disabled="vinculando !== null || previsualizando"
                  :title="`Vincular '${nombre}' como alias de '${sugerencia.nombre}'`"
                  @click="vincularAlias(nombre, sugerencia.id)"
                >
                  {{ vinculando === `${nombre}|${sugerencia.id}` ? 'Vinculando...' : sugerencia.nombre }}
                </button>
              </span>
            </li>
          </ul>
        </details>
        <details v-if="previa.quitados.length" class="lista-diff__grupo" open>
          <summary>Vuelven a automático ({{ previa.quitados.length }})</summary>
          <ul>
            <li v-for="item in previa.quitados" :key="item.cliente_id">{{ item.nombre }}</li>
          </ul>
        </details>
      </section>

      <div class="clientes-modal__actions">
        <button class="btn subtle" type="button" :disabled="!fuenteValida || previsualizando" @click="previsualizar">
          {{ previsualizando ? 'Previsualizando...' : 'Previsualizar' }}
        </button>
        <button
          class="btn primary"
          type="button"
          :disabled="!previa || previsualizando"
          :title="previa ? '' : 'Previsualizá la lista antes de aplicarla'"
          @click="abrirConfirmacion"
        >
          Aplicar
        </button>
        <button class="btn subtle" type="button" @click="handleClose">Cerrar</button>
      </div>
    </div>

    <ModalConfirmarAccionMasiva
      :open="confirmOpen"
      titulo="Aplicar lista de clientes"
      :mensaje="mensajeConfirmacion"
      :confirmando="aplicando"
      :error="errorAplicar"
      :resultado="resultadoAplicar"
      @close="cerrarConfirmacion"
      @confirm="aplicar"
    />
  </dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import ModalConfirmarAccionMasiva from '../../../components/infra/ModalConfirmarAccionMasiva.vue';
import {
  EXTENSIONES_LISTA,
  ORDEN_GRUPOS_CLIENTES,
  TAMANO_MAXIMO_LISTA,
  agregarAliasCliente,
  aplicarLista,
  etiquetaGrupo,
  etiquetaOrigen,
  previsualizarLista,
  type ClaveGrupoCliente,
  type FuenteLista,
  type ModoLista,
  type PrevisualizacionLista,
} from '../../api/clientesCategoria';

const props = defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  close: [];
  /** Se aplicó la lista o se vinculó un alias: el padre recarga el listado. */
  cambiado: [];
}>();

// Encabezados opcionales de la primera fila (mismo criterio que el parser del backend para archivos).
const ENCABEZADOS = new Set(['cliente', 'nombre cliente']);

const dialogEl = ref<HTMLDialogElement | null>(null);
const archivoInput = ref<HTMLInputElement | null>(null);
const fuenteTipo = ref<'nombres' | 'archivo'>('nombres');
const texto = ref('');
const archivo = ref<File | null>(null);
const categoriaValor = ref<ClaveGrupoCliente>('6');
const modo = ref<ModoLista>('agregar');

const previa = ref<PrevisualizacionLista | null>(null);
const previsualizando = ref(false);
const vinculando = ref<string | null>(null);
const error = ref('');

const confirmOpen = ref(false);
const aplicando = ref(false);
const errorAplicar = ref('');
const resultadoAplicar = ref<string | null>(null);

const categoria = computed<number | null>(() => (categoriaValor.value === 'sin' ? null : Number(categoriaValor.value)));

function normalizar(valor: string): string {
  return valor
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

const nombresPegados = computed<string[]>(() => {
  const lineas = texto.value
    .split(/\r?\n/)
    .map((linea) => linea.trim())
    .filter((linea) => linea.length > 0);
  if (lineas.length > 0 && ENCABEZADOS.has(normalizar(lineas[0]))) lineas.shift();
  return lineas;
});

const fuente = computed<FuenteLista | null>(() => {
  if (fuenteTipo.value === 'archivo') return archivo.value ? { tipo: 'archivo', archivo: archivo.value } : null;
  return nombresPegados.value.length > 0 ? { tipo: 'nombres', nombres: nombresPegados.value } : null;
});

const fuenteValida = computed(() => fuente.value !== null);

const mensajeConfirmacion = computed(() => {
  if (!previa.value) return '';
  const p = previa.value;
  const destino = etiquetaGrupo(categoriaValor.value);
  const partes = [
    `Se asigna ${destino} (origen Lista) a ${p.sube.length + p.baja.length + p.sin_cambio.length} cliente(s) existente(s)`,
    `se crean ${p.nuevos.length} cliente(s) nuevo(s)`,
  ];
  if (p.modo === 'reemplazar') partes.push(`${p.quitados.length} cliente(s) de la lista anterior vuelven a automático`);
  return `${partes.join(', ')}. La categoría se propaga a sus servicios (salvo excepciones).`;
});

function etiquetaCategoria(valor: number | null): string {
  return valor === null ? 'Sin categorizar' : `C${valor}`;
}

function onSeleccionarArchivo(event: Event): void {
  const elegido = (event.target as HTMLInputElement).files?.[0] ?? null;
  error.value = '';
  if (elegido && elegido.size > TAMANO_MAXIMO_LISTA) {
    archivo.value = null;
    error.value = 'El archivo supera los 5 MB.';
    if (archivoInput.value) archivoInput.value.value = '';
    return;
  }
  archivo.value = elegido;
}

// Cualquier cambio en lo que se aplicaría invalida la previsualización: "Aplicar" vuelve a exigirla.
watch([fuenteTipo, texto, archivo, categoriaValor, modo], () => {
  previa.value = null;
});

async function previsualizar(): Promise<void> {
  if (!fuente.value || previsualizando.value) return;
  previsualizando.value = true;
  error.value = '';
  try {
    previa.value = await previsualizarLista(fuente.value, categoria.value, modo.value);
  } catch (err: unknown) {
    previa.value = null;
    error.value = err instanceof Error ? err.message : 'No se pudo previsualizar la lista.';
  } finally {
    previsualizando.value = false;
  }
}

async function vincularAlias(nombre: string, clienteId: number): Promise<void> {
  if (vinculando.value !== null) return;
  vinculando.value = `${nombre}|${clienteId}`;
  error.value = '';
  try {
    await agregarAliasCliente(clienteId, nombre);
    emit('cambiado');
    await previsualizar();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo vincular el alias.';
  } finally {
    vinculando.value = null;
  }
}

function abrirConfirmacion(): void {
  if (!previa.value) return;
  errorAplicar.value = '';
  resultadoAplicar.value = null;
  confirmOpen.value = true;
}

function cerrarConfirmacion(): void {
  confirmOpen.value = false;
  if (resultadoAplicar.value !== null) {
    // Ya aplicada: la previsualización quedó vieja.
    previa.value = null;
    resultadoAplicar.value = null;
  }
}

async function aplicar(): Promise<void> {
  if (!fuente.value || aplicando.value || resultadoAplicar.value !== null) return;
  aplicando.value = true;
  errorAplicar.value = '';
  try {
    const respuesta = await aplicarLista(fuente.value, categoria.value, modo.value);
    const coincidentes = respuesta.sube.length + respuesta.baja.length + respuesta.sin_cambio.length;
    resultadoAplicar.value =
      `Lista aplicada: ${coincidentes} cliente(s) existente(s), ${respuesta.creados} creado(s), ` +
      `${respuesta.quitados.length} vuelto(s) a automático · ${respuesta.sync.servicios_actualizados} servicio(s) actualizado(s).`;
    emit('cambiado');
  } catch (err: unknown) {
    errorAplicar.value = err instanceof Error ? err.message : 'No se pudo aplicar la lista.';
  } finally {
    aplicando.value = false;
  }
}

function handleClose(): void {
  dialogEl.value?.close();
  emit('close');
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      error.value = '';
      previa.value = null;
      confirmOpen.value = false;
      dialogEl.value?.showModal();
      return;
    }
    if (dialogEl.value?.open) dialogEl.value.close();
  },
);
</script>

<style scoped>
.clientes-modal {
  width: min(720px, calc(100vw - 32px));
  max-height: calc(100vh - 48px);
  background: transparent;
  border: none;
  padding: 0;
}

.clientes-modal::backdrop {
  background: rgba(4, 8, 14, 0.74);
  backdrop-filter: blur(8px);
}

.clientes-modal__content {
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--color-text);
  box-shadow: var(--shadow-lg);
}

.clientes-modal__title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.clientes-modal__close {
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 1.4rem;
  line-height: 1;
}

.clientes-modal__close:hover {
  color: var(--color-text);
}

.clientes-modal__hint {
  margin: 0 0 14px;
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--muted);
}

.clientes-modal__error {
  margin: 0 0 12px;
  font-size: 0.85rem;
  color: var(--error);
}

.clientes-modal__actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
}

.lista-fuente {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
}

.lista-fuente__tab {
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--color-divider);
  background: transparent;
  color: var(--muted);
  font-size: 0.8rem;
  cursor: pointer;
}

.lista-fuente__tab.is-active {
  border-color: var(--color-accent);
  background: var(--color-brand-primary-tint);
  color: var(--color-accent);
}

.lista-texto {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  padding: 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-divider);
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 0.85rem;
  font-family: inherit;
}

.lista-archivo__dropzone {
  display: grid;
  gap: 4px;
  padding: 18px;
  border-radius: var(--radius-md);
  border: 1px dashed var(--color-divider);
  background: var(--color-bg);
  text-align: center;
  cursor: pointer;
  font-size: 0.85rem;
}

.lista-archivo__dropzone:hover {
  border-color: var(--color-accent);
}

.lista-archivo__dropzone small {
  color: var(--muted);
}

.lista-opciones {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 18px;
  margin: 12px 0;
}

.lista-opciones__campo {
  display: grid;
  gap: 4px;
  font-size: 0.78rem;
  color: var(--muted);
}

.lista-select {
  padding: 6px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-divider);
  background: var(--color-bg);
  color: var(--color-text);
}

.lista-opciones__modo {
  display: flex;
  gap: 14px;
  margin: 0;
  padding: 0;
  border: none;
  font-size: 0.85rem;
}

.lista-opciones__modo legend {
  margin-bottom: 4px;
  font-size: 0.78rem;
  color: var(--muted);
}

.lista-aviso {
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 0.82rem;
  line-height: 1.5;
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--warning) 33%, transparent);
}

.lista-diff {
  display: grid;
  gap: 8px;
  max-height: 340px;
  overflow-y: auto;
  padding: 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-divider);
  background: var(--color-bg);
}

.lista-diff__resumen {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.lista-diff__chip {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 0.75rem;
  background: color-mix(in srgb, var(--color-state-idle) 18%, transparent);
  color: var(--color-text);
}

.lista-diff__chip.is-sube {
  background: color-mix(in srgb, var(--success) 15%, transparent);
  color: var(--success);
}

.lista-diff__chip.is-baja {
  background: color-mix(in srgb, var(--warning) 15%, transparent);
  color: var(--warning);
}

.lista-diff__chip.is-nuevo {
  background: var(--color-brand-primary-soft);
  color: var(--color-accent-200);
}

.lista-diff__grupo summary {
  cursor: pointer;
  font-size: 0.85rem;
}

.lista-diff__grupo ul {
  margin: 6px 0 0;
  padding-left: 18px;
  display: grid;
  gap: 4px;
  font-size: 0.82rem;
}

.lista-diff__nota {
  margin: 6px 0 0;
  font-size: 0.78rem;
  color: var(--muted);
}

.lista-diff__meta {
  font-size: 0.75rem;
  color: var(--muted);
}

.lista-diff__nuevo {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.lista-diff__sugerencias {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.lista-diff__vincular {
  min-height: 22px;
  padding: 1px 8px;
  font-size: 0.72rem;
}
</style>
