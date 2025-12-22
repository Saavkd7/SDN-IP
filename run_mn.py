from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.topo import Topo
from abilene_topo import Abilene
from mininet.link import TCLink
import traffic_injector
import time
import os 

class Topology(Topo):
    def __init__(self, *args, **params):
        super().__init__(*args, **params)
        topo = Abilene()
        switches = {}
        for i in topo.city_names:
            dpid_int = topo.citiesID[i]
            dpid_hex = "{:016x}".format(dpid_int)
            switches[i] = self.addSwitch(i, dpid=dpid_hex, protocols='OpenFlow13')
            h = self.addHost(f'h_{i}')
            self.addLink(h, switches[i], bw=1000, delay='0ms')
        
        for u, v, bw, delay in topo.links:
            self.addLink(switches[u], switches[v], delay=delay)

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
                flows = traffic_injector.parse_traffic_matrix(full_path, scaling_factor=0.05)
                traffic_injector.inject_traffic(net, flows, duration=30)
    
    print("Network is ready. Type exit to stop.")
    CLI(net)
    net.stop() 

if __name__== '__main__':
    setLogLevel('info')
    run_network()
