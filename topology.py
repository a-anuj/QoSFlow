#!/usr/bin/env python3
"""
SDN QoS Project - Topology
Team: [fill in]

Layout:
    h1,h2 --- s1 ===(10Mbps bottleneck)=== s2 --- h3,h4
                                             |
                                            s3 --- h5,h6

h1 = "video call" host   (sends UDP, port 5001)
h2 = "movie download" host (sends TCP, port 5002)
h3 = receiver for both flows above (this is where contention actually shows up)

The s1<->s2 link is deliberately capped to 10Mbps with TCLink so there's a
real, finite pipe to fight over -- otherwise on a fast loopback link nothing
ever congests and you won't see any QoS effect at all.

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

    info('*** Adding switches\n')
    s1 = net.addSwitch('s1', protocols='OpenFlow13')
    s2 = net.addSwitch('s2', protocols='OpenFlow13')
    s3 = net.addSwitch('s3', protocols='OpenFlow13')

    info('*** Adding hosts\n')
    h1 = net.addHost('h1', ip='10.0.0.1/24')  # video call sender
    h2 = net.addHost('h2', ip='10.0.0.2/24')  # movie download sender
    h3 = net.addHost('h3', ip='10.0.0.3/24')  # receiver (both flows land here)
    h4 = net.addHost('h4', ip='10.0.0.4/24')
    h5 = net.addHost('h5', ip='10.0.0.5/24')
    h6 = net.addHost('h6', ip='10.0.0.6/24')

    info('*** Creating links\n')
    net.addLink(h1, s1)
    net.addLink(h2, s1)
    net.addLink(h3, s2)
    net.addLink(h4, s2)
    net.addLink(h5, s3)
    net.addLink(h6, s3)

    # The bottleneck: this is the link your QoS queues will actually live on.
    # cls=TCLink is passed explicitly here (not just relying on the
    # network-wide default) because some Mininet versions silently skip
    # bandwidth shaping on switch-to-switch links otherwise.
    net.addLink(s1, s2, cls=TCLink, bw=10, delay='2ms')   # <-- 10 Mbps shared pipe
    net.addLink(s2, s3, cls=TCLink, bw=10, delay='2ms')

    info('*** Starting network\n')
    net.build()
    c0.start()
    for s in (s1, s2, s3):
        s.start([c0])

    info('*** Network is up. Run pingall to verify connectivity.\n')
    CLI(net)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    build_network()
