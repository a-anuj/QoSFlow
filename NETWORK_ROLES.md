# Network Roles & Host Directory (IDAN SDN)

This document provides a comprehensive mapping of all **10 switches** and **20 hosts** in the IDAN topology, including their IP/MAC addresses, network zones, real-world business roles, and security policies.

---

## 1. Network Topology & Zone Overview

```mermaid
graph TD
    subgraph Zone1 ["Zone 1: Uplink & Bulk (s1)"]
        h1["h1 (10.0.0.1)<br/>VIP Video Sender"]
        h2["h2 (10.0.0.2)<br/>Bulk Downloader"]
        s1["Switch s1"]
        h1 --- s1
        h2 --- s1
    end

    subgraph Zone2 ["Zone 2: Primary Branch (s2)"]
        s2["Switch s2"]
        h3["h3 (10.0.0.3)<br/>Video Receiver / Staff"]
        h4["h4 (10.0.0.4)<br/>Branch Staff"]
        s2 --- h3
        s2 --- h4
    end

    subgraph Zone3 ["Zone 3: Central DB & Reception (s3)"]
        s3["Switch s3"]
        h5["h5 (10.0.0.5)<br/>Core Database Server"]
        h6["h6 (10.0.0.6)<br/>Guest Wi-Fi Device"]
        s3 --- h5
        s3 --- h6
    end

    subgraph Zone4_5 ["Zone 4 & 5: Department Workstations (s4, s5)"]
        s4["Switch s4 (Engineering)"]
        h7["h7 (10.0.0.7)<br/>Engineer"]
        h8["h8 (10.0.0.8)<br/>Engineer"]
        s4 --- h7
        s4 --- h8

        s5["Switch s5 (Finance)"]
        h9["h9 (10.0.0.9)<br/>Finance Officer"]
        h10["h10 (10.0.0.10)<br/>Finance Officer"]
        s5 --- h9
        s5 --- h10
    end

    subgraph Zone6_7 ["Zone 6 & 7: Visitor & IoT Zones (s6, s7)"]
        s6["Switch s6 (Guest Wi-Fi)"]
        h11["h11 (10.0.0.11)<br/>Guest Laptop"]
        h12["h12 (10.0.0.12)<br/>Guest Phone"]
        s6 --- h11
        s6 --- h12

        s7["Switch s7 (Visitor/IoT)"]
        h13["h13 (10.0.0.13)<br/>Contractor Laptop"]
        h14["h14 (10.0.0.14)<br/>Smart Display"]
        s7 --- h13
        s7 --- h14
    end

    subgraph Zone8_9 ["Zone 8 & 9: Datacenter Server Farm (s8, s9)"]
        s8["Switch s8 (App & Backup)"]
        h15["h15 (10.0.0.15)<br/>App Server"]
        h16["h16 (10.0.0.16)<br/>Backup Storage"]
        s8 --- h15
        s8 --- h16

        s9["Switch s9 (Web & Mail)"]
        h17["h17 (10.0.0.17)<br/>Web Server"]
        h18["h18 (10.0.0.18)<br/>Mail Server"]
        s9 --- h17
        s9 --- h18
    end

    subgraph Zone10 ["Zone 10: Executive Management (s10)"]
        s10["Switch s10"]
        h19["h19 (10.0.0.19)<br/>C-Suite Workstation"]
        h20["h20 (10.0.0.20)<br/>IT Admin Console"]
        s10 --- h19
        s10 --- h20
    end

    s1 ==="10 Mbps Bottleneck (QoS Queues)"=== s2
    s2 --- s3
    s3 --- s4
    s4 --- s5
    s5 --- s6
    s6 --- s7
    s7 --- s8
    s8 --- s9
    s9 --- s10
```

---

## 2. Complete Host Role Directory

