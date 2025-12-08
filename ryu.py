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
from MCS import plot_network
from MCS import recovery_path  
from abilene_topo import Abilene

class MCS(app_manager.RyuApp):
    def __init__(self, *args, **kwargs):
        super(MCS, self).__init__(*args, **kwargs)
        self.net = nx.DiGraph()
        self.sfnet = nx.Graph()
        self.top=Abilene()
        self.heroes=get_best_set()
        self.gra=plot_network(self.top.get_graph())
        self.failover=recovery_path()
        self.mac_port = {}
        self.datapath={}
        self.names={1:'ATLA', 2:'CHIN', 3: 'DNVR', 4: 'HSTN', 5:'IPLS',
                    6: 'KSCY', 7:'LOSA', 8:'NYCM', 9:'SNVA', 10: 'STTL',
                    11: 'WASH'}
    @set_ev_cls(event.EventLinkAdd, MAIN_DISPATCHER)
    def get_topology_data(self, ev):
        link = ev.link
        src = link.src.dpid
        dst = link.dst.dpid
        src_port = link.src.port_no 
        print(f"DEBUG: Link Detected {src} -> {dst}")     
        # 1. Update the Graph
        self.net.add_edge(src, dst, port=src_port, weight=1)
        self.sfnet = nx.minimum_spanning_tree(self.net.to_undirected())
        # 2. Check: Is this specific link (src->dst) part of a failure scenario?
        # We look up our pre-calculated dictionary
        if (src, dst) in self.failover:
            hero_id = self.failover[(src, dst)]
            datapath=link.src
            if src in self.datapath:
                datapath=self.datapath[src]
                ofproto=datapath.ofproto
                parser=datapath.ofproto_parser          
            # 3. Find the Port to the Hero
            # We need to know: To reach the Hero, which port do I exit?
            try:
                # Calculate path from Source -> Hero
                path_to_hero = nx.shortest_path(self.net, src, hero_id)
                next_hop = path_to_hero[1] # The switch directly after src      
                # Get the port on src that connects to next_hop
                hero_port = self.net[src][next_hop]['port']
                print(f"Protection: Link {src}->{dst} protected by Hero {hero_id} via Port {hero_port}")    
                # --- INSTALL THE FAST FAILOVER GROUP ---
               # BUCKET 1: Primary Path (The link we just found)
                actions_pri = [parser.OFPActionOutput(src_port)]
                bucket_pri = parser.OFPBucket(
                    watch_port=src_port, # Watch this specific interface
                    watch_group=ofproto.OFPG_ANY,
                    actions=actions_pri
                )
                # BUCKET 2: Backup Path (MPLS Tunnel to Hero)
                actions_backup = [
                    # A. Add the MPLS Header (The "Sticker")
                    parser.OFPActionPushMpls(ethertype=0x8847),    
                    # B. Write the Hero ID on the sticker
                    parser.OFPActionSetField(mpls_label=hero_id),   
                    # C. Send it to the Hero's direction
                    parser.OFPActionOutput(hero_port)
                ]
                bucket_backup = parser.OFPBucket(
                    watch_port=ofproto.OFPP_ANY, # Always ready
                    watch_group=ofproto.OFPG_ANY,
                    actions=actions_backup
                )

                # Create the Group
                # We use the 'src_port' as the Group ID for simplicity (Group 1 covers Port 1)
                req = parser.OFPGroupMod(
                    datapath,
                    command=ofproto.OFPGC_ADD,
                    type_=ofproto.OFPGT_FF, # Fast Failover
                    group_id=src_port,     
                    buckets=[bucket_pri, bucket_backup]
                )
                datapath.send_msg(req)
                self.logger.info(f"PROTECTION INSTALLED: {src}->{dst} (Port {src_port}) backed up by Hero {hero_id}")
                print(f"SUCCESS: Installed Group for {src} to {dst}")
            except nx.NetworkXNoPath:
                print(f"WARMING: No path to hero yet {src} to {dst}")
            except Exception as e:
                print(f"CRITICAL ERROR INSTALLING GROUP  {src} to {dst}: {e}")
        else: 
            self.logger.warning(f"Switch {src} is not connected yet!")
    # Listen for new links (LLDP) to build the graph
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        dpid=datapath.id
        self.datapath[dpid]=datapath
        ofproto=datapath.ofproto
        parser=datapath.ofproto_parser
        if dpid in self.heroes:
            #POPPING THE LABEL
            match_hero=parser.OFPMatch(eth_type=0x8847, mpls_label=dpid)
            actions_hero=[
                parser.OFPActionPopMpls(ethertype=0x0800), #removing label restore IPV4
                parser.OFPActionOutput(ofproto.OFPP_TABLE) # send back to table 0 to route as IP 
            ]
            inst_hero=[parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions_hero)]
            mod_hero=parser.OFPFlowMod(datapath=datapath, priority=100, #high priority
                                       match=match_hero, instructions=inst_hero) 
            datapath.send_msg(mod_hero)
            print(f"Hero Logic Installed on Switch {dpid}: Pop Label {dpid}")
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
        #only UPDATE IF E HAVENT SEEN THIS MAC BEFORE
        if src not in self.mac_port:
            self.mac_port[src]=(dpid, in_port)
            print(f"Learned Location {src} is at switch {dpid} port {in_port}")         
        if dst == 'ff:ff:ff:ff:ff:ff':
            actions = []
            all_switch_ports=[]
            #Identitiy all ports connected to other switches
            #check self.net to know which ports are Inter-Switch link
            if dpid in self.net:
                for neighbor in self.net[dpid]:
                    all_switch_ports.append(self.net[dpid][neighbor]['port'])
            #Flood along the spaning tree
            if dpid in self.sfnet:
                    tree_neighbors=list(self.sfnet[dpid])
                    #print(f"flooding from {dpid} to Three Neighbors: {tree neighbors}")
                    for neighbor in tree_neighbors:
                        if neighbor in self.net[dpid]:
                            out_port=self.net[dpid][neighbor]['port']
                            if out_port != in_port:
                                actions.append(parser.OFPActionOutput(out_port))
            #Loop prevention
            if 1 not in all_switch_ports:
                if in_port != 1:
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
                        actions=[parser.OFPActionOutput(out_port)]
                    else:
                        # Find the next hop
                        current_index = best_path.index(dpid)
                        next_switch = best_path[current_index + 1]
                        out_port = self.net[dpid][next_switch]['port']
                        if(dpid, next_switch) in self.failover:
                            actions=[parser.OFPActionGroup(group_id=out_port)]
                            self.logger.info(f"Using FAILOVER GROUP {out_port} for {src}")
                        else:
                            actions=[parser.OFPActionOutput(out_port)]
                    print(f"PATH FOUND: {src} to {dst} via Port {out_port}")
                    ###INSTALL THE MATCHFLOW
                    #added after WHEN PING FLOOD BECAUSE OF FLOWMOD doesmnt exist
                    match=parser.OFPMatch(eth_dst=dst)
                    inst=[parser.OFPInstructionActions(ofproto_v1_3.OFPIT_APPLY_ACTIONS, actions)]
                    mod=parser.OFPFlowMod(datapath=datapath,priority=1,
                                          match=match,instructions=inst)
                    datapath.send_msg(mod)
                    #ALSO SEND THE PACKET OUT SO THE FIRST PACKET NOT LOST
                    #out_actions= [parser_OFPActionOutput(out_port)]
                    #out=parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,in_port=in_portm actions=out_actions,data=msg.data)
                    #datapath.send_msg(out)
                    print(f"Rule installed : Dest: {dst} port{out_port}")
                except Exception as e :
                    # If graph exists but no path is found, flood
                    out_port = ofproto_v1_3.OFPP_FLOOD
                    print(f"crash : Path calculation ERROr {e}")
            else:
                # If switches aren't in the graph yet, flood
                out_port = ofproto_v1_3.OFPP_FLOOD
                print(f"SWITCH NOT IN GRAPH YET. Proceed to FLOOD...")
        else:
            # Destination unknown, flood
            out_port = ofproto_v1_3.OFPP_FLOOD
            print(f"UNKNOWN DESTINATION: {dst} ... FLOODING")

        # Send the packet out
        out_actions = [parser.OFPActionOutput(out_port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=msg.buffer_id,  
                                  in_port=in_port, 
                                  actions=out_actions, 
                                  data=msg.data)
        datapath.send_msg(out)
    @set_ev_cls(event.EventLinkDelete,MAIN_DISPATCHER)
    def link_delete_handler(self, ev):
        link=ev.link
        src=link.src.dpid
        dst=link.dst.dpid
        #Remove the edge from the main graph self.net 
        try:
            self.net.remove_edge(src,dst)
        except nx.NetworkXError:
            return
        self.sfnet = nx.minimum_spanning_tree(self.net.to_undirected())
        print(f"DEBUG: Link Removed {src}-> {dst}... Spaning Tree Updated")
