#!/bin/bash
# SDN QoS Project - Queue Setup
# Run this AFTER `sudo python3 topology.py` has built the network and
# BEFORE you start generating test traffic.
#
# This creates two queues on s1's port facing s2 (the bottleneck link):
#   queue 0 -> priority queue, effectively unrestricted (video call)
#   queue 1 -> capped at 2 Mbit/s out of the 10 Mbit/s link (movie download)
#
# WHY s1-eth3: in topology.py, h1 and h2 are added to s1 first (getting
# s1-eth1 and s1-eth2), so the s1<->s2 link becomes s1-eth3. Verify this
# yourself with `sudo ovs-vsctl show` if you change the topology at all --
# port numbering depends on link creation order, not on what you'd expect.

PORT="s1-eth3"

echo "Configuring QoS on $PORT ..."

sudo ovs-vsctl -- set port $PORT qos=@newqos \
  -- --id=@newqos create qos type=linux-htb \
       other-config:max-rate=10000000 \
       queues=0=@q0,1=@q1 \
  -- --id=@q0 create queue other-config:min-rate=6000000 other-config:max-rate=9000000 \
  -- --id=@q1 create queue other-config:min-rate=500000  other-config:max-rate=2000000

echo "Done. Verify with:"
echo "  sudo ovs-vsctl list qos"
echo "  sudo ovs-vsctl list queue"
echo ""
echo "To CHANGE the bulk cap live during a demo (e.g. professor asks):"
echo "  sudo ovs-vsctl set queue <queue-1-uuid> other-config:max-rate=500000"
echo "  (get the uuid from: sudo ovs-vsctl list queue)"
echo ""
echo "To remove QoS entirely (show the 'before' state again):"
echo "  sudo ovs-vsctl destroy qos $PORT ; sudo ovs-vsctl clear port $PORT qos"
