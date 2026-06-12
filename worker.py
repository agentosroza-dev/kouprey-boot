import os
import sys
import subprocess
import shutil
import datetime
import tempfile
import json

from PyQt6.QtCore import QThread, pyqtSignal


def _create_log_file(prefix: str) -> str:
    log_dir = os.path.join(tempfile.gettempdir(), 'kouprey-boot')
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(log_dir, f'{prefix}_{ts}.log')


_base = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
VENTOY_DIR = os.path.join(_base, 'assets', 'ventoy-1.1.12')
VENTOY_EXE = os.path.join(VENTOY_DIR, 'altexe', 'Ventoy2Disk_X64.exe')
if not os.path.isfile(VENTOY_EXE):
    VENTOY_EXE = os.path.join(VENTOY_DIR, 'Ventoy2Disk.exe')


def show_drive_ui(disk_number: int):
    """Assign a drive letter to the data partition and open Explorer."""
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-Command', f'''
$disk = {disk_number}
$parts = Get-Partition -DiskNumber $disk -ErrorAction SilentlyContinue
$dataPart = $parts | Where-Object {{
    $vol = Get-Volume -Partition $_ -ErrorAction SilentlyContinue
    $vol -and $vol.FileSystemLabel -ne "VTOYEFI"
}} | Select-Object -First 1
$letter = $null
if ($dataPart -and -not $dataPart.DriveLetter) {{
    $used = (Get-Volume).DriveLetter | Where-Object {{ $_ }} | ForEach-Object {{ "$_`:" }}
    for ($l = [char]'Z'; $l -ge [char]'C'; $l--) {{
        $dl = [char]$l
        if ($used -notcontains "$dl`:") {{
            Add-PartitionAccessPath -DiskNumber $disk `
                -PartitionNumber $dataPart.PartitionNumber `
                -AccessPath "$dl`:\" -ErrorAction SilentlyContinue
            $letter = $dl
            break
        }}
    }}
}} elseif ($dataPart) {{
    $letter = $dataPart.DriveLetter
}}
if ($letter) {{
    try {{
        $shell = New-Object -ComObject Shell.Application
        $shell.Open("$letter`:\\")
    }} catch {{}}
}}
'''],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def hide_drive_ui(disk_number: int, drive_letter: str):
    """Hide drive from Explorer and suppress 'Format disk' prompt."""
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-Command', f'''
$disk = {disk_number}
$dl = '{drive_letter}'
$shell = New-Object -ComObject Shell.Application
$shell.Windows() | ForEach-Object {{
    try {{
        $p = $_.Document.Folder.Self.Path
        if (-not $dl) {{
            $parts = Get-Partition -DiskNumber $disk -ErrorAction SilentlyContinue
            foreach ($part in $parts) {{
                if ($part.DriveLetter -and $p -eq "$($part.DriveLetter):\\") {{
                    $_.Quit()
                }}
            }}
        }} elseif ($p -eq "$dl`:\\" -or $p -like "*$dl*") {{
            $_.Quit()
        }}
    }} catch {{}}
}}
if ($dl) {{
    try {{
        $part = Get-Partition -DriveLetter $dl -ErrorAction Stop
        Remove-PartitionAccessPath -DiskNumber $part.DiskNumber `
            -PartitionNumber $part.PartitionNumber `
            -AccessPath "$dl`:\\" -ErrorAction SilentlyContinue
    }} catch {{}}
}} else {{
    Get-Partition -DiskNumber $disk -ErrorAction SilentlyContinue |
        Where-Object {{ $_.DriveLetter }} |
        ForEach-Object {{
            Remove-PartitionAccessPath -DiskNumber $disk `
                -PartitionNumber $_.PartitionNumber `
                -AccessPath "$($_.DriveLetter):\\" -ErrorAction SilentlyContinue
        }}
}}
'''],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


class VentoyFlashWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, disk_number: int):
        super().__init__()
        self._disk_number = disk_number
        self._log_path = ''

    def _log(self, msg: str):
        self.log.emit(msg)
        if self._log_path:
            ts = datetime.datetime.now().strftime('%H:%M:%S')
            try:
                with open(self._log_path, 'a', encoding='utf-8') as f:
                    f.write(f'[{ts}] {msg}\n')
            except Exception:
                pass

    def run(self):
        self._log_path = _create_log_file('flash')
        self._log(f'Ventoy flash starting on disk #{self._disk_number}')
        self._log(f'Log file: {self._log_path}')
        self.progress.emit('Installing Ventoy...')

        try:
            ok = self._flash()
            if ok:
                self.progress.emit('Ventoy installed successfully!')
                self._log('Ventoy installed successfully!')
                self.finished.emit(True, f'Ventoy installed.\nLog: {self._log_path}')
            else:
                self.finished.emit(False, f'Flash failed.\nLog: {self._log_path}')
        except Exception as e:
            self._log(f'Exception: {e}')
            self.finished.emit(False, str(e))

    def _flash(self) -> bool:
        disk = self._disk_number
        exe = VENTOY_EXE

        if not os.path.isfile(exe):
            self._log(f'Ventoy2Disk not found at {exe}')
            return False

        self._log(f'Running: {exe} -I -s -g {disk}')
        self.progress.emit(f'Running Ventoy2Disk on disk #{disk}...')

        try:
            result = subprocess.run(
                [exe, '-I', '-s', '-g', str(disk)],
                capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            if stdout:
                for line in stdout.splitlines():
                    self._log(line)
            if stderr:
                self._log(f'STDERR: {stderr}')

            if result.returncode == 0:
                self._log('Ventoy2Disk completed successfully')
                return True
            else:
                self._log(f'Ventoy2Disk exited with code {result.returncode}')
                return False
        except subprocess.TimeoutExpired:
            self._log('Ventoy2Disk timed out (5 min)')
            return False
        except Exception as e:
            self._log(f'Error running Ventoy2Disk: {e}')
            return False


class VentoyDeployWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, disk_number: int, data_mount: str, theme_name: str, theme_source: str):
        super().__init__()
        self._disk = disk_number
        self._data_mount = data_mount
        self._theme_name = theme_name
        self._theme_source = theme_source
        self._log_path = ''

    def _log(self, msg: str):
        self.log.emit(msg)
        if self._log_path:
            ts = datetime.datetime.now().strftime('%H:%M:%S')
            try:
                with open(self._log_path, 'a', encoding='utf-8') as f:
                    f.write(f'[{ts}] {msg}\n')
            except Exception:
                pass

    def run(self):
        self._log_path = _create_log_file('deploy')
        self._log(f'Theme deploy starting. Log: {self._log_path}')

        try:
            ok = self._deploy()
            if ok:
                self.progress.emit(f'Theme "{self._theme_name}" deployed!')
                self.finished.emit(True, f'Theme "{self._theme_name}" deployed.\nLog: {self._log_path}')
            else:
                self.finished.emit(False, f'Deploy failed.\nLog: {self._log_path}')
        except Exception as e:
            self._log(f'Exception: {e}')
            self.finished.emit(False, f'{e}\nLog: {self._log_path}')

    def _deploy(self) -> bool:
        data_mount = self._data_mount
        if not data_mount or not os.path.isdir(data_mount):
            self._log(f'Data mount point not found: {data_mount}')
            return False

        ventoy_dir = os.path.join(data_mount, 'ventoy')
        theme_dir = os.path.join(ventoy_dir, 'theme')
        os.makedirs(theme_dir, exist_ok=True)

        self.progress.emit('Cleaning old theme...')
        for item in os.listdir(theme_dir):
            item_path = os.path.join(theme_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
        self._log('Old theme cleaned')

        if not self._theme_source or not os.path.isdir(self._theme_source):
            self._log(f'Theme source not found: {self._theme_source}')
            return False

        self.progress.emit('Copying theme files...')
        self._log(f'Copying theme from {self._theme_source} to {theme_dir}')
        for item in os.listdir(self._theme_source):
            s = os.path.join(self._theme_source, item)
            d = os.path.join(theme_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
        self._log('Theme files copied to ventoy/theme/')

        self.progress.emit('Deploying ventoy.json...')
        plugin_src = os.path.join(VENTOY_DIR, 'plugin', 'ventoy', 'ventoy.json')
        plugin_dst = os.path.join(ventoy_dir, 'ventoy.json')
        if os.path.isfile(plugin_src):
            shutil.copy2(plugin_src, plugin_dst)
            self._log(f'ventoy.json deployed from plugin')
        else:
            default_json = {
                "theme": {
                    "file": "/ventoy/theme/theme.txt",
                    "display_mode": "GUI",
                    "ventoy_left": "5%",
                    "ventoy_top": "95%",
                    "ventoy_color": "#ffffff"
                }
            }
            with open(plugin_dst, 'w', encoding='utf-8') as f:
                json.dump(default_json, f, indent=4)
            self._log('Default ventoy.json created')

        self.progress.emit('Theme deployment complete!')
        return True


def rename_volume(drive_letter: str, new_label: str) -> bool:
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f'Set-Volume -DriveLetter "{drive_letter}" -NewFileSystemLabel "{new_label}"'],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False


class IsoFlashWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, disk_number: int, iso_path: str, device_path: str = ''):
        super().__init__()
        self._disk = disk_number
        self._iso = iso_path
        self._device_path = device_path
        import platform
        self._system = platform.system()
        self._log_path = ''

    def _log(self, msg: str):
        self.log.emit(msg)
        if self._log_path:
            ts = datetime.datetime.now().strftime('%H:%M:%S')
            try:
                with open(self._log_path, 'a', encoding='utf-8') as f:
                    f.write(f'[{ts}] {msg}\n')
            except Exception:
                pass

    def run(self):
        self._log_path = _create_log_file('iso_flash')
        self._log(f'ISO flash starting on disk #{self._disk}')
        self._log(f'ISO: {self._iso}')
        self._log(f'Log: {self._log_path}')

        try:
            ok = self._flash_iso()
            if ok:
                self.progress.emit('ISO written successfully!')
                self._log('ISO written successfully!')
                self.finished.emit(True, f'ISO written.\nLog: {self._log_path}')
            else:
                self.finished.emit(False, f'ISO flash failed.\nLog: {self._log_path}')
        except Exception as e:
            self._log(f'Exception: {e}')
            self.finished.emit(False, str(e))

    def _is_windows_iso(self) -> bool:
        try:
            import zipfile
            if zipfile.is_zipfile(self._iso):
                with zipfile.ZipFile(self._iso, 'r') as zf:
                    names_lower = [n.lower().replace('\\', '/') for n in zf.namelist()]
                    for marker in ('sources/install.wim', 'sources/install.esd',
                                   'boot/bootmgr', 'bootmgr', 'setup.exe'):
                        if any(n == marker or n.endswith('/' + marker) for n in names_lower):
                            return True
                    return False
        except Exception:
            pass
        try:
            with open(self._iso, 'rb') as f:
                f.seek(0x8001)
                magic = f.read(5)
                if magic == b'CD001':
                    f.seek(0)
                    header = f.read(8388608)
                    markers = (b'INSTALL.WIM', b'INSTALL.ESD', b'install.wim',
                               b'install.esd', b'BOOTMGR', b'bootmgr',
                               b'SETUP.EXE', b'setup.exe',
                               b'BOOT.WIM', b'boot.wim',
                               b'WINSETUP', b'WinSetup')
                    for marker in markers:
                        if marker in header:
                            return True
                    return False
        except Exception:
            pass
        return False

    def _is_winpe_iso(self) -> bool:
        """Detect WinPE (has boot.wim, no install.wim/esd)."""
        try:
            with open(self._iso, 'rb') as f:
                f.seek(0x8001)
                if f.read(5) == b'CD001':
                    f.seek(0)
                    header = f.read(8388608)
                    has_boot_wim = b'boot.wim' in header or b'BOOT.WIM' in header
                    has_install = (b'install.wim' in header or b'INSTALL.WIM' in header or
                                   b'install.esd' in header or b'INSTALL.ESD' in header)
                    return has_boot_wim and not has_install
        except Exception:
            pass
        return False

    def _clean_disk(self) -> bool:
        self._log('Cleaning disk...')
        self.progress.emit('Preparing disk...')
        if self._system == 'Windows':
            return self._clean_disk_windows()
        else:
            return self._clean_disk_linux()

    def _clean_disk_windows(self) -> bool:
        import time
        self._log(f'Cleaning disk #{self._disk} (Windows)...')

        # Step 1: Close all Explorer windows and release handles
        self._close_explorer_for_disk()

        # Step 2: Remove all partition drive letters via PowerShell
        self._log('Removing volume mount points...')
        try:
            # Take disk offline first to release locks
            subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 f'Set-Disk -Number {self._disk} -IsOffline $false -ErrorAction SilentlyContinue'],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass
        try:
            unmount_ps = (
                f'Get-Partition -DiskNumber {self._disk} -ErrorAction SilentlyContinue '
                f'| Where-Object {{ $_.DriveLetter }} '
                f'| ForEach-Object {{ '
                f'  Remove-PartitionAccessPath -DiskNumber {self._disk} '
                f'    -PartitionNumber $_.PartitionNumber '
                f"    -AccessPath \"$($_.DriveLetter):\\\" -ErrorAction SilentlyContinue; "
                f'  $_.DriveLetter }}'
            )
            subprocess.run(
                ['powershell', '-NoProfile', '-Command', unmount_ps],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass
        time.sleep(2)

        # Step 3: Try Clear-Disk first (works better on removable media)
        self._log('Attempting Clear-Disk via PowerShell...')
        try:
            clear_ps = (
                f'Clear-Disk -Number {self._disk} -RemoveData -RemoveOEM '
                f'-PassThru -ErrorAction Stop'
            )
            cr = subprocess.run(
                ['powershell', '-NoProfile', '-Command', clear_ps],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if cr.returncode == 0:
                self._log('Clear-Disk succeeded')
                time.sleep(2)
                return True
            else:
                err = cr.stderr.strip() or cr.stdout.strip()[:200]
                self._log(f'Clear-Disk failed: {err}')
        except subprocess.TimeoutExpired:
            self._log('Clear-Disk timed out (120s)')
        except Exception as e:
            self._log(f'Clear-Disk error: {e}')

        # Step 4: Fallback to diskpart clean (up to 3 attempts)
        for attempt in range(3):
            self._log(f'diskpart clean attempt {attempt + 1}/3')
            script = (
                f'select disk {self._disk}\n'
                f'attributes disk clear readonly\n'
                f'clean\n'
                f'exit\n'
            )
            try:
                result = subprocess.run(
                    ['diskpart'],
                    input=script,
                    capture_output=True, text=True, timeout=120,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except subprocess.TimeoutExpired:
                self._log('diskpart clean timed out')
                continue
            except Exception as e:
                self._log(f'diskpart error: {e}')
                continue

            out = result.stdout.strip()
            if out:
                for line in out.splitlines():
                    self._log(f'  diskpart: {line.strip()}')
            if 'Access is denied' in out or 'not supported on removable media' in out:
                self._log('diskpart clean not available, zeroing MBR directly...')
                # Fallback: zero out the first few MB of the disk to remove partition table
                if self._zero_mbr():
                    self._log('MBR zeroed successfully')
                    time.sleep(2)
                    return True
                self._log('ERROR: Cannot clean disk - please close all programs accessing this drive')
                self.progress.emit('ERROR: Close programs accessing this drive')
                return False
            if 'DiskPart has encountered an error' in out or result.returncode != 0:
                self._log(f'clean attempt {attempt + 1} failed, retrying...')
                time.sleep(3)
                continue
            self._log('diskpart clean completed')
            time.sleep(2)
            return True
        self._log('diskpart clean failed after 3 attempts')

        # Step 5: Last resort - zero MBR directly
        self._log('Attempting MBR zero as last resort...')
        if self._zero_mbr():
            self._log('MBR zeroed successfully')
            time.sleep(2)
            return True
        return False

    def _zero_mbr(self) -> bool:
        """Zero out the first few MB to remove partition table on removable media."""
        import time
        device = rf'\\.\PhysicalDrive{self._disk}'
        try:
            ps_code = (
                f"$dev = @\"\n{device}\n\"@; "
                f"$stream = [System.IO.File]::Open($dev, "
                f"[System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, "
                f"[System.IO.FileShare]::ReadWrite); "
                f"try {{ "
                f"  $buf = New-Object byte[] 10485760; "
                f"  $stream.Write($buf, 0, $buf.Length); "
                f"}} finally {{ $stream.Close() }} "
                f"Write-Output 'DONE'"
            )
            r = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_code],
                capture_output=True, text=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return r.returncode == 0
        except Exception as e:
            self._log(f'MBR zero failed: {e}')
            return False

    def _close_explorer_for_disk(self):
        import time
        self._log('Closing Explorer windows for disk...')
        try:
            subprocess.run(
                ['powershell', '-NoProfile', '-Command', f'''
