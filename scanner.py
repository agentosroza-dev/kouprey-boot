import os
import subprocess
import json
import time
import platform
from typing import Optional
from functools import partial


_CACHE_TTL = 3
_cache = {}


def _cached(key: str, fn, ttl: int = _CACHE_TTL):
    now = time.monotonic()
    if key in _cache and (now - _cache[key][0]) < ttl:
        return _cache[key][1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _clear_cache(key: str = None):
    if key:
        _cache.pop(key, None)
    else:
        _cache.clear()


class DriveInfo:
    def __init__(
        self,
        number: int,
        model: str,
        size_bytes: int,
        is_removable: bool,
        is_usb: bool,
        has_kouprey: bool = False,
        mount_point: str = '',
        device_path: str = '',
        data_mount_point: str = '',
    ):
        self.number = number
        self.model = model
        self.size_bytes = size_bytes
        self.is_removable = is_removable
        self.is_usb = is_usb
        self.has_kouprey = has_kouprey
        self.mount_point = mount_point
        self.device_path = device_path
        self.data_mount_point = data_mount_point

    @property
    def size_gb(self) -> str:
        gb = self.size_bytes / (1024 ** 3)
        if gb >= 100:
            return f'{round(gb)} GB'
        return f'{gb:.1f} GB'


class ThemeInfo:
    def __init__(self, name: str, path: str, background: str = ''):
        self.name = name
        self.path = path
        self.background = background
        self._title = ''

    @property
    def has_theme_file(self) -> bool:
        return os.path.isfile(os.path.join(self.path, 'theme.txt'))

    @property
    def title(self) -> str:
        if self._title:
            return self._title
        tf = os.path.join(self.path, 'theme.txt')
        if os.path.isfile(tf):
            with open(tf, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('title-text:'):
                        val = line.split(':', 1)[1].strip().strip('"')
                        if val:
                            self._title = val
                            return val
        return self.name

    @property
    def background_path(self) -> str:
        if self.background:
            return os.path.join(self.path, self.background)
        for name in ('background.png', 'background.jpg', 'splash.png'):
            p = os.path.join(self.path, name)
            if os.path.isfile(p):
                return p
        return ''


def _run_powershell(script: str, timeout: int = 10) -> str:
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ''


def list_usb_drives(force_refresh: bool = False) -> list[DriveInfo]:
    if force_refresh:
        _clear_cache('usb_drives')

    def _fetch():
        system = platform.system()
        if system == 'Windows':
            return _detect_windows_drives()
        elif system == 'Linux':
            return _detect_linux_drives()
        return []

    return _cached('usb_drives', _fetch)


def _detect_windows_drives() -> list[DriveInfo]:
    drives = []
    script = '''
    $drives = Get-Disk | Where-Object { $_.BusType -eq "USB" -or $_.BusType -eq "File Backed Virtual" }
    $result = @()
    foreach ($disk in $drives) {
        $parts = Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue
        $mount = ""
        $dataMount = ""
        $kouprey = $false
        $foundVol = $false
        foreach ($part in $parts) {
            $vol = Get-Volume -Partition $part -ErrorAction SilentlyContinue
            if ($vol.DriveLetter) {
                $foundVol = $true
                $mp = $vol.DriveLetter + ":\\"
                if ((Test-Path ($mp + "ISOS")) -or ($vol.FileSystemLabel -eq "KOUPREYDATA")) {
                    $kouprey = $true
                    $dataMount = $mp
                } elseif (-not $mount) {
                    $mount = $mp
                }
            } elseif ($vol.FileSystemLabel -eq "KOUPREYESP") {
                $kouprey = $true
            }
        }
        $result += [PSCustomObject]@{
            Number = $disk.Number
            Model = $disk.FriendlyName
            Size = $disk.Size
            Removable = $disk.IsRemovable
            BusType = $disk.BusType.ToString()
            MountPoint = $mount
            DataMountPoint = $dataMount
            HasKouprey = $kouprey
        }
    }
    $result | ConvertTo-Json
    '''
    raw = _run_powershell(script, timeout=15)
    if not raw:
        return drives

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return drives

    if not isinstance(data, list):
        data = [data]

    for item in data:
        num = item.get('Number', 0)
        drives.append(DriveInfo(
            number=num,
            model=item.get('Model', 'Unknown'),
            size_bytes=item.get('Size', 0),
            is_removable=item.get('Removable', False),
            is_usb=item.get('BusType') == 'USB',
            has_kouprey=item.get('HasKouprey', False),
            mount_point=item.get('MountPoint', ''),
            data_mount_point=item.get('DataMountPoint', ''),
            device_path=f'\\\\.\\PhysicalDrive{num}',
        ))
    return drives


def _detect_linux_drives() -> list[DriveInfo]:
    drives = []
    try:
        result = subprocess.run(
            ['lsblk', '-J', '-o', 'NAME,SIZE,TYPE,MODEL,MOUNTPOINT,TRAN'],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return drives
        data = json.loads(result.stdout)
    except Exception:
        return drives

    for dev in data.get('blockdevices', []):
        if dev.get('TYPE') != 'disk':
            continue
        if dev.get('TRAN') != 'usb':
            continue

        name = dev['NAME']
        size_str = dev.get('SIZE', '0')
        model = dev.get('MODEL') or f'/dev/{name}'
        mount_points = []

        def _walk_children(parts, mps):
            for p in parts:
                if p.get('mountpoint'):
                    mps.append(p['mountpoint'])
                if p.get('children'):
                    _walk_children(p['children'], mps)

        if dev.get('children'):
            _walk_children(dev['children'], mount_points)

        size_bytes = _parse_lsblk_size(size_str)
        mount = mount_points[0] if mount_points else ''

        has_kouprey = False
        for mp in mount_points:
            if (os.path.isfile(os.path.join(mp, 'EFI', 'BOOT', 'BOOTX64.EFI')) or
                os.path.isfile(os.path.join(mp, 'EFI', 'BOOT', 'grub.cfg')) or
                os.path.isfile(os.path.join(mp, 'grub', 'x86_64-efi', 'normal.mod'))):
                has_kouprey = True
                mount = mp
                break
        if not mount_points:
            has_kouprey = True

        drives.append(DriveInfo(
            number=0,
            model=model,
            size_bytes=size_bytes,
            is_removable=True,
            is_usb=True,
            has_kouprey=has_kouprey,
            mount_point=mount,
            device_path=f'/dev/{name}',
        ))

    return drives


def _parse_lsblk_size(size_str: str) -> int:
    size_str = size_str.strip()
    try:
        if size_str.endswith('G'):
            return int(float(size_str[:-1]) * (1024 ** 3))
        elif size_str.endswith('M'):
            return int(float(size_str[:-1]) * (1024 ** 2))
        elif size_str.endswith('T'):
            return int(float(size_str[:-1]) * (1024 ** 4))
        elif size_str.endswith('K'):
            return int(float(size_str[:-1]) * 1024)
        elif size_str.endswith('B'):
            return int(float(size_str[:-1]))
        else:
            return int(float(size_str))
    except (ValueError, TypeError):
        return 0


def get_platform_name() -> str:
    return platform.system()


def _theme_pack_name(root: str, themes_dir: str) -> str:
    rel = os.path.relpath(root, themes_dir)
    parts = rel.split(os.sep)
    if len(parts) >= 1:
        name = parts[0]
        for suffix in ( '-theme', '-themes'):
            if name.lower().endswith(suffix):
                name = name[:-len(suffix)]
                break
        words = name.replace('_', ' ').replace('-', ' ').split()
        return ' '.join(w.capitalize() for w in words)
    return os.path.basename(root)


def list_available_themes(themes_dir: str) -> list[ThemeInfo]:
    def _fetch():
        themes = []
        if not os.path.isdir(themes_dir):
            return themes
        seen = set()
        for root, dirs, files in os.walk(themes_dir):
            if 'theme.txt' not in files:
                continue
            name = _theme_pack_name(root, themes_dir)
            if name in seen:
                continue
            seen.add(name)

            bg = ''
            for fname in ('background.png', 'background.jpg', 'splash.png'):
                if fname in files:
                    bg = fname
                    break
            themes.append(ThemeInfo(name=name, path=root, background=bg))
        return sorted(themes, key=lambda t: t.name.lower())
    return _cached(f'themes_{themes_dir}', _fetch, ttl=5)



