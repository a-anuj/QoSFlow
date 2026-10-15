#!/usr/bin/env bash
# =============================================================================
# inject_problems.sh — Topology Chaos & Fault Injection Script (Hosts h11..h20)
#
# Injects 4 network problems strictly affecting the last 10 hosts (h11..h20):
#   1. IP Conflict: Sets h11 and h12 to the exact same IP (10.0.0.11/24).
#   2. Host Isolation: Shuts down h14's link interface (h14-eth0 down).
#   3. Subnet Misconfiguration: Changes h16's IP to wrong subnet (192.168.1.16/24).
#   4. Rogue Flow Rule: Installs an OpenFlow blackhole rule on s10 between h19 and h20.
#
# Usage:
#   sudo ./inject_problems.sh           # Inject the 4 problems
#   sudo ./inject_problems.sh --restore # Restore all hosts and flows to normal
# =============================================================================

set -e

# ANSI Color codes
RED='\033[91m'
GREEN='\033[92m'
YELLOW='\033[93m'
CYAN='\033[96m'
BOLD='\033[1m'
RESET='\033[0m'

# Check root privileges
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}${BOLD}Error:${RESET} This script must be run as root (use: sudo $0)"
    exit 1
fi

# Helper: execute a command inside a Mininet host namespace
run_host() {
    local host="$1"
    shift
    local pid
    pid=$(pgrep -f "mininet:${host}\b" | head -n 1)
    if [ -z "$pid" ]; then
        echo -e "${RED}Error:${RESET} Mininet host '${host}' is not running! Please start topology.py first." >&2
        return 1
    fi

    if command -v mnexec >/dev/null 2>&1; then
        mnexec -a "$pid" "$@"
    else
        nsenter -t "$pid" -n "$@"
    fi
}

# =============================================================================
# RESTORE FUNCTION
# =============================================================================
restore_all() {
    echo -e "\n${CYAN}${BOLD}╔════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${CYAN}${BOLD}║        RESTORE: Fixing All Injected Faults             ║${RESET}"
    echo -e "${CYAN}${BOLD}╚════════════════════════════════════════════════════════╝${RESET}\n"

    echo -e "${YELLOW}[1/4] Restoring h12 IP address to 10.0.0.12/24...${RESET}"
    run_host "h12" ip addr flush dev h12-eth0
    run_host "h12" ip addr add 10.0.0.12/24 dev h12-eth0
    echo -e "${GREEN}  ✓ h12 restored to 10.0.0.12/24${RESET}"

    echo -e "${YELLOW}[2/4] Bringing h14 interface back up...${RESET}"
    run_host "h14" ip link set h14-eth0 up
    echo -e "${GREEN}  ✓ h14-eth0 interface is UP${RESET}"

    echo -e "${YELLOW}[3/4] Restoring h16 IP to 10.0.0.16/24 (correct subnet)...${RESET}"
    run_host "h16" ip addr flush dev h16-eth0
    run_host "h16" ip addr add 10.0.0.16/24 dev h16-eth0
    echo -e "${GREEN}  ✓ h16 restored to 10.0.0.16/24${RESET}"

    echo -e "${YELLOW}[4/4] Removing rogue drop flows on switch s10 (cookie 0xDEAD)...${RESET}"
    ovs-ofctl -O OpenFlow13 del-flows s10 "cookie=0xDEAD/0xFFFFFFFF" 2>/dev/null || true
    echo -e "${GREEN}  ✓ Rogue flows on s10 deleted. h19 <-> h20 communication restored.${RESET}"

    echo -e "\n${GREEN}${BOLD} All 4 problems have been restored to normal!${RESET}\n"
    exit 0
}

# Check for --restore / -r flag
if [ "$1" = "--restore" ] || [ "$1" = "-r" ] || [ "$1" = "restore" ]; then
    restore_all
fi

# =============================================================================
# INJECT PROBLEMS FUNCTION
# =============================================================================
echo -e "\n${RED}${BOLD}╔════════════════════════════════════════════════════════╗${RESET}"
echo -e "${RED}${BOLD}║   INJECTING 4 NETWORK PROBLEMS (Hosts h11..h20)        ║${RESET}"
echo -e "${RED}${BOLD}╚════════════════════════════════════════════════════════╝${RESET}\n"

