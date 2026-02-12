import os
import glob
from sndlib_loader import SNDLibXMLParser
from green_models import ZodiacFX, NEC_PF5240

# --- CONFIGURACIÓN CORREGIDA (Mayúsculas importan) ---
BASE_DIR = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet"
PATHS = {
    "Abilene": os.path.join(BASE_DIR, "Abilene"),        # A mayúscula
    "Nobel-Germany": os.path.join(BASE_DIR, "Nobel-Germany")
}

def run_audit():
    print("==================================================")
    print("AUDITORÍA DE FÍSICA: ¿EL ZODIAC AGUANTA EL TRÁFICO CRUDO?")
    print("==================================================")
    
    # 1. Instanciar Modelos Físicos
    zodiac = ZodiacFX()
    nec = NEC_PF5240()
    
    print(f"CAPACIDAD FÍSICA ZODIAC: {zodiac.MU:,.0f} PPS")
    print(f"CAPACIDAD FÍSICA NEC:    {nec.MU:,.0f} PPS")
    
    # 2. Analizar cada topología
    for topo_name, folder_path in PATHS.items():
        print(f"\n--- Analizando: {topo_name} ---")
        
        if not os.path.isdir(folder_path):
            print(f"[SKIP] No existe la carpeta: {folder_path}")
            continue
            
        # --- FIX: ENCONTRAR UN XML REAL PARA INICIALIZAR ---
        xml_files = glob.glob(os.path.join(folder_path, "*.xml"))
        if not xml_files:
            print("[ERROR] Carpeta vacía (sin XMLs).")
            continue
            
        first_xml = xml_files[0] # Usamos el primero para aprender la topología
        
        # Inicializamos con un archivo real
        loader = SNDLibXMLParser(first_xml) 
        
        # --- FIX CRÍTICO: CARGAR EL GRAFO PRIMERO ---
        # Esto llena self.str_to_int para que el loader sepa quiénes son los nodos
        try:
            loader.get_graph() 
        except Exception as e:
            print(f"[ERROR] Falló al cargar topología base: {e}")
            continue
        
        # Ahora sí extraemos el tráfico PICO (Worst Case)
        peak_traffic = loader.get_peak_traffic_from_folder(folder_path, avg_packet_size_bytes=800)
        
        if not peak_traffic:
            print("[ERROR] No se pudo leer tráfico (Diccionario vacío).")
            continue
            
        # 3. Estadísticas
        vals = list(peak_traffic.values())
        if not vals: 
            print("[ALERTA] Se leyeron archivos pero no se encontró tráfico válido.")
            continue

        max_pps = max(vals)
        
        killed_nodes = 0
        risky_nodes = 0
        safe_nodes = 0
        
        print(f"{'Node ID':<10} | {'Load (PPS)':<15} | {'Estado Zodiac'}")
        print("-" * 45)
        
        # Imprimir resultados
        for node_id, load in peak_traffic.items():
            # Recuperar nombre real del nodo si es posible (solo para print)
            node_label = f"N{node_id}" 
            
            status = "✅ OK"
            if load > zodiac.MU:
                status = "💀 MUERTE"
                killed_nodes += 1
            elif load > (zodiac.MU * 0.9):
                status = "⚠️ RIESGO"
                risky_nodes += 1
            else:
                safe_nodes += 1
                
            # Mostramos todos los que mueren o los primeros 5
            if status != "✅ OK" or killed_nodes < 3:
                print(f"{node_label:<10} | {load:,.0f}        | {status}")
                
        print("-" * 45)
        print(f"Resumen {topo_name}:")
        print(f" > Máximo Flujo: {max_pps:,.0f} PPS")
        print(f" > Zodiac Colapsa en: {killed_nodes}/{len(vals)} nodos")
        
        # 4. VEREDICTO AUTOMÁTICO
        if killed_nodes == len(vals):
            print("\n🚨 [VEREDICTO] EL TRÁFICO CRUDO ES DEMASIADO GRANDE.")
            print("   -> NECESITAS APLICAR SCALING FACTOR EN 'sndlib_loader.py'.")
            print(f"   -> Sugerencia: SCALING_FACTOR = {zodiac.MU / max_pps:.4f}")
        elif killed_nodes == 0 and max_pps < (zodiac.MU * 0.2):
             print("\n⚠️ [VEREDICTO] EL TRÁFICO CRUDO ES DEMASIADO PEQUEÑO.")
             print("   -> El Zodiac nunca se saturará. Gráfica plana.")
        else:
             print("\n✅ [VEREDICTO] EXCELENTE. ZONA RICITOS DE ORO.")
             print("   -> Tienes heterogeneidad natural. ¡Puedes correr la simulación!")

if __name__ == "__main__":
    run_audit()
