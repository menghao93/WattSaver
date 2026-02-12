#!/usr/bin/env python3
"""WattSaver — System tray power manager for Linux.

Auto-detects CPU capabilities and adapts to any Intel CPU with intel_pstate
or acpi-cpufreq driver. Provides power profiles, undervolt presets, GPU
switching, and live CPU monitoring from the GNOME top bar.
"""

import glob
import os
import re
import subprocess
import signal
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, GLib, AyatanaAppIndicator3

# ── Paths ─────────────────────────────────────────────────────────────

HELPER_PATHS = [
    "/opt/wattsaver/wattsaver-helper.sh",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "wattsaver-helper.sh"),
]

SYSFS_CPU_BASE = "/sys/devices/system/cpu"
SYSFS_HWMON = "/sys/class/hwmon"

GPU_MODES = ["integrated", "hybrid", "nvidia"]
REFRESH_INTERVAL_MS = 2500

UNDERVOLT_PRESETS = [
    {"key": "none",       "label": "None (0 mV)",          "offset": 0},
    {"key": "light",      "label": "Light (-50 mV)",        "offset": -50},
    {"key": "medium",     "label": "Medium (-100 mV)",      "offset": -100},
    {"key": "aggressive", "label": "Aggressive (-125 mV)",  "offset": -125},
]


# ── Utility functions ─────────────────────────────────────────────────

def read_sysfs(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, IOError):
        return None


def read_sysfs_int(path):
    val = read_sysfs(path)
    if val and val.lstrip("-").isdigit():
        return int(val)
    return None


def has_command(name):
    try:
        return subprocess.run(
            ["which", name], capture_output=True
        ).returncode == 0
    except Exception:
        return False


