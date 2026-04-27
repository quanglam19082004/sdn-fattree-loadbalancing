from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI

class FatTree(Topo):
    def build(self, k=4):
        self.k = k
        self.pod = k
        self.iCoreLayer  = (k // 2) ** 2
        self.iAggLayer   = (k // 2) * k
        self.iEdgeLayer  = (k // 2) * k
        self.iHost       = self.iEdgeLayer * (k // 2)

        # -------------------------------------------------------
        # DPID layout (k=4):
        #   Core switches : DPID  1 ..  4   (4 switches)
        #   Agg  switches : DPID  5 .. 12   (8 switches)
        #   Edge switches : DPID 13 .. 20   (8 switches)
        # -------------------------------------------------------
        core_dpid_base = 1
        agg_dpid_base  = core_dpid_base + self.iCoreLayer        # 5
        edge_dpid_base = agg_dpid_base  + self.iAggLayer         # 13

        # --- Core switches ---
        core_switches = []
        for i in range(self.iCoreLayer):
            dpid = core_dpid_base + i
            sw   = self.addSwitch('c{}'.format(i + 1),
                                  dpid='{:016x}'.format(dpid))
            core_switches.append(sw)

        # --- Pods ---
        agg_idx  = 0
        edge_idx = 0

        for p in range(self.pod):
            agg_switches  = []
            edge_switches = []

            # Aggregation switches
            for a in range(k // 2):
                dpid = agg_dpid_base + agg_idx
                sw   = self.addSwitch('a{}{}'.format(p + 1, a + 1),
                                      dpid='{:016x}'.format(dpid))
                agg_switches.append(sw)
                agg_idx += 1

            # Edge switches
            for e in range(k // 2):
                dpid = edge_dpid_base + edge_idx
                sw   = self.addSwitch('e{}{}'.format(p + 1, e + 1),
                                      dpid='{:016x}'.format(dpid))
                edge_switches.append(sw)
                edge_idx += 1

            # Kết nối Agg <-> Edge
            for agg in agg_switches:
                for edge in edge_switches:
                    self.addLink(agg, edge)

            # Kết nối Core <-> Agg
            for a in range(k // 2):
                for c in range(k // 2):
                    self.addLink(agg_switches[a],
                                 core_switches[a * (k // 2) + c])

            # Tạo và kết nối Host -> Edge
            for e in range(k // 2):
                for h in range(k // 2):
                    host = self.addHost('h{}{}{}'.format(p + 1, e + 1, h + 1))
                    self.addLink(edge_switches[e], host)


def run():
    topo = FatTree(k=4)
    net  = Mininet(topo=topo,
                   controller=RemoteController,
                   switch=OVSSwitch,
                   link=TCLink)
    net.start()
    print("*** Topology Fat-Tree k=4 da san sang!")
    print("*** DPID layout:")
    print("***   Core  c1..c4  -> DPID  1.. 4")
    print("***   Agg   a11..   -> DPID  5..12")
    print("***   Edge  e11..   -> DPID 13..20")
    CLI(net)
    net.stop()


if __name__ == '__main__':
    run()