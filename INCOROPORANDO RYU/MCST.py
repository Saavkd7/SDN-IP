import networkx as nx
import os, json, logging, itertools
from green_models import NEC_PF5240, ZodiacFX, GreenNormalizer
from sndlib_loader import SNDLibXMLParser
import csv
import pandas as pd
import numpy as np
import random
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
    config=get_config()
    dataset_name=config.get('dataset','Abilene')
    base_dir="Dataset/TestSet"
    dataset_folder=dataset_name if (dataset_name.startswith('/') or dataset_name.startswith('Dataset')) else f"{base_dir}{dataset_name}"
    return dataset_folder

def get_traffic_profile(loader, G, dataset_folder, burst_multiplier,avg_packet,sigma):

    """
    Extrae el tráfico base y le inyecta el realismo de las micro-ráfagas (PAR).
    - burst_multiplier = 1.0 (Tráfico promedio pacífico)
    - burst_multiplier = 4.0 (Tormenta de tráfico / Realismo Carrier-Grade)
    """
    if dataset_folder and os.path.isdir(dataset_folder):
        print(f"[INFO] Scanning traffic from {os.path.basename(dataset_folder)} | PAR Multiplier: {burst_multiplier}x")
        raw_traffic = loader.get_peak_traffic_from_folder(G=G,folder_path=dataset_folder,avg_packet_size_bytes=avg_packet,sigma=sigma)    
    else:
        print(f"[WARNING] Falling back to default XML load | PAR Multiplier: {burst_multiplier}x")
        raw_traffic = loader.calculate_full_network_load(G=G)
        
    # Aplicar el multiplicador a todos los nodos
    adjusted_traffic = {node: traffic * burst_multiplier for node, traffic in raw_traffic.items()}
    return adjusted_traffic

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
            # Variabilidad de llegada (ca) y servicio (cs)
            ca = (sigma / lam_peak) if (lam_peak > 0 and sigma > 0) else 1.0
            cs = 0.2 if hw_type == "NEC_PF5240" else 1.2
            
            v_factor = (ca**2 + cs**2) / 2.0
            u_factor = rho / (1.0 - rho)
            
            # Wq (Espera) + S (Servicio) en segundos, luego TODO a ms
            waiting_time = u_factor * v_factor * (1.0 / mu)
            node_delay = (waiting_time + (1.0 / mu)) * 1000.0
        else:
            node_delay = MAX_DELAY_MS
        
        node_stats[n] = { 
            'norm_energy': watts / MAX_POWER,
            'q_delay': min(node_delay, MAX_DELAY_MS)
        }

    # 4. Asignación de pesos en Aristas
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

        


        



    #     node_stats[n] = {
    #         'hardware': hw.__class__.__name__,
    #         'norm_energy': watts / MAX_POWER,
    #         'mu': mu,
    #         'current_load': lam_peak # Guardamos la carga para el M/M/1 futuro
    #     }

    # # 2. ASIGNACIÓN DE ARISTAS O(E): FASE DE INGENIERÍA DE TRÁFICO
    # for u, v in G.edges():
    #     d_prop_ms = G[u][v].get('delay', 0.1) 
        
    #     stat_u = node_stats[u]
    #     stat_v = node_stats[v]
        
    #     # Energía promediada del enlace
    #     edge_norm_energy = (stat_u['norm_energy'] + stat_v['norm_energy']) / 2.0
        
    #     # Retardo de Cola en cada extremo (M/M/1 en milisegundos)
    #     q_u = (1.0 / (stat_u['mu'] - stat_u['current_load'])) * 1000.0 if stat_u['current_load'] < stat_u['mu'] else MAX_DELAY_MS
    #     q_v = (1.0 / (stat_v['mu'] - stat_v['current_load'])) * 1000.0 if stat_v['current_load'] < stat_v['mu'] else MAX_DELAY_MS
        
    #     avg_q_delay_ms = (q_u + q_v) / 2.0
    #     total_delay_ms = d_prop_ms + avg_q_delay_ms
        
    #     edge_norm_delay = min(total_delay_ms / MAX_DELAY_MS, 1.0)
        
    #     # SCORE HÍBRIDO FINAL
    #     score = (alpha * edge_norm_energy) + ((1.0 - alpha) * edge_norm_delay)
    #     # Almacenamos todo para observabilidad en el paper
    #     G[u][v]['score'] = score
    #     G[u][v]['link_energy_norm'] = edge_norm_energy
    #     G[u][v]['link_delay_ms'] = total_delay_ms


