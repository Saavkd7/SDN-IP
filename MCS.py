import networkx as nx
import os, json, logging, itertools
from green_models import NEC_PF5240, ZodiacFX, GreenNormalizer
from sndlib_loader import SNDLibXMLParser
import csv
import pandas as pd
import numpy as np
import random

# EL ANCLA DE DETERMINISMO ABSOLUTO
random.seed(42)
np.random.seed(42)
os.environ['PYTHONHASHSEED'] = '42'

#==================================================================
# 1. UTILS & LOADING
# ==============================================================================
def get_config():
    if not os.path.exists('config.json'): 
        return {"topology": "Top/abilene.xml", "dataset": "Dataset/TestSet/Abilene"}
    try: 
        with open('config.json', 'r') as f: return json.load(f)
    except: return {"topology": "Top/abilene.xml","dataset": "Dataset/TestSet/Abilene"}

def get_active_topology():
    config = get_config()
    filename = config.get('topology', 'abilene.xml')
    xml_filename = filename if filename.startswith('Top/') else f"Top/{filename}"
    return SNDLibXMLParser(xml_filename)

def get_active_dataset():
    config = get_config()
    # 1. Obtenemos lo que dice el config
    dataset_name = config.get('dataset', 'Abilene')
    
    # 2. Si el usuario puso una ruta que empieza por / o por ~ (Home)
    # expandimos el símbolo ~ para que Linux lo entienda
    if dataset_name.startswith('~'):
        return os.path.expanduser(dataset_name)
    
    # 3. Si ya es una ruta absoluta o ya tiene el prefijo Dataset
    if dataset_name.startswith('/') or dataset_name.startswith('Dataset'):
        return dataset_name
    
    # 4. Solo si es un nombre seco (ej: "Abilene"), le ponemos el prefijo
    base_dir = "Dataset/TestSet"
    return os.path.join(base_dir, dataset_name)
    
def get_traffic_profile(loader, G, dataset_folder, burst_multiplier, avg_packet, sigma):
    """
    Extrae el tráfico base (Nodos y Enlaces) y le inyecta el realismo de las micro-ráfagas (PAR).
    """
    if dataset_folder and os.path.isdir(dataset_folder):
        # Esta línea te confirmará en consola que entró a la carpeta correcta
        print(f"[OK] Detected Fp;der: {dataset_folder}. Parsing Starting XML FILES...")
        raw_nodes, raw_edges = loader.get_peak_traffic_from_folder(
            G=G, folder_path=dataset_folder, avg_packet_size_bytes=avg_packet, sigma=sigma
        )    
    else:
        print(f"[WARNING] No se encontró la carpeta: {dataset_folder}")
        print(f"[FALLBACK] Usando carga básica desde el archivo de topología.")
        raw_nodes, raw_edges = loader.calculate_full_network_load(G=G, avg_packet_size_bytes=avg_packet, sigma=sigma)
        
    adjusted_nodes = {n: traffic * burst_multiplier for n, traffic in raw_nodes.items()}
    adjusted_edges = {e: traffic * burst_multiplier for e, traffic in raw_edges.items()}
    
    return adjusted_nodes, adjusted_edges

