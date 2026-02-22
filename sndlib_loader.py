import xml.etree.ElementTree as ET
import networkx as nx
import logging
import math
import os
import glob
import random

class SNDLibXMLParser:
    def __init__(self, xml_file):
        self.xml_file = xml_file
        self.PROPAGATION_SPEED_KM_MS = 200.0
        self.str_to_int = {}
        # Corrección: Quitar los '< >' del string para no romper el parser
        self.ns = {'snd': 'http://sndlib.zib.de/network'}

    def _calculate_distance_km(self, coord1, coord2):
        # coord = (longitud, latitud)
        lon1, lat1 = map(math.radians, coord1)
        lon2, lat2 = map(math.radians, coord2)

        dlon = lon2 - lon1
        dlat = lat2 - lat1

        # Fórmula de Haversine
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        r = 6371  # Radio de la Tierra en km
        return c * r

    def get_graph(self):
        # 1. Parsing Defensivo del Archivo
        try:
            tree = ET.parse(self.xml_file)
            root = tree.getroot()
        except (ET.ParseError, FileNotFoundError) as e:
            logging.error(f"Error crítico al cargar la topología XML: {e}")
            raise

        G = nx.Graph()
        node_coords = {}
        
        # 2. Extracción Robusta de Nodos
        nodes_xml = root.findall('.//snd:node', self.ns)
        if not nodes_xml:
            logging.warning("Nodes NOT FOUND. Verify the namespace or XML structure.")

        for i, node in enumerate(nodes_xml, start=1):
            node_id_str = node.get('id')
            if not node_id_str:
                logging.warning("Removing a node because it doesn't contain an 'ID'")
                continue
                
            # Heurística de Fallback con Telemetría Explícita
            x, y = 0.0, 0.0
            coords = node.find('snd:coordinates', self.ns)
            
            if coords is not None:
                try:
                    x_str = next(child.text for child in coords if 'x' in child.tag)
                    y_str = next(child.text for child in coords if 'y' in child.tag)
                    x, y = float(x_str), float(y_str)
                except StopIteration:
                    logging.warning(f"Cooordinates (x/y) NO FOUND for the node '{node_id_str}'. Forcing pos a (0.0, 0.0).")
                except ValueError:
                    logging.warning(f"Numeric format corrupted in the coordinates node '{node_id_str}'. Forcing pos a (0.0, 0.0).")
            else:
                logging.warning(f"Label <coordinates> not present for the node '{node_id_str}'. Forcing pos a (0.0, 0.0).")
            
            self.str_to_int[node_id_str] = i 
            node_coords[node_id_str] = (x, y)
            G.add_node(i, label=node_id_str, pos=(x, y))

        # 3. Parsear Enlaces y Calcular Pesos Físicos
        links_xml = root.findall('.//snd:link', self.ns)
        for link in links_xml:
            s_elem = link.find('snd:source', self.ns)
            t_elem = link.find('snd:target', self.ns)
            
            if s_elem is None or t_elem is None:
                continue
                
            s_str, t_str = s_elem.text, t_elem.text
            
            if s_str in self.str_to_int and t_str in self.str_to_int:
                u = self.str_to_int[s_str]
                v = self.str_to_int[t_str]
                
                # Corrección del nombre del método para igualar al def superior
                dist_km = self._calculate_distance_km(node_coords[s_str], node_coords[t_str])
                
                delay_ms = max(0.1, dist_km / max(self.PROPAGATION_SPEED_KM_MS, 0.0001))
                G.add_edge(u, v, delay=delay_ms, distance_km=dist_km)

        # 4. Poda Topológica y Telemetría por Teoría de Conjuntos
        # Tomamos una fotografía del estado antes de mutilar la red
        original_nodes = set(G.nodes())
        original_edges = set(G.edges())

        # Ejecutamos la reducción al núcleo de grado 2
        G = nx.k_core(G, k=2).copy()

        # Calculamos la entropía (lo que fue destruido)
        pruned_nodes = original_nodes - set(G.nodes())
        pruned_edges = original_edges - set(G.edges())

        # Informamos al usuario si hubo mutilación
        if pruned_nodes or pruned_edges:
            logging.info(f"Toplogy cleaning (k-core=2) RUN:")
            logging.info(f" -> Removed Nodes ({len(pruned_nodes)}): {list(pruned_nodes)}")
            logging.info(f" -> Removed Links ({len(pruned_edges)}): {list(pruned_edges)}")

        return G
    

    def calculate_full_network_load(self,G,traffic_file_path=None, avg_packet_size_bytes=800, sigma=0.0):
        """
        Calcuate the reald load (PPS ) simulating SPF using 
        explictly the attribute delay  of the physical 
        topology
        """
        target_file=traffic_file_path if traffic_file_path else self.xml_file
        if not os.path.exists(target_file):
            logging.error(f"[LOADER] Archivo de tráfico ausente: {target_file}")
            return {}
        
        logging.info(f"[LOADER] simulating SPF upon: {os.path.basename(target_file)} | Sigma: {sigma}")

        try:
            tree=ET.parse(target_file)
            root=tree.getroot()
        except (ET.ParseError, FileNotFoundError) as e:
            logging.error(f"[LOADER] Fail by parsing XML demands: {e}")
            return {}
        node_lambda={n:0.0 for n in G.nodes()}
        demands=root.findall('.//snd:demand',self.ns)
        flows_routed=0
        for demand in demands:
            src_elem=demand.find('snd:source',self.ns)
            dst_elem=demand.find('snd:target',self.ns)
            val_elem=demand.find('snd:demandValue',self.ns)
            #Survival validation (FAIL-SAfE)
            if src_elem is None or dst_elem is None or val_elem is None:
                logging.debug("[LOADER-DROP] Ignored Demand: XML labels incompleted.")
                continue


            # src_str, dst_str=src_elem, dst_elem
            src_str, dst_str = src_elem.text, dst_elem.text
            mbps=float(val_elem.text)

            if mbps <=0.0:
                logging.debug(f"[LOADER-DROP] Ignoring {src_str}->{dst_str} FLow: Traffic 0 Mbps.")
                continue

            if src_str not in self.str_to_int or dst_str not in self.str_to_int:
                logging.warning(f"[LOADER-DROP] Flow {src_str}->{dst_str} ignored: UNknown IDs  (Not coincidence found with topology).")
                continue
            u=self.str_to_int[src_str]
            v=self.str_to_int[dst_str]
            
            if u not in G or v not in G:
                logging.debug(f"[LOADER-DROP] Flow {src_str}->{dst_str} ignored: One of the nodes was removed by K-Core.")
                continue

            # Stocastic Packet SIze
            if sigma >0:
                pkt_size=random.gauss(avg_packet_size_bytes,sigma)
                pkt_size=max(64.0,min(1500.0,pkt_size))
            else:
                pkt_size=float(avg_packet_size_bytes)
            
            #COnversion a PPS 
            pps=(mbps*1_000_000.0)/(pkt_size*8.0)
            #SPF ROUTING DIJKSTRA GUIDED FOR PURE DELAY
            try:
                path=nx.shortest_path(G,source=u, target=v, weight='delay')
                for node_in_path in path:
                    node_lambda[node_in_path]+= pps
                flows_routed+=1
            except nx.NetworkXNoPath:
                logging.debug(f"NO ROUTE between {src_str} and {dst_str}. Discarding flow")
        if flows_routed==0:
            logging.error("[LOADER] Zero router flows. Verify the nodes in the XML FILE")
            return node_lambda
        max_load=max(node_lambda.values())
        avg_load=sum(node_lambda.values())/len(node_lambda)
        logging.info(f" [LOADER] ROUTED{flows_routed} flows. Max load: {max_load:.0f}PPS. AVG:{avg_load:.0f}PPS" )
        return node_lambda 
       
         
    def get_peak_traffic_from_folder(self, G, folder_path, avg_packet_size_bytes=800, sigma=0.0):
    
        peak_node_lambda = {n: 0.0 for n in G.nodes()}

        search_pattern = os.path.join(folder_path, "*.xml")
        files = glob.glob(search_pattern)
        
        # EL ESCUDO CONTRA EL COLAPSO (Falla Controlada)
        if not files:
            logging.error(f"EMPTY DIRECTORY TRAFFIC: {folder_path}")
            logging.warning("Running FallBack: Calculating From the Toplogy file.")
            # Si no hay dataset, usamos el archivo base original para al menos tener una métrica > 0
            return self.calculate_full_network_load(G, self.xml_file, avg_packet_size_bytes, sigma)

        logging.info(f"Processing {len(files)} Traffic Matrices (SPF Routing) to extracting historic peak ...")

        for i, file_path in enumerate(files):
            current_snapshot = self.calculate_full_network_load(G, file_path, avg_packet_size_bytes, sigma)

            for n, pps in current_snapshot.items():
                if pps > peak_node_lambda.get(n, 0):
                    peak_node_lambda[n] = pps

            if i % 5 == 0 and i > 0: 
                logging.info(f"   > Procesados {i}/{len(files)} snapshots...")

        # LOGGERS
        top_hottest_nodes = sorted(peak_node_lambda.items(), key=lambda x: x[1], reverse=True)[:3]
        logging.info("--- EXTRACTION COMPLETED ---")
        logging.info("Nodes with the highest load historic  (High Watermark):")
        for node, peak_pps in top_hottest_nodes:
            logging.info(f"   -> Node {node}: {peak_pps:.0f} PPS")

        return peak_node_lambda