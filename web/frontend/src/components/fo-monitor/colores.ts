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