# Check if mininet is up
if ! pgrep -f "mininet:h11\b" >/dev/null 2>&1; then
    echo -e "${RED}${BOLD}Error:${RESET} Mininet does not seem to be running."
    echo -e "Please start the network first: ${BOLD}sudo python3 topology.py${RESET}"
    exit 1
fi

# -----------------------------------------------------------------------------
# Problem 1: IP Conflict (Duplicate IP on h11 & h12)
# -----------------------------------------------------------------------------
echo -e "${BOLD}${CYAN}Problem 1: IP Conflict (Duplicate IP Collision)${RESET}"
echo -e "  Target: ${YELLOW}h11${RESET} and ${YELLOW}h12${RESET} (Guest Wi-Fi on Switch s6)"
echo -e "  Action: Changing h12's IP from 10.0.0.12 to ${RED}10.0.0.11/24${RESET}"
run_host "h12" ip addr flush dev h12-eth0
run_host "h12" ip addr add 10.0.0.11/24 dev h12-eth0
echo -e "${RED}  ❌ Injected: Both h11 and h12 now have IP 10.0.0.11! (ARP collision)${RESET}\n"

# -----------------------------------------------------------------------------
# Problem 2: Host Isolation (Link Interface Down)
# -----------------------------------------------------------------------------
echo -e "${BOLD}${CYAN}Problem 2: Host Isolation (Physical / Link Failure)${RESET}"
echo -e "  Target: ${YELLOW}h14${RESET} (Lobby IoT Display on Switch s7)"
echo -e "  Action: Forcing interface ${RED}h14-eth0 DOWN${RESET}"
run_host "h14" ip link set h14-eth0 down
echo -e "${RED}  ❌ Injected: h14 is isolated! (100% packet loss to/from h14)${RESET}\n"

# -----------------------------------------------------------------------------
# Problem 3: Subnet Misconfiguration
# -----------------------------------------------------------------------------
echo -e "${BOLD}${CYAN}Problem 3: Subnet Misconfiguration${RESET}"
echo -e "  Target: ${YELLOW}h16${RESET} (Backup Server on Switch s8)"
echo -e "  Action: Changing h16 IP from 10.0.0.16/24 to ${RED}192.168.1.16/24${RESET}"
run_host "h16" ip addr flush dev h16-eth0
run_host "h16" ip addr add 192.168.1.16/24 dev h16-eth0
echo -e "${RED}  ❌ Injected: h16 is in wrong subnet (192.168.1.0/24)! Cannot reach 10.0.0.0/24${RESET}\n"

# -----------------------------------------------------------------------------
# Problem 4: Rogue OpenFlow Flow Rule (Blackhole)
# -----------------------------------------------------------------------------
echo -e "${BOLD}${CYAN}Problem 4: Rogue OpenFlow Drop Rule (Switch Blackhole)${RESET}"
echo -e "  Target: ${YELLOW}h19${RESET} <-> ${YELLOW}h20${RESET} (Executive & Admin on Switch s10)"
echo -e "  Action: Installing priority 600 drop flow on Switch s10"
ovs-ofctl -O OpenFlow13 add-flow s10 "cookie=0xDEAD,priority=600,dl_src=00:00:00:00:00:13,dl_dst=00:00:00:00:00:14,actions=drop"
ovs-ofctl -O OpenFlow13 add-flow s10 "cookie=0xDEAD,priority=600,dl_src=00:00:00:00:00:14,dl_dst=00:00:00:00:00:13,actions=drop"
echo -e "${RED}  ❌ Injected: Switch s10 silently drops all packets between h19 and h20!${RESET}\n"

# -----------------------------------------------------------------------------
# Summary & Verification Guide
# -----------------------------------------------------------------------------
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  4 Chaos Faults Successfully Injected!${RESET}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════${RESET}"
echo -e "How to observe in Mininet CLI:"
echo -e "  ${BOLD}mininet> h11 ping h12${RESET}   -> ARP conflicts & drops"
echo -e "  ${BOLD}mininet> h13 ping h14${RESET}   -> Destination Host Unreachable (h14 isolated)"
echo -e "  ${BOLD}mininet> h15 ping h16${RESET}   -> Subnet mismatch (100% loss)"
echo -e "  ${BOLD}mininet> h19 ping h20${RESET}   -> Blocked by rogue OpenFlow rule on s10"
echo -e ""
echo -e "To restore the network to pristine state, run:"
echo -e "  ${BOLD}sudo ./inject_problems.sh --restore${RESET}\n"
