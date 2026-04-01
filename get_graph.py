# ==========================================
# AÑADIR AL FINAL DE: get_graph.py (O en un script visual_main.py)
# ==========================================
import pandas as pd
import ast
import vis_utils
from MCS import get_active_topology # O de donde sea que importes tu loader original
from sndlib_loader import SNDLibXMLParser
from MCS import get_config
# ==========================================
#get_graph.py (Sección de visualización)
# ==========================================
import pandas as pd
import ast
import vis_utils
import numpy as np

def generate_q1_visuals(df, G):
    """
    Recibe el DataFrame directamente desde export_research_data_to_excel
    para evitar errores de parsing de tipos.
    """
    print(f"\n[VIS] Iniciando el pipeline de visualización Q1.")
    
    # Actos existentes
    print("[VIS] -> Renderizando Acto I: Frente de Pareto...")
    vis_utils.plot_pareto_front(df)
    
    print("[VIS] -> Renderizando Acto II: Transición de Hardware...")
    # Usamos el alpha más común en los Knee Points si es posible
    vis_utils.plot_hardware_transition(df, target_alpha=0.4) 
    
    print("[VIS] -> Renderizando Acto III: Mapa de Gravedad de Héroes...")
    vis_utils.plot_hero_gravity_map(df, G)
    
    print("[VIS] -> Renderizando Acto IV: Heatmap de Estrés Térmico...")
    vis_utils.plot_stress_heatmap(df)
    
    # --- NUEVOS ACTOS ---
    print("[VIS] -> Renderizando Acto V: Geometría del Knee-Point...")
    vis_utils.plot_pareto_chord_geometry(df, target_sigma=700)
    
    print("[VIS] -> Renderizando Acto VI: Inmunidad del SLA...")
    vis_utils.plot_sla_immunity_scaling(df)
    
    print(f"[SUCCESS] Se han generado 6 figuras en: {vis_utils.OUTPUT_DIR}/")

# --- PUNTO DE EJECUCIÓN FINAL ---
# --- PUNTO DE EJECUCIÓN FINAL CORREGIDO ---
# --- PUNTO DE EJECUCIÓN FINAL ---
if __name__ == "__main__":
    # 1. Resolvemos la ruta de la topología manualmente usando la configuración activa
    # Esto asegura que el script sea dinámico y no se quede solo en Abilene
    config = get_config()
    filename = config.get('topology', 'abilene.xml')
    xml_filename = filename if filename.startswith('Top/') else f"Top/{filename}"
    
    # 2. Instanciamos el objeto 'loader' aquí mismo
    loader = SNDLibXMLParser(xml_filename)
    
    # 3. Inyectamos el atributo 'xml_path' manualmente al objeto instanciado
    # Esto soluciona el AttributeError en el print y mantiene la trazabilidad del archivo
    loader.xml_path = xml_filename 
    
    # 4. Cargamos el grafo desde el objeto ya instanciado
    G_topology = loader.get_graph()
    
    # 5. Definimos la ruta del Excel de resultados
    excel_path = "Network_Optimization_Results.xlsx"
    
    print(f"[INFO] Cargando topología: {loader.xml_path}")
    print(f"[INFO] Cargando datos de: {excel_path}")

    try:
        # Cargamos los resultados de la simulación (Master_Data contiene todos los Sigmas/Alphas)
        df_resultados = pd.read_excel(excel_path, sheet_name="Master_Data")
        
        # 6. Lanzamos el pipeline de visualización Q1
        generate_q1_visuals(df_resultados, G_topology)
        
    except FileNotFoundError:
        print(f"[ERROR] No se encontró el archivo {excel_path}. Ejecuta la simulación primero.")
    except Exception as e:
        print(f"[ERROR] Ocurrió un fallo en el pipeline: {e}")