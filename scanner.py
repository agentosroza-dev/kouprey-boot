import os
import subprocess
import json
import time
import platform
from typing import Optional


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
        has_ventoy: bool = False,
        mount_point: str = '',
        device_path: str = '',
        data_mount_point: str = '',
        boot_type: str = '',
        os_name: str = '',
    ):
        self.number = number
        self.model = model
        self.size_bytes = size_bytes
        self.is_removable = is_removable
        self.is_usb = is_usb
        self.has_ventoy = has_ventoy
        self.mount_point = mount_point
        self.device_path = device_path
        self.data_mount_point = data_mount_point
        self.boot_type = boot_type
        self.os_name = os_name

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
        kwargs = {
            'capture_output': True, 'text': True, 'timeout': timeout,
        }
        if platform.system() == 'Windows':
            try:
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            except AttributeError:
                pass
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script], **kwargs
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
            drives = _detect_windows_drives()
        elif system == 'Linux':
            drives = _detect_linux_drives()
        else:
            return []
        for d in drives:
            bt, name = _detect_boot_on_drive(d)
            d.boot_type = bt
            d.os_name = name
        return drives

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
        $hasVentoy = $false
        foreach ($part in $parts) {
            $vol = Get-Volume -Partition $part -ErrorAction SilentlyContinue
            if ($vol.DriveLetter) {
                $mp = $vol.DriveLetter + ":\\"
                if ($vol.FileSystemLabel -eq "VTOYEFI") {
                    $hasVentoy = $true
                    $mount = $mp
                } elseif (Test-Path ($mp + "ventoy\\ventoy.json")) {
                    $hasVentoy = $true
                    $dataMount = $mp
                } elseif (-not $mount) {
                    $mount = $mp
                }
            } else {
                if ($vol.FileSystemLabel -eq "VTOYEFI") {
                    $hasVentoy = $true
                }
            }
        }
        if ($hasVentoy -and -not $dataMount) {
            foreach ($part in $parts) {
                $vol = Get-Volume -Partition $part -ErrorAction SilentlyContinue
                if ($vol.DriveLetter -and $vol.FileSystemLabel -ne "VTOYEFI") {
                    $dataMount = $vol.DriveLetter + ":\\"
                    break
                }
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
            HasVentoy = $hasVentoy
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
            has_ventoy=item.get('HasVentoy', False),
            mount_point=item.get('MountPoint', ''),
            data_mount_point=item.get('DataMountPoint', ''),
            device_path=f'\\\\.\\PhysicalDrive{num}',
        ))
    return drives


