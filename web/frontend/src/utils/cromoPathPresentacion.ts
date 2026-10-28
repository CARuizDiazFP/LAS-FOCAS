// Nombre de archivo: cromoPathPresentacion.ts
// Ubicación de archivo: web/frontend/src/utils/cromoPathPresentacion.ts
// Descripción: Helpers de presentación del camino óptico de Cromo (etiquetas, íconos y mensajes de error); los tipos viven en api/cromoPath.ts

import { ApiError } from '../api/client';
import type {
  CaminoAdicional,
  ExtremoCamino,
  PosicionPosible,
  TramoDelServicio,
} from '../api/cromoPath';

const TIPO_NODO_LABELS: Record<string, string> = {
  PELO: 'Pelo',
  FUSION: 'Fusión',
  CONECTOR_ODF: 'Conector de ODF',
  NO_RESUELTO: 'No resuelto por Cromo',
  CLASE_DESCONOCIDA: 'Clase desconocida',
  CABLE: 'Cable',
  BOTELLA: 'Botella',
  TUBO: 'Tubo',
  ODF: 'ODF',
  PATCHERA: 'Patchera',
  CAMARA: 'Cámara',
  SPLITTER: 'Splitter',
  PUERTO_SPLITTER: 'Puerto de splitter',
  CAJA_PON: 'Caja PON',
  CABLE_BAJADA: 'Cable de bajada',
  NODO: 'Nodo',
  ODF_NODO: 'ODF Nodo',
  FUSION_ODF: 'Fusión en ODF',
  ROSETA: 'Roseta',
};

/** Ícono Phosphor por tipo de nodo. Deliberadamente NO se usa color: los tipos se distinguen por
 * ícono para no introducir una paleta categórica nueva (ver nocturne-token-compliance). */
const TIPO_NODO_ICONOS: Record<string, string> = {
  PELO: 'ph-line-segment',
  FUSION: 'ph-arrows-merge',
  CONECTOR_ODF: 'ph-plugs-connected',
  NO_RESUELTO: 'ph-warning',
  CABLE: 'ph-line-segment',
  BOTELLA: 'ph-package',
  ODF: 'ph-plugs-connected',
  CAMARA: 'ph-map-pin',
  SPLITTER: 'ph-share-network',
  PUERTO_SPLITTER: 'ph-arrow-elbow-down-right',
  CAJA_PON: 'ph-package',
  CABLE_BAJADA: 'ph-line-segment',
  NODO: 'ph-buildings',
  ODF_NODO: 'ph-buildings',
  FUSION_ODF: 'ph-arrows-merge',
  ROSETA: 'ph-house-line',
};

export function tipoNodoLabel(tipo: string): string {
  return TIPO_NODO_LABELS[tipo] ?? tipo;
}

export function tipoNodoIcono(tipo: string): string {
  return TIPO_NODO_ICONOS[tipo] ?? 'ph-question';
}

/** "ODF X P1:39" / "ODF Nodo KORN P1:39" para un conector de ODF; "pelo 123" en cualquier otro caso. */
export function etiquetaExtremo(extremo: ExtremoCamino | null): string {
  if (!extremo) return '?';
  if (extremo.tipo !== 'CONECTOR_ODF' || extremo.odf_n_id == null) {
    return `pelo ${extremo.id_cromo}`;
  }
  const tipoOdf = extremo.odf_clase === 86 ? 'ODF Nodo' : 'ODF';
  const nombre = extremo.odf_nombre ?? String(extremo.odf_n_id);
  const posicion = [extremo.patchera_nombre, extremo.conector].filter(Boolean).join(':');
  return [tipoOdf, nombre, posicion].filter(Boolean).join(' ');
}

/** "Tramo 1 · ODF X:39 → ODF Nodo KORN O-1259853-1:39 · 24 pelos". */
export function etiquetaTramo(tramo: TramoDelServicio): string {
  return (
    `Tramo ${tramo.n} · ${etiquetaExtremo(tramo.extremos.a)} → ` +
    `${etiquetaExtremo(tramo.extremos.b)} · ${tramo.pelos_en_camino} pelos`
  );
}

