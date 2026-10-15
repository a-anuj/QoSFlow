#!/usr/bin/env python3
"""
tests/test_parser.py — Unit tests for idan/parser.py

Run with:
    pytest tests/test_parser.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from idan.parser import parse


# ---------------------------------------------------------------------------
# Happy-path tests (all 8 intent types)
# ---------------------------------------------------------------------------

class TestDisableHost:
    def test_basic(self):
        r = parse("disable h4")
        assert r == {"type": "disable_host", "params": {"host": "h4"}}

    def test_case_insensitive(self):
        r = parse("DISABLE H4")
        assert r["type"] == "disable_host"
        assert r["params"]["host"] == "h4"

    def test_with_trailing_space(self):
        r = parse("  disable h1  ")
        assert r["params"]["host"] == "h1"

    def test_each_host(self):
        for n in range(1, 7):
            r = parse(f"disable h{n}")
            assert r["params"]["host"] == f"h{n}"


class TestEnableHost:
    def test_basic(self):
        r = parse("enable h4")
        assert r == {"type": "enable_host", "params": {"host": "h4"}}

    def test_different_host(self):
        r = parse("enable h1")
        assert r["params"]["host"] == "h1"


class TestBlockPair:
    def test_basic(self):
        r = parse("block h2 and h3")
        assert r["type"] == "block_pair"
        assert r["params"]["a"] == "h2"
        assert r["params"]["b"] == "h3"

    def test_order_matters(self):
        r = parse("block h5 and h6")
        assert r["params"]["a"] == "h5"
        assert r["params"]["b"] == "h6"


class TestBlockFrom:
    def test_two_sources(self):
        r = parse("block h3 and h4 from h5")
        assert r["type"] == "block_from"
        assert set(r["params"]["sources"]) == {"h3", "h4"}
        assert r["params"]["target"] == "h5"

    def test_single_source(self):
        r = parse("block h2 from h5")
        assert r["type"] == "block_from"
        assert "h2" in r["params"]["sources"]
        assert r["params"]["target"] == "h5"


class TestAllowOnlyStaff:
    def test_basic(self):
        r = parse("only staff can reach h5")
        assert r == {"type": "allow_only_staff", "params": {"target": "h5"}}

    def test_case_insensitive(self):
        r = parse("Only Staff Can Reach h5")
        assert r["type"] == "allow_only_staff"


class TestIsolateHost:
    def test_basic(self):
        r = parse("isolate h6")
        assert r == {"type": "isolate_host", "params": {"host": "h6"}}


class TestLimitDownload:
    def test_integer_mbps(self):
        r = parse("limit downloads to 2 mbps")
        assert r["type"] == "limit_download"
        assert r["params"]["mbps"] == 2.0

    def test_float_mbps(self):
        r = parse("limit downloads to 1.5 mbps")
        assert r["params"]["mbps"] == 1.5

    def test_singular_form(self):
        r = parse("limit download to 3 mbps")
        assert r["type"] == "limit_download"

    def test_case_insensitive(self):
        r = parse("Limit Downloads To 5 Mbps")
        assert r["params"]["mbps"] == 5.0


class TestRemove:
    def test_basic(self):
        r = parse("remove i-0001")
        assert r == {"type": "remove", "params": {"id": "i-0001"}}

    def test_longer_id(self):
        r = parse("remove i-00123")
        assert r["params"]["id"] == "i-00123"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestParseErrors:
    def test_gibberish(self):
        with pytest.raises(ValueError):
            parse("make h4 faster")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse("")

    def test_misspelled_intent(self):
        with pytest.raises(ValueError):
            parse("dissable h4")

    def test_unknown_host_in_disable(self):
        # h9 doesn't exist
        with pytest.raises(ValueError):
            parse("disable h9")

    def test_block_without_and(self):
        # "block h2" alone doesn't match block_pair (needs "and")
        # it should also not match block_from
        with pytest.raises(ValueError):
            parse("block h2")