# ==============================================================================
# 2. CORE LOGIC: HYBRID WEIGHTS & PATHS
# ==============================================================================
def assign_green_weights(G, alpha, peak_node_traffic_pps, sigma):
    degrees = dict(G.degree()).values()
    max_degree = max(degrees) if degrees else 48
    MAX_POWER = GreenNormalizer.get_max_power(max_degree)
    MAX_DELAY_MS = GreenNormalizer.get_worst_delay_threshold() * 1000.0 
    ZODIAC_CAPACITY = ZodiacFX.MU 
    
    node_stats = {}
    for n in G.nodes():
        lam_peak = peak_node_traffic_pps.get(n, 0.0)
        # 1. Selección de HW
        hw = ZodiacFX() if lam_peak < (ZODIAC_CAPACITY * 0.95) else NEC_PF5240()
        hw_type = hw.__class__.__name__
        G.nodes[n]['hardware'] = hw_type
        # 2. Potencia
        watts = hw.get_base_power() + (G.degree(n) * hw.get_port_power())
        # 3. Kingman G/G/1
        mu = hw.get_capacity()
        rho = lam_peak / mu if mu > 0 else 0
        if 0 < rho < 0.99:
            ca = (sigma / lam_peak) if (lam_peak > 0 and sigma > 0) else 1.0
            cs = 0.2 if hw_type == "NEC_PF5240" else 1.2
            
            v_factor = (ca**2 + cs**2) / 2.0
            u_factor = rho / (1.0 - rho)
            
            waiting_time = u_factor * v_factor * (1.0 / mu)
            node_delay = (waiting_time + (1.0 / mu)) * 1000.0
        else:
            node_delay = MAX_DELAY_MS
        
        node_stats[n] = { 
            'norm_energy': watts / MAX_POWER,
            'q_delay': min(node_delay, MAX_DELAY_MS)
        }

    for u, v in G.edges():
        d_prop_ms = G[u][v].get('delay', 0.1) 
        stat_u, stat_v = node_stats[u], node_stats[v]
        
        edge_norm_energy = (stat_u['norm_energy'] + stat_v['norm_energy']) / 2.0
        avg_q_delay_ms = (stat_u['q_delay'] + stat_v['q_delay']) / 2.0
        total_delay_ms = d_prop_ms + avg_q_delay_ms
        
        edge_norm_delay = min(total_delay_ms / MAX_DELAY_MS, 1.0)
        
        G[u][v]['score'] = (alpha * edge_norm_energy) + ((1.0 - alpha) * edge_norm_delay)
        G[u][v]['link_energy_norm'] = edge_norm_energy
        G[u][v]['link_delay_ms'] = total_delay_ms

# ==============================================================================
# 3. SELECTION & GREEDY LOGIC
# ==============================================================================
def get_affected_destinations(G, u, v, weight_attr='score'):
    affected = set()
    try:
        base_paths = nx.single_source_dijkstra_path(G, u, weight=weight_attr)
    except nx.NetworkXException:
        return affected

    for dest, path in base_paths.items():
        if dest != u and len(path) > 1:
            if path[1] == v:  
                affected.add(dest)
                
    return affected

def build_failure_dict(G, weight_attr='score'):
    failures = {}
    for (u, v) in G.edges():
        failures[(u, v)] = get_affected_destinations(G, u, v, weight_attr)
        failures[(v, u)] = get_affected_destinations(G, v, u, weight_attr)
    return failures

def get_valid_candidates(G, nodes_list, failures_dict, weight_attr='score'):
    candidate_table = {}
    
    for (u, v), affected in failures_dict.items():
        valid_candidates = []
        edge_data = G.get_edge_data(u, v)
        if edge_data is not None: G.remove_edge(u, v)
            
        try:
            for c in nodes_list:
                if c == u: continue
                
                if not nx.has_path(G, source=u, target=c):
                    continue
                    
                can_repair_all = True
                for d in affected:
                    if not nx.has_path(G, source=c, target=d):
                        can_repair_all = False
                        break 
                        
                if can_repair_all:
                    valid_candidates.append(c)
                    
            candidate_table[(u, v)] = valid_candidates
        finally:
            if edge_data is not None: G.add_edge(u, v, **edge_data)
            
    return candidate_table

def find_minimum_set(candidate_table, all_nodes):
    node_coverage = {n: set() for n in all_nodes}
    for fail, heroes in candidate_table.items():
        for h_node in heroes: node_coverage[h_node].add(fail)
    uncovered = set(candidate_table.keys())
    base_set = []
    while uncovered:
        best = max(all_nodes, key=lambda n: len(node_coverage[n] & uncovered))
        if len(node_coverage[best] & uncovered) == 0: return None
        base_set.append(best)
        uncovered -= node_coverage[best]
    res = [tuple(sorted(base_set))]
    others = [n for n in all_nodes if n not in base_set]
    for n in others: res.append(tuple(sorted(base_set + [n])))
    for pair in itertools.combinations(others, 2): res.append(tuple(sorted(base_set + list(pair))))
    return list(set(res))

# ==============================================================================
# 4. THE TRIBUNAL (MULTI-OBJECTIVE OPTIMIZATION)
# ==============================================================================

