
# Nombre de archivo: test_map_generation.py
# Ubicación de archivo: scripts/test_map_generation.py
# Descripción: Script para probar la generación de mapas estáticos.

import logging
from pathlib import Path
from core.maps.static_map import build_static_map_png, MapStyle

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Coordenadas de ejemplo en Buenos Aires
    points = [
        (-34.6037, -58.3816), # Obelisco
        (-34.588, -58.423),   # Plaza Serrano
    ]
    output_path = Path("map_test.png")

    print(f"Generando mapa en {output_path.resolve()}")

    try:
        build_static_map_png(points, output_path)
        print("Mapa generado exitosamente.")
    except Exception as e:
        print(f"Error al generar el mapa: {e}")

    # Probando con un solo punto
    output_path_single = Path("map_test_single.png")
    print(f"Generando mapa de un solo punto en {output_path_single.resolve()}")
    try:
        build_static_map_png([points[0]], output_path_single)
        print("Mapa de un solo punto generado exitosamente.")
    except Exception as e:
        print(f"Error al generar el mapa de un solo punto: {e}")
