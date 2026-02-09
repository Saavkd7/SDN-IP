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
# ===================   ===========================================================
# 1. UTILS
# ==============================================================================
def get_config():
    if not os.path.exists('config.json'): 
        # CORRECCIÓN AQUÍ: Apunta a la carpeta correcta por defecto
        return {"alpha": 0.5, "topology": "Top/abilene.xml"} 
    with open('config.json', 'r') as f:
        return json.load(f)

def get_active_topology():
    config = get_config()
    filename = config.get('topology', 'abilene.xml')
    
    # Construir la ruta completa si no la tiene
    if not filename.startswith('Top/'):
        xml_filename = os.path.join('Top', filename)
    else:
        xml_filename = filename

    if os.path.exists(xml_filename):
        topo_loader = SNDLibXMLParser(xml_filename)
        return topo_loader
    else:
        print(f"[ERROR] File not found: {xml_filename}")
       
def assign_green_weights(G, candidate_set, alpha, node_traffic_pps):
    """
    LOGICA DINÁMICA: 
    - Si es Héroe Y su tráfico < Capacidad Zodiac -> Usa Zodiac (Green).
    - Si es Héroe Y su tráfico > Capacidad Zodiac -> Usa NEC (Performance Fallback).
    - Si no es Héroe -> Usa NEC (Legacy).
    """
    
    # Referencias
    degrees = [d for n, d in G.degree()]
    max_degree = max(degrees) if degrees else 48
    MAX_POWER = GreenNormalizer.get_max_power(max_degree)
    MAX_DELAY_THRESHOLD = GreenNormalizer.get_worst_delay_threshold()
    
    # Capacidad del Zodiac (El límite "Green")
    ZODIAC_CAPACITY = ZodiacFX.MU 

    for u, v in G.edges():
        
        # --- A. SELECCIÓN DE HARDWARE DINÁMICA ---
        lam = node_traffic_pps.get(v, 0.0) # Tráfico real del nodo destino
        
        hw = None
        p_base = 0.0
        p_port = 0.0
        mu = 0.0

        if v in candidate_set:
            # Es un candidato a Héroe. ¿Aguanta siendo Zodiac?
            if lam < (ZODIAC_CAPACITY * 0.95): # Margen seguridad 5%
                # SÍ: Usamos Hardware Green
                hw = ZodiacFX()
            else:
                # NO: Upgrade forzoso a NEC para no saturar
                hw = NEC_PF5240()
        else:
            # No es Héroe: Hardware Legacy por defecto
            hw = NEC_PF5240()

        # Extraemos specs del hardware decidido
        p_base = hw.get_base_power()
        p_port = hw.P_PORT
        mu = hw.get_capacity()

        # --- B. MODELADO DE ENERGÍA (Watts) ---
        active_ports = G.degree(v)
        total_watts = p_base + (active_ports * p_port)
        norm_energy = total_watts / MAX_POWER

        # --- C. MODELADO DE DELAY (M/M/1) ---
        d_prop = G[u][v].get('weight', 0.001) 
        
        # Como hicimos el upgrade automático, difícilmente habrá saturación masiva,
        # pero mantenemos la fórmula M/M/1 por si acaso.
        if lam >= (mu * 0.99):
            norm_delay = 1.0 
        else:
            d_queue = 1.0 / (mu - lam)
            total_delay = d_prop + d_queue
            norm_delay = min(total_delay / MAX_DELAY_THRESHOLD, 1.0)

        # --- D. SCORE HÍBRIDO FINAL ---
        score = (alpha * norm_energy) + ((1 - alpha) * norm_delay)
        
        G[u][v]['score_cost'] = score
        if not G.is_directed():
            G[v][u]['score_cost'] = score

