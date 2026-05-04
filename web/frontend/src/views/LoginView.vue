<!--
  Nombre de archivo: LoginView.vue
  Ubicación de archivo: web/frontend/src/views/LoginView.vue
  Descripción: Formulario de login del SPA — consume POST /api/auth/login y redirige al panel
-->
<template>
  <div class="login-wrapper">
    <div class="card">
      <h1>Acceso</h1>
      <div v-if="error" class="error">{{ error }}</div>
      <form @submit.prevent="handleLogin">
        <div class="field">
          <label>Usuario</label>
          <input v-model="username" name="username" type="text" required autofocus autocomplete="username" />
        </div>
        <div class="field">
          <label>Contraseña</label>
          <input v-model="password" name="password" type="password" required autocomplete="current-password" />
        </div>
        <button class="btn primary" type="submit" :disabled="loading">
          {{ loading ? 'Ingresando...' : 'Ingresar' }}
        </button>
      </form>
      <p class="muted small" style="margin-top:12px;">LAS-FOCAS</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { login } from '../api/auth';
import { useSession } from '../composables/useSession';

const router = useRouter();
const { setSession } = useSession();

const username = ref('');
const password = ref('');
const error = ref<string | null>(null);
const loading = ref(false);

async function handleLogin() {
  error.value = null;
  loading.value = true;
  try {
    const result = await login(username.value, password.value);
    if (result.ok && result.username && result.role && result.csrf) {
      setSession({
        authenticated: true,
        username: result.username,
        role: result.role,
        csrf: result.csrf,
      });
      await router.push('/');
    } else {
      error.value = result.error ?? 'Credenciales inválidas';
    }
  } catch {
    error.value = 'Error de conexión';
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  background: var(--bg);
}
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 28px;
  width: 360px;
}
.card h1 { margin-top: 0; color: var(--text); }
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}
.field label { font-size: 0.85rem; color: var(--muted); }
.field input {
  background: #0c1117;
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  width: 100%;
  box-sizing: border-box;
  font-family: inherit;
}
.field input:focus { outline: none; border-color: var(--primary); }
.error {
  color: #fca5a5;
  margin-bottom: 12px;
  font-size: 0.9rem;
}
.btn {
  width: 100%;
  background: var(--primary);
  border: 1px solid var(--primary);
  color: #fff;
  border-radius: 6px;
  padding: 10px;
  cursor: pointer;
  font-size: 1rem;
  font-family: inherit;
}
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
