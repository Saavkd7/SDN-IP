# ==========================================
# AÑADIR AL FINAL DE: get_graph.py (O en un script visual_main.py)
# ==========================================
import pandas as pd
import ast
import vis_utils
from MCS import get_active_topology # O de donde sea que importes tu loader original

def generate_q1_visuals(csv_file, G):
    print(f"\n[VIS] Iniciando el pipeline de visualización Q1. Leyendo: {csv_file}")
    
    try:
        df = pd.read_csv(csv_file)
    except FileNotFoundError:
        print(f"[CRITICAL] No se encuentra el archivo {csv_file}. Ejecuta la simulación primero.")
        return

    # PARSING ESTRICTO: Transformar las cadenas de texto engañosas de vuelta a listas de Python
    list_columns = ['WinnerSet_Names', 'NEC_Hero_Names', 'Zodiac_Hero_Names']
    for col in list_columns:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: ast.literal_eval(x) if isinstance(x, str) else x)
            
    print("[VIS] -> Renderizando Acto I: Frente de Pareto...")
    vis_utils.plot_pareto_front(df)
    
    print("[VIS] -> Renderizando Acto II: Transición de Hardware...")
    vis_utils.plot_hardware_transition(df, target_alpha=0.4) 
    
    print("[VIS] -> Renderizando Acto III: Mapa de Gravedad de Héroes...")
    vis_utils.plot_hero_gravity_map(df, G)
    
    print("[VIS] -> Renderizando Acto IV: Heatmap de Estrés Térmico...")
    vis_utils.plot_stress_heatmap(df)
    
    print(f"[SUCCESS] Todas las figuras han sido guardadas en la carpeta: {vis_utils.OUTPUT_DIR}/")

# --- PUNTO DE EJECUCIÓN FINAL ---
# 1. Cargamos el grafo directamente y de forma limpia, sin simular nada.
loader = get_active_topology() # Ajusta esta llamada a como inicialices tu parser normalmente
G_topology = loader.get_graph()

# 2. Leemos el CSV pre-existente
results_file = "./Nobel-Germany/simulation_results.csv"

# 3. Lanzamos la visualización
generate_q1_visuals(results_file, G_topology)