def get_pure_recovery_delay(G, placement_set, h_dict, cand_table, node_traffic_pps, edge_traffic_pps, sigma):
    total_delay = 0.0
    evaluated_failures = 0
    Z_CAP = ZodiacFX.MU * 0.95
    
    for (u, v), affected in h_dict.items():
        if not affected: continue
        
        valid_heroes = [h for h in placement_set if h in cand_table.get((u, v), [])]
        if not valid_heroes: return float('inf')
        
        # EL TRÁFICO QUE SE QUEDÓ SIN RUTA EN ESTA FALLA ESPECÍFICA
        broken_link = tuple(sorted((u, v)))
        lost_traffic = edge_traffic_pps.get(broken_link, 0.0)
            
        best_hero_delay = float('inf')
        for h in valid_heroes:
            # 1. Propagación
            edge_data = G.get_edge_data(u, v)
            if edge_data: G.remove_edge(u, v)
            try:
                tunnel = nx.shortest_path_length(G, u, h, weight='delay') if u != h else 0
                lengths = nx.single_source_dijkstra_path_length(G, h, weight='delay')
                repair = sum(lengths.get(d, 100.0) for d in affected) / len(affected)
                prop_delay = tunnel + repair
            except nx.NetworkXNoPath: 
                prop_delay = float('inf')
            finally:
                if edge_data: G.add_edge(u, v, **edge_data)
            
            # 2. Sincronización con el Arquitecto (Hardware Físico)
            base_lam = node_traffic_pps.get(h, 0.0)
            possible_rescues = [edge_traffic_pps.get(tuple(sorted(fail)), 0.0) 
                                for fail, heroes in cand_table.items() if h in heroes]
            worst_rescue = max(possible_rescues) if possible_rescues else 0.0
            
            hw_type = "NEC_PF5240" if (base_lam + worst_rescue) > Z_CAP else "ZodiacFX"
            mu = NEC_PF5240.MU if hw_type == "NEC_PF5240" else ZodiacFX.MU
            
            # 3. La Falla Real: Tráfico Base + El tráfico de ESTE enlace roto
            lam_post_fail = base_lam + lost_traffic
            
            rho = lam_post_fail / mu if mu > 0 else 0
            
            if 0 < rho < 0.99:
                ca = (sigma / lam_post_fail) if (lam_post_fail > 0 and sigma > 0) else 1.0
                cs = 0.2 if hw_type == "NEC_PF5240" else 1.2
                v_factor = (ca**2 + cs**2) / 2.0
                q_delay = (rho / (1.0 - rho)) * v_factor * (1.0 / mu)
                node_delay = (q_delay + (1.0 / mu)) * 1000.0 # ms
            else:
                node_delay = 1000.0 # SLA Explotó
            
            total_falla = prop_delay + node_delay
            if total_falla < best_hero_delay:
                best_hero_delay = total_falla
                
        total_delay += best_hero_delay
        evaluated_failures += 1
        
    return total_delay / evaluated_failures if evaluated_failures > 0 else float('inf')

def best_green_placement(G, valid_sets, alpha, node_traffic_pps, edge_traffic_pps, h_dict, cand_table, sigma):
    raw_results = []
    Z_CAP = ZodiacFX.MU * 0.95

    for s in valid_sets:
        watts = 0.0
        # --- ETAPA 1: EL ARQUITECTO (Hardware Provisioning) ---
        for node in s:
            base_traffic = node_traffic_pps.get(node, 0.0)
            
            possible_rescues = [edge_traffic_pps.get(tuple(sorted(fail)), 0.0) 
                                for fail, heroes in cand_table.items() if node in heroes]
            
            worst_rescue_load = max(possible_rescues) if possible_rescues else 0.0
            lam_max_theoretical = base_traffic + worst_rescue_load
            
            hw = NEC_PF5240 if lam_max_theoretical > Z_CAP else ZodiacFX
            watts += hw.P_BASE + (G.degree(node) * hw.P_PORT)
            
        # --- ETAPA 2: EL TRIBUNAL (Kingman Delay Evaluation) ---
        pure_delay = get_pure_recovery_delay(G, s, h_dict, cand_table, node_traffic_pps, edge_traffic_pps, sigma)
        raw_results.append({'set': s, 'watts': watts, 'delay': pure_delay})

    es, ds = [r['watts'] for r in raw_results], [r['delay'] for r in raw_results]
    min_e, max_e = min(es), max(es)
    min_d, max_d = min(ds), max(ds)
    e_range = (max_e - min_e) or 1.0
    d_range = (max_d - min_d) or 1.0

    best_score, winner = float('inf'), None
    for r in raw_results:
        norm_e = (r['watts'] - min_e) / e_range
        norm_d = (r['delay'] - min_d) / d_range
        
        score = (alpha * norm_e) + ((1 - alpha) * norm_d)
        
        r.update({'norm_e': norm_e, 'norm_d': norm_d, 'score': score})
        if score < best_score: 
            best_score, winner = score, r
        
    return winner['set'], winner['watts'], winner['delay'], best_score, raw_results