def get_path_score(G, u, v, c, affected):
    """
    Calcula el Green RPL (Costo total del camino de recuperación).
    1. Túnel: Costo (Energía + Delay M/M/1) de ir de Fuente (u) -> Héroe (c).
    2. Reparación: Costo promedio de ir de Héroe (c) -> Destinos (affected).
    """
    # Creamos una copia temporal para simular la falla del enlace (u, v)
    G_temp = G.copy()
    if G_temp.has_edge(u, v): 
        G_temp.remove_edge(u, v)

    # --- PARTE A: EL TÚNEL (Esfuerzo de Redirección) ---
    tunnel_cost = 0.0
    if u != c:
        try:
            # nx.shortest_path_length usará el 'score_cost' que ya tiene alpha, Watts y M/M/1
            tunnel_cost = nx.shortest_path_length(G_temp, source=u, target=c, weight='score_cost')
        except nx.NetworkXNoPath:
            return float('inf') # Inviable si no hay camino físico al héroe

    # --- PARTE B: LA REPARACIÓN (Esfuerzo de Entrega) ---
    if not affected:
        return tunnel_cost

    total_repair_cost = 0.0
    reachable_count = 0

    for dest in affected:
        try:
            # Costo acumulado desde el Héroe hasta el destino final
            dist = nx.shortest_path_length(G_temp, source=c, target=dest, weight='score_cost')
            total_repair_cost += dist
            reachable_count += 1
        except nx.NetworkXNoPath:
            return float('inf') # Si un destino queda aislado, la solución es inválida

    avg_repair_cost = total_repair_cost / reachable_count if reachable_count > 0 else 0

    # Green RPL = Costo del Túnel + Costo Promedio de Reparación
    return tunnel_cost + avg_repair_cost
# ==============================================================================
# 2. SELECTION LOGIC (Standard Graph Theory)
# ==============================================================================
def affected_destinations(G, i, j):
    affected = set()
    for d in G.nodes():
        try:
            paths = list(nx.all_shortest_paths(G, source=i, target=d, weight='weight'))
            failure = 0
            for path in paths:
                if j in path and path.index(j) == path.index(i) + 1:
                    failure += 1
            if failure == len(paths) and len(paths) > 0: affected.add(d)
        except nx.NetworkXNoPath: pass
    return affected

def failure_dict(G):
    failures = {}
    for (a, b) in G.edges():
        failures[(a, b)] = affected_destinations(G, a, b)
        failures[(b, a)] = affected_destinations(G, b, a)
    return failures

def candidates(G,a,h): # a variable a are the nodes h is the failure_dict
    candidate_table={}
    for (u,v), affected in h.items():
        valid_candidates=[]
        for c in a:
            reaching=False
            pathuc = list(nx.all_shortest_paths(G, source=u, target=c, weight='weight'))
            if c== u: continue
            pathF=False
            for path in pathuc:
                if not (v in path and path.index(v)== path.index(u)+1):
                    pathF=True
                    break
            if pathF:
                reaching=True
                for d in affected:
                    found=False
                    neighbors=G.neighbors(c)
                    for b  in neighbors:
                        pathFR = list(nx.all_shortest_paths(G, source=b, target=d, weight='weight'))
                        neigsfe=False
                        for pat in pathFR:
                            if u in pat and v in pat:
                                idx_u = pat.index(u)
                                idx_v = pat.index(v)
                                if idx_v == idx_u + 1 or idx_u == idx_v + 1:
                                    continue
                            neigsfe=True
                            break
                        if neigsfe:
                            found=True
                            break
                    if found==False:
                        reaching=False
                        break
            if reaching:
                valid_candidates.append(c)
        candidate_table[(u,v)]=valid_candidates
    return candidate_table

