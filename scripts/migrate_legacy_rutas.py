# Nombre de archivo: migrate_legacy_rutas.py
# Ubicación de archivo: scripts/migrate_legacy_rutas.py
# Descripción: Script para migrar servicios legacy al nuevo modelo de rutas
"""
Script de migración: Convertir servicios legacy al modelo de rutas.

Este script crea una RutaServicio "Principal" para cada servicio que no tenga rutas,
copiando los empalmes de la relación legacy (servicio_empalme_association)
a la nueva tabla (ruta_empalme_association).

Uso:
    # Desde la raíz del proyecto:
    python scripts/migrate_legacy_rutas.py
    
    # O dentro del contenedor:
    docker exec lasfocas-api python /app/scripts/migrate_legacy_rutas.py
"""

from __future__ import annotations

import logging
import os
import sys

# Agregar el directorio raíz al path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from db.models.infra import (
    Servicio,
    RutaServicio,
    RutaTipo,
    ruta_empalme_association,
)
from db.session import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def migrate_legacy_servicios() -> dict:
    """Migra servicios legacy al nuevo modelo de rutas.
    
    Returns:
        Dict con estadísticas de la migración
    """
    stats = {
        "servicios_procesados": 0,
        "rutas_creadas": 0,
        "empalmes_migrados": 0,
        "servicios_sin_empalmes": 0,
        "servicios_ya_migrados": 0,
        "errores": [],
    }
    
    with SessionLocal() as session:
        # Obtener todos los servicios
        servicios = session.query(Servicio).all()
        logger.info("Total de servicios en BD: %d", len(servicios))
        
        for servicio in servicios:
            try:
                # Verificar si ya tiene rutas
                if servicio.rutas:
                    stats["servicios_ya_migrados"] += 1
                    logger.debug(
                        "Servicio %s ya tiene %d rutas, omitiendo",
                        servicio.servicio_id,
                        len(servicio.rutas),
                    )
                    continue
                
                # Obtener empalmes de la relación legacy
                empalmes_legacy = servicio.empalmes
                
                if not empalmes_legacy:
                    stats["servicios_sin_empalmes"] += 1
                    logger.debug(
                        "Servicio %s no tiene empalmes legacy, omitiendo",
                        servicio.servicio_id,
                    )
                    continue
                
                # Crear ruta principal
                ruta = RutaServicio(
                    servicio_id=servicio.id,
                    nombre="Principal",
                    tipo=RutaTipo.PRINCIPAL,
                    activa=True,
                    nombre_archivo_origen=servicio.nombre_archivo_origen,
                )
                session.add(ruta)
                session.flush()  # Para obtener el ID de la ruta
                
                # Migrar empalmes a la nueva tabla asociativa
                for orden, empalme in enumerate(empalmes_legacy, start=1):
                    stmt = ruta_empalme_association.insert().values(
                        ruta_id=ruta.id,
                        empalme_id=empalme.id,
                        orden=orden,
                    )
                    session.execute(stmt)
                    stats["empalmes_migrados"] += 1
                
                stats["rutas_creadas"] += 1
                stats["servicios_procesados"] += 1
                
                logger.info(
                    "Migrado servicio %s: creada ruta ID=%d con %d empalmes",
                    servicio.servicio_id,
                    ruta.id,
                    len(empalmes_legacy),
                )
                
            except Exception as exc:
                error_msg = f"Error migrando servicio {servicio.servicio_id}: {exc}"
                stats["errores"].append(error_msg)
                logger.error(error_msg)
                session.rollback()
                continue
        
        # Commit final
        session.commit()
    
    return stats


def print_stats(stats: dict) -> None:
    """Imprime las estadísticas de la migración."""
    print("\n" + "=" * 60)
    print("RESUMEN DE MIGRACIÓN")
    print("=" * 60)
    print(f"Servicios procesados:    {stats['servicios_procesados']}")
    print(f"Rutas creadas:           {stats['rutas_creadas']}")
    print(f"Empalmes migrados:       {stats['empalmes_migrados']}")
    print(f"Servicios sin empalmes:  {stats['servicios_sin_empalmes']}")
    print(f"Servicios ya migrados:   {stats['servicios_ya_migrados']}")
    print(f"Errores:                 {len(stats['errores'])}")
    
    if stats["errores"]:
        print("\nErrores encontrados:")
        for error in stats["errores"]:
            print(f"  - {error}")
    
    print("=" * 60 + "\n")


def main() -> int:
    """Punto de entrada principal."""
    logger.info("Iniciando migración de servicios legacy a modelo de rutas...")
    
    try:
        stats = migrate_legacy_servicios()
        print_stats(stats)
        
        if stats["errores"]:
            return 1
        
        logger.info("Migración completada exitosamente")
        return 0
        
    except Exception as exc:
        logger.exception("Error fatal durante la migración: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
