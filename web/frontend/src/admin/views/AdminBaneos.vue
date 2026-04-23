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
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue';
import { getBaneosConfig, saveBaneosConfig, getBaneosHealth, startWorker, triggerManualNotification } from '../api/admin';

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

// ─── Carga inicial de configuración ──────────────────────────────────────
onMounted(async () => {
  try {
    const cfg = await getBaneosConfig();
    form.intervaloHoras = cfg.intervalo_horas;
    form.slackChannels = cfg.slack_channels;
    form.activo = cfg.activo;
    form.horaInicio = cfg.hora_inicio;
    dbData.ultimaEjecucion = cfg.ultima_ejecucion;
    dbData.ultimoError = cfg.ultimo_error;
  } catch {
    // Error cargando configuración — el form muestra defaults
  } finally {
    cargando.value = false;
  }
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
</script>
