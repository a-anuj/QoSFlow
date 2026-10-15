#!/usr/bin/env python3
"""
idan/parser.py — Rule-based intent parser for IDAN.

Converts plain-English admin commands into a structured dict:
    {"type": <intent_type>, "params": {...}}

Supported intent types (section 5.4 of the plan):
    disable_host    — "disable h4"
    enable_host     — "enable h4"
    block_pair      — "block h2 and h3"
    block_from      — "block h3 and h4 from h5"
    allow_only_staff— "only staff can reach h5"
    isolate_host    — "isolate h6"
    limit_download  — "limit downloads to 2 mbps"
    remove          — "remove i-0001"

Raises ValueError with a human-readable message for any unrecognised input.
"""

import re

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HOST_RE = r"h(?:[1-9]|1[0-9]|20)\b"  # hosts h1 through h20
ID_RE   = r"i-\d{4,}"                 # intent id like i-0001

def _host(text: str) -> str:
    """Extract a single host name from a string, or raise ValueError."""
    m = re.search(HOST_RE, text, re.IGNORECASE)
    if not m:
        raise ValueError(f"Expected a host name (h1–h20) but got: '{text}'")
    return m.group(0).lower()

def _hosts(text: str) -> list[str]:
    """Extract ALL host names from a string."""
    found = re.findall(HOST_RE, text, re.IGNORECASE)
    if not found:
        raise ValueError(f"No host names (h1–h20) found in: '{text}'")
    return [h.lower() for h in found]

def _mbps(text: str) -> float:
    """Extract a number (possibly float) before 'mbps'."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*mbps?", text, re.IGNORECASE)
    if not m:
        raise ValueError(f"Expected a bandwidth value like '2 mbps' but got: '{text}'")
    return float(m.group(1))

# ---------------------------------------------------------------------------
# Pattern table  (checked top-to-bottom; first match wins)
# ---------------------------------------------------------------------------
#
# Each entry is:  (compiled_regex, handler_function)
# The handler receives the re.Match object and returns the parsed dict.

def _parse_disable(m):
    return {"type": "disable_host", "params": {"host": _host(m.group(1))}}

def _parse_enable(m):
    return {"type": "enable_host", "params": {"host": _host(m.group(1))}}

def _parse_isolate(m):
    return {"type": "isolate_host", "params": {"host": _host(m.group(1))}}

def _parse_block_from(m):
    sources_text = m.group(1)
    target_text  = m.group(2)
    sources = _hosts(sources_text)
    target  = _host(target_text)
    if target in sources:
        raise ValueError(f"Target '{target}' cannot also be a source.")
    return {"type": "block_from", "params": {"sources": sources, "target": target}}

def _parse_block_pair(m):
    hosts = _hosts(m.group(0))   # scan the whole match
    if len(hosts) < 2:
        raise ValueError("'block … and …' requires exactly two host names.")
    return {"type": "block_pair", "params": {"a": hosts[0], "b": hosts[1]}}

def _parse_allow_only_staff(m):
    return {"type": "allow_only_staff", "params": {"target": _host(m.group(1))}}

def _parse_limit_download(m):
    mbps = _mbps(m.group(0))
    return {"type": "limit_download", "params": {"mbps": mbps}}

def _parse_remove(m):
    return {"type": "remove", "params": {"id": m.group(1).lower()}}

# (regex, handler) pairs — ORDER MATTERS: more specific patterns first
_PATTERNS = [
    # "block h3 and h4 from h5"  — must come before plain block_pair
    (re.compile(
        rf"block\s+(.+?)\s+from\s+({HOST_RE})",
        re.IGNORECASE),
     _parse_block_from),

    # "block h2 and h3"
    (re.compile(
        rf"block\s+({HOST_RE})\s+and\s+({HOST_RE})",
        re.IGNORECASE),
     _parse_block_pair),

    # "disable h4"
    (re.compile(
        r"disable\s+(.+)",
        re.IGNORECASE),
     _parse_disable),

    # "enable h4"
    (re.compile(
        r"enable\s+(.+)",
        re.IGNORECASE),
     _parse_enable),

    # "isolate h6"
    (re.compile(
        r"isolate\s+(.+)",
        re.IGNORECASE),
     _parse_isolate),

    # "only staff can reach h5"
    (re.compile(
        rf"only\s+staff\s+can\s+reach\s+({HOST_RE})",
        re.IGNORECASE),
     _parse_allow_only_staff),

    # "limit downloads to 2 mbps"  (also: "limit download to …")
    (re.compile(
        r"limit\s+downloads?\s+to\s+\d+(?:\.\d+)?\s*mbps?",
        re.IGNORECASE),
     _parse_limit_download),

    # "remove i-0001"
    (re.compile(
        r"remove\s+(i-\d{4,})",
        re.IGNORECASE),
     _parse_remove),
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(text: str) -> dict:
    """
    Parse *text* into an intent dict.

    Returns:
        {"type": str, "params": dict}

    Raises:
        ValueError  — if no pattern matches, with a human-readable message.
    """
    text = text.strip()
    for pattern, handler in _PATTERNS:
        m = pattern.search(text)
        if m:
            return handler(m)
    raise ValueError(
        f"Unrecognised intent: '{text}'\n"
        "Supported commands:\n"
        "  disable h<N>                     — block all traffic to/from host\n"
        "  enable h<N>                      — re-allow a previously disabled host\n"
        "  block h<A> and h<B>              — block traffic between two hosts\n"
        "  block h<A> and h<B> from h<C>    — block two sources from reaching a target\n"
        "  only staff can reach h<N>        — restrict access to a host to staff only\n"
        "  isolate h<N>                     — cut a host off from the whole network\n"
        "  limit downloads to <N> mbps      — cap the download queue rate\n"
        "  remove i-<NNNN>                  — delete a stored intent by id"
    )