def find_minimum_set(candidate_table, all_nodes, node_traffic_pps, max_k=9):
    """
    VERSIÓN AMPLIADA: Busca K, K+1 y K+2.
    Permite que compitan sets pequeños (probablemente NECs) contra sets 
    más grandes (posiblemente Zodiacs).
    """
    num_failures = len(candidate_table)
    
    # 1. Pre-procesamiento: Cobertura Lógica
    node_coverage = {node: set() for node in all_nodes}
    for failure_id, ((u, v), valid_heroes) in enumerate(candidate_table.items()):
        for hero in valid_heroes:
            node_coverage[hero].add(failure_id)

    print(f"Searching for LOGICAL optimal sets (Max size: {max_k})...")
    
    found_solutions = []
    min_k_found = None
    patience = 2  # Cuántos tamaños extra miramos después de encontrar el mínimo
    
    # 2. Barrido de K
    for k in range(1, len(all_nodes) + 1):
        if k > max_k: break
        
        # Si ya encontramos un K mínimo y nos pasamos de la paciencia, paramos.
        # Ej: Si encontramos sol en K=4, buscamos en 5 y 6, y paramos en 7.
        if min_k_found is not None and k > (min_k_found + patience):
            break

        current_k_solutions = []
        
        # Combinatoria
        # OPTIMIZACIÓN: Si el espacio de búsqueda es gigante, itertools puede tardar.
        # Para K pequeños está bien.
        for candidate_set in itertools.combinations(all_nodes, k):
            total_coverage = set().union(*[node_coverage[node] for node in candidate_set])
            
            if len(total_coverage) == num_failures:
                current_k_solutions.append(candidate_set)
        
        if current_k_solutions:
            print(f"  > Found {len(current_k_solutions)} valid sets at size K={k}")
            
            # Guardamos el primer K donde encontramos algo
            if min_k_found is None:
                min_k_found = k
            
            found_solutions.extend(current_k_solutions)
            
            # Límite de seguridad para no explotar la RAM con miles de sets
            if len(found_solutions) > 100:
                print("  > Candidate limit reached. Stopping search.")
                break

    if found_solutions:
        print(f"Total candidate sets found: {len(found_solutions)} (Sizes {min_k_found} to {min_k_found + patience})")
        return found_solutions
    
    return None
# ==============================================================================
# 3. BEST GREEN PLACEMENT (PHYSICS AWARE)
# ==============================================================================
def best_green_placement(G, h, candidate_table, valid_sets, alpha, node_traffic_pps):
    """
    FASE 2: Selección del Set Ganador con Hardware Dinámico.
    """
    best_total_score = float('inf')
    winner_set = None
    winner_watts = 0.0
    
    # Usamos la capacidad definida en la clase
    ZODIAC_CAPACITY = ZodiacFX.MU

    
    zodiac_candidates_count = 0
    mu_limit = ZodiacFX.MU
    for n, pps in node_traffic_pps.items():
        if pps < (mu_limit * 0.95):
            zodiac_candidates_count += 1
    print(f"[DEBUG] Traffic Analysis: {zodiac_candidates_count}/{len(G.nodes())} nodes are traffic-compatible with Zodiacs.")
    if zodiac_candidates_count == 0:
        print("[WARNING] ALL nodes have traffic > Zodiac Capacity. Alpha will have NO effect.")
    # -------------------------------------
    
    
    
    
    
    print(f"Evaluating {len(valid_sets)} sets with Dynamic Dimensioning...")

    for candidate_set in valid_sets:
        # 1. ACTUALIZAR PESOS (Esto decide internamente quién es Zodiac y quién NEC)
        assign_green_weights(G, candidate_set, alpha, node_traffic_pps)

        # 2. CÁLCULO REAL DE ENERGÍA (Sumando lo que realmente se instaló)
        current_network_watts = 0.0
        
        for node in G.nodes():
            # Lógica idéntica a assign_weights para ser coherentes
            lam = node_traffic_pps.get(node, 0.0)
            
            if node in candidate_set:
                # Intento de ser Green
                if lam < (ZODIAC_CAPACITY * 0.95):
                    # El tráfico permite ser Zodiac (20W)
                    hw_base = ZodiacFX.P_BASE
                    hw_port = ZodiacFX.P_PORT
                else:
                    # El tráfico obliga a ser NEC (118W)
                    hw_base = NEC_PF5240.P_BASE
                    hw_port = NEC_PF5240.P_PORT
            else:
                # No es Héroe -> NEC
                hw_base = NEC_PF5240.P_BASE
                hw_port = NEC_PF5240.P_PORT
            
            current_network_watts += hw_base + (G.degree(node) * hw_port)

        # 3. CÁLCULO DE RESILIENCIA GLOBAL
        total_recovery_score = 0.0
        for (u, v), affected in h.items():
            valid_heroes_in_set = [c for c in candidate_table[(u, v)] if c in candidate_set]
            
            if not valid_heroes_in_set:
                total_recovery_score = float('inf')
                break
            
            best_hero_score = min([
                get_path_score(G, u, v, c, affected) for c in valid_heroes_in_set
            ])
            total_recovery_score += best_hero_score

        # 4. SELECCIÓN
        if total_recovery_score < best_total_score:
            best_total_score = total_recovery_score
            winner_set = candidate_set
            winner_watts = current_network_watts

    return winner_set, winner_watts, best_total_score
