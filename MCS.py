import networkx as nx
import matplotlib.pyplot as plt
from collections import defaultdict
import itertools
from abilene_topo import Abilene

# def plot_network(G):
#     pos = {
#     1: (0, 1), 2: (0, 0.5), 3: (0.5, 0.5), 4: (1, 0.5), 
#     5: (1.5, 0.5), 6: (2, 0.5), 7: (2, 1), 8: (1.5, 1), 
#     9: (1, 1), 10: (0.5, 1) 11:
#     }
#     nx.draw(G,pos=pos,with_labels=True,width=2,node_size=600)
#     plt.xlim(-0.2, 2.2) 
#     plt.ylim(-0.2, 1.2) 
#     plt.show()
#     print(G)

#     print("Nodes:", G.nodes())
#     print("Edges:", G.edges())

def affected_destinations(G,i,j):
    affected=set()
    for d in G.nodes():
        failure=0
        #if d==i: continue
        paths=list(nx.all_shortest_paths(G, source=i, target=d))
        for path in paths:
            if j in path and path.index(j)== path.index(i)+1:
                failure +=1
        if failure== len(paths):
            affected.add(d)
    return affected

def failure_dict(G):
    failures={}
    for (a,b) in G.edges():
        failures[(a,b)]=affected_destinations(G,a,b)
        failures[(b,a)]=affected_destinations(G,b,a)
    return failures

def candidates(G,a,h): # a variable a are the nodes h is the failure_dict
    candidate_table={}
    for (u,v), affected in h.items():
        valid_candidates=[]
        for c in a:
            reaching=False
            pathuc=list(nx.all_shortest_paths(G, source=u, target=c))
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
                        pathFR=list(nx.all_shortest_paths(G, source=b, target=d))
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

def rpl_avg(G,u,v,c,affected):
    ho=0
    if u !=c:
        tnx=list(nx.all_shortest_paths(G,source=u,target=c))
        for pa in tnx:
            if u in pa and v in pa:
                idx_u = pa.index(u)
                idx_v = pa.index(v)
                if idx_v == idx_u + 1 or idx_u == idx_v + 1:
                    continue
            ho =(len(pa)-1)
            break
    total=0
    for d in affected:
        tnx1=list(nx.all_shortest_paths(G,source=c,target=d))
        neigsfe=False
        for pat in tnx1:
            if u in pat and v in pat:
                idx_u = pat.index(u)
                idx_v = pat.index(v)
                if idx_v == idx_u + 1 or idx_u == idx_v + 1:
                    continue
            neigsfe=True
            total+=(len(pat)-1)
            break
    if len(affected)>0:
        avg=total/len(affected)
    else:
        avg=0
        ho=0
    return ho+avg

def find_minimum_set(candidate_table, all_nodes):
    all_failures = list(candidate_table.keys())
    num_failures = len(all_failures)
    
    # Try sizes k = 1, 2, 3...
    for k in range(1, len(all_nodes) + 1):
        print(f"Checking candidate sets of size {k}...")
        
        # Generate all combinations of size k
        # e.g., (1,2), (1,3)...
        combinations = itertools.combinations(all_nodes, k)
        
        valid_sets = []
        
        for candidate_set in combinations:
            # Check if this specific set covers ALL failures
            covered_count = 0
            
            for failure in all_failures:
                # Get the valid candidates for this specific failure
                valid_options = candidate_table[failure]
                
                # Intersection: Is any node from our 'candidate_set' inside 'valid_options'?
                # If yes, this failure is covered.
                if set(candidate_set).intersection(valid_options):
                    covered_count += 1
            
            # Did we cover 100% of failures?
            if covered_count == num_failures:
                valid_sets.append(candidate_set)
        
        # If we found any valid sets of size k, we are done! 
        # (Since we started small, these are guaranteed to be the minimum size)
        if valid_sets:
            print(f"Found {len(valid_sets)} optimal sets of size {k}!")
            return valid_sets

    return None

def rpl_fail(G, u, v, c, affected):
    # 1. Create a temporary graph without the failed link
    G_temp = G.copy()
    if G_temp.has_edge(u, v):
        G_temp.remove_edge(u, v)
    
    # 2. Calculate tunnel distance (u -> c) using the temp graph
    try:
        if u != c:
            # We just need the length, not all paths!
            ho = nx.shortest_path_length(G_temp, source=u, target=c)
        else:
            ho = 0
            
        # 3. Calculate average repair distance (c -> affected)
        if not affected:
            return 0
            
        total = 0
        for d in affected:
            # Calculate path length on the map with the broken link
            dist = nx.shortest_path_length(G_temp, source=c, target=d)
            total += dist
            
        avg = total / len(affected)
        return ho + avg
        
    except nx.NetworkXNoPath:
        # If no path exists, this candidate is actually invalid!
        return float('inf')
def best_candidate(G,h,candidate_table,y):
    min_arpl=float('inf')
    best_set=None
    for t in y:
        current_set=0
        for (u,v), affected in h.items():
            valid_heroes = [node for node in t if node in candidate_table[(u,v)]]       
            best_failure=float('inf')
            for p in valid_heroes:
                ar=rpl_avg(G,u,v,p,affected)
                if ar< best_failure:
                    best_failure=ar
            current_set+= best_failure
        avg=current_set/len(h)
        print(f"Set{t}--> ARPL: {avg}")
        if avg<min_arpl:
            min_arpl=avg
            best_set = t
    return best_set

def recovery_path(u,v,affected,o,candidate_table):
    best_failure=float('inf')
    for p in o:
            if p in candidate_table[(u,v)]:
                ar=rpl_fail(G,u,v,p,affected)
                if ar<best_failure:
                    best_failure=ar
                    f=p
                else:
                    continue
    print(f"Links: {(u,v)} the best is candidate is {f} --> ARPL {best_failure}")
    
    return best_failure 

def get_best_set():
    topology=Abilene()
    G=topology.get_graph()
    h=failure_dict(G)
    candidate_table=candidates(G,G.nodes(),h)
    y=find_minimum_set(candidate_table,G.nodes())
    o=best_candidate(G,h,candidate_table,y)
    return o
    
    

if __name__== '__main__':
    print(get_best_set())