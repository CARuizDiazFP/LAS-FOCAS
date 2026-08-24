<!--
  Nombre de archivo: BaneosRevisionPanel.vue
  Ubicación de archivo: web/frontend/src/admin/components/BaneosRevisionPanel.vue
  Descripción: Tab "Revisión" de /admin/Servicios/Baneos — triage de Cámaras PENDIENTE_REVISION e Ingresos sin match
-->
<template>
  <!-- Acordeón: Cámaras Pendientes de Revisión -->
  <div class="card">
    <div
      class="accordion-header"
      style="display:flex;align-items:center;justify-content:space-between;cursor:pointer"
      @click="pendientes.abierto = !pendientes.abierto"
    >
      <h2 style="margin:0">🔄 Cámaras Pendientes de Revisión</h2>
      <span style="font-size:1.2rem">{{ pendientes.abierto ? '▲' : '▼' }}</span>
    </div>

    <div v-if="pendientes.abierto" style="margin-top:16px">
      <p style="color:var(--muted);font-size:0.9rem;margin-bottom:16px">
        Cámaras auto-registradas por el listener de ingresos que requieren
        aprobación o clasificación como alias de otra cámara.
      </p>

      <div v-if="pendientes.cargando" style="color:var(--muted)">Cargando…</div>
      <div v-else-if="pendientes.error" style="color:var(--error)">{{ pendientes.error }}</div>
      <div v-else-if="pendientes.lista.length === 0" style="color:var(--muted)">
        No hay cámaras pendientes de revisión.
      </div>
      <table v-else class="table" style="width:100%">
        <thead>
          <tr>
            <th>ID</th>
            <th>Nombre</th>
            <th>Registrada</th>
            <th>Acciones</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="cam in pendientes.lista" :key="cam.id">
            <td>{{ cam.id }}</td>
            <td>{{ cam.nombre }}</td>
            <td style="font-size:0.85rem;color:var(--muted)">{{ cam.last_update ? new Date(cam.last_update).toLocaleString('es-AR') : '—' }}</td>
            <td style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              <button
                class="btn primary"
                style="padding:4px 10px;font-size:0.82rem"
                :disabled="pendientes.accionando === cam.id"
                @click="handleAprobar(cam.id)"
              >
                ✅ Aprobar
              </button>
              <button
                class="btn"
                style="padding:4px 10px;font-size:0.82rem"
                :disabled="pendientes.accionando === cam.id"
                @click="toggleFormAlias(cam.id)"
              >
                🔗 Convertir en Alias
              </button>
              <button
                class="btn"
                style="padding:4px 10px;font-size:0.82rem;background:var(--warning);color:#fff;border-color:transparent"
                :disabled="pendientes.accionando === cam.id"
                @click="toggleFormCanon(cam.id, cam.nombre)"
              >
                🏷️ Definir Nombre Canón
              </button>
              <button
                class="btn"
                style="padding:4px 10px;font-size:0.82rem;background:var(--error);color:#fff;border-color:transparent"
                :disabled="pendientes.accionando === cam.id"
                @click="toggleEliminar(cam.id)"
              >
                🗑️ Eliminar
              </button>
              <!-- Formulario inline para convertir en alias -->
              <div v-if="pendientes.aliasFormId === cam.id" style="display:flex;gap:8px;align-items:center;margin-top:6px;width:100%">
                <input
                  v-model.number="pendientes.aliasDestinoId"
                  type="number"
                  placeholder="ID de cámara destino"
                  style="width:180px"
                />
                <button
                  class="btn primary"
                  style="padding:4px 10px;font-size:0.82rem"
                  :disabled="!pendientes.aliasDestinoId || pendientes.accionando === cam.id"
                  @click="handleConvertirAlias(cam.id)"
                >
                  Confirmar
                </button>
                <button
                  class="btn"
                  style="padding:4px 10px;font-size:0.82rem"
                  @click="pendientes.aliasFormId = null"
                >
                  Cancelar
                </button>
              </div>
              <!-- Formulario inline para dar de alta como cámara canónica -->
              <div v-if="pendientes.canonFormId === cam.id" style="display:flex;gap:8px;align-items:center;margin-top:6px;width:100%">
                <input
                  v-model="pendientes.canonNombre"
                  type="text"
                  placeholder="Nombre canónico oficial"
                  style="flex:1;min-width:220px"
                />
                <button
                  class="btn primary"
                  style="padding:4px 10px;font-size:0.82rem"
                  :disabled="!pendientes.canonNombre.trim() || pendientes.accionando === cam.id"
                  @click="handleDarDeAlta(cam.id)"
                >
                  Confirmar Alta
                </button>
                <button
                  class="btn"
                  style="padding:4px 10px;font-size:0.82rem"
                  @click="pendientes.canonFormId = null"
                >
                  Cancelar
                </button>
              </div>
              <!-- Confirmación de eliminación -->
              <div v-if="pendientes.eliminandoId === cam.id" style="display:flex;gap:8px;align-items:center;margin-top:6px;width:100%;background:color-mix(in srgb, var(--error) 15%, transparent);padding:8px;border-radius:6px">
                <span style="font-size:0.85rem;color:var(--error);flex:1">
                  ⚠️ ¿Eliminar permanentemente <strong>{{ cam.nombre }}</strong>? Esta acción no se puede deshacer.
                </span>
                <button
                  class="btn"
                  style="padding:4px 10px;font-size:0.82rem;background:var(--error);color:#fff;border-color:transparent"
                  :disabled="pendientes.accionando === cam.id"
                  @click="handleEliminar(cam.id)"
                >
                  Sí, eliminar
                </button>
                <button
                  class="btn"
                  style="padding:4px 10px;font-size:0.82rem"
                  @click="pendientes.eliminandoId = null"
                >
                  Cancelar
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="msg" :class="{ visible: !!pendientes.msg, ok: !pendientes.msgError, err: pendientes.msgError }" style="margin-top:12px">
        {{ pendientes.msg }}
      </div>
    </div>
  </div>

  <!-- Acordeón: Ingresos sin match -->
  <div class="card" style="margin-top:24px">
    <div
      class="accordion-header"
      style="display:flex;align-items:center;justify-content:space-between;cursor:pointer"
      @click="sinMatch.abierto = !sinMatch.abierto"
    >
      <h2 style="margin:0">🔍 Ingresos sin match</h2>
      <span style="font-size:1.2rem">{{ sinMatch.abierto ? '▲' : '▼' }}</span>
    </div>

    <div v-if="sinMatch.abierto" style="margin-top:16px">
      <p style="color:var(--muted);font-size:0.9rem;margin-bottom:16px">
        Casos donde un técnico (Slack) o una ubicación de tracking no matchearon contra el
        inventario. No son cámaras — es información para revisar manualmente y mejorar el regex de
        búsqueda. El ingreso del técnico nunca se bloqueó por esto.
      </p>

      <label style="display:flex;align-items:center;gap:6px;font-size:0.85rem;margin-bottom:12px;cursor:pointer">
        <input type="checkbox" v-model="sinMatch.soloPendientes" @change="cargarSinMatch" />
        Mostrar sólo no revisados
      </label>

      <div v-if="sinMatch.cargando" style="color:var(--muted)">Cargando…</div>
      <div v-else-if="sinMatch.error" style="color:var(--error)">{{ sinMatch.error }}</div>
      <div v-else-if="sinMatch.lista.length === 0" style="color:var(--muted)">
        No hay casos {{ sinMatch.soloPendientes ? 'sin revisar' : 'registrados' }}.
      </div>
      <table v-else class="table" style="width:100%">
        <thead>
          <tr>
            <th>Texto original</th>
            <th>Origen</th>
            <th>Contexto</th>
            <th>Registrado</th>
            <th>Acciones</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="caso in sinMatch.lista" :key="caso.id" :style="caso.revisado ? 'opacity:0.55' : ''">
            <td>{{ caso.texto_original }}</td>
            <td>{{ caso.origen === 'slack' ? '💬 Slack' : caso.origen === 'excel_camaras' ? '📊 Excel' : '📄 Tracking' }}</td>
            <td style="font-size:0.85rem;color:var(--muted)">{{ caso.contexto || '—' }}</td>
            <td style="font-size:0.85rem;color:var(--muted)">{{ caso.created_at ? new Date(caso.created_at).toLocaleString('es-AR') : '—' }}</td>
            <td>
              <button
                v-if="!caso.revisado"
                class="btn"
                style="padding:4px 10px;font-size:0.82rem"
                :disabled="sinMatch.accionando === caso.id"
                @click="handleMarcarRevisado(caso.id)"
              >
                ✅ Marcar revisado
              </button>
              <span v-else style="font-size:0.82rem;color:var(--muted)">Revisado</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, onMounted } from 'vue';

