# Kouprey Boot — Custom GRUB2 Multi-Boot USB

## Overview
Replaced Ventoy2Disk.exe dependency with a native Python flasher that partitions USB drives, installs GRUB2 2.14, and creates a complete multi-boot system with Linux/Windows ISO booting and persistence.

## Architecture

### USB Layout (GPT)
```
Partition 1: ESP (FAT32, 512 MB) — "Kouprey Boot" (GUID: C12A7328-...)
  └── EFI/BOOT/BOOTX64.EFI     (GRUB2 binary)
  └── EFI/BOOT/grub.cfg        (auto-generated)
  └── EFI/BOOT/grub/           (modules, fonts)
  └── EFI/BOOT/wimboot          (Windows ISO boot shim)

Partition 2: DATA (exFAT/NTFS/FAT32) — "Kouprey Data"
  └── ISOs/                    (user .iso files)
  └── themes/                  (GRUB2 themes deployed here)
  └── THEMES                   (marker file for GRUB search)
```

### Key Files

| File | Purpose |
|---|---|
| `assets/grub/` | Bundled GRUB2 2.14 x86_64-efi binaries (BOOTX64.EFI, 85 modules, fonts, wimboot) |
| `worker.py` | `KoupreyFlashWorker` — partitions USB via PowerShell, formats, installs GRUB2, generates grub.cfg. `DeployWorker` — copies themes to DATA partition and updates grub.cfg. |
| `scanner.py` | USB drive detection with GRUB2/Kouprey boot marker detection. Returns `DriveInfo` with `mount_point` (ESP) and `data_mount_point` (DATA partition). |
| `ui_main.py` | PyQt6 GUI. Dashboard shows drives with ✔/○ Kouprey badge. Flash page with FS selector. Deploy page for themes (hides app during operations). Settings page with light/dark and language. |

### Flashing Workflow (`KoupreyFlashWorker._flash_windows`)
```
1. Clear-Disk (PowerShell → diskpart fallback if locked)
2. Initialize-Disk GPT (PowerShell → diskpart fallback if MBR)
3. Create EFI partition (diskpart) → Format FAT32 "KoupreyBoot" (PowerShell)
   → Temp drive letter X/Y/Z assigned → removed after install (mountvol)
4. Create DATA partition (diskpart) → Format with user FS "KoupreyData" (PowerShell)
   → Drive letter T: (preferred) or last available
5. Copy BOOTX64.EFI, modules, fonts, wimboot to ESP
6. Create ISOs/ + themes/ + THEMES marker on DATA partition (10 retries + cmd.exe fallback)
7. Write grub.cfg → ESP/EFI/BOOT/grub.cfg
8. Remove ESP drive letter (hidden from Windows Explorer)
```

### GRUB2 Boot Menu Features
- Auto-scans DATA partition via `search --set=data_root --file /THEMES`
- Theme loaded from `($data_root)/themes/{name}/theme.txt` (default: starfield)
- Linux ISO boot via loopback + extracted vmlinuz/initrd
- Windows ISO boot via wimboot + NTFS
- Reboot, Shutdown, EFI firmware setup entries

### Recent Changes
- **ESP hidden:** No drive letter — mounted via `Add-PartitionAccessPath` temporarily during flash/deploy, then removed. Never visible in Explorer.
- **DATA letter:** `T:` preferred, fallback `Z..D`. Volume label "KoupreyData" (FAT32 11-char limit).
- **Scanner detection:** Detects Kouprey via `ISOS`/`themes`/`THEMES` on DATA partition or "KoupreyData" label (no longer depends on ESP files).
- **DeployWorker:** Mounts ESP temporarily via `Add-PartitionAccessPath` to access `grub.cfg`, copies themes to `T:\themes\{name}\`.
- **Progress bar:** Shows percentage + status text during flash/deploy (no window hiding).
- **Log files:** Auto-saved to `%TEMP%/kouprey-boot/{flash,deploy}_*.log`.
- **Partition ops:** diskpart.exe for partition creation (avoids CIM errors), PowerShell Format-Volume for formatting (avoids VDS "removable media" error).
- **Sidebar color:** Dedicated `NavBg` color (light: `#E8E8E8`, dark: `#2A2A2A`).
- **Admin check:** Early check in `_flash_windows()` with clear error if not elevated.
