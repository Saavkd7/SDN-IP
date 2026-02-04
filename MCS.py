import networkx as nx
import itertools
# Asegúrate de que green_models tenga las clases actualizadas (LegacyRouter, SDNSwitch)
# que definimos en la respuesta anterior (donde solo devuelven P_BASE).
import os
import json
from green_models import NEC_PF5240 , ZodiacFX
import matplotlib.pyplot as plt 
import numpy as np
import vis_utils 
from sndlib_loader import SNDLibXMLParser 
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
       
def assign_green_weights(G, candidate_set, alpha):
    """
    LOGICA SIMPLIFICADA:
    - Si el nodo es Héroe (está en candidate_set) -> Usamos perfil Zodiac.
    - Si el nodo NO es Héroe -> Usamos perfil NEC.
    - P_TOTAL = P_BASE + (Degree * P_PORT)
    """
    
    # 1. NORMALIZACIÓN (El peor caso siempre es un NEC lleno)
    degrees = [d for n, d in G.degree()]
    max_degree = max(degrees) if degrees else 48
    # Usamos el método estático o calculamos directo: Base NEC + (MaxPorts * PortNEC)
    MAX_POSSIBLE_WATTS = NEC_PF5240.P_BASE + (max_degree * NEC_PF5240.P_PORT)
    
    # Normalización de Delay
    delays = [d.get('weight', 1.0) for u, v, d in G.edges(data=True)]
    MAX_DELAY = max(delays) if delays else 1.0
    
    # 2. ASIGNACIÓN DE PESOS
    for u, v in G.edges():
        
        # --- A. DETERMINAR HARDWARE (SET MEMBERSHIP) ---
        if v in candidate_set:
            # ¡Es un Héroe! -> ZODIAC
            p_base = ZodiacFX.P_BASE
            p_port = ZodiacFX.P_PORT
        else:
            # Tráfico normal / Legacy -> NEC
            p_base = NEC_PF5240.P_BASE
            p_port = NEC_PF5240.P_PORT

        # --- B. CALCULAR PHYSICS (Ecuación 11) ---
        # Obtenemos cuántos cables tiene conectados realmente este nodo 'v'
        active_ports = G.degree(v)
        
        # P_config = PuertosActivos * ConsumoPorPuerto
        p_config = active_ports * p_port
        
        # Watts Totales
        total_node_watts = p_base + p_config
        
        # --- C. SCORE FINAL ---
        norm_energy = total_node_watts / MAX_POSSIBLE_WATTS
        
        raw_latency = G[u][v].get('weight', 1.0)
        norm_delay = raw_latency / MAX_DELAY
        
        score = (alpha * norm_energy) + ((1 - alpha) * norm_delay)
        
        G[u][v]['score_cost'] = score
        if not G.is_directed():
            G[v][u]['score_cost'] = score   
def get_path_score(G, u, v, c, affected):
    """
    Calcula el Green RPL:
    1. Túnel: Costo de ir de Fuente (u) -> Candidato (c).
    2. Reparación: Promedio del costo de ir de Candidato (c) -> Destinos (d).
    
    Usa el peso 'score_cost' que ya incluye (Alpha * Energía) + ((1-Alpha) * Delay).
    """
    # 0. Crear grafo temporal sin el enlace fallido (u,v)
    G_temp = G.copy()
    if G_temp.has_edge(u, v): 
        G_temp.remove_edge(u, v)

    # --- PARTE A: EL TÚNEL (Source -> Candidate) ---
    tunnel_cost = 0.0
    if u != c:
        try:
            # Calculamos el camino más barato en términos de 'score_cost'
            tunnel_cost = nx.shortest_path_length(G_temp, source=u, target=c, weight='score_cost')
        except nx.NetworkXNoPath:
            return float('inf') # Si no puede llegar al héroe, es inválido.

    # --- PARTE B: LA REPARACIÓN (Candidate -> Destinations Average) ---
    # ESTO ES LO QUE FALTABA
    if not affected:
        return tunnel_cost

    total_repair_cost = 0.0
    reachable_destinations = 0

    for dest in affected:
        try:
            # Costo desde el Héroe hasta cada destino afectado
            dist = nx.shortest_path_length(G_temp, source=c, target=dest, weight='score_cost')
            total_repair_cost += dist
            reachable_destinations += 1
        except nx.NetworkXNoPath:
            # Si un destino no es alcanzable, penalizamos fuertemente
            return float('inf')

    # Calcular el promedio
    avg_repair_cost = total_repair_cost / reachable_destinations if reachable_destinations > 0 else 0

    # --- RESULTADO FINAL (RPL Green) ---
    # Suma del esfuerzo del túnel + el esfuerzo promedio de entrega
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

