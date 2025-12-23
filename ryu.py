# 1. Standard Python Libraries
import networkx as nx
from datetime import datetime  # <--- ADDED FOR TIMESTAMPS

# 2. Ryu Core Components
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls

# 3. OpenFlow Protocol
from ryu.ofproto import ofproto_v1_3
from ryu.ofproto import ofproto_v1_3_parser as parser

# 4. Packet Decoding
from ryu.lib.packet import packet, ethernet, arp, ipv4

# 5. Topology Discovery
from ryu.topology import event
from MCS import get_best_set, plot_network, recovery_path
from abilene_topo import Abilene

class MCS(app_manager.RyuApp):
    def __init__(self, *args, **kwargs):
        super(MCS, self).__init__(*args, **kwargs)
        self.net = nx.DiGraph()
        self.sfnet = nx.Graph()
        self.top = Abilene()
        self.heroes = get_best_set()
              
        self.failover = recovery_path()
        self.mac_port = {}
        self.datapath = {}
        self.names = {1: 'ATLA', 2: 'CHIN', 3: 'DNVR', 4: 'HSTN', 5: 'IPLS',
                      6: 'KSCY', 7: 'LOSA', 8: 'NYCM', 9: 'SNVA', 10: 'STTL',
                      11: 'WASH'}
        hero_names = [self.get_name(h) for h in self.heroes]
        
        # Log initialization
        self.log_with_timestamp(f"The heroes will be Nodes: {hero_names}")

    def get_name(self, dpid):
        return self.names.get(dpid, f"Switch-{dpid}")

    # --- NEW HELPER METHOD FOR LOGGING ---
    def log_with_timestamp(self, message):
        # Format time as HH:MM:SS.ms
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {message}", flush=True)

    @set_ev_cls(event.EventLinkAdd, MAIN_DISPATCHER)
    def get_topology_data(self, ev):
        link = ev.link
        src = link.src.dpid
        dst = link.dst.dpid
        src_port = link.src.port_no
        
        self.net.add_edge(src, dst, port=src_port, weight=1)
        self.sfnet = nx.minimum_spanning_tree(self.net.to_undirected())
        
        if (src, dst) in self.failover:
            hero_id = self.failover[(src, dst)]
            datapath = link.src
            if src in self.datapath:
                datapath = self.datapath[src]
                ofproto = datapath.ofproto
                parser = datapath.ofproto_parser
            
            try:
                path_to_hero = nx.shortest_path(self.net, src, hero_id)
                if len(path_to_hero) > 1:
                    next_hop = path_to_hero[1]
                    hero_port = self.net[src][next_hop]['port']
                    src_name = self.get_name(src)
                    dst_name = self.get_name(dst)
                    hero_name = self.get_name(hero_id)

                    # LOGGING
                    self.log_with_timestamp(f"MCS PROTECTION READY: Link {src_name}->{dst_name} protected by HERO {hero_name}")
                    
                    # BUCKET 1: Primary (Queue 0)
                    actions_pri = [parser.OFPActionSetQueue(0), parser.OFPActionOutput(src_port)]
                    bucket_pri = parser.OFPBucket(watch_port=src_port, watch_group=ofproto.OFPG_ANY, actions=actions_pri)
                    
                    # BUCKET 2: Backup (Queue 0 + MPLS)
                    actions_backup = [
                        parser.OFPActionSetQueue(0),
                        parser.OFPActionPushMpls(ethertype=0x8847),
                        parser.OFPActionSetField(mpls_label=hero_id),
                        parser.OFPActionOutput(hero_port)
                    ]
                    bucket_backup = parser.OFPBucket(watch_port=ofproto.OFPP_ANY, watch_group=ofproto.OFPG_ANY, actions=actions_backup)

                    req = parser.OFPGroupMod(datapath, command=ofproto.OFPGC_ADD, type_=ofproto.OFPGT_FF,
                                             group_id=src_port, buckets=[bucket_pri, bucket_backup])
                    datapath.send_msg(req)
            except Exception as e:
                pass 

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        topo_app = app_manager.lookup_service_brick('switches')
        if topo_app:
            #  THE FIX: DISABLE TIMEOUT COMPLETELY
            topo_app.link_timeout = 3
            topo_app.link_discovery_interval = 1
            
        datapath = ev.msg.datapath
        dpid = datapath.id
        self.datapath[dpid] = datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        if dpid in self.heroes:
            match_hero = parser.OFPMatch(eth_type=0x8847, mpls_label=dpid)
            actions_hero = [parser.OFPActionPopMpls(ethertype=0x0800), parser.OFPActionOutput(ofproto.OFPP_TABLE)]
            inst_hero = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions_hero)]
            mod_hero = parser.OFPFlowMod(datapath=datapath, priority=100, match=match_hero, instructions=inst_hero)
            datapath.send_msg(mod_hero)
            
            # LOGGING
            self.log_with_timestamp(f"HERO NODE ONLINE: {self.get_name(dpid)} is ready to accept tunnels.")

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=0, match=match, instructions=inst)
        datapath.send_msg(mod)
        
        # INCOMING LLDP -> Queue 1
        match_lldp = parser.OFPMatch(eth_type=0x88cc)
        actions_lldp = [parser.OFPActionSetQueue(1), parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        inst_lldp = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions_lldp)]
        mod_lldp = parser.OFPFlowMod(datapath=datapath, priority=65535, match=match_lldp, instructions=inst_lldp)
        datapath.send_msg(mod_lldp)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        
        if eth.ethertype == 0x88cc or eth.ethertype == 0x86dd:
            return
            
        src = eth.src
        dst = eth.dst
        
        if src not in self.mac_port:
            self.mac_port[src] = (dpid, in_port)
            
        if dst == 'ff:ff:ff:ff:ff:ff':
            actions = []
            all_switch_ports = []
            if dpid in self.net:
                for neighbor in self.net[dpid]:
                    all_switch_ports.append(self.net[dpid][neighbor]['port'])
            if dpid in self.sfnet:
                for neighbor in self.sfnet[dpid]:
                    if neighbor in self.net[dpid]:
                        out_port = self.net[dpid][neighbor]['port']
                        if out_port != in_port:
                            actions.append(parser.OFPActionOutput(out_port))
            if 1 not in all_switch_ports and in_port != 1:
                actions.append(parser.OFPActionOutput(1))
            
            out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=msg.data)
            datapath.send_msg(out)
            return
            
        elif dst in self.mac_port:
            dst_switch = self.mac_port[dst][0]
            src_switch = self.mac_port[src][0]
            
            if self.net.has_node(src_switch) and self.net.has_node(dst_switch):
                try:
                    paths = list(nx.all_shortest_paths(self.net, source=src_switch, target=dst_switch))
                    best_path = paths[0]
                    if dpid == best_path[-1]:
                        out_port = self.mac_port[dst][1]
                        actions = [parser.OFPActionOutput(out_port)]
                    else:
                        current_index = best_path.index(dpid)
                        next_switch = best_path[current_index + 1]
                        out_port = self.net[dpid][next_switch]['port']
                        if (dpid, next_switch) in self.failover:
                            actions = [parser.OFPActionSetQueue(0), parser.OFPActionGroup(group_id=out_port)]
                        else:
                            actions = [parser.OFPActionSetQueue(0), parser.OFPActionOutput(out_port)]
                            
                    match = parser.OFPMatch(eth_dst=dst)
                    inst = [parser.OFPInstructionActions(ofproto_v1_3.OFPIT_APPLY_ACTIONS, actions)]
                    mod = parser.OFPFlowMod(datapath=datapath, priority=1, match=match, instructions=inst)
                    datapath.send_msg(mod)
                except Exception:
                    return
            else:
                out_port = ofproto_v1_3.OFPP_FLOOD
        else:
            out_port = ofproto_v1_3.OFPP_FLOOD

        out_actions = [parser.OFPActionSetQueue(0), parser.OFPActionOutput(out_port)]
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port, actions=out_actions, data=msg.data)
        datapath.send_msg(out)

    @set_ev_cls(event.EventLinkDelete, MAIN_DISPATCHER)
    def link_delete_handler(self, ev):
        link = ev.link
        src = link.src.dpid
        dst = link.dst.dpid
        try:
            self.net.remove_edge(src, dst)
            self.sfnet = nx.minimum_spanning_tree(self.net.to_undirected())
            
            # LOGGING
            self.log_with_timestamp(f"LINK FAILURE: {self.get_name(src)} -> {self.get_name(dst)} detected.")
            
            if (src, dst) in self.failover:
                hero_id = self.failover[(src, dst)]
                self.log_with_timestamp(f"MCS RECOVERY: Redirecting traffic to HERO {self.get_name(hero_id)} via Tunnel.")
                self.log_with_timestamp(f"  (Data is being encapsulated with MPLS Label {hero_id} automatically by Switch {self.get_name(src)})")
        except nx.NetworkXError:
            pass
