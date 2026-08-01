#!/usr/bin/env python3
"""
SDN QoS Project - RYU Controller
Team: [fill in]

What this app does:
  1. Normal L2 learning switch behaviour for everything (ARP, ping, etc.)
     so the network isn't broken for anything you didn't explicitly classify.
  2. Special-case flow rules for our two test flows:
       - UDP dst port 5001  ("video call")     -> queue 0 (priority, near-full rate)
       - TCP dst port 5002  ("movie download")  -> queue 1 (rate-capped)
     These rules use the OFPActionSetQueue action, which tells the switch
     which OVS queue to place the packet in on its way out.

IMPORTANT: The queue IDs used here (0 and 1) must match the queue IDs you
create with setup_queues.sh on the same switch/port, or this does nothing
useful -- the packet will just go out the default queue.

Run:
    ryu-manager qos_controller.py
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, ipv4, udp, tcp

# --- Config you'll want to tweak live during the demo -----------------
VIDEO_UDP_PORT = 5001   # "video call" traffic
BULK_TCP_PORT = 5002    # "movie download" traffic
PRIORITY_QUEUE_ID = 0   # must exist on the switch port (see setup_queues.sh)
CAPPED_QUEUE_ID = 1
QOS_FLOW_PRIORITY = 100  # higher than the default table-miss / L2 rules
# ------------------------------------------------------------------------


class QosSwitch(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(QosSwitch, self).__init__(*args, **kwargs)
        self.mac_to_port = {}   # {dpid: {mac: port}} -- standard L2 learning table

    # ---- Controller/switch handshake ----------------------------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Table-miss rule: anything unmatched goes to the controller.
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                           ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.logger.info("Switch %s connected, table-miss rule installed",
                          datapath.id)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None,
                 idle_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                              actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                     priority=priority, match=match,
                                     instructions=inst,
                                     idle_timeout=idle_timeout)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                     match=match, instructions=inst,
                                     idle_timeout=idle_timeout)
        datapath.send_msg(mod)

    # ---- Main packet handler -------------------------------------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return  # ignore LLDP

        dst = eth.dst
        src = eth.src

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        # --- Check if this is one of our QoS-classified flows -----------
        queue_id, proto_num, dst_port = self._classify_for_qos(pkt)

        if queue_id is not None and out_port != ofproto.OFPP_FLOOD:
            actions = [parser.OFPActionSetQueue(queue_id),
                       parser.OFPActionOutput(out_port)]
            match = parser.OFPMatch(
                in_port=in_port,
                eth_type=ether_types.ETH_TYPE_IP,
                ip_proto=proto_num,
                **({'udp_dst': dst_port} if proto_num == 17 else
                   {'tcp_dst': dst_port})
            )
            self.add_flow(datapath, QOS_FLOW_PRIORITY, match, actions,
                           idle_timeout=30)
            self.logger.info(
                "QoS rule installed on switch %s: -> queue %s, out port %s",
                dpid, queue_id, out_port)
        else:
            actions = [parser.OFPActionOutput(out_port)]
            if out_port != ofproto.OFPP_FLOOD:
                match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
                self.add_flow(datapath, 1, match, actions, idle_timeout=30)

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                   in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    # ---- Classification helper ------------------------------------------
    def _classify_for_qos(self, pkt):
        """Return (queue_id, ip_proto_number, dst_port) for the two test
        flows we care about, or (None, None, None) for everything else
        (which just falls through to normal L2 forwarding)."""
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt is None:
            return None, None, None

        udp_pkt = pkt.get_protocol(udp.udp)
        if udp_pkt and udp_pkt.dst_port == VIDEO_UDP_PORT:
            return PRIORITY_QUEUE_ID, 17, VIDEO_UDP_PORT   # 17 = UDP

        tcp_pkt = pkt.get_protocol(tcp.tcp)
        if tcp_pkt and tcp_pkt.dst_port == BULK_TCP_PORT:
            return CAPPED_QUEUE_ID, 6, BULK_TCP_PORT       # 6 = TCP

        return None, None, None
