<!--
  Nombre de archivo: VlanTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/VlanTab.vue
  Descripción: Tab Comparador de VLANs (Cisco IOS) — migrado desde panel.js
-->
<template>
  <article class="card">
    <header class="card-header">
      <h1>Comparador de VLANs</h1>
      <span class="badge">Nuevo</span>
    </header>
    <p class="muted">Pegá las configuraciones completas de las interfaces (formato Cisco IOS). El sistema detecta automáticamente las líneas <code>switchport trunk allowed vlan</code>, expande los rangos y muestra las diferencias.</p>
    <div class="vlan-input-grid">
      <div class="vlan-input">
        <label class="form-label">Interfaz A</label>
        <textarea v-model="textA" placeholder="interface GigabitEthernet0/1&#10; switchport trunk allowed vlan 1-30,101,306-308"></textarea>
        <small class="muted">Se muestran las VLANs que están únicamente en esta interfaz.</small>
      </div>
      <div class="vlan-input">
        <label class="form-label">Interfaz B</label>
        <textarea v-model="textB" placeholder="interface TenGigabitEthernet0/48&#10; switchport trunk allowed vlan add 1-10,40,306-310"></textarea>
        <small class="muted">Incluí todos los comandos relevantes; el parser ignora líneas ajenas.</small>
      </div>
    </div>
    <div class="card-actions">
      <button class="btn primary" :disabled="loading" @click="compare">Comparar</button>
      <button class="btn subtle" @click="clearAll">Limpiar</button>
    </div>
    <div :class="['result-box', statusClass]" role="status" aria-live="polite" aria-atomic="true">{{ statusText }}</div>
    <div class="vlan-results">
      <div class="vlan-result-card">
        <div class="vlan-result-header">
          <h2>Solo A</h2>
          <span class="vlan-count">{{ onlyA.length }}</span>
        </div>
        <div class="vlan-list" :class="{ empty: onlyA.length === 0 }" data-empty="Sin diferencias detectadas">
          <span v-for="v in onlyA" :key="v" class="vlan-pill">{{ v }}</span>
          <span v-if="onlyA.length === 0" class="muted" style="font-style:italic">Sin diferencias detectadas</span>
        </div>
      </div>
      <div class="vlan-result-card">
        <div class="vlan-result-header">
          <h2>Comunes</h2>
          <span class="vlan-count">{{ common.length }}</span>
        </div>
        <div class="vlan-list" :class="{ empty: common.length === 0 }">
          <span v-for="v in common" :key="v" class="vlan-pill">{{ v }}</span>
          <span v-if="common.length === 0" class="muted" style="font-style:italic">No hay coincidencias</span>
        </div>
      </div>
      <div class="vlan-result-card">
        <div class="vlan-result-header">
          <h2>Solo B</h2>
          <span class="vlan-count">{{ onlyB.length }}</span>
        </div>
        <div class="vlan-list" :class="{ empty: onlyB.length === 0 }">
          <span v-for="v in onlyB" :key="v" class="vlan-pill">{{ v }}</span>
          <span v-if="onlyB.length === 0" class="muted" style="font-style:italic">Sin diferencias detectadas</span>
        </div>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useSession } from '../../composables/useSession';

const { csrf } = useSession();
const textA = ref('');
const textB = ref('');
const loading = ref(false);
const statusText = ref('Ingresá dos configuraciones de interfaz trunk para comenzar.');
const statusClass = ref('muted');
const onlyA = ref<number[]>([]);
const onlyB = ref<number[]>([]);
const common = ref<number[]>([]);

function setStatus(msg: string, cls = 'info') {
  statusText.value = msg;
  statusClass.value = cls;
}

function resetResults() {
  onlyA.value = [];
  onlyB.value = [];
  common.value = [];
}

function clearAll() {
  textA.value = '';
  textB.value = '';
  resetResults();
  setStatus('Ingresá dos configuraciones de interfaz trunk para comenzar.', 'muted');
}

async function compare() {
  if (!textA.value.trim() || !textB.value.trim()) {
    resetResults();
    setStatus('Pegá configuraciones en ambos campos.', 'error');
    return;
  }
  setStatus('Comparando configuraciones...', 'info');
  loading.value = true;
  try {
    const res = await fetch('/api/tools/compare-vlans', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ text_a: textA.value, text_b: textB.value, csrf_token: csrf() }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error ?? 'Error comparando VLANs');
    const sorted = (arr: number[]) => [...arr].sort((a, b) => a - b);
    onlyA.value = sorted(data.only_a ?? []);
    onlyB.value = sorted(data.only_b ?? []);
    common.value = sorted(data.common ?? []);
    setStatus(
      `Totales: A ${data.total_a ?? 0} · B ${data.total_b ?? 0} · Coincidencias ${common.value.length}`,
      'success',
    );
  } catch (e: unknown) {
    resetResults();
    setStatus(e instanceof Error ? e.message : String(e), 'error');
  } finally {
    loading.value = false;
  }
}
</script>