# ==============================================================================
# 5. THE BRIDGE: RECOVERY PATH (Llamada por Ryu Controller)
# ==============================================================================

def get_path_score(G, u, v, c, affected):
    edge_data = G.get_edge_data(u, v)
    if edge_data is not None:
        G.remove_edge(u, v)

    tunnel_score = 0.0
    avg_repair_score = 0.0

    try:
        if u != c:
            try:
                tunnel_score = nx.shortest_path_length(G, source=u, target=c, weight='score')
            except nx.NetworkXNoPath:
                return float('inf')

        if affected:
            total_repair_score = 0.0
            for dest in affected:
                try:
                    path_score = nx.shortest_path_length(G, source=c, target=dest, weight='score')
                    total_repair_score += path_score
                except nx.NetworkXNoPath:
                    return float('inf')
                    
            avg_repair_score = total_repair_score / len(affected)

        return tunnel_score + avg_repair_score

    finally:
        if edge_data is not None:
            G.add_edge(u, v, **edge_data)

def recovery_path(alpha=None, node_traffic_pps=None, dataset=None,sigma=None):
    """
    Función de API para Mininet/Ryu.
    [NOTA DE INVESTIGACIÓN: Ryu generalmente no calcula el óptimo en tiempo real. 
    Usa el mapa de failover precalculado. Esta función se mantiene por compatibilidad heredada.]
    """
    loader = get_active_topology()
    G = loader.get_graph()
    
    if alpha is None: 
        alpha = get_config()['alpha']
        
    if node_traffic_pps is None:
        dataset_folder = dataset
        if os.path.isdir(dataset_folder):
            node_traffic_pps, edge_traffic_pps = get_traffic_profile(loader, G, dataset_folder, 1.0, 800, sigma)
        else:
            node_traffic_pps, edge_traffic_pps = loader.calculate_full_network_load(G=G)

    h_dict = build_failure_dict(G) 
    cand_table = get_valid_candidates(G, G.nodes(), h_dict) 
    valid_sets = find_minimum_set(cand_table, G.nodes())
    
    winner_set, _, _, _, _ = best_green_placement(G, valid_sets, alpha, node_traffic_pps, edge_traffic_pps, h_dict, cand_table, sigma)
    
    assign_green_weights(G, alpha, node_traffic_pps, sigma)
    failover = {}
    for (u, v), affected in h_dict.items():
        if not affected: continue
        best_hero, min_cost = None, float('inf')
        
        potentials = [n for n in winner_set if n in cand_table.get((u, v), [])]
        
        for h in potentials:
            cost = get_path_score(G, u, v, h, affected)
            if cost < min_cost: 
                min_cost = cost
                best_hero = h
                
        failover[(u, v)] = best_hero

    return list(winner_set), failover, G

def calculate_optimal_alpha(G, valid_sets, node_traffic_pps, edge_traffic_pps, h_dict, cand_table, sigma):
    import math
    print("\n[ANALYSIS] Calculating analytical Pareto Knee-Point (Optimal Alpha)...")
    alphas_to_test = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    raw_results = []
    
    for a in alphas_to_test:
        _, w_watts, w_delay, _, _ = best_green_placement(
            G, valid_sets, a, node_traffic_pps, edge_traffic_pps, h_dict, cand_table, sigma
        )
        raw_results.append({'alpha': a, 'watts': w_watts, 'delay': w_delay})
        
    e_vals = [r['watts'] for r in raw_results]
    d_vals = [r['delay'] for r in raw_results]
    
    e_min, e_max = min(e_vals), max(e_vals)
    d_min, d_max = min(d_vals), max(d_vals)
    
    e_range = (e_max - e_min) if (e_max - e_min) > 0 else 1.0
    d_range = (d_max - d_min) if (d_max - d_min) > 0 else 1.0

    best_alpha = None
    max_distance = -1.0
    
    for r in raw_results:
        e_norm = (r['watts'] - e_min) / e_range
        d_norm = (r['delay'] - d_min) / d_range
        
        distance = abs(e_norm + d_norm - 1.0) / math.sqrt(2)
        
        if distance > max_distance:
            max_distance = distance
            best_alpha = r['alpha']
            
    if best_alpha is None:
        raise ValueError("[CRITICAL] Pareto Optimization Failed.")
            
    print(f"[WINNER] Optimal Knee-Point Alpha analytically locked at: {best_alpha}")
    return best_alpha

