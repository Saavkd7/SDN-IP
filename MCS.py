import networkx as nx
import matplotlib.pyplot as plt
from collections import defaultdict
import itertools
def create_topology():
    nodes_ids=list(range(1,11))
    E1=(nodes_ids[0],nodes_ids[1])
    E2=(nodes_ids[9],nodes_ids[0])
    E3=(nodes_ids[1],nodes_ids[9])
    E4=(nodes_ids[2],nodes_ids[1])
    E5=(nodes_ids[9],nodes_ids[8])
    E6=(nodes_ids[8],nodes_ids[3])
    E7=(nodes_ids[2],nodes_ids[3])
    E8=(nodes_ids[8],nodes_ids[7])
    E9=(nodes_ids[7],nodes_ids[4])
    E10=(nodes_ids[3],nodes_ids[4])
    E11=(nodes_ids[4],nodes_ids[5])
    E12=(nodes_ids[7],nodes_ids[6])
    E13=(nodes_ids[6],nodes_ids[5])
    G=nx.Graph()
    G.add_nodes_from(nodes_ids)
    G.add_edges_from([E1,E2,E3,E4,E5,E6,E7,E8,E9,E10,E11,E12,E13])
    return G

def plot_network():
    G=create_topology()
    pos = {
    1: (0, 1), 2: (0, 0.5), 3: (0.5, 0.5), 4: (1, 0.5), 
    5: (1.5, 0.5), 6: (2, 0.5), 7: (2, 1), 8: (1.5, 1), 
    9: (1, 1), 10: (0.5, 1)
    }
    nx.draw(G,pos=pos,with_labels=True,width=2,node_size=600)
    plt.xlim(-0.2, 2.2) 
    plt.ylim(-0.2, 1.2) 
    plt.show()
    print(G)

    print("Nodes:", G.nodes())
    print("Edges:", G.edges())

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


G=create_topology()
h=failure_dict(G)
candidate_table=candidates(G,G.nodes(),h)
y=find_minimum_set(candidate_table,G.nodes())
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
print(f"The best candidate set are {best_set}")

