// Nombre de archivo: timeline.ts
// Ubicación de archivo: web/frontend/src/types/timeline.ts
// Descripción: Tipo genérico de evento para el componente ServiceTimeline — admite historial de upgrades de ID hoy, y Reclamos/Ingresos/Mantenimientos a futuro

export type TimelineEventType = 'upgrade_id' | 'reclamo' | 'ingreso' | 'mantenimiento';

export interface TimelineEvent {
  id: string | number;
  fecha: string | null;
  tipo: TimelineEventType;
  titulo: string;
  estado?: string;
  descripcion?: string;
  metadata?: Record<string, string | number | null>;
}
