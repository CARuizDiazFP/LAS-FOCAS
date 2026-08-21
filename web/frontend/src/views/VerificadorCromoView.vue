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
      <p v-if="eliminarExito" class="msg ok visible">{{ eliminarExito }}</p>
      <p v-if="separarExito" class="msg ok visible">{{ separarExito }}</p>
    </article>

    <article v-if="resultado" class="card verificador-cromo__card">
      <header class="verificador-cromo__resultado-header">
        <h2>{{ tipoActual.etiqueta }} <code>{{ resultado.nId }}</code></h2>
        <div class="verificador-cromo__resultado-header-right">
          <RouterLink
            v-if="camaraPadre"
            class="verificador-cromo__padre-link"
            :to="`/infra/Camaras/${camaraPadre.id}`"
          >
            <i class="ph ph-arrow-bend-left-up" aria-hidden="true"></i>
            Cámara padre: {{ camaraPadre.nombre || `ID ${camaraPadre.id}` }}
          </RouterLink>
          <button
            v-if="tipo === 'botella'"
            class="btn subtle"
            type="button"
            @click="mostrarModalCromo = true"
          >
            <i class="ph ph-eye" aria-hidden="true"></i>
            Ver info en Cromo
          </button>
          <button
            v-if="tipo === 'botella' && isAdmin"
            class="btn subtle"
            type="button"
            @click="eliminarConfirmarAbierto = true"
          >
            <i class="ph ph-trash" aria-hidden="true"></i>
            Eliminar Botella
          </button>
          <button
            v-if="tipo === 'botella' && isAdmin && camaraPadre"
            class="btn subtle"
            type="button"
            @click="abrirConfirmacionSeparar"
          >
            <i class="ph ph-arrows-split" aria-hidden="true"></i>
            Separar a nueva Cámara
          </button>
          <span class="verificador-cromo__chip">{{ resultado.servicios.length }} servicio(s)</span>
        </div>
      </header>

      <div v-if="eliminarConfirmarAbierto" class="verificador-cromo__eliminar-confirm">
        <p>
          ⚠️ ¿Eliminar permanentemente la Botella <strong>{{ resultado.meta[0]?.valor || `ID ${resultado.nId}` }}</strong>?
          Esta acción no se puede deshacer.
        </p>
        <ul v-if="eliminarBloqueos.length > 0" class="verificador-cromo__eliminar-bloqueos">
          <li v-for="b in eliminarBloqueos" :key="`${b.origen}:${b.id}`">
            {{ b.nombre || `ID ${b.id}` }} ({{ b.origen }}): {{ b.razon }}
          </li>
        </ul>
        <p v-else-if="eliminarErrorMsg" class="verificador-cromo__eliminar-error">{{ eliminarErrorMsg }}</p>
        <div class="verificador-cromo__eliminar-actions">
          <button class="btn danger" type="button" :disabled="eliminando" @click="handleEliminar">
            {{ eliminando ? 'Eliminando...' : 'Sí, eliminar' }}
          </button>
          <button class="btn subtle" type="button" :disabled="eliminando" @click="cerrarConfirmacionEliminar">
            Cancelar
          </button>
        </div>
      </div>

      <div v-if="separarConfirmarAbierto" class="verificador-cromo__separar-confirm">
        <p>
          Se va a crear una <strong>Cámara nueva e independiente</strong> para esta Botella,
          separándola de <strong>{{ camaraPadre?.nombre || `ID ${camaraPadre?.id}` }}</strong>.
        </p>
        <label for="separar-nombre">Nombre de la Botella / Cámara nueva</label>
        <input id="separar-nombre" v-model="separarNombreNuevo" type="text" maxlength="500" />
        <label for="separar-motivo">Motivo</label>
        <input
          id="separar-motivo"
          v-model="separarMotivo"
          type="text"
          maxlength="1000"
          placeholder="ej. agrupada por error con otra dirección de nombre parecido"
        />
        <p v-if="separarErrorMsg" class="verificador-cromo__eliminar-error">{{ separarErrorMsg }}</p>
        <div class="verificador-cromo__eliminar-actions">
          <button
            class="btn primary"
            type="button"
            :disabled="separando || !separarNombreNuevo.trim() || !separarMotivo.trim()"
            @click="handleSepararPadre"
          >
            {{ separando ? 'Separando...' : 'Sí, separar' }}
          </button>
          <button class="btn subtle" type="button" :disabled="separando" @click="cerrarConfirmacionSeparar">
            Cancelar
          </button>
        </div>
      </div>

      <dl class="verificador-cromo__meta">
        <div v-for="dato in resultado.meta" :key="dato.etiqueta">
          <dt>{{ dato.etiqueta }}</dt>
          <dd>{{ dato.valor ?? '—' }}</dd>
        </div>
      </dl>

      <div v-if="tipo === 'botella' && isAdmin" class="verificador-cromo__nombre-editar">
        <label for="verificador-cromo-nombre">Corregir nombre (local, no escribe hacia Cromo)</label>
        <div class="verificador-cromo__nombre-editar-row">
          <input id="verificador-cromo-nombre" v-model="nombreEditado" type="text" maxlength="500" />
          <button
            class="btn subtle"
            type="button"
            :disabled="guardandoNombre || !nombreEditado.trim()"
            @click="onGuardarNombre"
          >
            {{ guardandoNombre ? 'Guardando…' : 'Guardar nombre' }}
          </button>
        </div>
        <p v-if="nombreGuardadoOk" class="msg ok visible">Nombre actualizado.</p>
        <p v-if="nombreError" class="msg err visible">{{ nombreError }}</p>
      </div>

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

    <article v-if="tipo === 'botella' && resultado" class="card verificador-cromo__card">
      <header class="verificador-cromo__resultado-header">
        <h2>Cables asociados</h2>
        <span class="verificador-cromo__chip">{{ cablesBotella.length }} cable(s)</span>
      </header>

      <p v-if="cablesBotella.length === 0" class="hint">
        No se encontró ningún cable con esta botella como extremo en el inventario ingerido.
      </p>

      <table v-else class="tabla-cables">
        <thead>
          <tr>
            <th>ID</th>
            <th>Nombre de Cable</th>
            <th>Servicios Asociados</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="c in cablesBotella"
            :key="c.n_id"
            class="tabla-cables__fila"
            tabindex="0"
            role="button"
            :aria-label="`Ver detalle del cable ${c.nombre || c.n_id}`"
            @click="irACable(c)"
            @keydown.enter="irACable(c)"
          >
            <td>{{ c.n_id }}</td>
            <td>{{ c.nombre || '—' }}</td>
            <td>{{ c.cantidad_servicios }}</td>
          </tr>
        </tbody>
      </table>

      <!-- Futuro (Empalmes): tarjeta con la tabla de fusiones internas de esta botella
           (`app.cromo_fusiones` con `botella_n_id` propio) — misma estructura minimalista que la
           tabla de Cables de arriba. El backend todavía no expone este dato (ver comentario en
           `ResultadoBotella`, core/services/cromo/verificador.py, y en `CromoVerificacionBotella`,
           src/api/cromo.ts). -->
    </article>

    <article v-if="tipo === 'botella' && resultado" class="card verificador-cromo__card">
      <header class="verificador-cromo__resultado-header">
        <h2>Cables detectados en Cromo</h2>
        <div class="verificador-cromo__resultado-header-right">
          <button
            class="btn subtle"
            type="button"
            :disabled="cablesDetectadosCargando"
            @click="onConsultarCablesCromo"
          >
            <i class="ph ph-cloud-arrow-down" aria-hidden="true"></i>
            {{ cablesDetectadosCargando ? 'Consultando…' : 'Consultar Cromo' }}
          </button>
          <button
            v-if="isAdmin && cablesPendientes.length > 0"
            class="btn primary"
            type="button"
            :disabled="repoblando"
            @click="onRepoblarCables"
          >
            <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
            {{ repoblando ? 'Repoblando…' : `Repoblar Cables (${cablesPendientes.length})` }}
          </button>
          <span v-if="cablesDetectados" class="verificador-cromo__chip">
            {{ cablesDetectados.length }} detectado(s)
          </span>
        </div>
      </header>

      <p v-if="cablesDetectadosError" class="msg err visible">{{ cablesDetectadosError }}</p>
      <p v-if="repoblarError" class="msg err visible">{{ repoblarError }}</p>
      <p v-if="repoblarResultado" class="msg ok visible">
        Repoblado: {{ repoblarResultado.creados }} creado(s), {{ repoblarResultado.actualizados }} actualizado(s),
        {{ repoblarResultado.sin_cambios }} sin cambios{{
          repoblarResultado.errores ? `, ${repoblarResultado.errores} con error` : ''
        }}.
      </p>

      <p v-if="cablesDetectados === null" class="hint">
        Consulta en vivo contra Cromo (no se dispara automáticamente en cada búsqueda) — sirve para
        detectar cables que la ingesta omitió por un caso de "ID dual" (<code>hist</code>/<code>next_id</code>).
      </p>
      <p v-else-if="cablesDetectados.length === 0" class="hint">
        Cromo no reporta ningún cable conectado a esta botella.
      </p>

      <table v-else class="tabla-cables">
        <thead>
          <tr>
            <th>ID</th>
            <th>Nombre</th>
            <th>Extremo A</th>
            <th>Extremo B</th>
            <th>Estado local</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in cablesDetectados" :key="c.n_id">
            <td>{{ c.n_id }}</td>
            <td>{{ c.nombre || '—' }}</td>
            <td>{{ c.extremo_a_n_id ?? '—' }}</td>
            <td>{{ c.extremo_b_n_id ?? '—' }}</td>
            <td>
              <span
                :class="[
                  'verificador-cromo__estado-chip',
                  `verificador-cromo__estado-chip--${c.estado_local.toLowerCase()}`,
                ]"
              >
                {{ c.estado_local }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </article>

    <ModalVerificadorCromo
      :open="mostrarModalCromo"
      :n-id="resultado?.nId ?? null"
      @close="mostrarModalCromo = false"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import {
  editarNombreBotellaCromo,
  eliminarBotella,
  getCromoBotellaEstadoAsociacion,
  repoblarCablesCromo,
  separarBotellaDeCamaraPadre,
  type BloqueoEliminacion,
  type RepoblarCablesResponse,
  type SepararBotellaDePadreResponse,
} from '../api/botellas';
import { ApiError } from '../api/client';
import {
  detectarCablesCromo,
  verificarServiciosPorBotella,
  verificarServiciosPorCable,
  verificarServiciosPorTubo,
  type CromoCableDeBotella,
  type CromoCableDetectado,
  type CromoServicioEncontrado,
} from '../api/cromo';
import ModalVerificadorCromo from '../components/infra/ModalVerificadorCromo.vue';
import { useSession } from '../composables/useSession';

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
  // Sólo presente cuando tipo === 'botella' — cables que la tienen como extremo.
  cables?: CromoCableDeBotella[];
}