| Host | IP Address | MAC Address | Switch | Group | Real-World Role | Critical Constraints / Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`h1`** | `10.0.0.1` | `00:00:00:00:00:01` | `s1` | `video` | **Executive Video Call Sender** | Protected by Digital Twin. `h1 → h3` path can never be disabled. Priority Queue 0 on `s1-eth3`. |
| **`h2`** | `10.0.0.2` | `00:00:00:00:00:02` | `s1` | `download` | **Bulk File Downloader** | Rate-limited via OVS HTB Queue 1 on `s1-eth3` (dynamic 0.5–10 Mbps). |
| **`h3`** | `10.0.0.3` | `00:00:00:00:00:03` | `s2` | `staff` | **Video Call Receiver / Staff Workstation** | Other end of the `h1` video call. Disabling `h3` triggers Digital Twin `UNSAFE` verdict. |
| **`h4`** | `10.0.0.4` | `00:00:00:00:00:04` | `s2` | `staff` | **Branch Staff Workstation** | General staff workstation. Used to verify safe isolation without cutting off server access. |
| **`h5`** | `10.0.0.5` | `00:00:00:00:00:05` | `s3` | `server` | **Core Enterprise Database & HR Server** | Protected server. Digital Twin ensures at least one staff member can always reach `h5`. |
| **`h6`** | `10.0.0.6` | `00:00:00:00:00:06` | `s3` | `guest` | **Reception Guest Device** | Visitor phone/tablet in reception area. Subject to zero-trust quarantine policies. |
| **`h7`** | `10.0.0.7` | `00:00:00:00:00:07` | `s4` | `staff` | **Lead Software Engineer** | Engineering workstation requiring access to databases and build servers. |
| **`h8`** | `10.0.0.8` | `00:00:00:00:00:08` | `s4` | `staff` | **QA Engineer / CI Runner** | Engineering lab machine. |
| **`h9`** | `10.0.0.9` | `00:00:00:00:00:09` | `s5` | `staff` | **Senior Accountant** | Finance desk. Processes payroll and ledger against database `h5`. |
| **`h10`** | `10.0.0.10` | `00:00:00:00:00:0a` | `s5` | `staff` | **Financial Auditor** | Finance desk. Restricted from guest communication. |
| **`h11`** | `10.0.0.11` | `00:00:00:00:00:0b` | `s6` | `guest` | **Conference Room Visitor Laptop** | Untrusted guest Wi-Fi device. |
| **`h12`** | `10.0.0.12` | `00:00:00:00:00:0c` | `s6` | `guest` | **Visitor Smartphone** | Untrusted guest Wi-Fi device. |
| **`h13`** | `10.0.0.13` | `00:00:00:00:00:0d` | `s7` | `guest` | **External Contractor Laptop** | Temporary contractor machine. |
| **`h14`** | `10.0.0.14` | `00:00:00:00:00:0e` | `s7` | `guest` | **Smart TV / IoT Kiosk** | Lobby display device with limited trust. |
| **`h15`** | `10.0.0.15` | `00:00:00:00:00:0f` | `s8` | `server` | **Internal Application Server** | Hosts corporate ERP & internal web tools. |
| **`h16`** | `10.0.0.16` | `00:00:00:00:00:10` | `s8` | `server` | **Offsite Backup Storage Node** | Stores nocturnal database dumps and file backups. |
| **`h17`** | `10.0.0.17` | `00:00:00:00:00:11` | `s9` | `server` | **Public Web Server (DMZ)** | Hosts company portal. |
| **`h18`** | `10.0.0.18` | `00:00:00:00:00:12` | `s9` | `server` | **Corporate Mail Exchange** | SMTP/IMAP mail gateway. |
| **`h19`** | `10.0.0.19` | `00:00:00:00:00:13` | `s10` | `staff` | **Executive Leadership Workstation** | High-security executive terminal. |
| **`h20`** | `10.0.0.20` | `00:00:00:00:00:14` | `s10` | `staff` | **IT Administrator Console** | Management workstation with elevated monitoring privileges. |

---

## 3. Host Group Summary

| Group Name | Member Hosts | Business Purpose |
| :--- | :--- | :--- |
| **`video`** | `h1` | Dedicated VIP video conference sender. |
| **`download`** | `h2` | Heavy bulk data downloader subject to QoS shaping. |
| **`staff`** | `h3, h4, h7, h8, h9, h10, h19, h20` | Authorized enterprise employees (Engineering, Finance, Executives, Admins). |
| **`server`** | `h5, h15, h16, h17, h18` | Core datacenter servers (Database, App, Backup, Web, Mail). |
| **`guest`** | `h6, h11, h12, h13, h14` | Untrusted guest devices and IoT equipment. |

---

## 4. Digital Twin Safety Rules for These Hosts

The Digital Twin validates every intent against 4 mathematical invariant rules:

1. **Critical Video Flow (`h1 ↔ h3`):**
   * `h1` (Switch 1) and `h3` (Switch 2) form the critical video call.
   * Any intent that attempts to disable `h1` or `h3` is **rejected** (`UNSAFE`).
2. **Server Availability (`staff ↔ h5`):**
   * At least one primary staff host (`h3` or `h4`) must maintain reachability to database server `h5`.
   * An intent that blocks all staff from `h5` is **rejected** (`UNSAFE`).
3. **Queue Sanity (QoS on `s1`):**
   * Bandwidth adjustments on `s1-eth3` must be within `0.5 Mbps` and `10.0 Mbps`.
4. **Group Integrity:**
   * When an intent specifies `"staff"`, `"servers"`, or `"guests"`, all constituent hosts are automatically resolved.

---

## 5. Example Natural Language Commands

| Intent Goal | What to type in `idan> ` CLI | What IDAN Does Under the Hood |
| :--- | :--- | :--- |
| **Isolate a rogue guest device** | `isolate h11` | Disables incoming/outgoing traffic for `h11` on Switch `s6`. |
| **Protect servers from guests** | `block guests from reaching the servers` | Installs drop rules for all 5 guests targeting all 5 servers on `s3`, `s8`, and `s9`. |
| **Restrict server to employees** | `only staff can reach the servers` | Blocks all non-staff (`guest`, `download`) from accessing datacenter servers. |
| **Throttle backup/download pipe** | `limit downloads to 2.5 mbps` | Reprograms OVS Linux HTB Queue 1 on `s1-eth3` to 2,500,000 bps. |
| **Attempted unsafe admin error** | `disable h3` | Intercepted and blocked by Digital Twin (`UNSAFE: video call h1→h3 would break`). |
