// Nombre de archivo: index.ts
// Ubicación de archivo: web/frontend/src/router/index.ts
// Descripción: Router unificado del SPA — rutas de panel, admin, login y SLA con guards de sesión

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import { useSession } from '../composables/useSession';

const LoginView = () => import('../views/LoginView.vue');
const AppShell = () => import('../components/app-shell/AppShell.vue');
const ServicioHistoricoView = () => import('../views/servicios/ServicioHistoricoView.vue');
const ServicioIngresosView = () => import('../views/servicios/ServicioIngresosView.vue');
const ServicioCaminoView = () => import('../views/servicios/ServicioCaminoView.vue');
const ServicioReclamosView = () => import('../views/servicios/ServicioReclamosView.vue');
const ServicioBaneosView = () => import('../views/servicios/ServicioBaneosView.vue');
const PanelView = () => import('../views/PanelView.vue');
const SlaView = () => import('../views/SlaView.vue');
const ReportsHistoryView = () => import('../views/ReportsHistoryView.vue');
const ServiciosView = () => import('../views/ServiciosView.vue');
const ServicioDetalleView = () => import('../views/ServicioDetalleView.vue');
const CamaraDetailView = () => import('../views/CamaraDetailView.vue');
const VerificadorCromoView = () => import('../views/VerificadorCromoView.vue');
const EmpalmesBotellaCromoView = () => import('../views/EmpalmesBotellaCromoView.vue');
const ConectoresOdfCromoView = () => import('../views/ConectoresOdfCromoView.vue');
const ValidarDatosCromoView = () => import('../views/ValidarDatosCromoView.vue');
const InventarioCablesCromoView = () => import('../views/InventarioCablesCromoView.vue');
const FoMonitorView = () => import('../views/FoMonitorView.vue');
const CableDetalleCromoView = () => import('../views/CableDetalleCromoView.vue');
const InventarioOdfsCromoView = () => import('../views/InventarioOdfsCromoView.vue');
const InventarioPonCromoView = () => import('../views/InventarioPonCromoView.vue');
const OdfDetalleCromoView = () => import('../views/OdfDetalleCromoView.vue');
const BotellasInventarioView = () => import('../views/BotellasInventarioView.vue');
const BotellaDetalleUnificadaView = () => import('../views/BotellaDetalleUnificadaView.vue');
const RepetitividadTab = () => import('../views/tabs/RepetitividadTab.vue');
const VlanTab = () => import('../views/tabs/VlanTab.vue');
const FoTab = () => import('../views/tabs/FoTab.vue');
const CienaTab = () => import('../views/tabs/CienaTab.vue');
const InfraTab = () => import('../views/tabs/InfraTab.vue');
const AdminDashboard = () => import('../admin/views/AdminDashboard.vue');
const AdminUsuarios = () => import('../admin/views/AdminUsuarios.vue');
const AdminServicios = () => import('../admin/views/AdminServicios.vue');
const AdminServiciosViewer = () => import('../admin/views/AdminServiciosViewer.vue');
const AdminCamarasViewer = () => import('../admin/views/AdminCamarasViewer.vue');
const AdminBotellasViewer = () => import('../admin/views/AdminBotellasViewer.vue');
const AdminServiciosSinOdfViewer = () => import('../admin/views/AdminServiciosSinOdfViewer.vue');
const AdminHuerfanosViewer = () => import('../admin/views/AdminHuerfanosViewer.vue');
const AdminInconsistenciasCromoViewer = () => import('../admin/views/AdminInconsistenciasCromoViewer.vue');
const AdminIngesta = () => import('../admin/views/AdminIngesta.vue');
const AdminIngestaServicios = () => import('../admin/views/AdminIngestaServicios.vue');
const AdminIngestaCamaras = () => import('../admin/views/AdminIngestaCamaras.vue');
const AdminIngestaCromo = () => import('../admin/views/AdminIngestaCromo.vue');
const AdminBaneos = () => import('../admin/views/AdminBaneos.vue');
const AdminClientesCategoria = () => import('../admin/views/AdminClientesCategoria.vue');

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: AppShell,
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'panel',
        component: PanelView,
      },
      {
        path: 'infra',
        name: 'infra',
        component: InfraTab,
      },
      {
        path: 'repetitividad',
        name: 'repetitividad',
        component: RepetitividadTab,
      },
      {
        path: 'toolkit/vlan',
        name: 'toolkit-vlan',
        component: VlanTab,
      },
      {
        path: 'fo',
        name: 'fo',
        component: FoTab,
      },
      {
        path: 'toolkit/validar-datos-cromo',
        name: 'toolkit-validar-datos-cromo',
        component: ValidarDatosCromoView,
      },
      {
        path: 'dwdm/ciena',
        name: 'dwdm-ciena',
        component: CienaTab,
      },
      {
        path: 'sla',
        name: 'sla',
        component: SlaView,
      },
      {
        path: 'reports-history',
        name: 'reports-history',
        component: ReportsHistoryView,
      },
      {
        path: 'servicios',
        name: 'servicios',
        component: ServiciosView,
      },
      {
        path: 'servicios/ID/:idServicio',
        name: 'servicios-detail',
        component: ServicioDetalleView,
      },
      // Una ruta por sección: la ficha quedó compacta y cada detalle se abre en su propia vista,
      // linkeable y compartible. Ojo: la navegación real está hardcodeada en `AppShell.vue`, así
      // que estas rutas también se mapean en su `resolveCurrentView` para que el módulo
      // "Servicios" quede marcado activo.
      {
        path: 'servicios/ID/:idServicio/historico',
        name: 'servicios-detail-historico',
        component: ServicioHistoricoView,
      },
      {
        path: 'servicios/ID/:idServicio/ingresos',
        name: 'servicios-detail-ingresos',
        component: ServicioIngresosView,
      },
      {
        path: 'servicios/ID/:idServicio/camino',
        name: 'servicios-detail-camino',
        component: ServicioCaminoView,
      },
      {
        path: 'servicios/ID/:idServicio/reclamos',
        name: 'servicios-detail-reclamos',
        component: ServicioReclamosView,
      },
      {
        path: 'servicios/ID/:idServicio/baneos',
        name: 'servicios-detail-baneos',
        component: ServicioBaneosView,
      },
      { path: 'infra/Camaras/:id(\\d+)', name: 'camara-detail', component: CamaraDetailView },
      { path: 'infra/cromo/verificador', name: 'infra-cromo-verificador', component: VerificadorCromoView },
      {
        path: 'infra/cromo/verificador/empalmes',
        name: 'infra-cromo-verificador-empalmes',
        component: EmpalmesBotellaCromoView,
      },
      { path: 'infra/fo-monitor', name: 'infra-fo-monitor', component: FoMonitorView },
      { path: 'infra/cromo/cables', name: 'infra-cromo-cables', component: InventarioCablesCromoView },
      {
        path: 'infra/cromo/cables/ID:nId(\\d+)',
        name: 'infra-cromo-cable-detalle',
        component: CableDetalleCromoView,
      },
      { path: 'infra/cromo/odfs', name: 'infra-cromo-odfs', component: InventarioOdfsCromoView },
      // Cajas PON y rosetas comparten vista y endpoint: `ponVariante` es lo que la vista lee para
      // decidir qué clases pedir y qué columnas mostrar. Dos rutas y un componente, porque son dos
      // entradas distintas en la navegación pero la misma pantalla.
      {
        path: 'infra/cromo/pon',
        name: 'infra-cromo-pon',
        component: InventarioPonCromoView,
        meta: { ponVariante: 'caja' },
      },
      {
        path: 'infra/cromo/rosetas',
        name: 'infra-cromo-rosetas',
        component: InventarioPonCromoView,
        meta: { ponVariante: 'roseta' },
      },
      {
        path: 'infra/cromo/odfs/ID:nId(\\d+)',
        name: 'infra-cromo-odf-detalle',
        component: OdfDetalleCromoView,
      },
      {
        path: 'infra/cromo/verificador/conectores',
        name: 'infra-cromo-verificador-conectores',
        component: ConectoresOdfCromoView,
      },
      { path: 'infra/Botellas', name: 'infra-botellas', component: BotellasInventarioView },
      {
        path: 'infra/Camaras/Botellas/ID:id(\\d+)',
        name: 'infra-botellas-detalle',
        component: BotellaDetalleUnificadaView,
      },
    ],
  },
  {
    path: '/admin',
    component: AppShell,
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      {
        path: '',
        name: 'admin-dashboard',
        component: AdminDashboard,
        meta: { requiresAdmin: true },
      },
      {
        path: 'usuarios',
        name: 'admin-usuarios',
        component: AdminUsuarios,
        meta: { requiresAdmin: true },
      },
      {
        path: 'servicios',
        name: 'admin-servicios',
        component: AdminServicios,
        meta: { requiresAdmin: true },
      },
      {
        path: 'Servicios/Baneos',
        name: 'admin-baneos',
        component: AdminBaneos,
        meta: { requiresAdmin: true },
      },
      {
        path: 'ingesta',
        name: 'admin-ingesta',
        component: AdminIngesta,
        meta: { requiresAdmin: true },
      },
      {
        path: 'ingesta/servicios',
        name: 'admin-ingesta-servicios',
        component: AdminIngestaServicios,
        meta: { requiresAdmin: true },
      },
      {
        path: 'ingesta/camaras',
        name: 'admin-ingesta-camaras',
        component: AdminIngestaCamaras,
        meta: { requiresAdmin: true },
      },
      {
        path: 'ingesta/cromo',
        name: 'admin-ingesta-cromo',
        component: AdminIngestaCromo,
        meta: { requiresAdmin: true },
      },
      {
        path: 'servicios/viewer',
        name: 'admin-servicios-viewer',
        component: AdminServiciosViewer,
        meta: { requiresAdmin: true },
      },
      {
        path: 'servicios/viewer/Camaras',
        name: 'admin-servicios-viewer-camaras',
        component: AdminCamarasViewer,
        meta: { requiresAdmin: true },
      },
      {
        path: 'servicios/viewer/Botellas',
        name: 'admin-servicios-viewer-botellas',
        component: AdminBotellasViewer,
        meta: { requiresAdmin: true },
      },
      {
        path: 'servicios/viewer/ServiciosSinOdf',
        name: 'admin-servicios-viewer-sin-odf',
        component: AdminServiciosSinOdfViewer,
        meta: { requiresAdmin: true },
      },
      {
        path: 'servicios/viewer/Huerfanos',
        name: 'admin-servicios-viewer-huerfanos',
        component: AdminHuerfanosViewer,
        meta: { requiresAdmin: true },
      },
      {
        path: 'servicios/viewer/InconsistenciasCromo',
        name: 'admin-servicios-viewer-inconsistencias-cromo',
        component: AdminInconsistenciasCromoViewer,
        meta: { requiresAdmin: true },
      },
      {
        path: 'servicios/clientes-categoria',
        name: 'admin-clientes-categoria',
        component: AdminClientesCategoria,
        meta: { requiresAdmin: true },
      },
      { path: ':pathMatch(.*)*', redirect: '/admin' },
    ],
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

const legacyTabRedirects: Record<string, string> = {
  infra: '/infra',
  rep: '/repetitividad',
  repetitividad: '/repetitividad',
  vlan: '/toolkit/vlan',
  fo: '/fo',
  ciena: '/dwdm/ciena',
};

router.beforeEach(async (to) => {
  if (to.path === '/' && typeof to.query.tab === 'string') {
    const legacyTab = to.query.tab.toLowerCase();
    const redirectPath = legacyTabRedirects[legacyTab];

    if (redirectPath) {
      const nextQuery = { ...to.query };
      delete nextQuery.tab;
      return { path: redirectPath, query: nextQuery };
    }
  }

  const { ensureSession, state } = useSession();
  await ensureSession();

  if (to.path === '/login') {
    return state.value.authenticated ? '/' : true;
  }

  // Rutas públicas
  if (to.meta.requiresAuth === false) return true;

  if (!state.value.authenticated) {
    return '/login';
  }

  if (to.meta.requiresAdmin && (state.value.role ?? '').toLowerCase() !== 'admin') {
    return '/';
  }

  return true;
});

export default router;
