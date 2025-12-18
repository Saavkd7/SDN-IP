import networkx as nx   
class Abilene:
    def __init__(self):
        self.build()
    def build(self):
        self.city_names = ['ATLA', 'CHIN', 'DNVR', 'HSTN', 'IPLS', 
                      'KSCY', 'LOSA', 'NYCM', 'SNVA', 'STTL', 'WASH']
        self.citiesID={name: i for i,name in enumerate(self.city_names,start=1)}
        oc192=995
        oc48=249
        self.links= [
            # Link format: (Node A, Node B, Bandwidth (Mbps), Delay string)
            
            # --- THE CORE RING (OC-192) ---
            ('NYCM', 'WASH', oc192, '1.64ms'), # Short distance, high speed
            ('NYCM', 'CHIN', oc192, '5.73ms'),
            ('WASH', 'ATLA', oc192, '4.37ms'),
            ('ATLA', 'HSTN', oc192, '5.67ms'),
            ('HSTN', 'LOSA', oc192, '11.03ms'), # Long haul TX to CA
            ('LOSA', 'SNVA', oc192, '2.50ms'),
            ('SNVA', 'STTL', oc192, '5.69ms'),
            ('STTL', 'DNVR', oc192, '8.22ms'),
            ('DNVR', 'KSCY', oc192, '3.71ms'),
            ('KSCY', 'IPLS', oc192, '4.52ms'),
            ('IPLS', 'CHIN', oc192, '1.30ms'),
            
            # --- CROSS-CONNECTIONS & SUB-CORE (Mix of OC-192 and OC-48) ---
            
            # The "bottleneck" link in 2003/2004
            ('ATLA', 'IPLS', oc48,  '2.95ms'), 
            
            # Express links (usually upgraded early to offload the ring)
            ('HSTN', 'KSCY', oc192, '5.13ms'), 
            ('DNVR', 'SNVA', oc192, '7.57ms')
        ]

    def get_graph(self):
        G=nx.Graph()
        G.add_nodes_from(self.citiesID.values())
        for u, v, bw , delay in self.links:
            U=self.citiesID[u]
            V=self.citiesID[v]
            G.add_edge(U,V) #Weigh=delay to add later as paramether or bw
        return G 




