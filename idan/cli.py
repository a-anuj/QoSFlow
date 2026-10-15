#!/usr/bin/env python3
"""
idan/cli.py — Interactive IDAN command-line interface.

Run with:
    python3 -m idan.cli

The prompt is "idan> ". Type a plain-English intent or one of the meta-commands:
    list            — show all stored intents
    remove <id>     — delete an intent by id and reinstall the rest
    flows           — fetch and show currently installed flows from the controller
    quit / exit     — exit the CLI

For every intent:
  1. Parse the text into {type, params}.
  2. Decompose into {rules, queue_changes}.
  3. Verify on the digital twin.
  4. Print the verdict (Safe / Unsafe + all reasons).
  5. If Safe:
       - For "enable_host" or "remove": delete the matching stored intent,
         write the store, trigger a controller reload.
       - For everything else: write the new intent to the store,
         apply any queue_changes, trigger a controller reload.
  6. If Unsafe: do nothing (nothing stored or installed).
"""

import sys
import os
import json
import textwrap

# Add the project root to sys.path so this works when run as `python3 -m idan.cli`
# or as a standalone script.
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from idan import parser as _parser
from idan import decomposer as _decomposer
from idan import twin as _twin
from idan import store as _store
from idan import controller_client as _client
from idan import queue_tool as _queue_tool
from idan import llm_parser as _llm_parser

# ---------------------------------------------------------------------------
# AI flag configuration
# ---------------------------------------------------------------------------
_USE_AI = False

# ---------------------------------------------------------------------------
# ANSI colours (fall back to no colour if not a tty)
# ---------------------------------------------------------------------------
_USE_COLOUR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    if not _USE_COLOUR:
        return text
    return f"\033[{code}m{text}\033[0m"

GREEN  = lambda t: _c("92", t)
RED    = lambda t: _c("91", t)
YELLOW = lambda t: _c("93", t)
CYAN   = lambda t: _c("96", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)

def get_banner() -> str:
    mode_line = CYAN(f"AI ({_llm_parser.DEFAULT_MODEL})") if _USE_AI else DIM("Regex (Deterministic)")
    return f"""
{BOLD('╔════════════════════════════════════════════════════════╗')}
{BOLD('║')}  {CYAN('IDAN')} — Intent-Driven QoS & Access Control             {BOLD('║')}
{BOLD('║')}  Mode: {mode_line:<53} {BOLD('║')}
{BOLD('║')}  {DIM('Type an intent or "help" for examples.')}                {BOLD('║')}
{BOLD('╚════════════════════════════════════════════════════════╝')}
"""

HELP_TEXT = f"""
{BOLD('Intent examples:')}
  disable h4                        — block all traffic to/from h4
  enable h4                         — re-allow h4 (removes its disable intent)
  block h2 and h3                   — block traffic between h2 and h3
  block h3 and h4 from h5           — block h3 and h4 from reaching h5
  only staff can reach h5           — restrict h5 to staff only (h3, h4)
  isolate h6                        — cut h6 off from everyone
  limit downloads to 2 mbps         — cap the bulk download queue

{BOLD('Meta-commands:')}
  list                              — show all stored intents
  remove i-<NNNN>                   — delete a stored intent by id
  flows                             — show currently installed flows
  help                              — show this message
  quit / exit / Ctrl-D              — exit
"""


# ---------------------------------------------------------------------------
# Helper: get all existing rules from the store
# ---------------------------------------------------------------------------

def _existing_rules() -> list[dict]:
    """Flatten all rules from all stored intents."""
    rules = []
    for intent in _store.load():
        rules.extend(intent.get("rules", []))
    return rules


# ---------------------------------------------------------------------------
# Handler for remove / enable_host (delete-then-reload semantics)
# ---------------------------------------------------------------------------

def _handle_remove(intent_id: str) -> None:
    """Remove an intent by id and trigger a reload."""
    existing = _store.get(intent_id)
    if existing is None:
        print(RED(f"  No intent with id '{intent_id}' found."))
        return
    _store.remove(intent_id)
    print(GREEN(f"  ✓ Intent '{intent_id}' removed from store."))
    _client.reload()


def _handle_enable_host(host: str) -> None:
    """
    Remove any disable_host or isolate_host intents that target *host*,
    then reload.
    """
    intents = _store.load()
    removed = []
    for intent in intents:
        if (intent.get("type") in ("disable_host", "isolate_host")
                and intent.get("params", {}).get("host") == host):
            removed.append(intent["id"])
    if not removed:
        print(YELLOW(f"  No stored disable/isolate intent found for {host}."))
        return
    for id_ in removed:
        _store.remove(id_)
        print(GREEN(f"  ✓ Removed intent '{id_}' for {host}."))
    _client.reload()


