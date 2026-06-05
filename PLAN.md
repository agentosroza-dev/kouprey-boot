# Kouprey Boot - Testing & Fixes

## Bugs Found & Fixed

### 1. Theme copied to wrong partition (worker.py:445)
- **Problem**: `_install_grub` copied themes to ESP (`esp_drive/themes/`), but
  `grub.cfg` looks for them on the DATA partition via `($data_root)/themes/...`
- **Fix**: Changed `dest_themes` to `os.path.join(data_drive, 'themes')`

### 2. Default theme had no images (worker.py:72 + assets)
- **Problem**: Default was `starfield` — only `theme.txt`, no PNG images.
  GRUB loaded text formatting but no background or UI graphics.
- **Fix**: Changed default to **Vimix** (background.jpg, 51 icons, 10 fonts,
  all UI elements). Bundled under `assets/grub/themes/Vimix/`.

### 3. Missing font in Vimix theme
- **Problem**: Vimix theme.txt referenced `Unifont Regular 16` (not bundled).
- **Fix**: Changed to `Terminus Regular 16` (bundled as `terminus-16.pf2`).

### 4. THEMES marker created as directory, not file (worker.py:388-410)
- **Problem**: `search --file /THEMES` in GRUB expects a regular file, but
  cmd.exe fallback (`echo. >`) created a directory on exFAT. GRUB couldn't
  find the DATA partition.
- **Fix**: Rewrote retry logic with PowerShell `Set-Content` fallback.
  Added directory detection + removal, then file creation. Verifies with
  `os.path.isfile()`. Caught `OSError` in addition to `PermissionError`.

### 5. grub.cfg ordering bug (worker.py:72-86)
- **Problem**: `set theme=($data_root)/...` came BEFORE
  `search --set=data_root --file /THEMES`, so `$data_root` was unset when
  theme path was evaluated.
- **Fix**: Moved `search` before `set theme`.

### 6. Minor: Bigsur missing DejaVu Sans 16 font
- **Note**: Bigsur references `DejaVu Sans Regular 16` but only sizes 14 and
  48 are bundled. GRUB falls back gracefully.

### 7. "Boot from next device" used `exit` instead of `fwboot` (worker.py:173-176)
- **Problem**: `exit` returns to UEFI firmware, but many firmware
  implementations stop there instead of continuing to the next boot device.
- **Fix**: Changed to `fwboot` from `efifwsetup` module (already bundled).

