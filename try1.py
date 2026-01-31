import networkx as nx
import itertools
from abilene_topo import Abilene
from green_models import LegacyRouter, SDNSwitch

# ==============================================================================
# 1. HELPER FUNCTIONS (Candidate Selection)
# ==============================================================================

def affected_destinations(G, i, j):
    affected = set()
    for d in G.nodes():
        failure = 0
        paths = list(nx.all_shortest_paths(G, source=i, target=d))
        for path in paths:
            if j in path and path.index(j) == path.index(i) + 1:
                failure += 1
        if failure == len(paths):
            affected.add(d)
    return affected

def failure_dict(G):
    failures = {}
    for (a, b) in G.edges():
        failures[(a, b)] = affected_destinations(G, a, b)
        failures[(b, a)] = affected_destinations(G, b, a)
    return failures

def candidates(G, all_nodes, h): 
    candidate_table = {}
    for (u, v), affected in h.items():
        valid_candidates = []
        for c in all_nodes:
            if c == u: continue
            reaching = False
            try:
                # Basic connectivity check
                if nx.has_path(G, u, c):
                     valid_candidates.append(c)
            except:
                pass
        candidate_table[(u, v)] = valid_candidates
    return candidate_table

def rpl_avg(G, u, v, c, affected):
    """Calculates Average Repair Path Length (Delay Metric)"""
    ho = 0
    if u != c:
        try:
            # We use standard shortest path for delay calculation
            # (Weighted Dijkstra is removed to focus on Agility Cost)
            paths = list(nx.all_shortest_paths(G, source=u, target=c))
            for pa in paths:
                # Simple check to avoid failed link
                if not (u in pa and v in pa and pa.index(v) == pa.index(u)+1):
                     ho = len(pa) - 1
                     break
        except nx.NetworkXNoPath:
            return float('inf')

    total = 0
    if not affected: return ho

    for d in affected:
        try:
            dist = nx.shortest_path_length(G, source=c, target=d)
            total += dist
        except nx.NetworkXNoPath:
            total += 100 

    avg = total / len(affected)
    return ho + avg

def find_minimum_set(candidate_table, all_nodes):
    all_failures = list(candidate_table.keys())
    num_failures = len(all_failures)
    for k in range(1, len(all_nodes) + 1):
        combinations = itertools.combinations(all_nodes, k)
        valid_sets = []
        for candidate_set in combinations:
            covered_count = 0
            for failure in all_failures:
                valid_options = candidate_table[failure]
                if set(candidate_set).intersection(valid_options):
                    covered_count += 1
            if covered_count == num_failures:
                valid_sets.append(candidate_set)
        if valid_sets:
            print(f"Found {len(valid_sets)} optimal sets of size {k}!")
            return valid_sets
    return None

# ==============================================================================
# 2. GREEN LOGIC (P_Base + P_Config + P_Control)
# ==============================================================================

def get_structural_energy(G, candidate_set):
    """Calculates P_Base + P_Config (Static Power)"""
    total_watts = 0.0
    for node_id in G.nodes():
        num_ports = G.degree[node_id]
        if node_id in candidate_set:
            # Zodiac: Low Static Power
            watts = SDNSwitch.P_BASE + (num_ports * SDNSwitch.P_PORT)
        else:
            # Legacy: High Static Power
            watts = LegacyRouter.P_BASE + (num_ports * LegacyRouter.P_PORT)
        total_watts += watts
    return total_watts

def best_green_placement(G, h, candidate_table, valid_sets, alpha=0.5):
    """
    FINAL ALGORITHM:
    Minimizes: Alpha * (Static_Watts + Agility_Joules) + (1-Alpha) * Delay
    """
    best_score = float('inf')
    best_config = None
    
    # --- PRECISE ENERGY CONSTANTS (Agility Cost) ---
    # Cost per rule/destination to fix a failure
    COST_PER_DEST_ZODIAC = 0.00223  # High "Tax" for SDN (1.45J FlowMod + PacketIn)
    COST_PER_DEST_LEGACY = 0.00005  # Low "Tax" for Legacy (Internal CPU)

    # Normalization factors
    MAX_ENERGY = len(G.nodes()) * 125.0 
    MAX_DELAY = 10.0 

    print(f"\n--- SKEPTICAL SELECTION (Alpha={alpha}) ---")
    
    for candidate_set in valid_sets:
        # 1. STATIC POWER (P_Base + P_Config)
        static_watts = get_structural_energy(G, candidate_set)
        
        # 2. DYNAMIC CONTROL POWER (P_Control Prediction)
        total_agility_cost = 0.0
        total_rpl = 0
        
        for (u, v), affected in h.items():
            # How many rules are needed? (One per affected destination)
            num_destinations = len(affected)
            
            # Find the best hero in this set for this failure
            valid_heroes = [node for node in candidate_set if node in candidate_table[(u,v)]]
            
            best_rpl = float('inf')
            chosen_hero = None
            
            # Pick Hero based on shortest path (Delay)
            for hero in valid_heroes:
                rpl = rpl_avg(G, u, v, hero, affected)
                if rpl < best_rpl:
                    best_rpl = rpl
                    chosen_hero = hero
            
            total_rpl += best_rpl
            
            # CALCULATE CONTROL PENALTY
            if chosen_hero in candidate_set:
                # Hero is SDN: We pay the "Agility Tax"
                total_agility_cost += (num_destinations * COST_PER_DEST_ZODIAC)
            else:
                # Hero is Legacy: Tax is negligible
                total_agility_cost += (num_destinations * COST_PER_DEST_LEGACY)
                
        # 3. FINAL SCORING
        # We combine Watts (Static) + Joules (Dynamic) into one "Energy Impact" metric
        total_energy_impact = static_watts + total_agility_cost
        
        avg_rpl = total_rpl / len(h)
        norm_energy = total_energy_impact / MAX_ENERGY
        norm_delay = avg_rpl / MAX_DELAY
        
        score = (alpha * norm_energy) + ((1 - alpha) * norm_delay)
        
        print(f"Set {candidate_set} | Static: {static_watts:.0f}W | P_Control: {total_agility_cost:.4f}J | Score: {score:.4f}")

        if score < best_score:
            best_score = score
            best_config = candidate_set

    return best_config

# ==============================================================================
# 3. EXECUTION
# ==============================================================================

if __name__ == '__main__':
    topo = Abilene()
    G = topo.get_graph()
    
    print("Calculating Candidates...")
    h = failure_dict(G)
    cand_table = candidates(G, G.nodes(), h)
    valid_sets = find_minimum_set(cand_table, G.nodes())
    
    # Run with Alpha=0.5 (Balanced)
    winner = best_green_placement(G, h, cand_table, valid_sets, alpha=0.5)
    print(f"\n*** FINAL WINNER: {winner} ***")
