<!--
  Nombre de archivo: CamaraDetailView.vue
  Ubicación de archivo: web/frontend/src/views/CamaraDetailView.vue
  Descripción: Vista dedicada de detalle operativo para una cámara de infraestructura FO
-->
<template>
  <section class="camara-detail-page">
    <div class="camara-detail-shell">
      <RouterLink class="camara-detail-back" to="/?tab=infra">← Volver a Infraestructura</RouterLink>

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
            </div>
          </div>
          <div class="camara-detail-hero__actions">
            <button
              v-if="isAdmin"
              class="btn primary"
              type="button"
              @click="estadoModalOpen = true"
            >Editar estado</button>
          </div>
        </header>

        <section class="camara-detail-dashboard">
          <button class="camara-detail-card" type="button" @click="aliasModalOpen = true">
            <span class="camara-detail-card__eyebrow">Alias Conocidos</span>
            <strong>{{ aliases.length }}</strong>
            <p>{{ aliases.length ? 'Variantes detectadas del nombre canon.' : 'Sin alias registrados por ahora.' }}</p>
          </button>

          <button class="camara-detail-card" type="button" @click="registrosModalOpen = true">
            <span class="camara-detail-card__eyebrow">Registros</span>
            <strong>{{ registrosCount }}</strong>
            <p>Incluye baneos relacionados e historial manual de estado. Ingresos y egresos quedan maquetados para la próxima iteración.</p>
          </button>

          <button class="camara-detail-card" type="button" @click="serviciosModalOpen = true">
            <span class="camara-detail-card__eyebrow">Servicios Asociados</span>
            <strong>{{ serviciosCount }}</strong>
            <p>{{ camara.rutas.length }} ruta{{ camara.rutas.length !== 1 ? 's' : '' }} asociada{{ camara.rutas.length !== 1 ? 's' : '' }} a la cámara.</p>
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
      :placeholders="registros.placeholders"
      @close="registrosModalOpen = false"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useSession } from '../composables/useSession';
import CamaraEstadoModal from '../components/infra/CamaraEstadoModal.vue';
import ModalAlias from '../components/infra/ModalAlias.vue';
import ModalServicios from '../components/infra/ModalServicios.vue';
import ModalRegistros from '../components/infra/ModalRegistros.vue';

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
}

interface AliasItem {
  id: number;
  nombre: string;
  created_at: string | null;
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

interface RegistrosPayload {
  contexto: RegistrosContexto | null;
  baneos: RegistrosBaneo[];
  auditoria: RegistrosAuditoria[];
  placeholders: { ingresos: string; egresos: string };
}

const route = useRoute();
const { state } = useSession();
const isAdmin = computed(() => (state.value.role ?? '').toLowerCase() === 'admin');

const camara = ref<CamaraDetail | null>(null);
const aliases = ref<AliasItem[]>([]);
const registros = ref<RegistrosPayload>({
  contexto: null,
  baneos: [],
  auditoria: [],
  placeholders: {
    ingresos: 'Pendiente de integrar registros de ingresos en una próxima iteración.',
    egresos: 'Pendiente de integrar registros de egresos en una próxima iteración.',
  },
});

const loading = ref(true);
const errorMessage = ref('');
const estadoModalOpen = ref(false);
const aliasModalOpen = ref(false);
const serviciosModalOpen = ref(false);
const registrosModalOpen = ref(false);

const serviciosCount = computed(() => new Set((camara.value?.rutas ?? []).map((ruta) => ruta.servicio_id)).size);
const registrosCount = computed(() => registros.value.baneos.length + registros.value.auditoria.length);

function statusClass(status: string): string {
  const normalized = (status || 'LIBRE').toLowerCase();
  if (normalized === 'baneada') return 'baneada';
  if (normalized === 'ocupada') return 'ocupada';
  if (normalized === 'detectada') return 'detectada';
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
    const [camaraResponse, aliasesResponse, registrosResponse] = await Promise.all([
      fetch(`/api/infra/camaras/${camaraId}`, { credentials: 'include' }),
      fetch(`/api/infra/camaras/${camaraId}/aliases`, { credentials: 'include' }),
      fetch(`/api/infra/camaras/${camaraId}/registros`, { credentials: 'include' }),
    ]);

    const camaraData = await parseResponse<{ camara: CamaraDetail }>(camaraResponse);
    const aliasesData = await parseResponse<{ aliases: AliasItem[] }>(aliasesResponse);
    const registrosData = await parseResponse<RegistrosPayload>(registrosResponse);

    camara.value = camaraData.camara;
    aliases.value = aliasesData.aliases ?? [];
    registros.value = {
      contexto: registrosData.contexto ?? null,
      baneos: registrosData.baneos ?? [],
      auditoria: registrosData.auditoria ?? [],
      placeholders: registrosData.placeholders ?? registros.value.placeholders,
    };
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error);
    camara.value = null;
    aliases.value = [];
  } finally {
    loading.value = false;
  }
}