/** "Adicional 1 · ODF X P1:1 → ODF Y P2:1 · 40 pelos". */
export function etiquetaAdicional(adicional: CaminoAdicional): string {
  return (
    `Adicional ${adicional.n} · ${etiquetaExtremo(adicional.extremos.a)} → ` +
    `${etiquetaExtremo(adicional.extremos.b)} · ${adicional.pelos_en_camino} pelos`
  );
}

/** "ODF San Martin 137 P5 D · O-1252871-1:1 · pelo 1 F-PC-CC · etiqueta 44649 (otra etiqueta)". */
export function etiquetaPosicion(posicion: PosicionPosible): string {
  const bandejaConector =
    posicion.bandeja_nombre && posicion.numero_conector
      ? `${posicion.bandeja_nombre}:${posicion.numero_conector}`
      : posicion.posicion;
  const partes = [
    `ODF ${posicion.odf_nombre ?? posicion.odf_n_id ?? '?'}`,
    bandejaConector,
    ['pelo', posicion.numero_pelo, posicion.cable_nombre].filter(Boolean).join(' '),
    posicion.etiqueta_pelo ? `etiqueta ${posicion.etiqueta_pelo}` : null,
  ];
  const texto = partes.filter(Boolean).join(' · ');
  return posicion.etiqueta_ajena ? `${texto} (otra etiqueta)` : texto;
}


/**
 * Traduce un error del camino óptico a un mensaje accionable.
 *
 * Los textos de 404/502 son deliberadamente los mismos que ya usa `ModalVerificadorCromo` para
 * que el operador reconozca el mismo error en dos pantallas distintas.
 */
export function mensajeErrorCromoPath(
  error: unknown,
  contexto: { peloNId?: number | null } = {},
): string {
  if (error instanceof DOMException && error.name === 'TimeoutError') {
    return 'Cromo no respondió en 30 s. Podés seguir con la asociación manual: el camino es una señal, no un requisito.';
  }
  if (error instanceof ApiError) {
    if (error.status === 404) {
      const pelo = contexto.peloNId ? ` (pelo ${contexto.peloNId})` : '';
      return `Cromo no conoce este camino${pelo}. Puede haberse dado de baja, o el n_id local quedó desactualizado respecto de Cromo.`;
    }
    if (error.status === 502) {
      return 'Cromo no respondió. Probá de nuevo en un momento.';
    }
    if (error.status === 504 || error.status === 408) {
      return 'El backend cortó la espera de Cromo. El camino puede ser muy largo o Cromo estar saturado — probá de nuevo, o resolvé con otro pelo.';
    }
    if (error.status === 409) {
      return 'Este Servicio no tiene un camino que se pueda resolver: no hay ningún pelo de Cromo asociado.';
    }
    if (error.status === 403) {
      return 'Necesitás rol admin para resolver el camino óptico.';
    }
  }
  return error instanceof Error ? error.message : 'Error resolviendo el camino óptico en Cromo.';
}

/**
 * Error de leer, declarar o retirar la posición vigente. El backend ya manda un mensaje accionable
 * (409 "el conector X no es posición posible…", 404 "no tenía una posición vigente…"); los textos
 * genéricos de `mensajeErrorCromoPath` hablan de resolver el camino y acá confundirían.
 */
export function mensajeErrorPosicionVigente(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return 'Elegí entre 1 y 8 conectores para declarar.';
    if (error.status === 403 && error.message === 'CSRF inválido') {
      return 'La sesión venció: recargá la página y volvé a intentarlo.';
    }
    if (error.status === 403) return 'Necesitás rol admin para declarar la posición vigente.';
    return error.message;
  }
  return error instanceof Error ? error.message : 'Error con la posición vigente del Servicio.';
}