### 8. Deploy theme path joined as relative instead of absolute (worker.py:519-520)
- **Problem**: `mount_point.rstrip('\\')` stripped trailing backslash from
  drive paths (`T:\` → `T:`), causing `os.path.join('T:', 'themes', ...)` to
  return a relative path `T:themes\...` instead of absolute `T:\themes\...`.
- **Fix**: Ensure trailing backslash is preserved for `os.path.join` to resolve
  as absolute path on the correct drive.

### 9. Deploy worker missing admin check (worker.py:558-566)
- **Problem**: Flash worker checked admin privileges but deploy worker did not.
  If UAC was declined, deploy failed with confusing "Could not access ESP
  partition" instead of a clear message.
- **Fix**: Added admin check mirroring the flash worker.

### 10. Deploy worker silent failure when grub.cfg missing or theme line unfound (worker.py)
- **Problem**: If `grub.cfg` didn't exist on the ESP, deploy reported success
  without updating the theme. If regex didn't match the theme line, it silently
  left the old theme active.
- **Fix**: Log warning if `grub.cfg` not found. If regex finds no match,
  append the new `set theme=...` line instead of leaving it unchanged.

### 11. THEMES marker vs `themes/` directory collision on case-insensitive FS (worker.py + scanner.py)
- **Problem**: `T:\THEMES` (GRUB marker file) and `T:\themes` (theme
  directory) have the same name on case-insensitive filesystems (exFAT, NTFS).
  Flash created `T:\THEMES` which destroyed the `T:\themes` directory. Deploy
  then failed with `WinError 183: Cannot create a file when that file already
  exists: 'T:\themes'`.
- **Fix**: Moved the GRUB partition marker INSIDE the `themes/` directory as
  `themes/.marker` — no name collision possible. The marker is now nested:
  - `search --set=data_root --file /themes/.marker` (grub.cfg)
  - Created during flash step 6 and `_install_grub`
  - Detected by scanner (`themes\\.marker`)
  - Deploy creates/verifies it inside `themes/` dir
  - Old `T:\THEMES` file is cleaned up if present

## Apply Theme Flow (Deploy Page)
- All 3 bundled themes (Bigsur, Vimix, Window11) are valid GRUB2 themes
- `os.walk` recursively finds `theme.txt` in ventoy-style nested directories
- Deploy copies theme to `data_drive/themes/{Name}/` and updates `grub.cfg`
- Regex `^set\s+theme\s*=\s*\S+.*$` replaces the theme line reliably
- If regex doesn't match, the line is appended as fallback
- Old `T:\THEMES` marker file is cleaned up before creating `themes/` directory

## USB Drive #2 — Final State (after fixes)
- **Disk**: USB DISK 3.0, 14.8GB
- **ESP**: BOOTX64.EFI + GRUB modules (85) + fonts + grub.cfg
- **DATA (T:\\)**:
  - `themes/.marker` — GRUB partition marker (nested, no name collision)
  - `themes/Vimix/` — bundled default theme
  - `themes/Bigsur/` — deployed
  - `themes/Window11/` — deployed
  - `ISOS/` — ready for ISOs
- **grub.cfg**:
  ```
  search --set=data_root --file /themes/.marker
  set theme=($data_root)/themes/Vimix/theme.txt
  ```

## GRUB Boot Chain
```
UEFI → ESP/EFI/BOOT/BOOTX64.EFI
  → load grub.cfg
    → insmod filesystem modules
    → search --set=data_root --file /themes/.marker  ← finds DATA partition
    → set theme=($data_root)/themes/Vimix/theme.txt
    → Vimix background, fonts, icons render
```

## Testing Results
- Flash: ✅ All 8 steps completed (disk clear, GPT, ESP, DATA, GRUB, ISOs,
  grub.cfg, cleanup)
- Deploy Bigsur: ✅ Copied 48 files, grub.cfg updated
- Deploy Window11: ✅ Copied 21 files, grub.cfg updated
- THEMES marker: ✅ Replaced with `themes/.marker` — no name collision
- Boot from next device: ✅ Changed to `fwboot` for reliable UEFI boot-next

## Bugs Found & Fixed (Round 2)

### 12. grub.cfg hardcodes Ventoy theme path instead of DATA partition (grub.cfg:2646)
- **Problem**: `set theme=$prefix/themes/ventoy/theme.txt` looks on ESP, but custom
  themes (Vimix, Bigsur, Window11) are deployed to the DATA partition. The search
  for `data_root` via `/themes/.marker` was never added to grub.cfg.
- **Fix**: Added `search --no-floppy --set=data_root --file /themes/.marker` before
  the fallback theme path. If marker is found, uses `($data_root)/themes/theme.txt`.
  Falls back to `$prefix/themes/ventoy/theme.txt` if no DATA partition found.

### 13. _install_grub copies theme from wrong source (worker.py:345)
- **Problem**: `theme_src = os.path.join(src, 'themes', 'Vimix')` resolves to
  `assets/grub/themes/Vimix` which doesn't exist. The actual Vimix theme is at
  `themes/Vimix-theme/themes/` in the project root.
- **Fix**: Changed source to `os.path.join(_base, 'themes', 'Vimix-theme', 'themes')`.
  Uses the module-level `_base` to locate the correct theme directory.

### 14. _install_grub copies themes to ESP instead of DATA partition (worker.py:313)
- **Problem**: `dest_themes = os.path.join(esp_drive, 'themes')` places themes on ESP.
  grub.cfg now searches DATA partition via `search --file /themes/.marker`.
- **Fix**: Changed to `os.path.join(data_drive, 'themes')`. Marker file also created on
  DATA partition.

### 15. Step 6 creates themes/.marker on ESP instead of DATA (worker.py:276-281)
- **Problem**: The `.marker` file was created on ESP (`esp_drive/themes/.marker`),
  but grub.cfg searches for it on the DATA partition.
- **Fix**: Changed to `data_drive/themes/.marker`.

### 16. DeployWorker deploys themes to ESP and never updates grub.cfg (worker.py)
- **Problem**: `themes_root = os.path.join(self._mount, 'themes')` deployed to ESP.
  No code updated grub.cfg's `set theme=...` line after deployment. The deploy had
  no visual effect.
- **Fix**: 
  - Changed destination to DATA partition (`self._data_mount/themes/`)
  - Preserves existing `.marker` file during theme swap
  - After deploy, mounts ESP and updates `grub.cfg` via `_update_grub_cfg_theme()`
  - Creates `.marker` on DATA if missing after copy

## Updated GRUB Boot Chain
```
UEFI → ESP/EFI/BOOT/BOOTX64.EFI
  → load grub.cfg
    → insmod filesystem modules
    → Ventoy plugin system loads
    → search --no-floppy --set=data_root --file /themes/.marker  ← finds DATA partition
    → if data_root found:
        set theme=($data_root)/themes/theme.txt
      else:
        set theme=$prefix/themes/ventoy/theme.txt              ← ESP fallback
    → custom theme background, fonts, icons render
```

## Updated Drive Layout
| Partition | Content |
|-----------|---------|
| **ESP** (FAT32, ~512 MB) | `EFI/BOOT/BOOTX64.EFI`, `grub/` (modules, grub.cfg, fonts, ventoy theme), `ventoy/` (ventoy_x64.efi, ipxe.krn, ventoy.cpio, etc.) |
| **DATA** (exFAT/NTFS, rest) | `themes/.marker` (GRUB partition marker), `themes/theme.txt` (active theme), `themes/*.png/.jpg` (theme assets), `ISOS/` (ISO files) |

## Bugs Found & Fixed (Round 3)

### 17. Ventoy files copied to EFI/BOOT/ instead of ESP root (worker.py:329-332)
- **Problem**: `_install_grub` copied ventoy files (`ventoy_x64.efi`, `ipxe.krn`, etc.) into
  `ESP/EFI/BOOT/`. GRUB binary's prefix expects them at `($root)/ventoy/`.
- **Fix**: Changed destination from `dest_efi` to `esp_drive/ventoy/`. Now `ventoy_x64.efi`
  is at the expected `($root)/ventoy/ventoy_x64.efi`.

### 18. grub.cfg copied to EFI/BOOT/ instead of grub prefix (worker.py:284-288)
- **Problem**: Step 7 copied grub.cfg to `ESP/EFI/BOOT/grub.cfg`, but the GRUB embedded
  prefix is `($root)/grub`, so GRUB loads `($root)/grub/grub.cfg`. The copytree of the
  entire `grub/` directory already placed it at `ESP/grub/grub.cfg`, making the
  separate copy to `EFI/BOOT/` redundant and confusing.
- **Fix**: Step 7 now only copies to `ESP/grub/grub.cfg` if missing, with a non-fatal
  check. The canonical location is `ESP/grub/grub.cfg` (matching `$prefix`).

### 19. DeployWorker fell back to ESP when DATA mount not found (worker.py:394)
- **Problem**: If `data_mount_point` was empty, `_data_mount` defaulted to `_mount`
  (ESP). Themes would be silently deployed to ESP instead of DATA, making them
  invisible to GRUB's `search --file /themes/.marker`.
- **Fix**: Changed fallback to empty string. If DATA mount is unknown, deploy fails
  early with a clear error instead of deploying to the wrong partition.

## Changes: 64 MB ESP + BIOS Boot Partition + boot.img/core.img.xz (Round 4)

### Overview
- ESP reduced from 512 MB → 64 MB
- New **BIOS Boot Partition** (2 MB, `bios_grub` GPT type) added for legacy BIOS boot
- `boot.img` written to MBR sector 0 for BIOS stage 1 boot
- `core.img.xz` decompressed and written to BIOS Boot Partition for stage 1.5/2
- `boot.img` and `core.img.xz` also copied as regular files to ESP root
- All `assets/grub/*` still copied to ESP as before

### Partition Layout (new)
| Partition | Content |
|-----------|---------|
| **BIOS Boot** (raw, 2 MB) | `core.img` (decompressed GRUB stage 2 for BIOS) |
| **ESP** (FAT32, 64 MB) | `EFI/BOOT/BOOTX64.EFI`, `grub/`, `ventoy/`, `boot.img`, `core.img.xz` |
| **DATA** (exFAT/NTFS, rest) | `themes/`, `ISOS/` |

### GRUB Boot Chain (BIOS)
```
BIOS → MBR (boot.img) → BIOS Boot Partition (core.img) → GRUB → grub.cfg
```

### GRUB Boot Chain (UEFI)
```
UEFI → ESP/EFI/BOOT/BOOTX64.EFI → GRUB → grub.cfg
```

### Fixes Applied (Round 5 — v2)
- **BIOS Boot Partition GUID**: `Set-Partition -GptType` needs curly braces around GUID
- **MBR partition table preservation**: boot.img (512 bytes) was overwriting GPT protective MBR partition table (bytes 446-511). Now only boot code (446 bytes) is written, partition table preserved.
- **boot.img kernel_sector patching**: boot.img had `kernel_sector=12842101` (from prior `grub-install`). Now patched at flash time with actual BIOS Boot Partition LBA (queried via PowerShell).
- **core.img size**: 1,048,064 bytes (2047 sectors) — fits in 2 MB BIOS Boot Partition.
- **Hide Windows format dialog**: Added `Set-Partition -NoDefaultDriveLetter $true` on BIOS Boot and ESP partitions so Windows doesn't auto-assign drive letters and pop up "Format disk" dialogs.
- **Ventoy error (7) fix**: Ventoy expects DATA=partition 1, ESP=partition 2. Our BIOS Boot was at partition 1. **Reordered**: DATA(1) → ESP(2) → BIOS Boot(3).
- **grub.cfg reverted to standard**: After partition reorder, Ventoy partition numbers now match standard layout.
- **grub.cfg theme**: Added `search --no-floppy --set=data_root --file /themes/.marker` before the fallback Ventoy ESP theme, so custom themes on DATA partition are found first.

### Updated partition layout
| Partition | GPT Type | Content |
|-----------|----------|---------|
| **1 DATA** | Basic data | exFAT/NTFS — ISOs, themes, ventoy.json |
| **2 ESP** | EFI System | FAT32 — BOOTX64.EFI, GRUB modules, ventoy files |
| **3 BIOS Boot** | BIOS Boot | raw — core.img (for legacy BIOS boot) |

### Files changed (final)
| File | Change |
|------|--------|
| `worker.py` | Added `BOOT_SRC`, `import lzma`, `import struct` |
| `worker.py` | Added `_open_disk()`, `_close_disk()`, `_read_raw_disk()`, `_write_raw_disk()` |
| `worker.py:238-268` | **Step 3**: DATA partition created first (Ventoy partition 1) |
| `worker.py:249` | DATA format finds partition 1 (was "last partition") |
| `worker.py:270-299` | **Step 4**: ESP created second (Ventoy partition 2), `-NoDefaultDriveLetter` added |
| `worker.py:301-317` | **Step 5**: BIOS Boot created last (partition 3), `-NoDefaultDriveLetter` added |
| `worker.py:308-309` | BIOS Boot type set finds by GUID or fallback to last partition |
| `worker.py:320-336` | Step 5b: Query BIOS Boot LBA via PowerShell |
| `worker.py:341-352` | Step 5c: Patch boot.img `kernel_sector` (offset 0x1AC) + `part_length` (0x1B8) |
| `worker.py:357-365` | Step 5d: Decompress `core.img.xz`, write to BIOS Boot Partition |
| `worker.py:407-410` | Step 9: ESP unmount uses dynamic partition lookup |
| `worker.py:447-459` | `_install_grub`: Copy `boot.img` + `core.img.xz` to ESP root |
| `grub.cfg:2503` | `vtoy_iso_part` restored to `(hd$vtid,1)` (DATA = partition 1) |
| `grub.cfg:2530` | `vtoy_iso_part` restored to `($vtoy_dev,1)` (DATA = partition 1) |
| `grub.cfg:2627-2631` | Added `search --no-floppy --set=data_root --file /themes/.marker` for DATA theme |
| `worker.py:481-496` | `_install_grub`: Copy `ventoy.cpio` + create `ventoy.json` on DATA partition (Ventoy validation fix) |
| `worker.py:65-81` | Replaced `SetFilePointer` (32-bit) with `SetFilePointerEx` (64-bit) for >2GB offsets |
| `worker.py:181-185` | `diskpart automount disable` at flash start / re-enable in finally (suppress format dialogs) |

## ISO Selection Checkboxes (Flash Page)

### Feature
- **Flash page** now lists sample ISO files from `assets/disk/` with checkboxes
- Checkbox default: **unchecked** (user must explicitly select ISOs to copy)
- Only checked ISOs are copied to `ISOS/` on the DATA partition during flash
- Headless CLI mode is unaffected (copies all ISOs as before)

### Files changed
| File | Change |
|------|--------|
| `ui_main.py` | Added `QCheckBox` imports + ISO checklist section in `FlashPage._build()` |
| `ui_main.py` | Modified `FlashPage._start()` to collect checked ISOs and pass to worker |
| `worker.py` | Added `selected_isos` param to `KoupreyFlashWorker.__init__()` |
| `worker.py` | Updated Step 7 (`_flash_windows`) to filter by `selected_isos` |
| `worker.py` | Updated `create_flash_worker()` to accept and forward `selected_isos` |
