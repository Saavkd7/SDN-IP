from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.topo import Topo
from abilene_topo import Abilene
from mininet.link import TCLink
import traffic_injector  # <--- IMPORT THE NEW SCRIPT

class Topology(Topo):
    def __init__(self, *args, **params):
        super().__init__(*args, **params)
        topo = Abilene()
        switches = {}
        for i in topo.city_names:
                dpid_int = topo.citiesID[i]
                dpid_hex = "{:016x}".format(dpid_int)
                switches[i] = self.addSwitch(i, dpid=dpid_hex, protocols='OpenFlow13')
                # Ensure hostnames match traffic_injector (h_ATLA, etc.)
                h = self.addHost(f'h_{i}')
                self.addLink(h, switches[i], bw=1000, delay='0ms')
        
        for u, v, bw, delay in topo.links:
            # Mininet applies bandwidth limits here
            self.addLink(switches[u], switches[v], bw=bw, delay=delay)
def run_network():
    topo = Topology()
    net = Mininet(topo=topo, controller=RemoteController, link=TCLink, waitConnected=True)
    net.start()
    print("Network Started")
    print("Waiting for controller...")
    # --- ADD ---
    print("\n[!] Warming up network (LLDP & ARP discovery)...")
    # This might take 10-20 seconds but ensures the graph is built
    net.pingAll() 
    print("[!] Warmup complete. Topology is ready.\n")
    # ----------------------
    # --- TRAFFIC INJECTION BLOCK ---
    print("\n--- READY TO INJECT TRAFFIC ---")
    answer = input("Do you want to run the 2004 Traffic Matrix now? (y/n): ")
    if answer.lower() == 'y':
        tm_file = "tm.2004-03-01.04-45-00.dat" 
        # SCALING FACTOR: 10
        # This inflates the traffic to ensure we hit the 250Mbps limit
        flows = traffic_injector.parse_traffic_matrix(tm_file, scaling_factor=10)
        # Run for 30 seconds
        traffic_injector.inject_traffic(net, flows, duration=10)     
    # -------------------------------
    print("Network is ready. Type exit to stop.")
    CLI(net)
    net.stop() 
if __name__== '__main__':
    setLogLevel('info')
    run_network()