async function handleEstadoActualizado(): Promise<void> {
  await loadCamaraDetail();
}

function showInlineError(message: string): void {
  errorMessage.value = message;
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
  background:
    radial-gradient(circle at top left, rgba(59, 130, 246, 0.12), transparent 35%),
    radial-gradient(circle at top right, rgba(16, 185, 129, 0.1), transparent 30%),
    linear-gradient(180deg, #0b1118 0%, #0f1419 100%);
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
  color: #93c5fd;
  text-decoration: none;
  margin-bottom: 18px;
}

.camara-detail-back:hover {
  color: #dbeafe;
}

.camara-detail-state {
  display: grid;
  gap: 12px;
  padding: 22px;
  border-radius: 18px;
  background: rgba(15, 23, 42, 0.74);
  border: 1px solid rgba(148, 163, 184, 0.18);
  color: var(--text);
}

.camara-detail-state.error {
  color: #fecaca;
}

.camara-detail-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
  padding: 28px;
  border-radius: 24px;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.94), rgba(10, 15, 25, 0.96)),
    linear-gradient(135deg, rgba(59, 130, 246, 0.12), transparent 50%);
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.28);
}

.camara-detail-hero__content h1 {
  margin: 8px 0 12px;
  font-size: clamp(2rem, 4vw, 3rem);
  line-height: 1.05;
  color: #f8fafc;
}

.camara-detail-hero__eyebrow {
  margin: 0;
  color: #67e8f9;
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
  color: #e2e8f0;
  background: rgba(148, 163, 184, 0.14);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.camara-detail-status.libre {
  background: rgba(16, 185, 129, 0.18);
  color: #bbf7d0;
}

.camara-detail-status.ocupada {
  background: rgba(250, 204, 21, 0.16);
  color: #fde68a;
}

.camara-detail-status.baneada {
  background: rgba(239, 68, 68, 0.18);
  color: #fecaca;
}

.camara-detail-status.detectada {
  background: rgba(59, 130, 246, 0.18);
  color: #bfdbfe;
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
  background:
    linear-gradient(160deg, rgba(15, 23, 42, 0.94), rgba(8, 12, 20, 0.98));
  border: 1px solid rgba(148, 163, 184, 0.16);
  color: var(--text);
  cursor: pointer;
  box-shadow: 0 20px 46px rgba(0, 0, 0, 0.2);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.camara-detail-card:hover {
  transform: translateY(-4px);
  border-color: rgba(96, 165, 250, 0.34);
  box-shadow: 0 28px 52px rgba(0, 0, 0, 0.28);
}

.camara-detail-card__eyebrow {
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 0.74rem;
}

.camara-detail-card strong {
  font-size: clamp(1.8rem, 3vw, 2.4rem);
  color: #f8fafc;
}

.camara-detail-card p {
  margin: 0;
  color: #cbd5e1;
  line-height: 1.5;
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