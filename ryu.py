# 1. Standard Python Libraries
import networkx as nx              # The "Brain" (Graph & Dijkstra)
# 2. Ryu Core Components
from ryu.base import app_manager   # The "Shell" (All Ryu apps inherit from this)
from ryu.controller import ofp_event # Defines events like "PacketIn"
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER # States of the switch
from ryu.controller.handler import set_ev_cls # The "Decorator" to trigger functions
# 3. OpenFlow Protocol
from ryu.ofproto import ofproto_v1_3 # The "Language" (We use OpenFlow 1.3)
from ryu.ofproto import ofproto_v1_3_parser as parser # <--- MISSING IMPORT ADDED HERE
# 4. Packet Decoding (To understand what's inside the binary data)
from ryu.lib.packet import packet, ethernet, arp, ipv4
# 5. Topology Discovery (The "Scout")
from ryu.topology import event     # To listen for link/switch events
from MCS import get_best_set

class MCS(app_manager.RyuApp):
    def __init__(self, *args, **kwargs):
        super(MCS, self).__init__(*args, **kwargs)

        self.net = nx.DiGraph()
        self.heroes=get_best_set()
        self.mac_port = {}
        self.names={1:'ATLA', 2:'CHIN', 3: 'DNVR', 4: 'HSTN', 5:'IPLS',
                    6: 'KSCY', 7:'LOSA', 8:'NYCM', 9:'SNVA', 10: 'STTL',
                    11: 'WASH'}
    # Listen for new links (LLDP) to build the graph
    
    @set_ev_cls(event.EventLinkAdd, MAIN_DISPATCHER)
    def get_topology_data(self, ev):
        link = ev.link
        src_dpid = link.src.dpid
        dst_dpid = link.dst.dpid
        src_port = link.src.port_no
        # Add the link to our graph
        self.net.add_edge(src_dpid, dst_dpid, port=src_port, weight=1)
        self.sfnet=nx.minimum_spanning_tree(self.net.to_undirected())    
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        if datapath.id in self.heroes:
            print(f"Hero switch {datapath.id} connected")
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        # Install the Table-Miss Flow Entry
        # "Match Everything" (priority=0) -> "Send to Controller"
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        
        # Build the Flow Mod message
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=0,
                                match=match, instructions=inst)
        
        # Send it to the switch
        datapath.send_msg(mod)
        print(f" Table-Miss Flow Installed on Switch {datapath.id}")
    # Listen for packets (PacketIn)
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        in_port = msg.match['in_port']

        # Decode the raw data
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        
        # Ignore LLDP packets (to prevent loops/errors)
        if eth.ethertype == 0x88cc: 
            return
        
        if eth.ethertype == 0x86dd: ## IGNORING IPV6 
            return

        src = eth.src
        dst = eth.dst

        self.logger.info(f"Packet in switch {dpid} source {src} destination {dst}, in port {in_port}")

        # Learn the location of the source
        # self.mac_port[src] = (dpid, in_port)
        #only UPDATE IF E HAVENT SEEN THIS MAC BEFORE
        if src not in self.mac_port:
            self.mac_port[src]=(dpid, in_port)
            print(f"Learned Location {src} is at switch {dpid} port {in_port}")
            
        if dst == 'ff:ff:ff:ff:ff:ff':
            actions = []
            # Debug: See if the tree actually exists!
            if dpid in self.sfnet:
                xname=self.names.get(dpid, f"Switch_{dpid}")
                neighbors = list(self.sfnet[dpid])
                print(f"Flooding from Switch {xname}. Tree Neighbors: {neighbors}")
                for neighbor in neighbors:
                    out_port = self.net[dpid][neighbor]['port']
                    if out_port != in_port:
                        actions.append(parser.OFPActionOutput(out_port))
        

            if in_port!= 1:
                actions.append(parser.OFPActionOutput(1))
        
            out= parser.OFPPacketOut(datapath=datapath,buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=msg.data)
            datapath.send_msg(out)  
            return 
        # Path calculation logic
        elif dst in self.mac_port:
            dst_switch = self.mac_port[dst][0]
            src_switch = self.mac_port[src][0]
            
            # Check if source and dest switches are in the graph
            if self.net.has_node(src_switch) and self.net.has_node(dst_switch):
                try:
                    paths = list(nx.all_shortest_paths(self.net, source=src_switch, target=dst_switch))
                    best_path = paths[0]
                    
                    # If we are at the destination switch
                    if dpid == best_path[-1]:
                        out_port = self.mac_port[dst][1]
                    else:
                        # Find the next hop
                        current_index = best_path.index(dpid)
                        next_switch = best_path[current_index + 1]
                        out_port = self.net[dpid][next_switch]['port']
                    print(f"PATH FOUND: {src} to {dst} via Port {out_port}")
                    #added after WHEN PING FLOOD BECAUSE OF FLOWMOD doesmnt exist
                    match=parser.OFPMatch(eth_dst=dst)
                    actions=parser.OFPActionOutput(out_port)
                    inst=[parser.OFPInstructionActions(ofproto_v1_3.OFPIT_APPLY_ACTIONS, [actions])]
                    mod=parser.OFPFlowMod(datapath=datapath,priority=1,
                                          match=match,instructions=inst)
                    datapath.send_msg(mod)
                    print(f"Rule installed : Dest: {dst} port{out_port}")
                except Exception as e :
                    # If graph exists but no path is found, flood
                    out_port = ofproto_v1_3.OFPP_FLOOD
                    print(f"crash : {e}")
            else:
                # If switches aren't in the graph yet, flood
                out_port = ofproto_v1_3.OFPP_FLOOD
                print(f"SWITCH NOT IN GRAPH YET. Proceed to FLOOD...")
        else:
            # Destination unknown, flood
            out_port = ofproto_v1_3.OFPP_FLOOD
            print(f"UNKNOWN DESTINATION: {dst} ... FLOODING")

        # Send the packet out
        actions = [parser.OFPActionOutput(out_port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=msg.buffer_id,  
                                  in_port=in_port, 
                                  actions=actions, 
                                  data=msg.data)
        datapath.send_msg(out)
