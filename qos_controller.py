#!/usr/bin/env python3
"""
SDN QoS Project - RYU Controller with IDAN Support
Team: Anuj, Varun, Karthik, Narain

What this app does:
  1. Normal L2 learning switch behaviour for everything (ARP, ping, etc.)
     so the network isn't broken for anything you didn't explicitly classify.
  2. Special-case flow rules for our two test flows:
       - UDP dst port 5001  ("video call")     -> queue 0 (priority, near-full rate)
       - TCP dst port 5002  ("movie download")  -> queue 1 (rate-capped)
     These rules use the OFPActionSetQueue action, which tells the switch
     which OVS queue to place the packet in on its way out.
  3. IDAN intent layer:
       - On every switch connect (or reconnect), reads data/intents.json and
         re-installs all stored drop rules via sync_switch() — this provides
         automatic recovery after a controller restart.
       - REST endpoints:
           POST /idan/reload  — sync all connected switches
           GET  /idan/flows   — list IDAN rules currently in the flow table
       - All IDAN-installed flows are tagged with IDAN_COOKIE so they can be
         bulk-deleted and re-installed in one operation.

IMPORTANT: The queue IDs used here (0 and 1) must match the queue IDs you
create with setup_queues.sh on the same switch/port, or this does nothing
useful -- the packet will just go out the default queue.

Run:
    ryu-manager qos_controller.py
"""

import json
import os

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, ipv4, udp, tcp
from ryu.app.wsgi import WSGIApplication, ControllerBase, route, Response

import json as _json

# --- Config you'll want to tweak live during the demo -----------------
VIDEO_UDP_PORT = 5001   # "video call" traffic
BULK_TCP_PORT = 5002    # "movie download" traffic
PRIORITY_QUEUE_ID = 0   # must exist on the switch port (see setup_queues.sh)
CAPPED_QUEUE_ID = 1
QOS_FLOW_PRIORITY = 100  # higher than the default table-miss / L2 rules
# ------------------------------------------------------------------------

# --- IDAN constants -------------------------------------------------------
IDAN_COOKIE  = 0x1DA0
ALL_64       = 0xFFFFFFFFFFFFFFFF   # cookie mask: match all 64 bits
IDAN_PRIORITY = 200                  # drop rules sit above QoS (100) and L2 (1)
# --------------------------------------------------------------------------

# Path to intents.json (resolved relative to this file)
_HERE         = os.path.dirname(os.path.abspath(__file__))
_INTENTS_PATH = os.path.join(_HERE, "data", "intents.json")


def _load_rules() -> list:
    """Read data/intents.json and return a flat list of all rule dicts."""
    try:
        with open(_INTENTS_PATH) as f:
            intents = json.load(f)
        rules = []
        for intent in intents:
            rules.extend(intent.get("rules", []))
        return rules
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# REST API (WSGI)
# ---------------------------------------------------------------------------

class IDANRestController(ControllerBase):
    """Handles /idan/reload and /idan/flows endpoints."""

    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self.qos_switch_app = data["qos_switch_app"]

    @route("idan", "/idan/reload", methods=["POST"])
    def reload(self, req, **kwargs):
        """Re-sync all connected switches from intents.json."""
        app = self.qos_switch_app
        synced = []
        for dpid, dp in list(app.datapaths.items()):
            app.sync_switch(dp)
            synced.append(dpid)
        body = _json.dumps({"status": "ok", "synced_switches": synced})
        return Response(
            status=200,
            content_type="application/json",
            body=body.encode()
        )

    @route("idan", "/idan/flows", methods=["GET"])
    def list_flows(self, req, **kwargs):
        """Return the current IDAN rules from intents.json (not from the switch)."""
        rules = _load_rules()
        body = _json.dumps(rules)
        return Response(
            status=200,
            content_type="application/json",
            body=body.encode()
        )


# ---------------------------------------------------------------------------
# Main controller app
# ---------------------------------------------------------------------------

class QosSwitch(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(QosSwitch, self).__init__(*args, **kwargs)
        self.mac_to_port = {}   # {dpid: {mac: port}} -- standard L2 learning table
        self.datapaths   = {}   # {dpid: datapath} -- for reload

        # Register WSGI routes
        wsgi = kwargs["wsgi"]
        wsgi.register(IDANRestController, {"qos_switch_app": self})

    # ---- IDAN: sync one switch -------------------------------------------

    def sync_switch(self, dp):
        """
        Delete all IDAN-tagged flows on *dp*, then re-install every rule from
        intents.json for that switch.  This is the single operation used for:
          - Initial install (after switch connect)
          - Reload triggered by the CLI (POST /idan/reload)
          - Recovery after controller restart (switch_features_handler fires again)
        """
        ofp    = dp.ofproto
        parser = dp.ofproto_parser

        # Step 1: delete all previously installed IDAN flows on this switch
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp,
            cookie=IDAN_COOKIE,
            cookie_mask=ALL_64,
            table_id=ofp.OFPTT_ALL,
            command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY,
            out_group=ofp.OFPG_ANY,
        ))

        # Step 2: install every saved rule for this switch
        # "empty instructions = drop" (no actions means packet is dropped)
        for r in _load_rules():
            if r.get("dpid") == dp.id:
                match_fields = r.get("match", {})
                match = parser.OFPMatch(**match_fields)
                # instructions=[] means DROP
                dp.send_msg(parser.OFPFlowMod(
                    datapath=dp,
                    cookie=IDAN_COOKIE,
                    priority=r.get("priority", IDAN_PRIORITY),
                    match=match,
                    instructions=[],   # drop
                ))

        self.logger.info("IDAN: synced switch %s (%d rules loaded)",
                         dp.id, len([r for r in _load_rules() if r.get("dpid") == dp.id]))

    # ---- Controller/switch handshake ----------------------------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        dpid     = datapath.id

        # Remember the datapath for later reloads
        self.datapaths[dpid] = datapath

        # Table-miss rule: anything unmatched goes to the controller.
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                           ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.logger.info("Switch %s connected, table-miss rule installed", dpid)

        # IDAN: re-install all saved intents for this switch.
        # This provides automatic recovery when the controller restarts and
        # the switch reconnects.
        self.sync_switch(datapath)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None,
                 idle_timeout=0):
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        inst    = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                     priority=priority, match=match,
                                     instructions=inst, idle_timeout=idle_timeout)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                     match=match, instructions=inst,
                                     idle_timeout=idle_timeout)
        datapath.send_msg(mod)

    # ---- Main packet handler -------------------------------------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg      = ev.msg
        datapath = msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        dpid     = datapath.id
        in_port  = msg.match['in_port']

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
            # Only install SET_QUEUE on switches that actually have queues (s1).
            # On other switches, fall through to normal L2 forwarding.
            if dpid == 1:  # s1 is the only switch with queues
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
                # Non-queue switch: install a plain L2 forwarding rule
                actions = [parser.OFPActionOutput(out_port)]
                match   = parser.OFPMatch(in_port=in_port, eth_dst=dst)
                self.add_flow(datapath, 1, match, actions, idle_timeout=30)
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
