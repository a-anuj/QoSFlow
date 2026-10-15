#!/usr/bin/env python3
"""
idan/controller_client.py — Communicate with the RYU controller REST API.

The controller exposes:
    POST /idan/reload    — sync all connected switches from data/intents.json
    GET  /idan/flows     — list currently installed IDAN flows (for debugging)

If the controller is unreachable, reload() prints a warning instead of
crashing so the CLI remains usable even while the controller is down.
(The intents are still persisted to disk; they'll be picked up when the
controller restarts and the switch reconnects.)
"""

import urllib.request
import urllib.error
import json

CONTROLLER_URL = "http://127.0.0.1:8080"
RELOAD_ENDPOINT = f"{CONTROLLER_URL}/idan/reload"
FLOWS_ENDPOINT  = f"{CONTROLLER_URL}/idan/flows"
TIMEOUT = 3  # seconds


def reload() -> bool:
    """
    POST /idan/reload to trigger a sync on all connected switches.

    Returns True on success, False if the controller is unreachable.
    Prints a warning (not an exception) on failure.
    """
    try:
        req = urllib.request.Request(
            RELOAD_ENDPOINT,
            data=b"{}",                   # empty body; RYU expects bytes
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode()
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = body
            print(f"[controller] Reload OK: {data}")
            return True
    except urllib.error.URLError as exc:
        print(
            f"[controller] WARNING: could not reach controller at {RELOAD_ENDPOINT}. "
            f"Reason: {exc.reason}. "
            "Intent is saved to disk — it will be installed when the controller restarts."
        )
        return False
    except Exception as exc:
        print(f"[controller] WARNING: unexpected error during reload: {exc}")
        return False


def list_flows() -> list | None:
    """
    GET /idan/flows to retrieve the list of currently installed IDAN rules.

    Returns a list of rule dicts, or None if the controller is unreachable.
    """
    try:
        with urllib.request.urlopen(FLOWS_ENDPOINT, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        print(f"[controller] WARNING: could not reach {FLOWS_ENDPOINT}: {exc.reason}")
        return None
    except Exception as exc:
        print(f"[controller] WARNING: unexpected error fetching flows: {exc}")
        return None
