# Nombre de archivo: test_sla_web.py
# Ubicación de archivo: scripts/test_sla_web.py
# Descripción: Script para probar el endpoint SLA directamente y capturar errores

import asyncio
import io
from pathlib import Path
import pandas as pd
from fastapi.datastructures import UploadFile


async def test_sla_endpoint():
    """Prueba del flujo completo del endpoint SLA."""
    # Simular Excel de servicios
    servicios_df = pd.DataFrame([{
        'Tipo Servicio': 'Fibra',
        'Número Línea': 'SRV-01',
        'Nombre Cliente': 'Cliente Demo',
        'Horas Reclamos Todos': '01:30:00',
        'SLA Entregado': 0.985,
    }])
    buffer_servicios = io.BytesIO()
    with pd.ExcelWriter(buffer_servicios, engine='openpyxl') as writer:
        servicios_df.to_excel(writer, index=False)
    buffer_servicios.seek(0)
    
    # Simular Excel de reclamos
    reclamos_df = pd.DataFrame([{
        'Número Línea': 'SRV-01',
        'Número Reclamo': 'R-001',
        'Horas Netas Reclamo': '1.5',
        'Tipo Solución Reclamo': 'Corte',
        'Fecha Inicio Reclamo': '2025-06-10 08:00',
    }])
    buffer_reclamos = io.BytesIO()
    with pd.ExcelWriter(buffer_reclamos, engine='openpyxl') as writer:
        reclamos_df.to_excel(writer, index=False)
    buffer_reclamos.seek(0)
    
    # Crear UploadFiles simulados
    servicios_file = UploadFile(
        filename="Servicios Fuera de SLA.xlsx",
        file=buffer_servicios,
    )
    reclamos_file = UploadFile(
        filename="Reclamos SLA (1).xlsx",
        file=buffer_reclamos,
    )
    
    files = [servicios_file, reclamos_file]
    
    # Simular el procesamiento del endpoint
    from core.services import sla as sla_service
    
    try:
        print("Procesando archivos...")
        servicios_bytes: bytes | None = None
        reclamos_bytes: bytes | None = None
        
        for archivo in files:
            nombre = Path(archivo.filename).name
            print(f"Procesando: {nombre}")
            
            if not nombre.lower().endswith(".xlsx"):
                print(f"ERROR: {nombre} no tiene extensión .xlsx")
                return
            
            contenido = await archivo.read()
            await archivo.close()
            
            if not contenido:
                print(f"ERROR: {nombre} está vacío")
                return
            
            try:
                tipo = sla_service.identify_excel_kind(contenido)
                print(f"  Tipo identificado: {tipo}")
            except ValueError as exc:
                print(f"ERROR identificando tipo: {exc}")
                return
            
            if tipo == "servicios":
                if servicios_bytes is not None:
                    print("ERROR: Se recibió más de un Excel de servicios")
                    return
                servicios_bytes = contenido
            else:
                if reclamos_bytes is not None:
                    print("ERROR: Se recibió más de un Excel de reclamos")
                    return
                reclamos_bytes = contenido
        
        if servicios_bytes is None or reclamos_bytes is None:
            print("ERROR: Faltan archivos")
            return
        
        print("Generando informe...")
        documento = sla_service.generate_report_from_excel_pair(
            servicios_bytes,
            reclamos_bytes,
            mes=10,
            anio=2025,
            incluir_pdf=False,
        )
        
        print(f"SUCCESS: Informe generado en {documento.docx}")
        
    except Exception as exc:
        print(f"ERROR INESPERADO: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_sla_endpoint())
