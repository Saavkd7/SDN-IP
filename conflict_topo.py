import networkx as nx

class ConflictTopo :
    def __init__(self):
        self.build()

    def build(self):
        # 16 Nodes Total
        # Node 1 is the "Fast Center" (Degree 3)
        # Node 6 is the "Green Edge" (Degree 12!)
        self.city_names = ['CENTER', 'LEFT_A', 'LEFT_B', 
                           'BRIDGE_A', 'BRIDGE_B', 
                           'GREEN_HUB', 'G1', 'G2', 'G3', 'G4', 'G5', 
                           'G6', 'G7', 'G8', 'G9', 'G10']
        
        self.citiesID = {name: i for i, name in enumerate(self.city_names, start=1)}
        
        bw = 1000
        delay = '1ms'

        self.links = [
            # 1. LEFT RING (The "Busy" City)
            # Node 1 (CENTER) is here. Low RPL for these nodes.
            ('CENTER', 'LEFT_A', bw, delay),
            ('LEFT_A', 'LEFT_B', bw, delay),
            ('LEFT_B', 'CENTER', bw, delay),

            # 2. THE LONG BRIDGE (Adds Latency)
            # Connecting Left Ring to Right Ring
            ('CENTER', 'BRIDGE_A', bw, delay),
            ('BRIDGE_A', 'BRIDGE_B', bw, delay),
            ('BRIDGE_B', 'GREEN_HUB', bw, delay),

            # 3. THE GREEN TRAP (Right Ring)
            # Node 6 (GREEN_HUB) is here.
            ('GREEN_HUB', 'BRIDGE_A', bw, delay), # Completes a loop for redundancy
            
            # 4. THE ENERGY PUMP (Ghost Nodes)
            # We attach 10 "Ghosts" to GREEN_HUB.
            # It makes Node 6 "Heavy" (Degree 12+).
            # Replacing Node 6 saves ~3.7 Watts (Huge!)
            ('GREEN_HUB', 'G1', bw, delay), ('GREEN_HUB', 'G2', bw, delay),
            ('GREEN_HUB', 'G3', bw, delay), ('GREEN_HUB', 'G4', bw, delay),
            ('GREEN_HUB', 'G5', bw, delay), ('GREEN_HUB', 'G6', bw, delay),
            ('GREEN_HUB', 'G7', bw, delay), ('GREEN_HUB', 'G8', bw, delay),
            ('GREEN_HUB', 'G9', bw, delay), ('GREEN_HUB', 'G10', bw, delay),

            # 5. GHOST REDUNDANCY (Prevent Crashes)
            # Connect ghosts in a ring so they aren't isolated failures
            ('G1', 'G2', bw, delay), ('G2', 'G3', bw, delay),
            ('G3', 'G4', bw, delay), ('G4', 'G5', bw, delay),
            ('G5', 'G6', bw, delay), ('G6', 'G7', bw, delay),
            ('G7', 'G8', bw, delay), ('G8', 'G9', bw, delay),
            ('G9', 'G10', bw, delay), ('G10', 'GREEN_HUB', bw, delay)
        ]

    def get_graph(self):
        G = nx.Graph()
        G.add_nodes_from(self.citiesID.values())
        for u, v, bw, d in self.links:
            U = self.citiesID[u]
            V = self.citiesID[v]
            G.add_edge(U, V)
        return G
