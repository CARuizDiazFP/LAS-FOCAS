<!--
  Nombre de archivo: CamaraDetailView.vue
  Ubicación de archivo: web/frontend/src/views/CamaraDetailView.vue
  Descripción: Vista dedicada de detalle operativo para una cámara de infraestructura FO
-->
<template>
  <section class="camara-detail-page">
    <div class="camara-detail-shell">
      <RouterLink class="camara-detail-back" to="/infra">← Volver a Infraestructura</RouterLink>

      <div v-if="loading" class="camara-detail-state">Cargando detalle operativo de la cámara...</div>
      <div v-else-if="errorMessage" class="camara-detail-state error">
        <strong>No se pudo cargar la cámara.</strong>
        <span>{{ errorMessage }}</span>
        <button class="btn subtle" type="button" @click="void loadCamaraDetail()">Reintentar</button>
      </div>

      <template v-else-if="camara">
        <header class="camara-detail-hero">
          <div class="camara-detail-hero__content">
            <p class="camara-detail-hero__eyebrow">Infraestructura FO · Cámara</p>
            <h1>{{ camara.nombre || camara.direccion || `Cámara ${camara.id}` }}</h1>
            <div class="camara-detail-hero__meta">
              <span class="camara-detail-id">ID {{ camara.id }}</span>
              <span :class="['camara-detail-status', statusClass(camara.estado)]">{{ camara.estado || 'LIBRE' }}</span>
              <RouterLink
                v-if="camara.es_botella && camara.camara_padre_id"
                class="camara-detail-padre-link"
                :to="`/infra/Camaras/${camara.camara_padre_id}`"
              >
                <i class="ph ph-arrow-bend-left-up" aria-hidden="true"></i>
                Cámara padre: {{ camara.camara_padre_nombre || `ID ${camara.camara_padre_id}` }}
              </RouterLink>
            </div>
          </div>
          <div class="camara-detail-hero__actions">
            <button
              v-if="isAdmin"
              class="btn primary"
              type="button"
              @click="estadoModalOpen = true"
            >Editar estado</button>
            <button
              v-if="isAdmin && !camara.es_botella"
              class="btn subtle"
              type="button"
              @click="unificarModalOpen = true"
            >Unificar Cámara</button>
            <button
              v-if="isAdmin"
              class="btn subtle"
              type="button"
              @click="eliminarConfirmarAbierto = true"
            >{{ camara.es_botella ? 'Eliminar Botella' : 'Eliminar Cámara' }}</button>
          </div>
        </header>

        <div v-if="eliminarConfirmarAbierto" class="camara-detail-eliminar-confirm">
          <p>
            ⚠️ ¿Eliminar permanentemente <strong>{{ camara.nombre || `ID ${camara.id}` }}</strong>?
            Esta acción no se puede deshacer.
          </p>
          <ul v-if="eliminarBloqueos.length > 0" class="camara-detail-eliminar-bloqueos">
            <li v-for="b in eliminarBloqueos" :key="`${b.origen}:${b.id}`">
              {{ b.nombre || `ID ${b.id}` }} ({{ b.origen }}): {{ b.razon }}
            </li>
          </ul>
          <p v-else-if="eliminarErrorMsg" class="camara-detail-eliminar-error">{{ eliminarErrorMsg }}</p>
          <div class="camara-detail-eliminar-actions">
            <button class="btn danger" type="button" :disabled="eliminando" @click="handleEliminar">
              {{ eliminando ? 'Eliminando...' : 'Sí, eliminar' }}
            </button>
            <button class="btn subtle" type="button" :disabled="eliminando" @click="cerrarConfirmacionEliminar">
              Cancelar
            </button>
          </div>
        </div>

        <section class="camara-detail-dashboard">
          <button class="camara-detail-card" type="button" @click="aliasModalOpen = true">
            <span class="camara-detail-card__eyebrow">Alias Conocidos</span>
            <strong>{{ aliases.length }}</strong>
            <p>{{ aliases.length ? 'Variantes detectadas del nombre canon.' : 'Sin alias registrados por ahora.' }}</p>
          </button>

          <button class="camara-detail-card" type="button" @click="registrosModalOpen = true">
            <span class="camara-detail-card__eyebrow">Registros</span>
            <strong>{{ registrosCount }}</strong>
            <p>Alterna entre ingresos y baneos. Los baneos arrancan retraídos.</p>
          </button>

          <button class="camara-detail-card" type="button" @click="serviciosModalOpen = true">
            <span class="camara-detail-card__eyebrow">Servicios Asociados</span>
            <strong>{{ serviciosCount }}</strong>
            <p>{{ camara.rutas.length }} ruta{{ camara.rutas.length !== 1 ? 's' : '' }} asociada{{ camara.rutas.length !== 1 ? 's' : '' }}. Cada ID de servicio abre su tracking en un modal superpuesto.</p>
          </button>

          <button
            v-if="!camara.es_botella"
            class="camara-detail-card"
            type="button"
            @click="botellasModalOpen = true"
          >
            <span class="camara-detail-card__eyebrow">Botellas</span>
            <strong>{{ botellas.length }}</strong>
            <p>{{ botellas.length ? 'Cajas de empalme agrupadas bajo esta cámara física.' : 'Sin botellas asociadas — esta cámara no tiene sub-jerarquía.' }}</p>
          </button>
        </section>
      </template>
    </div>

    <CamaraEstadoModal
      :open="estadoModalOpen"
      :camara-id="camara?.id ?? null"
      :camara-nombre="camara?.nombre || camara?.direccion || ''"
      @close="estadoModalOpen = false"
      @updated="handleEstadoActualizado"
      @error="showInlineError"
    />

    <ModalAlias
      :open="aliasModalOpen"
      :camara-id="camara?.id ?? null"
      :camara-nombre="camara?.nombre || camara?.direccion || ''"
      :aliases="aliases"
      @close="aliasModalOpen = false"
    />

    <ModalServicios
      :open="serviciosModalOpen"
      :camara-id="camara?.id ?? null"
      :camara-nombre="camara?.nombre || camara?.direccion || ''"
      :rutas="camara?.rutas ?? []"
      @error="showInlineError"
      @close="serviciosModalOpen = false"
    />

    <ModalRegistros
      :open="registrosModalOpen"
      :camara-id="camara?.id ?? null"
      :camara-nombre="camara?.nombre || camara?.direccion || ''"
      :contexto="registros.contexto"
      :baneos="registros.baneos"
      :auditoria="registros.auditoria"
      :ingresos="registros.ingresos"
      @close="registrosModalOpen = false"
    />

    <ModalBotellas
      :open="botellasModalOpen"
      :camara-id="camara?.id ?? null"
      :camara-nombre="camara?.nombre || camara?.direccion || ''"
      :botellas="botellas"
      @close="botellasModalOpen = false"
    />

    <ModalUnificarCamara
      :open="unificarModalOpen"
      :camara-id="camara?.id ?? null"
      :camara-nombre="camara?.nombre || camara?.direccion || ''"
      @close="unificarModalOpen = false"
      @merged="handleUnificacionCompletada"
      @error="showInlineError"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useSession } from '../composables/useSession';
