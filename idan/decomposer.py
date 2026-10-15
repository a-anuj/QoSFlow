#!/usr/bin/env python3
"""
idan/decomposer.py — Translate a parsed intent into concrete OpenFlow rules
and/or queue_changes that can be installed in the real network.

Implements the mapping in section 5.5 of the plan:

    disable_host hX     → drop eth_src=hX and eth_dst=hX on hX's switch
    enable_host hX      → (handled by store + reload; no rules to add)
    block_pair a b      → drop src=a,dst=b on a's switch; drop src=b,dst=a on b's switch
    block_from [..] tgt → for each src, drop src=src,dst=tgt on tgt's switch
    isolate_host hX     → same as disable_host
    allow_only_staff tgt→ for every non-staff host, drop src=host,dst=tgt on tgt's switch
    limit_download Mbps → queue_changes only (no rules)
    remove id           → (handled by store; no rules to decompose here)

All rule dicts follow the contract in section 5.2:
    {"dpid": int, "priority": 200, "action": "drop", "match": {"eth_src": "..."}}
"""

import json
import os
from typing import Any

# ---------------------------------------------------------------------------
# Load network config once at import time
# ---------------------------------------------------------------------------

_HERE    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG_PATH = os.path.join(_HERE, "config", "network.json")

with open(_CFG_PATH) as _f:
    _CFG = json.load(_f)

_HOSTS    = _CFG["hosts"]          # {hN: {mac, ip, switch, group}}
_SWITCHES = _CFG["switches"]       # {sN: {dpid}}
_GROUPS   = _CFG["groups"]         # {staff: [hN, …], …}
_QUEUES   = _CFG["queues"]         # {port, switch, queue_ids, link_max_rate}

IDAN_DROP_PRIORITY = 200


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _dpid(switch_name: str) -> int:
    return _SWITCHES[switch_name]["dpid"]

def _mac(host: str) -> str:
    return _HOSTS[host]["mac"]

def _sw(host: str) -> str:
    return _HOSTS[host]["switch"]

def _drop(dpid: int, *, eth_src: str | None = None,
          eth_dst: str | None = None) -> dict:
    """Build a drop-rule dict."""
    match: dict[str, Any] = {}
    if eth_src:
        match["eth_src"] = eth_src
    if eth_dst:
        match["eth_dst"] = eth_dst
    return {
        "dpid":     dpid,
        "priority": IDAN_DROP_PRIORITY,
        "action":   "drop",
        "match":    match,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decompose(intent_type: str, params: dict) -> tuple[list, list]:
    """
    Given an intent type and its params, return:
        (rules, queue_changes)

    rules         — list of rule dicts (section 5.2 format)
    queue_changes — list of queue change dicts
                    [{"port": "s1-eth3", "queue_id": 1, "max_rate": <bps>}]

    Raises ValueError for unknown intent types (should not happen if parser
    and decomposer are kept in sync).
    """
    fn = _HANDLERS.get(intent_type)
    if fn is None:
        raise ValueError(f"decompose: unknown intent type '{intent_type}'")
    return fn(params)


# ---------------------------------------------------------------------------
# Per-type handlers
# ---------------------------------------------------------------------------

def _disable_host(params: dict) -> tuple[list, list]:
    host  = params["host"]
    dpid_ = _dpid(_sw(host))
    mac_  = _mac(host)
    rules = [
        _drop(dpid_, eth_src=mac_),
        _drop(dpid_, eth_dst=mac_),
    ]
    return rules, []


def _enable_host(_params: dict) -> tuple[list, list]:
    # Removal is handled by the CLI (remove the old intent from the store
    # and trigger a reload); nothing new to install.
    return [], []


def _isolate_host(params: dict) -> tuple[list, list]:
    # Same as disable_host
    return _disable_host(params)


def _block_pair(params: dict) -> tuple[list, list]:
    a, b = params["a"], params["b"]
    # If on the same switch, both rules go on the same dpid; if different
    # switches we put each rule on the switch that sees the outgoing packet.
    rules = [
        _drop(_dpid(_sw(a)), eth_src=_mac(a), eth_dst=_mac(b)),
        _drop(_dpid(_sw(b)), eth_src=_mac(b), eth_dst=_mac(a)),
    ]
    # Remove duplicates that arise when a and b share a switch
    seen = set()
    deduped = []
    for r in rules:
        key = (r["dpid"], r["match"].get("eth_src"), r["match"].get("eth_dst"))
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped, []


def _block_from(params: dict) -> tuple[list, list]:
    sources = params["sources"]
    targets = params.get("targets")
    if not targets:
        target = params.get("target")
        targets = [target] if target else []
    rules = []
    for tgt in targets:
        target_dpid = _dpid(_sw(tgt))
        for src in sources:
            rules.append(_drop(target_dpid, eth_src=_mac(src), eth_dst=_mac(tgt)))
    return rules, []


def _allow_only_staff(params: dict) -> tuple[list, list]:
    """
    Drop non-staff → target on the target's switch.
    Staff = hosts in the "staff" group. Everyone else is blocked.
    """
    targets = params.get("targets")
    if not targets:
        target = params.get("target")
        targets = [target] if target else _GROUPS.get("server", ["h5"])
    staff_set   = set(_GROUPS.get("staff", []))
    rules = []
    for tgt in targets:
        target_dpid = _dpid(_sw(tgt))
        for host in _HOSTS:
            if host == tgt:
                continue  # don't block target from itself
            if host in staff_set:
                continue  # staff are allowed
            rules.append(_drop(target_dpid, eth_src=_mac(host), eth_dst=_mac(tgt)))
    return rules, []


def _limit_download(params: dict) -> tuple[list, list]:
    mbps    = params["mbps"]
    bps     = int(mbps * 1_000_000)
    port    = _QUEUES["port"]          # "s1-eth3"
    queue_id = 1                       # bulk download queue
    queue_changes = [{"port": port, "queue_id": queue_id, "max_rate": bps}]
    return [], queue_changes


def _remove(_params: dict) -> tuple[list, list]:
    # The CLI removes the intent from the store before calling decompose;
    # there are no new rules to install.
    return [], []


_HANDLERS = {
    "disable_host":     _disable_host,
    "enable_host":      _enable_host,
    "isolate_host":     _isolate_host,
    "block_pair":       _block_pair,
    "block_from":       _block_from,
    "allow_only_staff": _allow_only_staff,
    "limit_download":   _limit_download,
    "remove":           _remove,
}
