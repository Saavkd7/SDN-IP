import os
import sys
import time
import json
import re
import pandas as pd
import xml.etree.ElementTree as ET

# Importamos tu lógica de topología para validar
from MCS import recovery_path 

class TrafficInjector:
    def __init__(self, net):
        self.net = net
        
        # --- CARGA Y EXTRACCIÓN DE LA TOPOLOGÍA DE REFERENCIA ---
        print("[TrafficInjector] Loading Reference Topology from MCS...")
        _, _, G = recovery_path() 
        
        # Extraemos los NOMBRES ('label') de los nodos.
        self.valid_nodes = set()
        for n in G.nodes():
            label = G.nodes[n].get('label', str(n))
            self.valid_nodes.add(label)
            
        print(f"[TrafficInjector] Validated {len(self.valid_nodes)} nodes in topology: {self.valid_nodes}")

    # ==============================================================================
    # 1. PARSE (Igual que antes)
    # ==============================================================================
    def parse(self, filepath, scaling_factor=1.0):
        if not os.path.exists(filepath):
            print(f"[ERROR] File not found: {filepath}")
            return []

        print(f"[*] Processing: {filepath} ...")
        raw_data = self._parse_xml_raw(filepath)
        return self._pandas_validation_pipeline(raw_data, scaling_factor)

    # ==============================================================================
    # 2. INJECT TRAFFIC & MEASURE (NUEVA LÓGICA)
    # ==============================================================================
    def inject_traffic(self, flows, duration=30, interval_id=1):
        """
        Inyecta tráfico Y mide métricas simultáneamente.
        Retorna lista de diccionarios con resultados.
        """
        if not flows:
            print("   [!] No flows to inject (List is empty).")
            return []

        print(f"\n   >>> INJECTING & MEASURING {len(flows)} FLOWS | Duration: {duration}s <<<")
        
        # A. Setup Servers (Evitar duplicados)
        destinations = set(flow['dst'] for flow in flows)
        for dst_label in destinations:
            safe_dst = dst_label[:8]
            h = self.net.get(f"h_{safe_dst}")
            if h:
                h.cmd('killall -9 iperf3') # Limpieza preventiva
                h.cmd('iperf3 -s -D') # -D corre en background
            else:
                print(f"[WARN]: Server host h_{safe_dst} not found!")
        
        time.sleep(1) # Esperar bind

        # B. Launch Clients (Iperf + Ping)
        active_measurements = []
        
        for i, flow in enumerate(flows):
            src_label = flow['src']
            dst_label = flow['dst']
            bw = flow['bw']

            safe_src = src_label[:8]
            safe_dst = dst_label[:8]

            h_src = self.net.get(f"h_{safe_src}")
            h_dst = self.net.get(f"h_{safe_dst}")

            if h_src and h_dst:
                # Archivos temporales
                iperf_file = f"/tmp/res_{interval_id}_{i}.json"
                ping_file = f"/tmp/ping_{interval_id}_{i}.txt"

                # Comandos:
                # 1. Iperf UDP (-u) salida JSON (-J)
                cmd_iperf = f"iperf3 -c {h_dst.IP()} -u -b {bw:.2f}M -t {duration} -J > {iperf_file} &"
                # 2. Ping para Delay (-i 0.5 medio segundo)
                cmd_ping = f"ping -c {int(duration*2)} -i 0.5 -q {h_dst.IP()} > {ping_file} &"

                h_src.cmd(cmd_iperf)
                h_src.cmd(cmd_ping)

                active_measurements.append({
                    'src': src_label,
                    'dst': dst_label,
                    'iperf_file': iperf_file,
                    'ping_file': ping_file
                })

        # C. Wait & Collect
        print(f"   -> Tests running... waiting {duration}s")
        time.sleep(duration + 2) # Buffer para escritura en disco

        results = []
        for m in active_measurements:
            jitter = 0.0
            throughput = 0.0
            loss = 0.0
            rtt = 0.0

            # Leer Iperf
            try:
                with open(m['iperf_file'], 'r') as f:
                    data = json.load(f)
                    stats = data['end']['sum']
                    jitter = stats.get('jitter_ms', 0.0)
                    throughput = stats.get('bits_per_second', 0.0) / 1e6
                    loss = stats.get('lost_percent', 0.0)
            except: pass

            # Leer Ping
            try:
                with open(m['ping_file'], 'r') as f:
                    content = f.read()
                    match = re.search(r'rtt min/avg/max/mdev = [\d\.]+/([\d\.]+)/', content)
                    if match: rtt = float(match.group(1))
            except: pass

            results.append({
                'Source': m['src'],
                'Destination': m['dst'],
                'Jitter_ms': round(jitter, 3),
                'Throughput_Mbps': round(throughput, 3),
                'Delay_RTT_ms': round(rtt, 3),
                'Loss_Percent': round(loss, 2)
            })
            
            # Borrar temporales
            os.system(f"rm {m['iperf_file']} {m['ping_file']}")

        # Cleanup final
        for dst_label in destinations:
            safe_dst = dst_label[:8]
            h = self.net.get(f"h_{safe_dst}")
            if h: h.cmd('killall -9 iperf3')

        return results

    # ==============================================================================
    # 3. PANDAS PIPELINE (MANTENIENDO TU LÓGICA DE FILTRADO)
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

        # --- CHECK 2: TOPOLOGY MATCHING (LA CLAVE) ---
        # Esta linea asegura que solo pasen flujos donde src Y dst existan en la topologia
        initial_count = len(df)
        df = df[df['src'].isin(self.valid_nodes) & df['dst'].isin(self.valid_nodes)]
        
        dropped = initial_count - len(df)
        if dropped > 0:
            print(f"   [WARN] Dropped {dropped} flows referencing nodes NOT in MCS topology.")

        # --- CHECK 3: MISSING NODES ---
        xml_nodes_present = set(df['src'].unique()) | set(df['dst'].unique())
        missing_nodes = self.valid_nodes - xml_nodes_present
        if missing_nodes:
            print(f"   [INFO] Matrix is silent for {len(missing_nodes)} nodes. Assuming zero traffic.")

        # --- CHECK 4: DATA TYPE & SCALING ---
        try:
            df['bw'] = df['raw_val'].astype(str).str.strip().astype(float) * scaling_factor
        except ValueError as e:
            print(f"   [ERROR] Non-numeric bandwidth values detected: {e}")
            return []

        # --- CHECK 5: LOGIC ---
        df = df[df['src'] != df['dst']] 
        df = df[df['bw'] > 0.001]       

        print(f"   -> Validation Passed. {len(df)} flows ready.")
        
        # --- ¡AQUÍ ESTÁ EL CAMBIO! ---
        # Cambiamos .itertuples() (Tuplas) por .to_dict('records') (Diccionarios)
        # Esto permite hacer flow['src'] en la funcion inject_traffic
        return df[['src', 'dst', 'bw']].to_dict('records')

    # ==============================================================================
    # 4. PARSER RAW (Igual que antes)
    # ==============================================================================
    def _parse_xml_raw(self, filepath):
        data = []
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            ns = {'n': 'http://sndlib.zib.de/network'}
            demands = root.findall('.//n:demand', ns)
            if not demands:
                demands = root.findall('.//demand')
                ns = None

            for d in demands:
                src = d.get('source')
                dst = d.get('target')
                val = d.get('demandValue')

                if src is None:
                    tag = d.find('n:source', ns) if ns else d.find('source')
                    if tag is not None: src = tag.text
                if dst is None:
                    tag = d.find('n:target', ns) if ns else d.find('target')
                    if tag is not None: dst = tag.text
                if val is None:
                    tag = d.find('n:demandValue', ns) if ns else d.find('demandValue')
                    if tag is not None: val = tag.text
                
                # Rescate por ID
                if src is None and d.get('id'):
                    parts = d.get('id').split('_')
                    if len(parts) >= 2:
                        src, dst = parts[0], parts[1]

                data.append({'src': src, 'dst': dst, 'raw_val': val})
        except Exception as e:
            print(f"[ERROR] XML Parse Error: {e}")
        return data