import networkx as nx
import random
import matplotlib.pyplot as plt





# ==============================================================================
# 1. MEDIUM TOPOLOGY: GEANT (Europe - 23 Nodes)
# ==============================================================================
class Geant:
    def __init__(self):
        self.build()

    def build(self):
        self.city_names = [
            'AMST', 'ATHE', 'BELG', 'BERL', 'BRAT', 'BRUS', 'BUDA', 'COPE',
            'DUBL', 'FRAN', 'GENE', 'LISB', 'LOND', 'MADR', 'MILA', 'MUNI',
            'PARI', 'PRAG', 'RIGA', 'ROME', 'SOFI', 'TALL', 'VIEN' 
        ]
        self.citiesID = {name: i for i, name in enumerate(self.city_names, start=1)}
        
        oc192 = 10000 * 0.005 
        oc48  = 2488.32 * 0.005

        self.links = [
            ('LOND', 'PARI', oc192, '3.20ms'), ('LOND', 'AMST', oc192, '3.50ms'),
            ('PARI', 'FRAN', oc192, '4.10ms'), ('FRAN', 'GENE', oc192, '3.80ms'),
            ('GENE', 'MILA', oc192, '2.90ms'), ('AMST', 'FRAN', oc192, '3.10ms'),
            ('AMST', 'BRUS', oc192, '1.80ms'), ('BRUS', 'PARI', oc192, '2.10ms'),
            ('PARI', 'MADR', oc192, '9.50ms'), ('MADR', 'LISB', oc48,  '5.20ms'),
            ('LOND', 'DUBL', oc192, '4.50ms'), ('AMST', 'COPE', oc192, '6.10ms'),
            ('COPE', 'TALL', oc48,  '8.50ms'), ('TALL', 'RIGA', oc48,  '3.20ms'),
            ('BERL', 'PRAG', oc192, '3.00ms'), ('FRAN', 'BERL', oc192, '4.20ms'),
            ('BERL', 'COPE', oc192, '4.50ms'), ('FRAN', 'MUNI', oc192, '3.00ms'),
            ('MUNI', 'VIEN', oc192, '3.50ms'), ('VIEN', 'BRAT', oc48,  '1.20ms'),
            ('VIEN', 'BUDA', oc192, '2.50ms'), ('BUDA', 'BELG', oc48,  '4.00ms'),
            ('BELG', 'SOFI', oc48,  '5.50ms'), ('SOFI', 'ATHE', oc48,  '7.80ms'),
            ('MILA', 'ROME', oc192, '5.10ms'), ('ROME', 'ATHE', oc48,  '12.50ms'),
            ('VIEN', 'PRAG', oc192, '3.10ms'),
            # Redundant Links
            ('LISB', 'LOND', oc48, '12.00ms'), ('DUBL', 'AMST', oc48, '8.50ms'),
            ('RIGA', 'BERL', oc48, '9.00ms'), ('BRAT', 'BUDA', oc48, '2.00ms')
        ]

    def get_graph(self):
        G = nx.Graph()
        G.add_nodes_from(self.citiesID.values())
        for u, v, bw, delay_str in self.links:
            if u in self.citiesID and v in self.citiesID:
                U = self.citiesID[u]
                V = self.citiesID[v]
                delay_val = float(delay_str.replace('ms', ''))
                G.add_edge(U, V, weight=delay_val, bandwidth=bw)
        return G
# ==============================================================================
# 2. ABILENE
# ==============================================================================
 class Abilene:
    def __init__(self):
        self.build()
    def build(self):
        self.city_names = ['ATLA', 'CHIN', 'DNVR', 'HSTN', 'IPLS', 
                      'KSCY', 'LOSA', 'NYCM', 'SNVA', 'STTL', 'WASH']
        self.citiesID={name: i for i,name in enumerate(self.city_names,start=1)}
        #oc192 real 10Gbps 
        oc192=10000*0.005 #Mbps scale down by 200 
        oc48=2488.32*0.005 #Mbps scale down by 200
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



