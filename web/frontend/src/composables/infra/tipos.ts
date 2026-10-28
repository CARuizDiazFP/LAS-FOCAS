// Nombre de archivo: tipos.ts
// Ubicación de archivo: web/frontend/src/composables/infra/tipos.ts
// Descripción: Tipos compartidos entre InfraTab, sus composables y sus modales hijos

/** Muestra un toast en InfraTab; los modales lo reciben como prop `notificar`. */
export type Notificar = (
  tipo: 'success' | 'error' | 'warning' | 'info',
  titulo: string,
  mensaje?: string,
) => void;
