#!/bin/bash
# run_all.sh — Start the full IDAN/QoSFlow stack from scratch.
#
# Run order (match section 10 of the plan):
#   Terminal 1: ryu-manager qos_controller.py
#   Terminal 2: sudo python3 topology.py
#   Terminal 3: sudo ./setup_queues.sh          (after topology is up)
#   Terminal 4: python3 -m idan.cli
#
# This helper script opens all four in separate gnome-terminal windows.
# If you prefer tmux or separate terminals, follow the manual order below.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================================"
echo "  IDAN / QoSFlow — Startup Sequence"
echo "============================================================"
echo ""
echo "Step 0: Cleaning old Mininet state..."
sudo mn -c 2>/dev/null || true

echo ""
echo "Step 1: Starting RYU controller..."
echo "   Command: ryu-manager $SCRIPT_DIR/qos_controller.py"
echo "   → Open a NEW terminal and run:"
echo "       cd $SCRIPT_DIR && ryu-manager qos_controller.py"
echo ""

echo "Step 2: Starting Mininet topology..."
echo "   Command: sudo python3 $SCRIPT_DIR/topology.py"
echo "   → Open a NEW terminal and run:"
echo "       cd $SCRIPT_DIR && sudo python3 topology.py"
echo ""

echo "Step 3: Set up queues (AFTER topology is up and pingall passes)..."
echo "   Command: sudo $SCRIPT_DIR/setup_queues.sh"
echo "   → Run this in any terminal after Mininet shows 'Network is up'."
echo ""

echo "Step 4: Start the IDAN CLI..."
echo "   Command: python3 -m idan.cli"
echo "   → Open a NEW terminal and run:"
echo "       cd $SCRIPT_DIR && python3 -m idan.cli"
echo ""

echo "============================================================"
echo "  Quick-start (auto-open gnome-terminal tabs, if available):"
echo "============================================================"

if command -v gnome-terminal &>/dev/null; then
    gnome-terminal \
        --tab --title="RYU Controller" \
            -- bash -c "cd $SCRIPT_DIR && ryu-manager qos_controller.py; exec bash" \
        --tab --title="Mininet Topology" \
            -- bash -c "cd $SCRIPT_DIR && sleep 2 && sudo python3 topology.py; exec bash" \
        --tab --title="IDAN CLI" \
            -- bash -c "cd $SCRIPT_DIR && echo 'Wait for topology, then run setup_queues.sh first.' && sleep 1 && python3 -m idan.cli; exec bash" \
        2>/dev/null || true
    echo "Opened gnome-terminal tabs."
else
    echo "(gnome-terminal not found — open terminals manually using the commands above)"
fi