class WheelTopo:
    def __init__(self):
        # Semilla fija para reproducibilidad científica (para que tus gráficas no cambien cada vez)
        random.seed(42) 

    def get_graph(self):
        # 1. Crear Rueda (0=Hub, 1-9=Rim)
        G = nx.wheel_graph(10)
        
        # 2. Definir Anchos de Banda (Estándar Abilene/Geant)
        oc192 = 10000 * 0.005  # 50.0 Mbps (Core)
        oc48  = 2488.32 * 0.005 # 12.44 Mbps (Edge)

        for u, v in G.edges():
            # --- CASO A: ENLACES AL HUB (SPOKES) ---
            # Representan fibra de alta calidad pero corta distancia.
            if u == 0 or v == 0:
                # Latencia baja pero VARIABLE (simula congestión real en el core)
                # Rango: 0.8ms a 2.8ms
                latency = round(random.uniform(0.8, 2.8), 2)
                
                G[u][v]['bandwidth'] = oc192
                G[u][v]['weight'] = latency # Importante para Dijkstra
                G[u][v]['delay_str'] = f"{latency}ms" # Estético
                
            # --- CASO B: ENLACES DE BORDE (RIM) ---
            # Representan enlaces viejos, largos o satelitales entre nodos periféricos.
            else:
                # Latencia alta y MUY VARIABLE (simula infraestructura inconsistente)
                # Rango: 25ms a 65ms
                # Esto obliga al algoritmo a elegir QUE parte del borde usar.
                latency = round(random.uniform(25.0, 65.0), 2)
                
                G[u][v]['bandwidth'] = oc48
                G[u][v]['weight'] = latency
                G[u][v]['delay_str'] = f"{latency}ms"

        return G



class Grid30_MultiLevel:
    def __init__(self):
        random.seed(42) # Semilla fija para reproducibilidad

    def get_graph(self):
        # 1. Grid 5x6 (30 Nodos)
        # Grados disponibles: 
        # - Esquinas: Grado 2 (Super Green)
        # - Bordes: Grado 3 (Medium)
        # - Centro: Grado 4 (High Power)
        G_temp = nx.grid_2d_graph(5, 6)
        G = nx.Graph()
        
        # Mapeo de coordenadas (x,y) a ID numérico 0-29
        mapping = {node: i for i, node in enumerate(G_temp.nodes())}
        
        # Definimos zonas
        oc192 = 10000 * 0.005 # Alta velocidad
        oc48  = 2488.32 * 0.005 # Baja velocidad

        for u_coord, v_coord in G_temp.edges():
            u = mapping[u_coord]
            v = mapping[v_coord]
            
            # --- ESTRATEGIA DE COSTOS PARA FORZAR 3 SETS ---
            
            # Calculamos qué tan "central" es el enlace
            # Coordenadas: x en [0,4], y en [0,5]
            # Centro aprox: x=2, y=2.5
            dist_u_center = abs(u_coord[0] - 2) + abs(u_coord[1] - 2.5)
            dist_v_center = abs(v_coord[0] - 2) + abs(v_coord[1] - 2.5)
            avg_dist = (dist_u_center + dist_v_center) / 2.0
            
            if avg_dist < 1.5:
                # ZONA 1: CORE (Centro) - Grado 4
                # Rapidísimo (1ms) pero obliga a usar nodos de alto consumo
                latency = random.uniform(0.5, 1.5)
                bw = oc192
            elif avg_dist < 3.0:
                # ZONA 2: MIDDLE (Anillo Intermedio) - Grado 3/4
                # Velocidad media (10ms)
                latency = random.uniform(8.0, 12.0)
                bw = oc192
            else:
                # ZONA 3: EDGE (Esquinas/Borde) - Grado 2/3
                # Lento (50ms) pero conecta nodos de bajo consumo
                latency = random.uniform(40.0, 60.0)
                bw = oc48

            G.add_edge(u, v, weight=latency, bandwidth=bw, delay_str=f"{latency:.2f}ms")
            
        return G


class Mesh30_Resilient:
    def __init__(self):
        random.seed(42)

    def get_graph(self):
        # 1. Base Grid 5x6 (30 Nodos)
        G_temp = nx.grid_2d_graph(5, 6)
        G = nx.Graph()
        mapping = {node: i for i, node in enumerate(G_temp.nodes())}
        
        # 2. Enlaces Cardinales (Estructura Base)
        for u_coord, v_coord in G_temp.edges():
            u, v = mapping[u_coord], mapping[v_coord]
            # Distancia al centro para lógica MultiLevel
            dist = abs(u_coord[0] - 2) + abs(u_coord[1] - 2.5)
            
            if dist < 1.5:
                lat = random.uniform(0.5, 1.5)  # Core: Rápido
                bw = 50.0
            else:
                lat = random.uniform(30.0, 50.0) # Edge: Lento
                bw = 12.0
            G.add_edge(u, v, weight=lat, bandwidth=bw)

        # 3. REDUNDANCIA CIENTÍFICA (Triangulación del Core)
        # Añadimos diagonales solo en el centro (filas 1 a 3, cols 1 a 4)
        # Esto crea "Caminos de Rescate" que reducen la concentración de reglas
        for r in range(1, 4):
            for c in range(1, 5):
                u = mapping[(r, c)]
                v = mapping[(r+1, c+1)]
                # Latencia intermedia para las diagonales
                G.add_edge(u, v, weight=15.0, bandwidth=25.0)

        return G