const route = useRoute();
const router = useRouter();

const tipo = ref<TipoObjeto>('cable');
const nIdTexto = ref('');
const buscando = ref(false);
const error = ref('');
const resultado = ref<ResultadoVista | null>(null);
// Navegación cruzada (2026-08-13): sólo se completa cuando tipo === 'botella' y la Botella tiene
// Cámara padre vinculada — ver core/services/cromo/camara_padre_service.py.
const camaraPadre = ref<{ id: number; nombre: string | null } | null>(null);
const mostrarModalCromo = ref(false);

const { state } = useSession();
const isAdmin = computed(() => (state.value.role ?? '').toLowerCase() === 'admin');

const eliminarConfirmarAbierto = ref(false);
const eliminando = ref(false);
const eliminarErrorMsg = ref('');
const eliminarBloqueos = ref<BloqueoEliminacion[]>([]);
const eliminarExito = ref('');

// "Cables detectados en Cromo" (ID dual: hist[]/next_id) — consulta EN VIVO, deliberadamente
// manual (no se dispara en cada búsqueda, mismo criterio que "Ver info en Cromo").
const cablesDetectados = ref<CromoCableDetectado[] | null>(null);
const cablesDetectadosCargando = ref(false);
const cablesDetectadosError = ref('');
const repoblando = ref(false);
const repoblarResultado = ref<RepoblarCablesResponse | null>(null);
const repoblarError = ref('');

