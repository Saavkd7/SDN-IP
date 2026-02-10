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
dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Nobel-Germany"
#dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Germany50"
#dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/abilene"
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
    
    # 1
    vis_utils.plot_alpha_sensitivity(G, h, cand_table, valid_sets, node_traffic_pps, best_green_placement)
    # 2
    vis_utils.analyze_tradeoffs(G, h, cand_table, valid_sets, node_traffic_pps, best_green_placement)
    # 3
    vis_utils.analyze_three_metrics(G, h, cand_table, valid_sets, node_traffic_pps, best_green_placement, assign_green_weights, get_path_score)
    
    # --- Generar mapa final para gráficas 4 y 5 ---
    _, final_failover, _ = recovery_path(alpha) 
    
    # 4
    vis_utils.plot_hero_load_distribution(final_failover, winner_set)
    # 5
    vis_utils.plot_recovery_delay_cdf(G, h, final_failover, get_path_score)
    # 6
    vis_utils.plot_k_size_impact(G, h, cand_table, valid_sets, node_traffic_pps, best_green_placement, alpha)
    
    print("\n[INFO] All graphs saved in 'img_results' folder.")

