<!--
  Nombre de archivo: ValidarDatosCromoView.vue
  Ubicación de archivo: web/frontend/src/views/ValidarDatosCromoView.vue
  Descripción: Validar datos DB Cromo (Tool Kit) — diagnóstico en vivo de un elemento Cromo por n_id, mismo parseo que la ingesta, sin tocar la base de datos local
-->
<template>
  <section class="validar-cromo">
    <header class="validar-cromo__header">
      <h1>Validar datos DB Cromo</h1>
      <p class="section-subtitle">
        Consultá un <code>n_id</code> directamente contra Cromo y mirá cómo lo interpretaría la
        ingesta — árbol completo de cables, tubos, pelos y fusiones. 100% en vivo: nunca se toca la
        base de datos local, ni siquiera en lectura. Los servicios de cada pelo se muestran crudos,
        sin matchear contra el maestro de servicios.
      </p>
    </header>

    <hr class="noc-rule" />

    <article class="card validar-cromo__card">
      <form class="validar-cromo__form" @submit.prevent="onBuscar">
        <div class="validar-cromo__input-row">
          <input
            v-model="nIdTexto"
            type="text"
            inputmode="numeric"
            placeholder="n_id de Cromo"
            autocomplete="off"
          />
          <button class="btn primary" type="submit" :disabled="buscando || !nIdValido">
            <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
            {{ buscando ? 'Consultando…' : 'Validar' }}
          </button>
        </div>
      </form>

      <p v-if="error" class="msg err visible">{{ error }}</p>
    </article>

    <template v-if="resultado">
      <article class="card validar-cromo__card">
        <header class="validar-cromo__resultado-header">
          <h2>{{ resultado.tipo_objeto }} <code>{{ resultado.n_id }}</code></h2>
          <span class="validar-cromo__chip">clase {{ resultado.clase ?? '—' }}</span>
        </header>

        <dl class="validar-cromo__meta">
          <div><dt>ID legado</dt><dd>{{ resultado.id_legacy || '—' }}</dd></div>
          <div><dt>Código de modelo</dt><dd>{{ resultado.codigo_modelo || '—' }}</dd></div>
          <div v-if="resultado.latitud != null"><dt>Latitud</dt><dd>{{ resultado.latitud }}</dd></div>
          <div v-if="resultado.longitud != null"><dt>Longitud</dt><dd>{{ resultado.longitud }}</dd></div>
        </dl>

        <div class="validar-cromo__destacado">
          <div>
            <span class="validar-cromo__destacado-etiqueta">Nombre</span>
            <p class="validar-cromo__destacado-valor">{{ resultado.nombre || '—' }}</p>
          </div>
          <div>
            <span class="validar-cromo__destacado-etiqueta">Notas</span>
            <p class="validar-cromo__destacado-valor">{{ resultado.notas || 'Sin notas.' }}</p>
          </div>
        </div>
      </article>

      <article v-if="resultado.errores_parseo.length > 0" class="card validar-cromo__card is-warning">
        <header class="validar-cromo__resultado-header">
          <h2>Errores de parseo</h2>
          <span class="validar-cromo__chip is-warn">{{ resultado.errores_parseo.length }}</span>
        </header>
        <ul class="validar-cromo__lista-errores">
          <li v-for="(err, idx) in resultado.errores_parseo" :key="idx">
            <code v-if="err.n_id">{{ err.n_id }}</code> {{ err.motivo }}
          </li>
        </ul>
      </article>

      <article class="card validar-cromo__card">
        <header class="validar-cromo__resultado-header">
          <h2>Cables asociados</h2>
          <span class="validar-cromo__chip">{{ resultado.cables.length }}</span>
        </header>
        <p v-if="resultado.cables.length === 0" class="hint">Sin cables asociados.</p>
        <table v-else class="tabla-topologia">
          <thead>
            <tr><th>ID</th><th>Nombre</th><th>Capacidad</th><th>Extremo A</th><th>Extremo B</th></tr>
          </thead>
          <tbody>
            <tr v-for="c in resultado.cables" :key="c.n_id">
              <td>{{ c.n_id }}</td>
              <td>{{ c.nombre || '—' }}</td>
              <td>{{ c.capacidad || '—' }}</td>
              <td>{{ c.extremo_a_nombre || c.extremo_a_n_id || '—' }}</td>
              <td>{{ c.extremo_b_nombre || c.extremo_b_n_id || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </article>

      <article class="card validar-cromo__card">
        <header class="validar-cromo__resultado-header">
          <h2>Empalmes (fusiones)</h2>
          <span class="validar-cromo__chip">{{ resultado.fusiones.length }}</span>
        </header>
        <p v-if="resultado.fusiones.length === 0" class="hint">Sin empalmes asociados.</p>
        <table v-else class="tabla-topologia">
          <thead>
            <tr><th>ID</th><th>Nombre del par</th><th>Pelo A</th><th>Pelo B</th></tr>
          </thead>
          <tbody>
            <tr v-for="f in resultado.fusiones" :key="f.n_id">
              <td>{{ f.n_id }}</td>
              <td>{{ f.nombre_par || '—' }}</td>
              <td>{{ f.pelo_a_n_id ?? '—' }}</td>
              <td>{{ f.pelo_b_n_id ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </article>

      <article class="card validar-cromo__card">
        <header class="validar-cromo__resultado-header">
          <h2>Tubos y pelos</h2>
          <span class="validar-cromo__chip">{{ resultado.tubos.length }} tubo(s)</span>
        </header>
        <p v-if="resultado.tubos.length === 0" class="hint">Sin tubos asociados.</p>
        <div v-else class="validar-cromo__tubos">
          <div v-for="t in resultado.tubos" :key="t.n_id" class="validar-cromo__tubo">
            <header>
              <strong>Buffer {{ t.nombre_color || t.n_id }}</strong>
              <span class="hint">{{ pelosDelTubo(t.n_id).length }} pelo(s)</span>
            </header>
            <table v-if="pelosDelTubo(t.n_id).length > 0" class="tabla-topologia">
              <thead>
                <tr><th>ID</th><th>N° pelo</th><th>Color</th><th>Servicio (crudo)</th></tr>
              </thead>
              <tbody>
                <tr v-for="p in pelosDelTubo(t.n_id)" :key="p.n_id">
                  <td>{{ p.n_id }}</td>
                  <td>{{ p.numero_pelo || '—' }}</td>
                  <td>{{ p.color || '—' }}</td>
                  <td>{{ p.servicio_raw || '—' }}<span v-if="p.servicio_numero"> ({{ p.servicio_numero }})</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="pelosSueltos.length > 0" class="validar-cromo__tubo">
            <header><strong>Pelos sin tubo propio en esta consulta</strong></header>
            <table class="tabla-topologia">
              <thead>
                <tr><th>ID</th><th>N° pelo</th><th>Color</th><th>Servicio (crudo)</th></tr>
              </thead>
              <tbody>
                <tr v-for="p in pelosSueltos" :key="p.n_id">
                  <td>{{ p.n_id }}</td>
                  <td>{{ p.numero_pelo || '—' }}</td>
                  <td>{{ p.color || '—' }}</td>
                  <td>{{ p.servicio_raw || '—' }}<span v-if="p.servicio_numero"> ({{ p.servicio_numero }})</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </article>

      <details class="validar-cromo__crudo">
        <summary>Ver payload crudo</summary>
        <pre>{{ JSON.stringify(resultado.payload_raw, null, 2) }}</pre>
      </details>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';

import { ApiError } from '../api/client';
import { validarElementoCromo, type CromoPeloValidacion, type CromoValidacionDatos } from '../api/cromo';

const nIdTexto = ref('');
const buscando = ref(false);
const error = ref('');
const resultado = ref<CromoValidacionDatos | null>(null);

const nIdValido = computed(() => /^\d+$/.test(nIdTexto.value.trim()));

const pelosSueltos = computed<CromoPeloValidacion[]>(() => {
  if (!resultado.value) return [];
  const idsTubos = new Set(resultado.value.tubos.map((t) => t.n_id));
  return resultado.value.pelos.filter((p) => p.tubo_n_id == null || !idsTubos.has(p.tubo_n_id));
});

function pelosDelTubo(tuboNId: number): CromoPeloValidacion[] {
  return resultado.value?.pelos.filter((p) => p.tubo_n_id === tuboNId) ?? [];
}

async function onBuscar(): Promise<void> {
  if (!nIdValido.value) return;
  const nId = Number(nIdTexto.value.trim());

  buscando.value = true;
  error.value = '';
  resultado.value = null;

  try {
    resultado.value = await validarElementoCromo(nId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      error.value = `No existe un elemento con n_id=${nId} en Cromo.`;
    } else if (e instanceof ApiError && e.status === 502) {
      error.value = 'Cromo no respondió. Probá de nuevo en un momento.';
    } else {
      error.value = e instanceof Error ? e.message : 'Error consultando Cromo.';
    }
  } finally {
    buscando.value = false;
  }
}
</script>

<style scoped>
.validar-cromo {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px 26px 30px;
}

.validar-cromo__header h1 {
  margin: 4px 0 6px;
}

.validar-cromo .hint {
  font-size: 0.8rem;
  color: var(--muted);
}

.validar-cromo__card {
  padding: 18px 20px;
}

.validar-cromo__card.is-warning {
  border: 1px solid color-mix(in srgb, var(--warning) 40%, transparent);
}

.validar-cromo__form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.validar-cromo__input-row {
  display: flex;
  gap: 10px;
}

.validar-cromo__input-row input {
  flex: 1;
  max-width: 360px;
}

.validar-cromo__resultado-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.validar-cromo__resultado-header h2 {
  font-size: 15px;
  margin: 0;
}

.validar-cromo__chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  color: var(--color-accent);
  white-space: nowrap;
}

.validar-cromo__chip.is-warn {
  background: color-mix(in srgb, var(--warning) 16%, transparent);
  color: var(--warning);
}

.validar-cromo__meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  margin: 0 0 14px;
}

.validar-cromo__meta div {
  border: 1px solid color-mix(in srgb, var(--color-text) 12%, transparent);
  border-radius: var(--radius-md);
  padding: 8px 11px;
}

.validar-cromo__meta dt {
  font-size: 11px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.validar-cromo__meta dd {
  font-size: 13.5px;
  font-weight: 500;
  margin: 2px 0 0;
  word-break: break-word;
}

.validar-cromo__destacado {
  display: grid;
  gap: 14px;
  padding: 14px;
  border-radius: 14px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
}

.validar-cromo__destacado-etiqueta {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}

.validar-cromo__destacado-valor {
  margin: 4px 0 0;
  font-size: 15px;
  word-break: break-word;
}

.validar-cromo__lista-errores {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--warning);
}

.validar-cromo__lista-errores code {
  margin-right: 6px;
}

.tabla-topologia {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.tabla-topologia th,
.tabla-topologia td {
  text-align: left;
  padding: 7px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--color-text) 10%, transparent);
}

.tabla-topologia th {
  font-weight: 500;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  font-size: 12px;
}

.validar-cromo__tubos {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.validar-cromo__tubo header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.validar-cromo__crudo summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--muted);
}

.validar-cromo__crudo pre {
  margin-top: 10px;
  padding: 12px;
  border-radius: 10px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  font-size: 11.5px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
