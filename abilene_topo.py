import networkx as nx   
class Abilene:
    def __init__(self):
        self.build()
    def build(self):
        self.city_names = ['ATLA', 'CHIN', 'DNVR', 'HSTN', 'IPLS', 
                      'KSCY', 'LOSA', 'NYCM', 'SNVA', 'STTL', 'WASH']
        self.citiesID={name: i for i,name in enumerate(self.city_names,start=1)}
        self.links=[
            ('NYCM', 'WASH', 10000, '1.64ms'),
            ('NYCM', 'CHIN', 10000, '5.73ms'),
            ('WASH', 'ATLA', 10000, '4.37ms'),
            ('ATLA', 'HSTN', 10000, '5.67ms'),
            ('HSTN', 'LOSA', 10000, '11.03ms'),
            ('LOSA', 'SNVA', 10000, '2.50ms'),
            ('SNVA', 'STTL', 10000, '5.69ms'),
            ('STTL', 'DNVR', 10000, '8.22ms'),
            ('DNVR', 'KSCY', 10000, '3.71ms'),
            ('KSCY', 'IPLS', 10000, '4.52ms'),
            ('IPLS', 'CHIN', 10000, '1.30ms'),
            ('ATLA', 'IPLS', 10000, '2.95ms'),
            ('HSTN', 'KSCY', 10000, '5.13ms'),
            ('DNVR', 'SNVA', 10000, '7.57ms')
        ]       
    def get_graph(self):
        G=nx.Graph()
        G.add_nodes_from(self.citiesID.values())
        for u, v, bw , delay in self.links:
            U=self.citiesID[u]
            V=self.citiesID[v]
            G.add_edge(U,V) #Weigh=delay to add later as paramether or bw
        return G 