import { getCamarasPendientes, aprobarCamara, convertirAlias, darDeAltaComoCanon, eliminarCamaraPendiente, getIngresosSinMatch, marcarRevisadoIngresoSinMatch, type CamaraPendiente, type IngresoSinMatch } from '../api/admin';

// ─── Estado cámaras pendientes de revisión ────────────────────────────────
const pendientes = reactive({
  abierto: false,
  cargando: false,
  lista: [] as CamaraPendiente[],
  error: '' as string,
  accionando: null as number | null,
  aliasFormId: null as number | null,
  aliasDestinoId: null as number | null,
  canonFormId: null as number | null,
  canonNombre: '' as string,
  eliminandoId: null as number | null,
  msg: '',
  msgError: false,
});

// ─── Estado ingresos sin match ────────────────────────────────────────────
const sinMatch = reactive({
  abierto: false,
  cargando: false,
  soloPendientes: true,
  lista: [] as IngresoSinMatch[],
  error: '' as string,
  accionando: null as number | null,
});

onMounted(() => {
  void cargarPendientes();
  void cargarSinMatch();
});

// ─── Cámaras pendientes de revisión ──────────────────────────────────────
async function cargarPendientes() {
  pendientes.cargando = true;
  pendientes.error = '';
  try {
    pendientes.lista = await getCamarasPendientes();
  } catch (e: unknown) {
    pendientes.error = e instanceof Error ? e.message : 'Error cargando pendientes.';
  } finally {
    pendientes.cargando = false;
  }
}