def find_minimum_set(candidate_table, all_nodes, max_k=9):
    # Heurística simple para Set Cover
    num_failures = len(candidate_table)
    node_coverage = {node: set() for node in all_nodes}
    
    # Pre-procesamiento: Qué fallas cubre cada nodo individualmente
    for failure_id, (_, valid_heroes) in enumerate(candidate_table.items()):
        for hero in valid_heroes:
            node_coverage[hero].add(failure_id)

    print(f"Searching for optimal sets (Max size checked: {max_k})...")
    
    # Buscamos el tamaño k más pequeño posible
    for k in range(1, len(all_nodes) + 1):
        if k > max_k: 
            return None
        
        found_solutions_at_k = [] # <--- Acumulador de soluciones
        
        # Probamos TODAS las combinaciones de este tamaño k
        for candidate_set in itertools.combinations(all_nodes, k):
            total_coverage = set().union(*[node_coverage[node] for node in candidate_set])
            
            if len(total_coverage) == num_failures:
                found_solutions_at_k.append(candidate_set)
        
        # Si encontramos al menos una solución de tamaño k, DEVOLVEMOS TODAS
        # para que la Fase 2 decida cuál es la mejor "Green".
        if found_solutions_at_k:
            print(f"Found {len(found_solutions_at_k)} valid sets of size {k}!")
            return found_solutions_at_k

    return None
# ==============================================================================
# 3. BEST GREEN PLACEMENT (PHYSICS AWARE)
# ==============================================================================
def best_green_placement(G, h, candidate_table, valid_sets, alpha=None):
    best_score = float('inf')
    best_config = None
    best_watts = 0.0 # <--- NUEVO: Variable para guardar los Watts del GANADOR

    # 1. Preparar conteo de reglas (Global para la red)
    # Cada destino afectado por cada falla requiere una regla en el Héroe.
    total_network_rules = sum(len(affected) for affected in h.values())
    print(f"MAX NUMER OF RULES: {total_network_rules}" )
    print(f"\n--- EVALUATING {len(valid_sets)} VALID SETS (Alpha={alpha}) ---")

    for candidate_set in valid_sets:
        # A. ACTUALIZAR PESOS (Pintamos el grafo con la configuración actual)
        # Esto pone barato a los Zodiac (Set) y caro a los NEC (Resto)
        assign_green_weights(G, candidate_set, alpha)
        
        # B. CALCULO DE POTENCIA ESTRUCTURAL (Base + Puertos Activos)
        structural_watts = 0.0
        for n in G.nodes():
            degree = G.degree(n)
            if n in candidate_set:
                # El nodo es un Héroe (Zodiac)
                p_node = ZodiacFX.P_BASE + (degree * ZodiacFX.P_PORT)
            else:
                # El nodo es Tráfico Normal (NEC)
                p_node = NEC_PF5240.P_BASE + (degree * NEC_PF5240.P_PORT)
            structural_watts += p_node

        # C. CALCULO DE POTENCIA DE CONTROL (Reglas + PacketIn)
        # Asumimos que TODAS las reglas de rescate van a los Héroes (Zodiac).
        # Costo Unitario = Costo de escribir regla + Costo de procesar paquete control
        unit_control_cost = ZodiacFX.E_FLOW_MOD + ZodiacFX.E_PACKET_IN
        control_watts = total_network_rules * unit_control_cost
        
        # Potencia Total (Physics)
        total_watts = structural_watts + control_watts
        # D. CALCULO DE DELAY (Métrica de Rutas)
        total_path_metric = 0.0
        for (u, v), affected in h.items():
            if not affected: continue
            
            # Buscamos cual de los héroes de este set sirve para esta falla
            # (Usamos la candidate_table para filtrar)
            valid_heroes_for_failure = [hero for hero in candidate_set if hero in candidate_table[(u,v)]]
            
            if valid_heroes_for_failure:
                # Elige el héroe que tenga el menor costo (Score Cost ya tiene Alpha integrado)
                best_fail_score = min([get_path_score(G, u, v, hero, affected) for hero in valid_heroes_for_failure])
                total_path_metric += best_fail_score
            else:
                total_path_metric += 1000.0 # Penalización (Safety)

        # E. SCORE FINAL
        # Nota: total_path_metric ya es una suma de 'score_cost' que incluye (Alpha*Energy + (1-Alpha)*Delay)
        # por lo que es la métrica directa de comparación.
        final_score = total_path_metric
        # CÁLCULO DEL PROMEDIO
        num_failures_active = sum(1 for affected in h.values() if affected)
        avg_cost = final_score / num_failures_active if num_failures_active > 0 else 0
        
        print(f"  -> Avg Cost per Failure: {avg_cost:.2f} (Total: {final_score:.2f} / Failures: {num_failures_active})")

        print(f"Set {candidate_set} | Struct: {structural_watts:.1f}W | Ctrl: {control_watts:.4f}W | TOTAL: {total_watts:.2f}W | Score: {final_score:.4f}")

        if final_score < best_score:
            best_score = final_score
            best_config = candidate_set
            best_watts = total_watts # <--- CAPTURA: Guardamos los watts de ESTE ganador
    return best_config, best_watts, best_score
    
