<!--
  Nombre de archivo: VerificadorCromoView.vue
  Ubicación de archivo: web/frontend/src/views/VerificadorCromoView.vue
  Descripción: Verificador de servicios sobre el inventario FO ingerido desde Cromo — qué servicios pasan por un cable/tubo/botella
-->
<template>
  <section class="verificador-cromo">
    <header class="verificador-cromo__header">
      <h1>Verificador de servicios Cromo</h1>
      <p class="section-subtitle">
        Buscá por <code>n_id</code> de Cromo qué servicios de <code>app.servicios</code> pasan por un cable
        entero, un tubo/buffer específico, o los cables que tienen una botella como extremo.
      </p>
    </header>

    <hr class="noc-rule" />

    <article class="card verificador-cromo__card">
      <form class="verificador-cromo__form" @submit.prevent="onBuscar">
        <div class="verificador-cromo__tipo" role="radiogroup" aria-label="Tipo de objeto">
          <label v-for="opcion in TIPOS" :key="opcion.valor" class="tipo-check">
            <input v-model="tipo" type="radio" name="tipo" :value="opcion.valor" />
            <i :class="['ph', opcion.icono]" aria-hidden="true"></i>
            {{ opcion.etiqueta }}
          </label>
        </div>

        <div class="verificador-cromo__input-row">
          <input
            v-model="nIdTexto"
            type="text"
            inputmode="numeric"
            :placeholder="`n_id de Cromo (${tipoActual.etiqueta.toLowerCase()})`"
            autocomplete="off"
          />
          <button class="btn primary" type="submit" :disabled="buscando || !nIdValido">
            <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
            {{ buscando ? 'Buscando…' : 'Buscar' }}
          </button>
        </div>
      </form>

      <p v-if="error" class="msg err visible">{{ error }}</p>
    </article>

    <article v-if="resultado" class="card verificador-cromo__card">
      <header class="verificador-cromo__resultado-header">
        <h2>{{ tipoActual.etiqueta }} <code>{{ resultado.nId }}</code></h2>
        <span class="verificador-cromo__chip">{{ resultado.servicios.length }} servicio(s)</span>
      </header>

      <dl class="verificador-cromo__meta">
        <div v-for="dato in resultado.meta" :key="dato.etiqueta">
          <dt>{{ dato.etiqueta }}</dt>
          <dd>{{ dato.valor ?? '—' }}</dd>
        </div>
      </dl>

      <p v-if="resultado.servicios.length === 0" class="hint">
        No se encontró ningún servicio matcheado que pase por acá — puede que todavía no haya sido
        ingerido, que no tenga servicio asociado (`at.61`), o que el match no se haya resuelto.
      </p>

      <table v-else class="tabla-servicios">
        <thead>
          <tr>
            <th>Servicio</th>
            <th>Cliente</th>
            <th>Estado</th>
            <th>Tipo</th>
            <th>Pelo</th>
            <th>Método</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in resultado.servicios" :key="`${s.servicio_id}-${s.pelo_n_id}`">
            <td>{{ s.servicio_id_externo }}</td>
            <td>{{ s.nombre_cliente || s.cliente || '—' }}</td>
            <td>
              <span class="verificador-cromo__estado">{{ s.estado_servicio || '—' }}</span>
            </td>
            <td>{{ s.tipo_servicio || '—' }}</td>
            <td>{{ s.pelo_n_id }}</td>
            <td>{{ s.metodo }}</td>
          </tr>
        </tbody>
      </table>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';

import { ApiError } from '../api/client';
import {
  verificarServiciosPorBotella,
  verificarServiciosPorCable,
  verificarServiciosPorTubo,
  type CromoServicioEncontrado,
} from '../api/cromo';

type TipoObjeto = 'cable' | 'tubo' | 'botella';

const TIPOS: Array<{ valor: TipoObjeto; etiqueta: string; icono: string }> = [
  { valor: 'cable', etiqueta: 'Cable', icono: 'ph-line-segment' },
  { valor: 'tubo', etiqueta: 'Tubo / buffer', icono: 'ph-circles-three' },
  { valor: 'botella', etiqueta: 'Botella', icono: 'ph-package' },
];

