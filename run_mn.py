import os
import time
import sys
# Mininet Imports
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.topo import Topo
from mininet.link import TCLink
# Custom Modules
from MCS import recovery_path  # Tu cerebro
from traffic_injector import TrafficInjector # Tu parser
# ==============================================================================
# Topology Class
# ==============================================================================
class MyTopology(Topo):
    def __init__(self, G, *args, **params):
        """
        Recibe el Grafo G como argumento para no recalcular recovery_path
        """
        super(MyTopology, self).__init__(*args, **params)
        
        #self.switches = {}
        self.my_sws = {}
        info(f"--- MININET: Creating {len(G.nodes())} Switches From XML ---\n")
        
        # 2. Agregar Switches y Hosts
        for n in G.nodes():
            # Obtener Label (Nombre real) o usar ID
            node_label = G.nodes[n].get('label', str(n))
            safe_label=node_label[:8]
            dpid_hex = "{:016x}".format(n)
            
            # Switch + Host
            #self.switches[n] = self.addSwitch(node_label, dpid=dpid_hex, protocols='OpenFlow13')
            self.my_sws[n] = self.addSwitch(safe_label, dpid=dpid_hex, protocols='OpenFlow13')
            h = self.addHost(f'h_{safe_label}')
            #self.addLink(h, self.switches[n]) 
            self.addLink(h,self.my_sws[n])

        # 3. Agregar Enlaces
        info(f"--- MININET: Creating {len(G.edges())} Links From XML ---\n")
        for u, v, data in G.edges(data=True):
            delay_val = data.get('delay_str', '1ms') 
            bw_val = data.get('bandwidth', 1000)
            #self.addLink(self.switches[u], self.switches[v], bw=bw_val, delay=delay_val)
            self.addLink(self.my_sws[u],self.my_sws[v],bw=bw_val,delay=delay_val)

#===============================================================================================================================================================
# RULES
#================================================================================================================================================================
def check_flow_rules(net):
    info("\n*** OPENFLOW RULES ***\n")
    print(f"{'Switch':<12} | {'Rules Installed'}")
    print("-" * 30)
    
    total_rules = 0
    for sw in net.switches:
        # 1. Ejecutar comando OVS: dump-flows
        # -O OpenFlow13: Usa protocolo 1.3
        # grep -c cookie: Cuenta las líneas que tienen 'cookie' (cada flujo tiene una)
        try:
            cmd_out = sw.cmd(f'ovs-ofctl dump-flows -O OpenFlow13 {sw.name} | grep -c cookie')
            count = int(cmd_out.strip())
            total_rules += count
            print(f"{sw.name:<12} | {count}")
        except:
            print(f"{sw.name:<12} | Error")
            
    print("-" * 30)
    print(f"Total Network Rules: {total_rules}\n")

# ==============================================================================
# MAIN RUNNER
# ==============================================================================
def run_network():
    # 1. OBTENCIÓN DE DATOS (MCS)
    info("--- LOADING MCS ALGORITHM & TOPOLOGY ---\n")
    # Llamamos a MCS una vez aquí para extraer todo lo necesario
    _, _, G = recovery_path() 
    # 2. INICIAR RED
    # Pasamos el grafo G a la topología para que se construya igual
    topo = MyTopology(G) 
    net = Mininet(topo=topo, controller=RemoteController, link=TCLink, waitConnected=True)
    net.start()
    info("[*] Network Started. Waiting for controller...\n")
    time.sleep(2)
    # 3. QoS CONFIG (Ambulance Lane)
    info("***CONFIGURING QoS***\n")
    for switch in net.switches:
        for intf in switch.intfList():
            if intf.name == 'lo': continue 
            # Configuración de Colas y Filtros para proteger el plano de control
            switch.cmd(f"ovs-vsctl set port {intf.name} qos=@newqos -- "
                       f"--id=@newqos create qos type=linux-htb other-config:max-rate=1000000000 queues:0=@q0 queues:1=@q1 -- "
                       f"--id=@q0 create queue other-config:min-rate=10000000 other-config:max-rate=900000000 -- "
                       f"--id=@q1 create queue other-config:min-rate=100000000 other-config:max-rate=1000000000")
            
            switch.cmd(f"tc filter add dev {intf.name} parent 1: prio 1 protocol 0x88cc flower flowid 1:2") # LLDP
            switch.cmd(f"tc filter add dev {intf.name} parent 1: prio 1 protocol 0x8942 flower flowid 1:2") # BDDP

    time.sleep(5) # Esperar descubrimiento
    net.pingAll() 
    check_flow_rules(net)
    # 4. INYECCIÓN DE TRÁFICO (EXTRACCIÓN DINÁMICA)
    print("\n--- READY TO INJECT TRAFFIC ---")
    answer = input("Run traffic from 'TestDataSet'? (y/n): ")
    
    if answer.lower() == 'y':
        folder_path = "/mnt/mainvolume/Backup/PROJECTS/SDN-IP/Hybrid+Network/Dataset/TestSet/abilene/"
        if os.path.isdir(folder_path):
            files = sorted([f for f in os.listdir(folder_path) if f.endswith(('.xml'))])
            Injector=TrafficInjector(net)
            
            for index, filename in enumerate(files):
                full_path = os.path.join(folder_path, filename)
                print(f"\n[Interval {index+1}/{len(files)}] Processing: {filename}")
                
                # Parsear (El factor 0.005 es tu ajuste de escala, cámbialo si quieres más carga)
                flows = Injector.parse(full_path, scaling_factor=0.005)            
                # Ejecutar
                Injector.inject_traffic(flows,duration=10)
                time.sleep(1) 
        else:
            print(f"[!] Folder '{folder_path}' not found.")
    
    info("Network ready. Type 'exit' to stop.\n")
    CLI(net)
    net.stop() 

if __name__== '__main__':
    setLogLevel('info')
    run_network()
