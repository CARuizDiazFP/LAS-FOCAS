// Nombre de archivo: textoPlanoAHtml.ts
// Ubicación de archivo: web/frontend/src/utils/textoPlanoAHtml.ts
// Descripción: Convierte texto plano en HTML seguro que conserva los saltos de línea (cuerpo del .eml)

const ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

/** Escapa `& < > " '` y envuelve en un `div` con `white-space: pre-wrap`: el backend arma el
 * `.eml` como HTML, así que sin esto se pierden los saltos y `<`/`&` se interpretan como markup. */
export function textoPlanoAHtml(texto: string): string {
  const escapado = texto.replace(/[&<>"']/g, (c) => ESCAPES[c]);
  return `<div style="white-space:pre-wrap;font-family:inherit">${escapado}</div>`;
}
