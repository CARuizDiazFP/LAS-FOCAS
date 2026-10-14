// Nombre de archivo: colores.ts
// Ubicación de archivo: web/frontend/src/components/fo-monitor/colores.ts
// Descripción: Colores del semáforo de FO Monitor resueltos desde los tokens Nocturne a rgb() para MapLibre

import type { ColorSemaforo } from '../../api/foMonitor';

export const TOKEN_POR_COLOR: Record<ColorSemaforo, string> = {
  VERDE: '--color-state-ok',
  AMARILLO: '--color-state-warn',
  NARANJA: '--color-state-degraded',
  ROJO: '--color-state-error',
  GRIS: '--color-state-idle',
};

export const ETIQUETA_COLOR: Record<ColorSemaforo, string> = {
  VERDE: 'Operativo (≥ 80 % UP)',
  AMARILLO: 'Caída nueva al egreso',
  NARANJA: 'Degradado (< 80 % UP)',
  ROJO: 'Caída total',
  GRIS: 'Sin dato / sin verificables',
};

/** MapLibre no lee variables CSS y los tokens son oklch(): se pintan en un canvas 1×1 y se lee el
 * pixel, que siempre devuelve sRGB sin importar el formato de origen. */
export function resolverToken(token: string, fallback = 'rgb(147, 151, 171)'): string {
  const valor = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  if (!valor) return fallback;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return fallback;
  const probe = document.createElement('span');
  probe.style.color = valor;
  document.body.appendChild(probe);
  const color = getComputedStyle(probe).color;
  probe.remove();
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return `rgb(${r}, ${g}, ${b})`;
}

export function paletaSemaforo(): Record<ColorSemaforo, string> {
  return Object.fromEntries(
    Object.entries(TOKEN_POR_COLOR).map(([color, token]) => [color, resolverToken(token)]),
  ) as Record<ColorSemaforo, string>;
}

/** Colores categóricos para resaltar servicios (máx. 8). Misma luminosidad/croma entre sí y tonos
 * alejados de los del semáforo (verde 155, ámbar 75, naranja 50, rojo 25) para no confundirlos. */
export const PALETA_SERVICIOS = [
  'oklch(0.74 0.15 285)', // violeta
  'oklch(0.74 0.13 225)', // azul
  'oklch(0.78 0.12 195)', // cian
  'oklch(0.72 0.17 330)', // magenta
  'oklch(0.80 0.12 110)', // lima
  'oklch(0.70 0.14 255)', // índigo
  'oklch(0.78 0.10 170)', // turquesa
  'oklch(0.72 0.12 0)',   // rosa
];

export function resolverColor(valor: string, fallback = 'rgb(147, 151, 171)'): string {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return fallback;
  const probe = document.createElement('span');
  probe.style.color = valor;
  document.body.appendChild(probe);
  const color = getComputedStyle(probe).color;
  probe.remove();
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return `rgb(${r}, ${g}, ${b})`;
}

export function colorServicio(indice: number): string {
  return PALETA_SERVICIOS[indice % PALETA_SERVICIOS.length];
}
