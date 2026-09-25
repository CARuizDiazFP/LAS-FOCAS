// Nombre de archivo: timelineFormato.ts
// Ubicación de archivo: web/frontend/src/components/servicios/timelineFormato.ts
// Descripción: Formato compartido de la línea de tiempo de Servicios — estado y fecha, usados
// tanto por la tira horizontal compacta como por la vista dedicada del histórico completo

const ESTADOS_OK = new Set(['instalado', 'activo', 'vigente']);
const ESTADOS_ERROR = new Set(['dado baja', 'baja']);

/** Token de estado del hito: `is-ok` / `is-error` / `is-idle`. */
export function estadoClase(estado: string): string {
  const valor = estado.trim().toLowerCase();
  if (ESTADOS_OK.has(valor)) return 'is-ok';
  if (ESTADOS_ERROR.has(valor)) return 'is-error';
  return 'is-idle';
}

const FECHA_SOLO_DIA = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Formatea una fecha de hito en es-AR.
 *
 * `fecha_instalacion`/`fecha_baja` llegan como fecha pura ("2019-11-01": campo `date` de Pydantic,
 * sin hora ni offset). `new Date("2019-11-01")` la interpreta como medianoche UTC y, formateada en
 * Argentina (UTC-3), muestra el día ANTERIOR ("31/10/2019"). Por eso la fecha pura se parsea a mano
 * y se construye con el constructor de 3 argumentos, que es hora LOCAL (nunca UTC) — así el día
 * formateado es el mismo en cualquier zona horaria.
 *
 * Una fecha imposible ("2019-13-45") cae al fallback de siempre: se devuelve el string crudo.
 */
export function formatearFecha(fecha: string): string {
  const soloDia = FECHA_SOLO_DIA.exec(fecha.trim());
  if (soloDia) {
    const [, anio, mes, dia] = soloDia;
    const local = new Date(Number(anio), Number(mes) - 1, Number(dia));
    const esFechaReal =
      !Number.isNaN(local.getTime()) &&
      local.getFullYear() === Number(anio) &&
      local.getMonth() === Number(mes) - 1 &&
      local.getDate() === Number(dia);
    if (esFechaReal) {
      return local.toLocaleDateString('es-AR', { year: 'numeric', month: '2-digit', day: '2-digit' });
    }
    return fecha;
  }

  const parsed = new Date(fecha);
  if (Number.isNaN(parsed.getTime())) return fecha;
  return parsed.toLocaleDateString('es-AR', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

/** Fecha corta para la tira horizontal, donde el año completo no entra. */
export function formatearFechaCorta(fecha: string): string {
  const completa = formatearFecha(fecha);
  const partes = completa.split('/');
  return partes.length === 3 ? `${partes[0]}/${partes[1]}/${partes[2].slice(-2)}` : completa;
}