# ==============================================================================
# 3. SELECTION & GREEDY LOGIC
# ==============================================================================
def get_affected_destinations(G, u, v, weight_attr='score'):
    """
    Descubre qué nodos destino quedan afectados si el enlace (u, v) se corta.
    Un destino es 'afectado' si la MEJOR ruta actual pasa obligatoriamente por (u, v).
    """
    affected = set()
    
    # 1. Obtenemos las distancias y caminos base ANTES de la falla
    try:
        base_paths = nx.single_source_dijkstra_path(G, u, weight=weight_attr)
    except nx.NetworkXException:
        return affected

    # 2. Analizamos: Si la ruta óptima de 'u' a 'dest' tiene a 'v' como primer salto, está afectado.
    for dest, path in base_paths.items():
        if dest != u and len(path) > 1:
            if path[1] == v:  # 'v' es el siguiente salto inmediato desde 'u'
                affected.add(dest)
                
    return affected

def build_failure_dict(G, weight_attr='score'):
    """
    Construye un mapa O(E) de cada cable de fibra y a quién deja sin internet si se rompe.
    Garantiza el cálculo en ambas direcciones para la instalación de reglas OpenFlow en Ryu.
    """
    failures = {}
    for (u, v) in G.edges():
        failures[(u, v)] = get_affected_destinations(G, u, v, weight_attr)
        failures[(v, u)] = get_affected_destinations(G, v, u, weight_attr)
    return failures



def get_valid_candidates(G, nodes_list, failures_dict, weight_attr='score'):
    """
    Encuentra los 'Héroes' (candidatos) válidos para cada falla.
    Un héroe es válido si:
    1. Puede ser alcanzado por la fuente sin usar el enlace roto (El Túnel existe).
    2. Puede alcanzar a TODOS los afectados sin usar el enlace roto (La Reparación es posible).
    """
    candidate_table = {}
    
    for (u, v), affected in failures_dict.items():
        valid_candidates = []
        
        # Cirugía Topológica In-Place: Rompemos el enlace temporalmente
        edge_data = G.get_edge_data(u, v)
        if edge_data is not None: G.remove_edge(u, v)
            
        try:
            for c in nodes_list:
                if c == u: continue
                
                # REGLA 1: ¿Existe un túnel viable de 'u' al candidato 'c' en la red rota?
                if not nx.has_path(G, source=u, target=c):
                    continue
                    
                # REGLA 2: ¿Puede el candidato 'c' alcanzar a TODOS los destinos afectados?
                can_repair_all = True
                for d in affected:
                    if not nx.has_path(G, source=c, target=d):
                        can_repair_all = False
                        break # Falla prematura, pasamos al siguiente candidato
                        
                if can_repair_all:
                    valid_candidates.append(c)
                    
            candidate_table[(u, v)] = valid_candidates
            
        finally:
            # Restauración In-Place: Soldamos el cable de fibra de vuelta
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

