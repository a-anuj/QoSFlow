#!/usr/bin/env python3
"""
SDN QoS Project - Topology (10 Switches, 20 Hosts)

Layout:
    h1,h2 --- s1 ===(10Mbps bottleneck)=== s2 --- h3,h4
                                             |
                                            s3 --- h5,h6
                                             |
                                            s4 --- h7,h8
                                             |
                                            s5 --- h9,h10
                                             |
                                            s6 --- h11,h12
                                             |
                                            s7 --- h13,h14
                                             |
                                            s8 --- h15,h16
                                             |
                                            s9 --- h17,h18
                                             |
                                           s10 --- h19,h20

Switches 1 and 2:
    s1: h1 (video sender), h2 (download sender) - Has QoS queues on s1-eth3
    s2: h3 (video receiver / staff), h4 (staff)
    s1 <-> s2: 10 Mbps shared bottleneck link (UNTOUCHED)

Switches 3..10:
    s3: h5 (server), h6 (guest)
    s4: h7 (staff), h8 (staff)
    s5: h9 (staff), h10 (staff)
    s6: h11 (guest), h12 (guest)
    s7: h13 (guest), h14 (guest)
    s8: h15 (server), h16 (server)
    s9: h17 (server), h18 (server)
    s10: h19 (staff), h20 (staff)

Run:
    sudo python3 topology.py
Then in the mininet CLI:
    mininet> pingall
"""

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info


def build_network():
    net = Mininet(controller=RemoteController, switch=OVSSwitch,
                  link=TCLink, autoSetMacs=True)

    info('*** Adding controller (make sure ryu-manager is already running)\n')
    c0 = net.addController('c0', controller=RemoteController,
                           ip='127.0.0.1', port=6633)

    info('*** Adding switches s1..s10\n')
    switches = {}
    for i in range(1, 11):
        sname = f's{i}'
        switches[sname] = net.addSwitch(sname, protocols='OpenFlow13')

    s1 = switches['s1']
    s2 = switches['s2']

    info('*** Adding hosts h1..h20\n')
    hosts = {}
    for i in range(1, 21):
        hname = f'h{i}'
        hosts[hname] = net.addHost(hname, ip=f'10.0.0.{i}/24')

    info('*** Connecting hosts to switches (2 hosts per switch)\n')
    # Host-to-switch attachments:
    # Each switch s_i gets h_(2i-1) and h_(2i)
    for i in range(1, 11):
        sw = switches[f's{i}']
        h_a = hosts[f'h{2*i - 1}']
        h_b = hosts[f'h{2*i}']
        net.addLink(h_a, sw)
        net.addLink(h_b, sw)

    info('*** Creating inter-switch links\n')
    # The bottleneck: s1 <-> s2 (untouched, 10 Mbps shared pipe for QoS)
    net.addLink(s1, s2, cls=TCLink, bw=10, delay='2ms')

    # s2 <-> s3 ... s9 <-> s10
    for i in range(2, 10):
        sw_curr = switches[f's{i}']
        sw_next = switches[f's{i+1}']
        net.addLink(sw_curr, sw_next, cls=TCLink, bw=10, delay='2ms')

    info('*** Starting network\n')
    net.build()
    c0.start()
    for sw in switches.values():
        sw.start([c0])

    info('*** Network is up (10 switches, 20 hosts). Run pingall to verify connectivity.\n')
    CLI(net)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    build_network()
