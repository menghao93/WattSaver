#!/bin/bash
# WattSaver Installer
# Supports: Ubuntu/Debian (apt), Fedora (dnf), Arch (pacman)
set -euo pipefail

INSTALL_DIR="/opt/wattsaver"
POLICY_DIR="/usr/share/polkit-1/actions"
AUTOSTART_DIR="$HOME/.config/autostart"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Helpers ──────────────────────────────────────────────────────────

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
fail() { echo -e "  ${RED}✗${NC} $*"; }
warn() { echo -e "  ${YELLOW}!${NC} $*"; }

# Detect package manager
detect_pkg_manager() {
    if command -v apt >/dev/null 2>&1; then
        echo "apt"
    elif command -v dnf >/dev/null 2>&1; then
        echo "dnf"
    elif command -v pacman >/dev/null 2>&1; then
        echo "pacman"
    else
        echo "unknown"
    fi
}

# ── Start ────────────────────────────────────────────────────────────

echo "=== WattSaver Installer ==="
echo

# Check for root (we need sudo for system dirs)
if [ "$EUID" -eq 0 ]; then
    echo "Please run this script as your normal user (not root)."
    echo "You will be prompted for sudo when needed."
    exit 1
fi

# ── Step 1: Check & install dependencies ─────────────────────────────

echo "[1/5] Checking dependencies..."
echo

MISSING=0
PKG_MANAGER=$(detect_pkg_manager)

# Check python3
if command -v python3 >/dev/null 2>&1; then
    PY_VERSION=$(python3 --version 2>&1)
    ok "Python 3 ($PY_VERSION)"
else
    fail "Python 3 not found"
    MISSING=1
fi

# Check pkexec (polkit)
if command -v pkexec >/dev/null 2>&1; then
    ok "pkexec (polkit)"
else
    fail "pkexec not found"
    MISSING=1
fi

# Check Python GTK bindings with actual imports
check_python_import() {
    python3 -c "$1" 2>/dev/null
}

if check_python_import "import gi"; then
    ok "PyGObject (gi)"
else
    fail "PyGObject (gi) — Python GTK bindings"
    MISSING=1
fi

if check_python_import "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk"; then
    ok "GTK 3.0"
else
    fail "GTK 3.0 — UI toolkit"
    MISSING=1
fi

if check_python_import "import gi; gi.require_version('AyatanaAppIndicator3', '0.1'); from gi.repository import AyatanaAppIndicator3"; then
    ok "AyatanaAppIndicator3 — system tray support"
else
    fail "AyatanaAppIndicator3 — system tray support"
    MISSING=1
fi

echo

# Install missing dependencies if needed
if [ "$MISSING" -eq 1 ]; then
    echo "Some dependencies are missing. Installing..."
    echo

    if [ "$PKG_MANAGER" = "unknown" ]; then
        echo "Could not detect package manager (apt/dnf/pacman)."
        echo "Please install these manually:"
        echo "  - python3 (3.8+)"
        echo "  - PyGObject (python3-gi or python3-gobject)"
        echo "  - GTK 3 GObject Introspection data"
        echo "  - AyatanaAppIndicator3 GObject Introspection data"
        echo "  - polkit (pkexec)"
        echo "Then re-run this installer."
        exit 1
    fi

    case "$PKG_MANAGER" in
        apt)
            echo "Detected package manager: apt (Debian/Ubuntu)"
            echo "Updating package lists..."
            sudo apt update
            echo
            echo "Installing packages..."
            sudo apt install -y \
                python3 \
                python3-gi \
                gir1.2-gtk-3.0 \
                gir1.2-ayatanaappindicator3-0.1 \
                policykit-1 \
                || {
                    echo
                    fail "apt install failed. See errors above."
                    echo
                    echo "Tip: If a package is not found, try:"
                    echo "  sudo apt update && sudo apt install -y gir1.2-ayatanaappindicator3-0.1"
                    echo
                    echo "On some systems the package may be named differently:"
                    echo "  apt search appindicator"
                    exit 1
                }
            ;;
        dnf)
            echo "Detected package manager: dnf (Fedora/RHEL)"
            echo "Installing packages..."
            sudo dnf install -y \
                python3 \
                python3-gobject \
                gtk3 \
                libayatana-appindicator-gtk3 \
                polkit \
                || {
                    echo
                    fail "dnf install failed. See errors above."
                    echo
                    echo "Tip: Search for available packages:"
                    echo "  dnf search appindicator"
                    exit 1
                }
            ;;
        pacman)
            echo "Detected package manager: pacman (Arch)"
            echo "Installing packages..."
            sudo pacman -S --needed --noconfirm \
                python \
                python-gobject \
                gtk3 \
                libayatana-appindicator \
                polkit \
                || {
                    echo
                    fail "pacman install failed. See errors above."
                    echo
                    echo "Tip: The AyatanaAppIndicator package may be in the AUR:"
                    echo "  yay -S libayatana-appindicator"
                    exit 1
                }
            ;;
    esac

    echo
    echo "Verifying dependencies after install..."
    echo

    STILL_MISSING=0

    if command -v python3 >/dev/null 2>&1; then
        ok "Python 3"
    else
        fail "Python 3 — still not found"
        STILL_MISSING=1
    fi

    if command -v pkexec >/dev/null 2>&1; then
        ok "pkexec"
    else
        fail "pkexec — still not found"
        STILL_MISSING=1
    fi

    if check_python_import "import gi"; then
        ok "PyGObject (gi)"
    else
        fail "PyGObject — still not working"
        STILL_MISSING=1
    fi

    if check_python_import "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk"; then
        ok "GTK 3.0"
    else
        fail "GTK 3.0 — still not working"
        STILL_MISSING=1
    fi

    if check_python_import "import gi; gi.require_version('AyatanaAppIndicator3', '0.1'); from gi.repository import AyatanaAppIndicator3"; then
        ok "AyatanaAppIndicator3"
    else
        fail "AyatanaAppIndicator3 — still not working"
        STILL_MISSING=1
    fi

    echo

    if [ "$STILL_MISSING" -eq 1 ]; then
        echo "Some dependencies could not be installed."
        echo "Please install them manually and re-run this installer."
        exit 1
    fi

    ok "All dependencies satisfied!"