def get_pure_recovery_delay(G, placement_set, h_dict, cand_table, node_traffic_pps, sigma):
    """
    Evaluación de Retardo Real post-falla usando Kingman (G/G/1).
    """
    total_delay = 0.0
    evaluated_failures = 0
    Z_CAP = ZodiacFX.MU * 0.95
    
    for (u, v), affected in h_dict.items():
        if not affected: continue
        
        valid_heroes = [h for h in placement_set if h in cand_table.get((u, v), [])]
        if not valid_heroes: return float('inf')
            
        best_hero_delay = float('inf')
        for h in valid_heroes:
            # 1. Retardo de Propagación (Física de la fibra)
            edge_data = G.get_edge_data(u, v)
            if edge_data: G.remove_edge(u, v)
            try:
                tunnel = nx.shortest_path_length(G, u, h, weight='delay') if u != h else 0
                lengths = nx.single_source_dijkstra_path_length(G, h, weight='delay')
                repair = sum(lengths.get(d, 100.0) for d in affected) / len(affected)
                prop_delay = tunnel + repair
            except: prop_delay = float('inf')
            finally:
                if edge_data: G.add_edge(u, v, **edge_data)
            
            # 2. Retardo de Cola Kingman (Física del Hardware)
            lam = node_traffic_pps.get(h, 0.0)
            # Identificar qué hardware tiene el héroe para asignar su cs
            hw_type = "NEC_PF5240" if lam > Z_CAP else "ZodiacFX"
            mu = NEC_PF5240.MU if hw_type == "NEC_PF5240" else ZodiacFX.MU
            
            rho = lam / mu if mu > 0 else 0
            if 0 < rho < 0.99:
                ca = (sigma / lam) if (lam > 0 and sigma > 0) else 1.0
                cs = 0.2 if hw_type == "NEC_PF5240" else 1.2
                v_factor = (ca**2 + cs**2) / 2.0
                q_delay = (rho / (1.0 - rho)) * v_factor * (1.0 / mu)
                node_delay = (q_delay + (1.0 / mu)) * 1000.0 # ms
            else:
                node_delay = 1000.0 # Penalización SLA
            
            total_falla = prop_delay + node_delay
            if total_falla < best_hero_delay:
                best_hero_delay = total_falla
                
        total_delay += best_hero_delay
        evaluated_failures += 1
        
    return total_delay / evaluated_failures if evaluated_failures > 0 else float('inf')


def best_green_placement(G, valid_sets, alpha, node_traffic_pps, h_dict, cand_table,sigma):
    """Elige al ganador cruzando Watts Reales vs Milisegundos Reales."""
    raw_results = []
    Z_CAP = ZodiacFX.MU * 0.95

    for s in valid_sets:
        watts = 0.0
        for node in s:
            traffic = node_traffic_pps.get(node, 0.0)
            hw = NEC_PF5240 if traffic > Z_CAP else ZodiacFX
            watts += hw.P_BASE + (G.degree(node) * hw.P_PORT)
            
        # Obtenemos milisegundos físicos puros
        pure_delay = get_pure_recovery_delay(G, s, h_dict, cand_table, node_traffic_pps,sigma)
        raw_results.append({'set': s, 'watts': watts, 'delay': pure_delay})

    es, ds = [r['watts'] for r in raw_results], [r['delay'] for r in raw_results]
    min_e, max_e, min_d, max_d = min(es), max(es), min(ds), max(ds)
    e_range, d_range = (max_e - min_e) or 1.0, (max_d - min_d) or 1.0

    best_score, winner = float('inf'), None
    for r in raw_results:
        norm_e = (r['watts'] - min_e) / e_range
        norm_d = (r['delay'] - min_d) / d_range
        
        # ✅ AQUÍ ES DONDE ALPHA JUZGA (Por primera y única vez)
        score = (alpha * norm_e) + ((1 - alpha) * norm_d)
        
        r.update({'norm_e': norm_e, 'norm_d': norm_d, 'score': score})
        if score < best_score: best_score, winner = score, r
        
    return winner['set'], winner['watts'], winner['delay'], best_score, raw_results

# ==============================================================================
# 5. THE BRIDGE: RECOVERY PATH (Llamada por Ryu Controller)
# ==============================================================================

