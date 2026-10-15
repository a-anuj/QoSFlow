#!/usr/bin/env python3
"""
tests/test_twin.py — Unit tests for idan/twin.py

Tests all rows from section 8 of the plan:
  1.  limit downloads to 2 mbps  → Safe
  2.  disable h4                 → Safe (h3 still reaches h5)
  3.  block h2 and h3            → Safe
  4.  only staff can reach h5    → Safe
  5.  isolate h6                 → Safe
  6.  block h3 and h4 from h5   → Unsafe (no staff can reach server)
  7.  disable h1                 → Unsafe (breaks h1→h3 video)
  8.  disable h3                 → Unsafe (h3 is staff; check if h4 still covers)

Run with:
    pytest tests/test_twin.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from idan import decomposer, twin


def _verdict(intent_type: str, params: dict, existing_rules: list = None) -> dict:
    """Helper: decompose then run twin.verdict."""
    rules, _qc = decomposer.decompose(intent_type, params)
    return twin.verdict(rules, intent_type, params, existing_rules or [])


# ---------------------------------------------------------------------------
# Safe cases
# ---------------------------------------------------------------------------

class TestSafeCases:

    def test_limit_download_2mbps(self):
        """Row 1: limit downloads to 2 mbps → Safe"""
        v = _verdict("limit_download", {"mbps": 2.0})
        assert v["status"] == "Safe", f"Expected Safe, got: {v['reasons']}"

    def test_limit_download_boundary_low(self):
        """0.5 Mbps is the minimum allowed."""
        v = _verdict("limit_download", {"mbps": 0.5})
        assert v["status"] == "Safe"

    def test_limit_download_boundary_high(self):
        """10 Mbps is the link cap."""
        v = _verdict("limit_download", {"mbps": 10.0})
        assert v["status"] == "Safe"

    def test_disable_h4(self):
        """Row 2: disable h4 → Safe (h3 still reaches h5)"""
        v = _verdict("disable_host", {"host": "h4"})
        assert v["status"] == "Safe", f"Expected Safe, got: {v['reasons']}"

    def test_disable_h6(self):
        """disable h6 → Safe (h6 is guest, doesn't break anything critical)"""
        v = _verdict("disable_host", {"host": "h6"})
        assert v["status"] == "Safe", f"Expected Safe, got: {v['reasons']}"

    def test_block_h2_and_h3(self):
        """Row 4: block h2 and h3 → Safe (h1↔h3 still works)"""
        v = _verdict("block_pair", {"a": "h2", "b": "h3"})
        assert v["status"] == "Safe", f"Expected Safe, got: {v['reasons']}"

    def test_allow_only_staff_h5(self):
        """Row 5: only staff can reach h5 → Safe"""
        v = _verdict("allow_only_staff", {"target": "h5"})
        assert v["status"] == "Safe", f"Expected Safe, got: {v['reasons']}"

    def test_isolate_h6(self):
        """Row 6: isolate h6 → Safe"""
        v = _verdict("isolate_host", {"host": "h6"})
        assert v["status"] == "Safe", f"Expected Safe, got: {v['reasons']}"

    def test_isolate_h2(self):
        """isolate h2 → Safe (h2 is download host, not critical)"""
        v = _verdict("isolate_host", {"host": "h2"})
        assert v["status"] == "Safe", f"Expected Safe, got: {v['reasons']}"

    def test_block_h5_from_h6(self):
        """block h6 from reaching h5 → Safe"""
        v = _verdict("block_from", {"sources": ["h6"], "target": "h5"})
        assert v["status"] == "Safe"


# ---------------------------------------------------------------------------
# Unsafe cases
# ---------------------------------------------------------------------------

class TestUnsafeCases:

    def test_block_h3_and_h4_from_h5(self):
        """Row 7: block h3 and h4 from h5 → Unsafe (no staff can reach server)"""
        v = _verdict("block_from", {"sources": ["h3", "h4"], "target": "h5"})
        assert v["status"] == "Unsafe", f"Expected Unsafe, got: {v['reasons']}"
        # The server-safety reason should be present
        assert any("server safety" in r.lower() or "staff" in r.lower()
                   for r in v["reasons"]), f"Missing server safety reason: {v['reasons']}"

    def test_disable_h1(self):
        """Row 8: disable h1 → Unsafe (breaks h1→h3 video call)"""
        v = _verdict("disable_host", {"host": "h1"})
        assert v["status"] == "Unsafe", f"Expected Unsafe, got: {v['reasons']}"
        # Critical-flow reason should be present
        assert any("h1" in r and "h3" in r for r in v["reasons"]), \
            f"Missing critical flow reason: {v['reasons']}"

    def test_disable_h3_blocked_by_critical_flow(self):
        """disable h3 → Unsafe because h1→h3 is the critical video call path.
        Even though h4 can still reach h5 (server safety passes), the
        critical-flow check (h1→h3) fails because h3 itself is disabled."""
        v = _verdict("disable_host", {"host": "h3"})
        assert v["status"] == "Unsafe", \
            f"disable h3 should be Unsafe (h1→h3 critical flow broken): {v['reasons']}"
        assert any("h1" in r and "h3" in r for r in v["reasons"]), \
            f"Missing critical-flow reason: {v['reasons']}"

    def test_disable_both_staff(self):
        """disable h3 and h4 via two calls → second should be Unsafe"""
        rules1, _ = decomposer.decompose("disable_host", {"host": "h3"})
        # Now try to also disable h4 with h3 already disabled
        v = _verdict("disable_host", {"host": "h4"}, existing_rules=rules1)
        assert v["status"] == "Unsafe", \
            f"Should be Unsafe (no staff can reach h5): {v['reasons']}"

    def test_limit_download_too_low(self):
        """limit downloads to 0.1 mbps → Unsafe (below min queue rate)"""
        v = _verdict("limit_download", {"mbps": 0.1})
        assert v["status"] == "Unsafe"

    def test_limit_download_too_high(self):
        """limit downloads to 11 mbps → Unsafe (above link cap)"""
        v = _verdict("limit_download", {"mbps": 11.0})
        assert v["status"] == "Unsafe"

    def test_disable_h1_is_critical(self):
        """disable h1 cuts the video call — must be rejected."""
        v = _verdict("disable_host", {"host": "h1"})
        assert v["status"] == "Unsafe"

    def test_disable_h3_cuts_video_path_check(self):
        """disable h3 does NOT cut h1→h3 (h3 is the target, not the source)."""
        # After disabling h3: h1 cannot reach h3 because h3 is disabled.
        v = _verdict("disable_host", {"host": "h3"})
        # h3 is disabled → h1→h3 is blocked → this SHOULD be Unsafe
        # because critical-flow check says h1→h3 must remain reachable.
        assert v["status"] == "Unsafe", \
            f"disable h3 should be Unsafe (h1→h3 is critical and gets broken): {v['reasons']}"


# ---------------------------------------------------------------------------
# Reachability unit tests
# ---------------------------------------------------------------------------

class TestReachability:

    def test_no_rules_all_reachable(self):
        """With no rules, all pairs should be reachable."""
        for src in ["h1", "h2", "h3"]:
            for dst in ["h4", "h5", "h6"]:
                assert twin.reachable(twin._G, src, dst, []), \
                    f"{src}→{dst} should be reachable with no rules"

    def test_drop_src_blocks_that_src(self):
        rules = [{"dpid": 2, "priority": 200, "action": "drop",
                  "match": {"eth_src": "00:00:00:00:00:04"}}]
        # h4 → h3: the rule on dpid=2 drops eth_src=h4's MAC → blocked
        assert not twin.reachable(twin._G, "h4", "h3", rules)

    def test_drop_src_does_not_affect_others(self):
        rules = [{"dpid": 2, "priority": 200, "action": "drop",
                  "match": {"eth_src": "00:00:00:00:00:04"}}]
        # h3 → h4 is a different direction — not blocked by this rule
        assert twin.reachable(twin._G, "h3", "h4", rules)

    def test_drop_dst_blocks_traffic_to_host(self):
        rules = [{"dpid": 2, "priority": 200, "action": "drop",
                  "match": {"eth_dst": "00:00:00:00:00:04"}}]
        # h3 → h4: blocked because eth_dst=h4's MAC is dropped on dpid=2
        assert not twin.reachable(twin._G, "h3", "h4", rules)

    def test_wrong_dpid_rule_has_no_effect(self):
        """A rule on dpid=1 should not affect traffic purely between s2 hosts."""
        rules = [{"dpid": 1, "priority": 200, "action": "drop",
                  "match": {"eth_src": "00:00:00:00:00:04"}}]
        # h4 is on s2 (dpid=2). Path h4→h3 goes through s2 only.
        # Rule is on dpid=1 which is NOT on the path → not blocked.
        assert twin.reachable(twin._G, "h4", "h3", rules)
