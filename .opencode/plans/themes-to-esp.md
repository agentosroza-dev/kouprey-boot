# Move Themes from DATA Partition to EFI System Partition (ESP)

## Summary

Move GRUB theme files from the DATA partition (partition 2) to the EFI System
Partition (partition 1) so that theme loading uses `$root` (always the ESP in
GRUB) instead of requiring a `search --file` to discover the DATA partition.

---

## Changes

### 1. `worker.py:_grub_cfg_content()` (line 92-93)

**Before:**
```python
search --no-floppy --set=data_root --file /themes/.marker
set theme=($data_root)/themes/theme.txt
```

**After:**
```python
search --no-floppy --set=data_root --file /ISOS/DUMMY
set theme=($root)/themes/theme.txt
```

- Search target changes from `/themes/.marker` to `/ISOS/DUMMY` (already created
  on DATA partition during flash step 6, line 413-416). Still needed for ISO
  menus and RedoBackoot ISO path.
- Theme path uses `($root)` (ESP) instead of `($data_root)` (DATA). GRUB's
  `$root` is always the ESP — no search needed.

---

### 2. `worker.py:_flash_windows()` — Step 6 (lines 426-435)

Move themes directory and `.marker` creation from DATA to ESP.

**Before:**
```python
themes_dir = os.path.join(data_drive, 'themes')
os.makedirs(themes_dir, exist_ok=True)
marker_path = os.path.join(themes_dir, '.marker')
with open(marker_path, 'w', encoding='utf-8') as f:
    f.write('# Kouprey Boot theme directory marker\n')
if os.path.isfile(marker_path):
    self._log(f'GRUB marker created: {marker_path} ...')
else:
    self._log(f'Warning: could not create GRUB marker ...')
self._log(f'Created {themes_dir}')
```

**After:**
```python
themes_dir = os.path.join(esp_drive, 'themes')
os.makedirs(themes_dir, exist_ok=True)
marker_path = os.path.join(themes_dir, '.marker')
with open(marker_path, 'w', encoding='utf-8') as f:
    f.write('# Kouprey Boot ESP theme directory\n')
self._log(f'ESP themes dir created: {themes_dir}')
```

- `esp_drive` replaces `data_drive`
- Simpler logging — no marker-warning noise (marker is informational now)

---

### 3. `worker.py:_install_grub()` (line 468)

**Before:**
```python
dest_themes = os.path.join(data_drive, 'themes')
```

**After:**
```python
dest_themes = os.path.join(esp_drive, 'themes')
```

Also remove the old-THEMES-marker cleanup (lines 525-528) since it's no longer
on DATA.

**Remove lines 525-528:**
```python
old_marker = os.path.join(data_drive, 'THEMES')
if os.path.isfile(old_marker):
    os.remove(old_marker)
    self._log(f'Removed old THEMES marker (now using themes/.marker)')
```

And update the marker content on line 533:
**Before:** `'# Kouprey Boot GRUB data partition marker\n'`
**After:** `'# Kouprey Boot ESP theme marker\n'`

---

### 4. `worker.py:DeployWorker.run()` (lines 609-636)

**Major changes:**
- `themes_root` target changes from DATA to ESP
- Mount ESP if not already mounted via `_mount_esp()`
- Add try/finally to ensure unmount

**Before:**
```python
themes_root = os.path.join(self._data_mount, 'themes')
old_marker = os.path.join(self._data_mount, 'THEMES')
if os.path.isfile(old_marker):
    os.remove(old_marker)
    self._log('Removed old THEMES marker file')
if os.path.isfile(themes_root):
    os.remove(themes_root)
    self._log('Removed file blocking themes/ directory')
os.makedirs(themes_root, exist_ok=True)

marker_path = os.path.join(themes_root, '.marker')
marker_content = ''
if os.path.isfile(marker_path):
    with open(marker_path, 'r', encoding='utf-8') as f:
        marker_content = f.read()
for item in os.listdir(themes_root):
    if item == '.marker':
        continue
    ...
```

**After:**
```python
# Mount ESP if no mount point was detected
if not self._mount:
    mounted = self._mount_esp()
    if mounted:
        self._mount = mounted + '\\'
        self._log(f'ESP mounted to {self._mount}')
    else:
        raise RuntimeError('Could not mount ESP partition')

themes_root = os.path.join(self._mount, 'themes')
os.makedirs(themes_root, exist_ok=True)

for item in os.listdir(themes_root):
    item_path = os.path.join(themes_root, item)
    if os.path.isdir(item_path):
        shutil.rmtree(item_path)
    else:
        os.remove(item_path)

shutil.copytree(self._options['theme_path'], themes_root, dirs_exist_ok=True)
self._log(f'Theme "{theme_name}" deployed to ESP: {themes_root}')
```

Also add `_unmount_esp()` in `finally` block.

---

### 5. `scanner.py:_detect_windows_drives()` (line 144)

The PowerShell check for DATA partition no longer uses `themes` dir or `THEMES`
marker (since themes are on ESP now).

**Before:**
```powershell
if ((Test-Path ($mp + "ISOS")) -or (Test-Path ($mp + "themes")) -or (Test-Path ($mp + "themes\\.marker")) -or (Test-Path ($mp + "THEMES"))) {
```

**After:**
```powershell
if ((Test-Path ($mp + "ISOS")) -or ($vol.FileSystemLabel -eq "KoupreyData")) {
```

The `themes` and `THEMES` checks are removed. Only `ISOS` dir or volume label
"KoupreyData" identifies the DATA partition.

---

## Files Modified

| File | Lines | Change |
|------|-------|--------|
| `worker.py` | 92-93 | `search` target → `/ISOS/DUMMY`, theme → `($root)/themes/theme.txt` |
| `worker.py` | 426-435 | Step 6 themes dir → ESP |
| `worker.py` | 468 | `dest_themes` → `esp_drive` |
| `worker.py` | 525-528 | Remove old THEMES cleanup |
| `worker.py` | 533 | Marker content text |
| `worker.py` | 609-636 | `DeployWorker.run()` → ESP target, mount/unmount |
| `worker.py` | 647 | Add `_unmount_esp()` in `finally` |
| `scanner.py` | 144 | Remove `themes/THEMES` from DATA detection |
