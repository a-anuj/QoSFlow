# IDAN Demo Script (≈ 5 minutes)

---

## Setup (before audience arrives)

```bash
sudo mn -c
ryu-manager qos_controller.py          # Terminal 1
sudo python3 topology.py               # Terminal 2
sudo ./setup_queues.sh                 # after topology is up
python3 -m idan.cli                    # Terminal 3
```

Have Mininet CLI and IDAN CLI both visible side by side.

---

## Step 1 — Baseline QoS (≈ 60 s)

**Say:** "First, let's show the existing QoS in action. We have two flows sharing
a 10 Mbps bottleneck: a video call from h1 and a bulk download from h2, both
going to h3."

Open xterms:
```
mininet> xterm h3 h1 h2
```

On **h3** (receiver):
```bash
iperf3 -s -p 5001 &
iperf3 -s -p 5002 &
```

On **h1** (video, 3 Mbps UDP):
```bash
iperf3 -c 10.0.0.3 -p 5001 -u -b 3M -t 30 -i 1
```

On **h2** (bulk download, greedy TCP):
```bash
iperf3 -c 10.0.0.3 -p 5002 -t 30 -i 1
```

**Say:** "Notice: video jitter is low and stable, TCP is capped at about 2 Mbps —
exactly as the queues dictate."

Now demonstrate IDAN changing the cap live:
```
idan> limit downloads to 1 mbps
```

**Say:** "We just changed the bulk cap to 1 Mbps via a plain English command.
No queue UUIDs, no ovs-vsctl, no rule editing."

Wait 5 s, then point to h2's iperf output — throughput drops to ~1 Mbps.

---

## Step 2 — Intent in plain English (≈ 60 s)

**Say:** "Now let's show access control. I want to disable host h4 entirely —
no traffic in or out."

```
idan> disable h4
```

**Say:** "The system parsed my English sentence, translated it into OpenFlow drop
rules, then ran four safety checks on a digital model of the network *before*
touching a single switch. All checks passed — it's Safe."

In Mininet:
```
mininet> pingall
```

**Say:** "Only pairs involving h4 fail. Everything else still works. Let's verify
the actual OpenFlow rules installed on s2:"

```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s2
```

Point to the two priority=200 drop entries.

---

## Step 3 — Zones and isolation (≈ 60 s)

**Say:** "Now let's protect the server zone. h5 is a protected server — only staff
(h3 and h4) should access it."

```
idan> only staff can reach h5
```

```
mininet> h3 ping -c 3 h5    # OK
mininet> h1 ping -c 3 h5    # fail
mininet> h6 ping -c 3 h5    # fail
```

**Say:** "And now quarantine the guest host h6:"

```
idan> isolate h6
```

```
mininet> h6 ping -c 3 h1    # fail
mininet> h1 ping -c 3 h3    # still works — we haven't broken anything
```

---

## Step 4 — Safety net (Unsafe rejection) (≈ 60 s)

**Say:** "Now the really important part — what if we make a mistake? Let's try
to block ALL staff from reaching the server."

```
idan> block h3 and h4 from h5
```

**Say:** "The system rejected it immediately. The digital twin detected that if
this rule were applied, no staff host could reach the server — a complete
lockout. Nothing was installed. Let's confirm:"

```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s3    # no new rules
```

---

## Step 5 — Restart recovery (≈ 60 s)

```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s2    # show current rules
```

**Say:** "The controller has all the rules from our intents in memory. What
happens if it crashes?"

Kill the controller (Ctrl+C in Terminal 1), then:

```bash
ryu-manager qos_controller.py
```

Wait for switches to reconnect (3–5 seconds), then:

```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s2    # rules are BACK
```

Point to the log line: `"IDAN: synced switch 2"`.

**Say:** "The rules are back. The controller reloads them automatically from the
JSON file on every switch reconnect. No human intervention needed."

---

## Wrap-up

**Say:** "To summarise: IDAN lets you manage your SDN in plain English. Every
intent is verified on a digital twin before it touches the network. All intents
survive a controller restart. The whole system is 7 Python files under 600 lines,
sitting on top of the existing QoSFlow controller without changing its
forwarding logic."
