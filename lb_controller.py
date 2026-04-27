"""
Fat-Tree k=4 SDN Controller - v9 (Fix intra-pod routing)
=========================================================
BUG FIX: Agg switch khi nhận từ edge phải flood đến TẤT CẢ port còn lại
(cả edge khác lẫn core), không chỉ uplink core.

Lý do: h111→h121 (cùng pod, khác edge) đi qua đường:
  e11 → a11 → e12 → h121   (KHÔNG qua core)
Nếu a11 chỉ flood lên core thì e12 không bao giờ nhận được ARP!

Split-horizon đúng cho Fat-Tree:
  AGG nhận từ AGG_DOWN(edge) → flood đến tất cả (edge khác + core)
  AGG nhận từ AGG_UP(core)   → chỉ flood xuống edge (không gửi ngược core)
  EDGE nhận từ host          → flood đến tất cả (uplink + host còn lại)
  EDGE nhận từ uplink        → chỉ flood xuống host
  CORE                       → flood đến tất cả trừ in_port

DPID: Core 1-4 | Agg 5-12 | Edge 13-20
Port: Edge {1,2}=uplink->agg | {3,4}=host
      Agg  {1,2}=downlink->edge | {3,4}=uplink->core
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (CONFIG_DISPATCHER, MAIN_DISPATCHER,
                                    set_ev_cls)
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp
from ryu.lib import hub

CORE_START=1;  CORE_END=4
AGG_START=5;   AGG_END=12
EDGE_START=13; EDGE_END=20

EDGE_UPLINK = {1, 2}   # edge  → agg
EDGE_HOST   = {3, 4}   # edge  → host
AGG_DOWN    = {1, 2}   # agg   → edge
AGG_UP      = {3, 4}   # agg   → core


def sw_type(dpid):
    if CORE_START  <= dpid <= CORE_END:  return 'core'
    if AGG_START   <= dpid <= AGG_END:   return 'aggregation'
    if EDGE_START  <= dpid <= EDGE_END:  return 'edge'
    return 'unknown'


class FatTreeHybridController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(FatTreeHybridController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}  # {dpid: {mac: port}}
        self.datapaths   = {}  # {dpid: datapath}
        self.port_stats  = {}  # {dpid: {port_no: bytes_total}}
        self.monitor_thread = hub.spawn(self._monitor)

    # =========================================================================
    # SWITCH KẾT NỐI
    # =========================================================================
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        dpid     = datapath.id

        self.datapaths[dpid]   = datapath
        self.mac_to_port[dpid] = {}

        self.logger.info("[CONNECT] DPID=%-3s  type=%s", dpid, sw_type(dpid))

        for et in [ether_types.ETH_TYPE_LLDP, 0x86DD]:
            self.add_flow(datapath, 65535,
                          parser.OFPMatch(eth_type=et), [])

        # OFPCML_NO_BUFFER: switch gửi toàn bộ gói lên controller
        self.add_flow(datapath, 0,
                      parser.OFPMatch(),
                      [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                              ofproto.OFPCML_NO_BUFFER)])

    # =========================================================================
    # PACKET IN
    # =========================================================================
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg      = ev.msg
        datapath = msg.datapath
        in_port  = msg.match['in_port']
        dpid     = datapath.id

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype in [ether_types.ETH_TYPE_LLDP, 0x86DD]:
            return

        src = eth.src
        dst = eth.dst

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        # ARP và Broadcast: flood split-horizon
        if (eth.ethertype == ether_types.ETH_TYPE_ARP or
                dst == 'ff:ff:ff:ff:ff:ff'):
            self._flood(datapath, in_port, msg.data)
            return

        # Unicast: định tuyến + cân bằng tải
        out_port = self._select_port(dpid, in_port, dst)
        if out_port is not None:
            match = datapath.ofproto_parser.OFPMatch(
                in_port=in_port, eth_dst=dst, eth_src=src)
            self._install_flow_and_send(datapath, match, out_port,
                                        in_port, msg.data)
        else:
            self._flood(datapath, in_port, msg.data)

    # =========================================================================
    # CHỌN PORT (Least Loaded Path)
    # =========================================================================
    def _select_port(self, dpid, in_port, dst_mac):
        stype   = sw_type(dpid)
        mac_tbl = self.mac_to_port.get(dpid, {})
        stats   = self.port_stats.get(dpid, {})

        if stype == 'edge':
            if in_port in EDGE_HOST:
                # Từ host: nếu đích cùng edge thì gửi thẳng
                if dst_mac in mac_tbl and mac_tbl[dst_mac] in EDGE_HOST:
                    return mac_tbl[dst_mac]
                # Ngược lại: chọn uplink ít tải hơn
                p1, p2 = stats.get(1, 0), stats.get(2, 0)
                chosen = 1 if p1 <= p2 else 2
                self.logger.info("[LB-EDGE] dpid=%-3s -> port %s (P1:%d P2:%d)",
                                 dpid, chosen, p1, p2)
                return chosen
            else:
                # Từ uplink: phải biết đích ở host port nào
                return mac_tbl.get(dst_mac)

        elif stype == 'aggregation':
            if in_port in AGG_DOWN:
                # Từ edge: nếu biết đích ở edge port nào thì gửi thẳng
                if dst_mac in mac_tbl and mac_tbl[dst_mac] in AGG_DOWN:
                    return mac_tbl[dst_mac]
                # Ngược lại: chọn uplink core ít tải hơn
                p3, p4 = stats.get(3, 0), stats.get(4, 0)
                chosen = 3 if p3 <= p4 else 4
                self.logger.info("[LB-AGG]  dpid=%-3s -> port %s (P3:%d P4:%d)",
                                 dpid, chosen, p3, p4)
                return chosen
            else:
                # Từ core: phải biết đích ở edge port nào
                return mac_tbl.get(dst_mac)

        elif stype == 'core':
            return mac_tbl.get(dst_mac)

        return None

    # =========================================================================
    # FLOOD SPLIT-HORIZON
    # =========================================================================
    def _flood(self, datapath, in_port, data):
        """
        Quy tắc flood split-horizon cho Fat-Tree:

        EDGE:
          host (3,4) → tất cả (uplink 1,2 + host còn lại)
          uplink(1,2) → chỉ host (3,4)

        AGG:
          edge(1,2) → TẤT CẢ port còn lại (edge khác + core)
                      ← KEY FIX: cần gửi sang edge khác cho intra-pod!
          core(3,4) → chỉ edge (1,2)  [không gửi ngược lên core khác]

        CORE:
          bất kỳ   → tất cả trừ in_port
        """
        dpid  = datapath.id
        stype = sw_type(dpid)
        phys  = self._get_ports(datapath)

        if not phys:
            self._send(datapath, in_port,
                       datapath.ofproto.OFPP_FLOOD, data)
            return

        out = [p for p in phys if p != in_port]

        if stype == 'edge':
            if in_port in EDGE_HOST:
                targets = out                              # lên uplink + host còn lại
            else:
                targets = [p for p in out if p in EDGE_HOST]  # chỉ xuống host

        elif stype == 'aggregation':
            if in_port in AGG_DOWN:
                targets = out                              # TẤT CẢ: edge khác + core
            else:
                targets = [p for p in out if p in AGG_DOWN]   # chỉ xuống edge

        elif stype == 'core':
            targets = out                                  # tất cả trừ in_port

        else:
            targets = out

        for p in targets:
            self._send(datapath, in_port, p, data)

    def _get_ports(self, datapath):
        ofproto = datapath.ofproto
        if hasattr(datapath, 'ports'):
            return [p for p in datapath.ports if p < ofproto.OFPP_MAX]
        return []

    # =========================================================================
    # HELPERS
    # =========================================================================
    def add_flow(self, datapath, priority, match, actions,
                 idle_timeout=0, hard_timeout=0):
        parser  = datapath.ofproto_parser
        ofproto = datapath.ofproto
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, priority=priority,
            match=match, instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout))

    def _install_flow_and_send(self, datapath, match, out_port,
                                in_port, data):
        parser = datapath.ofproto_parser
        self.add_flow(datapath, 1, match,
                      [parser.OFPActionOutput(out_port)],
                      idle_timeout=60)
        self._send(datapath, in_port, out_port, data)

    def _send(self, datapath, in_port, out_port, data):
        """Luôn dùng OFP_NO_BUFFER + data thật."""
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=in_port,
            actions=[parser.OFPActionOutput(out_port)],
            data=data)
        datapath.send_msg(out)

    # =========================================================================
    # STATE CHANGE
    # =========================================================================
    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, CONFIG_DISPATCHER])
    def _state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
        else:
            self.datapaths.pop(dp.id, None)

    # =========================================================================
    # TRAFFIC MONITORING
    # =========================================================================
    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                dp.send_msg(
                    dp.ofproto_parser.OFPPortStatsRequest(
                        dp, 0, dp.ofproto.OFPP_ANY))
            hub.sleep(5)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        self.port_stats.setdefault(dpid, {})
        for stat in ev.msg.body:
            total = stat.tx_bytes + stat.rx_bytes
            prev  = self.port_stats[dpid].get(stat.port_no, 0)
            delta = total - prev
            self.port_stats[dpid][stat.port_no] = total
            if delta > 0:
                self.logger.debug("[STATS] dpid=%-3s port=%-3s +%d B/5s",
                                  dpid, stat.port_no, delta)