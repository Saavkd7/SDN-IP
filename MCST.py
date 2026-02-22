import networkx as nx
import os, json, logging, itertools
from green_models import NEC_PF5240, ZodiacFX, GreenNormalizer
from sndlib_loader import SNDLibXMLParser

# ==============================================================================
# 1. UTILS & LOADING
# ==============================================================================
def get_config():
    if not os.path.exists('config.json'): 
        return {"alpha": 0.5, "topology": "Top/abilene.xml"}
    try: 
        with open('config.json', 'r') as f: return json.load(f)
    except: return {"alpha": 0.5, "topology": "Top/abilene.xml"}

def get_active_topology():
    config = get_config()
    filename = config.get('topology', 'abilene.xml')
    xml_filename = filename if filename.startswith('Top/') else f"Top/{filename}"
    return SNDLibXMLParser(xml_filename)

# ==============================================================================
# 2. CORE LOGIC: LATENCY & PATHS
# ==============================================================================
def get_network_latency_score(G, placement_set, node_traffic_pps, node_caps):
    min_prop_delays = {n: float('inf') for n in G.nodes()}
    nearest_ctrls = {n: None for n in G.nodes()}
    for ctrl in placement_set:
        try:
            paths = nx.single_source_dijkstra_path_length(G, ctrl, weight='delay')
            for node, dist in paths.items():
                if dist < min_prop_delays[node]:
                    min_prop_delays[node], nearest_ctrls[node] = dist, ctrl
        except: pass

    total_latency, count = 0.0, 0
    for n in G.nodes():
        ctrl = nearest_ctrls[n]
        if ctrl is None: continue
        lam, mu = node_traffic_pps.get(ctrl, 0.0), node_caps.get(ctrl, 1000000.0)
        q_delay = (1.0 / (mu - lam)) * 1000.0 if lam < mu * 0.99 else 1000.0
        total_latency += (min_prop_delays[n] + q_delay)
        count += 1
    return total_latency / count if count > 0 else float('inf')

# ==============================================================================
# 3. SELECTION & GREEDY LOGIC
# ==============================================================================
def affected_destinations(G, u, v, weight_attr='score'):
    try:
        paths = nx.single_source_dijkstra_path(G, u, weight=weight_attr)
        return {d for d, p in paths.items() if len(p) > 1 and p[1] == v}
    except: return set()

def failure_dict(G, weight_attr='score'):
    return {(u, v): affected_destinations(G, u, v, weight_attr) for u, v in G.edges()}

def candidates(G, nodes, h):
    table = {}
    for (u, v), affected in h.items():
        valid = []
        edge_data = G.get_edge_data(u, v)
        if edge_data: G.remove_edge(u, v)
        try:
            for c in nodes:
                if c != u and nx.has_path(G, u, c) and all(nx.has_path(G, c, d) for d in affected):
                    valid.append(c)
            table[(u, v)] = valid
        finally:
            if edge_data: G.add_edge(u, v, **edge_data)
    return table

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
def best_green_placement(G, valid_sets, alpha, node_traffic_pps):
    raw_results = []
    Z_CAP = ZodiacFX.MU * 0.95
    for s in valid_sets:
        watts, node_caps = 0.0, {}
        for node in s:
            traffic = node_traffic_pps.get(node, 0.0)
            hw = NEC_PF5240 if traffic > Z_CAP else ZodiacFX
            watts += hw.P_BASE + (G.degree(node) * hw.P_PORT)
            node_caps[node] = hw.MU
        delay = get_network_latency_score(G, s, node_traffic_pps, node_caps)
        raw_results.append({'set': s, 'watts': watts, 'delay': delay})

    es, ds = [r['watts'] for r in raw_results], [r['delay'] for r in raw_results]
    min_e, max_e, min_d, max_d = min(es), max(es), min(ds), max(ds)
    e_range, d_range = (max_e - min_e) or 1.0, (max_d - min_d) or 1.0

    best_score, winner = float('inf'), None
    for r in raw_results:
        norm_e = (r['watts'] - min_e) / e_range
        norm_d = (r['delay'] - min_d) / d_range
        score = (alpha * norm_e) + ((1 - alpha) * norm_d)
        r.update({'norm_e': norm_e, 'norm_d': norm_d, 'score': score})
        if score < best_score: best_score, winner = score, r
    return winner['set'], winner['watts'], winner['delay'], best_score, raw_results

