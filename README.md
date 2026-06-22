# Kouprey Boot Flash

Create bootable USB drives — flash ISOs directly, install Ventoy, or use Rufus.

## Features

- **ISO to Flash** — write `.iso` files directly to USB using `dd` (raw disk write)
- **Ventoy to USB** — install Ventoy bootloader with automatic theme deployment
- **Rufus** — launch Rufus for advanced flashing options
- **Theme Deployment** — apply GRUB themes to Ventoy drives
- **Dashboard** — detect and display bootable OS info on connected USB drives
- **Dark/Light mode** — toggleable theme support
- **Khmer/English** — bilingual UI

## Prerequisites

- Windows 10/11
- Python 3.12+ (for development)
- PyInstaller (for building)
- Administrator privileges (required for raw disk access)

## Project Structure

```
kouprey-boot/
├── main.py              # Entry point (admin elevation, app launch)
├── ui_main.py           # PyQt6 GUI (Dashboard, Flash, Deploy, Settings)
├── worker.py            # Background workers (dd flash, Ventoy, Rufus)
├── scanner.py           # USB drive detection and OS identification
├── theme.py             # Light/dark theme system and stylesheet builder
├── icons.py             # Lucide SVG icon loader
├── language.py          # i18n manager (Khmer/English)
├── build_portable.ps1   # Build script for single-file EXE
├── assets/
│   ├── dd/dd.exe        # dd for Windows (raw disk writer)
│   ├── rufus/           # Rufus binaries (x64, x86, arm64)
│   ├── ventoy-1.1.12/   # Ventoy bootloader
│   ├── lang/            # Translation files (en.json, km.json)
│   ├── icons/           # App icons
│   └── fonts/           # AgentosUI font family
├── themes/              # GRUB themes for Ventoy deployment
└── lucide/              # Lucide SVG icon pack
```

## Building

### Prerequisites

```powershell
pip install pyinstaller PyQt6
```

### Build Portable EXE

```powershell
.\build_portable.ps1
```

Or with a custom name:

```powershell
.\build_portable.ps1 -Name "MyCustomName"
```

With console window (for debugging):

```powershell
.\build_portable.ps1 -Console
```

### Build Output

The portable EXE is written to `dist\KoupreyBootFlash.exe`. All assets (dd, Rufus, Ventoy, themes, fonts, icons, languages) are bundled into the single executable.

## Development

### Running from source

```powershell
python main.py
```

Requires administrator privileges. The app will auto-elevate if needed.

### Adding assets

Place additional files in `assets/` — the build script bundles the entire directory recursively. No build script changes needed.

### Adding languages

Add or edit JSON files in `assets/lang/`. Keys must match between `en.json` and `km.json`.

## Flash Modes

| Tab | Description |
|-----|-------------|
| ISO to Flash | Writes ISO byte-for-byte to physical disk using `dd.exe`. Cleans the disk before writing. **Destroys all existing data.** |
| Rufus | Launches Rufus for interactive ISO flashing with advanced options |
| Ventoy to USB | Installs Ventoy bootloader. After flash, copies ISOs to the data partition to create a multi-boot USB |

## License

© 2026 Kouprey. Created by AgentOS.
