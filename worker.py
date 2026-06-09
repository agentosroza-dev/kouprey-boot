import os
import sys
import subprocess
import shutil
import datetime
import tempfile
import json
import lzma

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


class CustomFlashWorker(QThread):
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
        self._log_path = _create_log_file('custom_flash')
        self._log(f'Custom flash starting on disk #{self._disk_number}')
        self._log(f'Log file: {self._log_path}')
        self.progress.emit('Preparing disk partitions...')

        try:
            ok = self._flash()
            if ok:
                self.progress.emit('Custom flash completed!')
                self._log('Custom flash completed successfully!')
                self.finished.emit(True, f'Custom flash done.\nLog: {self._log_path}')
            else:
                self.finished.emit(False, f'Custom flash failed.\nLog: {self._log_path}')
        except Exception as e:
            self._log(f'Exception: {e}')
            self.finished.emit(False, str(e))

    def _flash(self) -> bool:
        disk = self._disk_number

        img_xz = os.path.join(VENTOY_DIR, 'ventoy', 'ventoy.disk.img.xz')
        if not os.path.isfile(img_xz):
            self._log(f'ventoy.disk.img.xz not found at {img_xz}')
            return False

        self._log('Decompressing ventoy disk image...')
        self.progress.emit('Decompressing Ventoy image...')
        try:
            with lzma.open(img_xz, 'rb') as f:
                ventoy_img = f.read()
        except Exception as e:
            self._log(f'Failed to decompress ventoy image: {e}')
            return False
        self._log(f'Decompressed {len(ventoy_img)} bytes')

        self._log('Cleaning and initializing disk...')
        self.progress.emit('Preparing disk...')
        prep_script = (
            f'select disk {disk}\n'
            'clean\n'
            'convert mbr\n'
            'convert gpt\n'
            'exit\n'
        )
        prep_path = os.path.join(tempfile.gettempdir(), f'prep_{disk}.txt')
        try:
            with open(prep_path, 'w') as f:
                f.write(prep_script)
            prep = subprocess.run(
                ['diskpart', '/s', prep_path],
                capture_output=True, text=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if prep.returncode != 0:
                self._log(f'Disk prep failed')
                try: os.remove(prep_path)
                except Exception: pass
                return False
        except Exception as e:
            self._log(f'Disk prep error: {e}')
            try: os.remove(prep_path)
            except Exception: pass
            return False
        try: os.remove(prep_path)
        except Exception: pass

        self._log('Creating partitions via PowerShell...')
        self.progress.emit('Creating partitions...')
        part_script = (
            f'$part1 = New-Partition -DiskNumber {disk} -UseMaximumSize; '
            f'$size = $part1.Size; '
            f'Resize-Partition -DiskNumber {disk} -PartitionNumber 1 -Size ($size - 33MB); '
            f'New-Partition -DiskNumber {disk} -Size 32MB | Out-Null; '
            f'$null = $part1 | Format-Volume -FileSystem exFAT -NewFileSystemLabel "Ventoy" '
            f'-Confirm:$false -Force; '
            f'Start-Sleep -Seconds 2; '
            f'$letter = (Get-Volume | Where-Object '
            f'{{ $_.FileSystemLabel -eq "Ventoy" -and $_.DriveLetter }}).DriveLetter; '
            f'if ($letter) {{ $letter }} '
            f'else {{ '
            f'Add-PartitionAccessPath -DiskNumber {disk} -PartitionNumber 1 -AccessPath "K:\\"; '
            f'"K" }}'
        )
        data_letter = ''
        try:
            ps = subprocess.run(
                ['powershell', '-NoProfile', '-Command', part_script],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            out = ps.stdout.strip()
            err = ps.stderr.strip()
            if err:
                for line in err.splitlines():
                    self._log(f'  ps err: {line}')
            if ps.returncode != 0:
                self._log(f'Partitioning failed with code {ps.returncode}')
                return False
            data_letter = out.strip()
            self._log(f'Data partition drive letter: {data_letter}')
        except Exception as e:
            self._log(f'Error during partitioning: {e}')
            return False

        self._log('Setting no_automount on VTOYEFI...')
        attr_script = (
            f'select disk {disk}\n'
            'select partition 2\n'
            'gpt attributes=0x8000000000000000\n'
            'exit\n'
        )
        attr_path = os.path.join(tempfile.gettempdir(), f'attr_{disk}.txt')
        try:
            with open(attr_path, 'w') as f:
                f.write(attr_script)
            subprocess.run(
                ['diskpart', '/s', attr_path],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            self._log(f'Failed to set attributes: {e}')
        try: os.remove(attr_path)
        except Exception: pass

        self._log('Getting partition offset...')
        self.progress.emit('Writing Ventoy boot image...')
        part_offset = self._get_vtoyefi_offset(disk)
        if part_offset is None:
            self._log('Could not determine VTOYEFI partition offset')
            return False

        self._log(f'Writing ventoy image at disk offset {part_offset}...')
        img_size = len(ventoy_img)
        img_temp = os.path.join(tempfile.gettempdir(), f'ventoy_img_{disk}.img')
        try:
            with open(img_temp, 'wb') as f:
                f.write(ventoy_img)
        except Exception as e:
            self._log(f'Failed to write ventoy image to temp: {e}')
            return False

        phys_path = f'\\\\.\\PhysicalDrive{disk}'
        write_script = (
            f'$path = "{phys_path}"; '
            f'$offset = {part_offset}; '
            f'$bytes = [System.IO.File]::ReadAllBytes("{img_temp}"); '
            f'$stream = [System.IO.File]::Open($path, '
            f'[System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, '
            f'[System.IO.FileShare]::ReadWrite); '
            f'$stream.Seek($offset, [System.IO.SeekOrigin]::Begin); '
            f'$stream.Write($bytes, 0, $bytes.Length); '
            f'$stream.Close()'
        )
        try:
            ps_result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', write_script],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if ps_result.returncode != 0:
                self._log(f'Raw write failed: {ps_result.stderr.strip()}')
                try: os.remove(img_temp)
                except Exception: pass
                return False
            self._log(f'Wrote {img_size} bytes to VTOYEFI partition at offset {part_offset}')
        except Exception as e:
            self._log(f'Error writing ventoy image: {e}')
            try: os.remove(img_temp)
            except Exception: pass
            return False
        try: os.remove(img_temp)
        except Exception: pass

        self._log('Setting up ventoy.json on data partition...')
        self.progress.emit('Finalizing...')
        if data_letter:
            ventoy_dir = os.path.join(f'{data_letter}:\\', 'ventoy')
            os.makedirs(ventoy_dir, exist_ok=True)
            default_json = {
                "theme": {
                    "file": "/ventoy/theme/theme.txt",
                    "display_mode": "GUI",
                    "ventoy_left": "5%",
                    "ventoy_top": "95%",
                    "ventoy_color": "#ffffff"
                }
            }
            with open(os.path.join(ventoy_dir, 'ventoy.json'), 'w', encoding='utf-8') as f:
                json.dump(default_json, f, indent=4)
            self._log('ventoy.json created on data partition')
        else:
            self._log('No data partition letter found, ventoy.json not created')

        self.progress.emit('Custom flash complete!')
        return True

    def _get_vtoyefi_offset(self, disk: int) -> int | None:
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 f'$parts = Get-Partition -DiskNumber {disk} | Sort-Object PartitionNumber; '
                 f'if ($parts.Count -ge 2) {{ $parts[1].Offset }} else {{ $parts[0].Offset }}'],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            val = result.stdout.strip()
            if val:
                return int(val)
        except Exception:
            pass
        return None

    def _get_data_partition_letter(self, disk: int) -> str:
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 f'$parts = Get-Partition -DiskNumber {disk} | Sort-Object PartitionNumber; '
                 f'if ($parts.Count -ge 1) {{ '
                 f'$vol = Get-Volume -Partition $parts[0] -ErrorAction SilentlyContinue; '
                 f'if ($vol.DriveLetter) {{ $vol.DriveLetter }} }}'],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            val = result.stdout.strip()
            if val:
                return val
        except Exception:
            pass
        return ''


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

        for item in os.listdir(theme_dir):
            item_path = os.path.join(theme_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)

        if not self._theme_source or not os.path.isdir(self._theme_source):
            self._log(f'Theme source not found: {self._theme_source}')
            return False

        self._log(f'Copying theme from {self._theme_source} to {theme_dir}')
        for item in os.listdir(self._theme_source):
            s = os.path.join(self._theme_source, item)
            d = os.path.join(theme_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
        self._log('Theme files copied to ventoy/theme/')

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


def create_flash_worker(disk_number: int, mode: str = 'ventoy') -> QThread:
    if mode == 'custom':
        return CustomFlashWorker(disk_number)
    return VentoyFlashWorker(disk_number)


def create_deploy_worker(disk_number: int, data_mount: str, theme_name: str, theme_source: str) -> VentoyDeployWorker:
    return VentoyDeployWorker(disk_number, data_mount, theme_name, theme_source)