$dl = (Get-Partition -DiskNumber {self._disk} -ErrorAction SilentlyContinue
       | Where-Object {{ $_.DriveLetter }} | Select-Object -First 1).DriveLetter
if (-not $dl) {{ exit }}
$shell = New-Object -ComObject Shell.Application
$shell.Windows() | ForEach-Object {{
    try {{
        $p = $_.Document.Folder.Self.Path
        if ($p -eq "$dl`:\\" -or $p -like "*$dl*") {{ $_.Quit() }}
    }} catch {{}}
}}
'''],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass

    def _clean_disk_linux(self) -> bool:
        import time
        device = self._get_linux_device()
        if not device:
            self._log('Could not determine Linux device path')
            return False
        self._log(f'Cleaning device: {device}')
        try:
            wipefs_result = subprocess.run(
                ['wipefs', '-a', device],
                capture_output=True, text=True, timeout=30,
            )
            if wipefs_result.stdout:
                self._log(wipefs_result.stdout.strip())
            if wipefs_result.stderr:
                self._log(wipefs_result.stderr.strip())
        except Exception as e:
            self._log(f'wipefs failed (may not be installed): {e}')

        try:
            with open(device, 'wb') as f:
                f.write(b'\x00' * 1048576)
            self._log('Zeroed first 1MB of device')
        except Exception as e:
            self._log(f'Error zeroing device: {e}')
            return False

        time.sleep(1)
        self._log('Device cleaned successfully')
        return True

    def _get_linux_device(self) -> str:
        if self._device_path:
            return self._device_path
        try:
            result = subprocess.run(
                ['lsblk', '-J', '-o', 'NAME,TYPE,TRAN'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return ''
            import json
            data = json.loads(result.stdout)
            usb = [d for d in data.get('blockdevices', [])
                   if d.get('TYPE') == 'disk' and d.get('TRAN') == 'usb']
            if self._disk < len(usb):
                return f'/dev/{usb[self._disk]["NAME"]}'
        except Exception as e:
            self._log(f'lsblk lookup failed: {e}')
        return f'/dev/sd{chr(97 + self._disk)}'

    def _prepare_and_format_fat32(self) -> str:
        import time
        import re

        if self._system != 'Windows':
            self._log('FAT32 preparation is Windows-only')
            return ''

        self._log('Cleaning and formatting disk as FAT32 for UEFI boot...')
        self.progress.emit('Formatting disk (FAT32)...')

        if not self._clean_disk_windows():
            self._log('Failed to clean disk before FAT32 format')
            return ''

        try:
            script = (
                f'select disk {self._disk}\n'
                f'create partition primary\n'
                f'select partition 1\n'
                f'active\n'
                f'format fs=fat32 label="WINUSB" quick\n'
                f'assign\n'
                f'exit\n'
            )
            result = subprocess.run(
                ['diskpart'],
                input=script,
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            out = result.stdout.strip()
            if out:
                for line in out.splitlines():
                    self._log(f'  diskpart: {line.strip()}')
            if 'Access is denied' in out:
                self._log('ERROR: Access denied - please run as administrator')
                self.progress.emit('ERROR: Run as administrator')
                return ''
            if 'DiskPart has encountered an error' in out or result.returncode != 0:
                self._log('diskpart format failed')
                return ''

            time.sleep(3)

            ps_cmd = (
                f'$parts = Get-Partition -DiskNumber {self._disk} '
                f'-ErrorAction SilentlyContinue; '
                f'foreach ($p in $parts) {{ '
                f'if ($p.DriveLetter -and $p.DriveLetter -ne [char]0) {{ '
                f'Write-Output $p.DriveLetter; break }} '
                f'}}'
            )
            pr = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_cmd],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            letter = pr.stdout.strip()[:1]
            if letter and letter.isalpha():
                return letter.upper()

            match = re.search(r'assigned.*?(\w):', out, re.IGNORECASE)
            if not match:
                match = re.search(r'Drive letter (\w)', out, re.IGNORECASE)
            if match:
                return match.group(1).upper()

            self._log('Could not determine drive letter')
            return ''
        except subprocess.TimeoutExpired:
            self._log('diskpart format timed out')
        except Exception as e:
            self._log(f'Error formatting disk: {e}')
        return ''

    def _refresh_disk(self):
        try:
            ps_cmd = f'Get-Disk -Number {self._disk} | Update-Disk -ErrorAction SilentlyContinue'
            subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_cmd],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass

    def _hide_drive_ui(self, drive_letter: str, reopen_explorer: bool = False):
        if reopen_explorer:
            try:
                subprocess.Popen(
                    ['explorer', f'{drive_letter}:\\'],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass
            return
        hide_drive_ui(self._disk, drive_letter)

    def _flash_windows_iso(self) -> bool:
        import time

        drive_letter = self._prepare_and_format_fat32()
        if not drive_letter:
            self._log('Failed to format disk as FAT32')
            return False

        self._log(f'USB formatted as FAT32 on drive {drive_letter}:')
        time.sleep(2)

        self.progress.emit('Mounting ISO...')
        self._log(f'Mounting ISO: {self._iso}')
        iso_path_escaped = self._iso.replace("'", "''")
        mount_cmd = (
            f"$iso = Mount-DiskImage -ImagePath '{iso_path_escaped}' -PassThru; "
            f"if ($iso) {{ Write-Output ('MOUNT:' + $iso.ImagePath) }} "
            f"else {{ Write-Output 'MOUNT:FAIL' }}"
        )
        mount_result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', mount_cmd],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        mount_out = mount_result.stdout.strip()
        if 'MOUNT:FAIL' in mount_out or mount_result.returncode != 0:
            self._log(f'Failed to mount ISO: {mount_result.stderr.strip()}')
            return False
        self._log('ISO mounted successfully')
        time.sleep(2)

        try:
            ps_cmd = (
                "$vol = Get-Volume | Where-Object { $_.DriveType -eq 'CD-ROM' -and $_.DriveLetter } "
                "| Sort-Object -Property DriveLetter -Descending | Select-Object -First 1; "
                "if ($vol) { Write-Output $vol.DriveLetter } else { Write-Output 'NONE' }"
            )
            vol_result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_cmd],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            iso_letter = vol_result.stdout.strip()[:1]
            if not iso_letter or not iso_letter.isalpha() or iso_letter.upper() == 'N':
                self._log('Could not find mounted ISO drive letter')
                return False
            self._log(f'ISO mounted on drive {iso_letter}:')

            self.progress.emit('Copying Windows files to USB...')
            self._log(f'Copying from {iso_letter}:\\ to {drive_letter}:\\ (excluding install.wim)')

            copy_cmd = (
                f'robocopy "{iso_letter}:\\" "{drive_letter}:\\" /E /R:1 /W:1 '
                f'/XF install.wim install.esd /NFL /NDL /NJH /NJS /nc /ns /np'
            )
            copy_result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', copy_cmd],
                capture_output=True, text=True, timeout=3600,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if copy_result.returncode >= 8:
                self._log(f'File copy failed (robocopy exit code {copy_result.returncode})')
                return False
            self._log('Base files copied successfully')

            self.progress.emit('Processing install.wim...')
            wim_path = f'{iso_letter}:\\sources\\install.wim'
            esd_path = f'{iso_letter}:\\sources\\install.esd'

            check_wim_cmd = f'if (Test-Path "{wim_path}") {{ Write-Output "EXISTS" }} else {{ Write-Output "NO" }}'
            wim_check = subprocess.run(
                ['powershell', '-NoProfile', '-Command', check_wim_cmd],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            has_wim = 'EXISTS' in wim_check.stdout

            check_esd_cmd = f'if (Test-Path "{esd_path}") {{ Write-Output "EXISTS" }} else {{ Write-Output "NO" }}'
            esd_check = subprocess.run(
                ['powershell', '-NoProfile', '-Command', check_esd_cmd],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            has_esd = 'EXISTS' in esd_check.stdout

            if has_wim:
                self._log('Found install.wim, checking size...')
                size_cmd = f'(Get-Item "{wim_path}").Length'
                size_result = subprocess.run(
                    ['powershell', '-NoProfile', '-Command', size_cmd],
                    capture_output=True, text=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                wim_size = int(size_result.stdout.strip()) if size_result.stdout.strip().isdigit() else 0
                self._log(f'install.wim size: {wim_size} bytes ({wim_size / (1024*1024*1024):.2f} GB)')

                if wim_size > 4 * 1024 * 1024 * 1024:
                    self._log('install.wim > 4GB, splitting for FAT32...')
                    self.progress.emit('Splitting install.wim for FAT32...')
                    split_cmd = (
                        f'Dism /Split-Image /ImageFile:"{wim_path}" '
                        f'/SWMFile:"{drive_letter}:\\sources\\install.swm" /FileSize:3800'
                    )
                    split_result = subprocess.run(
                        ['powershell', '-NoProfile', '-Command', split_cmd],
                        capture_output=True, text=True, timeout=1800,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    if split_result.returncode != 0:
                        dism_err = split_result.stderr.strip()
                        dism_out = split_result.stdout.strip()
                        self._log(f'DISM split failed (code {split_result.returncode})')
                        if dism_out:
                            for line in dism_out.splitlines():
                                self._log(f'  DISM: {line.strip()}')
                        if dism_err:
                            for line in dism_err.splitlines():
                                self._log(f'  DISM err: {line.strip()}')
                        return False
                    self._log('install.wim split into .swm files successfully')
                else:
                    self._log('install.wim <= 4GB, copying directly...')
                    self.progress.emit('Copying install.wim...')
                    copy_wim_cmd = f'Copy-Item "{wim_path}" "{drive_letter}:\\sources\\install.wim"'
                    copy_wim_result = subprocess.run(
                        ['powershell', '-NoProfile', '-Command', copy_wim_cmd],
                        capture_output=True, text=True, timeout=1800,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    if copy_wim_result.returncode != 0:
                        self._log(f'Failed to copy install.wim: {copy_wim_result.stderr.strip()}')
                        return False
                    self._log('install.wim copied successfully')

            elif has_esd:
                self._log('Found install.esd, copying directly...')
                self.progress.emit('Copying install.esd...')
                copy_esd_cmd = f'Copy-Item "{esd_path}" "{drive_letter}:\\sources\\install.esd"'
                copy_esd_result = subprocess.run(
                    ['powershell', '-NoProfile', '-Command', copy_esd_cmd],
                    capture_output=True, text=True, timeout=1800,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if copy_esd_result.returncode != 0:
                    self._log(f'Failed to copy install.esd: {copy_esd_result.stderr.strip()}')
                    return False
                self._log('install.esd copied successfully')
            elif self._is_winpe_iso():
                self._log('WinPE ISO: only boot.wim present, skipped install.wim/esd')
            else:
                self._log('No install.wim or install.esd found (may be WinPE)')

            self._log('All files copied successfully to USB')
            self.progress.emit('Files copied!')
            self._hide_drive_ui(drive_letter)
            return True
        finally:
            self.progress.emit('Cleaning up...')
            dismount_cmd = (
                f"Dismount-DiskImage -ImagePath '{iso_path_escaped}' -ErrorAction SilentlyContinue"
            )
            try:
                subprocess.run(
                    ['powershell', '-NoProfile', '-Command', dismount_cmd],
                    capture_output=True, text=True, timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass
            self._refresh_disk()

    def _flash_linux_iso(self) -> bool:
        if not self._clean_disk():
            self._log('Failed to clean disk')
            return False

        self._log(f'Writing ISO (raw): {self._iso}')
        self.progress.emit('Writing ISO to disk...')

        try:
            import platform as _platform
            sys_name = _platform.system()
            iso_size = os.path.getsize(self._iso)

            if sys_name == 'Windows':
                device = rf'\\.\PhysicalDrive{self._disk}'
                self._log('Writing via raw sector copy...')
                ps_code = (
                    f"$path = @\"\n{self._iso}\n\"@; "
                    f"$dev = @\"\n{device}\n\"@; "
                    f"$size = (Get-Item $path).Length; "
                    f"$stream = [System.IO.File]::Open($dev, "
                    f"[System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, "
                    f"[System.IO.FileShare]::ReadWrite); "
                    f"try {{ "
                    f"  $iso = [System.IO.File]::OpenRead($path); "
                    f"  try {{ "
                    f"    $buf = New-Object byte[] 1048576; "
                    f"    $total = 0; "
                    f"    while (($read = $iso.Read($buf, 0, $buf.Length)) -gt 0) {{ "
                    f"      $stream.Write($buf, 0, $read); "
                    f"      $total += $read; "
                    f"      Write-Output (\"PROGRESS:\" + [int]($total * 100 / $size)); "
                    f"    }} "
                    f"  }} finally {{ $iso.Close() }} "
                    f"}} finally {{ $stream.Close() }} "
                    f"Write-Output \"DONE\""
                )
                result = subprocess.run(
                    ['powershell', '-NoProfile', '-Command', ps_code],
                    capture_output=True, text=True, timeout=3600,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.startswith('PROGRESS:'):
                        pct = int(line.split(':')[1])
                        self.progress.emit(f'Writing ISO... {pct}%')
                        self._log(f'Written: {pct}%')
                    elif line == 'DONE':
                        self._log('ISO write completed')
                stderr = result.stderr.strip()
                if stderr:
                    self._log(f'PowerShell stderr: {stderr}')
                if result.returncode != 0:
                    self._log(f'PowerShell failed (code {result.returncode})')
                    return False
                self._refresh_disk()
                self.progress.emit('ISO written successfully!')
                self._hide_drive_ui('')
                try:
                    subprocess.run(
                        ['powershell', '-NoProfile', '-Command',
                         f'Get-Partition -DiskNumber {self._disk} -ErrorAction SilentlyContinue '
                         f'| Where-Object {{ $_.DriveLetter }} '
                         f'| ForEach-Object {{ '
                         f'  Remove-PartitionAccessPath -DiskNumber {self._disk} '
                         f'    -PartitionNumber $_.PartitionNumber '
                         f"    -AccessPath \"$($_.DriveLetter):\\\" -ErrorAction SilentlyContinue; "
                         f'}} ; '
                         f'Set-Disk -Number {self._disk} -IsOffline $true -ErrorAction SilentlyContinue'],
                        capture_output=True, text=True, timeout=30,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                except Exception:
                    pass
                return True

            else:
                device = self._get_linux_device()
                if not device:
                    self._log('Could not determine Linux device path')
                    return False
                self._log(f'Writing to device: {device}')
                self._log(f'ISO size: {iso_size} bytes')
                self._log('Writing via direct block copy...')
                chunk_size = 1024 * 1024
                written = 0
                last_pct = -1
                with open(self._iso, 'rb') as src, open(device, 'wb') as dst:
                    while True:
                        chunk = src.read(chunk_size)
                        if not chunk:
                            break
                        dst.write(chunk)
                        written += len(chunk)
                        pct = int(written * 100 / iso_size)
                        if pct != last_pct:
                            self.progress.emit(f'Writing ISO... {pct}%')
                            self._log(f'Written: {pct}%')
                            last_pct = pct
                import time
                time.sleep(2)
                self._log('ISO write completed')
                self.progress.emit('ISO written successfully!')
                return True

        except subprocess.TimeoutExpired:
            self._log('ISO write timed out')
        except Exception as e:
            self._log(f'Error writing ISO: {e}')
            import traceback
            self._log(traceback.format_exc())

        return False

    def _flash_iso(self) -> bool:
        is_win = self._is_windows_iso()
        is_pe = self._is_winpe_iso() if is_win else False

        if self._system == 'Windows' and (is_win or is_pe):
            if is_pe:
                self._log('Detected WinPE ISO - using mount and copy method (Windows)')
            else:
                self._log('Detected Windows Setup ISO - using mount and copy method (Windows)')
            return self._flash_windows_iso()
        else:
            if is_win or is_pe:
                self._log(f'Detected Windows/PE ISO - using raw write method ({self._system})')
            else:
                self._log(f'Detected Linux/hybrid ISO - using raw write method ({self._system})')
            return self._flash_linux_iso()


def is_windows_iso(iso_path: str) -> bool:
    try:
        import zipfile
        if zipfile.is_zipfile(iso_path):
            with zipfile.ZipFile(iso_path, 'r') as zf:
                names_lower = [n.lower().replace('\\', '/') for n in zf.namelist()]
                for marker in ('sources/install.wim', 'sources/install.esd',
                               'boot/bootmgr', 'bootmgr', 'setup.exe'):
                    if any(n == marker or n.endswith('/' + marker) for n in names_lower):
                        return True
                return False
    except Exception:
        pass
    try:
        with open(iso_path, 'rb') as f:
            f.seek(0x8001)
            magic = f.read(5)
            if magic == b'CD001':
                f.seek(0)
                header = f.read(8388608)
                markers = (b'INSTALL.WIM', b'INSTALL.ESD', b'install.wim',
                           b'install.esd', b'BOOTMGR', b'bootmgr',
                           b'SETUP.EXE', b'setup.exe',
                           b'BOOT.WIM', b'boot.wim',
                           b'WINSETUP', b'WinSetup',
                           b'\\SOURCES\\', b'\\sources\\',
                           b'/SOURCES/', b'/sources/')
                for marker in markers:
                    if marker in header:
                        return True
                return False
    except Exception:
        pass
    return False


def create_flash_worker(disk_number: int) -> VentoyFlashWorker:
    return VentoyFlashWorker(disk_number)


def create_deploy_worker(disk_number: int, data_mount: str, theme_name: str, theme_source: str) -> VentoyDeployWorker:
    return VentoyDeployWorker(disk_number, data_mount, theme_name, theme_source)


def create_iso_worker(disk_number: int, iso_path: str, device_path: str = '') -> IsoFlashWorker:
    return IsoFlashWorker(disk_number, iso_path, device_path)