function toggleFormAlias(id: number) {
  if (pendientes.aliasFormId === id) {
    pendientes.aliasFormId = null;
  } else {
    pendientes.aliasFormId = id;
    pendientes.aliasDestinoId = null;
    pendientes.canonFormId = null;
    pendientes.eliminandoId = null;
  }
}

async function handleAprobar(id: number) {
  pendientes.accionando = id;
  pendientes.msg = '';
  try {
    await aprobarCamara(id);
    pendientes.msg = `Cámara #${id} aprobada correctamente.`;
    pendientes.msgError = false;
    await cargarPendientes();
  } catch (e: unknown) {
    pendientes.msg = e instanceof Error ? e.message : 'Error al aprobar la cámara.';
    pendientes.msgError = true;
  } finally {
    pendientes.accionando = null;
  }
}

async function handleConvertirAlias(id: number) {
  if (!pendientes.aliasDestinoId) return;
  pendientes.accionando = id;
  pendientes.msg = '';
  try {
    await convertirAlias(id, pendientes.aliasDestinoId);
    pendientes.msg = `Cámara #${id} convertida en alias correctamente.`;
    pendientes.msgError = false;
    pendientes.aliasFormId = null;
    await cargarPendientes();
  } catch (e: unknown) {
    pendientes.msg = e instanceof Error ? e.message : 'Error al convertir alias.';
    pendientes.msgError = true;
  } finally {
    pendientes.accionando = null;
  }
}

function toggleFormCanon(id: number, nombreTecnico: string) {
  if (pendientes.canonFormId === id) {
    pendientes.canonFormId = null;
  } else {
    pendientes.canonFormId = id;
    pendientes.aliasFormId = null; // cerrar el otro form si estaba abierto
    pendientes.eliminandoId = null;
    pendientes.canonNombre = nombreTecnico;
  }
}

function toggleEliminar(id: number) {
  if (pendientes.eliminandoId === id) {
    pendientes.eliminandoId = null;
  } else {
    pendientes.eliminandoId = id;
    pendientes.aliasFormId = null;
    pendientes.canonFormId = null;
  }
}

async function handleEliminar(id: number) {
  pendientes.accionando = id;
  pendientes.msg = '';
  try {
    await eliminarCamaraPendiente(id);
    pendientes.msg = `Cámara #${id} eliminada permanentemente.`;
    pendientes.msgError = false;
    pendientes.eliminandoId = null;
    await cargarPendientes();
  } catch (e: unknown) {
    pendientes.msg = e instanceof Error ? e.message : 'Error al eliminar la cámara.';
    pendientes.msgError = true;
  } finally {
    pendientes.accionando = null;
  }
}

async function handleDarDeAlta(id: number) {
  const nombre = pendientes.canonNombre.trim();
  if (!nombre) return;
  pendientes.accionando = id;
  pendientes.msg = '';
  try {
    await darDeAltaComoCanon(id, nombre);
    const nombreOriginal = pendientes.lista.find(c => c.id === id)?.nombre ?? '';
    const conAlias = nombreOriginal && nombreOriginal.toLowerCase() !== nombre.toLowerCase();
    pendientes.msg = conAlias
      ? `Cámara #${id} dada de alta como "${nombre}". Nombre original "${nombreOriginal}" guardado como alias.`
      : `Cámara #${id} dada de alta como "${nombre}" correctamente.`;
    pendientes.msgError = false;
    pendientes.canonFormId = null;
    await cargarPendientes();
  } catch (e: unknown) {
    pendientes.msg = e instanceof Error ? e.message : 'Error al dar de alta la cámara.';
    pendientes.msgError = true;
  } finally {
    pendientes.accionando = null;
  }
}

// ─── Ingresos sin match ────────────────────────────────────────────────────
async function cargarSinMatch() {
  sinMatch.cargando = true;
  sinMatch.error = '';
  try {
    sinMatch.lista = await getIngresosSinMatch(sinMatch.soloPendientes ? false : undefined);
  } catch (e: unknown) {
    sinMatch.error = e instanceof Error ? e.message : 'Error cargando ingresos sin match.';
  } finally {
    sinMatch.cargando = false;
  }
}

async function handleMarcarRevisado(id: number) {
  sinMatch.accionando = id;
  try {
    await marcarRevisadoIngresoSinMatch(id);
    await cargarSinMatch();
  } catch {
    // El botón vuelve a habilitarse; el usuario puede reintentar.
  } finally {
    sinMatch.accionando = null;
  }
}
</script>
