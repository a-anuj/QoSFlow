# SDN QoS project — complete walkthrough

This document explains every file, every term, and every command used so far,
in enough depth to answer follow-up questions live.

---

## 1. The four files, what each one is responsible for

| File | Runs on | Responsible for |
|---|---|---|
| `topology.py` | Mininet | Builds the virtual network: 3 switches, 6 hosts, link bandwidths |
| `qos_controller.py` | RYU | The SDN "brain" — decides how switches forward and queue traffic |
| `setup_queues.sh` | OVS (bash) | Creates the actual rate-limited queues on the bottleneck port |
| `test_qos.sh` | reference notes | The iperf3 commands used to generate and measure test traffic |

These map directly onto your rubric: file 1 → rubric 1, file 2 → rubric 2,
file 3 → rubric 3, files 3+4 together produce the evidence for rubrics 4 and 5.

---

## 2. Key terminology, defined plainly

- **Mininet** — a tool that creates a *virtual* network (fake switches, fake
  hosts) entirely inside one Linux machine, using real Linux networking
  primitives (network namespaces, virtual Ethernet pairs) so it behaves like
  a real network for testing purposes.
- **RYU** — the SDN controller software. It's a Python framework that lets
  you write code that controls how OpenFlow switches behave.
- **OVS (Open vSwitch)** — the actual switch software Mininet uses to
  simulate each switch. It understands the OpenFlow protocol and also has
  its own separate configuration database (`ovs-vsctl`) for things OpenFlow
  doesn't cover, like queues.
- **OpenFlow** — the protocol RYU and OVS speak to each other over. It lets
  the controller install "flow rules" (match + action pairs) into a switch.
- **dpid (datapath ID)** — the unique ID a switch identifies itself with to
  the controller. s1, s2, s3 each get one automatically.
- **Flow rule / flow entry** — one row in a switch's flow table: "if a packet
  matches X, do Y." Installed by the controller via OpenFlow.
