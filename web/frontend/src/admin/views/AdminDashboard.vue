<!--
  Nombre de archivo: AdminDashboard.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminDashboard.vue
  Descripción: Vista raíz /admin — menú central con acceso a Usuarios y Servicios
-->
<template>
  <h1>Administración</h1>
  <p class="section-subtitle">Panel de control del sistema. Seleccioná un módulo para continuar.</p>

  <div class="dashboard-grid">
    <RouterLink to="/admin/usuarios" class="dashboard-btn">
      <span class="icon">👤</span>
      <span>Usuarios</span>
    </RouterLink>

    <RouterLink to="/admin/servicios" class="dashboard-btn">
      <span class="icon">⚙️</span>
      <span>Servicios</span>
    </RouterLink>
  </div>
</template>
