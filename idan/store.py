#!/usr/bin/env python3
"""
idan/store.py — Persistent intent store (data/intents.json).

Provides four operations:
    load()          -> list of intent dicts
    add(intent)     -> intent with "id" field filled in
    remove(id)      -> True if removed, False if not found
    next_id()       -> next available id string ("i-0001", "i-0002", …)

The file is written atomically (write to a tmp file, then rename) so a crash
mid-write never leaves a corrupt JSON file.
"""

import json
import os
import tempfile

# ---------------------------------------------------------------------------
# Paths (relative to this file's parent directory, not cwd)
# ---------------------------------------------------------------------------

_HERE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = os.path.join(_HERE, "data", "intents.json")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read() -> list:
    """Read and parse the JSON file. Returns [] if the file is missing/empty."""
    if not os.path.exists(_STORE):
        return []
    try:
        with open(_STORE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write(intents: list) -> None:
    """Write intents atomically by writing to a temp file then renaming."""
    os.makedirs(os.path.dirname(_STORE), exist_ok=True)
    dir_ = os.path.dirname(_STORE)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(intents, f, indent=2)
        os.replace(tmp_path, _STORE)  # atomic on POSIX
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load() -> list:
    """Return the full list of stored intents."""
    return _read()


def next_id() -> str:
    """Return the next unused id string (e.g. 'i-0001')."""
    intents = _read()
    if not intents:
        return "i-0001"
    # Extract the numeric part of each existing id
    nums = []
    for intent in intents:
        id_str = intent.get("id", "")
        if id_str.startswith("i-") and id_str[2:].isdigit():
            nums.append(int(id_str[2:]))
    n = max(nums) + 1 if nums else 1
    return f"i-{n:04d}"


def add(intent: dict) -> dict:
    """
    Assign an id to *intent* (if it doesn't have one), append it to the store,
    write to disk, and return the updated intent dict.
    """
    intents = _read()
    if "id" not in intent or not intent["id"]:
        intent = dict(intent)           # don't mutate the caller's dict
        intent["id"] = next_id()
    intents.append(intent)
    _write(intents)
    return intent


def remove(intent_id: str) -> bool:
    """
    Remove the intent with *intent_id* from the store.

    Returns True if an intent was removed, False if the id was not found.
    """
    intents = _read()
    before  = len(intents)
    intents = [i for i in intents if i.get("id") != intent_id]
    if len(intents) == before:
        return False
    _write(intents)
    return True


def get(intent_id: str) -> dict | None:
    """Return the intent with *intent_id*, or None if not found."""
    for intent in _read():
        if intent.get("id") == intent_id:
            return intent
    return None