def _detect_linux_drives() -> list[DriveInfo]:
    drives = []
    try:
        result = subprocess.run(
            ['lsblk', '-J', '-o', 'NAME,SIZE,TYPE,MODEL,MOUNTPOINT,TRAN,LABEL'],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return drives
        data = json.loads(result.stdout)
    except Exception:
        return drives

    usb_index = 0
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

        has_ventoy = False
        data_mount = ''
        for mp in mount_points:
            if os.path.isfile(os.path.join(mp, 'ventoy', 'ventoy.json')):
                has_ventoy = True
                data_mount = mp
                mount = mp
                break

        drives.append(DriveInfo(
            number=usb_index,
            model=model,
            size_bytes=size_bytes,
            is_removable=True,
            is_usb=True,
            has_ventoy=has_ventoy,
            mount_point=mount,
            device_path=f'/dev/{name}',
            data_mount_point=data_mount,
        ))
        usb_index += 1

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


def _detect_boot_on_path(mount: str) -> tuple[str, str]:
    if not mount or not os.path.isdir(mount):
        return ('', '')
    try:
        # --- Windows checks (highest priority) ---
        if os.path.isfile(os.path.join(mount, 'bootmgr')) or os.path.isfile(os.path.join(mount, 'bootmgr.efi')):
            if os.path.isfile(os.path.join(mount, 'sources', 'install.wim')) or os.path.isfile(os.path.join(mount, 'sources', 'install.esd')):
                return ('windows', 'Windows Setup')
            return ('windows', 'Windows')

        if os.path.isfile(os.path.join(mount, 'sources', 'boot.wim')):
            return ('winpe', 'Windows PE')

        efi_path = os.path.join(mount, 'EFI', 'Microsoft', 'Boot', 'bootmgfw.efi')
        if os.path.isfile(efi_path):
            if os.path.isfile(os.path.join(mount, 'sources', 'boot.wim')):
                return ('winpe', 'Windows PE')
            return ('windows', 'Windows')

        # --- Linux distro checks ---

        # Ubuntu / derivatives via .disk/info
        disk_info = os.path.join(mount, '.disk', 'info')
        if os.path.isfile(disk_info):
            with open(disk_info, 'r', errors='ignore') as f:
                content = f.read().lower()
            if 'ubuntu' in content:
                return ('ubuntu', 'Ubuntu')
            if 'mint' in content:
                return ('mint', 'Linux Mint')
            if 'debian' in content:
                return ('debian', 'Debian')

        # Ubuntu live: casper/
        if os.path.isdir(os.path.join(mount, 'casper')):
            if os.path.isfile(os.path.join(mount, 'casper', 'vmlinuz')) or os.path.isfile(os.path.join(mount, 'casper', 'vmlinuz.efi')):
                return ('ubuntu', 'Ubuntu')

        # Fedora live: LiveOS/
        if os.path.isdir(os.path.join(mount, 'LiveOS')):
            return ('fedora', 'Fedora')

        # Generic live: live/
        if os.path.isdir(os.path.join(mount, 'live')):
            if os.path.isfile(os.path.join(mount, 'live', 'vmlinuz')) or os.path.isfile(os.path.join(mount, 'live', 'vmlinuz.efi')):
                return ('linux', 'Linux')

        # Grub config parsing
        grub_cfg = os.path.join(mount, 'boot', 'grub', 'grub.cfg')
        if os.path.isfile(grub_cfg):
            with open(grub_cfg, 'r', errors='ignore') as f:
                content = f.read().lower()
            if 'ubuntu' in content:
                return ('ubuntu', 'Ubuntu')
            if 'mint' in content or 'linuxmint' in content:
                return ('mint', 'Linux Mint')
            if 'debian' in content:
                return ('debian', 'Debian')
            if 'fedora' in content:
                return ('fedora', 'Fedora')
            if 'manjaro' in content:
                return ('manjaro', 'Manjaro')
            if 'cachyos' in content or 'cachy' in content:
                return ('cachyos', 'CachyOS')
            if 'arch' in content:
                return ('arch', 'Arch Linux')
            if 'kali' in content:
                return ('kali', 'Kali Linux')
            if 'pop' in content:
                return ('pop', 'Pop!_OS')
            if 'opensuse' in content or 'suse' in content:
                return ('opensuse', 'openSUSE')
            if 'gentoo' in content:
                return ('gentoo', 'Gentoo')
            if 'slackware' in content:
                return ('slackware', 'Slackware')
            if 'centos' in content or 'rocky' in content or 'almalinux' in content:
                return ('redhat', 'Red Hat Linux')
            if 'linux' in content:
                return ('linux', 'Linux')

        # Syslinux config parsing
        for cfg_name in ['syslinux.cfg', 'extlinux.conf', 'isolinux.cfg']:
            cfg_path = os.path.join(mount, 'syslinux', cfg_name)
            if not os.path.isfile(cfg_path):
                cfg_path = os.path.join(mount, 'isolinux', cfg_name)
            if os.path.isfile(cfg_path):
                with open(cfg_path, 'r', errors='ignore') as f:
                    content = f.read().lower()
                if 'ubuntu' in content:
                    return ('ubuntu', 'Ubuntu')
                if 'mint' in content:
                    return ('mint', 'Linux Mint')
                if 'debian' in content:
                    return ('debian', 'Debian')
                if 'fedora' in content:
                    return ('fedora', 'Fedora')
                if 'manjaro' in content:
                    return ('manjaro', 'Manjaro')
                if 'cachyos' in content or 'cachy' in content:
                    return ('cachyos', 'CachyOS')
                if 'arch' in content:
                    return ('arch', 'Arch Linux')
                if 'kali' in content:
                    return ('kali', 'Kali Linux')
                if 'linux' in content:
                    return ('linux', 'Linux')

        # Syslinux / isolinux bootloader presence
        if os.path.isfile(os.path.join(mount, 'isolinux', 'isolinux.bin')):
            return ('linux', 'Linux')
        if os.path.isfile(os.path.join(mount, 'syslinux', 'syslinux.cfg')):
            return ('linux', 'Linux')

        # Generic UEFI boot
        if os.path.isfile(os.path.join(mount, 'EFI', 'BOOT', 'BOOTX64.EFI')):
            return ('linux', 'Linux')

        # Kernel files at root (common for arch, gentoo, etc.)
        if os.path.isfile(os.path.join(mount, 'vmlinuz')) or os.path.isfile(os.path.join(mount, 'vmlinuz.efi')):
            return ('linux', 'Linux')
        if os.path.isfile(os.path.join(mount, 'initrd.img')):
            return ('linux', 'Linux')

    except Exception:
        pass
    return ('', '')


def _detect_boot_on_drive(drive: DriveInfo) -> tuple[str, str]:
    if drive.has_ventoy:
        return ('ventoy', 'Ventoy')
    mounts = []
    if drive.mount_point:
        mounts.append(drive.mount_point)
    if drive.data_mount_point and drive.data_mount_point != drive.mount_point:
        mounts.append(drive.data_mount_point)
    for mp in mounts:
        bt, name = _detect_boot_on_path(mp)
        if bt:
            return (bt, name)
    return ('', '')


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
