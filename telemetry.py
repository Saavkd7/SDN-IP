import networkx as nx
import itertools
# Asegúrate de que green_models tenga las clases actualizadas (LegacyRouter, SDNSwitch)
# que definimos en la respuesta anterior (donde solo devuelven P_BASE).
import os
import json
from green_models import NEC_PF5240 , ZodiacFX, GreenNormalizer
import matplotlib.pyplot as plt 
import numpy as np
import vis_utils 
from sndlib_loader import SNDLibXMLParser 
import glob
import logging
# ===================   ===========================================================
# 1. UTILS
# ==============================================================================
def get_config():
    if not os.path.exists('config.json'): 
        # CORRECCIÓN AQUÍ: Apunta a la carpeta correcta por defecto
        return {"alpha": 0.5, "topology": "Top/abilene.xml"}
    try: 
        with open('config.json', 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        logging.error("config.json file is conrrupted... Using default values.") 
        return {"alpha": 0.5, "topology": "Top/abilene.xml"}
    
#LINUX ONLY 
def get_active_topology():
    config = get_config()
    filename = config.get('topology', 'abilene.xml')
    
    # Concatenate directly 
    xml_filename = filename if filename.startswith('Top/') else f"Top/{filename}"
    if not os.path.exists(xml_filename):
        raise FileNotFoundError(f"[FALTA ERROR] FILE NOT FOUND: {xml_filename}")

    return SNDLibXMLParser(xml_filename)

def assign_green_weights(G, alpha, peak_node_traffic_pps):
    """
    Despliegue de Hardware Basado en Datos (Data-Driven Hardware Placement).
    Evalúa el Pico de Tráfico Histórico. Si el pico < Capacidad Zodiac,
    despliega hardware Green. Caso contrario, mantiene hardware Legacy (NEC).
    """
    degrees = dict(G.degree()).values()
    max_degree = max(degrees) if degrees else 48
    MAX_POWER = GreenNormalizer.get_max_power(max_degree)
    MAX_DELAY_MS = GreenNormalizer.get_worst_delay_threshold() * 1000.0 

    ZODIAC_CAPACITY = ZodiacFX.MU 
    
    # 1. PRE-CÁLCULO O(V): FASE DE DESPLIEGUE (CAPACITY PLANNING)
    node_stats = {}
    for n in G.nodes():
        lam_peak = peak_node_traffic_pps.get(n, 0.0)
        
        # EL PAPER: Despliegue guiado puramente por el perfil de tráfico
        if lam_peak < (ZODIAC_CAPACITY * 0.90): # Margen de seguridad del 10%
            hw = ZodiacFX()
        else:
            hw = NEC_PF5240()
            
        watts = hw.get_base_power() + (G.degree(n) * hw.get_port_power())
        mu = hw.get_capacity()
        
        node_stats[n] = {
            'hardware': hw.__class__.__name__,
            'norm_energy': watts / MAX_POWER,
            'mu': mu,
            'current_load': lam_peak # Guardamos la carga para el M/M/1 futuro
        }

    # 2. ASIGNACIÓN DE ARISTAS O(E): FASE DE INGENIERÍA DE TRÁFICO
    for u, v in G.edges():
        d_prop_ms = G[u][v].get('delay', 0.1) 
        
        stat_u = node_stats[u]
        stat_v = node_stats[v]
        
        # Energía promediada del enlace ###PROYECCCION 
        edge_norm_energy = (stat_u['norm_energy'] + stat_v['norm_energy']) / 2.0
        
        # DELAY MM1 MODELING Retardo de Cola en cada extremo (M/M/1 en milisegundos)
        q_u = (1.0 / (stat_u['mu'] - stat_u['current_load'])) * 1000.0 if stat_u['current_load'] < stat_u['mu'] else MAX_DELAY_MS
        q_v = (1.0 / (stat_v['mu'] - stat_v['current_load'])) * 1000.0 if stat_v['current_load'] < stat_v['mu'] else MAX_DELAY_MS
        
        avg_q_delay_ms = (q_u + q_v) / 2.0
        total_delay_ms = d_prop_ms + avg_q_delay_ms
        
        edge_norm_delay = min(total_delay_ms / MAX_DELAY_MS, 1.0)
        
        # SCORE HÍBRIDO FINAL
        score = (alpha * edge_norm_energy) + ((1.0 - alpha) * edge_norm_delay)
        
        # Almacenamos todo para observabilidad en el paper
        G[u][v]['score'] = score
        G[u][v]['link_energy_norm'] = edge_norm_energy
        G[u][v]['link_delay_ms'] = total_delay_ms

def get_path_score(G, u, v, c, affected):
    """
    Calcula el Green RPL (Costo total del camino de recuperación) de forma ultrarrápida.
    Evita copias profundas del grafo y utiliza Dijkstra de fuente única.
    """
    # 1. CIRUGÍA IN-PLACE (O(1)): Aislar la falla temporalmente
    edge_data = G.get_edge_data(u, v)
    if edge_data is not None:
        G.remove_edge(u, v)

    tunnel_cost = 0.0
    avg_repair_cost = 0.0

    try:
        # --- PARTE A: EL TÚNEL (Esfuerzo de Redirección u -> c) ---
        if u != c:
            try:
                tunnel_cost = nx.shortest_path_length(G, source=u, target=c, weight='score')
            except nx.NetworkXNoPath:
                return float('inf') # Héroe inalcanzable

        # --- PARTE B: LA REPARACIÓN (Esfuerzo de Entrega c -> affected) ---
        if affected:
            # DIJKSTRA DE FUENTE ÚNICA: Calcula todas las rutas desde 'c' en una sola pasada
            lengths_from_hero = nx.single_source_dijkstra_path_length(G, c, weight='score')
            
            total_repair_cost = 0.0
            for dest in affected:
                if dest not in lengths_from_hero:
                    return float('inf') # Destino aislado, solución inválida
                total_repair_cost += lengths_from_hero[dest]
                
            avg_repair_cost = total_repair_cost / len(affected)

        return tunnel_cost + avg_repair_cost

    finally:
        # 2. RESTAURACIÓN TOPOLÓGICA (O(1)): Garantizamos que el grafo vuelva a la normalidad
        # El bloque 'finally' asegura la restauración incluso si ocurre un 'return' prematuro
        if edge_data is not None:
            G.add_edge(u, v, **edge_data)
# ==============================================================================
# 2. SELECTION LOGIC (Standard Graph Theory)
# ==============================================================================
def affected_destinations(G, u, v, weight_attr='score'):
    affected = set()
    #We get distances and paths before the fail link
    try:
        base_paths=nx.single_source_dijkstra_path(G,u,weight=weight_attr)
    except nx.NetworkXException:
        return affected
    #Analyze if the optimal route from u to dest  has a v as a first hop, is affected
    for dest , path in base_paths.items():
        if dest !=u and len(path)>1:
            if path[1]==v:
                affected.add(dest)
    return affected
        
def failure_dict(G, weight_attr='score'):
    failures = {}
    for (a, b) in G.edges():
        failures[(a, b)] = affected_destinations(G, a, b,weight_attr)
        failures[(b, a)] = affected_destinations(G, b, weight_attr)
    return failures


def candidates(G,a,h,weight_attr='score'): # a variable a are the nodes h is the failure_dict
    candidate_table={}
    for (u,v), affected in h.items():
        valid_candidates=[]
        #We broke in place the link
        edge_data=G.get_edge_data(u,v)
        if edge_data is not None: G.remove_edge(u,v)
        try:
            for c in a:
                if c==u: continue
                #RULE1
                #Does it exist a tunnel from u to c given the broken link?
                if not nx.has_path(G,source=u, target=c):
                    continue
                #RULE 2
                #is this candidate able to reach every single affected destination?
                can_repair_all=True
                for d in affected:
                    if not nx.has_path(G,source=c,target=d):
                        can_repair_all=False
                        break
                if can_repair_all:
                    valid_candidates.append(c)
                candidate_table[(u,v)]=valid_candidates
        finally:
            if edge_data is not None: G.add_edge(u,v,**edge_data)
    return candidate_table

def find_minimum_set(candidate_table, all_nodes, node_traffic_pps, max_k=9):
    """
    Solución Greedy Híbrida:
    1. Encuentra el 'Base Set' (Núcleo mínimo para 100% resiliencia).
    2. Genera expansiones redundantes para crear un Frente de Pareto y alimentar a Alpha.
    """
    import itertools
    
    # 1. Mapeo Inverso: Qué fallas cubre cada nodo
    node_coverage = {node: set() for node in all_nodes}
    all_failures = set(candidate_table.keys())
    
    for failure_id, valid_heroes in candidate_table.items():
        for hero in valid_heroes:
            node_coverage[hero].add(failure_id)

    print(f"Executing Fast Greedy Set Cover...")
    
    # 2. EL ALGORITMO GREEDY PURO (Búsqueda del Núcleo)
    uncovered_failures = set(all_failures)
    greedy_base_set = []
    
    while uncovered_failures:
        best_node = None
        best_coverage_count = -1
        
        for node in all_nodes:
            useful_coverage = node_coverage[node].intersection(uncovered_failures)
            if len(useful_coverage) > best_coverage_count:
                best_coverage_count = len(useful_coverage)
                best_node = node
                
        if best_coverage_count == 0:
            print("  [ERROR] Unsolvable: Impossible to cover all link failures.")
            return None
            
        greedy_base_set.append(best_node)
        uncovered_failures -= node_coverage[best_node]
        
    greedy_base_set = sorted(greedy_base_set)
    print(f"  > Greedy Base Set Found (Size {len(greedy_base_set)}): {greedy_base_set} -> 100% Resilience Guaranteed")
    
    # 3. GENERACIÓN DEL PARETO FRONT (La Expansión)
    # Todos estos sets INCLUYEN el base set, por lo que la resiliencia es matemáticamente innegociable.
    valid_sets = set()
    valid_sets.add(tuple(greedy_base_set))
    
    available_nodes = [n for n in all_nodes if n not in greedy_base_set]
    
    # Expansión Nivel 1: Añadir 1 Héroe redundante (Sube Energía, Baja Latencia)
    for extra in available_nodes:
        new_set = greedy_base_set + [extra]
        valid_sets.add(tuple(sorted(new_set)))
        
    # Expansión Nivel 2: Añadir 2 Héroes redundantes
    for extras in itertools.combinations(available_nodes, 2):
        new_set = greedy_base_set + list(extras)
        valid_sets.add(tuple(sorted(new_set)))

    found_solutions = list(valid_sets)
    print(f"  > Expansion Complete: {len(found_solutions)} Resilient Candidates generated for Alpha Tribunal.")
    
    return found_solutions

def get_network_latency_score(G, placement_set, node_traffic_pps, node_caps):
    """
    Calcula el retardo promedio del Plano de Control (Control Plane Latency).
    Evalúa el tiempo de respuesta: Propagación hacia el Héroe + Cola M/M/1 en la CPU del Héroe.
    """
    # 1. Búsqueda Optimizada (Evita O(V^2)): 
    # Lanzamos Dijkstra desde los Héroes (controladores) hacia la red.
    min_prop_delays = {n: float('inf') for n in G.nodes()}
    nearest_ctrls = {n: None for n in G.nodes()}
    
    for ctrl in placement_set:
        try:
            # USAMOS 'delay' FÍSICO, NO 'weight'
            paths_from_ctrl = nx.single_source_dijkstra_path_length(G, ctrl, weight='delay')
            
            for node, dist in paths_from_ctrl.items():
                if dist < min_prop_delays[node]:
                    min_prop_delays[node] = dist
                    nearest_ctrls[node] = ctrl
        except nx.NetworkXException:
            pass

    total_latency = 0.0
    connected_nodes = 0

    # 2. Evaluación M/M/1 del CPU del Héroe
    for n in G.nodes():
        ctrl = nearest_ctrls[n]
        if ctrl is None: continue # Nodo aislado del plano de control
        
        # Obtenemos la carga (lambda) y capacidad (mu) de ESE Héroe específico
        lam = node_traffic_pps.get(ctrl, 0.0)
        mu = node_caps.get(ctrl, 1000000.0) # Fallback seguro
        
        # Fórmula de Colas M/M/1
        if lam >= mu * 0.99:
            queue_delay = 1000.0 # Castigo de 1 segundo si el cerebro está saturado
        else:
            queue_delay = (1.0 / (mu - lam)) * 1000.0 # Milisegundos
            
        total_latency += (min_prop_delays[n] + queue_delay)
        connected_nodes += 1

    return total_latency / connected_nodes if connected_nodes > 0 else float('inf')

def best_green_placement(G, valid_sets, alpha, node_traffic_pps, ZODIAC_CAP=9500):
    """
    Tribunal Final Purificado: 
    Mide el costo energético de los Héroes vs la Latencia de Rescate.
    """
    if not valid_sets: return None, 0.0, 0.0, float('inf'), []

    raw_results = []
    max_e, min_e = -float('inf'), float('inf')
    max_d, min_d = -float('inf'), float('inf')

    for s in valid_sets:
        current_watts = 0.0
        node_caps = {}
        
        # 1. Energía de los Héroes (Auto-Scaling)
        for node in s:
            traffic = node_traffic_pps.get(node, 0.0)
            degree = G.degree(node)
            
            # Decidimos hardware según tráfico
            if traffic > ZODIAC_CAP:
                hw = NEC_PF5240
            else:
                hw = ZodiacFX
            
            watts = hw.P_BASE + (degree * hw.P_PORT)
            current_watts += watts
            node_caps[node] = hw.MU

        # 2. Evaluar Latencia M/M/1
        avg_delay = get_network_latency_score(G, s, node_traffic_pps, node_caps)
        
        raw_results.append({'set': s, 'watts': current_watts, 'delay': avg_delay})
        
        # Actualizamos límites para normalizar
        max_e, min_e = max(max_e, current_watts), min(min_e, current_watts)
        max_d, min_d = max(max_d, avg_delay), min(min_d, avg_delay)

    # 3. Normalización y Veredicto (Alpha Control)
    e_range = (max_e - min_e) if (max_e - min_e) > 0 else 1.0
    d_range = (max_d - min_d) if (max_d - min_d) > 0 else 1.0

    best_score = float('inf')
    winner = None

    for result in raw_results:
        norm_e = (result['watts'] - min_e) / e_range
        norm_d = (result['delay'] - min_d) / d_range
        
        # Ecuación Maestra: Aquí Alpha por fin podrá desempatar
        score = (alpha * norm_e) + ((1 - alpha) * norm_d)
        
        result['norm_e'] = norm_e
        result['norm_d'] = norm_d
        result['score'] = score
        
        if score < best_score:
            best_score = score
            winner = result

    return winner['set'], winner['watts'], winner['delay'], best_score, raw_results


def best_green_placement(G, valid_sets, alpha, node_traffic_pps, ZODIAC_CAP=9500):
    """
    Tribunal Final: Evaluación Multi-Objetivo con Normalización Dinámica.
    Armoniza Energía (Watts) y Retardo (ms) bajo el control absoluto de Alpha.
    """
    if not valid_sets: return None, 0.0, float('inf')

    # FASE 1: Exploración (Recolectar la física bruta de todos los sets)
    raw_results = []
    
    # Variables dinámicas para encontrar los extremos reales
    max_e, min_e = -float('inf'), float('inf')
    max_d, min_d = -float('inf'), float('inf')

    print("Executing Phase 1: Profiling Candidates...")
    for s in valid_sets:
        current_watts = 0.0
        node_caps = {}
        
        # Auto-Scaling de Hardware para los Héroes
        for node in s:
            traffic = node_traffic_pps.get(node, 0.0)
            if traffic > ZODIAC_CAP:
                p_base, p_port, cap = NEC_PF5240.P_BASE, NEC_PF5240.P_PORT, NEC_PF5240.MU
            else:
                p_base, p_port, cap = ZodiacFX.P_BASE, ZodiacFX.P_PORT, ZodiacFX.MU
                
            current_watts += p_base + (G.degree(node) * p_port)
            node_caps[node] = cap
            
        # Consumo del resto de la red (Baseline Legacy NEC)
        for n in G.nodes():
            if n not in s:
                current_watts += NEC_PF5240.P_BASE + (G.degree(n) * NEC_PF5240.P_PORT)

        # Evaluar la latencia usando la mitad del cerebro que ya auditamos
        avg_delay = get_network_latency_score(G, s, node_traffic_pps, node_caps)
        
        # Almacenar resultados en crudo y actualizar límites mundiales
        raw_results.append({'set': s, 'watts': current_watts, 'delay': avg_delay})
        
        max_e, min_e = max(max_e, current_watts), min(min_e, current_watts)
        max_d, min_d = max(max_d, avg_delay), min(min_d, avg_delay)

    # Prevención de división por cero (si todos los sets consumen/tardan exactamente lo mismo)
    e_range = (max_e - min_e) if (max_e - min_e) > 0 else 1.0
    d_range = (max_d - min_d) if (max_d - min_d) > 0 else 1.0

    # FASE 2: El Veredicto de Alpha (Normalización estricta 0.0 - 1.0)
    print(f"Executing Phase 2: Alpha Resolution (Alpha={alpha})...")
    best_score = float('inf')
    winner = None

    for result in raw_results:
        # Min-Max Normalization
        norm_e = (result['watts'] - min_e) / e_range
        norm_d = (result['delay'] - min_d) / d_range
        
        # La Ecuación Maestra
        score = (alpha * norm_e) + ((1 - alpha) * norm_d)
        result['nor_e']=norm_e
        result['norm_d']=norm_d
        result['score']=score
        if score < best_score:
            best_score = score
            winner = result

    print(f"  > WINNER SET: {winner['set']} | W: {winner['watts']:.2f} | D: {winner['delay']:.2f}ms | Score: {best_score:.4f}")
    return winner['set'], winner['watts'], winner['delay'], best_score, raw_results 

# ==============================================================================
# 5. Recovery PATH
# ==============================================================================
# --- REEMPLAZAR LA FUNCIÓN recovery_path ENTERA EN MCS.py ---
# --- REEMPLAZAR LA FUNCIÓN recovery_path ENTERA EN MCS.py ---

def recovery_path(alpha=None, node_traffic_pps=None): # <--- CAMBIO CRÍTICO: Añadir este argumento
    """
    Orquestador Principal del Algoritmo Green-MCS.
    """
    # 1. CARGA DE DATOS Y CONFIGURACIÓN
    topo_loader = get_active_topology()
    G = topo_loader.get_graph()

    # --- LÓGICA DE PROTECCIÓN: Usar tráfico externo si existe ---
    if node_traffic_pps is None:
        print("[MCS] WARNING: No external traffic provided. Loading from disk...")
        # Intenta cargar el dataset Nobel-Germany explícitamente
        #dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Nobel-Germany"
        #dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Germany50"
        dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/abilene"

        if os.path.isdir(dataset_folder):
            node_traffic_pps = topo_loader.get_peak_traffic_from_folder(dataset_folder)
        else:
            print("[MCS] ERROR: Dataset folder not found in MCS. Using topology default (Low Traffic).")
            node_traffic_pps = topo_loader.get_traffic_load()
    # ------------------------------------------------------------
    
    if alpha is None:
        config = get_config()
        alpha = float(config.get('alpha', 0.5))
    
    print(f"\n[MCS] Running Recovery Logic | Alpha: {alpha}")
    
    h = failure_dict(G)
    cand_table = candidates(G, G.nodes(), h)
    
    # 2. FASE 1: SETS VIABLES
    valid_sets = find_minimum_set(cand_table, G.nodes(), node_traffic_pps)
    
    if not valid_sets:
        print("[MCS] CRITICAL: No physically viable solution found.")
        return None, None, G

    ## 3. FASE 2: EL TRIBUNAL (ELEGIR GANADOR)
    # Atrapamos los 5 valores, incluyendo la telemetría para tus gráficos
    winner_set, winner_watts, winner_delay, total_score, raw_results = best_green_placement(
        G, valid_sets, alpha, node_traffic_pps
    )
    
    print(f"[MCS] Winner Set Selected: {list(winner_set)}")
    print(f"[MCS] Est. Power: {winner_watts:.2f}W | Est. Delay: {winner_delay:.2f}ms")

    # 4. FASE 3: FAILOVER MAP (El Enrutamiento Final)
    failover = {}
    
    # Inyectamos el 'score' híbrido en la red física
    assign_green_weights(G, winner_set, alpha, node_traffic_pps)
    
    for (u, v), affected in h.items():
        if not affected: continue 
        
        best_fail_score = float('inf')
        chosen_hero = None 
        
        # Solo los Héroes ganadores que además pueden salvar este enlace específico
        potential_heroes = [node for node in winner_set if node in cand_table.get((u, v), [])]
        
        for hero in potential_heroes:
            # Evaluamos el costo total del desvío usando la métrica purificada
            path_score = get_path_score(G, u, v, hero, affected)
            if path_score < best_fail_score:
                best_fail_score = path_score
                chosen_hero = hero
        
        if chosen_hero is not None:
            failover[(u, v)] = chosen_hero

    print(f"[MCS] Failover Map Generated: {len(failover)} protection rules active.")
    
    # Devolvemos el ganador, el mapa de recuperación y el grafo con sus métricas actualizadas
    return winner_set, failover, G



if __name__ == '__main__':
    
    # 1. Configuración de la Simulación
    config = get_config()
    alpha = float(config.get('alpha', 0.5))
    
    print("="*60)
    print(f"  GREEN-MCS HYBRID ORCHESTRATOR INITIALIZING (Alpha: {alpha})")
    print("="*60)
    
    # 2. Carga de Topología (SNDLib)
    topo_loader = get_active_topology()
    G = topo_loader.get_graph()
    print(f"[INFO] Topology Loaded: {len(G.nodes())} Nodes, {len(G.edges())} Edges.")
    
    # 3. EXTRACCIÓN DEL "WORST CASE" (Pico Histórico)
    dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/abilene"
    
    if os.path.isdir(dataset_folder):
        print(f"[INFO] Scanning Peak Traffic from: {os.path.basename(dataset_folder)}...")
        node_traffic_pps = topo_loader.get_peak_traffic_from_folder(dataset_folder)
    else:
        print(f"[WARNING] Dataset folder not found. Using topology default traffic.")
        node_traffic_pps = topo_loader.get_traffic_load()

    # 4. Ejecución del Pipeline Matemático
    print("\n[PHASE 1] Analyzing Topological Vulnerabilities...")
    h_dict = failure_dict(G)
    
    print("[PHASE 2] Identifying Hero Candidates...")
    cand_table = candidates(G, G.nodes(), h_dict)
    
    print("[PHASE 3] Combinatorial Reduction (Greedy Set Cover)...")
    valid_sets = find_minimum_set(cand_table, G.nodes(), node_traffic_pps, max_k=len(G.nodes()))
    
    # 5. El Veredicto Final
    if valid_sets:
        print("\n[PHASE 4] Executing Alpha-Driven Multi-Objective Optimization...")
        
        # Desempaquetado riguroso de las 5 variables del Tribunal
        winner_set, winner_watts, winner_delay, best_score, raw_results = best_green_placement(
            G, valid_sets, alpha, node_traffic_pps
        )
        
        print("\n" + "="*60)
        print("                 FINAL SIMULATION RESULT")
        print("="*60)
        print(f" [★] WINNER HERO SET : {list(winner_set)}")
        print(f" [⚡] TOTAL POWER     : {winner_watts:.2f} Watts")
        print(f" [⏱] AVG LATENCY     : {winner_delay:.2f} ms")
        print(f" [⚖] ALPHA SCORE     : {best_score:.4f} (Alpha={alpha})")
        print(f" [📊] TELEMETRY       : {len(raw_results)} candidates profiled for Pareto Front.")
        print("="*60 + "\n")
        
        # (Opcional) Aquí podrías iterar sobre raw_results si quisieras imprimir los perdedores
    else:
        print("\n[CRITICAL FAILURE] The algorithm could not find a viable placement to cover all link failures.")
   