import CamaraEstadoModal from '../components/infra/CamaraEstadoModal.vue';
import ModalAlias from '../components/infra/ModalAlias.vue';
import ModalServicios from '../components/infra/ModalServicios.vue';
import ModalRegistros from '../components/infra/ModalRegistros.vue';
import ModalBotellas from '../components/infra/ModalBotellas.vue';
import ModalUnificarCamara from '../components/infra/ModalUnificarCamara.vue';
import { ApiError } from '../api/client';
import { eliminarCamara } from '../api/camaras';
import { eliminarBotella, type BloqueoEliminacion, type BotellaOrigen } from '../api/botellas';

interface RutaItem {
  ruta_id: number;
  servicio_id: string;
  ruta_nombre: string;
  ruta_tipo: string;
  alias_ids: string[];
  transitos_count: number;
  punta_a_sitio: string | null;
  punta_b_sitio: string | null;
}

interface CamaraDetail {
  id: number;
  nombre: string;
  direccion: string | null;
  estado: string;
  editable: boolean;
  rutas: RutaItem[];
  es_botella: boolean;
  camara_padre_id: number | null;
  camara_padre_nombre: string | null;
}

interface AliasItem {
  id: number;
  nombre: string;
  created_at: string | null;
}

interface BotellaItem {
  id: number;
  nombre: string | null;
  estado: string | null;
  servicios: string[];
  origen: BotellaOrigen;
}

interface RegistrosContexto {
  estado_actual: string;
  estado_sugerido: string | null;
  tiene_baneo_activo: boolean;
  tiene_ingreso_activo: boolean;
}

interface RegistrosBaneo {
  id: number;
  ticket_asociado: string | null;
  servicio_protegido_id: string;
  ruta_protegida_id: number | null;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  motivo: string | null;
  activo: boolean;
}

interface RegistrosAuditoria {
  id: number;
  usuario: string;
  motivo: string;
  estado_anterior: string | null;
  estado_nuevo: string | null;
  estado_sugerido: string | null;
  created_at: string | null;
}

interface RegistrosIngreso {
  id: number;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  tecnico_id: string | null;
  cromo_botella_id: number | null;
}

