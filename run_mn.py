from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.topo import Topo
from MCS import  recovery_path
from mininet.link import TCLink
import traffic_injector
import time
import os 

class Topology(Topo):
    def __init__(self, *args, **params):
        super().__init__(*args, **params)
        
        #Get the real Graph from the MCS.py 
        # recovery_path return: (winner_set, failover, G)
        _, _, G = recovery_path() 
        switches = {}
        print(f"--- MININET: Creating {len(G.nodes())} Swtiches From  XML ---")
        # 2. Agregar Switches y Hosts (Iterando nodos de NetworkX)
        for n in G.nodes():
            # n is the integer ID  (1, 2, 3...)
            #Real name e.g 'Berling' If there's not exist , Use ID
            node_label = G.nodes[n].get('label', str(n))
            
            # DPID FORMAT Hexadecimal for Mininet (e.g: '0000000000000001')
            dpid_hex = "{:016x}".format(n)
            # Adding switch
            # Usamos the real name for the switch (e.g Berling)
            switches[n] = self.addSwitch(node_label, dpid=dpid_hex, protocols='OpenFlow13')
            
            # Adding a host connect to the switch (e.g: 'h_Berlin')
            # Dynamic IP: 10.0.0.1, 10.0.0.2...
            h = self.addHost(f'h_{node_label}')
            # Link Host-Switch (Infinity Bandwithd, delay 0)
            self.addLink(h, switches[n])

        # 3. Adding links among switches (Iterating edges de NetworkX)
        print(f"--- MININET: Creating {len(G.edges())} Links From XML ---")
        
        for u, v, data in G.edges(data=True):
            # 'data' is the dictionary of attributes of the link in NetworkX 
            # Extracting Delay  :Your parser saves: 'delay_str' (e.g: '4.52ms')
            #If there's not exist , we put '1ms' by default 
            delay_val = data.get('delay_str', '1ms') 
            # Extraer BW: Your parser saves 'bandwidth'
            bw_val = data.get('bandwidth', 1000) # Default 1000 Mbps
            # Agregar el Link usando las referencias guardadas en el dict 'switches'
            # Adding the link using the reerences save in the dict 'switches'
            self.addLink(switches[u], switches[v], bw=bw_val, delay=delay_val)

def run_network():
    topo = Topology()
    net = Mininet(topo=topo, controller=RemoteController, link=TCLink, waitConnected=True)
    net.start()
    print("Network Started")
    print("Waiting for controller...")
    time.sleep(2)
    
    print("*** CONFIGURING QoS (The Ambulance Lane) ***")
    for switch in net.switches:
        for intf in switch.intfList():
            if intf.name == 'lo': continue 
            
            # 1. Create Queues
            # Queue 0 (Default) -> Class 1:1
            # Queue 1 (High Prio) -> Class 1:2
            cmd_qos = (
                f"ovs-vsctl set port {intf.name} qos=@newqos -- "
                f"--id=@newqos create qos type=linux-htb other-config:max-rate=1000000000 queues:0=@q0 queues:1=@q1 -- "
                f"--id=@q0 create queue other-config:min-rate=10000000 other-config:max-rate=200000000 other-config:burst=100000 -- "
                f"--id=@q1 create queue other-config:min-rate=100000000 other-config:max-rate=1000000000 other-config:burst=100000"
            )
            switch.cmd(cmd_qos)
            
            # 2. ROBUST FILTERING (The Fix)
            # Use 'flower' classifier which doesn't care about byte offsets.
            # It finds 0x88cc (LLDP) wherever it is.
            
            # Match LLDP (0x88cc)
            cmd_lldp = f"tc filter add dev {intf.name} parent 1: prio 1 protocol 0x88cc flower flowid 1:2"
            switch.cmd(cmd_lldp)

            # Match BDDP (0x8942) - For ONOS/Floodlight support
            cmd_bddp = f"tc filter add dev {intf.name} parent 1: prio 1 protocol 0x8942 flower flowid 1:2"
            switch.cmd(cmd_bddp)

    print("*** QoS Configured: LLDP prioritized via TC Flower ***")
    
    print("Waiting for LLDP discovery (15s)...")
    time.sleep(15) 
    
    print("Testing connectivity (PingAll)...")
    net.pingAll() 
    print("[!] Topology is ready.\n")
    
    print("\n--- READY TO INJECT TRAFFIC ---")
    answer = input("Do you want to run the Traffic Matrices from a folder? (y/n): ")
    if answer.lower() == 'y':
        folder_path = ('TestDataSet')
        if os.path.isdir(folder_path):
            files = [f for f in os.listdir(folder_path) if f.endswith('.dat')]
            files.sort()
            for index, filename in enumerate(files):
                full_path = os.path.join(folder_path, filename)
                print(f"[{index+1}/{len(files)}] Processing: {filename}")
                flows = traffic_injector.parse_traffic_matrix(full_path, scaling_factor=0.005)
                traffic_injector.inject_traffic(net, flows, duration=30)
    
    print("Network is ready. Type exit to stop.")
    CLI(net)
    net.stop() 

if __name__== '__main__':
    setLogLevel('info')
    run_network()