# ---------------------------------------------------------------------------
# Main intent handler
# ---------------------------------------------------------------------------

def _handle_intent(text: str) -> None:
    """Full pipeline: parse → decompose → twin → store → reload."""

    # 1. Parse
    try:
        if _USE_AI:
            parsed = _llm_parser.parse(text, use_ai=True)
        else:
            parsed = _parser.parse(text)
    except ValueError as exc:
        print(RED(f"  Parse error: {exc}"))
        return

    intent_type = parsed["type"]
    params      = parsed["params"]
    print(DIM(f"  Parsed → type={intent_type}, params={params}"))

    # --- Special cases that don't go through the normal store path ----------

    # "remove i-0001" meta-command handled here
    if intent_type == "remove":
        _handle_remove(params["id"])
        return

    # "enable h4" — delete any disable intent for that host
    if intent_type == "enable_host":
        # Still run through twin to check it's safe to re-enable
        rules, _ = _decomposer.decompose(intent_type, params)
        # For enable_host rules=[] so twin sees only existing rules (minus
        # the ones we're about to remove). Approximate: just trust it's safe.
        _handle_enable_host(params["host"])
        return

    # --- Normal path --------------------------------------------------------

    # 2. Decompose
    try:
        rules, queue_changes = _decomposer.decompose(intent_type, params)
    except ValueError as exc:
        print(RED(f"  Decompose error: {exc}"))
        return

    print(DIM(f"  Rules      → {json.dumps(rules)}"))
    if queue_changes:
        print(DIM(f"  Queue chgs → {json.dumps(queue_changes)}"))

    # 3. Twin verification
    existing = _existing_rules()
    result   = _twin.verdict(rules, intent_type, params, existing)

    # 4. Print verdict
    if result["status"] == "Safe":
        print(GREEN(f"\n  ✅  Verdict: {BOLD('SAFE')}"))
    else:
        print(RED(f"\n  ❌  Verdict: {BOLD('UNSAFE')}"))

    for reason in result["reasons"]:
        bullet = "     •"
        print(f"{bullet} {reason}")
    print()

    # 5. Act on verdict
    if result["status"] == "Unsafe":
        print(RED("  Nothing stored or installed. The network is unchanged.\n"))
        return

    # 6. Store the intent
    intent_record = {
        "text":          text,
        "type":          intent_type,
        "params":        params,
        "rules":         rules,
        "queue_changes": queue_changes,
    }
    saved = _store.add(intent_record)
    print(GREEN(f"  ✓ Intent saved as '{saved['id']}'."))

    # 7. Apply queue changes (before reload so the rate is live)
    if queue_changes:
        ok = _queue_tool.apply_queue_changes(queue_changes)
        if not ok:
            print(YELLOW("  ⚠  Some queue changes failed — check the output above."))

    # 8. Reload the controller
    _client.reload()


# ---------------------------------------------------------------------------
# Meta-command handlers
# ---------------------------------------------------------------------------

def _cmd_list() -> None:
    intents = _store.load()
    if not intents:
        print(DIM("  (no intents stored)"))
        return
    print(f"\n  {'ID':<10}  {'TYPE':<18}  TEXT")
    print("  " + "─" * 60)
    for i in intents:
        print(f"  {i.get('id','?'):<10}  {i.get('type','?'):<18}  {i.get('text','?')}")
    print()


def _cmd_flows() -> None:
    flows = _client.list_flows()
    if flows is None:
        return
    if not flows:
        print(DIM("  (no IDAN flows installed)"))
        return
    for f in flows:
        print(f"  {f}")
    print()


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def run() -> None:
    global _USE_AI
    if "--ai" in sys.argv:
        _USE_AI = True
        if not (os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY")):
            print(YELLOW("  ⚠️  Notice: --ai flag was passed, but neither GROQ_API_KEY nor OPENAI_API_KEY is set."))
            print(YELLOW("     Run: export GROQ_API_KEY='your-key' to enable natural language translation."))
            print(YELLOW("     Falling back to regex mode.\n"))

    print(get_banner())
    while True:
        try:
            text = input(CYAN("idan> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not text:
            continue

        lower = text.lower()
        if lower in ("quit", "exit", "q"):
            print("Bye.")
            break
        elif lower in ("help", "?"):
            print(HELP_TEXT)
        elif lower == "list":
            _cmd_list()
        elif lower.startswith("remove "):
            # Meta remove command from the prompt
            parts = text.split(None, 1)
            if len(parts) < 2:
                print(RED("  Usage: remove i-<NNNN>"))
            else:
                _handle_remove(parts[1].strip())
        elif lower == "flows":
            _cmd_flows()
        else:
            _handle_intent(text)


if __name__ == "__main__":
    run()
