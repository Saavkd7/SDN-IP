import os
from MCS import get_active_topology, get_config, failure_dict, find_minimum_set, best_green_placement, candidates, get_path_score, assign_green_weights, recovery_path
import vis_utils

# 1. Configuración
config = get_config()
alpha = float(config.get('alpha', 0.5))

# 2. Carga de Topología
topo_loader = get_active_topology()
G = topo_loader.get_graph()

# 3. EXTRACCIÓN DEL "WORST CASE" (Pico Histórico)
#dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Nobel-Germany"
#dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Germany50"
dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/abilene"

if os.path.isdir(dataset_folder):
    # Esta función escanea todo y devuelve solo los valores máximos
    node_traffic_pps = topo_loader.get_peak_traffic_from_folder(dataset_folder)
else:
    print(f"[ERROR] Folder not found. Using topology default.")
    node_traffic_pps = topo_loader.get_traffic_load()

print(f"Running Green-MCS on PEAK TRAFFIC | Alpha: {alpha}")

# 4. Ejecución Estándar (Una sola vez, con los datos máximos)
h = failure_dict(G)
cand_table = candidates(G, G.nodes(), h)

valid_sets = find_minimum_set(cand_table, G.nodes(), node_traffic_pps, max_k=len(G.nodes()))
if valid_sets:
    winner_set, winner_watts, total_score = best_green_placement(G, h, cand_table, valid_sets, alpha, node_traffic_pps)
    print(f"\n[RESULT] Winner Set: {list(winner_set)}")
    print(f"[RESULT] Power: {winner_watts:.2f} W")
    
    # 1 (Baseline sigma=0)
    vis_utils.plot_alpha_sensitivity(G, h, cand_table, valid_sets, node_traffic_pps, best_green_placement)
    # 2 (Baseline sigma=0)
    vis_utils.analyze_tradeoffs(G, h, cand_table, valid_sets, node_traffic_pps, best_green_placement)
    # 3
    vis_utils.analyze_three_metrics(G, h, cand_table, valid_sets, node_traffic_pps, best_green_placement, assign_green_weights, get_path_score)
    
    # --- Generar mapa final para gráficas 4 y 5 ---
    _, final_failover, _ = recovery_path(alpha, node_traffic_pps=node_traffic_pps)
    
    # 4
    vis_utils.plot_hero_load_distribution(final_failover, winner_set)
    # 5
    vis_utils.plot_recovery_delay_cdf(G, h, final_failover, get_path_score)
    # 6
    vis_utils.plot_k_size_impact(G, h, cand_table, valid_sets, node_traffic_pps, best_green_placement, alpha)
    # 7
    vis_utils.plot_extreme_scenarios_comparison(
        G, h, winner_set, final_failover, node_traffic_pps, 
        precalculated_green_watts=winner_watts
    )

    print("\n[INFO] Base graphs saved in 'img_results' folder.")

    # =================================================================
    # NUEVO: ANÁLISIS ESTOCÁSTICO DE VARIANZA (Petición Prof. Mauro)
    # =================================================================
    print("\n" + "="*50)
    print("RUNNING STOCHASTIC VARIANCE ANALYSIS (Prof. Mauro Request)")
    print("="*50)
    
    sigmas_to_test = [0.0, 200.0, 400.0]
    stochastic_watts = []
    stochastic_delays = []

    for s_val in sigmas_to_test:
        print(f"\n---> Testing Variance: Sigma = {s_val} Bytes")
        
        # 1. Extraer tráfico aplicando la desviación estándar
        if os.path.isdir(dataset_folder):
            traffic_stoch = topo_loader.get_peak_traffic_from_folder(dataset_folder, sigma=s_val)
        else:
            traffic_stoch = topo_loader.get_traffic_load(sigma=s_val)
            
        # -----------------------------------------------------------
        # ¡LA MAGIA AQUÍ! 
        # Generar las Gráficas 1 y 2 para CADA valor de Sigma
        # -----------------------------------------------------------
        vis_utils.plot_alpha_sensitivity(G, h, cand_table, valid_sets, traffic_stoch, best_green_placement, sigma=s_val)
        vis_utils.analyze_tradeoffs(G, h, cand_table, valid_sets, traffic_stoch, best_green_placement, sigma=s_val)
            
        # 2. Correr la lógica de recuperación usando este tráfico modificado
        print(f"[MCS] Running offline optimization for stochastic traffic (Sigma={s_val})...")
        w_set, f_map, _ = recovery_path(alpha, node_traffic_pps=traffic_stoch)
        
        if w_set and f_map:
            # 3. Calcular las físicas reales (Consumo y Delay)
            real_w, real_ms = vis_utils.calculate_real_physics(G, h, w_set, f_map, traffic_stoch)
            stochastic_watts.append(real_w)
            stochastic_delays.append(real_ms)
            print(f"     Result: {real_w:.2f} W | {real_ms:.2f} ms")
        else:
            print(f"     [CRITICAL] No viable solution for Sigma={s_val}.")
            stochastic_watts.append(0)
            stochastic_delays.append(2000.0) # Penalización visual de saturación
            
    # 4. Generar la Gráfica 8
    vis_utils.plot_stochastic_variance_analysis(sigmas_to_test, stochastic_watts, stochastic_delays)
    print("\n[INFO] Stochastic Analysis Graphs successfully saved in 'img_results' folder.")