interface RegistrosPayload {
  contexto: RegistrosContexto | null;
  baneos: RegistrosBaneo[];
  auditoria: RegistrosAuditoria[];
  ingresos: RegistrosIngreso[];
}

const route = useRoute();
const router = useRouter();
const { state } = useSession();
const isAdmin = computed(() => (state.value.role ?? '').toLowerCase() === 'admin');

const camara = ref<CamaraDetail | null>(null);
const aliases = ref<AliasItem[]>([]);
const botellas = ref<BotellaItem[]>([]);
const registros = ref<RegistrosPayload>({
  contexto: null,
  baneos: [],
  auditoria: [],
  ingresos: [],
});

const loading = ref(true);
const errorMessage = ref('');
const estadoModalOpen = ref(false);
const aliasModalOpen = ref(false);
const serviciosModalOpen = ref(false);
const registrosModalOpen = ref(false);
const botellasModalOpen = ref(false);
const unificarModalOpen = ref(false);
const eliminarConfirmarAbierto = ref(false);
const eliminando = ref(false);
const eliminarErrorMsg = ref('');
const eliminarBloqueos = ref<BloqueoEliminacion[]>([]);

const serviciosCount = computed(() => new Set((camara.value?.rutas ?? []).map((ruta) => ruta.servicio_id)).size);
const registrosCount = computed(
  () => registros.value.baneos.length + registros.value.auditoria.length + registros.value.ingresos.length,
);

function statusClass(status: string): string {
  const normalized = (status || 'LIBRE').toLowerCase();
  if (normalized === 'baneada') return 'baneada';
  if (normalized === 'ocupada') return 'ocupada';
  if (normalized === 'detectada') return 'detectada';
  if (normalized === 'no_operativa') return 'no_operativa';
  return 'libre';
}

function getCamaraId(): number {
  const value = Number(route.params.id);
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error('El identificador de cámara no es válido.');
  }
  return value;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const data = await response.json() as T & { error?: string };
  if (!response.ok) {
    throw new Error(data.error ?? `Error ${response.status}`);
  }
  return data;
}

async function loadCamaraDetail(): Promise<void> {
  loading.value = true;
  errorMessage.value = '';
  try {
    const camaraId = getCamaraId();
    const [camaraResponse, aliasesResponse, registrosResponse, botellasResponse] = await Promise.all([
      fetch(`/api/infra/camaras/${camaraId}`, { credentials: 'include' }),
      fetch(`/api/infra/camaras/${camaraId}/aliases`, { credentials: 'include' }),
      fetch(`/api/infra/camaras/${camaraId}/registros`, { credentials: 'include' }),
      fetch(`/api/infra/camaras/${camaraId}/botellas`, { credentials: 'include' }),
    ]);

    const camaraData = await parseResponse<{ camara: CamaraDetail }>(camaraResponse);
    const aliasesData = await parseResponse<{ aliases: AliasItem[] }>(aliasesResponse);
    const registrosData = await parseResponse<RegistrosPayload>(registrosResponse);
    const botellasData = await parseResponse<{ botellas: BotellaItem[] }>(botellasResponse);

    camara.value = camaraData.camara;
    aliases.value = aliasesData.aliases ?? [];
    botellas.value = botellasData.botellas ?? [];
    registros.value = {
      contexto: registrosData.contexto ?? null,
      baneos: registrosData.baneos ?? [],
      auditoria: registrosData.auditoria ?? [],
      ingresos: registrosData.ingresos ?? [],
    };
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error);
    camara.value = null;
    aliases.value = [];
    botellas.value = [];
  } finally {
    loading.value = false;
  }
}

async function handleEstadoActualizado(): Promise<void> {
  await loadCamaraDetail();
}

async function handleUnificacionCompletada(): Promise<void> {
  // La Cámara secundaria se eliminó tras transferir todo lo heredable a esta — recarga el detalle
  // completo para reflejar Botellas, Cables, alias y estado final ya consolidados.
  await loadCamaraDetail();
}

function showInlineError(message: string): void {
  errorMessage.value = message;
}

function cerrarConfirmacionEliminar(): void {
  eliminarConfirmarAbierto.value = false;
  eliminarErrorMsg.value = '';
  eliminarBloqueos.value = [];
}

