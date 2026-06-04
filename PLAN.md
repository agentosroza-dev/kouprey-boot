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

### 10. Deploy worker silent failure when grub.cfg missing or theme line unfound (worker.py:607-616)
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