interface ResultadoVista {
  nId: number;
  meta: Array<{ etiqueta: string; valor: string | number | null }>;
  servicios: CromoServicioEncontrado[];
}

const tipo = ref<TipoObjeto>('cable');
const nIdTexto = ref('');
const buscando = ref(false);
const error = ref('');
const resultado = ref<ResultadoVista | null>(null);

const tipoActual = computed(() => TIPOS.find((t) => t.valor === tipo.value) ?? TIPOS[0]);
const nIdValido = computed(() => /^\d+$/.test(nIdTexto.value.trim()));

async function onBuscar(): Promise<void> {
  if (!nIdValido.value) return;
  const nId = Number(nIdTexto.value.trim());

  buscando.value = true;
  error.value = '';
  resultado.value = null;

  try {
    if (tipo.value === 'cable') {
      const r = await verificarServiciosPorCable(nId);
      resultado.value = {
        nId: r.cable_n_id,
        meta: [
          { etiqueta: 'Nombre', valor: r.nombre },
          { etiqueta: 'Capacidad', valor: r.capacidad },
          { etiqueta: 'Extremo A', valor: r.extremo_a_nombre },
          { etiqueta: 'Extremo B', valor: r.extremo_b_nombre },
        ],
        servicios: r.servicios,
      };
    } else if (tipo.value === 'tubo') {
      const r = await verificarServiciosPorTubo(nId);
      resultado.value = {
        nId: r.tubo_n_id,
        meta: [
          { etiqueta: 'Cable', valor: r.cable_n_id },
          { etiqueta: 'Orden', valor: r.orden },
          { etiqueta: 'Color', valor: r.nombre_color },
        ],
        servicios: r.servicios,
      };
    } else {
      const r = await verificarServiciosPorBotella(nId);
      resultado.value = {
        nId: r.botella_n_id,
        meta: [
          { etiqueta: 'Nombre', valor: r.nombre },
          { etiqueta: 'Clase', valor: r.clase },
          { etiqueta: 'Localidad', valor: r.localidad },
        ],
        servicios: r.servicios,
      };
    }
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      error.value = `No existe ${tipoActual.value.etiqueta.toLowerCase()} con n_id=${nId} en el inventario ingerido.`;
    } else {
      error.value = e instanceof Error ? e.message : 'Error consultando el verificador.';
    }
  } finally {
    buscando.value = false;
  }
}
</script>

<style scoped>
.verificador-cromo {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px 26px 30px;
}

.verificador-cromo__header h1 {
  margin: 4px 0 6px;
}

.verificador-cromo .hint {
  font-size: 0.8rem;
  color: var(--muted);
}

.verificador-cromo__card {
  padding: 18px 20px;
}

.verificador-cromo__form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.verificador-cromo__tipo {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.tipo-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
  cursor: pointer;
}

.verificador-cromo__input-row {
  display: flex;
  gap: 10px;
}

.verificador-cromo__input-row input {
  flex: 1;
  max-width: 360px;
}

.verificador-cromo__resultado-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.verificador-cromo__resultado-header h2 {
  font-size: 15px;
  margin: 0;
}

.verificador-cromo__chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  color: var(--color-accent);
  white-space: nowrap;
}

.verificador-cromo__meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  margin: 0 0 14px;
}

.verificador-cromo__meta div {
  border: 1px solid color-mix(in srgb, var(--color-text) 12%, transparent);
  border-radius: var(--radius-md);
  padding: 8px 11px;
}

.verificador-cromo__meta dt {
  font-size: 11px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.verificador-cromo__meta dd {
  font-size: 13.5px;
  font-weight: 500;
  margin: 2px 0 0;
  word-break: break-word;
}

.verificador-cromo__estado {
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}

.tabla-servicios {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.tabla-servicios th,
.tabla-servicios td {
  text-align: left;
  padding: 7px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--color-text) 10%, transparent);
}

.tabla-servicios th {
  font-weight: 500;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  font-size: 12px;
}
</style>