# ==============================================================================
# 4. CONTRIBUTION
# ==============================================================================
# def contribution(G, winner_set, total_watts_winner):
#     # 1. BASELINE: ¿Cuánto gastaría esta configuración si usáramos solo NECs (Lo estándar)?
#     # Recalculamos asumiendo que TODOS los nodos del set ganador son NEC_PF5240
#     baseline_watts = 0.0
#     for n in G.nodes():
#         degree = G.degree(n)
#         # En el Baseline, NO discriminamos, asumimos hardware potente/caro en el core
#         # O si prefieres, compara contra el winner_set siendo NECs:
#         if n in winner_set:
#             # Si hubiéramos puesto un NEC aquí en lugar de un Zodiac
#             p_node = NEC_PF5240.P_BASE + (degree * NEC_PF5240.P_PORT)
#         else:
#             # El resto sigue siendo NEC
#             p_node = NEC_PF5240.P_BASE + (degree * NEC_PF5240.P_PORT)
#         baseline_watts += p_node

#     # # 2. CÁLCULO DEL APORTE (GAP)
#     # energy_saved = baseline_watts - total_watts_winner
#     # percentage_saved = (energy_saved / baseline_watts) * 100

#     baseline_watts = 0.0
#     for n in G.nodes():
#         degree = G.degree(n)
#         # Asumiendo baseline puro NEC
#         p_node = NEC_PF5240.P_BASE + (degree * NEC_PF5240.P_PORT)
#         baseline_watts += p_node

#     # ... (Tus prints de reporte siguen igual) ...

#     # LLAMADA LIMPIA A LA GRÁFICA B
#     print("[GRAPHIC] Generating Graph B (Savings)...")
#     vis_utils.plot_graph_b_savings(baseline_watts, total_watts_winner)
#     # print(f"\n=== SCIENTIFIC CONTRIBUTION REPORT ===")
#     # print(f"Standard Approach (All-NEC): {baseline_watts:.2f} W")
#     # print(f"Green MCS Approach (Hybrid): {total_watts_winner:.2f} W")
#     # print(f"--------------------------------------")
#     # print(f"NET ENERGY SAVING: {energy_saved:.2f} W")
#     # print(f"EFFICIENCY GAIN:   {percentage_saved:.1f} %")
#     # print(f"======================================\n")
    
# ==============================================================================
# 5. Recovery PATH
# ==============================================================================

