<!--
  Nombre de archivo: PanelView.vue
  Ubicación de archivo: web/frontend/src/views/PanelView.vue
  Descripción: Vista Home del panel — renderiza el chat principal sin tabs legacy
-->
<template>
  <div class="panel-root">
    <div class="panel-content">
      <ChatTab />
    </div>
  </div>
</template>

<script setup lang="ts">
import ChatTab from './tabs/ChatTab.vue';
</script>

<style scoped>
.panel-root { display: flex; flex-direction: column; height: 100%; }
.panel-content { flex: 1; overflow-y: auto; }
</style>
