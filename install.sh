#!/bin/bash
# WattSaver Installer
set -euo pipefail

INSTALL_DIR="/opt/wattsaver"
POLICY_DIR="/usr/share/polkit-1/actions"
AUTOSTART_DIR="$HOME/.config/autostart"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== WattSaver Installer ==="
echo

# Check for root (we need sudo for system dirs)
if [ "$EUID" -eq 0 ]; then
    echo "Please run this script as your normal user (not root)."
    echo "You will be prompted for sudo when needed."
    exit 1
fi

# Install dependencies
echo "[1/5] Installing dependencies..."
sudo apt install -y gir1.2-ayatanaappindicator3-0.1 python3-gi gir1.2-gtk-3.0 2>/dev/null || {
    echo "Warning: Could not install some dependencies. They may already be installed."
}
echo

# Polkit auth policy choice
echo "[2/5] Authentication policy for power changes:"
echo "  1) Ask password once per session (recommended)"
echo "  2) Never ask for password"
echo "  3) Ask every time"
read -rp "Choose [1-3, default=1]: " AUTH_CHOICE
AUTH_CHOICE="${AUTH_CHOICE:-1}"

case "$AUTH_CHOICE" in
    2)
        AUTH_ACTIVE="yes"
        echo "  → Password will never be required."
        ;;
    3)
        AUTH_ACTIVE="auth_admin"
        echo "  → Password required every time."
        ;;
    *)
        AUTH_ACTIVE="auth_admin_keep"
        echo "  → Password required once per session."
        ;;
esac
echo

# Install files
echo "[3/5] Installing to $INSTALL_DIR..."
sudo mkdir -p "$INSTALL_DIR"
sudo cp "$SCRIPT_DIR/wattsaver.py" "$INSTALL_DIR/"
sudo cp "$SCRIPT_DIR/wattsaver-helper.sh" "$INSTALL_DIR/"
sudo chmod +x "$INSTALL_DIR/wattsaver.py" "$INSTALL_DIR/wattsaver-helper.sh"
sudo chown -R root:root "$INSTALL_DIR"

# Install polkit policy with chosen auth level
echo "[4/5] Installing polkit policy..."
TEMP_POLICY=$(mktemp)
sed "s|auth_admin_keep|$AUTH_ACTIVE|g" "$SCRIPT_DIR/com.github.wattsaver.policy" > "$TEMP_POLICY"
sudo cp "$TEMP_POLICY" "$POLICY_DIR/com.github.wattsaver.policy"
rm -f "$TEMP_POLICY"

# Create symlink
sudo ln -sf "$INSTALL_DIR/wattsaver.py" /usr/local/bin/wattsaver

# Autostart + app launcher
echo "[5/5] Setting up autostart and app launcher..."
mkdir -p "$AUTOSTART_DIR"
cp "$SCRIPT_DIR/wattsaver.desktop" "$AUTOSTART_DIR/wattsaver.desktop"
mkdir -p "$HOME/.local/share/applications"
cp "$SCRIPT_DIR/wattsaver.desktop" "$HOME/.local/share/applications/wattsaver.desktop"

echo
echo "=== Installation complete ==="
echo "  Run now:    wattsaver"
echo "  Autostart:  enabled (next login)"
echo "  Uninstall:  ~/WattSaver/uninstall.sh"