def get_path_score(G, u, v, c, affected):
    """
    Ruta guiada por 'score' híbrido (Alpha).
    DEVUELVE EL SCORE (Para que Alpha decida quién es el mejor Héroe para el failover).
    """
    edge_data = G.get_edge_data(u, v)
    if edge_data is not None:
        G.remove_edge(u, v)

    tunnel_score = 0.0
    avg_repair_score = 0.0

    try:
        # --- PARTE A: EL TÚNEL ---
        if u != c:
            try:
                # 1. Encontrar la ruta óptima según Alpha y obtener su SCORE TOTAL
                tunnel_score = nx.shortest_path_length(G, source=u, target=c, weight='score')
            except nx.NetworkXNoPath:
                return float('inf')

        # --- PARTE B: LA REPARACIÓN ---
        if affected:
            total_repair_score = 0.0
            for dest in affected:
                try:
                    # 1. Ruta óptima del héroe al destino según Alpha (SCORE TOTAL)
                    path_score = nx.shortest_path_length(G, source=c, target=dest, weight='score')
                    total_repair_score += path_score
                except nx.NetworkXNoPath:
                    return float('inf')
                    
            avg_repair_score = total_repair_score / len(affected)

        # LA VERDAD MATEMÁTICA: Devolvemos el costo híbrido para que 'recovery_path'
        # compare peras con peras respetando a Alpha en la elección del Héroe final.
        return tunnel_score + avg_repair_score

    finally:
        if edge_data is not None:
            G.add_edge(u, v, **edge_data)



def recovery_path(alpha=None, node_traffic_pps=None, dataset=None,sigma=None):
    """Función de API para Mininet/Ryu: Retorna (heroes, failover_map, grafo)."""
    loader = get_active_topology()
    G = loader.get_graph()
    
    if alpha is None: 
        alpha = get_config()['alpha']
        
    if node_traffic_pps is None:
        dataset_folder =dataset
        if os.path.isdir(dataset_folder):
            node_traffic_pps = loader.get_peak_traffic_from_folder(folder_path=dataset_folder, G=G)
        else:
            node_traffic_pps = loader.calculate_full_network_load(G=G)

    # 1. Pipeline de Selección (USANDO LAS FUNCIONES RESTAURADAS)
    h_dict = build_failure_dict(G) 
    cand_table = get_valid_candidates(G, G.nodes(), h_dict) 
    valid_sets = find_minimum_set(cand_table, G.nodes())
    
    # 2. El Tribunal (CON LOS ARGUMENTOS PARA EL RPL PROMEDIO)
    winner_set, _, _, _, _ = best_green_placement(G, valid_sets, alpha, node_traffic_pps, h_dict, cand_table,sigma)
    
    # 3. Mapeo de Failover para Túneles MPLS
    assign_green_weights(G, alpha, node_traffic_pps,sigma)
    failover = {}
    for (u, v), affected in h_dict.items():
        if not affected: continue
        best_hero, min_cost = None, float('inf')
        
        # Filtramos qué héroes del set ganador pueden salvar esta ruta específica
        potentials = [n for n in winner_set if n in cand_table.get((u, v), [])]
        
        for h in potentials:
            cost = get_path_score(G, u, v, h, affected)
            if cost < min_cost: 
                min_cost = cost
                best_hero = h
                
        failover[(u, v)] = best_hero

    return list(winner_set), failover, G



def calculate_optimal_alpha(G, valid_sets, node_traffic_pps, h_dict, cand_table,sigma):
    """
    Simulación de Pre-Vuelo: Detecta matemáticamente el punto de inflexión
    (Knee-Point) de la Frontera de Pareto para la topología actual.
    """
    import math
    print("\n[ANALYSIS] Calculating analytical Pareto Knee-Point (Optimal Alpha)...")
    alphas_to_test = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    raw_results = []
    
    # 1. Ejecutar simulación rápida para todos los alphas
    for a in alphas_to_test:
        _, w_watts, w_delay, _, _ = best_green_placement(
            G, valid_sets, a, node_traffic_pps, h_dict, cand_table,sigma
        )
        raw_results.append({'alpha': a, 'watts': w_watts, 'delay': w_delay})
        
    e_vals = [r['watts'] for r in raw_results]
    d_vals = [r['delay'] for r in raw_results]
    
    e_min, e_max = min(e_vals), max(e_vals)
    d_min, d_max = min(d_vals), max(d_vals)
    
    e_range = (e_max - e_min) if (e_max - e_min) > 0 else 1.0
    d_range = (d_max - d_min) if (d_max - d_min) > 0 else 1.0

    # Inicialización Científicamente Rigurosa (Sin sesgo humano)
    best_alpha = None
    max_distance = -1.0
    
    # 2. Calcular distancias ortogonales a la cuerda de Pareto
    for r in raw_results:
        e_norm = (r['watts'] - e_min) / e_range
        d_norm = (r['delay'] - d_min) / d_range
        
        # d = |x + y - 1| / sqrt(2)
        distance = abs(e_norm + d_norm - 1.0) / math.sqrt(2)
        
        if distance > max_distance:
            max_distance = distance
            best_alpha = r['alpha']
            
    # 3. La Guillotina Científica (Fail-Fast)
    if best_alpha is None:
        raise ValueError("[CRITICAL] Pareto Optimization Failed: Objective space collapsed. Topology might be mathematically unfeasible under current M/M/1 constraints.")
            
    print(f"[WINNER] Optimal Knee-Point Alpha analytically locked at: {best_alpha}")
    return best_alpha