async function handleEliminar(): Promise<void> {
  if (!camara.value) return;
  eliminando.value = true;
  eliminarErrorMsg.value = '';
  eliminarBloqueos.value = [];
  try {
    if (camara.value.es_botella) {
      await eliminarBotella('legado', camara.value.id);
    } else {
      await eliminarCamara(camara.value.id);
    }
    // El elemento que esta vista mostraba ya no existe — volver al listado general.
    void router.push('/infra');
  } catch (e: unknown) {
    if (e instanceof ApiError && e.status === 400 && e.payload && typeof e.payload === 'object') {
      const payload = e.payload as { bloqueos?: BloqueoEliminacion[] };
      eliminarBloqueos.value = payload.bloqueos ?? [];
    }
    eliminarErrorMsg.value = e instanceof Error ? e.message : 'No se pudo eliminar.';
  } finally {
    eliminando.value = false;
  }
}

watch(
  () => route.params.id,
  async () => {
    await loadCamaraDetail();
  },
);

onMounted(async () => {
  await loadCamaraDetail();
});
</script>

<style scoped>
.camara-detail-page {
  min-height: 100%;
}

.camara-detail-shell {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 20px 40px;
}

.camara-detail-back {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-accent);
  text-decoration: none;
  margin-bottom: 18px;
}

.camara-detail-back:hover {
  color: var(--color-accent-300);
}

.camara-detail-state {
  display: grid;
  gap: 12px;
  padding: 22px;
  border-radius: 18px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  color: var(--text);
}

.camara-detail-state.error {
  color: var(--error);
}

.camara-detail-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
  padding: 28px;
  border-radius: 24px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  box-shadow: var(--shadow-md);
}

.camara-detail-hero__content h1 {
  margin: 8px 0 12px;
  font-size: clamp(2rem, 4vw, 3rem);
  line-height: 1.05;
  color: var(--color-text);
}

.camara-detail-hero__eyebrow {
  margin: 0;
  color: var(--color-accent);
  text-transform: uppercase;
  letter-spacing: 0.16em;
  font-size: 0.76rem;
}

.camara-detail-hero__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.camara-detail-id,
.camara-detail-status {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 8px 14px;
  font-size: 0.84rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.camara-detail-id {
  color: var(--color-text);
  background: color-mix(in srgb, var(--color-neutral-400) 14%, transparent);
  border: 1px solid var(--color-divider);
}

.camara-detail-status.libre {
  background: color-mix(in srgb, var(--color-state-ok) 18%, transparent);
  color: var(--color-state-ok);
}

.camara-detail-status.ocupada {
  background: color-mix(in srgb, var(--color-state-warn) 18%, transparent);
  color: var(--color-state-warn);
}

.camara-detail-status.baneada {
  background: color-mix(in srgb, var(--color-state-error) 18%, transparent);
  color: var(--color-state-error);
}

.camara-detail-status.detectada {
  background: var(--color-brand-primary-soft);
  color: var(--color-accent-200);
}

.camara-detail-status.no_operativa {
  background: color-mix(in srgb, var(--color-state-idle) 18%, transparent);
  color: var(--color-state-idle);
}

.camara-detail-padre-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  padding: 8px 14px;
  font-size: 0.84rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--color-accent-200);
  background: var(--color-brand-primary-tint);
  border: 1px solid color-mix(in srgb, var(--color-accent) 22%, transparent);
  text-decoration: none;
  transition: background 0.15s ease;
}

.camara-detail-padre-link:hover,
.camara-detail-padre-link:focus-visible {
  background: var(--color-brand-primary-soft);
}

.camara-detail-dashboard {
  margin-top: 22px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
}

.camara-detail-card {
  text-align: left;
  display: grid;
  gap: 10px;
  padding: 22px;
  min-height: 220px;
  border-radius: 20px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  color: var(--text);
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.camara-detail-card:hover {
  transform: translateY(-4px);
  border-color: var(--color-accent);
  box-shadow: var(--shadow-md);
}

.camara-detail-card__eyebrow {
  color: var(--color-neutral-500);
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 0.74rem;
}

.camara-detail-card strong {
  font-size: clamp(1.8rem, 3vw, 2.4rem);
  color: var(--color-text);
}

.camara-detail-card p {
  margin: 0;
  color: var(--color-neutral-300);
  line-height: 1.5;
}

.camara-detail-eliminar-confirm {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 20px;
  border-radius: 16px;
  background: color-mix(in srgb, var(--error) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--error) 35%, transparent);
  color: var(--error);
}

.camara-detail-eliminar-confirm p {
  margin: 0;
}

.camara-detail-eliminar-bloqueos {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}

.camara-detail-eliminar-error {
  font-size: 13px;
}

.camara-detail-eliminar-actions {
  display: flex;
  gap: 10px;
}

@media (max-width: 720px) {
  .camara-detail-hero {
    padding: 22px;
    flex-direction: column;
  }

  .camara-detail-shell {
    padding: 20px 16px 32px;
  }
}
</style>