def recovery_path(alpha=None):
    """
    Orquestador Principal del Algoritmo Green-MCS.
    1. Carga Topología y Tráfico.
    2. Ejecuta Fase 1 (Búsqueda de Sets Físicamente Viables).
    3. Ejecuta Fase 2 (Selección del Ganador por Energía/Delay).
    4. Ejecuta Fase 3 (Generación de Mapa de Failover Detallado).
    """
    # 1. CARGA DE DATOS Y CONFIGURACIÓN
    # ---------------------------------------------------------
    topo_loader = get_active_topology() # Instancia del Parser
    G = topo_loader.get_graph()
    
    # ¡CRÍTICO! Extraemos la carga real para el modelo M/M/1
    dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/abilene"
    
    if os.path.isdir(dataset_folder):
        # Esta función escanea todo y devuelve solo los valores máximos
        node_traffic_pps = topo_loader.get_peak_traffic_from_folder(dataset_folder)
    else:
        print(f"[ERROR] Folder not found. Using topology default.")
        node_traffic_pps = topo_loader.get_traffic_load()
    
    if alpha is None:
        config = get_config() # Asumo que tienes esta función de utilidad
        alpha = float(config.get('alpha', 0.5))
    
    print(f"\n[MCS] Running Recovery Logic | Alpha: {alpha}")
    
    h = failure_dict(G)
    cand_table = candidates(G, G.nodes(), h)
    
    # 2. FASE 1: ENCONTRAR SETS VIABLES (FÍSICA + LÓGICA)
    # ---------------------------------------------------------
    # Ahora pasamos node_traffic_pps para filtrar Zodiacs saturados
    valid_sets = find_minimum_set(cand_table, G.nodes(), node_traffic_pps)
    
    if not valid_sets:
        print("[MCS] CRITICAL: No physically viable solution found (Network Saturated).")
        return None, None, G

    # 3. FASE 2: ELEGIR EL MEJOR SET (OPTIMIZACIÓN)
    # ---------------------------------------------------------
    # Seleccionamos el set que minimiza la suma de Energía y Delay Global
    winner_set, winner_watts, total_score = best_green_placement(
        G, h, cand_table, valid_sets, alpha, node_traffic_pps
    )
    
    print(f"[MCS] Winner Set Selected: {list(winner_set)}")
    print(f"[MCS] Est. Power: {winner_watts:.2f}W | Score: {total_score:.4f}")

    # 4. FASE 3: CONSTRUIR DICCIONARIO FAILOVER (MAPEO FINAL)
    # ---------------------------------------------------------
    # Aquí decidimos qué héroe específico del winner_set atiende cada falla.
    failover = {}
    
    # A. "Pintamos" el grafo final con los pesos del ganador para ruteo preciso
    assign_green_weights(G, winner_set, alpha, node_traffic_pps)
    
    # B. Asignación granular
    for (u, v), affected in h.items():
        if not affected: continue 
        
        best_fail_score = float('inf')
        chosen_hero = None 
        
        # Solo miramos candidatos que pertenezcan al WINNER SET
        potential_heroes = [node for node in winner_set if node in cand_table[(u, v)]]
        
        for hero in potential_heroes:
            # Calculamos el Green RPL (Túnel + Reparación)
            # Ya incluye M/M/1 y penalizaciones por saturación
            path_score = get_path_score(G, u, v, hero, affected)
            
            if path_score < best_fail_score:
                best_fail_score = path_score
                chosen_hero = hero
        
        if chosen_hero is not None:
            failover[(u, v)] = chosen_hero
        else:
            # Esto solo pasaría si la topología se fragmenta drásticamente
            print(f"[MCS] WARNING: Winner set cannot cover failure {(u,v)} logically based on current weights.")

    print(f"[MCS] Failover Map Generated: {len(failover)} rules.")
    
    # Retornamos G actualizado con los pesos finales ('score_cost') para visualización
    return winner_set, failover, G
#============================================================================================================================================================

# 6. SATURACION RULES 

#============================================================================================================================================================
# def check_saturation(G, h, winner_set, failover_map):
#     # Capacidad Hipotética de un Zodiac (Green) vs NEC (Standard)
#     ZODIAC_MAX_RULES = 20  # Poca memoria
#     NEC_MAX_RULES = 10000   # Mucha memoria

#     # Contamos cuántas reglas le tocan a cada Héroe en este escenario
#     hero_load = {hero: 0 for hero in winner_set}
    
#     for (u, v), assigned_hero in failover_map.items():
#         # Cuantos destinos se ven afectados por esta falla específica
#         num_reglas = len(h[(u, v)]) 
#         if assigned_hero in hero_load:
#             # Ese héroe debe cargar con todas estas reglas si ese enlace falla
#             # OJO: En el peor caso (Worst Case Scenario), el héroe debe tener espacio 
#             # para la falla más grande que le toque cubrir, NO la suma de todas (porque no fallan todas a la vez).
#             # PERO, para simplificar "Reserva de Recursos", a veces se suma. 
#             # Vamos a usar el criterio: "Max Single Failure Load" (El pico de carga)
#             hero_load[assigned_hero] = max(hero_load[assigned_hero], num_reglas)

#     print("\n--- SATURATION ANALYSIS ---")
#     status = "VIABLE"
#     for hero, load in hero_load.items():
#         print(f"  Hero {hero} Max Load: {load} flows/rules")
#         if load > ZODIAC_MAX_RULES:
#             print(f"  [CRITICAL] Hero {hero} OVERSATURATED! (Needs {load} > Cap {ZODIAC_MAX_RULES})")
#             status = "COLLAPSED"
    
#     return status


#=============================================================================================================================================================

# 7. GRAPHICS

# #==============================================================================================================================================================
# def analyze_tradeoff_sequence(G, h, cand_table, valid_sets):
#     print("\n--- COLLECTING DATA FOR GRAPH A ---")
    
#     alphas = np.linspace(0, 1, 11) 
#     results_watts = []
#     results_score = []

