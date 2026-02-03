import os
import sys
import time
import pandas as pd
import xml.etree.ElementTree as ET

# Importamos tu lógica de topología para validar
from MCS import recovery_path 

class TrafficInjector:
    def __init__(self, net):
        """
        :param net: Objeto Mininet.
        """
        self.net = net
        
        # --- CARGA Y EXTRACCIÓN DE LA TOPOLOGÍA DE REFERENCIA ---
        print("[TrafficInjector] Loading Reference Topology from MCS...")
        _, _, G = recovery_path() # Obtenemos el grafo NetworkX
        
        # Extraemos los NOMBRES ('label') de los nodos, que es lo que viene en el XML.
        # Si no hay label, usamos el ID string.
        self.valid_nodes = set()
        for n in G.nodes():
            label = G.nodes[n].get('label', str(n))
            self.valid_nodes.add(label)
            
        print(f"[TrafficInjector] Validated {len(self.valid_nodes)} nodes in topology: {self.valid_nodes}")

    # ==============================================================================
    # MÉTODOS PÚBLICOS
    # ==============================================================================
    def parse(self, filepath, scaling_factor=1.0):
        """
        Método Maestro: Lee, Valida (Topología/Nulls) y Escala.
        """
        if not os.path.exists(filepath):
            print(f"[ERROR] File not found: {filepath}")
            return []

        print(f"[*] Processing: {filepath} ...")
        
        # 1. Extracción Cruda (XML -> List of Dicts)
        raw_data = self._parse_xml_raw(filepath)
        
        # 2. Validación y Limpieza con Pandas
        return self._pandas_validation_pipeline(raw_data, scaling_factor)

    def inject_traffic(self, flows, duration=30):
        """
        Ejecuta la inyección en Mininet.
        """
        if not flows:
            print("   [!] No flows to inject (List is empty).")
            return

        print(f"\n   >>> INJECTING {len(flows)} FLOWS | Duration: {duration}s <<<")
        
        # A. Setup Servers
        destinations = set(dst for _, dst, _ in flows)
        for dst in destinations:
            safe_dst=dst[:8]
            h = self.net.get(f"h_{safe_dst}")
            if h:
                h.cmd('killall -9 iperf')
                h.cmd('iperf -s -u &')
            else:
                print(f"[WARN]: Server host h_{safe_dst} not found in MININET!")
        
        time.sleep(2) # Wait for bind

        # B. Launch Clients
        count = 0
        for src, dst, bw in flows:
            try:
                # Mapeo dinámico: h_NombreCiudad
                safe_src=src[:8]
                safe_dst=dst[:8]
                h_src = self.net.get(f"h_{safe_src}")
                h_dst = self.net.get(f"h_{safe_dst}")
                if h_src and h_dst:
                    cmd = f'iperf -c {h_dst.IP()} -u -b {bw:.2f}M -t {duration} &'
                    h_src.cmd(cmd)
                    count += 1
            except: pass
        
        print(f"   -> {count} streams active. Running...")
        
        # C. Progress & Cleanup
        for _ in range(duration + 2):
            time.sleep(1)
            
        for h in self.net.hosts:
            h.cmd('killall -9 iperf')
        print("   -> Done.")

    # ==============================================================================
    # MOTOR PANDAS (Validación y Limpieza)
    # ==============================================================================
    def _pandas_validation_pipeline(self, raw_data, scaling_factor):
        df = pd.DataFrame(raw_data)
        
        if df.empty:
            print("   [!] XML is empty.")
            return []

        # --- CHECK 1: NULL VALUES ---
        if df.isnull().values.any():
            print("   [CRITICAL] Dataset contains NULL values. Dropping corrupted rows.")
            df = df.dropna()

        # --- CHECK 2: TOPOLOGY MATCHING (Alien Nodes - Extranjeros) ---
        # Si el XML trae nodos que NO existen en la topología, los borramos.
        initial_count = len(df)
        df = df[df['src'].isin(self.valid_nodes) & df['dst'].isin(self.valid_nodes)]
        
        dropped = initial_count - len(df)
        if dropped > 0:
            print(f"   [WARN] Dropped {dropped} flows referencing nodes NOT in MCS topology.")

        # --- CHECK 3: MISSING NODES (Nodos Silenciosos) ---
        # Si la topología tiene nodos que no aparecen en el XML...
        xml_nodes_present = set(df['src'].unique()) | set(df['dst'].unique())
        missing_nodes = self.valid_nodes - xml_nodes_present
        
        # --- CAMBIO IMPORTANTE: NO DETENER, SOLO AVISAR ---
        if missing_nodes:
            # No es un error crítico, es simplemente que esos nodos no tienen tráfico en este intervalo.
            print(f"   [INFO] Matrix is silent for {len(missing_nodes)} nodes: {missing_nodes}. Assuming zero traffic.")
            # NO retornamos [] (return []), dejamos que siga.

        # --- CHECK 4: DATA TYPE & SCALING ---
        try:
            # Limpiamos espacios en blanco y convertimos a float
            # raw_val puede venir como ' 0.003 ' (strings sucios)
            df['bw'] = df['raw_val'].astype(str).str.strip().astype(float) * scaling_factor
        except ValueError as e:
            print(f"   [ERROR] Non-numeric bandwidth values detected: {e}")
            return []

        # --- CHECK 5: LOGIC (Loops & Noise) ---
        df = df[df['src'] != df['dst']] # No self-loops
        df = df[df['bw'] > 0.001]       # No zero traffic

        print(f"   -> Validation Passed. {len(df)} flows ready.")
        
        # Exportar a Tuplas
        return list(df[['src', 'dst', 'bw']].itertuples(index=False, name=None))

    # ==============================================================================
    # PARSER RAW
    # ==============================================================================
    def _parse_xml_raw(self, filepath):
        data = []
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            
            # 1. Definir Namespace (Vital para SNDLib)
            ns = {'n': 'http://sndlib.zib.de/network'}
            
            # Buscar demandas usando el namespace 'n'
            demands = root.findall('.//n:demand', ns)
            
            # Si no encuentra nada con namespace, intentar sin él (fallback)
            if not demands:
                demands = root.findall('.//demand')
                ns = None # Apagamos el namespace para las búsquedas siguientes

            for d in demands:
                # --- ESTRATEGIA 1: Atributos (SNDLib Clásico) ---
                src = d.get('source')
                dst = d.get('target')
                val = d.get('demandValue')

                # --- ESTRATEGIA 2: Etiquetas Hijas (Tu formato actual) ---
                # Si src sigue siendo None, buscamos adentro <source>...</source>
                if src is None:
                    # Buscamos 'n:source' si hay namespace, sino 'source' a secas
                    tag = d.find('n:source', ns) if ns else d.find('source')
                    if tag is not None: src = tag.text

                if dst is None:
                    tag = d.find('n:target', ns) if ns else d.find('target')
                    if tag is not None: dst = tag.text

                if val is None:
                    tag = d.find('n:demandValue', ns) if ns else d.find('demandValue')
                    if tag is not None: val = tag.text

                # --- ESTRATEGIA 3: Rescate desde el ID (Ultimísimo recurso) ---
                # Tu ID es 'ATLAM5_ATLAng'. Si todo falla, partimos el string.
                if src is None and d.get('id'):
                    parts = d.get('id').split('_')
                    if len(parts) >= 2:
                        src = parts[0]
                        dst = parts[1]
                        # El valor se queda en None o 0 si no se encuentra

                data.append({
                    'src': src,
                    'dst': dst,
                    'raw_val': val
                })
                
        except Exception as e:
            print(f"[ERROR] XML Parse Error: {e}")
            
        return data