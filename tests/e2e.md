# IDAN End-to-End Test Checklist

Copy-paste these commands to verify every row in the test matrix (section 8).

---

## Prerequisites

Start the environment in this order:

```bash
# Terminal 0 — clean any old Mininet state
sudo mn -c

# Terminal 1 — start the controller
cd /path/to/setup_sdn_project
ryu-manager qos_controller.py

# Terminal 2 — start the topology
sudo python3 topology.py
# (wait for "Network is up" message)

# Terminal 3 — set up queues (run after topology is up)
sudo ./setup_queues.sh

# Terminal 4 — start the IDAN CLI
python3 -m idan.cli
```

---

## Row 1 — limit downloads to 2 mbps

In the Mininet CLI (`xterm h3 h1 h2`):
```bash
# On h3:
iperf3 -s -p 5001 &
iperf3 -s -p 5002 &

# On h1 (video):
iperf3 -c 10.0.0.3 -p 5001 -u -b 3M -t 20 -i 1

# On h2 (download bulk) — run simultaneously:
iperf3 -c 10.0.0.3 -p 5002 -t 20 -i 1
```

In the IDAN CLI:
```
idan> limit downloads to 2 mbps
```

**Expected:** Twin returns Safe. Queue 1 on s1-eth3 is capped to 2 Mbps.
TCP throughput ≈ 2 Mbps. UDP jitter/loss stays low.

Verify queue was changed:
```bash
sudo ovs-vsctl list queue
```

---

## Row 2 — disable h4

```
idan> disable h4
```

**Expected:** Twin returns Safe. `intents.json` has the new entry.

In Mininet:
```
mininet> pingall
```

**Expected:** Only pairs involving h4 fail (h4 → h3, h4 → h5, etc.).

Verify flows on s2:
```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s2
```

Should show two priority=200 drop flows with `eth_src=00:00:00:00:00:04`
and `eth_dst=00:00:00:00:00:04`.

---

## Row 3 — remove (undo disable h4)

First, find the id from:
```
idan> list
```

Then:
```
idan> remove i-0001
```

(replace i-0001 with the actual id)

**Expected:** `pingall` shows h4 is reachable again.
`dump-flows s2` shows the priority-200 rules are gone.

---

## Row 4 — block h2 and h3

```
idan> block h2 and h3
```

**Expected:** Safe. h2↔h3 fail in pingall. h1↔h3 still works.

In Mininet:
```
mininet> h2 ping -c 3 h3     # should fail
mininet> h1 ping -c 3 h3     # should succeed
```

---

## Row 5 — only staff can reach h5

```
idan> only staff can reach h5
```

**Expected:** Safe. h3 and h4 can ping h5. h1, h2, h6 cannot.

```
mininet> h3 ping -c 3 h5    # OK
mininet> h4 ping -c 3 h5    # OK
mininet> h1 ping -c 3 h5    # fails
mininet> h2 ping -c 3 h5    # fails
mininet> h6 ping -c 3 h5    # fails
```

---

## Row 6 — isolate h6

```
idan> isolate h6
```

**Expected:** Safe. h6 reaches nobody.

```
mininet> h6 ping -c 3 h1    # fails
mininet> h6 ping -c 3 h5    # fails
mininet> h1 ping -c 3 h6    # fails
mininet> h5 ping -c 3 h3    # still works
```

---

## Row 7 — block h3 and h4 from h5 → UNSAFE

```
idan> block h3 and h4 from h5
```

**Expected:** Twin returns **UNSAFE** with reason "no staff host can reach h5".
Nothing is stored. `dump-flows s3` is unchanged.

```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s3    # should show no new priority-200 rules
```

---

## Row 8 — disable h1 → UNSAFE

```
idan> disable h1
```

**Expected:** Twin returns **UNSAFE** with reason "h1 cannot reach h3 after this rule".
Nothing stored or installed.

---

## Row 9 — Restart recovery

With some intents already stored (e.g. after Row 2):

```bash
# Check current flows on s2:
sudo ovs-ofctl -O OpenFlow13 dump-flows s2

# Kill the controller (Ctrl+C in Terminal 1)

# Start it again:
ryu-manager qos_controller.py

# Check flows again (after a few seconds for reconnect):
sudo ovs-ofctl -O OpenFlow13 dump-flows s2
```

**Expected:** RYU log shows "IDAN: synced switch 2". Priority-200 rules are back.

---

## Row 10 — Parser error (gibberish)

```
idan> make h4 faster
```

**Expected:** Parse error message printed. Nothing stored. Nothing installed.

---

## Cleanup

```bash
# In IDAN CLI:
idan> quit

# In Mininet CLI:
mininet> exit

# Clean state:
sudo mn -c
```
