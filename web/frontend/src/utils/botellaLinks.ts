// Nombre de archivo: botellaLinks.ts
// Ubicación de archivo: web/frontend/src/utils/botellaLinks.ts
// Descripción: Construye la ruta del shim de detalle de Botella (BotellaDetalleUnificadaView.vue) por origen

import type { BotellaOrigen } from '../api/botellas';

/**
 * `BotellaDetalleUnificadaView.vue` (ruta `/infra/Camaras/Botellas/ID:id`) reenvía al detalle real
 * según `route.query.origen` — este helper centraliza cómo armar esa ruta para que ningún
 * componente (`BotellasInventarioView.vue`, `ModalBotellas.vue`) tenga que reconstruirla a mano.
 */
export function botellaDetailPath(origen: BotellaOrigen, id: number) {
  return { path: `/infra/Camaras/Botellas/ID${id}`, query: { origen } };
}