def find_helper():
    for path in HELPER_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def run_helper(command, *args):
    helper = find_helper()
    if not helper:
        return False, "Helper script not found"
    cmd = ["pkexec", helper, command] + [str(a) for a in args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return True, result.stdout.strip()
        if result.returncode == 126:
            return False, "Authentication dismissed"
        return False, result.stderr.strip() or result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Operation timed out"
    except Exception as e:
        return False, str(e)


# ── CPU detection ─────────────────────────────────────────────────────

class CPUInfo:
    """Auto-detect CPU capabilities from sysfs."""

    def __init__(self):
        self.model = self._read_model()
        self.driver = read_sysfs(
            f"{SYSFS_CPU_BASE}/cpu0/cpufreq/scaling_driver"
        ) or "unknown"

        # Hardware frequency limits (kHz)
        self.hw_min_khz = read_sysfs_int(
            f"{SYSFS_CPU_BASE}/cpu0/cpufreq/cpuinfo_min_freq"
        ) or 800000
        self.hw_max_khz = read_sysfs_int(
            f"{SYSFS_CPU_BASE}/cpu0/cpufreq/cpuinfo_max_freq"
        ) or 4000000

        # Base frequency — try to read from sysfs, fall back to heuristic
        self.base_khz = self._detect_base_freq()

        # Count online CPUs
        self.online_cpus = self._count_online_cpus()

        # Available governors
        self.governors = self._read_governors()

    def _read_model(self):
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except (OSError, IOError):
            pass
        return "Unknown CPU"

    def _detect_base_freq(self):
        # Method 1: base_frequency sysfs (available on some kernels)
        val = read_sysfs_int(f"{SYSFS_CPU_BASE}/cpu0/cpufreq/base_frequency")
        if val:
            return val

        # Method 2: parse from CPU model string (e.g. "@ 2.40GHz")
        match = re.search(r"@\s*([\d.]+)\s*GHz", self.model)
        if match:
            return int(float(match.group(1)) * 1_000_000)

        # Method 3: midpoint between min and max
        return (self.hw_min_khz + self.hw_max_khz) // 2

    def _count_online_cpus(self):
        count = 0
        try:
            for entry in os.listdir(SYSFS_CPU_BASE):
                if re.match(r"cpu\d+$", entry):
                    cpufreq = f"{SYSFS_CPU_BASE}/{entry}/cpufreq"
                    if os.path.isdir(cpufreq):
                        count += 1
        except OSError:
            count = os.cpu_count() or 4
        return count

    def _read_governors(self):
        val = read_sysfs(
            f"{SYSFS_CPU_BASE}/cpu0/cpufreq/scaling_available_governors"
        )
        if val:
            return val.split()
        return ["powersave", "performance"]

    def build_profiles(self):
        """Generate power profiles adapted to this CPU's actual capabilities.

        Returns a list of profile dicts sorted by frequency (low to high):
          [{"key": ..., "label": ..., "freq_khz": ..., "icon": ...}, ...]

        Profiles:
          - Power Saver: hardware minimum frequency
          - Low:         25% of range between min and max
          - Balanced:    base frequency (or 50% if base is unknown)
          - High:        75% of range between min and max
          - Performance: hardware maximum frequency (turbo)
        """
        lo = self.hw_min_khz
        hi = self.hw_max_khz
        base = self.base_khz
        span = hi - lo

        profiles = [
            {
                "key": "powersaver",
                "label": f"Power Saver ({self._fmt_ghz(lo)})",
                "freq_khz": lo,
                "icon": "power-profile-power-saver-symbolic",
            },
            {
                "key": "low",
                "label": f"Low ({self._fmt_ghz(lo + span // 4)})",
                "freq_khz": lo + span // 4,
                "icon": "power-profile-power-saver-symbolic",
            },
            {
                "key": "balanced",
                "label": f"Balanced ({self._fmt_ghz(base)})",
                "freq_khz": base,
                "icon": "power-profile-balanced-symbolic",
            },
            {
                "key": "high",
                "label": f"High ({self._fmt_ghz(lo + 3 * span // 4)})",
                "freq_khz": lo + 3 * span // 4,
                "icon": "power-profile-performance-symbolic",
            },
            {
                "key": "performance",
                "label": f"Performance ({self._fmt_ghz(hi)})",
                "freq_khz": hi,
                "icon": "power-profile-performance-symbolic",
            },
        ]

        # Deduplicate profiles that ended up at the same frequency
        seen = set()
        unique = []
        for p in profiles:
            # Round to nearest 100 MHz to avoid near-duplicates
            bucket = round(p["freq_khz"] / 100000)
            if bucket not in seen:
                seen.add(bucket)
                unique.append(p)
        return unique

    @staticmethod
    def _fmt_ghz(khz):
        ghz = khz / 1_000_000
        if ghz == int(ghz):
            return f"{ghz:.1f} GHz"
        return f"{ghz:.2f} GHz"


# ── Main application ──────────────────────────────────────────────────

class WattSaver:
    def __init__(self):
        # Detect hardware
        self.cpu = CPUInfo()
        self.profiles = self.cpu.build_profiles()
        self.has_envycontrol = has_command("envycontrol")
        self.has_undervolt = has_command("intel-undervolt")

        # Detect current state
        self.current_profile_key = self._detect_profile()
        self.current_undervolt_key = self._detect_undervolt()

        self.profile_items = {}
        self.undervolt_items = {}

        # Create indicator
        current = self._get_profile(self.current_profile_key)
        icon = current["icon"] if current else "power-profile-balanced-symbolic"
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "wattsaver", icon, AyatanaAppIndicator3.IndicatorCategory.HARDWARE
        )
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("WattSaver")

        # Build menu
        self.menu = Gtk.Menu()
        self._build_menu()
        self.indicator.set_menu(self.menu)

        # Start sensor polling
        self._update_sensors()
        GLib.timeout_add(REFRESH_INTERVAL_MS, self._update_sensors)

    def _get_profile(self, key):
        for p in self.profiles:
            if p["key"] == key:
                return p
        return None

    # ── Menu construction ─────────────────────────────────────────────

    def _build_menu(self):
        # CPU info header
        cpu_label = Gtk.MenuItem(label=self.cpu.model)
        cpu_label.set_sensitive(False)
        self.menu.append(cpu_label)

        driver_label = Gtk.MenuItem(
            label=f"Driver: {self.cpu.driver}  |  Cores: {self.cpu.online_cpus}"
        )
        driver_label.set_sensitive(False)
        self.menu.append(driver_label)

        self.menu.append(Gtk.SeparatorMenuItem())

        # Live monitoring
        self.freq_item = Gtk.MenuItem(label="CPU: ... MHz")
        self.freq_item.set_sensitive(False)
        self.menu.append(self.freq_item)

        self.temp_item = Gtk.MenuItem(label="Temp: ... °C")
        self.temp_item.set_sensitive(False)
        self.menu.append(self.temp_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        # Power profiles (auto-detected)
        header = Gtk.MenuItem(label="Power Profile")
        header.set_sensitive(False)
        self.menu.append(header)

        group_item = None
        for profile in self.profiles:
            key = profile["key"]
            item = Gtk.RadioMenuItem.new_with_label_from_widget(
                group_item, profile["label"]
            )
            if group_item is None:
                group_item = item
            if key == self.current_profile_key:
                item.set_active(True)
            item.connect("toggled", self._on_profile_toggled, key)
            self.profile_items[key] = item
            self.menu.append(item)

        # Custom frequency option
        custom_item = Gtk.MenuItem(label="Custom frequency...")
        custom_item.connect("activate", self._on_custom_freq)
        self.menu.append(custom_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        # Undervolt presets
        if self.has_undervolt:
            header = Gtk.MenuItem(label="Undervolt Preset")
            header.set_sensitive(False)
            self.menu.append(header)

            group_item = None
            for preset in UNDERVOLT_PRESETS:
                key = preset["key"]
                item = Gtk.RadioMenuItem.new_with_label_from_widget(
                    group_item, preset["label"]
                )
                if group_item is None:
                    group_item = item
                if key == self.current_undervolt_key:
                    item.set_active(True)
                item.connect("toggled", self._on_undervolt_toggled, key)
                self.undervolt_items[key] = item
                self.menu.append(item)

            # Custom undervolt option
            custom_uv = Gtk.MenuItem(label="Custom undervolt...")
            custom_uv.connect("activate", self._on_custom_undervolt)
            self.menu.append(custom_uv)

            self.menu.append(Gtk.SeparatorMenuItem())

        # GPU mode
        if self.has_envycontrol:
            gpu_mode = self._detect_gpu_mode()
            self.gpu_item = Gtk.MenuItem(label=f"GPU: {gpu_mode}")
            self.gpu_item.set_submenu(self._build_gpu_submenu())
            self.menu.append(self.gpu_item)
            self.menu.append(Gtk.SeparatorMenuItem())

        # Quit
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self._on_quit)
        self.menu.append(quit_item)

        self.menu.show_all()

    def _build_gpu_submenu(self):
        submenu = Gtk.Menu()
        for mode in GPU_MODES:
            item = Gtk.MenuItem(label=mode.capitalize())
            item.connect("activate", self._on_gpu_switch, mode)
            submenu.append(item)
        submenu.show_all()
        return submenu

    # ── Sensor polling ────────────────────────────────────────────────

    def _update_sensors(self):
        # Average frequency across all online cores
        freqs = []
        try:
            for entry in sorted(os.listdir(SYSFS_CPU_BASE)):
                if not re.match(r"cpu\d+$", entry):
                    continue
                val = read_sysfs_int(
                    f"{SYSFS_CPU_BASE}/{entry}/cpufreq/scaling_cur_freq"
                )
                if val is not None:
                    freqs.append(val)
        except OSError:
            pass

        if freqs:
            avg_mhz = sum(freqs) / len(freqs) / 1000
            self.freq_item.set_label(f"CPU: {avg_mhz:.0f} MHz  ({len(freqs)} cores)")
        else:
            self.freq_item.set_label("CPU: N/A")

        # Temperature
        temp = self._read_cpu_temp()
        if temp is not None:
            self.temp_item.set_label(f"Temp: {temp:.0f} °C")
        else:
            self.temp_item.set_label("Temp: N/A")

        return True

    def _read_cpu_temp(self):
        # Try coretemp (Intel), then k10temp (AMD), then thermal_zone fallback
        try:
            for hwmon in os.listdir(SYSFS_HWMON):
                name = read_sysfs(os.path.join(SYSFS_HWMON, hwmon, "name"))
                if name in ("coretemp", "k10temp"):
                    val = read_sysfs_int(
                        os.path.join(SYSFS_HWMON, hwmon, "temp1_input")
                    )
                    if val is not None:
                        return val / 1000
        except OSError:
            pass

        # Fallback: thermal_zone0
        val = read_sysfs_int("/sys/class/thermal/thermal_zone0/temp")
        if val is not None:
            return val / 1000
        return None

    # ── State detection ───────────────────────────────────────────────

    def _detect_profile(self):
        """Match current scaling_max_freq to the closest profile."""
        current = read_sysfs_int(
            f"{SYSFS_CPU_BASE}/cpu0/cpufreq/scaling_max_freq"
        )
        if current is None:
            return "balanced"

        best_key = self.profiles[0]["key"]
        best_diff = abs(current - self.profiles[0]["freq_khz"])
        for p in self.profiles[1:]:
            diff = abs(current - p["freq_khz"])
            if diff < best_diff:
                best_diff = diff
                best_key = p["key"]
        return best_key

    def _detect_undervolt(self):
        try:
            with open("/etc/intel-undervolt.conf") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("undervolt") and "'CPU'" in line and "Cache" not in line:
                        parts = line.split()
                        offset = int(float(parts[-1]))
                        if offset == 0:
                            return "none"
                        elif offset >= -50:
                            return "light"
                        elif offset >= -100:
                            return "medium"
                        else:
                            return "aggressive"
        except (OSError, IOError, ValueError, IndexError):
            pass
        return "none"

    def _detect_gpu_mode(self):
        try:
            result = subprocess.run(
                ["envycontrol", "--query"],
                capture_output=True, text=True, timeout=5,
            )
            output = result.stdout.strip().lower()
            for mode in GPU_MODES:
                if mode in output:
                    return mode
        except Exception:
            pass
        return "unknown"

    # ── Callbacks ─────────────────────────────────────────────────────

    def _on_profile_toggled(self, item, profile_key):
        if not item.get_active():
            return
        if profile_key == self.current_profile_key:
            return

        profile = self._get_profile(profile_key)
        if not profile:
            return

        ok, msg = run_helper("set-freq", str(profile["freq_khz"]))
        if ok:
            self.current_profile_key = profile_key
            self.indicator.set_icon_full(profile["icon"], profile["label"])
        else:
            self._show_error("Profile Switch Failed", msg)
            self.profile_items[self.current_profile_key].set_active(True)

    def _on_custom_freq(self, _item):
        """Show a dialog for the user to enter a custom frequency."""
        dialog = Gtk.Dialog(
            title="Custom CPU Frequency",
            buttons=(
                Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                Gtk.STOCK_OK, Gtk.ResponseType.OK,
            ),
        )
        dialog.set_default_size(350, -1)

        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_margin_start(15)
        box.set_margin_end(15)
        box.set_margin_top(10)

        min_ghz = self.cpu.hw_min_khz / 1_000_000
        max_ghz = self.cpu.hw_max_khz / 1_000_000

        label = Gtk.Label(
            label=f"Enter max CPU frequency in GHz\n"
                  f"Range: {min_ghz:.2f} - {max_ghz:.2f} GHz"
        )
        label.set_line_wrap(True)
        box.add(label)

        adj = Gtk.Adjustment(
            value=max_ghz,
            lower=min_ghz,
            upper=max_ghz,
            step_increment=0.1,
            page_increment=0.5,
        )
        spin = Gtk.SpinButton(adjustment=adj, digits=2)
        box.add(spin)

        box.show_all()
        response = dialog.run()
        freq_ghz = spin.get_value()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return

        freq_khz = int(freq_ghz * 1_000_000)
        ok, msg = run_helper("set-freq", str(freq_khz))
        if ok:
            self.current_profile_key = "__custom__"
            self.indicator.set_icon_full(
                "power-profile-balanced-symbolic",
                f"Custom ({freq_ghz:.2f} GHz)",
            )
            # Deselect all radio items
            for item in self.profile_items.values():
                item.handler_block_by_func(self._on_profile_toggled)
                item.set_active(False)
                item.handler_unblock_by_func(self._on_profile_toggled)
        else:
            self._show_error("Failed to Set Frequency", msg)

    def _on_undervolt_toggled(self, item, preset_key):
        if not item.get_active():
            return
        if preset_key == self.current_undervolt_key:
            return

        for preset in UNDERVOLT_PRESETS:
            if preset["key"] == preset_key:
                offset = preset["offset"]
                break
        else:
            return

        ok, msg = run_helper("set-undervolt", str(offset))
        if ok:
            self.current_undervolt_key = preset_key
        else:
            self._show_error("Undervolt Failed", msg)
            self.undervolt_items[self.current_undervolt_key].set_active(True)

    def _on_custom_undervolt(self, _item):
        """Show a dialog for the user to enter a custom undervolt offset."""
        dialog = Gtk.Dialog(
            title="Custom Undervolt",
            buttons=(
                Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                Gtk.STOCK_OK, Gtk.ResponseType.OK,
            ),
        )
        dialog.set_default_size(350, -1)

        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_margin_start(15)
        box.set_margin_end(15)
        box.set_margin_top(10)

        label = Gtk.Label(
            label="Enter undervolt offset in mV (0 to -200)\n"
                  "WARNING: Aggressive values may cause crashes."
        )
        label.set_line_wrap(True)
        box.add(label)

        adj = Gtk.Adjustment(
            value=0, lower=-200, upper=0,
            step_increment=5, page_increment=25,
        )
        spin = Gtk.SpinButton(adjustment=adj, digits=0)
        box.add(spin)

        box.show_all()
        response = dialog.run()
        offset = int(spin.get_value())
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return

        ok, msg = run_helper("set-undervolt", str(offset))
        if ok:
            self.current_undervolt_key = "__custom__"
            for item in self.undervolt_items.values():
                item.handler_block_by_func(self._on_undervolt_toggled)
                item.set_active(False)
                item.handler_unblock_by_func(self._on_undervolt_toggled)
        else:
            self._show_error("Undervolt Failed", msg)

    def _on_gpu_switch(self, _item, mode):
        current = self._detect_gpu_mode()
        if mode == current:
            return

        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"Switch GPU to {mode}?",
        )
        dialog.format_secondary_text(
            "A reboot is required for the change to take effect."
        )
        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return

        ok, msg = run_helper("set-gpu", mode)
        if ok:
            self.gpu_item.set_label(f"GPU: {mode}")
            self._show_info("GPU Mode Changed", f"Switched to {mode}. Please reboot.")
        else:
            self._show_error("GPU Switch Failed", msg)

    def _on_quit(self, _item):
        Gtk.main_quit()

    # ── Dialogs ───────────────────────────────────────────────────────

    def _show_error(self, title, message):
        d = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK, text=title,
        )
        d.format_secondary_text(message)
        d.run()
        d.destroy()

    def _show_info(self, title, message):
        d = Gtk.MessageDialog(
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK, text=title,
        )
        d.format_secondary_text(message)
        d.run()
        d.destroy()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    WattSaver()
    Gtk.main()


if __name__ == "__main__":
    main()
