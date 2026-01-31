# 1. Standard Python Libraries
import networkx as nx
from datetime import datetime
from operator import attrgetter

# 2. Ryu Core Components
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib import hub  # <--- REQUIRED FOR BACKGROUND MONITORING

# 3. OpenFlow Protocol
from ryu.ofproto import ofproto_v1_3
from ryu.ofproto import ofproto_v1_3_parser as parser

# 4. Packet Decoding
from ryu.lib.packet import packet, ethernet, arp, ipv4

# 5. Topology Discovery
from ryu.topology import event

# 6. CUSTOM MODULES
from MCS import get_best_set, recovery_path
from topology import Abilene
from green_models import LegacyRouter, SDNSwitch # <--- IMPORTING YOUR PHYSICS ENGINE

class MCS(app_manager.RyuApp):
    def __init__(self, *args, **kwargs):
        super(MCS, self).__init__(*args, **kwargs)
        self.net = nx.DiGraph()
        self.sfnet = nx.Graph()
        self.top = Abilene()
        
        # 1. GET THE HEROES (SDN NODES)
        self.heroes = recovery_path()[0] #winner set
        
        # 2. CALCULATE FAILOVER MAP
        self.failover = recovery_path()[1] # MCS returns (set, map)
        
        self.mac_port = {}
        self.datapath = {}
        self.names = {1: 'ATLA', 2: 'CHIN', 3: 'DNVR', 4: 'HSTN', 5: 'IPLS',
                      6: 'KSCY', 7: 'LOSA', 8: 'NYCM', 9: 'SNVA', 10: 'STTL',
                      11: 'WASH'}
        
        # --- SHADOW TELEMETRY SYSTEM ---
        self.green_nodes = {}  # Stores {dpid: LegacyRouter/SDNSwitch Object}
        self.monitor_thread = hub.spawn(self._monitor) # Background Audit Thread

        hero_names = [self.get_name(h) for h in self.heroes]
        self.log_with_timestamp(f"The heroes (Green Nodes) are: {hero_names}")

    def get_name(self, dpid):
        return self.names.get(dpid, f"Switch-{dpid}")

    def log_with_timestamp(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {message}", flush=True)

    # --- BACKGROUND MONITOR (THE AUDITOR) ---
    def _monitor(self):
        """
        Wakes up every 5 seconds to calculate Network-Wide Power Consumption.
        """
        self.log_with_timestamp("Initializing Green Power Monitor...")
        while True:
            hub.sleep(5) # Audit window
            
            total_watts = 0.0
            print("\n--- [ENERGY AUDIT 5s] ---")
            
            for dpid, node_model in self.green_nodes.items():
                # 1. Update Physical State (Active Ports)
                if dpid in self.net:
                    node_model.set_active_ports(self.net.degree[dpid])
                
                # 2. Calculate Watts (Physics Formula)
                watts = node_model.get_power_watts(time_window_seconds=5.0)
                total_watts += watts
                
                # 3. Reset Counters for next window
                node_model.reset_control_counters()
                
                # Optional: Detailed Log per Node
                # print(f"  {self.get_name(dpid)} ({type(node_model).__name__}): {watts:.2f} W")
            
            print(f"  >>> TOTAL NETWORK POWER: {total_watts:.4f} Watts")
            print("-------------------------")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        topo_app = app_manager.lookup_service_brick('switches')
        if topo_app:
            topo_app.link_timeout = 3
            topo_app.link_discovery_interval = 1
            
        datapath = ev.msg.datapath
        dpid = datapath.id
        self.datapath[dpid] = datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # --- INSTANTIATE GREEN MODELS ---
        # If the node is in the 'heroes' list, it is SDN (Zodiac).
        # Otherwise, it is Legacy (NEC).
        if dpid in self.heroes:
            self.green_nodes[dpid] = SDNSwitch(dpid, self.get_name(dpid))
            self.log_with_timestamp(f"Registering {self.get_name(dpid)} as GREEN SDN SWITCH.")
            
            # Install Hero Rules (MPLS Pop)
            match_hero = parser.OFPMatch(eth_type=0x8847, mpls_label=dpid)
            actions_hero = [parser.OFPActionPopMpls(ethertype=0x0800), parser.OFPActionOutput(ofproto.OFPP_TABLE)]
            inst_hero = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions_hero)]
            mod_hero = parser.OFPFlowMod(datapath=datapath, priority=100, match=match_hero, instructions=inst_hero)
            datapath.send_msg(mod_hero)
        else:
            self.green_nodes[dpid] = LegacyRouter(dpid, self.get_name(dpid))
            self.log_with_timestamp(f"Registering {self.get_name(dpid)} as LEGACY ROUTER.")

        # Default Rules
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=0, match=match, instructions=inst)
        datapath.send_msg(mod)
        
        match_lldp = parser.OFPMatch(eth_type=0x88cc)
        actions_lldp = [parser.OFPActionSetQueue(1), parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        inst_lldp = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions_lldp)]
        mod_lldp = parser.OFPFlowMod(datapath=datapath, priority=65535, match=match_lldp, instructions=inst_lldp)
        datapath.send_msg(mod_lldp)

    @set_ev_cls(event.EventLinkAdd, MAIN_DISPATCHER)
    def get_topology_data(self, ev):
        link = ev.link
        src = link.src.dpid
        dst = link.dst.dpid
        src_port = link.src.port_no
        
        self.net.add_edge(src, dst, port=src_port, weight=1)
        self.sfnet = nx.minimum_spanning_tree(self.net.to_undirected())
        
        # --- INSTALL PROACTIVE GROUP TABLES (If applicable) ---
        if (src, dst) in self.failover:
            hero_id = self.failover[(src, dst)]
            if src in self.datapath:
                datapath = self.datapath[src]
                ofproto = datapath.ofproto
                parser = datapath.ofproto_parser
                
                try:
                    path_to_hero = nx.shortest_path(self.net, src, hero_id)
                    if len(path_to_hero) > 1:
                        next_hop = path_to_hero[1]
                        hero_port = self.net[src][next_hop]['port']
                        
                        # Fast Failover Group Logic
                        actions_pri = [parser.OFPActionSetQueue(0), parser.OFPActionOutput(src_port)]
                        bucket_pri = parser.OFPBucket(watch_port=src_port, watch_group=ofproto.OFPG_ANY, actions=actions_pri)
                        
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
                        self.log_with_timestamp(f"INSTALLED GROUP: {self.get_name(src)} -> {self.get_name(dst)} protected by {self.get_name(hero_id)}")
                except Exception:
                    pass

    @set_ev_cls(event.EventLinkDelete, MAIN_DISPATCHER)
    def link_delete_handler(self, ev):
        link = ev.link
        src = link.src.dpid
        dst = link.dst.dpid
        try:
            self.net.remove_edge(src, dst)
            self.sfnet = nx.minimum_spanning_tree(self.net.to_undirected())
            
            self.log_with_timestamp(f"LINK FAILURE: {self.get_name(src)} -> {self.get_name(dst)}")
            
            # --- ENERGY PHYSICS SIMULATION (THE CRITICAL PART) ---
            # We must tell the Green Model that a failure happened.
            if src in self.green_nodes:
                node_model = self.green_nodes[src]
                
                # IF LEGACY: Trigger the 'Convergence Storm' (High Energy)
                if isinstance(node_model, LegacyRouter):
                    self.log_with_timestamp(f"  [PHYSICS] Legacy Node {self.get_name(src)} Triggering OSPF Convergence (CPU Spike!)")
                    node_model.trigger_convergence()
                    
                # IF SDN: Trigger Hardware Failover (Zero Energy)
                elif isinstance(node_model, SDNSwitch):
                    self.log_with_timestamp(f"  [PHYSICS] SDN Node {self.get_name(src)} Triggering Fast Failover (Zero Energy)")
                    node_model.trigger_failover()

        except nx.NetworkXError:
            pass

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

        if dst in self.mac_port:
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
                        
                        # USE GROUP TABLE IF PROTECTED
                        if (dpid, next_switch) in self.failover:
                            actions = [parser.OFPActionSetQueue(0), parser.OFPActionGroup(group_id=out_port)]
                        else:
                            actions = [parser.OFPActionSetQueue(0), parser.OFPActionOutput(out_port)]
                            
                    match = parser.OFPMatch(eth_dst=dst)
                    inst = [parser.OFPInstructionActions(ofproto_v1_3.OFPIT_APPLY_ACTIONS, actions)]
                    mod = parser.OFPFlowMod(datapath=datapath, priority=1, match=match, instructions=inst)
                    datapath.send_msg(mod)
                    
                    # --- TELEMETRY: Count this as a PacketIn event ---
                    # Note: Legacy Routers count PacketIns as part of their "Control Plane Load"
                    if dpid in self.green_nodes:
                         # We manually increment, though for OSPF simulations usually only Link Failure matters
                         # self.green_nodes[dpid].control_events += 1
                         pass

                    out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=msg.data)
                    datapath.send_msg(out)
                    return
                except Exception:
                    return
        
        # Flooding
        out_port = ofproto_v1_3.OFPP_FLOOD
        out_actions = [parser.OFPActionSetQueue(0), parser.OFPActionOutput(out_port)]
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port, actions=out_actions, data=msg.data)
        datapath.send_msg(out)