- **Match** — the "if" part of a flow rule (e.g. "if UDP destination port is
  5001").
- **Action** — the "then" part (e.g. "send out port 3", "put in queue 1").
- **Table-miss rule** — a catch-all flow rule with the lowest priority that
  says "if nothing else matched, send this packet up to the controller for a
  decision." Every switch needs one or it silently drops unmatched packets.
- **Queue** — a separate buffer on a switch's *outgoing* port, with its own
  bandwidth rules. Not part of OpenFlow itself — configured separately via
  `ovs-vsctl`, then *referenced* from an OpenFlow action.
- **HTB (Hierarchical Token Bucket)** — the actual Linux kernel mechanism
  that enforces a queue's rate limit. OVS configures HTB for you when you
  create a queue with `type=linux-htb`.
- **`SET_QUEUE`** — the OpenFlow action that tells a packet "leave through
  queue N," where N must match a queue id that actually exists on the
  egress port.
- **TCLink** — a Mininet link class that applies real bandwidth/delay limits
  (via Linux `tc`) to a virtual link, so it behaves like a genuine
  bandwidth-constrained cable instead of an unlimited one.
- **qdisc (queueing discipline)** — the Linux kernel's term for "the rule
  governing how packets leaving an interface are queued/shaped." `tc qdisc
  show` reveals what's actually active on an interface.

---

## 3. `topology.py` — line by line concepts

```python
net = Mininet(controller=RemoteController, switch=OVSSwitch,
               link=TCLink, autoSetMacs=True)
```
Creates the network object. `controller=RemoteController` means "the
controller is a separate process I'll connect to" (this is RYU, running
outside Mininet) rather than Mininet's built-in reference controller.
`switch=OVSSwitch` means every switch will actually be an Open vSwitch
instance. `link=TCLink` sets the *default* link class (though we override it
explicitly for the bottleneck links — see below).

```python
c0 = net.addController('c0', controller=RemoteController,
                        ip='127.0.0.1', port=6633)
```
Tells Mininet where to find RYU: same machine (`127.0.0.1`), port 6633 (the
standard OpenFlow controller port RYU listens on by default).

```python
s1 = net.addSwitch('s1', protocols='OpenFlow13')
```
Creates a switch that will speak OpenFlow version 1.3 specifically — this
matters because your RYU app is written against `ofproto_v1_3`, and mismatch
between the switch's spoken version and the controller's expected version
means they simply won't understand each other.

```python
h1 = net.addHost('h1', ip='10.0.0.1/24')
```
Creates a virtual host with a fixed IP. All hosts share the `10.0.0.0/24`
subnet, so they can all reach each other with no routing needed — just
switching.

```python
net.addLink(h1, s1)
net.addLink(h2, s1)
...
net.addLink(s1, s2, cls=TCLink, bw=10, delay='2ms')
```
`addLink` creates a *virtual Ethernet (veth) pair* — think of it as a virtual
cable with two ends, one plugged into each device. Host-to-switch links use
whatever bandwidth the machine can push (uncapped) because they're not
meant to be the bottleneck. The switch-to-switch link is explicitly given
`cls=TCLink, bw=10` — this is the one deliberately constrained to 10 Mbps,
because it's the shared pipe your two competing hosts (h1, h2) both need to
cross to reach h3. **Port naming**: Mininet names ports in the order links
are added. Since h1 and h2 are linked to s1 *before* the s1–s2 link, that
switch-to-switch link becomes `s1-eth3` (h1→eth1, h2→eth2, s1-s2 link→eth3).
This is exactly why `setup_queues.sh` targets `s1-eth3`.

```python
net.build()
c0.start()
for s in (s1, s2, s3):
    s.start([c0])
```
`build()` actually creates all the virtual interfaces and namespaces.
`c0.start()` starts the controller connection object. Each switch's
`.start([c0])` tells that specific switch which controller(s) to connect to
— this is the moment the OpenFlow handshake happens, which is what triggers
your RYU app's `switch_features_handler`.

---

## 4. `qos_controller.py` — what it actually does, and why

**The big picture**: this file is a normal L2 learning switch (it forwards
based on learned MAC addresses, just like a regular switch would) *plus* two
special-case rules layered on top for your two test flows.

### `switch_features_handler`
Fires once per switch, the moment that switch connects to the controller.
Installs the table-miss rule (priority 0 — lowest, so it only catches
packets nothing else matched). This is your proof of "controller
connectivity" for rubric item 1 — you can literally watch this fire in the
RYU log when you run `topology.py`.

### `packet_in_handler`
Fires every time a switch sends a packet up to the controller (because it
didn't match anything better than the table-miss rule). This is where the
actual decision-making happens:

1. **Learn the source** — records "this MAC address is reachable via this
   port" in `self.mac_to_port`. This is standard L2 learning switch logic.
2. **Decide the output port** — if the destination MAC has been learned
   already, send directly to that port. Otherwise, flood (send out every
   port except the one it came from) — this is how the very first ping
   between two hosts works, before either side has been "learned" yet.
3. **Classify for QoS** (`_classify_for_qos`) — inspects the packet's IP
   protocol and destination port. If it's UDP port 5001 or TCP port 5002,
   it returns which queue that traffic belongs in. Everything else returns
   `None` and just gets normal L2 treatment.
4. **Install a flow rule** — if it's QoS traffic, install a rule with
   *both* a `SET_QUEUE` action and an `OUTPUT` action, at a higher priority
   (100) than the plain L2 rules (priority 1) or the table-miss rule
   (priority 0). Higher priority always wins when multiple rules could
   match the same packet.

### Why priority matters here specifically
Without the priority difference, there'd be no guarantee the QoS-aware rule
is the one that actually gets used — OpenFlow flow tables can have multiple
entries that *could* match the same packet, and the switch always picks the
highest-priority match. Setting QoS rules to priority 100 vs plain
forwarding at priority 1 guarantees your queue assignment always wins.

### Why `idle_timeout=30`
Flow rules aren't installed forever — after 30 seconds of no matching
traffic, the switch silently removes the rule and future packets go back to
the controller for a fresh decision. This keeps the flow table from filling
up with stale rules for connections that ended long ago.

---

## 5. How queues are actually built — the full mechanism

This is the two-layer system that confused you earlier, explained fully.

### Layer 1: the queue exists on the port (OVS database, `setup_queues.sh`)
```bash
sudo ovs-vsctl -- set port s1-eth3 qos=@newqos \
  -- --id=@newqos create qos type=linux-htb \
       other-config:max-rate=10000000 \
       queues=0=@q0,1=@q1 \
  -- --id=@q0 create queue other-config:min-rate=6000000 other-config:max-rate=9000000 \
  -- --id=@q1 create queue other-config:min-rate=500000  other-config:max-rate=2000000
```
Read this as one atomic transaction (the `--` separators chain multiple
operations together):
1. Create a **qos record** of type `linux-htb`, with an overall port cap of
   10 Mbit/s (`max-rate=10000000`, in bits/sec).
2. Create **queue 0**: min guaranteed 6 Mbit/s, max allowed 9 Mbit/s — this
   is your "priority" queue for the video call.
3. Create **queue 1**: min guaranteed 0.5 Mbit/s, max allowed 2 Mbit/s —
   this is your "capped" queue for the bulk download.
4. Attach this whole qos config to port `s1-eth3` via `set port ... qos=@newqos`.

Under the hood, OVS translates this into a Linux `tc` HTB hierarchy on that
interface — which is exactly what you saw when you ran `tc qdisc show dev
s1-eth3` and got `qdisc htb`.

### Layer 2: a flow rule tells packets which queue to use (RYU, at runtime)
```python
actions = [parser.OFPActionSetQueue(queue_id), parser.OFPActionOutput(out_port)]
```
This is a per-packet decision made by your controller. The queue only
*exists* because of Layer 1; this action just *routes traffic into it*.

**Critical rule**: the queue IDs in both layers must match exactly (`0` and
`1` in both files right now), and the port your flow rule outputs to must be
the same port the queue was created on. If either mismatches, packets still
get delivered — they just silently skip your intended queue and use
whatever the port's default behavior is.

### How to access / inspect queues right now
```bash
sudo ovs-vsctl list qos              # shows the qos record: type, max-rate, which queues belong to it
sudo ovs-vsctl list queue            # shows each individual queue: its uuid, min-rate, max-rate
sudo ovs-vsctl list port s1-eth3     # shows whether this port currently has a qos record attached (the 'qos' field)
sudo tc qdisc show dev s1-eth3       # shows the actual Linux kernel-level shaping rules (ground truth)
sudo ovs-ofctl -O OpenFlow13 dump-flows s1     # shows your flow rules, including which ones have SET_QUEUE actions
sudo ovs-ofctl -O OpenFlow13 queue-stats s1    # shows live packet/byte counters per queue -- proves traffic is actually using them
```

### How to change a queue's rate live (for your professor's "change something" test)
```bash
sudo ovs-vsctl list queue      # find the uuid of the queue you want to change
sudo ovs-vsctl set queue <uuid> other-config:max-rate=500000   # e.g. drop the bulk cap to 0.5 Mbit/s
```
This takes effect immediately — no restart needed. Rerun your iperf3 test
afterward to show the new cap in action.

### How to delete a queue (remove QoS entirely)
```bash
sudo ovs-vsctl clear port s1-eth3 qos
```
This detaches the qos record from the port — the port's `qos` field becomes
`[]` (empty) and traffic goes back to whatever the underlying link
(10 Mbit/s TCLink cap, but no priority/queueing logic) allows. Note: this
does *not* delete the underlying qos/queue database records — they become
orphaned but harmless. To fully remove them:
```bash
sudo ovs-vsctl destroy qos <qos-uuid>
sudo ovs-vsctl destroy queue <queue-uuid>   # once for each queue
```

### How to bring queues back
Just rerun `setup_queues.sh` — it recreates everything from scratch. Since
it always creates a fresh `qos` record (new uuid each time), running it
multiple times doesn't conflict with old orphaned entries; it simply
attaches a new, working config to the port.

---

## 6. The full pipeline, start to finish, one more time

1. `topology.py` builds the virtual network and the real 10 Mbit/s bottleneck
   link (`s1-eth3`), and connects each switch to RYU.
2. `qos_controller.py` is already running, waiting. The moment each switch
   connects, `switch_features_handler` installs the table-miss rule.
3. When any host sends a packet, if the switch doesn't already have a
   matching flow rule, the packet goes to the controller —
   `packet_in_handler` runs, learns the MAC, classifies the packet, and
   installs a flow rule (with a `SET_QUEUE` action if it's one of the two
   test flows).
4. `setup_queues.sh` has separately configured `s1-eth3` with two real,
   rate-limited queues at the OVS/kernel level.
5. When a classified packet leaves via `s1-eth3`, the `SET_QUEUE` action
   from step 3 places it into the matching queue from step 4, and Linux's
   HTB scheduler enforces that queue's rate limit in real time.
6. `iperf3` traffic run through this pipeline produces measurably different
   throughput/jitter depending on whether QoS is applied — this is your
   before/after evidence.

---

## 7. Likely follow-up questions and short answers

- **"Why UDP for video and TCP for download?"** — Real-time media (VoIP,
  video calls) genuinely uses UDP in practice because it doesn't want
  retransmission delays; TCP is what bulk transfers/downloads actually use
  because it guarantees delivery. The simulation mirrors real protocol
  choices, not just an arbitrary label.
- **"Why queues instead of just meters, or vice versa?"** — Queues do
  *scheduling* (who goes first when there's contention); meters do *rate
  limiting/dropping* (a hard cap regardless of priority). We used queues
  because we wanted both priority ordering and differentiated rate caps in
  one mechanism tied to the port.
- **"What happens if two switches both need the s1-eth3 style bottleneck?"**
  — You'd repeat the exact same `ovs-vsctl` queue setup on that switch's
  relevant port; the mechanism is per-port, not global.
- **"How do you know the queue is actually being used, not just
  configured?"** — `ovs-ofctl queue-stats` shows live per-queue packet/byte
  counters climbing during a test — that's not configuration, that's
  runtime evidence.
