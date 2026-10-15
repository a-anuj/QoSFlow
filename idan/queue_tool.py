#!/usr/bin/env python3
"""
idan/queue_tool.py — Change OVS queue rates without touching the controller.

Used by the CLI when the decomposer returns queue_changes (e.g. limit_download).

Each queue_change dict looks like:
    {"port": "s1-eth3", "queue_id": 1, "max_rate": 2000000}

The tool:
  1. Finds the OVS queue UUID for the given (port, queue_id) pair.
  2. Calls `ovs-vsctl set queue <uuid> other-config:max-rate=<bps>`.

Requires root / sudo (OVS commands need privilege). Prints a clear error
message if sudo is not available or OVS is not running.

Usage (from Python):
    from idan.queue_tool import apply_queue_changes
    apply_queue_changes([{"port": "s1-eth3", "queue_id": 1, "max_rate": 2000000}])

Usage (from shell, for testing):
    python3 -m idan.queue_tool s1-eth3 1 2000000
"""

import subprocess
import sys
import json
import re


def _run(cmd: list[str]) -> str:
    """Run a shell command and return stdout. Raises RuntimeError on failure."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _find_queue_uuid(port: str, queue_id: int) -> str | None:
    """
    Find the OVS UUID for the queue at position *queue_id* on *port*.

    Strategy:
      1. Get the QoS UUID attached to the port.
      2. List the QoS record to find the queue map.
      3. Return the UUID at the requested queue_id index.

    Returns None if the queue does not exist (QoS not configured yet).
    """
    try:
        # Step 1: get the QoS UUID on this port
        qos_uuid = _run(["sudo", "ovs-vsctl", "get", "port", port, "qos"])
        if not qos_uuid or qos_uuid == "[]":
            return None

        # Step 2: get the queues map from the QoS record
        # ovs-vsctl returns something like: {0=<uuid0>, 1=<uuid1>}
        queues_raw = _run(["sudo", "ovs-vsctl", "get", "qos", qos_uuid, "queues"])
        # Parse the map  {0=abc..., 1=def...}
        # Remove outer braces and split by comma
        queues_raw = queues_raw.strip("{}")
        queue_map = {}
        for part in queues_raw.split(","):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                queue_map[int(k.strip())] = v.strip()

        return queue_map.get(queue_id)

    except RuntimeError:
        return None


def set_max_rate(port: str, queue_id: int, bps: int) -> bool:
    """
    Set the max-rate (in bits/sec) for queue *queue_id* on *port*.

    Returns True on success, False on error (with an explanatory print).
    """
    uuid = _find_queue_uuid(port, queue_id)
    if uuid is None:
        print(
            f"[queue_tool] ERROR: Could not find queue {queue_id} on port {port}. "
            "Is setup_queues.sh been run yet?"
        )
        return False

    try:
        _run(["sudo", "ovs-vsctl", "set", "queue", uuid,
              f"other-config:max-rate={bps}"])
        mbps = bps / 1_000_000
        print(f"[queue_tool] Queue {queue_id} on {port} capped to {mbps:.2f} Mbps (UUID: {uuid}).")
        return True
    except RuntimeError as exc:
        print(f"[queue_tool] ERROR: {exc}")
        return False


def apply_queue_changes(queue_changes: list[dict]) -> bool:
    """
    Apply a list of queue_change dicts (as produced by the decomposer).

    Returns True if all changes succeeded, False if any failed.
    """
    if not queue_changes:
        return True
    all_ok = True
    for change in queue_changes:
        ok = set_max_rate(
            change["port"],
            change["queue_id"],
            change["max_rate"],
        )
        if not ok:
            all_ok = False
    return all_ok


# ---------------------------------------------------------------------------
# CLI entry point for quick testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python3 -m idan.queue_tool <port> <queue_id> <max_rate_bps>")
        print("  e.g. python3 -m idan.queue_tool s1-eth3 1 2000000")
        sys.exit(1)
    port_     = sys.argv[1]
    queue_id_ = int(sys.argv[2])
    bps_      = int(sys.argv[3])
    success   = set_max_rate(port_, queue_id_, bps_)
    sys.exit(0 if success else 1)
