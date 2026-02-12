#!/bin/bash
# WattSaver Privileged Helper
# This script runs as root via pkexec. It is the ONLY component that needs elevated privileges.
# Works with any Intel/AMD CPU — validates frequencies against actual hardware limits.
# Usage: wattsaver-helper.sh <command> <args...>

set -euo pipefail

COMMAND="${1:-}"
shift || true

die() { echo "ERROR: $*" >&2; exit 1; }

# Read hardware frequency limits from sysfs
get_hw_limits() {
    local cpu0="/sys/devices/system/cpu/cpu0/cpufreq"
    HW_MIN=$(cat "$cpu0/cpuinfo_min_freq" 2>/dev/null) || HW_MIN=0
    HW_MAX=$(cat "$cpu0/cpuinfo_max_freq" 2>/dev/null) || HW_MAX=99999999
}

case "$COMMAND" in

set-freq)
    # Accept any frequency in kHz, validate against hardware limits
    FREQ="${1:-}"
    [[ "$FREQ" =~ ^[0-9]+$ ]] || die "Frequency must be a positive integer (kHz)"

    get_hw_limits
    [ "$FREQ" -ge "$HW_MIN" ] && [ "$FREQ" -le "$HW_MAX" ] \
        || die "Frequency ${FREQ} kHz out of range (${HW_MIN}-${HW_MAX} kHz)"

    for cpu in /sys/devices/system/cpu/cpu[0-9]*; do
        [ -d "$cpu/cpufreq" ] || continue
        echo powersave > "$cpu/cpufreq/scaling_governor" 2>/dev/null || true
        echo "$FREQ" > "$cpu/cpufreq/scaling_max_freq" 2>/dev/null || true
    done
    echo "Max frequency set to ${FREQ} kHz on all cores"
    ;;

set-profile)
    # Legacy support: accept named profiles and map to set-freq
    PROFILE="${1:-}"
    case "$PROFILE" in
        battery)     FREQ=2400000 ;;
        balanced)    FREQ=3200000 ;;
        performance) FREQ=4100000 ;;
        *) die "Invalid profile: '$PROFILE'. Use set-freq for custom values." ;;
    esac

    for cpu in /sys/devices/system/cpu/cpu[0-9]*; do
        [ -d "$cpu/cpufreq" ] || continue
        echo powersave > "$cpu/cpufreq/scaling_governor" 2>/dev/null || true
        echo "$FREQ" > "$cpu/cpufreq/scaling_max_freq" 2>/dev/null || true
    done
    echo "Profile set to $PROFILE (max ${FREQ} kHz)"
    ;;

set-undervolt)
    OFFSET="${1:-}"

    # Validate: must be integer in range -200..0
    [[ "$OFFSET" =~ ^-?[0-9]+$ ]] || die "Undervolt offset must be an integer"
    [ "$OFFSET" -ge -200 ] && [ "$OFFSET" -le 0 ] || die "Undervolt offset must be between -200 and 0"

    CONF="/etc/intel-undervolt.conf"
    command -v intel-undervolt >/dev/null 2>&1 || die "intel-undervolt is not installed"
    [ -f "$CONF" ] || die "Config not found: $CONF"

    # Rewrite the config file
    cat > "$CONF" << EOF
# WattSaver managed intel-undervolt configuration
# Offset: ${OFFSET}mV

undervolt 0 'CPU' ${OFFSET}
undervolt 1 'GPU' 0
undervolt 2 'CPU Cache' ${OFFSET}
undervolt 3 'System Agent' 0
undervolt 4 'Analog I/O' 0

# Daemon update interval (milliseconds)
interval 5000

daemon undervolt:once
daemon power
daemon tjoffset
EOF

    intel-undervolt apply
    echo "Undervolt set to ${OFFSET}mV on CPU + Cache"
    ;;

set-gpu)
    MODE="${1:-}"
    case "$MODE" in
        integrated|hybrid|nvidia) ;;
        *) die "Invalid GPU mode: '$MODE'. Must be integrated|hybrid|nvidia" ;;
    esac

    command -v envycontrol >/dev/null 2>&1 || die "envycontrol is not installed"

    envycontrol -s "$MODE"
    echo "GPU mode set to $MODE. Reboot required."
    ;;

*)
    die "Unknown command: '$COMMAND'. Must be set-freq|set-profile|set-undervolt|set-gpu"
    ;;
esac