// Nombre editable (sólo admin) — se inicializa al buscar una botella, se refleja en `resultado`
// in-place al guardar (sin re-disparar la búsqueda).
const nombreEditado = ref('');
const guardandoNombre = ref(false);
const nombreGuardadoOk = ref(false);
const nombreError = ref('');

// "Separar a nueva Cámara" (sólo admin) — crea una Cámara padre nueva e independiente cuando el
// backfill de Cromo agrupó esta Botella con otra por nombre parecido.
const separarConfirmarAbierto = ref(false);
const separarNombreNuevo = ref('');
const separarMotivo = ref('');
const separando = ref(false);
const separarErrorMsg = ref('');
const separarExito = ref('');

const tipoActual = computed(() => TIPOS.find((t) => t.valor === tipo.value) ?? TIPOS[0]);
const nIdValido = computed(() => /^\d+$/.test(nIdTexto.value.trim()));
const cablesBotella = computed(() => resultado.value?.cables ?? []);
const cablesPendientes = computed(() => (cablesDetectados.value ?? []).filter((c) => c.estado_local !== 'OK'));

async function onBuscar(): Promise<void> {
  if (!nIdValido.value) return;
  const nId = Number(nIdTexto.value.trim());

  buscando.value = true;
  error.value = '';
  resultado.value = null;
  camaraPadre.value = null;
  eliminarExito.value = '';
  cerrarConfirmacionEliminar();
  cablesDetectados.value = null;
  cablesDetectadosError.value = '';
  repoblarResultado.value = null;
  repoblarError.value = '';
  nombreGuardadoOk.value = false;
  nombreError.value = '';
  separarExito.value = '';
  cerrarConfirmacionSeparar();

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
        cables: r.cables,
      };
      nombreEditado.value = r.nombre ?? '';
      // Best-effort: si falla, la Botella se sigue mostrando igual, sólo sin el link de navegación
      // cruzada — no es motivo para tratar la búsqueda completa como un error.
      try {
        const asociacion = await getCromoBotellaEstadoAsociacion(nId);
        camaraPadre.value = asociacion.camara_id
          ? { id: asociacion.camara_id, nombre: asociacion.camara_nombre }
          : null;
      } catch {
        camaraPadre.value = null;
      }
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

