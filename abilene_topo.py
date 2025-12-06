from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel
class Abilene(Topo):
    def build(self):
        city_names = ['ATLA', 'CHIN', 'DNVR', 'HSTN', 'IPLS', 
                      'KSCY', 'LOSA', 'NYCM', 'SNVA', 'STTL', 'WASH']
        
        switches = {}
        
        # 1. Crear Switches y Hosts (Conexión local rápida: 1Gbps, 0ms)
        for i, real_name in enumerate(city_names, start=1):
            switches[real_name] = self.addSwitch(real_name, dpid=hex(i)[2:], protocols='OpenFlow13')
            h = self.addHost(f'h_{real_name}')
            self.addLink(h, switches[real_name], bw=1000, delay='0ms')
        
    
        

        self.addLink(switches['NYCM'], switches['WASH'], bw=10000, delay='1.64ms') 
        self.addLink(switches['NYCM'], switches['CHIN'], bw=10000, delay='5.73ms') 
        self.addLink(switches['WASH'], switches['ATLA'], bw=10000, delay='4.37ms') 
        self.addLink(switches['ATLA'], switches['HSTN'], bw=10000, delay='5.67ms') 
        self.addLink(switches['HSTN'], switches['LOSA'], bw=10000, delay='11.03ms') 
        self.addLink(switches['LOSA'], switches['SNVA'], bw=10000, delay='2.50ms') 
        self.addLink(switches['SNVA'], switches['STTL'], bw=10000, delay='5.69ms') 
        self.addLink(switches['STTL'], switches['DNVR'], bw=10000, delay='8.22ms') 
        self.addLink(switches['DNVR'], switches['KSCY'], bw=10000, delay='3.71ms') 
        self.addLink(switches['KSCY'], switches['IPLS'], bw=10000, delay='4.52ms') 
        self.addLink(switches['IPLS'], switches['CHIN'], bw=10000, delay='1.30ms') 
        
        self.addLink(switches['ATLA'], switches['IPLS'], bw=10000, delay='2.95ms') 
        self.addLink(switches['HSTN'], switches['KSCY'], bw=10000, delay='5.13ms') 
        self.addLink(switches['DNVR'], switches['SNVA'], bw=10000, delay='7.57ms')

def run_network():

    topo=Abilene()
    net=Mininet(topo=topo, controller=RemoteController, waitConnected=True)
    net.start()
    print("Starting Network")
    print("Networkk's ready, type 'exit' to stop")
    CLI(net)

if __name__== '__main__':
    setLogLevel('info')
    run_network()