# ==============================================================================
# 4. CONTRIBUTION
# ==============================================================================
def contribution(G, winner_set, total_watts_winner):
    # 1. BASELINE: ¿Cuánto gastaría esta configuración si usáramos solo NECs (Lo estándar)?
    # Recalculamos asumiendo que TODOS los nodos del set ganador son NEC_PF5240
    baseline_watts = 0.0
    for n in G.nodes():
        degree = G.degree(n)
        # En el Baseline, NO discriminamos, asumimos hardware potente/caro en el core
        # O si prefieres, compara contra el winner_set siendo NECs:
        if n in winner_set:
            # Si hubiéramos puesto un NEC aquí en lugar de un Zodiac
            p_node = NEC_PF5240.P_BASE + (degree * NEC_PF5240.P_PORT)
        else:
            # El resto sigue siendo NEC
            p_node = NEC_PF5240.P_BASE + (degree * NEC_PF5240.P_PORT)
        baseline_watts += p_node

    # # 2. CÁLCULO DEL APORTE (GAP)
    # energy_saved = baseline_watts - total_watts_winner
    # percentage_saved = (energy_saved / baseline_watts) * 100

    baseline_watts = 0.0
    for n in G.nodes():
        degree = G.degree(n)
        # Asumiendo baseline puro NEC
        p_node = NEC_PF5240.P_BASE + (degree * NEC_PF5240.P_PORT)
        baseline_watts += p_node

    # ... (Tus prints de reporte siguen igual) ...

    # LLAMADA LIMPIA A LA GRÁFICA B
    print("[GRAPHIC] Generating Graph B (Savings)...")
    vis_utils.plot_graph_b_savings(baseline_watts, total_watts_winner)
    # print(f"\n=== SCIENTIFIC CONTRIBUTION REPORT ===")
    # print(f"Standard Approach (All-NEC): {baseline_watts:.2f} W")
    # print(f"Green MCS Approach (Hybrid): {total_watts_winner:.2f} W")
    # print(f"--------------------------------------")
    # print(f"NET ENERGY SAVING: {energy_saved:.2f} W")
    # print(f"EFFICIENCY GAIN:   {percentage_saved:.1f} %")
    # print(f"======================================\n")
    
# ==============================================================================
# 5. Recovery PATH
# ==============================================================================

