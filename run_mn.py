from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel
from abilene_topo import Abilene
from mininet.topo import Topo
from abilene_topo import Abilene

class Topology(Topo):
    def __init__(self, *args, **params):
        super().__init__(*args, **params)
        topo=Abilene()
        switches = {}
        # 1. Crear Switches y Hosts (Conexión local rápida: 1Gbps, 0ms)
        for i in topo.city_names:
                dpid_int=topo.citiesID[i]
                dpid_hex="{:016x}".format(dpid_int)
                switches[i] = self.addSwitch(i, dpid=dpid_hex, protocols='OpenFlow13')
                h = self.addHost(f'h_{i}')
                self.addLink(h, switches[i], bw=1000, delay='0ms')
        
        for u,v,bw, delay in topo.links:
            self.addLink(switches[u],switches[v], bw=bw,delay=delay)
def run_network():
    topo=Topology()
    net=Mininet(topo=topo, controller=RemoteController, waitConnected=True)
    net.start()
    print("Starting the network")
    print("Networok is ready , type exit to stop")
    CLI(net)
    net.stop()


if __name__== '__main__':
    setLogLevel('info')
    run_network()
