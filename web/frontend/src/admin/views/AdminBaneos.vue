<!--
  Nombre de archivo: AdminBaneos.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminBaneos.vue
  Descripción: Vista /admin/Servicios/Baneos — config del worker de notificaciones Slack y estado del worker
-->
<template>
  <h1>Servicios — Notificaciones de Baneos</h1>
  <p class="section-subtitle">
    Configuración del worker que envía reportes periódicos de cámaras baneadas a Slack.
  </p>

  <div v-if="cargando" style="color:var(--muted);padding:24px 0">Cargando configuración…</div>

  <div v-else class="two-col">

    <!-- Card: Configuración -->
    <div class="card">
      <h2>Configuración</h2>

      <form @submit.prevent="handleGuardar">
        <label>Intervalo de ejecución (horas)</label>
        <input
          v-model.number="form.intervaloHoras"
          type="number"
          min="1"
          required
        />
        <p class="hint">Cada cuántas horas se envía el reporte a Slack.</p>

        <label>Hora de inicio del ciclo <span style="color:var(--muted);font-size:0.8rem">(GMT -3)</span></label>
        <select v-model="form.horaInicio">
          <option :value="null">Sin horario fijo — comenzar de inmediato</option>
          <option v-for="h in 24" :key="h - 1" :value="h - 1">
            {{ String(h - 1).padStart(2, '0') }}:00 hs
          </option>
        </select>
        <p class="hint">
          Ancla el primer envío a esta hora (zona GMT -3). Con frecuencia 24 h y hora 07:00 el envío
          ocurre todos los días a las 7 am. Con frecuencia 12 h ocurrirá a las 07:00 y las 19:00.
        </p>

        <label>Canales o IDs de Slack</label>
        <textarea
          v-model="form.slackChannels"
          rows="3"
          placeholder="C08UB8ML3LP,#canal-secundario"
          style="resize:vertical"
        />
        <p class="hint">
          Separar múltiples destinos con coma. Se aceptan nombres con
          <strong>#</strong> o IDs de Slack tipo <strong>C08UB8ML3LP</strong>.
          Para canales privados o bots reinstalados, preferir el ID.
        </p>

        <div class="toggle-row">
          <label class="toggle-wrap">
            <input type="checkbox" v-model="form.activo" />
            <span class="toggle-slider" />
          </label>
          <span>Servicio activo</span>
        </div>

        <button type="submit" class="btn primary" :disabled="form.loading">
          {{ form.loading ? 'Guardando…' : 'Guardar Configuración' }}
        </button>

        <div class="msg" :class="{ visible: !!form.msg, ok: !form.error, err: form.error }">
          {{ form.msg }}
        </div>
      </form>
    </div>

    <!-- Card: Estado del Worker -->
    <div class="card">
      <h2>Estado del Worker</h2>

      <!-- Badge de estado -->
      <div style="text-align:center;padding:20px 0">
        <span class="status-badge" :class="health.estadoClase">
          <span class="status-dot" :class="health.estadoClase" />
          {{ health.etiqueta }}
        </span>
      </div>

      <!-- Detalles tras verificar -->
      <template v-if="health.verificado">
        <div class="info-row">
          <span class="info-label">Estado</span>
          <span class="info-value">{{ health.status || '—' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">Intervalo actual</span>
          <span class="info-value">{{ health.intervalo ? health.intervalo + 'h' : '—' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">Última ejecución</span>
          <span class="info-value">{{ health.lastRun || 'Nunca' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">Último error</span>
          <span class="info-value">{{ health.lastError || 'Ninguno' }}</span>
        </div>
      </template>

      <!-- Datos de DB (siempre visibles) -->
      <div class="info-row" style="margin-top:16px">
        <span class="info-label">Última ejecución (DB)</span>
        <span class="info-value">{{ dbData.ultimaEjecucion || 'Nunca' }}</span>
      </div>
      <p v-if="dbData.ultimoError" style="color:var(--error);font-size:0.85rem;margin-top:6px">
        ⚠ Último error: {{ dbData.ultimoError }}
      </p>

      <button
        type="button"
        class="btn primary"
        style="width:100%;margin-top:16px"
        :disabled="health.cargando"
        @click="verificarHealth"
      >
        {{ health.cargando ? 'Verificando…' : 'Verificar Estado' }}
      </button>

      <!-- Botón Iniciar Worker — visible solo cuando está offline o desconocido -->
      <template v-if="health.verificado && health.estadoClase !== 'ok'">
        <div style="margin-top:12px;border-top:1px solid var(--border);padding-top:12px">
          <p style="font-size:0.85rem;color:var(--muted);margin-bottom:8px">
            El worker está detenido o no responde.
          </p>
          <button
            type="button"
            class="btn"
            style="width:100%;background:var(--warning,#d97706);color:#fff"
            :disabled="workerStart.loading"
            @click="handleStartWorker"
          >
            {{ workerStart.loading ? 'Iniciando…' : '▶ Iniciar Worker' }}
          </button>
          <div
            class="msg"
            :class="{ visible: !!workerStart.msg, ok: !workerStart.error, err: workerStart.error }"
            style="margin-top:8px"
          >
            {{ workerStart.msg }}
          </div>
        </div>
      </template>
    </div>

  </div>

  <!-- Card: Envío Manual -->
  <div v-if="!cargando" class="card" style="margin-top:24px">
    <h2>Envío Manual</h2>
    <p style="color:var(--muted);font-size:0.9rem;margin-bottom:16px">
      Dispara el reporte de cámaras baneadas de forma inmediata, fuera del ciclo programado.
      Solo funciona si el worker está corriendo.
    </p>
    <button
      type="button"
      class="btn primary"
      :disabled="trigger.loading"
      @click="handleTrigger"
    >
      {{ trigger.loading ? 'Enviando…' : '📤 Enviar Aviso Ahora' }}
    </button>
    <div class="msg" :class="{ visible: !!trigger.msg, ok: !trigger.error, err: trigger.error }" style="margin-top:10px">
      {{ trigger.msg }}
    </div>
  </div>

  <!-- Card: Monitor de Ingresos -->
  <div v-if="!cargando" class="card" style="margin-top:24px">
    <h2>🎧 Monitor de Ingresos</h2>
    <p style="color:var(--muted);font-size:0.9rem;margin-bottom:16px">
      Escucha en tiempo real los formularios de ingreso técnico enviados en un canal de Slack.
      Al recibir un mensaje con el campo <em>Cámara:</em>, responde en el hilo con el estado de baneo.
      Requiere que <code>SLACK_APP_TOKEN</code> esté configurado en el worker.
    </p>
    <form @submit.prevent="handleGuardarListener" style="display:flex;flex-direction:column;gap:16px;max-width:480px">

      <!-- Canal de Slack -->
      <div>
        <label style="display:block;margin-bottom:4px;font-weight:500">Canal de Slack (ID o #nombre)</label>
        <input
          v-model="listener.canalId"
          type="text"
          placeholder="Ej: C0123ABCDEF"
          class="input"
          style="width:100%"
        />
      </div>

      <!-- Toggle: Filtrar mensajes de usuario (solo_workflows) -->
      <div class="toggle-row" style="flex-direction:column;align-items:flex-start;gap:6px">
        <div style="display:flex;align-items:center;gap:10px">
          <label class="toggle-wrap">
            <input type="checkbox" v-model="listener.soloWorkflows" />
            <span class="toggle-slider" />
          </label>
          <span style="font-weight:500">Filtrar mensajes de usuario</span>
          <span class="badge" :class="listener.soloWorkflows ? 'ok' : 'offline'">
            {{ listener.soloWorkflows ? 'Activo' : 'Inactivo' }}
          </span>
        </div>
        <p style="color:var(--muted);font-size:0.82rem;margin:0">
          Si está activo, el bot solo responde a mensajes enviados por Workflows de Slack con los IDs configurados abajo.
          Desactivalo para modo Dev (responde a cualquier mensaje de texto).
        </p>
      </div>

      <!-- Workflow IDs -->
      <div>
        <label style="display:block;margin-bottom:4px;font-weight:500">
          Workflow IDs permitidos
          <span v-if="!listener.soloWorkflows" style="color:var(--muted);font-weight:400;font-size:0.82rem"> (inactivo — filtro desactivado)</span>
        </label>
        <textarea
          v-model="listener.workflowIds"
          rows="3"
          :disabled="!listener.soloWorkflows"
          placeholder="Wf0B0KJF68BS,Wf0OTRA1ID2"
          style="resize:vertical;width:100%;opacity:1;transition:opacity 0.2s"
          :style="{ opacity: listener.soloWorkflows ? '1' : '0.45' }"
        />
        <p style="color:var(--muted);font-size:0.82rem;margin:4px 0 0">
          IDs de Workflow de Slack separados por coma. Dejá vacío para aceptar cualquier Workflow.
          El ID se ve en la URL del Workflow en la configuración de Slack.
        </p>
      </div>

      <!-- Toggle: Activar monitor -->
      <div class="toggle-row" style="align-items:center;gap:10px">
        <label class="toggle-wrap">
          <input type="checkbox" v-model="listener.activo" />
          <span class="toggle-slider" />
        </label>
        <span style="font-weight:500">Activar monitor</span>
        <span class="badge" :class="listener.activo ? 'ok' : 'offline'">
          {{ listener.activo ? 'Activo' : 'Inactivo' }}
        </span>
      </div>

      <button type="submit" class="btn primary" :disabled="listener.loading">
        {{ listener.loading ? 'Guardando…' : '💾 Guardar Configuración' }}
      </button>
      <div class="msg" :class="{ visible: !!listener.msg, ok: !listener.error, err: listener.error }">
        {{ listener.msg }}
      </div>
      <div v-if="listener.ultimoError" style="color:var(--danger);font-size:0.85rem;margin-top:4px">
        Último error: {{ listener.ultimoError }}
      </div>
    </form>
  </div>

  <!-- Acordeón: Cámaras Pendientes de Revisión -->
  <div v-if="!cargando" class="card" style="margin-top:24px">
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
      <div v-else-if="pendientes.error" style="color:var(--danger)">{{ pendientes.error }}</div>
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
            </td>
          </tr>
        </tbody>
      </table>

      <div class="msg" :class="{ visible: !!pendientes.msg, ok: !pendientes.msgError, err: pendientes.msgError }" style="margin-top:12px">
        {{ pendientes.msg }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue';
import { getBaneosConfig, saveBaneosConfig, getBaneosHealth, startWorker, triggerManualNotification, getListenerConfig, saveListenerConfig, getCamarasPendientes, aprobarCamara, convertirAlias, type CamaraPendiente } from '../api/admin';

// ─── Estado del formulario ────────────────────────────────────────────────
const form = reactive({
  intervaloHoras: 4,
  slackChannels: '',
  activo: true,
  horaInicio: null as number | null,
  loading: false,
  msg: '',
  error: false,
});

const dbData = reactive({
  ultimaEjecucion: null as string | null,
  ultimoError: null as string | null,
});

const cargando = ref(true);

// ─── Estado del health check ──────────────────────────────────────────────
const health = reactive({
  estadoClase: 'unknown' as 'ok' | 'offline' | 'unknown',
  etiqueta: 'Sin verificar',
  status: '',
  intervalo: null as number | null,
  lastRun: '',
  lastError: '',
  verificado: false,
  cargando: false,
});

// ─── Estado start worker ──────────────────────────────────────────────────
const workerStart = reactive({
  loading: false,
  msg: '',
  error: false,
});

// ─── Estado envío manual ──────────────────────────────────────────────────
const trigger = reactive({
  loading: false,
  msg: '',
  error: false,
});

// ─── Estado monitor de ingresos ───────────────────────────────────────────
const listener = reactive({
  activo: false,
  canalId: '',
  workflowIds: '',
  soloWorkflows: false,
  ultimoError: null as string | null,
  loading: false,
  msg: '',
  error: false,
});

// ─── Estado cámaras pendientes de revisión ────────────────────────────────
const pendientes = reactive({
  abierto: false,
  cargando: false,
  lista: [] as CamaraPendiente[],
  error: '' as string,
  accionando: null as number | null,
  aliasFormId: null as number | null,
  aliasDestinoId: null as number | null,
  msg: '',
  msgError: false,
});

// ─── Carga inicial de configuración ──────────────────────────────────────
onMounted(async () => {
  try {
    const [cfg, lstCfg] = await Promise.all([getBaneosConfig(), getListenerConfig()]);
    form.intervaloHoras = cfg.intervalo_horas;
    form.slackChannels = cfg.slack_channels;
    form.activo = cfg.activo;
    form.horaInicio = cfg.hora_inicio;
    dbData.ultimaEjecucion = cfg.ultima_ejecucion;
    dbData.ultimoError = cfg.ultimo_error;
    listener.activo = lstCfg.activo;
    listener.canalId = lstCfg.canal_id;
    listener.workflowIds = lstCfg.workflow_ids ?? '';
    listener.soloWorkflows = lstCfg.solo_workflows ?? false;
    listener.ultimoError = lstCfg.ultimo_error;
  } catch {
    // Error cargando configuración — el form muestra defaults
  } finally {
    cargando.value = false;
  }
  // Cargar lista de pendientes en background
  void cargarPendientes();
});

// ─── Guardar configuración ────────────────────────────────────────────────
async function handleGuardar() {
  form.loading = true;
  form.msg = '';
  try {
    await saveBaneosConfig(form.intervaloHoras, form.slackChannels, form.activo, form.horaInicio);
    form.msg = 'Configuración guardada correctamente.';
    form.error = false;
  } catch (e: unknown) {
    form.msg = e instanceof Error ? e.message : 'Error guardando configuración.';
    form.error = true;
  } finally {
    form.loading = false;
  }
}

// ─── Verificar estado del worker ──────────────────────────────────────────
async function verificarHealth() {
  health.cargando = true;
  try {
    const data = await getBaneosHealth();
    const isOk = data.status === 'ok';
    health.estadoClase = isOk ? 'ok' : 'offline';
    health.etiqueta = isOk ? 'Activo' : (data.status || 'Inactivo');
    health.status = data.status;
    health.intervalo = data.intervalo_horas ?? null;
    health.lastRun = data.last_run ?? '';
    health.lastError = data.last_error ?? '';
    health.verificado = true;
  } catch {
    health.estadoClase = 'offline';
    health.etiqueta = 'Error de conexión';
    health.verificado = true;
  } finally {
    health.cargando = false;
  }
}

// ─── Iniciar worker detenido ──────────────────────────────────────────────
async function handleStartWorker() {
  workerStart.loading = true;
  workerStart.msg = '';
  try {
    const res = await startWorker();
    workerStart.msg = res.status === 'already_running'
      ? 'El worker ya estaba corriendo.'
      : `Worker iniciado (${res.container_status ?? 'running'}).`;
    workerStart.error = false;
    // Refrescar estado inmediatamente
    await verificarHealth();
  } catch (e: unknown) {
    workerStart.msg = e instanceof Error ? e.message : 'Error iniciando el worker.';
    workerStart.error = true;
  } finally {
    workerStart.loading = false;
  }
}

// ─── Envío manual ─────────────────────────────────────────────────────────
async function handleTrigger() {
  trigger.loading = true;
  trigger.msg = '';
  try {
    await triggerManualNotification();
    trigger.msg = 'Aviso enviado. El reporte se está procesando en segundo plano.';
    trigger.error = false;
  } catch (e: unknown) {
    trigger.msg = e instanceof Error ? e.message : 'Error enviando aviso manual.';
    trigger.error = true;
  } finally {
    trigger.loading = false;
  }
}

// ─── Monitor de ingresos ───────────────────────────────────────────────────
async function handleGuardarListener() {
  listener.loading = true;
  listener.msg = '';
  try {
    await saveListenerConfig(listener.activo, listener.canalId, listener.workflowIds, listener.soloWorkflows);
    listener.msg = 'Configuración del monitor guardada.';
    listener.error = false;
  } catch (e: unknown) {
    listener.msg = e instanceof Error ? e.message : 'Error guardando configuración.';
    listener.error = true;
  } finally {
    listener.loading = false;
  }
}

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
</script>