##=====================================================================================
def deep_audit_node_7(G, hero=7):
    h_dict = failure_dict(G)
    evidence = {}
    
    print(f"\n{'='*70}")
    print(f"REPORT CARD: HERO NODE {hero} - FULL TOPOLOGICAL PROOF")
    print(f"{'='*70}")
    print(f"{'FAILED EDGE':<15} | {'AFFECTED':<12} | {'TUNNEL PATH':<20} | {'STATUS'}")
    print(f"{'-'*70}")

    for (u, v), affected in h_dict.items():
        edge_data = G.get_edge_data(u, v)
        G.remove_edge(u, v)
        try:
            # Prueba de Túnel
            tunnel = nx.has_path(G, u, hero)
            # Prueba de Reparación
            repair = all(nx.has_path(G, hero, d) for d in affected)
            
            status = "✅ OK" if (tunnel and repair) else "❌ FAIL"
            # Capturamos una ruta de ejemplo para el reporte
            path_str = "None"
            if tunnel:
                path_str = " -> ".join(map(str, nx.shortest_path(G, u, hero)[:3])) + "..."
            
            print(f"({u:>2}, {v:>2})       | {len(affected):>8}     | {path_str:<20} | {status}")
            evidence[(u, v)] = {"tunnel": tunnel, "repair": repair}
        finally:
            G.add_edge(u, v, **edge_data)
    
    print(f"{'='*70}\n")
    return evidence
##=====================================================================================

# ==============================================================================
# 6. MAIN ORCHESTRATOR (DATA-DRIVEN EDITION)
# ==============================================================================
if __name__ == '__main__':
    # 1. Config & Topology
    config = get_config(); alpha = config['alpha']
    loader = get_active_topology(); G = loader.get_graph()
    Z_CAP = ZodiacFX.MU * 0.95 # El límite físico de decisión
    
    # 2. CAPTURA DE TRÁFICO (Peak Analysis)
    #dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Abilene"
    #dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Germany50"
    dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Nobel-Germany"
    
    if os.path.isdir(dataset_folder):
        print(f"[INFO] Scanning real traffic patterns from: {os.path.basename(dataset_folder)}...")
        node_traffic_pps = loader.get_peak_traffic_from_folder(dataset_folder)
    else:
        node_traffic_pps = loader.get_traffic_load() 

    # 3. Execution Pipeline
    h_dict = failure_dict(G)
    cand_table = candidates(G, G.nodes(), h_dict)
    valid_sets = find_minimum_set(cand_table, G.nodes())
    
    # 4. The Tribunal
    w_set, w_watts, w_delay, b_score, raw_results = best_green_placement(
        G, valid_sets, alpha, node_traffic_pps
    )
    
    # 5. INVENTARIO DE HARDWARE (Telemetría Detallada)
    h_nec, h_zodiac = 0, 0
    p_nec, p_zodiac = 0, 0
    passive_power = 0.0

    # Analizar Héroes (Winner Set)
    for node in w_set:
        if node_traffic_pps.get(node, 0.0) > Z_CAP: h_nec += 1
        else: h_zodiac += 1

    # Analizar Red Pasiva (Nodos restantes)
    for n in G.nodes():
        if n not in w_set:
            traffic = node_traffic_pps.get(n, 0.0)
            # Decisión dinámica para la red pasiva
            if traffic > Z_CAP:
                hw = NEC_PF5240
                p_nec += 1
            else:
                hw = ZodiacFX
                p_zodiac += 1
            passive_power += hw.P_BASE + (G.degree(n) * hw.P_PORT)
    
    total_network_power = w_watts + passive_power

    # 6. Output Final de Grado Científico
    print("\n" + "="*60)
    print("   FINAL SIMULATION RESULT (HYBRID HARDWARE INVENTORY)")
    print("="*60)
    print(f" [★] WINNER HERO SET  : {list(w_set)}")
    print(f" [🛠] HERO HW MIX     : {h_nec} NEC, {h_zodiac} Zodiac")
    print(f" [📡] PASSIVE HW MIX  : {p_nec} NEC, {p_zodiac} Zodiac")
    print(f" [⚡] CONTROLLER POWER : {w_watts:.2f} Watts")
    print(f" [🏢] PASSIVE NETWORK  : {passive_power:.2f} Watts")
    print(f" [🌍] TOTAL NET POWER  : {total_network_power:.2f} Watts")
    print(f" [⏱] AVG RESP. DELAY  : {w_delay:.2f} ms")
    print(f" [⚖] ALPHA SCORE      : {b_score:.4f} (Alpha={alpha})")
    print("="*60 + "\n")