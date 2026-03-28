import os
import sys
import time
import json
import re
import pandas as pd
import xml.etree.ElementTree as ET
from MCS import recovery_path 

class TrafficInjector:
    def __init__(self, net):
        self.net = net
        print("[TrafficInjector] Loading Reference Topology from MCS...")
        _, _, G = recovery_path() 
        self.valid_nodes = set()
        for n in G.nodes():
            label = G.nodes[n].get('label', str(n))
            self.valid_nodes.add(label)
        print(f"[TrafficInjector] Validated {len(self.valid_nodes)} nodes.")

    def parse(self, filepath, scaling_factor=1.0):
        if not os.path.exists(filepath):
            print(f"[ERROR] File not found: {filepath}")
            return []
        print(f"[*] Processing: {os.path.basename(filepath)} ...")
        raw_data = self._parse_xml_raw(filepath)
        return self._pandas_validation_pipeline(raw_data, scaling_factor)

    def inject_traffic(self, flows, duration=30, interval_id=1):
        if not flows:
            return []

        print(f"\n   >>> INJECTING {len(flows)} FLOWS | Duration: {duration}s <<<")
        
        # --- 1. CONFIGURATION & CLEANUP ---
        # Adjust duration so late-starting flows have time to finish
        MIN_DURATION = (len(flows) * 0.1) + 20 
        actual_duration = max(duration, MIN_DURATION)
        print(f"   [*] Adjusted Duration to {actual_duration:.1f}s to ensure overlap.")

        for h in self.net.hosts: h.cmd('killall -9 iperf3')
        time.sleep(1)

        active_measurements = []
        base_port = 5000

        # --- 2. SERVER PHASE (PREPARATION) ---
        # We must start ALL servers and prepare metadata BEFORE clients start
        print("   [*] Launching Servers...")
        for i, flow in enumerate(flows):
            src_label = flow['src']
            dst_label = flow['dst']
            
            # Safe hostnames (h_ATLAng)
            safe_src = src_label[:8]
            safe_dst = dst_label[:8]
            
            h_dst = self.net.get(f"h_{safe_dst}")
            if not h_dst: continue # Skip if host not found

            port = base_port + i
            
            # Start Server in Background
            h_dst.cmd(f"iperf3 -s -p {port} -1 -D > /dev/null 2>&1")

            # Save metadata for the client phase
            active_measurements.append({
                'src_node': safe_src,
                'dst_node': safe_dst,
                'bw': flow['bw'],
                'port': port,
                'iperf_file': f"/tmp/res_{interval_id}_{i}.json",
                'ping_file': f"/tmp/ping_{interval_id}_{i}.txt"
            })

        print("   [*] Waiting 3s for servers to bind...")
        time.sleep(3)

        # --- 3. CLIENT PHASE (STAGGERED START) ---
        print(f"   [*] Firing {len(active_measurements)} clients (Staggered)...")
        
        for item in active_measurements:
            h_src = self.net.get(f"h_{item['src_node']}")
            h_dst = self.net.get(f"h_{item['dst_node']}")

            if h_src and h_dst:
                # STAGGER: Sleep 0.1s to prevent CPU Thundering Herd
                time.sleep(0.1)

                # Launch Client
                # Note: --connect-timeout 5000 (5s) helps if network is busy
                cmd_iperf = (f"iperf3 -c {h_dst.IP()} -p {item['port']} "
                             f"-u -b {item['bw']:.4f}M -t {actual_duration} -l 256"
                             f"--connect-timeout 5000 -J > {item['iperf_file']} 2> /dev/null &")
                
                h_src.cmd(cmd_iperf)
                
                # Optional Ping
                h_src.cmd(f"ping -c {int(actual_duration)} -i 1 -q {h_dst.IP()} > {item['ping_file']} &")

        print("   -> All flows injected. Network is fully loaded.")
        
        # Wait for the last flow to finish
        time.sleep(actual_duration + 5)

        # --- 4. COLLECTION PHASE (BLINDADA) ---
        results = []
        for item in active_measurements:
            jitter, throughput, loss, rtt = 0, 0, 0, 0
            error_msg = "OK"

            # Parse Iperf
            if os.path.exists(item['iperf_file']):
                with open(item['iperf_file'], 'r') as f:
                    content = f.read().strip()
                    if not content:
                        error_msg = "EMPTY_FILE"
                    else:
                        try:
                            data = json.loads(content)
                            if 'error' in data:
                                error_msg = f"IPERF_ERR: {data['error']}"
                            elif 'end' in data:
                                # Robust retrieval of UDP stats
                                stats = data['end'].get('sum') or data['end'].get('sum_sent') or data['end'].get('sum_received')
                                
                                if stats:
                                    jitter = stats.get('jitter_ms', 0.0)
                                    throughput = stats.get('bits_per_second', 0.0) / 1e6
                                    loss = stats.get('lost_percent', 0.0)
                                else:
                                    error_msg = "NO_UDP_STATS"
                            else:
                                error_msg = "NO_END_TAG"
                        except json.JSONDecodeError:
                            error_msg = "JSON_CRASH"
            else:
                error_msg = "FILE_MISSING"

            # Parse Ping
            if os.path.exists(item['ping_file']):
                with open(item['ping_file'], 'r') as f:
                    content = f.read()
                    if "100% packet loss" in content or not content:
                        rtt = -1 
                    else:
                        match = re.search(r'rtt min/avg/max/mdev = [\d\.]+/([\d\.]+)/', content)
                        if match: rtt = float(match.group(1))

            results.append({
                'Source': item['src_node'],
                'Destination': item['dst_node'],
                'Jitter_ms': round(jitter, 3),
                'Throughput_Mbps': round(throughput, 5),
                'Delay_RTT_ms': round(rtt, 3),
                'Loss_Percent': round(loss, 2),
                'Debug': error_msg 
            })
            
            # Clean temp files
            if os.path.exists(item['iperf_file']): os.remove(item['iperf_file'])
            if os.path.exists(item['ping_file']): os.remove(item['ping_file'])

        return results

    # ==============================================================================
    # PANDAS & PARSER (Sin Cambios)
    # ==============================================================================
    def _pandas_validation_pipeline(self, raw_data, scaling_factor):
        df = pd.DataFrame(raw_data)
        if df.empty: return []
        if df.isnull().values.any(): df = df.dropna()
        df = df[df['src'].isin(self.valid_nodes) & df['dst'].isin(self.valid_nodes)]
        try:
            df['bw'] = df['raw_val'].astype(str).str.strip().astype(float) * scaling_factor
            df['bw'] = df['bw'].clip(lower=0.5, upper=50.0)
        except: return []
        df = df[df['src'] != df['dst']]
        #df = df[df['bw'] > 0.001]
        return df[['src', 'dst', 'bw']].to_dict('records')

    def _parse_xml_raw(self, filepath):
        data = []
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            ns = {'n': 'http://sndlib.zib.de/network'}
            demands = root.findall('.//n:demand', ns) or root.findall('.//demand')
            ns = None if not root.findall('.//n:demand', ns) else ns

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
                if src is None and d.get('id'):
                    parts = d.get('id').split('_')
                    if len(parts) >= 2: src, dst = parts[0], parts[1]
                data.append({'src': src, 'dst': dst, 'raw_val': val})
        except: pass
        return data