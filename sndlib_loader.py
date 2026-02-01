import xml.etree.ElementTree as ET
import networkx as nx
import math

class SNDLibXMLParser:
    def __init__(self, xml_file):
        self.xml_file = xml_file
        self.OC192 = 10000 * 0.005  # High Bandwidth
        self.OC48 = 2488.32 * 0.005 # Low Bandwidth
        self.PROPAGATION_SPEED_KM_MS = 200.0 # km por milisegundo

    def _calculate_distance_km(self, coord1, coord2):
        dx = coord1[0] - coord2[0] 
        dy = coord1[1] - coord2[1] 
        dist_deg = math.sqrt(dx**2 + dy**2)
        return dist_deg * 111.0

    def get_graph(self):
        tree = ET.parse(self.xml_file)
        root = tree.getroot()
        ns = {'snd': 'http://sndlib.zib.de/network'}
        
        G = nx.Graph()
        
        # --- PASO A: NODOS ---
        node_coords = {} 
        str_to_int = {} 
        
        nodes_xml = root.findall('.//snd:node', ns)
        
        for i, node in enumerate(nodes_xml, start=1):
            node_id_str = node.get('id')
            x_elem = node.find('snd:coordinates/snd:x', ns)
            y_elem = node.find('snd:coordinates/snd:y', ns)
            
            x = float(x_elem.text) if x_elem is not None else 0.0
            y = float(y_elem.text) if y_elem is not None else 0.0
            
            str_to_int[node_id_str] = i
            node_coords[node_id_str] = (x, y)
            G.add_node(i, label=node_id_str, pos=(x, y))

        # --- PASO B: ENLACES ---
        links_xml = root.findall('.//snd:link', ns)
        
        for link in links_xml:
            source_str = link.find('snd:source', ns).text
            target_str = link.find('snd:target', ns).text
            
            if source_str in str_to_int and target_str in str_to_int:
                u = str_to_int[source_str]
                v = str_to_int[target_str]
                
                c1 = node_coords[source_str]
                c2 = node_coords[target_str]
                dist_km = self._calculate_distance_km(c1, c2)
                delay_ms = max(1.0, dist_km / self.PROPAGATION_SPEED_KM_MS)
                bw_val = self.OC192 
                
                G.add_edge(u, v, 
                           weight=delay_ms, 
                           bandwidth=bw_val, 
                           delay_str=f"{delay_ms:.2f}ms",
                           distance_km=dist_km)

        # --- PASO C: PRE-PROCESAMIENTO DE TOPOLOGIA ---
        print(f"[SNDLIB] Initial load: {len(G.nodes())} nodes, {len(G.edges())} links.")

        # 1. Eliminar nodos totalmente aislados (Degree 0)
        if not nx.is_connected(G):
            components = list(nx.connected_components(G))
            largest_cc = max(components, key=len)
            nodes_to_remove = [n for n in G.nodes() if n not in largest_cc]
            
            print(f"[CLEANUP] Removing {len(nodes_to_remove)} disconnected nodes...")
            G.remove_nodes_from(nodes_to_remove)

        # 2. Eliminar nodos hoja (Degree 1) RECURSIVAMENTE
        # Si tienes un nodo conectado por 1 solo cable, y ese cable falla, 
        # la red no puede recuperarse. El MCS fallará. Hay que quitarlos.
        while True:
            # Buscar nodos con grado 1
            leaf_nodes = [node for node, degree in dict(G.degree()).items() if degree == 1]
            
            if not leaf_nodes:
                break # Ya no quedan hojas, terminamos
            
            print(f"[CLEANUP] Pruning {len(leaf_nodes)} leaf nodes (Degree 1)...")
            for node in leaf_nodes:
                real_name = G.nodes[node].get('label', 'Unknown')
                print(f"   >>> PRUNED LEAF: ID={node}, Name='{real_name}'")
                G.remove_node(node)

        print(f"[SNDLIB] Final Topology: {len(G.nodes())} nodes, {len(G.edges())} links.")
        return G