def export_research_data_to_excel(G, valid_sets, loader, dataset_folder, h_dict, cand_table,avg_packet=800):
    """
    Genera un reporte científico de alta resolución en Excel.
    Analiza la sensibilidad de la red ante ráfagas (Sigma) y prioridades (Alpha).
    """
    filename = "Network_Optimization_Results.xlsx"
    
    # 1. Definición de Escenarios Científicos
    # Sigmas: De ideal (0) a crítico (1000)
    sigmas_to_test = [0, 100, 250, 500, 700]
    # Alphas: Resolución del 5% (21 puntos por escenario)
    alphas_to_test = np.linspace(0, 1, 11)
    
    all_data = []
    summary_data = []
    
    print(f"\n[EXCEL ENGINE] Starting Massive Sweep. Target: {len(sigmas_to_test) * len(alphas_to_test)} simulations.")
    
    # Creamos un escritor de Excel con múltiples hojas
    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        
        for sigma in sigmas_to_test:
            current_sigma_results = []
            print(f" > Processing Sigma: {sigma} ...")
            random.seed(42)
            # Captura de tráfico para este sigma específico
            # Nota: Usamos BURST_MULTIPLIER=1 para aislar el efecto de Sigma
            #node_traffic_pps = get_traffic_profile(loader, G, dataset_folder, , avg_packet, sigma=sigma)
            node_traffic_pps = get_traffic_profile(loader, G, dataset_folder, burst_multiplier=1.0, avg_packet=avg_packet, sigma=sigma)
            # Primero calculamos el Knee-Point de este Sigma para marcarlo en el Excel
            kp_alpha = calculate_optimal_alpha(G, valid_sets, node_traffic_pps, h_dict, cand_table, sigma)
            for alpha in alphas_to_test:
                # Ejecutamos el Tribunal de Kingman
                w_set, w_watts, w_delay, b_score, _ = best_green_placement(
                    G, valid_sets, alpha, node_traffic_pps, h_dict, cand_table, sigma
                )
                # Cálculo de Potencia de Nodos Pasivos (No Héroes)
                Z_CAP = ZodiacFX.MU * 0.95
                passive_p = 0.0
                h_nec, h_zod = 0, 0
                for n in G.nodes():
                    t = node_traffic_pps.get(n, 0.0)
                    if n in w_set:
                        if t > Z_CAP: h_nec += 1
                        else: h_zod += 1
                    else:
                        hw = NEC_PF5240 if t > Z_CAP else ZodiacFX
                        passive_p += hw.P_BASE + (G.degree(n) * hw.P_PORT)
                total_power = w_watts + passive_p
                # Cambia la validación del Knee-Point por una tolerancia matemática
                is_knee = "YES" if np.isclose(alpha, kp_alpha, atol=0.03) else "no"
                # Asegúrate de que el KP se calcule dinámicamente para cada sigma  
                row = {
                    'Sigma_Variance': sigma,
                    'Alpha_Weight': round(alpha, 2),
                    'Total_Power_W': round(total_power, 2),
                    'Avg_Recovery_Delay_ms': round(w_delay, 2),
                    'Hybrid_Score': round(b_score, 4),
                    'NEC_Heroes': h_nec,
                    'Zodiac_Heroes': h_zod,
                    'Is_Pareto_Knee': is_knee
                }        
                current_sigma_results.append(row)
                all_data.append(row)
                
                if is_knee == "YES":
                    summary_data.append(row)
            # Guardar hoja individual para este Sigma (Ideal para graficar curvas separadas)
            df_sigma = pd.DataFrame(current_sigma_results)
            df_sigma.to_excel(writer, sheet_name=f"Sigma_{sigma}", index=False)
        # 2. Hoja Resumen: La evolución del Knee-Point
        df_summary = pd.DataFrame(summary_data)
        df_summary.to_excel(writer, sheet_name="Knee_Point_Evolution", index=False)  
        # 3. Hoja Maestra: Todos los datos para Pivot Tables
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
    # 2. CAPTURA DE TRÁFICO    
    if os.path.isdir(dataset_folder):
        print(f"\n[INFO] Scanning real traffic patterns from: {os.path.basename(dataset_folder)}")
        node_traffic_pps = get_traffic_profile(
            loader, G, dataset_folder, BURST_MULTIPLIER, AVG_PACKET_SIZE, SIGMA_FACTOR
        )
    else:
        print("[WARNING] Traffic folder not found. Falling back to default.")
        node_traffic_pps = loader.calculate_full_network_load(G=G)
    # 3. PIPELINE TOPOLÓGICO (Fase Estática)
    h_dict = build_failure_dict(G)
    cand_table = get_valid_candidates(G, G.nodes(), h_dict)
    valid_sets = find_minimum_set(cand_table, G.nodes())
    # ==========================================================================
    # 4. LA MAGIA: DESCUBRIMIENTO DINÁMICO DEL ALPHA (Knee-Point)
    # ==========================================================================
    optimal_alpha = calculate_optimal_alpha(G, valid_sets, node_traffic_pps, h_dict, cand_table,SIGMA_FACTOR)
    # ==========================================================================
    # 5. EL TRIBUNAL: Ejecución final con el Alpha matemáticamente perfecto
    # ==========================================================================
    w_set, w_watts, w_delay, b_score, raw_results = best_green_placement(
        G, valid_sets, optimal_alpha, node_traffic_pps, h_dict, cand_table, SIGMA_FACTOR
    )    
    # 6. INVENTARIO DE HARDWARE Y MÉTRICAS
    h_nec, h_zodiac, p_nec, p_zodiac, passive_power = 0, 0, 0, 0, 0.0
    for node in w_set:
        if node_traffic_pps.get(node, 0.0) > Z_CAP: h_nec += 1
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
   # --- TRADUCCIÓN DE IDs A NOMBRES ---
    hero_names = [G.nodes[n].get('name', str(n)) for n in w_set]
    # 7. OUTPUT FINAL PARA EL PAPER
    print("\n" + "="*60)
    print(f"   FINAL SIMULATION: PAR={BURST_MULTIPLIER}x | SIGMA={SIGMA_FACTOR}")
    print("="*60)
    print(f" [★] OPTIMAL ALPHA    : {optimal_alpha} (Pareto Knee-Point)")
    print(f" [★] WINNER HERO SET  : {hero_names}") # <-- CAMBIO APLICADO AQUÍ
    print(f" [🛠] HERO HW MIX     : {h_nec} NEC, {h_zodiac} Zodiac")
    print(f" [📡] PASSIVE HW MIX  : {p_nec} NEC, {p_zodiac} Zodiac")
    print(f" [⚡] HERO POWER       : {w_watts:.2f} Watts")
    print(f" [🏢] PASSIVE NETWORK  : {passive_power:.2f} Watts")
    print(f" [🌍] TOTAL NET POWER  : {total_network_power:.2f} Watts")
    print(f" [⏱] AVG RESP. DELAY  : {w_delay:.2f} ms")
    print(f" [⚖] ALPHA SCORE      : {b_score:.4f}")
    print("="*60 + "\n")
    # Mapeo final en el Grafo
    assign_green_weights(G, optimal_alpha, node_traffic_pps,SIGMA_FACTOR)
    export_research_data_to_excel(G, valid_sets, loader, dataset_folder, h_dict, cand_table)

  
  