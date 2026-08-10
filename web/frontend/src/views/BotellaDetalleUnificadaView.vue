<!--
  Nombre de archivo: BotellaDetalleUnificadaView.vue
  Ubicación de archivo: web/frontend/src/views/BotellaDetalleUnificadaView.vue
  Descripción: Shim de redirección — URL estable /infra/Camaras/Botellas/ID:id, reenvía a la vista de detalle real según origen
-->
<template>
  <section class="botella-detalle-shim">
    <i class="ph ph-circle-notch botella-detalle-shim__spin" aria-hidden="true"></i>
    Redirigiendo al detalle de la botella...
  </section>
</template>

<script setup lang="ts">
import { onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';

/**
 * No hay todavía una identidad unificada entre Botellas Cromo y legado (mismo `id` puede coincidir en
 * valor entre las dos fuentes sin ser la misma fila) — en vez de duplicar la UI de detalle que YA
 * funciona para cada origen, esta vista sólo reenvía a la vista real correspondiente.
 */
const route = useRoute();
const router = useRouter();

onMounted(() => {
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

  void router.replace(`/infra/cromo/verificador?tipo=botella&n_id=${id}`);
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
</style>
