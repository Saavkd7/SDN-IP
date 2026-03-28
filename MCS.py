import networkx as nx
import os, json, logging, itertools
from green_models import NEC_PF5240, ZodiacFX, GreenNormalizer
from sndlib_loader import SNDLibXMLParser
import csv
import pandas as pd
#==================================================================
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

def get_traffic_profile(loader, G, dataset_folder=None, burst_multiplier=1.0,avg_packet=1500,sigma=0.0):

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
        if lam_peak < (ZODIAC_CAPACITY * 0.95): # Margen de seguridad del 10%
            hw = ZodiacFX()
        else:
            hw = NEC_PF5240()
        G.nodes[n]['hardware'] = hw.__class__.__name__    
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
        
        # Energía promediada del enlace
        edge_norm_energy = (stat_u['norm_energy'] + stat_v['norm_energy']) / 2.0
        
        # Retardo de Cola en cada extremo (M/M/1 en milisegundos)
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

def get_pure_recovery_delay(G, placement_set, h_dict, cand_table, node_traffic_pps):
    """
    Evalúa el RPL en milisegundos físicos puros + Retardo de Cola M/M/1.
    No hay política 'Alpha' aquí. Solo física.
    """
    total_delay = 0.0
    evaluated_failures = 0
    Z_CAP = ZodiacFX.MU * 0.95
    
    for (u, v), affected in h_dict.items():
        if not affected: continue
        
        valid_heroes = [h for h in placement_set if h in cand_table.get((u, v), [])]
        if not valid_heroes:
            return float('inf')
            
        best_hero_delay = float('inf')
        for h in valid_heroes:
            # 1. Distancia Topológica (PURA, sin Alpha)
            edge_data = G.get_edge_data(u, v)
            if edge_data: G.remove_edge(u, v)
            try:
                tunnel = nx.shortest_path_length(G, u, h, weight='delay') if u != h else 0
                lengths = nx.single_source_dijkstra_path_length(G, h, weight='delay')
                repair = sum(lengths.get(d, 100.0) for d in affected) / len(affected)
                prop_delay = tunnel + repair
            except: 
                prop_delay = float('inf')
            finally:
                if edge_data: G.add_edge(u, v, **edge_data)
            
            # 2. Retardo de Cola M/M/1 del Héroe
            lam = node_traffic_pps.get(h, 0.0)
            mu = NEC_PF5240.MU if lam > Z_CAP else ZodiacFX.MU
            q_delay = (1.0 / (mu - lam)) * 1000.0 if lam < mu * 0.99 else 1000.0
            
            # 3. Retardo Total de la Falla
            total_falla = prop_delay + q_delay
            if total_falla < best_hero_delay:
                best_hero_delay = total_falla
                
        total_delay += best_hero_delay
        evaluated_failures += 1
        
    return total_delay / evaluated_failures if evaluated_failures > 0 else float('inf')


def best_green_placement(G, valid_sets, alpha, node_traffic_pps, h_dict, cand_table):
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
        pure_delay = get_pure_recovery_delay(G, s, h_dict, cand_table, node_traffic_pps)
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



def recovery_path(alpha=None, node_traffic_pps=None, dataset=None):
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
    winner_set, _, _, _, _ = best_green_placement(G, valid_sets, alpha, node_traffic_pps, h_dict, cand_table)
    
    # 3. Mapeo de Failover para Túneles MPLS
    assign_green_weights(G, alpha, node_traffic_pps)
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




