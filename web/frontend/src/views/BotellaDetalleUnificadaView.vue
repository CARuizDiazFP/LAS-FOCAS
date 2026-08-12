<!--
  Nombre de archivo: BotellaDetalleUnificadaView.vue
  Ubicación de archivo: web/frontend/src/views/BotellaDetalleUnificadaView.vue
  Descripción: Shim de redirección — URL estable /infra/Camaras/Botellas/ID:id, reenvía a la vista de detalle real según origen; si la Botella Cromo está huérfana, ofrece resolverla acá mismo
-->
<template>
  <section class="botella-detalle-shim">
    <template v-if="huerfana">
      <div class="botella-detalle-shim__huerfana">
        <i class="ph ph-warning-circle" aria-hidden="true"></i>
        <h2>Botella sin Cámara asociada</h2>
        <p>
          <strong>{{ nombreBotella || `Botella ${nId}` }}</strong> no matcheó ningún patrón de
          nombre automático — asocialá manualmente a una Cámara existente o dá de alta una nueva.
        </p>
        <div class="botella-detalle-shim__actions">
          <button class="btn primary" type="button" @click="modalAsociarOpen = true">Resolver ahora</button>
          <button class="btn subtle" type="button" @click="irAlVerificador">Ver en el Verificador Cromo</button>
        </div>
      </div>

      <ModalAsociarHuerfanas
        :open="modalAsociarOpen"
        :n-ids="[nId]"
        @close="modalAsociarOpen = false"
        @asociada="irAlVerificador"
      />
    </template>
    <template v-else>
      <i class="ph ph-circle-notch botella-detalle-shim__spin" aria-hidden="true"></i>
      Redirigiendo al detalle de la botella...
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import ModalAsociarHuerfanas from '../components/infra/ModalAsociarHuerfanas.vue';

/**
 * No hay todavía una identidad unificada entre Botellas Cromo y legado (mismo `id` puede coincidir en
 * valor entre las dos fuentes sin ser la misma fila) — en vez de duplicar la UI de detalle que YA
 * funciona para cada origen, esta vista reenvía a la vista real correspondiente. Excepción (Caso 1,
 * 2026-08-11): si la Botella es de origen Cromo y está huérfana (sin `camara_id`), se ofrece
 * resolverla acá mismo en vez de redirigir directo al Verificador.
 */
const route = useRoute();
const router = useRouter();
const huerfana = ref(false);
const nombreBotella = ref('');
const modalAsociarOpen = ref(false);
const nId = ref(0);

function irAlVerificador(): void {
  void router.replace(`/infra/cromo/verificador?tipo=botella&n_id=${nId.value}`);
}

onMounted(async () => {
  const id = String(route.params.id ?? '').trim();
  const origen = String(route.query.origen ?? '').trim().toLowerCase();

  if (!id) {
    void router.replace('/infra/Botellas');
    return;
  }

  if (origen === 'legado') {
    void router.replace(`/infra/Camaras/${id}`);
    return;
  }

  nId.value = Number(id);
  try {
    const res = await fetch(`/api/infra/cromo-botellas/${nId.value}/estado-asociacion`, { credentials: 'include' });
    if (res.ok) {
      const data = await res.json() as { huerfana?: boolean; nombre?: string | null };
      if (data.huerfana) {
        huerfana.value = true;
        nombreBotella.value = data.nombre ?? '';
        return;
      }
    }
  } catch {
    // Si el chequeo falla, seguimos con el comportamiento anterior (redirigir sin más vueltas).
  }

  irAlVerificador();
});
</script>

<style scoped>
.botella-detalle-shim {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  height: 100%;
  padding: 40px;
  font-size: 13px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.botella-detalle-shim__spin {
  font-size: 16px;
  animation: spin 1s linear infinite;
}

.botella-detalle-shim__huerfana {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  max-width: 380px;
  text-align: center;
}

.botella-detalle-shim__huerfana i {
  font-size: 28px;
  color: var(--color-state-warn, #facc15);
}

.botella-detalle-shim__huerfana h2 {
  margin: 0;
  font-size: 16px;
  color: var(--color-text);
}

.botella-detalle-shim__huerfana p {
  margin: 0;
  line-height: 1.5;
}

.botella-detalle-shim__actions {
  display: flex;
  gap: 10px;
  margin-top: 6px;
}
</style>
