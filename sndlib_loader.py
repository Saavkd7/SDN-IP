import xml.etree.ElementTree as ET
import networkx as nx
import math
import os
import glob
class SNDLibXMLParser:
    def __init__(self, xml_file):
        self.xml_file = xml_file
        self.OC192 = 10000 * 0.005 
        self.PROPAGATION_SPEED_KM_MS = 200.0
        self.str_to_int = {} # <--- Ahora es un atributo de clase para reusarlo
        self.ns = {'snd': 'http://sndlib.zib.de/network'} # Namespace estandarizado

    def _calculate_distance_km(self, coord1, coord2):
        dx = coord1[0] - coord2[0] 
        dy = coord1[1] - coord2[1] 
        dist_deg = math.sqrt(dx**2 + dy**2)
        return dist_deg * 111.0

    def get_traffic_load(self, traffic_file_path=None, avg_packet_size_bytes=800):
        """
        Extrae <demand> y convierte Mbps a PPS (Lambda).
        Si traffic_file_path es None, usa el archivo de topología original.
        Si se pasa una ruta, lee las demandas de ese archivo externo.
        """
        # 1. Decidir qué archivo abrir
        target_file = traffic_file_path if traffic_file_path else self.xml_file
        
        if not os.path.exists(target_file):
            print(f"[ERROR] Traffic file not found: {target_file}")
            return {}

        print(f"[LOADER] Extracting traffic from: {os.path.basename(target_file)}")
        
        try:
            tree = ET.parse(target_file)
            root = tree.getroot()
        except ET.ParseError as e:
            print(f"[ERROR] XML Parse Error in traffic file: {e}")
            return {}
            
        # Diccionario para acumular Lambda por nodo {node_id: total_pps}
        # IMPORTANTE: Usamos self.str_to_int que se llenó al cargar el grafo
        node_lambda = {id_int: 0.0 for id_int in self.str_to_int.values()}
        
        # Buscar todas las demandas en el XML (namespace incluido)
        demands = root.findall('.//snd:demand', self.ns)
        
        bits_per_packet = avg_packet_size_bytes * 8
        total_mbs = 0

        for demand in demands:
            src_str = demand.find('snd:source', self.ns).text
            # demandValue en SNDLib suele ser Mbps
            val_elem = demand.find('snd:demandValue', self.ns)
            mbps = float(val_elem.text) if val_elem is not None else 0.0
            
            if src_str in self.str_to_int:
                src_id = self.str_to_int[src_str]
                # Conversión a PPS (Paquetes por Segundo)
                pps = (mbps * 1_000_000) / bits_per_packet
                node_lambda[src_id] += pps
                total_mbs += mbps
        
        print(f"[LOADER] Total Network Load: {total_mbs:.2f} Mbps")
        return node_lambda

    def get_graph(self):
        tree = ET.parse(self.xml_file)
        root = tree.getroot()
        
        G = nx.Graph()
        node_coords = {} 
        
        nodes_xml = root.findall('.//snd:node', self.ns)
        
        for i, node in enumerate(nodes_xml, start=1):
            node_id_str = node.get('id')
            x_elem = node.find('snd:coordinates/snd:snd:x', self.ns) # Ajustado namespace
            if x_elem is None: x_elem = node.find('snd:coordinates/snd:x', self.ns)
            y_elem = node.find('snd:coordinates/snd:snd:y', self.ns)
            if y_elem is None: y_elem = node.find('snd:coordinates/snd:y', self.ns)
            
            x = float(x_elem.text) if x_elem is not None else 0.0
            y = float(y_elem.text) if y_elem is not None else 0.0
            
            self.str_to_int[node_id_str] = i # Guardamos el mapeo
            node_coords[node_id_str] = (x, y)
            G.add_node(i, label=node_id_str, pos=(x, y))

        links_xml = root.findall('.//snd:link', self.ns)
        
        for link in links_xml:
            source_str = link.find('snd:source', self.ns).text
            target_str = link.find('snd:target', self.ns).text
            
            if source_str in self.str_to_int and target_str in self.str_to_int:
                u = self.str_to_int[source_str]
                v = self.str_to_int[target_str]
                
                c1 = node_coords[source_str]
                c2 = node_coords[target_str]
                dist_km = self._calculate_distance_km(c1, c2)
                delay_ms = max(1.0, dist_km / self.PROPAGATION_SPEED_KM_MS)
                
                G.add_edge(u, v, weight=delay_ms, distance_km=dist_km)

        # Cleanup de hojas (Degree 1)
        while True:
            leaf_nodes = [n for n, d in dict(G.degree()).items() if d <= 1]
            if not leaf_nodes: break
            G.remove_nodes_from(leaf_nodes)

        return G

    def get_peak_traffic_from_folder(self, folder_path, avg_packet_size_bytes=800):
        """
        Escanea TODOS los XMLs de una carpeta.
        Devuelve un diccionario con el TRÁFICO MÁXIMO (Peak) registrado para cada nodo.
        """
        # 1. Preparar diccionario de máximos en 0
        peak_node_lambda = {id_int: 0.0 for id_int in self.str_to_int.values()}
        
        # 2. Listar archivos
        search_pattern = os.path.join(folder_path, "*.xml")
        files = glob.glob(search_pattern)
        
        if not files:
            print(f"[ERROR] No XML files found in {folder_path}")
            return peak_node_lambda

        print(f"[LOADER] Scanning {len(files)} files for Peak Traffic Analysis...")
        
        bits_per_packet = avg_packet_size_bytes * 8
        
        # 3. Iterar y actualizar el máximo ("High Score")
        for i, file_path in enumerate(files):
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()
                
                demands = root.findall('.//snd:demand', self.ns)
                
                # Diccionario temporal para este archivo (Snapshot)
                current_snapshot_lambda = {id_int: 0.0 for id_int in self.str_to_int.values()}
                
                # Sumar todas las demandas de este momento
                for demand in demands:
                    src_str = demand.find('snd:source', self.ns).text
                    val_elem = demand.find('snd:demandValue', self.ns)
                    mbps = float(val_elem.text) if val_elem is not None else 0.0
                    
                    if src_str in self.str_to_int:
                        src_id = self.str_to_int[src_str]
                        pps = (mbps * 1_000_000) / bits_per_packet
                        current_snapshot_lambda[src_id] += pps
                
                # COMPARAR Y GUARDAR EL MÁXIMO
                for node_id, pps in current_snapshot_lambda.items():
                    if pps > peak_node_lambda[node_id]:
                        peak_node_lambda[node_id] = pps

                # Barra de progreso simple
                if i % 10 == 0: print(f"\rScanning... {i}/{len(files)}", end="")
                    
            except Exception as e:
                print(f"[WARNING] Error reading {os.path.basename(file_path)}: {e}")
                continue

        print(f"\n[LOADER] Peak Traffic Extraction Complete.")
        return peak_node_lambda