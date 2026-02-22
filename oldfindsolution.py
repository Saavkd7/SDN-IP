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



def get_network_latency_score(G, placement_set, node_traffic_pps, node_caps):
    """
    Calcula el delay promedio considerando propagación + colas M/M/1.
    Usamos una heurística rápida: Distancia al controlador más cercano + Delay de Cola de ese controlador.
    """
    total_latency = 0.0
    
    # Pre-calcular distancias desde todos los nodos a los controladores del set
    for n in G.nodes():
        # 1. Encontrar controlador más cercano (Latencia de Propagación)
        # (En la realidad MCS hace esto via Shortest Path)
        min_prop_delay = float('inf')
        nearest_ctrl = None
        
        for ctrl in placement_set:
            try:
                # Usamos el peso 'weight' que ya tiene latencia en ms
                dist = nx.shortest_path_length(G, source=n, target=ctrl, weight='weight')
                if dist < min_prop_delay:
                    min_prop_delay = dist
                    nearest_ctrl = ctrl
            except:
                pass
        
        if nearest_ctrl is None: continue # Nodo desconectado (raro)

        # 2. Calcular Delay de Cola en el Controlador (M/M/1)
        # Asumimos que el tráfico de este nodo va a ese controlador
        # Nota: Para optimización rápida, usamos la carga del propio controlador como proxy de congestión
        lam = node_traffic_pps.get(nearest_ctrl, 0) 
        mu = node_caps.get(nearest_ctrl, NEC_PF5240.MU)
        
        # Fórmula de Colas
        if lam >= mu * 0.99:
            queue_delay = 1000.0 # Castigo: 1 segundo
        else:
            queue_delay = (1.0 / (mu - lam)) * 1000.0 # ms
            
        total_latency += (min_prop_delay + queue_delay)

    return total_latency / len(G.nodes())
    
    return None
