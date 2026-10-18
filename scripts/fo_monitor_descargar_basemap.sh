#!/usr/bin/env bash
# Nombre de archivo: fo_monitor_descargar_basemap.sh
# Ubicación de archivo: scripts/fo_monitor_descargar_basemap.sh
# Descripción: Descarga el mapa base offline de FO Monitor (recorte PMTiles del AMBA + fuentes y sprites de protomaps)
#
# Requisito del relevamiento (2026-10-14): el mapa funciona sin Internet. Se descarga UNA vez (la VM
# sí tiene salida) un recorte del AMBA del build diario de protomaps y los assets del estilo, a un
# directorio que se monta de sólo lectura en el contenedor web (FOMON_BASEMAP_DIR).
#
# Por defecto sólo MIDE (dry-run): imprime cuánto ocuparía el recorte. Con --aplicar descarga.
#
# Uso:
#   scripts/fo_monitor_descargar_basemap.sh                      # dry-run, build de hoy
#   scripts/fo_monitor_descargar_basemap.sh --aplicar            # descarga a data/fo_monitor/
#   scripts/fo_monitor_descargar_basemap.sh --aplicar --maxzoom 14 --fecha 20261013 --destino /ruta

set -euo pipefail

PMTILES_VERSION="1.31.2"                                        # go-pmtiles, release 2026-07-22
# El release no publica checksums: SHA-256 del tarball Linux_x86_64 fijado al incorporarlo (2026-10-14).
PMTILES_SHA256="3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f"
ASSETS_COMMIT="028c18f713baecad011301ff7a69acc39bcc2ae7"        # protomaps/basemaps-assets, 2025-10-31
BBOX="-60.10,-35.50,-57.90,-34.15"                              # AMBA ampliado (99 % de las botellas)
FUENTES=("Noto Sans Regular" "Noto Sans Medium" "Noto Sans Italic")
SPRITE="dark"

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINO="${RAIZ}/data/fo_monitor"
MAXZOOM=15
FECHA="$(date -u +%Y%m%d)"
APLICAR=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --aplicar) APLICAR=1 ;;
    --maxzoom) MAXZOOM="$2"; shift ;;
    --fecha) FECHA="$2"; shift ;;
    --destino) DESTINO="$2"; shift ;;
    *) echo "Opción desconocida: $1" >&2; exit 2 ;;
  esac
  shift
done

HERRAMIENTAS="${HOME}/.cache/las-focas/pmtiles/${PMTILES_VERSION}"
PMTILES="${HERRAMIENTAS}/pmtiles"
if [[ ! -x "${PMTILES}" ]]; then
  mkdir -p "${HERRAMIENTAS}"
  base="https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}"
  tarball="go-pmtiles_${PMTILES_VERSION}_Linux_x86_64.tar.gz"
  curl -fsSL -o "${HERRAMIENTAS}/${tarball}" "${base}/${tarball}"
  echo "${PMTILES_SHA256}  ${HERRAMIENTAS}/${tarball}" | sha256sum -c -
  tar -xzf "${HERRAMIENTAS}/${tarball}" -C "${HERRAMIENTAS}" pmtiles
fi

ORIGEN="https://build.protomaps.com/${FECHA}.pmtiles"
echo "Origen: ${ORIGEN}  bbox=${BBOX}  maxzoom=${MAXZOOM}"
"${PMTILES}" extract "${ORIGEN}" "${DESTINO}/amba.pmtiles" --bbox="${BBOX}" --maxzoom="${MAXZOOM}" --dry-run

if [[ "${APLICAR}" -ne 1 ]]; then
  echo "Dry-run: no se descargó nada. Repetir con --aplicar para descargar a ${DESTINO}."
  exit 0
fi

mkdir -p "${DESTINO}"
echo "Espacio libre antes: $(df -h "${DESTINO}" | awk 'NR==2 {print $4}')"
"${PMTILES}" extract "${ORIGEN}" "${DESTINO}/amba.pmtiles.tmp" --bbox="${BBOX}" --maxzoom="${MAXZOOM}"
mv "${DESTINO}/amba.pmtiles.tmp" "${DESTINO}/amba.pmtiles"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
curl -fsSL -o "${TMP}/assets.zip" "https://github.com/protomaps/basemaps-assets/archive/${ASSETS_COMMIT}.zip"
python3 -I - "${TMP}/assets.zip" "${DESTINO}" "${SPRITE}" "${FUENTES[@]}" <<'PY'
import sys, zipfile
from pathlib import Path
zip_path, destino, sprite, *fuentes = sys.argv[1:]
destino = Path(destino)
with zipfile.ZipFile(zip_path) as z:
    for nombre in z.namelist():
        partes = nombre.split("/", 1)
        if len(partes) < 2 or nombre.endswith("/"):
            continue
        rel = partes[1]
        es_fuente = any(rel.startswith(f"fonts/{f}/") for f in fuentes)
        es_sprite = rel.startswith(f"sprites/v4/{sprite}")
        if not (es_fuente or es_sprite):
            continue
        salida = (destino / rel).resolve()
        if destino.resolve() not in salida.parents:
            raise SystemExit(f"ruta sospechosa en el zip: {nombre}")
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_bytes(z.read(nombre))
print("assets extraídos")
PY

du -sh "${DESTINO}"/amba.pmtiles "${DESTINO}"/fonts "${DESTINO}"/sprites
echo "Espacio libre después: $(df -h "${DESTINO}" | awk 'NR==2 {print $4}')"