#     for a in alphas:
#         # Solo calculamos, no imprimimos todo el log para no ensuciar
#         _, w_watts, w_score = best_green_placement(G, h, cand_table, valid_sets, alpha=a)
#         results_watts.append(w_watts)
#         results_score.append(w_score)
#     vis_utils.plot_graph_a_tradeoff(alphas, results_watts, results_score)


def plot_alpha_sensitivity(G, h, candidate_table, valid_sets, node_traffic_pps):
    """
    Genera una gráfica de sensibilidad variando Alpha.
    Etiqueta los nodos como (Z)odiac o (N)EC según su tráfico real.
    """
    print("\n--- Running Alpha Sensitivity Analysis ---")
    
    alphas = np.linspace(0.0, 1.0, 11) 
    k_values = []
    winners_history = []
    
    # Capacidad para clasificar (debe coincidir con assign_green_weights)
    ZODIAC_LIMIT = ZodiacFX.MU * 0.95 

    for alpha in alphas:
        # Ejecutamos Fase 2
        winner_set, _, _ = best_green_placement(
            G, h, candidate_table, valid_sets, alpha, node_traffic_pps
        )
        
        k = len(winner_set) if winner_set else 0
        k_values.append(k)
        
        # --- NUEVA LÓGICA DE ETIQUETADO ---
        if winner_set:
            sorted_nodes = sorted(list(winner_set))
            labeled_nodes = []
            for node in sorted_nodes:
                traf = node_traffic_pps.get(node, 0.0)
                if traf < ZODIAC_LIMIT:
                    labeled_nodes.append(f"{node}(Z)") # (Z) = Zodiac (Green)
                else:
                    labeled_nodes.append(f"{node}(N)") # (N) = NEC (Legacy)
            
            # Guardamos la lista bonita: "[1(N), 5(Z), ...]"
            winners_history.append(str(labeled_nodes).replace("'",""))
        else:
            winners_history.append("[]")

    # --- PLOTTING ---
    fig, ax = plt.subplots(figsize=(12, 7)) # Un poco más grande para que quepan las etiquetas
    
    # 1. Gráfica de Línea
    ax.step(alphas, k_values, where='mid', label='Set Size (K)', color='#2ca02c', linewidth=2)
    
    # 2. Anotaciones Inteligentes
    last_set_str = ""
    for i, alpha in enumerate(alphas):
        current_set_str = winners_history[i]
        
        # Solo anotamos si cambia la composición
        if current_set_str != last_set_str:
            # Formato de etiqueta con salto de línea si es muy larga
            label_text = f"α={alpha:.1f}\n{current_set_str}"
            
            # Ajuste dinámico de posición para que no se encimen
            offset_y = 30 + (i % 3) * 25 
            
            ax.annotate(label_text, 
                        xy=(alpha, k_values[i]), 
                        xytext=(0, offset_y), 
                        textcoords='offset points',
                        arrowprops=dict(arrowstyle="->", color='gray'),
                        bbox=dict(boxstyle="round,pad=0.3", fc="#f0f0f0", ec="black", alpha=0.9),
                        fontsize=8, ha='center') # Fuente más pequeña para que quepa
            
            last_set_str = current_set_str

    # Configuración del Eje
    ax.set_title("Sensitivity Analysis: Hero Set Composition & Hardware Roles", fontsize=14)
    ax.set_xlabel(r"Alpha ($\alpha$): 0=Delay Focused $\leftrightarrow$ 1=Energy Focused", fontsize=12)
    ax.set_ylabel("Set Size (K)", fontsize=12)
    
    # Leyenda explicativa en la gráfica
    ax.text(0.02, 0.95, "Legend:\n(Z) = Zodiac Node (Low Power)\n(N) = NEC Node (High Perf)", 
            transform=ax.transAxes, fontsize=10, bbox=dict(facecolor='white', alpha=0.8))

    ax.set_ylim(bottom=0, top=max(k_values)+2)
    ax.set_xlim(0, 1)
    ax.grid(True, linestyle='--', alpha=0.6)
    
    plt.tight_layout()
    plt.show()
    print("Sensitivity Graph Generated with Role Labels.")