def recovery_path(alpha=None):
    topo = get_active_topology()
    G = topo.get_graph()
    
    if alpha is None:
        config = get_config()
        alpha = float(config.get('alpha', 0.5))
    
    print(f"Running MCS with Alpha: {alpha}")
    
    h = failure_dict(G)
    cand_table = candidates(G, G.nodes(), h)
    
    # Fase 1: Encontrar Sets Válidos (Matemática - Set Cover)
    valid_sets = find_minimum_set(cand_table, G.nodes())
    
    if not valid_sets:
        print("No solution found.")
        return None, None

    # Fase 2: Elegir el MEJOR Set basado en Energía/Delay (Física)
    winner_set, _ , _ = best_green_placement(G, h, cand_table, valid_sets, alpha)
    print(f"[MCS BRIDGE] Selected Winner for Alpha={alpha}: {winner_set}")
    # Fase 3: Construir el Diccionario Failover (Tu lógica original)
    # Asignamos el mejor héroe DENTRO del winner_set para cada falla
    failover = {}
    
    # Importante: Aseguramos que el grafo tenga los pesos del ganador para el cálculo final
    assign_green_weights(G, winner_set, alpha)
    for (u, v), affected in h.items():
        if not affected: continue # Si no hay destinos afectados, no hay regla
        
        best_failure = float('inf')
        f = None # El héroe seleccionado
        
        # Solo miramos candidatos que estén DENTRO del set ganador
        for p in winner_set:
            if p in cand_table[(u, v)]:
                # Calculamos el costo (RPL/Score) usando la función actual
                # Nota: get_path_score es el equivalente a tu 'rpl_fail' antiguo
                ar = get_path_score(G, u, v, p, affected)
                
                if ar < best_failure:
                    best_failure = ar
                    f = p
        
        if f is not None:
            failover[(u, v)] = f
        else:
            print(f"WARNING: Winner set {winner_set} cannot cover failure {(u,v)} logically.")

    print(f"[FAILOVER MAP]: Generated {len(failover)} assignments.")

    return winner_set, failover, G
#============================================================================================================================================================

# 6. SATURACION RULES 

#============================================================================================================================================================
def check_saturation(G, h, winner_set, failover_map):
    # Capacidad Hipotética de un Zodiac (Green) vs NEC (Standard)
    ZODIAC_MAX_RULES = 20  # Poca memoria
    NEC_MAX_RULES = 10000   # Mucha memoria

    # Contamos cuántas reglas le tocan a cada Héroe en este escenario
    hero_load = {hero: 0 for hero in winner_set}
    
    for (u, v), assigned_hero in failover_map.items():
        # Cuantos destinos se ven afectados por esta falla específica
        num_reglas = len(h[(u, v)]) 
        if assigned_hero in hero_load:
            # Ese héroe debe cargar con todas estas reglas si ese enlace falla
            # OJO: En el peor caso (Worst Case Scenario), el héroe debe tener espacio 
            # para la falla más grande que le toque cubrir, NO la suma de todas (porque no fallan todas a la vez).
            # PERO, para simplificar "Reserva de Recursos", a veces se suma. 
            # Vamos a usar el criterio: "Max Single Failure Load" (El pico de carga)
            hero_load[assigned_hero] = max(hero_load[assigned_hero], num_reglas)

    print("\n--- SATURATION ANALYSIS ---")
    status = "VIABLE"
    for hero, load in hero_load.items():
        print(f"  Hero {hero} Max Load: {load} flows/rules")
        if load > ZODIAC_MAX_RULES:
            print(f"  [CRITICAL] Hero {hero} OVERSATURATED! (Needs {load} > Cap {ZODIAC_MAX_RULES})")
            status = "COLLAPSED"
    
    return status


#=============================================================================================================================================================

# 7. GRAPHICS

#==============================================================================================================================================================
def analyze_tradeoff_sequence(G, h, cand_table, valid_sets):
    print("\n--- COLLECTING DATA FOR GRAPH A ---")
    
    alphas = np.linspace(0, 1, 11) 
    results_watts = []
    results_score = []

    for a in alphas:
        # Solo calculamos, no imprimimos todo el log para no ensuciar
        _, w_watts, w_score = best_green_placement(G, h, cand_table, valid_sets, alpha=a)
        results_watts.append(w_watts)
        results_score.append(w_score)
    vis_utils.plot_graph_a_tradeoff(alphas, results_watts, results_score)





if __name__ == '__main__':
    alpha=None
    winner_set, failover, G=recovery_path()
    if alpha is None:
        config = get_config()
        alpha = float(config.get('alpha', 0.5))
    
    print(f"Running MCS with Alpha: {alpha}")
    
    h = failure_dict(G)
    cand_table = candidates(G, G.nodes(), h)
    valid_sets = find_minimum_set(cand_table, G.nodes())
    winner_set, winner_watts, _ = best_green_placement(G, h, cand_table, valid_sets, alpha)
    analyze_tradeoff_sequence(G, h, cand_table, valid_sets)
    check_saturation(G, h, winner_set, failover)
    contribution(G, winner_set, winner_watts)

