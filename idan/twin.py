#!/usr/bin/env python3
"""
idan/twin.py — Digital twin verification layer.

Builds a networkx graph of the topology from config/network.json and runs
four safety checks against candidate rules BEFORE anything touches a real switch.

Four checks (section 6 of the plan):
  1. Effect check       — the intent's targets are actually affected (blocked)
  2. Server safety      — at least one staff host can still reach h5
  3. Critical-flow check— h1 → h3 remains reachable
  4. Queue sanity       — for limit_download: 0.5 ≤ mbps ≤ 10

Public API:
    verdict(candidate_rules, intent_type, params, existing_rules=None)
        -> {"status": "Safe" | "Unsafe", "reasons": [str, ...]}

The reachability function is the one specified in the plan:
    reachable(G, src, dst, rules) -> bool
"""

import json
import os
from typing import Any

import networkx as nx

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

_HERE     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG_PATH = os.path.join(_HERE, "config", "network.json")

with open(_CFG_PATH) as _f:
    _CFG = json.load(_f)

_HOSTS    = _CFG["hosts"]
_SWITCHES = _CFG["switches"]
_LINKS    = _CFG["links"]
_GROUPS   = _CFG["groups"]
_QUEUES   = _CFG["queues"]

# ---------------------------------------------------------------------------
# Build the graph (once at import time)
# ---------------------------------------------------------------------------

def _build_graph() -> nx.Graph:
    G = nx.Graph()
    for host in _HOSTS:
        G.add_node(host)
    for sw in _SWITCHES:
        G.add_node(sw)
    # Host ↔ switch links (inferred from hosts' switch field)
    for host, info in _HOSTS.items():
        G.add_edge(host, info["switch"])
    # Switch ↔ switch links
    for link in _LINKS:
        G.add_edge(link["src"], link["dst"])
    return G

_G = _build_graph()

# ---------------------------------------------------------------------------
# MAC helper
# ---------------------------------------------------------------------------

def mac(h: str) -> str:
    """Return the MAC for host hN (e.g. 'h4' → '00:00:00:00:00:04')."""
    return _HOSTS[h]["mac"]

# ---------------------------------------------------------------------------
# Reachability (from the plan, section 6)
# ---------------------------------------------------------------------------

def reachable(G: nx.Graph, src: str, dst: str, rules: list[dict]) -> bool:
    """
    Return True if *src* can reach *dst* given the combined set of *rules*.

    Follows the algorithm in the plan:
    - Find the shortest path from src to dst.
    - Collect all switch DPIDs on that path.
    - Walk rules in descending priority order; the first matching rule wins.
    - A rule matches if its dpid is on the path AND its mac fields match.
    - If no rule matches, return True (default forward).
    """
    try:
        path = nx.shortest_path(G, src, dst)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return False

    # DPIDs of switches on the path
    sws = {_SWITCHES[n]["dpid"] for n in path if n in _SWITCHES}

    for r in sorted(rules, key=lambda r: -r["priority"]):
        m = r["match"]
        if r["dpid"] not in sws:
            continue
        # Check MAC fields — if the rule has that field, it must match src/dst
        src_ok = m.get("eth_src", mac(src)) == mac(src)
        dst_ok = m.get("eth_dst", mac(dst)) == mac(dst)
        if src_ok and dst_ok:
            return r["action"] != "drop"
    return True  # no matching rule → default forward

# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_effect(intent_type: str, params: dict,
                  all_rules: list[dict]) -> tuple[bool, str]:
    """
    Check 1: the intent's intended targets are actually blocked.
    Returns (ok, reason).  ok=True means the check PASSES (the effect is real).
    """
    if intent_type in ("disable_host", "isolate_host"):
        host = params["host"]
        # The host should not be able to reach any other host
        others = [h for h in _HOSTS if h != host]
        still_reachable = [h for h in others if reachable(_G, host, h, all_rules)]
        if still_reachable:
            return False, (
                f"Effect check failed: {host} can still reach "
                f"{', '.join(still_reachable)} after the rules are applied."
            )
        return True, "Effect verified: host is fully blocked."

    elif intent_type == "block_pair":
        a, b = params["a"], params["b"]
        ab = reachable(_G, a, b, all_rules)
        ba = reachable(_G, b, a, all_rules)
        if ab or ba:
            detail = []
            if ab: detail.append(f"{a}→{b}")
            if ba: detail.append(f"{b}→{a}")
            return False, f"Effect check failed: traffic still possible: {', '.join(detail)}."
        return True, "Effect verified: pair is mutually blocked."

    elif intent_type == "block_from":
        sources = params["sources"]
        target  = params["target"]
        still = [s for s in sources if reachable(_G, s, target, all_rules)]
        if still:
            return False, (
                f"Effect check failed: {', '.join(still)} can still reach {target}."
            )
        return True, "Effect verified: all sources are blocked from target."

    elif intent_type == "allow_only_staff":
        target    = params["target"]
        staff_set = set(_GROUPS.get("staff", []))
        non_staff = [h for h in _HOSTS if h != target and h not in staff_set]
        still = [h for h in non_staff if reachable(_G, h, target, all_rules)]
        if still:
            return False, (
                f"Effect check failed: non-staff hosts {still} can still reach {target}."
            )
        return True, "Effect verified: only staff can reach the target."

    elif intent_type == "limit_download":
        mbps = params["mbps"]
        if not (0.5 <= mbps <= 10):
            return False, (
                f"Queue sanity check failed: {mbps} Mbps is outside the allowed "
                "range [0.5, 10] Mbps."
            )
        return True, f"Queue sanity verified: {mbps} Mbps is within range."

    # For enable_host, remove — effect check not applicable; pass by default
    return True, "Effect check not applicable for this intent type."


def _check_server_safety(all_rules: list[dict]) -> tuple[bool, str]:
    """
    Check 2: at least one staff host can still reach h5 (the server).
    """
    staff = _GROUPS.get("staff", [])
    can_reach = [s for s in staff if reachable(_G, s, "h5", all_rules)]
    if not can_reach:
        return False, (
            "Server safety check failed: no staff host (h3, h4) can reach h5 "
            "after this rule is applied. The server would become inaccessible."
        )
    return True, f"Server safety OK: {', '.join(can_reach)} can still reach h5."


def _check_critical_flow(all_rules: list[dict]) -> tuple[bool, str]:
    """
    Check 3: the h1→h3 video call path must remain open.
    """
    if not reachable(_G, "h1", "h3", all_rules):
        return False, (
            "Critical-flow check failed: h1 cannot reach h3 after this rule. "
            "The video call (h1→h3) would be broken."
        )
    return True, "Critical-flow OK: h1→h3 remains reachable."


def _check_queue_sanity(intent_type: str, params: dict) -> tuple[bool, str]:
    """
    Check 4: for limit_download, 0.5 ≤ mbps ≤ 10.
    Only applies to limit_download; always passes for other types.
    """
    if intent_type != "limit_download":
        return True, "Queue sanity check not applicable."
    mbps = params.get("mbps", 0)
    if not (0.5 <= mbps <= 10):
        return False, (
            f"Queue sanity check failed: {mbps} Mbps is outside the valid range "
            "[0.5, 10] Mbps. Queue 1 has a minimum of 0.5 Mbps and the link cap is 10 Mbps."
        )
    return True, f"Queue sanity OK: {mbps} Mbps is within [0.5, 10] Mbps."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verdict(candidate_rules: list[dict], intent_type: str, params: dict,
            existing_rules: list[dict] | None = None) -> dict:
    """
    Run all four checks on *candidate_rules* combined with *existing_rules*.

    Args:
        candidate_rules: rules produced by decomposer for this intent
        intent_type:     e.g. "disable_host"
        params:          e.g. {"host": "h4"}
        existing_rules:  all currently stored rules (from the store); if None
                         defaults to []

    Returns:
        {"status": "Safe" | "Unsafe", "reasons": [str, ...]}
    """
    if existing_rules is None:
        existing_rules = []

    all_rules = existing_rules + candidate_rules
    reasons   = []
    safe      = True

    checks = [
        _check_effect(intent_type, params, all_rules),
        _check_server_safety(all_rules),
        _check_critical_flow(all_rules),
        _check_queue_sanity(intent_type, params),
    ]

    for ok, reason in checks:
        reasons.append(reason)
        if not ok:
            safe = False

    return {
        "status":  "Safe" if safe else "Unsafe",
        "reasons": reasons,
    }
