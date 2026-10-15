# QoSFlow + IDAN

**Intent-Driven QoS and Access Control for SDN with Pre-Deployment Verification**

Team: Anuj, Varun, Karthik, Narain

---

## Architecture

```
admin text
   |
 idan/parser.py          text → {type, params}
   |
 idan/decomposer.py      {type, params} → rules[] + queue_changes[]
   |
 idan/twin.py            rules + current rules → Safe / Unsafe + reasons
   |  (Safe only)
 idan/store.py           data/intents.json  (single source of truth)
   |
 idan/controller_client.py   POST http://127.0.0.1:8080/idan/reload
   |                         (+ idan/queue_tool.py for queue changes)
 qos_controller.py           reads intents.json → deletes IDAN flows → reinstalls
                             (also runs the same sync when a switch connects = recovery)
```

### Topology (10 Switches, 20 Hosts)

```
h1, h2 ──── s1 ══(10 Mbps)══ s2 ──── h3, h4
                              │
                             s3 ──── h5, h6
                              │
                             s4 ──── h7, h8
                              │
                             ...
                              │
                            s10 ──── h19, h20
```

> **Full Role Directory:** For detailed IP/MAC addresses, network zones, and real-world business roles for all 20 hosts, see [NETWORK_ROLES.md](file:///home/a-anuj/Desktop/setup_sdn_project/NETWORK_ROLES.md).

| Zone | Switch | Hosts | Primary Groups | Real-World Role |
|------|--------|-------|----------------|-----------------|
| Branch Uplink | `s1` | `h1`, `h2` | `video` (`h1`), `download` (`h2`) | VIP Zoom Sender & Bulk Downloader |
| Branch Office | `s2` | `h3`, `h4` | `staff` | Video Receiver & Local Employees |
| Reception/DB | `s3` | `h5`, `h6` | `server` (`h5`), `guest` (`h6`) | Core Enterprise DB & Visitor Kiosk |
| Engineering | `s4` | `h7`, `h8` | `staff` | Software & QA Engineers |
| Finance | `s5` | `h9`, `h10` | `staff` | Accounting & Audit Team |
| Guest Wi-Fi | `s6`, `s7` | `h11`..`h14` | `guest` | Visitor Phones & Contractor Laptops |
| Datacenter | `s8`, `s9` | `h15`..`h18` | `server` | App, Backup, Web & Mail Servers |
| Management | `s10` | `h19`, `h20` | `staff` | Executive Suite & IT Admin Console |

MACs: `00:00:00:00:00:XX` (in hex). IPs: `10.0.0.X`.

---

## Run Order

```bash
# 0. Clean old state
sudo mn -c

# 1. Start the RYU controller  (Terminal 1)
ryu-manager qos_controller.py

# 2. Start the topology  (Terminal 2)
sudo python3 topology.py

# 3. Set up queues  (after topology is up)
sudo ./setup_queues.sh

# 4. Start the IDAN CLI  (Terminal 3)
python3 -m idan.cli
```

Or use the helper:
```bash
bash run_all.sh
```

---

## Intent Grammar

| Intent | Type | Params |
|--------|------|--------|
| `disable h4` | `disable_host` | host |
| `enable h4` | `enable_host` | host |
| `block h2 and h3` | `block_pair` | a, b |
| `block h3 and h4 from h5` | `block_from` | sources[], target |
| `only staff can reach h5` | `allow_only_staff` | target |
| `isolate h6` | `isolate_host` | host |
| `limit downloads to 2 mbps` | `limit_download` | mbps |
| `remove i-0001` | `remove` | id |

---

## Digital Twin Safety Checks

Every intent is verified on a networkx model of the network **before** touching any switch:

1. **Effect check** — the targeted hosts are actually blocked after the rules are applied.
2. **Server safety** — at least one staff host (h3, h4) can still reach h5.
3. **Critical-flow check** — h1→h3 (the video call) remains reachable.
4. **Queue sanity** — for `limit_download`: 0.5 ≤ mbps ≤ 10.

If any check fails, the intent is rejected with a human-readable reason. Nothing is stored or installed.

---

## File Layout

```
qosflow/
  topology.py          # Mininet topology (unchanged)
  qos_controller.py    # RYU controller + IDAN support
  setup_queues.sh      # OVS queue setup
  test_qos.sh          # iperf3 test reference
  run_all.sh           # startup helper
  idan/
    __init__.py
    parser.py          # plain-English → {type, params}
    decomposer.py      # {type, params} → rules[], queue_changes[]
    twin.py            # digital twin: 4 safety checks
    store.py           # atomic JSON intent store
    cli.py             # interactive REPL
    controller_client.py  # POST /idan/reload
    queue_tool.py      # ovs-vsctl queue rate change
  config/
    network.json       # topology, host groups, queue config
  data/
    intents.json       # persistent intent store (starts as [])
  tests/
    test_parser.py     # 12+ parser unit tests
    test_twin.py       # twin tests for all section-8 rows
    e2e.md             # end-to-end test checklist
  demo/
    demo_script.md     # 5-minute demo with exact commands
```

---

## Running Tests

```bash
# Parser tests
pytest tests/test_parser.py -v

# Twin tests  
pytest tests/test_twin.py -v

# All tests
pytest tests/ -v
```

---

## Key Design Decisions

- **Priority 200 for drop rules** — IDAN drop rules sit above QoS (100) and L2 learning (1), so they always win.
- **IDAN_COOKIE = 0x1DA0** — all IDAN flows are tagged with this cookie, enabling bulk delete-then-reinstall without touching QoS or L2 flows.
- **Atomic JSON writes** — the store writes to a temp file then renames, so a crash mid-write never corrupts the intent database.
- **QoS only on s1** — `SET_QUEUE` rules are only installed on s1 (the only switch with queues); other switches get plain L2 forwarding to avoid the "queue doesn't exist" problem.
- **Restart recovery** — `switch_features_handler` calls `sync_switch()` on every switch connection, not just the first one. If the controller restarts, all intents are re-installed automatically when the switch reconnects.

---

## Useful Debugging Commands

```bash
# Show all flows on a switch
sudo ovs-ofctl -O OpenFlow13 dump-flows s2

# Show queue stats (bytes/packets per queue)
sudo ovs-ofctl -O OpenFlow13 queue-stats s1

# Show OVS queue configuration
sudo ovs-vsctl list queue

# Show IDAN intents loaded by the controller
curl http://127.0.0.1:8080/idan/flows

# Trigger a manual reload
curl -X POST http://127.0.0.1:8080/idan/reload
```