function cerrarConfirmacionEliminar(): void {
  eliminarConfirmarAbierto.value = false;
  eliminarErrorMsg.value = '';
  eliminarBloqueos.value = [];
}

async function handleEliminar(): Promise<void> {
  if (!resultado.value) return;
  eliminando.value = true;
  eliminarErrorMsg.value = '';
  eliminarBloqueos.value = [];
  try {
    await eliminarBotella('cromo', resultado.value.nId);
    eliminarExito.value = `Botella ID ${resultado.value.nId} eliminada correctamente.`;
    resultado.value = null;
    camaraPadre.value = null;
    cerrarConfirmacionEliminar();
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

async function onConsultarCablesCromo(): Promise<void> {
  if (!resultado.value) return;
  cablesDetectadosCargando.value = true;
  cablesDetectadosError.value = '';
  try {
    const r = await detectarCablesCromo(resultado.value.nId);
    cablesDetectados.value = r.cables;
  } catch (e) {
    cablesDetectadosError.value = e instanceof Error ? e.message : 'No se pudo consultar Cromo.';
  } finally {
    cablesDetectadosCargando.value = false;
  }
}

async function onRepoblarCables(): Promise<void> {
  if (!resultado.value) return;
  repoblando.value = true;
  repoblarError.value = '';
  repoblarResultado.value = null;
  try {
    const r = await repoblarCablesCromo(resultado.value.nId);
    repoblarResultado.value = r;
    await onConsultarCablesCromo(); // refresca la detección para reflejar el estado post-repoblado
  } catch (e) {
    repoblarError.value = e instanceof Error ? e.message : 'No se pudo repoblar cables.';
  } finally {
    repoblando.value = false;
  }
}

async function onGuardarNombre(): Promise<void> {
  if (!resultado.value) return;
  const nombreLimpio = nombreEditado.value.trim();
  if (!nombreLimpio) return;
  guardandoNombre.value = true;
  nombreError.value = '';
  nombreGuardadoOk.value = false;
  try {
    const r = await editarNombreBotellaCromo(resultado.value.nId, nombreLimpio);
    // Se refleja inmediato en la UI, sin re-disparar la búsqueda.
    resultado.value = {
      ...resultado.value,
      meta: resultado.value.meta.map((m) => (m.etiqueta === 'Nombre' ? { ...m, valor: r.nombre } : m)),
    };
    nombreEditado.value = r.nombre;
    nombreGuardadoOk.value = true;
  } catch (e) {
    nombreError.value = e instanceof Error ? e.message : 'No se pudo guardar el nombre.';
  } finally {
    guardandoNombre.value = false;
  }
}

function abrirConfirmacionSeparar(): void {
  if (!resultado.value) return;
  separarNombreNuevo.value = (resultado.value.meta.find((m) => m.etiqueta === 'Nombre')?.valor as string) ?? '';
  separarMotivo.value = '';
  separarErrorMsg.value = '';
  separarConfirmarAbierto.value = true;
}

function cerrarConfirmacionSeparar(): void {
  separarConfirmarAbierto.value = false;
  separarErrorMsg.value = '';
}

async function handleSepararPadre(): Promise<void> {
  if (!resultado.value) return;
  const nombreLimpio = separarNombreNuevo.value.trim();
  const motivoLimpio = separarMotivo.value.trim();
  if (!nombreLimpio || !motivoLimpio) return;

  separando.value = true;
  separarErrorMsg.value = '';
  try {
    const r: SepararBotellaDePadreResponse = await separarBotellaDeCamaraPadre(resultado.value.nId, nombreLimpio, motivoLimpio);
    separarExito.value = `Botella separada a la nueva Cámara "${r.camara_nueva_nombre}" (ID ${r.camara_nueva_id}).`;
    resultado.value = {
      ...resultado.value,
      meta: resultado.value.meta.map((m) => (m.etiqueta === 'Nombre' ? { ...m, valor: r.camara_nueva_nombre } : m)),
    };
    nombreEditado.value = r.camara_nueva_nombre;
    camaraPadre.value = { id: r.camara_nueva_id, nombre: r.camara_nueva_nombre };
    cerrarConfirmacionSeparar();
  } catch (e) {
    separarErrorMsg.value = e instanceof Error ? e.message : 'No se pudo separar la Botella.';
  } finally {
    separando.value = false;
  }
}

// Navegación cruzada desde otras vistas (ej. click en una Botella extremo dentro del detalle de un
// cable): precarga tipo + n_id desde la URL y dispara la búsqueda automáticamente. Siempre llega por
// una navegación completa a esta ruta (nunca un cambio de query dentro del propio Verificador ya
// montado — el único click que vivía dentro de esta vista, el de un cable de "Cables asociados",
// navega directo al detalle dedicado del cable, no actualiza el query de esta ruta), así que alcanza
// con `onMounted`.
onMounted(() => {
  const tipoQuery = route.query.tipo;
  const nIdQuery = route.query.n_id;
  const tipoValido = typeof tipoQuery === 'string' && TIPOS.some((t) => t.valor === tipoQuery);
  const nIdValidoQuery = typeof nIdQuery === 'string' && /^\d+$/.test(nIdQuery);
  if (tipoValido && nIdValidoQuery) {
    tipo.value = tipoQuery as TipoObjeto;
    nIdTexto.value = nIdQuery;
    void onBuscar();
  }
});

// Navega al detalle jerárquico dedicado del cable (Etapa 9, `CableDetalleCromoView.vue`) — no se
// queda en este Verificador con `tipo=cable`: esa tarjeta sólo muestra servicios, no tubos/pelos.
function irACable(cable: { n_id: number }): void {
  void router.push(`/infra/cromo/cables/ID${cable.n_id}`);
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

.verificador-cromo__resultado-header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.verificador-cromo__padre-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 3px 10px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
  color: var(--color-accent);
  text-decoration: none;
  white-space: nowrap;
}

.verificador-cromo__padre-link:hover,
.verificador-cromo__padre-link:focus-visible {
  background: color-mix(in srgb, var(--color-accent) 18%, transparent);
}

.verificador-cromo__chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  color: var(--color-accent);
  white-space: nowrap;
}

.verificador-cromo__eliminar-confirm {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 20px;
  margin-bottom: 14px;
  border-radius: 16px;
  background: color-mix(in srgb, var(--error) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--error) 35%, transparent);
  color: var(--error);
}