else
    ok "All dependencies already installed!"
fi

# Check optional tools
echo
echo "Optional tools:"
if command -v intel-undervolt >/dev/null 2>&1; then
    ok "intel-undervolt — undervolt presets will be available"
else
    warn "intel-undervolt not found — undervolt presets will be hidden"
fi

if command -v envycontrol >/dev/null 2>&1; then
    ok "envycontrol — GPU switching will be available"
else
    warn "envycontrol not found — GPU switching will be hidden"
fi

echo

# ── Check if already installed ───────────────────────────────────────

if [ -f "$INSTALL_DIR/wattsaver.py" ] && [ -f "$POLICY_DIR/com.github.wattsaver.policy" ]; then
    echo "WattSaver is already installed."
    echo "  1) Reinstall / change auth policy"
    echo "  2) Done — just needed the dependencies fixed"
    read -rp "Choose [1-2, default=2]: " REINSTALL_CHOICE
    REINSTALL_CHOICE="${REINSTALL_CHOICE:-2}"
    if [ "$REINSTALL_CHOICE" = "2" ]; then
        echo
        echo "=== Dependencies fixed ==="
        echo "  Run now:  wattsaver"
        exit 0
    fi
    echo
fi

# ── Step 2: Auth policy choice ───────────────────────────────────────

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

# ── Step 3: Install files ────────────────────────────────────────────

echo "[3/5] Installing to $INSTALL_DIR..."
sudo mkdir -p "$INSTALL_DIR"
sudo cp "$SCRIPT_DIR/wattsaver.py" "$INSTALL_DIR/"
sudo cp "$SCRIPT_DIR/wattsaver-helper.sh" "$INSTALL_DIR/"
sudo chmod +x "$INSTALL_DIR/wattsaver.py" "$INSTALL_DIR/wattsaver-helper.sh"
sudo chown -R root:root "$INSTALL_DIR"

# ── Step 4: Install polkit policy ────────────────────────────────────

echo "[4/5] Installing polkit policy..."
TEMP_POLICY=$(mktemp)
sed "s|auth_admin_keep|$AUTH_ACTIVE|g" "$SCRIPT_DIR/com.github.wattsaver.policy" > "$TEMP_POLICY"
sudo cp "$TEMP_POLICY" "$POLICY_DIR/com.github.wattsaver.policy"
rm -f "$TEMP_POLICY"

# Create symlink
sudo ln -sf "$INSTALL_DIR/wattsaver.py" /usr/local/bin/wattsaver

# ── Step 5: Autostart + app launcher ─────────────────────────────────

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
echo
echo "Tip: If the tray icon doesn't appear, enable the AppIndicator extension:"
echo "  gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com"
