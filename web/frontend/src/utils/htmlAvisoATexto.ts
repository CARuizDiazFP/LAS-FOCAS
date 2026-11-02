// Nombre de archivo: htmlAvisoATexto.ts
// Ubicación de archivo: web/frontend/src/utils/htmlAvisoATexto.ts
// Descripción: Pasa a texto plano el cuerpo HTML guardado de un aviso de baneo (email_body) para el textarea del modal

/** Lo mínimo de un `Node` que usa el recorrido (así se prueba sin DOM). */
export interface NodoAviso {
  nodeType: number;
  nodeName: string;
  textContent: string | null;
  childNodes: ArrayLike<NodoAviso>;
  getAttribute?(nombre: string): string | null;
}

const TEXTO = 3;
const ELEMENTO = 1;
const PARRAFOS = new Set(['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TABLE', 'UL', 'OL']);
const LINEAS = new Set(['DIV', 'TR', 'LI', 'SECTION', 'HEADER', 'FOOTER']);
const OMITIDOS = new Set(['STYLE', 'SCRIPT', 'HEAD', 'TITLE']);

/** El cuerpo que guardan el panel y el envío por SMTP (P27) es el envoltorio de `textoPlanoAHtml`: un único
 * `div` con `white-space: pre-wrap`. Su texto vuelve tal cual, con los saltos y los espacios del usuario, para
 * que guardar y reabrir no los colapse; `null` si el cuerpo es otra cosa (p. ej. la plantilla HTML vieja). */
export function textoDeEnvoltorioPreWrap(raiz: NodoAviso): string | null {
  const hijos = Array.from(raiz.childNodes).filter(
    (n) => n.nodeType === ELEMENTO || (n.nodeType === TEXTO && (n.textContent ?? '').trim() !== ''),
  );
  if (hijos.length !== 1) return null;
  const [div] = hijos;
  if (div.nodeName !== 'DIV' || !/white-space\s*:\s*pre-wrap/i.test(div.getAttribute?.('style') ?? '')) return null;
  return (div.textContent ?? '').trim();
}

/** Recorre el cuerpo hasta el primer `<hr>` (el pie "Generado por LAS-FOCAS" de los avisos guardados):
 * párrafos, títulos y tablas quedan separados por una línea en blanco; `div`, filas e ítems, por un salto;
 * `<br>` es un salto. */
export function textoDeNodoAviso(raiz: NodoAviso): string {
  let cortado = false;
  const recorrer = (nodo: NodoAviso): string => {
    if (cortado) return '';
    if (nodo.nodeType === TEXTO) return (nodo.textContent ?? '').replace(/\s+/g, ' ');
    if (nodo.nodeType !== ELEMENTO || OMITIDOS.has(nodo.nodeName)) return '';
    if (nodo.nodeName === 'HR') {
      cortado = true;
      return '';
    }
    if (nodo.nodeName === 'BR') return '\n';
    const dentro = Array.from(nodo.childNodes).map(recorrer).join('');
    if (PARRAFOS.has(nodo.nodeName)) return `\n\n${dentro}\n\n`;
    if (LINEAS.has(nodo.nodeName)) return `\n${dentro}\n`;
    if (nodo.nodeName === 'TD' || nodo.nodeName === 'TH') return `${dentro} `;
    return dentro;
  };
  return recorrer(raiz)
    .replace(/[ \t]*\n[ \t]*/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/** `email_body` lo guardan como HTML el `download-eml` y el envío por SMTP, en el panel y en la API: el
 * envoltorio de `textoPlanoAHtml` (desde P27) o, en los guardados viejos, el documento completo de la plantilla.
 * El modal edita texto plano y `textoPlanoAHtml` lo vuelve a envolver al descargar. Si ya es texto, va tal cual.
 * `DOMParser` arma un documento inerte (no ejecuta scripts ni carga recursos) y sólo se lee su texto. */
export function htmlAvisoATexto(html: string): string {
  if (!/<[a-z!/][^>]*>/i.test(html)) return html.trim();
  const cuerpo = new DOMParser().parseFromString(html, 'text/html').body;
  return textoDeEnvoltorioPreWrap(cuerpo) ?? textoDeNodoAviso(cuerpo);
}