def analyze_tradeoffs(G, h, candidate_table, valid_sets, node_traffic_pps):
    """
    Genera gráficas de impacto:
    1. Alpha vs. Potencia (Watts) -> Muestra el Ahorro.
    2. Alpha vs. Costo de Red (Score) -> Muestra el impacto en el rendimiento.
    """
    print("\n--- Running Trade-off Analysis (Power vs. Performance) ---")
    
    alphas = np.linspace(0.0, 1.0, 11)
    power_history = []
    score_history = []
    
    # 1. CÁLCULO DE LA LÍNEA BASE (WORST CASE - Todo NEC)
    # Asumimos que si no hiciéramos nada, todos los nodos serían NEC PF5240
    baseline_watts = 0.0
    for n in G.nodes():
        # P_BASE + (Puertos * P_PORT)
        baseline_watts += NEC_PF5240.P_BASE + (G.degree(n) * NEC_PF5240.P_PORT)
    
    baseline_list = [baseline_watts] * len(alphas)

    # 2. SIMULACIÓN
    for alpha in alphas:
        # Obtenemos los datos del ganador para este Alpha
        winner_set, winner_watts, total_score = best_green_placement(
            G, h, candidate_table, valid_sets, alpha, node_traffic_pps
        )
        
        power_history.append(winner_watts)
        score_history.append(total_score)

    # 3. GRAFICACIÓN
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10), sharex=True)
    
    # --- SUBPLOT 1: AHORRO DE ENERGÍA ---
    # Línea Roja: Lo que gasta una red tradicional
    ax1.plot(alphas, baseline_list, 'r--', label='Baseline (All-NEC Legacy)', linewidth=2, alpha=0.6)
    
    # Línea Verde: Tu solución
    ax1.plot(alphas, power_history, 'g-o', label='Green-MCS Solution', linewidth=3)
    
    # Rellenar el área de ahorro
    ax1.fill_between(alphas, power_history, baseline_list, color='green', alpha=0.1, label='Energy Savings')
    
    # Etiquetas y Estilo
    ax1.set_ylabel("Network Power Consumption (Watts)", fontsize=12)
    ax1.set_title("Energy Efficiency Analysis", fontsize=14)
    ax1.legend(loc='best')
    ax1.grid(True, linestyle=':', alpha=0.6)
    
    # Anotación del máximo ahorro (en Alpha=1.0)
    max_savings = baseline_watts - power_history[-1]
    percent_savings = (max_savings / baseline_watts) * 100
    ax1.annotate(f"Max Savings: {percent_savings:.1f}%", 
                 xy=(1.0, power_history[-1]), 
                 xytext=(0.7, power_history[-1] + (baseline_watts-power_history[-1])/2),
                 arrowprops=dict(arrowstyle="->", color='black'))

    # --- SUBPLOT 2: COSTO DE RENDIMIENTO (DELAY/RPL) ---
    # El Score representa el "costo" de mover los paquetes. Menos es mejor.
    # Si sube, significa que estamos sacrificando rutas óptimas.
    ax2.plot(alphas, score_history, 'b-s', label='Network Cost (Green RPL)', linewidth=2)
    
    ax2.set_ylabel("Routing Cost (Normalized Score)", fontsize=12)
    ax2.set_xlabel(r"Alpha ($\alpha$): 0=Performance $\leftrightarrow$ 1=Energy", fontsize=12)
    ax2.set_title("Performance Impact Analysis", fontsize=14)
    ax2.legend(loc='best')
    ax2.grid(True, linestyle=':', alpha=0.6)

    plt.tight_layout()
    plt.show()
    print(f"Trade-off Graphs Generated. Max Savings Potential: {percent_savings:.2f}%")
