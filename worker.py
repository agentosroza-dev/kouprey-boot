import re
import os
import sys
import subprocess
import shutil
import datetime
import tempfile
import json
import struct
import threading

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
DD_EXE = os.path.join(_base, 'assets', 'dd', 'dd.exe')


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

    def __init__(self, iso_path: str, disk_number: int):
        super().__init__()
        self._iso_path = iso_path
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
        self._log_path = _create_log_file('iso_flash')
        iso_name = os.path.basename(self._iso_path)
        iso_size = os.path.getsize(self._iso_path)
        size_gb = iso_size / (1024 ** 3)
        self._log(f'ISO flash: {iso_name} ({size_gb:.1f} GB) -> Disk #{self._disk_number}')
        self._log(f'Log file: {self._log_path}')
        self.progress.emit('0%')

        try:
            ok = self._flash()
            if ok:
                self.progress.emit('100%')
                self._log('ISO written successfully!')
                self.finished.emit(True, f'ISO written.\nLog: {self._log_path}')
            else:
                self.finished.emit(False, f'ISO write failed.\nLog: {self._log_path}')
        except Exception as e:
            self._log(f'Exception: {e}')
            self.finished.emit(False, str(e))

    def _flash(self) -> bool:
        iso_path = self._iso_path
        disk_number = self._disk_number
        device = rf'\\.\PhysicalDrive{disk_number}'

        if not os.path.isfile(DD_EXE):
            self._log(f'dd.exe not found at {DD_EXE}')
            return False

        iso_size = os.path.getsize(iso_path)
        iso_size_mb = iso_size / (1024 * 1024)
        self._log(f'ISO: {os.path.basename(iso_path)} ({iso_size_mb:.0f} MB)')

        self._log(f'Preparing Disk #{disk_number} (unmount + clean)...')
        self._unmount_disk(disk_number)

        import time

        for attempt in range(1, 4):
            if attempt > 1:
                self._log(f'Retry attempt {attempt}/3...')
                self._unmount_disk(disk_number)

            self._log(f'Writing to {device} with dd (bs=1M --progress)...')

            args = [
                DD_EXE,
                f'if={iso_path}',
                f'of={device}',
                'bs=1M',
                '--progress',
            ]

            try:
                popen = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except FileNotFoundError:
                self._log(f'dd.exe not found at {DD_EXE}')
                return False

            stderr_lines = []

            def read_stderr():
                for line in iter(popen.stderr.readline, ''):
                    stderr_lines.append(line.strip())

            t = threading.Thread(target=read_stderr, daemon=True)
            t.start()

            last_pct = -1
            try:
                for line in iter(popen.stdout.readline, ''):
                    line = line.strip()
                    if not line:
                        continue

                    pct = -1
                    if '%' in line:
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].endswith('%'):
                            try:
                                pct = int(parts[1].rstrip('%'))
                            except (ValueError, IndexError):
                                pass
                    elif re.match(r'^[\d,]+$', line):
                        try:
                            bytes_written = int(line.replace(',', ''))
                            if iso_size > 0:
                                pct = int(bytes_written * 100 / iso_size)
                        except (ValueError, IndexError):
                            pass

                    if pct >= 0 and pct != last_pct:
                        last_pct = pct
                        self.progress.emit(f'{pct}%')

                popen.wait(timeout=7200)
                t.join(timeout=5)

                for line in stderr_lines:
                    if line:
                        self._log(line)

                locked = any(
                    keyword in line.lower()
                    for line in stderr_lines
                    for keyword in ('being used by another process', 'access is denied',
                                    'error opening', 'error writing', 'cannot write')
                )

                if locked and attempt < 3:
                    self._log(f'Disk locked, retrying in 2s...')
                    time.sleep(2)
                    continue

                if locked:
                    self._log('dd failed after 3 attempts (disk still locked)')
                    return False

                if popen.returncode == 0:
                    self._log(f'dd completed ({iso_size_mb:.0f} MB written)')
                    self._log('Suppressing format prompt...')
                    hide_drive_ui(disk_number, '')
                    return True
                else:
                    self._log(f'dd exited with code {popen.returncode}')
                    return False

            except subprocess.TimeoutExpired:
                self._log('dd timed out (2 hours)')
                try:
                    popen.kill()
                except Exception:
                    pass
                return False
            except Exception as e:
                self._log(f'dd error: {e}')
                return False

        return False

    def _unmount_disk(self, disk_number: int):
        try:
            hide_drive_ui(disk_number, '')

            clean_script = (
                f'select disk {disk_number}\n'
                f'clean\n'
                f'exit\n'
            )
            result = subprocess.run(
                ['diskpart'],
                input=clean_script,
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if 'DiskPart succeeded in cleaning the disk' in result.stdout:
                self._log('Disk cleaned (partition table wiped), waiting for lock release...')
                import time
                time.sleep(3)
            else:
                self._log(f'diskpart clean: {result.stdout.strip()[:200]}')
        except Exception as e:
            self._log(f'Disk prep warning: {e}')


def get_exe_architecture(exe_path: str) -> str:
    try:
        with open(exe_path, 'rb') as f:
            f.seek(0x3C)
            pe_offset = struct.unpack('<I', f.read(4))[0]
            f.seek(pe_offset + 4)
            machine = struct.unpack('<H', f.read(2))[0]
        return {0x014C: 'x86', 0x8664: 'x64', 0xAA64: 'ARM64'}.get(machine, 'unknown')
    except Exception:
        return 'unknown'


class RufusFlashWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, rufus_exe: str):
        super().__init__()
        self._rufus_exe = rufus_exe
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
        self._log_path = _create_log_file('rufus')
        self._log(f'Rufus starting')
        self._log(f'Log: {self._log_path}')

        try:
            ok = self._flash_rufus()
            if ok:
                self.progress.emit('Rufus completed successfully!')
                self._log('Rufus completed successfully!')
                self.finished.emit(True, f'Rufus completed.\nLog: {self._log_path}')
            else:
                self.finished.emit(False, f'Rufus failed.\nLog: {self._log_path}')
        except Exception as e:
            self._log(f'Exception: {e}')
            self.finished.emit(False, str(e))

    def _flash_rufus(self) -> bool:
        args = [self._rufus_exe, '-gpt']

        cmd_str = ' '.join(args)
        self._log(f'Running: {cmd_str}')
        self.progress.emit('Launching Rufus...')

        import time
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            while proc.poll() is None:
                if self.isInterruptionRequested():
                    proc.terminate()
                    self._log('Rufus was cancelled')
                    return False
                time.sleep(0.5)

            stdout = proc.stdout.read().strip() if proc.stdout else ''
            stderr = proc.stderr.read().strip() if proc.stderr else ''
            if stdout:
                for line in stdout.splitlines():
                    self._log(line)
            if stderr:
                self._log(f'STDERR: {stderr}')

            if proc.returncode == 0:
                self._log('Rufus completed successfully')
                return True
            else:
                self._log(f'Rufus exited with code {proc.returncode}')
                return False
        except FileNotFoundError:
            self._log(f'Rufus executable not found: {self._rufus_exe}')
            return False
        except Exception as e:
            self._log(f'Error running Rufus: {e}')
            return False


def create_flash_worker(disk_number: int) -> VentoyFlashWorker:
    return VentoyFlashWorker(disk_number)


def create_deploy_worker(disk_number: int, data_mount: str, theme_name: str, theme_source: str) -> VentoyDeployWorker:
    return VentoyDeployWorker(disk_number, data_mount, theme_name, theme_source)


def create_iso_flash_worker(iso_path: str, disk_number: int) -> IsoFlashWorker:
    return IsoFlashWorker(iso_path, disk_number)


def create_rufus_worker(rufus_exe: str) -> RufusFlashWorker:
    return RufusFlashWorker(rufus_exe)