.verificador-cromo__eliminar-confirm p {
  margin: 0;
}

.verificador-cromo__eliminar-bloqueos {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}

.verificador-cromo__eliminar-error {
  font-size: 13px;
}

.verificador-cromo__eliminar-actions {
  display: flex;
  gap: 10px;
}

.verificador-cromo__separar-confirm {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 20px;
  margin-bottom: 14px;
  border-radius: 16px;
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--warning) 35%, transparent);
}

.verificador-cromo__separar-confirm p {
  margin: 0;
}

.verificador-cromo__separar-confirm label {
  font-size: 11px;
  color: var(--muted);
}

.verificador-cromo__separar-confirm input {
  max-width: 420px;
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

/* Misma estructura minimalista que .tabla-servicios, filas clickeables como en
   InventarioCablesCromoView.vue (mismo patrón accesible: role="button" + tabindex + @keydown.enter). */
.tabla-cables {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.tabla-cables th,
.tabla-cables td {
  text-align: left;
  padding: 7px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--color-text) 10%, transparent);
}

.tabla-cables th {
  font-weight: 500;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  font-size: 12px;
}

.tabla-cables__fila {
  cursor: pointer;
}

.tabla-cables__fila:hover {
  background: color-mix(in srgb, var(--color-text) 5%, transparent);
}

.tabla-cables__fila:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: -2px;
}

.verificador-cromo__nombre-editar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}

.verificador-cromo__nombre-editar label {
  font-size: 11px;
  color: var(--muted);
}

.verificador-cromo__nombre-editar-row {
  display: flex;
  gap: 10px;
}

.verificador-cromo__nombre-editar-row input {
  flex: 1;
  max-width: 360px;
}

.verificador-cromo__estado-chip {
  display: inline-flex;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 9px;
  border-radius: var(--radius-md);
}

.verificador-cromo__estado-chip--ok {
  background: color-mix(in srgb, var(--success) 16%, transparent);
  color: var(--success);
}

.verificador-cromo__estado-chip--desactualizado {
  background: color-mix(in srgb, var(--warning) 16%, transparent);
  color: var(--warning);
}

.verificador-cromo__estado-chip--falta {
  background: color-mix(in srgb, var(--error) 16%, transparent);
  color: var(--error);
}
</style>