def run_experiment_sweep(G, valid_sets, loader, dataset_folder, h_dict, cand_table, BURST, AVG):
    """
    Ejecuta el barrido y exporta de forma segregada tanto los conteos (para graficar)
    como las identidades textuales (para auditoría) de los Héroes NEC y Zodiac.
    """
    results_file = "simulation_results.csv"
    sigmas = [0, 100, 200, 400, 700] 
    alphas = [0, 0.20, 0.4, 0.6, 0.8, 1] 
    AVG_PKT = AVG 
    
    Z_CAP = ZodiacFX.MU * 0.95 
    
    with open(results_file, mode='w', newline='') as f:
        writer = csv.writer(f)
        # 1. CABECERAS NORMALIZADAS: Cuantitativo vs Cualitativo
        writer.writerow([
            'Sigma', 'Alpha', 'WinnerSet_Names', 
            'NEC_Heros_Count', 'NEC_Hero_Names',       # <-- Separación estricta
            'Zodiac_Heros_Count', 'Zodiac_Hero_Names', # <-- Separación estricta
            'NEC_Passive_Count', 'Zodiac_Passive_Count', 
            'Watts_Total', 'Delay_ms', 'Score'
        ])

        for s_factor in sigmas:
            traffic = get_traffic_profile(
                loader, 
                G, 
                dataset_folder=dataset_folder, 
                burst_multiplier=BURST, 
                avg_packet=AVG_PKT, 
                sigma=s_factor
            )

            for a_val in alphas:
                print(f"[RUNNING] Sigma: {s_factor} | Alpha: {a_val}")
                
                w_set, w_watts, w_delay, b_score, _ = best_green_placement(
                    G, valid_sets, a_val, traffic, h_dict, cand_table
                )
                
                named_w_set = [G.nodes[n].get('name', str(n)) for n in w_set]
                
                # 2. EXTRACCIÓN CUALITATIVA (Los Quiénes)
                nec_hero_nodes = [n for n in w_set if traffic.get(n, 0.0) > Z_CAP]
                zodiac_hero_nodes = [n for n in w_set if traffic.get(n, 0.0) <= Z_CAP]
                
                # Traducción a Nombres
                nec_hero_names = [G.nodes[n].get('name', str(n)) for n in nec_hero_nodes]
                zodiac_hero_names = [G.nodes[n].get('name', str(n)) for n in zodiac_hero_nodes]
                
                # 3. EXTRACCIÓN CUANTITATIVA (Los Cuántos)
                nec_heros_count = len(nec_hero_nodes)
                zodiac_heros_count = len(zodiac_hero_nodes)
                
                # 4. CONTEO DE PASIVOS
                nec_passive_count = 0
                zodiac_passive_count = 0
                passive_p = 0.0
                
                for n in G.nodes():
                    if n not in w_set:
                        t = traffic.get(n, 0.0)
                        if t > Z_CAP:
                            hw_obj = NEC_PF5240
                            nec_passive_count += 1
                        else:
                            hw_obj = ZodiacFX
                            zodiac_passive_count += 1
                            
                        passive_p += hw_obj.P_BASE + (G.degree(n) * hw_obj.P_PORT)
                
                # 5. EXPORTACIÓN ORDENADA
                writer.writerow([
                    s_factor, a_val, named_w_set, 
                    nec_heros_count, nec_hero_names, 
                    zodiac_heros_count, zodiac_hero_names, 
                    nec_passive_count, zodiac_passive_count, 
                    round(w_watts + passive_p, 2), round(w_delay, 2), round(b_score, 4)
                ])
                
    print(f"\n[DONE] Results exported to {results_file}")
    return G
# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
if __name__ == '__main__':
    # Configurar el Logger
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    # 1. CARGA DE CONFIGURACIÓN (La Fuente de Verdad)
    config = get_config()
    alpha = config.get('alpha', 0.5)
    
    # Parámetros de Estrés (Puedes moverlos al config.json si prefieres)
    BURST_MULTIPLIER = 1   # PAR
    SIGMA_FACTOR = 0.0      # Escala del tráfico
    AVG_PACKET_SIZE=800

    
    loader = get_active_topology()
    G = loader.get_graph() 
    Z_CAP = ZodiacFX.MU * 0.95
    
    # 2. CAPTURA DE TRÁFICO (Respetando el Dataset seleccionado)
    #dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Germany50"
    #dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Nobel-Germany"
    dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Abilene"
    
    if os.path.isdir(dataset_folder):
        print(f"\n[INFO] Scanning real traffic patterns from: {os.path.basename(dataset_folder)}")
        # Usamos la función perfiladora para aplicar Sigma y PAR
        node_traffic_pps = get_traffic_profile(
            loader, G, dataset_folder, BURST_MULTIPLIER, AVG_PACKET_SIZE, SIGMA_FACTOR
        )
    else:
        print("[WARNING] Traffic folder not found. Falling back to default.")
        node_traffic_pps = loader.calculate_full_network_load(G=G)

    # 3. PIPELINE DE EJECUCIÓN
    h_dict = build_failure_dict(G)
    cand_table = get_valid_candidates(G, G.nodes(), h_dict)

    matrix_data = []
    
    for link, candidates_list in cand_table.items():
        u, v = link
        affected = h_dict[link]
        # Estructura base de la fila
        row = {
            'Link_Index': f"({u}, {v})",
            'Affected_Destinations': str(affected)
        }
        
        # Proyección binaria: 1 si es candidato, 0 si no lo es
        for node in G.nodes():
            # Usamos el nombre de la columna dinámicamente, ej: 'Node_1'
            col_name = str(node) 
            row[col_name] = 1 if node in candidates_list else 0
            
        matrix_data.append(row)

    # 4. RENDERIZADO DEL DATAFRAME
    df_candidate_table = pd.DataFrame(matrix_data)
    
    print("\n--- SDN Candidate Table (T) ---")
    # Imprimimos la tabla en formato amigable para la terminal
    print(df_candidate_table.to_string(index=False))
    
    # 5. EXPORTACIÓN AUTOMATIZADA
    output_file = "SDN_Candidate_Table.csv"
    df_candidate_table.to_csv(output_file, index=False)
    print(f"\n[SUCCESS] Tabla binaria exportada a {output_file} lista para ser tabulada en tu paper.")





    
    
    # valid_sets = find_minimum_set(cand_table, G.nodes())
    
    # # EL TRIBUNAL: Ahora usa el 'alpha' que vino del JSON
    # w_set, w_watts, w_delay, b_score, raw_results = best_green_placement(
    #     G, valid_sets, alpha, node_traffic_pps, h_dict, cand_table
    # )
    
    # # 4. INVENTARIO DE HARDWARE (Cálculo de consumo total)
    # h_nec, h_zodiac, p_nec, p_zodiac, passive_power = 0, 0, 0, 0, 0.0
    # for node in w_set:
    #     if node_traffic_pps.get(node, 0.0) > Z_CAP: h_nec += 1
    #     else: h_zodiac += 1

    # for n in G.nodes():
    #     if n not in w_set:
    #         traffic = node_traffic_pps.get(n, 0.0)
    #         if traffic > Z_CAP: 
    #             hw, p_nec = NEC_PF5240, p_nec + 1
    #         else: 
    #             hw, p_zodiac = ZodiacFX, p_zodiac + 1
    #         passive_power += hw.P_BASE + (G.degree(n) * hw.P_PORT)
    
    # total_network_power = w_watts + passive_power
    # Lanzamos el barrido
    # run_experiment_sweep(G, valid_sets, loader, dataset_folder, h_dict, cand_table,BURST_MULTIPLIER,AVG_PACKET_SIZE)
   # 5. OUTPUT FINAL (Consistente y Profesional)
#     print("\n" + "="*60)
#     print(f"   FINAL SIMULATION: PAR={BURST_MULTIPLIER}x | SIGMA={SIGMA_FACTOR} | AVG PACKET SIZE={AVG_PACKET_SIZE} BYTES")
#     print("="*60)
#     print(f" [★] WINNER HERO SET  : {list(w_set)}")
#     print(f" [🛠] HERO HW MIX     : {h_nec} NEC, {h_zodiac} Zodiac")
#     print(f" [📡] PASSIVE HW MIX  : {p_nec} NEC, {p_zodiac} Zodiac")
#     print(f" [⚡] CONTROLLER POWER : {w_watts:.2f} Watts")
#     print(f" [🏢] PASSIVE NETWORK  : {passive_power:.2f} Watts")
#     print(f" [🌍] TOTAL NET POWER  : {total_network_power:.2f} Watts")
#     print(f" [⏱] AVG RESP. DELAY  : {w_delay:.2f} ms")
#     print(f" [⚖] ALPHA SCORE      : {b_score:.4f} (Alpha={alpha})")
#     print("="*60 + "\n")

#    # --- THE FIX: Uso de la Verdad Absoluta estática ---
#     assign_green_weights(G, alpha, node_traffic_pps)
    
#     # Extracción elegante y directa de los NOMBRES usando el diccionario de atributos (attr)
#     zodiac_node_names = [attr.get('name', str(n)) for n, attr in G.nodes(data=True) if attr.get('hardware') == 'ZodiacFX']
#     nec_node_names = [attr.get('name', str(n)) for n, attr in G.nodes(data=True) if attr.get('hardware') == 'NEC_PF5240']
    
#     # Telemetría legible para humanos
#     print(f"[Hardware Map] ZodiacFX Nodes (Green) : {zodiac_node_names}")
#     print(f"[Hardware Map] NEC PF5240 Nodes (Legacy): {nec_node_names}")