def analyze_three_metrics(G, h, candidate_table, valid_sets, node_traffic_pps):
    """
    Genera 3 gráficas verticales:
    1. Alpha vs. Ahorro de Energía (%)
    2. Alpha vs. Delay Puro (Score Normalizado de Latencia)
    3. Alpha vs. Función Objetivo (Score Combinado)
    """
    print("\n--- Running Multi-Metric Analysis (Savings, Delay, Score) ---")
    
    alphas = np.linspace(0.0, 1.0, 11)
    
    # Listas para guardar los ejes Y
    savings_history = []
    delay_history = []
    score_history = []
    
    # 1. BASELINE (Consumo Máximo - Todo NEC)
    baseline_watts = 0.0
    for n in G.nodes():
        baseline_watts += NEC_PF5240.P_BASE + (G.degree(n) * NEC_PF5240.P_PORT)
    
    # 2. BUCLE DE SIMULACIÓN
    for alpha in alphas:
        # A. Encontrar al Ganador con el Alpha actual
        winner_set, winner_watts, total_score = best_green_placement(
            G, h, candidate_table, valid_sets, alpha, node_traffic_pps
        )
        
        # --- METRICA 1: AHORRO (%) ---
        savings_pct = ((baseline_watts - winner_watts) / baseline_watts) * 100
        savings_history.append(savings_pct)
        
        # --- METRICA 3: SCORE (Directo) ---
        score_history.append(total_score)
        
        # --- METRICA 2: DELAY PURO (Truco Matemático) ---
        # Recalculamos el costo de este MISMO set ganador, pero como si Alpha fuera 0.0
        # Esto nos da solo la parte del Delay de la ecuación.
        assign_green_weights(G, winner_set, 0.0, node_traffic_pps) # Alpha 0 = Solo Delay
        
        pure_delay_score = 0.0
        for (u, v), affected in h.items():
            valid_heroes = [c for c in candidate_table[(u, v)] if c in winner_set]
            if not valid_heroes:
                pure_delay_score = float('inf')
                break
            # Calculamos ruta con pesos de solo delay
            best_h = min([get_path_score(G, u, v, c, affected) for c in valid_heroes])
            pure_delay_score += best_h
            
        delay_history.append(pure_delay_score)

    # 3. PLOTTING (3 Subplots)
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 12), sharex=True)
    
    # --- GRÁFICA 1: ENERGY SAVINGS ---
    ax1.plot(alphas, savings_history, 'g-o', linewidth=2.5)
    ax1.fill_between(alphas, savings_history, 0, color='green', alpha=0.1)
    ax1.set_ylabel("% Energy Savings")
    ax1.set_title("1. Energy Savings vs. Baseline (Higher is Better)", fontsize=12)
    ax1.grid(True, linestyle='--', alpha=0.6)
    
    # Anotar el máximo ahorro
    max_sav = max(savings_history)
    ax1.annotate(f"Max: {max_sav:.1f}%", xy=(1.0, max_sav), xytext=(0.8, max_sav-5),
                 arrowprops=dict(facecolor='black', arrowstyle='->'))

    # --- GRÁFICA 2: PURE DELAY ---
    ax2.plot(alphas, delay_history, 'r-s', linewidth=2.5)
    ax2.set_ylabel("Network Delay Cost (Norm)")
    ax2.set_title("2. Impact on Latency/Delay (Lower is Better)", fontsize=12)
    ax2.grid(True, linestyle='--', alpha=0.6)
    
    # --- GRÁFICA 3: OBJECTIVE SCORE ---
    ax3.plot(alphas, score_history, 'b-^', linewidth=2.5)
    ax3.set_ylabel("Objective Function (Min)")
    ax3.set_xlabel(r"Alpha ($\alpha$): 0=Performance $\leftrightarrow$ 1=Energy")
    ax3.set_title("3. Algorithm Objective Score (Optimization Goal)", fontsize=12)
    ax3.grid(True, linestyle='--', alpha=0.6)

    plt.tight_layout()
    plt.show()
    print("Multi-Metric Analysis Generated.")
if __name__ == '__main__':
    # 1. Configuración
    config = get_config()
    alpha = float(config.get('alpha', 0.5))
    
    # 2. Carga de Topología
    topo_loader = get_active_topology()
    G = topo_loader.get_graph()
    
    # 3. EXTRACCIÓN DEL "WORST CASE" (Pico Histórico)
    dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Nobel-Germany"
    #dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/Germany50"
    #dataset_folder = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/abilene"
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
        print(f"\n[RESULT] Winner Set for Peak Traffic: {list(winner_set)}")
        print(f"[RESULT] Power Consumption at Peak: {winner_watts:.2f} W")
        
        # Gráfica de sensibilidad
        #plot_alpha_sensitivity(G, h, cand_table, valid_sets, node_traffic_pps)
        #analyze_tradeoffs(G, h, cand_table, valid_sets, node_traffic_pps)
        analyze_three_metrics(G, h, cand_table, valid_sets, node_traffic_pps)
    else:
        print("\n[CRITICAL ERROR] Even with upgraded hardware, the Peak Traffic is too high.")


    