def export_research_data_to_excel(G, valid_sets, loader, dataset_folder, h_dict, cand_table, avg_packet=800):
    filename = "Network_Optimization_Results.xlsx"
    sigmas_to_test = [0, 100, 250, 500, 700]
    alphas_to_test = np.linspace(0, 1, 11)
    
    all_data = []
    summary_data = []
    
    print(f"\n[EXCEL ENGINE] Starting Massive Sweep. Target: {len(sigmas_to_test) * len(alphas_to_test)} simulations.")
    
    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        for sigma in sigmas_to_test:
            current_sigma_results = []
            print(f" > Processing Sigma: {sigma} ...")
            random.seed(42)
            
            node_traffic_pps, edge_traffic_pps = get_traffic_profile(loader, G, dataset_folder, burst_multiplier=1.0, avg_packet=avg_packet, sigma=sigma)
            kp_alpha = calculate_optimal_alpha(G, valid_sets, node_traffic_pps, edge_traffic_pps, h_dict, cand_table, sigma)
            
            for alpha in alphas_to_test:
                w_set, w_watts, w_delay, b_score, _ = best_green_placement(
                    G, valid_sets, alpha, node_traffic_pps, edge_traffic_pps, h_dict, cand_table, sigma
                )
                
                Z_CAP = ZodiacFX.MU * 0.95
                passive_p = 0.0
                h_nec, h_zod = 0, 0
                p_nec, p_zod = 0, 0  # Contadores pasivos inicializados

                for n in G.nodes():
                    t = node_traffic_pps.get(n, 0.0)
                    if n in w_set:
                        # Los Héroes se calculan contra su peor caso también para el reporte
                        possible_rescues = [edge_traffic_pps.get(tuple(sorted(fail)), 0.0) 
                                            for fail, heroes in cand_table.items() if n in heroes]
                        worst_rescue = max(possible_rescues) if possible_rescues else 0.0
                        if (t + worst_rescue) > Z_CAP: h_nec += 1
                        else: h_zod += 1
                    else:
                        hw = NEC_PF5240 if t > Z_CAP else ZodiacFX
                        passive_p += hw.P_BASE + (G.degree(n) * hw.P_PORT)
                        # Sumar a los contadores pasivos
                        if t > Z_CAP: p_nec += 1
                        else: p_zod += 1
                        
                total_power = w_watts + passive_p
                is_knee = "YES" if np.isclose(alpha, kp_alpha, atol=0.03) else "no"
                
                row = {
                    'Sigma_Variance': sigma,
                    'Alpha_Weight': round(alpha, 2),
                    'Total_Power_W': round(total_power, 2),
                    'Avg_Recovery_Delay_ms': round(w_delay, 2),
                    'Hybrid_Score': round(b_score, 4),
                    'NEC_Heroes': h_nec,
                    'Zodiac_Heroes': h_zod,
                    'NEC_Passive': p_nec,    # Nuevo insight
                    'Zodiac_Passive': p_zod, # Nuevo insight
                    'Is_Pareto_Knee': is_knee
                }        
                current_sigma_results.append(row)
                all_data.append(row)
                
                if is_knee == "YES":
                    summary_data.append(row)
                    
            df_sigma = pd.DataFrame(current_sigma_results)
            df_sigma.to_excel(writer, sheet_name=f"Sigma_{sigma}", index=False)
            
        df_summary = pd.DataFrame(summary_data)
        df_summary.to_excel(writer, sheet_name="Knee_Point_Evolution", index=False)  
        df_master = pd.DataFrame(all_data)
        df_master.to_excel(writer, sheet_name="Master_Data", index=False)
        
    print(f"\n[SUCCESS] Excel report generated: {filename}")
    print(f"Total scenarios analyzed: {len(all_data)}")

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    BURST_MULTIPLIER = 1   
    SIGMA_FACTOR = 700     
    AVG_PACKET_SIZE = 800
    loader = get_active_topology()
    dataset_folder=get_active_dataset()
    G = loader.get_graph() 
    Z_CAP = ZodiacFX.MU * 0.95 
    
    if os.path.isdir(dataset_folder):
        print(f"\n[INFO] Scanning real traffic patterns from: {os.path.basename(dataset_folder)}")
        node_traffic_pps, edge_traffic_pps = get_traffic_profile(
            loader, G, dataset_folder, BURST_MULTIPLIER, AVG_PACKET_SIZE, SIGMA_FACTOR
        )
    else:
        print("[WARNING] Traffic folder not found. Falling back to default.")
        node_traffic_pps, edge_traffic_pps = loader.calculate_full_network_load(G=G, avg_packet_size_bytes=AVG_PACKET_SIZE, sigma=SIGMA_FACTOR)
        
    h_dict = build_failure_dict(G)
    cand_table = get_valid_candidates(G, G.nodes(), h_dict)
    valid_sets = find_minimum_set(cand_table, G.nodes())

    optimal_alpha = calculate_optimal_alpha(G, valid_sets, node_traffic_pps, edge_traffic_pps, h_dict, cand_table, SIGMA_FACTOR)

    w_set, w_watts, w_delay, b_score, raw_results = best_green_placement(
        G, valid_sets, optimal_alpha, node_traffic_pps, edge_traffic_pps, h_dict, cand_table, SIGMA_FACTOR
    )    
    
    h_nec, h_zodiac, p_nec, p_zodiac, passive_power = 0, 0, 0, 0, 0.0
    for node in w_set:
        base_t = node_traffic_pps.get(node, 0.0)
        possible_rescues = [edge_traffic_pps.get(tuple(sorted(fail)), 0.0) 
                            for fail, heroes in cand_table.items() if node in heroes]
        worst_rescue = max(possible_rescues) if possible_rescues else 0.0
        
        if (base_t + worst_rescue) > Z_CAP: h_nec += 1
        else: h_zodiac += 1
        
    for n in G.nodes():
        if n not in w_set:
            traffic = node_traffic_pps.get(n, 0.0)
            if traffic > Z_CAP: 
                hw, p_nec = NEC_PF5240, p_nec + 1
            else: 
                hw, p_zodiac = ZodiacFX, p_zodiac + 1
            passive_power += hw.P_BASE + (G.degree(n) * hw.P_PORT)
            
    total_network_power = w_watts + passive_power
    hero_names = [G.nodes[n].get('name', str(n)) for n in w_set]

    print("\n" + "="*60)
    print(f"   FINAL SIMULATION: PAR={BURST_MULTIPLIER}x | SIGMA={SIGMA_FACTOR}")
    print("="*60)
    print(f" [★] OPTIMAL ALPHA    : {optimal_alpha} (Pareto Knee-Point)")
    print(f" [★] WINNER HERO SET  : {hero_names}") 
    print(f" [🛠] HERO HW MIX     : {h_nec} NEC, {h_zodiac} Zodiac")
    print(f" [📡] PASSIVE HW MIX  : {p_nec} NEC, {p_zodiac} Zodiac")
    print(f" [⚡] HERO POWER       : {w_watts:.2f} Watts")
    print(f" [🏢] PASSIVE NETWORK  : {passive_power:.2f} Watts")
    print(f" [🌍] TOTAL NET POWER  : {total_network_power:.2f} Watts")
    print(f" [⏱] AVG RESP. DELAY  : {w_delay:.2f} ms")
    print(f" [⚖] ALPHA SCORE      : {b_score:.4f}")
    print("="*60 + "\n")

    assign_green_weights(G, optimal_alpha, node_traffic_pps, SIGMA_FACTOR)
    export_research_data_to_excel(G, valid_sets, loader, dataset_folder, h_dict, cand_table, AVG_PACKET_SIZE)
