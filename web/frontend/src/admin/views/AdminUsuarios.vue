<!--
  Nombre de archivo: AdminUsuarios.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminUsuarios.vue
  Descripción: Vista /admin/usuarios — crear usuario y cambiar contraseña
-->
<template>
  <h1>Usuarios</h1>
  <p class="section-subtitle">Gestión de cuentas del sistema.</p>

  <div class="two-col">

    <!-- Crear usuario -->
    <div class="card">
      <h2>Crear usuario</h2>
      <form @submit.prevent="handleCrear">
        <label>Usuario</label>
        <input v-model="crear.username" type="text" required />

        <label>Contraseña</label>
        <input v-model="crear.password" type="password" required />

        <label>Rol</label>
        <select v-model="crear.role">
          <option value="admin">Admin</option>
          <option value="ownergroup">OwnerGroup</option>
          <option value="invitado">Invitado</option>
        </select>
        <p class="hint">Roles válidos: Admin, OwnerGroup, Invitado.</p>

        <button type="submit" class="btn primary" :disabled="crear.loading">
          {{ crear.loading ? 'Creando…' : 'Crear usuario' }}
        </button>

        <div class="msg" :class="{ visible: !!crear.msg, ok: !crear.error, err: crear.error }">
          {{ crear.msg }}
        </div>
      </form>
    </div>

    <!-- Cambiar contraseña -->
    <div class="card">
      <h2>Cambiar mi contraseña</h2>
      <form @submit.prevent="handleCambiar">
        <label>Contraseña actual</label>
        <input v-model="cambiar.current" type="password" required />

        <label>Nueva contraseña</label>
        <input v-model="cambiar.nuevo" type="password" required />

        <button type="submit" class="btn primary" :disabled="cambiar.loading">
          {{ cambiar.loading ? 'Guardando…' : 'Cambiar contraseña' }}
        </button>

        <div class="msg" :class="{ visible: !!cambiar.msg, ok: !cambiar.error, err: cambiar.error }">
          {{ cambiar.msg }}
        </div>
      </form>
    </div>

  </div>
</template>

<script setup lang="ts">
import { reactive } from 'vue';
import { createUser, changePassword } from '../api/admin';

const crear = reactive({
  username: '',
  password: '',
  role: 'ownergroup',
  loading: false,
  msg: '',
  error: false,
});

const cambiar = reactive({
  current: '',
  nuevo: '',
  loading: false,
  msg: '',
  error: false,
});

async function handleCrear() {
  crear.loading = true;
  crear.msg = '';
  try {
    await createUser(crear.username, crear.password, crear.role);
    crear.msg = `Usuario "${crear.username}" creado correctamente.`;
    crear.error = false;
    crear.username = '';
    crear.password = '';
  } catch (e: unknown) {
    crear.msg = e instanceof Error ? e.message : 'Error desconocido';
    crear.error = true;
  } finally {
    crear.loading = false;
  }
}

async function handleCambiar() {
  cambiar.loading = true;
  cambiar.msg = '';
  try {
    await changePassword(cambiar.current, cambiar.nuevo);
    cambiar.msg = 'Contraseña actualizada correctamente.';
    cambiar.error = false;
    cambiar.current = '';
    cambiar.nuevo = '';
  } catch (e: unknown) {
    cambiar.msg = e instanceof Error ? e.message : 'Error desconocido';
    cambiar.error = true;
  } finally {
    cambiar.loading = false;
  }
}
</script>
