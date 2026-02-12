#!/bin/bash
# WattSaver Uninstaller
set -euo pipefail

echo "=== WattSaver Uninstaller ==="
echo

read -rp "Remove WattSaver? [y/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo "Removing installed files..."
sudo rm -rf /opt/wattsaver
sudo rm -f /usr/share/polkit-1/actions/com.github.wattsaver.policy
sudo rm -f /usr/local/bin/wattsaver
rm -f "$HOME/.config/autostart/wattsaver.desktop"

echo
echo "=== WattSaver uninstalled ==="
echo "Source files in ~/WattSaver/ were not removed."
