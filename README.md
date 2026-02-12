# WattSaver

A lightweight system tray power manager for Linux. WattSaver sits in your GNOME top bar and gives you instant control over CPU frequency, undervolt, and GPU switching — no terminal needed.

WattSaver **auto-detects your CPU** and adapts its profiles to your hardware. It works on any Intel CPU supported by `intel_pstate` or `acpi-cpufreq`.

## Features

- **Auto-detected power profiles** — Profiles are generated based on your CPU's actual frequency range (min, base, turbo). No hardcoded values.
- **Custom frequency** — Set any frequency within your CPU's supported range via a simple spin-button dialog.
- **Live monitoring** — Real-time CPU frequency and temperature in the dropdown menu, updated every 2.5 seconds.
- **Undervolt presets** — Quick presets (0 / -50 / -100 / -125 mV) plus a custom dialog for any value. Requires [intel-undervolt](https://github.com/kitsunyan/intel-undervolt). Section is hidden if not installed.
- **GPU switching** — Switch between integrated / hybrid / NVIDIA modes. Requires [envycontrol](https://github.com/bayasdev/envycontrol). Section is hidden if not installed.
- **System tray icon** — Changes based on active profile (power saver / balanced / performance).
- **Autostart** — Launches automatically on login.
- **Secure** — Only a single helper script runs as root (via polkit/pkexec). All inputs are validated.

## Screenshots

<!-- Add screenshots here -->
*Coming soon*

## Compatibility

### Tested CPUs

| CPU | Driver | Status |
|-----|--------|--------|
| Intel Core i5-9300H | intel_pstate | Fully working |

> **Help us expand this list!** Try WattSaver on your hardware and [open an issue](https://github.com/menghao93/WattSaver/issues) with your results.

### Requirements

| Component | Required | Purpose |
|-----------|----------|---------|
| Ubuntu 20.04+ / Debian 11+ / Fedora 36+ | Yes | Base OS |
| GNOME Shell 40+ | Yes | Desktop environment |
| Python 3.8+ | Yes | Main application |
| PyGObject (python3-gi) | Yes | GTK bindings |
| gir1.2-ayatanaappindicator3-0.1 | Yes | System tray icon |
| gnome-shell-extension-appindicator | Yes | Enable tray icons in GNOME |
| [intel-undervolt](https://github.com/kitsunyan/intel-undervolt) | Optional | CPU undervolting (Intel only) |
| [envycontrol](https://github.com/bayasdev/envycontrol) | Optional | NVIDIA GPU switching |

### Supported CPU Drivers

- **intel_pstate** — Intel Core 2nd gen (Sandy Bridge) and newer
- **acpi-cpufreq** — Older Intel CPUs and fallback driver
- **amd-pstate** — AMD Ryzen (frequency control only, no undervolt)

### CPU Generation Notes

| Generation | Freq Control | Undervolt | Notes |
|------------|-------------|-----------|-------|
| Intel 2nd-3rd gen (Sandy/Ivy Bridge) | Yes | Yes | Full support |
| Intel 4th-9th gen (Haswell-Coffee Lake) | Yes | Yes | Best undervolt support |
| Intel 10th-11th gen (Ice/Tiger Lake) | Yes | Maybe | Undervolt often locked by firmware (Plundervolt mitigation). Check BIOS for "Overclocking" or "Voltage Offset". |
| Intel 12th-14th gen (Alder/Raptor Lake) | Yes | Unlikely | Hybrid architecture (P+E cores). Undervolt locked on most laptops. Frequency capping still very useful. |
| Intel Core Ultra (Meteor/Arrow/Lunar Lake) | Yes | No | Undervolt locked by firmware. Frequency profiles and GPU switching still work. Built-in power management is better but capping turbo still saves battery. |
| AMD Ryzen | Yes | No | Use `acpi-cpufreq` or `amd-pstate`. Undervolt section hidden. Consider [ryzenadj](https://github.com/FlyGoat/RyzenAdj) for power limits. |

## Installation

### Quick Install

```bash
git clone https://github.com/menghao93/WattSaver.git
cd WattSaver
bash install.sh
```

The installer will:
1. Install Python dependencies (`gir1.2-ayatanaappindicator3-0.1`)
2. Ask your preferred authentication policy
3. Copy files to `/opt/wattsaver/`
4. Install the polkit policy for privilege escalation
5. Set up autostart on login
6. Create a `wattsaver` command in your PATH

### Run Without Installing

```bash
# Install the one required dependency
sudo apt install gir1.2-ayatanaappindicator3-0.1

# Run directly
python3 wattsaver.py
```

### Optional: Install intel-undervolt

```bash
cd /tmp
git clone https://github.com/kitsunyan/intel-undervolt.git
cd intel-undervolt
./configure && make && sudo make install
sudo modprobe msr
```

### Optional: Install envycontrol

```bash
cd /tmp
git clone https://github.com/bayasdev/envycontrol.git
cd envycontrol
sudo python3 setup.py install
```

## Usage

### Launch

```bash
wattsaver          # after install
python3 wattsaver.py   # from source
```

Or just log out and back in — it starts automatically.

### Menu Layout

When you click the tray icon:

```
Intel(R) Core(TM) i5-9300H CPU @ 2.40GHz
Driver: intel_pstate  |  Cores: 7
─────────────────────────────────
CPU: 2847 MHz  (7 cores)
Temp: 52 °C
─────────────────────────────────
Power Profile
  ○ Power Saver (0.80 GHz)
  ○ Low (1.63 GHz)
  ● Balanced (2.40 GHz)
  ○ High (3.28 GHz)
  ○ Performance (4.10 GHz)
  Custom frequency...
─────────────────────────────────
Undervolt Preset
  ○ None (0 mV)
  ○ Light (-50 mV)
  ● Medium (-100 mV)
  ○ Aggressive (-125 mV)
  Custom undervolt...
─────────────────────────────────
GPU: hybrid  ►
─────────────────────────────────
Quit
```

**Profiles adapt to your CPU.** A machine with a 5.0 GHz turbo will show different frequency values than one with 3.6 GHz.

### How Auto-Detection Works

WattSaver reads your CPU's hardware limits from sysfs:

| Value | Source | Example (i5-9300H) |
|-------|--------|---------------------|
| Min frequency | `cpuinfo_min_freq` | 800 MHz |
| Base frequency | `base_frequency` or CPU model string | 2400 MHz |
| Max frequency | `cpuinfo_max_freq` | 4100 MHz |

Profiles are calculated as:

| Profile | Frequency |
|---------|-----------|
| Power Saver | Hardware minimum |
| Low | 25% between min and max |
| Balanced | Base clock |
| High | 75% between min and max |
| Performance | Hardware maximum (turbo) |

Near-duplicate profiles are automatically removed (e.g., if base clock equals the 25% mark).

## Uninstall

```bash
cd ~/WattSaver
bash uninstall.sh
```

Removes installed files, polkit policy, autostart entry, and PATH symlink. Source files in `~/WattSaver/` are kept.

## Architecture

```
wattsaver.py                    Main app (runs as your user)
    │
    ├── Reads sysfs directly    CPU freq, temp, hardware limits
    │   (no root needed)        /sys/devices/system/cpu/...
    │                           /sys/class/hwmon/...
    │
    ├── pkexec ──► wattsaver-helper.sh    Privileged helper (runs as root)
    │               ├── set-freq          Set CPU max frequency (any value)
    │               ├── set-undervolt     Rewrite config + apply
    │               └── set-gpu           Invoke envycontrol
    │
    └── polkit policy            com.github.wattsaver.policy
                                 Controls authentication behavior
```

### Security Model

- The main Python app **never runs as root**
- Only `wattsaver-helper.sh` executes with elevated privileges via `pkexec`
- **All inputs are validated:**
  - Frequencies are range-checked against hardware sysfs limits
  - Undervolt offsets are clamped to -200..0 mV
  - GPU modes are whitelisted (integrated/hybrid/nvidia)
- The polkit policy controls whether a password prompt appears

## Contributing

Contributions are welcome! Here are areas that need help:

### Wanted

- **Testing on more hardware** — Try it on your CPU and report results
- **AMD undervolt support** — Integration with [ryzenadj](https://github.com/FlyGoat/RyzenAdj) for AMD CPUs
- **Per-core frequency control** — Set different frequencies on P-cores vs E-cores (Intel 12th gen+)
- **Translations** — Menu labels are currently English-only
- **Flatpak / Snap packaging**
- **KDE / XFCE support** — May need a different indicator library
- **Power consumption display** — Read RAPL energy counters

### How to Contribute

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Test on your hardware
5. Submit a pull request

### Reporting Issues

Please include:
```bash
lscpu
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver
cat /etc/os-release
gnome-shell --version
```

## FAQ

**Q: The icon doesn't appear in the top bar?**
A: Enable the AppIndicator GNOME extension:
```bash
gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com
```

**Q: Undervolt / GPU section is missing?**
A: Those sections only appear when the corresponding tool (`intel-undervolt` / `envycontrol`) is installed. Install them and restart WattSaver.

**Q: "Authentication dismissed" errors?**
A: You canceled the password dialog. For passwordless operation, reinstall with `bash install.sh` and choose option 2.

**Q: Does this work on Wayland?**
A: Yes, with the AppIndicator GNOME extension enabled.

**Q: Will undervolting damage my CPU?**
A: No. Undervolting reduces voltage, not increases it. The worst case is a system freeze — reboot and use a less aggressive value. The voltage resets on every reboot unless you enable the `intel-undervolt` systemd service.

**Q: Profiles reset after reboot?**
A: Yes. WattSaver restores your profile on login via autostart. For undervolt persistence independent of WattSaver, run `sudo systemctl enable intel-undervolt`.

## License

[MIT](LICENSE)
